"""rendering.bits_bundle — a BITS book as Bookshelf holds it: whole or chunked.

NCBI Bookshelf keeps a NIEHS report (NIEHS-07 onward) as a CHUNKED bundle: a
``TOC.nxml`` (a ``<book-part-wrapper id="toc">`` carrying the collection-meta,
the book-meta with the abstract, and a ``<toc>`` giving the reading order) plus
one ``<book-part-wrapper>`` file per part (foreword, front-matter parts, body
book-parts, book-apps).  We generate one ``<book>`` (jats_generator.generate_bits)
and treat it as the internal form; this module moves between the two shapes and
reduces either to a structural OUTLINE that can be compared part for part.

Public API:
    read_bundle(path) -> <book> element   a chunked bundle dir, a TOC.nxml, or a
                                           single BITS file, as one <book> tree
    parse_book(xml) -> element            the same for a document held in memory
    outline(book) -> [OutlineEntry]       the structure, in document order
    structure_keys(entries) -> [str]      the comparable form of an outline

What the outline records is STRUCTURE: the part sequence (element, book-part-type,
label, title), the section tree under each part (label, title), and where each
table / figure / media object sits (by its label).  It deliberately leaves out
what NCBI's converter assigns at ingest — element ids (S1, t-2-01, bp1),
``sec-type="otherN"``, ``disp-level``, pmcid book ids, prev/next part links — and
content (caption wording, paragraph text, reference counts).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

from lxml import etree

_PARSER = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False,
                          remove_comments=True)

# The part elements a book's regions hold (BITS 2.0 front-matter / book-body /
# book-back content).
_PART_TAGS = ("foreword", "preface", "dedication", "front-matter-part", "ack",
              "book-part", "book-app", "glossary", "notes")
# Where a chunked part file says it came from (book-part-wrapper @from-where) →
# the <book> region element that holds it.
_REGION_OF = {"front-matter": "front-matter", "body": "book-body", "back": "book-back"}
# Objects whose placement (not wording) is structure.
_OBJECT_TAGS = ("table-wrap", "fig", "media", "supplementary-material", "disp-formula")


def _ws(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").replace(" ", " ")).strip()


def _text(el) -> str:
    return _ws("".join(el.itertext())) if el is not None else ""


def _parse_file(path: Path) -> etree._Element:
    return etree.parse(str(path), _PARSER).getroot()


# ---------------------------------------------------------------------------
# Reading: chunked bundle → one <book>
# ---------------------------------------------------------------------------

def _toc_document_ids(toc) -> list[str]:
    """The part document-ids in reading order: the top-level toc-entries'
    nav-pointer targets (nested entries point INTO a part, at a section)."""
    ids: list[str] = []
    for entry in toc.findall("toc-entry"):
        ro = entry.find("nav-pointer/related-object")
        doc_id = ro.get("document-id") if ro is not None else None
        if doc_id and doc_id not in ids:
            ids.append(doc_id)
    return ids


def _assemble(toc_root, bundle_dir: Path) -> etree._Element:
    """A chunked bundle (TOC.nxml + one file per part) as one <book>."""
    book = etree.Element("book", nsmap=toc_root.nsmap)
    for cm in toc_root.findall("collection-meta"):
        book.append(cm)
    bm = toc_root.find("book-meta")
    if bm is not None:
        book.append(bm)
    regions: dict[str, etree._Element] = {}
    for doc_id in _toc_document_ids(toc_root.find("toc")):
        path = bundle_dir / f"{doc_id}.nxml"
        if not path.exists():
            continue
        wrapper = _parse_file(path)
        part = next((c for c in wrapper if isinstance(c.tag, str) and c.tag in _PART_TAGS), None)
        if part is None:
            continue
        region = _REGION_OF.get(wrapper.get("from-where", ""), "book-body")
        if region not in regions:
            regions[region] = etree.Element(region)
        regions[region].append(part)
    for region in ("front-matter", "book-body", "book-back"):
        if region in regions:
            book.append(regions[region])
    return book


def parse_book(xml) -> etree._Element:
    """A BITS document held in memory (str or bytes), parsed without its DTD."""
    return etree.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml, _PARSER)


def read_bundle(path) -> etree._Element:
    """One <book> tree from a chunked bundle directory, its TOC.nxml, or a single
    BITS file (a <book>, or a <book-part-wrapper> that holds the whole book)."""
    path = Path(path)
    toc_path = path / "TOC.nxml" if path.is_dir() else path
    root = _parse_file(toc_path)
    if root.tag == "book-part-wrapper" and root.find("toc") is not None:
        return _assemble(root, toc_path.parent)
    return root


# ---------------------------------------------------------------------------
# Outline
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OutlineEntry:
    depth: int
    kind: str          # element name (book-title, foreword, book-part, sec, table-wrap, …)
    part_type: str     # @book-part-type of a part, else ""
    label: str
    title: str         # heading text; caption title for an object (content, not compared)

    def to_dict(self) -> dict:
        return asdict(self)


def _caption_title(obj) -> str:
    cap = obj.find("caption")
    if cap is None:
        return ""
    t = cap.find("title")
    if t is None:
        t = cap.find("p")
    return _text(t)


def _walk_blocks(container, depth: int, out: list[OutlineEntry]) -> None:
    for el in container:
        if not isinstance(el.tag, str):
            continue
        tag = el.tag
        if tag in ("sec", "app"):
            out.append(OutlineEntry(depth, tag, "", _text(el.find("label")),
                                    _text(el.find("title"))))
            _walk_blocks(el, depth + 1, out)
        elif tag in _OBJECT_TAGS:
            out.append(OutlineEntry(depth, tag, "", _text(el.find("label")),
                                    _caption_title(el)))
        elif tag == "ref-list":
            out.append(OutlineEntry(depth, tag, "", "", _text(el.find("title"))))
        elif tag in ("back", "fig-group", "boxed-text", "app-group"):
            _walk_blocks(el, depth, out)


def _part_entry(part) -> tuple[OutlineEntry, list]:
    tg = part.find("book-part-meta/title-group")
    if tg is None:
        tg = part
    entry = OutlineEntry(0, part.tag, part.get("book-part-type", ""),
                         _text(tg.find("label")), _text(tg.find("title")))
    bodies = [c for c in part if isinstance(c.tag, str)
              and c.tag in ("body", "named-book-part-body", "back")]
    if part.tag == "ack":
        bodies = [part]
    return entry, bodies


def outline(book) -> list[OutlineEntry]:
    """The structure of a BITS book (see the module docstring for what counts)."""
    out: list[OutlineEntry] = []
    bm = book.find("book-meta")
    if bm is not None:
        btg = bm.find("book-title-group")
        if btg is not None:
            out.append(OutlineEntry(0, "book-title", "", "", _text(btg.find("book-title"))))
            for sub in btg.findall("subtitle"):
                out.append(OutlineEntry(0, "subtitle", "", "", _text(sub)))
        for cg in bm.findall("contrib-group"):
            out.append(OutlineEntry(0, "contrib-group", cg.get("content-type", ""), "",
                                    f"{len(cg.findall('contrib'))} contrib"))
        ab = bm.find("abstract")
        if ab is not None:
            out.append(OutlineEntry(0, "abstract", "", "", _text(ab.find("title"))))
            for sec in ab.findall("sec"):
                out.append(OutlineEntry(1, "sec", "", _text(sec.find("label")),
                                        _text(sec.find("title"))))
    for region in ("front-matter", "book-body", "book-back"):
        reg = book.find(region)
        if reg is None:
            continue
        parts = []
        for c in reg:
            if not isinstance(c.tag, str):
                continue
            if c.tag in ("book-app-group", "app-group"):
                parts.extend(x for x in c if isinstance(x.tag, str))
            else:
                parts.append(c)
        for part in parts:
            if part.tag == "ref-list":
                out.append(OutlineEntry(0, "ref-list", "", "", _text(part.find("title"))))
                continue
            if part.tag not in _PART_TAGS:
                continue
            entry, bodies = _part_entry(part)
            out.append(entry)
            for body in bodies:
                _walk_blocks(body, 1, out)
    return out


# Kinds whose `title` is heading text (structure); for objects and the
# contributor count it is content, so it stays out of the comparable key.
_TITLED_KINDS = frozenset({"book-title", "subtitle", "abstract", "sec", "app", "ref-list",
                           *_PART_TAGS})


def structure_keys(entries: list[OutlineEntry]) -> list[str]:
    """One comparable line per outline entry: indent + kind + [part type] +
    label + heading title.  Object captions and counts are left out."""
    lines = []
    for e in entries:
        bits = [e.kind]
        if e.part_type:
            bits.append(f"[{e.part_type}]")
        if e.label:
            bits.append(f"<{e.label}>")
        if e.kind in _TITLED_KINDS and e.title:
            bits.append(e.title)
        lines.append("  " * e.depth + " ".join(bits))
    return lines
