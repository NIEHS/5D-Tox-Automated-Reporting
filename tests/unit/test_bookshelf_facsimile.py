"""
The Bookshelf facsimile (rendering.bookshelf_preview) renders the BITS book as
it is: one page per part in reading order, labels and headings from the parts
themselves (ADR-0028), a Contents landing with the abstract and the nested
sections; and it renders a chunked Bookshelf bundle — ours or a published
book's — the same way.
"""

import re
from pathlib import Path

import pytest

from rendering.bookshelf_preview import render_book_file, render_book_xml
from rendering.jats_generator import generate_bits
from rendering.report_data import scaffold_report_data
from tooling.bits_structure import BOOKSHELF


@pytest.fixture(scope="module")
def page() -> str:
    data = scaffold_report_data(chemical_name="Perfluorohexanesulfonamide",
                                casrn="41997-13-1", dtxsid="DTXSID50469320")
    data["references"] = {"paragraphs": ["[1] First ref.", "[2] Second ref."]}
    return render_book_xml(generate_bits(data))


def _article(html: str, slug: str) -> str:
    m = re.search(rf'<article class="bk-page" data-slug="{re.escape(slug)}" hidden>(.*?)</article>',
                  html, re.S)
    assert m, slug
    return m.group(1)


def test_one_page_per_part_in_reading_order(page):
    slugs = re.findall(r'<article class="bk-page" data-slug="([^"]+)"', page)
    assert slugs[:8] == ["contents", "fm-foreword", "fm-authors", "fm-contributors",
                         "fm-peer-review", "fm-publication", "fm-acknowledgments",
                         "bp-background"]
    assert slugs[-7:] == ["bp-references", "app-appendix-a", "app-appendix-b", "app-appendix-c",
                          "app-appendix-d", "app-appendix-e", "app-appendix-f"]


def test_labels_come_from_the_book(page):
    app_c = _article(page, "app-appendix-c")
    assert '<span class="label">Appendix C</span>' in app_c
    assert '<span class="label">C.1</span> Gene Expression Quality Control' in app_c


def test_a_part_page_does_not_repeat_its_title(page):
    body = _article(page, "bp-methods").split('itemprop="text">', 1)[1]
    assert ">Materials and Methods</h" not in body
    assert ">Study Design</h2>" in body


def test_references_page_is_the_numbered_list(page):
    refs = _article(page, "bp-references")
    assert '<li id="ref1" value="1">First ref.</li>' in refs


def test_contents_has_the_abstract_and_nested_sections(page):
    contents = _article(page, "contents")
    assert '<div class="bk-abstract" itemprop="description"><h2>Abstract</h2>' in contents
    methods = contents.split('href="#bp-methods">', 1)[1].split("</li></ul>", 1)[0]
    assert "Study Design" in methods and 'class="bk-contents c-nested"' in methods
    assert re.search(r'>Appendix A\. [^<]+</a>', contents)


def test_landing_shows_the_series_facts_the_book_declares(page):
    contents = _article(page, "contents")
    assert '<p class="bk-series-line"><i>NIEHS Report</i></p>' in contents
    assert "<h3>About the Series</h3>" in contents
    assert "ISSN (Electronic): 2768-5632" in contents
    assert 'data-obj="obj-copyright"' in contents
    assert 'id="bk-cite" data-obj="obj-cite-contents"' in page
    assert re.search(r'id="obj-cite-contents">.*?\[Internet\]\.', contents)
    foreword = _article(page, "fm-foreword")
    assert '<div class="iconblock bk-book-banner">' in foreword
    assert re.search(r'id="obj-cite-fm-foreword">.*?\[Internet\]\..*? Foreword\.</p>', foreword)
    assert "Other titles in this collection" in page and "NIEHS Report Series" in page


def test_a_chunked_bundle_renders_like_the_book(tmp_path):
    from rendering.bits_bundle import split_book

    data = scaffold_report_data(chemical_name="X", casrn="1-1-1", dtxsid="DTXSID0000001")
    for name, content in split_book(generate_bits(data)).items():
        (tmp_path / name).write_bytes(content)
    html = render_book_file(tmp_path)
    slugs = re.findall(r'<article class="bk-page" data-slug="([^"]+)"', html)
    assert slugs[1:3] == ["fm-foreword", "fm-authors"]    # ids from <book-part-id>
    assert '<span class="label">Appendix B</span>' in html


def test_published_bundle_renders():
    if not (BOOKSHELF / "NIEHS-10" / "TOC.nxml").exists():
        pytest.skip("published NIEHS-10 bundle not downloaded (assets/cebs/_bookshelf)")
    html = render_book_file(BOOKSHELF / "NIEHS-10")
    slugs = re.findall(r'<article class="bk-page" data-slug="([^"]+)"', html)
    assert len(slugs) == 1 + 17
    authors = _article(html, "fm-authors")
    assert '<div class="author">Scott S. Auerbach' in authors
    assert '<div class="bk-formula" id="e-2-01"><math' in html
    assert 'class="bk-media"' in _article(html, "a-2-F")
    assert "data:image/jpeg;base64," in _article(html, "a-2-C")


# The real Bookshelf landing page of NIEHS Report 10 (NBK589955).
LANDING = (Path(__file__).resolve().parents[1] / "fixtures" / "reference" / "NIEHS-10"
           / "bookshelf-landing.html")


def _txt(el) -> str:
    return " ".join("".join(el.itertext()).replace(" ", " ").split())


def _landing_facts(root) -> dict:
    """What a reader sees on a book's landing page, from either the real page
    or the facsimile's Contents article."""
    meta = root.xpath(".//div[contains(@class,'meta-content')]")[0]
    box = root.xpath(".//div[h3='About the Series']")[0]
    return {
        "title": _txt(meta.xpath(".//h1")[0]),
        "subtitle": _txt(meta.xpath(".//div[@class='subtitle']")[0]),
        "series": _txt(meta.xpath(".//p[i]")[0]),
        "authors": _txt(meta.xpath(".//p[@class='contrib-group']")[0]),
        "publication": _txt(meta.xpath(".//div[contains(@class,'half_rhythm')]")[0]),
        "affiliations": [_txt(a) for a in meta.xpath(".//div[@class='affiliation']")],
        "abstract": [(_txt(h), len(h.xpath("following-sibling::p")))
                     for h in root.xpath(".//h4[@class='inline']")],
        "contents": [(len(a.xpath("ancestor::ul")), _txt(a))
                     for a in root.xpath(".//a[contains(@class,'toc-item')]")],
        "about_series": [_txt(d) for d in box.xpath("div")],
    }


def test_published_book_landing_matches_the_real_bookshelf_page():
    """The published NIEHS-10 bundle through the facsimile gives the landing
    page Bookshelf serves for it: title block, abstract, contents, series box
    and the Cite this Page text."""
    from lxml import html as lhtml

    if not (BOOKSHELF / "NIEHS-10" / "TOC.nxml").exists():
        pytest.skip("published NIEHS-10 bundle not downloaded (assets/cebs/_bookshelf)")
    real = lhtml.fromstring(LANDING.read_text(encoding="utf-8"))
    page = lhtml.fromstring(render_book_file(BOOKSHELF / "NIEHS-10"))
    ours = page.xpath("//article[@data-slug='contents']")[0]
    assert _landing_facts(ours) == _landing_facts(real)
    assert (_txt(page.xpath("//div[@id='obj-cite-contents']/p")[0])
            == _txt(real.xpath("//div[@class='bk_tt']")[0]))


PAGES = LANDING.parent / "bookshelf-pages"


def _part_page_facts(root) -> dict:
    """What a reader sees on a part's page, from either the real page or the
    facsimile's article for it: the book banner, the heading, the content (its
    text and its simple lists' lines) and the page's citation."""
    banner = root.xpath(".//div[contains(@class,'iconblock')]")[0]
    body = root.xpath(".//div[contains(@class,'body-content')]")[0]
    return {
        "banner": _txt(banner.xpath(".//h2")[0]),
        "details": [_txt(d) for d in banner.xpath(".//div[contains(@class,'ui-widget')]/div"
                                                   " | .//details/div")],
        "heading": _txt(root.xpath(".//div[contains(@class,'meta-content')]//h1")[0]),
        "text": _txt(body),
        "lists": [[_txt(d) for d in li.xpath("div")]
                  for li in body.xpath(".//ul[contains(@class,'simple-list')]/li")],
        "cite": _txt(root.xpath(".//div[@class='bk_tt'] | .//div[starts-with(@id,'obj-cite-')]/p")[0]),
    }


@pytest.mark.parametrize("real_page", sorted(PAGES.glob("*.html")), ids=lambda p: p.stem)
def test_published_part_page_matches_the_real_bookshelf_page(real_page):
    """Each saved Bookshelf page of NIEHS-10 (named by its Bookshelf location,
    which is the part's id in the bundle) and the facsimile's page for that
    part show the same banner, heading, content and citation."""
    from lxml import html as lhtml

    if not (BOOKSHELF / "NIEHS-10" / "TOC.nxml").exists():
        pytest.skip("published NIEHS-10 bundle not downloaded (assets/cebs/_bookshelf)")
    real = lhtml.fromstring(real_page.read_text(encoding="utf-8"))
    page = lhtml.fromstring(render_book_file(BOOKSHELF / "NIEHS-10"))
    ours = page.xpath(f"//article[@data-slug='{real_page.stem}']")
    assert ours, f"no facsimile page for {real_page.stem}"
    assert _part_page_facts(ours[0]) == _part_page_facts(real)
