"""Build the committed fixtures, by construction, so the demo runs offline.

A fixture is the SQL each run "generated". For a STABLE question, all K runs
get the defended answer_sql. For a FLAPPING question, we interleave the correct
answer_sql and the question's buggy_sql across runs, which makes the harness
see two different results for the same question, exactly the production failure
Bedrock exists to catch. This is truth by construction: we know which questions
flap because we built them that way, and the harness must independently
rediscover them from the runs alone.

Two fixtures are written:
  * fixture.jsonl          - the BASELINE: 3 known flappers.
  * fixture_candidate.jsonl - a regressed candidate where one extra question
    (top_category) also flaps, so `bedrock gate` goes red on a real regression.

Run:  python data/generate_fixture.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, gold as gold_mod  # noqa: E402

K = config.K_RUNS
BASELINE_FLAPPERS = {"total_revenue", "revenue_completed", "revenue_computers"}
CANDIDATE_FLAPPERS = BASELINE_FLAPPERS | {"top_category"}


def build(items, flappers, path):
    lines = []
    for item in items:
        for run in range(K):
            if item.id in flappers and item.buggy_sql:
                # interleave: even runs correct, odd runs buggy -> it flaps
                sql = item.answer_sql if run % 2 == 0 else item.buggy_sql
            else:
                sql = item.answer_sql
            lines.append(json.dumps({"id": item.id, "run": run, "sql": sql}))
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(lines)} runs over {len(items)} questions -> {path}")


def main():
    items = gold_mod.load()
    candidate_path = str(Path(config.FIXTURE_PATH).with_name("fixture_candidate.jsonl"))
    build(items, BASELINE_FLAPPERS, config.FIXTURE_PATH)
    build(items, CANDIDATE_FLAPPERS, candidate_path)


if __name__ == "__main__":
    main()
