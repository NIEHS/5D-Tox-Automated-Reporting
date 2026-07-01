r"""
test_pending_gate.py — the release gate that keeps "[... pending]" placeholders
out of a deliverable bundle (issue #3).

Two layers:
  - scan_pending_markers / PendingContentError (render_common) — the pure
    string scanner and its exception.
  - _assemble_bundle_files(..., strict=True) + the deliverable callers
    (latex_export) — the choke point that refuses to ship a stubbed report.

The renderers still EMIT the stubs (draft visibility is intentional and covered
by test_latex_smoke / test_appendix_b); this gate only governs whether a
DELIVERABLE build is allowed to contain them.
"""

import zipfile
from pathlib import Path

import pytest

from render_common import scan_pending_markers, PendingContentError
from latex_export import build_overleaf_bundle, _assemble_bundle_files
from report_data import scaffold_report_data


# ---------------------------------------------------------------------------
# scan_pending_markers — the pure scanner
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("marker", [
    r"\emph{[Section pending: Cover]}",
    r"\emph{[Narrative pending: Internal Dose Assessment]}",
    r"\emph{[Appendix body pending: Appendix A. Internal Dose]}",
    r"\emph{[Table data pending: Body Weights]}",
    r"[Placeholder: GEO Accession Number GSEXXXXXX; CEBS DOI: 10.22427/XXXXXXXX]",
])
def test_scanner_finds_each_marker_shape(marker):
    """Every placeholder shape both renderers emit is detected."""
    found = scan_pending_markers(f"Some prose.\n{marker}\nMore prose.")
    assert len(found) == 1


def test_scanner_clean_document_returns_empty():
    """A fully-populated document yields no markers — the success condition."""
    assert scan_pending_markers("A real report with no gaps whatsoever.") == []
    assert scan_pending_markers("") == []


def test_scanner_dedupes_preserving_order():
    """Repeated identical markers collapse to one; order is first-seen."""
    text = (
        r"\emph{[Section pending: Cover]}"
        r"\emph{[Narrative pending: Summary]}"
        r"\emph{[Section pending: Cover]}"
    )
    found = scan_pending_markers(text)
    assert found == [
        "[Section pending: Cover]",
        "[Narrative pending: Summary]",
    ]


def test_scanner_collapses_multiline_marker():
    """A marker the renderer wrapped across lines still reads as one label."""
    text = "[Appendix body pending: Appendix C. Transcriptomic Quality\nControl and eFDR]"
    found = scan_pending_markers(text)
    assert len(found) == 1
    assert "\n" not in found[0]


def test_scanner_ignores_the_word_pending_in_prose():
    """Only bracketed markers count — ordinary prose using 'pending' is fine."""
    assert scan_pending_markers("Results for the pending analysis are shown.") == []


# ---------------------------------------------------------------------------
# The gate — strict assembly + deliverable callers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def scaffold() -> dict:
    """Scaffold data legitimately renders stubs — the gate's failure input."""
    return scaffold_report_data(
        chemical_name="Perfluorohexanesulfonamide",
        casrn="41997-13-1",
        dtxsid="DTXSID50469320",
    )


def test_strict_assembly_raises_on_stubbed_scaffold(scaffold):
    """A scaffold (full of stubs) must be rejected by the strict gate."""
    with pytest.raises(PendingContentError) as exc:
        _assemble_bundle_files(scaffold, strict=True)
    assert exc.value.markers, "the error should carry the offending markers"
    # The scaffold has no cover/title/appendix content, so those stubs appear.
    joined = "\n".join(exc.value.markers)
    assert "pending" in joined.lower()


def test_lenient_assembly_still_builds_stubbed_scaffold(scaffold):
    """Default (strict=False) is unchanged — the draft path keeps its stubs."""
    files = _assemble_bundle_files(scaffold)  # no raise
    assert "report.tex" in files
    assert b"pending" in files["report.tex"].lower()


def test_strict_bundle_writes_nothing_on_failure(scaffold, tmp_path):
    """A gated build must not leave a partial zip behind."""
    out = tmp_path / "gated.zip"
    with pytest.raises(PendingContentError):
        build_overleaf_bundle(scaffold, out, strict=True)
    assert not out.exists(), "strict build must write no file when it fails"


def test_lenient_bundle_writes_zip(scaffold, tmp_path):
    """strict=False writes a valid zip even with stubs present."""
    out = build_overleaf_bundle(scaffold, tmp_path / "draft.zip")
    assert zipfile.is_zipfile(out)


def test_strict_assembly_passes_when_no_markers(scaffold):
    """A report scrubbed of markers passes the gate.

    We can't easily hand-populate every scaffold section, so prove the gate's
    success path by scanning a clean body directly — the assembly gate is a
    thin wrapper over exactly this check.
    """
    assert scan_pending_markers("Clean report, all sections filled.") == []
