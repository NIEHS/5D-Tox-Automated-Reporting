"""Tests for rendering.preview_surface — the materialized, history-retaining, docx-default
preview (Phase 5). Uses the conftest `sessions_dir` fixture so SESSIONS_DIR points at
a tmp dir; an empty session exercises load_session_data's scaffold fallback."""

from __future__ import annotations

import pytest

from rendering import preview_surface
from rendering.preview_surface import (
    materialize_preview,
    preview_file_path,
    render_surface,
)

DTXSID = "DTXSIDTEST01"


# ---------------------------------------------------------------------------
# render_surface dispatch
# ---------------------------------------------------------------------------

def test_render_surface_docx_returns_bytes():
    data = _scaffold()
    out = render_surface(data, None, surface="docx")
    assert isinstance(out, bytes) and len(out) > 0
    # A .docx is a zip — starts with PK.
    assert out[:2] == b"PK"


def test_render_surface_html_returns_str():
    data = _scaffold()
    out = render_surface(data, None, surface="html")
    assert isinstance(out, str) and "<" in out


@pytest.mark.parametrize("surface", ["latex", "jats"])
def test_render_surface_unimplemented_raises(surface):
    with pytest.raises(NotImplementedError):
        render_surface(_scaffold(), None, surface=surface)


def test_render_surface_unknown_raises_value_error():
    with pytest.raises(ValueError):
        render_surface(_scaffold(), None, surface="pdf")


# ---------------------------------------------------------------------------
# materialize_preview — file materialization + history retention
# ---------------------------------------------------------------------------

def test_materialize_docx_writes_deliverable_and_html_view(sessions_dir):
    manifest = materialize_preview(DTXSID, surface="docx")

    assert manifest["deliverable"] == "docx"
    assert manifest["view"] == "default"
    assert set(manifest["files"]) == {"docx", "html"}

    docx_path = preview_file_path(DTXSID, "docx")
    html_path = preview_file_path(DTXSID, "html")
    assert docx_path.exists() and docx_path.read_bytes()[:2] == b"PK"
    # The HTML view is always emitted, even when docx is the deliverable.
    assert html_path.exists() and "<" in html_path.read_text(encoding="utf-8")


def test_materialize_html_surface_only_writes_html(sessions_dir):
    manifest = materialize_preview(DTXSID, surface="html")
    # When the deliverable IS html, the view and deliverable coincide — one file.
    assert set(manifest["files"]) == {"html"}
    assert preview_file_path(DTXSID, "html").exists()


def test_materialize_unimplemented_surface_raises(sessions_dir):
    with pytest.raises(NotImplementedError):
        materialize_preview(DTXSID, surface="latex")


def test_materialize_unknown_surface_raises(sessions_dir):
    with pytest.raises(ValueError):
        materialize_preview(DTXSID, surface="pdf")


def test_second_materialize_archives_prior(sessions_dir):
    materialize_preview(DTXSID, surface="docx")
    first_bytes = preview_file_path(DTXSID, "docx").read_bytes()

    # Re-materialize (e.g. a restyle / report-update). The prior set is archived.
    materialize_preview(DTXSID, surface="docx")

    hist_root = sessions_dir / DTXSID / "preview" / "default" / "history"
    assert hist_root.exists()
    snapshots = list(hist_root.iterdir())
    assert len(snapshots) == 1
    archived = snapshots[0]
    # The archived snapshot holds the prior deliverable + view.
    names = {p.name for p in archived.iterdir()}
    assert "preview.docx" in names and "preview.html" in names
    # Current file still present after the rebuild.
    assert preview_file_path(DTXSID, "docx").exists()
    # Archived bytes equal the first render.
    assert (archived / "preview.docx").read_bytes() == first_bytes


def test_materialize_empty_session_degrades_to_scaffold(sessions_dir):
    # No session content on disk at all — load_session_data returns scaffold-only,
    # so materialization must still succeed (not crash).
    manifest = materialize_preview("DTXSIDNOSESS", surface="docx")
    assert preview_file_path("DTXSIDNOSESS", "docx").exists()
    assert manifest["deliverable"] == "docx"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _scaffold() -> dict:
    from rendering.report_data import scaffold_report_data
    return scaffold_report_data(
        chemical_name="Test Article", casrn="000-00-0", dtxsid=DTXSID
    )
