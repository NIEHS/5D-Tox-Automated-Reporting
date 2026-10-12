"""BMDS 2.7 engine against NTP's recorded runs (CEBS Parameter workbooks,
NIEHS-02 … NIEHS-10): NTP's package, with only the executable step answered
from the recording, must write the same dfiles and reach the same rule bins,
recommendations, BMDs and high-dose drops.

The dataset is rebuilt from the recorded dfile (6-decimal means). One recorded
dataset turns on the means' last bits (NIEHS-10 female TSH: after two drops
the change from control is a tie, and NTP's full-precision means made it
negative); it is reproduced from the per-animal data in test_bmds27_engine."""

from pathlib import Path

import pytest

from pipeline.bmds27 import engine, oracle
from pipeline.bmds27.ntp_bmds import constants
from pipeline.bmds27.ntp_bmds.datasets import ContinuousDataset
from pipeline.bmds27.runner import ReplayExecutor

REFERENCE = Path(__file__).resolve().parents[1] / "fixtures" / "reference"
REPORTS = [f"NIEHS-{n:02d}" for n in range(2, 11)]
# Needs full-precision means (see the module docstring).
PRECISION_TIE = {("NIEHS-10", "Female", "Thyroid Stimulating Hormone")}


def _cases():
    for report in REPORTS:
        fx = oracle.load_fixture(REFERENCE / report / oracle.FIXTURE_NAME)
        for ds in fx["datasets"]:
            ident = (report, ds.get("sex"), ds.get("endpoint"))
            marks = [pytest.mark.xfail(strict=True, reason="needs full-precision means")] \
                if ident in PRECISION_TIE else []
            yield pytest.param(report, ds, marks=marks,
                               id=f"{report}-{ds['sheet']}-{ds['dataset_index']}-{ds.get('sex')}")


def _same_number(ours, recorded) -> bool:
    if isinstance(ours, str) or isinstance(recorded, str):  # "-", Windows "1.#QNAN"
        return str(ours) == str(recorded)
    if recorded is None or ours is None:
        return recorded is None and ours is None
    return abs(float(ours) - float(recorded)) <= 1e-9 * max(1.0, abs(float(recorded)))


@pytest.mark.parametrize("report,ds", list(_cases()))
def test_engine_reproduces_ntp_recorded_runs(report, ds):
    first = ds["runs"][0]["dfile"]
    doses, ns, means, sds = zip(*oracle.dataset_rows(first))
    dataset = ContinuousDataset(doses=list(doses), ns=list(ns), means=list(means), stdevs=list(sds))
    ex = ReplayExecutor(oracle.recorded_runs(ds))
    session = engine.run_dataset(dataset, ex)
    ours = engine.session_rows(session)

    assert not ex.misses, f"{len(ex.misses)} dfiles NTP never ran"
    assert [(r["doses_dropped"], r["model_index"]) for r in ours] == \
        [(r["doses_dropped"], r["model_index"]) for r in ds["runs"]]
    for o, r in zip(ours, ds["runs"]):
        where = f"drop {r['doses_dropped']} {r['model_name']}"
        assert o["model_name"] == r["model_name"], where
        assert o["dfile"] == r["dfile"], where
        assert o["logic_bin"] == r["logic_bin"], where
        assert bool(o["recommended"]) == bool(r["recommended"]), where
        for k in ("BMD", "BMDL", "AIC"):
            assert _same_number(o[k], r[k]), f"{where} {k}: {o[k]} vs {r[k]}"


def test_every_bmds_era_report_has_an_oracle():
    counts = {r: len(oracle.load_fixture(REFERENCE / r / oracle.FIXTURE_NAME)["datasets"])
              for r in REPORTS}
    assert all(counts.values()), counts
    assert sum(counts.values()) == 173


def test_bin_text_is_ntps():
    assert constants.BIN_TEXT == {0: "valid", 1: "warning", 2: "failure"}
