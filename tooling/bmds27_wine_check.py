"""tooling/bmds27_wine_check.py — BMDS 2.7 on this machine against NTP's recorded runs.

Runs every recorded dfile (tests/fixtures/reference/<R>/bmds27_runs.json.xz)
through the executables as pipeline.bmds27 would run them here — under Wine,
with Microsoft's msvcrt.dll when one is supplied (BMDS27_MSVCRT, or
assets/windows/msvcrt.dll) — and then the whole engine on every recorded
dataset, and reports:

  per model    runs whose BMD, BMDL and AIC parse to NTP's exactly
  per dataset  the recommended model and BMD against NTP's (identical, within
               2%, different), and each one that differs

The self-check (pipeline.bmds27.available) uses a few of these runs; this is
the whole set (ADR-0030, "Under Wine").

Usage:
    python -m tooling.bmds27_wine_check [NIEHS-10 ...]   default: NIEHS-02 … NIEHS-10
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pipeline.bmds27 as bmds27
from pipeline.bmds27 import engine, oracle
from pipeline.bmds27.ntp_bmds import constants
from pipeline.bmds27.ntp_bmds.datasets import ContinuousDataset
from pipeline.bmds27.ntp_bmds.parser import OutputParser

REFERENCE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "reference"
REPORTS = [f"NIEHS-{n:02d}" for n in range(2, 11)]
# Needs the per-animal values (test_bmds27_engine), not the dfile's 6 decimals.
PRECISION_TIE = {("NIEHS-10", "Female", "Thyroid Stimulating Hormone")}


def _model_family(name: str) -> str:
    return name if name.startswith("Exponential") else name.split("-")[0]


def _rel(a, b) -> float:
    try:
        return abs(float(a) - float(b)) / max(abs(float(b)), 1e-12)
    except (TypeError, ValueError):
        return 0.0 if a == b else float("inf")


def check(reports: list[str], ex) -> dict:
    per_model: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    datasets = []
    for report in reports:
        dss = oracle.load_fixture(REFERENCE / report / oracle.FIXTURE_NAME)["datasets"]
        runs = [r for ds in dss for r in ds["runs"] if r.get("outfile")]

        def one(r):
            exe, prefix, name = bmds27._exe_of(r["model_name"])
            got = ex.run(exe, r["dfile"], prefix).get("output")
            want = OutputParser(r["outfile"], constants.CONTINUOUS, name).output
            have = OutputParser(got, constants.CONTINUOUS, name).output if got else {}
            return _model_family(r["model_name"]), all(want.get(k) == have.get(k)
                                                       for k in ("BMD", "BMDL", "AIC"))

        with ThreadPoolExecutor(16) as pool:
            for family, same in pool.map(one, runs):
                per_model[family][0 if same else 1] += 1
        for ds in dss:
            if (report, ds.get("sex"), ds.get("endpoint")) in PRECISION_TIE:
                continue
            doses, ns, means, sds = zip(*oracle.dataset_rows(ds["runs"][0]["dfile"]))
            res = engine.result_of(engine.run_dataset(ContinuousDataset(
                doses=list(doses), ns=list(ns), means=list(means), stdevs=list(sds)), ex))
            ntp = next((r for r in ds["runs"] if r["recommended"]), None) or {}
            same = (ntp.get("model_name") == res["model_name"]
                    and _rel(res["bmd"], ntp.get("BMD")) == 0 and _rel(res["bmdl"], ntp.get("BMDL")) == 0)
            close = (not same and res["bmd"] is not None and ntp.get("BMD") is not None
                     and _rel(res["bmd"], ntp["BMD"]) <= 0.02 and _rel(res["bmdl"], ntp.get("BMDL")) <= 0.02)
            datasets.append({"report": report, "sex": ds.get("sex"), "endpoint": ds.get("endpoint"),
                             "verdict": "identical" if same else "within 2%" if close else "different",
                             "ntp": (ntp.get("model_name"), ntp.get("BMD"), ntp.get("BMDL"),
                                     ntp.get("doses_dropped")),
                             "ours": (res["model_name"], res["bmd"], res["bmdl"], res["doses_dropped"])})
    return {"per_model": dict(per_model), "datasets": datasets}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("reports", nargs="*", default=REPORTS)
    args = ap.parse_args(argv)
    ex, runtime = bmds27._wine_executor()
    print(f"BMDS 2.7 under Wine with {runtime}")
    r = check(args.reports, ex)
    total = [sum(v[i] for v in r["per_model"].values()) for i in (0, 1)]
    print(f"model runs identical to NTP's: {total[0]}/{sum(total)}")
    for family, (same, diff) in sorted(r["per_model"].items()):
        print(f"   {family:15} {same}/{same + diff}")
    verdicts = [d["verdict"] for d in r["datasets"]]
    print(f"datasets: {verdicts.count('identical')} identical, {verdicts.count('within 2%')} within 2%, "
          f"{verdicts.count('different')} different (of {len(verdicts)})")
    for d in r["datasets"]:
        if d["verdict"] != "identical":
            print(f"   {d['verdict']:9} {d['report']} {d['sex']} {d['endpoint']}: NTP {d['ntp']} | here {d['ours']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
