"""
Tests for the Methods "Final Sample Counts" table (Table 1) — a first-class
`sample-counts-table` tree node declared in the YAML template.

Covers the three moving parts:
  - build_sample_counts_from_context: builds the matrix from a MethodsContext,
    reconstructing genomics_sample_counts from a session's _fingerprints.json
    when the cached context lacks them (the stale-cache path).
  - both emitters (LaTeX + HTML) render the "Table 1." caption, a known count
    row, and dashes for the fully-culled 333/1000 mg/kg groups.
  - the node earns Table 1 positionally.
"""

import json

from document_node import DocNode
from document_tree import DOCUMENT_TREE, compute_table_numbers, find_node
from latex_generator import _render_sample_counts_table as latex_sc
from html_generator import _render_sample_counts_table as html_sc


# A node matching the YAML entry (headingless, data_key sample_counts, authored
# caption).  compute_table_numbers assigns the number on the real tree; for the
# emitter tests we set it explicitly.
def _node(table_number=1):
    n = DocNode(
        id="table-sample-counts",
        title="Final Sample Counts for Benchmark Dose Analysis of the Transcriptomics Data",
        level=0, node_type="sample-counts-table", data_key="sample_counts",
        caption="Final Sample Counts for Benchmark Dose Analysis of the Transcriptomics Data",
    )
    n.table_number = table_number
    return n


_BUILT = {
    "caption": "Final Sample Counts for BMD Analysis of Transcriptomics Data",
    "headers": ["", "0 mg/kg", "37 mg/kg", "333 mg/kg", "1000 mg/kg"],
    "rows": [
        ["**Female**", "", "", "", ""],
        ["  Kidney", "10", "5", "–", "–"],
        ["  Liver", "10", "5", "–", "–"],
        ["**Male**", "", "", "", ""],
        ["  Kidney", "10", "5", "–", "–"],
    ],
    "footnotes": [],
}


# ---------------------------------------------------------------------------
# Positional numbering
# ---------------------------------------------------------------------------

def test_node_is_table_one_positionally():
    import copy
    tree = copy.deepcopy(DOCUMENT_TREE)
    compute_table_numbers(tree)
    node = find_node("table-sample-counts", tree)
    assert node is not None
    assert node.node_type == "sample-counts-table"
    assert node.table_number == 1


# ---------------------------------------------------------------------------
# Builder — with and without pre-computed counts
# ---------------------------------------------------------------------------

def test_build_uses_context_counts_when_present():
    from methods_table1 import build_sample_counts_from_context
    ctx = {
        "dose_groups": [0.0, 37.0, 333.0],
        "dose_unit": "mg/kg",
        "genomics_sample_counts": {"Liver": {"Male": {0.0: 10, 37.0: 5, 333.0: 0}}},
    }
    built = build_sample_counts_from_context(ctx)
    assert built is not None
    # Header corner + 3 dose columns.
    assert built["headers"][0] == ""
    assert "0 mg/kg" in built["headers"] and "333 mg/kg" in built["headers"]
    # Male sex-header row + one Liver row.
    labels = [r[0] for r in built["rows"]]
    assert "**Male**" in labels
    liver = next(r for r in built["rows"] if r[0].strip() == "Liver")
    assert liver[1:] == ["10", "5", "–"]   # 333 → dash


def test_build_reconstructs_from_fingerprints_when_context_lacks_counts(tmp_path):
    """A stale cache (genomics_sample_counts absent) still yields Table 1 by
    reconstructing counts from the session's _fingerprints.json."""
    from methods_table1 import build_sample_counts_from_context
    # Minimal gene_expression fingerprint carrying n_animals_by_dose.
    (tmp_path / "_fingerprints.json").write_text(json.dumps({
        "Liver_Male.txt": {
            "data_type": "gene_expression", "organ": "Liver", "sexes": ["Male"],
            "n_animals_by_dose": {"0.0": 10, "37.0": 5, "333.0": 0},
        },
    }), encoding="utf-8")

    ctx = {
        "dose_groups": [0.0, 37.0, 333.0],
        "dose_unit": "mg/kg",
        # No genomics_sample_counts key — the stale-cache case.
    }
    built = build_sample_counts_from_context(ctx, session_dir=tmp_path)
    assert built is not None
    liver = next(r for r in built["rows"] if r[0].strip() == "Liver")
    assert liver[1:] == ["10", "5", "–"]


def test_build_returns_none_without_context():
    from methods_table1 import build_sample_counts_from_context
    assert build_sample_counts_from_context(None) is None
    assert build_sample_counts_from_context({}) is None


def test_build_returns_none_when_no_counts_and_no_session():
    from methods_table1 import build_sample_counts_from_context
    # No counts and no session_dir → nothing to tabulate.
    assert build_sample_counts_from_context(
        {"dose_groups": [0.0], "dose_unit": "mg/kg"}
    ) is None


# ---------------------------------------------------------------------------
# Emitters — both surfaces
# ---------------------------------------------------------------------------

def test_latex_emitter_caption_rows_and_dashes():
    tex = latex_sc(_node(1), {"sample_counts": _BUILT})
    assert "\\begin{niehstable}" in tex and "\\end{niehstable}" in tex
    # "Table 1." caption (node.caption wins).
    assert "Table 1. Final Sample Counts for Benchmark Dose" in tex
    # Sex-header row rendered as a bold multicolumn separator.
    assert "\\textbf{Female}" in tex and "\\textbf{Male}" in tex
    # A known count row + the culled-group dashes.
    assert "Kidney & 10 & 5" in tex
    assert "–" in tex   # en dash for 333/1000
    # \small width guard present.
    assert "\\small" in tex


def test_html_emitter_caption_rows_and_dashes():
    html = html_sc(_node(1), {"sample_counts": _BUILT})
    assert '<table class="niehstable">' in html
    assert "<caption>Table 1. Final Sample Counts for Benchmark Dose" in html
    # Sex-header row is a bold full-width separator.
    assert "<strong>Female</strong>" in html and "<strong>Male</strong>" in html
    assert "<td>Kidney</td><td>10</td><td>5</td>" in html
    assert "–" in html


def test_emitters_pending_when_no_data():
    node = _node(1)
    tex = latex_sc(node, {})
    html = html_sc(node, {})
    assert "pending" in tex.lower()
    assert "pending" in html.lower()
    # Still claims Table 1 (appears in the list of tables) even when pending.
    assert "Table 1." in tex and "Table 1." in html
