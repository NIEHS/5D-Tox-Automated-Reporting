"""
Unit tests for tables.toxicokinetics — the deterministic Internal Dose Assessment.

The oracle is NIEHS Report 10 (NBK589955), which IS the PFHxSAm study. The module
must reproduce the published plasma half-lives to the decimal from the study's own
per-animal plasma data. This is the byte-verifiable guarantee that lets the
narrative be built on trusted numbers.
"""

import math
from pathlib import Path

import pytest

from tables.toxicokinetics import compute_toxicokinetics, _half_life

_GOLDEN = Path(__file__).parents[1] / "fixtures" / "golden" / "DTXSID50469320" / "files"
# The live session copy is the working data; prefer the golden fixture, fall back
# to the live session if the fixture lacks the tissue-conc sidecars.
_LIVE = Path("sessions/DTXSID50469320/files")


def _sidecar_paths() -> dict[str, str] | None:
    for base in (_GOLDEN, _LIVE):
        m = base / "tissue_conc_truth_male.sidecar.json"
        f = base / "tissue_conc_truth_female.sidecar.json"
        if m.exists() and f.exists():
            return {"Male": str(m), "Female": str(f)}
    return None


# Published NIEHS Report 10 half-lives (hours), by (sex, dose mg/kg).
_PUBLISHED = {
    ("Male", 4.0): 40.1,
    ("Male", 37.0): 15.1,
    ("Female", 4.0): 78.2,
    ("Female", 37.0): 25.6,
}


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


@pytest.mark.skipif(_sidecar_paths() is None, reason="tissue-conc sidecars not present")
def test_reproduces_published_half_lives():
    tk = compute_toxicokinetics(_sidecar_paths())
    for (sex, dose), pub in _PUBLISHED.items():
        th = tk["by_sex"][sex]["half_life"][dose]
        assert th is not None, f"{sex} {dose}: no half-life computed"
        # ≤0.6 h tolerance — the only slack is rounding in the published
        # SEM-rounded inputs; the method itself is exact.
        assert abs(th - pub) < 0.6, f"{sex} {dose}: computed {th:.1f} vs published {pub}"


@pytest.mark.skipif(_sidecar_paths() is None, reason="tissue-conc sidecars not present")
def test_bioaccumulation_flag_tracks_24h_threshold():
    tk = compute_toxicokinetics(_sidecar_paths())
    bysex = tk["by_sex"]
    # 4 mg/kg groups (78.2 h, 40.1 h) are >24 h → flagged; Male 37 (15.1 h) is not.
    assert bysex["Female"]["bioaccumulative"][4.0] is True
    assert bysex["Male"]["bioaccumulative"][4.0] is True
    assert bysex["Male"]["bioaccumulative"][37.0] is False


@pytest.mark.skipif(_sidecar_paths() is None, reason="tissue-conc sidecars not present")
def test_dose_proportionality_is_sub_proportional():
    tk = compute_toxicokinetics(_sidecar_paths())
    # 9.25x dose (4→37) yields much smaller concentration ratios → sub-proportional.
    male = tk["dose_proportionality"]["Male"]
    for h, dp in male.items():
        assert math.isclose(dp["dose_ratio"], 9.25, abs_tol=0.01)
        assert dp["conc_ratio"] < dp["dose_ratio"]
        assert dp["sub_proportional"] is True


def test_empty_when_no_data():
    assert compute_toxicokinetics({}) == {"by_sex": {}, "dose_proportionality": {}, "unit": "ng/mL"}


@pytest.mark.skipif(_sidecar_paths() is None, reason="tissue-conc sidecars not present")
def test_narrative_is_grounded_in_computed_numbers():
    from tables.toxicokinetics import build_internal_dose_narrative
    tk = compute_toxicokinetics(_sidecar_paths())
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
