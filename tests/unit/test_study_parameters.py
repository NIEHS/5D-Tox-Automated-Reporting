"""No fallbacks for study parameters (user decision 2026-11-16).

Every parameter a report states is recorded by the study's data or stated in
study_design.json; missing or conflicting ones refuse Process, named
(pipeline.study_parameters, safeguards.inputs.require_study_parameters).  The
independent review of 7b58a68 reproduced three silent defaults this replaces:
mixed ppm/mg/kg became mg/kg, 5d + 28d became "five days", and an inhalation
study with no unit read "by inhalation in corn oil".
"""

import json

import pytest

from pipeline.study_parameters import STATED_FIELDS, resolve, stated_field_errors

DESIGN = {"species": "rat", "strain": "Sprague-Dawley", "articleRoute": "oral",
          "administrationMeans": "gavage", "articleVehicle": "corn oil", "studyDuration": "5d"}
DOSING = {"dosingDays": 5, "dosingSchedule": "once daily"}


def _integrated(*eds, provenance=None):
    exps = [{"name": f"e{i}", "experimentDescription": dict(ed)} for i, ed in enumerate(eds)]
    out = {"doseResponseExperiments": exps}
    if provenance:
        out["_meta"] = {"metadata_provenance": provenance}
    return out


def test_complete_from_recorded_and_stated():
    p = resolve(_integrated(DESIGN, DESIGN), ["mg/kg"], DOSING)
    assert p.complete and p.problems() == []
    assert p.values == {"species": "rat", "strain": "Sprague-Dawley", "route": "gavage",
                        "vehicle": "corn oil", "duration_days": 5, "dosing_days": 5,
                        "dosing_schedule": "once daily", "dose_unit": "mg/kg"}
    assert p.sources["dose_unit"] == "recorded" and p.sources["dosing_days"] == "stated"


def test_nothing_is_assumed():
    p = resolve(_integrated({"species": "rat"}), [], {})
    assert not p.complete
    assert list(p.missing) == ["strain", "route", "vehicle", "duration_days", "dosing_days",
                               "dosing_schedule", "dose_unit"]
    assert "no dose unit is recorded or stated" in p.problems()


def test_conflicting_dose_units_are_never_mg_kg():
    p = resolve(_integrated(DESIGN), ["ppm", "mg/kg"], DOSING)
    assert p.values["dose_unit"] is None and p.conflicting["dose_unit"] == ["mg/kg", "ppm"]
    # A person picks among the units the files record …
    chosen = resolve(_integrated(DESIGN), ["ppm", "mg/kg"], {**DOSING, "doseUnit": "ppm"})
    assert chosen.complete and (chosen.values["dose_unit"], chosen.sources["dose_unit"]) == (
        "ppm", "stated")
    # … but never overrides the one unit they record.
    contradicted = resolve(_integrated(DESIGN), ["mg/kg"], {**DOSING, "doseUnit": "ppm"})
    assert contradicted.conflicting["dose_unit"] == ["mg/kg", "ppm (stated)"]
    assert resolve(_integrated(DESIGN), ["PPM", "ppm"], DOSING).values["dose_unit"] == "PPM"


def test_conflicting_durations_are_never_five_days():
    p = resolve(_integrated(DESIGN, {**DESIGN, "studyDuration": "28d"}), ["mg/kg"], DOSING)
    assert p.values["duration_days"] is None and p.conflicting["duration_days"] == ["28d", "5d"]
    assert any("conflicting values for the study duration" in x for x in p.problems())


def test_an_inhalation_study_without_a_unit_is_refused_not_given_corn_oil():
    inhaled = {"species": "rat", "strain": "Sprague-Dawley", "articleRoute": "inhaled",
               "administrationMeans": "whole-body", "studyDuration": "5d"}
    p = resolve(_integrated(inhaled), [], {"dosingDays": 5,
                                           "dosingSchedule": "6 hours plus T90 per day"})
    assert p.missing == ("dose_unit",)
    assert (p.values["route"], p.inhalation, p.values["vehicle"]) == ("inhaled", "whole-body",
                                                                       None)
    assert p.not_applicable == ("vehicle",)


def test_the_unit_never_implies_a_route():
    p = resolve(_integrated({"species": "rat"}), ["ppm"], {})
    assert p.values["route"] is None and "route" in p.missing


def test_where_each_value_came_from():
    prov = {"e0": {"species": "workbook", "strain": "llm", "articleVehicle": "stated"}}
    p = resolve(_integrated(DESIGN, provenance=prov), ["mg/kg"], DOSING)
    assert (p.sources["species"], p.sources["strain"], p.sources["vehicle"]) == (
        "recorded", "inferred", "stated")


def test_a_stated_fact_no_experiment_carries_yet_counts():
    p = resolve(None, ["mg/kg"], {**DESIGN, **DOSING})
    assert p.complete and p.sources["species"] == "stated"


def test_stated_values_are_checked():
    assert "doseUnit" in STATED_FIELDS and "dosingDays" in STATED_FIELDS
    assert stated_field_errors({"doseUnit": "mg/kg", "dosingDays": 4,
                                "dosingSchedule": "once daily"}) == []
    errors = stated_field_errors({"doseUnit": "furlongs", "dosingDays": 0,
                                  "dosingSchedule": "weekly"})
    assert len(errors) == 3


def _session(sessions_dir, sid, fields):
    d = sessions_dir / sid
    d.mkdir(parents=True)
    integrated = _integrated(DESIGN)
    integrated.update({"name": sid, "_meta": {"dtxsid": sid, "integrated_at": "2026-11-16",
                                             "source_files": {}}})
    for e in integrated["doseResponseExperiments"]:
        e.update({"treatments": [], "probeResponses": []})
    (d / "integrated.json").write_text(json.dumps(integrated))
    (d / "study_design.json").write_text(json.dumps({"fields": fields}))
    return d


def test_process_is_refused_naming_the_parameters(sessions_dir):
    from safeguards.inputs import require_study_parameters
    from safeguards.refusals import Refused, explain
    from workflow.store import DiskPoolStore

    _session(sessions_dir, "DTXSID_SP1", {})
    with pytest.raises(Refused) as e:
        require_study_parameters("DTXSID_SP1", DiskPoolStore())
    assert e.value.code == "study_parameters_incomplete" and e.value.status_code == 422
    assert set(e.value.details["parameters"]) == {"dosing_days", "dosing_schedule",
                                                  "dose_unit"}
    assert explain(e.value)["error"]["fix"] == "facts"

    _session(sessions_dir, "DTXSID_SP2", {**DOSING, "doseUnit": "mg/kg"})
    assert require_study_parameters("DTXSID_SP2", DiskPoolStore()).complete


def test_the_engine_derives_them(sessions_dir):
    from workflow.engine import WorkflowEngine
    from workflow.store import DiskPoolStore

    _session(sessions_dir, "DTXSID_SP3", {"dosingDays": 5})
    out = WorkflowEngine("DTXSID_SP3", DiskPoolStore()).study_parameters()
    assert out["complete"] is False and out["missing"] == ["dosing_schedule", "dose_unit"]
    assert out["sources"]["dosing_days"] == "stated"


def test_stating_merges_and_null_withdraws(sessions_dir):
    from workflow.steps import record_study_design
    from workflow.store import DiskPoolStore

    d = _session(sessions_dir, "DTXSID_SP4", {**DOSING})
    record_study_design("DTXSID_SP4", {"doseUnit": "mg/kg"}, DiskPoolStore())
    assert json.loads((d / "study_design.json").read_text())["fields"] == {**DOSING,
                                                                          "doseUnit": "mg/kg"}
    record_study_design("DTXSID_SP4", {"dosingDays": None}, DiskPoolStore())
    assert "dosingDays" not in json.loads((d / "study_design.json").read_text())["fields"]
