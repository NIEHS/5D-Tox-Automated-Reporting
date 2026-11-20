"""The values a study's package says were left out of the analysis (ADR-0037).

The conversion leaves the named values out and marks them in the sidecars
(bmdx-pipe, packages/bmdx-pipe/tests/test_excluded_values.py).  Here: the file
check refuses a file that cannot be followed exactly, the tables note the
cells that are without a value, and the Methods state how many were left out.
"""

import json
import types

from bmdx_pipe import TableRow, tox_study_csv_to_pivot_txt
from bmdx_pipe.excluded_values import ExcludedValue, pool_excluded_values
from bmdx_pipe.file_integrator import fingerprint_file

from pipeline.excluded_values import check_excluded_values
from tables.table_builder_common import (
    detect_core_animal_availability,
    excluded_note_text,
    lettered_footnote,
    note_excluded_cell,
)

HEADER = "Animal ID,Endpoint,Observation Day,Reason,Note\n"
OW = "NTP Study Number,Concentration,Animal ID,Sex,Selection,Kidney-Right,Terminal Body Weight,Removal Day\n"
DESIGN = {"species": "mouse", "route": "inhalation", "duration_days": 5}


def _session(tmp_path, excluded_rows, organ_rows=None):
    """A session whose files/ holds an organ weight CSV's derived files and an
    excluded-values file; returns (session dir, fingerprints)."""
    files = tmp_path / "files"
    files.mkdir()
    excl = files / "Excluded_Values.csv"
    excl.write_text(HEADER + excluded_rows)
    src = tmp_path / "organ_weights_truth_female.csv"
    src.write_text(OW + (organ_rows or (
        "S,0,1,Female,Core Animals,0.13,20.0,SD5\n"
        "S,0,2,Female,Core Animals,0.14,21.0,SD5\n"
        "S,0,3,Female,Core Animals,0.12,20.5,SD5\n"
        "S,0,4,Female,Core Animals,0.06,22.2,SD5\n"
        "S,250,5,Female,Core Animals,0.15,18.0,SD5\n"
        "S,250,6,Female,Core Animals,0.14,18.5,SD5\n")))
    tox_study_csv_to_pivot_txt(str(src), str(files), "Organ Weight", "tox_study",
                               excluded=pool_excluded_values(files))
    fps = {"x1": fingerprint_file("x1", excl.name, str(excl), "csv", "2026-11-20T00:00:00+00:00")}
    return tmp_path, fps


# ── the file check ──────────────────────────────────────────────────────────

def test_a_value_that_was_left_out_is_reported_as_information(tmp_path):
    session, fps = _session(tmp_path, "4,Kidney-Right,SD5,measurement problem,\n")
    [issue] = check_excluded_values(fps, session)
    assert (issue["severity"], issue["issue_type"]) == ("info", "excluded_values_applied")
    assert "animal 4, Kidney-Right, SD5" in issue["message"]
    assert "the laboratory indicated the measurement as inadequate" in issue["message"]
    assert issue["details"]["values"][0]["value"] == "0.06"


def test_a_value_the_data_does_not_hold_is_an_error(tmp_path):
    session, fps = _session(tmp_path, "4,Kidney-Right,SD5,measurement problem,\n"
                                      "99,Kidney-Right,SD5,measurement problem,\n"   # no such animal
                                      "3,Spleen,SD5,unrelated illness,\n")           # no such endpoint
    issues = {i["issue_type"]: i for i in check_excluded_values(fps, session)}
    missing = issues["excluded_value_not_found"]
    assert missing["severity"] == "error"
    assert [r["row"] for r in missing["details"]["rows"]] == [3, 4]
    assert "nothing was left out for them" in missing["message"]
    assert "excluded_values_applied" in issues          # the row that was followed


def test_a_row_that_does_not_read_is_an_error(tmp_path):
    session, fps = _session(tmp_path, "4,Kidney-Right,SD5,looked low,\n")
    [issue] = check_excluded_values(fps, session)
    assert (issue["severity"], issue["issue_type"]) == ("error", "excluded_values_unreadable")
    assert "row 2" in issue["message"] and "not one of" in issue["message"]
    # And nothing was left out by a guess.
    side = json.load(open(session / "files" / "organ_weights_truth_female.sidecar.json"))
    assert all("excluded" not in o for a in side["animals"].values() for o in a["observations"])


def test_a_pool_without_such_a_file_has_no_issue(tmp_path):
    assert check_excluded_values({}, tmp_path) == []


# ── the tables ──────────────────────────────────────────────────────────────

def test_the_note_is_worded_as_the_book_words_it():
    # NIEHS-12 Table 3, footnote e.
    assert excluded_note_text(9, ["as published"]) == "n = 9. One value was excluded as an outlier."
    text = excluded_note_text(3, ["measurement problem", "measurement problem",
                                  "unrelated illness"])
    assert text == ("n = 3. Two values were excluded because the laboratory indicated the "
                    "measurement as inadequate. One value was excluded because the animal was "
                    "suspected of illness from causes other than exposure.")


def test_one_note_for_every_cell_with_the_same_wording():
    footnotes = [lettered_footnote("Data.", "data_format", target="header")]
    a, b = {"label": "A"}, {"label": "B"}
    note_excluded_cell(footnotes, a, 0.0, 9, ["as published"])
    note_excluded_cell(footnotes, b, 0.0, 9, ["as published"])
    note_excluded_cell(footnotes, b, 250.0, 4, ["as published"])
    assert [f["text"] for f in footnotes[1:]] == [
        "n = 9. One value was excluded as an outlier.",
        "n = 4. One value was excluded as an outlier."]
    assert a["marker_refs"]["0"] == b["marker_refs"]["0"] == footnotes[1]["id"]
    assert b["marker_refs"]["250"] == footnotes[2]["id"]


def test_the_note_stays_when_the_book_does_not_note_its_rule_made_exclusions():
    # NIEHS-12: `table_notes: outlier_exclusions: false` (its internal dose
    # outlier test is applied without a note), and Table 3 notes its one
    # stated exclusion.
    from rendering.report_data_overlays import apply_table_notes
    from tables.table_builder_common import finalize_footnotes

    footnotes = [lettered_footnote("Dixon.", "outliers")]
    row = {"label": "Kidney-Right Relative (mg/g)"}
    note_excluded_cell(footnotes, row, 0.0, 9, ["as published"])
    data = {"apical_sections": [{"footnotes": footnotes, "table_data": {"Female": [row]}}]}
    finalize_footnotes(footnotes, data["apical_sections"][0]["table_data"])
    apply_table_notes(data, {"outlier_exclusions": False})
    [kept] = data["apical_sections"][0]["footnotes"]
    assert kept["text"] == "n = 9. One value was excluded as an outlier."
    assert row["markers"] == {"0": kept["letter"]}


def _stat(label, vals, bmd="—"):
    return TableRow(label=label, values_by_dose=vals, n_by_dose={}, bmd_str=bmd, bmdl_str=bmd,
                    trend_marker="*", bmd_status=None, loel=250.0, noel=None, direction="UP",
                    responsive=True)


def test_the_organ_weight_table_notes_the_cells_without_the_value(tmp_path):
    from tables.organ_weight_table import build_organ_weight_table_from_sidecar
    from tables.table_builder_common import find_sidecar_paths

    session, _ = _session(tmp_path, "4,Kidney-Right,SD5,as published,Table 3 footnote e\n")
    stats = {"Female": [
        _stat("Terminal Body Weight", {0.0: "20.9 ± 0.5", 250.0: "18.3 ± 0.3"}),
        _stat("Kidney-Right", {0.0: "0.13 ± 0.01", 250.0: "0.15 ± 0.01*"}),
        _stat("Kidney-Right Relative", {0.0: "6.34 ± 0.1*", 250.0: "7.95 ± 0.2*"}, bmd="161.5"),
    ]}
    out = build_organ_weight_table_from_sidecar(
        find_sidecar_paths(str(session), "Organ Weight"), stats, dose_unit="ppm", design=DESIGN)
    # (The CSV records no units, so the labels end in a placeholder for them.)
    rows = {r["label"].split(" (")[0]: r for r in out["table_data"]["Female"]}
    [note] = [f for f in out["footnotes"] if "excluded" in f.get("text", "")]
    assert note["text"] == "n = 3. One value was excluded as an outlier."
    # Last, as the book prints it, and on the cell of the group it is about.
    assert note["letter"] == max(f["letter"] for f in out["footnotes"] if f.get("letter"))
    for label in ("Kidney-Right Absolute", "Kidney-Right Relative"):
        assert note["letter"] in rows[label]["markers"]["0"].split(","), label
        assert "250" not in rows[label].get("markers", {})
    # The group's n is the study's: only the cell is short.
    assert rows["n"]["values"]["0"] == "4"
    assert "0" not in rows["Terminal Body Weight"].get("markers", {})


def test_an_animal_whose_only_value_was_left_out_is_not_a_missing_sample(tmp_path):
    session, _ = _session(
        tmp_path, "4,Kidney-Right,,unrelated illness,\n4,Terminal Body Weight,,unrelated illness,\n")
    side = json.load(open(session / "files" / "organ_weights_truth_female.sidecar.json"))
    _n, _total, missing = detect_core_animal_availability({"Female": side})
    assert missing["Female"] == {}


# ── the BMD summary ─────────────────────────────────────────────────────────

def _row(label, bmd="100", responsive=True):
    return types.SimpleNamespace(
        label=label, bmd_str=bmd, bmdl_str="50", bmd_status="viable" if responsive else None,
        loel=250.0, noel=100.0, direction="DOWN", responsive=responsive)


def test_body_weights_by_study_day_are_listed_as_niehs_12_lists_them():
    from pipeline.processing_helpers import _build_apical_bmd_summary

    tables = {"Body Weight": {"Female": [
        _row("SD0", responsive=False), _row("SD1", responsive=False),
        _row("SD2", "107.8"), _row("SD3", "118.5"), _row("SD4", "133.3"),
        _row("SD5", "227.1"),                       # the terminal day: not by its day
        _row("Body Weight Gain", "159.8"),
    ]}}
    listed = [e["endpoint"] for e in _build_apical_bmd_summary(tables)]
    assert listed == ["Body Weight on Study Day 2", "Body Weight on Study Day 3",
                      "Body Weight on Study Day 4", "Body Weight Gain"]


# ── the Methods ─────────────────────────────────────────────────────────────

def test_the_statistics_subsection_ends_with_a_paragraph_built_from_the_data():
    from narrative.methods_analysis import excluded_values_paragraph
    from narrative.methods_design import _with_excluded_values
    from narrative.methods_models import MethodsContext

    stated = ("Prior to analysis, one value was excluded as an outlier. "
              "It is noted in the table it belongs to.")
    assert excluded_values_paragraph([(None, {"as published": 1})]) == stated
    assert excluded_values_paragraph([(None, None)]) is None
    assert excluded_values_paragraph([(None, {"measurement problem": 2, "unrelated illness": 1})]) == (
        "Prior to analysis, two values that the laboratory indicated as inadequate because of "
        "measurement problems were excluded and one value from an animal suspected of illness "
        "from causes other than experimental exposure was excluded. Each is noted in the table "
        "it belongs to.")

    ctx = MethodsContext(excluded_values={"as published": 1})
    written = ["Williams and Dunnett.", "LOEL and NOEL."]
    assert _with_excluded_values("stat_analysis", written, ctx) == written + [stated]
    # Built again, it replaces itself; another subsection is left as it is.
    assert _with_excluded_values("stat_analysis", written + [stated], ctx) == written + [stated]
    assert _with_excluded_values("clinical_pathology", written, ctx) == written
    # A study with nothing left out says nothing, and loses an earlier statement.
    assert _with_excluded_values("stat_analysis", written + [stated], MethodsContext()) == written


def test_the_model_is_told_to_say_nothing_about_exclusions():
    from narrative.methods_models import MethodsContext
    from narrative.methods_prompt import _stat_analysis_guideline
    from pipeline.method_profile import resolve

    ctx = MethodsContext(excluded_values={"as published": 1})
    method = resolve("ntp-5day-2025")
    ctx.method_profile, ctx.method_settings = method.profile, dict(method.values)
    assert "Do not describe any outlier test or exclusion of values." in _stat_analysis_guideline(ctx)


def test_a_report_over_several_studies_states_each_studys():
    from rendering.report_compose import _state_each_studys_excluded_values

    first = ("Prior to analysis, one value was excluded as an outlier. "
             "It is noted in the table it belongs to.")
    data = {"methods": {"sections": [
        {"key": "stat_analysis", "paragraphs": ["Williams and Dunnett.", first]},
        {"key": "bmd_apical", "paragraphs": ["BMD."]}]}}
    studies = [
        {"title": "Rats", "data": {"methods": {"excluded_values": {"as published": 1}}}},
        {"title": "Mice", "data": {"methods": {"excluded_values": {"as published": 1}}}}]
    _state_each_studys_excluded_values(data, studies)
    stat, bmd = data["methods"]["sections"]
    assert stat["paragraphs"] == [
        "Williams and Dunnett.",
        "Prior to analysis, one value was excluded as an outlier for the rats and one value "
        "was excluded as an outlier for the mice. Each is noted in the table it belongs to."]
    assert bmd["paragraphs"] == ["BMD."]
    # Only the mice's: the first study's own statement is not left standing.
    studies[0]["data"]["methods"] = {}
    _state_each_studys_excluded_values(data, studies)
    assert data["methods"]["sections"][0]["paragraphs"][-1] == (
        "Prior to analysis, one value was excluded as an outlier for the mice. "
        "It is noted in the table it belongs to.")


def test_the_methods_context_counts_the_core_values_left_out(tmp_path):
    from narrative.methods_extract import _excluded_value_counts

    session, _ = _session(tmp_path, "4,Kidney-Right,SD5,measurement problem,\n")
    assert _excluded_value_counts(str(session)) == {"measurement problem": 1}
    (session / "files" / "Excluded_Values.csv").unlink()
    assert _excluded_value_counts(str(tmp_path / "nowhere")) is None


CC = ("NTP Study Number,Concentration,Animal ID,Sex,Selection,Bile salts/acids,Albumin,"
      "Total protein,Observation Day,Terminal Flag\n")
BW = "NTP Study Number,Concentration,Animal ID,Sex,Selection,Body Weight,Observation Day,Terminal Flag\n"


def _derived(tmp_path, name, platform, text, excluded):
    files = tmp_path / "files"
    files.mkdir(exist_ok=True)
    src = tmp_path / name
    src.write_text(text)
    [out] = tox_study_csv_to_pivot_txt(str(src), str(files), platform, "tox_study",
                                       excluded=excluded)
    return out.replace(".txt", ".sidecar.json")


def _ev(animal, endpoint, day="", reason="as published"):
    return ExcludedValue(animal, endpoint, day, reason, "the book", "Excluded_Values.csv", 2)


def test_the_clinical_pathology_table_notes_the_cell_and_the_derived_ones(tmp_path):
    from tables.clinical_pathology_table import build_clinical_pathology_table_from_sidecar

    rows = "".join(f"S,{dose},{aid},Female,Core Animals,{bile},{alb},{tp},SD5,Yes\n"
                   for dose, aid, bile, alb, tp in [
                       (0, 1, 6.0, 4.1, 6.5), (0, 2, 5.0, 4.0, 6.4),
                       (10, 201, 9.0, 4.2, 6.6), (10, 202, 0, 4.1, 6.3), (10, 203, 9.6, 4.0, 6.2)])
    sidecar = _derived(tmp_path, "clin_chem_truth_female.csv", "Clinical Chemistry", CC + rows,
                       [_ev("202", "Bile salts/acids", "SD5"),
                        _ev("203", "Albumin", "SD5", "measurement problem")])
    stats = {"Female": [
        _stat("Bile salts/acids", {0.0: "5.5 ± 0.5", 10.0: "9.3 ± 0.3"}),
        _stat("Albumin", {0.0: "4.05 ± 0.05", 10.0: "4.15 ± 0.05"}),
        _stat("Total protein", {0.0: "6.45 ± 0.05", 10.0: "6.37 ± 0.12"}),
        _stat("Globulin", {0.0: "2.40 ± 0.00", 10.0: "2.30 ± 0.10"}),
    ]}
    out = build_clinical_pathology_table_from_sidecar(
        "Clinical Chemistry", {"Female": sidecar}, stats, dose_unit="ppm", design=DESIGN)
    rows = {r["label"]: r for r in out["table_data"]["Female"]}
    notes = {f["letter"]: f["text"] for f in out["footnotes"] if "excluded" in f.get("text", "")}
    assert sorted(notes.values()) == [
        "n = 2. One value was excluded as an outlier.",
        "n = 2. One value was excluded because the laboratory indicated the measurement "
        "as inadequate."]
    by_text = {t: letter for letter, t in notes.items()}
    assert rows["Bile salts/acids"]["markers"] == {
        "10": by_text["n = 2. One value was excluded as an outlier."]}
    measurement = by_text["n = 2. One value was excluded because the laboratory indicated "
                          "the measurement as inadequate."]
    assert rows["Albumin"]["markers"] == {"10": measurement}
    # Globulin is total protein minus albumin: it is without the animal too.
    assert rows["Globulin"]["markers"] == {"10": measurement}
    assert "markers" not in rows["Total protein"]
    assert rows["n"]["values"]["10"] == "3"


def test_the_body_weight_table_notes_the_day_and_the_gain(tmp_path):
    from tables.body_weight_table import build_body_weight_table_from_sidecar

    rows = "".join(f"S,{dose},{aid},Female,Core Animals,{w0},SD0,\n"
                   f"S,{dose},{aid},Female,Core Animals,{w5},SD5,Yes\n"
                   for dose, aid, w0, w5 in [(0, 1, 200.0, 210.0), (0, 2, 202.0, 150.0),
                                             (0, 3, 198.0, 209.0), (10, 4, 201.0, 211.0),
                                             (10, 5, 199.0, 208.0)])
    sidecar = _derived(tmp_path, "body_weight_truth_female.csv", "Body Weight", BW + rows,
                       [_ev("2", "Body Weight", "SD5", "unrelated illness")])
    gain = _stat("Body Weight Gain", {0.0: "10.5 ± 0.5", 10.0: "9.5 ± 0.5"})
    out = build_body_weight_table_from_sidecar(
        {"Female": sidecar}, {"Female": {"Body Weight Gain": gain}}, dose_unit="ppm",
        design=DESIGN)
    rows = {r["label"]: r for r in out["table_data"]["Female"]}
    [note] = [f for f in out["footnotes"] if "excluded" in f.get("text", "")]
    assert note["text"] == ("n = 2. One value was excluded because the animal was suspected "
                            "of illness from causes other than exposure.")
    assert rows["5"]["markers"] == {"0": note["letter"]}
    assert rows["Body Weight Gain"]["markers"] == {"0": note["letter"]}
    assert "markers" not in rows["0"]
    # The day's mean is of the two animals left.
    assert rows["5"]["values"]["0"].startswith("209.5")
