"""
rendering.preview_surface — surface dispatch + a materialized, history-retaining preview.

The four report emitters (`generate_html`, `generate_latex`, `generate_docx`,
`generate_bits`/`generate_jats`) all project the SAME marshalled data dict + DocNode
tree onto different output formats (see project_render_surfaces). This module adds:

  1. `render_surface` — one dispatch over the emitters, keyed by surface name. Only
     `docx` (the default deliverable) and `html` (the always-viewable proxy) are
     implemented; `latex`/`jats` are named but raise NotImplementedError — the
     "provisioned but unimplemented" surfaces (adding one later is a one-line wire).
  2. `materialize_preview` — build the data on-disk (no request body), render, and
     write a preview ARTIFACT under the session dir instead of the old pull-based
     ephemeral srcdoc (project_integrated_wizard_versioned_preview Decision 5).

Docx-by-default with an always-emitted HTML view: docx is the canonical download,
but docx cannot render in an iframe and docx→pdf is host-fix-pending
(feedback_onlyoffice_not_libreoffice), so `preview.html` is ALWAYS written as the
on-screen view regardless of the chosen deliverable surface.

Each preview belongs to a report VIEW (a saved structure+filters lens, view_config).
Preview files retain HISTORY: each rebuild archives the prior set into
`preview/<view>/history/<ts>/` before overwriting, mirroring
session_store.save_section's archive-before-overwrite. A restyle re-materializes the
SAME view (archive + rewrite, no new content revision) — styling is a pure
re-projection and never bumps a content revision (Decision 1).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from document_model.view_config import DEFAULT_VIEW, build_view_tree
from pipeline.session_store import now_iso, session_dir
from rendering.latex_export import load_session_data

# Surfaces the dispatch knows about. IMPLEMENTED_SURFACES render today; the rest
# are provisioned (named so the UI can list them) but raise on use.
IMPLEMENTED_SURFACES: frozenset[str] = frozenset({"docx", "html"})
KNOWN_SURFACES: frozenset[str] = frozenset({"docx", "html", "latex", "jats"})

DEFAULT_SURFACE = "docx"

# Filename the deliverable/view files take, per surface.
_SURFACE_FILENAME: dict[str, str] = {
    "docx": "preview.docx",
    "html": "preview.html",
    "latex": "preview.tex",
    "jats": "preview.xml",
}


def render_surface(
    data: dict,
    tree: "list | None",
    surface: str = DEFAULT_SURFACE,
    section_filter: str | None = None,
) -> bytes | str:
    """Render `data` to one output surface.

    docx → bytes (generate_docx); html → str (generate_html). latex/jats are known
    surface names but NOT implemented — they raise NotImplementedError so the caller
    (and the UI) can offer them as disabled options without a silent wrong render.
    An unknown surface raises ValueError.
    """
    if surface == "docx":
        from rendering.docx_generator import generate_docx
        return generate_docx(data, tree)
    if surface == "html":
        from rendering.html_generator import generate_html
        return generate_html(data, section_filter=section_filter, tree=tree)
    if surface in ("latex", "jats"):
        raise NotImplementedError(
            f"Preview surface {surface!r} is provisioned but not implemented yet"
        )
    raise ValueError(f"Unknown preview surface: {surface!r}")


def _preview_dir(dtxsid: str, view: str) -> Path:
    return session_dir(dtxsid) / "preview" / view


def _identity(dtxsid: str) -> tuple[str, str]:
    """Resolve (chemical_name, casrn) from the session's identity/meta, mirroring
    how integrate_step (workflow/steps.py) reads the test article. Falls back to the
    scaffold defaults so an un-integrated session still previews."""
    from rendering.latex_export import _load_json
    sess = session_dir(dtxsid)
    for name in ("identity.json", "meta.json"):
        data = _load_json(sess / name)
        if isinstance(data, dict):
            chem = (data.get("name") or "").strip()
            casrn = (data.get("casrn") or "").strip()
            if chem or casrn:
                return chem or "Test Article", casrn or "000-00-0"
    return "Test Article", "000-00-0"


def _archive_prior(preview_dir: Path, ts: str) -> None:
    """Move the current preview files into history/<ts>/ before a rebuild.

    Mirrors session_store.save_section's archive-before-overwrite: prior renders are
    retained (preview history) rather than clobbered. Only the deliverable files
    are archived — the history/ subtree itself is skipped.
    """
    existing = [
        p for p in preview_dir.glob("*")
        if p.is_file() and p.name != "manifest.json"
    ]
    if not existing:
        return
    hist = preview_dir / "history" / ts.replace(":", "-")
    hist.mkdir(parents=True, exist_ok=True)
    for p in existing:
        shutil.move(str(p), str(hist / p.name))


def materialize_preview(
    dtxsid: str,
    surface: str = DEFAULT_SURFACE,
    view: str | None = None,
) -> dict:
    """Render and persist the preview artifact set for a session.

    Builds the report data from disk (`load_session_data` — scaffold-only when the
    session has no content), resolves the DocNode tree for the view, then writes:

      * `preview.<ext>` for the chosen deliverable `surface` (default docx), AND
      * `preview.html` — always, as the guaranteed on-screen view (docx can't render
        in an iframe). When surface == "html" the two coincide.

    Files land under `sessions/<dtxsid>/preview/<view>/`; the prior set is archived
    into `history/<ts>/` first so every rebuild is retained. Returns a manifest
    `{view, ts, deliverable, files: {surface: rel_path}}` (also written as
    manifest.json alongside the files).
    """
    if surface not in KNOWN_SURFACES:
        raise ValueError(f"Unknown preview surface: {surface!r}")

    view = view or DEFAULT_VIEW
    ts = now_iso()

    chemical_name, casrn = _identity(dtxsid)
    data = load_session_data(dtxsid, chemical_name=chemical_name, casrn=casrn, view=view)
    tree = build_view_tree(dtxsid, view)

    preview_dir = _preview_dir(dtxsid, view)
    preview_dir.mkdir(parents=True, exist_ok=True)
    _archive_prior(preview_dir, ts)

    files: dict[str, str] = {}

    # Deliverable surface (default docx). str→text, bytes→binary.
    deliverable_out = render_surface(data, tree, surface=surface)
    deliverable_name = _SURFACE_FILENAME[surface]
    deliverable_path = preview_dir / deliverable_name
    if isinstance(deliverable_out, bytes):
        deliverable_path.write_bytes(deliverable_out)
    else:
        deliverable_path.write_text(deliverable_out, encoding="utf-8")
    files[surface] = f"preview/{view}/{deliverable_name}"

    # HTML view — always, unless the deliverable already IS html.
    if surface != "html":
        html_out = render_surface(data, tree, surface="html")
        assert isinstance(html_out, str)  # generate_html always returns str
        (preview_dir / "preview.html").write_text(html_out, encoding="utf-8")
        files["html"] = f"preview/{view}/preview.html"

    manifest = {
        "view": view,
        "ts": ts,
        "deliverable": surface,
        "files": files,
    }
    import json
    (preview_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest


def preview_file_path(
    dtxsid: str, surface: str, view: str | None = None
) -> Path:
    """Absolute path to a materialized preview file for a surface, or the html view
    when surface == 'html'. Does not check existence — callers (the download/view
    routes) 404 on a missing file."""
    view = view or DEFAULT_VIEW
    name = _SURFACE_FILENAME.get(surface, "preview.html")
    return _preview_dir(dtxsid, view) / name
