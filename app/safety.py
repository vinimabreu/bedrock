"""The safety gate. Nothing reaches the database until it passes through here.

Letting a language model write SQL that runs against a real database is the
scary part of text-to-SQL. This module is the answer, and it is defence in
depth, not a single check:

  1. The database connection itself is opened read-only (see app/db.py). That
     is the real guarantee: even a query that slipped past this validator
     physically cannot write, because SQLite rejects writes on the connection.
  2. This validator runs first anyway. It blocks anything that is not a single
     read-only SELECT and gives the agent a clear reason, which is what lets it
     rewrite a bad query instead of just failing.
  3. A row LIMIT is injected when the query has none, so a careless question
     cannot pull an entire table into the model's context.

The validator is deliberately strict: when in doubt, reject. A rejected query
costs one extra model call; a permitted destructive query could cost the data.
"""

import re
from dataclasses import dataclass

# Statements that write or change structure. Matched as whole words so a column
# named "updated_at" or "deleted_flag" does not trip the "UPDATE"/"DELETE" rule.
FORBIDDEN = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "REPLACE",
    "TRUNCATE", "ATTACH", "DETACH", "PRAGMA", "VACUUM", "REINDEX",
    "GRANT", "REVOKE", "COMMIT", "ROLLBACK", "SAVEPOINT", "BEGIN",
]


@dataclass
class Verdict:
    ok: bool
    reason: str = ""


def validate(sql: str) -> Verdict:
    """Decide whether `sql` is a safe, single, read-only statement."""
    cleaned = _strip_comments(sql).strip()
    if not cleaned:
        return Verdict(False, "the query is empty")

    # One statement only. A trailing semicolon is fine; an internal one means
    # someone is trying to smuggle a second statement (e.g. "...; DROP TABLE").
    body = cleaned.rstrip(";").strip()
    if ";" in body:
        return Verdict(False, "only a single statement is allowed")

    # Must start as a read query. WITH covers common table expressions that
    # still end in a SELECT.
    first = re.match(r"[A-Za-z]+", body)
    if not first or first.group(0).upper() not in ("SELECT", "WITH"):
        return Verdict(False, "only SELECT queries are allowed (read-only)")

    upper = body.upper()
    for keyword in FORBIDDEN:
        if re.search(rf"\b{keyword}\b", upper):
            return Verdict(False, f"the keyword {keyword} is not allowed (read-only access)")

    return Verdict(True)


def ensure_limit(sql: str, max_rows: int) -> str:
    """Append a row cap when the query has no LIMIT of its own.

    The check is whole-word and case-insensitive. A query that already sets a
    LIMIT (even inside a subquery) is left untouched; the goal is only to stop
    an unbounded top-level result, not to second-guess a deliberate limit.
    """
    body = sql.rstrip().rstrip(";").rstrip()
    if re.search(r"\bLIMIT\b", body, re.IGNORECASE):
        return body
    return f"{body}\nLIMIT {max_rows}"


def _strip_comments(sql: str) -> str:
    """Remove -- line comments and /* block comments */ before inspection.

    A comment is a classic place to hide a second statement from a naive
    scanner, so we drop them before any of the checks above run.
    """
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql
