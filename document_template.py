"""
document_template.py — load a data-driven document template and instantiate it
into the canonical DocNode tree (ADR-0003, Phase 2).

A *template* is data (a YAML file under templates/): an ordered, nested
selection of component types from the catalog (render_capabilities).  This
module turns that data into the runtime DocNode tree the renderers and the
navigation panel consume.  So the document structure is now AUTHORED as data
and the in-memory tree is the OUTPUT of instantiating it — invariant #2 (the
tree drives all structure) is preserved; only the tree's *source* moved from a
hand-written Python literal to a template the instantiator reproduces.

Three things the template does NOT carry, because they are computed:

  - level — derived as `0 if the type is headingless else nesting depth`,
    using the catalog's `headingless` flag.
  - table_number / figure_number — positional, assigned later by the
    numbering pre-pass (compute_table_numbers).

Single source of truth for the node shape
------------------------------------------
The set of fields a template node may bind is DERIVED from the DocNode
dataclass (document_node.DocNode) — see `_BINDING_FIELDS` — rather than
re-listed here.  Adding a field to DocNode therefore cannot silently diverge
from what the instantiator forwards or what the validator accepts.

Import graph (no cycle): document_node (a leaf module) ← document_template ←
document_tree; document_template also reads the catalog (render_capabilities).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from dataclasses import fields
from pathlib import Path

import yaml

from document_node import DocNode
from render_capabilities import (
    COMPONENT_CATALOG,
    capabilities_for,
    is_allowed_child,
    is_captionable,
    is_headingless,
    required_bindings_for,
)


# ---------------------------------------------------------------------------
# Constants — derived from the DocNode shape so they cannot drift
# ---------------------------------------------------------------------------

# Where authored templates live.  One file per template; YAML is the authoring
# format (comments, readability), JSON is the canonical comparison form used by
# the golden-tree test.
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# DocNode fields the instantiator computes or handles specially, so a template
# must NOT bind them by name:
#   level, table_number, figure_number — computed
#   node_type — bound via the template's `type` key (the one renamed field)
#   children  — recursion, not a scalar binding
_COMPUTED_OR_SPECIAL = frozenset(
    {"level", "node_type", "children", "table_number", "figure_number"}
)

# The scalar binding fields a template node supplies BY THE SAME NAME as the
# DocNode field (id, title, data_key, platform, narrative_key, ready_key,
# methods_key).  DERIVED from DocNode so there is ONE source of truth: add a
# (non-computed) field to DocNode and it becomes forwardable automatically,
# with no risk of the validator and the constructor disagreeing.
_BINDING_FIELDS = tuple(
    f.name for f in fields(DocNode) if f.name not in _COMPUTED_OR_SPECIAL
)

# Every key a template node entry may carry: the binding fields plus `type`
# (→ node_type) and `children` (recursion).  Anything else is an authoring
# mistake (a typo, a stale field) and is rejected loudly.
_KNOWN_KEYS = frozenset(_BINDING_FIELDS) | {"type", "children"}

# Keys every node entry must supply regardless of type.
_REQUIRED_KEYS = ("id", "type", "title")


# ---------------------------------------------------------------------------
# Helper / validation functions (private)
# ---------------------------------------------------------------------------

def _validate_entry(entry: dict, parent_type: str | None) -> None:
    """
    Reject a malformed template entry before it becomes a broken tree node.

    Checks, in order: it's a mapping; it has the required keys; it has no
    unknown keys; its type exists in the catalog; the catalog's containment
    grammar permits this type under its parent; and every binding the type
    REQUIRES (e.g. a `table` needs a `platform`) is present and non-empty.
    """
    if not isinstance(entry, dict):
        raise ValueError(
            f"template node must be a mapping, got {type(entry).__name__}: {entry!r}"
        )

    node_id = entry.get("id", "<no-id>")

    missing = [k for k in _REQUIRED_KEYS if k not in entry]
    if missing:
        raise ValueError(f"template node {node_id!r} is missing required key(s): {missing}")

    unknown = set(entry) - _KNOWN_KEYS
    if unknown:
        raise ValueError(f"template node {node_id!r} has unknown key(s): {sorted(unknown)}")

    node_type = entry["type"]
    if node_type not in COMPONENT_CATALOG:
        raise ValueError(
            f"template node {node_id!r} uses type {node_type!r}, which is not in the catalog"
        )

    # Containment grammar: a child's type must be an allowed child of its
    # parent's type.  Top-level nodes have no parent and are not checked here.
    if parent_type is not None and not is_allowed_child(parent_type, node_type):
        raise ValueError(
            f"template node {node_id!r}: type {node_type!r} is not an allowed child "
            f"of parent type {parent_type!r}"
        )

    # Required bindings: a type may declare wiring it cannot render without
    # (e.g. a `table` must name a `platform`).  Catch the omission HERE, at
    # load time, instead of as a silently-empty section at render time.
    for binding in required_bindings_for(node_type):
        value = entry.get(binding)
        if value is None or value == "":
            raise ValueError(
                f"template node {node_id!r} of type {node_type!r} is missing "
                f"required binding {binding!r}"
            )

    # Layout settings are gated on the type's capability (ADR-0003 Amendment 1):
    # orientation may only be authored on an orientable type, and only as
    # portrait/landscape.  A bad hand-edit fails loudly at load time.
    orientation = entry.get("orientation")
    if orientation is not None:
        if orientation not in ("portrait", "landscape"):
            raise ValueError(
                f"template node {node_id!r}: orientation must be 'portrait' or "
                f"'landscape', got {orientation!r}"
            )
        if not capabilities_for(node_type).orientable:
            raise ValueError(
                f"template node {node_id!r}: orientation set but type "
                f"{node_type!r} is not orientable"
            )

    # Captions are gated on the type's captionable flag (ADR-0004 amendment a):
    # caption only on table-like types (BITS <table-wrap>/<fig>); a section
    # carries only <title>.  Empty/None captions are simply absent.
    if entry.get("caption") and not is_captionable(node_type):
        raise ValueError(
            f"template node {node_id!r}: caption set but type "
            f"{node_type!r} is not captionable"
        )


def _instantiate(template: list[dict], depth: int, parent_type: str | None) -> list[DocNode]:
    """
    Recursive worker for instantiate().  `depth` (1 at the top) drives level
    derivation; `parent_type` drives containment validation.
    """
    nodes: list[DocNode] = []
    for entry in template:
        _validate_entry(entry, parent_type)
        node_type = entry["type"]
        # level is derived, never authored: headingless types (cover, title
        # page, bare data tables) are level 0; everything else takes its
        # nesting depth (top-level = 1).
        level = 0 if is_headingless(node_type) else depth
        children = _instantiate(entry.get("children", []), depth + 1, node_type)
        # Forward every binding field by name; an absent optional field becomes
        # None (DocNode's default), exactly matching the old hand-written literal.
        bindings = {name: entry.get(name) for name in _BINDING_FIELDS}
        nodes.append(
            DocNode(node_type=node_type, level=level, children=children, **bindings)
        )
    return nodes


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_template(name: str) -> list[dict]:
    """
    Load a template by name (without extension) from TEMPLATES_DIR.

    Returns the raw list of node-entry dicts.  Raises FileNotFoundError if the
    template file does not exist, or ValueError if the file is not a YAML list.
    """
    path = TEMPLATES_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"no template named {name!r} at {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(
            f"template {name!r} must be a YAML list of node entries, got {type(data).__name__}"
        )
    return data


def instantiate(template: list[dict]) -> list[DocNode]:
    """
    Instantiate a template (list of node-entry dicts) into a DocNode tree.

    Validates each entry, derives heading level from the catalog's headingless
    flag and nesting depth, recurses into children, and constructs DocNodes.
    Positional table/figure numbers are NOT assigned here — the caller runs
    compute_table_numbers() afterward, exactly as before.
    """
    return _instantiate(template, depth=1, parent_type=None)


def build_tree(name: str) -> list[DocNode]:
    """Convenience: load a named template and instantiate it in one call."""
    return instantiate(load_template(name))
