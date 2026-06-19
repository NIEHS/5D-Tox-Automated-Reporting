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
    front_matter_plan,
    has_paragraph_content,
    assert_dispatch_covers,
    walk_emit,
    LATEX_OMITS,
    incidence_table_plan,
    apical_table_plan,
    unified_narrative_paragraphs,
    bmd_summary_plan,
    BMD_SUMMARY_HEADERS,
    appendix_roster_rows,
    methods_subsection_content,
    genomics_role,
    genomics_intro_paragraphs,
    genomics_entries,
    gene_set_table_rows,
    gene_table_rows,
    genomics_description_items,
    genomics_chart_caption,
    GENE_SET_TABLE_HEADERS,
    GENE_TABLE_HEADERS,
    find_apical_section as _find_apical_section,
    table_caption as _table_caption,
)
from genomics_content import genomics_content_plan
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
_UNICODE_TO_LATEX: list[tuple[str, str]] = [
    ("≤", r"\ensuremath{\le}"),   # ≤
    ("≥", r"\ensuremath{\ge}"),   # ≥
    # Subscript digits ₀–₉ → \textsubscript{N}
    *((chr(0x2080 + d), rf"\textsubscript{{{d}}}") for d in range(10)),
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


def _render_paragraphs(paragraphs: list[str]) -> str:
    """
    Render a flat list of paragraph strings as LaTeX, separated by blank
    lines (which TeX interprets as paragraph breaks).

    Each paragraph is escaped individually, with embedded URLs spliced into
    breakable \\url{} links (see _splice_urls — this is what keeps long
    reference URLs from overflowing the margin).  Returns "" for empty input
    so callers can detect "no content" and substitute a placeholder.
    """
    if not paragraphs:
        return ""
    return "\n\n".join(_splice_urls(p) for p in paragraphs)


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


def _render_front_matter(node: DocNode, data: dict) -> str:
    """
    Front-matter section (foreword, about, peer review, publication
    details, acknowledgments, abstract).

    Renders as a heading plus the section's paragraphs.  The content lives
    at data[node.data_key] as a dict with a "paragraphs" key holding a
    list of strings — same shape Typst consumes.  If content is missing or
    empty, we emit a "[Section pending]" placeholder so the structure
    stays visible (decision #8).

    ADR-0006: the content-source decision (labeled-sections vs paragraphs vs
    nothing) is the shared render_common.front_matter_plan EXTRACT; only the
    LaTeX markup below — and the format-dependent "empty body → pending"
    fallback — is EMIT and lives here.
    """
    plan = front_matter_plan(node, data)
    if plan.kind == "labeled":
        body = _render_labeled_sections(plan.labeled_parts)
    else:
        # "paragraphs" carries the flat list; "none" carries [] → "" → pending.
        body = _render_paragraphs(plan.paragraphs)
    if not body:
        body = f"\\emph{{[Section pending: {_escape_latex(node.title)}]}}"
    return f"{_heading(node.level, node.title)}\n\n{body}"


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

    Methods subsections set node.methods_key and store their content in
    data["methods"]["sections"] (a flat list keyed by heading), not at
    data[data_key]["paragraphs"].  We detect that case and route to the
    methods-specific lookup.
    """
    if node.methods_key:
        return _render_methods_subsection(node, data)
    return _render_front_matter(node, data)


def _render_methods_subsection(node: DocNode, data: dict) -> str:
    """
    M&M subsection — content lives in data["methods"]["sections"] as a
    flat list of {level, key, heading, paragraphs, [table]} dicts.  The
    node-to-section match is by the stable methods_key (see
    methods_subsection_content); the heading is display text only.
    """
    # ADR-0006 Amendment 1: the heading-match lookup and content-present
    # decision are shared; the markup is LaTeX emit.  The inline table (e.g. the
    # Final Sample Counts table under Transcriptomics → Sample Collection)
    # renders after the prose.
    paragraphs, inline = methods_subsection_content(node, data)
    body = _render_paragraphs(paragraphs) if has_paragraph_content(paragraphs) else ""
    if inline is not None:
        body = (body + "\n\n" + _render_inline_table(inline)).strip()
    if not body:
        body = f"\\emph{{[Section pending: {_escape_latex(node.title)}]}}"
    return f"{_heading(node.level, node.title)}\n\n{body}"


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

    Appendix B (Animal Identifiers) renders the animal roster from
    data["appendix_animals"] when the session supplied it.  The other
    appendices are not yet wired to data, so they emit a visible
    "[Appendix body pending]" line so the author knows to expect content.
    """
    heading = _heading(node.level, node.title)
    rows = appendix_roster_rows(node, data)
    if rows is not None:
        return f"{heading}\n\n{_emit_animal_roster(rows)}"
    body = f"\\emph{{[Appendix body pending: {_escape_latex(node.title)}]}}"
    return f"{heading}\n\n{body}"


def _emit_animal_roster(rows: list[list[str]]) -> str:
    r"""
    EMIT the Appendix B animal roster as a page-breaking longtable.

    ~300 animals don't fit one page, and the niehstable float can't break
    across pages — so this uses longtable (loaded by niehs.cls), whose
    \endhead repeats the column header on every page.  Rows come pre-built
    (animal_id, sex, dose) from appendix_roster_rows (ADR-0006 Amendment 1).

    Each cell is escaped exactly once (by _emit_tabular_row) — matching the
    HTML roster's single-escape.  This converges a pre-existing divergence:
    the old code pre-escaped animal_id/sex and then _emit_tabular_row escaped
    them again (a latent double-escape, harmless for plain IDs but wrong for an
    id carrying LaTeX specials).
    """
    head = (
        "\\begin{longtable}{l l r}\n"
        "\\toprule\n"
        "Animal ID & Sex & Dose (mg/kg) \\\\\n"
        "\\midrule\n"
        "\\endhead\n"
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
    """
    # ADR-0006 Amendment 1: the narrative-paragraph selection AND the
    # content-present decision are shared; only the markup is LaTeX emit.
    paragraphs = unified_narrative_paragraphs(node, data)
    if has_paragraph_content(paragraphs):
        body = _render_paragraphs(paragraphs)
    else:
        body = f"\\emph{{[Narrative pending: {_escape_latex(node.title)}]}}"
    return f"{_heading(node.level, node.title)}\n\n{body}"


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
        organ = (entry.get("organ") or "").capitalize()
        sex = (entry.get("sex") or "").capitalize()
        sub_title = f"{organ}, {sex}"
        blocks.append(f"\\subsubsection{{{_escape_latex(sub_title)}}}")

        # Each (organ, sex) block is an ordered list of sub-addressable content
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


def _render_gene_set_table(entry: dict) -> str:
    """
    Render the top-gene-sets table for one (organ, sex) of a genomics
    section.  Schema (per gene_sets[i]):
      rank, go_id, go_term, bmd, bmdl, n_genes, direction.
    """
    rows = gene_set_table_rows(entry)
    if rows is None:
        return f"\\emph{{[Top gene sets pending: {_escape_latex(entry.get('organ', ''))}, {_escape_latex(entry.get('sex', ''))}]}}"

    colspec = "l l l r r r l"
    lines = [f"\\begin{{tabular}}{{{colspec}}}", "\\toprule",
             _emit_tabular_row(list(GENE_SET_TABLE_HEADERS)), "\\midrule"]
    for cells in rows:
        lines.append(_emit_tabular_row(cells))
    lines.append("\\bottomrule")
    lines.append("\\end{tabular}")
    # Scale-to-fit: unlike apical tables (which float through the niehstable
    # environment and get its adjustbox wrap), these genomics gene/gene-set
    # tables are emitted inline inside the genomics section as a bare tabular.
    # Wrap the bare tabular in the same "max width=\linewidth" adjustbox so a
    # wide 7-column table shrinks to the text width instead of overflowing the
    # margin; a table that already fits is left at natural size.
    return "\\adjustbox{max width=\\linewidth}{%\n" + "\n".join(lines) + "\n}"


def _render_gene_table(entry: dict) -> str:
    """
    Render the top-genes table for one (organ, sex) of a gene BMD section.
    Schema (per top_genes[i]):
      rank, gene, bmd, bmdl, direction, fold_change.
    """
    rows = gene_table_rows(entry)
    if rows is None:
        return f"\\emph{{[Top genes pending: {_escape_latex(entry.get('organ', ''))}, {_escape_latex(entry.get('sex', ''))}]}}"

    colspec = "l l r r l r"
    lines = [f"\\begin{{tabular}}{{{colspec}}}", "\\toprule",
             _emit_tabular_row(list(GENE_TABLE_HEADERS)), "\\midrule"]
    for cells in rows:
        lines.append(_emit_tabular_row(cells))
    lines.append("\\bottomrule")
    lines.append("\\end{tabular}")
    # Scale-to-fit: unlike apical tables (which float through the niehstable
    # environment and get its adjustbox wrap), these genomics gene/gene-set
    # tables are emitted inline inside the genomics section as a bare tabular.
    # Wrap the bare tabular in the same "max width=\linewidth" adjustbox so a
    # wide 7-column table shrinks to the text width instead of overflowing the
    # margin; a table that already fits is left at natural size.
    return "\\adjustbox{max width=\\linewidth}{%\n" + "\n".join(lines) + "\n}"


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


def _render_unimplemented(node: DocNode, data: dict) -> str:
    """
    Catch-all for node_types not yet ported (table, bmd-summary,
    genomics-section, narrative+tables, incidence-table, cover, title-page).

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
# Cover and title-page deliberately stay unimplemented per decision #6
# (skip cover in v1, use \\maketitle for the title page) — the outer
# \\maketitle call in _document_skeleton handles that page, so the
# corresponding tree nodes simply emit a comment-only placeholder.
_DISPATCH: dict[str, object] = {
    "front-matter":      _render_front_matter,
    "narrative":         _render_narrative,
    "heading-only":      _render_heading_only,
    "appendix":          _render_appendix,
    "tables-list":       _render_tables_list,
    "toc":               _render_toc,
    "narrative+tables":  _render_narrative_tables,
    "table":             _render_apical_table,
    "incidence-table":   _render_incidence_table,
    "bmd-summary":       _render_bmd_summary,
    "genomics-section":  _render_genomics_section,
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


def _walk_latex(node: DocNode, data: dict) -> list[str]:
    """
    Render a node and its descendants to a flat, document-ordered list of
    LaTeX chunks; the caller joins them with blank lines to produce the body.

    Thin wrapper over the shared render_common.walk_emit skeleton (ADR-0006):
    the traversal + accumulator are common, only the LaTeX-specific emit below
    is passed in.  Same skeleton as html_generator._walk_html.
    """
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

    Per decision #6 we skip the NIEHS-branded cover and use \maketitle.
    The Table of Contents is no longer emitted here: it is a `toc` node in the
    document tree (ADR-0003), rendered as native \tableofcontents (which LaTeX
    auto-populates from the \section commands the body emits).

    The class file (niehs.cls) owns page geometry, fonts, the niehstable
    environment, and the fancyhdr running header — this function only
    emits the structural skeleton and feeds the header its text.

    Args:
        running_header: the per-page running-header title.  niehs.cls
            defines \niehsrunningheader empty; we \renewcommand it here so
            the header (which the class shows from the page after
            \maketitle onward) carries the full report title, matching the
            reference and the HTML preview.  Must already be LaTeX-escaped.
    """
    # Strings are concatenated rather than f-format'd to avoid the
    # double-brace escaping noise that .format() requires.  LaTeX is
    # already brace-heavy; readability wins.
    return (
        "\\documentclass{niehs}\n"
        "\n"
        "\\title{" + title + "}\n"
        "\\author{" + author + "}\n"
        "\\date{\\today}\n"
        "\\renewcommand{\\niehsrunningheader}{" + running_header + "}\n"
        "\n"
        "\\begin{document}\n"
        # Front matter is numbered in roman (NIEHS Report 10).  Set this
        # before \maketitle so the title page is page i; the body switches
        # to arabic via a \pagenumbering{arabic} injected into `body` at the
        # front-matter/body boundary (see generate_latex).
        "\\pagenumbering{roman}\n"
        "\\maketitle\n"
        # No visible number on the title page — the reference shows a
        # date/ISSN footer there, not a page number.
        "\\thispagestyle{empty}\n"
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
) -> str:
    """
    Walk DOCUMENT_TREE + data and produce a complete report.tex source string.

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
        node = find_node(section_filter)
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
        body=generate_report_body(data), running_header=running_header,
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


def generate_report_body(data: dict) -> str:
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
    """
    body_first_id = first_body_node_id()
    body_chunks: list[str] = []
    for top in DOCUMENT_TREE:
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
