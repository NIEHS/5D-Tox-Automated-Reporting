"""
freeform_content.py — authored ("freeform") document content in a small set of
representations.

Most document-tree nodes get their content from the pipeline via
``data[node.data_key]``.  The two ``freeform-*`` component types are the
exception: their content is **authored** — written in the template (or an
external file), not produced by the pipeline — in one of three representations:

  - ``latex`` — raw LaTeX, native to the Overleaf bundle surface;
  - ``html``  — raw HTML, native to the in-app preview surface (this is also
    what a clipboard paste yields: the OS clipboard's ``text/html`` flavor is
    what carries styling, so "paste styled content" is just authoring ``html``);
  - ``docx``  — an imported Word file, converted once at load time into BOTH a
    LaTeX and an HTML rendering of a documented common subset.

Two render surfaces consume the result: ``latex_generator`` (Overleaf bundle)
and ``html_generator`` (preview).  A representation that is native to only one
surface (``latex``/``html``) renders on its surface and shows a short *pending
note* on the other — unless the author supplies a **dual-source** mapping
(``content: {latex: ..., html: ...}``), in which case each surface uses its own
native source.  ``docx`` is dual-native (it converts to both).

This module owns the representation registry, the per-surface resolver, and the
docx→(latex, html) converter.  It imports NOTHING from the renderers (the
dependency points renderers → here, like ``chart_registry``), so there is no
import cycle; the escape helpers below are deliberately small and local rather
than imported from the generators.

Resolution is done ONCE, at tree-build time (``document_template`` calls
``resolve_freeform`` in the instantiator and stores ``{latex, html}`` on the
node), so a docx file is parsed a single time total and both renderers just read
the precomputed markup.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Representation registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Representation:
    """One authored-content representation.

    Fields:
        name:           "latex" | "html" | "docx".
        native_surface: the surface this representation renders to natively
                        ("latex" or "html").  None for ``docx``, which converts
                        to BOTH surfaces (dual-native).
    """
    name: str
    native_surface: str | None


_REPRESENTATIONS: dict[str, Representation] = {
    "latex": Representation("latex", native_surface="latex"),
    "html": Representation("html", native_surface="html"),
    "docx": Representation("docx", native_surface=None),  # converts to both
}

# The two render surfaces a resolved-content dict carries markup for.
SURFACES: tuple[str, ...] = ("latex", "html")

VALID_REPRESENTATIONS: frozenset[str] = frozenset(_REPRESENTATIONS)


def is_valid_representation(name: str) -> bool:
    return name in _REPRESENTATIONS


# ---------------------------------------------------------------------------
# Pending note (foreign surface)
# ---------------------------------------------------------------------------

def pending_note(representation: str, surface: str) -> str:
    """A short human-readable note for a surface that has no native rendering of
    this content (e.g. raw ``latex`` content viewed on the HTML surface).  The
    renderers wrap this in their own markup."""
    other = "HTML preview" if surface == "latex" else "Overleaf/LaTeX export"
    return (
        f"[content authored as {representation}; shown on the {other}]"
    )


# ---------------------------------------------------------------------------
# Minimal, LOCAL escape helpers (no import from the renderers → no cycle)
# ---------------------------------------------------------------------------

# Only used by the docx converter, whose text comes from a Word file (plain
# strings).  Authored ``latex``/``html`` content is the user's own markup and is
# passed through verbatim, never escaped.

_LATEX_SPECIALS = {
    "\\": r"\textbackslash{}",
    "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
    "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def _latex_escape(text: str) -> str:
    out = []
    for ch in text or "":
        out.append(_LATEX_SPECIALS.get(ch, ch))
    return "".join(out)


_HTML_SPECIALS = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}


def _html_escape(text: str) -> str:
    out = []
    for ch in text or "":
        out.append(_HTML_SPECIALS.get(ch, ch))
    return "".join(out)


# ---------------------------------------------------------------------------
# docx → block model (one walk, two emitters)
# ---------------------------------------------------------------------------
# A deliberately small, documented common subset.  Each Block is a plain dict so
# the two emitters stay trivial and can't drift on structure.
#
# Block kinds:
#   {"kind": "heading", "level": 1..3, "runs": [Run, ...]}
#   {"kind": "paragraph", "runs": [Run, ...]}
#   {"kind": "list-item", "ordered": bool, "runs": [Run, ...]}
#   {"kind": "table", "rows": [[ [Run,...] , ...], ...]}   # cell = list[Run]
# Run: {"text": str, "bold": bool, "italic": bool, "underline": bool}
#
# Unsupported docx features (images, nested tables, complex styling) are dropped
# with a logged note — the subset is intentionally simple.


def _runs_from_paragraph(paragraph) -> list[dict]:
    """Collapse a docx paragraph's runs into our Run dicts (bold/italic/underline)."""
    runs: list[dict] = []
    for r in paragraph.runs:
        text = r.text or ""
        if not text:
            continue
        runs.append({
            "text": text,
            "bold": bool(r.bold),
            "italic": bool(r.italic),
            "underline": bool(r.underline),
        })
    return runs


def _walk_docx(path: Path) -> list[dict]:
    """Parse a .docx into our block list, in document order.

    Paragraphs and tables are interleaved in the body, so we iterate the body's
    XML children and map each back to a python-docx Paragraph or Table.
    """
    import docx
    from docx.document import Document as _Doc  # noqa: F401
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(str(path))
    blocks: list[dict] = []

    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            para = Paragraph(child, document)
            style = (para.style.name or "") if para.style else ""
            runs = _runs_from_paragraph(para)
            if not runs:
                continue  # blank line
            if style.startswith("Heading"):
                # "Heading 1".."Heading 3" → level; deeper headings clamp to 3.
                try:
                    level = int(style.split()[-1])
                except (ValueError, IndexError):
                    level = 1
                blocks.append({"kind": "heading", "level": min(max(level, 1), 3),
                               "runs": runs})
            elif style.startswith("List Bullet"):
                blocks.append({"kind": "list-item", "ordered": False, "runs": runs})
            elif style.startswith("List Number"):
                blocks.append({"kind": "list-item", "ordered": True, "runs": runs})
            else:
                blocks.append({"kind": "paragraph", "runs": runs})
        elif isinstance(child, CT_Tbl):
            tbl = Table(child, document)
            rows: list[list[list[dict]]] = []
            for row in tbl.rows:
                cells: list[list[dict]] = []
                for cell in row.cells:
                    # A cell may hold several paragraphs; flatten their runs.
                    cell_runs: list[dict] = []
                    for p in cell.paragraphs:
                        cell_runs.extend(_runs_from_paragraph(p))
                    if not cell_runs:
                        cell_runs = [{"text": "", "bold": False,
                                      "italic": False, "underline": False}]
                    cells.append(cell_runs)
                rows.append(cells)
            if rows:
                blocks.append({"kind": "table", "rows": rows})
        # else: sectPr and other elements are ignored.

    return blocks


# ---- emitters -------------------------------------------------------------

def _runs_to_latex(runs: list[dict]) -> str:
    out = []
    for r in runs:
        t = _latex_escape(r["text"])
        if r.get("bold"):
            t = f"\\textbf{{{t}}}"
        if r.get("italic"):
            t = f"\\textit{{{t}}}"
        if r.get("underline"):
            t = f"\\underline{{{t}}}"
        out.append(t)
    return "".join(out)


def _emit_latex(blocks: list[dict]) -> str:
    _HEADING_CMD = {1: r"\section*", 2: r"\subsection*", 3: r"\subsubsection*"}
    out: list[str] = []
    i = 0
    n = len(blocks)
    while i < n:
        b = blocks[i]
        kind = b["kind"]
        if kind == "heading":
            cmd = _HEADING_CMD.get(b["level"], r"\subsubsection*")
            out.append(f"{cmd}{{{_runs_to_latex(b['runs'])}}}")
            i += 1
        elif kind == "paragraph":
            out.append(_runs_to_latex(b["runs"]))
            i += 1
        elif kind == "list-item":
            # Gather a contiguous run of list items of the same ordering.
            ordered = b["ordered"]
            items = []
            while i < n and blocks[i]["kind"] == "list-item" and blocks[i]["ordered"] == ordered:
                items.append(blocks[i]["runs"])
                i += 1
            env = "enumerate" if ordered else "itemize"
            body = "\n".join(f"  \\item {_runs_to_latex(r)}" for r in items)
            out.append(f"\\begin{{{env}}}\n{body}\n\\end{{{env}}}")
        elif kind == "table":
            rows = b["rows"]
            ncols = max((len(r) for r in rows), default=1)
            colspec = "|".join(["l"] * ncols)
            lines = [f"\\begin{{tabular}}{{{colspec}}}", "\\hline"]
            for row in rows:
                cells = [_runs_to_latex(c) for c in row]
                cells += [""] * (ncols - len(cells))
                lines.append(" & ".join(cells) + r" \\")
                lines.append("\\hline")
            lines.append("\\end{tabular}")
            out.append("\n".join(lines))
            i += 1
        else:
            i += 1
    return "\n\n".join(out)


def _runs_to_html(runs: list[dict]) -> str:
    out = []
    for r in runs:
        t = _html_escape(r["text"])
        if r.get("bold"):
            t = f"<strong>{t}</strong>"
        if r.get("italic"):
            t = f"<em>{t}</em>"
        if r.get("underline"):
            t = f"<u>{t}</u>"
        out.append(t)
    return "".join(out)


def _emit_html(blocks: list[dict]) -> str:
    out: list[str] = []
    i = 0
    n = len(blocks)
    while i < n:
        b = blocks[i]
        kind = b["kind"]
        if kind == "heading":
            lvl = min(max(b["level"] + 1, 2), 4)  # h2..h4 (page title owns h1)
            out.append(f"<h{lvl}>{_runs_to_html(b['runs'])}</h{lvl}>")
            i += 1
        elif kind == "paragraph":
            out.append(f"<p>{_runs_to_html(b['runs'])}</p>")
            i += 1
        elif kind == "list-item":
            ordered = b["ordered"]
            items = []
            while i < n and blocks[i]["kind"] == "list-item" and blocks[i]["ordered"] == ordered:
                items.append(blocks[i]["runs"])
                i += 1
            tag = "ol" if ordered else "ul"
            body = "".join(f"<li>{_runs_to_html(r)}</li>" for r in items)
            out.append(f"<{tag}>{body}</{tag}>")
        elif kind == "table":
            rows = b["rows"]
            tr = []
            for row in rows:
                tds = "".join(f"<td>{_runs_to_html(c)}</td>" for c in row)
                tr.append(f"<tr>{tds}</tr>")
            out.append('<table class="freeform-table"><tbody>'
                       + "".join(tr) + "</tbody></table>")
            i += 1
        else:
            i += 1
    return "\n".join(out)


def docx_to_surfaces(path: Path) -> dict:
    """Convert a .docx file to ``{latex, html}`` markup (one walk, two emitters)."""
    blocks = _walk_docx(path)
    if not blocks:
        logger.warning("freeform: docx %s produced no convertible blocks", path)
    return {"latex": _emit_latex(blocks), "html": _emit_html(blocks)}


# ---------------------------------------------------------------------------
# The resolver — authored content → per-surface markup
# ---------------------------------------------------------------------------

def _read_source_file(content_file: str, base_dir: Path) -> str:
    path = (base_dir / content_file)
    if not path.is_file():
        raise ValueError(
            f"freeform content_file not found: {content_file!r} "
            f"(resolved to {path})"
        )
    return path.read_text(encoding="utf-8")


def resolve_freeform(
    content,
    content_file: str | None,
    representation: str | None,
    *,
    base_dir: Path,
) -> dict:
    """
    Resolve authored content into per-surface markup: ``{"latex": str|None,
    "html": str|None}``.  A None value means that surface has no native
    rendering (the renderer shows a pending note).

    Cases:
      - ``content`` is a dual-source mapping ({latex, html}): each surface uses
        its own source verbatim (a missing key → None on that surface).
      - else a single source — inline ``content`` string OR the text of
        ``content_file`` — interpreted per ``representation``:
          * latex → {latex: src, html: None}
          * html  → {latex: None, html: src}
          * docx  → parse ``content_file`` once → {latex, html}

    ``base_dir`` is the directory ``content_file`` paths resolve against
    (templates/).  Validation of which fields may coexist is done by the
    template validator BEFORE this is called; this function trusts that and
    raises only on a genuinely unreadable/empty source.
    """
    # Dual-source mapping: surface-specific native sources.
    if isinstance(content, dict):
        return {
            "latex": content.get("latex"),
            "html": content.get("html"),
        }

    rep = representation
    if rep == "docx":
        if not content_file:
            raise ValueError("freeform representation 'docx' requires content_file")
        path = Path(content_file)
        if not path.is_absolute():
            path = base_dir / content_file
        if not path.is_file():
            raise ValueError(
                f"freeform content_file not found: {content_file!r} "
                f"(resolved to {path})"
            )
        return docx_to_surfaces(path)

    # Single textual source: inline content string, or read from file.
    if content is not None:
        source = str(content)
    elif content_file:
        source = _read_source_file(content_file, base_dir)
    else:
        raise ValueError("freeform node has neither content nor content_file")

    if rep == "latex":
        return {"latex": source, "html": None}
    if rep == "html":
        return {"latex": None, "html": source}
    raise ValueError(
        f"freeform representation must be one of {sorted(VALID_REPRESENTATIONS)}, "
        f"got {rep!r}"
    )
