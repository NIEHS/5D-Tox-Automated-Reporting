"""
session_query.py — read-only SQL over a session's DuckDB (ADR-0016 Phase B).

The query layer the power-user tools sit on. Opens
``sessions/<dtxsid>/session.duckdb`` (built by pipeline.session_db) with
``read_only=True`` and runs a SINGLE ``SELECT`` / ``WITH`` statement, returning
``{columns, rows, row_count, truncated}``.

Safety — a browser can send arbitrary SQL here, so the boundary is defence in
depth:

  1. The DB is opened ``read_only=True`` — writes/DDL fail at the engine.
  2. The statement is parsed at the API: only a single ``SELECT`` / ``WITH``
     leading token is allowed; ``;``-chained multi-statements are rejected.
  3. Results are ``LIMIT``-capped (``max_rows``) with a ``truncated`` flag; a
     statement ``timeout`` bounds runaway scans.
  4. The DB is per-session and holds only that session's study data — no
     cross-session or secret exposure. (The knowledge-base DB stays separate.)

Mirrors ToxKBQuerier's context-manager lifecycle so the duckdb connection is
always released.
"""

from __future__ import annotations

import re
from pathlib import Path

import duckdb

from pipeline.session_store import session_dir

# Result cap: rows beyond this are dropped and ``truncated`` is set. Keeps a
# careless "SELECT * FROM measurement" from shipping the whole table to a browser.
DEFAULT_MAX_ROWS = 10_000

# Statement timeout (seconds) — bounds a runaway scan. DuckDB has no per-query
# timeout knob in older builds; we approximate with the interrupt-based
# ``SET statement_timeout`` where available and fall back to no-op otherwise.
DEFAULT_TIMEOUT_S = 30

# Only these leading keywords are allowed (read-only query forms).
_ALLOWED_LEADING = ("select", "with")


class QueryError(ValueError):
    """A user SQL / request error (bad statement, no DB) — a 4xx, not a 500."""


def session_db_path(dtxsid: str) -> Path:
    """Path to a session's DuckDB (may not exist)."""
    return session_dir(dtxsid) / "session.duckdb"


def _strip_sql_comments(sql: str) -> str:
    """Remove -- line comments and /* */ block comments so the leading-token and
    single-statement checks see only real SQL (a comment must not smuggle a
    second statement or hide the leading verb)."""
    # block comments (non-greedy, across newlines)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    # line comments
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql


def validate_sql(sql: str) -> str:
    """Validate a user SQL string for the read-only boundary; return the cleaned,
    single statement (trailing ``;`` stripped). Raises QueryError on any breach.

    Rules: non-empty; leading token in {select, with}; at most one statement
    (a single optional trailing ``;`` is allowed, but no ``;`` that is followed
    by more SQL).
    """
    if not sql or not sql.strip():
        raise QueryError("empty query")

    stripped = _strip_sql_comments(sql).strip()
    if not stripped:
        raise QueryError("empty query")

    # single statement: allow exactly one trailing ';', reject any ';' with SQL
    # after it (a multi-statement body).
    body = stripped.rstrip().rstrip(";").rstrip()
    if ";" in body:
        raise QueryError("multiple statements are not allowed")

    leading = body.split(None, 1)[0].lower() if body else ""
    if leading not in _ALLOWED_LEADING:
        raise QueryError(
            f"only SELECT / WITH queries are allowed (got {leading!r})"
        )
    return body


class SessionQuerier:
    """Read-only SQL access to one session's DuckDB."""

    def __init__(self, dtxsid: str):
        self.dtxsid = dtxsid
        db = session_db_path(dtxsid)
        if not db.exists():
            raise QueryError(
                f"no query database for session {dtxsid!r} — process the session "
                f"first (session.duckdb is built during processing)"
            )
        self.con = duckdb.connect(str(db), read_only=True)

    def close(self):
        self.con.close()

    def __enter__(self) -> "SessionQuerier":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.close()
        return False

    def _apply_timeout(self, seconds: int) -> None:
        # Best-effort: not all DuckDB builds expose a statement timeout. Wrap so a
        # missing setting never breaks the query path.
        try:
            self.con.execute(f"SET statement_timeout = '{int(seconds)}s'")
        except duckdb.Error:
            pass

    def run_sql(
        self,
        sql: str,
        *,
        max_rows: int = DEFAULT_MAX_ROWS,
        timeout_s: int = DEFAULT_TIMEOUT_S,
    ) -> dict:
        """Run one read-only SELECT/WITH; return {columns, rows, row_count,
        truncated}. ``rows`` is a list of lists (JSON-friendly). Raises QueryError
        on a rejected/failed statement.
        """
        body = validate_sql(sql)
        self._apply_timeout(timeout_s)

        # Fetch one more than the cap so we can report truncation without a second
        # COUNT query.
        wrapped = f"SELECT * FROM ({body}) AS _q LIMIT {int(max_rows) + 1}"
        try:
            cur = self.con.execute(wrapped)
        except duckdb.Error as e:
            raise QueryError(str(e)) from e

        columns = [d[0] for d in (cur.description or [])]
        fetched = cur.fetchall()
        truncated = len(fetched) > max_rows
        rows = [list(r) for r in fetched[:max_rows]]
        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
        }

    def schema(self) -> dict:
        """The table/column catalog for the console's schema sidebar:
        ``{tables: [{name, columns: [{name, type}]}]}``, ordered."""
        rows = self.con.execute(
            "SELECT table_name, column_name, data_type "
            "FROM information_schema.columns "
            "WHERE table_schema = 'main' "
            "ORDER BY table_name, ordinal_position"
        ).fetchall()
        tables: dict[str, list] = {}
        for tname, cname, ctype in rows:
            tables.setdefault(tname, []).append({"name": cname, "type": ctype})
        return {
            "tables": [
                {"name": t, "columns": cols} for t, cols in tables.items()
            ]
        }
