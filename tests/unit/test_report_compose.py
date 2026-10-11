"""
A report over several studies (rendering.report_compose, ADR-0029 §9): the
report session lists its member studies (studies.json) and their data merge
into the report's — combined tables grouped by study, on the union of the
studies' dose levels; one References list; the studies named together.
"""

import json

import pytest

from document_model.document_node import DocNode
from pipeline.study_design import species_plural, subject_phrase
from rendering import report_compose
from rendering.render_common import apical_table_plan

CAPTION = "Summary of Body Weights of Female {species} Exposed to 1,4-DCB for Five Days"


def _row(doses, values):
    return {"endpoint": "Body Weight", "doses": doses, "values": values,
            "bmd": "ND", "bmdl": "ND"}


def _member(species, title, doses, ref, extra_platform=None):
    sections = [{"platform": "Body Weight", "caption": CAPTION.format(species=title),
                 "dose_unit": "ppm",
                 "footnotes": [{"kind": "lettered", "id": "data_format", "text": "Mean ± SE."}],
                 "table_data": {"Female": [_row(doses, [f"{species}{d}" for d in doses])]}}]
    if extra_platform:
        sections.append({"platform": extra_platform, "caption": CAPTION.format(species=title),
                         "table_data": {"Female": [_row(doses, ["h"] * len(doses))]}})
    heads = [f"{d} ppm" for d in doses]
    return {
        "study_design": {"species": species, "strain": None, "route": "inhaled",
                         "vehicle": None, "duration_days": 5},
        "dose_unit": "ppm",
        "apical_sections": sections,
        "genomics_sections": [{"type": "gene_set", "organ": "liver", "narrative": ["n"],
                               "sexes": [{"sex": "female", "gene_sets": [{"go_id": species}],
                                          "narrative": [f"{species} prose [1]."]}]}],
        "bmd_summary": {"endpoints": [{"endpoint": "Liver", "sex": "Female", "bmd": "1"}]},
        "sample_counts": {"caption": "Final Sample Counts", "headers": [""] + heads,
                          "rows": [["**Female**"] + [""] * len(doses),
                                   ["  Liver"] + ["5"] * len(doses)], "footnotes": []},
        "summary": {"paragraphs": [f"{title} summary."]},
        "abstract": {"sections": [{"label": "Results", "text": f"{title} results."}]},
        "references": {"paragraphs": [f"[1] {title} reference."]},
    }


@pytest.fixture
def composed(tmp_path, monkeypatch):
    import pipeline.session_store as store
    import rendering.latex_export as latex_export
    monkeypatch.setattr(store, "SESSIONS_DIR", tmp_path)
    (tmp_path / "R").mkdir()
    (tmp_path / "R" / "studies.json").write_text(json.dumps({"rat": "R_rat", "mouse": "R_mouse"}))
    members = {"R_rat": _member("rat", "Rats", [0, 1, 10, 800], "a", "Hematology"),
               "R_mouse": _member("mouse", "Mice", [0, 10, 400], "b")}
    monkeypatch.setattr(latex_export, "load_session_data",
                        lambda sid, *a, **k: json.loads(json.dumps(members[sid])))
    data = {"abstract": {"sections": [{"label": "Background", "text": "Why."}]},
            "references": {"paragraphs": ["[1] Background reference."]}}
    assert report_compose.compose_studies(data, "R", "1,4-DCB", "106-46-7")
    return data


def test_a_single_study_session_is_left_alone(tmp_path, monkeypatch):
    import pipeline.session_store as store
    monkeypatch.setattr(store, "SESSIONS_DIR", tmp_path)
    data = {"x": 1}
    assert not report_compose.compose_studies(data, "S", "c", "n")
    assert data == {"x": 1}


def test_the_report_lists_its_studies(composed):
    assert [(s["key"], s["title"], s["dtxsid"]) for s in composed["studies"]] == [
        ("rat", "Rats", "R_rat"), ("mouse", "Mice", "R_mouse")]
    assert set(composed["studies"][0]["data"]) <= set(report_compose.STUDY_KEYS)


def test_a_combined_table_groups_rows_by_study_on_the_dose_union(composed):
    bw = composed["apical_sections"][0]
    assert list(bw["table_data"]) == ["Rats", "Mice"]
    assert bw["caption"].endswith("of Female Rats and Mice Exposed to 1,4-DCB for Five Days")
    assert [fn["letter"] for fn in bw["footnotes"]] == ["a"]
    node = DocNode(id="bw", title="BW", node_type="table", platform="Body Weight")
    plan = apical_table_plan(node, composed)
    assert plan.doses == [0, 1, 10, 400, 800]
    rats, mice = (b.rows[0].cells[1:6] for b in plan.sex_blocks)
    assert rats == ["rat0", "rat1", "rat10", "NA", "rat800"]
    assert mice == ["mouse0", "NA", "mouse10", "mouse400", "NA"]


def test_a_table_one_study_has_names_that_study_only(composed):
    hema = composed["apical_sections"][1]
    assert list(hema["table_data"]) == ["Rats"]
    assert hema["caption"].endswith("of Female Rats Exposed to 1,4-DCB for Five Days")


def test_genomic_tables_group_by_study_and_leave_the_prose_to_the_studies(composed):
    (liver,) = composed["genomics_sections"]
    assert [b["sex"] for b in liver["sexes"]] == ["Rats", "Mice"]
    assert liver["narrative"] == []


def test_one_references_list_numbered_through_the_studies(composed):
    assert composed["references"]["paragraphs"] == [
        "[1] Background reference.", "[2] Rats reference.", "[3] Mice reference."]
    rat, mouse = (s["data"]["genomics_sections"][0]["sexes"][0]["narrative"]
                  for s in composed["studies"])
    assert rat == ["rat prose [2]."] and mouse == ["mouse prose [3]."]


def test_summary_tables_and_counts_take_the_study_labels(composed):
    assert [e["sex"] for e in composed["bmd_summary"]["endpoints"]] == ["Rats", "Mice"]
    counts = composed["sample_counts"]
    assert counts["headers"] == ["", "0 ppm", "1 ppm", "10 ppm", "400 ppm", "800 ppm"]
    assert counts["rows"][2] == ["**Mice**", "", "", "", "", ""]
    assert counts["rows"][3] == ["  Liver", "5", "NA", "5", "5", "NA"]


def test_the_design_names_the_studies_together(composed):
    design = composed["study_design"]
    assert species_plural(design, capitalize=True) == "Rats and Mice"
    assert subject_phrase(design) == "rats and mice"
    assert design["route"] == "inhaled" and design["duration_days"] == 5


def test_the_abstract_states_each_study_after_the_report_background(composed):
    sections = {s["label"]: s["text"] for s in composed["abstract"]["sections"]}
    assert sections == {"Background": "Why.", "Results": "Rats results. Mice results."}
    assert composed["summary"]["paragraphs"] == ["Rats summary.", "Mice summary."]


def test_several_sexes_label_groups_by_sex_and_study():
    from rendering.report_compose import _study_sexes
    assert _study_sexes({"apical_sections": [{"table_data": {"Male": [1], "Female": [1]}}]}) == {
        "Male", "Female"}
