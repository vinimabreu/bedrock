"""The gold set and its defended answer keys.

A gold item is a question plus an answer_sql we stand behind. The answer key is
executed ONCE against the read-only database to produce the truth result set
that every run is scored against. This is truth by construction: the executed
answer key IS the ground truth, so a question is "correct" exactly when a run
returns the same result set the answer key does.

An optional buggy_sql is used ONLY by the fixture generator to manufacture a
deliberately flaky question for the offline demo. The harness never sees it.
"""

import json
from dataclasses import dataclass

from . import config, db


@dataclass
class GoldItem:
    id: str
    question: str
    answer_sql: str
    buggy_sql: str | None = None


def load(path: str | None = None) -> list[GoldItem]:
    path = path or config.GOLD_PATH
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    items = [
        GoldItem(
            id=item["id"],
            question=item["question"],
            answer_sql=item["answer_sql"],
            buggy_sql=item.get("buggy_sql"),
        )
        for item in data
    ]
    # Fail loud on a malformed gold set rather than mis-scoring later: an empty
    # set has nothing to measure, and a duplicate id would clobber per_question
    # while still counting toward n_questions (which would fool the gate).
    if not items:
        raise ValueError(f"gold set at {path} is empty")
    ids = [item.id for item in items]
    dups = sorted({i for i in ids if ids.count(i) > 1})
    if dups:
        raise ValueError(f"duplicate gold id(s) in {path}: {', '.join(dups)}")
    return items


def answer_key(conn, item: GoldItem):
    """Execute the answer_sql and return (columns, rows).

    Fail loud: if the answer key itself is broken, raise instead of letting a
    bad key silently define a wrong truth. A gold set that does not run is a
    bug in the gold set, and the demo must never paper over it.
    """
    try:
        result = db.run_query(conn, item.answer_sql, config.QUERY_TIMEOUT_S)
    except db.QueryError as exc:
        raise db.QueryError(
            f"answer key for '{item.id}' failed to run: {exc}"
        ) from exc
    # The agent path injects a LIMIT (config.MAX_ROWS) when a query has none, so
    # a result above the cap would be truncated for the candidate but full for
    # the key, and a correct query would be scored wrong. Equivalence is only
    # defined below the cap: reject an oversized key loudly instead of comparing
    # a full set against a truncated one.
    if len(result.rows) >= config.MAX_ROWS:
        raise db.QueryError(
            f"answer key for '{item.id}' returns >= {config.MAX_ROWS} rows; "
            "equivalence is only defined below the row cap. Add an explicit "
            "ORDER BY ... LIMIT to the answer_sql, or raise BEDROCK_MAX_ROWS."
        )
    return result.columns, result.rows
