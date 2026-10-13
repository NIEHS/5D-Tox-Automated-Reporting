"""A published report's companion: the published book's content as a session
(rendering.published_clone, tooling.published_clone, ADR-0029 §13).

One small BITS book holds every shape the clone maps — front parts, a
paragraph run split by a table, a table with two header rows and lettered
notes, a figure with a note and its label in its caption, a formula, an
appendix, the references, a collaboration author, a structured abstract — and
the companion built from it is rendered through the real surfaces."""

import io
import json
import zipfile

import pytest
import yaml
from lxml import etree

PNG = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")

BOOK = """<book xmlns:xlink="http://www.w3.org/1999/xlink">
<book-meta>
  <book-title-group>
    <book-title>NIEHS Report on the Test Study of Testium (CASRN 1-2-3) in Sprague Dawley Rats</book-title>
    <subtitle>NIEHS Report 99</subtitle>
  </book-title-group>
  <contrib-group content-type="authors">
    <contrib contrib-type="author"><collab>National Toxicology Program<contrib-group>
      <contrib><name><surname>Auerbach</surname><given-names>Scott S.</given-names></name></contrib>
      <contrib><name><surname>Cora</surname><given-names>Michelle C.</given-names></name></contrib>
    </contrib-group></collab><xref ref-type="aff" rid="aff-1"><sup>1</sup></xref></contrib>
    <aff id="aff-1"><label>1</label>Division of Translational Toxicology, NIEHS</aff>
  </contrib-group>
  <pub-date><month>03</month><year>2023</year></pub-date>
  <collection-meta collection-type="book-series"><title-group><title>NIEHS Report Series</title></title-group><issn>2768-5632</issn></collection-meta>
  <abstract>
    <sec><title>Background</title><p>Testium in Sprague Dawley<sup>&#x000ae;</sup> rats.</p></sec>
    <sec><title>Results</title><p>The BMD<sub>L</sub> was 1.2 mg/kg.</p></sec>
  </abstract>
</book-meta>
<front-matter>
  <foreword book-part-type="foreword" id="fw"><book-part-meta><title-group><title>Foreword</title></title-group></book-part-meta>
    <named-book-part-body><p>The foreword, as printed.</p></named-book-part-body></foreword>
  <front-matter-part book-part-type="contributors" id="fc"><book-part-meta><title-group><title>Contributors</title></title-group></book-part-meta>
    <named-book-part-body><p>Roles are listed below.</p>
      <table-wrap id="t-2-a"><caption><title>Author and Contributor Roles<sup>a</sup></title></caption>
        <table><thead><tr><th>Role</th><th>Definition</th></tr></thead>
        <tbody><tr><td>Conceptualization</td><td>Ideas</td></tr></tbody></table>
        <table-wrap-foot><fn id="fn-a"><label>a</label><p>From CRediT.</p></fn></table-wrap-foot>
      </table-wrap></named-book-part-body></front-matter-part>
</front-matter>
<book-body>
  <book-part book-part-type="section" id="ch-results"><book-part-meta><title-group><title>Results</title></title-group></book-part-meta>
    <body><sec id="S1"><title>Organ Weights</title>
      <p>Liver weight rose with dose <italic>in vivo</italic> (Table 1).<table-wrap id="t-2-01">
        <label>Table 1</label><caption><title>Liver Weights of Male Rats<sup>a</sup></title></caption>
        <table><thead>
          <tr><th rowspan="2">Endpoint</th><th colspan="2">Dose (mg/kg)</th></tr>
          <tr><th>0</th><th>441</th></tr></thead>
        <tbody><tr><td><bold>Liver</bold></td><td></td><td></td></tr>
          <tr><td>Absolute (g)</td><td>12.1</td><td><bold>441<sup>b</sup></bold></td></tr></tbody></table>
        <table-wrap-foot><fn id="fn-1a"><label><sup>a</sup></label><p>Mean &#x000b1; SE.</p></fn>
          <fn id="fn-1b"><label><sup>b</sup></label><p>p &#x02264; 0.05.</p></fn></table-wrap-foot>
      </table-wrap>Kidney weight did not change.</p>
      <p>The rate was computed as</p>
      <disp-formula id="e1"><mml:math xmlns:mml="http://www.w3.org/1998/Math/MathML"><mml:mtext>Rate = </mml:mtext><mml:mfrac><mml:mrow><mml:mtext>hits</mml:mtext></mml:mrow><mml:mrow><mml:mtext>2,680</mml:mtext></mml:mrow></mml:mfrac></mml:math><label>(1)</label></disp-formula>
    </sec></body></book-part>
  <book-part book-part-type="section" id="ch-refs"><book-part-meta><title-group><title>References</title></title-group></book-part-meta>
    <back><ref-list id="refs1"><ref id="r1"><label>1</label><mixed-citation>Doe J. <italic>A study</italic>. 2020.</mixed-citation></ref></ref-list></back></book-part>
</book-body>
<book-back><book-app-group>
  <book-app id="app-c" book-part-type="appendix"><book-part-meta><title-group><label>Appendix A</label><title>Transcriptomics</title></title-group></book-part-meta>
    <body><sec id="SC1"><title>Principal Components</title>
      <fig id="fig-c1"><caption><p>Figure A-1. A Principal Component Analysis<fn><p>Each point is an animal.</p></fn></p></caption>
        <graphic xlink:href="fig-c1.jpg"/></fig></sec></body></book-app>
</book-app-group></book-back>
</book>"""


@pytest.fixture
def clone():
    from rendering.published_clone import clone_book
    return clone_book(etree.fromstring(BOOK), {"fig-c1.jpg": f"data:image/png;base64,{PNG}"})


def _nodes(entries):
    for e in entries:
        yield e
        yield from _nodes(e.get("children") or [])


def _by_type(clone, kind):
    return [n for r in clone["document"] for n in _nodes(r["children"]) if n["type"] == kind]


def test_the_book_maps_to_node_entries_in_its_own_order(clone):
    front, body, back = clone["document"]
    assert [n["type"] for n in front["children"]][:4] == ["title-page", "front-matter", "toc",
                                                         "tables-list"]
    assert front["children"][1]["element"] == "foreword"
    assert front["children"][-1]["element"] == "abstract"
    results = body["children"][0]
    assert results["title"] == "Results" and results["type"] == "heading-only"
    sec = results["children"][0]
    # A paragraph split around its table: prose, the table, the rest of the prose.
    assert [k["type"] for k in sec["children"]] == ["narrative", "data-table", "narrative"]
    assert body["children"][1]["type"] == "reference-list"
    assert back["children"][0]["type"] == "appendix"
    assert back["children"][0]["title"] == "Transcriptomics"


def test_the_front_part_text_is_verbatim(clone):
    foreword = clone["document"][0]["children"][1]
    assert clone["content"][foreword["data_key"]]["verbatim"] is True
    assert clone["content"][foreword["data_key"]]["paragraphs"] == [["The foreword, as printed."]]


def test_a_table_keeps_its_header_rows_inline_cells_and_lettered_notes(clone):
    t1 = next(n for n in _by_type(clone, "data-table") if n["id"] == "clone-t-2-01")
    m = clone["content"][t1["data_key"]]
    # Spans expanded as bits_compare.expand_rows does: a row span repeats,
    # a column span leaves its cells blank.
    assert m["head_rows"] == [["Endpoint", "Dose (mg/kg)", ""], ["Endpoint", "0", "441"]]
    # A footnote mark inside a bold value keeps its own style.
    assert m["rows"][1][2] == [{"type": "bold", "text": "441"}, {"type": "sup", "text": "b"}]
    assert m["caption"] == ["Liver Weights of Male Rats", {"type": "sup", "text": "a"}]
    assert [f["letter"] for f in m["footnotes"]] == ["a", "b"]
    # The front table's note label is printed without a superscript.
    front_t = next(n for n in _by_type(clone, "data-table") if n["id"] == "clone-t-2-a")
    assert clone["content"][front_t["data_key"]]["footnotes"][0].get("letter_style") == "plain"
    assert ("table", "clone-t-2-01", "Table 1") in clone["labels"]


def test_a_figure_label_written_in_its_caption_is_taken_out(clone):
    fig = _by_type(clone, "figure")[0]
    payload = clone["content"][fig["data_key"]]
    assert payload["caption"] == "A Principal Component Analysis"
    assert payload["png_b64"] == PNG and payload["mimetype"] == "image/png"
    assert payload["notes"] == ["Each point is an animal."]
    assert ("figure", fig["id"], "Figure A-1") in clone["labels"]


def test_a_formula_reads_as_a_line_and_references_keep_their_numbers(clone):
    paras = [p for v in clone["content"].values() if isinstance(v, dict)
             for p in v.get("paragraphs") or []]
    assert ["Rate = hits / 2,680 (1)"] in paras
    assert clone["content"]["references"]["paragraphs"] == [
        ["[1] Doe J. ", {"type": "italic", "text": "A study"}, ". 2020."]]


def test_the_book_facts_and_a_collaboration_author(clone):
    front = clone["front"]
    assert front["subtitle"] == "NIEHS Report 99" and front["report_date"] == "March 2023"
    assert front["authors"] == [{"name": "National Toxicology Program",
                                 "affiliation": "Division of Translational Toxicology, NIEHS",
                                 "members": ["Scott S. Auerbach", "Michelle C. Cora"]}]
    assert front["abstract"]["parts"] == ["Background", "Results"]
    assert front["abstract"]["sections"][1]["text"] == [
        "The BMD", {"type": "sub", "text": "L"}, " was 1.2 mg/kg."]


# ---------------------------------------------------------------------------
# The companion session, rendered
# ---------------------------------------------------------------------------

def _companion(sessions_dir, clone, cid="DTXSID99_published", twin="DTXSID99"):
    from document_model.document_config import save_session_document_yaml
    from rendering.published_clone import CLONE_FILE, CONTENT_FILE
    d = sessions_dir / cid
    d.mkdir(parents=True)
    save_session_document_yaml(cid, yaml.safe_dump({"document": clone["document"]},
                                                   sort_keys=False, allow_unicode=True))
    (d / CONTENT_FILE).write_text(json.dumps(
        {"content": clone["content"], "front": clone["front"], "labels": clone["labels"]}))
    (d / "identity.json").write_text(json.dumps({"dtxsid": cid, "name": "Testium"}))
    (d / CLONE_FILE).write_text(json.dumps({"report": "NIEHS-99", "twin": twin, "format": 1}))
    return cid


def test_the_companion_numbers_its_tables_as_the_book_does(sessions_dir, clone):
    from document_model.document_tree import find_node
    from document_model.view_config import build_view_tree
    cid = _companion(sessions_dir, clone)
    tree = build_view_tree(cid, "default")
    assert find_node("clone-t-2-01", tree).table_number == 1
    front_table = find_node("clone-t-2-a", tree)       # the front matter's: unnumbered
    assert front_table.table_number is None and front_table.table_label is None
    fig = next(n for n in _by_type(clone, "figure"))
    node = find_node(fig["id"], tree)
    assert f"Figure {node.figure_label or node.figure_number}" == "Figure A-1"


def test_the_companion_renders_its_bits_as_the_book(sessions_dir, clone):
    from rendering.preview_surface import render_preview
    cid = _companion(sessions_dir, clone)
    bundle = render_preview(cid, surface="bits")
    with zipfile.ZipFile(io.BytesIO(bundle)) as z:      # the chunked bundle's parts
        text = "".join(z.read(n).decode("utf-8") for n in z.namelist()
                       if n.endswith((".xml", ".nxml")))
    assert "<book-title>NIEHS Report on the Test Study of Testium" in text
    assert "<subtitle>NIEHS Report 99</subtitle>" in text
    assert "<collab>National Toxicology Program<contrib-group>" in text
    assert "<td><bold>441</bold><sup>b</sup></td>" in text          # not pretty-printed apart
    assert "<label><sup>a</sup></label>" in text
    assert "Sprague Dawley<sup>®</sup> rats" in text


def test_the_companion_renders_through_html_and_docx(sessions_dir, clone):
    import re

    from docx import Document

    from rendering.preview_surface import render_preview
    cid = _companion(sessions_dir, clone)
    page = render_preview(cid, surface="html")
    assert "Each point is an animal." in page                     # the figure's note
    assert "Table 1. Liver Weights of Male Rats<sup>a</sup>" in page
    assert not re.search(r"<h[1-6][^>]*>\s*</h[1-6]>", page)        # untitled runs: no heading
    doc = Document(io.BytesIO(render_preview(cid, surface="docx")))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "NIEHS Report 99" in text and "March 2023" in text      # the cover states them
    assert "«" not in text


def test_the_shelf_links_a_companion_from_its_twin_and_back(sessions_dir, clone, monkeypatch):
    from fastapi.testclient import TestClient

    import web_routes.compare_routes as cr
    from web_routes import bookshelf_routes as br
    from web_routes.background_server import app

    twin = sessions_dir / "DTXSID99"
    twin.mkdir()
    (twin / "integrated.json").write_text("{}")
    (twin / "_cache_sections_0123456789abcdef.json").write_text("{}")
    cid = _companion(sessions_dir, clone)
    monkeypatch.setattr(cr, "published_report", {"DTXSID99": "NIEHS-99"}.get)

    published, unpublished = br.shelf_books()
    assert [(b["dtxsid"], b["companion"]) for b in published] == [("DTXSID99", cid)]
    assert not unpublished                                  # the companion is no book of its own
    shelf = TestClient(app).get("/Bookshelf").text
    assert f'href="/Bookshelf/{cid}">Published content' in shelf
    assert {"label": "Published content (NIEHS-99)", "href": f"/Bookshelf/{cid}"} in \
        br._download_links("DTXSID99")
    back = br._download_links(cid)
    assert {"label": "Generated report", "href": "/Bookshelf/DTXSID99"} in back
    assert {"label": "Compare with NIEHS-99", "href": "/Compare/DTXSID99"} in back
    assert br.has_generated_report(cid)


def test_the_companion_page_says_it_is_the_report_as_published(sessions_dir, clone):
    """A companion's Bookshelf page is how the report reads on Bookshelf as
    published, not a preview of how a generated report will read."""
    from rendering.preview_surface import render_preview
    cid = _companion(sessions_dir, clone)
    page = render_preview(cid, surface="bookshelf")
    assert "How the report reads on NCBI Bookshelf: NIEHS Report 99 as published" in page
    assert "A preview of how the report will read" not in page
    assert "preview</span>" not in page


def test_a_generated_report_page_is_still_a_preview():
    from rendering.bookshelf_preview import render_book_xml
    page = render_book_xml(BOOK)
    assert "A preview of how the report will read on NCBI Bookshelf" in page
    assert "as published" not in page


def test_a_generated_version_of_a_published_report_says_what_it_is_for():
    from rendering.bookshelf_preview import render_book_xml
    page = render_book_xml(BOOK, generated_of="NIEHS-99")
    assert ("A version of the report (already published), as generated by rlm-bmdx from the "
            "report&#8217;s BITS XML, and application pipeline. This may be used as a way of "
            "evaluating the report generation pipeline.") in page
    assert "A preview of how the report will read" not in page


def test_a_page_served_from_the_shelf_links_back_to_it():
    from rendering.bookshelf_preview import render_book_xml
    page = render_book_xml(BOOK, shelf="/Bookshelf")
    assert '<a class="bk-shelf" href="/Bookshelf">Bookshelf</a>' in page
    assert '<a href="/Bookshelf">rlm-bmdx Report Series</a>' in page
    alone = render_book_xml(BOOK)                       # a file has no shelf to link
    assert 'class="bk-shelf"' not in alone and "rlm-bmdx Report Series" not in alone
