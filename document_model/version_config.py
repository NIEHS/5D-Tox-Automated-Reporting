"""
version_config.py — per-DTXSID report VERSIONS (structure + filters).

A single processed dataset can back multiple report versions, each with its own
document STRUCTURE and its own data FILTERS (which sexes/assays/organs/genes
appear) — and, later, its own computational METHODS.  Phase 2 made the compute
caches filter-agnostic (the full superset), so a version is purely a render-time
projection: no reprocessing when you switch or add one.

Storage: ``sessions/<dtxsid>/versions/<name>.yaml``.  Each file is a mapping:

    document:   [ ...node entries... ]     # optional — falls back to the global tree
    filters:                               # optional — canonical filter shape
      organs:   {area: {sex|"*": [tokens]}}
      sex:      {area: {sex|"*": [tokens]}}
      assays:   {area: {sex|"*": [tokens]}}
      genes:    {"*": {"*": [tokens]}}
      gene_sets:{"*": {"*": [tokens]}}
    charts:     [types] | null             # optional — closed-vocab enable list
    methods:    { ... }                    # optional — reserved for phase 4

The ``default`` version reproduces today's behavior: absent ⇒ the global
template's structure + filters.  Back-compat: a legacy single
``sessions/<dtxsid>/document.yaml`` (document_config) is surfaced as the
``default`` version's structure when no versions/ dir exists.

Only structure + filters are handled here; the heavy compute never sees a
version.  History/archive mirrors document_config (each save archives the prior
file under history/_versions/<name>/).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from pipeline.session_store import SESSIONS_DIR

_VERSIONS_DIR = "versions"
_VERSIONS_HISTORY = "_versions"
DEFAULT_VERSION = "default"


def versions_dir(dtxsid: str) -> Path:
    """Directory holding a session's version files (may not exist)."""
    return SESSIONS_DIR / dtxsid / _VERSIONS_DIR


def version_path(dtxsid: str, name: str) -> Path:
    """Path to one version file (may not exist).  ``name`` is a bare slug."""
    return versions_dir(dtxsid) / f"{_safe_name(name)}.yaml"


def _safe_name(name: str) -> str:
    """A filesystem-safe version slug.  Rejects path separators / traversal so a
    version name can never escape the versions/ dir."""
    slug = (name or "").strip()
    if not slug or "/" in slug or "\\" in slug or slug in (".", ".."):
        raise ValueError(f"invalid version name {name!r}")
    return slug


def list_versions(dtxsid: str) -> list[str]:
    """Names of a session's saved versions, sorted; always includes 'default'.

    'default' is implicit — it exists conceptually even with no file (it means
    "the global template's structure + filters"), so callers can always render
    it.  Any *.yaml under versions/ is a named version."""
    names = {DEFAULT_VERSION}
    d = versions_dir(dtxsid)
    if d.exists():
        names.update(p.stem for p in d.glob("*.yaml") if p.is_file())
    return sorted(names)


def load_version(dtxsid: str, name: str) -> dict:
    """
    Load a version's raw mapping (``{document?, filters?, charts?, methods?}``).

    Returns ``{}`` for a version with no file — including ``default`` when no
    file exists (the caller then falls back to the global template).  Raises
    ValueError if the stored YAML is not a mapping.
    """
    path = version_path(dtxsid, name)
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(
            f"version {name!r} must be a YAML mapping, got {type(data).__name__}"
        )
    return data


def save_version(dtxsid: str, name: str, data: dict) -> None:
    """
    Validate then persist a version mapping, archiving any prior file.

    Validates the STRUCTURE (if a ``document`` block is present) with the same
    full tree build document_config uses, so an invalid structure never lands.
    The ``filters`` block is stored as-is (canonical shape produced by
    document_template.normalize_filters); it is validated lazily at render.
    """
    if not isinstance(data, dict):
        raise ValueError("version data must be a mapping")
    document = data.get("document")
    if document is not None:
        # Reuse document_config's validating tree build (raises on bad structure).
        from document_model.document_config import _tree_from_document_list
        if not isinstance(document, list):
            raise ValueError("version 'document' must be a list of node entries")
        _tree_from_document_list(document)

    path = version_path(dtxsid, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    _archive_before_overwrite(path, _history_dir(dtxsid, name))
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def delete_version(dtxsid: str, name: str) -> bool:
    """Delete a named version file (archiving it first).  'default' cannot be
    deleted (it is implicit).  Returns True if a file was removed."""
    if _safe_name(name) == DEFAULT_VERSION:
        raise ValueError("the 'default' version cannot be deleted")
    path = version_path(dtxsid, name)
    if not path.exists():
        return False
    _archive_before_overwrite(path, _history_dir(dtxsid, name))
    path.unlink()
    return True


def resolve_version_filters(dtxsid: str, name: str) -> dict:
    """
    The canonical ``{dimension: {area: {sex: [tokens]}}}`` filters + ``charts``
    for a version, ready for the render path.

    Resolution: a version's own ``filters``/``charts`` win; otherwise fall back
    to the GLOBAL template's filters (document_template.load_report_filters) —
    so ``default`` (and any version that doesn't override filters) reproduces
    today's output.
    """
    from document_model.document_tree import ACTIVE_TEMPLATE
    from document_model.document_template import load_report_filters

    version = load_version(dtxsid, name) if name else {}
    if "filters" in version or "charts" in version:
        return {
            "filters": version.get("filters") or {},
            "charts": version.get("charts"),
        }
    # No version-level filter override → the global template's filters.
    return load_report_filters(ACTIVE_TEMPLATE)


def build_version_tree(dtxsid: str, name: str):
    """
    The DocNode tree for a version: its own ``document`` structure if present,
    else the session's legacy document.yaml (document_config), else None so the
    caller uses the global DOCUMENT_TREE.
    """
    version = load_version(dtxsid, name) if name else {}
    document = version.get("document")
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
    return SESSIONS_DIR / dtxsid / "history" / _VERSIONS_HISTORY / _safe_name(name)


def _archive_before_overwrite(path: Path, history_dir: Path) -> None:
    if not path.exists():
        return
    from pipeline.session_store import now_iso
    safe_ts = now_iso().replace(":", "-")
    history_dir.mkdir(parents=True, exist_ok=True)
    (history_dir / f"{safe_ts}{path.suffix}").write_text(
        path.read_text(encoding="utf-8"), encoding="utf-8",
    )
