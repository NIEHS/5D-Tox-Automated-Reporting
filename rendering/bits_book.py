"""
rendering.bits_book — the report as a BITS <book>, shaped like the published one.

The reports publish on NCBI Bookshelf as BITS books (NIEHS Report 10 =
NBK589955).  This module builds the book SHELL — <collection-meta>, <book-meta>
and the parts of <front-matter> / <book-body> / <book-back> — and reuses the
block emitters of rendering.jats_generator (sections, tables, figures, freeform
prose, xrefs) for what goes inside each part.

ADR-0028: the structure is the published book's, and it is DECLARED in the
template, not decided here.  Each top-level node names its BITS `element` and
`book_part_type`; this module projects them:

  element            emitted as
  -----------------  ------------------------------------------------------------
  book-meta          the title page: <book-title> (the title page's own title
                     builder) + <subtitle> (the report number, when supplied)
  abstract           <book-meta><abstract>, one <sec> per declared part
  foreword           <foreword book-part-type=…> in <front-matter>
  front-matter-part  <front-matter-part book-part-type=…>; the authors /
                     contributors types list the session's roster
  book-part          <book-part book-part-type=…> whose <body> holds the node's
                     content directly (no repeated <sec>); a reference list's
                     part holds <back><ref-list> of numbered <ref>s instead
  book-app           <book-app book-part-type="appendix"> in <book-back>
  (none)             print-only nodes (toc, tables-list): Bookshelf builds its
                     own table of contents

The series facts (collection, series title + ISSN, publisher, permissions) come
from the template's `book_meta:` block; the study's (report number, DOI, date,
authors) from the session's front matter, and are emitted only when supplied.
Where a declared part has no content yet, a visible pending paragraph keeps the
gap in view instead of dropping the part.
"""

from __future__ import annotations

import re
from datetime import date

from lxml import etree

from document_model.document_node import DocNode
from document_model.document_tree import render_nodes
from rendering.jats_generator import E, _XLINK, _append_node, _p, _p_inline
from rendering.render_common import (
    front_matter_plan,
    inline_plain_text,
    resolve_narrative_content,
)

_BITS_DOCTYPE = (
    '<!DOCTYPE book PUBLIC '
    '"-//NLM//DTD BITS Book Interchange DTD v2.0 20151225//EN" '
    '"BITS-book2.dtd">'
)

# The region container each top-level node's part goes into.
_REGION_CONTAINER = {"front": "front-matter", "body": "book-body", "back": "book-back"}

# The roster-listing front-matter parts (book_part_type → the front-matter
# roster key and the content-type prefix the published books use on its <p>s).
_ROSTER_PARTS = {
    "authors": ("authors", "author", "author-affiliation"),
    "contributors": ("contributors", "contributor", "contrib-affiliation"),
}

_MONTHS = {m: i for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"), start=1)}


# ---------------------------------------------------------------------------
# Declarations: the series (template) and the study (front matter)
# ---------------------------------------------------------------------------

def book_meta_declaration(data: dict) -> dict:
    """The series facts: `data["book_meta"]` when the caller supplies it, else
    the active template's `book_meta:` block (ADR-0028 §6)."""
    if isinstance(data.get("book_meta"), dict):
        return data["book_meta"]
    from document_model.document_template import load_book_meta
    from document_model.document_tree import ACTIVE_TEMPLATE
    return load_book_meta(ACTIVE_TEMPLATE)


def _front_matter(data: dict) -> dict:
    fm = data.get("front_matter")
    return fm if isinstance(fm, dict) else {}


def _publication(data: dict) -> dict:
    pub = _front_matter(data).get("publication")
    return pub if isinstance(pub, dict) else {}


# ---------------------------------------------------------------------------
# <collection-meta> + <book-meta>
# ---------------------------------------------------------------------------

def _collection_meta(decl: dict) -> list:
    """The Bookshelf collection and the book series (title + ISSN), as the
    published books carry them."""
    out = []
    collection = decl.get("collection") or {}
    if collection.get("title"):
        out.append(E("collection-meta", {"collection-type": "ncbi-books-collection"},
                     E("title-group", E.title(str(collection["title"])))))
    series = decl.get("series") or {}
    if series.get("title") or series.get("issn"):
        cm = E("collection-meta", {"collection-type": "book-series"})
        if series.get("title"):
            cm.append(E("title-group", E.title(str(series["title"]))))
        if series.get("issn"):
            cm.append(E.issn({"publication-format": "electronic"}, str(series["issn"])))
        out.append(cm)
    return out


def _book_title(title_node: DocNode | None, data: dict) -> str:
    """The book title: the title page's own title (its cover layout's title
    builder), so the BITS title and the printed title page cannot differ."""
    if title_node is not None:
        from document_model.cover_layouts import get_cover_layout
        builder = get_cover_layout(title_node.subtype).title_builder
        if builder is not None:
            title = " ".join(ln.strip() for ln in builder(data) if ln and ln.strip())
            if title:
                return title
    return str(data.get("chemical_name") or data.get("title") or "Untitled Report")


def _authors(data: dict) -> list[dict]:
    return [a for a in _front_matter(data).get("authors") or []
            if isinstance(a, dict) and (a.get("name") or "").strip()]


def _name(full: str) -> etree._Element:
    """A roster name as BITS <name name-style="western">.  The roster holds one
    name string ("Scott S. Auerbach, Ph.D."); the StyleChecker requires the
    parsed form, so the part before any comma (degrees, titles) is split at its
    last space: surname = the last word, given-names = the rest."""
    words = full.split(",", 1)[0].split()
    name = E.name({"name-style": "western"}, E.surname(words[-1] if words else full.strip()))
    if len(words) > 1:
        name.append(E("given-names", " ".join(words[:-1])))
    return name


def _contrib_group(data: dict) -> list:
    """<contrib-group content-type="authors"> + one <aff> per distinct
    affiliation, from the author roster (nothing when no roster is supplied)."""
    authors = _authors(data)
    if not authors:
        return []
    affs: list[str] = []
    for a in authors:
        aff = (a.get("affiliation") or "").strip()
        if aff and aff not in affs:
            affs.append(aff)
    cg = E("contrib-group", {"content-type": "authors"})
    for a in authors:
        contrib = E.contrib({"contrib-type": "author"}, _name(a["name"]))
        aff = (a.get("affiliation") or "").strip()
        if aff:
            n = affs.index(aff) + 1
            contrib.append(E.xref({"ref-type": "aff", "rid": f"aff-{n}"}, E.sup(str(n))))
        cg.append(contrib)
    return [cg] + [E.aff({"id": f"aff-{n}"}, E.label(str(n)), aff)
                   for n, aff in enumerate(affs, start=1)]


def _pub_date(data: dict) -> etree._Element:
    """<pub-date> from the publication date the front matter (or data) states:
    month + year when it names a month.  StyleChecker needs a parsed <year>;
    before the report is dated the current year stands in as provisional —
    NCBI stamps the authoritative date at publication."""
    raw = str(_publication(data).get("report_date") or data.get("report_date") or "")
    pub_date = E("pub-date", {"date-type": "pub", "publication-format": "electronic"})
    month = next((n for name, n in _MONTHS.items() if name in raw.lower()), None)
    if month:
        pub_date.append(E.month(f"{month:02d}"))
    m = re.search(r"\b(\d{4})\b", raw)
    pub_date.append(E.year(m.group(1) if m else str(date.today().year)))
    return pub_date


def _abstract(node: DocNode, data: dict) -> etree._Element:
    """<abstract> with one <sec> per DECLARED part (node.parts) in order — the
    published Background / Methods / Results / Summary.  A part with no text
    yet gets a visible pending paragraph; a labeled part the data holds but the
    template does not declare is kept, after the declared ones."""
    plan = front_matter_plan(node, data)
    texts: dict[str, list[str]] = {}
    current = ""
    for label, body in (plan.labeled_parts if plan.kind == "labeled" else []):
        current = label or current
        if (body or "").strip():
            texts.setdefault(current, []).append(body)
    declared = list(node.parts or [])
    order = declared + [lbl for lbl in texts if lbl not in declared]
    abstract = E.abstract({"id": "abstract1"}, E.title(node.title or "Abstract"))
    n = 0
    for i, label in enumerate(order, start=1):
        sec = E.sec({"id": f"Sabs{i}"})
        if label:
            sec.append(E.title(label))
        bodies = texts.get(label) or []
        if not bodies:
            bodies = [f"[Abstract {label or 'text'} pending: not yet generated for this study.]"]
        for body in bodies:
            n += 1
            para = _p(body)
            para.set("id", f"Pabs{n}")
            sec.append(para)
        abstract.append(sec)
    return abstract


def _build_book_meta(data: dict, nodes: list[DocNode], decl: dict) -> etree._Element:
    """<book-meta>, in the BITS content-model order: book-id, the title group,
    authors + affiliations, pub-date, publisher, permissions, abstract."""
    pub = _publication(data)
    bm = E("book-meta")
    if (pub.get("doi") or "").strip():
        bm.append(E("book-id", {"book-id-type": "doi"}, pub["doi"].strip()))
    title_node = next((n for n in nodes if n.element == "book-meta"), None)
    btg = E("book-title-group", E("book-title", _book_title(title_node, data)))
    if (pub.get("report_number") or "").strip():
        btg.append(E.subtitle(pub["report_number"].strip()))
    bm.append(btg)
    for el in _contrib_group(data):
        bm.append(el)
    bm.append(_pub_date(data))
    publisher = decl.get("publisher") or {}
    name = str(publisher.get("name") or data.get("publisher") or "")
    if name:
        pub_el = E.publisher(E("publisher-name", name))
        if publisher.get("loc"):
            pub_el.append(E("publisher-loc", str(publisher["loc"])))
        bm.append(pub_el)
    permissions = decl.get("permissions") or {}
    if permissions.get("statement"):
        lic = E.license(E("license-p", str(permissions["statement"])))
        if permissions.get("license_href"):
            lic.set(f"{{{_XLINK}}}href", str(permissions["license_href"]))
        bm.append(E.permissions(lic))
    abstract_node = next((n for n in nodes if n.element == "abstract"), None)
    if abstract_node is not None:
        bm.append(_abstract(abstract_node, data))
    return bm


# ---------------------------------------------------------------------------
# Parts
# ---------------------------------------------------------------------------

def _part_meta(node: DocNode, label: str | None = None) -> etree._Element:
    title_group = E("title-group")
    if label:
        title_group.append(E.label(label))
    title_group.append(E.title(node.title or ""))
    return E("book-part-meta", title_group)


def _part_attrs(node: DocNode, prefix: str) -> dict:
    attrs = {"id": f"{prefix}-{node.id}"}
    if node.book_part_type:
        attrs["book-part-type"] = node.book_part_type
    return attrs


def _pending(node: DocNode, why: str = "content pending") -> etree._Element:
    return E.p(f"[{node.title}: {why}.]")


def _prose_blocks(node: DocNode, data: dict) -> list:
    """The prose of a front-matter node as <p>s (a labeled node's parts as
    titled <sec>s), via the shared narrative resolver."""
    rc = resolve_narrative_content(node, data)
    out: list = []
    if rc.kind in ("paragraphs", "methods"):
        for para in rc.paragraphs:
            if inline_plain_text(para).strip():
                out.append(_p_inline(para))
    elif rc.kind == "labeled":
        for label, btext in rc.labeled_parts:
            if (btext or "").strip():
                out.append(E.sec(E.title(label) if label else E.title(), _p(btext)))
    return out


def _roster_blocks(node: DocNode, data: dict) -> list:
    """An authors / contributors part, as the published books list it: one
    <list list-type="simple"> item per affiliation (the affiliation in bold,
    then one line per person).  Only what the roster states — name and role."""
    roster_key, person_type, aff_type = _ROSTER_PARTS[node.book_part_type]
    roster = [p for p in _front_matter(data).get(roster_key) or []
              if isinstance(p, dict) and (p.get("name") or "").strip()]
    if not roster:
        return []
    groups: dict[str, list[dict]] = {}
    for person in roster:
        groups.setdefault((person.get("affiliation") or "").strip(), []).append(person)
    lst = E("list", {"list-type": "simple", "list-content": "contributors"})
    for aff, people in groups.items():
        item = E("list-item")
        if aff:
            item.append(E.p({"content-type": aff_type}, E.bold(aff)))
        for person in people:
            line = ", ".join(x for x in ((person.get("name") or "").strip(),
                                         (person.get("role") or "").strip()) if x)
            item.append(E.p({"content-type": person_type}, line))
        lst.append(item)
    return [lst]


def _front_part(node: DocNode, data: dict) -> etree._Element:
    """<foreword> / <front-matter-part>: title in <book-part-meta>, content in
    <named-book-part-body>."""
    blocks: list = []
    if node.book_part_type in _ROSTER_PARTS:
        blocks = _roster_blocks(node, data)
        if not blocks:
            blocks = _prose_blocks(node, data) or [
                _pending(node, "not supplied for this study")]
    else:
        blocks = _prose_blocks(node, data) or [_pending(node)]
    return E(node.element, _part_attrs(node, "fm"), _part_meta(node),
             E("named-book-part-body", *blocks))


_REF_NUMBER_RE = re.compile(r"^\s*\[(\d+)\]\s*")


def _ref_list(node: DocNode, data: dict) -> etree._Element:
    """<ref-list> of numbered <ref>s, one per reference paragraph.  The citation
    keeps its text (<mixed-citation>); its "[n]" in-text number becomes the
    <label>.  No references yet → a pending paragraph inside the list."""
    rc = resolve_narrative_content(node, data)
    if rc.kind in ("paragraphs", "methods"):
        texts = [inline_plain_text(p) for p in rc.paragraphs]
    elif rc.kind == "labeled":
        texts = [btext for _label, btext in rc.labeled_parts]
    else:
        texts = []
    rl = E("ref-list", {"id": "ref-list1"})
    for i, text in enumerate((t.strip() for t in texts if t and t.strip()), start=1):
        m = _REF_NUMBER_RE.match(text)
        label = m.group(1) if m else str(i)
        citation = text[m.end():] if m else text
        rl.append(E.ref({"id": f"ref{i}"}, E.label(label), E("mixed-citation", citation)))
    if not len(rl):
        rl.append(_pending(node, "no references yet"))
    return rl


def _part_body(node: DocNode, data: dict) -> etree._Element:
    """A body part's <body>: the node's own content, directly.  The node is
    rendered through the shared block emitters and its own <sec> is unwrapped —
    the part's <title-group> is its heading, so the body never repeats it."""
    scratch = E.body()
    _append_node(scratch, node, data)
    body = E.body()
    for el in list(scratch):
        if el.tag == "sec" and el.get("id") == f"sec-{node.id}":
            for child in list(el):
                if child.tag not in ("label", "title"):
                    body.append(child)
        else:
            body.append(el)
    if not any(isinstance(c.tag, str) for c in body):
        body.append(E.p(f"[Section pending: {node.title}]"))
    return body


def _book_part(node: DocNode, data: dict) -> etree._Element:
    """<book-part>: the References list as <back><ref-list>, any other part as
    <body>."""
    meta = _part_meta(node)
    if node.role == "ref-list":
        return E("book-part", _part_attrs(node, "bp"), meta, E.back(_ref_list(node, data)))
    return E("book-part", _part_attrs(node, "bp"), meta, _part_body(node, data))


def _part(node: DocNode, data: dict) -> list:
    """The part(s) a top-level node contributes to its region container."""
    element = node.element
    if element in ("foreword", "front-matter-part"):
        return [_front_part(node, data)]
    if element == "book-part":
        return [_book_part(node, data)]
    if element == "book-app":
        holder = E.x()
        _append_node(holder, node, data)   # the shared appendix emitter (+ any
        return list(holder)                # protection marker comment before it)
    return []   # book-meta / abstract (in <book-meta>) and print-only nodes


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_book(data: dict) -> etree._Element:
    """The BITS <book> element for a report (see the module docstring)."""
    nodes = render_nodes(data)                      # this study's tree, numbered
    decl = book_meta_declaration(data)
    # Declare the xlink prefix on the root so <ext-link xlink:href> serializes
    # with the literal "xlink" prefix the BITS/JATS DTD fixes (an auto-assigned
    # ns0 prefix is rejected: "No declaration for attribute href").
    book = etree.Element("book", {"dtd-version": "2.0"}, nsmap={"xlink": _XLINK})
    for cm in _collection_meta(decl):
        book.append(cm)
    book.append(_build_book_meta(data, nodes, decl))
    containers: dict[str, etree._Element] = {}
    for node in nodes:
        parts = _part(node, data)
        if not parts:
            continue
        region = _REGION_CONTAINER.get(node.region or "body", "book-body")
        if region not in containers:
            containers[region] = E(region)
        # The published books float the body's tables and figures (Bookshelf
        # shows a card that opens the object) and anchor the appendices' in the
        # text (shown in full).
        position = "anchor" if node.element == "book-app" else "float"
        for part in parts:
            for obj in part.iter("table-wrap", "fig"):
                if obj.get("position") is None:
                    obj.set("position", position)
            containers[region].append(part)
    for region in ("front-matter", "book-body", "book-back"):
        if region in containers:
            book.append(containers[region])
    return book


def generate_bits(data: dict) -> str:
    """Project the report to a BITS <book> XML string (the Bookshelf submission
    form): XML declaration + BITS 2.0 DOCTYPE + the book."""
    return etree.tostring(
        build_book(data), xml_declaration=True, encoding="UTF-8", pretty_print=True,
        doctype=_BITS_DOCTYPE,
    ).decode("utf-8")
