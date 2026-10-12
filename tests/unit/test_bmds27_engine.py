"""BMDS 2.7 engine (pipeline.bmds27): datasets from per-animal values, the
result it reports, the rows it writes, the Wine executor and the availability
check — all without Wine (a stand-in `wine` script, or recorded runs)."""

import json
import math
import stat
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

import pytest

import pipeline.bmds27 as bmds27
from pipeline.bmds27 import binaries, engine, oracle
from pipeline.bmds27.ntp_bmds.models.base import RunStatus
from pipeline.bmds27.runner import ReplayExecutor, WineExecutor

NIEHS10 = Path(__file__).resolve().parents[1] / "fixtures" / "reference" / "NIEHS-10"


def _recorded(sex, endpoint):
    fx = oracle.load_fixture(NIEHS10 / oracle.FIXTURE_NAME)
    return next(d for d in fx["datasets"] if d["sex"] == sex and d["endpoint"] == endpoint)


def _animals(sex, column):
    import pandas as pd
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        d = pd.read_excel(NIEHS10 / "C20022-01_Individual_Animal_Hormone_Data.xlsx", sheet_name="Data")
    d = d[(d.Sex == sex) & d[column].notna()]
    return list(d.Concentration), list(d[column])


def test_full_precision_means_reproduce_the_tie_ntp_ran():
    # Female TSH: after two drops the means' change from control sums to a tie;
    # NTP's full-precision means made it negative (a decreasing restriction).
    # Built from the animals, every round's dfile is one NTP ran.
    rec = _recorded("Female", "Thyroid Stimulating Hormone")
    dataset, notes = engine.dataset_from_animals(*_animals("Female", "Thyroid Stimulating Hormone"))
    assert notes == []
    ex = ReplayExecutor(oracle.recorded_runs(rec))
    session = engine.run_dataset(dataset, ex)
    assert not ex.misses
    rows = engine.session_rows(session)
    assert [(r["doses_dropped"], r["model_index"]) for r in rows] == \
        [(r["doses_dropped"], r["model_index"]) for r in rec["runs"]]
    assert [bool(r["recommended"]) for r in rows] == [bool(r["recommended"]) for r in rec["runs"]]
    res = engine.result_of(session)
    chosen = next(r for r in rec["runs"] if r["recommended"])
    assert res["status"] == "viable" and res["bmd"] == chosen["BMD"] and res["bmdl"] == chosen["BMDL"]
    assert res["doses_dropped"] == chosen["doses_dropped"] == 5
    assert res["model_name"] == chosen["model_name"]
    assert res["bmr"] == {"type": "sd", "factor": 1.0}


def test_dataset_from_animals_counts_present_values_and_leaves_out_single_animals():
    doses = [0, 0, 0, 1, 1, 2, 2, 2, 3]
    ys = [1.0, 2.0, None, 3.0, 5.0, 2.0, float("nan"), 4.0, 9.0]
    ds, notes = engine.dataset_from_animals(doses, ys)
    assert ds.doses == [0.0, 1.0, 2.0] and ds.ns == [2, 2, 2]
    assert ds.means == [1.5, 4.0, 3.0]
    assert math.isclose(ds.stdevs[1], math.sqrt(2.0))           # n − 1
    assert notes == ["dose 3 left out: 1 animal(s)"]


def test_run_endpoints_reports_and_records_every_round():
    rec = _recorded("Female", "Thyroid Stimulating Hormone")
    doses, ys = _animals("Female", "Thyroid Stimulating Hormone")
    results, record = engine.run_endpoints(
        [{"key": "Female::Thyroid Stimulating Hormone", "sex": "Female", "platform": "Hormones",
          "endpoint": "Thyroid Stimulating Hormone", "Y": ys, "doses_per_animal": doses},
         {"key": "Female::empty", "Y": [], "doses_per_animal": []},
         {"key": "Female::two groups", "Y": [1.0, 2.0, 3.0, 4.0], "doses_per_animal": [0, 0, 1, 1]}],
        executor=ReplayExecutor(oracle.recorded_runs(rec)))
    r = results["Female::Thyroid Stimulating Hormone"]
    assert r["source"] == "bmds27" and r["status"] == "viable" and r["doses_dropped"] == 5
    assert "Female::empty" not in results
    assert results["Female::two groups"]["status"] == "NVM"
    assert "not modelled" in results["Female::two groups"]["notes"]
    rr = record["Female::Thyroid Stimulating Hormone"]
    assert rr["dataset"]["doses"] == [0.0, 0.15, 0.5, 1.4, 4.0, 12.0, 37.0, 111.0]  # before drops
    assert len(rr["runs"]) == len(rec["runs"])
    assert {r["dfile"] for r in rr["runs"]} == {r["dfile"] for r in rec["runs"]}
    json.dumps(record, default=str)


def test_no_recommended_model_is_nvm():
    rec = _recorded("Female", "Thyroid Stimulating Hormone")
    # Answer only the first round: nothing is recommended, every later round is unrecorded.
    first = {r["dfile"]: r for r in rec["runs"] if r["doses_dropped"] == 0}
    dataset, _ = engine.dataset_from_animals(*_animals("Female", "Thyroid Stimulating Hormone"))
    session = engine.run_dataset(dataset, ReplayExecutor(first))
    res = engine.result_of(session)
    assert res["status"] == "NVM" and res["bmd"] is None and res["model_name"] is None


# ── the rows the engine writes (pipeline.processing_helpers) ─────────────────

def _row(label, *, responsive, trend="", loel=None, bmd="—", status=None):
    return SimpleNamespace(label=label, responsive=responsive, trend_marker=trend, loel=loel,
                           bmd_str=bmd, bmdl_str=bmd, bmd_status=status)


class _Method:
    def __init__(self, eligibility):
        self.values = {"apical.bmd.engine": "bmds_2_7_high_dose_drop",
                       "apical.bmd.eligibility": eligibility}

    def get(self, key):
        return self.values.get(key)


@pytest.mark.parametrize("eligibility,expected", [
    ("trend_and_pairwise", {"both", "nvm"}),
    ("trend_or_pairwise", {"both", "nvm", "pairwise only", "trend only"}),
])
def test_engine_is_the_source_of_record_for_the_rows_it_models(eligibility, expected):
    from pipeline.processing_helpers import fill_rows_from_toxicr

    rows = [_row("both", responsive=True, trend="**", loel=4.0),
            _row("nvm", responsive=True, trend="*", loel=1.0),
            _row("pairwise only", responsive=False, loel=0.5, bmd="3.2", status="viable"),
            _row("trend only", responsive=False, trend="*"),
            _row("nothing", responsive=False, bmd="7.7", status="viable")]
    results = {f"Male::{r.label}": {"source": "bmds27", "status": "viable", "bmd": 1.23456,
                                    "bmdl": 0.5, "model_name": "Hill", "bmr_config": "engine_default",
                                    "bmr": {"type": "sd", "factor": 1.0}} for r in rows}
    results["Male::nvm"] = {"source": "bmds27", "status": "NVM", "bmd": None, "bmdl": None}
    n = fill_rows_from_toxicr({"Organ Weight": {"Male": rows}}, results, bmd_decimals=3,
                              method=_Method(eligibility))
    written = {r.label for r in rows if getattr(r, "_bmd_fill", None)}
    assert written == expected and n == len(expected)
    by = {r.label: r for r in rows}
    assert (by["both"].bmd_str, by["both"].bmdl_str, by["both"].bmd_status) == ("1.235", "0.500", "viable")
    assert by["both"]._bmd_fill["source"] == "bmds27"
    assert by["nvm"].bmd_str == "NVM" and by["nvm"].bmd_status == "NVM"
    # Not modelled by this method: a BMDExpress (.bm2) value does not stand in.
    assert (by["nothing"].bmd_str, by["nothing"].bmd_status) == ("—", None)


# ── the executable step ──────────────────────────────────────────────────────

FAKE_WINE = """#!{python}
import os, sys
exe, dfile = sys.argv[1], sys.argv[2]
data = open(dfile, "rb").read()
prefix = os.environ.get("FAKE_PREFIX", "")
with open(prefix + dfile.rsplit(".", 1)[0] + ".out", "w") as f:
    f.write("exe=%s crlf=%s\\n" % (os.path.basename(exe), b"\\r\\n" in data))
print("ran")
"""


def test_wine_executor_writes_the_dfile_as_windows_did_and_reads_the_named_output(tmp_path, monkeypatch):
    wine = tmp_path / "wine"
    wine.write_text(FAKE_WINE.format(python=sys.executable))
    wine.chmod(wine.stat().st_mode | stat.S_IEXEC)
    ex = WineExecutor(tmp_path, wine=str(wine))
    monkeypatch.setenv("FAKE_PREFIX", "M3")
    res = ex.run("exponential", "a\nb\n", "M3")
    assert res["status"] == RunStatus.SUCCESS
    assert res["output"] == "exe=exponential.exe crlf=True\n"
    assert res["stdout"] == "ran"
    monkeypatch.setenv("FAKE_PREFIX", "")
    assert ex.run("exponential", "a\n", "M3")["output"] is None   # not where NTP's rule looks


# ── availability ─────────────────────────────────────────────────────────────

def test_certification_passes_on_ntp_runs_and_fails_on_different_output():
    recs = json.loads(bmds27._CERTIFICATION.read_text())
    assert {r["model_name"].split("-")[0] for r in recs} >= {"Linear", "Polynomial", "Power", "Hill", "Exponential"}
    assert bmds27.certify(ReplayExecutor({r["dfile"]: r for r in recs})) == []
    bad = {r["dfile"]: {**r, "outfile": r["outfile"].replace("BMD =", "BMD = 9", 1)} for r in recs}
    assert bmds27.certify(ReplayExecutor(bad))


def test_unavailable_without_wine(monkeypatch):
    bmds27._status.cache_clear()
    monkeypatch.setattr(bmds27.shutil, "which", lambda name: None)
    try:
        assert bmds27.available() is False
        assert "Wine is not installed" in bmds27.unavailable_reason()
        with pytest.raises(RuntimeError):
            bmds27.executor()
    finally:
        bmds27._status.cache_clear()


def test_binaries_are_checked_against_the_ntp_package(tmp_path, monkeypatch):
    for name in binaries.FILES:
        (tmp_path / name).write_bytes(b"not it")
    monkeypatch.setenv("BMDS27_BIN", str(tmp_path))
    with pytest.raises(binaries.BinariesUnavailable, match="sha256 differs"):
        binaries.bin_dir()


# ── Process dispatch (pipeline.process_integrated._get_bmds) ─────────────────

def test_process_runs_the_bmds27_engine_when_the_method_asks_and_keeps_the_record(tmp_path, monkeypatch):
    import asyncio

    from pipeline import process_integrated as pi

    rec = _recorded("Female", "Thyroid Stimulating Hormone")
    doses, ys = _animals("Female", "Thyroid Stimulating Hormone")
    saved = {}
    monkeypatch.setattr(pi, "_load_cache", lambda *a: None)
    monkeypatch.setattr(pi, "_save_cache", lambda d, kind, h, data: saved.setdefault(kind, data))
    monkeypatch.setattr(pi, "_session_dir", lambda d: tmp_path)
    monkeypatch.setattr(bmds27, "executor", lambda: ReplayExecutor(oracle.recorded_runs(rec)))
    monkeypatch.setattr(pi, "run_bmds_for_endpoints",
                        lambda *a, **k: pytest.fail("the ToxicR path must not run"))
    ctx = SimpleNamespace(dtxsid="DTXSID0TEST", bmds_hash="h1", method=_Method("trend_and_pairwise"),
                          integrated={}, bmds_inputs=[{
                              "key": "Female::Thyroid Stimulating Hormone", "sex": "Female",
                              "endpoint": "Thyroid Stimulating Hormone", "platform": "Hormones",
                              "Y": ys, "doses_per_animal": doses}])
    asyncio.run(pi._get_bmds(ctx))
    assert ctx.bmds_results["Female::Thyroid Stimulating Hormone"]["source"] == "bmds27"
    assert saved["bmds"] is ctx.bmds_results
    written = json.loads((tmp_path / "bmds27_runs.json").read_text())
    assert written["bmds_hash"] == "h1"
    assert len(written["endpoints"]["Female::Thyroid Stimulating Hormone"]["runs"]) == len(rec["runs"])


def test_methods_guidance_describes_the_engine_that_ran(monkeypatch):
    from narrative import methods_prompt
    from pipeline import method_profile as mp

    monkeypatch.setattr(bmds27, "unavailable_reason", lambda: None)
    s = mp.resolve("ntp-5day-2021")
    ctx = SimpleNamespace(method_settings=s.values, method_profile=s.profile, dtxsid="",
                          has_body_weight=True, has_organ_weights=True, has_clin_chem=True,
                          has_hematology=False, has_hormones=False)
    text = methods_prompt._bmd_apical_guideline(ctx)
    assert "Benchmark Dose Software (BMDS) version 2.7.0" in text
    assert "highest dose group was removed" in text
    assert "Table D-1" in text and "R2 >=" not in text
    assert "1 standard deviation" in text


# ── Microsoft's msvcrt.dll (binaries.msvcrt_path / with_msvcrt) ──────────────

def _pe(machine=0x14C, dll=True) -> bytes:
    import struct
    head = bytearray(0x200)
    head[:2] = b"MZ"
    struct.pack_into("<I", head, 0x3C, 0x80)
    head[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<H", head, 0x84, machine)
    struct.pack_into("<H", head, 0x80 + 22, 0x2000 if dll else 0x0102)
    return bytes(head)


def test_msvcrt_must_be_a_32_bit_dll(tmp_path, monkeypatch):
    for name, data, problem in [("x64.dll", _pe(machine=0x8664), "not 32-bit"),
                                ("exe.dll", _pe(dll=False), "not a DLL"),
                                ("text.dll", b"hello", "not a Windows")]:
        (tmp_path / name).write_bytes(data)
        monkeypatch.setenv("BMDS27_MSVCRT", str(tmp_path / name))
        with pytest.raises(binaries.BinariesUnavailable, match=problem):
            binaries.msvcrt_path()
    (tmp_path / "ok.dll").write_bytes(_pe())
    monkeypatch.setenv("BMDS27_MSVCRT", str(tmp_path / "ok.dll"))
    assert binaries.msvcrt_path() == tmp_path / "ok.dll"
    monkeypatch.setenv("BMDS27_MSVCRT", str(tmp_path / "missing.dll"))
    with pytest.raises(binaries.BinariesUnavailable, match="no such file"):
        binaries.msvcrt_path()
    monkeypatch.delenv("BMDS27_MSVCRT")
    monkeypatch.setattr(binaries, "MSVCRT_DEFAULT", tmp_path / "absent.dll")
    assert binaries.msvcrt_path() is None                 # Wine's own msvcrt


def test_with_msvcrt_puts_the_dll_beside_the_executables(tmp_path, monkeypatch):
    src = tmp_path / "bin"
    src.mkdir()
    for name in binaries.FILES:
        (src / name).write_bytes(name.encode())
    monkeypatch.setattr(binaries, "FILES", {n: binaries._sha256(src / n) for n in binaries.FILES})
    (tmp_path / "msvcrt.dll").write_bytes(_pe())
    out = binaries.with_msvcrt(src, tmp_path / "msvcrt.dll")
    assert sorted(p.name for p in out.iterdir()) == sorted([*binaries.FILES, "msvcrt.dll"])
    assert binaries.with_msvcrt(src, tmp_path / "msvcrt.dll") == out      # reused


def test_wine_executor_asks_wine_for_the_native_msvcrt(tmp_path, monkeypatch):
    wine = tmp_path / "wine"
    wine.write_text("#!/bin/sh\n")
    monkeypatch.setenv("WINEDLLOVERRIDES", "mscoree,mshtml=")
    assert WineExecutor(tmp_path, wine=str(wine))._env()["WINEDLLOVERRIDES"] == "mscoree,mshtml="
    assert WineExecutor(tmp_path, wine=str(wine), native_msvcrt=True)._env()["WINEDLLOVERRIDES"] \
        == "mscoree,mshtml=;msvcrt=n,b"
