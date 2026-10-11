"""Animal condition: the biosampling cohort is not mortality, and clinical
signs are never contradicted or invented.

NIEHS-13 removes its "Biosample Animals" on SD4 by schedule; counting them
as early deaths made every concentration, the control included, "begin
exhibiting signs of overt toxicity on study day 4".
"""

import json

from bmdx_pipe.clinical_observations import IncidenceRow
from common.animal_selection import is_biosampling
from narrative.unified_narrative import _build_animal_condition_paragraphs, extract_mortality

INHALED_RATS = {"species": "rat", "route": "inhaled"}


def _sidecar(tmp_path):
    def animal(dose, selection, last):
        days = [f"SD{d}" for d in range(last + 1)]
        return {"dose": dose, "selection": selection, "observations": [
            {"day": d, "endpoint": "Body Weight", "value": "180", "terminal": d == days[-1]}
            for d in days]}
    animals = {}
    for i, dose in enumerate((0.0, 0.0, 800.0, 800.0)):
        animals[str(i)] = animal(dose, "Core Animals", 5)
    for i, dose in enumerate((0.0, 800.0)):
        animals[f"b{i}"] = animal(dose, "Biosample Animals", 4)
    path = tmp_path / "bw.sidecar.json"
    path.write_text(json.dumps({"animals": animals}))
    return {"Female": str(path)}


def test_both_biosampling_spellings():
    assert is_biosampling("Biosample Animals") and is_biosampling("Biosampling Animals")
    assert not is_biosampling("Core Animals") and not is_biosampling(None)


def test_scheduled_biosampling_removal_is_not_mortality(tmp_path):
    m = extract_mortality(_sidecar(tmp_path))
    assert m["expected_terminal_day"] == "SD5"
    assert all(v["Female"]["early_deaths"] == 0 for v in m["by_dose"].values())
    assert m["by_dose"][0.0]["Female"]["total"] == 2


def test_survivors_with_clinical_signs_are_not_called_sign_free(tmp_path):
    m = extract_mortality(_sidecar(tmp_path))
    inc = {"Female": [IncidenceRow(label="Tremors (Moderate)",
                                   incidence_by_dose={0.0: "0/2", 800.0: "2/2"})]}
    text = _build_animal_condition_paragraphs("DCB", "ppm", m, inc, INHALED_RATS)[0]
    assert text == ("All female rats survived to study termination (SD5). Female rats "
                    "exposed to 800 ppm of DCB exhibited clinical signs, which included "
                    "tremors (moderate).")
    quiet = _build_animal_condition_paragraphs("DCB", "ppm", m, {}, INHALED_RATS)[0]
    assert quiet.endswith("without signs of overt toxicity.")
    # No clinical observations recorded: no claim either way.
    unobserved = _build_animal_condition_paragraphs("DCB", "ppm", m, None, INHALED_RATS)[0]
    assert unobserved == "All female rats survived to study termination (SD5)."


def _with_deaths(tmp_path):
    m = extract_mortality(_sidecar(tmp_path))
    m["by_dose"][800.0]["Female"].update(early_deaths=1, death_days={"SD3": 1})
    m["all_survived_doses"] = [0.0]
    return m


def test_signs_onset_comes_from_the_observations_not_the_deaths(tmp_path):
    inc = {"Female": [IncidenceRow(label="Tremors (Moderate)",
                                   incidence_by_dose={0.0: "0/2", 800.0: "2/2"},
                                   onset_day_by_dose={800.0: 0})]}
    text = _build_animal_condition_paragraphs("DCB", "ppm", _with_deaths(tmp_path), inc,
                                              INHALED_RATS)[0]
    assert text.startswith("Female rats exposed to 800 ppm of DCB began exhibiting signs "
                           "of overt toxicity on study day 0, which included tremors")
    assert "by study day 3" in text


def test_no_observations_no_signs_sentence(tmp_path):
    text = _build_animal_condition_paragraphs("DCB", "ppm", _with_deaths(tmp_path), None,
                                              INHALED_RATS)[0]
    assert "signs" not in text
    assert text.startswith("In the 800 ppm group, 1 female rat was found dead or moribund")
