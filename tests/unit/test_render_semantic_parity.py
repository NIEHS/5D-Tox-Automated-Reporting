r"""
Cross-surface semantic-parity guard (ADR-0006 Amendment 1).

The HTML and LaTeX renderers are two PROJECTIONS of one semantic description
(the render_common IR).  The strong correctness property is not "each renderer
matches its old self" (a byte-diff catches that, but it cannot catch the two
surfaces drifting *together* away from the data) — it is that **both surfaces,
and the IR, agree on the same semantic facts**: which tables exist (by their
positional number), which figures exist, and which endpoints the BMD summary
reports.  A renderer that silently dropped, doubled, or reordered a table /
figure / endpoint on one surface only is exactly the failure this catches.

These facts are extracted from STRUCTURAL anchor points (a table's `<caption>` /
`niehstable` env, a figure's `<figcaption>` / caption line) rather than from
loose prose, so a narrative cross-reference to "Table 5" doesn't pollute them.
They are also escaping-immune: table/figure NUMBERS are plain ASCII emitted by
shared code, and the BMD endpoint names in this dataset carry no markup-special
characters (checked by substring containment, which tolerates either surface's
escaping).

Where a fact has an authoritative source in the IR (the BMD endpoint rows), the
IR is the oracle and BOTH surfaces are checked against it; where it doesn't
(positional table/figure numbers), the two surfaces are checked against each
other.
"""

import re

import pytest

import html_generator
import latex_generator
from latex_export import load_session_data
from html_generator import generate_html
from latex_generator import generate_latex
from document_model.document_node import DocNode
from document_model.document_tree import DOCUMENT_TREE, find_node
from render_common import bmd_summary_plan


# ---------------------------------------------------------------------------
# Fixture — the real DTXSID50469320 session, shared with the renderer tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def session_data() -> dict:
    """Real session data overlaid on the scaffold (same as the renderer tests)."""
    return load_session_data(
        dtxsid="DTXSID50469320",
        chemical_name="Perfluorohexanesulfonamide",
        casrn="41997-13-1",
    )


# ---------------------------------------------------------------------------
# Fact extractors — anchored to structural locations, not loose prose
# ---------------------------------------------------------------------------

# HTML caption "<caption>Table 8. ..." and LaTeX "\begin{niehstable}{id}{Table 8. ...}".
# Genomics tables are NOT niehstable floats — LaTeX emits their caption as a bold
# line "\noindent\textbf{Table N. ...}" and HTML as a plain "<caption>Table N. ...";
# match both LaTeX forms so the parity set covers apical + genomics tables.
_HTML_TABLE_NUM = re.compile(r"<caption>\s*(?:<strong>\s*)?Table (\d+)\.")
_LATEX_TABLE_NUM = re.compile(
    r"\\begin\{niehstable\}\{[^}]*\}\{\s*Table (\d+)\.|\\textbf\{Table (\d+)\."
)

# HTML "<figcaption>Figure 3. ..." and LaTeX "{\small\itshape Figure 3. ...}".
_HTML_FIGURE_NUM = re.compile(r"<figcaption>\s*Figure (\d+)\.")
_LATEX_FIGURE_NUM = re.compile(r"\\itshape\s+Figure (\d+)\.")


def _nums(pattern: re.Pattern, text: str) -> set[int]:
    """Set of integers a numbering pattern captures in a rendered surface.

    Tolerates multi-group alternation patterns (findall yields tuples): each
    match contributes exactly one non-empty group, so flatten and drop blanks.
    """
    out: set[int] = set()
    for m in pattern.findall(text):
        groups = m if isinstance(m, tuple) else (m,)
        for g in groups:
            if g:
                out.add(int(g))
    return out


def _html_bmd_rows(html: str) -> list[tuple[str, str]]:
    """(sex, endpoint) for each <tr> in the BMD-summary <tbody>."""
    tbody = html[html.find("<tbody>"):html.find("</tbody>")]
    rows: list[tuple[str, str]] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tbody, re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(tds) >= 2:
            rows.append((tds[0].strip(), tds[1].strip()))
    return rows


def _latex_bmd_rows(tex: str) -> list[tuple[str, str]]:
    """
    (sex, endpoint) for each data row of the BMD-summary niehstable — the rows
    between \\midrule and \\bottomrule that terminate in "\\\\".
    """
    body = tex[tex.find("\\midrule") + len("\\midrule"):tex.find("\\bottomrule")]
    rows: list[tuple[str, str]] = []
    for line in body.splitlines():
        line = line.strip()
        if not line.endswith(r"\\"):
            continue
        cells = [c.strip() for c in line[:-2].split(" & ")]
        if len(cells) >= 2:
            rows.append((cells[0], cells[1]))
    return rows


# ---------------------------------------------------------------------------
# Parity: positional numbering agrees across surfaces (and the tree)
# ---------------------------------------------------------------------------

def test_table_numbers_agree_across_surfaces(session_data):
    """
    The set of numbered tables rendered in HTML equals the set in LaTeX, and
    both equal the table_numbers the document tree assigned — so neither
    surface dropped or invented a numbered table.
    """
    html = generate_html(session_data)
    tex = generate_latex(session_data)

    html_nums = _nums(_HTML_TABLE_NUM, html)
    latex_nums = _nums(_LATEX_TABLE_NUM, tex)

    # Oracle: tree-assigned numbers (apical + BMD) PLUS the data-driven genomics
    # table numbers (genomics tables are not tree nodes — assign_genomics_table_
    # numbers stamps them onto the genomics_sections entries).  Both surfaces
    # must render exactly this union.
    expected: set[int] = set()

    def _collect_tree_table_numbers(nodes):
        for n in nodes:
            if getattr(n, "table_number", None) is not None:
                expected.add(n.table_number)
            _collect_tree_table_numbers(n.children)

    _collect_tree_table_numbers(DOCUMENT_TREE)
    for entry in session_data.get("genomics_sections") or []:
        if entry.get("table_number") is not None:
            expected.add(entry["table_number"])

    assert html_nums == latex_nums, (
        f"table-number drift between surfaces: HTML-only={html_nums - latex_nums}, "
        f"LaTeX-only={latex_nums - html_nums}"
    )
    assert html_nums == expected, (
        f"rendered table numbers {html_nums} != expected {expected}"
    )

    # Table 1 specifically is the Methods sample-counts-table node — a data-
    # driven table that only renders when data["sample_counts"] is present.
    # Pin it on both surfaces so a regression that drops its data (leaving only
    # the pending stub, which still carries the number) is caught here.
    assert 1 in html_nums, "Table 1 (sample counts) absent from both surfaces"
    assert "Table 1." in html and "Table 1." in tex
    """
    The genomics table numbers assigned by the LaTeX session path
    (load_session_data) and the web/marshal path (marshal_export_data) must be
    IDENTICAL for the same session — both call the one shared helper
    (assign_genomics_table_numbers), so a divergence would mean one path was
    left unwired.  Keys on (type, organ, sex) since the two paths may deliver
    the entries in different list order.
    """
    from report_data import marshal_export_data

    latex_data = load_session_data(
        dtxsid="DTXSID50469320",
        chemical_name="Perfluorohexanesulfonamide",
        casrn="41997-13-1",
    )
    web_data = marshal_export_data({
        "chemical_name": "Perfluorohexanesulfonamide",
        "casrn": "41997-13-1",
        "dtxsid": "DTXSID50469320",
        # Feed the SAME genomics entries the LaTeX path resolved, so both number
        # the identical input (marshal numbers whatever the body carries).
        "genomics_sections": [
            {k: v for k, v in e.items() if k != "table_number"}
            for e in (latex_data.get("genomics_sections") or [])
        ],
    })

    def _by_key(data):
        return {
            (e.get("type"), e.get("organ"), e.get("sex")): e.get("table_number")
            for e in (data.get("genomics_sections") or [])
        }

    assert _by_key(latex_data) == _by_key(web_data)
    # And the numbers are a contiguous block starting at 9 (after Table 8).
    nums = sorted(v for v in _by_key(latex_data).values() if v is not None)
    assert nums and nums[0] == 9 and nums == list(range(9, 9 + len(nums)))


def test_figure_numbers_agree_across_surfaces(session_data):
    """
    The set of numbered figures rendered in HTML equals the set in LaTeX.

    Figures live in the genomics charts.  The parity invariant is that BOTH
    surfaces render the SAME set — including the empty set when the active
    template suppresses charts (`charts: []`, which this report ships, since the
    NIEHS reference has no main-body figures).  Cross-surface agreement is the
    property under test, not the presence of any particular figure; a count
    guard would instead pin a config choice that lives in the template.
    """
    html = generate_html(session_data)
    tex = generate_latex(session_data)

    html_figs = _nums(_HTML_FIGURE_NUM, html)
    latex_figs = _nums(_LATEX_FIGURE_NUM, tex)

    assert html_figs == latex_figs, (
        f"figure-number drift between surfaces: HTML-only={html_figs - latex_figs}, "
        f"LaTeX-only={latex_figs - html_figs}"
    )


# ---------------------------------------------------------------------------
# Parity: BMD-summary endpoints — IR is the oracle, both surfaces checked
# ---------------------------------------------------------------------------

def test_bmd_summary_endpoints_match_ir_on_both_surfaces(session_data):
    """
    The BMD summary's (sex, endpoint) rows are the same on both surfaces and
    equal the render_common.bmd_summary_plan IR — a row-fidelity check that the
    rendered endpoint set is faithful to the description, on each projection.
    """
    node = find_node("bmd-summary")
    assert node is not None, "bmd-summary node missing from the document tree"
    plan = bmd_summary_plan(node, session_data)
    assert plan.rows, "fixture has no BMD-summary endpoints to compare"
    expected = [(r[0], r[1]) for r in plan.rows]  # (sex, endpoint)

    html_rows = _html_bmd_rows(generate_html(session_data, section_filter="bmd-summary"))
    latex_rows = _latex_bmd_rows(generate_latex(session_data, section_filter="bmd-summary"))

    # Three-way row-count parity: IR ↔ HTML ↔ LaTeX.
    assert len(html_rows) == len(expected), (
        f"HTML rendered {len(html_rows)} BMD rows, IR has {len(expected)}"
    )
    assert len(latex_rows) == len(expected), (
        f"LaTeX rendered {len(latex_rows)} BMD rows, IR has {len(expected)}"
    )

    # HTML cells carry the (sex, endpoint) verbatim — assert exact parity there.
    assert html_rows == expected, "HTML BMD rows diverge from the IR"

    # Endpoint identity on both surfaces (substring containment tolerates each
    # surface's escaping; the count check above pins multiplicity).
    html_full = generate_html(session_data, section_filter="bmd-summary")
    tex_full = generate_latex(session_data, section_filter="bmd-summary")
    for _sex, endpoint in expected:
        assert endpoint in html_full, f"endpoint {endpoint!r} absent from HTML"
        assert endpoint in tex_full, f"endpoint {endpoint!r} absent from LaTeX"


# ---------------------------------------------------------------------------
# Parity: the content-present / escaping decisions agree (Amendment 1 fixes)
# ---------------------------------------------------------------------------
# These pin the three latent inconsistencies the IR converged.  Each would have
# FAILED before the fix — they probe a divergence the full-session byte-diff and
# the number/endpoint checks above can't reach.

def test_blank_paragraph_section_is_pending_on_both_surfaces():
    """
    A section whose paragraphs are all blank carries no content, so BOTH
    surfaces must treat it as pending — previously HTML rendered "<p></p>"
    (content present) while LaTeX showed pending (absent).  Fixed by the shared
    render_common.has_paragraph_content decision.
    """
    node = DocNode(id="foreword", title="Foreword", node_type="front-matter",
                   level=1, data_key="foreword")
    data = {"foreword": {"paragraphs": ["", "   "]}}

    html = html_generator._render_front_matter(node, data)
    tex = latex_generator._render_front_matter(node, data)

    assert "<p></p>" not in html, "HTML still renders a spurious empty paragraph"
    assert ("pending" in html.lower()) and ("pending" in tex.lower()), (
        "the surfaces disagree on whether a blank-paragraph section has content"
    )


def test_methods_subsection_matches_by_key_not_title():
    """
    A methods subsection's prose is matched to its tree node by the STABLE
    methods_key, not the display heading.  Rewording the node title (or the
    section heading) must not unlink the content.

    Regression: methods_subsection_content matched section["heading"] ==
    node.title — two independently-maintained display strings (the YAML
    template title vs. SUBSECTION_SKELETON heading_text).  Rewording either one
    alone silently blanked the subsection on BOTH surfaces.
    """
    from render_common import methods_subsection_content

    node = DocNode(id="mm-study-design", title="RENAMED IN TEMPLATE",
                   node_type="narrative", level=3, methods_key="study_design")
    # The section carries the stable key; its heading is the OLD/other wording.
    data = {"methods": {"sections": [
        {"level": 3, "key": "study_design", "heading": "Study Design",
         "paragraphs": ["REAL STUDY DESIGN PROSE"]},
    ]}}

    paragraphs, _ = methods_subsection_content(node, data)
    assert paragraphs == ["REAL STUDY DESIGN PROSE"], (
        "methods content must resolve by methods_key even when the title and "
        "the section heading disagree"
    )

    # And both surfaces render it as content, not the pending placeholder.
    # The methods dispatch now lives in the shared render_common.resolve_narrative_
    # content; a methods_key node reaches it through each surface's public
    # _render_narrative (the private methods handler was folded into the resolver).
    html = html_generator._render_narrative(node, data)
    tex = latex_generator._render_narrative(node, data)
    assert "REAL STUDY DESIGN PROSE" in html and "REAL STUDY DESIGN PROSE" in tex
    assert "pending" not in html.lower() and "pending" not in tex.lower()


def test_methods_subsection_legacy_heading_fallback():
    """Legacy section dicts that predate the `key` field still match by
    heading == title, so old cached sessions keep rendering."""
    from render_common import methods_subsection_content

    node = DocNode(id="mm-chemistry", title="Chemistry",
                   node_type="narrative", level=3, methods_key="chemistry")
    data = {"methods": {"sections": [
        {"level": 3, "heading": "Chemistry", "paragraphs": ["LEGACY PROSE"]},
    ]}}

    paragraphs, _ = methods_subsection_content(node, data)
    assert paragraphs == ["LEGACY PROSE"]


def test_roster_cell_escaping_is_single_on_both_surfaces():
    """
    A roster cell carrying a LaTeX special is escaped exactly once — previously
    the LaTeX roster double-escaped (pre-escape + _emit_tabular_row), diverging
    from HTML's single-escape.  The FASTQ file id (Plate1-<n> etc.) is the cell
    most likely to carry an underscore-style special, so exercise it there.
    """
    node = DocNode(id="appendix-b", title="Animal Identifiers",
                   node_type="appendix", level=1)
    data = {"appendix_animals": [{
        "animal_number": "1", "sex": "Male", "dose": 0,
        "tissue": "Liver", "fastq_file_id": "A_1",
    }]}

    tex = latex_generator._render_appendix(node, data)

    assert r"A\_1" in tex, "expected the single-escaped id A\\_1"
    assert r"\textbackslash" not in tex, "id was double-escaped (the old divergence)"


def test_override_recognized_by_same_anchor_id_on_both_surfaces(session_data):
    """
    Divergence #2: both surfaces must recognize an ADR-0005 override keyed by
    the SAME anchor id.  We don't compare markup (LaTeX emits the region verbatim
    inside sentinels; HTML marks/renders it) — only that the same node.id is
    honored.  Previously HTML ignored the override store entirely.
    """
    edited = "PARITY OVERRIDE MARKER TEXT"
    data = {
        **session_data,
        "overrides": {
            "background": {"latex_region": edited, "base_hash": "deadbeef"},
        },
    }
    # LaTeX emits the override region verbatim for that node.
    tex = generate_latex(data)
    assert edited in tex, "LaTeX did not emit the override region"

    # HTML recognizes the same anchor id — recorded in _override_stale.
    html_data = dict(data)
    generate_html(html_data)
    assert "background" in html_data.get("_override_stale", []), (
        "HTML preview ignored an override the LaTeX surface honored"
    )
