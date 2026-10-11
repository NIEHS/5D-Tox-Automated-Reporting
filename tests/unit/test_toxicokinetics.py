"""
Unit tests for tables.toxicokinetics — the deterministic Internal Dose Assessment.

The oracle is NIEHS Report 10 (NBK589955), which IS the PFHxSAm study. The module
must reproduce the published plasma half-lives to the decimal from the study's own
per-animal plasma data. This is the byte-verifiable guarantee that lets the
narrative be built on trusted numbers.
"""

import json
import math

import pytest

from tables.toxicokinetics import compute_toxicokinetics, _half_life
from tests.conftest import REFERENCE_DIR

# Published NIEHS Report 10 half-lives (hours), by (sex, dose mg/kg) — the
# report text (p. 30), carried in the reference fixture.
_PUBLISHED = {
    (sex, float(dose)): hl
    for sex, by_dose in json.loads(
        (REFERENCE_DIR / "NIEHS-10" / "report_values.json").read_text()
    )["plasma_half_life_hours"].items()
    for dose, hl in by_dose.items()
}


@pytest.fixture
def plasma_sidecars(reference_session):
    """NIEHS-10's plasma sidecars, ingested from the published CEBS workbook."""
    from tables.table_builder_common import find_sidecar_paths
    session = reference_session("NIEHS-10", "DTXSID50469320")
    return find_sidecar_paths(str(session), "Tissue Concentration")


def test_half_life_formula_matches_first_order():
    # ke = ln(C1/C2)/dt ; t_half = ln2/ke. Hand-check one cell.
    ke, th = _half_life(33.8, 23.1, 22.0)  # Male 4 mg/kg
    assert math.isclose(ke, math.log(33.8 / 23.1) / 22.0)
    assert math.isclose(th, 40.1, abs_tol=0.1)


def test_half_life_none_when_not_declining():
    # No elimination observed (late >= early) → cannot estimate.
    assert _half_life(20.0, 25.0, 22.0) is None
    assert _half_life(0.0, 10.0, 22.0) is None
    assert _half_life(30.0, 20.0, 0.0) is None


def test_reproduces_published_half_lives(plasma_sidecars):
    tk = compute_toxicokinetics(plasma_sidecars)
    assert tk["unit"] == "µg/mL"  # the CEBS Key sheet's "ug/ml"
    for (sex, dose), pub in _PUBLISHED.items():
        th = tk["by_sex"][sex]["half_life"][dose]
        assert th is not None, f"{sex} {dose}: no half-life computed"
        # Exact at the published precision (one decimal), from the CEBS workbook.
        assert round(th, 1) == pub, f"{sex} {dose}: computed {th:.3f} vs published {pub}"


def test_bioaccumulation_flag_tracks_24h_threshold(plasma_sidecars):
    tk = compute_toxicokinetics(plasma_sidecars)
    bysex = tk["by_sex"]
    # 4 mg/kg groups (78.2 h, 40.1 h) are >24 h → flagged; Male 37 (15.1 h) is not.
    assert bysex["Female"]["bioaccumulative"][4.0] is True
    assert bysex["Male"]["bioaccumulative"][4.0] is True
    assert bysex["Male"]["bioaccumulative"][37.0] is False


def test_dose_proportionality_is_sub_proportional(plasma_sidecars):
    tk = compute_toxicokinetics(plasma_sidecars)
    # 9.25x dose (4→37) yields much smaller concentration ratios → sub-proportional.
    male = tk["dose_proportionality"]["Male"]
    for h, dp in male.items():
        assert math.isclose(dp["dose_ratio"], 9.25, abs_tol=0.01)
        assert dp["conc_ratio"] < dp["dose_ratio"]
        assert dp["sub_proportional"] is True


def test_empty_when_no_data():
    # No data, no unit — never a default.
    assert compute_toxicokinetics({}) == {"by_sex": {}, "dose_proportionality": {}, "unit": None}


def test_narrative_is_grounded_in_computed_numbers(plasma_sidecars):
    from tables.toxicokinetics import build_internal_dose_narrative
    tk = compute_toxicokinetics(plasma_sidecars)
    paras = build_internal_dose_narrative(tk, "PFHxSAm", "mg/kg")
    text = " ".join(paras).lower()
    assert len(paras) >= 3
    # The published half-lives appear verbatim (prose derives from the numbers).
    assert "78.2" in text and "40.1" in text and "15.1" in text
    # The reference interpretive frame is present.
    assert "sub" in text or "less than proportionally" in text
    assert "absorption, distribution, metabolism" in text
    assert "clearance" in text
    # Sex difference read (females higher in this study).
    assert "female" in text and "higher" in text


def test_narrative_empty_when_no_tk():
    from tables.toxicokinetics import build_internal_dose_narrative
    assert build_internal_dose_narrative({"by_sex": {}}, "X") == []
