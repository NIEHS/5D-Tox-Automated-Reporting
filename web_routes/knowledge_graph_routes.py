"""
HTTP routes for the knowledge-graph crawl-config editor.

Exposes the literature-crawl configuration (GovernorConfig surface) for viewing
and per-session editing, tracked against a frozen "original" baseline. Config-only:
no crawl is launched here. Persistence is one JSON file per session
(sessions/{dtxsid}/crawl_config.json), archived before each overwrite.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from web_routes.dtxsid_param import Dtxsid

from knowledge_base.crawl_config import (
    ORIGINAL_CRAWL_CONFIG,
    diff_against_original,
    validate_config,
)
from workflow.store import DiskPoolStore

logger = logging.getLogger(__name__)

router = APIRouter()

_CONFIG_NAME = "crawl_config.json"


def _archive_prior(dtxsid: str, store: DiskPoolStore) -> None:
    """Archive the current session config to history/ before it's overwritten."""
    path = store.session_dir(dtxsid) / _CONFIG_NAME
    if not path.exists():
        return
    from pipeline.session_store import now_iso
    history_dir = store.session_dir(dtxsid) / "history" / "crawl_config"
    history_dir.mkdir(parents=True, exist_ok=True)
    safe_ts = now_iso().replace(":", "-")
    (history_dir / f"{safe_ts}.json").write_text(
        path.read_text(encoding="utf-8"), encoding="utf-8",
    )


def _current_config(dtxsid: str, store: DiskPoolStore, *, force_default: bool) -> tuple[dict, bool]:
    """Return (config, is_default). Falls back to the frozen original when the
    session has no saved config (or default is forced)."""
    if not force_default:
        saved = store.read_json(dtxsid, _CONFIG_NAME)
        if isinstance(saved, dict):
            return saved, False
    return dict(ORIGINAL_CRAWL_CONFIG), True


@router.get("/api/crawl-config/{dtxsid}")
async def api_get_crawl_config(dtxsid: Dtxsid, default: int = 0):
    """Load the session's crawl config (or the frozen original if unedited).

    Returns the config, whether it's the default, the immutable original (so the
    client can render its own diff), and the server-computed change-list.
    """
    store = DiskPoolStore()
    config, is_default = _current_config(dtxsid, store, force_default=bool(default))
    return JSONResponse({
        "config": config,
        "is_default": is_default,
        "original": ORIGINAL_CRAWL_CONFIG,
        "diff": diff_against_original(config),
    })


@router.post("/api/crawl-config/{dtxsid}")
async def api_save_crawl_config(dtxsid: Dtxsid, request: Request):
    """Validate and persist a tweaked crawl config. 422 on invalid, nothing written."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=422)

    config = body.get("config") if isinstance(body, dict) else None
    if not isinstance(config, dict):
        return JSONResponse({"error": "body must be {\"config\": {...}}"}, status_code=422)

    try:
        validate_config(config)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)

    store = DiskPoolStore()
    _archive_prior(dtxsid, store)
    store.write_json(dtxsid, _CONFIG_NAME, config)
    return JSONResponse({"ok": True, "diff": diff_against_original(config)})


@router.post("/api/crawl-config/{dtxsid}/reset")
async def api_reset_crawl_config(dtxsid: Dtxsid):
    """Revert to the frozen original by removing the session config (archived first)."""
    store = DiskPoolStore()
    _archive_prior(dtxsid, store)
    path = store.session_dir(dtxsid) / _CONFIG_NAME
    existed = path.exists()
    if existed:
        path.unlink()
    return JSONResponse({
        "ok": True,
        "reset": existed,
        "config": dict(ORIGINAL_CRAWL_CONFIG),
        "is_default": True,
        "original": ORIGINAL_CRAWL_CONFIG,
        "diff": {},
    })
