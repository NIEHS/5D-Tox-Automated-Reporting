"""The report's prose names the study's species, never a fixed "rats".

Every deterministic narrative builder takes the study design
(pipeline.study_design.study_design_facts); None means the standard design
(Sprague Dawley rats by gavage), so callers without a design read as before.
"""

from narrative.abstract_apical import build_abstract_results_apical
from narrative.report_summary import build_report_summary
from narrative.unified_narrative import _build_animal_condition_paragraphs
from tables.table_builder_common import build_attrition_footnote

MICE = {"species": "mouse", "route": "gavage", "duration_days": 5}
INHALED_RATS = {"species": "rat", "route": "inhaled", "duration_days": 5}

_APICAL = [{"endpoint": "Liver Weight", "sex": "Female", "platform": "Organ Weight",
            "bmd": "12.0", "bmdl": "6.0", "bmd_status": "viable", "direction": "increase"}]


def _deaths():
    return {
        "by_dose": {
            0.0: {"Female": {"total": 5, "early_deaths": 0}},
            800.0: {"Female": {"total": 5, "early_deaths": 1, "death_days": {"SD2": 1}}},
        },
        "expected_terminal_day": "SD5",
        "all_survived_doses": [0.0],
    }


def test_animal_condition_names_species_and_inhalation_verb():
    from bmdx_pipe.clinical_observations import IncidenceRow

    signs = {"Female": [IncidenceRow(label="Tremors", incidence_by_dose={0.0: "0/5", 800.0: "2/5"},
                                     onset_day_by_dose={800.0: 0})]}
    text = _build_animal_condition_paragraphs("DCB", "ppm", _deaths(), signs, INHALED_RATS)[0]
    assert text.startswith("Female rats exposed to 800 ppm of DCB")
    mice = _build_animal_condition_paragraphs("X", "mg/kg", _deaths(), signs, MICE)[0]
    assert mice.startswith("Female mice administered 800 mg/kg of X")
    assert "1 female mouse" in mice and "rat" not in mice
    # No design → the standard design's wording, unchanged.
    std = _build_animal_condition_paragraphs("X", "mg/kg", _deaths(), signs)[0]
    assert std.startswith("Female rats administered")


def test_abstract_and_summary_name_the_species():
    ab = build_abstract_results_apical(_APICAL, sexes=["Female"], design=MICE)
    assert "In female mice, the effects included" in ab and "rats" not in ab
    summary = " ".join(build_report_summary(_APICAL, {}, chemical_name="X",
                                            sexes=["Female"], design=MICE))
    assert "female mice" in summary and "rats" not in summary


def test_footnote_names_the_species():
    record, _ = build_attrition_footnote(
        {"Female": {800.0: 5}}, {"Female": {800.0: 0}}, [0.0, 800.0], "mg/kg", MICE)
    assert "800 mg/kg mice were found dead" in record["text"]


def test_unrecorded_species_reads_animals():
    ab = build_abstract_results_apical(_APICAL, sexes=["Female"], design={"species": None})
    assert "In female animals," in ab


def test_sampling_time_word_follows_the_route():
    from narrative.abstract_pk import build_abstract_results_pk
    from tables.tissue_concentration_table import _parse_timepoint

    ep = "Plasma 2 Hour Chemical Concentration"
    assert _parse_timepoint(ep) == "2 h postdose"
    assert _parse_timepoint(ep, "postexposure") == "2 h postexposure"

    conc = {"Male": {4: {2: 10.0, 24: 2.0}}, "Female": {4: {2: 20.0, 24: 5.0}}}
    half = {"Male": {4: 40.1}, "Female": {4: 78.2}}
    oral = build_abstract_results_pk("X", conc, half, [2, 24])
    inhaled = build_abstract_results_pk("X", conc, half, [2, 24], design=INHALED_RATS)
    assert "2 and 24 hours postdose" in oral
    assert "2 and 24 hours postexposure" in inhaled and "postdose" not in inhaled
