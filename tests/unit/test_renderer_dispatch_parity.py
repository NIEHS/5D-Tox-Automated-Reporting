r"""
Renderer dispatch-parity guard.

ADR-0006 #3 turned what used to be the load-bearing assertion here — "the two
renderers' _DISPATCH tables must agree" — into a STRUCTURAL guarantee: each
renderer now calls render_common.assert_dispatch_covers() against the canonical
RENDERABLE_NODE_TYPES registry at IMPORT time, so a node type registered in one
renderer but not the other (the silent fall-through to "[Section pending]" on
one surface) raises RenderDispatchError on import instead of slipping through.

So these tests no longer compare the two tables to each other — the registry
does that. What remains worth testing:

  1. Both renderers import (a smoke check that the import-time assertions pass
     for the real dispatch tables) — and the registry stays in sync with the
     document tree, so every node_type the tree can actually contain has an
     emitter in both surfaces (modulo the documented LaTeX omission).
  2. The guarantee has teeth: assert_dispatch_covers actually raises on a
     drifted table, rather than silently accepting it.

The LaTeX renderer DELIBERATELY omits cover/title-page (it builds the title
page with \maketitle); that one divergence is declared in render_common.LATEX_OMITS.
"""

import pytest

import html_generator
import latex_generator
from document_tree import DOCUMENT_TREE
from render_common import (
    RENDERABLE_NODE_TYPES,
    LATEX_OMITS,
    RenderDispatchError,
    assert_dispatch_covers,
)


def _tree_node_types(nodes) -> set:
    """Collect every node_type that actually appears in the document tree."""
    seen = set()
    for node in nodes:
        seen.add(node.node_type)
        seen |= _tree_node_types(node.children)
    return seen


def test_registry_covers_every_tree_node_type():
    """
    Every node_type the document tree can contain must be in the canonical
    registry.  Combined with the import-time assert_dispatch_covers() calls in
    each renderer, this transitively guarantees every tree node renders in both
    surfaces (LaTeX's cover/title-page omission aside) — the property the old
    two-table comparison used to check directly.
    """
    tree_types = _tree_node_types(DOCUMENT_TREE)
    unregistered = tree_types - RENDERABLE_NODE_TYPES
    assert not unregistered, (
        "DOCUMENT_TREE contains node_types absent from "
        f"render_common.RENDERABLE_NODE_TYPES: {sorted(unregistered)}. Add them "
        "to the registry and give both renderers an emitter."
    )


def test_both_renderer_dispatch_tables_satisfy_the_registry():
    """
    Smoke check: the real dispatch tables pass the same assertion the renderers
    run at import.  (If they didn't, importing html_generator / latex_generator
    above would already have raised — this makes the guarantee explicit.)
    """
    assert_dispatch_covers(html_generator._DISPATCH, renderer="HTML")
    assert_dispatch_covers(
        latex_generator._DISPATCH, renderer="LaTeX", allow_omit=LATEX_OMITS
    )


def test_assert_dispatch_covers_raises_on_missing_emitter():
    """A table missing a registered type must raise — the guarantee has teeth."""
    incomplete = {t: object() for t in RENDERABLE_NODE_TYPES if t != "table"}
    with pytest.raises(RenderDispatchError, match="missing emitters"):
        assert_dispatch_covers(incomplete, renderer="Test")


def test_assert_dispatch_covers_raises_on_unknown_type():
    """A table registering a type the registry doesn't know must also raise."""
    extra = {t: object() for t in RENDERABLE_NODE_TYPES}
    extra["totally-made-up-type"] = object()
    with pytest.raises(RenderDispatchError, match="absent from the"):
        assert_dispatch_covers(extra, renderer="Test")
