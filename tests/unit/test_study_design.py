"""Study-design facts come from the recorded metadata, never protocol defaults."""

import pytest

from narrative.abstract_methods import build_abstract_methods
from narrative.methods_design import (
    assemble_methods_sections, build_chemistry, build_dose_selection, build_study_design,
    refresh_data_built,
)
from narrative.methods_models import MethodsContext
from pipeline.study_design import (
    administration_phrase, study_design_facts, study_type_label, subject_phrase, vehicle_phrase,
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


def test_unrecorded_facts_stay_unrecorded():
    """No standard design (2026-11-16): a fact the data do not record is None
    — Process refuses the study until it is stated (pipeline.study_parameters)."""
    f = study_design_facts(_integrated(species="rat"))
    assert (f["strain"], f["route"], f["vehicle"], f["duration_days"]) == (None,) * 4
    assert "fallback" not in f
    assert subject_phrase(f) == "rats"
    assert subject_phrase(study_design_facts({})) == "animals"


def test_recorded_values_stand():
    f = study_design_facts(_integrated(species="mouse", administrationMeans="dietary"))
    assert f["route"] == "dietary" and f["strain"] is None


def test_disagreeing_experiments_are_not_resolved():
    integ = _integrated(articleVehicle="corn oil")
    integ["doseResponseExperiments"][1]["experimentDescription"]["articleVehicle"] = "water"
    f = study_design_facts(integ)
    assert f["vehicle"] is None and f["conflicts"] == ["articleVehicle"]


def test_oral_alone_does_not_say_how():
    assert study_design_facts(_integrated(articleRoute="oral"))["route"] is None


def _ctx(**kw):
    fields = dict(chemical_name="Triclosan", casrn="3380-34-5", dtxsid="DTXSID5032498",
                  dose_groups=[0, 7.8, 15.6, 31.25], sexes=["Male"],
                  n_per_group=4, n_control=4, species="rat", dose_unit="mg/kg",
                  duration_days=5, dosing_days=5, dosing_schedule="once daily")
    return MethodsContext(**{**fields, **kw})


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
    assert "corn oil" not in design and "gavage" not in design   # none assumed
    assert "animal source" in scan_pending_markers(design)[0]

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


def test_a_member_study_names_its_substance_not_its_session():
    # NIEHS-12/13's rat and mouse member sessions are "<DTXSID>_rat" / "_mouse".
    ctx = _ctx()
    ctx.dtxsid = "DTXSID1020431_rat"
    chem = build_chemistry(ctx)[0]
    assert "(CASRN 3380-34-5; DTXSID1020431)." in chem


def test_a_render_rebuilds_the_data_built_subsections_from_the_cached_context():
    cached = [{"key": "chemistry", "heading": "Chemistry", "level": 3,
               "paragraphs": ["stale wording"]},
              {"key": "clinical_obs", "heading": "Clinical Observations", "level": 4,
               "paragraphs": ["LLM text"]}]
    out = refresh_data_built(cached, _ctx().to_dict())
    assert out[0]["paragraphs"][0].startswith("The test article was Triclosan")
    assert out[1]["paragraphs"] == ["LLM text"]
    assert refresh_data_built(cached, None) is cached


def test_the_abstract_names_each_bmr_as_used():
    ctx = _ctx(has_gene_expression=True, ge_organs=["liver"],
               bmr_type="Std. Dev.", bmr_factor=1.0)
    assert "one standard deviation was used to model all endpoints." in \
        build_abstract_methods(ctx)
    ctx.bmr_type, ctx.bmr_factor = "Relative Deviation", 0.25
    ctx.apical_bmr = ("Standard Deviation", 1.0)
    text = build_abstract_methods(ctx)
    assert ("one standard deviation was used to model all apical endpoints, whereas a "
            "benchmark response of a 25% relative deviation was used to model the gene "
            "expression data.") in text
    ctx.bmr_type = ctx.bmr_factor = ctx.apical_bmr = None
    assert "benchmark response" in scan_pending_markers(build_abstract_methods(ctx))[0]


def test_assembly_keeps_skeleton_order_and_ignores_llm_for_data_keys():
    skeleton = [("study_design", "Study Design", 3), ("chemistry", "Chemistry", 3),
                ("clinical_obs", "Clinical Observations", 4)]
    llm = {"study_design": "Quarantined 7 days.", "clinical_obs": "Observed daily.\n\nTwice."}
    sections = assemble_methods_sections(_ctx(), skeleton, llm)
    assert [s.key for s in sections] == ["study_design", "chemistry", "clinical_obs"]
    assert "Quarantined" not in sections[0].paragraphs[0]
    assert sections[2].paragraphs == ["Observed daily.", "Twice."]


def test_duration_recorded_else_none():
    from pipeline.study_design import caption_treatment, duration_phrase

    recorded = study_design_facts(_integrated(studyDuration="28d"))
    assert recorded["duration_days"] == 28
    assert caption_treatment(recorded, "X") == "Administered X for 28 Days"
    assert study_design_facts(_integrated())["duration_days"] is None   # never five days
    # An hour-scale study is not given five days.
    assert study_design_facts(_integrated(studyDuration="6h"))["duration_days"] is None
    assert duration_phrase(1) == "One Day" and duration_phrase(None) == ""


def test_the_dosing_days_and_schedule_are_the_studys():
    """RR-8 … NIEHS-06: "once daily for 4 consecutive days" (a 5-day study,
    necropsy on day 4); NIEHS-12, 13: "for 6 hours plus T90 per day"."""
    design = build_study_design(_ctx(route="gavage", dosing_days=4))[0]
    assert "once daily for 4 consecutive days (study days 0–3)" in design
    assert "euthanized on study day 4, the day after the final dose" in design
    inhaled = build_study_design(_ctx(route="inhaled", inhalation="whole-body", dose_unit="ppm",
                                      dosing_schedule="6 hours plus T90 per day"))[0]
    assert ("by whole-body inhalation for 6 hours plus T90 per day for 5 consecutive days "
            "(study days 0–4)") in inhaled
    abstract = build_abstract_methods(_ctx(route="gavage", dosing_days=4))
    assert "once daily for 4 consecutive days by gavage (study days 0–3)" in abstract
    assert "On study day 4, the day after the final dose" in abstract


def test_a_context_cached_before_the_parameters_is_refused():
    from workflow.errors import StepError
    old = {k: v for k, v in _ctx().to_dict().items()
           if k not in ("dosing_days", "dosing_schedule")}
    with pytest.raises(StepError, match="run Process again"):
        refresh_data_built([{"key": "study_design", "paragraphs": ["x"]}], old)
    with pytest.raises(StepError, match="run Process again"):
        build_abstract_methods(MethodsContext.from_dict(old))


def test_apical_caption_for_an_inhalation_study():
    from tables.table_builder_common import apical_caption

    design = study_design_facts(_integrated(species="rat", articleRoute="inhaled",
                                            studyDuration="5d"))
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


def test_a_stated_design_is_put_on_every_experiment():
    from pipeline.study_design import apply_design_fields

    integrated = _integrated(species="rat")
    assert apply_design_fields(integrated, {"strain": "Wistar", "administrationMeans": "gavage",
                                            "articleVehicle": "water", "studyDuration": "5d",
                                            "doseUnit": "mg/kg", "dosingDays": 5}) == 2
    f = study_design_facts(integrated)
    assert (f["strain"], f["route"], f["vehicle"], f["duration_days"]) == (
        "Wistar", "gavage", "water", 5)
    # The stated-only parameters stay in study_design.json, off the experiments.
    assert "doseUnit" not in integrated["doseResponseExperiments"][0]["experimentDescription"]


def test_a_single_sex_study_names_its_sex_in_the_title():
    """The published titles name the sex of a single-sex study: "Male Sprague
    Dawley … Rats" (NIEHS-02 … 06), "Female … Rats and … Mice" (NIEHS-12, 13),
    and none for both sexes (NIEHS-07 … 10)."""
    from pipeline.study_design import sex_word, title_subjects

    sd = {"species": "rat", "strain": "Sprague-Dawley"}
    males = study_design_facts({"doseResponseExperiments": [
        {"experimentDescription": {**sd, "sex": "male"}},
        {"experimentDescription": {**sd, "sex": "Male"}}]})
    both = study_design_facts({"doseResponseExperiments": [
        {"experimentDescription": {**sd, "sex": "male"}},
        {"experimentDescription": {**sd, "sex": "female"}}]})
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


def test_the_inhalation_method_names_the_study_type():
    """"Route: Whole-Body Inhalation" (administrationMeans "whole-body") keeps
    the route inhalation and names the method: "(Whole-body Inhalation
    Studies)", "by whole-body inhalation" (NIEHS-12, 13).  Unrecorded, the
    method is not named."""
    f = study_design_facts(_integrated(species="rat", articleRoute="inhaled",
                                       administrationMeans="whole-body"))
    assert (f["route"], f["inhalation"]) == ("inhaled", "whole-body")
    assert study_type_label(f) == "Whole-body Inhalation Studies"
    assert administration_phrase(f) == "by whole-body inhalation"
    plain = study_design_facts(_integrated(species="rat", articleRoute="inhaled"))
    assert (plain["inhalation"], study_type_label(plain)) == (None, "Inhalation Studies")


def test_the_abstract_names_each_apical_domains_bmr_when_they_differ():
    # The February 2026 DTT method: clinical chemistry at 25% RD, the rest at 1 SD.
    ctx = _ctx(has_gene_expression=True, ge_organs=["liver"],
               bmr_type="Relative Deviation", bmr_factor=0.25,
               apical_bmrs={"Body Weight": ["Standard Deviation", 1.0],
                            "Organ Weight": ["Standard Deviation", 1.0],
                            "Clinical Chemistry": ["Relative Deviation", 0.25]})
    assert ("A benchmark response of one standard deviation was used to model the body "
            "weight and organ weight endpoints, and a benchmark response of a 25% relative "
            "deviation was used to model the clinical chemistry endpoints and the gene "
            "expression data.") in build_abstract_methods(ctx)


def test_the_transcriptomic_settings_are_the_gene_expression_projects():
    from narrative.methods_extract import _is_transcriptomic, extract_methods_context

    def project(provider, bmr, factor):
        notes = ["BMR Type: " + bmr, f"BMR Factor: {factor}"]
        return {"doseResponseExperiments": [{"chip": {"provider": provider, "name": provider}}],
                "bMDResult": [{"analysisInfo": {"notes": notes}}]}
    apical = project("generic", "Standard Deviation", 1.0)
    genomic = project("BioSpyder", "Relative Deviation", 0.25)
    assert _is_transcriptomic(genomic) and not _is_transcriptomic(apical)
    from pipeline.study_parameters import resolve
    params = resolve(None, ["mg/kg"], {
        "species": "rat", "strain": "Sprague-Dawley", "administrationMeans": "gavage",
        "articleVehicle": "corn oil", "studyDuration": "5d", "dosingDays": 5,
        "dosingSchedule": "once daily"})
    ctx = extract_methods_context(
        {"name": "X"}, {"f1": {"filename": "Body weight.bm2", "platform": "Body Weight"}},
        parameters=params, bm2_jsons={"Body weight": apical, "Gene Expression": genomic})
    assert (ctx.bmr_type, ctx.bmr_factor) == ("Relative Deviation", 0.25)
    assert ctx.apical_bmrs == {"Body Weight": ["Standard Deviation", 1.0]}
