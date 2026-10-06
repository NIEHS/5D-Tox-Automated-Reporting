"""Bookshelf litarch bundles → sections, tables, figures (tooling/bookshelf_breakdown).

Synthetic bundles in both layouts: the whole book in TOC.nxml (RR-8,
NIEHS-02…06) and one file per part ordered by the TOC (NIEHS-07 onward).
"""

import json

from lxml import etree

from tooling.bookshelf_breakdown import break_down, expand

_META = """<book-meta><book-id book-id-type="pmcid">niehs_99</book-id>
<book-id book-id-type="doi">10.22427/NIEHS-99</book-id>
<book-title-group><book-title>Study of X</book-title><subtitle>NIEHS Report 99</subtitle></book-title-group>
<pub-date><month>4</month><year>2026</year></pub-date>
<abstract><title>Abstract</title><sec><title>Background</title><p>X is used.</p></sec></abstract></book-meta>"""

_TABLE = """<table-wrap id="t-2-02"><label>Table&#x000a0;2</label>
<caption><title>Summary of Body Weights</title></caption>
<table><thead><tr><th>Endpoint<sup>a</sup></th><th>0&#x000a0;ppm</th><th>1&#x000a0;ppm</th></tr></thead>
<tbody><tr><td rowspan="2">Rats</td><td>10</td><td>5</td></tr>
<tr><td>190.0 &#x000b1; 3.8</td><td><italic>186.5</italic> &#x000b1; 4.0*</td></tr>
<tr><td colspan="3">Mice</td></tr></tbody></table>
<table-wrap-foot><fn><label>*</label><p>Statistically significant at p&#x000a0;&#x02264;&#x000a0;0.05.</p></fn></table-wrap-foot>
</table-wrap>"""


def _write(d, name, xml):
    (d / name).write_text('<?xml version="1.0"?>\n' + xml)


def test_spans_expand_into_a_full_grid():
    t = etree.fromstring('<tbody><tr><td rowspan="2">A</td><td colspan="2">B</td></tr>'
                         '<tr><td>c</td><td>d</td></tr></tbody>')
    assert expand(t.findall("tr")) == [["A", "B", "B"], ["A", "c", "d"]]


def test_single_file_book(tmp_path):
    _write(tmp_path, "TOC.nxml", f"""<book-part-wrapper id="toc">{_META}
<book-part><front-matter><front-matter-part id="fm1"><book-part-meta><title-group>
<title>Publication Details</title></title-group></book-part-meta><named-book-part-body><p>Details.</p>
</named-book-part-body></front-matter-part></front-matter>
<body><sec id="S1"><title>Background</title><p>Bg <xref>1</xref>.</p></sec>
<sec id="S3"><title>Results</title><sec><title>Body Weights</title><p>Text.</p>{_TABLE}</sec></sec></body>
<back><ref-list id="refs1"><title>References</title><ref><mixed-citation>Ref one.</mixed-citation></ref></ref-list>
<app id="a-2-A"><label>Appendix A</label><title>Data</title><fig id="fig-1"><label>Figure A-1</label>
<caption><p>A PCA plot</p></caption><graphic xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="img1"/></fig>
</app></back></book-part></book-part-wrapper>""")
    (tmp_path / "img1.jpg").write_bytes(b"jpg")
    (tmp_path / "SOURCE.txt").write_text("source: litarch (niehs_99_NBK123456.tar.gz)\n")
    rep = break_down(str(tmp_path), "NIEHS-99")
    assert rep["nbk"] == "NBK123456" and rep["published"] == "2026-04"
    assert [p["title"] for p in rep["parts"]] == [
        "Abstract", "Publication Details", "Background", "Results", "References", "Appendix A. Data"]
    t = json.loads((tmp_path / "breakdown/tables/t-2-02.json").read_text())
    assert t["label"] == "Table 2" and t["part"] == "Results" and t["section"] == ["Body Weights"]
    assert t["header"] == [["Endpoint<sup>a</sup>", "0 ppm", "1 ppm"]]
    # rowspan carried down, colspan across; cell text keeps its literal asterisk
    assert t["rows"] == [["Rats", "10", "5"], ["Rats", "190.0 ± 3.8", "186.5 ± 4.0*"], ["Mice"] * 3]
    assert t["footnotes"] == [{"label": "*", "text": "Statistically significant at p ≤ 0.05."}]
    assert rep["figures"][0]["file"] == "img1.jpg" and rep["figures"][0]["title"] == "A PCA plot"
    results = (tmp_path / "breakdown/sections/03_results.md").read_text()
    assert "## Body Weights" in results and "(../tables/t-2-02.md)" in results


def test_split_book_follows_toc_order(tmp_path):
    _write(tmp_path, "TOC.nxml", f"""<book-part-wrapper id="toc">{_META}<toc>
<toc-entry><nav-pointer><related-object document-id="bp1"/></nav-pointer></toc-entry>
<toc-entry><nav-pointer><related-object document-id="bp3"/></nav-pointer></toc-entry>
</toc></book-part-wrapper>""")
    for doc, title, body in (("bp3", "Results", f"<sec><title>Apical</title>{_TABLE}</sec>"),
                             ("bp1", "Background", "<p>Bg.</p>")):
        _write(tmp_path, f"{doc}.nxml", f"""<book-part-wrapper>{_META}<book-part><book-part-meta><title-group>
<title>{title}</title></title-group></book-part-meta><body>{body}</body></book-part></book-part-wrapper>""")
    rep = break_down(str(tmp_path), "NIEHS-99")
    assert [(p["key"], p["title"]) for p in rep["parts"]] == [
        ("abstract", "Abstract"), ("bp1", "Background"), ("bp3", "Results")]
    assert rep["tables"][0]["section"] == ["Apical"] and rep["tables"][0]["source"] == "bp3.nxml"
