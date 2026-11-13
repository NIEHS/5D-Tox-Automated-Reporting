"""
rendering/published_clone.py — a published report's content as one of ours: the
companion of an app-generated published report (ADR-0029 §13).

The published books are local as Bookshelf BITS bundles
(assets/cebs/_bookshelf/<REPORT>).  ``clone_book`` turns one into what a
session renders from — a document structure (node entries, the declaration a
session's document.yaml holds) and the content each node binds — so the book's
own text, tables and figures render through our four surfaces like any report,
beside the report the app generates from the study's data
(tooling.published_clone builds the ``<DTXSID>_published`` sessions).

What becomes what, in the published order:

  foreword / front-matter-part / ack   a front-matter part (its element and
                                       book-part-type as published)
  book-part, sec                       a section (heading-only), nesting kept
  a run of p / list / formula / media  an untitled narrative: its paragraphs,
                                       inline italic / bold / sup / sub / links
                                       kept; a cross-reference is its text
  table-wrap                           a data-table: caption, header rows, body
                                       rows (spans on the grid, a full-width row
                                       a group row), lettered footnotes
  fig                                  a figure, the bundle's image
  book-app / app                       an appendix
  a part holding only a ref-list       the References (reference-list)
  book-meta                            the title, report number, date, authors,
                                       publisher, series and abstract

Numbers are not copied: tables, figures and appendices are numbered by the
tree, positionally, as every report is.  In the book's own order they come out
as the book's; the companion's check (tooling.published_clone --check) says
where they do not.  What the model cannot hold is stated, not hidden: a list
is paragraphs (its marker kept), a formula its text, a supplied file its name.
"""

from __future__ import annotations

import re

from rendering.bits_compare import XLINK, expand_rows, text_of
from rendering.render_common import (
    INLINE_BOLD, INLINE_ITALIC, INLINE_SUB, INLINE_SUP, inline_plain_text, make_ext_link,
)

CLONE_FILE = "published_clone.json"
CONTENT_FILE = "published_content.json"
# Raised when what clone_book makes changes, so built companions are rebuilt.
FORMAT = 10

_STYLE = {"italic": INLINE_ITALIC, "bold": INLINE_BOLD, "sup": INLINE_SUP, "sub": INLINE_SUB}
_SKIP_INLINE = frozenset({"fn", "label"})
_FLOW_WRAPPERS = frozenset({"body", "named-book-part-body", "back", "boxed-text", "disp-quote",
                            "fig-group", "app-group", "fn-group"})
_NO_CONTENT = frozenset({"title", "label", "sec-meta", "book-part-meta", "alt-title",
                         "object-id", "title-group"})
_BREAKABLE_ROWS = 25


def _ln(el) -> str:
    return el.tag.split("}")[-1] if isinstance(el.tag, str) else ""


# ---------------------------------------------------------------------------
# Inline text → inline units
# ---------------------------------------------------------------------------

def _flat(el) -> str:
    """An element's text, every descendant's included (a styled run's)."""
    return "".join(t for t in el.itertext())


def _units(el, skip: frozenset = _SKIP_INLINE) -> list:
    out: list = [el.text or ""]
    for c in el:
        out += _unit(c, skip)
        out.append(c.tail or "")
    return out


def _unit(c, skip: frozenset) -> list:
    tag = _ln(c)
    if not tag or tag in skip:
        return []
    if tag == "break":
        return [" "]
    if tag in _STYLE:
        # The model holds one style per run: a run styled inside this one
        # (a footnote mark in a bold value) keeps its own; the rest takes this.
        out = []
        for u in _units(c, skip):
            if isinstance(u, str):
                if u:
                    out.append({"type": _STYLE[tag], "text": u})
            else:
                out.append(u)
        return out if any(inline_plain_text([u]).strip() for u in out) else []
    if tag in ("ext-link", "uri"):
        text = _flat(c)
        href = c.get(XLINK) or text
        return [make_ext_link(text or href, href)] if (text or href).strip() else []
    # xref, named-content, sc, monospace, MathML …: their content.
    return _units(c, skip)


_WS = re.compile(r"[ \t\r\n]+")


def tidy(units: list) -> list:
    """Inline units with runs of whitespace collapsed (no-break spaces kept, as
    the book prints them), adjacent text joined and the ends stripped."""
    out: list = []
    for u in units:
        if isinstance(u, str):
            u = _WS.sub(" ", u)
            if not u:
                continue
            if out and isinstance(out[-1], str):
                out[-1] = _WS.sub(" ", out[-1] + u)
                continue
        else:
            u = dict(u, text=_WS.sub(" ", u.get("text", "")))
            if not u["text"].strip():
                # A styled run of spaces only (an indent in a bold cell) is
                # just the spaces.
                u = u["text"]
                if out and isinstance(out[-1], str):
                    out[-1] = _WS.sub(" ", out[-1] + u)
                else:
                    out.append(u)
                continue
        out.append(u)
    if out and isinstance(out[0], str):
        out[0] = out[0].lstrip()
    if out and isinstance(out[-1], str):
        out[-1] = out[-1].rstrip()
    return [u for u in out if u != ""]


def inline(el, skip: frozenset = _SKIP_INLINE) -> list:
    """An element's text as tidy inline units."""
    return tidy(_units(el, skip)) if el is not None else []


def _cell(units: list):
    """A table cell: plain text as a str, else its inline units."""
    return inline_plain_text(units) if all(isinstance(u, str) for u in units) else units


def plain(el) -> str:
    return inline_plain_text(inline(el))


def _text(value) -> str:
    """A str, or inline units as their text."""
    return inline_plain_text(value) if isinstance(value, list) else (value or "")


# ---------------------------------------------------------------------------
# The flow inside a container
# ---------------------------------------------------------------------------

_BLOCKS_IN_P = frozenset({"table-wrap", "fig", "list", "media", "disp-formula", "disp-quote",
                          "boxed-text", "supplementary-material", "fig-group"})


def _math_text(el) -> str:
    """A MathML expression as plain text (see _flow, disp-formula)."""
    kids = list(el)
    if _ln(el) == "mfrac" and len(kids) == 2:
        return f"{_math_text(kids[0]).strip()} / {_math_text(kids[1]).strip()}"
    return (el.text or "") + "".join(_math_text(k) + (k.tail or "") for k in kids)


def _flow(container):
    """(kind, element-or-units) items of a container in reading order: "p"
    (inline units), "table", "fig", "sec", "refs" — a <p> split around any block
    element nested in it, wrappers (body, boxed-text …) walked through, lists,
    formulas and supplied files as paragraphs."""
    for c in container:
        tag = _ln(c)
        if not tag or tag in _NO_CONTENT:
            continue
        if tag == "p":
            buf = [c.text or ""]
            for k in c:
                if _ln(k) in _BLOCKS_IN_P:
                    if inline_plain_text(tidy(buf)).strip():
                        yield "p", tidy(buf)
                    yield from _flow([k])
                    buf = [k.tail or ""]
                else:
                    buf += _unit(k, _SKIP_INLINE)
                    buf.append(k.tail or "")
            if inline_plain_text(tidy(buf)).strip():
                yield "p", tidy(buf)
        elif tag == "list":
            yield from _list_items(c)
        elif tag == "table-wrap":
            yield "table", c
        elif tag == "fig":
            yield "fig", c
        elif tag in ("sec", "app"):
            yield "sec", c
        elif tag == "ref-list":
            yield "refs", c
        elif tag in ("media", "supplementary-material") and c.get(XLINK):
            yield "file", c
        elif tag in ("media", "supplementary-material"):
            label = plain(c.find("label"))
            caption = inline(c.find("caption")) or inline(c)
            href = c.get(XLINK) or ""
            units = ([f"{label}. "] if label else []) + caption + (
                [f" ({href})"] if href and href not in inline_plain_text(caption) else [])
            if inline_plain_text(units).strip():
                yield "p", tidy(units)
        elif tag == "disp-formula":
            # MathML is not in the model: the formula as a line of text, a
            # fraction as "numerator / denominator", its number after.
            math = next((m for m in c if _ln(m) == "math"), None)
            text = _WS.sub(" ", _math_text(math) if math is not None
                           else inline_plain_text(inline(c, frozenset({"label"})))).strip()
            label = plain(c.find("label"))
            if text:
                yield "p", [text + (f"\u2003{label}" if label else "")]
        elif tag in _FLOW_WRAPPERS:
            yield from _flow(c)
        elif tag == "fn":
            label = plain(c.find("label"))
            units = [u for p in c.findall("p") for u in inline(p) + [" "]]
            if units:
                yield "p", tidy(([{"type": INLINE_SUP, "text": label}] if label else []) + units)
        else:
            units = inline(c)
            if inline_plain_text(units).strip():
                yield "p", units


def _list_items(lst):
    """A list's items as paragraphs.  The marker a list type implies (a
    bullet, a number) is presentation, not the book's text, so only an item's
    own <label> is kept."""
    for item in lst.findall("list-item"):
        marker = plain(item.find("label"))
        first = True
        for c in item:
            tag = _ln(c)
            if tag == "list":
                yield from _list_items(c)
            elif tag == "p":
                units = inline(c)
                if inline_plain_text(units).strip():
                    yield "p", (tidy([f"{marker} "] + units) if first and marker else units)
                    first = False


# ---------------------------------------------------------------------------
# Tables and figures
# ---------------------------------------------------------------------------

def _caption(el) -> str:
    return inline_plain_text(caption_units(el))


def caption_units(el) -> list:
    """A table's or figure's caption — its title and paragraphs — as inline
    units (a footnote mark, BMD_L's subscript kept)."""
    cap = el.find("caption")
    if cap is None:
        return []
    out: list = []
    for part in [cap.find("title"), *cap.findall("p")]:
        units = inline(part) if part is not None else []
        if inline_plain_text(units).strip():
            out += ([" "] if out else []) + units
    return tidy(out)


_LABEL_IN_TEXT = re.compile(r"^\s*((?:Table|Figure)\s+[A-Z]?-?\d+)\.\s*")


def _label_and_caption(el) -> tuple[str, list]:
    """An object's label and caption.  Where the book writes the label into
    the caption ("Figure C-1. A Principal …", NIEHS-02 … 06) rather than in
    <label>, it is taken out: the tree numbers the object."""
    label, units = plain(el.find("label")), caption_units(el)
    if not label and units and isinstance(units[0], str):
        m = _LABEL_IN_TEXT.match(units[0])
        if m:
            label = m.group(1)
            units = tidy([units[0][m.end():]] + units[1:])
    return label, units


def table_matrix(tw) -> tuple[str, dict]:
    """(label, the data-table matrix) of a <table-wrap>."""
    head = [tr for tr in tw.iter("tr") if _ln(tr.getparent()) == "thead"]
    body = [tr for tr in tw.iter("tr") if _ln(tr.getparent()) != "thead"]
    if not head and body and all(_ln(c) == "th" for c in body[0] if _ln(c)):
        head, body = body[:1], body[1:]
    cell = lambda c: _cell(inline(c))   # noqa: E731
    head_rows = expand_rows(head, cell=cell)
    rows = expand_rows(body, cell=cell)
    width = max((len(r) for r in head_rows + rows), default=0)
    for i, tr in enumerate(body):
        cells = [c for c in tr if _ln(c) in ("td", "th")]
        if len(cells) == 1 and width > 1 and int(cells[0].get("colspan") or 1) >= width:
            label = plain(cells[0])
            if label:
                rows[i] = [f"**{label}**"] + [""] * (width - 1)
    footnotes = []
    for fn in tw.findall("table-wrap-foot//fn"):
        label = fn.find("label")
        letter = plain(label)
        units = tidy([u for p in fn.findall("p") for u in inline(p) + [" "]]) or inline(fn)
        if units and letter:
            note = {"kind": "lettered", "letter": letter, "text": _cell(units)}
            if label.find("sup") is None:
                note["letter_style"] = "plain"
            footnotes.append(note)
        elif units:
            footnotes.append({"kind": "definition", "text": _cell(units)})
    for p in tw.findall("table-wrap-foot/p"):
        units = inline(p)
        if units:
            footnotes.append({"kind": "definition", "text": _cell(units)})
    label, caption = _label_and_caption(tw)
    matrix = {"caption": _cell(caption), "head_rows": head_rows, "rows": rows,
              "footnotes": footnotes}
    if len(rows) > _BREAKABLE_ROWS:
        matrix["breakable"] = True
    return label, matrix


def figure_payload(fig, images: dict) -> tuple[str, dict | None]:
    """(label, the figure payload {png_b64, filename, mimetype, caption}) of a
    <fig>; no payload when the bundle has no image for it."""
    g = fig.find(".//graphic")
    href = (g.get(XLINK) or "") if g is not None else ""
    uri = images.get(href) or ""
    m = re.match(r"data:([^;]+);base64,(.*)", uri, re.S)
    notes = [_cell(inline(p)) for p in fig.findall("caption//fn/p")]
    notes += [_cell(inline(a)) for a in fig.findall("attrib")]
    label, caption = _label_and_caption(fig)
    payload = ({"png_b64": m.group(2), "filename": href, "mimetype": m.group(1),
                "caption": inline_plain_text(caption), "notes": [n for n in notes if n]}
               if m else None)
    return label, payload


# ---------------------------------------------------------------------------
# The book
# ---------------------------------------------------------------------------

class _Cloner:
    def __init__(self, images: dict):
        self.images = images
        self.in_front = False      # a front-matter part holds no supplied files
        self.content: dict = {}
        self.ids: set[str] = set()
        self.labels: list[tuple[str, str, str]] = []   # (kind, node id, published label)

    def nid(self, el, kind: str) -> str:
        base = re.sub(r"[^A-Za-z0-9_-]+", "-", (el.get("id") if el is not None else "") or "")
        base = f"clone-{base.strip('-') or kind}"
        nid, n = base, 1
        while nid in self.ids:
            n += 1
            nid = f"{base}-{n}"
        self.ids.add(nid)
        return nid

    def _key(self, nid: str) -> str:
        return nid.replace("-", "_")

    def prose(self, paragraphs: list, at=None) -> dict:
        nid = self.nid(at, "text")
        self.content[self._key(nid)] = {"paragraphs": paragraphs}
        return {"id": nid, "type": "narrative", "title": "", "data_key": self._key(nid),
                "binding": "programmatic"}

    def children(self, container) -> list[dict]:
        """The node entries of a container's flow."""
        out: list[dict] = []
        run: list = []

        def flush():
            if run:
                out.append(self.prose(list(run)))
                run.clear()

        for kind, item in _flow(container if isinstance(container, list) else list(container)):
            if kind == "p":
                run.append(item)
                continue
            flush()
            if kind == "table":
                out.append(self.table(item))
            elif kind == "fig":
                entry = self.figure(item)
                if entry:
                    out.append(entry)
            elif kind == "sec":
                out += self.section(item)
            elif kind == "refs":
                out.append(self.prose(self.references(item), item))
            elif kind == "file":
                out += self.supplied(item, run)
        flush()
        return out

    def section(self, sec) -> list[dict]:
        title = plain(sec.find("title")) or plain(sec.find("label"))
        if not title:                       # an untitled sec: its content is the parent's
            return self.children(sec)
        return [{"id": self.nid(sec, "sec"), "type": "heading-only", "title": title,
                 "children": self.children(sec)}]

    def table(self, tw) -> dict:
        nid = self.nid(tw, "table")
        label, matrix = table_matrix(tw)
        self.content[self._key(nid)] = matrix
        self.labels.append(("table", nid, label))
        return {"id": nid, "type": "data-table",
                "title": _text(matrix["caption"]) or label or "Table",
                "data_key": self._key(nid)}

    def figure(self, fig) -> dict | None:
        nid = self.nid(fig, "fig")
        label, payload = figure_payload(fig, self.images)
        self.labels.append(("figure", nid, label))
        if payload:
            self.content[self._key(nid)] = payload
        title = (payload or {}).get("caption") or _text(_label_and_caption(fig)[1])
        return {"id": nid, "type": "figure", "subtype": "chart",
                "title": title or label or "Figure", "data_key": self._key(nid)}

    def supplied(self, el, run: list) -> list[dict]:
        """A supplied file: a supplementary-material node (its caption's title,
        the file), or in the front matter, where none may stand, a paragraph."""
        href = el.get(XLINK)
        title = _caption(el) or plain(el.find("label")) or href
        if self.in_front:
            run.append([f"{title} ({href})"])
            return []
        return [{"id": self.nid(el, "file"), "type": "supplementary-material",
                 "title": title, "content_file": href}]

    @staticmethod
    def references(rl) -> list:
        out = []
        for ref in rl.findall("ref"):
            cit = ref.find("mixed-citation")
            if cit is None:
                cit = ref.find("element-citation")
            units = inline(cit if cit is not None else ref, frozenset({"fn", "label"}))
            label = plain(ref.find("label"))
            if units:
                out.append(tidy([f"[{label}] "] + units) if label else units)
        return out

    def references_only(self, part) -> list | None:
        """The citations of a part that holds nothing but a ref-list."""
        lists = [e for e in part.iter() if _ln(e) == "ref-list"]
        if len(lists) != 1:
            return None
        rl = lists[0]
        others = [e for e in part.iter() if _ln(e) in ("p", "table-wrap", "fig", "sec", "list")
                  and rl not in e.iterancestors() and e not in rl.iter()]
        return None if others else self.references(rl)

    def part(self, el, region: str) -> dict | None:
        tag = _ln(el)
        meta = el.find("book-part-meta/title-group")
        title = plain((meta if meta is not None else el).find("title")) or \
            plain((meta if meta is not None else el).find("label"))
        btype = el.get("book-part-type")
        refs = self.references_only(el)
        if refs is not None and (tag in ("book-part", "ref-list") or region == "back"):
            self.content["references"] = {"paragraphs": refs}
            entry = {"id": self.nid(el, "references"), "type": "reference-list",
                     "title": title or "References", "data_key": "references",
                     "element": "ref-list" if tag == "ref-list" else "book-part"}
            if tag != "ref-list":
                entry["book_part_type"] = btype or "section"
            return entry
        self.in_front = region == "front"
        kids = self.children(el)
        self.in_front = False
        if region == "front":
            entry = {"id": self.nid(el, "front"), "type": "front-matter", "title": title,
                     "element": tag, "data_key": None}
            if kids and kids[0]["type"] == "narrative":
                lead = kids.pop(0)
                entry["data_key"] = lead["data_key"]
                self.content[lead["data_key"]]["verbatim"] = True
            else:
                entry["data_key"] = self._key(entry["id"])
                self.content[entry["data_key"]] = {"paragraphs": []}
        elif tag in ("book-app", "app"):
            entry = {"id": self.nid(el, "appendix"), "type": "appendix", "title": title,
                     "element": tag}
        else:
            entry = {"id": self.nid(el, "part"), "type": "heading-only", "title": title,
                     "element": tag}
        if btype:
            entry["book_part_type"] = btype
        if kids:
            entry["children"] = kids
        return entry


_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December")


def _front(book) -> dict:
    """The book-level facts: title, report number, date, DOI, authors,
    publisher, permissions, series, abstract."""
    from rendering.bits_bundle import whole_book_part
    from rendering.bookshelf_landing import _authors

    bm = book.find("book-meta")
    authors, affs = _authors(bm) if bm is not None else ([], [])
    aff_text = dict(affs)
    month = text_of(bm.find("pub-date/month")) if bm is not None else ""
    year = text_of(bm.find("pub-date/year")) if bm is not None else ""
    date = " ".join(x for x in (_MONTHS[int(month) - 1] if month.isdigit() and 1 <= int(month) <= 12
                                else "", year) if x)
    series = book.find("collection-meta[@collection-type='book-series']")
    collection = book.find("collection-meta[@collection-type='ncbi-books-collection']")
    abstract = bm.find("abstract") if bm is not None else None
    sections, parts = [], []
    if abstract is not None:
        for c in abstract:
            if _ln(c) == "sec":
                label = plain(c.find("title"))
                parts.append(label)
                for p in c.findall("p"):
                    sections.append({"label": label, "text": _cell(inline(p))})
            elif _ln(c) == "p":
                sections.append({"label": "", "text": _cell(inline(c))})
    doi = bm.find("book-id[@book-id-type='doi']") if bm is not None else None
    publisher = bm.find("publisher") if bm is not None else None
    return {
        "title": plain(bm.find("book-title-group/book-title")) if bm is not None else "",
        "subtitle": plain(bm.find("book-title-group/subtitle")) if bm is not None else "",
        "report_date": date, "doi": text_of(doi) if doi is not None else "",
        "authors": [{"name": a["name"],
                     "affiliation": aff_text.get(a["affs"][0], "") if a["affs"] else "",
                     **({"members": a["members"]} if a.get("members") else {})}
                    for a in authors],
        "publisher": {"name": text_of(publisher.find("publisher-name")),
                      "loc": text_of(publisher.find("publisher-loc"))}
        if publisher is not None else {},
        "permissions": text_of(bm.find("permissions/license/license-p"))
        if bm is not None and bm.find("permissions/license/license-p") is not None else "",
        "series": {"title": text_of(series.find("title-group/title")),
                   "issn": text_of(series.find("issn"))} if series is not None else {},
        "collection": {"title": text_of(collection.find("title-group/title"))}
        if collection is not None else {},
        "abstract": {"parts": parts, "sections": sections},
        "packaging": "single-file" if whole_book_part(book) is not None else "chunked",
    }


def clone_book(book, images: dict) -> dict:
    """The published book as {document, content, front, labels}: the node
    entries of its structure (a session's document.yaml list), the content
    each node binds (by data_key), its book-level facts, and the published
    label of every table and figure (kind, node id, label) to check the
    tree's numbering against."""
    from rendering.bits_bundle import book_regions

    c = _Cloner(images)
    front = _front(book)
    regions = {"front-matter": "front", "body": "body", "book-body": "body",
               "back": "back", "book-back": "back"}
    containers: dict[str, list] = {"front": [], "body": [], "back": []}
    for reg in book_regions(book):
        region = regions.get(_ln(reg))
        if region is None:
            continue
        parts = []
        for el in reg:
            if _ln(el) in ("book-app-group", "app-group"):
                parts += [a for a in el if _ln(a)]
            elif _ln(el):
                parts.append(el)
        for el in parts:
            if _ln(el) in _NO_CONTENT:
                continue
            entry = c.part(el, region)
            if entry:
                containers[region].append(entry)

    # The title page (the book's own title, document_model.cover_layouts) first,
    # the contents lists after the foreword, the abstract last — where every
    # definition puts them.
    fm = containers["front"]
    at = 1 if fm and fm[0].get("element") == "foreword" else 0
    fm[at:at] = [{"id": "toc", "type": "toc", "title": "Table of Contents"},
                 {"id": "tables-list", "type": "tables-list", "title": "Tables"}]
    fm.insert(0, {"id": "title-page", "type": "title-page", "title": "Title Page",
                  "element": "book-meta"})
    if front["abstract"]["sections"]:
        abstract = {"id": "abstract", "type": "front-matter", "title": "Abstract",
                    "data_key": "abstract", "element": "abstract"}
        if front["abstract"]["parts"]:
            abstract["parts"] = front["abstract"]["parts"]
        fm.append(abstract)
        c.content["abstract"] = {"sections": front["abstract"]["sections"]}
    document = [{"region": r, "children": containers[r]} for r in ("front", "body", "back")
                if containers[r]]
    return {"document": document, "content": c.content, "front": front, "labels": c.labels}


def apply_clone(data: dict, clone: dict) -> None:
    """Lay a companion's content over the report scaffold (``data``, in
    place): its nodes' content, and the book's title, date, authors, series
    and packaging — nothing the scaffold says about a study's data stays."""
    front = clone.get("front") or {}
    for key in ("apical_sections", "genomics_sections", "studies", "bmd_summary"):
        data.pop(key, None)
    data["apical_sections"], data["genomics_sections"] = [], []
    data.update(clone.get("content") or {})
    data["title"] = data["running_header"] = data["book_title"] = front.get("title") or ""
    data["front_matter"] = {
        "authors": front.get("authors") or [],
        "publication": {"report_number": front.get("subtitle") or "",
                        "doi": front.get("doi") or "",
                        "report_date": front.get("report_date") or ""}}
    # The cover's and the title page's report number, date and ISSN.
    for key, value in (("report_number", front.get("subtitle")),
                       ("report_date", front.get("report_date")),
                       ("issn", (front.get("series") or {}).get("issn"))):
        if value:
            data[key] = value
    data["book_meta"] = {k: v for k, v in (
        ("publisher", front.get("publisher")),
        ("permissions", {"statement": front["permissions"]} if front.get("permissions") else None),
        ("series", front.get("series")),
        ("collection", front.get("collection"))) if v}
    data["packaging"] = front.get("packaging") or "chunked"
