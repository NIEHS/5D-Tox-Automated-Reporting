"""
web_routes/structure_routes.py — helper routes for the visual document-structure
editor (Configure step, "Document structure" tab).

The on-disk format of a session's structure is YAML (`document:` list of region
containers → node entries), validated on save by document_model.document_config.
The editor works on the PARSED shape (a JSON node tree) and needs four things
the text editor did not:

  GET  /api/document-structure/catalog       the component catalog as JSON —
                                             per node type: allowed children,
                                             required bindings, capabilities —
                                             plus the binding vocabularies
                                             (platforms, data keys, ...) for
                                             pickers. Rule-driven UI: nothing
                                             structural is hardcoded client-side.
  POST /api/document-structure/parse    {yaml}     → {document}  (YAML → node list)
  POST /api/document-structure/dump     {document} → {yaml}      (node list → YAML,
                                             same dumper as the default config
                                             so round-trips are byte-stable)
  POST /api/document-structure/validate {document} → {ok, error?, node_id?}
                                             dry-run of the full save-time
                                             validation, with a best-effort
                                             attribution to the offending node.

None of these write anything; saving still goes through the existing
POST /api/document-config/{dtxsid}, which re-validates. (They live under
/api/document-structure/ because that route's {dtxsid} path parameter would
otherwise capture "parse"/"dump"/"validate" as a session id.) YAML remains the
source of truth on disk; the editor is a projection of it.
"""

from __future__ import annotations

import logging
import re

import yaml
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()

_ORIENTATIONS = ("portrait", "landscape")
_REGIONS = ("front", "body", "back")


def _catalog_payload() -> dict:
    """The component catalog + binding vocabularies, JSON-shaped."""
    from document_model import document_template as dt
    from document_model.render_capabilities import (
        COMPONENT_CATALOG, FIGURE_SUBTYPES, FRONT_MATTER_ROLES_BY_DATA_KEY,
    )
    from workflow.phases import APICAL_PLATFORMS

    types = {}
    for name, comp in COMPONENT_CATALOG.items():
        cap = comp.capabilities
        types[name] = {
            "allowed_children": list(comp.allowed_children),
            "requires": list(comp.requires),
            "orientable": cap.orientable,
            "breakable": cap.breakable,
            "editable": cap.editable,
            "captionable": comp.captionable,
            "headingless": comp.headingless,
            "subtypable": name in dt._SUBTYPABLE_TYPES,
            "freeform": name in dt._FREEFORM_TYPES,
        }

    # Vocabularies: what the DEFAULT template uses, plus the closed sets the
    # code knows. Pickers offer these; free text stays allowed (the server
    # validates on save).
    seen: dict[str, set] = {"data_key": set(), "narrative_key": set(), "methods_key": set(),
                            "platform": set(), "subtype": set()}

    def walk(entries):
        for e in entries or []:
            if not isinstance(e, dict):
                continue
            for k in seen:
                v = e.get(k)
                if isinstance(v, str) and v:
                    seen[k].add(v)
            walk(e.get("children"))

    from document_model import document_config as dc
    walk(dc.load_template(dc.ACTIVE_TEMPLATE))
    seen["platform"] |= set(APICAL_PLATFORMS) | {"Clinical Observations", "Tissue Concentration"}
    seen["data_key"] |= set(FRONT_MATTER_ROLES_BY_DATA_KEY)
    seen["subtype"] |= set(FIGURE_SUBTYPES)

    return {
        "types": types,
        "node_keys": sorted(dt._KNOWN_KEYS),
        "regions": list(_REGIONS),
        "vocab": {
            "platforms": sorted(seen["platform"]),
            "data_keys": sorted(seen["data_key"]),
            "narrative_keys": sorted(seen["narrative_key"]),
            "methods_keys": sorted(seen["methods_key"]),
            "subtypes": sorted(seen["subtype"]),
            "orientations": list(_ORIENTATIONS),
        },
    }


@router.get("/api/document-structure/catalog")
async def api_document_catalog():
    try:
        return JSONResponse(_catalog_payload())
    except Exception as e:
        logger.exception("document-catalog failed")
        return JSONResponse({"error": f"catalog unavailable: {e}"}, status_code=500)


async def _json_body(request: Request) -> dict | None:
    try:
        body = await request.json()
    except Exception:
        return None
    return body if isinstance(body, dict) else None


@router.post("/api/document-structure/parse")
async def api_document_config_parse(request: Request):
    """YAML text → the node-entry list the editor edits (no validation beyond
    shape; the editor validates as you go)."""
    from document_model.document_config import _parse_document_yaml
    body = await _json_body(request)
    text = (body or {}).get("yaml")
    if not isinstance(text, str) or not text.strip():
        return JSONResponse({"error": "Request must include a non-empty 'yaml' string."}, status_code=400)
    try:
        return JSONResponse({"document": _parse_document_yaml(text)})
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=422)


@router.post("/api/document-structure/dump")
async def api_document_config_dump(request: Request):
    """Node-entry list → YAML text, using the same dumper as the default config
    so the Advanced tab shows exactly what will be saved."""
    body = await _json_body(request)
    document = (body or {}).get("document")
    if not isinstance(document, list):
        return JSONResponse({"error": "Request must include a 'document' list."}, status_code=400)
    text = yaml.safe_dump({"document": document}, sort_keys=False, allow_unicode=True)
    return JSONResponse({"yaml": text})


def _all_ids(entries) -> list[str]:
    out: list[str] = []
    for e in entries or []:
        if isinstance(e, dict):
            if isinstance(e.get("id"), str):
                out.append(e["id"])
            out.extend(_all_ids(e.get("children")))
    return out


def attribute_error(message: str, document: list) -> str | None:
    """Best-effort: which node does a validation message talk about? The
    validator quotes ids ('foo' / "foo"); pick the quoted token that is a real
    node id in this document (longest first, so 'table-1' beats 'table')."""
    ids = set(_all_ids(document))
    quoted = re.findall(r"['\"]([A-Za-z0-9_.-]+)['\"]", message)
    for tok in sorted(set(quoted), key=len, reverse=True):
        if tok in ids:
            return tok
    return None


@router.post("/api/document-structure/validate")
async def api_document_config_validate(request: Request):
    """Dry-run the full save-time validation on a node-entry list."""
    from document_model.document_config import _tree_from_document_list
    body = await _json_body(request)
    document = (body or {}).get("document")
    if not isinstance(document, list):
        return JSONResponse({"error": "Request must include a 'document' list."}, status_code=400)
    try:
        _tree_from_document_list(document)
    except ValueError as e:
        msg = str(e)
        return JSONResponse({"ok": False, "error": msg, "node_id": attribute_error(msg, document)})
    except Exception as e:  # a crash in validation is still "not valid" for the editor
        logger.exception("document-config validate crashed")
        return JSONResponse({"ok": False, "error": f"validation failed: {e}", "node_id": None})
    return JSONResponse({"ok": True})
