"""tooling/report_compare.py — the published report and ours, compared for reading.

For every published study we generate a report for (tooling.build_published_reports),
compare the published Bookshelf book (assets/cebs/_bookshelf/<REPORT>) with ours
(output/<DTXSID>/<DTXSID>-bits.zip, the chunked BITS bundle we deliver) section
by section and block by block (rendering.bits_compare), and write, per report,
into the output directory:

  <REPORT>.html            the comparison to read by eye: side by side or
                           unified, switched on the page (rendering.bits_compare_page)
  <REPORT>.diff            the conventional unified diff of the two books' flat
                           text, one hunk run per section, for any diff tool
                           (`delta`, `diff2html`, `less`, an editor)
  <REPORT>.published.txt   the flat texts that diff is taken over: one line per
  <REPORT>.generated.txt   paragraph, list item, reference or table row
  index.html               every report, by how much of its wording matches

`--fresh` renders ours from the session instead of reading the files in
output/ (what the /Compare page does), so a comparison can follow a change
before the deliverables are rebuilt.

Usage:
    python -m tooling.report_compare [DTXSID|REPORT ...] [--out output/QC/compare]
                                     [--fresh] [--context N] [--format html,diff]
Default: every published report whose generated report is on disk.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from rendering.bits_compare import compare, flat_lines, load_book, unified_diff
from rendering.bits_compare_page import render_index, render_page

REPO_ROOT = Path(__file__).resolve().parent.parent
BOOKSHELF = REPO_ROOT / "assets" / "cebs" / "_bookshelf"
OUTPUT = REPO_ROOT / "output"
DEFAULT_OUT = OUTPUT / "QC" / "compare"


def published_studies() -> dict[str, tuple[str, str]]:
    """report → (DTXSID, test article name), for every published report."""
    from tooling.build_published_reports import STUDIES
    return {report: (row[0], row[1]) for report, row in STUDIES.items()}


def resolve(names: list[str]) -> list[tuple[str, str, str]]:
    """(report, DTXSID, name) for each argument, given as a report or a DTXSID;
    every published report when none is given."""
    studies = published_studies()
    by_dtxsid = {d: r for r, (d, _) in studies.items()}
    out = []
    for n in names or list(studies):
        report = n if n in studies else by_dtxsid.get(n)
        if report is None:
            raise SystemExit(f"{n}: not a published report or its study's DTXSID")
        out.append((report, *studies[report]))
    return out


def our_source(dtxsid: str, fresh: bool):
    """What ours is read from: the session, rendered now (`fresh`), or the
    delivered bundle in output/, else the single BITS file there."""
    if fresh:
        from rendering.preview_surface import render_preview
        return render_preview(dtxsid, surface="bits")
    zipped = OUTPUT / dtxsid / f"{dtxsid}-bits.zip"
    return zipped if zipped.exists() else OUTPUT / dtxsid / f"{dtxsid}.xml"


def build(report: str, dtxsid: str, name: str, *, fresh: bool = False):
    """The comparison of one published report with ours."""
    pub_book, pub_images = load_book(BOOKSHELF / report)
    our_book, our_images = load_book(our_source(dtxsid, fresh))
    return compare(pub_book, our_book, left_images=pub_images, right_images=our_images)


def page_title(report: str, name: str) -> str:
    return f"{report} · {name} — published vs generated"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="*", help="reports (NIEHS-10) or DTXSIDs; default all")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--fresh", action="store_true",
                    help="render ours from the session rather than read output/")
    ap.add_argument("--context", type=int, default=2, help="context lines in the .diff")
    ap.add_argument("--format", default="html,diff",
                    help="comma list of html, diff (the .diff and its flat texts)")
    args = ap.parse_args(argv)
    formats = {f.strip() for f in args.format.split(",") if f.strip()}
    args.out.mkdir(parents=True, exist_ok=True)

    rows = []
    for report, dtxsid, name in resolve(args.names):
        links = []
        if not (BOOKSHELF / report / "TOC.nxml").exists():
            print(f"{report}: no published bundle in {BOOKSHELF.relative_to(REPO_ROOT)}")
            continue
        src = our_source(dtxsid, False)
        if not args.fresh and not src.exists():
            print(f"{report} ({dtxsid}): no generated report in output/")
            rows.append({"report": report, "name": name, "dtxsid": dtxsid, "sim": None,
                         "error": "not generated", "links": []})
            continue
        cmp = build(report, dtxsid, name, fresh=args.fresh)
        left = f"published/{report}"
        right = f"generated/{dtxsid}"
        if "diff" in formats:
            (args.out / f"{report}.diff").write_text(
                unified_diff(cmp, left, right, args.context), encoding="utf-8")
            for side, secs in (("published", cmp.left_order), ("generated", cmp.right_order)):
                (args.out / f"{report}.{side}.txt").write_text(
                    "\n".join(flat_lines(secs)[0]) + "\n", encoding="utf-8")
            links += [(".diff", f"{report}.diff"), ("published.txt", f"{report}.published.txt"),
                      ("generated.txt", f"{report}.generated.txt")]
        if "html" in formats:
            when = datetime.now().strftime("%Y-%m-%d %H:%M")
            source = "rendered from the session" if args.fresh else f"read from {src.relative_to(REPO_ROOT)}"
            page = render_page(
                cmp, title=page_title(report, name),
                left_label=f"Published — {report} (Bookshelf)",
                right_label=f"Generated — {dtxsid}",
                subtitle=f"{dtxsid} · ours {source} · compared {when}",
                links=tuple(links) + (("all reports", "index.html"),))
            (args.out / f"{report}.html").write_text(page, encoding="utf-8")
            links.insert(0, ("compare", f"{report}.html"))
        c = cmp.counts()
        print(f"{report} ({dtxsid}): {cmp.sim:.0%} of words match; "
              f"{c.get('changed', 0)} changed, {c.get('rewritten', 0)} rewritten, "
              f"{c.get('published-only', 0)} published only, {c.get('ours-only', 0)} ours only")
        rows.append({"report": report, "name": name, "dtxsid": dtxsid, "sim": cmp.sim,
                     "counts": c, "links": links})

    if "html" in formats and rows:
        (args.out / "index.html").write_text(render_index(
            rows, title="Published vs generated reports",
            note="Each published NIEHS/NTP report beside the one generated from its data. "
                 "Words matching = matching words over all words, both books."),
            encoding="utf-8")
    print(f"wrote {args.out.relative_to(REPO_ROOT) if args.out.is_relative_to(REPO_ROOT) else args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
