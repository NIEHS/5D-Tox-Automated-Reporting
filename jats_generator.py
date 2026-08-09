"""
jats_generator.py — JATS/BITS XML projection of the report.

Third export surface (ADR-0004), peer to html_generator and latex_generator.
It walks the SAME DOCUMENT_TREE with the SAME data dict and reuses the shared
format-agnostic EXTRACT plans (render_common) so the projection stays in
lock-step with the other three surfaces — it is a new EMIT over the same
decisions, never a re-derivation.

Coverage: metadata (journal-meta / article-meta), the narrative spine (title,
structured abstract, and every body narrative section via the shared
resolve_narrative_content dispatch), and DATA TABLES — apical / incidence /
sample-counts / bmd-summary plus the genomics gene-set & gene GRIDS — projected
to BITS <table-wrap>.  Still deferred (each emits a visible <!-- TODO --> comment
so a gap is never silent): figures / genomics CHARTS (BITS <fig>/<graphic> +
image packaging is a distinct phase) and the genomics section narrative.

Why journal <article> and not book <book>: per the current working assumption
the reports are treated as PMC journal articles (the self-service PMC Article
Previewer + StyleChecker path).  If they later become BITS <book-part>, the
region split (front/body/back) and the element vocabulary change, but the
tree-walk + plan reuse below do not.

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
from render_common import (
    front_matter_plan,
    resolve_narrative_content,
    apical_table_plan,
    incidence_table_plan,
    sample_counts_table,
    bmd_summary_plan,
    BMD_SUMMARY_HEADERS,
    genomics_entries,
    genomics_role,
    genomics_table_caption,
    gene_set_table_rows,
    gene_table_rows,
    GENE_SET_TABLE_HEADERS,
    GENE_TABLE_HEADERS,
)

# JATS has no default namespace in the archiving/publishing tag set (elements
# are unqualified); xlink IS namespaced.  ElementMaker with no namespace emits
# bare element names, which is what jats-html.xsl and the StyleChecker expect.
E = ElementMaker()
_XLINK = "http://www.w3.org/1999/xlink"

# JATS 1.3 Journal Archiving and Interchange DOCTYPE. PMC/Bookshelf ingest (and
# the Article Previewer) reject XML with "no DOCTYPE Declaration or other schema
# reference"; the StyleChecker's id()-based tests also assume a DTD-validated
# parse. FPI + system id are the verbatim values from the DTD itself
# (jats.nlm.nih.gov/archiving/1.3/JATS-archivearticle1-3.dtd, Z39.96-2021).
_JATS_DOCTYPE = (
    '<!DOCTYPE article PUBLIC '
    '"-//NLM//DTD JATS (Z39.96) Journal Archiving and Interchange DTD '
    'v1.3 20210610//EN" '
    '"JATS-archivearticle1-3.dtd">'
)


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
            # rid MUST equal the <table-wrap> @id the emitter assigns (T-<id>),
            # or the cross-reference dangles — both go through table_wrap_id().
            xref = E.xref(
                {"ref-type": "table", "rid": table_wrap_id(target_id)},
                f"Table {num}",
            )
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
# Data tables — BITS/JATS <table-wrap> projection of the shared grid plans
# ---------------------------------------------------------------------------
# Every data table (apical, incidence, sample-counts, bmd-summary, and the
# genomics gene-set/gene grids) reduces to the SAME shape — caption + header row
# + body rows, with an occasional "**Sex**" full-width separator row — so one
# low-level builder serves them all.  The per-node handlers below only assemble
# (headers, rows, footnotes) from the shared render_common EXTRACT plans and hand
# them here; this is the JATS EMIT peer of html_generator's table handlers.
#
# StyleChecker contract (verified empirically against v5.48 for the `article`
# stream): <table>/<table-wrap> must be non-empty; footnotes must live under
# <table-wrap-foot>; a table-wrap @id "must begin with T" (book/manuscript stream
# only — silent for article, but we honor it as cheap future-proofing).

# The T-prefix a table-wrap id carries.  Kept in ONE place so the xref resolver
# (which must target the SAME id) and the emitter can't drift.
_TABLE_ID_PREFIX = "T-"


def table_wrap_id(node_id: str) -> str:
    """The <table-wrap> @id for a node id — T-prefixed per the StyleChecker id
    rule.  The single source both the emitter and the xref resolver use, so a
    cross-reference's rid always matches the table it points at."""
    return f"{_TABLE_ID_PREFIX}{node_id}"


def _split_label(caption: str) -> tuple[str, str]:
    """Split a "Table N. <descriptive>" caption into (label, descriptive).

    BITS models the number as a separate <label> from the <caption><p> text, so
    a positional "Table 8. Foo" becomes <label>Table 8</label> + <p>Foo</p>.
    When the caption carries no leading "Table N" locator, label is "" and the
    whole string is the descriptive text."""
    m = re.match(r"\s*(Table\s+[^.]+?)\.\s*(.*)", caption or "", re.S)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "", (caption or "").strip()


def _table_wrap(
    node_id: str,
    caption: str,
    headers: list[str],
    rows: list[list[str]],
    footnotes: list | None = None,
) -> etree._Element:
    """Build one <table-wrap> from a grid (caption + header row + body rows).

    Row convention (shared by the apical / sample-counts / genomics plans): a row
    whose first cell is wrapped in ``**…**`` is a SEX SEPARATOR — emitted as a
    single full-width <td> spanning every column (the BITS analogue of the html
    ``sex-separator`` <tr>), with the ``**`` stripped.  All other cells are plain
    text (lxml escapes them); table cells are data, not narrative, so xref tokens
    are NOT resolved inside them.

    Footnotes (the typed dicts table_builder_common emits: ``{text, [letter]}``)
    go under <table-wrap-foot> as <fn><p> — omitted entirely when there are none,
    since an empty <table-wrap-foot> fails the StyleChecker empty-element check."""
    ncols = max([len(headers)] + [len(r) for r in rows], default=1)
    tw = E("table-wrap", {"id": table_wrap_id(node_id)})

    label, descriptive = _split_label(caption)
    if label:
        tw.append(E.label(label))
    if descriptive:
        tw.append(E.caption(E.p(descriptive)))

    table = E.table()
    if headers:
        thead = E.thead(E.tr(*[E.th(str(h)) for h in headers]))
        table.append(thead)
    tbody = E.tbody()
    for row in rows:
        cells = [str(c) for c in row]
        first = cells[0] if cells else ""
        if first.startswith("**") and first.endswith("**"):
            label_text = first.strip("*").strip()
            tbody.append(E.tr(E.td({"colspan": str(ncols)}, label_text)))
        else:
            tbody.append(E.tr(*[E.td(c) for c in cells]))
    table.append(tbody)
    tw.append(table)

    foots = [f for f in (footnotes or []) if (f.get("text") if isinstance(f, dict) else f)]
    if foots:
        foot = E("table-wrap-foot")
        for f in foots:
            text = f.get("text", "") if isinstance(f, dict) else str(f)
            foot.append(E.fn(E.p(str(text))))
        tw.append(foot)
    return tw


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
# Body — per-node-type data-table handlers (BITS <table-wrap> EMIT)
# ---------------------------------------------------------------------------
# Each returns a list of block elements (a <table-wrap>, maybe preceded by prose
# <p>s, or a TODO <!-- comment --> when the plan is empty) that _build_body drops
# straight into <body>.  The (headers, rows, footnotes) come from the shared
# render_common EXTRACT plans — no data logic here, only JATS markup.

def _dose_label(dose, unit: str) -> str:
    """Plain dose-column label ("0 mg/kg").  Mirrors html/latex _format_dose_label
    without the non-breaking-space / escaping presentation each of those adds."""
    if dose == 0 or dose == 0.0:
        return f"0 {unit}"
    if isinstance(dose, float) and dose.is_integer():
        return f"{int(dose)} {unit}"
    return f"{dose} {unit}"


def _todo(node: DocNode, why: str = "not yet projected") -> etree._Element:
    """A visible gap marker — never a silent drop."""
    return etree.Comment(f" TODO tracer: {why} (id={node.id}, type={node.node_type}) ")


def _emit_apical_table(node: DocNode, data: dict) -> list:
    """Apical dose-response `table` → one <table-wrap>.  Headers = first-column +
    one per dose + BMD/BMDL; sex blocks become **Sex** separator rows."""
    plan = apical_table_plan(node, data)
    if plan is None:
        return [_todo(node, "apical table data pending")]
    headers = (
        [plan.first_col]
        + [_dose_label(d, plan.dose_unit) for d in plan.doses]
        + [f"BMD1Std ({plan.dose_unit})", f"BMDL1Std ({plan.dose_unit})"]
    )
    rows: list[list[str]] = []
    for block in plan.sex_blocks:
        rows.append([f"**{block.sex_label}**"])
        for r in block.rows:
            rows.append(r.cells)
    return [_table_wrap(node.id, plan.caption, headers, rows, plan.footnotes)]


def _emit_incidence_table(node: DocNode, data: dict) -> list:
    """Clinical-observations `incidence-table` → one <table-wrap>."""
    plan = incidence_table_plan(node, data)
    if plan is None:
        return [_todo(node, "incidence table data pending")]
    headers = ["Observation"] + [_dose_label(d, plan.dose_unit) for d in plan.doses]
    return [_table_wrap(node.id, plan.caption, headers, plan.rows, plan.footnotes)]


def _emit_sample_counts_table(node: DocNode, data: dict) -> list:
    """Methods `sample-counts-table` (Final Sample Counts matrix) → <table-wrap>."""
    built = sample_counts_table(node, data)
    if built is None:
        return [_todo(node, "sample-counts data pending")]
    return [_table_wrap(
        node.id, built.get("caption", node.title or ""),
        [str(h) for h in built.get("headers", [])],
        built.get("rows", []) or [],
        built.get("footnotes", []) or [],
    )]


def _emit_bmd_summary(node: DocNode, data: dict) -> list:
    """`bmd-summary` → its summary prose <p>s, then the endpoint <table-wrap>.

    Unlike the pure tables this node ALSO carries prose (it is not narrative-
    family, so the resolver refactor didn't touch it) — emit those paragraphs
    first so the summary sentences aren't dropped, then the table when present."""
    plan = bmd_summary_plan(node, data)
    out: list = []
    for para in plan.paragraphs:
        if isinstance(para, str) and para.strip():
            out.append(_p(para))
    if plan.rows is not None:
        out.append(_table_wrap(
            node.id, plan.caption, list(BMD_SUMMARY_HEADERS), plan.rows,
        ))
    elif not out:
        out.append(_todo(node, "bmd-summary endpoints + prose pending"))
    return out


def _emit_genomics_tables(node: DocNode, data: dict) -> list:
    """Partial `genomics-section`: emit the gene-set / gene GRID tables as
    <table-wrap>s (one per organ entry); charts + narrative stay TODO markers
    (deferred to the figures phase — see project_bits_export).

    Genomics tables are not tree nodes, so their number/caption come from the
    entry (genomics_table_caption); the <table-wrap> id is derived per entry
    (Tgs-/Tg-<organ>) rather than from a node id."""
    role = genomics_role(node)
    entries = genomics_entries(node, data)
    out: list = []
    if not entries:
        return [_todo(node, "genomics data pending")]
    for entry in entries:
        rows = gene_set_table_rows(entry) if role == "gene_set" else gene_table_rows(entry)
        headers = GENE_SET_TABLE_HEADERS if role == "gene_set" else GENE_TABLE_HEADERS
        organ = (entry.get("organ") or "organ").strip().lower().replace(" ", "-")
        wrap_id = f"{'gs' if role == 'gene_set' else 'g'}-{organ}"
        if rows:
            out.append(_table_wrap(
                wrap_id, genomics_table_caption(entry), list(headers), rows,
            ))
    # Charts + section narrative are deferred — mark the gap explicitly.
    out.append(_todo(node, "genomics charts + narrative deferred to figures phase"))
    return out


# ---------------------------------------------------------------------------
# Body — prose narrative sections + data tables
# ---------------------------------------------------------------------------

_PROSE_TYPES = frozenset({"narrative", "narrative+tables", "front-matter"})

# node_type → its data-table EMIT handler (returns a list of body blocks).
_TABLE_EMITTERS = {
    "table": _emit_apical_table,
    "incidence-table": _emit_incidence_table,
    "sample-counts-table": _emit_sample_counts_table,
    "bmd-summary": _emit_bmd_summary,
    "genomics-section": _emit_genomics_tables,
}


def _build_body(data: dict) -> etree._Element:
    """Walk the tree; emit body content for each node in document order.

    Narrative nodes (narrative / narrative+tables) become <sec> blocks via the
    shared resolve_narrative_content dispatch; data-table nodes project to
    <table-wrap> via _TABLE_EMITTERS.  Figures and the genomics chart/narrative
    parts emit a visible TODO comment so a gap is never silent.  Front-matter
    prose is handled in <front>, so it is skipped here.

    Emission is flat (document order); a faithful nested <sec> tree mirroring the
    heading-only containers is a follow-up.
    """
    body = E.body()

    def visit(node: DocNode) -> None:
        if node.region != "body":
            return
        if node.node_type in {"narrative", "narrative+tables"}:
            # ONE shared dispatch (render_common.resolve_narrative_content) picks
            # the content source — the same call html/latex/docx make — so JATS no
            # longer sees only the front_matter_plan shape and silently drops the
            # Methods (methods_key) + Results (unified_narratives) prose.
            rc = resolve_narrative_content(node, data)
            sec = E.sec({"id": f"sec-{node.id}"})
            if node.title:
                sec.append(E.title(node.title))
            if rc.kind in ("paragraphs", "methods"):
                for para in rc.paragraphs:
                    if isinstance(para, str) and not para.strip():
                        continue
                    sec.append(_p(para if isinstance(para, str) else str(para)))
                # DECIDED: the methods inline table (Final Sample Counts) is
                # deferred to the data-tables phase — carry a visible marker here
                # instead of a <table-wrap>, so the gap stays explicit.
                if rc.kind == "methods" and rc.inline_table is not None:
                    sec.append(etree.Comment(
                        f" TODO tracer: inline methods table for '{node.id}' "
                        f"deferred to data-tables phase "))
            elif rc.kind == "labeled":
                for label, btext in rc.labeled_parts:
                    if (btext or "").strip():
                        sub = E.sec(E.title(label) if label else E.title(), _p(btext))
                        sec.append(sub)
            body.append(sec)
        elif node.node_type in _TABLE_EMITTERS:
            # Data tables (apical / incidence / sample-counts / bmd-summary /
            # genomics grids) project to <table-wrap> via the shared plans.
            for block in _TABLE_EMITTERS[node.node_type](node, data):
                body.append(block)
        elif node.node_type == "figure":
            # Figures (BITS <fig>/<graphic>) are the next phase — image packaging
            # is a distinct concern; keep the gap explicit.
            body.append(_todo(node, "figure not yet projected"))

    walk_tree(DOCUMENT_TREE, visit)
    return body


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_jats(data: dict) -> str:
    """Project the report to a JATS journal <article> XML string.

    TRACER BULLET — prose spine only.  Numbering is computed first (positional,
    so xref labels resolve), then front + body are built by walking the shared
    DOCUMENT_TREE.  Returns a UTF-8 XML declaration + JATS 1.3 DOCTYPE +
    pretty-printed article.
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
        doctype=_JATS_DOCTYPE,
    ).decode("utf-8")
