"""tooling/bmds27_conformance.py — our apical datasets against NTP's BMDS 2.7 runs.

For a BMDS-era report, compares the session's apical endpoints (the per-animal
values Process models, from the newest `_cache_ntp_*.json`) with the datasets
NTP's package modelled (tests/fixtures/reference/<R>/bmds27_runs.json.xz):

  datasets     each NTP dataset matched to our endpoint by sex and name, and our
               dataset — N, mean, SD per dose as pipeline.bmds27.engine builds it,
               printed as the dfile prints it — against NTP's dfile
  eligibility  which of our endpoints NTP modelled, against the significance our
               statistics found (trend; any pairwise), to settle the rule

Usage:
    python -m tooling.bmds27_conformance [NIEHS-10 ...]   default: NIEHS-02 … NIEHS-10
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

from pipeline.bmds27 import engine, oracle

REPO = Path(__file__).resolve().parent.parent
REFERENCE = REPO / "tests" / "fixtures" / "reference"
REPORTS = [f"NIEHS-{n:02d}" for n in range(2, 11)]


def _norm(name: str) -> str:
    n = re.sub(r"\s+", " ", (name or "").lower()).strip()
    n = re.sub(r"\b(absolute|weight)\b|\(measured\)", "", n)
    return re.sub(r"\s+", " ", n).strip()


def _session_of(report: str) -> str | None:
    from tooling.build_published_reports import STUDIES
    entry = dict(STUDIES).get(report)
    return entry[0] if entry else None


def _ntp_rows(dtxsid: str) -> dict:
    from common.paths import SESSIONS_DIR
    caches = glob.glob(str(SESSIONS_DIR / dtxsid / "_cache_ntp_*.json"))
    if not caches:
        return {}
    return json.loads(Path(max(caches, key=os.path.getmtime)).read_text())


def _significance(row: dict) -> tuple[bool, bool]:
    trend = bool(row.get("trend_marker"))
    pairwise = any("*" in str(v) for d, v in (row.get("values_by_dose") or {}).items()
                   if float(d) != 0)
    return trend, pairwise


def _fmt(rows) -> list[str]:
    return [f"{d:f} {n} {m:f} {s:f}" for d, n, m, s in rows]


def check(report: str) -> dict:
    dtxsid = _session_of(report)
    fx = oracle.load_fixture(REFERENCE / report / oracle.FIXTURE_NAME)
    ntp = _ntp_rows(dtxsid) if dtxsid else {}
    ours = {}
    for platform, by_sex in ntp.items():
        for sex, rows in by_sex.items():
            for row in rows:
                if row.get("_bmds_input"):
                    ours[(sex.lower(), _norm(row["label"]))] = (platform, row)
    out = {"report": report, "session": dtxsid, "datasets": [], "unmatched": []}
    modelled = set()
    for ds in fx["datasets"]:
        key = ((ds.get("sex") or "").lower(), _norm(ds.get("endpoint")))
        hit = ours.get(key)
        if hit is None:
            out["unmatched"].append(f"{ds.get('sex')} {ds.get('endpoint')}")
            continue
        modelled.add(key)
        bi = hit[1]["_bmds_input"]
        dataset, notes = engine.dataset_from_animals(bi["doses_per_animal"], bi["Y"])
        theirs = _fmt(oracle.dataset_rows(ds["runs"][0]["dfile"]))
        mine = _fmt(zip(dataset.doses, dataset.ns, dataset.means, dataset.stdevs))
        out["datasets"].append({"endpoint": f"{ds.get('sex')} {ds.get('endpoint')}",
                                "same": mine == theirs, "ours": mine, "ntp": theirs,
                                "notes": notes})
    table = Counter()
    for key, (platform, row) in ours.items():
        if platform == "Body Weight" and row["label"] != "Body Weight Gain":
            continue
        trend, pairwise = _significance(row)
        table[(key in modelled, trend, pairwise, bool(row.get("responsive")))] += 1
    out["eligibility"] = [{"modelled": m, "trend": t, "pairwise": p, "responsive": r, "n": n}
                          for (m, t, p, r), n in sorted(table.items())]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("reports", nargs="*", default=REPORTS)
    ap.add_argument("--verbose", "-v", action="store_true", help="print differing datasets")
    args = ap.parse_args(argv)
    for report in args.reports:
        r = check(report)
        same = sum(d["same"] for d in r["datasets"])
        print(f"{report} ({r['session']}): datasets {same}/{len(r['datasets'])} identical; "
              f"{len(r['unmatched'])} NTP datasets without an endpoint of ours")
        for u in r["unmatched"]:
            print(f"   unmatched: {u}")
        for d in r["datasets"]:
            if not d["same"] and args.verbose:
                print(f"   differs: {d['endpoint']} {d['notes']}\n      ours {d['ours']}\n      ntp  {d['ntp']}")
            elif not d["same"]:
                print(f"   differs: {d['endpoint']}")
        print("   eligibility  modelled trend pairwise responsive  n")
        for e in r["eligibility"]:
            print(f"                {e['modelled']!s:8} {e['trend']!s:5} {e['pairwise']!s:8} "
                  f"{e['responsive']!s:10} {e['n']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
