r"""
test_document_reconcile.py — diff x sentinel attribution (ADR-0005).

Proves the reconciler classifies edits to an anchored report.tex correctly:
  - a leaf region edit attributes to that region;
  - an edit to a genomics ITEM attributes to the item, not its enclosing node
    (innermost wins);
  - an edit to a node's OWN content (outside its items) attributes to the node;
  - removing / reordering child sentinels is STRUCTURAL (a warning), never a
    silent content override;
  - a vanished sentinel is reported, not crashed on;
  - apply_reconcile persists the right override (edited body + base_hash of the
    BASELINE region, so the renderer's stale-check lines up).
"""

import roundtrip.overrides as do
from roundtrip.reconcile import reconcile, apply_reconcile


def _wrap(kind: str, aid: str, body: str) -> str:
    return f"%% rlm:begin {kind} {aid}\n{body}\n%% rlm:end {kind} {aid}"


# A genomics-like node with one nested content item.
def _doc(intro: str, narrative: str) -> str:
    item = _wrap("item", "gene-sets::liver-male-narrative", narrative)
    return _wrap("node", "gene-sets", f"{intro}\n{item}")


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------

def test_leaf_edit_attributed():
    base = _wrap("node", "summary", "ORIGINAL")
    edited = _wrap("node", "summary", "EDITED")
    r = reconcile(base, edited)
    assert set(r.edits) == {"summary"}
    assert r.edits["summary"]["edited_body"] == "EDITED"
    assert r.edits["summary"]["baseline_body"] == "ORIGINAL"
    assert not r.structural


def test_item_edit_attributes_item_not_node():
    base = _doc("INTRO", "NARR ORIGINAL")
    edited = _doc("INTRO", "NARR EDITED")
    r = reconcile(base, edited)
    # innermost wins: the item, not the enclosing node
    assert set(r.edits) == {"gene-sets::liver-male-narrative"}
    assert "gene-sets" not in r.edits
    assert not r.structural


def test_node_own_edit_attributes_node():
    base = _doc("INTRO", "NARR")
    edited = _doc("INTRO EDITED", "NARR")  # node's own intro changed, item same
    r = reconcile(base, edited)
    assert set(r.edits) == {"gene-sets"}
    assert "gene-sets::liver-male-narrative" not in r.edits


def test_both_node_and_item_edit_ancestor_subsumes():
    base = _doc("INTRO", "NARR")
    edited = _doc("INTRO EDITED", "NARR EDITED")
    r = reconcile(base, edited)
    # The node override carries the whole body (incl. the edited item), so the
    # subsumed item attribution is dropped.
    assert set(r.edits) == {"gene-sets"}


def test_removed_child_is_structural():
    base = _doc("INTRO", "NARR")
    edited = _wrap("node", "gene-sets", "INTRO")  # item sentinel gone
    r = reconcile(base, edited)
    assert not r.edits
    assert any("gene-sets" in w for w in r.structural)
    assert any("no longer anchored" in w for w in r.structural)


def test_reordered_children_is_structural():
    a = _wrap("item", "gene-sets::a", "A")
    b = _wrap("item", "gene-sets::b", "B")
    base = _wrap("node", "gene-sets", f"{a}\n{b}")
    edited = _wrap("node", "gene-sets", f"{b}\n{a}")  # same items, swapped
    r = reconcile(base, edited)
    assert not r.edits
    assert any("child structure changed" in w for w in r.structural)


def test_unchanged_yields_nothing():
    doc = _doc("INTRO", "NARR")
    r = reconcile(doc, doc)
    assert not r.edits and not r.structural and not r.parse_warnings


# ---------------------------------------------------------------------------
# Persisting overrides
# ---------------------------------------------------------------------------

def test_apply_writes_override(tmp_path):
    base = _wrap("node", "summary", "ORIGINAL SUMMARY")
    edited = _wrap("node", "summary", "REWORDED SUMMARY")
    summary = apply_reconcile(
        "DTXSIDTEST", base, edited, source="overleaf", sessions_dir=tmp_path,
    )
    assert summary["written"] == ["summary"]

    ov = do.get_override("DTXSIDTEST", "summary", sessions_dir=tmp_path)
    assert ov["latex_region"] == "REWORDED SUMMARY"
    # base_hash is the hash of the BASELINE region → matches what the renderer
    # recomputes for the (unchanged) generated region, so it reads "not stale".
    assert ov["base_hash"] == do.region_hash("ORIGINAL SUMMARY")
    assert ov["source"] == "overleaf"


# ---------------------------------------------------------------------------
# html_region derivation (divergence #2, Phase B)
# ---------------------------------------------------------------------------

def test_apply_stores_html_region_for_prose_edit(tmp_path):
    """An edit in the supported prose vocabulary gets an html_region too."""
    base = _wrap("node", "summary", "ORIGINAL")
    edited = _wrap("node", "summary", "Edited with \\textbf{bold} prose.")
    apply_reconcile("DTXSIDTEST", base, edited, sessions_dir=tmp_path)
    ov = do.get_override("DTXSIDTEST", "summary", sessions_dir=tmp_path)
    assert ov["html_region"] == "<p>Edited with <strong>bold</strong> prose.</p>"


def test_apply_omits_html_region_for_untranslatable_edit(tmp_path):
    """
    An edit containing markup the conservative translator doesn't handle (a
    table environment) stores NO html_region — the preview falls back to the
    Phase A stale marker rather than emitting broken HTML.
    """
    base = _wrap("node", "summary", "ORIGINAL")
    edited = _wrap("node", "summary",
                   "\\begin{niehstable}{x}\n1 & 2 \\\\\n\\end{niehstable}")
    apply_reconcile("DTXSIDTEST", base, edited, sessions_dir=tmp_path)
    ov = do.get_override("DTXSIDTEST", "summary", sessions_dir=tmp_path)
    assert "html_region" not in ov
    # The latex_region is still stored verbatim — only the HTML rendering is absent.
    assert "niehstable" in ov["latex_region"]
