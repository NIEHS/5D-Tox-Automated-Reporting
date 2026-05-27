r"""
Renderer dispatch-parity guard.

The HTML and LaTeX renderers each keep a `_DISPATCH` table mapping node_type
to a render handler.  Nothing structurally forces the two tables to agree, so
a node_type added to one renderer but not the other would render fine in one
output surface and silently fall through to `_render_unimplemented` ("[Section
pending]") in the other — a desync the author would only notice on Overleaf.
These tests turn that silent drift into a loud failure.

The LaTeX renderer DELIBERATELY omits `cover`/`title-page` (it builds the
title page with \maketitle), so those two types are the one allowed divergence.
"""

import html_generator
import latex_generator
from document_tree import DOCUMENT_TREE

# The single documented, intentional divergence between the two renderers.
LATEX_OMITS = {"cover", "title-page"}


def _tree_node_types(nodes) -> set:
    """Collect every node_type that actually appears in the document tree."""
    seen = set()
    for node in nodes:
        seen.add(node.node_type)
        seen |= _tree_node_types(node.children)
    return seen


def test_dispatch_tables_match_except_documented_exception():
    """HTML and LaTeX must register the same node_types, modulo cover/title-page."""
    html_types = set(html_generator._DISPATCH)
    latex_types = set(latex_generator._DISPATCH)

    html_only = html_types - latex_types
    latex_only = latex_types - html_types

    assert html_only == LATEX_OMITS, (
        "HTML/LaTeX dispatch drifted beyond the documented cover/title-page "
        f"exception. HTML-only (unexpected)={html_only - LATEX_OMITS}, "
        f"LaTeX-only (unexpected)={latex_only}"
    )
    assert latex_only == set(), f"LaTeX registers node_types HTML doesn't: {latex_only}"


def test_every_tree_node_type_has_a_handler_in_both_renderers():
    """Every node_type used in DOCUMENT_TREE must render in both surfaces."""
    tree_types = _tree_node_types(DOCUMENT_TREE)

    missing_html = tree_types - set(html_generator._DISPATCH)
    missing_latex = tree_types - set(latex_generator._DISPATCH) - LATEX_OMITS

    assert not missing_html, (
        f"node_types in DOCUMENT_TREE with no HTML handler: {missing_html}"
    )
    assert not missing_latex, (
        f"node_types in DOCUMENT_TREE with no LaTeX handler "
        f"(beyond the {LATEX_OMITS} exception): {missing_latex}"
    )
