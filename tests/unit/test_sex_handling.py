"""Sex handling for single-sex and sexless studies.

- The BMDProject schema maps BMDExpress's "not a single sex" vocabulary values
  (both / mixed / NA) to None — rlm-bmdx's sexless representation — while still
  rejecting genuinely unknown values.
- The animal-condition narrative names the study's ACTUAL sexes rather than a
  hardcoded "male and female".
"""

import pytest

from narrative.unified_narrative import _mortality_sex_subject
from pipeline.bmd_project_schema import ExperimentDescription


@pytest.mark.parametrize("raw", ["both", "Both", "mixed", "NA", ""])
def test_not_single_sex_values_normalize_to_none(raw):
    assert ExperimentDescription(sex=raw).sex is None


@pytest.mark.parametrize("raw", ["male", "female"])
def test_single_sex_values_pass_through(raw):
    assert ExperimentDescription(sex=raw).sex == raw


def test_unknown_sex_value_still_rejected():
    with pytest.raises(Exception):
        ExperimentDescription(sex="hermaphrodite")


def _mortality(*sexes):
    return {"by_dose": {0.0: {s: {"total": 4, "early_deaths": 0} for s in sexes}}}


@pytest.mark.parametrize("sexes, expected", [
    (("Male", "Female"), "male and female rats"),
    (("Male",), "male rats"),
    (("Female",), "female rats"),
    ((), "rats"),
])
def test_mortality_sex_subject(sexes, expected):
    assert _mortality_sex_subject(_mortality(*sexes)) == expected
