"""tooling/deposit_captions.py — a published study's own wording for its deposited
files, taken from its published book.

A deposited file is listed under its file name (pipeline.deposit.default_caption)
unless the study states its caption (templates/studies/<DTXSID>/deposit.yaml,
`captions:`).  For a published study that wording is the published book's: this
copies each <media> caption that differs from the file-name default into the
study's deposit.yaml, keeping any `kinds:` it states.

    python -m tooling.deposit_captions [REPORT ...]     default: every published report
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from pipeline.deposit import default_caption
from rendering.bits_bundle import _text, read_bundle
from tooling.bits_structure import BOOKSHELF, PUBLISHED

REPO_ROOT = Path(__file__).resolve().parent.parent
_XLINK_HREF = "{http://www.w3.org/1999/xlink}href"


def published_captions(report: str) -> dict[str, str]:
    """file → caption title, for every <media> of the published book."""
    out = {}
    for media in read_bundle(BOOKSHELF / report).iter("media"):
        title = media.find("caption/title")
        out[media.get(_XLINK_HREF)] = _text(title)
    return out


def write_captions(dtxsid: str, report: str) -> int:
    """Write the captions that differ from the default; return how many."""
    captions = {f: c for f, c in published_captions(report).items() if c and c != default_caption(f)}
    path = REPO_ROOT / "templates" / "studies" / dtxsid / "deposit.yaml"
    stated = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    stated = stated or {}
    header = (f"# {report}'s own wording for its deposited files (ADR-0029, pipeline.deposit):\n"
              f"# the caption each is listed under in its Supplemental Data appendix, as the\n"
              f"# published book has it (tooling.deposit_captions).  Files not named here are\n"
              f"# listed by their file name.\n")
    body = {k: v for k, v in stated.items() if k != "captions"}
    if captions:
        body["captions"] = captions
    if not body:
        return 0                                   # nothing to state
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + yaml.safe_dump(body, sort_keys=False, allow_unicode=True, width=1000),
                    encoding="utf-8")
    return len(captions)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("reports", nargs="*", help="published report names, e.g. NIEHS-10")
    args = ap.parse_args(argv)
    by_report = {r: d for d, r in PUBLISHED.items()}
    for report in args.reports or sorted(by_report):
        if not (BOOKSHELF / report / "TOC.nxml").exists():
            print(f"{report}: published bundle not downloaded")
            continue
        n = write_captions(by_report[report], report)
        print(f"{report}: {n} caption(s) differ from the file name")
    return 0


if __name__ == "__main__":
    sys.exit(main())
