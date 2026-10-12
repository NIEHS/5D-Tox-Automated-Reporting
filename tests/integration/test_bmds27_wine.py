"""BMDS 2.7 under Wine against NTP's recorded runs — the engine's acceptance.

Every recorded dfile (NIEHS-10 by default; BMDS27_WINE_ALL=1 for NIEHS-02 …
NIEHS-10) is run through the real executables, and the output must parse to
the values NTP's run recorded. Then the whole engine (models, rules,
recommendation, high-dose drops) runs on the recorded datasets with Wine in
place of the recording. Skipped where Wine is not installed.

    pytest -m wine tests/integration/test_bmds27_wine.py
"""

import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import pipeline.bmds27 as bmds27
from pipeline.bmds27 import engine, oracle
from pipeline.bmds27.ntp_bmds import constants
from pipeline.bmds27.ntp_bmds.datasets import ContinuousDataset
from pipeline.bmds27.ntp_bmds.parser import OutputParser

pytestmark = [pytest.mark.wine,
              pytest.mark.skipif(not shutil.which("wine"), reason="Wine is not installed")]

REFERENCE = Path(__file__).resolve().parents[1] / "fixtures" / "reference"
REPORTS = ([f"NIEHS-{n:02d}" for n in range(2, 11)] if os.environ.get("BMDS27_WINE_ALL")
           else ["NIEHS-10"])
KEYS = ("BMD", "BMDL", "BMDU", "AIC", "p_value1", "p_value2", "p_value3", "p_value4",
        "residual_of_interest")


def _datasets(report):
    return oracle.load_fixture(REFERENCE / report / oracle.FIXTURE_NAME)["datasets"]


def test_engine_certifies_here():
    assert bmds27.available(), bmds27.unavailable_reason()


@pytest.mark.parametrize("report", REPORTS)
def test_executables_reproduce_every_recorded_output(report):
    ex = bmds27.executor()
    runs = [r for ds in _datasets(report) for r in ds["runs"] if r.get("outfile")]

    def one(r):
        exe, prefix, name = bmds27._exe_of(r["model_name"])
        got = ex.run(exe, r["dfile"], prefix).get("output")
        if not got:
            return f"{r['model_name']}: no output"
        want = OutputParser(r["outfile"], constants.CONTINUOUS, name).output
        have = OutputParser(got, constants.CONTINUOUS, name).output
        diff = [k for k in KEYS if want.get(k) != have.get(k)]
        return f"{r['model_name']}: " + ", ".join(f"{k} {have.get(k)} vs {want.get(k)}" for k in diff) \
            if diff else None

    with ThreadPoolExecutor(max_workers=8) as pool:
        problems = [p for p in pool.map(one, runs) if p]
    assert not problems, f"{len(problems)}/{len(runs)} differ, e.g. {problems[:5]}"


@pytest.mark.parametrize("report", REPORTS)
def test_engine_under_wine_reaches_ntps_recommendations(report):
    ex = bmds27.executor()
    for ds in _datasets(report):
        doses, ns, means, sds = zip(*oracle.dataset_rows(ds["runs"][0]["dfile"]))
        if (report, ds.get("sex"), ds.get("endpoint")) == ("NIEHS-10", "Female", "Thyroid Stimulating Hormone"):
            continue  # needs full-precision means (test_bmds27_oracle)
        session = engine.run_dataset(ContinuousDataset(doses=list(doses), ns=list(ns),
                                                       means=list(means), stdevs=list(sds)), ex)
        ours = engine.session_rows(session)
        assert [(r["doses_dropped"], r["model_index"], bool(r["recommended"])) for r in ours] == \
            [(r["doses_dropped"], r["model_index"], bool(r["recommended"])) for r in ds["runs"]], \
            f"{ds['sheet']} {ds.get('sex')} {ds.get('endpoint')}"
