#!/usr/bin/env python3
"""tooling/bookshelf_preview.py — CLI for the Bookshelf-style preview renderer.

Thin wrapper over rendering.bookshelf_preview: read a BITS book — a <book> XML
(the artifact jats_generator.generate_bits produces) or a chunked Bookshelf
bundle directory (TOC.nxml + one file per part: our `bits` surface unzipped, or
a published book from assets/cebs/_bookshelf/<REPORT>) — and write a Bookshelf
reader-view lookalike HTML file.  Rendering ours and the published book of the
same study through it gives a side-by-side comparison.  See the rendering
module for the fidelity caveats.

Usage:
    python -m tooling.bookshelf_preview output/DTXSID50469320/DTXSID50469320.xml \
        -o output/DTXSID50469320-bookshelf-preview.html
    python -m tooling.bookshelf_preview assets/cebs/_bookshelf/NIEHS-10 \
        -o output/NIEHS-10-published-bookshelf-preview.html
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rendering.bookshelf_preview import render_book_file


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("xml", type=Path,
                    help="BITS <book> XML, or a chunked bundle directory (TOC.nxml + parts)")
    ap.add_argument("-o", "--out", type=Path, default=None,
                    help="output HTML path (default: <xml stem>-bookshelf-preview.html)")
    args = ap.parse_args()
    out = args.out or args.xml.with_name(args.xml.stem + "-bookshelf-preview.html")
    html_text = render_book_file(args.xml)
    out.write_text(html_text, encoding="utf-8")
    print(f"wrote {out} ({len(html_text):,} bytes)")


if __name__ == "__main__":
    main()
