"""Study-design facts come from the recorded metadata, never protocol defaults."""

from narrative.methods_design import (
    assemble_methods_sections, build_chemistry, build_dose_selection, build_study_design,
)
from narrative.methods_models import MethodsContext
from pipeline.study_design import (
    administration_phrase, resolve_dose_unit, study_design_facts, study_type_label,
    subject_phrase, vehicle_phrase,
)
from rendering.render_common import scan_pending_markers


def _integrated(**ed):
    return {"doseResponseExperiments": [{"name": "a", "experimentDescription": dict(ed)},
                                        {"name": "b", "experimentDescription": dict(ed)}]}


def test_facts_from_recorded_metadata():
    f = study_design_facts(_integrated(species="rat", strain="Sprague-Dawley",
                                       articleRoute="oral", administrationMeans="gavage",
                                       articleVehicle="corn oil"))
    assert (f["species"], f["strain"], f["route"], f["vehicle"]) == (
        "rat", "Sprague-Dawley", "gavage", "corn oil")
    assert subject_phrase(f) == "Sprague Dawley rats"
    assert administration_phrase(f) == "by gavage"
    assert vehicle_phrase(f) == "in corn oil"
    assert study_type_label(f) == "Gavage Studies"


def test_unrecorded_facts_take_the_standard_design():
    """Sprague Dawley rats, gavage in corn oil, five days — listed as fallback, not recorded."""
    f = study_design_facts(_integrated(species="rat"), "mg/kg")
    assert (f["strain"], f["route"], f["vehicle"]) == ("Sprague-Dawley", "gavage", "corn oil")
    assert sorted(f["fallback"]) == ["duration_days", "route", "strain", "vehicle"]
    assert subject_phrase(f) == "Sprague Dawley rats"


def test_ppm_means_inhalation_not_gavage():
    f = study_design_facts(_integrated(species="rat"), "ppm")
    assert f["route"] == "inhaled" and f["vehicle"] is None
    assert administration_phrase(f) == "by inhalation"
    assert study_type_label(f) == "Inhalation Studies"


def test_recorded_values_win_over_the_fallback():
    f = study_design_facts(_integrated(species="mouse", administrationMeans="dietary"), "mg/kg")
    assert f["route"] == "dietary" and f["strain"] is None   # no mouse strain fallback
    assert "route" not in f["fallback"]


def test_unknown_unit_gets_no_route_fallback():
    f = study_design_facts(_integrated(species="rat"), "µM")
    assert f["route"] is None and f["vehicle"] is None
    assert subject_phrase(study_design_facts({})) == "animals"


def test_dose_unit_resolution():
    assert resolve_dose_unit("ppm", ["mg/kg"]) == ("ppm", "stated")
    assert resolve_dose_unit(None, ["ppm", "ppm"]) == ("ppm", "recorded")
    assert resolve_dose_unit(None, ["ppm", "mg/kg"]) == ("mg/kg", "fallback")
    assert resolve_dose_unit(None, []) == ("mg/kg", "fallback")


def test_disagreeing_experiments_are_not_resolved():
    integ = _integrated(articleVehicle="corn oil")
    integ["doseResponseExperiments"][1]["experimentDescription"]["articleVehicle"] = "water"
    f = study_design_facts(integ, "mg/kg")
    assert f["vehicle"] is None and f["conflicts"] == ["articleVehicle"]   # no fallback over it


def test_oral_alone_does_not_say_how():
    assert study_design_facts(_integrated(articleRoute="oral"), "µM")["route"] is None


def _ctx(**kw):
    return MethodsContext(chemical_name="Triclosan", casrn="3380-34-5", dtxsid="DTXSID5032498",
                          dose_groups=[0, 7.8, 15.6, 31.25], sexes=["Male"],
                          n_per_group=4, n_control=4, species="rat", **kw)


def test_inhalation_methods_wording():
    c = _ctx(strain="Sprague Dawley", route="inhaled", dose_unit="ppm")
    design = build_study_design(c)[0]
    assert design.startswith("Male Sprague Dawley rats were exposed to Triclosan by inhalation")
    assert "exposure concentrations of 0 (chamber control), 7.8, 15.6, and 31.25 ppm" in design
    assert "after the final exposure" in design
    assert "exposure concentrations from 7.8 to 31.25 ppm" in build_dose_selection(c)[0]
    assert "spacing between consecutive concentrations" in build_dose_selection(c)[0]
    # Inhalation controls breathe clean air: no vehicle, no formulations.
    assert "in the chamber control group" in design
    assert "vehicle" not in design
    chem = build_chemistry(c)[0]
    assert "vehicle" not in chem and "formulation" not in chem
    assert "chamber concentration monitoring" in chem


def test_significance_footnote_names_the_control_group():
    from tables.table_builder_common import significance_explanation
    assert "chamber control group" in significance_explanation("ppm")
    assert "vehicle" not in significance_explanation("ppm")
    assert "vehicle control group" in significance_explanation("mg/kg")


def test_methods_subsections_state_data_and_flag_the_rest():
    design = build_study_design(_ctx())[0]
    assert design.startswith("Male rats were administered Triclosan once daily")
    assert "0 (vehicle control), 7.8, 15.6, and 31.25 mg/kg" in design
    assert "4 core male animals in each treated group" in design
    assert "corn oil" not in design and "gavage" not in design
    assert "route of administration" in scan_pending_markers(design)[0]

    assert "approximately 2.0-fold spacing" in build_dose_selection(_ctx())[0]
    chem = build_chemistry(_ctx())[0]
    assert chem.startswith("The test article was Triclosan (CASRN 3380-34-5; DTXSID5032498).")
    assert "purity" in scan_pending_markers(chem)[0]


def test_recorded_design_appears_in_methods():
    design = build_study_design(_ctx(strain="Sprague Dawley", route="gavage",
                                     vehicle="corn oil"))[0]
    assert design.startswith("Male Sprague Dawley rats were administered Triclosan "
                             "by gavage in corn oil once daily")
    marker = scan_pending_markers(design)[0]
    assert "route" not in marker and "animal source" in marker


def test_assembly_keeps_skeleton_order_and_ignores_llm_for_data_keys():
    skeleton = [("study_design", "Study Design", 3), ("chemistry", "Chemistry", 3),
                ("clinical_obs", "Clinical Observations", 4)]
    llm = {"study_design": "Quarantined 7 days.", "clinical_obs": "Observed daily.\n\nTwice."}
    sections = assemble_methods_sections(_ctx(), skeleton, llm)
    assert [s.key for s in sections] == ["study_design", "chemistry", "clinical_obs"]
    assert "Quarantined" not in sections[0].paragraphs[0]
    assert sections[2].paragraphs == ["Observed daily.", "Twice."]


def test_duration_recorded_else_standard_five_days():
    from pipeline.study_design import caption_treatment, duration_phrase

    recorded = study_design_facts(_integrated(studyDuration="28d"), "mg/kg")
    assert recorded["duration_days"] == 28 and "duration_days" not in recorded["fallback"]
    assert caption_treatment(recorded, "X") == "Administered X for 28 Days"
    fallback = study_design_facts(_integrated(), "mg/kg")
    assert fallback["duration_days"] == 5 and "duration_days" in fallback["fallback"]
    # An hour-scale study is not given five days.
    hours = study_design_facts(_integrated(studyDuration="6h"), "mg/kg")
    assert hours["duration_days"] is None and "duration_days" not in hours["fallback"]
    assert duration_phrase(1) == "One Day" and duration_phrase(None) == ""


def test_apical_caption_for_an_inhalation_study():
    from tables.table_builder_common import apical_caption

    design = study_design_facts(_integrated(species="rat"), "ppm")
    cap = apical_caption("Summary of Body Weights of {subject} {treatment}",
                         {"Female": [{"label": "x"}]}, "1,4-Dichlorobenzene", design)
    assert cap == ("Summary of Body Weights of Female Rats "
                   "Exposed to 1,4-Dichlorobenzene for Five Days")


def test_stated_design_fields_are_checked_against_the_vocabulary():
    from pipeline.study_design import design_field_errors

    vocab = {"strain": {"rat": ["Sprague-Dawley", "Wistar"]}, "articleVehicle": ["corn oil"]}
    assert design_field_errors({"strain": "Sprague-Dawley", "articleVehicle": "corn oil"},
                               vocab) == []
    errors = design_field_errors({"strain": "SD", "supplier": "Envigo"}, vocab)
    assert any("supplier" in e for e in errors) and any("'SD'" in e for e in errors)


def test_a_stated_design_replaces_the_fallback():
    from pipeline.study_design import apply_design_fields

    integrated = _integrated(species="rat")
    assert apply_design_fields(integrated, {"strain": "Wistar", "administrationMeans": "gavage",
                                            "articleVehicle": "water", "studyDuration": "5d"}) == 2
    f = study_design_facts(integrated, "mg/kg")
    assert (f["strain"], f["route"], f["vehicle"], f["duration_days"]) == (
        "Wistar", "gavage", "water", 5)
    assert f["fallback"] == []


def test_a_single_sex_study_names_its_sex_in_the_title():
    """The published titles name the sex of a single-sex study: "Male Sprague
    Dawley … Rats" (NIEHS-02 … 06), "Female … Rats and … Mice" (NIEHS-12, 13),
    and none for both sexes (NIEHS-07 … 10)."""
    from pipeline.study_design import sex_word, title_subjects

    males = study_design_facts({"doseResponseExperiments": [
        {"experimentDescription": {"species": "rat", "sex": "male"}},
        {"experimentDescription": {"species": "rat", "sex": "Male"}}]})
    both = study_design_facts({"doseResponseExperiments": [
        {"experimentDescription": {"species": "rat", "sex": "male"}},
        {"experimentDescription": {"species": "rat", "sex": "female"}}]})
    assert males["sexes"] == ["male"] and both["sexes"] == ["female", "male"]
    animals = lambda f: subject_phrase(f, capitalize=True)          # noqa: E731
    assert title_subjects(males, animals) == "Male Sprague Dawley Rats"
    assert title_subjects(both, animals) == "Sprague Dawley Rats"
    assert sex_word(study_design_facts(_integrated(species="rat"))) == ""

    rats = {"species": "rat", "strain": "Sprague-Dawley", "sexes": ["female"]}
    mice = {"species": "mouse", "strain": "B6D2F1", "sexes": ["female"]}
    assert (title_subjects({"studies": [rats, mice]}, animals)
            == "Female Sprague Dawley Rats and B6D2F1 Mice")
    assert (title_subjects({"studies": [rats, {**mice, "sexes": ["male"]}]}, animals)
            == "Female Sprague Dawley Rats and Male B6D2F1 Mice")
