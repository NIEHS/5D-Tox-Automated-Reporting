r"""
test_latex_smoke.py — Tracer-bullet smoke test for latex_generator.

Verifies that the generator produces a structurally valid .tex from the
NIEHS scaffold data and that all five implemented node_types render
their expected output.  Also asserts the class file ships in the right
place so a future "Overleaf bundle" exporter can find it.

What this proves
----------------
  - generate_latex returns a string with the LaTeX document skeleton.
  - Section headings derived from DOCUMENT_TREE appear in the right
    sectioning level (\section vs \subsection).
  - Unimplemented node_types (cover, title-page, table, bmd-summary,
    genomics-section, etc.) emit visible placeholders rather than crashing.
  - LaTeX-special characters in input strings are escaped, not splatted.
  - latex/niehs.cls exists alongside the generator (the export bundle
    will pair them).

What this does NOT prove
------------------------
  - That the output renders well visually — that's a manual review step
    once we have pdflatex available.
  - That the actual M&M / Results / Genomics content renders correctly —
    those node_types are unimplemented in this tracer-bullet commit.

Optional pdflatex compile
-------------------------
If pdflatex is on PATH, we additionally compile the generated .tex into
a temp dir alongside niehs.cls and assert pdflatex exits 0 with a PDF
on disk.  The check is skipped (not failed) when pdflatex is unavailable,
because most contributors won't have a TeX distribution installed and
we don't want to block CI / local dev on it.  Overleaf is the real
compile target.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from latex_generator import generate_latex
from report_pdf import scaffold_report_data


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# tests/unit/test_latex_smoke.py → parents[2] is the repo root.  We resolve
# the class file relative to that so the test is location-independent.

REPO_ROOT = Path(__file__).resolve().parents[2]
CLASS_FILE = REPO_ROOT / "latex" / "niehs.cls"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def scaffold() -> dict:
    """
    Build the full NIEHS scaffold for a sample chemical.

    This is the same scaffold the production export path uses
    (report_pdf.scaffold_report_data → marshal_export_data overlay).
    For the smoke test we exercise the scaffold-only branch: every
    section has placeholder content but the structure is complete.

    Returns:
        The dict the generator will consume.
    """
    return scaffold_report_data(
        chemical_name="Perfluorohexanesulfonamide",
        casrn="41997-13-1",
        dtxsid="DTXSID50469320",
    )


# ---------------------------------------------------------------------------
# Tests — document skeleton
# ---------------------------------------------------------------------------

def test_generates_document_skeleton(scaffold):
    """The output must be a complete LaTeX document, not a fragment."""
    tex = generate_latex(scaffold)
    assert r"\documentclass{niehs}" in tex
    assert r"\begin{document}" in tex
    assert r"\end{document}" in tex
    assert r"\maketitle" in tex
    assert r"\tableofcontents" in tex


def test_title_and_author_are_set(scaffold):
    """Title metadata from the data dict must flow into the preamble."""
    tex = generate_latex(scaffold)
    assert r"\title{" in tex
    assert r"\author{" in tex
    # Scaffold title includes the chemical name; verify the substitution
    # actually happened (not a literal "{title}" placeholder leak).
    assert "Perfluorohexanesulfonamide" in tex


# ---------------------------------------------------------------------------
# Tests — implemented node_types render correctly
# ---------------------------------------------------------------------------

def test_front_matter_renders_as_section(scaffold):
    r"""Foreword is a front-matter node at level=1 → \section."""
    tex = generate_latex(scaffold)
    assert r"\section{Foreword}" in tex


def test_narrative_renders_as_section(scaffold):
    r"""Background and Summary are narrative nodes at level=1 → \section."""
    tex = generate_latex(scaffold)
    assert r"\section{Background}" in tex
    assert r"\section{Summary}" in tex


def test_heading_only_emits_parent_heading(scaffold):
    """Materials and Methods is heading-only; the heading must appear."""
    tex = generate_latex(scaffold)
    assert r"\section{Materials and Methods}" in tex
    assert r"\section{Results}" in tex


def test_appendix_renders_with_pending_placeholder(scaffold):
    """Appendices render as heading + visible pending placeholder."""
    tex = generate_latex(scaffold)
    assert r"\section{Appendix A. Internal Dose Assessment}" in tex
    assert "Appendix body pending" in tex


def test_tables_list_renders_stub(scaffold):
    """tables-list node emits a heading + stub placeholder for v1."""
    tex = generate_latex(scaffold)
    assert r"\section{Tables}" in tex
    assert "List of tables: pending" in tex


# ---------------------------------------------------------------------------
# Tests — unimplemented node_types emit visible placeholders
# ---------------------------------------------------------------------------

def test_unimplemented_types_have_pending_placeholders(scaffold):
    """
    Cover, title-page, narrative+tables, table, bmd-summary, and
    genomics-section all fall through to _render_unimplemented.

    Tracer-bullet requirement: they don't crash, and they emit a visible
    [Section pending: <type>] string so the author sees the gap.
    """
    tex = generate_latex(scaffold)
    # The generic placeholder format from _pending_placeholder()
    assert "[Section pending: cover" in tex
    assert "[Section pending: title-page" in tex
    assert "[Section pending: narrative+tables" in tex
    assert "[Section pending: bmd-summary" in tex
    assert "[Section pending: genomics-section" in tex


def test_narrative_tables_groups_emit_their_subsection_headings(scaffold):
    r"""
    narrative+tables nodes (Animal Condition, Clinical Pathology, etc.)
    are unimplemented but have level=2, so their \subsection heading
    must still appear.  Otherwise the Results section TOC would be empty.
    """
    tex = generate_latex(scaffold)
    assert r"\subsection{Animal Condition, Body Weights, and Organ Weights}" in tex
    assert r"\subsection{Clinical Pathology}" in tex
    assert r"\subsection{Internal Dose Assessment}" in tex


# ---------------------------------------------------------------------------
# Tests — LaTeX special-character escaping
# ---------------------------------------------------------------------------

def test_special_characters_are_escaped():
    """
    Chemical names containing & % # _ must be escaped in the title so
    pdflatex doesn't choke.  We don't run pdflatex here — we just check
    the escape happened.
    """
    data = {
        "title": "Test & Demo 50% Compound_X",
        "author": "Acme & Co",
    }
    tex = generate_latex(data)
    # Original unescaped form must not appear
    assert "Test & Demo" not in tex
    # Escaped form must appear
    assert r"Test \& Demo" in tex
    assert r"50\% Compound\_X" in tex
    assert r"Acme \& Co" in tex


# ---------------------------------------------------------------------------
# Tests — companion class file ships
# ---------------------------------------------------------------------------

def test_class_file_exists():
    """
    latex/niehs.cls must ship alongside the generator.  When the export
    bundler is built (future session), it will copy this file into the
    Overleaf zip next to report.tex.
    """
    assert CLASS_FILE.exists(), (
        f"Expected niehs.cls at {CLASS_FILE} — the generator emits "
        f"\\documentclass{{niehs}} and the file must travel with the .tex."
    )


def test_class_file_provides_class():
    """Sanity-check that niehs.cls actually declares itself."""
    content = CLASS_FILE.read_text()
    assert r"\ProvidesClass{niehs}" in content
    assert r"\LoadClass" in content


# ---------------------------------------------------------------------------
# Optional: actually compile the .tex (skipped if pdflatex missing)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    shutil.which("pdflatex") is None,
    reason="pdflatex not on PATH — install TeX Live or run on a CI image with it",
)
def test_pdflatex_compiles(scaffold, tmp_path):
    """
    End-to-end compile check.  Writes the generated .tex and the class
    file into tmp_path and runs pdflatex.  Asserts a PDF lands and the
    process exits 0.

    Skipped silently when pdflatex is unavailable — most contributors
    don't have a TeX distribution installed and we don't want to block
    local dev on it.
    """
    tex = generate_latex(scaffold)
    (tmp_path / "report.tex").write_text(tex)
    (tmp_path / "niehs.cls").write_text(CLASS_FILE.read_text())

    result = subprocess.run(
        ["pdflatex", "-interaction=batchmode", "-halt-on-error", "report.tex"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    pdf_path = tmp_path / "report.pdf"
    assert pdf_path.exists() and result.returncode == 0, (
        f"pdflatex failed (exit {result.returncode}).\n"
        f"--- STDOUT (last 2000 chars) ---\n{result.stdout[-2000:]}\n"
        f"--- STDERR ---\n{result.stderr}\n"
        f"--- log tail ---\n"
        + (tmp_path / "report.log").read_text()[-2000:]
        if (tmp_path / "report.log").exists()
        else ""
    )
