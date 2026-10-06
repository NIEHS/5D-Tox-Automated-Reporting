"""Animal condition: the biosampling cohort is not mortality, and clinical
signs are never contradicted.

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
    quiet = _build_animal_condition_paragraphs("DCB", "ppm", m, None, INHALED_RATS)[0]
    assert quiet.endswith("without signs of overt toxicity.")
