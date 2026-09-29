#!/usr/bin/env python3
"""tooling/bookshelf_preview.py — CLI for the Bookshelf-style preview renderer.

Thin wrapper over rendering.bookshelf_preview: read a BITS <book> XML (the
artifact jats_generator.generate_bits produces) and write a Bookshelf reader-view
lookalike HTML file.  See the rendering module for the fidelity caveats.

Usage:
    python -m tooling.bookshelf_preview output/DTXSID50469320-report.xml \
        -o output/DTXSID50469320-bookshelf-preview.html
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rendering.bookshelf_preview import render_book_file


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("xml", type=Path, help="BITS <book> XML (generate_bits output)")
    ap.add_argument("-o", "--out", type=Path, default=None,
                    help="output HTML path (default: <xml stem>-bookshelf-preview.html)")
    args = ap.parse_args()
    out = args.out or args.xml.with_name(args.xml.stem + "-bookshelf-preview.html")
    html_text = render_book_file(args.xml)
    out.write_text(html_text, encoding="utf-8")
    print(f"wrote {out} ({len(html_text):,} bytes)")


if __name__ == "__main__":
    main()
