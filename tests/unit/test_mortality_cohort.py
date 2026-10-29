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


# --- the Removal Reasons workbook's dispositions (common.dispositions) -------

def _structure(*removed):
    """Animals 0-3 core, b0/b1 internal-dose, all scheduled but ``removed``:
    (id, disposition, day)."""
    animals = {str(i): {"sex": "Female", "dose": d, "selection": "Core Animals",
                        "disposition": "Scheduled Removal (Terminal)", "removal_day": "SD5"}
               for i, d in enumerate((0.0, 0.0, 800.0, 800.0))}
    animals.update({f"b{i}": {"sex": "Female", "dose": d, "selection": "Biosample Animals",
                              "disposition": "Biological Sampling", "removal_day": "SD4"}
                    for i, d in enumerate((0.0, 800.0))})
    for aid, disposition, day in removed:
        animals[aid].update(disposition=disposition, removal_day=f"SD{day}")
    return {"animals": animals}


def test_an_internal_dose_animal_found_dead_is_reported_and_the_core_survived(tmp_path):
    # NIEHS-13 rats: "One internal concentration assessment animal in the
    # 800 ppm group was found dead on study day 4.  All core rats … survived".
    m = extract_mortality(_sidecar(tmp_path), _structure(("b1", "Found Dead", 4)))
    assert m["internal_removals"] == [
        {"sex": "Female", "dose": 800.0, "disposition": "Found Dead", "day": 4}]
    text = _build_animal_condition_paragraphs("DCB", "ppm", m, None, INHALED_RATS)[0]
    assert text == ("One internal concentration assessment animal in the 800 ppm group "
                    "was found dead on study day 4. All core female rats survived to study "
                    "termination (SD5).")


def test_a_core_animal_euthanized_moribund_is_named_as_such(tmp_path):
    # NIEHS-12 mice: "… was euthanized moribund on study day 4", and the
    # internal-dose animals' accidental death and deaths.
    sidecar = _sidecar(tmp_path)
    m = extract_mortality(sidecar, _structure(("3", "Euthanized Moribund", 4),
                                              ("b0", "Accidental Death", 1),
                                              ("b1", "Found Dead", 3)))
    assert m["by_dose"][800.0]["Female"]["removals"] == [
        {"disposition": "Euthanized Moribund", "day": 4}]
    assert m["all_survived_doses"] == [0.0]
    text = _build_animal_condition_paragraphs("DCB", "ppm", m, None, INHALED_RATS)[0]
    assert text.startswith(
        "In the internal concentration assessment rats, one rat in the 0 ppm group died "
        "accidentally on study day 1 and one rat in the 800 ppm group was found dead on "
        "study day 3. ")
    assert "In the 800 ppm group, one female rat was euthanized moribund on study day 4." in text
    assert "found dead or moribund" not in text


def test_the_body_weight_footnote_says_how_the_animal_left(tmp_path):
    from tables.body_weight_table import build_body_weight_table_from_sidecar
    from common.dispositions import dispositions

    path = tmp_path / "bw.sidecar.json"
    days = lambda last: [{"day": f"SD{d}", "endpoint": "Body Weight", "value": "20",
                          "terminal": d == last} for d in range(last + 1)]
    path.write_text(json.dumps({"animals": {
        "1": {"dose": 0.0, "selection": "Core Animals", "observations": days(5)},
        "2": {"dose": 0.0, "selection": "Core Animals", "observations": days(5)},
        "3": {"dose": 250.0, "selection": "Core Animals", "observations": days(5)},
        "4": {"dose": 250.0, "selection": "Core Animals", "observations": days(4)},
    }}))
    structure = {"animals": {"4": {"sex": "Female", "dose": 250.0, "selection": "Core Animals",
                                   "disposition": "Euthanized Moribund", "removal_day": "SD4"}}}

    def notes(disp):
        out = build_body_weight_table_from_sidecar({"Female": str(path)}, dose_unit="ppm",
                                                   design={"species": "mouse"},
                                                   dispositions=disp)
        return [f["text"] for f in out["footnotes"]]

    assert "One female mouse was euthanized moribund on study day 4." in notes(
        dispositions(structure))
    # No Removal Reasons workbook: as before.
    assert "One female mouse was found dead on study day 4." in notes(None)
