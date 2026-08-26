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
        captionable      — whether this type carries a descriptive caption
                           paragraph (a table or figure — BITS <table-wrap> /
                           <fig> with <caption><p>).  ADR-0004 amendment (a).
                           Sections are NOT captionable (BITS <sec> has <title>
                           only).  The instantiator rejects `caption:` on a
                           non-captionable type.
        emits            — the ordered VOCABULARY ROLE TYPES a node of this type
                           produces as it renders (vocabulary.py).  This is the
                           granularity bridge: our structural key is the
                           node_type, but Word/descriptive-markup styles at the
                           PARAGRAPH level — one `narrative` node emits a heading
                           paragraph (role `section_heading`) AND body paragraphs
                           (role `body_para`), two different roles.  The handler
                           decides WHICH emitted paragraph is which role; this
                           field DECLARES the set so the mapping is inspectable
                           and validatable.  Names are vocabulary type names
                           (resolved against the active vocabulary), not catalog
                           node_types.  Empty = not yet crosswalked (falls back to
                           the legacy per-node styling).  ADR-0010.
    """
    capabilities: NodeCapabilities = field(default_factory=NodeCapabilities)
    content_kinds: tuple[str, ...] = ()
    headingless: bool = False
    allowed_children: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    captionable: bool = False
    emits: tuple[str, ...] = ()


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
# grows only when a genuinely new content kind appears.  `freeform` is authored
# content (latex/html/docx) carried ON the node, not produced by the pipeline.
CONTENT_KINDS: frozenset[str] = frozenset(
    {"text", "table", "chart", "image", "toc-entry", "freeform"}
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
        # The title page is the ORIGINAL role-emitting node (it already styles per
        # semantic role via the title_page sub-layer — the proof-of-pattern this
        # crosswalk generalizes).  It emits one paragraph per title-page role.
        emits=(
            "report_title", "report_type", "report_subtitle",
            "publication_date", "report_number", "issn",
            "publisher_name", "publication_institute", "publication_department",
        ),
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
            "bmd-summary", "genomics-section", "sample-counts-table",
            "freeform-page", "freeform-block", "page-break",
        ),
        emits=("section_heading",),
    ),
    # ── An explicit page break — a headingless, content-free structural marker
    #    the author drops between siblings to force a new page (the reference
    #    breaks before certain sections/appendices).  Distinct from a per-node
    #    user break override (which is keyed by node id in the orientation/break
    #    overlay): this is an AUTHORED, first-class node in the template.  It
    #    carries nothing — no heading, no data, no caption — so its capabilities
    #    are _FIXED (the break itself is not further breakable/orientable) and it
    #    requires no bindings.  Emitted as \clearpage (LaTeX) / a break-before
    #    marker (HTML), reusing the same mechanism freeform-page uses.
    "page-break": ComponentType(
        capabilities=_FIXED, content_kinds=(), headingless=True,
    ),
    # ── Prose sections — editable text, breakable; never landscape (running
    #    body text doesn't rotate).
    # front-matter emits SECTION-SPECIFIC roles derived from its data_key (see
    # FRONT_MATTER_ROLES_BY_DATA_KEY / front_matter_roles_for): the NTP template
    # styles the Abstract head differently from the Foreword title from the
    # Reference head, so a generic section_heading/body_para would lose that.  The
    # generic pair here is the FALLBACK for a data_key with no specific mapping.
    "front-matter": ComponentType(
        capabilities=_PROSE, content_kinds=("text",), requires=("data_key",),
        emits=("section_heading", "body_para"),
    ),
    "narrative": ComponentType(
        capabilities=_PROSE, content_kinds=("text",), requires=("data_key",),
        emits=("section_heading", "body_para"),
    ),
    # Appendices carry their own heading; a body is either a data-derived
    # roster (Appendix B, handled in the renderer) or authored freeform content
    # nested as a child (Appendices A/D/E/F — the reference's static prose /
    # rules tables / manifests).  freeform children are the sanctioned
    # authored-content channel, so allow them here.
    "appendix": ComponentType(
        capabilities=_PROSE, content_kinds=("text",),
        allowed_children=("freeform-block", "freeform-page"),
        emits=("appendix_heading", "body_para"),
    ),
    # ── Prose + child tables — the section's own content is the narrative
    #    text; the wide tables are separate child `table` nodes, each
    #    orientable on its own (prose stays portrait while a table flips).
    "narrative+tables": ComponentType(
        capabilities=_PROSE,
        content_kinds=("text",),
        allowed_children=("table", "incidence-table"),
        emits=("section_heading", "body_para"),
    ),
    # ── Data tables — orientable + breakable, headingless (caption/label, no
    #    section heading); data comes from the integrated dataset, not text.
    "table": ComponentType(
        capabilities=_DATA_BLOCK, content_kinds=("table",), headingless=True,
        requires=("platform",), captionable=True,
        emits=("table_title", "table_body_cell", "table_footnote"),
    ),
    "incidence-table": ComponentType(
        capabilities=_DATA_BLOCK, content_kinds=("table",), headingless=True,
        requires=("platform",), captionable=True,
        emits=("table_title", "table_body_cell", "table_footnote"),
    ),
    # ── The Methods sample-counts matrix — "Table 1. Final Sample Counts for
    #    BMD Analysis of the Transcriptomics Data" (organ×sex rows × dose
    #    columns).  A headingless, captionable data table like `table`, but its
    #    data comes from data[data_key] (the built {caption, headers, rows,
    #    footnotes} matrix) rather than a platform's apical_sections — so it
    #    requires a `data_key`, not a `platform`.  Orientable because the 11
    #    dose columns want landscape.
    "sample-counts-table": ComponentType(
        capabilities=_DATA_BLOCK, content_kinds=("table",), headingless=True,
        requires=("data_key",), captionable=True,
        emits=("table_title", "table_body_cell", "table_footnote"),
    ),
    # ── A figure — the pictorial peer of `table` (ADR-0012).  Data/content as an
    #    IMAGE (a lossless PNG), where `table` is data as a grid.  The KIND of
    #    picture is a `subtype` (FIGURE_SUBTYPES: chart | logo; photograph/diagram
    #    reserved): subtype=chart renders a data-derived plot via chart_style;
    #    subtype=logo places a supplied branding asset.  Headingless + captionable
    #    + orientable like a data table; emits the figure-furniture roles (caption/
    #    title/source/note/alt-text + the graphic paragraph).  The graphic role is
    #    subtype-dependent (fig_graphic vs logo_graphic), so it is NOT in `emits`
    #    here — the handler selects it.  Its plot-internal styling is chart_style's
    #    job, deliberately NOT folded into the paragraph vocabulary (ADR-0009).
    "figure": ComponentType(
        capabilities=_DATA_BLOCK, content_kinds=("chart", "image"), headingless=True,
        captionable=True,
        emits=("fig_title", "fig_caption", "fig_source", "fig_note", "fig_alt_text"),
    ),
    # ── A summary section whose body is one table (it DOES have a heading).
    #    Captionable because its body is the table whose <caption><p> is the
    #    descriptive paragraph (BITS-wise, the <table-wrap> carries the caption).
    "bmd-summary": ComponentType(
        capabilities=_DATA_BLOCK, content_kinds=("table",), requires=("data_key",),
        captionable=True,
        emits=("section_heading", "table_title", "table_body_cell", "table_footnote"),
    ),
    # ── The genomics monolith — a heading-bearing section carrying narrative
    #    + tables + charts.  ADR-0003 Phase 4 decomposes its content_kinds
    #    into ordered, sub-addressable content items.
    "genomics-section": ComponentType(
        capabilities=_DATA_BLOCK, content_kinds=("text", "table", "chart"),
        requires=("data_key", "narrative_key"),
        emits=("section_heading", "body_para", "table_title",
               "table_body_cell", "fig_caption"),
    ),
    # ── Freeform AUTHORED content — the only types whose content lives ON the
    #    node (content/content_file/representation) rather than in the pipeline
    #    data dict.  Held in one of a small set of representations (latex / html
    #    / docx); resolved to per-surface markup at instantiation.  The
    #    content-field validation is custom (see document_template.
    #    _validate_freeform_entry), so `requires` stays empty.  Not captionable
    #    (the authored content carries its own structure), not orientable.
    #    freeform-page forces its own page (the renderer emits a page break);
    #    freeform-block is an inline insert with no forced break.
    "freeform-page": ComponentType(
        capabilities=_STRUCTURAL, content_kinds=("freeform",),
    ),
    "freeform-block": ComponentType(
        capabilities=_STRUCTURAL, content_kinds=("freeform",),
    ),
}

# Fallback for a node_type not in the catalog: an inert component (no
# capabilities, no content, not headingless, no children).  This is what
# lets the template reference a type before it has an entry — the new type
# is simply inert until someone defines it above.
_DEFAULT_COMPONENT = ComponentType()


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


def emits_for(node_type: str) -> tuple[str, ...]:
    """Return the vocabulary ROLE TYPES a node of this type emits (the crosswalk
    from our structural node_type to the paragraph-granular semantic roles the
    surfaces style).  Empty when the type is not yet crosswalked — the renderer
    then falls back to the legacy per-node styling.  See ComponentType.emits."""
    return component_for(node_type).emits


# The front-matter DATA_KEY → (heading role, body role) crosswalk.  Each NTP
# front-matter section is a distinct semantic type in the template's style family
# (the Abstract head is 1-15_Abstract_Head, the Foreword title 1-21_Foreword_Title,
# etc.), so a front-matter node styles its heading + body by roles DERIVED FROM
# ITS data_key — not the generic section_heading/body_para.  Deriving from
# data_key (rather than a new authored field) means existing templates need no
# editing.  A data_key absent here falls back to the generic pair, so a new
# front-matter section renders (generically) until it gains a mapping.  The role
# names resolve against the active vocabulary (vocab/ntp-report.yaml).
FRONT_MATTER_ROLES_BY_DATA_KEY: dict[str, tuple[str, str]] = {
    "foreword":            ("foreword_title", "foreword_text"),
    "abstract":            ("abstract_head", "abstract"),
    "about_report":        ("about_this_report_head", "frontmatter_para"),
    "peer_review":         ("peer_review_desc_head", "peer_review_desc_text"),
    "acknowledgments":     ("acknowledgement_headfront", "acknowledgement"),
    "publication_details": ("frontmatter_head1", "frontmatter_para"),
    "references":          ("reference_head", "references"),
}

# The generic fallback pair (matches the front-matter catalog `emits`).
_FRONT_MATTER_GENERIC_ROLES = ("section_heading", "body_para")


def front_matter_roles_for(data_key: str | None) -> tuple[str, str]:
    """Return the (heading_role, body_role) a front-matter node emits, derived
    from its ``data_key``.  Falls back to the generic section_heading/body_para
    pair for an unmapped/absent data_key so any front-matter section still
    renders.  The renderer applies the heading role to the section heading and
    the body role to each prose paragraph."""
    return FRONT_MATTER_ROLES_BY_DATA_KEY.get(data_key or "", _FRONT_MATTER_GENERIC_ROLES)


# The `figure` node's semantic subtype — the KIND of pictorial content (ADR-0012).
# Closed but extensible; only `chart` and `logo` are implemented now (the real
# cases: data-derived plots + cover/title branding).  photograph/diagram/... are
# reserved: add here + give them an artifact source + a graphic role when a report
# needs one.  A subtype absent here is a template authoring error (rejected at load).
FIGURE_SUBTYPES = frozenset({"chart", "logo"})

# Which figure-furniture GRAPHIC role a subtype's image paragraph uses.  A logo is
# branding (1-26_Logo_Graphic); everything else is a content figure graphic
# (0-32a_Fig_Graphic).  The image paragraph's role is therefore subtype-dependent
# and chosen by the handler, not fixed in the catalog `emits`.
_FIGURE_GRAPHIC_ROLE = {"logo": "logo_graphic"}
_FIGURE_GRAPHIC_DEFAULT = "fig_graphic"


def figure_graphic_role(subtype: str | None) -> str:
    """The graphic-paragraph role for a figure of this subtype: `logo_graphic`
    for a logo, `fig_graphic` for a chart / content image."""
    return _FIGURE_GRAPHIC_ROLE.get(subtype or "", _FIGURE_GRAPHIC_DEFAULT)


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


def is_captionable(node_type: str) -> bool:
    """
    Whether this type carries a descriptive caption paragraph (a table or
    figure).  Used by the instantiator to gate the `caption:` field — sections
    have only <title>, not <caption><p> (ADR-0004 amendment a).
    """
    return component_for(node_type).captionable


def is_allowed_child(parent_type: str, child_type: str) -> bool:
    """
    Whether `child_type` is permitted directly under `parent_type` per the
    catalog's containment grammar.  Used by the template instantiator to
    reject malformed nesting before it becomes a broken tree.
    """
    return child_type in allowed_children_for(parent_type)


def landscape_requested(
    node_type: str,
    node_id: str,
    orientations: dict | None,
    default: str | None = None,
) -> bool:
    """
    Whether a node should render in landscape, resolving the EFFECTIVE
    orientation (ADR-0003 Amendment 1):

        effective = per-session override (if set) else the template `default`,
        and the result is landscape only if effective == "landscape" AND the
        type is orientable.

    Precedence is override > template default > portrait.  Gating on the per-
    type capability means a stale/invalid setting for a no-longer-orientable
    type is silently ignored — the catalog stays authoritative.  Both renderers'
    tree walks AND both export paths call this, so "is this landscape?" is
    answered in exactly ONE place.

    Args:
        node_type:    the DocNode's node_type (capability lookup key).
        node_id:      the DocNode's id (override lookup key).
        orientations: the per-id override map {node_id: "landscape"|"portrait"};
                      may be None/empty when the user has overridden nothing.
        default:      the template-authored default orientation for this node
                      (DocNode.orientation), used when there is no override.
    """
    if not capabilities_for(node_type).orientable:
        return False
    override = (orientations or {}).get(node_id)
    effective = override if override is not None else default
    return effective == "landscape"


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


def content_item_break_requested(
    component_id: str, item_id: str, breaks: dict | None, edge: str = "before",
) -> bool:
    """
    Whether a page break should be placed before/after a specific content item
    INSIDE a component (ADR-0003 Part B Feature 2, sub-addressable page breaks).

    The twin of content_item_landscape_requested: the break overlay is keyed by
    the SAME composite "component_id::content_item_id" string, so an individual
    table or chart inside a section can start (or end) its own page independently
    of the whole node. Node-level breaks stay on the separate, established
    `styles.instances.<id>.break_before` channel (resolve_layout_style) — this
    resolver is ONLY for the item grain that channel cannot reach.

    The overlay value is a mapping ``{"before": bool, "after": bool}``; `edge`
    selects which. There is no per-type capability gate (like the orientation
    twin): the caller consults this only for items its content plan marks
    `breakable`, so breakability is decided by the plan, not the node type.
    """
    entry = (breaks or {}).get(f"{component_id}::{item_id}")
    if not isinstance(entry, dict):
        return False
    return entry.get(edge) is True


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
