"""
render_common.py — format-agnostic EXTRACT step shared by the HTML and LaTeX
renderers (ADR-0006).

The two renderers (html_generator.py, latex_generator.py) walk the same
canonical DocNode tree and, for most node types, make the *same decision* about
WHAT to render — they differ only in the markup they EMIT.  Historically that
shared decision logic was copy-pasted into both files, which let them drift
(the reason tests/unit/test_renderer_dispatch_parity.py exists).  ADR-0006
splits each handler into:

  * EXTRACT (here) — a pure function that inspects the node + report data and
    returns a small, markup-free description of what should be rendered;
  * EMIT (in each renderer) — turns that description into HTML or LaTeX,
    applying its own escaping and wrapping.

This module is the extract half.  It deliberately produces NO markup and knows
nothing about HTML or LaTeX — everything here is "which content, in which
order," never "what tags."  Step 2 of ADR-0006 migrates the three provably
identical handlers (front-matter, labeled-sections, narrative) onto it; later
steps move the table handlers.

A note on what stays in the emitters: the "rendered body came out empty, so
show a [Section pending] placeholder" decision is intentionally NOT made here.
Emptiness is format-dependent — e.g. a single empty-string paragraph renders as
"<p></p>" in HTML (non-empty) but "" in LaTeX (empty, → pending).  Preserving
that pre-existing per-format behavior means the pending fallback stays in each
emitter; this module only chooses the content SOURCE.
"""

from __future__ import annotations

# DocNode is the node SHAPE (document_node.py), imported directly rather than
# via document_tree to keep this leaf module free of the tree/template import
# chain — the renderers already depend on both, but nothing here needs the
# instantiated DOCUMENT_TREE, only the node type for hints.
from dataclasses import dataclass, field

from document_node import DocNode
# Render-time numeric re-rounding for mean ± SE cells — already the shared
# formatter both renderers used; the apical extractor applies it once here so
# both surfaces get identical cell text.
from table_builder_common import format_mean_se_display, format_display_number


# ---------------------------------------------------------------------------
# Type definitions — markup-free descriptions handed to the emitters
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FrontMatterPlan:
    """
    What a front-matter / narrative node should render, decided once and
    consumed by either renderer.

    Fields:
        level:         heading level (passed straight to the renderer's
                       _heading); 0 means "no heading."
        title:         heading text (raw, unescaped — the emitter escapes it).
        kind:          which body source won the precedence:
                         "labeled"    → render labeled_parts as a structured
                                        abstract (run-in bold labels);
                         "paragraphs" → render paragraphs as a flat prose list;
                         "none"       → no content source; the emitter's
                                        empty-body check will show "pending."
        labeled_parts: [(label, text)] for kind == "labeled"; label may be ""
                       (text is already stripped and guaranteed non-empty).
        paragraphs:    list of raw paragraph strings for kind == "paragraphs".
    """
    level: int
    title: str
    kind: str
    labeled_parts: list[tuple[str, str]] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Extractors — pure, markup-free
# ---------------------------------------------------------------------------

def has_paragraph_content(paragraphs) -> bool:
    """
    Does this paragraph list carry any real content?

    True iff at least one entry has non-whitespace text.  This is the
    "content present / absent" decision the IR owns (ADR-0006 Amendment 1):
    before, each emitter inferred it from format-dependent emptiness — HTML
    rendered a single empty-string paragraph as "<p></p>" (treated as present)
    while LaTeX rendered it as "" (treated as absent, → pending), so the two
    surfaces silently disagreed about whether a section had content.  Deciding
    it once here makes both projections agree.
    """
    return any((p or "").strip() for p in (paragraphs or []))


def labeled_section_parts(sections) -> list[tuple[str, str]]:
    """
    Normalise a structured-abstract "sections" list into [(label, text)],
    dropping anything that carries no text.

    This is the iterate-and-filter logic that both renderers' old
    _render_labeled_sections shared verbatim: skip non-dict entries, strip the
    text and skip it when empty (so a Methods abstract with no MethodsContext
    contributes nothing), strip the label (which may legitimately be empty for
    an unlabeled paragraph).  Only the per-part MARKUP differed between
    renderers, and that stays in each emitter.

    Args:
        sections: the raw list from content["sections"] (may be None, or
            contain junk — both are tolerated).

    Returns:
        A list of (label, text) tuples.  Both strings are stripped; text is
        guaranteed truthy; label may be "".  Empty list when nothing qualifies.
    """
    parts: list[tuple[str, str]] = []
    for sec in sections or []:
        if not isinstance(sec, dict):
            continue
        text = (sec.get("text") or "").strip()
        if not text:
            continue
        label = (sec.get("label") or "").strip()
        parts.append((label, text))
    return parts


def front_matter_plan(node: DocNode, data: dict) -> FrontMatterPlan:
    """
    Decide which body a front-matter / narrative node renders, format-agnostically.

    Reproduces the precedence both renderers' _render_front_matter shared:

      1. The content lives at data[node.data_key] and must be a dict.
      2. If it carries labeled sections with any non-empty text, that wins
         (the structured-abstract path: Background / Methods / Results / Summary).
      3. Otherwise fall back to the flat "paragraphs" list.
      4. If neither yields content, kind is "none" and the emitter shows a
         pending placeholder.

    Note step 2's "any non-empty text" gate matches the old behavior exactly:
    the previous code rendered labeled sections, and only if that produced an
    EMPTY string fell through to paragraphs.  Labeled-section emptiness depends
    solely on whether any section has text — a format-agnostic condition — so
    resolving it here (via labeled_section_parts) is faithful to both renderers.

    Args:
        node: the DocNode being rendered (uses .data_key, .level, .title).
        data: the full report data dict.

    Returns:
        A FrontMatterPlan describing the chosen content source.
    """
    content = data.get(node.data_key) if node.data_key else None
    if isinstance(content, dict):
        parts = labeled_section_parts(content.get("sections"))
        if parts:
            return FrontMatterPlan(node.level, node.title, "labeled", labeled_parts=parts)
        paragraphs = content.get("paragraphs", []) or []
        # has_paragraph_content (not bare truthiness): a list of only empty
        # strings carries no content and must resolve to "none" on BOTH
        # surfaces, not "<p></p>" on one and pending on the other.
        if has_paragraph_content(paragraphs):
            return FrontMatterPlan(node.level, node.title, "paragraphs", paragraphs=paragraphs)
    return FrontMatterPlan(node.level, node.title, "none")


# ---------------------------------------------------------------------------
# Table extractors (ADR-0006 step 4) — shared lookup + markup-free plans
# ---------------------------------------------------------------------------
# The table handlers historically duplicated their section lookup, caption
# building, and row assembly across both renderers, differing only in the
# markup (and in dose-label formatting, which genuinely differs: LaTeX uses a
# "~" non-breaking space and escapes the unit, HTML uses a plain space — so the
# emitters keep their own _format_dose_label and the plans carry RAW dose values
# rather than pre-formatted column labels).

def find_apical_section(node: DocNode, data: dict) -> dict | None:
    """
    Locate the apical_sections entry whose platform matches this table node.

    apical_sections is the flat list marshal_export_data produces from session
    state; each entry has a "platform" key ("Body Weight", "Clinical
    Chemistry", ...) matched against node.platform.  A title-based fallback
    handles the legacy scaffold form where some entries carry no platform.

    Returns the matching dict, or None when nothing matches (the caller then
    emits a placeholder).
    """
    sections = data.get("apical_sections", []) or []
    for sec in sections:
        if sec.get("platform") and sec["platform"] == node.platform:
            return sec
    # Fallback: title-based match against the section's title key.
    for sec in sections:
        if sec.get("title") and node.platform in sec.get("title", ""):
            return sec
    return None


def table_caption(node: DocNode, base_caption: str) -> str:
    """
    Build the plain-text table caption, prefixed with "Table N. " from the
    auto-assigned table_number (document tree position).

    Strips leftover Typst-era placeholder tokens ("{sex}", "{compound}").  Per
    ADR-0004 amendment (a) the node's own authored `caption` wins over the
    data-overlay base caption, falling back to it when unset.

    Returns plain text — escaping (HTML) or non-escaping (the LaTeX niehstable
    env consumes it raw) is the emitter's concern, which is why this is shared.
    """
    cleaned = (node.caption or base_caption or "")
    cleaned = cleaned.replace("{sex}", "Male and Female").replace("{compound}", "")
    cleaned = cleaned.strip()
    if node.table_number is not None:
        return f"Table {node.table_number}. {cleaned}" if cleaned else f"Table {node.table_number}"
    return cleaned


@dataclass(frozen=True)
class IncidenceTablePlan:
    """
    Markup-free description of a clinical-observations incidence table (one row
    per observation, one column per dose group).

    Fields:
        node_id:   stable node id (LaTeX keys its niehstable env on it).
        caption:   plain-text "Table N. ..." caption (see table_caption).
        doses:     RAW dose values; each emitter formats its own column labels
                   (HTML "0 mg/kg" vs LaTeX "0~mg/kg") via its _format_dose_label.
        dose_unit: unit string for those labels.
        rows:      one cell-string list per observation, already padded to
                   1 + len(doses) columns (missing counts filled with "0").
        footnotes: raw footnote dicts; the emitter renders the markup.
    """
    node_id: str
    caption: str
    doses: list
    dose_unit: str
    rows: list[list[str]]
    footnotes: list


def incidence_table_plan(node: DocNode, data: dict) -> IncidenceTablePlan | None:
    """
    EXTRACT for the incidence table: resolve the section, assemble padded cell
    rows, and build the caption — all format-agnostic.

    Returns None when the section is missing or carries no rows; the emitter
    turns that into its placeholder (preserving both renderers' old behavior of
    emitting a placeholder in either case).
    """
    section = find_apical_section(node, data)
    if not section:
        return None
    rows_src = section.get("incidence_rows", []) or section.get("rows", []) or []
    if not rows_src:
        return None

    doses = section.get("doses", []) or []
    dose_unit = section.get("dose_unit", "mg/kg")
    # Column count = the Observation label column plus one per dose group; rows
    # are padded to this so a short counts list still fills every dose column.
    ncols = 1 + len(doses)

    rows: list[list[str]] = []
    for row in rows_src:
        label = row.get("observation") or row.get("label") or ""
        counts = row.get("counts") or row.get("values") or []
        cells = [str(label), *[str(c) for c in counts]]
        while len(cells) < ncols:
            cells.append("0")
        rows.append(cells)

    caption = table_caption(node, section.get("caption", "") or node.title)
    return IncidenceTablePlan(
        node.id, caption, doses, dose_unit, rows, section.get("footnotes", []) or []
    )


@dataclass(frozen=True)
class ApicalRow:
    """
    One data row of an apical dose-response table.

    cells:    full cell-string list, already padded to the table's column count
              (mean ± SE values re-rounded via format_mean_se_display, BMD/BMDL
              appended, short rows filled with "—").
    is_n_row: True for the per-dose N-count row.  Only the HTML emitter uses
              this (to tag the <tr> with class="n-row"); the LaTeX emitter
              ignores it — a pre-existing divergence preserved by carrying the
              flag in the plan rather than acting on it here.
    """
    cells: list[str]
    is_n_row: bool


@dataclass(frozen=True)
class ApicalSexBlock:
    """A Male or Female group within an apical table: a label + its data rows."""
    sex_label: str
    rows: list[ApicalRow]


@dataclass(frozen=True)
class ApicalTablePlan:
    """
    Markup-free description of an apical dose-response table.

    The emitters build their own column headers (the dose labels and the
    "BMD/BMDL ... (unit)" columns differ per format — unicode subscript + plain
    space in HTML, \\textsubscript + "~" + escaping in LaTeX) and their own
    sex-separator rows, but consume the shared per-row cells below.

    Fields:
        node_id:   stable node id (LaTeX keys its niehstable env on it).
        caption:   plain-text "Table N. ..." caption.
        first_col: first-column header ("Endpoint" / "Study Day").
        dose_unit: unit for the dose-column labels and the BMD/BMDL columns.
        doses:     RAW dose values (emitter formats the column labels).
        ncols:     total column count = 1 (label) + len(doses) + 2 (BMD, BMDL);
                   the value rows are already padded to this.
        sex_blocks: present sexes in Male, Female order (empty sexes dropped).
        footnotes: raw footnote dicts; the emitter renders the markup.
    """
    node_id: str
    caption: str
    first_col: str
    dose_unit: str
    doses: list
    ncols: int
    sex_blocks: list[ApicalSexBlock]
    footnotes: list


def apical_table_plan(node: DocNode, data: dict) -> ApicalTablePlan | None:
    """
    EXTRACT for the apical dose-response table: section lookup, dose grid, and
    the Male/Female row cells — all format-agnostic.

    Returns None when the section, its table_data, or both sex row lists are
    missing, so the emitter renders its placeholder (preserving the old
    behavior of a placeholder in any of those cases).
    """
    section = find_apical_section(node, data)
    if not section or not section.get("table_data"):
        return None

    table_data = section.get("table_data", {})
    male_rows = table_data.get("Male", []) or []
    female_rows = table_data.get("Female", []) or []
    if not male_rows and not female_rows:
        return None

    dose_unit = section.get("dose_unit", "mg/kg")
    first_col = section.get("first_col_header", "Endpoint")

    # All rows share the same dose grid (it IS the column structure); pull it
    # from the first row that carries one.
    ref_row = (male_rows or female_rows)[0]
    doses = ref_row.get("doses", []) or []
    # Columns: label + one per dose + the two BMD/BMDL trailing columns.
    ncols = 1 + len(doses) + 2

    sex_blocks: list[ApicalSexBlock] = []
    for sex_label, rows in (("Male", male_rows), ("Female", female_rows)):
        if not rows:
            continue
        built: list[ApicalRow] = []
        for row in rows:
            label = row.get("endpoint") or row.get("day_label") or row.get("label") or ""
            values = row.get("values", []) or []
            bmd = row.get("bmd", "—") or "—"
            bmdl = row.get("bmdl", "—") or "—"
            # Re-round each mean ± SE cell to a uniform, magnitude-appropriate
            # precision at render time (format_mean_se_display leaves n counts,
            # incidence, and NA/ND/— sentinels untouched).  bmd/bmdl are not
            # mean ± SE pairs and pass through unchanged.
            cells = [
                str(label),
                *[format_mean_se_display(str(v)) for v in values],
                str(bmd),
                str(bmdl),
            ]
            while len(cells) < ncols:
                cells.append("—")
            built.append(ApicalRow(cells=cells, is_n_row=bool(row.get("is_n_row"))))
        sex_blocks.append(ApicalSexBlock(sex_label=sex_label, rows=built))

    caption = table_caption(node, section.get("caption", ""))
    return ApicalTablePlan(
        node.id, caption, first_col, dose_unit, doses, ncols, sex_blocks,
        section.get("footnotes", []) or [],
    )


# ---------------------------------------------------------------------------
# Results-section extractors (ADR-0006 Amendment 1 — completing the IR)
# ---------------------------------------------------------------------------

def unified_narrative_paragraphs(node: DocNode, data: dict) -> list[str]:
    """
    Resolve the prose paragraphs for a narrative+tables group node.

    The narrative lives at data["unified_narratives"][node.narrative_key] when
    the node carries a narrative_key; the stored entry is either a legacy list
    of strings or a dict with a "paragraphs" key.  Returns [] when absent — the
    emitter decides what an empty body means (its placeholder), since emptiness
    is format-dependent.
    """
    if not node.narrative_key:
        return []
    unified = data.get("unified_narratives", {})
    if not isinstance(unified, dict):
        return []
    entry = unified.get(node.narrative_key)
    if isinstance(entry, list):
        return entry
    if isinstance(entry, dict):
        return entry.get("paragraphs", []) or []
    return []


# Column meaning of the apical-endpoint BMD summary table — semantic vocabulary
# shared by both surfaces; each emitter renders these labels in its own markup
# (and LaTeX adds its own column-alignment spec, which is presentation).
BMD_SUMMARY_HEADERS: tuple[str, ...] = (
    "Sex", "Endpoint", "BMD", "BMDL", "LOEL", "NOEL", "Direction",
)


@dataclass(frozen=True)
class BmdSummaryPlan:
    """
    Markup-free description of the Apical Endpoint BMD Summary node.

    Fields:
        caption:    plain-text "Table N. ..." caption.
        paragraphs: the summary prose (rendered above the table, and on its own
                    when there are no endpoints).
        rows:       one cell-string list per endpoint in BMD_SUMMARY_HEADERS
                    order, or None when the session has no endpoints yet (the
                    emitter then shows prose-or-placeholder, no table).
    """
    caption: str
    paragraphs: list[str]
    rows: list[list[str]] | None


def bmd_summary_plan(node: DocNode, data: dict) -> BmdSummaryPlan:
    """
    EXTRACT for the BMD summary: prose + one row per endpoint, format-agnostic.

    rows is None (not []) when there are no endpoints, so the emitter can
    distinguish "no table at all" from "an empty table."
    """
    summary = data.get("bmd_summary", {}) or {}
    endpoints = summary.get("endpoints", []) or []
    paragraphs = summary.get("paragraphs", []) or []

    rows: list[list[str]] | None = None
    if endpoints:
        rows = [
            [
                str(ep.get("sex", "")),
                str(ep.get("endpoint", "")),
                str(ep.get("bmd", "—") or "—"),
                str(ep.get("bmdl", "—") or "—"),
                str(ep.get("loel", "—") or "—"),
                str(ep.get("noel", "—") or "—"),
                str(ep.get("direction", "")),
            ]
            for ep in endpoints
        ]

    return BmdSummaryPlan(table_caption(node, node.title), paragraphs, rows)


# Column meaning of the Appendix B animal roster (semantic vocabulary shared by
# both surfaces; the LaTeX longtable header is laid out separately — presentation).
ANIMAL_ROSTER_HEADERS: tuple[str, ...] = ("Animal ID", "Sex", "Dose (mg/kg)")


def _roster_dose(dose) -> str:
    """Format a roster dose: drop a trailing ".0" on whole numbers, else "—"."""
    if isinstance(dose, (int, float)):
        return str(int(dose)) if float(dose).is_integer() else str(dose)
    return "—"


def appendix_roster_rows(node: DocNode, data: dict) -> list[list[str]] | None:
    """
    EXTRACT for the Appendix B animal roster: one [animal_id, sex, dose] row per
    animal, format-agnostic (raw strings; each emitter escapes).

    Returns None for any appendix other than B, or when the session supplied no
    roster — the emitter then shows its "[Appendix body pending]" stub.  The
    "Appendix B carries the roster" decision is the semantic part and lives here.
    """
    if node.id != "appendix-b" or not data.get("appendix_animals"):
        return None
    return [
        [str(r.get("animal_id", "")), str(r.get("sex", "")), _roster_dose(r.get("dose"))]
        for r in data["appendix_animals"]
    ]


def methods_subsection_content(
    node: DocNode, data: dict
) -> tuple[list[str], dict | None]:
    """
    EXTRACT for a Materials & Methods subsection: locate this node's methods
    section and return its (paragraphs, inline_table).

    The methods content lives at data["methods"]["sections"] as a flat list of
    {key, heading, paragraphs, [table]} dicts.  We match on the STABLE `key`
    (the node's methods_key, matching MethodsSection.key / SUBSECTION_SKELETON)
    — NOT the display heading.  Both the production methods_report path and the
    scaffold _build_methods_sections_from_tree path emit that key; matching on
    it means rewording a subsection title in the template or the skeleton can't
    silently unlink a subsection's prose (the two heading strings are
    independently maintained).  The heading match is kept only as a fallback for
    legacy section dicts that predate the key field.

    The inline table, when present, is already in a neutral {caption, headers,
    rows, footnotes} shape that each emitter renders in its own markup, so it is
    passed through as-is rather than re-modelled here.

    Returns ([], None) when no section matches (the emitter shows its pending
    placeholder — emptiness is format-dependent, so that decision stays in emit).
    """
    methods = data.get("methods", {})
    if not isinstance(methods, dict):
        return [], None

    def _unpack(section: dict) -> tuple[list[str], dict | None]:
        table = section.get("table")
        return (
            section.get("paragraphs", []) or [],
            table if isinstance(table, dict) else None,
        )

    sections = methods.get("sections", [])

    # Primary: match on the stable methods_key binding.
    node_key = node.methods_key
    if node_key:
        for section in sections:
            if section.get("key") == node_key:
                return _unpack(section)

    # Fallback: legacy section dicts without a `key` — match the display heading.
    for section in sections:
        if not section.get("key") and section.get("heading") == node.title:
            return _unpack(section)

    return [], None


# ---------------------------------------------------------------------------
# Genomics-section extractors (ADR-0006 Amendment 1 — semantic core only)
# ---------------------------------------------------------------------------
# The genomics handler's PRESENTATION (inline base64 <figure> vs
# \includegraphics file reference, <h4> vs \subsubsection, table wrapping) and
# its TRANSPORT (the ADR-0005 per-item override + round-trip anchors, LaTeX
# only) stay in the emitters.  Only the semantic core is shared here: which
# role, which intro, which entries, the gene/gene-set table ROWS, the
# description (label, text) pairs, and each chart's "Figure N." caption text.

# Column meaning of the two genomics tables (semantic vocabulary; each emitter
# supplies its own markup and — LaTeX — column alignment).
GENE_SET_TABLE_HEADERS: tuple[str, ...] = (
    "Rank", "GO ID", "Term", "BMD", "BMDL", "Genes", "Direction",
)
GENE_TABLE_HEADERS: tuple[str, ...] = (
    "Rank", "Gene", "BMD", "BMDL", "Direction", "Fold Change",
)


def genomics_role(node: DocNode) -> str:
    """'gene_set' for the Gene Set BMD section node, 'gene' otherwise."""
    return "gene_set" if node.id == "gene-sets" else "gene"


def genomics_intro_paragraphs(node: DocNode, data: dict) -> list[str]:
    """
    The top-of-section narrative paragraphs for a genomics section, from
    data["gene_set_narrative"] / ["gene_narrative"] (a legacy list or a dict
    with a "paragraphs" list).  [] when absent.
    """
    key = "gene_set_narrative" if genomics_role(node) == "gene_set" else "gene_narrative"
    top = data.get(key)
    if isinstance(top, list):
        return top
    if isinstance(top, dict) and isinstance(top.get("paragraphs"), list):
        return top["paragraphs"]
    return []


def genomics_entries(node: DocNode, data: dict) -> list[dict]:
    """The data["genomics_sections"] entries whose type matches this node's role."""
    role = genomics_role(node)
    return [s for s in (data.get("genomics_sections", []) or []) if s.get("type") == role]


def gene_set_table_rows(entry: dict) -> list[list[str]] | None:
    """
    Rows for the top-gene-sets table of one (organ, sex) entry, in
    GENE_SET_TABLE_HEADERS order.  None when the entry has no gene sets yet (the
    emitter shows its pending placeholder, which carries the organ/sex).
    """
    rows = entry.get("gene_sets", []) or []
    if not rows:
        return None
    return [
        [
            str(r.get("rank", "")),
            str(r.get("go_id", "")),
            str(r.get("go_term", "")),
            str(format_display_number(r.get("bmd"))),
            str(format_display_number(r.get("bmdl"))),
            str(r.get("n_genes", "")),
            str(r.get("direction", "")),
        ]
        for r in rows
    ]


def gene_table_rows(entry: dict) -> list[list[str]] | None:
    """
    Rows for the top-genes table of one (organ, sex) entry, in
    GENE_TABLE_HEADERS order.  None when the entry has no genes yet.
    """
    rows = entry.get("top_genes", []) or []
    if not rows:
        return None
    return [
        [
            str(r.get("rank", "")),
            str(r.get("gene") or r.get("gene_symbol", "")),
            str(format_display_number(r.get("bmd"))),
            str(format_display_number(r.get("bmdl"))),
            str(r.get("direction", "")),
            str(format_display_number(r.get("fold_change"))),
        ]
        for r in rows
    ]


def genomics_description_items(descriptions) -> list[tuple[str, str]]:
    """
    Normalise a go-term / gene definition list into [(label, text)], dropping
    entries with neither.  label falls back across label/go_term/gene/go_id;
    text across text/description.  Each emitter renders the markup (<dl> / LaTeX).
    """
    out: list[tuple[str, str]] = []
    for d in descriptions or []:
        if not isinstance(d, dict):
            continue
        label = d.get("label") or d.get("go_term") or d.get("gene") or d.get("go_id") or ""
        text = d.get("text") or d.get("description") or ""
        if not (label or text):
            continue
        out.append((label, text))
    return out


def genomics_chart_caption(chart: dict) -> str:
    """
    The visible "Figure N. <descriptive>" caption text for a genomics chart
    (ADR-0004 amendment (e)).  The trailing rstrip drops the dangling space when
    the descriptive caption is empty.  Returns the bare descriptive caption when
    no figure number is assigned.  This is the figure's IDENTITY text — shared;
    whether it becomes an <figcaption> or a LaTeX caption is the emitter's job.
    """
    text = chart.get("caption", "")
    fig_num = chart.get("figure_number")
    if fig_num is not None:
        text = f"Figure {fig_num}. {text}".rstrip()
    return text


# ---------------------------------------------------------------------------
# Dispatch registry — the canonical set of renderable node types (ADR-0006 #3)
# ---------------------------------------------------------------------------
# Before ADR-0006 #3, each renderer kept its own _DISPATCH table and the two
# were forced to agree only by tests/unit/test_renderer_dispatch_parity.py —
# a guard bolted onto a problem the structure didn't prevent.  This registry IS
# that structure: one canonical list both renderers validate their dispatch
# against at IMPORT time, so a node type added to one renderer but not the other
# (the silent-fall-through-to-"[Section pending]" bug) becomes a loud failure on
# import, not a surprise on Overleaf.

# Every node_type the report tree can contain and that a renderer is expected to
# emit.  Adding a node type to the document tree means adding it here AND giving
# both renderers an emitter for it (or declaring a structural omission below).
RENDERABLE_NODE_TYPES: frozenset[str] = frozenset({
    "cover",
    "title-page",
    "front-matter",
    "narrative",
    "heading-only",
    "appendix",
    "tables-list",
    "toc",
    "narrative+tables",
    "table",
    "incidence-table",
    "bmd-summary",
    "genomics-section",
})

# Node types a renderer may legitimately NOT implement, with the structural
# reason.  The LaTeX renderer builds the title page with \maketitle (ADR-0003
# decision #6), so its cover / title-page tree nodes intentionally emit nothing;
# this is the single documented divergence between the two surfaces.
LATEX_OMITS: frozenset[str] = frozenset({"cover", "title-page"})


class RenderDispatchError(RuntimeError):
    """
    Raised at import time when a renderer's dispatch table does not match the
    canonical RENDERABLE_NODE_TYPES registry — either it's missing an emitter
    for a registered type, or it registers a type the registry doesn't know
    about (which means the registry is stale).  Either way the two output
    surfaces would silently disagree, so we fail loudly instead.
    """


def assert_dispatch_covers(
    dispatch, *, renderer: str, allow_omit: frozenset[str] = frozenset()
) -> None:
    """
    Verify a renderer's dispatch table exactly matches the registry.

    Called by each renderer immediately after it defines its `_DISPATCH`, so a
    coverage gap is an import-time RenderDispatchError rather than a silent
    "[Section pending]" placeholder discovered later on one surface only.

    Args:
        dispatch:   the renderer's node_type → handler mapping (any object whose
                    iteration yields the registered node_type keys — a dict).
        renderer:   human-readable renderer name for the error message
                    (e.g. "HTML", "LaTeX").
        allow_omit: node types this renderer is permitted to skip because it
                    handles them structurally elsewhere (LaTeX passes
                    LATEX_OMITS for cover/title-page).

    Raises:
        RenderDispatchError: if any registered type (minus allow_omit) has no
            emitter, or if the table registers a type outside the registry.
    """
    keys = set(dispatch)
    missing = RENDERABLE_NODE_TYPES - keys - allow_omit
    if missing:
        raise RenderDispatchError(
            f"{renderer} renderer is missing emitters for registered node "
            f"types: {sorted(missing)}. Add a handler, or — if this renderer "
            f"handles them structurally — pass them in allow_omit."
        )
    unknown = keys - RENDERABLE_NODE_TYPES
    if unknown:
        raise RenderDispatchError(
            f"{renderer} renderer registers node types absent from the "
            f"canonical RENDERABLE_NODE_TYPES registry: {sorted(unknown)}. "
            f"Add them to render_common.RENDERABLE_NODE_TYPES so the other "
            f"renderer is required to handle them too."
        )
