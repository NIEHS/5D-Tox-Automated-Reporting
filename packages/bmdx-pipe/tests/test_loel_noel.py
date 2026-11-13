"""LOEL/NOEL as the NIEHS summaries print them.

LOEL is the lowest dose with a significant pairwise difference from control;
NOEL the highest tested dose below it.  When there is no LOEL, or no tested
dose below it, NOEL is not determined (None → "ND") — never the control or the
highest dose (NIEHS-10 summary: female MCH LOEL 0.15 / NOEL ND; erythrocyte
count ND / ND).
"""

from bmdx_pipe.apical_report import build_table_data


def _project(groups: dict[float, list[float]]) -> dict:
    doses, values = [], []
    for d, vals in groups.items():
        doses += [d] * len(vals)
        values += vals
    return {"doseResponseExperiments": [{
        "name": "organ_weights_truth_male",
        "experimentDescription": {"platform": "Organ Weight"},
        "treatments": [{"dose": d} for d in doses],
        "probeResponses": [{"probe": {"id": "Liver"}, "responses": values}],
    }], "bMDResult": []}


def _row(groups):
    return next(r for r in build_table_data(_project(groups), {})["Male"] if r.label == "Liver")


FLAT = [10.0, 10.2, 9.9, 10.1, 10.0]
HIGH = [14.0, 14.3, 13.8, 14.1, 14.2]


def test_noel_is_the_dose_below_the_loel():
    r = _row({0.0: FLAT, 1.0: FLAT, 10.0: HIGH, 100.0: HIGH})
    assert (r.loel, r.noel) == (10.0, 1.0)


def test_noel_not_determined_when_the_lowest_dose_is_the_loel():
    r = _row({0.0: FLAT, 1.0: HIGH, 10.0: HIGH, 100.0: HIGH})
    assert (r.loel, r.noel) == (1.0, None)


def test_neither_determined_without_a_significant_dose():
    r = _row({0.0: FLAT, 1.0: FLAT, 10.0: FLAT, 100.0: FLAT})
    assert (r.loel, r.noel) == (None, None)
