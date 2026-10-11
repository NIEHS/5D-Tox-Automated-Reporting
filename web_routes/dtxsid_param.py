"""
web_routes/dtxsid_param.py — FastAPI dependency that validates the `{dtxsid}`
URL segment before a handler runs.

Usage in a route::

    from web_routes.dtxsid_param import Dtxsid

    @router.post("/api/session/reset/{dtxsid}")
    async def api_session_reset(dtxsid: Dtxsid):
        ...

`Dtxsid` is ``Annotated[str, Depends(require_dtxsid)]``: FastAPI resolves the
dependency's own ``dtxsid`` argument from the path (its name matches the path
parameter), `require_dtxsid` runs `common.dtxsid.validate_dtxsid`, and a bad
value raises InvalidDtxsid, which the app's exception handler turns into a 400
``{"error": ...}`` — the handler body never sees it. Starlette percent-decodes
path segments before this point, so ``%2e%2e`` arrives as ``..`` and is
rejected like any other.

This is the FIRST layer; the sink-level check in session_store (and every
``SESSIONS_DIR / validate_dtxsid(...)`` site) is the second and also covers
ids supplied in JSON bodies.
"""

from typing import Annotated

from fastapi import Depends

from common.dtxsid import validate_dtxsid


def require_dtxsid(dtxsid: str) -> str:
    """Validate the `{dtxsid}` path parameter; return it unchanged."""
    return validate_dtxsid(dtxsid)


Dtxsid = Annotated[str, Depends(require_dtxsid)]
