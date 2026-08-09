"""
latex_generator.py — LaTeX rendering of the NIEHS biological potency report.

This module is the LaTeX-side counterpart to report_data.py's Typst pipeline.
It walks the canonical document_tree.DOCUMENT_TREE and emits a flat report.tex
that, together with latex/niehs.cls, compiles via pdflatex to a NIEHS-styled
PDF.  The .tex output is the artifact authors upload to Overleaf and hand-edit.

Why this exists
---------------
The project is migrating its final-output path from Typst to LaTeX (see
[[project_latex_pivot]] in memory).  The reason is authoring ergonomics:
NIEHS authors and reviewers know LaTeX; they do not know Typst.  Overleaf
is the editing surface they expect for the polish/sign-off step.

Architecture (per 2026-05-19 grilling session, "Option B")
---------------------------------------------------------
The eleven design decisions that shape this module:

  1. Render-time architecture — Python pre-renders a flat report.tex from
     DOCUMENT_TREE + data.  No JIT JSON parsing at LaTeX compile time.
  2. Regen policy — one-shot hand-off.  After export, the .tex is the
     author's; we do not round-trip their edits back into session JSON.
  3. Styling — hybrid.  Vanilla \\section / \\subsection for prose;
     niehs.cls only for tables and a handful of specialized environments.
  4. Tables — Python emits ready-to-render tabular rows; the class wraps
     them with caption + footnote chrome.
  5. Footnotes — threeparttable + \\tnote{a}.  Python keeps assigning
     letters (existing finalize_footnotes logic stays put).
  6. Cover + title — skip the NIEHS-branded cover in v1; emit a plain
     \\maketitle title page.
  7. Genomics charts — Plotly to_image(format="pdf") into figures/; the
     export bundles report.tex + niehs.cls + figures/ as a zip.
  8. Empty sections — emit every section in tree order.  Empty sections
     get a visible "[Section pending]" placeholder so authors see the gap.
  9. Preview scope — LaTeX replaces Typst entirely, including per-section
     preview PDFs in the web app.  Typst (eventually) goes away.
 10. Preview compile — fragment compile.  When section_filter is set, the
     generator emits a stripped .tex containing only the requested subtree.
 11. PDF/UA accessibility — dropped in v1; documented as a regression
     against the Typst path.  Re-evaluate in v2+.

Tracer-bullet scope (this commit)
---------------------------------
End-to-end pipeline: DOCUMENT_TREE + data dict → compilable report.tex.

Implemented node_types: front-matter, narrative, appendix, heading-only,
tables-list (stub).

Everything else — tables, BMD summary, genomics, narrative+tables, cover,
title-page, incidence-table, narrative+tables — falls through to
_render_unimplemented, which emits a visible "[Section pending]" placeholder
so the .tex still compiles and the author sees the structural gap in
Overleaf.

Future sessions will fill in the unimplemented handlers, wire the fragment-
compile preview path into the web app, and bundle figures/ for export.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
# DOCUMENT_TREE is the canonical structure (heading hierarchy, section ids,
# data_keys).  DocNode is the per-node type; we annotate handlers with it.

import re

from document_tree import (
    DOCUMENT_TREE,
    DocNode,
    find_node,
    first_body_node_id,
    walk_tree,
)
from render_capabilities import content_item_landscape_requested
from render_common import (
    NarrativeContent,
    resolve_narrative_content,
    has_paragraph_content,
    normalize_inline,
    inline_plain_text,
    paragraph_has_inline,
    INLINE_EXT_LINK,
    assert_dispatch_covers,
    walk_emit,
    LATEX_OMITS,
    incidence_table_plan,
    apical_table_plan,
    bmd_summary_plan,
    BMD_SUMMARY_HEADERS,
    appendix_roster_rows,
    appendix_heading_text,
    ANIMAL_ROSTER_HEADERS,
    sample_counts_table,
    genomics_role,
    genomics_intro_paragraphs,
    genomics_entries,
    gene_set_table_rows,
    gene_table_rows,
    genomics_description_items,
    genomics_chart_caption,
    genomics_table_caption,
    GENE_SET_TABLE_HEADERS,
    GENE_TABLE_HEADERS,
    find_apical_section as _find_apical_section,
    table_caption as _table_caption,
)
from genomics_content import genomics_content_plan
from layout_style import resolve_layout_style
from freeform_content import pending_note as _freeform_pending_note
from cover_layouts import get_cover_layout
from roundtrip.overrides import region_hash
from roundtrip.anchors import wrap as _anchor
from cross_references import resolve_xrefs_latex, latex_label_key
# Shared display-precision knob: rounds the raw modeling-step BMD/BMDL/fold-
# change floats to a configurable number of decimals at render time (see
# table_builder_common.DISPLAY_DECIMALS).
from table_builder_common import format_display_number, format_mean_se_display


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Map DocNode.level → article-class LaTeX sectioning command.
# Level 0 means "no heading" (cover, title-page, table nodes) — the dispatch
# skips heading emission for those.  Level 1/2/3 are H1/H2/H3 in the tree
# and map to article's three top-most sectioning units.  Anything deeper
# falls back to \paragraph in _heading() to avoid a KeyError; the tree
# does not produce level > 3 today, so this is defensive only.
_HEADING_BY_LEVEL: dict[int, str] = {
    1: r"\section",
    2: r"\subsection",
    3: r"\subsubsection",
}

# LaTeX characters that have syntactic meaning and must be escaped when
# user-supplied or session-derived text gets spliced into the .tex output.
#
# Order matters: the backslash substitution must run first.  If we replaced
# "&" → "\&" before "\\" → "\\textbackslash{}", the backslash in "\&" would
# itself get substituted on the next pass, producing
# "\textbackslash{}&", which is wrong.
#
# Without escaping, an ampersand in a chemical name (e.g., a salt form)
# would terminate a tabular cell mid-row, and a percent sign in a footnote
# would comment out the rest of the line.  Both are common failure modes
# when piping arbitrary scientific text into LaTeX.
_LATEX_ESCAPES: list[tuple[str, str]] = [
    ("\\", r"\textbackslash{}"),
    ("&", r"\&"),
    ("%", r"\%"),
    ("$", r"\$"),
    ("#", r"\#"),
    ("_", r"\_"),
    ("{", r"\{"),
    ("}", r"\}"),
    ("~", r"\textasciitilde{}"),
    ("^", r"\textasciicircum{}"),
]

# Unicode characters common in toxicology/statistics text that the report's
# font (lmodern / T1) cannot render — they silently DROP from the PDF under
# both tectonic and Overleaf's pdflatex (confirmed by a real compile: e.g.
# "p ≤ 0.05" and "BMD₁Std" lost their ≤ and subscript).  Translate
# them to LaTeX commands (math fonts carry the relations; \textsubscript for
# subscript digits).  Applied as a post-pass AFTER the special-character
# escaping above, so the backslashes/braces we insert here are not re-escaped.
# Superscript-digit codepoints are NOT contiguous: 1/2/3 are the legacy
# Latin-1 chars (U+00B9/B2/B3) while 0 and 4–9 live in U+2070–2079.  Mapped
# to \textsuperscript{N} so scientific-notation exponents in LLM prose (e.g.
# an FDR of "6.66×10⁻³⁴") survive the compile instead of silently dropping
# their exponent — which changes the value by orders of magnitude.
_SUPERSCRIPT_DIGIT_CP: dict[int, int] = {
    0: 0x2070, 1: 0x00B9, 2: 0x00B2, 3: 0x00B3, 4: 0x2074,
    5: 0x2075, 6: 0x2076, 7: 0x2077, 8: 0x2078, 9: 0x2079,
}

_UNICODE_TO_LATEX: list[tuple[str, str]] = [
    ("≤", r"\ensuremath{\le}"),   # ≤
    ("≥", r"\ensuremath{\ge}"),   # ≥
    # Subscript digits ₀–₉ → \textsubscript{N}
    *((chr(0x2080 + d), rf"\textsubscript{{{d}}}") for d in range(10)),
    # Superscript minus ⁻ (U+207B) + superscript digits → \textsuperscript{…}
    ("⁻", r"\textsuperscript{-}"),
    *((chr(cp), rf"\textsuperscript{{{d}}}") for d, cp in _SUPERSCRIPT_DIGIT_CP.items()),
    # Registered-trademark ® (U+00AE) — not in lmodern under T1, so pdflatex
    # silently drops it (the strain "(Hsd:Sprague Dawley® SD®)" on the cover
    # would lose both marks).  textcomp (loaded via lmodern/T1) provides it.
    ("®", r"\textregistered{}"),
]


# ---------------------------------------------------------------------------
# Helper functions (private)
# ---------------------------------------------------------------------------

def _escape_latex(text: str) -> str:
    """
    Escape LaTeX-special characters in plain text.

    Called wherever we splice arbitrary strings (chemical names, narrative
    paragraphs, section titles, footnote bodies) into the .tex output.
    Returns the empty string for None / empty input so callers can chain
    safely without None-checks.

    Note: this is not a full sanitizer.  Math expressions and intentional
    LaTeX commands (e.g., LLM output that already contains \\textit{...})
    are also escaped, which is a small cost — at v1 we accept that prose
    will not contain embedded LaTeX.  When/if the LLM starts emitting
    formatted output, this routine grows a "trusted-input" bypass.
    """
    if not text:
        return ""
    for raw, repl in _LATEX_ESCAPES:
        text = text.replace(raw, repl)
    # Translate font-unrenderable Unicode to LaTeX commands AFTER escaping, so
    # the commands we insert (\ensuremath{...}, \textsubscript{...}) survive.
    for raw, repl in _UNICODE_TO_LATEX:
        text = text.replace(raw, repl)
    # Resolve semantic cross-references AFTER escaping (ADR-0004 amendment c):
    # [[xref:id]] tokens survive the escape pass (brackets are not LaTeX-
    # special), and the \ref{} we insert is therefore not re-escaped.
    text = resolve_xrefs_latex(text)
    return text


def _heading(level: int, title: str) -> str:
    """
    Emit a LaTeX sectioning command for the given level + title.

    Level 0 returns "" so callers can unconditionally splice the result.
    Title text is escaped before splicing — section titles can contain
    ampersands (e.g., "Body Weights & Organ Weights").
    """
    if level <= 0:
        return ""
    cmd = _HEADING_BY_LEVEL.get(level, r"\paragraph")
    return f"{cmd}{{{_escape_latex(title)}}}"


# Match an http/https URL up to the next whitespace.  Trailing sentence
# punctuation (e.g. the period in "...11603678.") gets pulled back out in
# _splice_urls so it stays in the prose and out of the clickable link.
_URL_RE = re.compile(r"https?://\S+")
_URL_TRAILING_PUNCT = ".,;:!?)]}>\"'"


def _splice_urls(text: str) -> str:
    r"""
    Escape `text` for LaTeX, but render any embedded http(s) URL as a
    breakable \url{...} instead of escaped prose.

    Why this exists: a URL escaped as ordinary text is one long unbreakable
    token — its '/' and '.' are not TeX line-break points — so a long
    reference URL (PubChem, ATSDR, CDC links) runs past the right margin
    (overfull \hbox).  \url, with xurl loaded in niehs.cls, breaks after any
    character AND renders the URL as a blue clickable link via hyperref,
    matching the NIEHS references convention.  Only the URL substrings are
    special-cased; all surrounding prose is escaped normally.
    """
    out: list[str] = []
    pos = 0
    for m in _URL_RE.finditer(text):
        url = m.group(0)
        start, end = m.start(), m.end()
        # Peel trailing sentence punctuation back off the URL so "...123."
        # keeps its period in the prose and out of the \url link target.
        while url and url[-1] in _URL_TRAILING_PUNCT:
            url = url[:-1]
            end -= 1
        # Escape the prose before the URL, then emit the URL raw inside \url{}
        # (the url/xurl package handles its own special characters).
        out.append(_escape_latex(text[pos:start]))
        out.append("\\url{" + url + "}")
        pos = end
    out.append(_escape_latex(text[pos:]))
    return "".join(out)


def _render_inline(paragraph) -> str:
    r"""Render one paragraph (a plain str OR a list of inline units — the
    render_common inline model) to LaTeX.  A plain str keeps the exact
    _splice_urls path (bare-URL → breakable \url{}); an ext-link unit becomes an
    \href{url}{text} (hyperref, loaded in niehs.cls), text escaped; an unknown
    typed unit degrades to its escaped text."""
    if not paragraph_has_inline(paragraph):
        text = inline_plain_text(paragraph) if isinstance(paragraph, list) else paragraph
        return _splice_urls(text or "")
    out: list[str] = []
    for unit in normalize_inline(paragraph):
        if isinstance(unit, str):
            out.append(_splice_urls(unit))
        elif unit.get("type") == INLINE_EXT_LINK:
            href = unit.get("href", "")
            out.append(rf"\href{{{href}}}{{{_escape_latex(unit.get('text', ''))}}}")
        else:
            out.append(_escape_latex(unit.get("text", "")))
    return "".join(out)


def _render_paragraphs(paragraphs: list) -> str:
    """
    Render a list of paragraphs as LaTeX, separated by blank lines (TeX paragraph
    breaks).  A paragraph is a plain string OR a list of inline units
    (render_common inline model); _render_inline escapes/links either.  Bare URLs
    in plain text still become breakable \\url{} (keeps long reference URLs off
    the margin).  Returns "" for empty input so callers can substitute a
    placeholder.
    """
    if not paragraphs:
        return ""
    return "\n\n".join(_render_inline(p) for p in paragraphs)


def _pending_placeholder(node_type: str) -> str:
    """
    Emit the visible "section pending" placeholder we use for unimplemented
    node_types in the tracer bullet.

    Per decision #8 (empty sections), the placeholder is intentionally
    human-readable: authors who open the exported .tex in Overleaf can
    grep for "[Section pending" and immediately see what's still TODO.
    """
    return (
        f"\\emph{{[Section pending: {_escape_latex(node_type)} "
        f"rendering not yet implemented in tracer-bullet.]}}"
    )


# ---------------------------------------------------------------------------
# Per-node-type render functions
# ---------------------------------------------------------------------------
# Each handler takes (node, data) and returns the LaTeX for that node alone
# (not its children — the walker handles children separately after calling
# the handler).  Returning "" means "this node contributes no output."
#
# Adding a new node_type means: write a _render_<type> function below and
# register it in _DISPATCH.  Anything not registered falls through to
# _render_unimplemented and emits a visible placeholder.


def _emit_narrative_body(rc: NarrativeContent) -> str:
    r"""EMIT the body of a resolved NarrativeContent as LaTeX — no heading, no
    pending fallback (those belong to the caller, since emptiness is per-surface).

    The content SOURCE was already chosen by render_common.resolve_narrative_
    content; this is the pure LaTeX EMIT for each kind:
      labeled    → bold run-in-label paragraphs (\textbf{Label.} ...);
      paragraphs → flat paragraph list;
      methods    → the same paragraph list plus, when present, the inline table
                   (Final Sample Counts under Transcriptomics → Sample Collection);
      none       → "" (caller substitutes its \emph{[... pending]} placeholder).
    The has_paragraph_content guard reproduces the old methods handler exactly
    (an inline-table-only section emits just the table)."""
    if rc.kind == "labeled":
        return _render_labeled_sections(rc.labeled_parts)
    if rc.kind in ("paragraphs", "methods"):
        body = _render_paragraphs(rc.paragraphs) if has_paragraph_content(rc.paragraphs) else ""
        if rc.kind == "methods" and rc.inline_table is not None:
            body = (body + "\n\n" + _render_inline_table(rc.inline_table)).strip()
        return body
    return ""


def _render_narrative_family(node: DocNode, data: dict, pending_word: str) -> str:
    r"""Heading + resolved narrative body, with the surface's pending fallback.

    The single LaTeX entry point for every narrative-family node type: resolve
    the content ONCE via the shared dispatch, emit it, and fall back to
    \emph{[<pending_word> pending: <title>]} when the body is empty.  Callers
    pass "Section" or "Narrative" to preserve the pre-refactor per-type wording."""
    rc = resolve_narrative_content(node, data)
    body = _emit_narrative_body(rc)
    if not body:
        body = f"\\emph{{[{pending_word} pending: {_escape_latex(node.title)}]}}"
    return f"{_heading(node.level, node.title)}\n\n{body}"


def _render_front_matter(node: DocNode, data: dict) -> str:
    """
    Front-matter section (foreword, about, peer review, publication
    details, acknowledgments, abstract).

    Renders as a heading plus the section's paragraphs.  The content-source
    decision now lives in the shared render_common.resolve_narrative_content
    dispatch; only the LaTeX markup and the format-dependent "empty body →
    pending" fallback are EMIT here (decision #8 keeps the structure visible).
    """
    return _render_narrative_family(node, data, "Section")


def _render_labeled_sections(parts: list[tuple[str, str]]) -> str:
    r"""
    EMIT normalised labeled-section parts as paragraphs with a bold run-in
    label (e.g. "\textbf{Background.} ...").  Input is the (label, text) list
    from render_common.front_matter_plan (already filtered to non-empty text);
    a "" label renders an unlabeled paragraph.
    """
    out: list[str] = []
    for label, text in parts:
        if label:
            out.append(
                f"\\noindent\\textbf{{{_escape_latex(label)}.}} {_escape_latex(text)}"
            )
        else:
            out.append(_escape_latex(text))
    return "\n\n".join(out)


def _render_narrative(node: DocNode, data: dict) -> str:
    """
    Plain narrative section (background, summary, references, and most M&M
    subsections).  Same shape as front-matter at the LaTeX level — page
    numbering switches (roman → arabic) happen in niehs.cls, not here.

    M&M subsections (methods_key) and plain prose both route through the shared
    resolve_narrative_content dispatch, which selects the right content source.
    """
    return _render_narrative_family(node, data, "Section")


def _render_inline_table(table: dict) -> str:
    """
    Render an inline table (used by M&M subsections like Sample Collection
    for the Final Sample Counts table — Table 1).

    Expected shape: {"caption": str, "headers": [str], "rows": [[cell]],
    "footnotes": [...]}.  Rendered as a niehstable env so it joins the
    \\listoftables.
    """
    caption = _escape_latex(table.get("caption", ""))
    headers = table.get("headers", [])
    rows = table.get("rows", [])
    footnotes = table.get("footnotes", [])
    if not headers and not rows:
        return ""

    # Column spec: left-align first column, center the rest.  Most M&M
    # tables are descriptive (text columns) — center alignment looks
    # right for the typical sample-counts shape.
    ncols = max(len(headers), max((len(r) for r in rows), default=0))
    colspec = "l" + "c" * (ncols - 1) if ncols > 1 else "l"

    body_lines = ["\\begin{tabular}{" + colspec + "}", "\\toprule"]
    if headers:
        body_lines.append(_emit_tabular_row([str(h) for h in headers]))
        body_lines.append("\\midrule")
    for row in rows:
        body_lines.append(_emit_tabular_row([str(c) for c in row]))
    body_lines.append("\\bottomrule")
    body_lines.append("\\end{tabular}")

    tabular = "\n".join(body_lines)
    notes = _emit_table_footnotes(footnotes)

    # Anonymous label — inline tables don't have a stable id from the
    # document tree, so we synthesize one from the caption hash.  This
    # is intentional: cross-references to inline tables aren't supported
    # in v1, only auto-numbering via \listoftables.
    label = "inline-" + str(abs(hash(caption)) % 10_000_000)
    return (
        f"\\begin{{niehstable}}{{{label}}}{{{caption}}}\n"
        f"{tabular}"
        f"{notes}\n"
        f"\\end{{niehstable}}"
    )


def _render_heading_only(node: DocNode, data: dict) -> str:
    """
    Structural heading whose actual content lives in this node's children
    (Materials and Methods, Results, sub-groups like Clinical Examinations
    and Sample Collection, Transcriptomics, Data Analysis).

    We emit only the heading.  The walker handles children separately
    after this returns.
    """
    return _heading(node.level, node.title)


def _render_appendix(node: DocNode, data: dict) -> str:
    """
    Appendix node (Appendix A through F).

    Three body sources, in precedence order:
      - Appendix B (Animal Identifiers) renders the animal roster from
        data["appendix_animals"] when the session supplied it.
      - Appendices A/D/E/F carry authored freeform CHILD nodes (the reference's
        static prose / rules tables / manifests).  We emit only the heading here
        and let the walker render the child body after us — so we must NOT also
        emit the pending stub, or the appendix would show stub + real content.
      - An appendix with neither (Appendix C, whose content needs pipeline data
        we don't retain) still emits the visible "[Appendix body pending]" line.
    """
    heading = _heading(node.level, appendix_heading_text(node))
    rows = appendix_roster_rows(node, data)
    if rows is not None:
        return f"{heading}\n\n{_emit_animal_roster(rows)}"
    if node.children:
        return heading
    body = f"\\emph{{[Appendix body pending: {_escape_latex(node.title)}]}}"
    return f"{heading}\n\n{body}"


def _emit_animal_roster(rows: list[list[str]]) -> str:
    r"""
    EMIT the Appendix B roster as a page-breaking longtable — the reference's
    Table B-1 "Animal Numbers and FASTQ Data File Names", one row per
    (animal x tissue).

    Hundreds of rows don't fit one page, and the niehstable float can't break
    across pages — so this uses longtable (loaded by niehs.cls), whose
    \endhead repeats the column header on every page.  Rows come pre-built
    (animal_number, sex, dose, tissue, fastq_file_id) from appendix_roster_rows;
    the header text is driven from ANIMAL_ROSTER_HEADERS so it can't drift from
    the shared column vocabulary.

    Each cell is escaped exactly once (by _emit_tabular_row) — matching the
    HTML roster's single-escape.
    """
    caption = ("\\caption*{\\textbf{Table B-1. Animal Numbers and FASTQ Data "
               "File Names}}\\\\\n")
    # colspec: number | sex | dose(r) | tissue | fastq-id — mirrors the 5 headers.
    colspec = "l l r l l"
    header_cells = " & ".join(_escape_latex(h) for h in ANIMAL_ROSTER_HEADERS)
    col_head = (
        "\\toprule\n"
        f"{header_cells} \\\\\n"
        "\\midrule\n"
    )
    head = (
        f"\\begin{{longtable}}{{{colspec}}}\n"
        f"{caption}{col_head}\\endfirsthead\n"
        f"{col_head}\\endhead\n"
    )
    body = "\n".join(_emit_tabular_row(r) for r in rows)
    return head + body + "\n\\bottomrule\n\\end{longtable}"


def _render_tables_list(node: DocNode, data: dict) -> str:
    r"""
    Tables list in front matter.

    All table nodes render through the niehstable environment, which
    wraps a \begin{table} float with \caption.  That makes LaTeX's
    \listoftables enumerate them automatically with page numbers — no
    manual scaffolding needed.
    """
    return f"{_heading(node.level, node.title)}\n\n\\listoftables"


def _render_toc(node: DocNode, data: dict) -> str:
    r"""
    Table of Contents — a generated front-matter component (ADR-0003),
    distinct from the navigation panel.

    Maps to LaTeX's native \tableofcontents, which auto-populates from the
    \section/\subsection commands the body emits and gets two-pass page
    numbers.  The component SELF-HEADS (\tableofcontents emits its own
    unnumbered "Contents" heading), so no \section is emitted here — which is
    why the catalog marks `toc` headingless.  This was previously hardcoded in
    the document skeleton; it is now driven by a `toc` node in the tree.
    """
    return "\\tableofcontents"


# ---------------------------------------------------------------------------
# Table-rendering helpers
# ---------------------------------------------------------------------------
# Most NIEHS tables share a tabular core (header row, separator rows, data
# rows, lettered footnotes).  These helpers keep the per-type handlers
# focused on data shape, not LaTeX syntax.

def _emit_tabular_row(cells: list[str], *, raw: bool = False) -> str:
    r"""
    Format a single tabular row as "cell1 & cell2 & \dots & cellN \\".

    cells are LaTeX-escaped unless raw=True (used when cells already
    contain intentional LaTeX, e.g., \textbf{Male} for a sex separator).
    """
    if raw:
        body = " & ".join(cells)
    else:
        body = " & ".join(_escape_latex(c) for c in cells)
    return body + r" \\"


def _emit_table_footnotes(footnotes: list) -> str:
    r"""
    Emit a threeparttable \begin{tablenotes}...\end{tablenotes} block.

    footnotes is the typed list produced by table_builder_common's
    finalize_footnotes: each entry is a dict with kind ("lettered",
    "legend", "definition"), letter (for lettered records), and text.
    We render lettered notes as \item[<letter>] entries; legend and
    definition entries get \item (no marker).
    """
    if not footnotes:
        return ""
    items: list[str] = []
    for fn in footnotes:
        if not isinstance(fn, dict):
            continue
        kind = fn.get("kind", "")
        text = fn.get("text") or fn.get("body") or ""
        if not text:
            continue
        if kind == "lettered" and fn.get("letter"):
            items.append(
                f"\\item[{_escape_latex(fn['letter'])}] {_escape_latex(text)}"
            )
        else:
            items.append(f"\\item {_escape_latex(text)}")
    if not items:
        return ""
    return "\n\\begin{tablenotes}\n" + "\n".join(items) + "\n\\end{tablenotes}"


def _format_dose_label(dose, unit: str) -> str:
    """
    Format a dose value with its unit, using a non-breaking space so
    "0.15 mg/kg" stays on one line in the column header.
    """
    unit_part = _escape_latex(unit)
    if dose == 0 or dose == 0.0:
        return f"0~{unit_part}"
    # Numeric doses render with their natural string form; if the value
    # is an int-valued float we drop the trailing ".0" for readability.
    if isinstance(dose, float) and dose.is_integer():
        return f"{int(dose)}~{unit_part}"
    return f"{_escape_latex(str(dose))}~{unit_part}"


# _table_caption / _find_apical_section now live in render_common (ADR-0006 #4)
# and are imported above under their old private names, so every handler that
# calls them is unchanged.


# ---------------------------------------------------------------------------
# Apical / dose-response tables
# ---------------------------------------------------------------------------

def _render_apical_table(node: DocNode, data: dict) -> str:
    r"""
    Render a single apical dose-response table.

    Expected data shape (per apical_sections[i]):
      - platform:       "Body Weight" | "Clinical Chemistry" | ...
      - caption:        base caption text (Table N prefix added here)
      - dose_unit:      "mg/kg" by default
      - table_data:     {"Male": [row, ...], "Female": [row, ...]}
      - footnotes:      [{kind, letter, text}, ...]
      - first_col_header (optional): "Endpoint" | "Study Day"

    Each row dict has:
      - endpoint (or day_label): row label in the first column
      - doses: [dose values], same order across all rows
      - values: [str], parallel to doses
      - bmd, bmdl: strings (already formatted)

    Scaffold data has empty table_data; we emit a placeholder so the
    section is visible in the TOC and \listoftables.
    """
    plan = apical_table_plan(node, data)
    if plan is None:
        return _emit_table_placeholder(node)

    headers = [plan.first_col] + [_format_dose_label(d, plan.dose_unit) for d in plan.doses] + [
        f"BMD\\textsubscript{{1Std}} ({_escape_latex(plan.dose_unit)})",
        f"BMDL\\textsubscript{{1Std}} ({_escape_latex(plan.dose_unit)})",
    ]
    colspec = "l" + "c" * (plan.ncols - 1)

    lines = [f"\\begin{{tabular}}{{{colspec}}}", "\\toprule",
             _emit_tabular_row(headers, raw=True), "\\midrule"]

    for block in plan.sex_blocks:
        # Bold separator row spanning all columns.
        lines.append(
            f"\\multicolumn{{{plan.ncols}}}{{l}}{{\\textbf{{{block.sex_label}}}}} \\\\"
        )
        for row in block.rows:
            # n-row distinction is HTML-only; LaTeX emits every row the same.
            lines.append(_emit_tabular_row(row.cells))

    lines.append("\\bottomrule")
    lines.append("\\end{tabular}")
    tabular = "\n".join(lines)

    notes = _emit_table_footnotes(plan.footnotes)

    return (
        f"\\begin{{niehstable}}{{{latex_label_key(node.id)}}}{{{plan.caption}}}\n"
        f"{tabular}"
        f"{notes}\n"
        f"\\end{{niehstable}}"
    )


def _emit_table_placeholder(node: DocNode) -> str:
    """
    Emit a minimal niehstable env with a "[data pending]" caption so the
    table still claims its number and appears in \\listoftables, but no
    rows render.  Used when the session hasn't generated data for this
    table yet.
    """
    caption = _table_caption(node, node.title or "")
    return (
        f"\\begin{{niehstable}}{{{latex_label_key(node.id)}}}{{{caption}}}\n"
        f"\\emph{{[Table data pending: {_escape_latex(node.title)}]}}\n"
        f"\\end{{niehstable}}"
    )


def _render_sample_counts_table(node: DocNode, data: dict) -> str:
    r"""
    Render the Methods "Final Sample Counts" matrix (Table 1) as a niehstable.

    The built matrix ({caption, headers, rows, footnotes}) comes from the shared
    sample_counts_table EXTRACT; its rows carry two conventions from the DOCX
    builder that we honor here (build_table1_data / methods_report._add_methods_
    table): a sex-header row has its first cell wrapped in "**...**" and spans
    the table (a bold separator, like the apical sex blocks); organ rows carry
    two leading spaces on the first cell.  \small keeps the 11 dose columns on
    the page; the walker's landscape wrap handles the width (node is orientable +
    orientation: landscape in the template).
    """
    built = sample_counts_table(node, data)
    if built is None:
        return _emit_table_placeholder(node)

    headers = [str(h) for h in built.get("headers", [])]
    rows = built.get("rows", [])
    ncols = max(len(headers), max((len(r) for r in rows), default=0))
    colspec = "l" + "c" * (ncols - 1) if ncols > 1 else "l"

    lines = [f"\\begin{{tabular}}{{{colspec}}}", "\\toprule",
             _emit_tabular_row(headers), "\\midrule"]
    for row in rows:
        cells = [str(c) for c in row]
        first = cells[0] if cells else ""
        if first.startswith("**") and first.endswith("**"):
            # Sex-header separator row — bold, spanning every column.
            label = first.strip("*").strip()
            lines.append(
                f"\\multicolumn{{{ncols}}}{{l}}{{\\textbf{{{_escape_latex(label)}}}}} \\\\"
            )
        else:
            if cells:
                cells[0] = cells[0].strip()
            lines.append(_emit_tabular_row(cells))
    lines.append("\\bottomrule")
    lines.append("\\end{tabular}")
    tabular = "{\\small\n" + "\n".join(lines) + "\n}"

    notes = _emit_table_footnotes(built.get("footnotes", []))
    caption = _table_caption(node, built.get("caption", ""))
    return (
        f"\\begin{{niehstable}}{{{latex_label_key(node.id)}}}{{{caption}}}\n"
        f"{tabular}"
        f"{notes}\n"
        f"\\end{{niehstable}}"
    )


# ---------------------------------------------------------------------------
# Narrative + tables group (Results subsections)
# ---------------------------------------------------------------------------

def _render_narrative_tables(node: DocNode, data: dict) -> str:
    """
    H2 group under Results (Animal Condition, Clinical Pathology, etc.).

    Emits the group heading plus the unified narrative paragraphs.  Child
    table nodes are walked separately by _walk_latex and render through
    _render_apical_table or _render_incidence_table.

    The narrative lives at data["unified_narratives"][node.narrative_key]
    when narrative_key is set.  Falls back to a placeholder when missing.

    The narrative-paragraph selection is the shared resolve_narrative_content
    dispatch; only the markup + the "Narrative pending" wording are LaTeX emit.
    """
    return _render_narrative_family(node, data, "Narrative")


# ---------------------------------------------------------------------------
# BMD summary table
# ---------------------------------------------------------------------------

def _render_bmd_summary(node: DocNode, data: dict) -> str:
    r"""
    Apical Endpoint Benchmark Dose Summary table.

    data["bmd_summary"] = {"paragraphs": [...], "endpoints": [...]}.
    Each endpoint dict has: sex, endpoint, bmd, bmdl, loel, noel, direction.
    """
    # ADR-0006 Amendment 1: prose, per-endpoint rows, and caption are the shared
    # render_common.bmd_summary_plan EXTRACT; this only EMITs the LaTeX (the
    # column-alignment spec stays here — it's presentation).
    plan = bmd_summary_plan(node, data)
    heading = _heading(node.level, node.title)
    prose = _render_paragraphs(plan.paragraphs)

    if plan.rows is None:
        body = prose or f"\\emph{{[BMD summary endpoints pending: {_escape_latex(node.title)}]}}"
        return f"{heading}\n\n{body}"

    colspec = "l l r r r r l"
    lines = [f"\\begin{{tabular}}{{{colspec}}}", "\\toprule",
             _emit_tabular_row(list(BMD_SUMMARY_HEADERS)), "\\midrule"]
    for cells in plan.rows:
        lines.append(_emit_tabular_row(cells))
    lines.append("\\bottomrule")
    lines.append("\\end{tabular}")
    tabular = "\n".join(lines)

    block = (
        f"\\begin{{niehstable}}{{{latex_label_key(node.id)}}}{{{plan.caption}}}\n"
        f"{tabular}\n"
        f"\\end{{niehstable}}"
    )
    return f"{heading}\n\n{prose}\n\n{block}".strip()


# ---------------------------------------------------------------------------
# Incidence (clinical observations) table
# ---------------------------------------------------------------------------

def _render_incidence_table(node: DocNode, data: dict) -> str:
    r"""
    Clinical Observations table.

    Different shape from the dose-response tables: each row is one
    observation, each column a dose group with an incidence count.
    Source data lives in apical_sections matched on platform; the
    section's "incidence_rows" key (when present) holds the matrix.

    Falls through to a placeholder when data is missing.
    """
    plan = incidence_table_plan(node, data)
    if plan is None:
        return _emit_table_placeholder(node)

    headers = ["Observation"] + [_format_dose_label(d, plan.dose_unit) for d in plan.doses]
    ncols = len(headers)
    colspec = "l" + "c" * (ncols - 1)

    lines = [f"\\begin{{tabular}}{{{colspec}}}", "\\toprule",
             _emit_tabular_row(headers, raw=True), "\\midrule"]
    for cells in plan.rows:
        lines.append(_emit_tabular_row(cells))
    lines.append("\\bottomrule")
    lines.append("\\end{tabular}")
    tabular = "\n".join(lines)

    notes = _emit_table_footnotes(plan.footnotes)
    return (
        f"\\begin{{niehstable}}{{{latex_label_key(node.id)}}}{{{plan.caption}}}\n"
        f"{tabular}"
        f"{notes}\n"
        f"\\end{{niehstable}}"
    )


# ---------------------------------------------------------------------------
# Genomics section (gene set + gene BMD)
# ---------------------------------------------------------------------------

def _render_genomics_section(node: DocNode, data: dict) -> str:
    """
    Gene Set BMD Analysis or Gene BMD Analysis section.

    data["genomics_sections"] is a flat list of per-(type, organ, sex)
    entries.  We filter to the ones matching this node's role (gene_set
    vs gene) and emit one H3 subsection per entry.

    Each entry's payload:
      - gene_sets[] (for gene_set type) or top_genes[] (for gene type)
      - go_descriptions[] or gene_descriptions[]
      - caption: per-organ-sex caption

    When the payload arrays are empty (scaffold), we emit a heading +
    placeholder for that organ-sex so the structure stays visible.
    """
    # ADR-0006 Amendment 1: role / intro / entries selection and the table rows
    # are the shared EXTRACT; the \subsubsection markup, the per-item loop, the
    # \includegraphics chart, the landscape wrap, and the ADR-0005 override +
    # anchor (transport) are LaTeX emit.
    role = genomics_role(node)
    heading = _heading(node.level, node.title)
    intro = _render_paragraphs(genomics_intro_paragraphs(node, data))

    entries = genomics_entries(node, data)
    if not entries:
        body = intro or f"\\emph{{[Genomics data pending: {_escape_latex(node.title)}]}}"
        return f"{heading}\n\n{body}"

    blocks: list[str] = [heading]
    if intro:
        blocks.append(intro)

    for entry in entries:
        # One entry per organ (both sexes stacked in a single table — reference
        # Tables 9–12).  No per-sex subsection heading; the table's own Male /
        # Female separator rows delineate the sexes.
        #
        # Each organ block is an ordered list of sub-addressable content
        # items (ADR-0003 Phase 4); the table is independently orientable, so a
        # wide gene table can flip landscape on its own via the composite
        # "(component, content-item)" orientation key.  Order/identity come from
        # the shared content plan; this loop reproduces the former monolith's
        # output when no per-item orientation is set.
        for item in genomics_content_plan(entry, role):
            chunk = _render_genomics_item(entry, role, item)
            if not chunk:
                continue
            if item["orientable"] and content_item_landscape_requested(
                node.id, item["item_id"], data.get("orientations")
            ):
                chunk = "\\begin{landscape}\n" + chunk + "\n\\end{landscape}"
            # ADR-0005: sub-addressable item grain — key on the composite
            # "<node-id>::<item-id>" (the same key the orientation overlay uses)
            # so a single genomics narrative/table can be overridden + attributed
            # on its own.  Override first, then bracket in item sentinels.
            item_key = f"{node.id}::{item['item_id']}"
            chunk = _apply_override(chunk, data.get("overrides") or {}, item_key, data)
            chunk = _anchor("item", item_key, chunk)
            blocks.append(chunk)

    return "\n\n".join(b for b in blocks if b)


def _render_genomics_item(entry: dict, role: str, item: dict) -> str:
    """
    Render one content item of a genomics (organ, sex) block (see
    genomics_content.genomics_content_plan for the item shape).
    """
    part = item.get("part")
    if part == "narrative":
        return _render_paragraphs(entry.get("narrative") or [])
    if part == "table":
        return (
            _render_gene_set_table(entry) if role == "gene_set"
            else _render_gene_table(entry)
        )
    if part == "chart":
        return _render_genomics_chart(entry, item.get("chart_key"))
    if part == "descriptions":
        descriptions = (
            entry.get("go_descriptions") if role == "gene_set"
            else entry.get("gene_descriptions")
        ) or []
        return _render_description_list(descriptions)
    return ""


def _render_genomics_chart(entry: dict, chart_key: str | None) -> str:
    r"""
    Render one attached genomics chart as a centered \includegraphics with an
    italic caption.  The image file (figures/<filename>) is written into the
    bundle by latex_export.build_overleaf_bundle; the filename comes from the
    chart dict so the .tex reference and the written file always agree.
    """
    chart = next(
        (c for c in (entry.get("charts") or []) if c.get("key") == chart_key),
        None,
    )
    if not chart or not chart.get("filename"):
        return ""
    # ADR-0004 amendment (e) — the "Figure N." caption text is the shared
    # genomics_chart_caption EXTRACT; here we only escape it for LaTeX.
    caption = _escape_latex(genomics_chart_caption(chart))
    return (
        "\\begin{center}\n"
        f"\\includegraphics[width=0.85\\linewidth]{{figures/{chart['filename']}}}\\\\\n"
        f"{{\\small\\itshape {caption}}}\n"
        "\\end{center}"
    )


def _render_figure(node: DocNode, data: dict) -> str:
    r"""A first-class figure node (ADR-0012) as a centered \includegraphics + an
    italic "Figure N." caption.  The artifact is a payload at data[data_key]
    (``{filename, caption}``); the image file figures/<filename> is written into
    the bundle by latex_export (same path genomics charts use), so the .tex
    reference and the written file agree.  A missing payload emits a visible
    pending note, never a silent gap."""
    payload = (data.get(node.data_key) if node.data_key else None) or {}
    text = node.caption or payload.get("caption") or node.title
    label = f"Figure {node.figure_number}. " if node.figure_number else ""
    caption = _escape_latex(f"{label}{text}") if text else ""
    filename = payload.get("filename")
    if not filename:
        return f"\\emph{{[Figure pending: {_escape_latex(node.title)}]}}"
    return (
        "\\begin{center}\n"
        f"\\includegraphics[width=0.85\\linewidth]{{figures/{filename}}}\\\\\n"
        f"{{\\small\\itshape {caption}}}\n"
        "\\end{center}"
    )


def _genomics_caption_block(entry: dict) -> str:
    r"""
    The bold "Table N. ..." caption line above a genomics table.

    Text comes from the shared genomics_table_caption EXTRACT (data-driven,
    escaped here for LaTeX); the trailing blank line separates it from the
    tabular.  Empty when the entry has no caption text (shouldn't happen once
    numbers are assigned).
    """
    caption = genomics_table_caption(entry)
    if not caption:
        return ""
    return f"\\noindent\\textbf{{{_escape_latex(caption)}}}\n\n"


def _render_gene_set_table(entry: dict) -> str:
    """
    Render the top-gene-sets table for one organ (both sexes stacked) of a
    genomics section.  8 columns (reference Table 9/10); rows carry `**Male**` /
    `**Female**` separator rows (bold, full-width) between the sex blocks.
    """
    rows = gene_set_table_rows(entry)
    if rows is None:
        return f"\\emph{{[Top gene sets pending: {_escape_latex(entry.get('organ', ''))}]}}"

    ncols = len(GENE_SET_TABLE_HEADERS)
    colspec = "p{0.24\\linewidth} l l p{0.20\\linewidth} r r r r"
    lines = [f"\\begin{{tabular}}{{{colspec}}}", "\\toprule",
             _emit_tabular_row(list(GENE_SET_TABLE_HEADERS)), "\\midrule"]
    for cells in rows:
        first = cells[0] if cells else ""
        if first.startswith("**") and first.endswith("**"):
            label = first.strip("*").strip()
            lines.append(
                f"\\multicolumn{{{ncols}}}{{l}}{{\\textbf{{{_escape_latex(label)}}}}} \\\\"
            )
        else:
            lines.append(_emit_tabular_row(cells))
    lines.append("\\bottomrule")
    lines.append("\\end{tabular}")
    # Scale-to-fit: unlike apical tables (which float through the niehstable
    # environment and get its adjustbox wrap), these genomics gene/gene-set
    # tables are emitted inline inside the genomics section as a bare tabular.
    # Wrap the bare tabular in the same "max width=\linewidth" adjustbox so a
    # wide 7-column table shrinks to the text width instead of overflowing the
    # margin; a table that already fits is left at natural size.
    table = "\\adjustbox{max width=\\linewidth}{%\n" + "\n".join(lines) + "\n}"
    # Positional "Table N." caption (data-driven), emitted above the tabular in
    # the same bold style the appendix tables use.
    return _genomics_caption_block(entry) + table


def _render_gene_table(entry: dict) -> str:
    """
    Render the top-genes table for one organ (both sexes stacked) of a gene BMD
    section.  6 columns (reference Table 11/12); rows carry `**Male**` /
    `**Female**` separator rows (bold, full-width) between the sex blocks.
    """
    rows = gene_table_rows(entry)
    if rows is None:
        return f"\\emph{{[Top genes pending: {_escape_latex(entry.get('organ', ''))}]}}"

    ncols = len(GENE_TABLE_HEADERS)
    colspec = "l l l l r l"
    lines = [f"\\begin{{tabular}}{{{colspec}}}", "\\toprule",
             _emit_tabular_row(list(GENE_TABLE_HEADERS)), "\\midrule"]
    for cells in rows:
        first = cells[0] if cells else ""
        if first.startswith("**") and first.endswith("**"):
            label = first.strip("*").strip()
            lines.append(
                f"\\multicolumn{{{ncols}}}{{l}}{{\\textbf{{{_escape_latex(label)}}}}} \\\\"
            )
        else:
            lines.append(_emit_tabular_row(cells))
    lines.append("\\bottomrule")
    lines.append("\\end{tabular}")
    # Scale-to-fit: unlike apical tables (which float through the niehstable
    # environment and get its adjustbox wrap), these genomics gene/gene-set
    # tables are emitted inline inside the genomics section as a bare tabular.
    # Wrap the bare tabular in the same "max width=\linewidth" adjustbox so a
    # wide 7-column table shrinks to the text width instead of overflowing the
    # margin; a table that already fits is left at natural size.
    table = "\\adjustbox{max width=\\linewidth}{%\n" + "\n".join(lines) + "\n}"
    # Positional "Table N." caption (data-driven), emitted above the tabular in
    # the same bold style the appendix tables use.
    return _genomics_caption_block(entry) + table


def _render_description_list(descriptions: list) -> str:
    """
    Emit a description list (one paragraph per entry).

    descriptions is a list of dicts with at least {"label", "text"} or
    {"go_term", "description"} or {"gene", "description"}.  We try
    several common shapes.
    """
    items = [
        f"\\noindent\\textbf{{{_escape_latex(label)}}}: {_escape_latex(text)}"
        for label, text in genomics_description_items(descriptions)
    ]
    return "\n\n".join(items)


def _freeform_body_latex(node: DocNode) -> str:
    """Shared body for the two freeform handlers: the node's resolved LaTeX
    markup (emitted VERBATIM — authored LaTeX is the user's own content), or a
    pending note when this representation has no native LaTeX rendering (e.g. an
    `html` node with no dual-source latex)."""
    resolved = node.resolved_content or {}
    latex = resolved.get("latex")
    if latex:
        return latex
    rep = node.representation or "html"
    return f"\\emph{{{_escape_latex(_freeform_pending_note(rep, 'latex'))}}}"


def _render_freeform_page(node: DocNode, data: dict) -> str:
    r"""
    Freeform AUTHORED content that starts its own page.  Emits ``\clearpage``
    so the page is isolated, an optional heading (skipped when title is empty),
    then the resolved LaTeX content verbatim (or a pending note).
    """
    heading = _heading(node.level, node.title) if node.title else ""
    body = _freeform_body_latex(node)
    parts = ["\\clearpage"]
    if heading:
        parts.append(heading)
    parts.append(body)
    return "\n\n".join(parts)


def _render_freeform_block(node: DocNode, data: dict) -> str:
    """
    Freeform AUTHORED content rendered inline (no forced page break).  Optional
    heading + the resolved LaTeX content verbatim (or a pending note).
    """
    heading = _heading(node.level, node.title) if node.title else ""
    body = _freeform_body_latex(node)
    if heading:
        return f"{heading}\n\n{body}"
    return body


def _render_page_break(node: DocNode, data: dict) -> str:
    r"""
    An explicit author-placed page break.  Emits ``\clearpage`` (flush floats +
    start a new page), the same primitive freeform-page uses.  Carries no
    heading or content of its own.
    """
    return "\\clearpage"


def _cover_point(dx: float, dy: float, *, corner: str = "north west") -> str:
    r"""A tikz `current page` coordinate dx pt right / dy pt DOWN from a corner."""
    return f"([xshift={dx}pt, yshift={-dy}pt]current page.{corner})"


def _render_cover(node: DocNode, data: dict) -> str:
    r"""
    Full-bleed branded cover page (page 1), driven by the node's cover subtype.

    The layout — assets, palette, institution name, title lines, and all geometry
    — comes from cover_layouts.get_cover_layout(node.subtype); this handler is the
    generic emitter that turns that spec into a tikzpicture.  Built with
    `remember picture, overlay` anchored to `current page` so it ignores the 1in
    text block and covers the whole sheet; coordinates are measured DOWN from the
    top-left (metrics are origin-top-left points).  No running header / page
    number (\thispagestyle{empty}); a trailing \clearpage ends the page.  The
    layout's assets are shipped into the bundle root by latex_export.
    """
    layout = get_cover_layout(node.subtype)
    m = layout.metrics
    bg_img, logo_img = layout.assets[0], layout.assets[1]
    title_tex = " \\\\\n".join(_escape_latex(ln) for ln in layout.title_builder(data))
    institution_tex = "\\\\".join(_escape_latex(ln) for ln in layout.institution_lines)
    report_number = _escape_latex(data.get("report_number", ""))
    report_date = _escape_latex(data.get("report_date", ""))

    # Brand palette → \definecolor{cover<key>}{HTML}{...}; the nodes below
    # reference cover<title>/cover<meta>/etc.
    color_defs = "".join(
        f"  \\definecolor{{cover{k}}}{{HTML}}{{{v}}}\n"
        for k, v in layout.palette.items()
    )

    bg_top = m["bg_top"]
    band_h = m["band_height"]
    # Accent-bar polygons: dark block from explicit vertices; green block from its
    # two left vertices then the two page-east corners at the bar top/bottom.
    dark_pts = " -- ".join(_cover_point(x, y) for x, y in m["bar_dark"])
    green_left = " -- ".join(_cover_point(x, y) for x, y in m["bar_green_left"])
    green_pts = (
        f"{green_left} -- "
        f"{_cover_point(0, m['bar_bottom'], corner='north east')} -- "
        f"{_cover_point(0, m['bar_top'], corner='north east')}"
    )

    return (
        "% cover node — full-bleed branded cover (layout: " + layout.name + ")\n"
        "\\thispagestyle{empty}%\n"
        + color_defs
        + "\\begin{tikzpicture}[remember picture, overlay]\n"
        # Brand-color field from bg_top to the page bottom.
        f"  \\fill[coversage] {_cover_point(0, bg_top)} rectangle (current page.south east);\n"
        # Background image (hexagon pattern) across the same field.
        f"  \\node[anchor=north west, inner sep=0pt] at {_cover_point(0, bg_top)} "
        f"{{\\includegraphics[width=\\paperwidth, height=\\dimexpr\\paperheight-{bg_top}pt\\relax]{{{bg_img}}}}};\n"
        # White institution band across the top.
        f"  \\fill[white] (current page.north west) rectangle {_cover_point(0, band_h, corner='north east')};\n"
        # Logo badge, top-left of the band.
        f"  \\node[anchor=north west, inner sep=0pt] at {_cover_point(m['logo_x'], m['logo_y'])} "
        f"{{\\includegraphics[height={m['logo_height']}pt]{{{logo_img}}}}};\n"
        # Institution text, to the right of the badge.
        f"  \\node[anchor=north west, text=covertitle, font=\\sffamily\\bfseries\\fontsize{{{m['institution_size']}}}{{16}}\\selectfont, align=left] "
        f"at {_cover_point(m['institution_x'], m['institution_y'])} {{{institution_tex}}};\n"
        # Bicolor accent bar: two parallelograms with a slanted white gap between.
        f"  \\fill[coverdarkgray] {dark_pts} -- cycle;\n"
        f"  \\fill[covergreen] {green_pts} -- cycle;\n"
        # Title block.
        f"  \\node[anchor=north west, text=covertitle, font=\\sffamily\\bfseries\\fontsize{{{m['title_size']}}}{{{m['title_leading']}}}\\selectfont, align=left, text width={m['title_width_frac']}\\paperwidth] "
        f"at {_cover_point(m['title_x'], m['title_y'])} {{{title_tex}}};\n"
        # Report number + date under the title.
        f"  \\node[anchor=north west, text=covermeta, font=\\sffamily\\fontsize{{{m['meta_size']}}}{{14}}\\selectfont] "
        f"at {_cover_point(m['meta_x'], m['report_number_y'])} {{{report_number}}};\n"
        f"  \\node[anchor=north west, text=covermeta, font=\\sffamily\\fontsize{{{m['meta_size']}}}{{14}}\\selectfont] "
        f"at {_cover_point(m['meta_x'], m['report_date_y'])} {{{report_date}}};\n"
        "\\end{tikzpicture}%\n"
        "\\clearpage"
    )


def _render_title_page(node: DocNode, data: dict) -> str:
    r"""
    Inner title page (page 2) — centered title block, report number/date, and the
    publisher block, driven by the node's cover subtype (same layout the cover
    uses: shared title_builder + publisher_builder).  Mirrors
    html_generator._render_cover (the HTML surface folds the title block into its
    "cover" node).  Normal margins, no running header, no page number; a trailing
    \clearpage ends it before the front matter.
    """
    layout = get_cover_layout(node.subtype)
    title_tex = " \\\\\n".join(_escape_latex(ln) for ln in layout.title_builder(data))

    report_number = _escape_latex(data.get("report_number", ""))
    report_date = _escape_latex(data.get("report_date", ""))
    report_block = " \\\\\n".join(x for x in (report_number, report_date) if x)

    pub_block = " \\\\\n".join(
        _escape_latex(ln) for ln in layout.publisher_builder(data)
    )

    parts = [
        "% title-page node — centered inner title page (layout: " + layout.name + ")",
        "\\thispagestyle{empty}%",
        "\\begin{center}",
        "\\vspace*{1.4in}",
        "{\\sffamily\\bfseries\\large\n" + title_tex + "\\par}",
    ]
    if report_block:
        parts.append("\\vspace{2.5em}\n{" + report_block + "\\par}")
    parts.append("\\vspace{3em}\n{" + pub_block + "\\par}")
    parts.append("\\end{center}")
    parts.append("\\clearpage")
    return "\n".join(parts)


def _render_unimplemented(node: DocNode, data: dict) -> str:
    """
    Catch-all for node_types not yet ported (table, bmd-summary,
    genomics-section, narrative+tables, incidence-table).

    Emits this node's heading (if it has one) plus a visible pending
    placeholder.  The .tex still compiles cleanly; the author sees the
    structural gap in Overleaf and knows what's outstanding.

    For level=0 nodes (cover, title-page, individual table nodes), there
    is no heading to anchor on, so we leave a comment with the node id so
    a future session can grep the output to verify the right placeholders
    appeared in the right places.
    """
    heading = _heading(node.level, node.title) if node.level > 0 else ""
    placeholder = _pending_placeholder(node.node_type)
    if heading:
        return f"{heading}\n\n{placeholder}"
    return (
        f"% {node.node_type} node {node.id} — pending implementation\n"
        f"{placeholder}"
    )


# Dispatch table — one entry per DocNode.node_type value.  Anything not
# listed here falls through to _render_unimplemented.
#
# cover / title-page ARE rendered here now (a full-bleed branded cover +
# centered inner title page, ported from the approved Typst layout) — the
# old decision-#6 \\maketitle path is retired (see _document_skeleton and the
# ADR note).  So LATEX_OMITS is empty and both types have real emitters.
_DISPATCH: dict[str, object] = {
    "cover":             _render_cover,
    "title-page":        _render_title_page,
    "front-matter":      _render_front_matter,
    "narrative":         _render_narrative,
    "heading-only":      _render_heading_only,
    "appendix":          _render_appendix,
    "tables-list":       _render_tables_list,
    "toc":               _render_toc,
    "narrative+tables":  _render_narrative_tables,
    "table":             _render_apical_table,
    "incidence-table":   _render_incidence_table,
    "figure":            _render_figure,
    "sample-counts-table": _render_sample_counts_table,
    "bmd-summary":       _render_bmd_summary,
    "genomics-section":  _render_genomics_section,
    "freeform-page":     _render_freeform_page,
    "freeform-block":    _render_freeform_block,
    "page-break":        _render_page_break,
}

# ADR-0006 #3: fail loudly at import if this table drifts from the canonical
# registry.  LaTeX omits cover/title-page (handled by \maketitle, decision #6),
# declared via LATEX_OMITS rather than left as a silent gap.
assert_dispatch_covers(_DISPATCH, renderer="LaTeX", allow_omit=LATEX_OMITS)


# ---------------------------------------------------------------------------
# Tree walk
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ADR-0005 round-trip anchors + override overlay
# ---------------------------------------------------------------------------
# Every rendered node (and each sub-addressable genomics content item) is
# wrapped in a pair of sentinel COMMENTS keyed to its stable id, so the
# round-trip reconciler can map an edited .tex region back to the node it owns.
# The sentinel FORMAT lives in roundtrip.anchors (imported as `_anchor` at the
# top of this module) — owned there so writer (this generator) and reader (the
# reconciler) can't drift.  The override overlay below is app-side: it decides
# how a stored human edit replaces freshly generated content at render time.


def _apply_override(generated: str, overrides: dict, anchor_id: str, data: dict) -> str:
    """
    Replace a freshly generated region with its user-owned override, if any.

    The override's latex_region is emitted verbatim — the user owns this region
    (ADR-0005 "override wins, never silently recomputed").  When the override's
    base_hash no longer matches the freshly generated region, the underlying
    data has drifted since the human edited it: the override STILL wins (it is
    returned), but the anchor id is recorded under data["_override_stale"] so
    the app can flag it for review rather than silently masking the change.

    Returns the region to emit (the override when present, else `generated`).
    """
    override = overrides.get(anchor_id)
    if not override:
        return generated
    base = override.get("base_hash")
    if base and base != region_hash(generated):
        data.setdefault("_override_stale", []).append(anchor_id)
    return override.get("latex_region", generated)


# ---------------------------------------------------------------------------
# Per-content-type layout styling (the LaTeX half of the abstract spec)
# ---------------------------------------------------------------------------
# resolve_layout_style (layout_style.py) merges the document's styles config
# down to ONE flat dict per node; _layout_to_latex translates that abstract
# spec into the surrounding LaTeX markup.  The HTML twin emits the SAME resolved
# spec as CSS rules (html_generator), so the two surfaces can't drift (ADR-0006).
# An empty spec ⇒ ("", "") ⇒ the chunk is untouched, so a document with no
# `styles` block compiles byte-identically to before this feature.

_FONT_FAMILY_CMD = {"serif": r"\rmfamily", "sans": r"\sffamily", "mono": r"\ttfamily"}
_ALIGN_CMD = {"left": r"\raggedright", "right": r"\raggedleft", "center": r"\centering"}
# justify is LaTeX's default (fully-justified) → no declaration emitted.


def _fmt_num(x: float) -> str:
    """Format a computed number without trailing-zero noise (15.40 → '15.4')."""
    s = f"{x:.4f}".rstrip("0").rstrip(".")
    return s or "0"


def _parse_length(value: str) -> "tuple[float, str] | None":
    """Split a validated length like '11pt' into (11.0, 'pt'); None if unparseable."""
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)(pt|mm|cm|in|em|ex)", value or "")
    if not m:
        return None
    return float(m.group(1)), m.group(2)


def _expand_hex(color: str) -> str:
    """'#abc' → 'AABBCC', '#aabbcc' → 'AABBCC' (xcolor HTML model wants 6 upper hex)."""
    h = color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return h.upper()


def _layout_to_latex(style: dict) -> "tuple[str, str]":
    r"""
    Translate one resolved abstract style spec into surrounding LaTeX markup.

    Returns ``(pre, post)`` such that ``pre + chunk + post`` renders the chunk
    with the requested typography and flow.  Font/color/alignment/indent are
    scoped in a group ``{ ... \par}`` (the trailing ``\par`` flushes the
    paragraph while the size/leading is still active — the standard LaTeX
    size-change gotcha); vertical space and page breaks sit OUTSIDE the group,
    and ``keep_together`` wraps everything in an unbreakable minipage.

    An empty / falsy spec returns ``("", "")`` — the no-op that keeps a
    style-less document byte-identical to the pre-feature output.
    """
    if not style:
        return "", ""

    # --- inside-the-group declarations (font, color, alignment, indent) ---
    decls: list[str] = []
    # Font precedence (see layout_style.LAYOUT_KEY_SCHEMA): an explicit `font`
    # (literal family name) wins via fontspec's \fontspec; otherwise the abstract
    # `font_family` maps to \rmfamily/\sffamily/\ttfamily.  The \fontspec call is
    # GUARDED by \ifdefined\fontspec so it is inert under pdflatex+lmodern (the
    # class's current engine — the true-branch tokens are skipped, not executed,
    # when fontspec is absent) and active under XeTeX/LuaTeX with fontspec loaded
    # (the `tect`/Overleaf path, where the named system font must be installed).
    font_name = (style.get("font") or "").strip()
    if font_name:
        decls.append(rf"\ifdefined\fontspec\fontspec{{{font_name}}}\fi")
    else:
        fam = _FONT_FAMILY_CMD.get(style.get("font_family"))
        if fam:
            decls.append(fam)

    size = style.get("font_size")
    line_height = style.get("line_height")
    if size:
        parsed = _parse_length(size)
        if parsed:
            num, unit = parsed
            lead = num * (line_height if isinstance(line_height, (int, float)) else 1.2)
            decls.append(rf"\fontsize{{{size}}}{{{_fmt_num(lead)}{unit}}}\selectfont")
    elif isinstance(line_height, (int, float)):
        # Leading multiplier with no explicit size → scale the current size.
        decls.append(rf"\linespread{{{_fmt_num(line_height)}}}\selectfont")

    if style.get("weight") == "bold":
        decls.append(r"\bfseries")
    if style.get("style") == "italic":
        decls.append(r"\itshape")

    color = style.get("color")
    if color:
        h = _expand_hex(color)
        name = "ctcolor" + h.lower()
        decls.append(rf"\definecolor{{{name}}}{{HTML}}{{{h}}}\color{{{name}}}")

    align = _ALIGN_CMD.get(style.get("align"))
    if align:
        decls.append(align)

    indent = style.get("first_line_indent")
    if indent and _parse_length(indent):
        decls.append(rf"\setlength\parindent{{{indent}}}")

    # letter_spacing → soul's \sodef defines a per-node tracking macro (\rlmls),
    # scoped INSIDE this declaration group so it never leaks.  soul spaces by a
    # FIXED width, so an em/ex value (no resolvable size here) is rejected — only
    # an absolute length drives it, matching the docx surface (w:spacing twips).
    # The word/outer inter-word spaces are soul's documented sensible defaults;
    # only the inter-LETTER space (2nd arg) carries the requested value.  The
    # \rlmls{...} WRAP is emitted below alongside \uppercase (both wrap the chunk).
    letter_spacing = style.get("letter_spacing")
    ls_abs = bool(letter_spacing and _parse_length(letter_spacing)
                  and not letter_spacing.endswith(("em", "ex")))
    if ls_abs:
        decls.append(
            rf"\sodef\rlmls{{}}{{{letter_spacing}}}"
            r"{.5em plus.1em minus.1em}{1em plus.1em minus.1em}"
        )

    # --- outside-the-group flow (space + page breaks) and keep-together box ---
    pre_parts: list[str] = []
    post_parts: list[str] = []

    if style.get("break_before") == "page":
        pre_parts.append("\\clearpage")
    sb = style.get("space_before")
    if sb and _parse_length(sb):
        pre_parts.append(rf"\vspace{{{sb}}}")
    keep = style.get("keep_together") is True
    if keep:
        pre_parts.append(r"\begin{minipage}{\linewidth}")

    if decls:
        pre_parts.append("{" + "".join(decls))
        post_parts.append(r"\par}")

    # text_transform: uppercase → the TeX primitive \uppercase wrapped INNERMOST
    # around the chunk, independent of the decls group so it applies with or
    # without other declarations.  We use the primitive, NOT \MakeUppercase:
    # \MakeUppercase is not \long, so a \par (blank line) inside its argument is a
    # hard error — and a node chunk is multi-paragraph (heading + body).
    # \uppercase reads a balanced group and tolerates \par (verified by a real
    # tect compile), uppercasing character tokens while leaving control sequences
    # (\section, \emph, \clearpage) intact.  Like CSS/Word it covers the whole
    # node's text (parity: the CSS div and docx run-loop both cover heading+body).
    # Caveat: \uppercase is ASCII-oriented (no LICR/accent handling) — fine for the
    # display title this targets.  Closes BEFORE \par} (the group flush).
    if style.get("text_transform") == "uppercase":
        pre_parts.append(r"\uppercase{")
        post_parts.insert(0, "}")

    # letter_spacing wrap: \rlmls{...} (defined by the \sodef decl above), nested
    # INNERMOST — inside \uppercase so soul receives already-cased character
    # tokens (\uppercase leaves the \rlmls control sequence intact; soul is
    # finicky with macros in its own argument, so it must be the inner one).
    if ls_abs:
        pre_parts.append(r"\rlmls{")
        post_parts.insert(0, "}")

    if keep:
        post_parts.append(r"\end{minipage}")
    sa = style.get("space_after")
    if sa and _parse_length(sa):
        post_parts.append(rf"\vspace{{{sa}}}")
    if style.get("break_after") == "page":
        post_parts.append("\\clearpage")

    pre = "\n".join(pre_parts)
    if pre:
        pre += "\n"
    post = "\n".join(post_parts)
    if post:
        post = "\n" + post
    return pre, post


def _walk_latex(node: DocNode, data: dict) -> list[str]:
    """
    Render a node and its descendants to a flat, document-ordered list of
    LaTeX chunks; the caller joins them with blank lines to produce the body.

    Thin wrapper over the shared render_common.walk_emit skeleton (ADR-0006):
    the traversal + accumulator are common, only the LaTeX-specific emit below
    is passed in.  Same skeleton as html_generator._walk_html.
    """
    layout_cfg = data.get("layout_style")

    def _wrap_style(n: DocNode, chunk: str) -> str:
        # Per-content-type typography/flow.  The DECISION (resolved spec) is
        # shared with HTML via data["layout_style"]; only this LaTeX WRAP is
        # surface-specific.  Empty cfg → resolve_layout_style returns {} →
        # _layout_to_latex returns ("", "") → chunk unchanged (byte-identical).
        pre, post = _layout_to_latex(
            resolve_layout_style(layout_cfg, n.node_type, n.id)
        )
        return pre + chunk + post

    def _wrap_post(n: DocNode, chunk: str) -> str:
        # ADR-0005: if a human owns this region (edited and reconciled into the
        # override store), emit their version verbatim instead of the generated
        # one.  Applied AFTER the orientation wrap so the override region matches
        # exactly what sits between the sentinels.
        chunk = _apply_override(chunk, data.get("overrides") or {}, n.id, data)
        # Then bracket the whole node block in begin/end sentinels keyed to
        # node.id, so the round-trip reconciler can attribute an edited region
        # back to this node.  Inert in the PDF.
        return _anchor("node", n.id, chunk)

    # wrap_post carries the override+anchor that HTML deliberately omits — the
    # ONE intentional surface divergence (HTML is the on-screen preview, LaTeX
    # the Overleaf round-trip surface).  See the divergence-#2 TODO in memory.
    return walk_emit(
        node, data,
        walk=walk_tree,
        dispatch=_DISPATCH,
        fallback=_render_unimplemented,
        # pdflscape rotates both the content and the PDF page, so Overleaf shows
        # it landscape.
        wrap_landscape=lambda chunk: "\\begin{landscape}\n" + chunk + "\n\\end{landscape}",
        wrap_style=_wrap_style,
        wrap_post=_wrap_post,
    )


# ---------------------------------------------------------------------------
# Document skeleton
# ---------------------------------------------------------------------------

def _document_skeleton(
    title: str, author: str, body: str, running_header: str = ""
) -> str:
    r"""
    Wrap a rendered body in the outer LaTeX document scaffolding for a
    full-report compile.

    The cover page and inner title page are now rendered as tree NODES (the
    first two `front`-region children → _render_cover / _render_title_page in
    `body`), not by \maketitle — so this skeleton no longer emits \maketitle or
    a \title/\author block.  The old decision-#6 \maketitle path is retired (see
    the ADR note).  The Table of Contents is likewise a `toc` node in the tree
    (ADR-0003), rendered as native \tableofcontents.

    The class file (niehs.cls) owns page geometry, fonts, the niehstable
    environment, and the fancyhdr running header — this function only
    emits the structural skeleton and feeds the header its text.

    Args:
        running_header: the per-page running-header title.  niehs.cls
            defines \niehsrunningheader empty; we \renewcommand it here so
            the header carries the full report title on every content page
            (the cover / title-page nodes set \thispagestyle{empty}, so no
            header shows there).  Must already be LaTeX-escaped.
    """
    # `title`/`author` are intentionally unused now that \maketitle is gone —
    # the cover/title-page nodes render the title from the data dict.  Kept in
    # the signature so callers (_doc_metadata unpacking) don't change.
    del title, author
    # Strings are concatenated rather than f-format'd to avoid the
    # double-brace escaping noise that .format() requires.  LaTeX is
    # already brace-heavy; readability wins.
    return (
        "\\documentclass{niehs}\n"
        "\n"
        "\\renewcommand{\\niehsrunningheader}{" + running_header + "}\n"
        "\n"
        "\\begin{document}\n"
        # Front matter is numbered in roman (NIEHS Report 10).  Set before the
        # body renders; the cover node's \thispagestyle{empty} keeps page i
        # unnumbered, and the body switches to arabic via \pagenumbering{arabic}
        # injected into `body` at the front-matter/body boundary (generate_latex).
        "\\pagenumbering{roman}\n"
        "\n"
        + body + "\n"
        "\n"
        "\\end{document}\n"
    )


def _fragment_skeleton(body: str) -> str:
    r"""
    Wrap a rendered body in the minimal LaTeX scaffolding needed to
    compile it as a stand-alone fragment (the preview path per decision
    #10).

    What's stripped vs the full document
    ------------------------------------
    A fragment compile is the path the web app hits when the user clicks
    "Preview Apical" or "Preview BMD Summary".  It does NOT need:

      - title page (\maketitle, no metadata block)
      - table of contents
      - front matter (foreword, abstract, peer review, etc.)
      - any other top-level body sections beyond the selected subtree

    The compile budget on Overleaf for a fragment is ~2-5 seconds vs
    ~20-30 for the full report; stripping everything outside the requested
    subtree is what makes the iteration loop tolerable.

    Why a tiny header is still required
    -----------------------------------
    LaTeX cannot compile bare body content — every fragment needs a
    \documentclass, a \begin{document} ... \end{document} pair, and any
    packages the body uses (niehstable env depends on threeparttable +
    table float, both of which niehs.cls loads).  So we still emit those.
    """
    return (
        "\\documentclass{niehs}\n"
        "\n"
        "\\begin{document}\n"
        + body + "\n"
        "\\end{document}\n"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_latex(
    data: dict,
    section_filter: str | None = None,
    tree: "list | None" = None,
) -> str:
    """
    Walk the document tree + data and produce a complete report.tex source string.

    Args:
        data:           The same dict marshal_export_data builds for Typst.
                        Top-level keys are content blobs addressed by
                        DocNode.data_key (e.g., data["background"] holds
                        {"paragraphs": [...]}, data["abstract"] holds the
                        structured abstract sections, etc.).
        section_filter: For the fragment-compile preview path (decision
                        #10).  When set, only the subtree rooted at the
                        given node id renders.  Tracer-bullet ignores
                        this — full walk only.  Threaded through now so
                        the public signature is stable.
        tree:           Optional per-session document tree.  When None (the
                        default), the global DOCUMENT_TREE is used, so existing
                        callers are byte-identical.  The HTML twin threads the
                        same param — the two renderers stay in lockstep
                        (ADR-0006); ADR-0007 follow-on per-session structure.

    Returns:
        A self-contained .tex source string.  The caller is responsible
        for placing latex/niehs.cls alongside it before invoking pdflatex.
    """
    # ── Fragment-compile path (decision #10) ─────────────────────────
    # When section_filter is set, return a stand-alone .tex containing
    # only the subtree at that node id.  This is what the web app's
    # per-tab preview button hits.  Front matter, TOC, and \maketitle
    # are all stripped — see _fragment_skeleton's docstring for why.
    if section_filter:
        node = find_node(section_filter, tree)
        if node is None:
            # Unknown id → empty fragment with a comment so callers can
            # detect the miss without crashing.  No exception, because
            # the web app may pass user-controlled ids and we'd rather
            # show a blank preview than 500 the request.
            body = f"% No node found for section_filter={section_filter!r}\n"
            return _fragment_skeleton(body)
        body_chunks = _walk_latex(node, data)
        return _fragment_skeleton("\n\n".join(body_chunks))

    # ── Full-report path ─────────────────────────────────────────────
    # Self-contained document = the same skeleton wrapped around the body.
    # Kept for tests, fragment previews, and any caller that wants one file.
    title, author, running_header = _doc_metadata(data)
    return _document_skeleton(
        title=title, author=author,
        body=generate_report_body(data, tree=tree), running_header=running_header,
    )


def _doc_metadata(data: dict) -> "tuple[str, str, str]":
    """
    (title, author, running_header) for the document skeleton, escaped.

    marshal_export_data fills these from the session test-article forms;
    scaffold_report_data supplies smoke-test defaults.  running_header is the
    dedicated never-abbreviated title form (same source the HTML preview uses,
    so both surfaces show an identical header), falling back to the title.
    """
    title = _escape_latex(data.get("title", "5dToxReport"))
    author = _escape_latex(
        data.get("author", "NIEHS Division of Translational Toxicology")
    )
    running_header = _escape_latex(
        data.get("running_header") or data.get("title", "5dToxReport")
    )
    return title, author, running_header


def generate_report_body(data: dict, tree: "list | None" = None) -> str:
    r"""
    Render just the report BODY — sections + round-trip anchors, no preamble.

    This is `report.tex` in the split (Option B) Overleaf bundle: `main.tex`
    holds the preamble and `\input{report}`s this.  Keeping the body in its own
    file makes the structure/prose boundary physical — the preamble (main.tex)
    is app-owned, the anchored body (report.tex) is what the committee edits and
    the reconciler diffs.

    Page numbering switches from roman (front matter) to arabic (body) at the
    body's first top-level node — the boundary the tree owns via
    first_body_node_id() (region == "body", ADR-0004 amendment d) so the LaTeX
    and HTML renderers can't drift on where the switch lands.  \clearpage
    flushes pending floats so the switch lands on the body's opening page.

    `tree` defaults to the global DOCUMENT_TREE; a per-session tree renders that
    session's own structure (ADR-0007 follow-on).
    """
    nodes = tree if tree is not None else DOCUMENT_TREE
    body_first_id = first_body_node_id(nodes)
    body_chunks: list[str] = []
    for top in nodes:
        if top.id == body_first_id:
            body_chunks.append("\\clearpage\n\\pagenumbering{arabic}")
        body_chunks.extend(_walk_latex(top, data))
    # Paragraph break between every chunk; LaTeX collapses consecutive blank
    # lines into one paragraph break, so this is safe even when chunks end in
    # newlines.
    return "\n\n".join(body_chunks)


def generate_main_tex(data: dict) -> str:
    r"""
    Render `main.tex` — the Overleaf entry document for the split bundle.

    Same preamble/skeleton as the self-contained generate_latex, but its body is
    just `\input{report}` (no extension → LaTeX reads report.tex).  This matches
    Overleaf's default main-document convention (main.tex), so no per-project
    "set main document" step is needed, and it keeps the editable, anchored body
    isolated in report.tex.
    """
    title, author, running_header = _doc_metadata(data)
    return _document_skeleton(
        title=title, author=author,
        body="\\input{report}", running_header=running_header,
    )
