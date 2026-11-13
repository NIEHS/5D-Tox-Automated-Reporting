"""bmd_acceptance — the NIEHS defined-category filter on apical BMDs.

The expectations are the published NIEHS-13 (1,4-dichlorobenzene) apical BMD
summaries: rat and mouse, BMR 1 SD, ToxicR Laplace model averaging.
"""

import pytest

from bmdx_pipe.apical_report import _classify_bmd_result
from bmdx_pipe.bmd_acceptance import classify, classify_from_doses, r_squared

RAT_DOSES = [0, 1, 10, 50, 150, 400, 800]
MOUSE_DOSES = [0, 1, 10, 50, 150, 400]


@pytest.mark.parametrize("bmd, bmdl, r2, doses, status", [
    # Published values.
    (191.38, 127.62, 0.9904, RAT_DOSES, "viable"),   # rat liver relative
    (259.76, 93.33, 0.9572, RAT_DOSES, "viable"),    # rat kidney-L absolute (BMDU NaN)
    (15.07, 2.18, 0.8739, MOUSE_DOSES, "viable"),    # mouse A/G ratio, BMDU/BMDL 97
    # Published NVM.
    (339.98, 77.03, 0.5596, RAT_DOSES, "NVM"),       # rat kidney-R relative: R²
    (None, None, 0.5756, RAT_DOSES, "NVM"),          # rat SDH: no BMD
    (60.95, 5.91, 0.8432, MOUSE_DOSES, "NVM"),       # mouse BW gain: BMD/BMDL 10.3
])
def test_niehs13_published_outcomes(bmd, bmdl, r2, doses, status):
    assert classify_from_doses(bmd, bmdl, r2, doses)[0] == status


def test_bmd_above_highest_dose_is_nvm():
    status, reason = classify(900.0, 400.0, 0.9, 1.0, 800.0)
    assert status == "NVM" and "highest dose" in reason


def test_bmd_below_a_third_of_lowest_dose_is_not_reportable():
    assert classify(3.0, 1.0, 0.9, 10.0, 800.0)[0] == "NR"


def test_missing_r2_and_bmdl_are_not_applied():
    assert classify(100.0, None, None, 1.0, 800.0) == ("viable", "")


def test_r_squared_on_group_means():
    assert r_squared([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 1.0
    assert r_squared([1.0, 2.0, 3.0], [2.0, 2.0, 2.0]) == 0.0
    assert r_squared([2.0, 2.0], [2.0, 2.0]) is None


def test_bm2_result_uses_stored_r_squared():
    bsr = {"success": "true", "rSquared": 0.5596}
    assert _classify_bmd_result(339.98, 77.03, 1.0, 800.0, bsr) == "NVM"
    bsr["rSquared"] = 0.85
    assert _classify_bmd_result(219.18, 89.38, 1.0, 800.0, bsr) == "viable"
    assert _classify_bmd_result(219.18, 89.38, 1.0, 800.0, {"success": None}) == "NVM"
    assert _classify_bmd_result(None, None, 1.0, 800.0, None) == "failure"


def test_format_bmd_precision():
    from bmdx_pipe.apical_report import format_bmd
    assert format_bmd(191.376, 1) == "191.4"
    assert format_bmd(0.94, 1) == "0.9"
    assert format_bmd(0.034, 1) == "0.034"
    assert format_bmd(63.04) == "63"


def test_bmd_lookup_resolves_inline_and_referenced_jackson_objects():
    # Jackson writes each object inline on first sight (its id as "@ref") and
    # as the bare id afterwards.  The NIEHS-13 non-genomic project carries BMD
    # results for experiments it does not list — inline inside the bMDResult.
    from bmdx_pipe.apical_report import _build_bmd_result_lookup

    probe = {"@ref": 9, "id": "Liver Weight Relative"}
    listed = {"@ref": 1, "name": "rat", "treatments": [{"dose": d} for d in RAT_DOSES],
              "probeResponses": [{"@ref": 2, "probe": probe}]}
    bsr = {"success": "true", "rSquared": 0.99}
    project = {
        "doseResponseExperiments": [listed],
        "bMDResult": [
            {"doseResponseExperiment": {"@ref": 5, "name": "other", "treatments": [{"dose": 0}, {"dose": 10}],
                                        "probeResponses": [{"@ref": 6, "probe": {"@ref": 7, "id": "SD2"}}]},
             "probeStatResults": [{"probeResponse": 6, "bestBMD": 5.0, "bestBMDL": 2.0, "bestStatResult": bsr}]},
            {"doseResponseExperiment": 1,
             "probeStatResults": [{"probeResponse": 2, "bestBMD": 191.38, "bestBMDL": 127.62,
                                   "bestStatResult": bsr}]},
        ],
    }
    lookup = _build_bmd_result_lookup(project)
    assert lookup[("rat", "Liver Weight Relative")]["status"] == "viable"
    assert lookup[("other", "SD2")]["bmd"] == 5.0
