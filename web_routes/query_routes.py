"""
Query routes — the read-only SQL API over a session's DuckDB (ADR-0016 Phase B).

The transport layer for the power-user query tool. Both routes are read-only:

  POST /api/query/{dtxsid}
      Body: {"sql": "SELECT ...", "max_rows"?: int}
      → {columns, rows, row_count, truncated}
      Runs ONE read-only SELECT/WITH via query.session_query (which opens the DB
      read_only and enforces the SELECT-only / single-statement / LIMIT guards).

  GET /api/query/{dtxsid}/schema
      → {tables: [{name, columns: [{name, type}]}]}
      The table/column catalog for the console's schema sidebar.

A rejected statement or a missing DB is a 400 (QueryError), not a 500 — the
client surfaces it to the user. The session DB holds only that session's study
data, so there is no cross-session exposure.
"""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from query.session_query import (
    DEFAULT_MAX_ROWS,
    QueryError,
    SessionQuerier,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Hard ceiling on the client-requested max_rows, so a caller can't ask for an
# unbounded result by passing a huge max_rows.
_MAX_ROWS_CEILING = 50_000


@router.post("/api/query/{dtxsid}")
async def api_query(dtxsid: str, request: Request):
    """Run one read-only SELECT/WITH against the session DB."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "request body must be JSON"}, status_code=400)

    if not isinstance(body, dict):
        return JSONResponse({"error": "request body must be a JSON object"}, status_code=400)

    sql = body.get("sql")
    if not isinstance(sql, str):
        return JSONResponse({"error": "'sql' (string) is required"}, status_code=400)

    max_rows = body.get("max_rows", DEFAULT_MAX_ROWS)
    try:
        max_rows = min(int(max_rows), _MAX_ROWS_CEILING)
    except (TypeError, ValueError):
        max_rows = DEFAULT_MAX_ROWS
    if max_rows < 1:
        max_rows = DEFAULT_MAX_ROWS

    try:
        with SessionQuerier(dtxsid) as q:
            result = q.run_sql(sql, max_rows=max_rows)
        return JSONResponse(result)
    except QueryError as e:
        # user/request error (bad SQL, no DB) — a 400, not a server fault
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:  # unexpected — log and surface generically
        logger.exception("query failed for %s", dtxsid)
        return JSONResponse({"error": f"query failed: {e}"}, status_code=500)


@router.get("/api/query/{dtxsid}/schema")
async def api_query_schema(dtxsid: str):
    """The table/column catalog for the session DB (schema sidebar)."""
    try:
        with SessionQuerier(dtxsid) as q:
            return JSONResponse(q.schema())
    except QueryError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        logger.exception("schema fetch failed for %s", dtxsid)
        return JSONResponse({"error": f"schema fetch failed: {e}"}, status_code=500)
