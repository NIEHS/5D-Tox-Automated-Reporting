"""The study workbooks drive the pool (ADR-0032).

A study workbook in the pool is converted at validation into the files the
pool uses: a pivot and sidecar per sex, or for clinical observations a CSV per
sex.  Every other source of the platform is set aside in _originals/, where the
value cross-check still compares it with the workbook.
"""

import filecmp
import json

from pipeline.pool_fingerprints import derived_source, ensure_fingerprints
from tables.table_builder_common import find_sidecar_paths, load_sidecar

BW = "C20022-01_Individual_Animal_Body_Weight_Data.xlsx"
CO = "C20022-01_Individual_Animal_Clinical_Observations_Data.xlsx"


def test_workbooks_alone_give_the_same_pool_files_as_the_csvs(reference_session):
    wb_only = reference_session("NIEHS-10", "DTXSID50469320", csvs=False)
    from_csv = reference_session("NIEHS-10", "DTXSID_CSV")
    for name in ("body_weight_truth_male.txt", "organ_weights_truth_female.txt",
                 "tissue_conc_truth_male.txt"):
        assert filecmp.cmp(wb_only / "files" / name, from_csv / "files" / name, shallow=False)
        a = json.loads((wb_only / "files" / name).with_suffix(".sidecar.json").read_text())
        b = json.loads((from_csv / "files" / name).with_suffix(".sidecar.json").read_text())
        assert a.pop("source") != b.pop("source") and a == b
    # Clinical observations: a CSV per sex, for the incidence tables.
    co = wb_only / "files" / "clinical_obs_truth_male.csv"
    assert derived_source(co) == CO
    assert co.read_text().split("\n", 1)[1] == \
        (from_csv / "files" / "clinical_obs_truth_male.csv").read_text()
    assert not (wb_only / "_originals").exists()


def test_a_workbook_supersedes_the_csvs(reference_session):
    session = reference_session("NIEHS-10", "DTXSID50469320", with_workbooks=True)
    sidecars = find_sidecar_paths(str(session), "Body Weight")
    assert {load_sidecar(p)["source"] for p in sidecars.values()} == {BW}
    originals = {p.name for p in (session / "_originals").iterdir()}
    assert {"body_weight_truth_male.csv", "clinical_obs_truth_male.csv"} <= originals
    files = {p.name for p in (session / "files").iterdir()}
    assert not {f for f in files if f.endswith(".units.json")}
    # Re-validating changes nothing: the derived files are recognised as the
    # workbook's, and nothing is set aside twice.
    before = sorted(p.name for p in (session / "files").iterdir())
    fps = ensure_fingerprints("DTXSID50469320", force=True)
    assert sorted(p.name for p in (session / "files").iterdir()) == before
    assert len({fp.filename for fp in fps.values()}) == len(fps)


def test_a_csv_uploaded_after_the_workbook_is_set_aside(reference_session):
    session = reference_session("NIEHS-10", "DTXSID50469320", csvs=False)
    from pipeline.pool_fingerprints import fingerprint_and_store
    csv = session / "files" / "body_weight_truth_male.csv"
    csv.write_text("NTP Study Number,Concentration,Animal ID,Sex,Selection,Body Weight,"
                   "Observation Day,Terminal Flag\nC20022-01,0,101,Male,Core Animals,1.0,SD0,\n")
    fingerprint_and_store("u1", csv.name, str(csv), "csv", "DTXSID50469320")
    assert (session / "_originals" / csv.name).exists() and not csv.exists()
    sc = load_sidecar(find_sidecar_paths(str(session), "Body Weight")["Male"])
    assert sc["source"] == BW
