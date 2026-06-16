"""Regression tests for the hardening pass (adversarial review 2026-06-16).

Each test pins a fix for a confirmed finding so it cannot silently come back.
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config, db, equivalence, fixture, gate, gold, harness  # noqa: E402
from app.gold import GoldItem  # noqa: E402

NAN = float("nan")


# --- equivalence: bool / NaN / documented column-name scope ---

def test_bool_never_collides_with_numeric_0_or_1():
    assert not equivalence.equal(["v"], [(True,)], ["v"], [(1,)])
    assert not equivalence.equal(["v"], [(False,)], ["v"], [(0,)])


def test_identical_nan_results_compare_equal_not_flaky():
    assert equivalence.equal(["v"], [(NAN,)], ["v"], [(NAN,)])


def test_column_names_are_intentionally_not_part_of_equality():
    # documented v1 scope: same values under different labels are equal
    assert equivalence.equal(["customers"], [(200,)], ["distinct_buyers"], [(200,)])


# --- gold: oversized answer key, duplicate id, empty set all fail loud ---

def test_answer_key_above_row_cap_raises():
    conn = db.connect(config.DB_PATH)
    item = GoldItem("big", "every order item id?", "SELECT id FROM order_items")
    original = config.MAX_ROWS
    config.MAX_ROWS = 5
    try:
        raised = False
        try:
            gold.answer_key(conn, item)
        except db.QueryError as exc:
            raised = True
            assert "row cap" in str(exc)
        assert raised, "oversized answer key should raise, not silently truncate"
    finally:
        config.MAX_ROWS = original


def _write_gold(rows):
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(rows, handle)
    handle.close()
    return handle.name


def test_duplicate_gold_id_raises():
    path = _write_gold([
        {"id": "dup", "question": "a?", "answer_sql": "SELECT 1"},
        {"id": "dup", "question": "b?", "answer_sql": "SELECT 2"},
    ])
    try:
        raised = False
        try:
            gold.load(path)
        except ValueError as exc:
            raised = True
            assert "duplicate" in str(exc).lower()
        assert raised
    finally:
        os.remove(path)


def test_empty_gold_set_raises():
    path = _write_gold([])
    try:
        raised = False
        try:
            gold.load(path)
        except ValueError as exc:
            raised = True
            assert "empty" in str(exc).lower()
        assert raised
    finally:
        os.remove(path)


# --- harness: k < 1 fails loud instead of an IndexError ---

def test_k_below_one_raises():
    conn = db.connect(config.DB_PATH)
    raised = False
    try:
        harness.run_stability(conn, [], lambda qid, run: None, k=0)
    except ValueError as exc:
        raised = True
        assert "k must be >= 1" in str(exc)
    assert raised


# --- fixture: missing coverage is reported, not a mid-run KeyError ---

def test_fixture_reports_missing_coverage():
    fx = fixture.FixtureLLM({("a", 0): "SELECT 1"})
    gaps = fx.missing(["a"], 3)
    assert ("a", 1) in gaps and ("a", 2) in gaps
    assert ("a", 0) not in gaps


# --- gate: a malformed run fails loud, never silently passes ---

def test_gate_raises_on_missing_metric_keys():
    baseline = {"metrics": {"n_questions": 14}, "per_question": {}}  # missing trust_rate etc.
    candidate = {"metrics": {"n_questions": 14}, "per_question": {}}
    raised = False
    try:
        gate.run_gate(baseline, candidate)
    except ValueError as exc:
        raised = True
        assert "missing keys" in str(exc)
    assert raised


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
