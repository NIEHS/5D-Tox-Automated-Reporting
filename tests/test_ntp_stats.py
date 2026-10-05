"""ntp_stats: the NTP trend/pairwise procedure (Jonckheere selects Williams or
Dunnett for weights, Shirley or Dunn for clinical pathology), and its use in
build_table_data, including the derived relative organ weights."""

import math

import numpy as np
import pytest

from bmdx_pipe import ntp_stats
from bmdx_pipe.apical_report import build_table_data


def _groups(means, n=5, sd=1.0, seed=0):
    """{dose: values} with fixed noise, control first (dose 0)."""
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal((len(means), n)) * sd
    doses = [0.0, 1.0, 3.0, 10.0, 30.0, 100.0][: len(means)]  # 5 means: top dose 30
    return {d: list(m + noise[i]) for i, (d, m) in enumerate(zip(doses, means))}


# Williams (1971) Table 1, df = infinity, equal replication, one-sided alpha 0.05.
@pytest.mark.parametrize("k, critical", [(1, 1.645), (2, 1.716), (3, 1.739),
                                         (4, 1.750), (5, 1.756)])
def test_williams_null_reproduces_published_critical_values(k, critical):
    null = ntp_stats._williams_null((10,) * (k + 1), math.inf)
    assert np.quantile(null, 0.95) == pytest.approx(critical, abs=0.012)


def test_dunnett_p_is_monotone_in_effect_size():
    # The Java DunnettsTest this replaces returned p ~ 0.44 at 8 SD.
    ps = []
    for effect in (2, 4, 8, 12):
        g = _groups([0, 0, 0, effect], n=5, seed=1)
        ps.append(ntp_stats.dunnett([np.asarray(g[d]) for d in sorted(g)])[3])
    assert ps == sorted(ps, reverse=True)
    assert ps[-1] < 1e-4


def test_strong_trend_selects_williams_and_steps_down():
    res = ntp_stats.ntp_pairwise(_groups([10, 10, 10.5, 13, 16]), ntp_stats.PARAMETRIC)
    assert res.direction == "UP" and res.jonckheere_p <= 0.01
    assert res.method == "williams"
    assert res.pairwise_p[30.0] <= 0.01 and res.pairwise_p[10.0] <= 0.05
    # Step-down stops at the first non-significant dose; lower doses get 1.0.
    assert res.pairwise_p[1.0] == 1.0


def test_no_trend_selects_dunnett_or_dunn():
    flat = _groups([10, 10, 10, 10], seed=3)
    assert ntp_stats.ntp_pairwise(flat, ntp_stats.PARAMETRIC).method == "dunnett"
    assert ntp_stats.ntp_pairwise(flat, ntp_stats.NONPARAMETRIC).method == "dunn"


def test_nonparametric_trend_selects_shirley_downward():
    res = ntp_stats.ntp_pairwise(_groups([20, 19.5, 17, 14, 11]), ntp_stats.NONPARAMETRIC)
    assert res.direction == "DOWN" and res.method == "shirley"
    assert res.pairwise_p[30.0] <= 0.05


def test_empty_dose_group_is_left_out():
    g = _groups([10, 11, 13, 16])
    g[10.0] = []
    res = ntp_stats.ntp_pairwise(g, ntp_stats.PARAMETRIC)
    assert 10.0 not in res.pairwise_p and res.method != "none"


def test_platform_family():
    assert ntp_stats.family_for_platform("Organ Weight") == ntp_stats.PARAMETRIC
    assert ntp_stats.family_for_platform("Clinical Chemistry") == ntp_stats.NONPARAMETRIC
    assert ntp_stats.family_for_platform("S1500+_rat") is None


def _organ_experiment():
    doses = [0.0] * 5 + [10.0] * 5 + [100.0] * 5
    rng = np.random.default_rng(7)
    tbw = [250 + rng.standard_normal() for _ in doses]
    # Liver rises with dose, body weight does not: relative weight rises too.
    liver = [8 + (0.0 if d == 0 else 0.5 if d == 10 else 3.0) + 0.2 * rng.standard_normal()
             for d in doses]
    liver[3] = None  # a missing organ weight stays missing in the relative weight
    return {
        "name": "organ_weights_truth_male",
        "experimentDescription": {"platform": "Organ Weight"},
        "treatments": [{"dose": d} for d in doses],
        "probeResponses": [
            {"probe": {"id": "Liver"}, "responses": liver},
            {"probe": {"id": "Terminal Body Weight"}, "responses": tbw},
        ],
    }, liver, tbw


def test_build_table_data_derives_relative_organ_weights():
    exp, liver, tbw = _organ_experiment()
    rows = {r.label: r for r in build_table_data({"doseResponseExperiments": [exp]}, {})["Male"]}
    assert set(rows) == {"Liver", "Terminal Body Weight", "Liver Relative"}
    rel = rows["Liver Relative"]
    assert rel.pairwise_method == "williams" and rel.responsive
    assert rel.loel in (10.0, 100.0)
    assert rel.n_by_dose[0.0] == 4
    expected = [o / t * 1000 for o, t in zip(liver, tbw) if o is not None]
    assert rel._bmds_input["Y"] == pytest.approx(expected)
    assert rows["Liver"].pairwise_method == "williams"


def test_single_animal_group_is_left_out_of_the_tests():
    # A lone survivor at the top dose must not stop Williams' step-down.
    g = _groups([10, 10.5, 13, 16])
    g[30.0] = [10.0]
    res = ntp_stats.ntp_pairwise(g, ntp_stats.PARAMETRIC)
    assert 30.0 not in res.pairwise_p
    assert res.method == "williams" and res.pairwise_p[10.0] <= 0.01
