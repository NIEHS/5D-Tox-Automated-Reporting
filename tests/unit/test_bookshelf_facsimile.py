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
    assert '<span class="label">C.1.</span> Gene Expression Quality Control' in app_c


def test_a_part_page_does_not_repeat_its_title(page):
    body = _article(page, "bp-methods").split('itemprop="text">', 1)[1]
    assert ">Materials and Methods</h" not in body
    assert ">Study Design</h2>" in body


def test_references_page_is_the_numbered_list(page):
    refs = _article(page, "bp-references")
    assert '<dt>1.</dt><dd><div class="bk_ref" id="ref1">First ref.</div></dd>' in refs


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


def test_a_single_file_book_is_one_page():
    """A single-file book (one whole-book <book-part>, NIEHS-02 … 06) is one
    page, as Bookshelf serves it: each part in reading order under its own h2
    ("Appendix A. Animals"), its sections a level below."""
    book = ("<book><book-meta><book-title-group><book-title>B</book-title>"
            "</book-title-group></book-meta><book-body><book-part id=\"book\">"
            "<book-part-meta><title-group><title>B</title></title-group></book-part-meta>"
            "<front-matter><ack id=\"a1\"><title>Acknowledgments</title><p>t</p></ack>"
            "</front-matter><body><sec id=\"s1\"><title>Background</title><p>x</p>"
            "<sec id=\"s1-1\"><title>Use</title><p>u</p></sec></sec></body>"
            "<back><app id=\"x\"><label>Appendix A</label><title>Animals</title>"
            "<sec id=\"x1\"><label>A.1</label><title>Ids</title><p>y</p></sec></app></back>"
            "</book-part></book-body></book>")
    html = render_book_xml(book)
    assert re.findall(r'<article class="bk-page" data-slug="([^"]+)"', html) == ["contents"]
    parts = re.findall(r'<div class="bk-part" id="([^"]+)"><h2 id="_\1_">([^<]+)</h2>', html)
    assert parts == [("a1", "Acknowledgments"), ("s1", "Background"), ("x", "Appendix A. Animals")]
    assert ">Use</h3>" in html and "Ids</h3>" in html
    assert "<h2>Contents</h2>" not in html


def test_published_bundle_renders():
    if not (BOOKSHELF / "NIEHS-10" / "TOC.nxml").exists():
        pytest.skip("published NIEHS-10 bundle not downloaded (assets/cebs/_bookshelf)")
    html = render_book_file(BOOKSHELF / "NIEHS-10")
    slugs = re.findall(r'<article class="bk-page" data-slug="([^"]+)"', html)
    assert len(slugs) == 1 + 17
    authors = _article(html, "fm-authors")
    assert '<div class="author">Scott S. Auerbach' in authors
    assert re.search(r'<div class="bk-formula" id="e-2-01">.*?<math.*?\(1\)</span>', html, re.S)
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
    # Not read on the page: the real page's hidden figure stash, the
    # facsimile's lightbox copies and its table thumbnails (a shrunken copy of
    # the table, where the real card shows an image).
    for el in body.xpath(".//*[contains(@style,'display:none') or contains(@class,'bk-object')"
                         " or contains(@class,'bk-thumb')]"):
        el.getparent().remove(el)
    # Nor NCBI's own lookups: the [PMC free article] / [PubMed] links Bookshelf
    # adds to references by matching them against its databases (a ref with no
    # PMID in the book can get one).  The book's DOIs ([CrossRef]) are compared.
    text = re.sub(r"\s*\[(PMC free article|PubMed)(: \w+)?\]", "", _txt(body))
    return {
        "banner": _txt(banner.xpath(".//h2")[0]),
        "details": [_txt(d) for d in banner.xpath(".//div[contains(@class,'ui-widget')]/div"
                                                   " | .//details/div")],
        "heading": _txt(root.xpath(".//div[contains(@class,'meta-content')]//h1")[0]),
        "text": text,
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


def _words(text: str) -> "collections.Counter":
    import collections
    return collections.Counter(re.findall(r"\w+", text.replace(" ", " ")))


@pytest.mark.parametrize("report", ["NIEHS-07", "NIEHS-08", "NIEHS-09", "NIEHS-10",
                                    "NIEHS-12", "NIEHS-13"])
def test_facsimile_drops_no_text_of_a_published_part(report):
    """Every word of every part of a published chunked book reaches the
    facsimile's page for it — no element's content is silently dropped (as
    <break/> once joined "then<break/>20" into "then20")."""
    from lxml import etree, html as lhtml

    bundle = BOOKSHELF / report
    if not (bundle / "TOC.nxml").exists():
        pytest.skip(f"published {report} bundle not downloaded (assets/cebs/_bookshelf)")
    page = lhtml.fromstring(render_book_file(bundle))
    parser = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False)
    for f in sorted(bundle.glob("*.nxml")):
        if f.name == "TOC.nxml":
            continue
        root = etree.parse(str(f), parser).getroot()
        part = next(c for c in root if isinstance(c.tag, str)
                    and c.tag not in ("collection-meta", "book-meta"))
        for meta in part.findall("book-part-meta"):
            for c in [c for c in meta if c.tag != "title-group"]:
                meta.remove(c)
        ours = page.xpath(f"//article[@data-slug='{f.stem}']")[0]
        missing = _words(" ".join(part.itertext())) - _words(" ".join(ours.itertext()))
        assert not missing, f"{report} {f.stem}: {list(missing.elements())[:20]}"


# PubReader pages (?report=reader) of the single-file NIEHS-02 (NBK585461),
# whose landing is the whole book, and of the chunked NIEHS-13 (NBK621744),
# whose landing lists its parts.
READER_02 = LANDING.parents[1] / "NIEHS-02" / "bookshelf-pages" / "toc-reader.html"
READER_13 = LANDING.parents[1] / "NIEHS-13" / "bookshelf-pages" / "toc-reader.html"


def _plain(el) -> str:
    # PubReader also breaks URLs with zero-width spaces; the classic page and
    # the facsimile with <wbr> only.
    return _txt(el).replace("​", "")


def _single_book_facts(root) -> dict:
    """What a reader sees on a single-file book's one page, from either the
    real page or the facsimile's: the title block, the abstract, the tables
    (label and caption — PubReader shows every table as a card, the classic
    view an appendix's in full), and each part's heading, section headings and
    text."""
    for el in root.xpath(".//*[contains(@class,'bk-object') or contains(@class,'bk-thumb')"
                         " or contains(@class,'bk_prnt')]"):
        el.getparent().remove(el)
    tables = []
    for t in root.xpath(".//div[contains(@class,'iconblock') and contains(@class,'table-wrap')]"
                        " | .//div[@class='table']"):
        if t.get("class") == "table":
            head = _plain(t.xpath("h3/span[@class='label']")[0])
            cap = t.xpath("h3/span[@class='title']")
        else:
            head = _plain(t.xpath(".//h4")[0])
            cap = t.xpath(".//p[contains(@class,'float-caption')]")
        tables.append((head, _plain(cap[0]).rstrip(". ") if cap else ""))
        t.getparent().remove(t)
    parts = root.xpath(".//div[@id][h2][not(ancestor::div[@itemprop='description'])]"
                       "[not(ancestor::div[@id][h2])]")
    return {
        "title": _plain(root.xpath(".//h1")[0]),
        "subtitle": _plain(root.xpath(".//div[@class='subtitle']")[0]),
        "series": _plain(root.xpath(".//p[i]")[0]),
        "authors": [_plain(a) for a in root.xpath(".//span[@itemprop='author']")],
        "affiliations": [_plain(a) for a in root.xpath(".//div[@class='affiliation']")],
        "abstract": [_plain(h) for h in root.xpath(".//h4[@class='inline']")],
        "tables": tables,
        "parts": [(p.get("id"), _plain(p.xpath("h2")[0]), [_plain(h) for h in p.xpath(".//h3")],
                   re.sub(r"\s*\[(PMC free article|PubMed)(: \w+)?\]", "", _plain(p)))
                  for p in parts],
    }


def test_single_file_book_is_one_page_like_the_real_bookshelf_page():
    """A single-file book (NIEHS-02) is one page on Bookshelf: its landing
    holds the title block, the abstract and every part under its h2, in
    reading order.  The facsimile of the published bundle shows the same."""
    from lxml import html as lhtml

    if not (BOOKSHELF / "NIEHS-02" / "TOC.nxml").exists():
        pytest.skip("published NIEHS-02 bundle not downloaded (assets/cebs/_bookshelf)")
    real = lhtml.fromstring(READER_02.read_text(encoding="utf-8"))
    page = lhtml.fromstring(render_book_file(BOOKSHELF / "NIEHS-02"))
    assert [a.get("data-slug") for a in page.xpath("//article[@class='bk-page']")] == ["contents"]
    ours = _single_book_facts(page.xpath("//article[@data-slug='contents']")[0])
    expected = _single_book_facts(real.xpath("//div[contains(@class,'main-content')]")[0])
    assert ours["parts"][-1][:2] == ("a-2-F", "Appendix F. Supplemental Data")
    assert ours == expected


def test_single_file_book_tables_match_the_real_ones():
    """Each table of the single-file NIEHS-02 — its cells and its notes — as
    the real page holds it (PubReader keeps the full tables after the text)."""
    from lxml import html as lhtml

    if not (BOOKSHELF / "NIEHS-02" / "TOC.nxml").exists():
        pytest.skip("published NIEHS-02 bundle not downloaded (assets/cebs/_bookshelf)")
    real = lhtml.fromstring(READER_02.read_text(encoding="utf-8"))
    page = lhtml.fromstring(render_book_file(BOOKSHELF / "NIEHS-02"))
    real_tables = real.xpath("//article[@data-type='table-wrap']")
    assert len(real_tables) == 13
    for art in real_tables:
        tid = art.xpath(".//*[starts-with(@id,'t-2-')]")[0].get("id")
        ours = page.xpath(f"//*[@id='obj-{tid}' or (@id='{tid}' and @class='table')]")
        assert ours, tid
        assert _plain(ours[0].xpath(".//table")[0]) == _plain(art.xpath(".//table")[0]), tid
        assert ([_plain(p) for p in ours[0].xpath(".//p[contains(@class,'no_margin')]")]
                == [_plain(p) for p in art.xpath(".//div[@class='tblwrap-foot']//p")]), tid


def test_chunked_book_contents_lists_the_real_parts():
    """The chunked NIEHS-13's landing lists the book's parts as Bookshelf does:
    the same title, and each part, by its location and its heading, in order."""
    from lxml import html as lhtml

    if not (BOOKSHELF / "NIEHS-13" / "TOC.nxml").exists():
        pytest.skip("published NIEHS-13 bundle not downloaded (assets/cebs/_bookshelf)")
    real = lhtml.fromstring(READER_13.read_text(encoding="utf-8"))
    page = lhtml.fromstring(render_book_file(BOOKSHELF / "NIEHS-13"))
    contents = page.xpath("//article[@data-slug='contents']")[0]
    assert _plain(contents.xpath(".//h1")[0]) == _plain(real.xpath("//div[@class='fm-sec']/h1")[0])
    expected = [(a.get("href").split("/")[-2], _plain(a))
                for a in real.xpath("//ul[contains(@class,'toc')]/li/a[@class='toc-item']")]
    assert len(expected) == 18
    assert [(a.get("href")[1:], _plain(a))
            for a in contents.xpath(".//ul[@class='bk-contents']/li/a[@class='toc-item']")] == expected
