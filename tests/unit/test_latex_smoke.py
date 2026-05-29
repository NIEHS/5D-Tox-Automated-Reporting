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
from report_data import scaffold_report_data


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
    (report_data.scaffold_report_data → marshal_export_data overlay).
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


def test_roman_front_matter_then_arabic_body(scaffold):
    r"""
    Front matter is numbered in roman, the body in arabic restarted at 1
    (NIEHS Report 10: Background = arabic page 1).  The preamble sets
    \pagenumbering{roman} before \maketitle; \pagenumbering{arabic} is
    injected at the front-matter/body boundary, before \section{Background}.
    """
    tex = generate_latex(scaffold)
    assert r"\pagenumbering{roman}" in tex
    assert r"\pagenumbering{arabic}" in tex
    # Order: roman is set first (preamble), arabic later (at the body).
    assert tex.index(r"\pagenumbering{roman}") < tex.index(r"\pagenumbering{arabic}")
    # The arabic switch lands at the front-matter/body boundary: after the
    # last front-matter section (Abstract) and right before Background.
    assert tex.index(r"\section{Abstract}") < tex.index(r"\pagenumbering{arabic}")
    assert tex.index(r"\pagenumbering{arabic}") < tex.index(r"\section{Background}")
    # The title page carries no visible number.
    assert r"\thispagestyle{empty}" in tex


def test_running_header_is_set(scaffold):
    r"""
    The fancyhdr running header (niehs.cls) must be fed the report title
    via \renewcommand{\niehsrunningheader}{...}, so the .tex carries the
    same running header as the reference and the HTML preview.
    """
    tex = generate_latex(scaffold)
    assert r"\renewcommand{\niehsrunningheader}{" in tex
    # The injected header is the full title form — chemical name present.
    header_line = next(
        ln for ln in tex.splitlines() if r"\renewcommand{\niehsrunningheader}" in ln
    )
    assert "Perfluorohexanesulfonamide" in header_line


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


def test_tables_list_renders_listoftables(scaffold):
    r"""tables-list node emits the heading + \listoftables (auto-populated)."""
    tex = generate_latex(scaffold)
    assert r"\section{Tables}" in tex
    assert r"\listoftables" in tex


# ---------------------------------------------------------------------------
# Tests — unimplemented node_types emit visible placeholders
# ---------------------------------------------------------------------------

def test_cover_and_title_page_still_unimplemented(scaffold):
    """
    Cover and title-page remain unimplemented by design (decision #6 —
    \\maketitle handles the title; the NIEHS-branded cover is deferred).
    They emit comment-only placeholders so the .tex still compiles.
    """
    tex = generate_latex(scaffold)
    assert "[Section pending: cover" in tex
    assert "[Section pending: title-page" in tex


def test_narrative_tables_groups_render_with_heading(scaffold):
    r"""
    narrative+tables groups emit their H2 heading + a narrative chunk
    (real or placeholder).  No more "[Section pending: narrative+tables".
    """
    tex = generate_latex(scaffold)
    assert r"\subsection{Animal Condition, Body Weights, and Organ Weights}" in tex
    assert r"\subsection{Clinical Pathology}" in tex
    # Should NOT carry the generic _render_unimplemented placeholder
    assert "[Section pending: narrative+tables" not in tex


def test_bmd_summary_renders_table(scaffold):
    """BMD summary emits a niehstable env (scaffold has 1 placeholder endpoint)."""
    tex = generate_latex(scaffold)
    assert r"\subsection{Apical Endpoint Benchmark Dose Summary}" in tex
    # The scaffold endpoint produces a tabular with the BMD/BMDL columns.
    assert r"\begin{niehstable}{bmd-summary}" in tex
    assert "BMD" in tex and "BMDL" in tex


def test_genomics_sections_render_subsubsections(scaffold):
    r"""
    Genomics sections emit per-(organ, sex) \subsubsection headings
    (scaffold has 4 entries: liver/kidney × male).
    """
    tex = generate_latex(scaffold)
    assert r"\subsection{Gene Set Benchmark Dose Analysis}" in tex
    assert r"\subsection{Gene Benchmark Dose Analysis}" in tex
    assert r"\subsubsection{Liver, Male}" in tex
    assert r"\subsubsection{Kidney, Male}" in tex


def test_apical_table_nodes_emit_niehstable_envs(scaffold):
    r"""
    "table" node_type emits a \begin{niehstable}{<id>}{<caption>} env
    even when data is empty (placeholder caption + body, so the table
    still claims a number for \listoftables).
    """
    tex = generate_latex(scaffold)
    assert r"\begin{niehstable}{table-body-weight}" in tex
    assert r"\begin{niehstable}{table-organ-weight}" in tex
    assert r"\begin{niehstable}{table-clin-chem}" in tex


def test_methods_subsections_render(scaffold):
    r"""
    M&M subsections (Study Design, Chemistry, etc.) emit their
    \subsection heading.  Scaffold has empty paragraph lists, so the
    body falls to the [Section pending: ...] per-subsection placeholder
    — but the structure is visible.
    """
    tex = generate_latex(scaffold)
    assert r"\subsection{Study Design}" in tex
    assert r"\subsection{Dose Selection Rationale}" in tex
    assert r"\subsection{Chemistry}" in tex
    # The deepest H3 subsections also appear
    assert r"\subsubsection{Clinical Observations}" in tex
    assert r"\subsubsection{RNA Isolation, Library Creation, and Sequencing}" in tex


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


def test_unrenderable_unicode_is_translated_to_latex():
    r"""
    Characters absent from the report font (≤ ≥ and subscript digits) must be
    translated to LaTeX commands; otherwise they silently drop from the PDF on
    both tectonic and Overleaf's pdflatex (a real compile confirmed this for
    "p ≤ 0.05" and "BMD₁Std").
    """
    from latex_generator import _escape_latex
    out = _escape_latex("BMD₁Std, p ≤ 0.05, n ≥ 3")
    # The raw font-unrenderable characters must be gone…
    assert "≤" not in out and "≥" not in out and "₁" not in out
    # …replaced by their LaTeX equivalents.
    assert r"\ensuremath{\le}" in out
    assert r"\ensuremath{\ge}" in out
    assert r"\textsubscript{1}" in out


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


def test_class_file_loads_pdflscape():
    """niehs.cls must load pdflscape so \\begin{landscape} works."""
    content = CLASS_FILE.read_text()
    assert r"\RequirePackage{pdflscape}" in content


def test_landscape_orientation_wraps_in_pdflscape(scaffold):
    r"""
    A node flagged landscape in data["orientations"] is wrapped in
    pdflscape's landscape environment so Overleaf renders that page rotated.
    """
    data = {**scaffold, "orientations": {"bmd-summary": "landscape"}}
    tex = generate_latex(data)
    assert r"\begin{landscape}" in tex
    assert r"\end{landscape}" in tex


def test_landscape_flag_on_non_orientable_node_ignored(scaffold):
    r"""
    A landscape flag on a non-orientable node (prose) is ignored — the
    capability dictionary gates the wrap on both render sides.
    """
    data = {**scaffold, "orientations": {"background": "landscape"}}
    tex = generate_latex(data)
    assert r"\begin{landscape}" not in tex


def test_class_file_configures_running_header():
    r"""
    niehs.cls must set up the fancyhdr running header: load fancyhdr,
    define the (empty-by-default) \niehsrunningheader macro, and switch on
    \pagestyle{fancy}.  The title page stays header-less automatically via
    \maketitle's plain style, so the header begins after it — matching the
    reference (NIEHS Report 10), where the header starts at the Foreword.
    """
    content = CLASS_FILE.read_text()
    assert r"\RequirePackage{fancyhdr}" in content
    assert r"\newcommand{\niehsrunningheader}{}" in content
    assert r"\pagestyle{fancy}" in content
    assert r"\fancyhead[C]{" in content


# ---------------------------------------------------------------------------
# Tests — section_filter fragment-compile path (decision #10)
# ---------------------------------------------------------------------------

def test_fragment_compile_omits_front_matter(scaffold):
    r"""
    A fragment compile (section_filter set) must NOT emit \maketitle,
    \tableofcontents, the title metadata, or any front-matter section.
    The point of fragments is to be small + fast on Overleaf.
    """
    tex = generate_latex(scaffold, section_filter="bmd-summary")
    assert r"\maketitle" not in tex
    assert r"\tableofcontents" not in tex
    assert r"\title{" not in tex
    assert r"\section{Foreword}" not in tex
    assert r"\section{Background}" not in tex
    # Fragments don't set the running header — niehs.cls leaves it empty,
    # so a fragment compile shows a blank header (fine for the fast path).
    assert r"\renewcommand{\niehsrunningheader}" not in tex


def test_fragment_compile_includes_target_subtree(scaffold):
    """A fragment must include the requested node's heading + body."""
    tex = generate_latex(scaffold, section_filter="bmd-summary")
    assert r"\documentclass{niehs}" in tex
    assert r"\begin{document}" in tex
    assert r"\end{document}" in tex
    # The bmd-summary node renders as \subsection (level=2)
    assert r"\subsection{Apical Endpoint Benchmark Dose Summary}" in tex


def test_fragment_compile_recurses_into_subtree(scaffold):
    r"""
    Filtering to a parent node must include all descendants.  Filtering
    to "animal-condition" should bring in the three child table nodes.
    """
    tex = generate_latex(scaffold, section_filter="animal-condition")
    assert r"\subsection{Animal Condition, Body Weights, and Organ Weights}" in tex
    assert r"\begin{niehstable}{table-body-weight}" in tex
    assert r"\begin{niehstable}{table-organ-weight}" in tex
    assert r"\begin{niehstable}{table-clinical-obs}" in tex


def test_fragment_compile_unknown_id_returns_empty_body(scaffold):
    """
    Unknown section_filter values render a stub fragment with a
    diagnostic comment but never crash — the web app may pass user-
    controlled ids and we'd rather show a blank preview than 500.
    """
    tex = generate_latex(scaffold, section_filter="not-a-real-node-id")
    assert r"\begin{document}" in tex
    assert r"\end{document}" in tex
    assert "No node found for section_filter" in tex
    # And nothing else from the body
    assert r"\section{Background}" not in tex


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
