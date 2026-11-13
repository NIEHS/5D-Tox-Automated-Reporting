"""Every BMD in a report prints at one precision (report_bmd_decimals)."""

from bmdx_pipe.apical_report import format_bmd

from genomics.bmdexpress_categories import report_bmd_decimals
from narrative.narrative_helpers import _format_bmd_value, genomics_bmd_decimals
from narrative.report_summary import build_report_summary


def test_format_bmd_fixed_decimals():
    assert format_bmd(437.0, 1) == "437.0"
    assert format_bmd(0.94, 1) == "0.9"
    assert format_bmd(0.034, 1) == "0.034"      # never "0.0"
    assert format_bmd(7.2641, 3) == "7.264"
    assert format_bmd(63.04) == "63"             # legacy 3 significant figures


def test_prose_formatter_passes_markers_through():
    assert _format_bmd_value(36.735, 1) == "36.7"
    assert _format_bmd_value("NVM", 1) == "NVM"
    assert _format_bmd_value(None, 1) == "—"
    assert _format_bmd_value(0.520, None) == "0.52"


def _integ(gene_level: bool):
    exp = {"name": "liver", "experimentDescription": {"dataType": "gene_expression"}}
    cats = [{"name": "liver_curvefit_GENE_x" if gene_level else "liver_curvefit_GO_BP_x",
             "categoryAnalsyisResults": []}]
    return {"doseResponseExperiments": [exp], "categoryAnalysisResults": cats}


def test_report_precision_follows_the_method():
    assert report_bmd_decimals(_integ(gene_level=True)) == 1     # 2025 (NIEHS-12/13)
    assert report_bmd_decimals(_integ(gene_level=False)) == 3    # NIEHS-10
    assert report_bmd_decimals({"doseResponseExperiments": []}) == 1


def test_summary_uses_the_stamped_precision():
    genomics = {"liver_male": {
        "bmd_decimals": 1,
        "gene_sets_by_stat": {"median": [{"go_term": "t", "go_id": "GO:1",
                                          "bmd": 4.2317, "bmdl": 2.1724}]},
        "top_genes": [{"gene_symbol": "Eci1", "bmd": 3.3412, "bmdl": 0.3491}],
    }}
    assert genomics_bmd_decimals(genomics) == 1
    text = " ".join(build_report_summary([], genomics, chemical_name="X",
                                         dose_groups=[0, 7.8], sexes=["Male"]))
    assert "4.2 (2.2) mg/kg" in text and "3.3 (0.3) mg/kg" in text
    assert "4.232" not in text
