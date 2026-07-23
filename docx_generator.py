r"""
docx_generator.py — Microsoft Word (.docx) rendering of the NIEHS biological
potency report.

This module is the third sibling of latex_generator.py and html_generator.py.
All three walk the same DOCUMENT_TREE with the same data dict and dispatch on the
same set of node_type values (render_common.RENDERABLE_NODE_TYPES); they differ
only in the output each per-node handler produces.  That gives a Word export a
1:1 semantic match with the Overleaf .tex and the in-app HTML preview — same
tree, same data, same dispatch, just a different emitter.

Why a third surface
-------------------
Some stakeholders' publishing workflows are Word-driven (track-changes review,
house .dotx templates).  ADR-0008 (Option B) accepted a Word emitter as a
one-way OUTPUT surface: we generate a .docx from the tree, but never treat Word
as a source of truth — the tree + data remain canonical (Architectural
Invariant #1/#2).  Round-tripping Word back INTO the tree is a separate,
existing concern (freeform_content.py ingests an authored .docx block); this
module is generation only.

Architecture mirror + the one deliberate divergence
---------------------------------------------------
The dispatch table and per-type handlers follow html_generator.py's structure.
The ONE structural difference: LaTeX and HTML emitters return markup STRINGS and
share render_common.walk_emit (which accumulates a flat list of chunks).  Word is
an object model — python-docx handlers MUTATE a Document in place — so a handler
here has signature ``_render_<type>(doc, node, data) -> None`` and this module
runs its own ``_walk_docx_tree`` rather than walk_emit.  Everything semantic
(which content source wins, table rows, captions, roster) still comes from the
shared render_common EXTRACT plans, so this surface cannot drift from the other
two on WHAT a section contains — only on how Word renders it.

Scope (v1)
----------
Full node-type parity (all 17 RENDERABLE_NODE_TYPES) + a clean typographic
cover/title page + roman→arabic two-section page numbering + booktabs-style
tables + inline genomics chart images.  NOT in v1 (deliberate, documented
follow-ups): the per-node ``layout_style`` styling the other two surfaces honour
(this surface uses the Word base styles), and a configurable-fonts binding.
"""

from __future__ import annotations

import base64
import re
from io import BytesIO

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from cover_layouts import get_cover_layout
from document_tree import DOCUMENT_TREE, DocNode, first_body_node_id, walk_tree
from freeform_content import pending_note as _freeform_pending_note
from render_common import (
    ANIMAL_ROSTER_HEADERS,
    BMD_SUMMARY_HEADERS,
    GENE_SET_TABLE_HEADERS,
    GENE_TABLE_HEADERS,
    apical_table_plan,
    appendix_roster_rows,
    assert_dispatch_covers,
    bmd_summary_plan,
    front_matter_plan,
    gene_set_table_rows,
    gene_table_rows,
    genomics_chart_caption,
    genomics_description_items,
    genomics_entries,
    genomics_intro_paragraphs,
    genomics_role,
    genomics_table_caption,
    has_paragraph_content,
    incidence_table_plan,
    methods_subsection_content,
    sample_counts_table,
    table_caption as _table_caption,
    unified_narrative_paragraphs,
)
from genomics_content import genomics_content_plan
from layout_style import resolve_layout_style
from table_builder_common import format_display_number, format_mean_se_display


# ---------------------------------------------------------------------------
# Constants — the reference typography spec
# ---------------------------------------------------------------------------
# Every value below was MEASURED from docs/NIEHS-Report-10-Reference.pdf (all 80
# pages, via PyMuPDF span analysis), so the generated Word styles reproduce the
# reference's fonts/sizes rather than Word's default theme (Calibri/Aptos).  We
# name the font FAMILIES ("Times New Roman", "Arial"); the actual glyphs come
# from the render machine's installed fonts — the reference-identical set lives
# in assets/fonts/ (gitignored, licensed) for local measurement only.

# US-Letter page + one-inch margins (NIEHS Report 10 trim: text block L=72pt,
# R≈540pt, top/bottom ≈35pt band for the running header/footer → 1" margins with
# the header/footer 0.5" from the edge).
_PAGE_WIDTH = Inches(8.5)
_PAGE_HEIGHT = Inches(11.0)
_MARGIN = Inches(1.0)
_HEADER_FOOTER_DISTANCE = Inches(0.5)

# Font families (matched by name against the render machine's installed fonts).
_BODY_FONT = "Times New Roman"     # body text — 78/80 reference pages
_HEADING_FONT = "Arial"            # all headings + table headers

# Point sizes (measured).  Body 12pt; headings step 17/15/13 by level; the
# front-matter 16/14pt heading variants collapse to level-1 17pt in v1 (a ≤1pt
# divergence that doesn't move pagination).  Tables start at a uniform 10pt (the
# reference steps 10→9→8.5→8 by density — a later diff-driven tuning pass).
_BODY_PT = 12
_HEADING_PT: dict[int, int] = {1: 17, 2: 15, 3: 13}
_TABLE_PT = 10
_HEADER_PT = 12

# Black — the reference body + title-page text color (headings and title).
_BLACK = RGBColor(0x00, 0x00, 0x00)

# DocNode.level → Word built-in heading style.  Level 0 = no heading (cover,
# leaf table nodes); levels 1-3 nest under the document title.
_HEADING_STYLE_BY_LEVEL: dict[int, str] = {
    1: "Heading 1",
    2: "Heading 2",
    3: "Heading 3",
}

# Abstract font-family → concrete Word font, used only when a resolved style
# carries `font_family` (serif/sans/mono) but NOT an explicit `font` name.  The
# literal `font` always wins (see layout_style.LAYOUT_KEY_SCHEMA precedence note).
_DOCX_FONT_BY_FAMILY: dict[str, str] = {
    "serif": "Times New Roman",
    "sans": "Arial",
    "mono": "Consolas",
}

# Points per absolute unit, for converting a resolved-style length to Pt.  em/ex
# are relative and can't be resolved without the current font size, so a length
# in those units is ignored on the docx surface (logged as skipped).
_PT_PER_UNIT: dict[str, float] = {
    "pt": 1.0, "mm": 72.0 / 25.4, "cm": 72.0 / 2.54, "in": 72.0,
}
_LENGTH_RE = re.compile(r"^(-?\d+(?:\.\d+)?)(pt|mm|cm|in|em|ex)$")

# Strip C0 control chars (except tab/newline) that would make the OOXML invalid.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
# Minimal HTML tag stripper for freeform html fallback (see _freeform_text).
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text) -> str:
    """Coerce a value to a control-char-free string safe for an OOXML run."""
    return _CONTROL_RE.sub("", str(text if text is not None else ""))


def _style_run(run, *, size_pt: int, font: str | None = None, bold: bool = False):
    """Set explicit size/font/weight on a run (used for table cells, which must
    not inherit the 12pt body size — the reference tables run smaller)."""
    run.font.size = Pt(size_pt)
    if font:
        run.font.name = font
    if bold:
        run.bold = True
    return run


# ---------------------------------------------------------------------------
# Low-level docx helpers
# ---------------------------------------------------------------------------

def _add_heading(doc: Document, level: int, title: str, data: dict | None = None) -> None:
    """Append a heading paragraph for levels 1-3; level 0/empty adds nothing.

    Role-driven path (ADR-0010 Phase 2): when a vocabulary is active (``data``
    carries it), the level maps to the section_heading_N role and the paragraph
    gets that role's NATIVE Word style (3-0Na_HeadN_NoNumber).  Otherwise the
    built-in Heading 1-3 styles (_HEADING_STYLE_BY_LEVEL) — the pre-vocabulary
    look."""
    if not title or level not in _HEADING_STYLE_BY_LEVEL:
        return
    style = _HEADING_STYLE_BY_LEVEL[level]
    if data is not None:
        role_style = _role_style_name(data, f"section_heading_{level}")
        if role_style and role_style in {s.name for s in doc.styles}:
            style = role_style
    doc.add_paragraph(_clean(title), style=style)


def _add_paragraphs(doc: Document, paragraphs) -> bool:
    """
    Append one body paragraph per non-empty string.  Returns True if anything
    was added (so callers can fall back to a pending line when nothing was).
    """
    added = False
    for p in paragraphs or []:
        text = _clean(p).strip()
        if not text:
            continue
        doc.add_paragraph(text)
        added = True
    return added


def _add_labeled_sections(doc: Document, parts) -> None:
    """
    Structured-abstract parts as paragraphs with a bold run-in label — the Word
    twin of html_generator._render_labeled_sections.  A "" label is unlabeled.
    """
    for label, text in parts:
        para = doc.add_paragraph()
        if label:
            run = para.add_run(f"{_clean(label)}. ")
            run.bold = True
        para.add_run(_clean(text))


def _add_pending(doc: Document, label: str) -> None:
    """Visible italic "[pending]" placeholder — the Word twin of _pending."""
    para = doc.add_paragraph()
    run = para.add_run(f"[{_clean(label)}]")
    run.italic = True


def _set_repeat_header(row) -> None:
    """Mark a table row as a header that repeats on each page (tblHeader)."""
    trPr = row._tr.get_or_add_trPr()
    tblHeader = OxmlElement("w:tblHeader")
    tblHeader.set(qn("w:val"), "true")
    trPr.append(tblHeader)


def _set_edge_border(el, edge: str, sz: str = "8") -> None:
    """
    Give a table (tblPr/tblBorders) or cell (tcPr/tcBorders) a single ``edge``
    border (top/bottom/...), leaving the others untouched.  Used to build the
    booktabs look (horizontal rules only).
    """
    if el.tag.endswith("}tbl"):
        pr = el.tblPr
        borders_tag = "w:tblBorders"
    else:  # a <w:tc> cell
        pr = el.get_or_add_tcPr()
        borders_tag = "w:tcBorders"
    borders = pr.find(qn(borders_tag))
    if borders is None:
        borders = OxmlElement(borders_tag)
        pr.append(borders)
    e = borders.find(qn(f"w:{edge}"))
    if e is None:
        e = OxmlElement(f"w:{edge}")
        borders.append(e)
    e.set(qn("w:val"), "single")
    e.set(qn("w:sz"), sz)
    e.set(qn("w:space"), "0")
    e.set(qn("w:color"), "000000")


def _booktabs_table(
    doc: Document,
    headers: list[str],
    rows: list[list[str]],
    *,
    caption: str = "",
    footnotes: list | None = None,
    merged_label_rows: bool = False,
) -> None:
    """
    Append a booktabs-style table (top rule, header rule, bottom rule; no
    vertical or inner-body rules) — the Word analogue of the ``niehstable``
    environment / HTML ``.niehstable``.

    caption:            rendered as a bold paragraph ABOVE the table (NIEHS
                        places table captions above), matching the "Table N."
                        text the shared _table_caption / genomics_table_caption
                        already built.
    footnotes:          the typed footnote dicts render as small paragraphs
                        below the table (lettered entries keep their letter).
    merged_label_rows:  when True, a body row whose first cell is wrapped in
                        ``**...**`` (the apical / sample-counts sex separator)
                        is emitted as a single bold cell merged across all
                        columns — the Word twin of the HTML colspan row.
    """
    if caption:
        cap = doc.add_paragraph()
        cap.add_run(_clean(caption)).bold = True

    ncols = max(len(headers), max((len(r) for r in rows), default=0), 1)
    table = doc.add_table(rows=0, cols=ncols)
    table.autofit = True

    if headers:
        hcells = table.add_row().cells
        for i, h in enumerate(headers):
            if i >= ncols:
                break
            para = hcells[i].paragraphs[0]
            # Reference table headers are Arial Bold, one step below body size.
            _style_run(para.add_run(_clean(h)), size_pt=_TABLE_PT,
                       font=_HEADING_FONT, bold=True)
        _set_repeat_header(table.rows[0])
        for c in table.rows[0]._tr.tc_lst:
            _set_edge_border(c, "bottom")

    for row in rows:
        cells = [_clean(c) for c in row]
        first = cells[0] if cells else ""
        if merged_label_rows and first.startswith("**") and first.endswith("**"):
            tr = table.add_row()
            merged = tr.cells[0]
            for other in tr.cells[1:]:
                merged = merged.merge(other)
            _style_run(merged.paragraphs[0].add_run(first.strip("*").strip()),
                       size_pt=_TABLE_PT, bold=True)
            continue
        tr = table.add_row()
        for i in range(ncols):
            val = cells[i].strip() if i < len(cells) else ""
            # Data cells: body font (Times), table size (10pt).
            _style_run(tr.cells[i].paragraphs[0].add_run(val), size_pt=_TABLE_PT)

    # Outer top + bottom rules complete the booktabs frame.
    _set_edge_border(table._tbl, "top")
    _set_edge_border(table._tbl, "bottom")

    _add_footnotes(doc, footnotes)


def _add_footnotes(doc: Document, footnotes) -> None:
    """Render table footnotes as small paragraphs below a table."""
    for fn in footnotes or []:
        if not isinstance(fn, dict):
            continue
        text = fn.get("text") or fn.get("body") or ""
        if not text:
            continue
        para = doc.add_paragraph()
        if fn.get("kind") == "lettered" and fn.get("letter"):
            marker = para.add_run(f"{_clean(fn['letter'])} ")
            marker.font.superscript = True
            marker.font.size = Pt(8)
        run = para.add_run(_clean(text))
        run.font.size = Pt(8)


def _add_page_break(doc: Document) -> None:
    """Append an explicit page break (its own empty paragraph)."""
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


# ---------------------------------------------------------------------------
# Per-node-type render handlers — _render_<type>(doc, node, data) -> None
# ---------------------------------------------------------------------------
# Each handler appends this node's OWN content to the Document (children are
# walked separately by _walk_docx_tree).  Mirrors the html_generator handlers
# 1:1 in which shared EXTRACT plan it consumes.


def _render_front_matter(doc: Document, node: DocNode, data: dict) -> None:
    """Front-matter / narrative section: heading + labeled-sections or prose."""
    _add_heading(doc, node.level, node.title, data)
    plan = front_matter_plan(node, data)
    if plan.kind == "labeled":
        _add_labeled_sections(doc, plan.labeled_parts)
    elif plan.kind == "paragraphs":
        _add_paragraphs(doc, plan.paragraphs)
    else:
        _add_pending(doc, f"Section pending: {node.title}")


def _render_narrative(doc: Document, node: DocNode, data: dict) -> None:
    """Plain narrative — M&M subsections route through the methods lookup."""
    if node.methods_key:
        _render_methods_subsection(doc, node, data)
    else:
        _render_front_matter(doc, node, data)


def _render_methods_subsection(doc: Document, node: DocNode, data: dict) -> None:
    """M&M subsection — prose + optional inline table, matched by methods_key."""
    _add_heading(doc, node.level, node.title, data)
    paragraphs, inline = methods_subsection_content(node, data)
    added = _add_paragraphs(doc, paragraphs) if has_paragraph_content(paragraphs) else False
    if inline is not None:
        _render_inline_table(doc, inline)
        added = True
    if not added:
        _add_pending(doc, f"Section pending: {node.title}")


def _render_inline_table(doc: Document, table: dict) -> None:
    """Inline neutral {caption, headers, rows, footnotes} table."""
    headers = [str(h) for h in table.get("headers", [])]
    rows = [[str(c) for c in r] for r in table.get("rows", [])]
    if not headers and not rows:
        return
    _booktabs_table(
        doc, headers, rows,
        caption=table.get("caption", ""),
        footnotes=table.get("footnotes", []),
    )


def _render_sample_counts_table(doc: Document, node: DocNode, data: dict) -> None:
    """Methods 'Final Sample Counts' matrix (Table 1) with sex-separator rows."""
    built = sample_counts_table(node, data)
    if built is None:
        _add_pending(doc, f"Table data pending: {node.title}")
        return
    headers = [str(h) for h in built.get("headers", [])]
    rows = [[str(c) for c in r] for r in built.get("rows", [])]
    _booktabs_table(
        doc, headers, rows,
        caption=_table_caption(node, built.get("caption", "")),
        footnotes=built.get("footnotes", []),
        merged_label_rows=True,
    )


def _render_heading_only(doc: Document, node: DocNode, data: dict) -> None:
    """Structural heading; children rendered separately by the walker."""
    _add_heading(doc, node.level, node.title, data)


def _render_appendix(doc: Document, node: DocNode, data: dict) -> None:
    """Appendix — B renders the animal roster; others heading + stub/children."""
    _add_heading(doc, node.level, node.title, data)
    rows = appendix_roster_rows(node, data)
    if rows is not None:
        _booktabs_table(
            doc, list(ANIMAL_ROSTER_HEADERS), rows,
            caption="Table B-1. Animal Numbers and FASTQ Data File Names",
        )
        return
    if not node.children:
        _add_pending(doc, f"Appendix body pending: {node.title}")


def _render_tables_list(doc: Document, node: DocNode, data: dict) -> None:
    """Front-matter list of tables from data['table_entries']."""
    _add_heading(doc, node.level, node.title, data)
    entries = data.get("table_entries") or []
    if not entries:
        _add_pending(doc, "List of tables: pending.")
        return
    for entry in entries:
        n = entry.get("table_number")
        title = entry.get("title", "")
        line = f"Table {n}. {title}" if n is not None else title
        doc.add_paragraph(_clean(line), style="List Number")


def _render_toc(doc: Document, node: DocNode, data: dict) -> None:
    """
    Contents — a STATIC list built from data['toc_entries'], indented by level.

    Word can auto-generate a TOC field, but that renders as "right-click →
    update field" until the user does so; a static list is what actually shows
    on open and mirrors the HTML preview exactly (the LaTeX path uses native
    \\tableofcontents).
    """
    doc.add_paragraph(_clean(node.title), style="Heading 1")
    entries = data.get("toc_entries") or []
    if not entries:
        _add_pending(doc, "Table of contents: pending.")
        return
    for entry in entries:
        lvl = entry.get("level", 1)
        para = doc.add_paragraph(_clean(entry.get("title", "")))
        if isinstance(lvl, int) and lvl > 1:
            para.paragraph_format.left_indent = Pt((lvl - 1) * 18)


def _render_narrative_tables(doc: Document, node: DocNode, data: dict) -> None:
    """H2 group under Results: heading + unified narrative; tables walked after."""
    _add_heading(doc, node.level, node.title, data)
    paragraphs = unified_narrative_paragraphs(node, data)
    if has_paragraph_content(paragraphs):
        _add_paragraphs(doc, paragraphs)
    else:
        _add_pending(doc, f"Narrative pending: {node.title}")


def _render_apical_table(doc: Document, node: DocNode, data: dict) -> None:
    """Apical dose-response table (Male/Female blocks, BMD/BMDL columns)."""
    plan = apical_table_plan(node, data)
    if plan is None:
        _add_pending(doc, f"Table data pending: {node.title}")
        return
    headers = (
        [plan.first_col]
        + [_format_dose_label(d, plan.dose_unit) for d in plan.doses]
        + [f"BMD 1Std ({plan.dose_unit})", f"BMDL 1Std ({plan.dose_unit})"]
    )
    rows: list[list[str]] = []
    for block in plan.sex_blocks:
        rows.append([f"**{block.sex_label}**"])
        for row in block.rows:
            rows.append(row.cells)
    _booktabs_table(
        doc, headers, rows,
        caption=plan.caption, footnotes=plan.footnotes, merged_label_rows=True,
    )


def _render_incidence_table(doc: Document, node: DocNode, data: dict) -> None:
    """Clinical Observations incidence table (observation × dose group)."""
    plan = incidence_table_plan(node, data)
    if plan is None:
        _add_pending(doc, f"Table data pending: {node.title}")
        return
    headers = ["Observation"] + [_format_dose_label(d, plan.dose_unit) for d in plan.doses]
    _booktabs_table(
        doc, headers, plan.rows, caption=plan.caption, footnotes=plan.footnotes,
    )


def _render_bmd_summary(doc: Document, node: DocNode, data: dict) -> None:
    """Apical Endpoint BMD Summary — prose + one row per endpoint."""
    plan = bmd_summary_plan(node, data)
    _add_heading(doc, node.level, node.title, data)
    prose = _add_paragraphs(doc, plan.paragraphs)
    if plan.rows is None:
        if not prose:
            _add_pending(doc, f"BMD summary endpoints pending: {node.title}")
        return
    _booktabs_table(doc, list(BMD_SUMMARY_HEADERS), plan.rows, caption=plan.caption)


def _render_genomics_section(doc: Document, node: DocNode, data: dict) -> None:
    """Gene Set / Gene BMD section — per-(organ, sex) subsections."""
    role = genomics_role(node)
    _add_heading(doc, node.level, node.title, data)
    intro = _add_paragraphs(doc, genomics_intro_paragraphs(node, data))

    entries = genomics_entries(node, data)
    if not entries:
        if not intro:
            _add_pending(doc, f"Genomics data pending: {node.title}")
        return

    for entry in entries:
        organ = (entry.get("organ") or "").capitalize()
        sex = (entry.get("sex") or "").capitalize()
        doc.add_paragraph(_clean(f"{organ}, {sex}"), style="Heading 4")
        for item in genomics_content_plan(entry, role):
            _render_genomics_item(doc, entry, role, item)


def _render_genomics_item(doc: Document, entry: dict, role: str, item: dict) -> None:
    """One content item of a genomics (organ, sex) block."""
    part = item.get("part")
    if part == "narrative":
        _add_paragraphs(doc, entry.get("narrative") or [])
    elif part == "table":
        if role == "gene_set":
            _render_gene_set_table(doc, entry)
        else:
            _render_gene_table(doc, entry)
    elif part == "chart":
        chart = next(
            (c for c in (entry.get("charts") or []) if c.get("key") == item.get("chart_key")),
            None,
        )
        if chart:
            _add_chart_image(doc, chart)
    elif part == "descriptions":
        descriptions = (
            entry.get("go_descriptions") if role == "gene_set"
            else entry.get("gene_descriptions")
        ) or []
        _add_description_list(doc, descriptions)


def _render_figure(doc: Document, node: DocNode, data: dict) -> None:
    """A first-class figure node (ADR-0012): embed its lossless PNG + caption.

    The artifact is a payload dict at ``data[data_key]`` shaped like a chart
    payload (``{png_b64 | filename, caption}``) — so chart figures reuse the
    genomics chart pipeline's output verbatim and logo figures supply an image
    the same way.  Caption is ``node.caption`` (authored) or the payload's, prefixed
    with the positional ``Figure N.`` from node.figure_number.  A missing payload
    renders a visible pending note, never a silent gap."""
    payload = (data.get(node.data_key) if node.data_key else None) or {}
    png = payload.get("png_b64", "")
    if png.startswith("data:"):
        png = png.split(",", 1)[1]
    if png:
        try:
            doc.add_picture(BytesIO(base64.b64decode(png)), width=Inches(5.5))
        except Exception:
            _add_pending(doc, f"Figure image failed to decode: {node.title}")
    else:
        _add_pending(doc, f"Figure pending: {node.title}")
    text = node.caption or payload.get("caption") or node.title
    if text:
        label = f"Figure {node.figure_number}. " if node.figure_number else ""
        cap = doc.add_paragraph()
        run = cap.add_run(_clean(f"{label}{text}"))
        run.italic = True
        run.font.size = Pt(9)
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER


def _render_gene_set_table(doc: Document, entry: dict) -> None:
    """Top-gene-sets table for one (organ, sex)."""
    rows = gene_set_table_rows(entry)
    if rows is None:
        _add_pending(doc, f"Top gene sets pending: {entry.get('organ','')}, {entry.get('sex','')}")
        return
    _booktabs_table(doc, list(GENE_SET_TABLE_HEADERS), rows, caption=genomics_table_caption(entry))


def _render_gene_table(doc: Document, entry: dict) -> None:
    """Top-genes table for one (organ, sex)."""
    rows = gene_table_rows(entry)
    if rows is None:
        _add_pending(doc, f"Top genes pending: {entry.get('organ','')}, {entry.get('sex','')}")
        return
    _booktabs_table(doc, list(GENE_TABLE_HEADERS), rows, caption=genomics_table_caption(entry))


def _add_description_list(doc: Document, descriptions) -> None:
    """A definition list of go-term / gene descriptions (bold term + text)."""
    for label, text in genomics_description_items(descriptions):
        para = doc.add_paragraph()
        if label:
            para.add_run(f"{_clean(label)}: ").bold = True
        para.add_run(_clean(text))


def _add_chart_image(doc: Document, chart: dict) -> None:
    """Embed a genomics chart PNG inline (decoded from its base64 payload)."""
    png = chart.get("png_b64", "")
    if not png:
        return
    if png.startswith("data:"):
        png = png.split(",", 1)[1]
    try:
        raw = base64.b64decode(png)
        doc.add_picture(BytesIO(raw), width=Inches(5.5))
    except Exception:
        return
    caption = genomics_chart_caption(chart)
    if caption:
        cap = doc.add_paragraph()
        run = cap.add_run(_clean(caption))
        run.italic = True
        run.font.size = Pt(9)
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER


def _render_cover(doc: Document, node: DocNode, data: dict) -> None:
    """
    Branded page-1 cover — EXCLUDED on the Word surface (emits nothing).

    The reference cover (NIEHS Report 10, page 1) is hexagon artwork under a
    luminosity-masked gradient with Myriad Pro / Helvetica Neue text — Word can't
    embed that PDF page and the branded pixels aren't the fidelity target, so the
    docx skips the cover entirely and opens on the title page (the LaTeX surface
    keeps its tikz cover; see latex_generator._render_cover).  The handler stays
    registered so the dispatch table still covers every node type; it just
    contributes no content.
    """
    return


# The hardcoded per-role title-page spec — the measured reference default that
# stands in when a role has no configured style (so an empty config renders
# byte-identically to the pre-role behavior).  `title` roles = Arial Bold 20pt
# black; everything else = Times New Roman 12pt black; all centered.
_TITLE_PAGE_ROLE_DEFAULTS: dict = {
    "report_title": {"font": _HEADING_FONT, "size": 20, "bold": True},
}
_TITLE_PAGE_META_DEFAULT = {"font": _BODY_FONT, "size": 12, "bold": False}


def _resolve_title_page_role(layout_cfg: "dict | None", role: str) -> dict:
    """The configured style for a title-page role, resolved in precedence order:
    ``defaults`` ← ``types["title-page"]`` (a page-wide baseline) ←
    ``title_page[role]`` (the per-role override).  Empty when nothing configured
    (the handler then keeps the measured hardcoded spec).

    NB the handler owns ALL title-page styling: the generic per-node overlay in
    `_walk_docx_tree` is SKIPPED for this node (see `_visit`), so this resolver
    must fold in the node-level ``types``/``instances`` layers itself — otherwise
    a page-wide `types["title-page"]` style would be lost."""
    if not layout_cfg:
        return {}
    style = dict(layout_cfg.get("defaults") or {})
    style.update((layout_cfg.get("types") or {}).get("title-page") or {})
    style.update((layout_cfg.get("instances") or {}).get("title-page") or {})
    style.update((layout_cfg.get("title_page") or {}).get(role) or {})
    return style


def _render_title_page(doc: Document, node: DocNode, data: dict) -> None:
    """
    Inner title page (reference page 2) — a centered typographic block.  Each
    semantic ROLE (report_title, report_number, publication_date, publisher_name,
    publisher_affiliation, issn, …) is emitted as ONE paragraph (multi-line roles
    like the title use internal line breaks, matching the reference's single
    title paragraph — not one paragraph per line).

    Styling precedence per role: the measured hardcoded reference spec
    (`_TITLE_PAGE_ROLE_DEFAULTS`) is applied first, then the configured
    ``styles.title_page[role]`` (resolved over ``defaults``) is overlaid via the
    shared `_apply_paragraph_style`, so any key the config omits keeps its
    reference value (ADR-0006 no-drift: an empty config renders unchanged).

    Text comes from the SAME cover_layouts builder the wording is single-sourced
    through, so the surfaces can't drift on wording.  Falls back to the flat
    title/publisher builders when a layout supplies no role builder.
    """
    layout = get_cover_layout(node.subtype)
    layout_cfg = data.get("layout_style")

    blocks = layout.title_page_blocks(data) if layout.title_page_blocks else None
    if blocks is None:
        # Legacy fallback: a layout without the role builder → old flat behavior.
        blocks = [("report_title", layout.title_builder(data))]
        for meta in (data.get("report_number", ""), data.get("report_date", "")):
            if meta:
                blocks.append(("report_number", [meta]))
        blocks.append(("publisher_affiliation", layout.publisher_builder(data)))

    for role, lines in blocks:
        lines = [_clean(ln) for ln in lines if ln]
        if not lines:
            continue
        para = doc.add_paragraph()
        run = para.add_run(lines[0])
        for extra in lines[1:]:
            run.add_break(WD_BREAK.LINE)
            run = para.add_run(extra)
        # Role-driven path (ADR-0010 Phase 2): when a vocabulary is active, tag the
        # paragraph with the role's NATIVE Word style — the title inherits the NTP
        # 1-NN typography (incl. the neutral single line spacing) with NO hardcoded
        # defaults.  Otherwise fall back to the measured reference defaults +
        # optional config overlay (the pre-vocabulary look).
        style_name = _role_style_name(data, role)
        if style_name:
            try:
                para.style = doc.styles[style_name]
            except KeyError:
                style_name = None
        if not style_name:
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            base = _TITLE_PAGE_ROLE_DEFAULTS.get(role, _TITLE_PAGE_META_DEFAULT)
            for r in para.runs:
                r.font.name = base["font"]
                r.font.size = Pt(base["size"])
                r.font.bold = base["bold"]
                r.font.color.rgb = _BLACK
            role_style = _resolve_title_page_role(layout_cfg, role)
            if role_style:
                _apply_paragraph_style(para, role_style)


def _freeform_text(node: DocNode) -> str:
    """
    Plain text for a freeform node on the Word surface.  There is no docx entry
    in resolved_content ({latex, html}); fall back to the html body with tags
    stripped (readable prose), else a pending note naming the authored surface.
    """
    resolved = node.resolved_content or {}
    html = resolved.get("html")
    if html:
        text = _TAG_RE.sub("", html)
        return re.sub(r"\s+\n", "\n", text).strip()
    rep = node.representation or "latex"
    return _freeform_pending_note(rep, "html")


def _render_freeform_page(doc: Document, node: DocNode, data: dict) -> None:
    """Freeform authored page — forces its own page, then heading + body text."""
    _add_page_break(doc)
    if node.title:
        _add_heading(doc, node.level, node.title, data)
    _add_paragraphs(doc, _freeform_text(node).split("\n\n"))


def _render_freeform_block(doc: Document, node: DocNode, data: dict) -> None:
    """Freeform authored block — inline, no forced page break."""
    if node.title:
        _add_heading(doc, node.level, node.title, data)
    _add_paragraphs(doc, _freeform_text(node).split("\n\n"))


def _render_page_break(doc: Document, node: DocNode, data: dict) -> None:
    """An explicit author-placed page break."""
    _add_page_break(doc)


def _render_unimplemented(doc: Document, node: DocNode, data: dict) -> None:
    """Catch-all — heading (if any) + a visible pending placeholder."""
    _add_heading(doc, node.level, node.title, data)
    _add_pending(doc, f"Section pending: {node.node_type} rendering not yet implemented")


def _format_dose_label(dose, unit: str) -> str:
    """Format a dose value with its unit (the Word/plain-space form)."""
    if dose == 0 or dose == 0.0:
        return f"0 {unit}"
    if isinstance(dose, float) and dose.is_integer():
        return f"{int(dose)} {unit}"
    return f"{dose} {unit}"


# ---------------------------------------------------------------------------
# Dispatch registry — validated against the canonical set at import (ADR-0006 #3)
# ---------------------------------------------------------------------------

_DISPATCH: dict[str, object] = {
    "cover":               _render_cover,
    "title-page":          _render_title_page,
    "front-matter":        _render_front_matter,
    "narrative":           _render_narrative,
    "heading-only":        _render_heading_only,
    "appendix":            _render_appendix,
    "tables-list":         _render_tables_list,
    "toc":                 _render_toc,
    "narrative+tables":    _render_narrative_tables,
    "table":               _render_apical_table,
    "incidence-table":     _render_incidence_table,
    "figure":              _render_figure,
    "sample-counts-table": _render_sample_counts_table,
    "bmd-summary":         _render_bmd_summary,
    "genomics-section":    _render_genomics_section,
    "freeform-page":       _render_freeform_page,
    "freeform-block":      _render_freeform_block,
    "page-break":          _render_page_break,
}

# Fail loudly at import if this table drifts from the canonical registry — the
# same guarantee the HTML and LaTeX surfaces get (ADR-0006 #3).  Word implements
# every renderable type, so no omissions are allowed.
assert_dispatch_covers(_DISPATCH, renderer="Word/OOXML")


# ---------------------------------------------------------------------------
# Per-node layout styling (the docx twin of _layout_to_css_props / _layout_to_latex)
# ---------------------------------------------------------------------------

def _length_to_pt(value) -> "float | None":
    """A resolved-style length ('6pt', '0.5in') → points; None if unparseable or
    in a relative unit (em/ex) we can't resolve without the current font size."""
    m = _LENGTH_RE.match(str(value or ""))
    if not m:
        return None
    factor = _PT_PER_UNIT.get(m.group(2))
    return float(m.group(1)) * factor if factor is not None else None


def _resolve_font_name(style: dict) -> "str | None":
    """The concrete Word font for a resolved style: the literal `font` wins, else
    map `font_family` (serif/sans/mono) through _DOCX_FONT_BY_FAMILY.  See the
    precedence note in layout_style.LAYOUT_KEY_SCHEMA."""
    name = (style.get("font") or "").strip()
    if name:
        return name
    return _DOCX_FONT_BY_FAMILY.get(style.get("font_family"))


def _apply_run_style(run, style: dict) -> None:
    """Apply the character-level part of a resolved style to one run (delegates to
    _apply_font_style on the run's font)."""
    _apply_font_style(run.font, style)


def _apply_font_style(font, style: dict) -> None:
    """Apply the character-level part of a resolved style to a Font object — works
    for both a run's font and a named style's font (both expose the same Font API
    + a `_element` carrying an rPr).  So the same character logic bakes into a
    style DEFINITION (Phase 2) or overlays a run (legacy path)."""
    name = _resolve_font_name(style)
    if name:
        font.name = name
    size = _length_to_pt(style.get("font_size"))
    if size:
        font.size = Pt(size)
    weight = style.get("weight")
    if weight == "bold":
        font.bold = True
    elif weight == "normal":
        font.bold = False
    st = style.get("style")
    if st == "italic":
        font.italic = True
    elif st == "normal":
        font.italic = False
    tt = style.get("text_transform")
    if tt == "uppercase":
        font.all_caps = True   # w:caps — a DISPLAY transform (text unchanged)
    elif tt == "none":
        font.all_caps = False
    color = style.get("color")
    if isinstance(color, str) and color.startswith("#"):
        h = color.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) == 6:
            font.color.rgb = RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    # letter_spacing → rPr <w:spacing w:val="TWIPS"> (character spacing, in twips =
    # pt*20).  python-docx's Font exposes no `spacing`, so set it on the rPr
    # directly.  Font._element is the run (rPr host) or the style element (both
    # answer get_or_add_rPr).  Absolute units only (em/ex → _length_to_pt None).
    ls_pt = _length_to_pt(style.get("letter_spacing"))
    if ls_pt is not None:
        rpr = font._element.get_or_add_rPr()
        spacing = rpr.find(qn("w:spacing"))
        if spacing is None:
            spacing = OxmlElement("w:spacing")
            rpr.append(spacing)
        spacing.set(qn("w:val"), str(int(round(ls_pt * 20))))


def _apply_style_props_to_style(word_style, style: dict) -> None:
    """Apply a resolved style dict to a Word STYLE object (not a paragraph): its
    paragraph_format + its font.  Used to bake a vocabulary type's OWN delta into
    a named <w:style> (ADR-0010 Phase 2), so the style DEFINITION carries the
    property and every paragraph tagged with it inherits — the native Word model,
    unlike the per-paragraph overlay _apply_paragraph_style does for the legacy
    path.  Only the character part differs (a style has one .font, not runs)."""
    if not style:
        return
    pf = word_style.paragraph_format
    align = style.get("align")
    if align:
        pf.alignment = {
            "left": WD_ALIGN_PARAGRAPH.LEFT, "right": WD_ALIGN_PARAGRAPH.RIGHT,
            "center": WD_ALIGN_PARAGRAPH.CENTER, "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
        }.get(align)
    lh = style.get("line_height")
    if isinstance(lh, (int, float)) and not isinstance(lh, bool):
        pf.line_spacing = lh
    sb = _length_to_pt(style.get("space_before"))
    if sb is not None:
        pf.space_before = Pt(sb)
    sa = _length_to_pt(style.get("space_after"))
    if sa is not None:
        pf.space_after = Pt(sa)
    indent = _length_to_pt(style.get("first_line_indent"))
    if indent is not None:
        pf.first_line_indent = Pt(indent)
    if style.get("keep_together") is True:
        pf.keep_together = True
    if style.get("break_before") == "page":
        pf.page_break_before = True
    _apply_font_style(word_style.font, style)


def _apply_paragraph_style(paragraph, style: dict) -> None:
    """Apply the paragraph-level part of a resolved style to one paragraph, and
    the character-level part to each of its runs (so inheritance is explicit)."""
    pf = paragraph.paragraph_format
    align = style.get("align")
    if align:
        pf.alignment = {
            "left": WD_ALIGN_PARAGRAPH.LEFT, "right": WD_ALIGN_PARAGRAPH.RIGHT,
            "center": WD_ALIGN_PARAGRAPH.CENTER, "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
        }.get(align)
    lh = style.get("line_height")
    if isinstance(lh, (int, float)) and not isinstance(lh, bool):
        pf.line_spacing = lh
    sb = _length_to_pt(style.get("space_before"))
    if sb is not None:
        pf.space_before = Pt(sb)
    sa = _length_to_pt(style.get("space_after"))
    if sa is not None:
        pf.space_after = Pt(sa)
    indent = _length_to_pt(style.get("first_line_indent"))
    if indent is not None:
        pf.first_line_indent = Pt(indent)
    if style.get("keep_together") is True:
        pf.keep_together = True
    # NB: break_before / break_after are NODE-level flow, applied once at the node
    # boundary by _layout_to_docx (not here) — see the note there.  Applying them
    # per paragraph would break before/after EVERY paragraph of a multi-paragraph
    # node, diverging from HTML (one wrapping div) and LaTeX (one \clearpage).
    for run in paragraph.runs:
        _apply_run_style(run, style)


def _layout_to_docx(paragraphs, style: dict) -> None:
    r"""
    Apply a resolved abstract style spec to a run of paragraphs — the docx twin
    of html_generator._layout_to_css_props and latex_generator._layout_to_latex.

    Unlike those string-wrapping surfaces, Word is an object model: the node's
    handler has ALREADY appended its paragraphs, so this overlays the per-node
    ``types``/``instances`` styling onto them (the base ``Normal``/``Heading``
    style from _build_style_skeleton is the baseline; this wins over it, mirroring
    the other two surfaces' _wrap_style layering).  Empty style ⇒ no-op, so a
    style-less document is byte-identical to the pre-feature output.

    ``break_before`` / ``break_after`` are NODE-level flow and are applied ONCE
    here at the node boundary — before the first paragraph, after the last —
    matching HTML's single wrapping div and LaTeX's single \clearpage.  Word has
    no paragraph "page-break-after" property (OOXML only offers pageBreakBefore),
    so an after-break is emitted as a trailing page-break run; this is why the
    extractor can read ``break_before`` from a style but never ``break_after``.
    """
    if not style:
        return
    paragraphs = list(paragraphs)
    for paragraph in paragraphs:
        _apply_paragraph_style(paragraph, style)
    if not paragraphs:
        return
    if style.get("break_before") == "page":
        paragraphs[0].paragraph_format.page_break_before = True
    if style.get("break_after") == "page":
        paragraphs[-1].add_run().add_break(WD_BREAK.PAGE)


# ---------------------------------------------------------------------------
# Tree walk + document skeleton
# ---------------------------------------------------------------------------

def _walk_docx_tree(doc: Document, node: DocNode, data: dict) -> None:
    """
    Render a node and its descendants into the Document in document order.

    The Word analogue of html_generator._walk_html / latex_generator._walk_latex,
    but it can't reuse render_common.walk_emit: that skeleton accumulates markup
    STRINGS, whereas Word handlers mutate the Document.  So this runs the shared
    walk_tree primitive directly with a _visit callback that dispatches to the
    (doc, node, data) handlers — same pre-order traversal, object-model emit.

    Per-node layout styling (ADR-0006 parity with the other surfaces): the
    resolved ``types``/``instances`` spec is applied to exactly the paragraphs a
    node's handler added, by snapshotting the paragraph count before/after the
    handler runs.  The DECISION (resolved spec) is shared via
    data["layout_style"]; only this object-model application is surface-specific.
    """
    layout_cfg = data.get("layout_style")

    def _visit(n: DocNode) -> None:
        before = len(doc.paragraphs)
        handler = _DISPATCH.get(n.node_type, _render_unimplemented)
        handler(doc, n, data)
        # The title-page handler applies its own PER-ROLE styling (it folds in the
        # node-level types/instances layers itself); skip the generic uniform
        # overlay so it doesn't clobber the per-role fonts/sizes with one style.
        if layout_cfg and n.node_type != "title-page":
            style = resolve_layout_style(layout_cfg, n.node_type, n.id)
            if style:
                _layout_to_docx(doc.paragraphs[before:], style)

    walk_tree([node], _visit)


def _set_section_page_numbering(section, fmt: str, start: int) -> None:
    """
    Set a section's <w:pgNumType> format (lowerRoman / decimal) + start.

    <w:pgNumType> must sit at its schema-mandated position in CT_SectPr (after
    pgSz/pgMar, before cols) — a bare append lands it after docGrid, which is
    out of sequence and gets silently dropped on save.  We insert it before the
    first of the elements the schema says follow it, so the ordering is valid
    regardless of which of those a given section happens to carry.
    """
    sectPr = section._sectPr
    pgNumType = sectPr.find(qn("w:pgNumType"))
    if pgNumType is None:
        pgNumType = OxmlElement("w:pgNumType")
        _insert_in_schema_order(
            sectPr, pgNumType,
            successors=("w:cols", "w:formProt", "w:vAlign", "w:noEndnote",
                        "w:titlePg", "w:textDirection", "w:bidi", "w:rtlGutter",
                        "w:docGrid", "w:printerSettings", "w:sectPrChange"),
        )
    pgNumType.set(qn("w:fmt"), fmt)
    pgNumType.set(qn("w:start"), str(start))


def _insert_in_schema_order(parent, element, *, successors: tuple[str, ...]) -> None:
    """
    Insert ``element`` before the first existing child whose tag is in
    ``successors`` (the elements the schema requires to come AFTER it), else
    append.  Keeps a hand-built element valid against the OOXML sequence.
    """
    for tag in successors:
        found = parent.find(qn(tag))
        if found is not None:
            found.addprevious(element)
            return
    parent.append(element)


def _add_page_number_field(paragraph) -> None:
    """Insert a PAGE field into a (footer) paragraph, centered by the caller."""
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = "PAGE"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(instr)
    run._r.append(end)


def _emu_or_default(document: dict, key: str, default):
    """A document-level length in EMU (via docx Pt/Inches types) or the default.
    Lengths are stored as strings ('12pt', '1in'); parse to pt then to a
    Length."""
    pt = _length_to_pt(document.get(key)) if document else None
    return Pt(pt) if pt is not None else default


def _load_active_vocabulary(data: dict):
    """Load the vocabulary named by ``data['vocabulary']`` (a vocab/<name>.yaml
    stem), or None when unset — the opt-in switch for role-driven styling.  A load
    error is swallowed to None (fall back to legacy styling) rather than breaking
    generation; the vocabulary is an enhancement, not a hard dependency."""
    name = (data.get("vocabulary") or "").strip()
    if not name:
        return None
    try:
        import vocabulary as _vocab
        return _vocab.load_vocabulary(name)
    except Exception:
        return None


def _role_style_name(data: dict, role: str) -> "str | None":
    """The Word style name a vocabulary role maps to (its docx binding), or None
    when no vocabulary is active or the role is unknown — the switch that makes a
    handler apply a native pStyle only on the role-driven path, falling back to
    its legacy styling otherwise."""
    vocab = data.get("_vocabulary")
    if vocab is None or vocab.get(role) is None:
        return None
    import vocabulary as _vocab
    return _vocab.resolve_bindings(vocab, role)["docx"]


def _build_vocabulary_styles(doc: Document, vocab) -> None:
    """Emit the vocabulary's type graph as native Word paragraph styles (ADR-0010
    Phase 2): one <w:style> per type, styleId/name = its docx binding, basedOn =
    the specialization parent's binding, properties = the type's OWN style delta.
    The resulting styles.xml mirrors the NTP basedOn graph, so applying a role by
    pStyle resolves through the same inheritance the reference uses — and a
    co-author opening the docx sees the real named-style palette.

    Built in specialization order (parents before children) so base_style can be
    assigned.  A type whose docx binding is an EXISTING style (Normal, Heading 1)
    updates that style in place rather than adding a duplicate."""
    import vocabulary as _vocab
    from docx.enum.style import WD_STYLE_TYPE

    styles = doc.styles

    # Topological order: a type appears after its `specializes` parent.  The
    # graph is a shallow forest (roots → NTP roles), so a simple resolved-set
    # sweep terminates quickly.
    remaining = dict(vocab.types)
    ordered: list[str] = []
    placed: set[str] = set()
    while remaining:
        progressed = False
        for name, rec in list(remaining.items()):
            parent = rec.specializes
            if parent is None or parent in placed or parent not in vocab.types:
                ordered.append(name)
                placed.add(name)
                del remaining[name]
                progressed = True
        if not progressed:  # defensive: a cycle (validation should prevent this)
            ordered.extend(remaining)
            break

    for name in ordered:
        rec = vocab.types[name]
        bindings = _vocab.resolve_bindings(vocab, name)
        style_name = bindings["docx"]
        # Reuse an existing Word style of that name, else create a paragraph style.
        try:
            style = styles[style_name]
        except KeyError:
            style = styles.add_style(style_name, WD_STYLE_TYPE.PARAGRAPH)
        # basedOn = the parent type's docx style (skip if the parent isn't a real
        # style in the doc, e.g. a pure grouping root whose binding we didn't emit).
        # CRITICAL: skip when the parent binds to the SAME Word style name — a
        # curated alias (e.g. publisher_location) may reuse its concrete parent's
        # Word style; both vocab types then map to one physical <w:style>, and
        # setting basedOn to itself is a self-reference Word can't resolve (the
        # chain breaks → left/default rendering).  Same-name ⇒ same style ⇒ no edge.
        if rec.specializes and rec.specializes in vocab.types:
            parent_name = _vocab.resolve_bindings(vocab, rec.specializes)["docx"]
            if parent_name != style_name:
                try:
                    style.base_style = styles[parent_name]
                except KeyError:
                    pass
        # Apply ONLY this type's own delta (inheritance carries the rest), so the
        # emitted style mirrors the NTP delta-based definitions.
        if rec.style:
            _apply_style_props_to_style(style, rec.style)


def _neutralize_docdefaults_spacing(styles) -> None:
    """Remove python-docx's default docDefaults paragraph spacing entirely, so the
    document root is spacing-neutral like the NTP reference.

    A fresh Document() ships docDefaults pPr <w:spacing w:line="276" (1.15x)
    w:after="200" (10pt)> — the modern-Office default.  The NTP reference's
    docDefaults has NO spacing element at all (verified): every gap comes from the
    individual 1-NN/0-NN STYLES, never a document-wide default.  Leaving the
    default in place means (a) the title inherits 1.15x line spacing, and (b) a
    paragraph without its own space_after inherits a 10pt gap — which is why a
    hand-inserted paragraph on the title page opened a huge gap.  We drop the
    whole <w:spacing> element to match the reference; each style's own
    space_before/after then governs, and single line spacing applies by default.
    python-docx exposes no docDefaults API, so we edit the element directly.
    Idempotent + safe if the element is absent."""
    el = styles.element
    ppr = el.find(
        "/".join(qn(t) for t in ("w:docDefaults", "w:pPrDefault", "w:pPr"))
    )
    if ppr is None:
        return
    spacing = ppr.find(qn("w:spacing"))
    if spacing is not None:
        ppr.remove(spacing)


def _build_style_skeleton(doc: Document, document: dict | None = None) -> None:
    """
    Bind the base typography onto the document's Word styles BEFORE any content
    is walked, replacing Word's default theme (Calibri/Aptos).

    All handlers create paragraphs via the ``Normal`` / ``Heading 1-3`` styles,
    so restyling those here cascades to the whole document — the base look lives
    in ONE place rather than being set per run.  Fonts are named by FAMILY (the
    Font.name setter writes both w:ascii and w:hAnsi runProps), so Word uses the
    installed font regardless of its theme's minor/major font.

    ``document`` is the optional resolved document-level style block
    (styles.document); its ``default_font`` / ``default_font_size`` /
    ``header_font`` override the measured constants when present, so the base
    body/header fonts become DATA.  Absent ⇒ the measured reference constants.
    """
    document = document or {}
    body_font = (document.get("default_font") or "").strip() or _BODY_FONT
    body_size = _length_to_pt(document.get("default_font_size")) or _BODY_PT
    header_font = (document.get("header_font") or "").strip() or _BODY_FONT
    header_size = _length_to_pt(document.get("header_font_size")) or _HEADER_PT

    styles = doc.styles

    # Neutralize python-docx's non-reference docDefaults (ADR-0010): a fresh
    # Document() ships docDefaults pPr <w:spacing w:line="276" lineRule="auto">
    # (1.15x) + after=200, the modern-Office default.  The NTP reference sets NO
    # line spacing at the document root, so every part — including the title,
    # which inherits the root, not Normal — renders SINGLE.  Our 1.15x root is
    # exactly why the generated title looked mis-spaced.  Strip the docDefaults
    # paragraph spacing so the neutral single default (vocab/base.yaml `text`)
    # applies; Normal below still sets its own space_after for body paragraphs.
    _neutralize_docdefaults_spacing(styles)

    normal = styles["Normal"]
    normal.font.name = body_font
    normal.font.size = Pt(body_size)
    normal.font.color.rgb = _BLACK
    npf = normal.paragraph_format
    # Times' natural single spacing gives the reference's ~13.8pt line pitch;
    # block paragraphs (no first-line indent) with a little space after.
    npf.line_spacing_rule = WD_LINE_SPACING.SINGLE
    npf.space_before = Pt(0)
    npf.space_after = Pt(6)
    npf.first_line_indent = Pt(0)

    for level, size in _HEADING_PT.items():
        style = styles[f"Heading {level}"]
        style.font.name = _HEADING_FONT
        style.font.bold = True
        style.font.size = Pt(size)
        # Word's built-in headings are blue — the reference headings are black.
        style.font.color.rgb = _BLACK
        hpf = style.paragraph_format
        hpf.keep_with_next = True
        hpf.space_before = Pt(12)
        hpf.space_after = Pt(4)

    # The running header rides on the built-in "Header" style.
    header = styles["Header"]
    header.font.name = header_font
    header.font.size = Pt(header_size)


def _configure_section(section, running_header: str, document: dict | None = None) -> None:
    """US-Letter geometry + a running header + a centered page-number footer.

    ``document`` (the resolved styles.document block) overrides the page size,
    margins, and header distance when present; absent ⇒ the measured constants."""
    document = document or {}
    section.page_width = _emu_or_default(document, "page_width", _PAGE_WIDTH)
    section.page_height = _emu_or_default(document, "page_height", _PAGE_HEIGHT)
    section.top_margin = _emu_or_default(document, "margin_top", _MARGIN)
    section.bottom_margin = _emu_or_default(document, "margin_bottom", _MARGIN)
    section.left_margin = _emu_or_default(document, "margin_left", _MARGIN)
    section.right_margin = _emu_or_default(document, "margin_right", _MARGIN)
    hdr = _emu_or_default(document, "header_distance", _HEADER_FOOTER_DISTANCE)
    section.header_distance = hdr
    section.footer_distance = hdr

    header_para = section.header.paragraphs[0]
    header_para.text = _clean(running_header)
    header_para.alignment = WD_ALIGN_PARAGRAPH.CENTER

    footer_para = section.footer.paragraphs[0]
    footer_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _add_page_number_field(footer_para)


def generate_docx(data: dict, tree: "list | None" = None) -> bytes:
    """
    Walk the document tree + data and produce a complete .docx as bytes.

    Same data dict the other two surfaces consume (report_data.marshal_export_data
    / latex_export.load_session_data).  Front matter is roman-numbered and the
    body restarts at arabic 1 at first_body_node_id — the same boundary the
    HTML/LaTeX surfaces switch on, so the three agree on where front matter ends.

    Args:
        data: the render-ready data dict.
        tree: optional per-session DocNode forest; None uses DOCUMENT_TREE.

    Returns:
        The .docx file contents as bytes (ready to write to disk or stream).
    """
    nodes = tree if tree is not None else DOCUMENT_TREE
    running_header = data.get("running_header") or data.get("title") or "5dToxReport"
    # Optional document-level style block (page geometry + base fonts); absent ⇒
    # the measured reference constants.  Same styles config the per-node layer
    # reads, under its own "document" key.
    document = (data.get("layout_style") or {}).get("document") or {}

    doc = Document()
    _build_style_skeleton(doc, document)
    # Opt-in role-driven styling (ADR-0010 Phase 2): when the data dict names a
    # vocabulary, build its type graph as native Word styles so handlers can apply
    # them by pStyle and a co-author sees the real NTP palette.  Absent ⇒ the
    # legacy per-node styling path, byte-identical to before.
    vocab = _load_active_vocabulary(data)
    if vocab is not None:
        _build_vocabulary_styles(doc, vocab)
        # Stash on a shallow copy so handlers can resolve a role → Word style name
        # (via _role_style_name) without threading a new parameter.  Copy, don't
        # mutate the caller's dict.
        data = {**data, "_vocabulary": vocab}
    front_section = doc.sections[0]
    _configure_section(front_section, running_header, document)
    # No page number on the cover page itself (front matter numbering still
    # counts it as page i, matching the reference's unnumbered cover).
    front_section.different_first_page_header_footer = True

    body_first_id = first_body_node_id(nodes)
    added_body_section = False
    in_body = False

    for top in nodes:
        if body_first_id is not None and top.id == body_first_id and not in_body:
            # Section break → the body restarts page numbering at arabic 1.
            doc.add_section(WD_SECTION.NEW_PAGE)
            _configure_section(doc.sections[-1], running_header, document)
            added_body_section = True
            in_body = True
        _walk_docx_tree(doc, top, data)

    # Page-number formats: front matter lower-roman, body decimal-from-1.
    # add_section() relocates the FIRST section's <w:sectPr> into the last
    # body paragraph, so a reference captured before that call goes stale —
    # re-fetch both sections from doc.sections here, after all breaks are in.
    _set_section_page_numbering(doc.sections[0], "lowerRoman", 1)
    if added_body_section:
        _set_section_page_numbering(doc.sections[-1], "decimal", 1)

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()
