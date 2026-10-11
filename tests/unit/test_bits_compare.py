"""
The published book and ours, compared for reading (rendering.bits_compare):
sections align by heading path and blocks by content; a change is marked word
by word and cell by cell; a difference of typography alone is told apart; a
section, table or row the books order differently is still paired; and the
conventional unified diff, applied to the published book's flat text, gives
ours exactly.
"""

import copy
import re

import pytest
from lxml import etree

from rendering.bits_bundle import parse_book
from rendering.bits_compare import compare, flat_lines, sections, unified_diff, word_ops
from rendering.bits_compare_tables import align_rows, column_map
from rendering.bits_compare_page import render_page
from tooling.bits_structure import BOOKSHELF


def _book(body: str, title: str = "A Report") -> etree._Element:
    return parse_book(f"""<book><book-meta><book-title-group><book-title>{title}</book-title>
      </book-title-group></book-meta><book-body>{body}</book-body></book>""")


def _part(title: str, inner: str) -> str:
    return (f'<book-part book-part-type="chapter"><book-part-meta><title-group><title>{title}'
            f'</title></title-group></book-part-meta><body>{inner}</body></book-part>')


TABLE = """<table-wrap id="t1"><label>Table 1</label><caption><title>Sample Counts</title></caption>
<table><thead><tr><th/><th>0 mg/kg</th><th>1 mg/kg</th></tr></thead><tbody>
{rows}</tbody></table><table-wrap-foot><fn><label>a</label><p>A note.</p></fn></table-wrap-foot>
</table-wrap>"""
MALE = '<tr><td colspan="3">Male</td></tr><tr><td>Liver</td><td>10</td><td>5</td></tr>'
FEMALE = '<tr><td colspan="3">Female</td></tr><tr><td>Liver</td><td>10</td><td>{n}</td></tr>'


def _apply(text_lines: list[str], diff: str) -> list[str]:
    """Apply a unified diff to a list of lines (the hunks in order)."""
    out, pos = [], 0
    lines = diff.splitlines()[2:]
    k = 0
    while k < len(lines):
        m = re.match(r"@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@", lines[k])
        assert m, lines[k]
        start = int(m.group(1)) - (0 if m.group(2) == "0" else 1)
        out += text_lines[pos:start]
        pos = start
        k += 1
        while k < len(lines) and not lines[k].startswith("@@"):
            tag, body = lines[k][:1], lines[k][1:]
            if tag in (" ", "-"):
                assert text_lines[pos] == body
                pos += 1
            if tag in (" ", "+"):
                out.append(body)
            k += 1
    return out + text_lines[pos:]


def _roundtrip(cmp) -> None:
    left = flat_lines(cmp.left_order)[0]
    right = flat_lines(cmp.right_order)[0]
    assert _apply(left, unified_diff(cmp, "a", "b")) == right


def test_the_same_book_is_the_same():
    book = _book(_part("Results", "<p>Body weights fell.</p>" + TABLE.format(rows=MALE)))
    cmp = compare(book, copy.deepcopy(book))
    assert cmp.sim == 1.0
    assert set(cmp.counts()) == {"same"}
    assert unified_diff(cmp, "a", "b") == ""


def test_a_changed_word_and_a_changed_number_are_marked():
    a = _book(_part("Results", "<p>The BMD was 8.5 mg/kg in male rats.</p>"))
    b = _book(_part("Results", "<p>The BMD was 8.7 mg/kg in female rats.</p>"))
    cmp = compare(a, b)
    (bp,) = cmp.sections[1].blocks
    assert bp.status == "changed"
    changes = [(x, y) for op, x, y in word_ops(bp.left.text, bp.right.text) if op != "equal"]
    assert changes == [("8.5", "8.7"), ("male", "female")]   # a number is one token
    _roundtrip(cmp)


def test_typography_alone_is_its_own_kind_of_difference():
    a = _book(_part("Methods", "<p>Doses “high” – 1,000 mg/kg.</p>"))
    b = _book(_part("Methods", '<p>Doses "high" - 1,000 mg/kg.</p>'))
    (bp,) = compare(a, b).sections[1].blocks
    assert bp.status == "typo"


def test_a_superscript_does_not_fuse_with_its_word():
    a = _book(_part("Results", "<p>Weight<sup>a</sup> fell.</p>"))
    b = _book(_part("Results", "<p>Weight fell.</p>"))
    (bp,) = compare(a, b).sections[1].blocks
    ops = [op for op, x, y in word_ops(bp.left.text, bp.right.text) if op != "equal"]
    assert ops == ["delete"]


def test_sections_align_by_heading_and_a_reordered_one_is_paired_as_moved():
    a = _book(_part("Background", "<p>One.</p>") + _part("Methods", "<p>Two.</p>")
              + _part("Results", "<p>Three.</p>"))
    b = _book(_part("Background", "<p>One.</p>") + _part("Results", "<p>Three.</p>")
              + _part("Methods", "<p>Two, changed.</p>"))
    cmp = compare(a, b)
    titles = [(sp.left and sp.left.title, sp.right and sp.right.title) for sp in cmp.sections[1:]]
    assert titles == [("Background", "Background"), ("Methods", "Methods"), ("Results", "Results")]
    assert sum(1 for sp in cmp.sections if sp.moved) == 1
    _roundtrip(cmp)


def test_a_section_only_one_book_has_stands_alone():
    a = _book(_part("Background", "<p>One.</p>") + _part("Discussion", "<p>Talk.</p>"))
    b = _book(_part("Background", "<p>One.</p>"))
    cmp = compare(a, b)
    assert cmp.sections[-1].status == "published-only"
    _roundtrip(cmp)


def test_table_rows_pair_within_their_group_whatever_the_order():
    a = _book(_part("Results", TABLE.format(rows=MALE + FEMALE.format(n=4))))
    b = _book(_part("Results", TABLE.format(rows=FEMALE.format(n=5) + MALE)))
    (bp,) = compare(a, b).sections[1].blocks
    grid_a, grid_b = bp.left.grid, bp.right.grid
    assert grid_a[1] == ["Male", "", ""]                 # a column span stands once
    # published: head, Male, Liver 5, Female, Liver 4; ours: head, Female, Liver 5, Male, Liver 5
    rows = {i: (j, moved) for i, j, moved in align_rows(bp.left, bp.right) if i is not None}
    assert rows[4][0] == 2 and grid_b[2] == ["Liver", "10", "5"]   # Female's faces Female's
    assert rows[2][0] == 4                                         # Male's faces Male's
    assert any(moved for _, moved in rows.values())
    _roundtrip(compare(a, b))


def _table(head: str, body: str) -> str:
    return (f'<table-wrap><label>Table 8</label><caption><title>Summary</title></caption><table>'
            f'<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></table-wrap>')


def _tr(*cells: str) -> str:
    return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"


def test_tables_laid_out_differently_still_compare_cell_for_cell():
    """The 2023 book groups rows under Male / Female heading rows, ours has a
    Sex column; the book's endpoint is "Total T4 (μg/dL)", ours "Total
    Thyroxine"; its BMD column is BMD<sub>1Std</sub> (mg/kg), ours BMD."""
    pub = _table("<th>Endpoint</th><th>BMD<sub>1Std</sub> (mg/kg)</th><th>LOEL (mg/kg)<sup>a</sup></th>"
                 "<th>NOEL</th><th>Direction of Change</th>",
                 '<tr><td colspan="5">Male</td></tr>'
                 + _tr("Total T4 (μg/dL)", "7.264", "12", "4", "DOWN")
                 + _tr("Terminal Body Wt. (g)", "16.2", "12", "4", "UP")
                 + '<tr><td colspan="5">Female</td></tr>'
                 + _tr("Total T4 (μg/dL)", "0.417", "37", "12", "DOWN"))
    ours = _table("<th>Sex</th><th>Endpoint</th><th>BMD</th><th>LOEL (mg/kg)</th><th>NOEL</th>"
                  "<th>Direction</th>",
                  _tr("Female", "Total Thyroxine", "14.8", "37", "12", "DOWN")
                  + _tr("Male", "Total Thyroxine", "8.5", "12", "4", "DOWN")
                  + _tr("Male", "Terminal Body Weight (g)", "16.2", "12", "4", "UP"))
    (bp,) = compare(_book(_part("Results", pub)), _book(_part("Results", ours))).sections[1].blocks
    cols = column_map(bp.left, bp.right)
    assert cols == [(None, 0), (0, 1), (1, 2), (2, 3), (3, 4), (4, 5)]   # Sex has no counterpart
    rows = {i: j for i, j, _ in align_rows(bp.left, bp.right, cols) if i is not None}
    assert rows[2] == 2      # Male T4 (BMD 7.264) faces our Male Thyroxine (8.5), not Female's
    assert rows[3] == 3      # Wt. / Weight
    assert rows[5] == 1      # Female T4 faces our Female Thyroxine
    assert rows[1] is None and rows[4] is None   # the heading rows have no counterpart


def test_a_row_label_never_abbreviates_into_another_row():
    pub = _table("<th/><th>4 mg/kg</th>", _tr("n", "3") + _tr("2 Hours Postdose (ng/mL)", "33.8"))
    ours = _table("<th>Timepoint</th><th>4 mg/kg</th>", _tr("n", "3") + _tr("2 h postdose", "33.8"))
    (bp,) = compare(_book(_part("Results", pub)), _book(_part("Results", ours))).sections[1].blocks
    assert [(i, j) for i, j, _ in align_rows(bp.left, bp.right)] == [(0, 0), (1, 1), (2, 2)]


def test_a_table_in_another_section_is_paired_where_published_and_ours_keeps_a_stub():
    a = _book(_part("Results", TABLE.format(rows=MALE)) + _part("Summary", "<p>End.</p>"))
    b = _book(_part("Results", "<p>See below.</p>") + _part("Summary", "<p>End.</p>"
                                                            + TABLE.format(rows=MALE)))
    cmp = compare(a, b)
    results, summary = cmp.sections[1], cmp.sections[2]
    table = next(bp for bp in results.blocks if bp.kind == "table")
    assert table.left and table.right and table.status == "same"
    assert "Summary" in table.moved
    stub = next(bp for bp in summary.blocks if bp.status == "moved-stub")
    assert stub.twin is table
    _roundtrip(cmp)


def test_the_page_holds_both_views_and_the_outline():
    a = _book(_part("Results", "<p>The BMD was 8.5 mg/kg.</p>" + TABLE.format(rows=MALE)))
    b = _book(_part("Results", "<p>The BMD was 8.7 mg/kg.</p>" + TABLE.format(rows=MALE)))
    page = render_page(compare(a, b), title="T", left_label="Published", right_label="Ours")
    assert '<div class="v-sbs">' in page and '<div class="v-uni">' in page
    assert "<del>8.5</del>" in page and "<ins>8.7</ins>" in page
    assert 'class="outline"' in page and 'href="#s1"' in page


@pytest.mark.skipif(not (BOOKSHELF / "NIEHS-10" / "TOC.nxml").exists(),
                    reason="published Bookshelf bundles not downloaded")
def test_real_books_align_and_their_diff_applies():
    from rendering.bits_compare import load_book
    n10, images = load_book(BOOKSHELF / "NIEHS-10")
    assert images                                     # the figures come with the book
    same = compare(n10, copy.deepcopy(n10))
    assert same.sim == 1.0 and set(same.counts()) == {"same"}
    n09, _ = load_book(BOOKSHELF / "NIEHS-09")      # same era, another chemical
    cmp = compare(n10, n09)
    heads = [sp for sp in cmp.sections if sp.left is not None and sp.right is not None]
    assert len(heads) >= 0.9 * len(sections(n10))     # the outline corresponds
    _roundtrip(cmp)


def test_compare_routes_name_only_published_studies(client, sessions_dir):
    (sessions_dir / "DTXSID7000001").mkdir()
    assert client.get("/Compare").status_code == 200
    assert client.get("/Compare/DTXSID7000001").status_code == 404
    assert client.get("/Compare/DTXSID7000001/diff").status_code == 404
    assert client.get("/Compare/DTXSID7000001/published.txt").status_code == 404
