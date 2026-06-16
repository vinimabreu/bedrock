"""Turn a live database into a compact text description for the model.

A text-to-SQL agent is only as good as the schema you hand it. We do NOT
hardcode the schema: we read it from the database itself, so the same agent
works against any SQLite file you point it at. The description includes the
exact CREATE statements (so column names, types and foreign keys are precise)
plus a few sample rows per table (so the model sees real value shapes, like the
date format or the set of status strings).
"""

import sqlite3
from textwrap import indent

SAMPLE_ROWS = 3


def describe(conn: sqlite3.Connection) -> str:
    """Build the schema prompt block for every user table in the database."""
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        ).fetchall()
    ]
    if not tables:
        return "(the database has no tables)"

    blocks = []
    for table in tables:
        ddl = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()[0]
        block = f"{ddl.strip()};"

        samples = _sample_rows(conn, table)
        if samples:
            block += "\n-- sample rows:\n" + indent(samples, "-- ")
        blocks.append(block)

    return "\n\n".join(blocks)


def _sample_rows(conn: sqlite3.Connection, table: str) -> str:
    """A few rows rendered as `col=value` lines, so the model sees real data."""
    cur = conn.execute(f'SELECT * FROM "{table}" LIMIT {SAMPLE_ROWS}')
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    lines = []
    for row in rows:
        pairs = ", ".join(f"{c}={_short(v)}" for c, v in zip(cols, row))
        lines.append(pairs)
    return "\n".join(lines)


def _short(value: object, limit: int = 40) -> str:
    """Render a cell value compactly for the schema preview."""
    text = "NULL" if value is None else str(value)
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text
