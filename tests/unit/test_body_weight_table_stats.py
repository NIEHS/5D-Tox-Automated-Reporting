"""Each sex's body weight rows take markers and BMDs from that sex's statistics.

The builder used to key BMDs by study day alone ("SD5"), so the first
responsive sex's day-5 BMD printed in the other sex's row too.
"""

import json

from bmdx_pipe import TableRow

from tables.body_weight_table import build_body_weight_table_from_sidecar


def _sidecar(tmp_path, sex):
    animals = {}
    for i, (dose, w0, w5) in enumerate([(0, 250, 270), (0, 252, 271), (100, 251, 240), (100, 249, 238)]):
        animals[f"{sex[0]}{i}"] = {"dose": dose, "selection": "Core Animals", "observations": [
            {"day": "SD0", "endpoint": "Body Weight", "value": str(w0), "terminal": False},
            {"day": "SD5", "endpoint": "Body Weight", "value": str(w5), "terminal": True}]}
    p = tmp_path / f"body_weight_truth_{sex.lower()}.sidecar.json"
    p.write_text(json.dumps({"animals": animals}))
    return str(p)


def test_bmd_and_markers_stay_with_their_sex(tmp_path):
    male_sd5 = TableRow(label="SD5", values_by_dose={0.0: "270.5 ± 0.5**", 100.0: "239.0 ± 1.0**"},
                        bmd_str="55.0", bmdl_str="30.0", responsive=True)
    female_sd5 = TableRow(label="SD5", values_by_dose={0.0: "270.5 ± 0.5", 100.0: "239.0 ± 1.0"},
                          responsive=False)
    table = build_body_weight_table_from_sidecar(
        {"Male": _sidecar(tmp_path, "Male"), "Female": _sidecar(tmp_path, "Female")},
        stats_rows={"Male": {"SD5": male_sd5}, "Female": {"SD5": female_sd5}})
    male = {r["label"]: r for r in table["table_data"]["Male"]}
    female = {r["label"]: r for r in table["table_data"]["Female"]}
    assert (male["5"]["bmd"], female["5"]["bmd"]) == ("55.0", "ND")
    assert list(male["5"]["values"].values())[1].endswith("**")
    assert not any(v.endswith("*") for v in female["5"]["values"].values())
    # A marked cell brings the * / ** legend.
    assert any(f.get("kind") == "legend" and "significant trend test" in f["text"] for f in table["footnotes"])
