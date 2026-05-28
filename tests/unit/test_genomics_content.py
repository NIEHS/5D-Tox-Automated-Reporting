"""
Tests for the genomics content-item decomposition (ADR-0003 Phase 4, Part B).

Two concerns:
  1. genomics_content_plan returns the correct ordered, stably-identified
     content items for a (organ, sex) entry — the single source of item order
     and identity shared by both renderers.
  2. The LaTeX renderer honours sub-addressable orientation: flipping a single
     content item (via the composite "<component>::<item>" key) wraps only that
     item in a landscape environment, and the absence of any composite key
     leaves the output exactly as the pre-decomposition monolith produced it
     (verified more strongly by the byte-identical golden/baseline checks).
"""

from document_node import DocNode
from genomics_content import genomics_content_plan
from latex_generator import _render_genomics_section

_GENE_SET_ROW = {
    "rank": 1, "go_id": "GO:0001", "go_term": "apoptosis",
    "bmd": 12.3, "bmdl": 8.1, "n_genes": 5, "direction": "up",
}


def test_plan_full_gene_set_entry_is_ordered_and_identified():
    entry = {
        "type": "gene_set", "organ": "Liver", "sex": "Male",
        "narrative": ["prose"], "gene_sets": [_GENE_SET_ROW],
        "go_descriptions": [{"go_term": "apoptosis", "description": "d"}],
    }
    plan = genomics_content_plan(entry, "gene_set")
    assert [p["part"] for p in plan] == ["narrative", "table", "descriptions"]
    assert [p["item_id"] for p in plan] == [
        "liver-male-narrative", "liver-male-table", "liver-male-descriptions",
    ]
    # Only the table is orientable.
    assert [p["orientable"] for p in plan] == [False, True, False]


def test_plan_table_is_always_present_even_when_empty():
    entry = {"type": "gene_set", "organ": "Kidney", "sex": "Female", "gene_sets": []}
    plan = genomics_content_plan(entry, "gene_set")
    assert [p["part"] for p in plan] == ["table"]
    assert plan[0]["item_id"] == "kidney-female-table"


def test_plan_gene_entry_uses_gene_descriptions():
    entry = {
        "type": "gene", "organ": "Liver", "sex": "Male",
        "top_genes": [{"rank": 1, "gene": "Cyp1a1"}],
        "gene_descriptions": [{"gene": "Cyp1a1", "description": "d"}],
    }
    plan = genomics_content_plan(entry, "gene")
    assert [p["part"] for p in plan] == ["table", "descriptions"]


def _gene_set_node():
    return DocNode(id="gene-sets", title="Gene Set BMD Analysis",
                   level=2, node_type="genomics-section")


def _gene_set_data(orientations=None):
    return {
        "genomics_sections": [
            {"type": "gene_set", "organ": "liver", "sex": "male",
             "gene_sets": [_GENE_SET_ROW]},
        ],
        "orientations": orientations or {},
    }


def test_content_item_orientation_wraps_only_that_item():
    data = _gene_set_data({"gene-sets::liver-male-table": "landscape"})
    out = _render_genomics_section(_gene_set_node(), data)
    assert "\\begin{landscape}" in out and "\\end{landscape}" in out


def test_no_composite_key_means_no_landscape_wrap():
    out = _render_genomics_section(_gene_set_node(), _gene_set_data())
    assert "\\begin{landscape}" not in out


def test_plan_includes_chart_items_when_charts_attached():
    entry = {
        "type": "gene_set", "organ": "Liver", "sex": "Male",
        "gene_sets": [_GENE_SET_ROW],
        "charts": [
            {"key": "umap", "filename": "genomics-liver-male-umap.png",
             "png_b64": "x", "caption": "U"},
            {"key": "cluster", "filename": "genomics-liver-male-cluster.png",
             "png_b64": "y", "caption": "C"},
        ],
    }
    plan = genomics_content_plan(entry, "gene_set")
    # table first, then one orientable chart item per attached chart, in order.
    assert [p["part"] for p in plan] == ["table", "chart", "chart"]
    charts = [p for p in plan if p["part"] == "chart"]
    assert [p["chart_key"] for p in charts] == ["umap", "cluster"]
    assert [p["item_id"] for p in charts] == ["liver-male-umap", "liver-male-cluster"]
    assert all(p["orientable"] for p in charts)


def test_latex_renders_chart_includegraphics_with_matching_filename():
    data = {
        "genomics_sections": [{
            "type": "gene_set", "organ": "liver", "sex": "male",
            "gene_sets": [_GENE_SET_ROW],
            "charts": [{"key": "umap", "filename": "genomics-liver-male-umap.png",
                        "png_b64": "x", "caption": "UMAP of liver"}],
        }],
        "orientations": {},
    }
    out = _render_genomics_section(_gene_set_node(), data)
    assert "\\includegraphics" in out
    # The \includegraphics path must be exactly the chart's own filename, so the
    # bundler writes the same name (no missing-figure compile error).
    assert "figures/genomics-liver-male-umap.png" in out
