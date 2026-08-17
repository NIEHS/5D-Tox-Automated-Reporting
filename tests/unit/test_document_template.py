"""
Golden-tree equality oracle for the data-driven template (ADR-0003 Phase 2).

ADR-0003 makes DOCUMENT_TREE the OUTPUT of instantiating a template, not a
hand-written literal.  The cutover is only safe if the instantiated tree
reproduces the original hand-written tree EXACTLY — structure, ordering,
derived levels, and positional table numbers.  This test is that oracle: it
instantiates templates/niehs-5day-report.yaml and asserts the serialized
result matches the frozen snapshot captured from the original literal
(tests/unit/fixtures/document_tree_golden.json), byte-for-byte.

This mirrors ADR-0002's golden-snapshot discipline: a single structural change
in the template or the instantiator that diverges from the original tree fails
here.  If a divergence is INTENTIONAL (the template legitimately changed),
regenerate the fixture:

    UPDATE_GOLDEN=1 uv run python -m pytest tests/unit/test_document_template.py

The structural-validation tests below pin the instantiator's guard rails
(unknown type, unknown key, disallowed nesting, missing required key, missing
required binding).
"""

import json
import os
import pathlib

import pytest

from document_model.document_tree import compute_table_numbers, serialize_tree
from document_model.document_template import build_tree, instantiate, load_template

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "document_tree_golden.json"
TEMPLATE_NAME = "niehs-5day-report"


def _instantiated_serialized() -> str:
    """Instantiate the template and serialize it the same way the fixture was."""
    tree = build_tree(TEMPLATE_NAME)
    compute_table_numbers(tree)  # positional numbers, exactly as on the literal
    return json.dumps(serialize_tree(tree), sort_keys=True, indent=2, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------------------
# The golden-tree equality test — the Phase-2 cutover oracle
# ---------------------------------------------------------------------------

def test_instantiated_template_matches_frozen_tree():
    produced = _instantiated_serialized()

    if os.environ.get("UPDATE_GOLDEN"):
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(produced, encoding="utf-8")
        pytest.skip(f"UPDATE_GOLDEN set — regenerated {FIXTURE.name}")

    expected = FIXTURE.read_text(encoding="utf-8")
    assert produced == expected, (
        "Instantiating the template no longer reproduces the frozen document "
        "tree.\nIf this change is INTENTIONAL, regenerate the fixture:\n"
        "    UPDATE_GOLDEN=1 uv run python -m pytest tests/unit/test_document_template.py"
    )


# ---------------------------------------------------------------------------
# Instantiator guard rails
# ---------------------------------------------------------------------------

def test_unknown_type_is_rejected():
    with pytest.raises(ValueError, match="not in the catalog"):
        instantiate([{"id": "x", "type": "no-such-type", "title": "X"}])


def test_unknown_key_is_rejected():
    with pytest.raises(ValueError, match="unknown key"):
        instantiate([{"id": "x", "type": "narrative", "title": "X",
                      "data_key": "d", "bogus": 1}])


def test_missing_required_key_is_rejected():
    with pytest.raises(ValueError, match="missing required key"):
        instantiate([{"type": "narrative", "title": "X"}])


def test_disallowed_child_is_rejected():
    # `table` is not an allowed child of `narrative` (only of narrative+tables).
    bad = [
        {
            "id": "p",
            "type": "narrative",
            "title": "P",
            "data_key": "d",
            "children": [{"id": "c", "type": "table", "title": "C", "platform": "P"}],
        }
    ]
    with pytest.raises(ValueError, match="not an allowed child"):
        instantiate(bad)


def test_subtype_accepted_on_cover_and_title_page():
    # subtype (which branded cover layout) is valid on cover / title-page.
    tree = instantiate([
        {"id": "cover", "type": "cover", "title": "C", "subtype": "niehs-5d-tox"},
        {"id": "tp", "type": "title-page", "title": "T", "subtype": "niehs-5d-tox"},
    ])
    assert tree[0].subtype == "niehs-5d-tox"
    assert tree[1].subtype == "niehs-5d-tox"


def test_subtype_rejected_on_other_types():
    # subtype on a non-cover type is a template authoring error.
    with pytest.raises(ValueError, match="subtype is only valid on"):
        instantiate([{"id": "s", "type": "heading-only", "title": "S",
                      "subtype": "niehs-5d-tox"}])


def test_missing_required_binding_is_rejected():
    # A `table` must name a `platform`; omitting it is a load-time error.
    bad = [
        {
            "id": "nt",
            "type": "narrative+tables",
            "title": "NT",
            "children": [{"id": "t", "type": "table", "title": "T"}],
        }
    ]
    with pytest.raises(ValueError, match="missing required binding 'platform'"):
        instantiate(bad)


def test_level_is_derived_not_authored():
    """A headingless type gets level 0; a heading type gets its nesting depth."""
    tree = instantiate(
        [
            {"id": "sec", "type": "heading-only", "title": "S", "children": [
                {"id": "tbl", "type": "narrative+tables", "title": "NT", "children": [
                    {"id": "t", "type": "table", "title": "T", "platform": "P"},
                ]},
            ]},
        ]
    )
    sec = tree[0]
    nt = sec.children[0]
    t = nt.children[0]
    assert sec.level == 1          # heading-only at depth 1
    assert nt.level == 2           # narrative+tables at depth 2
    assert t.level == 0            # table is headingless → level 0 regardless of depth


def test_template_file_loads_as_a_list():
    # ADR-0004 amendment d: top level is three region containers, not bare
    # node entries.  The first one is the front-matter container; its first
    # child is the title page (there is no cover node — the reference DOCX opens
    # directly on the title page).
    data = load_template(TEMPLATE_NAME)
    assert isinstance(data, list) and data, "template should be a non-empty list"
    assert data[0]["region"] == "front"
    assert data[0]["children"][0]["id"] == "title-page"
    assert [c["region"] for c in data] == ["front", "body", "back"]


# ---------------------------------------------------------------------------
# Declarative layout settings (ADR-0003 Amendment 1)
# ---------------------------------------------------------------------------

def test_orientation_accepted_on_orientable_type():
    tree = instantiate([{"id": "t", "type": "table", "title": "T",
                         "platform": "P", "orientation": "landscape"}])
    assert tree[0].orientation == "landscape"


def test_orientation_rejected_on_non_orientable_type():
    # `narrative` is not orientable, so authoring orientation on it is a
    # load-time error (capability-gated), not a silent no-op.
    with pytest.raises(ValueError, match="not orientable"):
        instantiate([{"id": "x", "type": "narrative", "title": "X",
                      "data_key": "d", "orientation": "landscape"}])


def test_invalid_orientation_value_rejected():
    with pytest.raises(ValueError, match="orientation must be"):
        instantiate([{"id": "t", "type": "table", "title": "T",
                      "platform": "P", "orientation": "sideways"}])


def test_caption_accepted_on_captionable_table():
    tree = instantiate([{"id": "t", "type": "table", "title": "T",
                         "platform": "P", "caption": "A descriptive line."}])
    assert tree[0].caption == "A descriptive line."


def test_caption_rejected_on_non_captionable_section():
    # `narrative` is a section (BITS <sec>: <title> only, no <caption>), so
    # authoring `caption` on it must fail loudly — capability-gated.
    with pytest.raises(ValueError, match="not captionable"):
        instantiate([{"id": "x", "type": "narrative", "title": "X",
                      "data_key": "d", "caption": "nope"}])


# ---------------------------------------------------------------------------
# Region containers (ADR-0004 amendment d)
# ---------------------------------------------------------------------------

def test_region_container_inherits_region_to_descendants():
    """A region container sets `region` on every child and grandchild."""
    tree = instantiate([
        {"region": "body", "children": [
            {"id": "sec", "type": "heading-only", "title": "S", "children": [
                {"id": "nt", "type": "narrative+tables", "title": "NT", "children": [
                    {"id": "t", "type": "table", "title": "T", "platform": "P"},
                ]},
            ]},
        ]},
    ])
    sec = tree[0]
    nt = sec.children[0]
    t = nt.children[0]
    assert sec.region == "body"
    assert nt.region == "body"
    assert t.region == "body"


def test_region_container_with_invalid_region_is_rejected():
    with pytest.raises(ValueError, match="region must be one of"):
        instantiate([{"region": "middle", "children": []}])


def test_region_container_with_unknown_key_is_rejected():
    # Only `region` and `children` are allowed on a region container.
    with pytest.raises(ValueError, match="unknown key"):
        instantiate([{"region": "front", "children": [], "stray": 1}])


def test_region_container_children_must_be_a_list():
    with pytest.raises(ValueError, match="must be a list"):
        instantiate([{"region": "front", "children": "not-a-list"}])


def test_bare_top_level_entry_has_region_none():
    # Back-compat: a bare node entry (no region container) instantiates
    # with region=None — used by every existing guard-rail test above.
    tree = instantiate([{"id": "x", "type": "narrative", "title": "X",
                         "data_key": "d"}])
    assert tree[0].region is None


def test_top_level_unrolls_regions_into_flat_list():
    """instantiate() returns a flat list of nodes; region containers are
    unrolled so DOCUMENT_TREE keeps the pre-amendment shape."""
    tree = instantiate([
        {"region": "front", "children": [
            {"id": "cover", "type": "cover", "title": "Cover"},
        ]},
        {"region": "body", "children": [
            {"id": "bg", "type": "narrative", "title": "BG", "data_key": "bg"},
        ]},
    ])
    assert [n.id for n in tree] == ["cover", "bg"]
    assert [n.region for n in tree] == ["front", "body"]


# ---------------------------------------------------------------------------
# ADR-0003 Part B — authored content_items instantiation + validation
# ---------------------------------------------------------------------------

def _node_with_items(items):
    return [{"id": "sec", "type": "narrative", "title": "Sec",
             "data_key": "d", "content_items": items}]


def test_content_items_instantiate_onto_node():
    tree = instantiate(_node_with_items([
        {"id": "intro", "kind": "text", "text": "Hello."},
        {"id": "tbl", "kind": "table", "data_key": "some_table", "orientable": True},
    ]))
    node = tree[0]
    assert [ci.id for ci in node.content_items] == ["intro", "tbl"]
    assert node.content_items[0].kind == "text"
    assert node.content_items[1].orientable is True
    assert node.content_items[1].data_key == "some_table"


def test_content_item_unknown_kind_rejected():
    with pytest.raises(ValueError, match="is not a content kind"):
        instantiate(_node_with_items([{"id": "x", "kind": "bogus"}]))


def test_content_item_duplicate_id_rejected():
    with pytest.raises(ValueError, match="duplicate content-item id"):
        instantiate(_node_with_items([
            {"id": "dup", "kind": "text", "text": "a"},
            {"id": "dup", "kind": "text", "text": "b"},
        ]))


def test_content_item_unknown_key_rejected():
    with pytest.raises(ValueError, match="unknown key"):
        instantiate(_node_with_items([{"id": "x", "kind": "text", "bogus": 1}]))


def test_content_item_text_and_data_key_both_rejected():
    with pytest.raises(ValueError, match="only one of 'text' or 'data_key'"):
        instantiate(_node_with_items([
            {"id": "x", "kind": "table", "text": "t", "data_key": "d"},
        ]))


def test_content_item_missing_id_rejected():
    with pytest.raises(ValueError, match="missing required 'id'"):
        instantiate(_node_with_items([{"kind": "text", "text": "t"}]))


def test_content_item_bad_orientation_rejected():
    with pytest.raises(ValueError, match="orientation must be"):
        instantiate(_node_with_items([
            {"id": "x", "kind": "table", "data_key": "d", "orientation": "sideways"},
        ]))


def test_content_items_serialize_round_trips():
    from document_model.document_tree import serialize_tree
    tree = instantiate(_node_with_items([
        {"id": "tbl", "kind": "table", "data_key": "d2", "orientable": True,
         "caption": "Cap"},
    ]))
    d = serialize_tree(tree)[0]
    assert d["content_items"] == [
        {"id": "tbl", "kind": "table", "orientable": True,
         "data_key": "d2", "caption": "Cap"},
    ]


def test_cross_component_item_id_reuse_is_allowed():
    """Item ids are unique WITHIN a component, not globally — two sibling nodes
    may each own an item with the same id (the composite <node>::<item> key
    disambiguates). This must NOT raise."""
    tree = instantiate([
        {"id": "a", "type": "narrative", "title": "A", "data_key": "da",
         "content_items": [{"id": "table", "kind": "table", "data_key": "x"}]},
        {"id": "b", "type": "narrative", "title": "B", "data_key": "db",
         "content_items": [{"id": "table", "kind": "table", "data_key": "y"}]},
    ])
    assert tree[0].content_items[0].id == tree[1].content_items[0].id == "table"
