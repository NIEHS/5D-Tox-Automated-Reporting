"""
ADR-0028 gate: our BITS book has the PUBLISHED book's structure.

The published NIEHS-10 book (NCBI litarch bundle, assets/cebs/_bookshelf/NIEHS-10,
gitignored) is reduced to its structural outline by rendering.bits_bundle and
committed as tests/fixtures/reference/NIEHS-10/bookshelf-outline.json
(regenerate: python -m tooling.bits_structure --reference NIEHS-10 --write-fixture).
Our book for the same study is reduced the same way and diffed.  What may still
differ is listed in KNOWN_CONTENT_GAPS — content we do not produce yet, never
structure — and the diff must equal that list exactly, so progress and
regressions both show up here.
"""

from pathlib import Path

import pytest

from rendering.bits_bundle import outline, parse_book, read_bundle, structure_keys
from tooling.bits_structure import BOOKSHELF, load_fixture, published_outline, structure_diff

REPO = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# The bundle reader + outline (synthetic, always runs)
# ---------------------------------------------------------------------------

_META = ("<collection-meta><title-group><title>Series</title></title-group></collection-meta>"
         "<book-meta><book-title-group><book-title>Study of X</book-title>"
         "<subtitle>Report 9</subtitle></book-title-group>{abstract}</book-meta>")


def _wrapper(doc_id: str, where: str, part: str, abstract: str = "") -> str:
    return (f'<book-part-wrapper id="{doc_id}" content-type="section" from-where="{where}">'
            f"{_META.format(abstract=abstract)}{part}</book-part-wrapper>")


def _bundle(tmp_path: Path) -> Path:
    toc = (_wrapper("toc", "", "", abstract="<abstract><title>Abstract</title>"
                    "<sec><title>Background</title><p>b</p></sec></abstract>")
           .replace("</book-part-wrapper>", "")
           + "<toc>"
           + "".join(f'<toc-entry><title>{i}</title><nav-pointer><related-object '
                     f'document-id="{i}"/></nav-pointer></toc-entry>'
                     for i in ("fw", "bp1", "app-a"))
           + "</toc></book-part-wrapper>")
    (tmp_path / "TOC.nxml").write_text(toc)
    (tmp_path / "fw.nxml").write_text(_wrapper(
        "fw", "front-matter",
        '<foreword book-part-type="foreword"><book-part-meta><title-group><title>Foreword'
        "</title></title-group></book-part-meta><named-book-part-body><p>x</p>"
        "</named-book-part-body></foreword>"))
    (tmp_path / "bp1.nxml").write_text(_wrapper(
        "bp1", "body",
        '<book-part book-part-type="section"><book-part-meta><title-group><title>Methods'
        '</title></title-group></book-part-meta><body><sec id="S1" sec-type="other1">'
        "<title>Design</title><p>p</p><table-wrap id=\"t1\"><label>Table 1</label>"
        "<caption><title>Counts</title></caption><table/></table-wrap></sec></body></book-part>"))
    (tmp_path / "app-a.nxml").write_text(_wrapper(
        "app-a", "back",
        '<book-app book-part-type="appendix"><book-part-meta><title-group><label>Appendix A'
        "</label><title>Dose</title></title-group></book-part-meta><body><sec><label>A.1</label>"
        "<title>Plasma</title><p>q</p></sec></body></book-app>"))
    return tmp_path


def test_reader_assembles_a_chunked_bundle_in_toc_order(tmp_path):
    book = read_bundle(_bundle(tmp_path))
    assert [c.tag for c in book] == ["collection-meta", "book-meta", "front-matter",
                                     "book-body", "book-back"]
    assert book.find("book-body/book-part/body/sec/title").text == "Design"


def test_outline_is_structure_without_converter_artefacts(tmp_path):
    keys = structure_keys(outline(read_bundle(_bundle(tmp_path))))
    assert keys == [
        "book-title Study of X",
        "subtitle Report 9",
        "abstract Abstract",
        "  sec Background",
        "foreword [foreword] Foreword",
        "book-part [section] Methods",
        "  sec Design",
        "    table-wrap <Table 1>",     # caption wording is content, not structure
        "book-app [appendix] <Appendix A> Dose",
        "  sec <A.1> Plasma",
    ]


def test_reader_takes_a_single_book_file(tmp_path):
    p = tmp_path / "book.xml"
    p.write_text('<book><book-body><book-part book-part-type="section"><book-part-meta>'
                 "<title-group><title>Background</title></title-group></book-part-meta>"
                 "<body><p>x</p></body></book-part></book-body></book>")
    assert structure_keys(outline(read_bundle(p))) == ["book-part [section] Background"]


# ---------------------------------------------------------------------------
# The committed reference outline
# ---------------------------------------------------------------------------

def test_reference_fixture_is_the_published_bundle():
    """The committed outline is what the bundle reduces to (when the gitignored
    bundle is present to check against)."""
    if not (BOOKSHELF / "NIEHS-10" / "TOC.nxml").exists():
        pytest.skip("published NIEHS-10 bundle not downloaded (assets/cebs/_bookshelf)")
    assert load_fixture("NIEHS-10") == published_outline("NIEHS-10")


def test_reference_fixture_has_the_published_parts():
    parts = [e for e in load_fixture("NIEHS-10") if e.depth == 0]
    kinds = [(e.kind, e.part_type) for e in parts
             if e.kind not in ("book-title", "subtitle", "contrib-group", "abstract")]
    assert kinds == (
        [("foreword", "foreword"), ("front-matter-part", "authors"),
         ("front-matter-part", "contributors"), ("front-matter-part", "peer-review"),
         ("front-matter-part", "section"), ("front-matter-part", "acknowledgments")]
        + [("book-part", "section")] * 5
        + [("book-app", "appendix")] * 6
    )


# ---------------------------------------------------------------------------
# Ours against the published book
# ---------------------------------------------------------------------------

# What our NIEHS-10 book still lacks or has differently, as `-` (published only)
# / `+` (ours only) outline lines.  CONTENT gaps only — each needs data or
# authored content the pipeline does not produce yet:
KNOWN_CONTENT_GAPS: list[str] = []


@pytest.mark.xfail(strict=True, reason="ADR-0028 structure refactor in progress")
def test_niehs10_structure_matches_published(real_session_50469320):
    from rendering.jats_generator import generate_bits
    from rendering.latex_export import load_session_data
    data = load_session_data(dtxsid="DTXSID50469320",
                             chemical_name="Perfluorohexanesulfonamide",
                             casrn="41997-13-1")
    ours = outline(parse_book(generate_bits(data)))
    assert structure_diff(load_fixture("NIEHS-10"), ours) == KNOWN_CONTENT_GAPS
