"""Database access, opened read-only and bounded by a timeout.

This is the layer that actually touches SQLite. Two deliberate choices:

  * The connection is opened with mode=ro (read-only) via a file: URI. This is
    the hard guarantee behind the whole project: the agent can generate any SQL
    it likes, but the connection will refuse to write. The validator in
    safety.py is the friendly first line; this is the wall behind it.

  * A wall-clock timeout aborts a query that runs too long. A read-only query
    cannot corrupt anything, but a bad cartesian join can still hang the
    process, so we interrupt it through SQLite's progress handler.
"""

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


class QueryError(Exception):
    """Raised when a query fails to execute or exceeds its time budget."""


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]

    @property
    def row_count(self) -> int:
        return len(self.rows)


def connect(db_path: str) -> sqlite3.Connection:
    """Open `db_path` strictly read-only."""
    path = Path(db_path)
    if not path.exists():
        raise QueryError(
            f"database not found at {db_path}. Restore data/store.db from the repository."
        )
    # mode=ro makes the connection reject every write at the SQLite level.
    uri = f"file:{path.as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def run_query(conn: sqlite3.Connection, sql: str, timeout_s: float) -> QueryResult:
    """Execute a read-only SQL string and return its columns and rows.

    Raises QueryError on any SQLite error or on timeout, with the message the
    agent needs to rewrite the query.
    """
    deadline = time.monotonic() + timeout_s

    def _watchdog() -> int:
        # Returning non-zero from the progress handler aborts the query. SQLite
        # calls this every N virtual-machine instructions (set below).
        return 1 if time.monotonic() > deadline else 0

    conn.set_progress_handler(_watchdog, 1000)
    try:
        cur = conn.execute(sql)
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        return QueryResult(columns=columns, rows=rows)
    except sqlite3.OperationalError as exc:
        if "interrupted" in str(exc).lower():
            raise QueryError(f"query exceeded the {timeout_s:.0f}s time limit") from exc
        raise QueryError(str(exc)) from exc
    except sqlite3.Error as exc:
        raise QueryError(str(exc)) from exc
    finally:
        conn.set_progress_handler(None, 0)
