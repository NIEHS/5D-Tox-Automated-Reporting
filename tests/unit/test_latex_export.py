r"""
test_latex_export.py — Smoke test for the Overleaf bundle builder.

Verifies that build_overleaf_bundle produces a valid zip containing the
files Overleaf expects: report.tex at the root, niehs.cls alongside it,
an empty figures/ directory, and a customer-facing README.md.

What this proves
----------------
  - The zip writes cleanly and is a real PKZIP archive.
  - All four expected entries are present.
  - report.tex is the same content generate_latex would produce
    (no accidental truncation or re-rendering inside the bundler).
  - niehs.cls in the zip is byte-identical to the source-tree class.
  - README.md mentions "Overleaf" so authors can search for instructions.

What this does NOT prove
------------------------
  - That the bundle actually compiles on Overleaf — that's a manual
    verification step.  Overleaf compatibility is asserted at the
    zip-format and file-layout level only.
"""

import zipfile
from pathlib import Path

import pytest

from latex_export import (
    CLASS_FILE,
    build_overleaf_bundle,
)
from latex_generator import generate_latex
from report_pdf import scaffold_report_data


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def scaffold() -> dict:
    """
    Same scaffold the production demo uses — Perfluorohexanesulfonamide.

    Module-scoped because building the scaffold is cheap but not free,
    and every test in this file just reads from the resulting bundle.
    """
    return scaffold_report_data(
        chemical_name="Perfluorohexanesulfonamide",
        casrn="41997-13-1",
        dtxsid="DTXSID50469320",
    )


@pytest.fixture
def bundle_path(scaffold, tmp_path) -> Path:
    """Build a bundle into a tmp dir; return the resulting zip path."""
    out = tmp_path / "bundle.zip"
    return build_overleaf_bundle(scaffold, out)


# ---------------------------------------------------------------------------
# Tests — zip structure
# ---------------------------------------------------------------------------

def test_bundle_is_a_valid_zip(bundle_path):
    """The bundle must be a real PKZIP archive Overleaf can extract."""
    assert zipfile.is_zipfile(bundle_path), (
        f"Bundle at {bundle_path} is not a valid zip"
    )


def test_bundle_contains_required_files(bundle_path):
    """All four required entries must be present at the zip root."""
    with zipfile.ZipFile(bundle_path) as zf:
        names = set(zf.namelist())
    assert "report.tex" in names
    assert "niehs.cls" in names
    assert "figures/.gitkeep" in names
    assert "README.md" in names


def test_bundle_has_no_top_level_directory(bundle_path):
    r"""
    Overleaf's "Upload Project" expects report.tex at the archive root,
    not inside a top-level folder.  Reject any entry whose first path
    component would put the .tex inside a subdirectory.
    """
    with zipfile.ZipFile(bundle_path) as zf:
        names = zf.namelist()
    # report.tex must be at root, not "myproject/report.tex"
    assert "report.tex" in names, (
        f"report.tex must be at the zip root; got {names}"
    )


# ---------------------------------------------------------------------------
# Tests — content fidelity
# ---------------------------------------------------------------------------

def test_report_tex_matches_generator_output(bundle_path, scaffold):
    """
    The .tex inside the zip must be exactly what generate_latex would
    produce for the same data — the bundler is a thin wrapper, not a
    second renderer.
    """
    with zipfile.ZipFile(bundle_path) as zf:
        tex_in_zip = zf.read("report.tex").decode("utf-8")
    expected = generate_latex(scaffold)
    assert tex_in_zip == expected


def test_class_file_matches_source(bundle_path):
    """niehs.cls in the zip must be byte-identical to the source-tree class."""
    with zipfile.ZipFile(bundle_path) as zf:
        cls_in_zip = zf.read("niehs.cls").decode("utf-8")
    assert cls_in_zip == CLASS_FILE.read_text()


def test_readme_mentions_overleaf(bundle_path):
    """Authors should be able to grep the bundle for 'Overleaf' and find help."""
    with zipfile.ZipFile(bundle_path) as zf:
        readme = zf.read("README.md").decode("utf-8")
    assert "Overleaf" in readme
    assert "Recompile" in readme


# ---------------------------------------------------------------------------
# Tests — include_readme toggle
# ---------------------------------------------------------------------------

def test_bundle_without_readme(scaffold, tmp_path):
    """
    The include_readme=False path is intended for production exports
    where authors already know the workflow.  The README should be
    absent but every other file present.
    """
    out = tmp_path / "lean.zip"
    build_overleaf_bundle(scaffold, out, include_readme=False)
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    assert "report.tex" in names
    assert "niehs.cls" in names
    assert "README.md" not in names
