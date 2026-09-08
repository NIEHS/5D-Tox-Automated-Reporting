"""
Characterization net for file classification + pool cross-validation.

bmdx-pipe had NO tests. Before the ADR-0017 content/provenance-classification
refactor (and the bmdx-pipe seam re-cut it motivates), this pins the CURRENT
behavior of the classifier and the dose-group cross-check — INCLUDING the known
bug — so the refactor's diff is exactly the intended change and nothing else.

The load-bearing case is the xlsx misclassification: a NIEHS-native
`*_Organ_Weight_Data.xlsx` (raw study-team source of truth) is labeled `inferred`
by the filename regex because its name lacks a `_truth`/`_tox_study` token, and is
then compared as an `inferred` file against a genuinely-inferred pivoted txt whose
top dose groups died out — producing a spurious dose_mismatch ERROR. ADR-0017 will
make the xlsx classify as `tox_study` (from its own "Key to Column Labels" content),
at which point THESE expected values change in a controlled, reviewable way.

Driven over the real golden fixture in the sibling rlm-bmdx repo.
"""

import os
import uuid
from pathlib import Path

import pytest

from bmdx_pipe.file_integrator import (
    detect_platform_and_type,
    fingerprint_file,
    validate_pool,
)

# The golden fixture lives in the sibling repo; skip cleanly if it's absent.
_GOLDEN = Path("/workspace/rlm-bmdx/tests/fixtures/golden/DTXSID50469320/files")
pytestmark = pytest.mark.skipif(
    not _GOLDEN.exists(), reason="rlm-bmdx golden fixture not present"
)


# ---------------------------------------------------------------------------
# 1. detect_platform_and_type — the FILENAME classifier (pins the bug).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename,ext,expected", [
    # ★ THE BUG: raw study-team xlsx, no _truth token → mislabeled 'inferred'.
    # ADR-0017 flips this to ('Organ Weight', 'tox_study') from Key-tab content.
    ("C20022-01_Individual_Animal_Organ_Weight_Data.xlsx", "xlsx",
     ("Organ Weight", "inferred")),
    ("C20022-01_Individual_Animal_Body_Weight_Data.xlsx", "xlsx",
     ("Body Weight", "inferred")),
    # A _truth-suffixed file classifies tox_study (the token IS present).
    ("organ_weights_truth_male.txt", "txt", ("Organ Weight", "tox_study")),
    ("body_weight_truth_female.txt", "txt", ("Body Weight", "tox_study")),
    # A plain (no-token) txt → inferred.
    ("male_organ_weights.txt", "txt", ("Organ Weight", "inferred")),
    ("female_body_weight.txt", "txt", ("Body Weight", "inferred")),
])
def test_detect_platform_and_type_current_behavior(filename, ext, expected):
    assert detect_platform_and_type(filename, ext) == expected


def test_gene_expression_heuristic_needs_size():
    # Organ-prefixed name is only gene_expression when >100KB (else unrecognized).
    small = detect_platform_and_type("Liver_PFHxSAm_Male_No0.txt", "txt", file_size=1000)
    big = detect_platform_and_type("Liver_PFHxSAm_Male_No0.txt", "txt", file_size=500_000)
    assert small == (None, None)
    assert big == (None, "gene_expression")


# ---------------------------------------------------------------------------
# 2. validate_pool end-to-end — pins the 4 spurious dose_mismatch ERRORS.
# ---------------------------------------------------------------------------

def _fingerprint_all(files_dir: Path):
    fps = {}
    for p in sorted(files_dir.iterdir()):
        if not p.is_file() or p.name.endswith(".sidecar.json"):
            continue
        ext = p.suffix.lstrip(".").lower()
        if ext not in ("xlsx", "txt", "csv", "bm2"):
            continue
        fid = str(uuid.uuid4())
        try:
            fp = fingerprint_file(fid, p.name, str(p), ext,
                                  ts_added="2026-01-01T00:00:00+00:00")
        except Exception:
            continue
        fps[fid] = fp
    return fps


def test_golden_pool_produces_four_dose_mismatch_errors():
    """The observed live-app behavior: exactly 4 dose_mismatch errors, all
    xlsx-vs-short-txt within an Organ/Body Weight domain. Post-ADR-0017 this count
    should drop to 0 (the xlsx becomes tox_study, so the dose check exempts the
    cross-dataType pair). Pinned so that change is explicit."""
    fps = _fingerprint_all(_GOLDEN)
    report = validate_pool("DTXSID50469320", fps)

    errors = [i for i in report.issues if i.get("severity") == "error"]
    dose = [i for i in errors if i.get("issue_type") == "dose_mismatch"]

    assert len(dose) == 4, (
        f"expected 4 dose_mismatch errors (the bug), got {len(dose)}: "
        f"{[i.get('message') for i in dose]}"
    )
    # The `platform` field is the compound Platform|dataType key, and both sides
    # are `|inferred` — THAT is the bug (the raw xlsx mislabeled inferred, so it
    # is compared against the genuinely-inferred short txt as if they must match).
    platforms = sorted({i.get("platform") for i in dose})
    assert platforms == ["Body Weight|inferred", "Organ Weight|inferred"]


def test_dose_check_exempts_cross_datatype_pairs():
    """The EXEMPTION is already correct — a tox_study file legitimately has more
    dose groups than its inferred projection, and the check must not flag that.
    This is why ADR-0017 (fixing the xlsx label) resolves the bug WITHOUT touching
    the dose check: pin that same-domain tox_study vs inferred does NOT error."""
    from bmdx_pipe.file_integrator import _check_dose_consistency, _build_coverage_matrix

    fps = _fingerprint_all(_GOLDEN)
    matrix = _build_coverage_matrix(fps)
    # Find any domain that has both a tox_study and an inferred file and assert
    # the check produced no dose_mismatch BETWEEN those two datatypes.
    # (Structural: the exemption lives in _check_dose_consistency' data_type guard.)
    for domain, tiers in matrix.items():
        issues = _check_dose_consistency(domain, tiers, fps)
        for iss in issues:
            involved = [fps[f] for f in iss.files_involved if f in fps]
            dtypes = {fp.data_type for fp in involved}
            assert not (dtypes == {"tox_study", "inferred"}), (
                f"cross-datatype pair wrongly flagged in {domain}: {iss.message}"
            )
