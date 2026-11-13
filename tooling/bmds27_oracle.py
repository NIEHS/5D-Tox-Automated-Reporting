"""tooling/bmds27_oracle.py — store NTP's recorded BMDS 2.7 runs as test fixtures.

Reads each BMDS-era report's Parameter workbook(s) from assets/cebs/<R>/
(NIEHS-05's is named Model_Parameters.docx but is a workbook) and writes
tests/fixtures/reference/<R>/bmds27_runs.json.xz (pipeline.bmds27.oracle).

Usage:
    python -m tooling.bmds27_oracle [NIEHS-02 ...]      default: every report found
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from pipeline.bmds27.oracle import FIXTURE_NAME, read_workbooks, write_fixture

REPO = Path(__file__).resolve().parent.parent
CEBS = REPO / "assets" / "cebs"
FIXTURES = REPO / "tests" / "fixtures" / "reference"
REPORTS = [f"NIEHS-{n:02d}" for n in range(2, 11)]


def workbooks(report: str) -> list[Path]:
    d = CEBS / report
    found = sorted(d.glob("*_Parameter_*.xlsx")) or sorted(d.glob("Model_Parameters.xlsx"))
    return found or sorted(d.glob("Model_Parameters.docx"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("reports", nargs="*", default=REPORTS)
    args = ap.parse_args(argv)
    for report in args.reports:
        paths = workbooks(report)
        if not paths:
            print(f"{report}: no Parameter workbook in {CEBS / report}", file=sys.stderr)
            continue
        with tempfile.TemporaryDirectory() as tmp:
            readable = []
            for p in paths:  # a workbook named .docx: give pandas the right suffix
                if p.suffix != ".xlsx":
                    q = Path(tmp) / (p.stem + ".xlsx")
                    shutil.copy(p, q)
                    p = q
                readable.append(p)
            datasets = read_workbooks(readable)
        dest = FIXTURES / report / FIXTURE_NAME
        write_fixture(datasets, dest, report=report, sources=[p.name for p in paths])
        runs = sum(len(d["runs"]) for d in datasets)
        print(f"{report}: {len(datasets)} datasets, {runs} model runs → "
              f"{dest.relative_to(REPO)} ({dest.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
