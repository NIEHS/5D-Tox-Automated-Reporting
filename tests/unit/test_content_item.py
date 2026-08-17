"""
Unit tests for the content-item model (ADR-0003 Part B, Stage 2):
  * the ContentItem dataclass (document_model/content_item.py) — leaf shape;
  * resolve_content_items (rendering/render_common.py) — the single ordered
    sequence every emitter iterates for a component's sub-addressable items.

Stage 2 wires ONLY the genomics branch (a behavior-preserving refactor); the
template-authored branch is a later stage and resolves to [] here.
"""

import pytest

from document_model.content_item import ContentItem
from document_model.document_node import DocNode
from rendering.render_common import resolve_content_items, ResolvedContentItem


# --- ContentItem dataclass ------------------------------------------------

def test_content_item_defaults():
    ci = ContentItem(id="liver-table", kind="table")
    assert ci.orientable is False and ci.breakable is False
    assert ci.text is None and ci.data_key is None
    # dispatch_part falls back to kind when part is unset
    assert ci.dispatch_part == "table"


def test_content_item_dispatch_part_prefers_part():
    ci = ContentItem(id="x", kind="text", part="narrative")
    assert ci.dispatch_part == "narrative"


# --- resolve_content_items: genomics branch -------------------------------

def _genomics_node(node_id="gene-sets"):
    return DocNode(id=node_id, title="Gene Set BMD Analysis",
                   node_type="genomics-section", data_key="genomics_sections",
                   narrative_key="gene_set_narrative")


def _data(entries):
    return {"genomics_sections": entries}


def test_resolve_genomics_orders_items_and_keys_them():
    # One gene_set entry with narrative + (implicit) table + descriptions.
    entry = {
        "type": "gene_set", "organ": "Liver",
        "narrative": ["Hepatic gene expression ..."],
        "gene_sets": [{"name": "GO:x", "bmd_median": "0.5"}],
        "go_descriptions": [{"go_term": "GO:x", "description": "d"}],
    }
    resolved = resolve_content_items(_genomics_node(), _data([entry]))
    assert [r.item_id for r in resolved] == [
        "liver-narrative", "liver-table", "liver-descriptions",
    ]
    # composite overlay key = "<component>::<item>"
    assert resolved[0].overlay_key == "gene-sets::liver-narrative"
    # each carries its source entry + role for the surface's per-item renderer
    assert all(r.source == "genomics" for r in resolved)
    assert all(r.role == "gene_set" for r in resolved)
    assert resolved[0].entry is entry
    # the table item is the orientable one
    table = next(r for r in resolved if r.item_id == "liver-table")
    assert table.orientable is True


def test_resolve_genomics_only_matching_role_entries():
    # A gene-sets node ignores gene-type entries (role filtering).
    entries = [
        {"type": "gene_set", "organ": "Liver", "gene_sets": [{}]},
        {"type": "gene", "organ": "Kidney", "top_genes": [{}]},
    ]
    resolved = resolve_content_items(_genomics_node("gene-sets"), _data(entries))
    assert {r.entry["organ"] for r in resolved} == {"Liver"}


def test_resolve_genomics_empty_when_no_entries():
    assert resolve_content_items(_genomics_node(), _data([])) == []


# --- resolve_content_items: non-genomics -> [] (template branch is later) --

def test_resolve_non_genomics_node_is_empty():
    n = DocNode(id="background", title="Background", node_type="narrative",
                data_key="background")
    assert resolve_content_items(n, {"background": {"paragraphs": ["x"]}}) == []


def test_resolved_content_item_overlay_key():
    r = ResolvedContentItem(component_id="gene-bmd", item_id="kidney-table",
                            orientable=True, source="genomics")
    assert r.overlay_key == "gene-bmd::kidney-table"
