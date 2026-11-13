"""
test_inline_content.py — the minimal inline-content model (ext-link) and its
translation on all three surfaces (ADR-0010 inline sibling of the block catalog).

A hyperlink is SEMANTIC content (a display text + a target URI), not a styling
annotation; each surface derives its own presentation.  A paragraph is either a
plain str (unchanged) or a list of inline units (str runs + typed dicts).
"""

import rendering.render_common as rc
import rendering.html_generator as hg
import rendering.latex_generator as lg
import rendering.docx_generator as dg
from docx import Document
from docx.oxml.ns import qn


_PARA = [
    "Published by the ",
    rc.make_ext_link("NIEHS", "https://www.niehs.nih.gov/"),
    " and indexed in ",
    rc.make_ext_link("PubMed", "https://pubmed.ncbi.nlm.nih.gov/"),
    ".",
]


# ---------------------------------------------------------------------------
# The model in render_common
# ---------------------------------------------------------------------------

def test_normalize_inline_coerces_str_and_list():
    assert rc.normalize_inline("hello") == ["hello"]
    assert rc.normalize_inline("") == []
    assert rc.normalize_inline(None) == []
    assert rc.normalize_inline(_PARA) == _PARA


def test_inline_plain_text_flattens():
    assert rc.inline_plain_text("hello") == "hello"
    assert rc.inline_plain_text(_PARA) == "Published by the NIEHS and indexed in PubMed."


def test_paragraph_has_inline_only_for_typed_units():
    assert rc.paragraph_has_inline(_PARA) is True
    assert rc.paragraph_has_inline("plain") is False
    assert rc.paragraph_has_inline(["a", "b"]) is False   # plain runs, no typed unit


def test_has_paragraph_content_handles_inline_lists():
    assert rc.has_paragraph_content([_PARA]) is True
    assert rc.has_paragraph_content([[""]]) is False
    assert rc.has_paragraph_content(["plain"]) is True


# ---------------------------------------------------------------------------
# The three surface translations — a link is a link on every surface
# ---------------------------------------------------------------------------

def test_html_renders_anchor():
    out = hg._render_inline(_PARA)
    assert '<a href="https://www.niehs.nih.gov/">NIEHS</a>' in out
    assert '<a href="https://pubmed.ncbi.nlm.nih.gov/">PubMed</a>' in out


def test_latex_renders_href():
    out = lg._render_inline(_PARA)
    assert r"\href{https://www.niehs.nih.gov/}{NIEHS}" in out
    assert r"\href{https://pubmed.ncbi.nlm.nih.gov/}{PubMed}" in out


def test_docx_renders_hyperlink_relationships():
    doc = Document()
    para = doc.add_paragraph()
    dg._add_inline_runs(para, _PARA)
    links = para._p.findall(qn("w:hyperlink"))
    assert len(links) == 2
    targets = {r.target_ref for r in doc.part.rels.values() if "hyperlink" in r.reltype}
    assert "https://www.niehs.nih.gov/" in targets
    assert "https://pubmed.ncbi.nlm.nih.gov/" in targets
    # The display text is present, the URL is NOT inlined as text (it's the target).
    assert para.text == "Published by the NIEHS and indexed in PubMed."


def test_plain_string_paragraph_unchanged_on_all_surfaces():
    # A plain string keeps the exact pre-inline path (no <a>/\href/hyperlink).
    assert hg._render_inline("just prose") == "just prose"
    assert lg._render_inline("just prose") == "just prose"
    doc = Document(); p = doc.add_paragraph(); dg._add_inline_runs(p, "just prose")
    assert not p._p.findall(qn("w:hyperlink"))
    assert p.text == "just prose"


def test_unknown_inline_unit_degrades_to_text():
    para = ["see ", {"type": "xref", "text": "Table 1", "target": "t1"}]
    assert "Table 1" in hg._render_inline(para)
    assert "Table 1" in lg._render_inline(para)


# ---------------------------------------------------------------------------
# End-to-end: the foreword boilerplate carries its anchors on every surface
# ---------------------------------------------------------------------------

def test_foreword_hyperlinks_render_end_to_end():
    from rendering.report_data import scaffold_report_data
    from io import BytesIO
    data = scaffold_report_data(chemical_name="X", casrn="1-1-1", dtxsid="X")

    html = hg.generate_html(data)
    assert '<a href="https://www.niehs.nih.gov/">' in html
    assert 'href="https://pubmed.ncbi.nlm.nih.gov/"' in html

    tex = lg.generate_latex(data)
    assert r"\href{https://www.niehs.nih.gov/}" in tex

    doc = Document(BytesIO(dg.generate_docx(data)))
    targets = {r.target_ref for r in doc.part.rels.values() if "hyperlink" in r.reltype}
    assert {
        "https://www.niehs.nih.gov/",
        "https://www.niehs.nih.gov/research/atniehs/dtt/index.cfm",
        "https://pubmed.ncbi.nlm.nih.gov/",
    } <= targets


def test_italic_and_subscript_render_on_every_surface():
    """A gene symbol in italics and BMD_L's subscript L (the books' genomic
    results, rendering.genomics_results) on each surface."""
    from rendering.jats_generator import _p_inline
    from lxml import etree
    para = [rc.make_italic("Spp1"), " with a BMD (BMD", rc.make_sub("L"), ")"]
    assert hg._render_inline(para) == "<i>Spp1</i> with a BMD (BMD<sub>L</sub>)"
    assert lg._render_inline(para) == r"\textit{Spp1} with a BMD (BMD\textsubscript{L})"
    doc = Document(); p = doc.add_paragraph(); dg._add_inline_runs(p, para)
    runs = p.runs
    assert (runs[0].text, runs[0].italic) == ("Spp1", True)
    assert (runs[2].text, runs[2].font.subscript) == ("L", True)
    assert etree.tostring(_p_inline(para), encoding="unicode") == (
        "<p><italic>Spp1</italic> with a BMD (BMD<sub>L</sub>)</p>")


def test_superscript_and_bold_render_on_every_surface():
    """A footnote mark and a bold run (the published books' content,
    rendering.published_clone) on each surface."""
    from rendering.jats_generator import _p_inline
    from lxml import etree
    para = [rc.make_bold("Liver"), " weight", rc.make_sup("a")]
    assert hg._render_inline(para) == "<b>Liver</b> weight<sup>a</sup>"
    assert lg._render_inline(para) == r"\textbf{Liver} weight\textsuperscript{a}"
    doc = Document(); p = doc.add_paragraph(); dg._add_inline_runs(p, para)
    assert (p.runs[0].bold, p.runs[2].font.superscript) == (True, True)
    assert etree.tostring(_p_inline(para), encoding="unicode") == (
        "<p><bold>Liver</bold> weight<sup>a</sup></p>")


def test_a_matrix_with_header_rows_and_inline_cells_on_every_surface():
    """A published table (rendering.published_clone): two header rows, a cell
    with a footnote mark, an inline footnote — on each surface."""
    from lxml import etree
    from document_model.document_node import DocNode
    from rendering.jats_generator import _emit_sample_counts_table
    node = DocNode(id="t", title="T", node_type="data-table", data_key="m")
    data = {"m": {"caption": "Weights", "head_rows": [["", "Dose (mg/kg)", ""], ["n", "0", "10"]],
                  "rows": [["Male", "5", ["4", rc.make_sup("a")]]],
                  "footnotes": [{"kind": "definition", "text": [rc.make_sup("a"), "One died."]}]}}
    html = hg._render_sample_counts_table(node, data)
    assert html.count("<tr><th>") == 2 and "<td>4<sup>a</sup></td>" in html
    assert "<li><sup>a</sup>One died.</li>" in html
    latex = lg._render_sample_counts_table(node, data)
    assert r" & Dose (mg/kg) &  \\" in latex and r"4\textsuperscript{a}" in latex
    doc = Document(); dg._render_sample_counts_table(doc, node, data)
    table = doc.tables[0]
    assert len(table.rows) == 3 and table.rows[2].cells[2].text == "4a"
    assert table.rows[2].cells[2].paragraphs[0].runs[1].font.superscript
    (tw,) = _emit_sample_counts_table(node, data)
    xml = etree.tostring(tw, encoding="unicode")
    assert xml.count("<tr><th>") == 2 and "<td>4<sup>a</sup></td>" in xml
    assert "<fn><p><sup>a</sup>One died.</p></fn>" in xml
