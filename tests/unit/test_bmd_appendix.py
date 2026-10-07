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
