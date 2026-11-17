"""The report states the apical BMD method that was computed (2026-11-17).

One record (tables.apical_bmds.apical_bmd_method) of where each assay's BMDs
come from and the settings in force; the Methods paragraph
(narrative.methods_analysis) and the legends are built from it.  Before, the
paragraph was written from a guideline that named one engine, "constant
variance" and the method profile's BMR for every study, the legends said "one
standard deviation" as a literal, and a pinned method this tool cannot run was
replaced with only a log line to say so.
"""

import pytest

from narrative.methods_analysis import build_bmd_apical
from narrative.methods_models import MethodsContext
from pipeline import method_profile as mp
from tables.apical_bmds import (
    apical_bmd_method, bmd_terms, bmr_phrase, bmr_tag, platform_bmrs,
)

SD1 = {"type": "SD", "factor": 1.0}
RD25 = {"type": "RD", "factor": 0.25}


def _result(source, bmr_type, factor, variance="Constant Variance: 1"):
    notes = [f"Data Source: {source}", "BMDExpress3 Version: BMDExpress 3.20.0156 BETA",
             "Model Averaging Method: Laplace Model Averaging",
             "Models fit: hill, power, exponential 3, exponential 5",
             f"BMR Type: {bmr_type}", f"BMR Factor: {factor}"]
    return {"analysisInfo": {"notes": notes + ([variance] if variance else [])}}


def _integrated(*results):
    return {"bMDResult": list(results)}


PLATFORMS = {"Body Weight": ["Female", "Male"], "Clinical Chemistry": ["Female", "Male"],
             "Hormones": ["Female", "Male"]}
RECORDED = _integrated(
    _result("female_body_weight", "Standard Deviation", 1.0),
    _result("male_body_weight", "Standard Deviation", 1.0),
    _result("female_clin_chem", "Relative Deviation", 0.25),
    _result("male_clin_chem", "Relative Deviation", 0.25),
)


def _ctx(record, method, **kw):
    return MethodsContext(method_settings=dict(method.values), method_profile=method.profile,
                          sexes=["Female", "Male"], apical_bmd_method=record,
                          method_substitutions=[dict(x) for x in method.substitutions], **kw)


def test_the_record_separates_recorded_from_inferred():
    method = mp.resolve("ntp-5day-2025.1")
    record = apical_bmd_method(RECORDED, method, PLATFORMS)
    assert record["engine"] == "toxicr_model_average"
    by_source = [(s["source"], s["bmr"], sorted(s["platforms"])) for s in record["settings"]]
    assert by_source == [("recorded", SD1, ["Body Weight"]),
                         ("recorded", RD25, ["Clinical Chemistry"]),
                         ("inferred", SD1, ["Hormones"])]
    recorded = record["settings"][0]
    assert recorded["analysis"] == {
        "software": "BMDExpress 3.20.0156 BETA", "selection": "Laplace Model Averaging",
        "models": ["hill", "power", "exponential 3", "exponential 5"],
        "constant_variance": True}
    assert recorded["constant_variance"] is True
    assert platform_bmrs(record, "Clinical Chemistry") == [RD25]
    assert platform_bmrs(record, "Hematology") == []


def test_the_variance_stated_is_the_variance_fit():
    """A project that records a BMR but no variance note is fit with
    nonconstant variance (tables.apical_bmds._parse_notes); the record and the
    paragraph say so, and say the project does not record it."""
    method = mp.resolve("ntp-5day-2025.1")
    integrated = _integrated(_result("male_body_weight", "Standard Deviation", 1.0, variance=None))
    record = apical_bmd_method(integrated, method, {"Body Weight": ["Male"]})
    setting = record["settings"][0]
    assert setting["constant_variance"] is False
    assert setting["analysis"]["constant_variance"] is None
    text = " ".join(build_bmd_apical(_ctx(record, method)))
    assert "a variance setting the project does not record" in text
    assert "models with nonconstant variance at the same BMR" in text
    assert "with constant variance" not in text


def test_the_paragraph_states_each_source_and_its_settings():
    method = mp.resolve("ntp-5day-2025.1")
    text = " ".join(build_bmd_apical(_ctx(apical_bmd_method(RECORDED, method, PLATFORMS), method)))
    assert "are those of the study's BMDExpress analysis (BMDExpress 3.20.0156 BETA)" in text
    assert "the body weight endpoints, at a benchmark response (BMR) of 1 standard deviation" in text
    assert "the clinical chemistry endpoints, at a BMR of 25% relative deviation" in text
    assert "record no BMD analysis of the hormone endpoints" in text
    assert "its R² was below 0.6, its BMD/BMDL ratio was above 10, or its BMD was above" in text
    assert "For body weight, the BMD" in text and "specified for this study" not in text


def test_a_method_this_tool_cannot_run_is_stated_in_the_methods(monkeypatch):
    from pipeline import bmds27

    monkeypatch.setattr(bmds27, "unavailable_reason", lambda: "no Wine")
    method = mp.resolve("ntp-5day-2021.1")
    assert {s["setting"]: (s["asked"], s["used"]) for s in method.substitutions} == {
        "apical.bmd.engine": ("bmds_2_7_high_dose_drop", "toxicr_model_average"),
        "apical.bmd.eligibility": ("all_endpoints", "trend_and_pairwise")}
    record = apical_bmd_method({}, method, {"Organ Weight": ["Male"]})
    assert [s["source"] for s in record["settings"]] == ["inferred"]
    paragraphs = build_bmd_apical(_ctx(record, method))
    assert "ToxicR Laplace model averaging" in paragraphs[0] and "BMDS" not in paragraphs[0]
    assert "organ weight (male) endpoints" in paragraphs[0]
    assert "For body weight" not in paragraphs[0]
    assert ("The analysis method specified for this study (ntp-5day-2021.1) computes these "
            "BMDs with the Benchmark Dose Software (BMDS) version 2.7.0; it could not be run "
            "where this report was produced.") in paragraphs[1]
    assert "are not the results of that software" in paragraphs[1]
    assert "no Wine" not in paragraphs[1]
    assert "That method reports a BMD for every endpoint modeled" in paragraphs[1]


def test_a_context_without_the_record_is_refused():
    from narrative.methods_design import refresh_data_built
    from workflow.errors import StepError

    old = MethodsContext(dosing_days=5, dosing_schedule="once daily", dose_unit="mg/kg").to_dict()
    with pytest.raises(StepError, match="run Process again"):
        refresh_data_built([{"key": "bmd_apical", "paragraphs": ["ToxicR, constant variance"]}],
                           old)


def test_the_paragraph_is_never_asked_of_the_model():
    from narrative.methods_design import DATA_BUILT_KEYS
    from narrative.methods_prompt import _build_subsection_guidelines

    assert "bmd_apical" in DATA_BUILT_KEYS
    method = mp.resolve("ntp-5day-2025.1")
    ctx = _ctx(apical_bmd_method({}, method, {}), method, dosing_days=5,
               dosing_schedule="once daily", dose_unit="mg/kg")
    guides = _build_subsection_guidelines(ctx, [("bmd_apical", "x", 4), ("stat_analysis", "y", 4)])
    assert "- bmd_apical:" not in guides and "- stat_analysis:" in guides


def test_bmr_words_and_tags_assume_nothing():
    assert (bmr_phrase(SD1), bmr_tag(SD1)) == ("1 standard deviation", "1Std")
    assert (bmr_phrase(RD25), bmr_tag(RD25)) == ("25% relative deviation", "rd25")
    assert bmr_phrase({"type": "SD", "factor": 2.0}) == "2 standard deviations"
    assert (bmr_phrase(None), bmr_tag(None), bmr_tag({})) == (None, "", "")


def test_the_legend_defines_the_bmr_that_was_fit():
    from tables.table_builder_common import bmd_definition_footnote

    one = bmd_definition_footnote([SD1])
    assert one["bmrs"] == [SD1] and one["text"] == (
        "BMD₁Std = benchmark dose corresponding to a benchmark response set to one standard "
        "deviation from the mean; BMDL₁Std = benchmark dose lower confidence limit "
        "corresponding to a benchmark response set to one standard deviation from the mean; "
        "NA = not applicable; ND = not determined.")
    assert bmd_definition_footnote(None) == {
        "kind": "definition", "bmrs": [],
        "text": "BMD = benchmark dose; BMDL = benchmark dose lower confidence limit; "
                "NA = not applicable; ND = not determined."}
    assert bmd_terms([RD25]).startswith(
        "BMDrd25 = benchmark dose corresponding to a benchmark response set to a 25% "
        "relative deviation from the control mean")
    mixed = bmd_terms([SD1, RD25])
    assert mixed.startswith("BMD = benchmark dose; BMDL = benchmark dose lower confidence limit")
    assert "one standard deviation from the mean or a 25% relative deviation" in mixed
    assert bmd_terms(None) == "BMD = benchmark dose; BMDL = benchmark dose lower confidence limit"


# ── The eFDR subsection says what the report has ─────────────────────────────

def test_the_efdr_subsection_says_whether_the_report_has_the_analysis():
    from narrative.methods_analysis import efdr_paragraphs
    from rendering.genomics_appendix import _state_efdr_in_methods

    [none] = efdr_paragraphs(False)
    assert none.startswith("No empirical false discovery rate analysis")
    [has] = efdr_paragraphs(True, "D-1")
    assert "are reported with Table D-1" in has and "not included" not in has

    # A report whose session holds the analysis states it, whatever the
    # study's own Methods said (a composed report: NIEHS-12, 13).
    data = {"methods": {"sections": [
        {"key": "efdr", "heading": "eFDR", "paragraphs": [none]},
        {"key": "chemistry", "paragraphs": ["x"]}]}}
    _state_efdr_in_methods(data, [], {"tissues": [{"species": "rat"}]})
    efdr, chemistry = data["methods"]["sections"]
    assert efdr["paragraphs"][0].startswith("The empirical false discovery rate of the genomic")
    assert efdr["heading"] == "eFDR" and chemistry["paragraphs"] == ["x"]
    _state_efdr_in_methods(data, [], None)
    assert data["methods"]["sections"][0]["paragraphs"] == [none]


def test_a_composed_report_states_each_studys_bmd_method_when_they_differ():
    from rendering.report_compose import _state_each_studys_bmd_method

    def study(title, text):
        return {"title": title, "data": {"methods": {"sections": [
            {"key": "bmd_apical", "paragraphs": [text]}]}}}

    data = {"methods": {"sections": [{"key": "bmd_apical", "paragraphs": ["A"]},
                                     {"key": "chemistry", "paragraphs": ["c"]}]}}
    _state_each_studys_bmd_method(data, [study("Rats", "A"), study("Mice", "A")])
    assert data["methods"]["sections"][0]["paragraphs"] == ["A"]
    _state_each_studys_bmd_method(data, [study("Rats", "A"), study("Mice", "B")])
    assert data["methods"]["sections"][0]["paragraphs"] == ["Rats. A", "Mice. B"]
    assert data["methods"]["sections"][1]["paragraphs"] == ["c"]


def test_the_export_takes_its_gene_set_cutoffs_from_the_studys_method(monkeypatch):
    """Fixed defaults (20 to 500 genes) stood in the export path; the 2018
    method the Methods state reports gene sets of 10 to 250 genes."""
    from rendering import latex_export

    monkeypatch.setattr(mp, "session_method", lambda dtxsid, **kw: mp.resolve("ntp-5day-2018"))
    assert latex_export._resolve_go_cutoffs("DTXSID_X", None) == {
        "go_pct": 5, "go_min_genes": 10, "go_max_genes": 250, "go_min_bmd": 3}
