"""
Tests for cross_references — semantic [[xref:id]] token resolution
(ADR-0004 amendment c).

Covers:
  - table xrefs resolve to the right markup on both render surfaces;
  - an unknown id leaves a visible broken-ref marker (not silent);
  - the broken-ref marker is NOT re-matched (no double-substitution);
  - text without tokens passes through unchanged;
  - composite content-item ids are recognised by the pattern;
  - integration: tokens in _escape_latex'd text survive escaping and resolve.
"""

import re

from cross_references import resolve_xrefs_latex, resolve_xrefs_html
from latex_generator import _escape_latex


def test_table_xref_resolves_to_latex_ref():
    out = resolve_xrefs_latex("see [[xref:bmd-summary]] for details")
    assert "Table~\\ref{tab:bmd-summary}" in out
    # token must be consumed
    assert "[[xref:bmd-summary]]" not in out


def test_table_xref_resolves_to_html_anchor_with_number():
    out = resolve_xrefs_html("see [[xref:bmd-summary]] for details")
    # Numbered + linked to the section anchor.  Number is positional so we
    # don't pin a literal — just require an integer.
    assert re.search(r'<a class="xref" href="#sec-bmd-summary">Table \d+</a>', out)
    assert "[[xref:bmd-summary]]" not in out


def test_unknown_xref_leaves_visible_broken_marker():
    msg_l = resolve_xrefs_latex("see [[xref:no-such-node]]")
    msg_h = resolve_xrefs_html("see [[xref:no-such-node]]")
    assert "[[xref:??no-such-node]]" in msg_l
    assert "[[xref:??no-such-node]]" in msg_h


def test_broken_marker_does_not_re_match():
    """`??` is not in the id pattern, so the visible broken marker must not be
    re-matched on a second resolver pass (no infinite-loop / double-sub)."""
    broken = "[[xref:??no-such-node]]"
    assert resolve_xrefs_latex(broken) == broken
    assert resolve_xrefs_html(broken) == broken


def test_text_without_tokens_passes_through_unchanged():
    sample = "Plain narrative with no references."
    assert resolve_xrefs_latex(sample) == sample
    assert resolve_xrefs_html(sample) == sample


def test_composite_content_item_id_pattern_matches():
    """The id pattern admits composite content-item ids (gene-sets::liver-male-
    table); they won't resolve to a node yet (content items aren't in
    find_node), but they must be RECOGNISED as tokens so the author sees a
    broken-ref marker rather than the token passing through as prose."""
    out = resolve_xrefs_latex("see [[xref:gene-sets::liver-male-table]]")
    assert "[[xref:??gene-sets::liver-male-table]]" in out


def test_escape_latex_integration_resolves_xref_after_escaping():
    """A token in narrative text must survive _escape_latex's character escape
    and then be resolved into the LaTeX cross-reference markup."""
    out = _escape_latex("see [[xref:bmd-summary]] for the BMD endpoints")
    assert "Table~\\ref{tab:bmd-summary}" in out
    assert "[[xref:bmd-summary]]" not in out
