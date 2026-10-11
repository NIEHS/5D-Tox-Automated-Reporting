"""Unit tests for the bm2↔ToxicR apical-BMD reconcile (tasks #34/#48).

Covers the merge in ``_build_apical_bmd_summary`` — provenance stamping, filling
bm2-blank endpoints from viable ToxicR fits, overlap validation and divergence
collection — and the armed overlap hard-stop in ``_report_bmd_divergences``.
These protect the correctness gate: a genuine bm2↔ToxicR divergence must halt the
run, an agreement must render, and a bm2-usable value must never be silently
overwritten by ToxicR.
"""

import types

import pytest

from pipeline.processing_helpers import _build_apical_bmd_summary, _BMD_DIVERGENCE_TOL


def _row(label, bmd, status, *, bmdl="—", loel=12.0, noel=4.0,
         direction="↓", responsive=True):
    return types.SimpleNamespace(
        label=label, bmd_str=bmd, bmdl_str=bmdl, bmd_status=status,
        loel=loel, noel=noel, direction=direction, responsive=responsive,
        values_by_dose=[0, 4, 12, 37, 111],
    )


def _tables(*rows, platform="Clinical Chemistry", sex="Male"):
    return {platform: {sex: list(rows)}}


# --- the merge (_build_apical_bmd_summary with bmds_results) ---------------

def test_no_toxicr_leaves_summary_byte_identical():
    """No bmds_results → no provenance keys, so the standalone bm2 summary and
    its filter-agnostic cache stay byte-identical to the pre-reconcile build."""
    rows = _build_apical_bmd_summary(_tables(_row("Cholesterol", "100", "viable")))
    assert rows and all("source" not in r and "validated" not in r for r in rows)


def test_provenance_stamped_when_no_overlap():
    rows = _build_apical_bmd_summary(
        _tables(_row("Cholesterol", "100", "viable")),
        bmds_results={}, divergences=[],
    )
    assert rows[0]["source"] == "bm2"
    assert rows[0]["validated"] is None  # nothing to cross-check against


def test_fill_bm2_blank_from_toxicr():
    pt = _tables(_row("Total Triiodothyronine", "—", None), platform="Hormones")
    br = {"Male::Total Triiodothyronine": {
        "bmd": 27.3, "bmdl": 10.8, "status": "viable",
        "model_name": "Exp 3", "bmr_config": "inferred"}}
    r = _build_apical_bmd_summary(pt, bmds_results=br, divergences=[])[0]
    assert r["source"] == "toxicr" and r["filled"] is True
    assert r["bmd"] == "27.3"
    assert r["bmr_config"] == "inferred"  # footnoted in the rendered summary
    assert r["model_name"] == "Exp 3"


def test_toxicr_nonviable_does_not_fill():
    """A blank bm2 endpoint whose ToxicR fit is NOT viable stays bm2/blank."""
    pt = _tables(_row("Total Triiodothyronine", "—", None), platform="Hormones")
    br = {"Male::Total Triiodothyronine": {"bmd": None, "bmdl": None, "status": "NVM"}}
    r = _build_apical_bmd_summary(pt, bmds_results=br, divergences=[])[0]
    assert r["source"] == "bm2" and r.get("filled") is None


def test_overlap_agreement_validated():
    br = {"Male::Cholesterol": {"bmd": 98.0, "bmdl": 55.0, "status": "viable"}}
    div: list = []
    r = _build_apical_bmd_summary(
        _tables(_row("Cholesterol", "100", "viable")),
        bmds_results=br, divergences=div,
    )[0]
    assert r["source"] == "bm2" and r["validated"] is True
    assert r["bmd"] == "100"  # bm2 kept
    assert div == []


def test_overlap_divergence_flagged_without_overwrite():
    br = {"Male::Urea Nitrogen": {"bmd": 62.0, "bmdl": 40.0, "status": "viable"}}
    div: list = []
    r = _build_apical_bmd_summary(
        _tables(_row("Urea Nitrogen", "106", "viable")),
        bmds_results=br, divergences=div,
    )[0]
    assert r["validated"] is False
    assert r["bmd"] == "106"  # NO silent overwrite — bm2 value kept
    assert len(div) == 1
    d = div[0]
    assert d["endpoint"] == "Urea Nitrogen"
    assert d["bm2_bmd"] == 106.0 and d["toxicr_bmd"] == 62.0
    assert d["rel_delta"] > _BMD_DIVERGENCE_TOL


# --- the armed hard-stop (_report_bmd_divergences) ------------------------

_DIVERGENCE = [{
    "endpoint": "Urea Nitrogen", "sex": "Male", "platform": "Clinical Chemistry",
    "bm2_bmd": 106.0, "toxicr_bmd": 62.0, "rel_delta": 0.415,
}]


def test_hard_stop_armed_raises_naming_endpoint(monkeypatch):
    from pipeline import process_integrated as pi
    monkeypatch.setattr(pi, "_BMD_HARD_STOP", True)
    with pytest.raises(pi.BmdDivergenceError) as exc:
        pi._report_bmd_divergences("DTXSID_TEST", _DIVERGENCE)
    msg = str(exc.value)
    assert "Urea Nitrogen" in msg and "106" in msg and "62" in msg


def test_hard_stop_dormant_logs_without_raising(monkeypatch):
    from pipeline import process_integrated as pi
    monkeypatch.setattr(pi, "_BMD_HARD_STOP", False)
    # Must not raise while dormant — divergence is flag-only.
    pi._report_bmd_divergences("DTXSID_TEST", _DIVERGENCE)
