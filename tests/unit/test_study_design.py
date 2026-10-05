"""Study-design facts come from the recorded metadata, never protocol defaults."""

from narrative.methods_design import (
    assemble_methods_sections, build_chemistry, build_dose_selection, build_study_design,
)
from narrative.methods_models import MethodsContext
from pipeline.study_design import (
    administration_phrase, study_design_facts, study_type_label, subject_phrase,
    vehicle_phrase,
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


def test_nothing_defaulted():
    f = study_design_facts(_integrated(species="rat"))
    assert f["strain"] is f["route"] is f["vehicle"] is None
    assert subject_phrase(f) == "rats"
    assert administration_phrase(f) == vehicle_phrase(f) == study_type_label(f) == ""
    assert subject_phrase(study_design_facts({})) == "animals"


def test_disagreeing_experiments_are_not_resolved():
    integ = _integrated(articleVehicle="corn oil")
    integ["doseResponseExperiments"][1]["experimentDescription"]["articleVehicle"] = "water"
    f = study_design_facts(integ)
    assert f["vehicle"] is None and f["conflicts"] == ["articleVehicle"]


def test_oral_alone_does_not_say_how():
    assert study_design_facts(_integrated(articleRoute="oral"))["route"] is None


def _ctx(**kw):
    return MethodsContext(chemical_name="Triclosan", casrn="3380-34-5", dtxsid="DTXSID5032498",
                          dose_groups=[0, 7.8, 15.6, 31.25], sexes=["Male"],
                          n_per_group=4, n_control=4, species="rat", **kw)


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
