"""
Regression test for the mixed-type BMD column bug in interpret.py.

A genomics section's gene list can carry a BMD of the literal string "NaN"
(not the float) for genes that passed the responsiveness prefilter but had a
BMD model failure.  When such a list was turned into a DataFrame, the `bmd`
column stayed object-dtype (float + str), and `analyze()` raised
`TypeError: '<=' not supported between instances of 'float' and 'str'` on
`df["bmd"].min()`.

`build_genomics_interpretation` now coerces `bmd` to numeric before calling
`analyze()`.  These tests pin that: the string "NaN" must become a real float
NaN that min()/max() skip, the genes must NOT be dropped (they belong to the
responsive set used for enrichment), and the whole call must not raise.

The DB (ToxKBQuerier) and the enrichment pipeline (analyze, which makes
network calls) are stubbed so the test is deterministic and offline — it
exercises exactly the coercion this fix added.
"""

import math

import pandas as pd

import interpret
import interpret_analysis
from interpret import AnalysisResult


# A gene list mirroring the real liver_male data that triggered the crash:
# mostly numeric BMDs with a couple of literal-string "NaN" model failures.
_GENE_LIST = [
    {"gene_symbol": "PRLR", "bmd": 1.2, "direction": "up"},
    {"gene_symbol": "ZFP354A", "bmd": 3.4, "direction": "down"},
    {"gene_symbol": "BADMODEL1", "bmd": "NaN", "direction": "up"},
    {"gene_symbol": "BADMODEL2", "bmd": "NaN", "direction": "down"},
]


def test_build_genomics_interpretation_coerces_string_nan_bmd(monkeypatch):
    captured = {}

    # Stub the DB so no duckdb file is opened.
    class _DummyKB:
        def __init__(self, db_path):
            pass

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()
            return False

    # Stub analyze() to capture the DataFrame it receives and run the exact
    # operations that used to raise on a mixed float/str column.
    def _fake_analyze(df, kb, fdr_cutoff=0.05):
        captured["df"] = df
        bmd_min = float(df["bmd"].min())   # crashed pre-fix
        bmd_max = float(df["bmd"].max())   # crashed pre-fix
        return AnalysisResult(
            df=df,
            responsive_genes=list(df["gene_symbol"]),
            bmd_min=bmd_min,
            bmd_max=bmd_max,
            n_up=0,
            n_down=0,
            pw_enriched=[],
            go_enriched=[],
            bmd_ordered=[],
            organ_sig={},
            gene_literature=[],
            top_papers=[],
        )

    monkeypatch.setattr(interpret_analysis, "ToxKBQuerier", _DummyKB)
    monkeypatch.setattr(interpret_analysis, "analyze", _fake_analyze)

    out = interpret.build_genomics_interpretation(
        {"all_genes": _GENE_LIST}, db_path="unused.duckdb",
    )

    df = captured["df"]
    # The bmd column is now numeric, not object-dtype.
    assert pd.api.types.is_numeric_dtype(df["bmd"])
    # The two model-failure genes are KEPT (responsive set must not shrink),
    # their BMDs turned into real float NaN.
    assert len(df) == 4
    assert df["bmd"].isna().sum() == 2
    # min/max are computed over the numeric values, skipping NaN.
    bmd_range = out["analysis_result"]["bmd_range"]
    assert bmd_range == [1.2, 3.4]
    assert out["analysis_result"]["n_responsive"] == 4


def test_min_max_over_all_string_nan_does_not_raise(monkeypatch):
    # Degenerate case: every BMD is the string "NaN".  min()/max() return NaN
    # rather than raising; the call must still succeed gracefully.
    class _DummyKB:
        def __init__(self, db_path):
            pass

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()
            return False

    def _fake_analyze(df, kb, fdr_cutoff=0.05):
        return AnalysisResult(
            df=df,
            responsive_genes=list(df["gene_symbol"]),
            bmd_min=float(df["bmd"].min()),
            bmd_max=float(df["bmd"].max()),
            n_up=0, n_down=0, pw_enriched=[], go_enriched=[], bmd_ordered=[],
            organ_sig={}, gene_literature=[], top_papers=[],
        )

    monkeypatch.setattr(interpret_analysis, "ToxKBQuerier", _DummyKB)
    monkeypatch.setattr(interpret_analysis, "analyze", _fake_analyze)

    out = interpret.build_genomics_interpretation(
        {"all_genes": [
            {"gene_symbol": "A", "bmd": "NaN"},
            {"gene_symbol": "B", "bmd": "NaN"},
        ]},
        db_path="unused.duckdb",
    )
    lo, hi = out["analysis_result"]["bmd_range"]
    assert math.isnan(lo) and math.isnan(hi)
