"""The only module that talks to Claude.

Isolating the model behind a small interface (LLM) has two payoffs:

  * The agent loop in agent.py depends on the interface, not on Anthropic. The
    tests inject a ScriptedLLM that returns canned SQL, so the whole
    self-correction loop is tested deterministically with no API key and no
    network.
  * Swapping the model, or the provider, touches this file only.

Two jobs live here: turn a question (plus schema, plus the previous error) into
SQL, and turn a result set back into a plain-English answer.
"""

import re
from typing import Protocol

from . import config

# The instruction that keeps the model on rails. It is told, in order: the
# dialect, that it may only read, to lean on the schema it was given, and to
# return SQL and nothing else so we never have to guess where the query starts.
SQL_SYSTEM = (
    "You translate questions into a single SQLite SELECT query. "
    "Rules: read-only, one statement, no semicolons except a trailing one, "
    "never write or alter data. Use only the tables and columns in the schema "
    "you are given. Prefer explicit JOINs and clear column aliases. "
    "Return ONLY the SQL, with no prose and no markdown fences."
)

ANSWER_SYSTEM = (
    "You explain a SQL query result to a non-technical reader in two or three "
    "sentences. State the concrete numbers. Do not invent values that are not "
    "in the rows. If the result is empty, say that plainly."
)


class LLM(Protocol):
    """The minimal surface the agent needs from a model."""

    def write_sql(self, question: str, schema: str, prior_error: str | None) -> str: ...

    def explain(self, question: str, sql: str, columns: list[str], rows: list[tuple]) -> str: ...


class ClaudeLLM:
    """Real implementation backed by the Anthropic API."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        # Imported lazily so the package (and its tests) load without anthropic
        # installed or an API key present.
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key) if api_key else Anthropic()
        self._model = model or config.ANTHROPIC_MODEL

    def write_sql(self, question: str, schema: str, prior_error: str | None) -> str:
        prompt = f"Schema:\n{schema}\n\nQuestion: {question}"
        if prior_error:
            # Feeding the failure back is the heart of self-correction: the
            # model sees its own broken query's error and fixes it.
            prompt += (
                f"\n\nYour previous attempt failed with this error:\n{prior_error}\n"
                "Write a corrected query."
            )
        text = self._complete(SQL_SYSTEM, prompt, max_tokens=600)
        return extract_sql(text)

    def explain(self, question: str, sql: str, columns: list[str], rows: list[tuple]) -> str:
        preview = _render_rows(columns, rows)
        prompt = (
            f"Question: {question}\n\nSQL that ran:\n{sql}\n\n"
            f"Result ({len(rows)} rows):\n{preview}"
        )
        return self._complete(ANSWER_SYSTEM, prompt, max_tokens=400).strip()

    def _complete(self, system: str, prompt: str, max_tokens: int) -> str:
        message = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text


def extract_sql(text: str) -> str:
    """Pull the SQL out of a model response, fences or not.

    The system prompt asks for bare SQL, but models sometimes wrap it in a
    ```sql block anyway. We strip that defensively so a stray fence never turns
    into a syntax error.
    """
    fenced = re.search(r"```(?:sql)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    return text.strip()


def _render_rows(columns: list[str], rows: list[tuple], limit: int = 30) -> str:
    """A compact text table for the explain prompt, capped so it stays small."""
    if not columns:
        return "(no columns)"
    head = " | ".join(columns)
    lines = [head, "-" * len(head)]
    for row in rows[:limit]:
        lines.append(" | ".join("NULL" if v is None else str(v) for v in row))
    if len(rows) > limit:
        lines.append(f"... ({len(rows) - limit} more rows)")
    return "\n".join(lines)


class ScriptedLLM:
    """Test double: hands back pre-set SQL strings, then a fixed explanation.

    Each call to write_sql returns the next item in `sqls`. That lets a test
    script a wrong-then-right sequence and assert the agent recovers.
    """

    def __init__(self, sqls: list[str], answer: str = "(scripted answer)"):
        self._sqls = list(sqls)
        self._answer = answer
        self.calls: list[str | None] = []   # prior_error seen on each call

    def write_sql(self, question: str, schema: str, prior_error: str | None) -> str:
        self.calls.append(prior_error)
        if not self._sqls:
            raise AssertionError("ScriptedLLM ran out of scripted SQL")
        return self._sqls.pop(0)

    def explain(self, question: str, sql: str, columns: list[str], rows: list[tuple]) -> str:
        return self._answer
