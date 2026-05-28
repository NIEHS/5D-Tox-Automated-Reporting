"""
render_capabilities.py — the component-type catalog.

This module is the SINGLE coupling point between the document template
(document_tree.py's node types) and the renderers/interaction layer.  It is
an *unordered registry of component types* (the "catalog" of ADR-0003): for
each document-semantic type it declares

  - its render *capabilities* (orientation / page-break / inline-edit),
  - the *content kinds* a component of that type may hold (text, table,
    chart, …) — the seed of the sub-addressable content-item model,
  - whether the type is *headingless* (renders with no heading of its own —
    e.g. the cover, a bare data table), and
  - its *allowed children* — the set of node types that may nest directly
    under it (a flat per-type adjacency list; the containment grammar is a
    DAG, since e.g. `table` lives under several parents).

Why this exists
---------------
User configuration of the rendered pages — which tables are landscape,
where page breaks go, which prose gets edited — must NOT care when the
document template evolves.  As long as a new section reuses an existing
component type (a `table`, a `narrative`, …), the renderers and UI already
know what to do with it: zero code change.  Only a genuinely new component
type (a new capability profile, content kind, or containment rule) requires
an edit here.  This is also what a data-driven template (ADR-0003) selects
from: a template picks types from this catalog and orders/nests them, and
the instantiator validates the nesting against `allowed_children`.

Decoupling contract
--------------------
  - This module imports NOTHING from document_tree.  It is keyed by
    node_type *strings*, so the dependency points one way (consumers →
    here) and the template never depends on the rendering layer.
  - Consumers: latex_generator and html_generator gate their per-node
    behaviour on capabilities; background_server annotates the serialized
    tree so the frontend reads capabilities instead of hardcoding its own
    copy of the mapping; the instantiator (ADR-0003 Phase 2) reads
    `headingless` to derive heading level and `allowed_children` to validate
    a template.
  - User choices (orientation/break/edit) are stored separately, keyed by
    node *id*; this module only says what's *possible* per node *type*.

How it fits the larger system
------------------------------
Template (a data spec)  ─ instantiated against ─▶  this catalog  ─▶  DocNode
tree  ─ walked by ─▶  Renderer.  The interaction UI reads capabilities (via
the annotated tree) to decide what to offer and writes the per-id overlay;
the renderer reads the overlay AND this catalog to decide what to emit.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Type definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NodeCapabilities:
    """
    The rendering operations a document-semantic type supports.

    Each flag answers one yes/no question about what the user may do to a
    node of this type in the interactive preview:

        orientable — its page can be flipped between portrait and landscape
                     (wide data tables, charts, figures).
        breakable  — a user-inserted page break may be placed before/after
                     it (most content; not the fixed front pages).
        editable   — its textual content may be edited in a popup (prose
                     sections; NOT data-driven tables, which come from the
                     integrated dataset).

    Defaults are all False so an unknown/unmapped type is treated as
    "no operations" — the safe, do-nothing fallback.
    """
    orientable: bool = False
    breakable: bool = False
    editable: bool = False

    def to_dict(self) -> dict:
        """Plain-dict form for JSON serialization to the frontend."""
        return {
            "orientable": self.orientable,
            "breakable": self.breakable,
            "editable": self.editable,
        }


@dataclass(frozen=True)
class ComponentType:
    """
    One entry in the component-type catalog — everything the system knows
    about a document-semantic type, independent of any single document.

    Fields:
        capabilities     — the render/interaction operations it supports
                           (see NodeCapabilities).
        content_kinds    — the kinds of content a component of this type may
                           hold, drawn from CONTENT_KINDS.  Today this is
                           declarative; ADR-0003 Phase 4 makes these the
                           sub-addressable content items inside a component.
                           A type whose payload is its child *nodes* (e.g.
                           heading-only) has no own content kinds.
        headingless      — True when the type renders with NO heading of its
                           own (cover, title page, a bare data table).  The
                           instantiator derives heading level from this:
                           level = 0 if headingless else nesting-depth, so
                           level need not be authored in the template.
        allowed_children — node types that may nest directly under this type
                           (a flat adjacency list).  Empty = a leaf type.
                           The instantiator validates a template's nesting
                           against this; it is a DAG, not a tree, because a
                           type like `table` appears under several parents.
        requires         — binding fields a node of this type MUST supply
                           (e.g. a `table` must name a `platform`).  The
                           instantiator rejects a template node that omits one
                           at LOAD time, instead of letting it render empty.
                           Names must be DocNode binding fields.
    """
    capabilities: NodeCapabilities = field(default_factory=NodeCapabilities)
    content_kinds: tuple[str, ...] = ()
    headingless: bool = False
    allowed_children: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Constants — capability presets, content-kind vocabulary, the catalog
# ---------------------------------------------------------------------------

# Named capability presets.  Most types fall into one of four profiles;
# naming them keeps the catalog DRY and makes the clusters explicit (the
# preference is composition of orthogonal traits, NOT a type taxonomy).
_FIXED = NodeCapabilities()                                  # nothing configurable
_STRUCTURAL = NodeCapabilities(breakable=True)               # may start a new page only
_PROSE = NodeCapabilities(breakable=True, editable=True)     # editable text, breakable
_DATA_BLOCK = NodeCapabilities(orientable=True, breakable=True)  # tables/charts/figures

# The closed vocabulary of content-item kinds a component may hold.  Kept
# deliberately small (a minimal subset of a full block-content model); it
# grows only when a genuinely new content kind appears.
CONTENT_KINDS: frozenset[str] = frozenset(
    {"text", "table", "chart", "image", "toc-entry"}
)

# The catalog: node_type → ComponentType.  This is the single place that
# grows when the template gains a node type.  `headingless` and
# `allowed_children` mirror today's DOCUMENT_TREE (Phase 2 verifies the
# match); `content_kinds` describes what each component carries.
COMPONENT_CATALOG: dict[str, ComponentType] = {
    # ── Fixed front pages — auto-laid-out, headingless, nothing to configure.
    "cover": ComponentType(
        capabilities=_FIXED, content_kinds=(), headingless=True,
    ),
    "title-page": ComponentType(
        capabilities=_FIXED, content_kinds=(), headingless=True,
    ),
    # ── Auto-generated list of tables — generated entries; can start a page.
    "tables-list": ComponentType(
        capabilities=_STRUCTURAL, content_kinds=("toc-entry",),
    ),
    # ── Generated Table of Contents — a front-matter component (distinct from
    #    the navigation panel).  It SELF-HEADS: LaTeX's \tableofcontents emits
    #    its own unnumbered "Contents" heading and the HTML renderer emits its
    #    own, so the generic heading machinery is skipped — hence headingless
    #    (level 0).  Generated from the tree's section order.
    "toc": ComponentType(
        capabilities=_STRUCTURAL, content_kinds=("toc-entry",), headingless=True,
    ),
    # ── A heading with no own content; its child NODES carry the content.
    #    This is the recursive structural container (it may nest itself).
    "heading-only": ComponentType(
        capabilities=_STRUCTURAL,
        content_kinds=(),
        allowed_children=(
            "heading-only", "narrative", "narrative+tables",
            "bmd-summary", "genomics-section",
        ),
    ),
    # ── Prose sections — editable text, breakable; never landscape (running
    #    body text doesn't rotate).
    "front-matter": ComponentType(
        capabilities=_PROSE, content_kinds=("text",), requires=("data_key",),
    ),
    "narrative": ComponentType(
        capabilities=_PROSE, content_kinds=("text",), requires=("data_key",),
    ),
    # Appendices currently carry no wiring (bodies are pending), so nothing is
    # required of them yet.
    "appendix": ComponentType(capabilities=_PROSE, content_kinds=("text",)),
    # ── Prose + child tables — the section's own content is the narrative
    #    text; the wide tables are separate child `table` nodes, each
    #    orientable on its own (prose stays portrait while a table flips).
    "narrative+tables": ComponentType(
        capabilities=_PROSE,
        content_kinds=("text",),
        allowed_children=("table", "incidence-table"),
    ),
    # ── Data tables — orientable + breakable, headingless (caption/label, no
    #    section heading); data comes from the integrated dataset, not text.
    "table": ComponentType(
        capabilities=_DATA_BLOCK, content_kinds=("table",), headingless=True,
        requires=("platform",),
    ),
    "incidence-table": ComponentType(
        capabilities=_DATA_BLOCK, content_kinds=("table",), headingless=True,
        requires=("platform",),
    ),
    # ── A summary section whose body is one table (it DOES have a heading).
    "bmd-summary": ComponentType(
        capabilities=_DATA_BLOCK, content_kinds=("table",), requires=("data_key",),
    ),
    # ── The genomics monolith — a heading-bearing section carrying narrative
    #    + tables + charts.  ADR-0003 Phase 4 decomposes its content_kinds
    #    into ordered, sub-addressable content items.
    "genomics-section": ComponentType(
        capabilities=_DATA_BLOCK, content_kinds=("text", "table", "chart"),
        requires=("data_key", "narrative_key"),
    ),
}

# Backward-compatible view: the historical node_type → capabilities map,
# now DERIVED from the catalog so there is a single source of truth.
CAPABILITIES_BY_TYPE: dict[str, NodeCapabilities] = {
    node_type: spec.capabilities for node_type, spec in COMPONENT_CATALOG.items()
}

# Fallback for a node_type not in the catalog: an inert component (no
# capabilities, no content, not headingless, no children).  This is what
# lets the template reference a type before it has an entry — the new type
# is simply inert until someone defines it above.
_DEFAULT_COMPONENT = ComponentType()
_DEFAULT_CAPABILITIES = _DEFAULT_COMPONENT.capabilities


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def component_for(node_type: str) -> ComponentType:
    """
    Return the full catalog entry for a document-semantic type, or the safe
    inert default for an unrecognized type.
    """
    return COMPONENT_CATALOG.get(node_type, _DEFAULT_COMPONENT)


def capabilities_for(node_type: str) -> NodeCapabilities:
    """
    Return the capabilities for a document-semantic type, or the safe
    all-False default for an unrecognized type.
    """
    return component_for(node_type).capabilities


def content_kinds_for(node_type: str) -> tuple[str, ...]:
    """Return the content kinds a component of this type may hold."""
    return component_for(node_type).content_kinds


def is_headingless(node_type: str) -> bool:
    """
    Whether this type renders with no heading of its own.  The instantiator
    uses this to derive heading level: level = 0 if headingless else depth.
    """
    return component_for(node_type).headingless


def allowed_children_for(node_type: str) -> tuple[str, ...]:
    """Return the node types that may nest directly under this type."""
    return component_for(node_type).allowed_children


def required_bindings_for(node_type: str) -> tuple[str, ...]:
    """
    Return the binding fields a node of this type must supply.  The template
    instantiator rejects a node that omits one of these at load time.
    """
    return component_for(node_type).requires


def is_allowed_child(parent_type: str, child_type: str) -> bool:
    """
    Whether `child_type` is permitted directly under `parent_type` per the
    catalog's containment grammar.  Used by the template instantiator to
    reject malformed nesting before it becomes a broken tree.
    """
    return child_type in allowed_children_for(parent_type)


def landscape_requested(
    node_type: str, node_id: str, orientations: dict | None
) -> bool:
    """
    Whether a node should render in landscape: the user flipped it to
    "landscape" AND its semantic type is orientable.

    Gating the user's per-id overlay on the per-type capability means a stale
    or invalid orientation flag (e.g. left over for a node type that is no
    longer orientable) is silently ignored — the catalog stays authoritative.
    Both renderers' tree walks call this so the gate condition lives in ONE
    place instead of being copy-pasted (and able to drift) between the HTML
    and LaTeX `_walk`s.

    Args:
        node_type:    the DocNode's node_type (capability lookup key).
        node_id:      the DocNode's id (overlay lookup key).
        orientations: the per-id overlay map {node_id: "landscape"}; may be
                      None/empty when the user has flipped nothing.
    """
    return (
        (orientations or {}).get(node_id) == "landscape"
        and capabilities_for(node_type).orientable
    )


def content_item_landscape_requested(
    component_id: str, item_id: str, orientations: dict | None
) -> bool:
    """
    Whether a specific content item INSIDE a component should render landscape
    (ADR-0003 Phase 4, sub-addressable orientation).

    The orientation overlay may be keyed by the composite (component_id,
    content_item_id) — encoded as the string "component_id::content_item_id" —
    so an individual table or chart inside a section flips independently of the
    whole section.  Plain node-id keys continue to orient an entire node via
    landscape_requested(); the two key shapes coexist in one overlay map.

    There is no per-type capability gate here: the caller (the genomics
    renderer) only consults this for content items its content plan marks
    orientable, so orientability is decided by the plan, not the node type.
    """
    return (orientations or {}).get(f"{component_id}::{item_id}") == "landscape"


def annotate_capabilities(nodes: list[dict]) -> list[dict]:
    """
    Walk a *serialized* tree (the list-of-dicts from serialize_tree) and add
    a "capabilities" dict to every node, derived from its "type".  Mutates
    in place and also returns the list for convenience.

    background_server calls this once on the serialized tree so the injected
    window.__DOCUMENT_TREE__ and the /api/document-tree response both carry
    capabilities — the frontend then reads node.capabilities directly
    instead of duplicating the type→capability mapping in JavaScript.
    """
    for node in nodes:
        node["capabilities"] = capabilities_for(node.get("type", "")).to_dict()
        children = node.get("children")
        if children:
            annotate_capabilities(children)
    return nodes
