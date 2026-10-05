"""Relative organ weights carry their own NTP statistics.

bmdx-pipe's build_table_data derives "<organ> Relative" endpoints (per-animal
organ / terminal body weight x 1000) and tests them like absolute weights.
Pins the three consumers: the Organ Weight table fills the organ's relative
row from those statistics (instead of an unmarked sidecar computation, and
without listing "Liver Relative" as an organ of its own), the organ-weight
narrative names absolute and relative weights together, and the BMD summary
labels them in the reference's "Absolute/Relative <Organ> Weight" form.
"""

from pathlib import Path

from bmdx_pipe import TableRow

from narrative.unified_narrative import _build_organ_weight_paragraphs
from pipeline.processing_helpers import _summary_endpoint_label
from tables.organ_weight_table import build_organ_weight_table_from_sidecar

_FILES = Path(__file__).resolve().parents[1] / "fixtures/golden/DTXSID50469320/files"


def _row(label, vals, bmd="—", resp=True, trend="**"):
    return TableRow(label=label, values_by_dose=vals, n_by_dose={}, bmd_str=bmd,
                    bmdl_str=bmd, trend_marker=trend, bmd_status=None, loel=4.0,
                    noel=1.4, direction="UP", responsive=resp)


def test_organ_table_relative_row_uses_ntp_statistics():
    stats = {"Male": [
        _row("Liver", {0.0: "10.0 ± 0.2**", 4.0: "12.0 ± 0.3**"}, bmd="2.5"),
        _row("Liver Relative", {0.0: "40.0 ± 0.5**", 4.0: "47.0 ± 0.6**"}, bmd="1.9"),
    ]}
    out = build_organ_weight_table_from_sidecar(
        {"Male": str(_FILES / "organ_weights_truth_male.sidecar.json")}, stats)
    rows = {r["label"]: r for r in out["table_data"]["Male"]}
    assert "Liver Relative Absolute (g)" not in rows
    rel = rows["Liver Relative (mg/g)"]
    assert rel["values"]["0"] == "40.0 ± 0.5**"
    assert rel["values"]["4"] == "47.0 ± 0.6**"
    assert rel["bmd"] == "1.9" and rel["responsive"] and rel["emphasize"]
    assert rel["trend_marker"] == "**"


def test_organ_table_relative_row_without_statistics_stays_display_only():
    stats = {"Male": [_row("Liver", {0.0: "10.0 ± 0.2"}, bmd="2.5")]}
    out = build_organ_weight_table_from_sidecar(
        {"Male": str(_FILES / "organ_weights_truth_male.sidecar.json")}, stats)
    rel = {r["label"]: r for r in out["table_data"]["Male"]}["Liver Relative (mg/g)"]
    assert rel["bmd"] == "ND" and not rel["responsive"]
    assert "*" not in "".join(rel["values"].values())


def test_narrative_pairs_bare_absolute_with_relative():
    rows = [_row("Liver", {0.0: "5.0", 4.0: "9.0**"}, bmd="2.5"),
            _row("Liver Relative", {0.0: "2.0", 4.0: "3.0**"}, bmd="1.9")]
    out = _build_organ_weight_paragraphs({"Organ Weight": {"Male": rows}}, "X", "mg/kg")
    assert "Liver absolute and relative weight" in out[0]
    assert "(absolute weight)" in out[0] and "(relative weight)" in out[0]


def test_summary_labels_keep_laterality_and_weight_kind():
    assert _summary_endpoint_label("Liver", "Organ Weight") == "Absolute Liver Weight"
    assert _summary_endpoint_label("Liver Relative", "Organ Weight") == "Relative Liver Weight"
    assert _summary_endpoint_label("Kidney-Left", "Organ Weight") == "Absolute Left Kidney Weight"
    assert (_summary_endpoint_label("Kidney-Right Relative", "Organ Weight")
            == "Relative Right Kidney Weight")
    assert _summary_endpoint_label("Cholesterol", "Clinical Chemistry") == "Cholesterol"
