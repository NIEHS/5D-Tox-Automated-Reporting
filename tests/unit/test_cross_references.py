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

from cross_references import resolve_xrefs_latex, resolve_xrefs_html, latex_label_key
from document_model.document_node import DocNode
from latex_generator import _escape_latex, _emit_table_placeholder


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


# ---------------------------------------------------------------------------
# latex_label_key — sanitizing node ids for \label{tab:<id>} / \ref{tab:<id>}
# ---------------------------------------------------------------------------

def test_latex_label_key_is_identity_on_plain_slugs():
    """Every id in the tree today is a plain [a-z0-9-] slug, so the sanitizer
    must be the identity on them — otherwise it would change the .tex output."""
    for slug in ("bmd-summary", "table-clinical-obs", "appendix-a", "results"):
        assert latex_label_key(slug) == slug


def test_latex_label_key_strips_latex_special_chars():
    r"""An id with a LaTeX-special char (here `&` and `_`) must not survive raw
    into the key — `_` would expand to subscript math and `&` is an alignment
    tab, either of which breaks the \label{tab:<id>}."""
    key = latex_label_key("foo_bar&baz")
    assert "&" not in key
    assert "_" not in key


def test_niehstable_label_site_strips_special_char_from_id():
    r"""The niehstable label site (latex_generator) must route node.id through
    latex_label_key, so a special-char id never reaches \label{tab:<id>} raw.

    RED before the fix: the placeholder spliced node.id directly, so the
    emitted `\begin{niehstable}{...}` carried a literal `&`.
    """
    node = DocNode(id="tbl-a&b", title="Body Weight", level=0,
                   node_type="incidence-table")
    placeholder = _emit_table_placeholder(node)
    m = re.search(r"\\begin\{niehstable\}\{([^}]*)\}", placeholder)
    assert m, "expected a niehstable environment in the placeholder"
    assert "&" not in m.group(1), "raw & leaked into the niehstable label key"


def test_niehstable_label_matches_ref_for_underscore_id(monkeypatch):
    r"""The label site (latex_generator) and the ref site (cross_references)
    must emit the SAME key for the same id, or a \ref won't resolve to its
    \label.  `_` is the one LaTeX-special char that survives the xref token
    pattern (\w includes it) AND is a valid node id, so it's the realistic
    failure: pre-fix the ref emitted `\ref{tab:tbl_foo}` (subscript-math break)
    while the label emitted the same raw `_`.  Both now route through
    latex_label_key, collapsing `_` to `-` on both sides.

    RED before the fix: ref carried a raw `_`, mismatching the label key.
    """
    table_node = DocNode(id="tbl_foo", title="Body Weight", level=0,
                         node_type="incidence-table")
    # The ref site resolves the target via find_node; point it at our node so
    # the table-typed branch (which emits \ref{tab:...}) is exercised.
    monkeypatch.setattr("cross_references.find_node", lambda _id: table_node)

    placeholder = _emit_table_placeholder(table_node)
    label_key = re.search(r"\\begin\{niehstable\}\{([^}]*)\}", placeholder).group(1)
    assert "_" not in label_key

    ref = resolve_xrefs_latex("see [[xref:tbl_foo]]")
    assert f"\\ref{{tab:{label_key}}}" in ref
