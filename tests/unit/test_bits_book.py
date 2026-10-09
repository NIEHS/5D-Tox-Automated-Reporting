"""
ADR-0028: the BITS book has the published books' part structure, from the
scaffold report (no session needed).
"""

import pytest
from lxml import etree

from rendering.bits_bundle import outline, parse_book, structure_keys
from rendering.jats_generator import generate_bits
from rendering.jats_stylecheck import dtd_validate, stylecheck
from rendering.report_data import scaffold_report_data


_MATRIX = {"headers": ["Organ", "0 mg/kg"], "rows": [["Liver", "5"]], "footnotes": []}


@pytest.fixture(scope="module")
def scaffold() -> dict:
    data = scaffold_report_data(chemical_name="Perfluorohexanesulfonamide",
                                casrn="41997-13-1", dtxsid="DTXSID50469320")
    # Table 1 and the Appendix B roster, so their placement can be checked.
    data["sample_counts"] = dict(_MATRIX)
    data["appendix_animals_matrix"] = dict(_MATRIX)
    return data


@pytest.fixture(scope="module")
def book(scaffold):
    return parse_book(generate_bits(scaffold))


def _parts(book):
    return [(p.tag, p.get("book-part-type"), p.findtext("book-part-meta/title-group/title"))
            for region in ("front-matter", "book-body", "book-back")
            for p in book.find(region) if isinstance(p.tag, str)]


def test_the_parts_are_the_published_books(book):
    assert _parts(book) == [
        ("foreword", "foreword", "Foreword"),
        ("front-matter-part", "authors", "Authors"),
        ("front-matter-part", "contributors", "Contributors"),
        ("front-matter-part", "peer-review", "Peer Review"),
        ("front-matter-part", "section", "Publication Details"),
        ("front-matter-part", "acknowledgments", "Acknowledgments"),
        ("book-part", "section", "Background"),
        ("book-part", "section", "Materials and Methods"),
        ("book-part", "section", "Results"),
        ("book-part", "section", "Summary"),
        ("book-part", "section", "References"),
    ] + [("book-app", "appendix", t) for t in (
        "Internal Dose Assessment", "Animal Identifiers",
        "Transcriptomic Quality Control and Empirical False Discovery Rate",
        "Benchmark Dose Modeling and Acceptance Criteria", "Organ Weight Descriptions",
        "Supplemental Data")]


def test_a_part_body_does_not_repeat_its_title(book):
    for part in book.find("book-body"):
        body = part.find("body")
        if body is None:
            continue
        title = part.findtext("book-part-meta/title-group/title")
        assert not [s for s in body.findall("sec") if s.findtext("title") == title], title


def test_appendix_and_section_labels_are_separate(book):
    app_c = book.find("book-back")[2]
    assert app_c.findtext("book-part-meta/title-group/label") == "Appendix C"
    secs = app_c.findall("body/sec")
    assert [(s.findtext("label"), s.findtext("title")) for s in secs] == [
        ("C.1", "Gene Expression Quality Control"), ("C.2", "Empirical False Discovery Rate")]


def test_table_one_sits_in_its_section_with_a_caption_title(book):
    methods = book.find("book-body")[1]
    qc = next(s for s in methods.iter("sec")
              if s.findtext("title") == "Sequencing Quality Checks and Outlier Removal")
    tw = qc.find("table-wrap")
    assert tw is not None and tw.findtext("label") == "Table 1"
    assert tw.findtext("caption/title").startswith("Final Sample Counts")
    keys = structure_keys(outline(book))
    assert not any("Final Sample Counts" in k for k in keys), "Table 1 got a section of its own"


def test_appendix_tables_are_blocks_not_sections(book):
    app_b = book.find("book-back")[1]
    assert [c.tag for c in app_b.find("body") if isinstance(c.tag, str)] == ["table-wrap"]


def test_references_part_holds_a_numbered_ref_list():
    data = scaffold_report_data(chemical_name="X", casrn="1-1-1", dtxsid="DTXSID0000001")
    data["references"] = {"paragraphs": ["[1] First ref.", "[2] Second ref."]}
    refs = parse_book(generate_bits(data)).find("book-body")[-1]
    assert refs.find("body") is None
    rl = refs.find("back/ref-list")
    assert [(r.findtext("label"), r.findtext("mixed-citation")) for r in rl.findall("ref")] == [
        ("1", "First ref."), ("2", "Second ref.")]


def test_abstract_has_every_declared_part(book):
    ab = book.find("book-meta/abstract")
    assert ab.findtext("title") == "Abstract"
    assert [s.findtext("title") for s in ab.findall("sec")] == [
        "Background", "Methods", "Results", "Summary"]


def test_series_and_title_come_from_the_declarations(book):
    series = book.find("collection-meta[@collection-type='book-series']")
    assert series.findtext("title-group/title") == "NIEHS Report"
    assert series.findtext("issn") == "2768-5632"
    title = book.findtext("book-meta/book-title-group/book-title")
    assert title.startswith("NIEHS Report on the In Vivo Repeat Dose Biological Potency Study of "
                            "Perfluorohexanesulfonamide (CASRN 41997-13-1)")


def test_unsupplied_rosters_stay_visible_as_pending(book):
    authors = book.find("front-matter/front-matter-part[@book-part-type='authors']")
    assert "not supplied" in "".join(authors.itertext())
    assert book.find("book-meta/contrib-group") is None


def test_a_supplied_front_matter_fills_authors_title_and_meta():
    data = scaffold_report_data(chemical_name="X", casrn="1-1-1", dtxsid="DTXSID0000001")
    data["front_matter"] = {
        "authors": [{"name": "Ann Lee", "role": "Study Scientist", "affiliation": "NIEHS"},
                    {"name": "Bo Kim", "role": "", "affiliation": "Battelle"}],
        "contributors": [],
        "publication": {"report_number": "NIEHS Report 99", "doi": "10.22427/NIEHS-99",
                        "report_date": "March 2026"},
    }
    xml = generate_bits(data)
    book = parse_book(xml)
    bm = book.find("book-meta")
    assert bm.findtext("book-id[@book-id-type='doi']") == "10.22427/NIEHS-99"
    assert bm.findtext("book-title-group/subtitle") == "NIEHS Report 99"
    assert [(c.findtext("name/surname"), c.findtext("name/given-names"))
            for c in bm.findall("contrib-group/contrib")] == [("Lee", "Ann"), ("Kim", "Bo")]
    assert [a.get("id") for a in bm.findall("aff")] == ["aff-1", "aff-2"]
    assert (bm.findtext("pub-date/month"), bm.findtext("pub-date/year")) == ("03", "2026")
    items = book.findall("front-matter/front-matter-part[@book-part-type='authors']"
                         "/named-book-part-body/list/list-item")
    assert [[("".join(p.itertext()).strip(), p.get("content-type")) for p in i.findall("p")] for i in items] == [
        [("NIEHS", "author-affiliation"), ("Ann Lee, Study Scientist", "author")],
        [("Battelle", "author-affiliation"), ("Bo Kim", "author")],
    ]
    assert not dtd_validate(xml, "book"), dtd_validate(xml, "book")
    assert not stylecheck(xml, "book").errors


def test_scaffold_book_is_valid(scaffold):
    xml = generate_bits(scaffold)
    assert not dtd_validate(xml, "book")
    assert not stylecheck(xml, "book").errors
