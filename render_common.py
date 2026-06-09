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
        if paragraphs:
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
