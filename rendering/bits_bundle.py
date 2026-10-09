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
    split_book(xml) -> {filename: bytes}  a <book> as a chunked bundle (TOC.nxml
                                           + one book-part-wrapper per part)
    bundle_zip(xml, images) -> bytes      that bundle zipped, with the figure files
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

import base64
import copy
import io
import re
import zipfile
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
# Writing: one <book> → chunked bundle
# ---------------------------------------------------------------------------

_BITS_SYSTEM_ID = "BITS-book2.dtd"
_BITS_PUBLIC_ID = "-//NLM//DTD BITS Book Interchange DTD v2.0 20151225//EN"
_FROM_WHERE = {"front-matter": "front-matter", "book-body": "body", "book-back": "back"}


def _serialize(root: etree._Element) -> bytes:
    return etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", pretty_print=True,
        doctype=f'<!DOCTYPE {root.tag} PUBLIC "{_BITS_PUBLIC_ID}" "{_BITS_SYSTEM_ID}">',
    )


def _book_parts(book) -> list[tuple[str, etree._Element]]:
    """(from-where, part) for every part of the book, in reading order."""
    out = []
    for region, where in _FROM_WHERE.items():
        reg = book.find(region)
        if reg is None:
            continue
        for c in reg:
            if not isinstance(c.tag, str):
                continue
            if c.tag in ("book-app-group", "app-group"):
                out.extend((where, a) for a in c if isinstance(a.tag, str))
            elif c.tag in _PART_TAGS:
                out.append((where, c))
    return out


def _part_title(part) -> tuple[str, str]:
    tg = part.find("book-part-meta/title-group")
    if tg is None:
        tg = part
    return _text(tg.find("label")), _text(tg.find("title"))


def _toc_entry(doc_id: str, doc_type: str, label: str, title: str,
               object_id: str | None = None) -> etree._Element:
    entry = etree.Element("toc-entry", {"id": f"toc_{object_id or doc_id}"})
    if label:
        etree.SubElement(entry, "label").text = label
    etree.SubElement(entry, "title").text = title
    nav = etree.SubElement(entry, "nav-pointer", {"nav-pointer-type": "point"})
    attrs = {"link-type": "booklink", "document-id": doc_id, "document-type": doc_type}
    if object_id:
        attrs.update({"object-id": object_id, "object-type": "section"})
    etree.SubElement(nav, "related-object", attrs)
    return entry


def split_book(xml) -> dict[str, bytes]:
    """A BITS <book> as the chunked bundle Bookshelf holds (ADR-0028 §7):

      TOC.nxml        <book-part-wrapper id="toc" content-type="toc"> with the
                      collection-meta, the full book-meta (with the abstract) and
                      a <toc>: one entry per part in reading order, the body
                      parts' top-level sections nested under theirs;
      <part-id>.nxml  one <book-part-wrapper> per part — collection-meta, the
                      book-meta without the abstract, then the part, whose
                      <book-part-meta> leads with its <book-part-id>.

    The part's own @id becomes the wrapper's id and the file name (our ids; NCBI
    assigns its own at ingest)."""
    book = xml if isinstance(xml, etree._Element) else parse_book(xml)
    collection = book.findall("collection-meta")
    book_meta = book.find("book-meta")
    lean_meta = copy.deepcopy(book_meta) if book_meta is not None else None
    if lean_meta is not None:
        for ab in lean_meta.findall("abstract"):
            lean_meta.remove(ab)

    def wrapper(attrs: dict, meta) -> etree._Element:
        w = etree.Element("book-part-wrapper", {**attrs, "dtd-version": "2.0"},
                          nsmap=book.nsmap)
        for cm in collection:
            w.append(copy.deepcopy(cm))
        if meta is not None:
            w.append(copy.deepcopy(meta))
        return w

    files: dict[str, bytes] = {}
    toc = etree.Element("toc")
    for n, (where, part) in enumerate(_book_parts(book), start=1):
        part = copy.deepcopy(part)
        doc_id = part.attrib.pop("id", None) or f"part{n}"
        doc_type = part.get("book-part-type") or "section"
        meta = part.find("book-part-meta")
        if meta is None:
            meta = etree.Element("book-part-meta")
            part.insert(0, meta)
        part_id = etree.Element("book-part-id", {"book-part-id-type": "publisher-id"})
        part_id.text = doc_id
        meta.insert(0, part_id)
        content_type = "appendix" if part.tag == "book-app" else "section"
        w = wrapper({"id": doc_id, "content-type": content_type, "from-where": where},
                    lean_meta)
        w.append(part)
        files[f"{doc_id}.nxml"] = _serialize(w)

        label, title = _part_title(part)
        entry = _toc_entry(doc_id, doc_type, label, title)
        if part.tag == "book-part":
            for sec in part.findall("body/sec"):
                if sec.get("id"):
                    entry.append(_toc_entry(doc_id, doc_type, _text(sec.find("label")),
                                            _text(sec.find("title")), sec.get("id")))
        toc.append(entry)

    toc_wrapper = wrapper({"id": "toc", "content-type": "toc"}, book_meta)
    if len(toc):
        toc_wrapper.append(toc)
    files = {"TOC.nxml": _serialize(toc_wrapper), **files}
    return files


def bundle_zip(xml, images: dict[str, str] | None = None) -> bytes:
    """The chunked bundle of a BITS <book>, zipped: TOC.nxml, one file per part,
    and the figure files its <graphic>s name (`images`: filename → base64 PNG,
    as rendering.bookshelf_preview.chart_images builds it)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in split_book(xml).items():
            zf.writestr(name, content)
        for name, b64 in (images or {}).items():
            raw = b64.split(",", 1)[1] if b64.startswith("data:") else b64
            zf.writestr(name, base64.b64decode(raw))
    return buf.getvalue()


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
    if part.tag in ("ack", "sec", "app"):
        bodies = [part]
    return entry, bodies


def book_regions(book) -> list:
    """The book's front-matter, body and back, in order.  A chunked bundle or our
    <book> holds them as front-matter / book-body / book-back; a single-file book
    (RR-8, NIEHS-02 … 06) holds the whole book in one <book-part> whose
    front-matter, body (one top-level <sec> per chapter) and back (ref-list,
    <app>s) they are."""
    regions = [book.find(r) for r in ("front-matter", "book-body", "book-back")]
    if any(r is not None for r in regions):
        return [r for r in regions if r is not None]
    for bp in book.findall("book-part"):
        inner = [bp.find(r) for r in ("front-matter", "body", "back")]
        if any(r is not None for r in inner):
            return [r for r in inner if r is not None]
    return []


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
    for reg in book_regions(book):
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
            if part.tag not in _PART_TAGS and part.tag not in ("sec", "app"):
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
