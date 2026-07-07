"""
document_config.py — per-session document STRUCTURE overrides (ADR-0007 follow-on).

The document tree is normally a single global built once at import from
``templates/niehs-5day-report.yaml`` (see document_tree.DOCUMENT_TREE).  This
module lets a single report (keyed by DTXSID) carry its OWN ``document:``
structure — sections, ordering, titles, orientation, freeform content — without
touching the global default template or re-integrating the study data.

Scope is deliberately STRUCTURE ONLY: the per-session file holds just the
``document:`` block.  The data-filter / chart blocks (organs, sex, assays,
genes, charts) stay global, because those feed the integration pipeline and
editing them would require a reprocess — the opposite of this feature's promise.

Storage: ``sessions/<dtxsid>/document.yaml``.  Absent ⇒ the caller falls back to
the global DOCUMENT_TREE (build_session_tree returns None), so an untouched
session renders byte-identically to today.

The file may be EITHER a bare YAML list of node entries or a mapping with a
``document:`` key — the same dual shape document_template.load_template accepts —
so a user can paste either form.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from document_node import DocNode
from document_template import instantiate, load_template
from document_tree import (
    ACTIVE_TEMPLATE,
    build_node_index,
    compute_table_numbers,
)
from session_store import SESSIONS_DIR

_SESSION_DOCUMENT_FILE = "document.yaml"


def session_document_path(dtxsid: str) -> Path:
    """Path to a session's per-session document-structure YAML (may not exist)."""
    return SESSIONS_DIR / dtxsid / _SESSION_DOCUMENT_FILE


def _parse_document_yaml(text: str) -> list[dict]:
    """
    Parse a document-structure YAML STRING into the node-entry list.

    Mirrors document_template.load_template's dual-shape acceptance (a bare list,
    or a mapping with a ``document:`` key), but from a string rather than a named
    file.  Raises ValueError if the shape is neither, or if the YAML is invalid.
    """
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ValueError(f"invalid YAML: {e}") from e
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "document" in data:
        doc = data["document"]
        if not isinstance(doc, list):
            raise ValueError(
                f"'document' must be a list of node entries, got {type(doc).__name__}"
            )
        return doc
    raise ValueError(
        "document config must be a YAML list of node entries, or a mapping with "
        f"a 'document' key, got {type(data).__name__}"
    )


def _tree_from_document_list(document: list[dict]) -> list[DocNode]:
    """
    Instantiate + finalize a tree from a parsed document list.

    Runs the full validation the global tree gets: instantiate() validates every
    entry against the catalog (type, containment, required bindings, capability-
    gated orientation/caption, freeform rules), and build_node_index() enforces
    globally-unique ids.  Both raise ValueError on bad input.  compute_table_numbers
    assigns positional table numbers on the fresh tree (in place).
    """
    tree = instantiate(document)
    compute_table_numbers(tree)
    build_node_index(tree)  # raises on duplicate ids; return value not needed here
    return tree


def default_document_yaml() -> str:
    """
    The global default ``document:`` structure, serialized to YAML text.

    Shown in the config editor when a session has no per-session override yet, so
    the user starts from the real active structure.  Re-dumped from the parsed
    block (comments in the source file are not carried), wrapped under a
    ``document:`` key to match the canonical file shape.
    """
    document = load_template(ACTIVE_TEMPLATE)
    return yaml.safe_dump({"document": document}, sort_keys=False, allow_unicode=True)


def load_session_document_yaml(dtxsid: str) -> str | None:
    """Raw per-session document YAML text, or None if the session has no override."""
    path = session_document_path(dtxsid)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def build_session_tree(dtxsid: str) -> list[DocNode] | None:
    """
    Build a per-session DocNode tree from the session's document.yaml.

    Returns None when the session has no per-session override, so callers fall
    back to the global DOCUMENT_TREE.  Raises ValueError if a stored file is
    somehow invalid (it shouldn't be — save validates before writing).
    """
    text = load_session_document_yaml(dtxsid)
    if text is None:
        return None
    return _tree_from_document_list(_parse_document_yaml(text))


def save_session_document_yaml(dtxsid: str, text: str) -> None:
    """
    Validate then persist a session's document-structure YAML.

    Validation is a full tree build (_tree_from_document_list): any parse error,
    catalog violation, missing required binding, bad orientation/caption, freeform
    rule breach, or duplicate id raises ValueError BEFORE anything is written — so
    an invalid edit never lands on disk and the previous structure stays intact.
    """
    _tree_from_document_list(_parse_document_yaml(text))  # validate; raises on failure
    path = session_document_path(dtxsid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
