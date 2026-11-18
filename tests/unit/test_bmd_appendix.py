"""Appendix D states the thresholds the apical BMD classifier applies — the
study's method profile's (ADR-0027)."""

from pipeline.method_profile import resolve
from rendering.bmd_appendix import build_bmd_acceptance_matrix


def test_table_d1_thresholds_come_from_the_method_profile():
    rows = {r[0]: r for r in build_bmd_acceptance_matrix(resolve("ntp-5day-2025"))["rows"]}
    assert rows["Goodness of fit"][2] == "0.6"
    assert rows["BMD-to-BMDL ratio"][2] == "10"
    assert rows["Low BMD"][2] == "3"
    assert all(r[3] == "NVM" for name, r in rows.items() if name != "Low BMD")


def test_table_d1_follows_a_study_overlay():
    method = resolve("ntp-5day-2025", overlay={"apical": {"bmd": {"acceptance": {
        "r2_min": 0.5, "bmd_bmdl_max": 20.0, "bmd_above_highest_dose": "keep",
        "not_reportable_fraction": 0.1}}}})
    rows = {r[0]: r for r in build_bmd_acceptance_matrix(method)["rows"]}
    assert (rows["Goodness of fit"][2], rows["BMD-to-BMDL ratio"][2], rows["Low BMD"][2]) \
        == ("0.5", "20", "10")
    assert "High BMD" not in rows


def test_appendix_d_no_longer_describes_bmds_27():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2] / "templates" / "freeform"
    for name in ("appendix-d.html", "appendix-d.tex"):
        text = (root / name).read_text(encoding="utf-8")
        assert "BMDS 2.7" not in text and "Table D-1" not in text


def test_matrix_col_widths_become_ragged_p_columns():
    from rendering.latex_generator import _matrix_colspec
    assert _matrix_colspec({}, 3, "lcc") == "lcc"
    spec = _matrix_colspec({"col_widths": [0.2, None]}, 3, "lcc")
    assert spec == r">{\raggedright\arraybackslash}p{0.2\linewidth} c c"


def test_docx_freeform_text_decodes_entities():
    from types import SimpleNamespace
    from rendering.docx_generator import _freeform_text
    node = SimpleNamespace(resolved_content={"html": "<p>the study&rsquo;s Table&nbsp;1</p>"},
                           representation="html")
    assert _freeform_text(node) == "the study’s Table 1"


def test_a_replaced_engine_is_noted_under_the_table(monkeypatch):
    """RR-8 and NIEHS-02 … 10 pin BMDS 2.7; ToxicR runs.  Their definitions
    title Appendix D for the BMDS rules, so the table says they were not
    applied (it was recorded only in the log)."""
    from pipeline import bmds27

    monkeypatch.setattr(bmds27, "unavailable_reason", lambda: "no Wine")
    matrix = build_bmd_acceptance_matrix(resolve("ntp-5day-2021.1"))
    assert matrix["caption"] == "Benchmark Dose Acceptance Criteria for Apical Endpoints"
    note = matrix["footnotes"][-1]["text"]
    assert "(ntp-5day-2021.1) selects a model by the model recommendation rules of the " \
           "Benchmark Dose Software (BMDS) version 2.7.0" in note
    assert "Those rules were not applied" in note and "no Wine" not in note
    # A study whose own method is the one in force has no such note.
    assert len(build_bmd_acceptance_matrix(resolve("ntp-5day-2025.1"))["footnotes"]) == 1


def test_the_bmds_engine_prints_its_own_rules(monkeypatch):
    from pipeline import bmds27

    monkeypatch.setattr(bmds27, "unavailable_reason", lambda: None)
    matrix = build_bmd_acceptance_matrix(resolve("ntp-5day-2021.1"))
    assert matrix["caption"].startswith("Benchmark Dose Model Recommendation/Selection Rules")
    rows = {r[0]: r[1:] for r in matrix["rows"]}
    assert rows["GGOF"] == ["0.1", "Warning"] and rows["BMD exists"] == ["NA", "Failure"]
    assert "Goodness of fit" not in rows and "BMDU exists" not in rows
