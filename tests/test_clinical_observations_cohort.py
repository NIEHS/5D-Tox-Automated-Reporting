"""Clinical-observation incidence counts the Core cohort only, by default.

The NTP I05 summary reports Core and biosampling animals separately; the
CEBS packages spell the latter "Biosampling Animals" (NIEHS-10) or
"Biosample Animals" (NIEHS-07/-12/-13).
"""

from bmdx_pipe.clinical_observations import build_clinical_obs_tables

_CSV = """NTP Study Number,Concentration,Animal ID,Sex,Selection,Observation Day,Observation,Site,Modifier,Severity
1,0,1,Female,Core Animals,SD0,Normal,,,
1,800,2,Female,Core Animals,SD0,Tremors,,,Moderate
1,800,3,Female,Core Animals,SD0,Normal,,,
1,800,11,Female,Biosample Animals,SD1,Ataxia,,,Moderate
1,800,12,Female,Biosampling Animals,SD0,Tremors,,,Moderate
"""


def test_core_cohort_only_by_default(tmp_path):
    path = tmp_path / "clin.csv"
    path.write_text(_CSV)
    rows = {r.label: r for r in build_clinical_obs_tables([str(path)])["Female"]}
    assert set(rows) == {"Tremors (Moderate)"}
    assert rows["Tremors (Moderate)"].incidence_by_dose == {0.0: "0/1", 800.0: "1/2"}


def test_biosampling_cohort_on_request(tmp_path):
    path = tmp_path / "clin.csv"
    path.write_text(_CSV)
    rows = {r.label: r for r in build_clinical_obs_tables([str(path)], include_biosampling=True)["Female"]}
    assert rows["Tremors (Moderate)"].incidence_by_dose[800.0] == "2/4"
    assert "Ataxia (Moderate)" in rows


def test_onset_day_is_the_earliest_observation_per_dose(tmp_path):
    path = tmp_path / "clin.csv"
    path.write_text(_CSV + "1,800,3,Female,Core Animals,SD2,Tremors,,,Moderate\n"
                           "1,800,2,Female,Core Animals,SD3,Tremors,,,Moderate\n")
    row = build_clinical_obs_tables([str(path)])["Female"][0]
    assert row.onset_day_by_dose == {800.0: 0}


def test_a_row_keeps_the_columns_its_label_is_built_from(tmp_path):
    """Prose can't parse "Discharge — Eye, Bilateral, Red" back: is "Eye" a
    site or a modifier?  The row keeps the four columns."""
    path = tmp_path / "clin.csv"
    path.write_text(_CSV + "1,800,3,Female,Core Animals,SD2,Discharge,Eye,\"Bilateral, Red\",\n")
    rows = {r.label: r for r in build_clinical_obs_tables([str(path)])["Female"]}
    assert rows["Discharge — Eye, Bilateral, Red"].parts == {
        "observation": "Discharge", "site": "Eye", "modifier": "Bilateral, Red", "severity": ""}
    assert rows["Tremors (Moderate)"].parts["severity"] == "Moderate"
