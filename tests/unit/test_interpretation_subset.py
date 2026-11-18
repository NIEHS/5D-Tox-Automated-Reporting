"""Enrichment of a ranked subset is not presented as enrichment of the
responsive set (independent review, 2026-11-16)."""

from unittest import mock

import narrative.interpret_analysis as ia


class _KB:
    def __init__(self, *a):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _run(section):
    seen = {}

    def fake_analyze(df, kb, fdr_cutoff, enrichment_withheld=""):
        seen["withheld"] = enrichment_withheld
        seen["genes"] = list(df["gene_symbol"])
        raise StopIteration      # stop after the call: what reached analyze is what is tested

    with mock.patch.object(ia, "ToxKBQuerier", _KB), \
         mock.patch.object(ia, "analyze", fake_analyze):
        try:
            ia.build_genomics_interpretation(section, "kb.duckdb")
        except StopIteration:
            pass
    return seen


def test_without_all_genes_enrichment_is_withheld():
    top = [{"gene_symbol": "Cyp1a1", "bmd": 1.0}, {"gene_symbol": "Nqo1", "bmd": 2.0}]
    seen = _run({"top_genes": top})
    assert seen["genes"] == ["Cyp1a1", "Nqo1"] and "not available" in seen["withheld"]
    seen = _run({"top_genes": top, "all_genes": top + [{"gene_symbol": "Gstm1", "bmd": 3.0}]})
    assert len(seen["genes"]) == 3 and seen["withheld"] == ""


def test_the_context_says_the_genes_are_a_subset():
    import pandas as pd
    r = ia.AnalysisResult(df=pd.DataFrame(), responsive_genes=["a", "b"], bmd_min=1, bmd_max=2,
                          n_up=0, n_down=0, pw_enriched=[], go_enriched=[], bmd_ordered=[],
                          organ_sig={}, gene_literature=[], top_papers=[],
                          enrichment_withheld="only its top genes")
    text = ia.format_context_text(r)
    assert "a ranked subset, not the complete responsive set" in text
    assert text.count("Not computed: only its top genes") == 2
