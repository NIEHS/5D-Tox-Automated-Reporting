"""
web_routes/refusal_response.py — a refusal as an HTTP response.

The application's usual ``{"error": message}`` body with the explanation
beside it (``code``, ``say``, ``fix``, ``details``: safeguards.refusals), so a
client that reads only ``error`` keeps working and a new one can show the
person what happened and what to do.
"""

from __future__ import annotations

from fastapi.responses import JSONResponse

from safeguards.refusals import error_body


def refusal_response(exc: BaseException) -> JSONResponse:
    body, status = error_body(exc)
    return JSONResponse(body, status_code=status)
