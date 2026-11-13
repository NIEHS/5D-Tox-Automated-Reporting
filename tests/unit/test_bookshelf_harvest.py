"""The host-side Bookshelf harvester's offline parts: naming, fetch plan, page links.

tooling/bookshelf_harvest.py runs on the host (Bookshelf gates the sandbox
behind reCAPTCHA); these pin what it fetches from a book's E-utilities records.
"""

from tooling.bookshelf_harvest import catalogue, images, is_gated, object_links, plan, report_name

_RECORDS = [
    {"uid": "1", "rtype": "book", "title": "NIEHS Report on … Studies of 1,4-Dichlorobenzene: NIEHS Report 13",
     "id": "niehs_13/PMC", "accessionid": "NBK621744", "pubdate": "2026/04/01 00:00"},
    {"uid": "2", "rtype": "sec", "title": "Results", "id": "niehs_13/sec/bp3/PMC", "accessionid": "NBK621727"},
    {"uid": "3", "rtype": "sec", "title": "Apical Endpoint Analysis", "id": "niehs_13/bp3/sec/S12/PMC",
     "accessionid": "NBK621727"},
    {"uid": "4", "rtype": "table", "title": "Table 2. Summary of Body Weights and Body Weight Gain",
     "id": "niehs_13/bp3/table/t-2-02/PMC", "accessionid": "NBK621727"},
]


def test_report_names_from_titles():
    assert report_name(_RECORDS[0]["title"], "x") == "NIEHS-13"
    assert report_name("NIEHS Report 2", "x") == "NIEHS-02"
    assert report_name("NTP Research Report on … Triphenyl Phosphate: Research Report 8", "x") == "RR-8"
    assert report_name("Something else", "ntpniehs10") == "ntpniehs10"


def test_plan_fetches_pdf_parts_and_full_tables():
    urls = {j["path"]: j["url"] for j in plan(_RECORDS)}
    assert urls["Bookshelf_NBK621744.pdf"].endswith("/books/NBK621744/pdf/Bookshelf_NBK621744.pdf")
    assert urls["parts/NBK621727.html"].endswith("/books/NBK621727/")   # one page per part
    assert urls["table/NBK621727_t-2-02.html"].endswith("/books/NBK621727/table/t-2-02/?report=objectonly")
    assert len(urls) == 4


def test_pages_yield_figures_and_images():
    html = (b'<a href="/books/NBK621727/figure/f2-01/?report=objectonly">Figure 1</a>'
            b'<img src="/books/NBK621727/bin/f2-01.jpg">')
    assert [j["path"] for j in object_links(html)] == ["figure/NBK621727_f2-01.html"]
    assert images(html) == [("https://www.ncbi.nlm.nih.gov/books/NBK621727/bin/f2-01.jpg",
                             "bin/NBK621727_f2-01.jpg")]


def test_recaptcha_page_is_not_content():
    assert is_gated(b'<html><head><base href="https://www.google.com/recaptcha/challengepage/">')
    assert not is_gated(b"<html><head><title>Results - NIEHS Report 13</title>")


def test_catalogue_lists_tables_under_their_part():
    md = catalogue("NIEHS-13", _RECORDS)
    assert "## Results  (NBK621727, `parts/NBK621727.html`)" in md
    assert "- table: Table 2. Summary of Body Weights and Body Weight Gain  `table/NBK621727_t-2-02.html`" in md
