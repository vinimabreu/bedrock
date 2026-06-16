"""The harness must rediscover, from runs alone, which questions are flaky.

These use the real read-only store.db (deterministic execution) and a
hand-built fixture of SQL per run, so we KNOW the intended verdict and assert
the harness independently arrives at it. Truth by construction.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config, db, harness  # noqa: E402
from app.fixture import FixtureLLM  # noqa: E402
from app.gold import GoldItem  # noqa: E402

GOOD = "SELECT ROUND(SUM(quantity * unit_price), 2) AS revenue FROM order_items"
BUGGY = "SELECT ROUND(SUM(unit_price), 2) AS revenue FROM order_items"
BROKEN = "SELECT revenue FROM nonexistent_table"


def _run(item, sql_by_run, k):
    conn = db.connect(config.DB_PATH)
    by_id_run = {(item.id, run): sql for run, sql in sql_by_run.items()}
    factory = FixtureLLM(by_id_run).for_run
    report = harness.run_stability(conn, [item], factory, k=k)
    return report.questions[0]


def test_stable_correct_when_every_run_matches_the_key():
    item = GoldItem("rev", "total revenue?", GOOD)
    q = _run(item, {0: GOOD, 1: GOOD, 2: GOOD, 3: GOOD}, k=4)
    assert q.verdict == harness.STABLE_CORRECT
    assert q.accuracy == 1.0
    assert q.flip_rate == 0.0
    assert q.n_distinct == 1


def test_flaky_when_runs_disagree_with_each_other():
    item = GoldItem("rev", "total revenue?", GOOD)
    # correct on 0,2,4; buggy on 1,3  -> flaps
    q = _run(item, {0: GOOD, 1: BUGGY, 2: GOOD, 3: BUGGY, 4: GOOD}, k=5)
    assert q.verdict == harness.FLAKY
    assert q.accuracy == 0.6
    assert q.flip_rate == 0.4
    assert q.n_distinct == 2
    assert q.is_flapper


def test_stable_wrong_when_consistently_off_the_key():
    item = GoldItem("rev", "total revenue?", GOOD)
    q = _run(item, {0: BUGGY, 1: BUGGY, 2: BUGGY}, k=3)
    assert q.verdict == harness.STABLE_WRONG
    assert q.accuracy == 0.0
    assert q.flip_rate == 0.0  # it agrees with itself, just wrongly


def test_error_when_every_run_fails_to_produce_a_valid_query():
    item = GoldItem("rev", "total revenue?", GOOD)
    q = _run(item, {0: BROKEN, 1: BROKEN, 2: BROKEN}, k=3)
    assert q.verdict == harness.ERROR
    assert q.accuracy == 0.0


def test_report_metrics_aggregate_correctly():
    conn = db.connect(config.DB_PATH)
    items = [
        GoldItem("a", "total revenue?", GOOD),
        GoldItem("b", "total revenue?", GOOD),
    ]
    by_id_run = {}
    for run, sql in enumerate([GOOD, GOOD, GOOD, GOOD]):
        by_id_run[("a", run)] = sql
    for run, sql in enumerate([GOOD, BUGGY, GOOD, BUGGY]):
        by_id_run[("b", run)] = sql
    report = harness.run_stability(conn, items, FixtureLLM(by_id_run).for_run, k=4)
    m = report.metrics()
    assert m["n_questions"] == 2
    assert m["stable_correct"] == 1
    assert m["flaky"] == 1
    assert m["trust_rate"] == 0.5


if __name__ == "__main__":
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
