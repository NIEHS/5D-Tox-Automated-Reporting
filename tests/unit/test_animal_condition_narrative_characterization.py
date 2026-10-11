"""
Characterization gate for _build_animal_condition_paragraphs (Phase 2 decomposition).

Pins the EXACT current prose output across every branch BEFORE the builder is
rewritten to a template+render form. Captured from the live builder on 2026-09-02.

Branches covered: no mortality data (empty), the all-survived brief statement, the
full mortality paragraph with clinical signs, the same without signs, and the edge
case where there is no earliest-death day / no latest-day clause / no surviving
sentence.

Revised 2026-10-06: the signs sentence states the clinical observations' onset day
(IncidenceRow.onset_day_by_dose) and the findings seen in the groups with deaths,
never the first death day; with no clinical observations recorded (None) nothing
is said about signs either way (no sentence fragment, no "did not exhibit signs").
"""

from bmdx_pipe.clinical_observations import IncidenceRow

from narrative.unified_narrative import _build_animal_condition_paragraphs


UNIT = "mg/kg"
CN = "PFHxSAm"

_MORT_ALL_SURVIVED = {
    "expected_terminal_day": "SD5",
    "by_dose": {
        0.0: {"Male": {"total": 5, "early_deaths": 0, "death_days": {}},
              "Female": {"total": 5, "early_deaths": 0, "death_days": {}}},
        50.0: {"Male": {"total": 5, "early_deaths": 0, "death_days": {}},
               "Female": {"total": 5, "early_deaths": 0, "death_days": {}}},
    },
    "all_survived_doses": [0.0, 50.0],
}

_MORT_FULL = {
    "expected_terminal_day": "SD5",
    "by_dose": {
        0.0: {"Male": {"total": 5, "early_deaths": 0, "death_days": {}},
              "Female": {"total": 5, "early_deaths": 0, "death_days": {}}},
        50.0: {"Male": {"total": 5, "early_deaths": 0, "death_days": {}},
               "Female": {"total": 5, "early_deaths": 0, "death_days": {}}},
        333.0: {"Male": {"total": 5, "early_deaths": 3, "death_days": {"SD0": 1, "SD1": 2}},
                "Female": {"total": 5, "early_deaths": 1, "death_days": {"SD2": 1}}},
        1000.0: {"Male": {"total": 5, "early_deaths": 5, "death_days": {"SD0": 5}},
                 "Female": {"total": 5, "early_deaths": 5, "death_days": {"SD0": 5}}},
    },
    "all_survived_doses": [0.0, 50.0],
}

_SIGNS = {
    "Male": [IncidenceRow(label="Discharge — Eye, Bilateral, Red",
                          incidence_by_dose={0.0: "0/5", 50.0: "0/5", 333.0: "2/5", 1000.0: "4/5"},
                          onset_day_by_dose={333.0: 1, 1000.0: 0}),
             IncidenceRow(label="Lethargy",
                          incidence_by_dose={0.0: "0/5", 50.0: "0/5", 333.0: "0/5", 1000.0: "3/5"},
                          onset_day_by_dose={1000.0: 0})],
    "Female": [IncidenceRow(label="Discharge — Eye, Bilateral, Red",
                            incidence_by_dose={0.0: "0/5", 50.0: "0/5", 333.0: "0/5", 1000.0: "2/5"},
                            onset_day_by_dose={1000.0: 0})],
}

_MORT_EDGE = {
    "expected_terminal_day": "SD5",
    "by_dose": {
        0.0: {"Male": {"total": 5, "early_deaths": 0, "death_days": {}},
              "Female": {"total": 5, "early_deaths": 0, "death_days": {}}},
        1000.0: {"Male": {"total": 5, "early_deaths": 2, "death_days": {}},
                 "Female": {"total": 5, "early_deaths": 0, "death_days": {}}},
    },
    "all_survived_doses": [0.0],
}


def test_no_mortality_data_returns_empty():
    assert _build_animal_condition_paragraphs(CN, UNIT, {}, None) == []


def test_all_survived_brief_statement():
    # Clinical observations recorded, all normal.
    out = _build_animal_condition_paragraphs(CN, UNIT, _MORT_ALL_SURVIVED, {})
    assert out == [
        "All male and female rats survived to study termination (SD5) without "
        "signs of overt toxicity."
    ]
    # None recorded: survival only.
    assert _build_animal_condition_paragraphs(CN, UNIT, _MORT_ALL_SURVIVED, None) == [
        "All male and female rats survived to study termination (SD5)."
    ]


def test_full_mortality_with_clinical_signs():
    out = _build_animal_condition_paragraphs(CN, UNIT, _MORT_FULL, _SIGNS)
    assert out == [
        "Male and female rats administered 333 and 1000 mg/kg of PFHxSAm began "
        "exhibiting signs of overt toxicity on study day 0, which included "
        "discharge — eye, bilateral, red and lethargy. In the 333 mg/kg group, "
        "3 male rats and 1 female rat were found dead or moribund by study day "
        "2. In the 1000 mg/kg group, 5 male rats and 5 female rats were found "
        "dead or moribund. Rats in the 50 mg/kg groups did not exhibit signs of "
        "overt toxicity, and all survived to study termination."
    ]


def test_full_mortality_without_signs():
    # No clinical observations recorded: the death details stand alone.
    out = _build_animal_condition_paragraphs(CN, UNIT, _MORT_FULL, None)
    assert out == [
        "In the 333 mg/kg "
        "group, 3 male rats and 1 female rat were found dead or moribund by "
        "study day 2. In the 1000 mg/kg group, 5 male rats and 5 female rats "
        "were found dead or moribund. Rats in the 50 mg/kg groups all survived "
        "to study termination."
    ]


def test_edge_no_earliest_no_latest_no_surviving():
    # earliest_death_day stays None (empty death_days), latest_day_num stays 0,
    # and the only surviving dose is the control (0.0, filtered out) → no
    # surviving sentence.
    out = _build_animal_condition_paragraphs(CN, UNIT, _MORT_EDGE, None)
    assert out == [
        "In the 1000 mg/kg group, 2 male rats were found dead or moribund."
    ]
