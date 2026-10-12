"""web_routes.supplemental_routes — a study's supplemental data, served locally.

Until a study's data deposit is made (and its DOI known, when the publishing
package is created), its Supplemental Data appendix names the LOCAL url of its
supplemental folder, ``sessions/<id>/supplemental/`` (pipeline.deposit,
local_url).  These routes make that url resolve:

  GET /api/sessions/<dtxsid>/supplemental/          the folder's files, linked
  GET /api/sessions/<dtxsid>/supplemental/<name>    one file

Only files directly in the folder are served; a name with a path separator,
or one that is not there, is a 404.
"""

from __future__ import annotations

import html as _html
from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from pipeline.deposit import LOCAL_DIR, deposit_listing
from pipeline.session_store import session_path
from web_routes.dtxsid_param import Dtxsid

router = APIRouter()


def _folder(dtxsid: str):
    return session_path(dtxsid) / LOCAL_DIR


@router.get(f"/api/sessions/{{dtxsid}}/{LOCAL_DIR}/")
async def api_supplemental_folder(dtxsid: Dtxsid):
    folder = _folder(dtxsid)
    files = deposit_listing(folder) if folder.is_dir() else []
    items = "".join(f'<li><a href="{quote(name)}">{_html.escape(name)}</a> ({size:,} bytes)</li>'
                    for name, size in files)
    body = (f"<ul>{items}</ul>" if files
            else "<p>No supplemental files have been gathered for this study yet.</p>")
    return HTMLResponse(f"<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
                        f"<title>Supplemental data — {_html.escape(dtxsid)}</title></head>"
                        f"<body><h1>Supplemental data — {_html.escape(dtxsid)}</h1>{body}"
                        f"</body></html>")


@router.get(f"/api/sessions/{{dtxsid}}/{LOCAL_DIR}/{{name}}")
async def api_supplemental_file(dtxsid: Dtxsid, name: str):
    folder = _folder(dtxsid)
    path = folder / name
    if "/" in name or "\\" in name or name in (".", "..") or not path.is_file() \
            or path.parent.resolve() != folder.resolve():
        return JSONResponse({"error": f"no supplemental file {name!r}"}, status_code=404)
    return FileResponse(str(path), filename=name)
