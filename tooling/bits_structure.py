"""tooling/bits_structure.py — compare a generated report's BITS structure with
the published Bookshelf book of the same study, part by part.

The published side is the NCBI litarch bundle under
assets/cebs/_bookshelf/<REPORT>/ (TOC.nxml + one file per part); ours is the
BITS book in output/<DTXSID>/<DTXSID>.xml.  Both reduce to the structural
outline of rendering.bits_bundle (parts, book-part types, labels, section
titles, object placement), and the difference is printed as a unified diff
(`-` published only, `+` ours only).

    python -m tooling.bits_structure [DTXSID ...]        diff (default: every published study)
    python -m tooling.bits_structure [--reference NIEHS-10] --write-fixture
        write the published outline(s) to tests/fixtures/reference/<REPORT>/bookshelf-outline.json,
        and the files deposited with each book (name, size) to .../deposit-files.json
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

from rendering.bits_bundle import OutlineEntry, outline, read_bundle, structure_keys

REPO_ROOT = Path(__file__).resolve().parent.parent
BOOKSHELF = REPO_ROOT / "assets" / "cebs" / "_bookshelf"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "reference"

# Generated study → published report (the studies tooling.build_published_reports builds).
PUBLISHED = {
    "DTXSID1021952": "RR-8", "DTXSID1025300": "NIEHS-02", "DTXSID6024701": "NIEHS-03",
    "DTXSID3025465": "NIEHS-04", "DTXSID4028880": "NIEHS-05", "DTXSID4021391": "NIEHS-06",
    "DTXSID00190950": "NIEHS-07", "DTXSID2029905": "NIEHS-08", "DTXSID1022477": "NIEHS-09",
    "DTXSID50469320": "NIEHS-10", "DTXSID6020430": "NIEHS-12", "DTXSID1020431": "NIEHS-13",
}


def published_outline(report: str) -> list[OutlineEntry]:
    return outline(read_bundle(BOOKSHELF / report))


def generated_outline(dtxsid: str) -> list[OutlineEntry]:
    return outline(read_bundle(REPO_ROOT / "output" / dtxsid / f"{dtxsid}.xml"))


def fixture_path(report: str) -> Path:
    return FIXTURES / report / "bookshelf-outline.json"


def load_fixture(report: str) -> list[OutlineEntry]:
    rows = json.loads(fixture_path(report).read_text(encoding="utf-8"))
    return [OutlineEntry(**r) for r in rows]


def structure_diff(published: list[OutlineEntry], ours: list[OutlineEntry]) -> list[str]:
    """The `-`/`+` lines of a unified diff of the two outlines' structure keys."""
    lines = difflib.unified_diff(structure_keys(published), structure_keys(ours),
                                 lineterm="", n=0)
    return [ln for ln in lines
            if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dtxsids", nargs="*", help="generated studies (default: all published)")
    ap.add_argument("--reference", help="published report name, e.g. NIEHS-10")
    ap.add_argument("--write-fixture", action="store_true",
                    help="write the published outline (--reference, else every "
                         "published report) to tests/fixtures/reference/")
    args = ap.parse_args()

    if args.write_fixture:
        reports = [args.reference] if args.reference else [
            r for r in PUBLISHED.values() if (BOOKSHELF / r / "TOC.nxml").exists()]
        for report in reports:
            path = fixture_path(report)
            path.parent.mkdir(parents=True, exist_ok=True)
            rows = [e.to_dict() for e in published_outline(report)]
            path.write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n",
                            encoding="utf-8")
            print(f"wrote {path.relative_to(REPO_ROOT)} ({len(rows)} entries)")
            from pipeline.deposit import deposit_listing
            from tooling.build_published_reports import BOOK_OWN_FILES
            listing = deposit_listing(BOOKSHELF / report, BOOK_OWN_FILES)
            dep = path.parent / "deposit-files.json"
            dep.write_text(json.dumps(listing, indent=0, ensure_ascii=False) + "\n",
                           encoding="utf-8")
            print(f"wrote {dep.relative_to(REPO_ROOT)} ({len(listing)} files)")
        return 0

    status = 0
    for dtxsid in args.dtxsids or list(PUBLISHED):
        report = PUBLISHED.get(dtxsid)
        if report is None or not (BOOKSHELF / report).is_dir():
            print(f"== {dtxsid}: no published bundle")
            continue
        xml = REPO_ROOT / "output" / dtxsid / f"{dtxsid}.xml"
        if not xml.exists():
            print(f"== {dtxsid} ({report}): no generated BITS ({xml.relative_to(REPO_ROOT)})")
            continue
        diff = structure_diff(published_outline(report), generated_outline(dtxsid))
        print(f"== {dtxsid} ({report}): {len(diff)} differing line(s)")
        for ln in diff:
            print("  " + ln)
        status = status or (1 if diff else 0)
    return status


if __name__ == "__main__":
    sys.exit(main())
