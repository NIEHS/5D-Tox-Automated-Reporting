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

from document_tree import (
    DOCUMENT_TREE,
    DocNode,
    find_node,
)
from render_capabilities import landscape_requested, content_item_landscape_requested
from genomics_content import genomics_content_plan
from cross_references import resolve_xrefs_latex


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


def _render_paragraphs(paragraphs: list[str]) -> str:
    """
    Render a flat list of paragraph strings as LaTeX, separated by blank
    lines (which TeX interprets as paragraph breaks).

    Each paragraph is escaped individually.  Returns "" for empty input so
    callers can detect "no content" and substitute a placeholder.
    """
    if not paragraphs:
        return ""
    return "\n\n".join(_escape_latex(p) for p in paragraphs)


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
    """
    body = ""
    if node.data_key:
        content = data.get(node.data_key)
        if isinstance(content, dict):
            # The abstract is a structured set of labeled sections
            # (Background / Methods / Results / Summary); every other
            # front-matter section is a flat paragraph list.  Render whichever
            # shape actually carries content.
            if content.get("sections"):
                body = _render_labeled_sections(content["sections"])
            if not body:
                body = _render_paragraphs(content.get("paragraphs", []))
    if not body:
        body = f"\\emph{{[Section pending: {_escape_latex(node.title)}]}}"
    return f"{_heading(node.level, node.title)}\n\n{body}"


def _render_labeled_sections(sections: list) -> str:
    r"""
    Render structured-abstract sections ({label, text}) as paragraphs with a
    bold run-in label (e.g. "\textbf{Background.} ...").  Empty-text sections
    (such as a Methods abstract with no MethodsContext) are skipped, so a
    partial abstract renders only the parts that have content.
    """
    parts: list[str] = []
    for sec in sections or []:
        if not isinstance(sec, dict):
            continue
        text = (sec.get("text") or "").strip()
        if not text:
            continue
        label = (sec.get("label") or "").strip()
        if label:
            parts.append(
                f"\\noindent\\textbf{{{_escape_latex(label)}.}} {_escape_latex(text)}"
            )
        else:
            parts.append(_escape_latex(text))
    return "\n\n".join(parts)


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
    flat list of {level, heading, paragraphs, [table]} dicts.  We match
    each tree node by title against section.heading.

    Why title-match instead of an explicit key
    ------------------------------------------
    Both _build_methods_sections_from_tree (scaffold path) and the
    production methods_report path produce sections keyed on the human-
    readable heading.  Carrying a separate "methods_key" field through
    the data dict would duplicate that — the title is already canonical.
    """
    body = ""
    methods = data.get("methods", {})
    if isinstance(methods, dict):
        for section in methods.get("sections", []):
            if section.get("heading") == node.title:
                body = _render_paragraphs(section.get("paragraphs", []))
                # If the section carries an inline table (e.g., the Final
                # Sample Counts table that appears under Transcriptomics
                # → Sample Collection), render it after the prose.
                table_inline = section.get("table")
                if isinstance(table_inline, dict):
                    body = (body + "\n\n" + _render_inline_table(table_inline)).strip()
                break
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
    if node.id == "appendix-b" and data.get("appendix_animals"):
        return f"{heading}\n\n{_render_animal_identifiers(data['appendix_animals'])}"
    body = f"\\emph{{[Appendix body pending: {_escape_latex(node.title)}]}}"
    return f"{heading}\n\n{body}"


def _render_animal_identifiers(rows: list) -> str:
    r"""
    The Appendix B animal roster as a page-breaking longtable.

    ~300 animals don't fit one page, and the niehstable float can't break
    across pages — so this uses longtable (loaded by niehs.cls), whose
    \endhead repeats the column header on every page.
    """
    head = (
        "\\begin{longtable}{l l r}\n"
        "\\toprule\n"
        "Animal ID & Sex & Dose (mg/kg) \\\\\n"
        "\\midrule\n"
        "\\endhead\n"
    )
    body = "\n".join(
        _emit_tabular_row([
            _escape_latex(str(r.get("animal_id", ""))),
            _escape_latex(str(r.get("sex", ""))),
            _format_dose_value(r.get("dose")),
        ])
        for r in rows
    )
    return head + body + "\n\\bottomrule\n\\end{longtable}"


def _format_dose_value(dose) -> str:
    """Format a numeric dose for the roster: drop a trailing .0, else as-is."""
    if isinstance(dose, (int, float)):
        return str(int(dose)) if float(dose).is_integer() else str(dose)
    return "—"


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


def _table_caption(node: DocNode, base_caption: str) -> str:
    """
    Prefix the caption with "Table N. " using the auto-assigned table_number
    from the document tree.  Strips any leftover Typst-era placeholders like
    "{compound}" or "{sex}" that the data builders may have emitted.

    ADR-0004 amendment (a) — de-overloaded caption: prefer the addressable
    item's own `caption` (template / item-authored, the BITS <caption><p>
    role) over the data-overlay base caption; fall back when not set, so the
    existing data-driven path is preserved unchanged.
    """
    cleaned = (node.caption or base_caption or "")
    # Replace placeholder patterns left over from Typst-style templating.
    cleaned = cleaned.replace("{sex}", "Male and Female").replace("{compound}", "")
    cleaned = cleaned.strip()
    if node.table_number is not None:
        return f"Table {node.table_number}. {cleaned}" if cleaned else f"Table {node.table_number}"
    return cleaned


# ---------------------------------------------------------------------------
# Apical / dose-response tables
# ---------------------------------------------------------------------------

def _find_apical_section(node: DocNode, data: dict) -> dict | None:
    """
    Locate the apical_sections entry whose platform matches this table
    node's platform field.  Returns the matching dict or None.

    apical_sections is the flat list marshal_export_data produces from
    session state.  Each entry has a "platform" key ("Body Weight",
    "Clinical Chemistry", etc.) that we match against node.platform.
    Title-based fallback handles the legacy scaffold form where some
    entries don't carry a platform.
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
    section = _find_apical_section(node, data)
    if not section or not section.get("table_data"):
        return _emit_table_placeholder(node)

    table_data = section.get("table_data", {})
    male_rows = table_data.get("Male", []) or []
    female_rows = table_data.get("Female", []) or []
    if not male_rows and not female_rows:
        return _emit_table_placeholder(node)

    dose_unit = section.get("dose_unit", "mg/kg")
    first_col = section.get("first_col_header", "Endpoint")

    # Pull the dose list from the first row that has it — all rows share
    # the same dose grid (it's the column structure).
    ref_row = (male_rows or female_rows)[0]
    doses = ref_row.get("doses", []) or []

    headers = [first_col] + [_format_dose_label(d, dose_unit) for d in doses] + [
        f"BMD\\textsubscript{{1Std}} ({_escape_latex(dose_unit)})",
        f"BMDL\\textsubscript{{1Std}} ({_escape_latex(dose_unit)})",
    ]
    ncols = len(headers)
    colspec = "l" + "c" * (ncols - 1)

    lines = [f"\\begin{{tabular}}{{{colspec}}}", "\\toprule",
             _emit_tabular_row(headers, raw=True), "\\midrule"]

    for sex_label, rows in (("Male", male_rows), ("Female", female_rows)):
        if not rows:
            continue
        # Bold separator row spanning all columns.
        lines.append(
            f"\\multicolumn{{{ncols}}}{{l}}{{\\textbf{{{sex_label}}}}} \\\\"
        )
        for row in rows:
            label = row.get("endpoint") or row.get("day_label") or row.get("label") or ""
            values = row.get("values", []) or []
            bmd = row.get("bmd", "—") or "—"
            bmdl = row.get("bmdl", "—") or "—"
            cells = [str(label), *[str(v) for v in values], str(bmd), str(bmdl)]
            # Pad shorter rows to ncols so the tabular doesn't error.
            while len(cells) < ncols:
                cells.append("—")
            lines.append(_emit_tabular_row(cells))

    lines.append("\\bottomrule")
    lines.append("\\end{tabular}")
    tabular = "\n".join(lines)

    notes = _emit_table_footnotes(section.get("footnotes", []))
    caption = _table_caption(node, section.get("caption", ""))

    return (
        f"\\begin{{niehstable}}{{{node.id}}}{{{caption}}}\n"
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
        f"\\begin{{niehstable}}{{{node.id}}}{{{caption}}}\n"
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
    table nodes are walked separately by _walk and render through
    _render_apical_table or _render_incidence_table.

    The narrative lives at data["unified_narratives"][node.narrative_key]
    when narrative_key is set.  Falls back to a placeholder when missing.
    """
    paragraphs: list[str] = []
    if node.narrative_key:
        unified = data.get("unified_narratives", {})
        if isinstance(unified, dict):
            entry = unified.get(node.narrative_key)
            # Entries may be a list of strings (legacy) or a dict with a
            # "paragraphs" key.  Handle both.
            if isinstance(entry, list):
                paragraphs = entry
            elif isinstance(entry, dict):
                paragraphs = entry.get("paragraphs", []) or []

    body = _render_paragraphs(paragraphs)
    if not body:
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
    summary = data.get("bmd_summary", {}) or {}
    endpoints = summary.get("endpoints", []) or []
    paragraphs = summary.get("paragraphs", []) or []

    heading = _heading(node.level, node.title)
    prose = _render_paragraphs(paragraphs)

    if not endpoints:
        body = prose or f"\\emph{{[BMD summary endpoints pending: {_escape_latex(node.title)}]}}"
        return f"{heading}\n\n{body}"

    headers = ["Sex", "Endpoint", "BMD", "BMDL", "LOEL", "NOEL", "Direction"]
    colspec = "l l r r r r l"
    lines = [f"\\begin{{tabular}}{{{colspec}}}", "\\toprule",
             _emit_tabular_row(headers), "\\midrule"]
    for ep in endpoints:
        cells = [
            str(ep.get("sex", "")),
            str(ep.get("endpoint", "")),
            str(ep.get("bmd", "—") or "—"),
            str(ep.get("bmdl", "—") or "—"),
            str(ep.get("loel", "—") or "—"),
            str(ep.get("noel", "—") or "—"),
            str(ep.get("direction", "")),
        ]
        lines.append(_emit_tabular_row(cells))
    lines.append("\\bottomrule")
    lines.append("\\end{tabular}")
    tabular = "\n".join(lines)

    caption = _table_caption(node, node.title)
    block = (
        f"\\begin{{niehstable}}{{{node.id}}}{{{caption}}}\n"
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
    section = _find_apical_section(node, data)
    if not section:
        return _emit_table_placeholder(node)
    rows = section.get("incidence_rows", []) or section.get("rows", []) or []
    if not rows:
        return _emit_table_placeholder(node)

    doses = section.get("doses", []) or []
    dose_unit = section.get("dose_unit", "mg/kg")
    headers = ["Observation"] + [_format_dose_label(d, dose_unit) for d in doses]
    ncols = len(headers)
    colspec = "l" + "c" * (ncols - 1)

    lines = [f"\\begin{{tabular}}{{{colspec}}}", "\\toprule",
             _emit_tabular_row(headers, raw=True), "\\midrule"]
    for row in rows:
        label = row.get("observation") or row.get("label") or ""
        counts = row.get("counts") or row.get("values") or []
        cells = [str(label), *[str(c) for c in counts]]
        while len(cells) < ncols:
            cells.append("0")
        lines.append(_emit_tabular_row(cells))
    lines.append("\\bottomrule")
    lines.append("\\end{tabular}")
    tabular = "\n".join(lines)

    notes = _emit_table_footnotes(section.get("footnotes", []))
    caption = _table_caption(node, section.get("caption", "") or node.title)
    return (
        f"\\begin{{niehstable}}{{{node.id}}}{{{caption}}}\n"
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
    role = "gene_set" if node.id == "gene-sets" else "gene"
    heading = _heading(node.level, node.title)
    # Top-level narrative (data["gene_set_narrative"] or data["gene_narrative"])
    # may be a dict {by_organ: {...}} or a list of paragraphs; we treat
    # only the list / paragraphs-bearing case at the section level.
    top_narrative_key = "gene_set_narrative" if role == "gene_set" else "gene_narrative"
    top_nar = data.get(top_narrative_key)
    intro_paragraphs: list[str] = []
    if isinstance(top_nar, list):
        intro_paragraphs = top_nar
    elif isinstance(top_nar, dict) and isinstance(top_nar.get("paragraphs"), list):
        intro_paragraphs = top_nar["paragraphs"]
    intro = _render_paragraphs(intro_paragraphs)

    entries = [
        s for s in (data.get("genomics_sections", []) or [])
        if s.get("type") == role
    ]
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
    # ADR-0004 amendment (e) — prefix the caption with "Figure N." using the
    # positional figure_number assigned at chart-attach time; the trailing
    # rstrip drops the dangling space when the descriptive caption is empty.
    caption_text = chart.get("caption", "")
    fig_num = chart.get("figure_number")
    if fig_num is not None:
        caption_text = f"Figure {fig_num}. {caption_text}".rstrip()
    caption = _escape_latex(caption_text)
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
    rows = entry.get("gene_sets", []) or []
    if not rows:
        return f"\\emph{{[Top gene sets pending: {_escape_latex(entry.get('organ', ''))}, {_escape_latex(entry.get('sex', ''))}]}}"

    headers = ["Rank", "GO ID", "Term", "BMD", "BMDL", "Genes", "Direction"]
    colspec = "l l l r r r l"
    lines = [f"\\begin{{tabular}}{{{colspec}}}", "\\toprule",
             _emit_tabular_row(headers), "\\midrule"]
    for r in rows:
        cells = [
            str(r.get("rank", "")),
            str(r.get("go_id", "")),
            str(r.get("go_term", "")),
            f"{r.get('bmd', '—')}",
            f"{r.get('bmdl', '—')}",
            str(r.get("n_genes", "")),
            str(r.get("direction", "")),
        ]
        lines.append(_emit_tabular_row(cells))
    lines.append("\\bottomrule")
    lines.append("\\end{tabular}")
    return "\n".join(lines)


def _render_gene_table(entry: dict) -> str:
    """
    Render the top-genes table for one (organ, sex) of a gene BMD section.
    Schema (per top_genes[i]):
      rank, gene, bmd, bmdl, direction, fold_change.
    """
    rows = entry.get("top_genes", []) or []
    if not rows:
        return f"\\emph{{[Top genes pending: {_escape_latex(entry.get('organ', ''))}, {_escape_latex(entry.get('sex', ''))}]}}"

    headers = ["Rank", "Gene", "BMD", "BMDL", "Direction", "Fold Change"]
    colspec = "l l r r l r"
    lines = [f"\\begin{{tabular}}{{{colspec}}}", "\\toprule",
             _emit_tabular_row(headers), "\\midrule"]
    for r in rows:
        cells = [
            str(r.get("rank", "")),
            str(r.get("gene", "")),
            f"{r.get('bmd', '—')}",
            f"{r.get('bmdl', '—')}",
            str(r.get("direction", "")),
            f"{r.get('fold_change', '—')}",
        ]
        lines.append(_emit_tabular_row(cells))
    lines.append("\\bottomrule")
    lines.append("\\end{tabular}")
    return "\n".join(lines)


def _render_description_list(descriptions: list) -> str:
    """
    Emit a description list (one paragraph per entry).

    descriptions is a list of dicts with at least {"label", "text"} or
    {"go_term", "description"} or {"gene", "description"}.  We try
    several common shapes.
    """
    items = []
    for d in descriptions:
        if not isinstance(d, dict):
            continue
        label = (
            d.get("label")
            or d.get("go_term")
            or d.get("gene")
            or d.get("go_id")
            or ""
        )
        text = d.get("text") or d.get("description") or ""
        if not (label or text):
            continue
        items.append(
            f"\\noindent\\textbf{{{_escape_latex(label)}}}: {_escape_latex(text)}"
        )
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


# ---------------------------------------------------------------------------
# Tree walk
# ---------------------------------------------------------------------------

def _walk(node: DocNode, data: dict) -> list[str]:
    """
    Render one node, then recurse into its children.

    The handler is responsible for the node's own output.  Children are
    walked here, after the parent's chunk, preserving document order.
    Returns a flat list of LaTeX chunks; the caller joins them with blank
    lines to produce the final body.
    """
    handler = _DISPATCH.get(node.node_type, _render_unimplemented)
    chunks: list[str] = []
    chunk = handler(node, data)
    if chunk:
        # Per-node landscape: wrap this node's output in pdflscape's
        # landscape environment when the user flipped it AND the node's
        # semantic type is orientable (capability dictionary).  Gating on the
        # capability ignores stale/invalid overlay flags — the dictionary is
        # authoritative on both the UI and render sides.  pdflscape rotates
        # both the content and the PDF page, so Overleaf shows it landscape.
        if landscape_requested(node.node_type, node.id, data.get("orientations"),
                               default=node.orientation):
            chunk = "\\begin{landscape}\n" + chunk + "\n\\end{landscape}"
        chunks.append(chunk)
    for child in node.children:
        chunks.extend(_walk(child, data))
    return chunks


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
        body_chunks = _walk(node, data)
        return _fragment_skeleton("\n\n".join(body_chunks))

    # ── Full-report path ─────────────────────────────────────────────
    # Pull title metadata from the data dict.  marshal_export_data fills
    # these in from session test-article forms; scaffold_report_data also
    # provides defaults for the smoke-test path.
    title = _escape_latex(data.get("title", "5dToxReport"))
    author = _escape_latex(
        data.get("author", "NIEHS Division of Translational Toxicology")
    )
    # Running header = the dedicated "running_header" field (the full,
    # never-abbreviated title form report_data.py sets), falling back to
    # the plain title.  Same source the HTML preview uses, so both output
    # surfaces show the identical header.
    running_header = _escape_latex(
        data.get("running_header") or data.get("title", "5dToxReport")
    )

    # Walk every top-level node in document order.  Each call to _walk
    # returns one chunk for the node itself plus chunks for all its
    # descendants, already flattened in document order.
    #
    # Page numbering switches from roman (front matter) to arabic (body) at
    # the first top-level node with region == "body" — the body's first page
    # (Background) becomes arabic page 1, matching NIEHS Report 10.  Region
    # is set by the template's region containers (ADR-0004 amendment d);
    # before that, this used a node-type membership set.  \clearpage flushes
    # any pending floats first so the switch lands on the body's opening
    # page, not a stray float page.
    body_chunks: list[str] = []
    switched_to_body = False
    for top in DOCUMENT_TREE:
        if not switched_to_body and top.region == "body":
            body_chunks.append("\\clearpage\n\\pagenumbering{arabic}")
            switched_to_body = True
        body_chunks.extend(_walk(top, data))

    # Paragraph break between every chunk.  LaTeX collapses consecutive
    # blank lines into a single paragraph break, so this is safe even
    # when chunks already end in newlines.
    body = "\n\n".join(body_chunks)

    return _document_skeleton(
        title=title, author=author, body=body, running_header=running_header
    )
