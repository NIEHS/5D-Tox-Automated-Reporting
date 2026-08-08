"""
jats_generator.py — TRACER BULLET: JATS/BITS XML projection of the report.

Third export surface (ADR-0004), peer to html_generator and latex_generator.
It walks the SAME DOCUMENT_TREE with the SAME data dict and reuses the shared
format-agnostic IR (render_common.front_matter_plan) so the projection stays in
lock-step with the other two surfaces.  This is deliberately a TRACER BULLET,
not the full generator: it emits a JATS journal <article> covering the prose
spine (title, structured abstract, body narrative sections) so we can prove the
end-to-end loop — emit → render offline (jats-html.xsl) → StyleCheck.  Data
tables, figures, and the genomics monolith are NOT projected yet; each unhandled
node_type emits an XML comment marker so gaps are visible, never silent.

Why journal <article> and not book <book>: per the current working assumption
the reports are treated as PMC journal articles (the self-service PMC Article
Previewer + StyleChecker path).  If they later become BITS <book-part>, the
region split (front/body/back) and the element vocabulary change, but the
tree-walk + IR reuse below do not.

The tree numbering (compute_table_numbers) is positional, so in-text references
are authored as [[xref:id]] tokens (cross_references.py) and materialize here to
BITS <xref ref-type="table" rid="..."> with the resolved positional label as its
text — the "future" branch named in cross_references.py's docstring.
"""

from __future__ import annotations

import re
from datetime import date

from lxml import etree
from lxml.builder import ElementMaker

from document_tree import (
    DOCUMENT_TREE,
    DocNode,
    NUMBERED_TABLE_TYPES,
    compute_table_numbers,
    find_node,
    walk_tree,
)
from render_common import front_matter_plan

# JATS has no default namespace in the archiving/publishing tag set (elements
# are unqualified); xlink IS namespaced.  ElementMaker with no namespace emits
# bare element names, which is what jats-html.xsl and the StyleChecker expect.
E = ElementMaker()
_XLINK = "http://www.w3.org/1999/xlink"


# ---------------------------------------------------------------------------
# In-text cross references — the BITS branch cross_references.py defers
# ---------------------------------------------------------------------------

def _resolve_xrefs_jats(text: str, parent: etree._Element) -> None:
    """Append `text` to `parent`, converting [[xref:id]] tokens to <xref>.

    Mirrors cross_references.resolve_xrefs_{latex,html} but builds real XML
    nodes (mixed content) instead of a markup string, so the token becomes a
    genuine <xref ref-type="table" rid="id">Table N</xref> with tail text — the
    BITS form the module's docstring lists as future.  Unknown / non-table
    targets fall through to a visible broken-ref marker in the text, matching
    the other surfaces' _broken() behavior.
    """
    import re
    from cross_references import _XREF_RE  # reuse the one token pattern

    pos = 0
    last_el: etree._Element | None = None

    def _emit_text(s: str) -> None:
        nonlocal last_el
        if not s:
            return
        if last_el is None:
            parent.text = (parent.text or "") + s
        else:
            last_el.tail = (last_el.tail or "") + s

    for m in _XREF_RE.finditer(text or ""):
        _emit_text(text[pos:m.start()])
        target_id = m.group(1)
        node = find_node(target_id)
        if node is not None and node.node_type in NUMBERED_TABLE_TYPES:
            num = node.table_number if node.table_number is not None else "?"
            xref = E.xref({"ref-type": "table", "rid": target_id}, f"Table {num}")
            parent.append(xref)
            last_el = xref
        else:
            _emit_text(f"[[xref:??{target_id}]]")
        pos = m.end()
    _emit_text((text or "")[pos:])


def _p(text: str) -> etree._Element:
    """A <p> whose body is `text` with xref tokens resolved to <xref> nodes."""
    p = E.p()
    _resolve_xrefs_jats(text, p)
    return p


# ---------------------------------------------------------------------------
# Front matter — journal-meta + article-meta (metadata + title + abstract)
# ---------------------------------------------------------------------------

# The report is projected as a PMC research article (current working assumption;
# see project_bits_export).  A closed StyleChecker list governs @article-type
# (stylecheck-named-tests.xsl); "research-article" is the canonical value.
_ARTICLE_TYPE = "research-article"

# Draft elocation token used until NCBI assigns the real one at publication.
# StyleChecker requires <fpage> or <elocation-id> to be PRESENT and non-empty;
# the value is not otherwise validated for a draft.
_DRAFT_ELOCATION = "e-draft"


def _build_journal_meta(data: dict) -> etree._Element:
    """Emit <journal-meta> with the children journal-meta-check requires:
    a publisher-id <journal-id>, a <journal-title> (via <journal-title-group>),
    and an <issn>.  Values come from the same data fields the cover/title-page
    surface reads (report_series, issn), so the three surfaces stay in step."""
    series = str(data.get("report_series") or "NIEHS Report Series")
    issn = str(data.get("issn") or "")
    jmeta = E("journal-meta",
        E("journal-id", {"journal-id-type": "publisher-id"}, "niehs-report"),
        E("journal-title-group", E("journal-title", series)),
    )
    if issn:
        jmeta.append(E.issn({"pub-type": "epub"}, issn))
    return jmeta


def _build_pub_date(data: dict) -> etree._Element:
    """Emit an electronic <pub-date>.  StyleChecker clears the "real publication
    date" error on the structural branch pub-date[@date-type][@publication-format],
    but TWO further checks constrain the content: empty-element-check fails on an
    empty pub-date, and date-content-check rejects a free-text <string-date>
    ("All dates must contain parsed content").  So pub-date needs a real parsed
    <year> (date-check permits a lone year; a <day> would require a <month>).  We
    use the 4-digit year in report_date when present; before a report is dated
    (the scaffold's "«Month Year»" placeholder) we fall back to the current year
    as a provisional value — NCBI stamps the authoritative date at publication."""
    pub_date = E("pub-date", {"date-type": "pub", "publication-format": "electronic"})
    m = re.search(r"\b(\d{4})\b", str(data.get("report_date") or ""))
    year = m.group(1) if m else str(date.today().year)
    pub_date.append(E.year(year))
    return pub_date


def _build_front(data: dict) -> etree._Element:
    """Emit <front> = <journal-meta> + <article-meta>.

    article-meta carries, in JATS content-model order: <article-categories>
    (a heading subj-group), <title-group>, <pub-date>, <elocation-id>, and — if
    present — a structured <abstract> (one <sec> per labeled part: Background /
    Methods / Results / Summary)."""
    title = data.get("chemical_name") or "Untitled Report"

    # Heading subject: the report series names the collection this belongs to.
    subject = str(data.get("report_series") or "Research Report")
    elocation = str(data.get("report_number") or "").strip() or _DRAFT_ELOCATION

    article_meta = E("article-meta",
        E("article-categories",
            E("subj-group", {"subj-group-type": "heading"}, E.subject(subject))),
        E("title-group", E("article-title", str(title))),
        _build_pub_date(data),
        E("elocation-id", elocation),
    )

    # Structured abstract: reuse the SAME IR the html/latex fronts consume.
    abstract_node = find_node("abstract")
    if abstract_node is not None:
        plan = front_matter_plan(abstract_node, data)
        if plan.kind == "labeled" and plan.labeled_parts:
            abstract = E.abstract()
            for label, body in plan.labeled_parts:
                if not (body or "").strip():
                    continue
                sec = E.sec()
                if label:
                    sec.append(E.title(label))
                sec.append(_p(body))
                abstract.append(sec)
            if len(abstract):
                article_meta.append(abstract)

    return E.front(_build_journal_meta(data), article_meta)


# ---------------------------------------------------------------------------
# Body — prose narrative sections (tracer scope)
# ---------------------------------------------------------------------------

_PROSE_TYPES = frozenset({"narrative", "narrative+tables", "front-matter"})


def _build_body(data: dict) -> etree._Element:
    """Walk the tree; emit a JATS <sec> for each body prose section.

    Tracer scope: only prose (narrative / narrative+tables) nodes in the body
    region are projected, plus heading-only containers (as nesting <sec>s).
    Data tables, figures, and genomics emit a visible TODO comment so the gap
    is never silent.  Front-matter prose is handled in <front>, so it is
    skipped here.
    """
    body = E.body()
    # Flat emission keyed by a shallow id→section map keeps the tracer simple;
    # a faithful nested <sec> tree is a follow-up (mirrors heading-only nesting).
    seen_gap: set[str] = set()

    def visit(node: DocNode) -> None:
        if node.region != "body":
            return
        if node.node_type in {"narrative", "narrative+tables"}:
            plan = front_matter_plan(node, data)
            sec = E.sec({"id": f"sec-{node.id}"})
            if node.title:
                sec.append(E.title(node.title))
            if plan.kind == "paragraphs":
                for para in plan.paragraphs:
                    if (para or "").strip():
                        sec.append(_p(para))
            elif plan.kind == "labeled":
                for label, btext in plan.labeled_parts:
                    if (btext or "").strip():
                        sub = E.sec(E.title(label) if label else E.title(), _p(btext))
                        sec.append(sub)
            body.append(sec)
        elif node.node_type in NUMBERED_TABLE_TYPES or node.node_type in {
            "figure", "genomics-section",
        }:
            if node.node_type not in seen_gap:
                seen_gap.add(node.node_type)
            body.append(etree.Comment(
                f" TODO tracer: node_type '{node.node_type}' not yet projected "
                f"(id={node.id}) "))

    walk_tree(DOCUMENT_TREE, visit)
    return body


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_jats(data: dict) -> str:
    """Project the report to a JATS journal <article> XML string.

    TRACER BULLET — prose spine only.  Numbering is computed first (positional,
    so xref labels resolve), then front + body are built by walking the shared
    DOCUMENT_TREE.  Returns a UTF-8 XML declaration + pretty-printed article.
    """
    compute_table_numbers()  # positional numbers → xref labels resolve
    article = E.article(
        {
            "dtd-version": "1.3",
            "article-type": _ARTICLE_TYPE,
            f"{{{_XLINK}}}dummy": "x",  # xlink ns decl carrier
        },
        _build_front(data),
        _build_body(data),
    )
    # Drop the dummy attr used only to force the xlink namespace declaration.
    del article.attrib[f"{{{_XLINK}}}dummy"]
    etree.cleanup_namespaces(article)
    return etree.tostring(
        article, xml_declaration=True, encoding="UTF-8", pretty_print=True,
    ).decode("utf-8")
