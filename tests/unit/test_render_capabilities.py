"""
test_render_capabilities.py — the document-semantic → rendering-semantic
capability dictionary.

Verifies the single coupling point: which rendering operations each node
type supports, the safe default for unknown types (so the template can add
a type without breaking anything), and the tree annotation the frontend
reads.
"""

from render_capabilities import (
    capabilities_for,
    annotate_capabilities,
    NodeCapabilities,
)


# ---------------------------------------------------------------------------
# capabilities_for
# ---------------------------------------------------------------------------

def test_tables_are_orientable_and_breakable_not_editable():
    """Data tables/charts: flippable + breakable, but data-driven (no text edit)."""
    for t in ("table", "incidence-table", "bmd-summary", "genomics-section"):
        c = capabilities_for(t)
        assert c.orientable, t
        assert c.breakable, t
        assert not c.editable, t


def test_prose_is_editable_and_breakable_not_orientable():
    """Prose: editable text + breakable, never landscape."""
    for t in ("narrative", "front-matter", "appendix", "narrative+tables"):
        c = capabilities_for(t)
        assert c.editable, t
        assert c.breakable, t
        assert not c.orientable, t


def test_fixed_front_pages_have_no_capabilities():
    """Cover / title page are auto-laid-out — nothing is user-configurable."""
    for t in ("cover", "title-page"):
        c = capabilities_for(t)
        assert not (c.orientable or c.breakable or c.editable), t


def test_unknown_type_gets_safe_default():
    """
    A type the dictionary doesn't cover is inert (all False) — this is what
    lets the template add a node type without a code change elsewhere.
    """
    c = capabilities_for("some-future-node-type")
    assert c == NodeCapabilities()
    assert not (c.orientable or c.breakable or c.editable)


# ---------------------------------------------------------------------------
# annotate_capabilities
# ---------------------------------------------------------------------------

def test_annotate_capabilities_walks_tree_recursively():
    """Every node (and child) gets a capabilities dict from its type."""
    tree = [
        {"id": "results", "type": "heading-only", "children": [
            {"id": "tbl", "type": "table"},
            {"id": "bg", "type": "narrative"},
        ]},
    ]
    annotate_capabilities(tree)
    assert tree[0]["capabilities"]["breakable"] is True
    assert tree[0]["capabilities"]["orientable"] is False
    assert tree[0]["children"][0]["capabilities"]["orientable"] is True   # table
    assert tree[0]["children"][1]["capabilities"]["editable"] is True     # narrative
    assert tree[0]["children"][1]["capabilities"]["orientable"] is False
