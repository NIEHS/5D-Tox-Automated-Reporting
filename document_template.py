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
  - table_number — positional, assigned later by the numbering pre-pass
    (compute_table_numbers).
  - figure_number — reserved positional field; there is no DocNode-level
    figure-numbering pass yet (genomics chart figure numbers are assigned on
    the chart payloads by genomics_charts.attach_genomics_charts), so it stays
    None on the tree today.

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
#   region    — set by the top-level region container (ADR-0004 amendment d),
#               inherited by descendants — never authored on a node entry.
_COMPUTED_OR_SPECIAL = frozenset(
    {"level", "node_type", "children", "table_number", "figure_number", "region"}
)

# Valid region names — project directly to BITS <front-matter> / <book-body> /
# <book-back> on a future BITS export (ADR-0004 amendment d).
_VALID_REGIONS: tuple[str, ...] = ("front", "body", "back")
_REGION_CONTAINER_KEYS = frozenset({"region", "children"})

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


def _validate_region_container(entry: dict) -> None:
    """
    Validate a top-level region container ({region: ..., children: [...]}) —
    ADR-0004 amendment d.  Caller has already confirmed `region` is a key.
    """
    extra = set(entry) - _REGION_CONTAINER_KEYS
    if extra:
        raise ValueError(f"region container has unknown key(s): {sorted(extra)}")
    region = entry["region"]
    if region not in _VALID_REGIONS:
        raise ValueError(
            f"region must be one of {list(_VALID_REGIONS)}, got {region!r}"
        )
    children = entry.get("children", [])
    if not isinstance(children, list):
        raise ValueError("region container 'children' must be a list")


def _instantiate_node(
    entry: dict,
    depth: int,
    parent_type: str | None,
    region: str | None,
) -> DocNode:
    """
    Instantiate a single node entry, recursing into its children.  `region`
    is the book region inherited from the top-level region container (ADR-0004
    amendment d); descendants share it.  `depth` (1 at the top) drives level
    derivation; `parent_type` drives containment validation.
    """
    _validate_entry(entry, parent_type)
    node_type = entry["type"]
    # level is derived, never authored: headingless types (cover, title page,
    # bare data tables) are level 0; everything else takes its nesting depth.
    level = 0 if is_headingless(node_type) else depth
    children = [
        _instantiate_node(c, depth + 1, node_type, region)
        for c in entry.get("children", [])
    ]
    # Forward every binding field by name; an absent optional field becomes
    # None (DocNode's default), exactly matching the old hand-written literal.
    bindings = {name: entry.get(name) for name in _BINDING_FIELDS}
    return DocNode(
        node_type=node_type, level=level, children=children, region=region, **bindings
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _load_raw(name: str):
    """Parse a template YAML file by name; return the raw deserialized value
    (a list for legacy scaffolds, or a mapping with a ``document:`` key for the
    full config).  Raises FileNotFoundError if absent."""
    path = TEMPLATES_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"no template named {name!r} at {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_template(name: str) -> list[dict]:
    """
    Load a template by name (without extension) from TEMPLATES_DIR.

    Returns the raw list of node-entry dicts (the *document* structure).  The
    file may be EITHER:

      - a bare YAML list of node entries (legacy scaffolds, unit-test fixtures), or
      - a mapping with a ``document:`` key holding that list, alongside optional
        sibling blocks (``chart_style``, ``chart_types``) read by
        :func:`load_chart_style` / :func:`load_chart_types`.

    Either way this returns the document LIST, so ``instantiate``, ``build_tree``,
    and the golden-tree test are unaffected by the sibling blocks.  Raises
    ValueError if the shape is neither.
    """
    data = _load_raw(name)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "document" in data:
        doc = data["document"]
        if not isinstance(doc, list):
            raise ValueError(
                f"template {name!r}: 'document' must be a list of node entries, "
                f"got {type(doc).__name__}"
            )
        return doc
    raise ValueError(
        f"template {name!r} must be a YAML list of node entries, or a mapping "
        f"with a 'document' key, got {type(data).__name__}"
    )


def load_chart_style(name: str) -> dict:
    """
    Load the ``chart_style`` block from a template (the three-layer style config
    consumed by chart_style.resolve_chart_style).  Returns ``{}`` when the file
    is a bare list or has no ``chart_style`` key — so the no-config render path
    (built-in defaults only) is unchanged.

    Validates SHAPE only (loudly): ``chart_style`` must be a mapping whose
    ``defaults``/``types``/``instances`` sub-blocks, when present, are mappings.
    Unknown *style keys* are not fatal here — they are reported per-instance at
    render time (genomics_viz logs chart_style.unknown_style_keys).
    """
    data = _load_raw(name)
    if not isinstance(data, dict):
        return {}
    cfg = data.get("chart_style")
    if cfg is None:
        return {}
    if not isinstance(cfg, dict):
        raise ValueError(
            f"template {name!r}: 'chart_style' must be a mapping, "
            f"got {type(cfg).__name__}"
        )
    for sub in ("defaults", "types", "instances"):
        if sub in cfg and not isinstance(cfg[sub], dict):
            raise ValueError(
                f"template {name!r}: chart_style.{sub} must be a mapping, "
                f"got {type(cfg[sub]).__name__}"
            )
    return cfg


def load_chart_types(name: str):
    """
    Load the ``chart_types`` block and build the effective chart-type registry.

    Returns ``chart_registry.build_registry(raw)`` — the built-in code types
    (umap, cluster) merged with the data-driven types declared in the template.
    Each declared spec is validated LOUDLY by build_registry (a name colliding
    with a code type, a non-mapping spec, or a missing trace/x/y raises).  A bare
    list or a missing ``chart_types`` key yields just the built-ins (today's
    behaviour).
    """
    import chart_registry

    data = _load_raw(name)
    raw = data.get("chart_types") if isinstance(data, dict) else None
    if raw is not None and not isinstance(raw, dict):
        raise ValueError(
            f"template {name!r}: 'chart_types' must be a mapping of "
            f"name → spec, got {type(raw).__name__}"
        )
    return chart_registry.build_registry(raw)


def instantiate(template: list[dict]) -> list[DocNode]:
    """
    Instantiate a template into a flat list of DocNode top-level entries.

    Top-level template entries are EITHER region containers
    ({region: "front"|"body"|"back", children: [...]}) — ADR-0004 amendment d
    — OR bare node entries (back-compat for unit-test scaffolding).  Region
    containers set the `region` for their children and descendants; bare
    entries get region=None.  The returned list is flat (regions are unrolled
    so DOCUMENT_TREE shape is unchanged); each node carries `region`.

    Validates each entry against the catalog (type, containment, required
    bindings, capability-gated orientation/caption), derives heading level
    from the catalog's headingless flag + nesting depth, and recurses into
    children.  Positional table/figure numbers are NOT assigned here — the
    caller runs compute_table_numbers() afterward, exactly as before.
    """
    nodes: list[DocNode] = []
    for entry in template:
        if isinstance(entry, dict) and "region" in entry:
            _validate_region_container(entry)
            region = entry["region"]
            for child in entry.get("children", []):
                nodes.append(_instantiate_node(child, depth=1, parent_type=None, region=region))
        else:
            nodes.append(_instantiate_node(entry, depth=1, parent_type=None, region=None))
    return nodes


def build_tree(name: str) -> list[DocNode]:
    """Convenience: load a named template and instantiate it in one call."""
    return instantiate(load_template(name))
