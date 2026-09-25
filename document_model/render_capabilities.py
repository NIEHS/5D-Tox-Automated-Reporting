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
    e.g. the cover, a bare data table),
  - its *role* — the document role it plays, drawn from a closed BITS 2.x
    profile (ROLE_PROFILE).  Containment (what may nest under what) is decided
    by ROLE ALONE, and the per-role allowed children are copied from the BITS
    content models, never invented here (ADR-0025), and
  - its *bindings* — how its content is produced (BINDINGS: container /
    programmatic / llm / authored / derived).  The first listed binding is the
    preset's default; a template entry may pick another listed one.

Two orthogonal axes (ADR-0025)
------------------------------
A catalog `type` is a PRESET: a named (role, binding) pair plus the render
facts (capabilities, emitted paragraph roles, required fields).  The role says
WHERE a node may sit and how it lays out; the binding says WHERE ITS CONTENT
COMES FROM and what the workflow tracks about it.  Keeping the two apart is
what lets an authored table sit in an appendix, or a figure sit inside a
sub-section, without a new type being invented for each combination.

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
the instantiator validates the nesting against the role profile.

Decoupling contract
--------------------
  - This module imports NOTHING from document_tree.  It is keyed by
    node_type *strings*, so the dependency points one way (consumers →
    here) and the template never depends on the rendering layer.
  - Consumers: latex_generator and html_generator gate their per-node
    behaviour on capabilities; background_server annotates the serialized
    tree so the frontend reads capabilities instead of hardcoding its own
    copy of the mapping; the instantiator (ADR-0003 Phase 2) reads
    `headingless` to derive heading level and the role profile (via
    allowed_children_for / is_allowed_child) to validate a template.
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
class RoleSpec:
    """
    One document ROLE in the BITS profile (ADR-0025 §2): the structural facts a
    node inherits from the BITS element it projects to.

    Fields:
        bits_element     — the BITS 2.x element this role maps to on export
                           (None for the one presentation-only marker, page-break,
                           which has no XML counterpart).
        allowed_children — the ROLES that may nest directly under this role.
                           Copied from the BITS content model of `bits_element`
                           (e.g. <sec> and <app> hold flow blocks then <sec>*);
                           this table is the ONLY place containment is written.
    """
    bits_element: str | None
    allowed_children: tuple[str, ...] = ()


# The BITS profile — every role a node may play, keyed by role name.  Allowed
# children come from the BITS 2.1 tag library (verified 2026-09-25):
#   <front-matter-part> → <named-book-part-body> → <sec>*  (+ flow blocks)
#   <sec>  → (flow blocks)*, <sec>*      flow blocks = table-wrap | fig |
#   <app>  → (flow blocks)*, <sec>*                    supplementary-material
#   <toc>, <table-wrap>, <fig>, <supplementary-material> → leaves for our purposes
# Two deliberate extensions beyond base BITS (ADR-0025 §7): a generated `toc`
# may sit first inside an `app` (the reference's per-appendix mini-ToCs; the
# BITS emitter promotes such an appendix to a book-part or drops the derived
# toc), and `page-break` — a print directive with no XML meaning — is tolerated
# anywhere a flow block is.
ROLE_PROFILE: dict[str, RoleSpec] = {
    # <book-meta> material: the branded cover and the inner title page.
    "book-meta": RoleSpec("book-meta"),
    # A named front-matter section (Foreword, About This Report, Abstract …).
    # May hold sub-sections — the reference nests Authors / Contributors under
    # About This Report.
    "front-matter-part": RoleSpec(
        "front-matter-part", ("sec", "table-wrap", "fig", "page-break"),
    ),
    # A generated list: contents, list of tables, list of figures.
    "toc": RoleSpec("toc"),
    # THE recursive container: any titled section at any depth.
    "sec": RoleSpec(
        "sec", ("sec", "table-wrap", "fig", "supplementary-material", "page-break"),
    ),
    # A captioned table, whatever produced it.
    "table-wrap": RoleSpec("table-wrap"),
    # A captioned figure, whatever produced it.
    "fig": RoleSpec("fig"),
    # One supplied data file (title + file name) — the reference's Appendix F.
    "supplementary-material": RoleSpec("supplementary-material"),
    # An appendix: a structured document part in its own right.
    "app": RoleSpec(
        "app", ("toc", "sec", "table-wrap", "fig", "supplementary-material", "page-break"),
    ),
    # Presentation-only marker; no BITS element.
    "page-break": RoleSpec(None),
}

# The closed binding vocabulary — HOW a node's content is produced (ADR-0025
# §3).  It is the section catalog's `kind` vocabulary promoted to a declared
# node attribute, plus `container` for nodes with no content of their own.
#   container    — no own content; its children carry it.
#   programmatic — built from integrated.json by code (a platform table, the
#                  sample-counts matrix, the body-weight narrative).
#   llm          — generated by a narrative generator; reviewable/approvable.
#   authored     — supplied content (ADR-0018): a content_file / inline content,
#                  a supplied figure, a supplied table.
#   derived      — computed from the tree or the session's artifacts; never
#                  authored or approved (a ToC, a list of tables, labels).
BINDINGS: frozenset[str] = frozenset(
    {"container", "programmatic", "llm", "authored", "derived"}
)


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
        role             — the document role this preset plays (a ROLE_PROFILE
                           key).  Containment is decided by role: this type may
                           nest under a parent iff its role is in the parent
                           role's allowed_children (see allowed_children_for).
        bindings         — the content bindings this preset admits (BINDINGS
                           members); bindings[0] is the DEFAULT a template entry
                           gets when it names none.  A preset whose content
                           source varies by data_key (narrative, front-matter)
                           lists every binding it can honestly carry.
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
    role: str = "sec"
    bindings: tuple[str, ...] = ("container",)
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

# The catalog: node_type → ComponentType.  Each entry is a PRESET for a
# (role, binding) pair (ADR-0025 §4); this is the single place that grows when
# the template gains a node type.  `headingless` mirrors today's DOCUMENT_TREE
# (Phase 2 verifies the match); `content_kinds` describes what each component
# carries; containment is NOT written here — it follows from `role` via
# ROLE_PROFILE.
COMPONENT_CATALOG: dict[str, ComponentType] = {
    # ── Fixed front pages — auto-laid-out, headingless, nothing to configure.
    "cover": ComponentType(
        capabilities=_FIXED, content_kinds=(), headingless=True,
        role="book-meta", bindings=("derived",),
    ),
    "title-page": ComponentType(
        capabilities=_FIXED, content_kinds=(), headingless=True,
        role="book-meta", bindings=("derived",),
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
        role="toc", bindings=("derived",),
    ),
    # ── Auto-generated list of figures — the figure twin of tables-list (the
    #    reference's appendices C and D open with a "Figures" list).  Same role
    #    (BITS <toc>, distinguished by content-type); entries come from the
    #    numbered figure nodes.
    "figures-list": ComponentType(
        capabilities=_STRUCTURAL, content_kinds=("toc-entry",),
        role="toc", bindings=("derived",),
    ),
    # ── Generated Table of Contents — a front-matter component (distinct from
    #    the navigation panel).  It SELF-HEADS: LaTeX's \tableofcontents emits
    #    its own unnumbered "Contents" heading and the HTML renderer emits its
    #    own, so the generic heading machinery is skipped — hence headingless
    #    (level 0).  Generated from the tree's section order.
    "toc": ComponentType(
        capabilities=_STRUCTURAL, content_kinds=("toc-entry",), headingless=True,
        role="toc", bindings=("derived",),
    ),
    # ── A heading with no own content; its child NODES carry the content.
    #    This is the recursive structural container (it may nest itself).
    # A plain container by default; a heading that carries a section's data_key
    # (Materials and Methods, whose subsections are the LLM-generated prose) may
    # declare the producer of that content.
    "heading-only": ComponentType(
        capabilities=_STRUCTURAL,
        content_kinds=(),
        role="sec", bindings=("container", "llm", "programmatic"),
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
        role="page-break", bindings=("derived",),
    ),
    # ── Prose sections — editable text, breakable; never landscape (running
    #    body text doesn't rotate).
    # front-matter emits SECTION-SPECIFIC roles derived from its data_key (see
    # FRONT_MATTER_ROLES_BY_DATA_KEY / front_matter_roles_for): the NTP template
    # styles the Abstract head differently from the Foreword title from the
    # Reference head, so a generic section_heading/body_para would lose that.  The
    # generic pair here is the FALLBACK for a data_key with no specific mapping.
    # Its content source varies by data_key: boilerplate/provisioned parts
    # (foreword, about_report, peer_review, publication_details, acknowledgments)
    # are AUTHORED; the abstract is LLM-generated.  Authored is the default; an
    # entry may declare `binding: llm`.
    "front-matter": ComponentType(
        capabilities=_PROSE, content_kinds=("text",), requires=("data_key",),
        role="front-matter-part", bindings=("authored", "llm", "programmatic"),
        emits=("section_heading", "body_para"),
    ),
    # A titled prose section.  Background / Methods / Summary are LLM-generated
    # (the default); References is DERIVED from the citation inventory; a
    # programmatic narrative (built from data by code) is also expressible.
    "narrative": ComponentType(
        capabilities=_PROSE, content_kinds=("text",), requires=("data_key",),
        role="sec", bindings=("llm", "programmatic", "derived"),
        emits=("section_heading", "body_para"),
    ),
    # Appendices carry their own heading; a body is either a data-derived
    # roster (Appendix B, handled in the renderer) or authored freeform content
    # nested as a child (Appendices A/D/E/F — the reference's static prose /
    # rules tables / manifests).  freeform children are the sanctioned
    # authored-content channel, so allow them here.
    # Its role is BITS <app>: a structured document part that may hold sections,
    # tables, figures, supplied files and a generated mini-ToC (ADR-0025) — no
    # longer restricted to freeform children.
    "appendix": ComponentType(
        capabilities=_PROSE, content_kinds=("text",),
        role="app", bindings=("container",),
        emits=("appendix_heading", "body_para"),
    ),
    # ── Prose + child tables — the section's own content is the narrative
    #    text; the wide tables are separate child `table` nodes, each
    #    orientable on its own (prose stays portrait while a table flips).
    "narrative+tables": ComponentType(
        capabilities=_PROSE,
        content_kinds=("text",),
        # The group narratives (animal condition, clinical pathology, internal
        # dose) are built from the tables by code — programmatic, not LLM.
        role="sec", bindings=("programmatic", "llm"),
        emits=("section_heading", "body_para"),
    ),
    # ── Data tables — orientable + breakable, headingless (caption/label, no
    #    section heading); data comes from the integrated dataset, not text.
    # `platform` is required by the PROGRAMMATIC-APICAL binding these presets
    # carry, not by the table-wrap role (an authored table needs none).
    "table": ComponentType(
        capabilities=_DATA_BLOCK, content_kinds=("table",), headingless=True,
        role="table-wrap", bindings=("programmatic",),
        requires=("platform",), captionable=True,
        emits=("table_title", "table_body_cell", "table_footnote"),
    ),
    "incidence-table": ComponentType(
        capabilities=_DATA_BLOCK, content_kinds=("table",), headingless=True,
        role="table-wrap", bindings=("programmatic",),
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
        role="table-wrap", bindings=("programmatic",),
        requires=("data_key",), captionable=True,
        emits=("table_title", "table_body_cell", "table_footnote"),
    ),
    # ── A generic programmatic matrix table: the same {caption, headers, rows,
    #    footnotes} shape at data[data_key] that sample-counts-table renders, but
    #    for ANY pipeline-built table (an appendix's animal roster, an eFDR
    #    false-positive count).  Same emitters; a distinct preset so the
    #    sample-counts name stops doing double duty (ADR-0025 §4).
    "data-table": ComponentType(
        capabilities=_DATA_BLOCK, content_kinds=("table",), headingless=True,
        role="table-wrap", bindings=("programmatic",),
        requires=("data_key",), captionable=True,
        emits=("table_title", "table_body_cell", "table_footnote"),
    ),
    # ── An AUTHORED table: caption + supplied table markup (content /
    #    content_file, validated like the freeform types).  The reference's
    #    Appendix D model-rules table.  Captioned and numbered like any
    #    table-wrap; the body is the author's own markup.
    "authored-table": ComponentType(
        capabilities=_DATA_BLOCK, content_kinds=("table", "freeform"), headingless=True,
        role="table-wrap", bindings=("authored",),
        captionable=True,
        emits=("table_title",),
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
    # Its binding follows the subtype (ADR-0023): `chart` is programmatic (a
    # data figure); `diagram` / `photograph` / `logo` are authored (supplied).
    "figure": ComponentType(
        capabilities=_DATA_BLOCK, content_kinds=("chart", "image"), headingless=True,
        role="fig", bindings=("programmatic", "authored"),
        captionable=True,
        emits=("fig_title", "fig_caption", "fig_source", "fig_note", "fig_alt_text"),
    ),
    # ── A summary section whose body is one table (it DOES have a heading).
    #    Captionable because its body is the table whose <caption><p> is the
    #    descriptive paragraph (BITS-wise, the <table-wrap> carries the caption).
    # The workflow classifies the BMD summary as DERIVED (a deterministic
    # reduction of the apical results that also carries an LLM paragraph — one
    # section, still approvable); that stays its default so the Sections screen
    # keeps treating it as it always has (section_catalog).
    "bmd-summary": ComponentType(
        capabilities=_DATA_BLOCK, content_kinds=("table",), requires=("data_key",),
        role="sec", bindings=("derived", "programmatic"),
        captionable=True,
        emits=("section_heading", "table_title", "table_body_cell", "table_footnote"),
    ),
    # ── The genomics monolith — a heading-bearing section carrying narrative
    #    + tables + charts.  ADR-0003 Phase 4 decomposes its content_kinds
    #    into ordered, sub-addressable content items.
    "genomics-section": ComponentType(
        capabilities=_DATA_BLOCK, content_kinds=("text", "table", "chart"),
        role="sec", bindings=("llm",),
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
    #    Both are role `sec` (a titled authored section that may itself hold
    #    sub-sections, tables and figures — the reference's appendix prose).
    "freeform-page": ComponentType(
        capabilities=_STRUCTURAL, content_kinds=("freeform",),
        role="sec", bindings=("authored",),
    ),
    "freeform-block": ComponentType(
        capabilities=_STRUCTURAL, content_kinds=("freeform",),
        role="sec", bindings=("authored",),
    ),
    # ── One supplied data file: a title paragraph plus the file name (the
    #    reference's Appendix F lists 55 of them under four headings).  Role
    #    BITS <supplementary-material>; `content_file` names the file.  Listed
    #    as authored: the entry is written by hand; a session-derived manifest
    #    (binding `derived`) is the intended follow-on.
    "supplementary-material": ComponentType(
        capabilities=_FIXED, content_kinds=(), headingless=True,
        role="supplementary-material", bindings=("authored", "derived"),
        emits=("supplementary_material_title", "supplementary_material_filename"),
    ),
}

# Fallback for a node_type not in the catalog: an inert component (no
# capabilities, no content, not headingless, no children).  This is what
# lets the template reference a type before it has an entry — the new type
# is simply inert until someone defines it above.
_DEFAULT_COMPONENT = ComponentType()

# Fallback for a role not in the profile: an inert leaf that nothing may nest
# under (and that, absent from every allowed_children tuple, nests nowhere).
_DEFAULT_ROLE = RoleSpec(None)


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
FIGURE_SUBTYPES = frozenset({"chart", "logo", "diagram", "photograph"})

# Subtypes whose image is SUPPLIED (ADR-0023 authored-figures): the template
# names the image file in `content_file`.  `chart` is the data-figure subtype
# (programmatic, from a chart payload at data[data_key]); `logo` is a fixed
# branding asset the renderer locates itself.  The image channel for diagram /
# photograph is validated at load (the file name is required) and wired to the
# emitters in ADR-0025 migration phase 3 — until then they render the visible
# "[Figure pending]" note like any figure without a payload.
AUTHORED_FIGURE_SUBTYPES = frozenset({"diagram", "photograph"})

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


def role_for(node_type: str) -> str:
    """The document role (a ROLE_PROFILE key) a catalog type plays."""
    return component_for(node_type).role


def role_spec_for(role: str) -> RoleSpec:
    """The profile entry for a role; an unknown role is an inert leaf."""
    return ROLE_PROFILE.get(role, _DEFAULT_ROLE)


def bindings_for(node_type: str) -> tuple[str, ...]:
    """The content bindings a catalog type admits (bindings[0] is the default)."""
    return component_for(node_type).bindings


def default_binding_for(node_type: str) -> str:
    """The binding a template entry of this type gets when it names none."""
    return bindings_for(node_type)[0]


def preset_for(role: str, binding: str) -> str | None:
    """
    The canonical catalog type for an explicit (role, binding) pair — the first
    preset (in catalog order) whose role matches and whose bindings include
    `binding`; None when no preset exists for the pair.  This is how a template
    entry that states `role:` + `binding:` instead of `type:` resolves.
    """
    for name, comp in COMPONENT_CATALOG.items():
        if comp.role == role and binding in comp.bindings:
            return name
    return None


def allowed_children_for(node_type: str) -> tuple[str, ...]:
    """
    Return the node types that may nest directly under this type — DERIVED
    from the role profile: every catalog type whose role is an allowed child
    role of this type's role (in catalog order).  Nothing is written per type.
    """
    child_roles = role_spec_for(role_for(node_type)).allowed_children
    return tuple(
        name for name, comp in COMPONENT_CATALOG.items() if comp.role in child_roles
    )


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
    Whether `child_type` is permitted directly under `parent_type` — decided by
    ROLE alone (ADR-0025 §1): the child's role must be in the parent role's
    allowed children.  Used by the template instantiator to reject malformed
    nesting before it becomes a broken tree.
    """
    parent_role = role_for(parent_type)
    return role_for(child_type) in role_spec_for(parent_role).allowed_children


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
