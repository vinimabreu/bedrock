"""Offline replay (and live recording) of the SQL an agent generates.

The killer demo runs with NO API key. Instead of calling a model K times per
question, we replay SQL recorded earlier into a JSONL fixture, one line per
run: {"id": ..., "run": ..., "sql": ...}. FixtureLLM hands that SQL back to the
REAL agent loop, which runs it against the REAL read-only database, so every
metric is provable offline and reproducible to the row.

The same format records LIVE runs (see RecordingLLM): wrap a real model, run
the harness once with a key, and the generated SQL is appended to a fixture you
can commit. So a maintainer regenerates the fixture from a live model for the
hero screenshot, then everyone reproduces the exact run with no key.

A fixture is keyed by (question_id, run) rather than a flat queue, because a
question is asked K times and each run may differ. That divergence across runs
is the entire thing Bedrock measures.
"""

import json
import os


class FixtureLLM:
    """Replays recorded SQL. Use `for_run(id, run)` to get an llm.LLM-shaped
    object bound to one (question, run)."""

    def __init__(self, by_id_run: dict, answer: str = "(replayed from fixture)"):
        self._sql = dict(by_id_run)  # {(id, run): sql}
        self._answer = answer

    @classmethod
    def from_jsonl(cls, path: str) -> "FixtureLLM":
        by_id_run = {}
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                record = json.loads(line)
                by_id_run[(record["id"], int(record["run"]))] = record["sql"]
        if not by_id_run:
            raise ValueError(f"fixture at {path} contained no runs")
        return cls(by_id_run)

    def for_run(self, question_id: str, run: int):
        return _BoundReplay(self._sql, question_id, run, self._answer)

    def missing(self, item_ids, k: int) -> list:
        """The (id, run) keys absent for these questions over k runs, so a
        caller can fail loud BEFORE scoring instead of hitting a mid-run
        KeyError on a stale or partially-written fixture."""
        gaps = []
        for question_id in item_ids:
            for run in range(k):
                if (question_id, run) not in self._sql:
                    gaps.append((question_id, run))
        return gaps


class _BoundReplay:
    """An llm.LLM for exactly one (question, run): always returns the recorded
    SQL. Returning the same SQL on a retry is intentional: if the recorded
    query is invalid it will fail the same way each attempt and the run is
    scored as an error, which is the honest outcome."""

    def __init__(self, sql_map, question_id, run, answer):
        self._sql_map = sql_map
        self._question_id = question_id
        self._run = run
        self._answer = answer

    def write_sql(self, question, schema, prior_error):
        key = (self._question_id, self._run)
        if key not in self._sql_map:
            raise KeyError(
                f"no fixture SQL for id={self._question_id!r} run={self._run}"
            )
        return self._sql_map[key]

    def explain(self, question, sql, columns, rows):
        return self._answer


class RecordingLLM:
    """Wraps a real llm.LLM, appending every generated SQL to a JSONL fixture.

    Bind one per (id, run) with `for_run`, run the harness live once, and the
    fixture is written as a side effect. Used to regenerate fixtures from a
    live model, never on the offline path.
    """

    def __init__(self, inner, path: str):
        self._inner = inner
        self._path = path

    def for_run(self, question_id: str, run: int):
        return _BoundRecorder(self._inner, self._path, question_id, run)


class _BoundRecorder:
    def __init__(self, inner, path, question_id, run):
        self._inner = inner
        self._path = path
        self._question_id = question_id
        self._run = run

    def write_sql(self, question, schema, prior_error):
        sql = self._inner.write_sql(question, schema, prior_error)
        with open(self._path, "a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {"id": self._question_id, "run": self._run, "sql": sql}
                )
                + "\n"
            )
        return sql

    def explain(self, question, sql, columns, rows):
        return self._inner.explain(question, sql, columns, rows)


def reset(path: str) -> None:
    """Remove an existing fixture so a recording run starts clean."""
    if os.path.exists(path):
        os.remove(path)
