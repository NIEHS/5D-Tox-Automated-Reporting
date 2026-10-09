"""rendering.bookshelf_landing — the facsimile's book landing page (the Contents
page) and the book-level pieces around it, as NCBI Bookshelf shows a book.

The reference is the real landing page of NIEHS Report 10 (NBK589955), kept at
tests/fixtures/reference/NIEHS-10/bookshelf-landing.html.  Everything shown is
read from the book's own book-meta and collection-meta, nothing is supplied
here:

  - the title block: the title, the subtitle ("NIEHS Report 10"), the series in
    italics, the authors ("A, B, and C."), an "Author Information and
    Affiliations" toggle (authors with affiliation numbers, then the
    affiliations), the publication line ("Loc: Publisher; 2023 Mar."), a
    "Copyright and Permissions" dialog and a link to the report at its DOI;
  - the abstract, each part led by an inline "Background:" heading;
  - the Contents: every part in reading order ("Appendix A. Title"), a body
    part's sections nested under it;
  - the "About the Series" box (series title, ISSN with its format);
  - for the rail, "Cite this Page" and "Other titles in this collection"; for
    the foot, the copyright notice and the DOI.

Every part's page (tests/fixtures/reference/NIEHS-10/bookshelf-pages/) opens
with the book banner (book_banner) and cites the book and the part
(cite_object).

Bookshelf ID and PMID, which the real page also shows, are assigned by NCBI at
ingest and are in no BITS file, so they are not shown.

Used by rendering.bookshelf_preview, whose inline helpers it shares.
"""

from __future__ import annotations

import re

from rendering.bookshelf_preview import _Page, _esc, _inline, _title_text, _ws_text

_MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
               "Nov", "Dec")

# "Cite this Page" names this many authors, then "et al." (NBK589955: 20
# authors → "Auerbach SS, Ballin JD, Blake JC, et al.").
_CITE_AUTHORS = 3


def _aff_text(aff) -> str:
    """An <aff>'s text without its <label>."""
    parts = [aff.text or ""]
    for child in aff:
        if child.tag != "label":
            parts.append("".join(child.itertext()))
        parts.append(child.tail or "")
    return " ".join("".join(parts).split())


def _initials(given: str) -> str:
    """NLM citation initials: "Scott S." → "SS", "Melanie A.R." → "MAR"."""
    return "".join(w[0] for w in re.split(r"[\s.\-]+", given) if w)


def _authors(bm) -> tuple[list[dict], list[tuple[str, str]]]:
    """The book's authors ({name, cite, affs}) and affiliations [(label, text)].
    The <aff>s sit inside the contrib-group (published) or beside it (ours)."""
    affs: list[tuple[str, str]] = []
    label_by_id: dict[str, str] = {}
    for n, aff in enumerate(bm.iter("aff"), start=1):
        label = _ws_text(aff.find("label")) or str(n)
        affs.append((label, _aff_text(aff)))
        if aff.get("id"):
            label_by_id[aff.get("id")] = label
    authors = []
    for c in bm.findall("contrib-group/contrib"):
        given, surname = _ws_text(c.find("name/given-names")), _ws_text(c.find("name/surname"))
        name = " ".join(x for x in (given, surname) if x) or _ws_text(c.find("string-name"))
        if not name:
            continue
        cite = " ".join(x for x in (surname, _initials(given)) if x) or name
        rids = [x.get("rid", "") for x in c.findall("xref[@ref-type='aff']")]
        authors.append({"name": name, "cite": cite,
                        "affs": [label_by_id[r] for r in rids if r in label_by_id]})
    return authors, affs


def book_facts(root) -> dict:
    """The book-level facts the masthead, the landing page and the rail show."""
    bm = root.find("book-meta")

    def get(path):
        return _ws_text(bm.find(path)) if bm is not None else ""

    authors, affs = _authors(bm) if bm is not None else ([], [])
    series = root.find("collection-meta[@collection-type='book-series']")
    collection = root.find("collection-meta[@collection-type='ncbi-books-collection']")
    issn = series.find("issn") if series is not None else None
    if issn is None and bm is not None:
        issn = bm.find("issn")
    title_el = bm.find("book-title-group/book-title") if bm is not None else None
    month = get("pub-date/month")
    return {
        "title": _ws_text(title_el) or "Untitled",
        "title_html": _inline(title_el) if title_el is not None else "Untitled",
        "subtitle": get("book-title-group/subtitle"),
        "series": _ws_text(series.find("title-group/title")) if series is not None else "",
        "collection": (_ws_text(collection.find("title-group/title"))
                       if collection is not None else ""),
        "authors": authors,
        "affiliations": affs,
        "publisher": get("publisher/publisher-name"),
        "loc": get("publisher/publisher-loc"),
        "issn": _ws_text(issn),
        "issn_format": (issn.get("publication-format") or "") if issn is not None else "",
        "license": get("permissions/license/license-p") or get("permissions/copyright-statement"),
        "year": get("pub-date/year"),
        "month": _MONTH_ABBR[int(month) - 1] if month.isdigit() and 1 <= int(month) <= 12 else "",
        "doi": get("book-id[@book-id-type='doi']"),
        "abstract": bm.find("abstract") if bm is not None else None,
    }


def _name_list(names: list[str]) -> str:
    """"A", "A and B", "A, B, and C" — as Bookshelf joins a contrib-group."""
    if len(names) <= 2:
        return " and ".join(names)
    return ", ".join(names[:-1]) + ", and " + names[-1]


def _pub_line(m: dict) -> str:
    """"Research Triangle Park (NC): National Institute …; 2023 Mar"."""
    where = ": ".join(x for x in (m["loc"], m["publisher"]) if x)
    when = " ".join(x for x in (m["year"], m["month"]) if x)
    return "; ".join(x for x in (where, when) if x)


def _cite_authors(m: dict) -> str:
    """"Auerbach SS, Ballin JD, Blake JC, et al." ("" with no authors)."""
    cites = [a["cite"] for a in m["authors"]]
    who = ", ".join(cites[:_CITE_AUTHORS]) + (", et al" if len(cites) > _CITE_AUTHORS else "")
    return f"{who}." if who else ""


def _internet_title(m: dict) -> str:
    """"Title: Subtitle [Internet]" — the book as a citation names it."""
    return ": ".join(x for x in (m["title"], m["subtitle"]) if x) + " [Internet]"


def citation(m: dict, part: str = "") -> str:
    """The "Cite this Page" text.  The landing page cites the book with its DOI
    ("Auerbach SS, … et al. Title: Subtitle [Internet]. Loc: Publisher;
    2023 Mar. doi: 10.22427/…"); a part's page cites the book without it,
    followed by the part's title ("…; 2023 Mar. Foreword.")."""
    out = [_cite_authors(m), f"{_internet_title(m)}."]
    if _pub_line(m):
        out.append(f"{_pub_line(m)}.")
    if part:
        out.append(f"{part}.")
    elif m["doi"]:
        out.append(f"doi: {m['doi']}")
    return " ".join(x for x in out if x)


def _author_info(m: dict) -> str:
    """The "Author Information and Affiliations" toggle: each author with the
    numbers of their affiliations, then the numbered affiliations."""
    if not m["authors"]:
        return ""
    names = [f'{_esc(a["name"])}' + (f'<sup>{_esc(",".join(a["affs"]))}</sup>' if a["affs"] else "")
             for a in m["authors"]]
    affs = "".join(f'<div class="affiliation"><sup>{_esc(n)}</sup> {_esc(t)}</div>'
                   for n, t in m["affiliations"])
    aff_block = f"<h4>Affiliations</h4>{affs}" if affs else ""
    return ('<details class="bk-authinfo"><summary>Author Information and Affiliations</summary>'
            f'<h4>Authors</h4><p class="contrib-group">{_name_list(names)}.</p>'
            f"{aff_block}</details>")


def _title_block(m: dict) -> str:
    sub = f'<div class="subtitle">{_esc(m["subtitle"])}</div>' if m["subtitle"] else ""
    series = f'<p class="bk-series-line"><i>{_esc(m["series"])}</i></p>' if m["series"] else ""
    authors = ""
    if m["authors"]:
        names = [f'<span itemprop="author">{_esc(a["name"])}</span>' for a in m["authors"]]
        authors = f'<p class="contrib-group">{_name_list(names)}.</p>'
    publine = (f'<div class="half_rhythm bk-pubinfo">{_esc(_pub_line(m))}.</div>'
               if _pub_line(m) else "")
    links = []
    if m["license"]:
        links.append('<a href="#" data-obj="obj-copyright">Copyright and Permissions</a>')
    if m["doi"]:
        links.append(_publisher_link(m))
    links_html = ('<ul class="inline_list bk-meta-links">'
                  + "".join(f"<li>{x}</li>" for x in links) + "</ul>") if links else ""
    copyright_obj = (f'<div class="bk-object" id="obj-copyright"><h3>Copyright and Permissions</h3>'
                     f'<p>{_esc(m["license"])}</p></div>') if m["license"] else ""
    return (f'<div class="meta-content fm-sec"><h1 class="book-h1">{m["title_html"]}</h1>'
            f'{sub}{series}{authors}{_author_info(m)}{publine}{links_html}{copyright_obj}</div>')


def _abstract_html(abs_el) -> str:
    """The structured abstract: each part's heading inline before its first
    paragraph ("Background:"), its other paragraphs following."""
    parts: list[str] = []
    for sec in abs_el.findall("sec"):
        label = _title_text(sec)
        head = f'<h4 class="inline">{_esc(label)}:</h4>' if label else ""
        paras = "".join(f"<p>{_inline(p)}</p>" for p in sec.findall("p"))
        sid = f' id="{_esc(sec.get("id"))}"' if sec.get("id") else ""
        parts.append(f'<div class="bk-abs-sec"{sid}>{head}{paras}</div>')
    if not parts:   # an unstructured abstract
        parts = [f"<p>{_inline(p)}</p>" for p in abs_el.findall("p")]
    title = _ws_text(abs_el.find("title")) or "Abstract"
    return f'<div class="bk-abstract" itemprop="description"><h2>{_esc(title)}</h2>{"".join(parts)}</div>'


def _series_box(m: dict) -> str:
    """"About the Series": the series title and its ISSN ("ISSN (Electronic):")."""
    if not (m["series"] or m["issn"]):
        return ""
    rows = [f'<div class="half_rhythm">{_esc(m["series"])}</div>'] if m["series"] else []
    if m["issn"]:
        fmt = f' ({m["issn_format"].capitalize()})' if m["issn_format"] else ""
        rows.append(f'<div class="half_rhythm">ISSN{_esc(fmt)}: {_esc(m["issn"])}</div>')
    return f'<div class="boxed bk-series"><h3>About the Series</h3>{"".join(rows)}</div>'


def contents_article(pages: list[_Page], m: dict) -> str:
    """The book's landing page: the title block, the abstract the book-meta
    carries, the Contents — every part in reading order, a body part's
    sections nested under it (the published <toc> shape) — and About the
    Series."""
    lis = []
    for p in pages:
        text = f"{p.label}. {p.title}" if p.label else p.title
        nested = ""
        if p.kind == "chapter" and p.subnav:
            nested = '<ul class="bk-contents c-nested">' + "".join(
                f'<li><a class="toc-item" href="#{_esc(sid)}">{_esc(stitle)}</a></li>'
                for sid, stitle in p.subnav) + "</ul>"
        lis.append(f'<li class="c-{p.kind}"><a class="toc-item" href="#{_esc(p.slug)}">'
                   f"{_esc(text)}</a>{nested}</li>")
    abstract = _abstract_html(m["abstract"]) if m["abstract"] is not None else ""
    return (f'<article class="bk-page" data-slug="contents" hidden>{_title_block(m)}'
            f'<div class="body-content whole_rhythm" itemprop="text">{abstract}'
            f'<h2>Contents</h2><ul class="bk-contents">{"".join(lis)}</ul>'
            f'{_series_box(m)}</div>{cite_object(m, "contents")}</article>')


# The rail's "Cite this Page" entry; the facsimile's script points it at the
# current page's citation (obj-cite-<slug>, see cite_object).
CITE_ITEM = '<li><a href="#" id="bk-cite" data-obj="obj-cite-contents">Cite this Page</a></li>'


def cite_object(m: dict, slug: str, part: str = "") -> str:
    """A page's "Cite this Page" dialog content (hidden until opened)."""
    return (f'<div class="bk-object" id="obj-cite-{_esc(slug)}"><h3>Cite this Page</h3>'
            f'<p class="bk-cite">{_esc(citation(m, part))}</p></div>')


def _publisher_link(m: dict) -> str:
    return (f'<a href="https://doi.org/{_esc(m["doi"])}" target="_blank" rel="noopener">'
            "View this report on the publisher&#8217;s website</a>") if m["doi"] else ""


def book_banner(m: dict) -> str:
    """The banner heading every part's page: the book as cited ("Title:
    Subtitle [Internet]."), a "Show details" toggle (authors as cited, the
    publication line), and links to the Contents and the publisher."""
    details = "".join(f"<div>{_esc(x)}</div>" for x in
                      (_cite_authors(m), f"{_pub_line(m)}." if _pub_line(m) else "") if x)
    toggle = (f"<details><summary>Show details</summary>{details}</details>"
              if details else "")
    links = ['<a class="bk_cntns" href="#contents">Contents</a>', _publisher_link(m)]
    sub = f": {_esc(m['subtitle'])}" if m["subtitle"] else ""
    return (f'<div class="iconblock bk-book-banner"><h2>{m["title_html"]}{sub} [Internet].</h2>'
            f'{toggle}<ul class="inline_list">'
            + "".join(f"<li>{x}</li>" for x in links if x) + "</ul></div>")


def collection_panel(m: dict) -> str:
    """The rail's "Other titles in this collection" panel."""
    if not m["collection"]:
        return ""
    return ('<div class="rail-panel"><div class="rail-title">Other titles in this collection'
            f'</div><ul class="rail-links"><li><span class="rail-text">{_esc(m["collection"])}'
            "</span></li></ul></div>")


def post_content(m: dict) -> str:
    """The foot of every page: the copyright notice and the DOI."""
    rows = []
    if m["license"]:
        rows.append(f'<p class="small"><strong>Copyright Notice.</strong> {_esc(m["license"])}</p>')
    if m["doi"]:
        rows.append(f'<p class="small">DOI: <a href="https://doi.org/{_esc(m["doi"])}" '
                    f'target="_blank" rel="noopener">{_esc(m["doi"])}</a></p>')
    return "".join(rows)
