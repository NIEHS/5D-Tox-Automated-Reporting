"""
ADR-0028: the template declares the BITS part each top-level node becomes,
flow content precedes sub-sections, and appendix section labels are computed.
"""

import pytest

from document_model.document_template import instantiate, load_book_meta
from document_model.document_tree import compute_table_numbers
from rendering.render_common import section_heading_text


def _sec(id_, title, **kw):
    return {"id": id_, "type": "heading-only", "title": title, **kw}


def test_parts_default_their_element_and_type_by_region():
    tree = instantiate([
        {"region": "front", "children": [
            {"id": "tp", "type": "title-page", "title": "Title Page"},
            {"id": "toc", "type": "toc", "title": "Contents"},
            {"id": "pr", "type": "front-matter", "title": "Peer Review", "data_key": "peer_review"},
        ]},
        {"region": "body", "children": [_sec("m", "Methods")]},
        {"region": "back", "children": [{"id": "a", "type": "appendix", "title": "A"}]},
    ])
    got = {n.id: (n.element, n.book_part_type) for n in tree}
    assert got == {
        "tp": ("book-meta", None),
        "toc": (None, None),                      # print-only: no BITS element
        "pr": ("front-matter-part", "section"),
        "m": ("book-part", "section"),
        "a": ("book-app", "appendix"),
    }


def test_authored_element_and_type_win():
    tree = instantiate([{"region": "front", "children": [
        {"id": "fw", "type": "front-matter", "title": "Foreword", "data_key": "foreword",
         "element": "foreword", "book_part_type": "foreword"}]}])
    assert (tree[0].element, tree[0].book_part_type) == ("foreword", "foreword")


def test_element_is_a_part_level_bits_element():
    with pytest.raises(ValueError, match="not a part-level BITS element"):
        instantiate([{"region": "body", "children": [_sec("m", "M", element="sec")]}])


def test_part_fields_are_refused_on_nested_nodes():
    with pytest.raises(ValueError, match="top-level part"):
        instantiate([_sec("m", "M", children=[_sec("s", "S", book_part_type="section")])])


def test_parts_must_be_labels():
    with pytest.raises(ValueError, match="parts must be a list"):
        instantiate([{"id": "ab", "type": "front-matter", "title": "Abstract",
                      "data_key": "abstract", "parts": "Background"}])


def test_a_table_may_not_follow_a_sub_section():
    table = {"id": "t", "type": "data-table", "title": "T", "data_key": "x"}
    with pytest.raises(ValueError, match="must come before a section's sub-sections"):
        instantiate([_sec("m", "M", children=[_sec("s", "S"), table])])
    # Before the sub-section, or after an UNTITLED authored block, it is flow.
    instantiate([_sec("m", "M", children=[table, _sec("s", "S")])])
    instantiate([_sec("m", "M", children=[
        {"id": "f", "type": "freeform-block", "title": "", "content": {"html": "<p>x</p>"}},
        table])])


def test_appendix_sections_get_computed_labels():
    tree = instantiate([{"region": "back", "children": [
        {"id": "a", "type": "appendix", "title": "A"},
        {"id": "b", "type": "appendix", "title": "B", "children": [
            {"id": "blk", "type": "freeform-block", "title": "", "content": {"html": "<p>x</p>"}},
            _sec("b1", "First", children=[_sec("b11", "Inner")]),
            _sec("b2", "Second"),
        ]},
    ]}])
    compute_table_numbers(tree)
    b = tree[1]
    labels = {c.id: c.sec_label for c in b.children}
    assert labels == {"blk": None, "b1": "B.1", "b2": "B.2"}
    assert b.children[1].children[0].sec_label == "B.1.1"
    # Print composes the label; the title itself stays bare.
    assert section_heading_text(b.children[1]) == "B.1. First"
    assert b.children[1].title == "First"


def test_body_sections_carry_no_label():
    tree = instantiate([{"region": "body", "children": [_sec("m", "M", children=[_sec("s", "S")])]}])
    compute_table_numbers(tree)
    assert tree[0].children[0].sec_label is None
    assert section_heading_text(tree[0].children[0]) == "S"


def test_shipped_template_declares_the_series_book_meta():
    bm = load_book_meta("niehs-5day-report")
    assert bm["series"]["issn"] == "2768-5632"
    assert bm["publisher"]["name"] == "National Institute of Environmental Health Sciences"
