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

Driven over the given-PFHxSAm regression fixture in the sibling rlm-bmdx repo.
"""

import uuid
from pathlib import Path

import pytest

from bmdx_pipe.file_integrator import (
    classify_derived_by_anchor,
    detect_platform_and_type,
    fingerprint_file,
    validate_pool,
)

# The fixture lives in the sibling repo; skip cleanly if it's absent.
_GOLDEN = Path("/workspace/rlm-bmdx/tests/fixtures/regression/given-pfhxsam-2026/files")
pytestmark = pytest.mark.skipif(
    not _GOLDEN.exists(), reason="rlm-bmdx given-PFHxSAm regression fixture not present"
)


# ---------------------------------------------------------------------------
# 1. detect_platform_and_type — the FILENAME classifier (pins the bug).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename,ext,expected", [
    # detect_platform_and_type is the PURE FILENAME classifier and is UNCHANGED by
    # ADR-0017: on the bare name (no content), a study xlsx still reads 'inferred'
    # for lack of a _truth token. The ADR-0017 fix is an OVERRIDE in fingerprint_xlsx
    # (when is_study_file, data_type → 'tox_study' from the Key+Data sheets) — see
    # test_study_xlsx_classifies_tox_study_by_content below. So this pins that the
    # filename classifier itself did NOT change.
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


def test_golden_pool_has_no_dose_mismatch_errors_after_adr0017():
    """★ ADR-0017 increment 1: the bug is FIXED at its root. Before, the golden
    pool produced 4 spurious dose_mismatch errors (raw xlsx mislabeled `inferred`,
    compared against the genuinely-inferred short txt). Now the study xlsx
    classifies `tox_study` from its Key+Data content, so the dose check's
    cross-dataType exemption engages and the count is 0. (Was: assert len == 4.)"""
    fps = _fingerprint_all(_GOLDEN)
    report = validate_pool("DTXSID50469320", fps)

    errors = [i for i in report.issues if i.get("severity") == "error"]
    dose = [i for i in errors if i.get("issue_type") == "dose_mismatch"]

    assert len(dose) == 0, (
        f"expected 0 dose_mismatch errors (ADR-0017 fix), got {len(dose)}: "
        f"{[i.get('message') for i in dose]}"
    )


def test_study_xlsx_classifies_tox_study_by_content():
    """★ ADR-0017 increment 1: a study-file xlsx is `tox_study` from its OWN
    content (Key+Data sheet structure = is_study_file), regardless of its filename
    lacking a `_truth` token. This is the override in fingerprint_xlsx."""
    fps = _fingerprint_all(_GOLDEN)
    xlsx = [fp for fp in fps.values() if fp.file_type == "xlsx" and fp.is_study_file]
    assert xlsx, "expected study xlsx in the golden pool"
    for fp in xlsx:
        assert fp.data_type == "tox_study", (
            f"{fp.filename} is a study file but data_type={fp.data_type!r} "
            f"(ADR-0017: study xlsx → tox_study by content)"
        )


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


# ---------------------------------------------------------------------------
# ADR-0017 Increment D — content-anchored dataType classification
# ---------------------------------------------------------------------------


def _by_name(fps: dict) -> dict:
    """Re-key fingerprints by filename for readable assertions."""
    return {fp.filename: fp for fp in fps.values()}


def test_D_classifier_is_noop_on_correctly_labeled_golden():
    """On the golden pool every derived file is already correctly labeled
    (increment 1 + filename), so the anchor classifier must change NOTHING —
    it only overrides when content PROVES loss, and here it never contradicts."""
    fps = _fingerprint_all(_GOLDEN)
    before = {fid: fp.data_type for fid, fp in fps.items()}
    classify_derived_by_anchor(fps)
    after = {fid: fp.data_type for fid, fp in fps.items()}
    changed = {fid: (before[fid], after[fid]) for fid in before if before[fid] != after[fid]}
    assert changed == {}, f"classifier changed labels on golden: {changed}"


def test_D_detects_dropped_dose_as_inferred():
    """The dropped-dose platforms (Body/Organ Weight, where 333/1000 mg/kg died
    out) are content-proven `inferred`; nothing-dropped platforms are ambiguous
    and keep their prior label."""
    fps = _fingerprint_all(_GOLDEN)
    decisions = classify_derived_by_anchor(fps)
    named = {fps[fid].filename: reason for fid, (dt, reason) in decisions.items()}
    # Dropped-dose files → provable_loss
    for f in ("male_body_weight.txt", "female_body_weight.txt",
              "male_organ_weights.txt", "female_organ_weights.txt"):
        assert named.get(f) == "provable_loss", f"{f}: {named.get(f)}"
    # No-death platforms → ambiguous (kept)
    for f in ("male_hormone_data.txt", "male_clin_chem.txt"):
        assert named.get(f) == "ambiguous_keep_prior", f"{f}: {named.get(f)}"


def test_D_recovers_inferred_from_content_when_filename_lies():
    """★ The ADR-0017 goal: classification independent of filename. A dropped-dose
    file mislabeled `tox_study` (as a non-NIEHS filename would) is recovered to
    `inferred` from its dose-group content."""
    fps = _fingerprint_all(_GOLDEN)
    named = _by_name(fps)
    named["male_organ_weights.txt"].data_type = "tox_study"  # poison the label
    classify_derived_by_anchor(fps)
    assert named["male_organ_weights.txt"].data_type == "inferred"


def test_D_does_not_override_ambiguous_label():
    """Restraint: an ambiguous file (same dose-group set as the anchor) keeps
    whatever label it had — content cannot override what content cannot prove."""
    fps = _fingerprint_all(_GOLDEN)
    named = _by_name(fps)
    # Hormones has no deaths → ambiguous. Poison BOTH directions; both must stand.
    named["male_hormone_data.txt"].data_type = "tox_study"
    named["hormones_truth_male.txt"].data_type = "inferred"
    classify_derived_by_anchor(fps)
    assert named["male_hormone_data.txt"].data_type == "tox_study"
    assert named["hormones_truth_male.txt"].data_type == "inferred"


def test_D_does_not_touch_gene_expression_or_bm2():
    """Gene-expression txt and every bm2 are outside the apical-roster model and
    must never be reclassified by the anchor comparison."""
    fps = _fingerprint_all(_GOLDEN)
    before = {fid: fp.data_type for fid, fp in fps.items()
              if fp.data_type == "gene_expression" or fp.file_type == "bm2"}
    assert before, "expected gene_expression / bm2 files in the golden pool"
    classify_derived_by_anchor(fps)
    for fid, dt in before.items():
        assert fps[fid].data_type == dt, f"{fps[fid].filename} was reclassified"


def test_D_no_anchor_means_no_change():
    """With no study-xlsx anchor in the pool, the classifier is inert — the
    filename label remains the fallback."""
    fps = _fingerprint_all(_GOLDEN)
    # Drop every study xlsx anchor.
    fps = {fid: fp for fid, fp in fps.items()
           if not (fp.file_type == "xlsx" and fp.is_study_file)}
    before = {fid: fp.data_type for fid, fp in fps.items()}
    decisions = classify_derived_by_anchor(fps)
    assert decisions == {}, "classifier acted despite no anchor"
    assert {fid: fp.data_type for fid, fp in fps.items()} == before
