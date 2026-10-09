"""
The Bookshelf facsimile (rendering.bookshelf_preview) renders the BITS book as
it is: one page per part in reading order, labels and headings from the parts
themselves (ADR-0028), a Contents landing with the abstract and the nested
sections; and it renders a chunked Bookshelf bundle — ours or a published
book's — the same way.
"""

import re

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
    assert '<div class="bk-abstract"><h2>Abstract</h2>' in contents
    methods = contents.split('href="#bp-methods">', 1)[1].split("</li></ul>", 1)[0]
    assert "Study Design" in methods and 'class="bk-contents c-nested"' in methods
    assert '<span class="c-label">Appendix A</span>' in contents


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
    assert 'class="li-p author"' in authors and "Scott S. Auerbach" in authors
    assert '<div class="bk-formula" id="e-2-01"><math' in html
    assert 'class="bk-media"' in _article(html, "a-2-F")
    assert "data:image/jpeg;base64," in _article(html, "a-2-C")
