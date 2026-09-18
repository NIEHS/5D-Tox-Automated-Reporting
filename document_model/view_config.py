"""
view_config.py — per-DTXSID report VIEWS (structure + filters).

A single processed dataset can be projected into multiple report views, each with
its own document STRUCTURE and its own data FILTERS (which sexes/assays/organs/genes
appear) — and, later, its own computational METHODS.  Phase 2 made the compute
caches filter-agnostic (the full superset), so a view is purely a render-time
projection: no reprocessing when you switch or add one.

A "view" is a saved LENS over the one evolving report, NOT a coexisting version in
a branch/tag tree (ADR-0020: one report that evolves, with history behind it).
Content history/undo lives elsewhere (session_store save_section version numbers +
the /api/session/.../history routes) — that is the "history behind it" and is
distinct from a view.

Storage: ``sessions/<dtxsid>/views/<name>.yaml``.  Each file is a mapping:

    document:   [ ...node entries... ]     # optional — falls back to the global tree
    filters:                               # optional — canonical filter shape
      organs:   {area: {sex|"*": [tokens]}}
      sex:      {area: {sex|"*": [tokens]}}
      assays:   {area: {sex|"*": [tokens]}}
      genes:    {"*": {"*": [tokens]}}
      gene_sets:{"*": {"*": [tokens]}}
    charts:     [types] | null             # optional — closed-vocab enable list
    methods:    { ... }                    # optional — reserved for phase 4

The ``default`` view reproduces today's behavior: absent ⇒ the global
template's structure + filters.  Back-compat: a legacy single
``sessions/<dtxsid>/document.yaml`` (document_config) is surfaced as the
``default`` view's structure when no views/ dir exists.

Only structure + filters are handled here; the heavy compute never sees a
view.  History/archive mirrors document_config (each save archives the prior
file under history/_views/<name>/).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from common.paths import SESSIONS_DIR
from common.dtxsid import validate_dtxsid

_VIEWS_DIR = "views"
_VIEWS_HISTORY = "_views"
DEFAULT_VIEW = "default"


def views_dir(dtxsid: str) -> Path:
    """Directory holding a session's view files (may not exist)."""
    return SESSIONS_DIR / validate_dtxsid(dtxsid) / _VIEWS_DIR


def view_path(dtxsid: str, name: str) -> Path:
    """Path to one view file (may not exist).  ``name`` is a bare slug."""
    return views_dir(dtxsid) / f"{_safe_name(name)}.yaml"


def _safe_name(name: str) -> str:
    """A filesystem-safe view slug.  Rejects path separators / traversal so a
    view name can never escape the views/ dir."""
    slug = (name or "").strip()
    if not slug or "/" in slug or "\\" in slug or slug in (".", ".."):
        raise ValueError(f"invalid view name {name!r}")
    return slug


def list_views(dtxsid: str) -> list[str]:
    """Names of a session's saved views, sorted; always includes 'default'.

    'default' is implicit — it exists conceptually even with no file (it means
    "the global template's structure + filters"), so callers can always render
    it.  Any *.yaml under views/ is a named view."""
    names = {DEFAULT_VIEW}
    d = views_dir(dtxsid)
    if d.exists():
        names.update(p.stem for p in d.glob("*.yaml") if p.is_file())
    return sorted(names)


def load_view(dtxsid: str, name: str) -> dict:
    """
    Load a view's raw mapping (``{document?, filters?, charts?, methods?}``).

    Returns ``{}`` for a view with no file — including ``default`` when no
    file exists (the caller then falls back to the global template).  Raises
    ValueError if the stored YAML is not a mapping.
    """
    path = view_path(dtxsid, name)
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(
            f"view {name!r} must be a YAML mapping, got {type(data).__name__}"
        )
    return data


def save_view(dtxsid: str, name: str, data: dict) -> None:
    """
    Validate then persist a view mapping, archiving any prior file.

    Validates the STRUCTURE (if a ``document`` block is present) with the same
    full tree build document_config uses, so an invalid structure never lands.
    The ``filters`` block is normalized to the canonical
    ``{dimension: {area: {sex_key: [tokens]}}}`` shape and validated on the way
    in (document_template.normalize_filters_block) — the render-time consumer
    (resolve_report_allowlist) assumes that shape, so a non-canonical or
    malformed filters block must be caught here, not crash at render.  A bad
    ``charts`` block (must be a list of type strings, or null) is rejected too.
    """
    if not isinstance(data, dict):
        raise ValueError("view data must be a mapping")
    document = data.get("document")
    if document is not None:
        # Reuse document_config's validating tree build (raises on bad structure).
        from document_model.document_config import _tree_from_document_list
        if not isinstance(document, list):
            raise ValueError("view 'document' must be a list of node entries")
        _tree_from_document_list(document)

    # Normalize + validate filters (canonical shape), so render never sees a
    # legacy/malformed shape.  Rewrite the stored value with the canonical form.
    data = dict(data)  # don't mutate the caller's mapping
    if "filters" in data:
        from document_model.document_template import normalize_filters_block
        data["filters"] = normalize_filters_block(data.get("filters"))

    # charts is a closed-vocab enable list: a list of type strings, or null
    # (absent/null ⇒ render all; [] ⇒ render none — presence-sensitive, so we
    # keep [] distinct from absent and never coerce it away).
    if "charts" in data and data["charts"] is not None:
        charts = data["charts"]
        if not isinstance(charts, list) or not all(isinstance(c, str) for c in charts):
            raise ValueError("view 'charts' must be a list of type strings, or null")

    path = view_path(dtxsid, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    _archive_before_overwrite(path, _history_dir(dtxsid, name))
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def delete_view(dtxsid: str, name: str) -> bool:
    """Delete a named view file (archiving it first).  'default' cannot be
    deleted (it is implicit).  Returns True if a file was removed."""
    if _safe_name(name) == DEFAULT_VIEW:
        raise ValueError("the 'default' view cannot be deleted")
    path = view_path(dtxsid, name)
    if not path.exists():
        return False
    _archive_before_overwrite(path, _history_dir(dtxsid, name))
    path.unlink()
    return True


def resolve_view_filters(dtxsid: str, name: str) -> dict:
    """
    The canonical ``{dimension: {area: {sex: [tokens]}}}`` filters + ``charts``
    for a view, ready for the render path.

    Resolution: a view's own ``filters``/``charts`` win; otherwise fall back
    to the GLOBAL template's filters (document_template.load_report_filters) —
    so ``default`` (and any view that doesn't override filters) reproduces
    today's output.
    """
    from document_model.document_tree import ACTIVE_TEMPLATE
    from document_model.document_template import load_report_filters

    view = load_view(dtxsid, name) if name else {}
    if "filters" in view or "charts" in view:
        return {
            "filters": view.get("filters") or {},
            "charts": view.get("charts"),
        }
    # No view-level filter override → the global template's filters.
    return load_report_filters(ACTIVE_TEMPLATE)


def build_view_tree(dtxsid: str, name: str):
    """
    The DocNode tree for a view: its own ``document`` structure if present,
    else the session's legacy document.yaml (document_config), else None so the
    caller uses the global DOCUMENT_TREE.
    """
    view = load_view(dtxsid, name) if name else {}
    document = view.get("document")
    if document is not None:
        from document_model.document_config import _tree_from_document_list
        return _tree_from_document_list(document)
    # Fall back to the legacy per-session single-structure override.
    from document_model.document_config import build_session_tree
    return build_session_tree(dtxsid)


# ---------------------------------------------------------------------------
# History / archive — mirrors document_config._archive_before_overwrite.
# ---------------------------------------------------------------------------

def _history_dir(dtxsid: str, name: str) -> Path:
    return SESSIONS_DIR / validate_dtxsid(dtxsid) / "history" / _VIEWS_HISTORY / _safe_name(name)


def _archive_before_overwrite(path: Path, history_dir: Path) -> None:
    if not path.exists():
        return
    from common.clock import now_iso
    safe_ts = now_iso().replace(":", "-")
    history_dir.mkdir(parents=True, exist_ok=True)
    (history_dir / f"{safe_ts}{path.suffix}").write_text(
        path.read_text(encoding="utf-8"), encoding="utf-8",
    )
