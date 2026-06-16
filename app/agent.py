"""The agent loop: ask -> write SQL -> check -> run -> self-correct -> answer.

This is what makes the project an *agent* rather than a single prompt. One shot
at SQL generation is a demo; the value is in the loop. When a query is rejected
by the safety gate or errors against the database, the failure is fed back to
the model and it tries again, up to a bounded number of times. Every attempt is
recorded, so the self-correction is observable instead of hidden.

The loop depends only on the LLM interface and the safety/db helpers, so it is
fully testable with a scripted model and no network.
"""

from dataclasses import dataclass, field

from . import config, db, safety
from .llm import LLM


@dataclass
class Attempt:
    """One trip through the loop, kept for the trace."""
    n: int
    sql: str
    ok: bool
    error: str | None = None
    rows: int | None = None


@dataclass
class Result:
    question: str
    succeeded: bool
    attempts: list[Attempt] = field(default_factory=list)
    sql: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    answer: str = ""

    @property
    def retries(self) -> int:
        """How many corrections it took (0 means first try worked)."""
        return max(0, len(self.attempts) - 1)


class SqlAgent:
    def __init__(
        self,
        conn,
        schema: str,
        llm: LLM,
        max_retries: int = config.MAX_RETRIES,
        max_rows: int = config.MAX_ROWS,
        timeout_s: float = config.QUERY_TIMEOUT_S,
    ):
        self._conn = conn
        self._schema = schema
        self._llm = llm
        self._max_retries = max_retries
        self._max_rows = max_rows
        self._timeout_s = timeout_s

    def ask(self, question: str) -> Result:
        result = Result(question=question, succeeded=False)
        prior_error: str | None = None

        # First attempt plus up to max_retries corrections.
        for n in range(1, self._max_retries + 2):
            raw = self._llm.write_sql(question, self._schema, prior_error)

            verdict = safety.validate(raw)
            if not verdict.ok:
                # Blocked before touching the database. Tell the model why.
                result.attempts.append(Attempt(n=n, sql=raw, ok=False, error=verdict.reason))
                prior_error = f"the query was rejected by the safety check: {verdict.reason}"
                continue

            sql = safety.ensure_limit(raw, self._max_rows)
            try:
                query = db.run_query(self._conn, sql, self._timeout_s)
            except db.QueryError as exc:
                result.attempts.append(Attempt(n=n, sql=sql, ok=False, error=str(exc)))
                prior_error = str(exc)
                continue

            # Success. Record it, write the plain-English answer, and stop.
            result.attempts.append(Attempt(n=n, sql=sql, ok=True, rows=query.row_count))
            result.succeeded = True
            result.sql = sql
            result.columns = query.columns
            result.rows = query.rows
            result.answer = self._llm.explain(question, sql, query.columns, query.rows)
            return result

        # Every attempt failed. Surface the last error rather than pretending.
        last = result.attempts[-1].error if result.attempts else "no attempts"
        result.answer = (
            f"I could not produce a valid query after {len(result.attempts)} "
            f"attempts. Last error: {last}"
        )
        return result
