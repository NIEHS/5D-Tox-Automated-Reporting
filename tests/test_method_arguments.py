"""The method is the caller's (ADR-0027): settings arrive as arguments.

rlm-bmdx resolves them from the study's method profile; the defaults are the
NTP procedure and the NIEHS-12/13 acceptance filter, unchanged."""

from bmdx_pipe import bmd_acceptance
from bmdx_pipe.ntp_stats import DEFAULT_METHOD, NONPARAMETRIC, PARAMETRIC, StatsMethod, ntp_pairwise

GROUPS = {0: [10.0, 10.5, 9.8, 10.2, 10.1], 10: [10.9, 11.3, 11.0, 11.4, 11.2],
          30: [12.1, 12.5, 12.0, 12.6, 12.3]}


def test_defaults_are_the_ntp_procedure():
    assert DEFAULT_METHOD.family("Organ Weight") == PARAMETRIC
    assert DEFAULT_METHOD.family("Hematology") == NONPARAMETRIC
    assert DEFAULT_METHOD.marker(0.004) == "**" and DEFAULT_METHOD.marker(0.03) == "*"
    assert ntp_pairwise(GROUPS, PARAMETRIC).method == "williams"


def test_trend_selection_and_family_come_from_the_method():
    never_trend = StatsMethod(trend_select_p=0.0)
    assert ntp_pairwise(GROUPS, PARAMETRIC, method=never_trend).method == "dunnett"
    custom = StatsMethod(families=(("Organ Weight", NONPARAMETRIC),))
    assert custom.family("Organ Weight") == NONPARAMETRIC and custom.family("Body Weight") is None


def test_min_group_n_from_the_method():
    groups = {0: [1.0, 1.1, 0.9], 5: [2.0, 2.1]}
    assert ntp_pairwise(groups, PARAMETRIC).pairwise_p                       # n = 2 tested
    assert not ntp_pairwise(groups, PARAMETRIC, method=StatsMethod(min_group_n=3)).pairwise_p


def test_acceptance_criteria_from_the_caller():
    assert bmd_acceptance.classify(50, 20, 0.55, 10, 100)[0] == "NVM"           # R² < 0.6
    loose = bmd_acceptance.Criteria(r2_min=0.5)
    assert bmd_acceptance.classify(50, 20, 0.55, 10, 100, loose)[0] == "viable"
    no_cap = bmd_acceptance.Criteria(max_dose=False)
    assert bmd_acceptance.classify(150, 100, 0.9, 10, 100)[0] == "NVM"
    assert bmd_acceptance.classify(150, 100, 0.9, 10, 100, no_cap)[0] == "viable"
