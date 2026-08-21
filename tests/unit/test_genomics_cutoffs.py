"""
Unit tests for the phase-4 GO-cutoff-at-read model.

Phase 4 moved the four GO-category cutoffs (go_pct / go_min_genes / go_max_genes
/ go_min_bmd) OUT of the genomics extraction+cache key and INTO a render-time
filter (processing_helpers.apply_genomics_cutoffs), applied to the cutoff-
agnostic superset.  So a report version can change cutoffs with no Java
re-extraction — the same "extract full, filter at read" model sections/genomics
allowlists already use.
"""

import pytest

from pipeline.processing_helpers import apply_genomics_cutoffs
from pipeline.cache_plumbing import _hash_genomics


def _superset():
    # A minimal cutoff-agnostic genomics superset: one section, one stat, four GO
    # rows spanning the cutoff dimensions.  gene_sets_chart_by_stat holds ALL rows
    # (with n_genes / n_genes_with_bmd), which is what apply_genomics_cutoffs reads.
    rows = [
        # go_id,          n_genes, n_passed  → pct
        {"go_id": "GO:1", "go_term": "a", "n_genes": 100, "n_genes_with_bmd": 40},  # pct 40
        {"go_id": "GO:2", "go_term": "b", "n_genes": 100, "n_genes_with_bmd": 5},   # pct 5
        {"go_id": "GO:3", "go_term": "c", "n_genes": 10,  "n_genes_with_bmd": 8},   # tiny category
        {"go_id": "GO:4", "go_term": "d", "n_genes": 800, "n_genes_with_bmd": 90},  # too broad
    ]
    return {
        "liver_male": {
            "organ": "liver", "sex": "male",
            "gene_sets_chart_by_stat": {"median": [dict(r) for r in rows]},
            "gene_sets_by_stat": {"median": []},  # overwritten by the filter
        }
    }


class TestApplyGenomicsCutoffs:
    def test_default_cutoffs_keep_passing_rows(self):
        out = apply_genomics_cutoffs(
            _superset(), go_pct=5, go_min_genes=20, go_max_genes=500, go_min_bmd=3)
        kept = [r["go_id"] for r in out["liver_male"]["gene_sets_chart_by_stat"]["median"]]
        # GO:1 (pct40), GO:2 (pct5, ==threshold) pass; GO:3 too few total genes
        # (10 < 20); GO:4 too broad (800 > 500).
        assert kept == ["GO:1", "GO:2"]

    def test_stricter_pct_drops_more(self):
        out = apply_genomics_cutoffs(
            _superset(), go_pct=10, go_min_genes=20, go_max_genes=500, go_min_bmd=3)
        kept = [r["go_id"] for r in out["liver_male"]["gene_sets_chart_by_stat"]["median"]]
        assert kept == ["GO:1"]  # only pct40 clears the 10% bar

    def test_min_bmd_gate(self):
        # go_min_bmd = 41 keeps only rows with >=41 genes-with-bmd: GO:4 (90).
        out = apply_genomics_cutoffs(
            _superset(), go_pct=0, go_min_genes=0, go_max_genes=10**9, go_min_bmd=41)
        kept = [r["go_id"] for r in out["liver_male"]["gene_sets_chart_by_stat"]["median"]]
        assert kept == ["GO:4"]

    def test_top_slice_reranked(self):
        # With everything permissive, gene_sets_by_stat is the top-10 of the chart
        # list, freshly ranked 1..N in the (BMD-sorted) chart order.
        out = apply_genomics_cutoffs(
            _superset(), go_pct=0, go_min_genes=0, go_max_genes=10**9, go_min_bmd=0)
        top = out["liver_male"]["gene_sets_by_stat"]["median"]
        assert [r["rank"] for r in top] == [1, 2, 3, 4]
        # ranks are assigned here, not carried from the cache
        assert all("rank" in r for r in top)

    def test_input_not_mutated(self):
        superset = _superset()
        before = len(superset["liver_male"]["gene_sets_chart_by_stat"]["median"])
        apply_genomics_cutoffs(
            superset, go_pct=50, go_min_genes=0, go_max_genes=10**9, go_min_bmd=0)
        after = len(superset["liver_male"]["gene_sets_chart_by_stat"]["median"])
        assert before == after == 4  # cached superset untouched


class TestGenomicsHashCutoffAgnostic:
    def test_hash_ignores_cutoffs(self):
        # _hash_genomics no longer accepts cutoff args; the same (bmd_stats,
        # ge_filename) always hashes identically → one superset serves every
        # version regardless of its cutoffs.
        a = _hash_genomics(["median"], "ge.bm2")
        b = _hash_genomics(["median"], "ge.bm2")
        assert a == b

    def test_hash_changes_with_stat_or_file(self):
        base = _hash_genomics(["median"], "ge.bm2")
        assert _hash_genomics(["mean"], "ge.bm2") != base
        assert _hash_genomics(["median"], "other.bm2") != base
