"""
latex_export.py — Overleaf bundle exporter for the LaTeX rendering path.

This module wraps latex_generator.generate_latex with the file-bundle layer:
it pairs the generated report.tex with the niehs.cls class file, an empty
figures/ directory for future genomics chart PDFs, and a short README aimed
at the human who'll drop the bundle into Overleaf.

Why a bundle, not just a .tex
-----------------------------
Per the Option B grilling session (2026-05-19, decision #7), the LaTeX
export path produces a zip the author uploads to Overleaf in a single
drag-and-drop.  Overleaf extracts the zip into a new project, sees
report.tex at the root, recognizes niehs.cls as a local class file (next
to the .tex), and runs pdflatex.  This works without any Overleaf
configuration.

The figures/ directory is empty in v1 but ships in the bundle anyway so
the directory structure that future genomics chart exports (PDF per UMAP
or cluster scatter, per decision #7) will use is already in place — when
those land, the author re-exports and the zip simply gains files.

Demo / customer hand-off
------------------------
The CLI entry point at the bottom of this file generates a bundle from
scaffold data for the requested chemical and writes it to dist/.  That
file is what a customer demo shows: "drop this zip into Overleaf and
press compile, you get a PDF."

Usage
-----
Programmatic:

    from report_pdf import scaffold_report_data
    from latex_export import build_overleaf_bundle
    data = scaffold_report_data(chemical_name="Perfluorohexanesulfonamide", ...)
    build_overleaf_bundle(data, Path("dist/niehs-overleaf-bundle.zip"))

CLI:

    uv run python -m latex_export                          # default scaffold
    uv run python -m latex_export --dtxsid DTXSID50469320  # named chemical
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
# zipfile is in the stdlib and produces zips Overleaf accepts directly.
# pathlib for the .cls source path (alongside this file).
# argparse for the CLI entry point used in the demo workflow.

import argparse
import zipfile
from pathlib import Path

from latex_generator import generate_latex


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The class file ships at <repo>/latex/niehs.cls and travels with the bundle.
# Resolved relative to this module so callers can be in any CWD.
REPO_ROOT = Path(__file__).resolve().parent
CLASS_FILE = REPO_ROOT / "latex" / "niehs.cls"

# Default destination for the CLI demo bundle.  dist/ is gitignored so the
# generated zip never accidentally gets committed.
DEFAULT_BUNDLE_PATH = REPO_ROOT / "dist" / "niehs-overleaf-bundle.zip"


# The customer-facing README that ships INSIDE the zip.  Written in plain
# Markdown because Overleaf's file pane previews .md files inline, so the
# customer sees the instructions the moment they open the project.
_README_TEMPLATE = """# NIEHS Biological Potency Report — Overleaf Bundle

This zip contains a LaTeX render of an NIEHS biological potency report
generated from session data.  Drop it into Overleaf to compile.

## How to use this bundle

1. Go to <https://www.overleaf.com> and sign in.
2. Click **New Project → Upload Project** and select this zip file.
3. Overleaf extracts the files and opens the project.
4. Click **Recompile** (top of the editor) — the PDF appears in the right
   pane.

The main file is `report.tex`.  The class file `niehs.cls` defines the
NIEHS styling (page geometry, table layout, footnote chrome) and lives
alongside the .tex; you don't need to touch it.

## What's in the bundle

| File                | Purpose                                                |
|---------------------|--------------------------------------------------------|
| `report.tex`        | The report itself.  Edit this in Overleaf to revise.   |
| `niehs.cls`         | NIEHS document class.  Hand-edit only for style tweaks.|
| `figures/`          | Genomics charts (UMAP, cluster scatter) as PDFs.       |
| `README.md`         | This file.                                             |

## What's complete and what's pending

This is a generated report from an in-progress migration to LaTeX.  Some
sections render their real content, others appear as visible placeholders
flagged with `[Section pending: ...]`.  Search the .tex for that string
to find every gap; each one will be filled in as the migration progresses.

Currently rendered with real content (when session data exists):

  - Foreword, About This Report, Peer Review, Publication Details,
    Acknowledgments
  - Background
  - Summary, References

Currently rendered as placeholders (next implementation passes):

  - Cover page (deliberately deferred — replaced with `\\maketitle`)
  - Materials and Methods subsections
  - Results tables (apical dose-response, BMD summary, genomics)
  - Tables list
  - Appendices

## Editing the report

Overleaf's editor is the intended authoring surface.  Edit prose directly
in `report.tex`.  Changes to the document structure (adding sections,
reordering) should not be made in the .tex — those are driven by
`document_tree.py` in the source repo and the .tex regenerates from it.

## Regenerating the bundle

When session data updates (new BMD analysis, fresh narrative), re-export
from the source app to get a fresh zip.  This is a one-way hand-off:
edits made in Overleaf do not flow back to the source session.
"""


# ---------------------------------------------------------------------------
# Helper functions (private)
# ---------------------------------------------------------------------------

def _read_class_file() -> str:
    """
    Read niehs.cls from disk.

    Resolved relative to this module's location, so callers can run from
    any working directory (CLI, web endpoint, etc.).  Errors loudly if
    the file is missing — that's a packaging bug, not user error.
    """
    if not CLASS_FILE.exists():
        raise FileNotFoundError(
            f"Expected niehs.cls at {CLASS_FILE} — the bundle exporter "
            f"cannot ship without the class file."
        )
    return CLASS_FILE.read_text()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_overleaf_bundle(
    data: dict,
    out_path: Path,
    *,
    include_readme: bool = True,
) -> Path:
    """
    Build an Overleaf-ready zip from the given report data.

    The zip lays out files at its root (no top-level directory), which is
    the layout Overleaf's "Upload Project" import expects.  Layout:

        report.tex          ← generated from DOCUMENT_TREE + data
        niehs.cls           ← copied from <repo>/latex/niehs.cls
        figures/.gitkeep    ← empty placeholder so the dir exists
        README.md           ← customer-facing instructions

    Args:
        data:           The report data dict — same shape used by
                        latex_generator.generate_latex (and by Typst's
                        marshal_export_data).
        out_path:       Filesystem path the zip will be written to.  The
                        parent directory is created if missing.
        include_readme: Pass False to skip the README (e.g., for tests
                        that only care about the .tex / .cls payload).

    Returns:
        out_path, for chaining or convenience in the CLI.
    """
    # Ensure the destination directory exists.  dist/ is the canonical
    # location and is gitignored, but callers can write anywhere.
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Generate the .tex and read the .cls now (in-memory) so the zip
    # write below is a single fast operation with no fs surprises.
    tex_source = generate_latex(data)
    cls_source = _read_class_file()

    # ZIP_DEFLATED gets us standard PKZIP compression — Overleaf handles
    # this format without any special flags.  ZIP_LZMA produces smaller
    # files but some Overleaf importers reject it.
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("report.tex", tex_source)
        zf.writestr("niehs.cls", cls_source)
        # Empty figures/ directory.  Zip files don't really represent
        # directories — we add an empty .gitkeep so the dir materializes
        # on extraction and future genomics chart PDFs have a home.
        zf.writestr("figures/.gitkeep", "")
        if include_readme:
            zf.writestr("README.md", _README_TEMPLATE)

    return out_path


# ---------------------------------------------------------------------------
# CLI entry point — the demo workflow
# ---------------------------------------------------------------------------

def _main() -> None:
    """
    Build a demo bundle from scaffold data and print where it landed.

    Used in two contexts:
      - Customer demos: produces the zip the prospect drags into Overleaf.
      - Local sanity checks: confirms the generator+class+bundle pipeline
        all hang together without spinning up the web app.
    """
    # Import here to keep module import cheap when latex_export is used
    # purely as a library (the web export endpoint, for instance).
    from report_pdf import scaffold_report_data

    parser = argparse.ArgumentParser(
        description="Build an Overleaf-ready zip from scaffold report data.",
    )
    parser.add_argument(
        "--chemical-name",
        default="Perfluorohexanesulfonamide",
        help="Test article name (default: Perfluorohexanesulfonamide)",
    )
    parser.add_argument(
        "--casrn",
        default="41997-13-1",
        help="CASRN for the test article",
    )
    parser.add_argument(
        "--dtxsid",
        default="DTXSID50469320",
        help="DSSTox ID — used only as a session identifier here",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_BUNDLE_PATH,
        help=f"Zip output path (default: {DEFAULT_BUNDLE_PATH})",
    )
    args = parser.parse_args()

    # Build the scaffold (placeholder front matter + empty body stubs).
    # When this is wired into the production export endpoint, the call
    # will route through marshal_export_data to overlay real session
    # content on top of the scaffold.  For the demo, scaffold alone is
    # enough to show the document structure.
    data = scaffold_report_data(
        chemical_name=args.chemical_name,
        casrn=args.casrn,
        dtxsid=args.dtxsid,
    )

    bundle = build_overleaf_bundle(data, args.out)
    size_kb = bundle.stat().st_size / 1024
    print(f"Wrote {bundle} ({size_kb:.1f} KB)")
    print()
    print("To demo:")
    print("  1. Open https://www.overleaf.com")
    print("  2. New Project → Upload Project → select this zip")
    print("  3. Hit Recompile")


if __name__ == "__main__":
    _main()
