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

from document_model.document_node import DocNode
# Render-time numeric re-rounding for mean ± SE cells — already the shared
# formatter both renderers used; the apical extractor applies it once here so
# both surfaces get identical cell text.
from tables.table_builder_common import format_mean_se_display, format_display_number
# The per-node landscape DECISION is format-agnostic (it inspects the node type,
# the orientation overlay, and the node default) — only the WRAP markup differs.
# render_capabilities is a clean low-level module that imports nothing from
# document_tree / the renderers / this module, so importing it here keeps
# render_common a leaf (the tree walk itself is still passed in, never imported).
from document_model.render_capabilities import landscape_requested
# Guard is the DERIVED edit-hardness scale (ADR-0015).  rendering may import
# workflow (workflow must never import rendering); this pulls in only the small
# GuardLevel enum, no engine/store, so render_common stays a leaf on the render
# side.  resolve_protection (below) reads a pre-resolved per-node level map off
# `data` — step 5 renders the mark; computing the level from facts is another
# step's job.
from workflow.guard import GuardLevel

import math
import re


# ---------------------------------------------------------------------------
# Release gate — pending-placeholder detection (issue #3)
# ---------------------------------------------------------------------------
# Both renderers deliberately emit visible "[... pending]" placeholders for
# unimplemented / data-missing nodes so authors editing the draft can grep for
# the gaps (see latex_generator._pending_placeholder and the html mirror).
# That draft visibility is correct — but a placeholder must NEVER survive into a
# customer-facing DELIVERABLE.  Rather than thread a "strict" flag through the
# ~15 emit sites, the deliverable build scans the FINISHED output string once
# here (the single choke point) and refuses to ship if any marker survived.
#
# One family of marker shapes, all emitted as bracketed "[<label> pending: ...]"
# or "[Placeholder: ...]".  The last shape catches LLM-generated prose that
# leaks a "[Placeholder: GEO Accession ...]" note the model was told to fill —
# a different mechanism than the tree stubs, but the same defect for a reader.
_PENDING_MARKER_RE = re.compile(
    r"\[(?:"
    r"Section pending"
    r"|Narrative pending"
    r"|Appendix body pending"
    r"|Table data pending"
    r"|Placeholder"
    r")\b[^\]]*\]",
    re.IGNORECASE,
)


class PendingContentError(RuntimeError):
    """
    Raised when a DELIVERABLE build (strict mode) would emit a document that
    still contains one or more "[... pending]" / "[Placeholder: ...]" markers.

    The message lists every surviving marker so the caller sees exactly which
    sections are unresolved.  Carries the raw marker list on `.markers` for
    programmatic callers (route handlers, tests).
    """

    def __init__(self, markers: list[str]) -> None:
        self.markers = markers
        preview = "\n".join(f"  - {m}" for m in markers)
        super().__init__(
            f"{len(markers)} unresolved placeholder(s) would ship in the "
            f"deliverable:\n{preview}"
        )


def scan_pending_markers(text: str) -> list[str]:
    """
    Return every pending-placeholder marker found in a rendered report string,
    in document order, de-duplicated while preserving first-seen order.

    Format-agnostic: the markers are the same bracketed tokens in both the
    LaTeX and HTML surfaces (the brackets survive \\emph{...} / <em>...</em>
    wrapping), so one scan serves either deliverable.  Returns [] when the
    document is clean — the release-gate success condition.
    """
    seen: dict[str, None] = {}
    for m in _PENDING_MARKER_RE.finditer(text or ""):
        # Collapse internal whitespace so a marker broken across lines by the
        # renderer still reads as one label.
        marker = " ".join(m.group(0).split())
        seen.setdefault(marker, None)
    return list(seen)


# ---------------------------------------------------------------------------
# Inline content model — semantic units WITHIN a paragraph (ADR-0010 inline
# sibling of the block COMPONENT_CATALOG)
# ---------------------------------------------------------------------------
# A hyperlink (and, later, a cross-reference, a superscript, an emphasis) is
# SEMANTIC content, not a styling annotation: the link's TARGET is information
# ("this text refers to the NIEHS site"); the appearance (blue/underlined/
# clickable) is a per-surface RENDERING INSTRUCTION each emitter derives — the
# same decision/emit split ADR-0006 applies to block styling, one level down.
#
# Representation (deliberately minimal, room to grow):
#   - a PARAGRAPH is either a plain ``str`` (the common case, unchanged) OR a
#     list of INLINE UNITS;
#   - an inline unit is either a plain ``str`` (a literal run) or a typed dict.
#     The only type today is ``ext-link`` (projects to BITS <ext-link>/HTML <a>):
#         {"type": "ext-link", "text": "PubMed", "href": "https://pubmed..."}
#   - a future unit (``xref``, ``sup``, ``emphasis``) is a new ``type`` the
#     emitters learn; unknown types degrade to their ``text`` (never a hard fail).
#
# ``normalize_inline`` coerces either shape to a list of units so every emitter
# has ONE code path; ``inline_plain_text`` flattens to bare text (for alt-text,
# link detection, the pending-marker scan).  The three surface emitters
# (html/latex/docx) each translate a unit to their markup — that per-surface
# translation is the only place link presentation is decided.

INLINE_EXT_LINK = "ext-link"


def make_ext_link(text: str, href: str) -> dict:
    """One inline external-link unit (the semantic content: display text + its
    target URI).  Presentation is each surface's business."""
    return {"type": INLINE_EXT_LINK, "text": text, "href": href}


def normalize_inline(paragraph) -> list:
    """Coerce a paragraph (a plain str OR a list of inline units) to a list of
    inline units, so an emitter has one path.  A plain str → ``[str]``; a list
    passes through (its str/dict units intact).  None/empty → ``[]``."""
    if paragraph is None:
        return []
    if isinstance(paragraph, str):
        return [paragraph] if paragraph else []
    if isinstance(paragraph, list):
        return paragraph
    return [str(paragraph)]


def inline_plain_text(paragraph) -> str:
    """Flatten a paragraph (plain str or inline-unit list) to bare text — the
    link display text for a typed unit, the literal for a str.  Used where only
    the text matters (pending-marker scan, docx alt, has-content checks)."""
    parts: list[str] = []
    for unit in normalize_inline(paragraph):
        if isinstance(unit, str):
            parts.append(unit)
        elif isinstance(unit, dict):
            parts.append(str(unit.get("text", "")))
    return "".join(parts)


def paragraph_has_inline(paragraph) -> bool:
    """True when a paragraph carries any TYPED inline unit (a link etc.), i.e. it
    is not a plain string / list of plain strings.  Lets an emitter keep its fast
    plain-text path and only branch to inline rendering when needed."""
    return any(isinstance(u, dict) for u in normalize_inline(paragraph))


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


@dataclass(frozen=True)
class NarrativeContent:
    """The resolved content of ONE narrative-family node, source-agnostic.

    A narrative-family node (`narrative`, `front-matter`, `narrative+tables`)
    keeps its prose in one of three DIFFERENT data shapes, and which shape
    applies is decided by the node itself (its node_type + whether it carries a
    methods_key).  Historically each render surface re-implemented that dispatch
    in its own `_render_narrative` — three hand-copies that agreed only by
    discipline, and a fourth (JATS) that copied one branch and silently dropped
    ~20 sections.  `resolve_narrative_content` makes the decision ONCE and returns
    this union; every surface consumes it and owns only its markup.  This is the
    narrative-content analogue of the node-type dispatch centralization ADR-0006
    did with RENDERABLE_NODE_TYPES / assert_dispatch_covers.

    The union is LOSSLESS — it carries every shape a surface consumes today, so
    relocating the dispatch here changes no surface's output:

        kind:          which content source won —
                         "labeled"    → labeled_parts (structured-abstract parts);
                         "paragraphs" → paragraphs (flat prose: background, summary,
                                        references, and the Results narrative+tables
                                        groups via unified_narratives);
                         "methods"    → paragraphs (+ optional inline_table) for an
                                        M&M subsection matched by methods_key;
                         "none"       → no content source; the emitter shows its own
                                        (format-dependent) pending placeholder.
        level:         heading level (0 = none) — passed straight to the emitter.
        title:         heading text (raw, unescaped — the emitter escapes).
        labeled_parts: [(label, text)] for kind == "labeled"; label may be "".
        paragraphs:    raw paragraph units for kind in {"paragraphs", "methods"}.
        inline_table:  the neutral {caption, headers, rows, footnotes} dict for a
                       methods subsection that carries an inline table (only the
                       "methods" kind ever sets it); None otherwise.  Surfaces
                       that render inline tables read this; a surface may ignore
                       it (JATS defers <table-wrap> to the data-tables phase).

    Emptiness stays a per-surface EMIT decision (see module docstring): kind
    "none" is the ONLY signal here, and a surface may additionally treat an
    all-whitespace paragraphs list as pending in its own way.
    """
    kind: str
    level: int
    title: str
    labeled_parts: list[tuple[str, str]] = field(default_factory=list)
    paragraphs: list = field(default_factory=list)
    inline_table: dict | None = None


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

    A paragraph is a plain string OR an inline-unit list (the inline model);
    inline_plain_text flattens either to bare text for the emptiness check.
    """
    return any(inline_plain_text(p).strip() for p in (paragraphs or []))


def appendix_heading_text(node: DocNode) -> str:
    """Compose an appendix heading's display text: "Appendix {letter}. {title}".

    The letter comes from ``node.appendix_letter`` (assigned positionally by
    document_tree.compute_appendix_letters — the single source of truth; titles
    no longer bake in a literal "Appendix A." prefix).  Falls back to the bare
    title when no letter is set (scaffold/test nodes, or a non-appendix caller),
    so this never fabricates a prefix it wasn't given.

    Used by the LaTeX and HTML surfaces, which have no auto-numbering machinery
    and must put the letter into the visible heading text.  The docx surface
    does NOT use this: it applies the NTP `4-05_Appendix_Head_1` style whose own
    numbered list emits "Appendix A." (and feeds the chapter-relative page
    numbering), matching the reference byte-for-byte with a bare-title run.
    """
    letter = node.appendix_letter
    title = node.title or ""
    if not letter:
        return title
    return f"Appendix {letter}. {title}" if title else f"Appendix {letter}"


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
# Reconstructs the reference's Table B-1 "Animal Numbers and FASTQ Data File
# Names": one row per (animal x sequenced tissue).
ANIMAL_ROSTER_HEADERS: tuple[str, ...] = (
    "Animal Number", "Sex", "Dose (mg/kg)", "Tissue", "FASTQ File ID",
)


def _roster_dose(dose) -> str:
    """Format a roster dose: drop a trailing ".0" on whole numbers, else "—"."""
    if isinstance(dose, (int, float)):
        return str(int(dose)) if float(dose).is_integer() else str(dose)
    return "—"


def appendix_roster_rows(node: DocNode, data: dict) -> list[list[str]] | None:
    """
    EXTRACT for the Appendix B animal roster: one row per (animal x tissue) in
    ANIMAL_ROSTER_HEADERS order — [animal_number, sex, dose, tissue, fastq_file_id]
    — format-agnostic (raw strings; each emitter escapes).

    Rows arrive already joined + sorted (latex_export._load_animal_identifiers);
    this only projects them to the shared column order.  Returns None for any
    appendix other than B, or when the session supplied no roster — the emitter
    then shows its "[Appendix body pending]" stub.  The "Appendix B carries the
    roster" decision is the semantic part and lives here.
    """
    if node.id != "appendix-b" or not data.get("appendix_animals"):
        return None
    return [
        [
            str(r.get("animal_number", "")),
            str(r.get("sex", "")),
            _roster_dose(r.get("dose")),
            str(r.get("tissue", "")),
            str(r.get("fastq_file_id", "")),
        ]
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


def resolve_narrative_content(node: DocNode, data: dict) -> NarrativeContent:
    """Resolve a narrative-family node's content, source-agnostic (THE dispatch).

    This is the single place that decides WHICH of the three narrative content
    shapes a node uses — the decision every render surface used to hand-copy into
    its own `_render_narrative`/`_render_narrative_tables` (and that JATS copied
    incompletely, dropping the Methods + Results prose).  Precedence, verbatim
    from the surfaces:

      1. `narrative+tables` group node → prose from `unified_narratives`
         (`unified_narrative_paragraphs`).  Its child `table` nodes are walked
         separately by each surface; this resolves only the group's own prose.
      2. a node carrying `methods_key` → the M&M subsection lookup
         (`methods_subsection_content`), which returns (paragraphs, inline_table).
      3. otherwise (plain `narrative` / `front-matter`) → `front_matter_plan`,
         whose labeled/paragraphs/none kinds map straight onto NarrativeContent.

    Returns a NarrativeContent whose `kind` drives the emitter's markup switch.
    "none" means no content source was found; the emitter applies its own
    (format-dependent) pending placeholder — this function never decides
    emptiness beyond "no source at all" (see module docstring).

    Note the ordering: the `narrative+tables` check is first and independent of
    `methods_key` (a group node has a narrative_key, not a methods_key, so the
    order only matters defensively), and `front_matter_plan` is the fallback that
    also serves genuine `front-matter` nodes — so this one function covers all
    three narrative-family node types uniformly.
    """
    if node.node_type == "narrative+tables":
        paragraphs = unified_narrative_paragraphs(node, data)
        kind = "paragraphs" if has_paragraph_content(paragraphs) else "none"
        return NarrativeContent(kind, node.level, node.title, paragraphs=paragraphs)

    if node.methods_key:
        paragraphs, inline = methods_subsection_content(node, data)
        has = has_paragraph_content(paragraphs) or inline is not None
        return NarrativeContent(
            "methods" if has else "none",
            node.level, node.title,
            paragraphs=paragraphs, inline_table=inline,
        )

    plan = front_matter_plan(node, data)
    return NarrativeContent(
        plan.kind, plan.level, plan.title,
        labeled_parts=plan.labeled_parts, paragraphs=plan.paragraphs,
    )


def sample_counts_table(node: DocNode, data: dict) -> dict | None:
    """
    EXTRACT for a ``sample-counts-table`` node (Methods "Final Sample Counts"
    matrix — Table 1).  The already-built table dict lives at
    ``data[node.data_key]`` in the neutral ``{caption, headers, rows,
    footnotes}`` shape (produced by methods_table1.build_sample_counts_from_
    context on both export paths), so each emitter renders it in its own markup.

    Returns the dict when present and non-empty, else None (the emitter shows
    its pending placeholder — emptiness handling is format-dependent, so it
    stays in emit, matching the inline-table / apical-table pattern).
    """
    key = node.data_key
    if not key:
        return None
    built = data.get(key)
    if not isinstance(built, dict):
        return None
    if not built.get("headers") and not built.get("rows"):
        return None
    return built


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
# supplies its own markup and — LaTeX — column alignment).  These mirror the
# reference NIEHS-10 Tables 9–12 exactly (both sexes stacked; see
# gene_set_table_rows / gene_table_rows for the sex-separator rows).
GENE_SET_TABLE_HEADERS: tuple[str, ...] = (
    "Category Name",
    "No. of Active Genes/ Platform Genes in Gene Set",
    "% Gene Set Coverage",
    "Active Genes",
    "BMD1std Median of Gene Set Transcripts (mg/kg)",
    "Median BMDL1Std–BMDU1Std (mg/kg)",
    "Genes with Changed Direction Up",
    "Genes with Changed Direction Down",
)
GENE_TABLE_HEADERS: tuple[str, ...] = (
    "Gene Symbol",
    "Entrez Gene IDs",
    "Probe IDs",
    "BMD1Std (BMDL1std–BMDU1std) in mg/kg",
    "Maximum Fold Change",
    "Direction of Expression Change",
)

# Entrez Gene IDs are not present in our extraction (the probe id suffix is a
# probe number, not the Entrez id; no gene->Entrez source in the KB).  The
# reference column is kept for structural parity, stubbed with an em dash.
_ENTREZ_STUB = "—"


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


# ---------------------------------------------------------------------------
# Content-item resolution (ADR-0003 Part B) — the one sequence every emitter
# iterates for a component's sub-addressable content items.
# ---------------------------------------------------------------------------
# The two authoring modes converge HERE, at the emitter boundary, rather than by
# mutating the process-global DOCUMENT_TREE (which per-session data-derived items
# must never touch):
#   * RENDER-TIME (genomics) — flatten genomics_content_plan across the section's
#     entries; each resolved item carries its (entry, role) so the surface's
#     existing per-item renderer works unchanged.
#   * TEMPLATE-AUTHORED (static) — a node's own content_items list (wired in a
#     later stage; not yet consumed here).
# Stage 2 covers ONLY the genomics branch as a behavior-preserving refactor: the
# four _render_genomics_section handlers stop calling genomics_content_plan
# directly and iterate resolve_content_items instead, byte-identically.

class ResolvedContentItem:
    """One content item ready for an emitter, carrying everything the surface's
    per-item renderer needs. For genomics: the plan dict (`item`) plus its source
    `entry` and `role`, so `_render_genomics_item(entry, role, item)` is unchanged.

    `component_id` + `item_id` give the composite overlay/anchor key
    "<component_id>::<item_id>". `orientable` mirrors the plan flag.
    """

    __slots__ = ("component_id", "item_id", "orientable", "source", "entry",
                 "role", "item")

    def __init__(self, *, component_id, item_id, orientable, source,
                 entry=None, role=None, item=None):
        self.component_id = component_id
        self.item_id = item_id
        self.orientable = orientable
        self.source = source          # "genomics" | "authored"
        self.entry = entry            # genomics: the source entry dict
        self.role = role              # genomics: "gene_set" | "gene"
        self.item = item              # genomics: the plan dict

    @property
    def overlay_key(self) -> str:
        return f"{self.component_id}::{self.item_id}"


def resolve_content_items(node: DocNode, data: dict) -> "list[ResolvedContentItem]":
    """The ordered content items a component contributes, medium-agnostically.

    Genomics-section → the per-entry genomics_content_plan flattened in document
    order, each item wrapped with its (entry, role). Any other node → [] (the
    template-authored branch lands in a later stage). This is the single sequence
    all four emitters iterate; it reproduces the former per-handler
    entry×item nested loop exactly (byte-identical) while removing the
    per-surface duplication of that loop.
    """
    from genomics.genomics_content import genomics_content_plan

    if node.node_type == "genomics-section":
        role = genomics_role(node)
        resolved: list[ResolvedContentItem] = []
        for entry in genomics_entries(node, data):
            for item in genomics_content_plan(entry, role):
                resolved.append(ResolvedContentItem(
                    component_id=node.id,
                    item_id=item["item_id"],
                    orientable=item.get("orientable", False),
                    source="genomics",
                    entry=entry,
                    role=role,
                    item=item,
                ))
        return resolved

    return []


# Genomics BMD values print to 3 decimals in the reference (e.g. "0.520",
# "0.160–2.885") — one place finer than the apical default.
_GENOMICS_DECIMALS = 3


def _entry_sex_blocks(entry: dict, rows_key: str) -> list[tuple[str, list]]:
    """Return the entry's per-sex row blocks as [(sex_label, rows), ...].

    New shape: entry["sexes"] = [{"sex": "Male", <rows_key>: [...]}, ...] — one
    table stacks both sexes (reference Tables 9–12).  Falls back to the OLD
    single-(organ, sex) shape (entry["sex"] + entry[rows_key]) so a stale
    payload still renders.  Blocks with no rows are dropped."""
    out: list[tuple[str, list]] = []
    sexes = entry.get("sexes")
    if isinstance(sexes, list) and sexes:
        for block in sexes:
            rows = block.get(rows_key) or []
            if rows:
                out.append((str(block.get("sex", "")).strip().capitalize(), rows))
    else:
        rows = entry.get(rows_key) or []
        if rows:
            out.append((str(entry.get("sex", "")).strip().capitalize(), rows))
    return out


def _finite_or_none(v):
    """Return v unless it is None or a non-finite float / "NaN"/"inf" string,
    in which case None (so range/BMD formatting shows the em-dash placeholder
    rather than a literal "nan")."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v  # a label / pre-formatted string — leave as-is
    return None if (math.isnan(f) or math.isinf(f)) else v


def _bmd_range(lo, hi) -> str:
    """Format a "BMDL–BMDU" range with an en dash, e.g. "0.160–2.885".  Either
    bound missing / non-finite collapses to the single present value (or "—" for
    none)."""
    lo = _finite_or_none(lo)
    hi = _finite_or_none(hi)
    lo_s = format_display_number(lo, _GENOMICS_DECIMALS) if lo is not None else "—"
    hi_s = format_display_number(hi, _GENOMICS_DECIMALS) if hi is not None else "—"
    if lo_s == "—" and hi_s == "—":
        return "—"
    if hi_s == "—":
        return lo_s
    if lo_s == "—":
        return hi_s
    return f"{lo_s}–{hi_s}"


def gene_set_table_rows(entry: dict) -> list[list[str]] | None:
    """
    Rows for the top-gene-sets table of one PER-ORGAN entry, in
    GENE_SET_TABLE_HEADERS order, with both sexes stacked: each sex contributes
    a ``**Sex**`` separator row (rendered as a merged full-width label by all
    three emitters) followed by that sex's Top-10 gene-set rows.  None when the
    entry has no gene sets at all (emitter shows its pending placeholder).

    Columns match the reference (Table 9/10): Category Name (GO id + tab +
    term), No. Active/Platform Genes, % Coverage, Active Genes list, BMD median,
    Median BMDL–BMDU range, Up count, Down count.
    """
    blocks = _entry_sex_blocks(entry, "gene_sets")
    if not blocks:
        return None
    ncol = len(GENE_SET_TABLE_HEADERS)
    out: list[list[str]] = []
    for sex_label, rows in blocks:
        if sex_label:
            out.append([f"**{sex_label}**"] + [""] * (ncol - 1))
        for r in rows:
            n_genes = r.get("n_genes", 0) or 0
            n_bmd = r.get("n_genes_with_bmd", 0) or 0
            pct = f"{round(n_bmd / n_genes * 100)}%" if n_genes else ""
            genes = str(r.get("genes", "") or "").replace(";", "; ")
            out.append([
                f"{r.get('go_id', '')}\t{r.get('go_term', '')}".strip(),
                f"{n_bmd}/{n_genes}",
                pct,
                genes,
                str(format_display_number(r.get("bmd"), _GENOMICS_DECIMALS)),
                _bmd_range(r.get("bmdl"), r.get("bmdu")),
                str(r.get("n_up", "")),
                str(r.get("n_down", "")),
            ])
    return out


def gene_table_rows(entry: dict) -> list[list[str]] | None:
    """
    Rows for the top-genes table of one PER-ORGAN entry, in GENE_TABLE_HEADERS
    order, both sexes stacked (``**Sex**`` separator + that sex's Top-10 genes).
    None when the entry has no genes at all.

    Columns match the reference (Table 11/12): Gene Symbol, Entrez Gene IDs
    (STUBBED "—" — not in our data), Probe IDs, BMD (BMDL–BMDU), Maximum Fold
    Change, Direction of Expression Change.
    """
    blocks = _entry_sex_blocks(entry, "top_genes")
    if not blocks:
        return None
    ncol = len(GENE_TABLE_HEADERS)
    out: list[list[str]] = []
    for sex_label, rows in blocks:
        if sex_label:
            out.append([f"**{sex_label}**"] + [""] * (ncol - 1))
        for r in rows:
            bmd = format_display_number(r.get("bmd"), _GENOMICS_DECIMALS)
            rng = _bmd_range(r.get("bmdl"), r.get("bmdu"))
            bmd_cell = f"{bmd} ({rng})" if bmd != "—" else "—"
            # Reference "Maximum Fold Change" is the MAGNITUDE (always positive,
            # 1 decimal); the sign lives in the Direction column instead.
            fc = r.get("fold_change")
            try:
                fc_cell = f"{abs(float(fc)):.1f}"
            except (TypeError, ValueError):
                fc_cell = format_display_number(fc)
            out.append([
                str(r.get("gene") or r.get("gene_symbol", "")),
                _ENTREZ_STUB,
                str(r.get("probe_id", "") or ""),
                bmd_cell,
                fc_cell,
                str(r.get("direction", "")).upper(),
            ])
    return out


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


def genomics_table_caption(entry: dict) -> str:
    """
    The "Table N. <descriptive>" caption for one PER-ORGAN genomics table.

    The number comes from ``entry["table_number"]``, assigned positionally by
    document_tree.assign_genomics_table_numbers (the data-side companion to
    compute_table_numbers, since genomics tables are not tree nodes).  The
    descriptive text is DATA-DRIVEN from the entry's organ / type and Top-N row
    count and matches the reference phrasing exactly: "Top N <Organ> Gene
    Ontology Biological Process Gene Sets Ranked by Potency of Perturbation,
    Sorted by Benchmark Dose Median" / "Top N <Organ> Genes Ranked by Potency of
    Perturbation, Sorted by Benchmark Dose Median".  No sex in the locator — the
    table now stacks both sexes (reference Tables 9–12).

    Shared so both surfaces label the table identically; the emitter decides
    whether it becomes a LaTeX caption line or an HTML <caption>.  Returns the
    bare descriptive text when no number is assigned (scaffold / preview).
    """
    organ = (entry.get("organ") or "").strip().capitalize()
    role = entry.get("type")

    # Top-N: the per-sex Top-N is uniform (10), so report the max sex block's
    # length rather than the summed row count across both sexes.
    blocks = entry.get("sexes")
    if isinstance(blocks, list) and blocks:
        key = "gene_sets" if role == "gene_set" else "top_genes"
        n = max((len(b.get(key) or []) for b in blocks), default=0)
    else:
        rows = entry.get("gene_sets") if role == "gene_set" else entry.get("top_genes")
        n = len(rows or [])

    kind = ("Gene Ontology Biological Process Gene Sets"
            if role == "gene_set" else "Genes")
    lead = f"Top {n} " if n else "Top "
    descriptive = (
        f"{lead}{organ} {kind} Ranked by Potency of Perturbation, "
        "Sorted by Benchmark Dose Median"
    ).replace("  ", " ").strip()

    num = entry.get("table_number")
    if num is not None:
        return f"Table {num}. {descriptive}"
    return descriptive


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
    "figure",
    "bmd-summary",
    "sample-counts-table",
    "genomics-section",
    "freeform-page",
    "freeform-block",
    "page-break",
})

# Node types a renderer may legitimately NOT implement, with the structural
# reason.  Empty now: the LaTeX renderer used to omit cover / title-page and
# build the title page with \maketitle (ADR-0003 decision #6), but both are now
# real emitters (_render_cover / _render_title_page — a full-bleed branded cover
# + centered inner title page), so the two surfaces render every node type and
# there is no remaining documented divergence.
LATEX_OMITS: frozenset[str] = frozenset()


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


# ---------------------------------------------------------------------------
# Tree walk + per-node emit (ADR-0006)
# ---------------------------------------------------------------------------

def walk_emit(
    node: DocNode,
    data: dict,
    *,
    walk,
    dispatch,
    fallback,
    wrap_landscape,
    emit_pre=None,
    wrap_post=None,
    wrap_style=None,
) -> list[str]:
    r"""
    Render a node and its descendants to a flat, document-ordered list of
    markup chunks — the shared skeleton behind latex_generator._walk_latex and
    html_generator._walk_html.

    The traversal (visit node, then recurse children in order) is the shared
    ``walk_tree`` primitive (ADR-0006); the per-node EMIT differs by surface and
    is supplied by the caller as callables.  Both renderers used to hand-write
    this same accumulator loop, which let the two walks drift — extracting it
    here is what keeps them in lockstep.

    The accumulator pattern (close over ``chunks`` inside a ``_visit`` callback,
    because ``walk_tree`` is side-effect-only) lives here once instead of in
    both renderers.

    Args:
        node: the subtree root to render (walked as ``[node]``).
        data: the report data dict, threaded to every handler + wrap callable.
        walk: the traversal primitive — pass ``document_tree.walk_tree``.  It is
            a PARAMETER rather than an import so render_common stays a leaf
            module (importing walk_tree would pull in document_tree's
            instantiated DOCUMENT_TREE at import time).
        dispatch: the renderer's ``node_type -> handler`` mapping.
        fallback: handler used for an unregistered node type
            (each renderer's ``_render_unimplemented``).
        wrap_landscape: ``chunk -> chunk`` applied when the node is orientable
            and the overlay requests landscape.  The DECISION is shared (made
            here via landscape_requested); only this WRAP markup is per-surface.
        emit_pre: optional ``node -> str`` whose non-empty result is appended
            BEFORE the node's own chunk (HTML's scroll-target ``<span>``; LaTeX
            passes None — it has no pre-chunk).
        wrap_post: optional ``(node, chunk) -> chunk`` applied AFTER the
            landscape wrap.  LaTeX passes the ADR-0005 override substitution +
            round-trip anchor here; HTML passes None.  This None-vs-wrap is the
            ONE intentional surface divergence (the preview shows generated
            content only, never human overrides) — see the divergence-#2 TODO
            in memory ([[project_rlm_arch1_walk_emit]]) for the plan to give
            HTML its own override-substitution wrap_post.
        wrap_style: optional ``(node, chunk) -> chunk`` applied AFTER the
            landscape wrap and BEFORE wrap_post — the per-content-type font/flow
            styling wrap.  The DECISION (what style this node resolves to) is
            shared: both surfaces read the same ``data["layout_style"]`` config;
            only this WRAP markup is per-surface.  LaTeX passes a wrapper that
            brackets the chunk in a font/spacing group; HTML passes None because
            it applies the same resolved spec as CSS rules in the document
            ``<style>`` block rather than inline (same shared-decision /
            per-surface-emit split as wrap_landscape).

    Returns:
        The list of markup chunks in document order; the caller joins them.
    """
    chunks: list[str] = []

    def _visit(n: DocNode) -> None:
        handler = dispatch.get(n.node_type, fallback)
        chunk = handler(n, data)
        if not chunk:
            return
        if emit_pre is not None:
            pre = emit_pre(n)
            if pre:
                chunks.append(pre)
        # Per-node landscape: wrap this node's output when the user flipped it
        # AND the node's semantic type is orientable (capability dictionary).
        # Gating on the capability ignores stale/invalid overlay flags — the
        # dictionary is authoritative on both the UI and render sides.
        if landscape_requested(n.node_type, n.id, data.get("orientations"),
                               default=n.orientation):
            chunk = wrap_landscape(chunk)
        # Per-node font/flow styling (per-content-type layout spec).  Applied
        # after the landscape wrap so a styled node still rotates correctly, and
        # before wrap_post so an ADR-0005 override substitution sees the final
        # styled markup.  HTML passes None here (it emits CSS rules instead).
        if wrap_style is not None:
            chunk = wrap_style(n, chunk)
        if wrap_post is not None:
            chunk = wrap_post(n, chunk)
        chunks.append(chunk)

    walk([node], _visit)
    return chunks


# ---------------------------------------------------------------------------
# Per-node protection mark (ADR-0014 step 5) — the render-channel half.
# ---------------------------------------------------------------------------
# The workflow's human-facing guard (workflow.guard.human_guard) is the intensity
# of the "protected" visual mark; step 5 only SURFACES a pre-resolved per-node
# level so every output surface can draw it.  The level map is threaded on the
# report data under data["protection"] — a plain {node_id -> GuardLevel} dict,
# keyed by the globally-unique DocNode.id (the same key the ADR-0005 override
# overlay uses).  Computing the level from facts is deferred to a later step;
# this step never touches facts.  An ABSENT or empty map ⇒ every node resolves
# to OPEN ⇒ no mark ⇒ byte-identical output to before this feature (the same
# no-op safety property the layout-style / override overlays guarantee).

def resolve_protection(node_id: str, data: dict) -> GuardLevel:
    """Look up the pre-resolved human-facing guard level for one node.

    Reads ``data["protection"]`` (a ``{node_id -> level}`` map) and returns the
    stored level for ``node_id``, or ``GuardLevel.OPEN`` when the map is absent,
    empty, or has no entry for this node.  The stored value is tolerated as a
    ``GuardLevel``, a plain ``int`` (its numeric value), or a ``str`` (its member
    NAME, case-insensitive) — the map is produced by another step / surface and
    may arrive JSON-round-tripped, so this stays permissive.  An unrecognized
    value degrades to OPEN (no mark) rather than raising: a malformed protection
    entry must never break a render.

    Pure and dependency-light: no I/O, no fact computation, no mutation of
    ``data`` — just a lookup + coercion.
    """
    protection = data.get("protection")
    if not protection:
        return GuardLevel.OPEN
    raw = protection.get(node_id)
    if raw is None:
        return GuardLevel.OPEN
    return _coerce_guard_level(raw)


def _coerce_guard_level(raw) -> GuardLevel:
    """Coerce a stored protection value to a GuardLevel; OPEN on anything odd."""
    if isinstance(raw, GuardLevel):
        return raw
    if isinstance(raw, bool):
        # bool is an int subclass; treat True as GUARDED, False as OPEN rather
        # than as the int 1/0 (a stored boolean flag reads as "protected?").
        return GuardLevel.GUARDED if raw else GuardLevel.OPEN
    if isinstance(raw, int):
        try:
            return GuardLevel(raw)
        except ValueError:
            return GuardLevel.OPEN
    if isinstance(raw, str):
        try:
            return GuardLevel[raw.strip().upper()]
        except KeyError:
            # Also accept a stringified int ("1") for JSON-lossy transports.
            try:
                return GuardLevel(int(raw.strip()))
            except (ValueError, TypeError):
                return GuardLevel.OPEN
    return GuardLevel.OPEN


def is_protected(level: GuardLevel) -> bool:
    """Does this level warrant a visual protection mark? (>= GUARDED)."""
    return level >= GuardLevel.GUARDED
