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

from latex_export import load_session_data
from html_generator import generate_html
from latex_generator import generate_latex
from document_tree import DOCUMENT_TREE, find_node
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
_HTML_TABLE_NUM = re.compile(r"<caption>\s*Table (\d+)\.")
_LATEX_TABLE_NUM = re.compile(r"\\begin\{niehstable\}\{[^}]*\}\{\s*Table (\d+)\.")

# HTML "<figcaption>Figure 3. ..." and LaTeX "{\small\itshape Figure 3. ...}".
_HTML_FIGURE_NUM = re.compile(r"<figcaption>\s*Figure (\d+)\.")
_LATEX_FIGURE_NUM = re.compile(r"\\itshape\s+Figure (\d+)\.")


def _nums(pattern: re.Pattern, text: str) -> set[int]:
    """Set of integers a numbering pattern captures in a rendered surface."""
    return {int(m) for m in pattern.findall(text)}


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

    # Tree oracle: every node the walker assigned a table_number to renders a
    # caption (real table or "[data pending]" placeholder both carry it).
    expected: set[int] = set()

    def _collect(nodes):
        for n in nodes:
            if getattr(n, "table_number", None) is not None:
                expected.add(n.table_number)
            _collect(n.children)

    _collect(DOCUMENT_TREE)

    assert html_nums == latex_nums, (
        f"table-number drift between surfaces: HTML-only={html_nums - latex_nums}, "
        f"LaTeX-only={latex_nums - html_nums}"
    )
    assert html_nums == expected, (
        f"rendered table numbers {html_nums} != tree-assigned {expected}"
    )


def test_figure_numbers_agree_across_surfaces(session_data):
    """
    The set of numbered figures rendered in HTML equals the set in LaTeX.

    Figures live in the genomics charts; the session has them, so this is a
    real (non-vacuous) check — guarded by the non-empty assertion below.
    """
    html = generate_html(session_data)
    tex = generate_latex(session_data)

    html_figs = _nums(_HTML_FIGURE_NUM, html)
    latex_figs = _nums(_LATEX_FIGURE_NUM, tex)

    assert html_figs, "expected at least one numbered figure in the HTML render"
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
