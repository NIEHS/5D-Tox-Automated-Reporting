"""
web_routes/app_mount.py — serves the new interface's built bundle (``ui/dist``)
at ``/app`` (MODULES.md §5; the prefix is provisional until the interface has a
name).

The bundle is a single-page app: its own router owns every path under /app. So
a path that names a file of the bundle (``/app/assets/index-1a2b.js``) serves
that file, and any other path under /app (``/app/studies/DTXSID…/files``)
serves ``index.html``, and the app shows the screen the path names.

Nothing outside /app changes. The bundle is looked up on each request, so a
fresh build is served without a restart; until there is one, /app answers 404
saying so.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

PREFIX = "/app"
DIST_DIR = Path(__file__).resolve().parent.parent / "ui" / "dist"


def _not_built(dist: Path) -> JSONResponse:
    return JSONResponse(
        {"error": f"The interface has not been built ({dist} is missing): "
                  f"cd ui && npm install && npm run build"}, status_code=404)


def make_router(dist: Path = DIST_DIR) -> APIRouter:
    """The /app routes over the bundle in `dist`."""
    router = APIRouter()

    @router.get(PREFIX, include_in_schema=False)
    async def _app_root():
        return RedirectResponse(url=f"{PREFIX}/")

    @router.get(PREFIX + "/{path:path}", include_in_schema=False)
    async def _app_path(path: str):
        index = dist / "index.html"
        if not index.is_file():
            return _not_built(dist)
        root = dist.resolve()
        if path:
            candidate = (dist / path).resolve()
            # A file of the bundle, and only of the bundle (no ../ out of it).
            if candidate.is_file() and candidate.is_relative_to(root):
                return FileResponse(candidate)
        # Re-read each time, never cached, so a rebuilt bundle shows at once.
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return router


router = make_router()
