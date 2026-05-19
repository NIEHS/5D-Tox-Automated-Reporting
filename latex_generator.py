"""
latex_generator.py — LaTeX rendering of the NIEHS biological potency report.

This module is the LaTeX-side counterpart to report_pdf.py's Typst pipeline.
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

from document_tree import DOCUMENT_TREE, DocNode


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
            paragraphs = content.get("paragraphs", [])
            body = _render_paragraphs(paragraphs)
    if not body:
        body = f"\\emph{{[Section pending: {_escape_latex(node.title)}]}}"
    return f"{_heading(node.level, node.title)}\n\n{body}"


def _render_narrative(node: DocNode, data: dict) -> str:
    """
    Plain narrative section (background, summary, references, and most M&M
    subsections).  Same shape as front-matter at the LaTeX level — page
    numbering switches (roman → arabic) happen in niehs.cls, not here.

    Methods subsections share data_key="methods" and address their actual
    content via methods_key into data["methods"]["sections"].  Tracer-
    bullet does not unpack that structure, so methods subsections will
    fall through to the "[Section pending]" branch — that's expected and
    fixed in the M&M rendering session.
    """
    return _render_front_matter(node, data)


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

    The tree currently has appendices as heading-only stubs.  Real
    appendix content (study data tables, animal identifiers, QC plots)
    is deferred to a future session.  Tracer-bullet emits a visible
    "[Appendix body pending]" line so the author knows to expect content
    here later.
    """
    body = f"\\emph{{[Appendix body pending: {_escape_latex(node.title)}]}}"
    return f"{_heading(node.level, node.title)}\n\n{body}"


def _render_tables_list(node: DocNode, data: dict) -> str:
    """
    Tables list in front matter.

    Typst auto-generates this by walking the document tree to collect
    every table node.  For tracer-bullet we emit a heading + placeholder;
    a future session will likely use LaTeX's \\listoftables once table
    captions are wired into proper float environments.
    """
    return (
        f"{_heading(node.level, node.title)}\n\n"
        f"\\emph{{[List of tables: pending.]}}"
    )


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


# Dispatch table — registers each per-type handler.  Anything not listed
# here falls through to _render_unimplemented.  Tracer-bullet only wires
# the five simplest handlers; future sessions extend this map.
_DISPATCH: dict[str, object] = {
    "front-matter":  _render_front_matter,
    "narrative":     _render_narrative,
    "heading-only":  _render_heading_only,
    "appendix":      _render_appendix,
    "tables-list":   _render_tables_list,
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
        chunks.append(chunk)
    for child in node.children:
        chunks.extend(_walk(child, data))
    return chunks


# ---------------------------------------------------------------------------
# Document skeleton
# ---------------------------------------------------------------------------

def _document_skeleton(title: str, author: str, body: str) -> str:
    """
    Wrap a rendered body in the outer LaTeX document scaffolding.

    Per decision #6 we skip the NIEHS-branded cover and use \\maketitle.
    \\tableofcontents follows the title page so the author sees a TOC
    immediately; LaTeX auto-populates it from the \\section commands the
    body emits.

    The class file (niehs.cls) owns page geometry, fonts, and the
    niehstable environment — this function only emits the structural
    skeleton.
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
        "\n"
        "\\begin{document}\n"
        "\\maketitle\n"
        "\\tableofcontents\n"
        "\n"
        + body + "\n"
        "\n"
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
    # section_filter wiring is intentionally deferred — see decision #10
    # in the resolved Option B plan.  Reference it so static analysis
    # doesn't flag the parameter as unused.
    _ = section_filter

    # Pull title metadata from the data dict.  marshal_export_data fills
    # these in from session test-article forms; scaffold_report_data also
    # provides defaults for the smoke-test path.
    title = _escape_latex(data.get("title", "5dToxReport"))
    author = _escape_latex(
        data.get("author", "NIEHS Division of Translational Toxicology")
    )

    # Walk every top-level node in document order.  Each call to _walk
    # returns one chunk for the node itself plus chunks for all its
    # descendants, already flattened in document order.
    body_chunks: list[str] = []
    for top in DOCUMENT_TREE:
        body_chunks.extend(_walk(top, data))

    # Paragraph break between every chunk.  LaTeX collapses consecutive
    # blank lines into a single paragraph break, so this is safe even
    # when chunks already end in newlines.
    body = "\n\n".join(body_chunks)

    return _document_skeleton(title=title, author=author, body=body)
