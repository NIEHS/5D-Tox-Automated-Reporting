"""Body Weight Gain is derived at ingest — Core animals, first to last study day.

NIEHS reports and models it (BMD/LOEL/NOEL summaries; NIEHS-13's own
BMDExpress input holds exactly the Core animals weighed on both days).
"""

from bmdx_pipe import tox_study_csv_to_pivot_txt

HEADER = "NTP Study Number,Concentration,Animal ID,Sex,Selection,Body Weight,Observation Day,Terminal Flag\n"


def _pivot(tmp_path, rows: str) -> dict[str, dict[str, str]]:
    csv = tmp_path / "body_weight_truth_male.csv"
    csv.write_text(HEADER + rows)
    [out] = tox_study_csv_to_pivot_txt(str(csv), str(tmp_path), "Body Weight", "tox_study")
    lines = [ln.split("\t") for ln in open(out).read().splitlines() if not ln.startswith("#")]
    animals = lines[0][1:]
    return {r[0]: dict(zip(animals, r[1:])) for r in lines[2:]}


def test_gain_is_last_minus_first_day_for_core_animals(tmp_path):
    rows = _pivot(tmp_path,
                  "S,0,1,Male,Core Animals,296.5,SD0,\n"
                  "S,0,1,Male,Core Animals,311.0,SD5,Yes\n"
                  "S,4,2,Male,Core Animals,292.6,SD0,\n"
                  "S,4,2,Male,Core Animals,308.2,SD5,Yes\n"
                  "S,4,3,Male,Biosampling Animals,290.0,SD0,\n"     # weighed both days, not Core
                  "S,4,3,Male,Biosampling Animals,300.0,SD5,Yes\n"
                  "S,4,4,Male,Core Animals,280.0,SD0,\n"            # died: no SD5 weight
                  "S,4,4,Male,Core Animals,270.0,SD1,Yes\n")
    gain = rows["Body Weight Gain"]
    assert float(gain["1"]) == 14.5 and float(gain["2"]) == 15.6
    assert "3" not in gain                     # Biosampling: not in the pivot at all
    assert gain["4"] == "NaN"
    assert "SD0" in rows and "SD5" in rows   # the day rows are unchanged


def test_no_gain_with_a_single_study_day(tmp_path):
    rows = _pivot(tmp_path, "S,0,1,Male,Core Animals,296.5,SD0,Yes\n")
    assert "Body Weight Gain" not in rows
