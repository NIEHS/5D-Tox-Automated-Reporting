r"""
latex_export.py — Overleaf bundle exporter for the LaTeX rendering path.

This module wraps the LaTeX generator with the file-bundle layer: it pairs the
generated main.tex (Overleaf entry: preamble + \input{report}) and report.tex
(the body) with the niehs.cls class file, a figures/ directory for genomics
chart images, and a short README aimed at the human who'll work in Overleaf.

Why a bundle, not just a .tex
-----------------------------
Per the Option B grilling session (2026-05-19, decision #7), the LaTeX
export path produces a zip the author uploads to Overleaf in a single
drag-and-drop.  Overleaf extracts the zip into a new project, sees
main.tex at the root (its default main document), recognizes niehs.cls as a
local class file alongside, and runs pdflatex.  This works without any
Overleaf configuration — no "set main document" step.

The figures/ directory carries the genomics chart images (one PNG per UMAP /
cluster scatter, decoded from the session chart cache) when the session has
them; a scaffold-only export ships an empty figures/ (a .gitkeep) instead.

Demo / customer hand-off
------------------------
The CLI entry point at the bottom of this file generates a bundle from
scaffold data for the requested chemical and writes it to dist/.  That
file is what a customer demo shows: "drop this zip into Overleaf and
press compile, you get a PDF."

Usage
-----
Programmatic:

    from rendering.report_data import scaffold_report_data
    from rendering.latex_export import build_overleaf_bundle
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
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path

from rendering.latex_generator import generate_main_tex, generate_report_body


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The class file ships at <repo>/latex/niehs.cls and travels with the bundle.
# Resolved relative to this module so callers can be in any CWD.
REPO_ROOT = Path(__file__).resolve().parent.parent
CLASS_FILE = REPO_ROOT / "latex" / "niehs.cls"

# Cover assets (background image, NIH badge) are declared per report-cover
# subtype in cover_layouts and live under assets/.  They ship at the bundle root
# alongside main.tex so _render_cover's bare \includegraphics resolves.  Which
# assets ship is driven by the layouts in play (cover_layouts.required_assets),
# not a hardcoded list here — a new report cover ships its own assets with no
# edit to this module.  ALL_COVER_ASSETS is every registered layout's assets
# (used to declare the managed-dir entries, which must be static).
import document_model.cover_layouts as _cover_layouts

ALL_COVER_ASSETS = _cover_layouts.required_assets(_cover_layouts._COVER_LAYOUTS)

# Default destination for the CLI demo bundle.  dist/ is gitignored so the
# generated zip never accidentally gets committed.
DEFAULT_BUNDLE_PATH = REPO_ROOT / "dist" / "niehs-overleaf-bundle.zip"

# Where dev / working report documents live — one TRACKED directory per session,
# the expanded Overleaf bundle materialized as real files.  This is the local
# git working tree that Overleaf's git-bridge will push/pull (ADR-0005), kept in
# sync with the session cache under sessions/<dtxsid>/.  Unlike dist/ (gitignored
# zips), documents/ is committed so the working tree is portable.
DOCUMENTS_DIR = REPO_ROOT / "documents"

# Sync sidecar dropped in each document directory.  Links the document back to
# its source session and records a content fingerprint, so we can tell when a
# re-sync is needed and (later, ADR-0005) which git commit the generated
# baseline corresponds to.  Deterministic — no timestamps — so an unchanged
# re-sync produces no sidecar diff.
_SYNC_SIDECAR = ".rlm-sync.json"

# Files/dirs the directory writer fully OWNS and regenerates on every sync.  A
# re-sync clears these first so a chart that disappeared upstream (or a renamed
# file) doesn't linger.  Everything else in the document directory — notably
# .git and the .rlm-sync.json sidecar — is left untouched.
_MANAGED_DIR_ENTRIES = (
    "main.tex", "report.tex", "niehs.cls", "README.md", "figures",
    *ALL_COVER_ASSETS,
)


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

The main file is `main.tex` (Overleaf's default main document) — it holds the
preamble and `\\input`s `report.tex`, which carries the report body.  Edit the
prose in `report.tex`.  The class file `niehs.cls` defines the NIEHS styling
(page geometry, table layout, footnote chrome) and lives alongside; you don't
need to touch it.

## What's in the bundle

| File                | Purpose                                                |
|---------------------|--------------------------------------------------------|
| `main.tex`          | Entry document: preamble + `\\input{report}`.  Compile this. |
| `report.tex`        | The report body.  Edit this in Overleaf to revise prose.|
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

From a developer terminal in the source repo:

```
# Scaffold-only bundle (structural skeleton, no chemical-specific data)
uv run python -m latex_export

# Real-session bundle — overlays cached state from sessions/<dtxsid>/
uv run python -m latex_export --session --dtxsid DTXSID50469320
```
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


def _read_cover_asset(name: str) -> bytes:
    """
    Read a cover asset (background image / NIH badge) by basename from the
    cover_layouts assets/ dir.

    Same fail-loud contract as _read_class_file: a missing asset is a packaging
    bug (the cover node's \\includegraphics would fail to compile), not user
    error.
    """
    path = _cover_layouts.asset_path(name)
    if not path.exists():
        raise FileNotFoundError(
            f"Expected cover asset {name!r} at {path} — the bundle exporter "
            f"cannot ship without it (the cover page's \\includegraphics needs it)."
        )
    return path.read_bytes()


def _cover_subtypes_in_tree(tree) -> "list":
    """
    The cover / title-page subtypes present in a document tree (defaulting when a
    node carries none), so the assembler ships exactly the assets those covers
    need.  Falls back to the global DOCUMENT_TREE when tree is None.
    """
    from document_model.document_tree import DOCUMENT_TREE, walk_tree
    subtypes: list = []
    seen = set()

    def visit(node):
        if node.node_type in ("cover", "title-page"):
            key = node.subtype  # None → default, resolved by required_assets
            if key not in seen:
                seen.add(key)
                subtypes.append(key)

    walk_tree(tree if tree is not None else DOCUMENT_TREE, visit)
    return subtypes


# ---------------------------------------------------------------------------
# Session cache loader — turns a session directory into a data dict
# ---------------------------------------------------------------------------

# Where session caches live.  This module assumes the conventional repo
# layout: sessions/<DTXSID>/ holds the per-chemical state.
_SESSIONS_DIR = REPO_ROOT / "sessions"


def _resolve_apical_filters(dtxsid: str, version: str | None) -> dict:
    """
    Resolve the apical + organ-weight allowlists for a version into the flat
    args apply_section_filters / apply_apical_filters take.

    Reads the version's canonical filters (version_config.resolve_version_filters,
    which falls back to the global template for 'default' / no override) and
    projects them to legacy-shaped allowlists via resolve_report_allowlist.
    All-None ⇒ no filtering (the full superset renders).
    """
    from document_model.version_config import resolve_version_filters, DEFAULT_VERSION
    from document_model.document_template import resolve_report_allowlist

    filters = resolve_version_filters(dtxsid, version or DEFAULT_VERSION).get("filters") or {}

    def _area(dim, area):
        return resolve_report_allowlist(filters, dim, area)

    # assays: rebuild the {area: [tokens] | {sex: [tokens]}} shape the apical
    # filter expects, from the canonical {area: {sex: [tokens]}}.
    assays = {}
    for area, sexmap in (filters.get("assays") or {}).items():
        if set(sexmap) == {"*"}:
            assays[area] = sexmap["*"]
        else:
            assays[area] = {s: t for s, t in sexmap.items() if s != "*"}
    return {
        "sex_apical": _area("sex", "apical"),
        "sex_ow": _area("sex", "organ-weight"),
        "organ_ow": _area("organs", "organ-weight"),
        "assays": assays or None,
    }


def _latest(session_dir: Path, glob_pattern: str) -> Path | None:
    """
    Return the most recently modified file matching the glob, or None.

    Session caches are keyed on a hash of the input fingerprints; when
    the inputs change a new cache file appears alongside the old one.
    Picking the newest mtime is the right heuristic for "the active
    cache" in the absence of a manifest.
    """
    candidates = sorted(session_dir.glob(glob_pattern), key=lambda p: p.stat().st_mtime)
    return candidates[-1] if candidates else None


def _load_json(path: Path | None) -> dict | list | None:
    """Read a JSON file or return None if absent / unreadable."""
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _normalize_apical_section(sec: dict) -> dict:
    """
    Backwards-compat shim: delegates to the canonical normalizer in
    report_data so the CLI path and the web-export marshaling path share
    one implementation.
    """
    from rendering.report_data import normalize_apical_section_for_render
    return normalize_apical_section_for_render(sec)


def _load_genomics_interpretations(
    session_dir: Path,
    genomics_cache: dict,
) -> dict[tuple[str, str], dict]:
    """
    Build a {(organ_lower, sex_lower): {gene_set_narrative, gene_narrative}}
    map from the per-organ×sex `_cache_interpretation_<organ>_<sex>_*.json`
    files, keyed off the (post-filter) genomics_cache keys so filtered-out
    sections contribute no narrative.

    Mirrors the canonical reader at session_routes.py: split each
    "<organ>_<sex>" key, build the prefix via the shared
    interpretation_cache_prefix helper, and pick the latest cache by mtime.
    """
    out: dict[tuple[str, str], dict] = {}
    if not isinstance(genomics_cache, dict):
        return out
    from genomics.genomics_narratives import interpretation_cache_prefix
    for key in genomics_cache.keys():
        if "_" not in key:
            continue
        organ_k, sex_k = key.split("_", 1)
        organ_k = organ_k.lower()
        sex_k = sex_k.lower()
        prefix = interpretation_cache_prefix(organ_k, sex_k)
        latest = _latest(session_dir, f"{prefix}*.json")
        interp = _load_json(latest)
        if not isinstance(interp, dict):
            continue
        out[(organ_k, sex_k)] = {
            "gene_set_narrative": interp.get("gene_set_narrative") or [],
            "gene_narrative": interp.get("gene_narrative") or [],
        }
    return out


def _convert_genomics_cache(
    genomics_cache: dict,
    interpretations: dict[tuple[str, str], dict] | None = None,
) -> list[dict]:
    """
    Convert the `_cache_genomics_*.json` shape into the list-of-sections
    form data["genomics_sections"] expects.

    Input shape:  {"<organ>_<sex>": {organ, sex, gene_sets_by_stat,
                  top_genes, ...}, ...}.
    Output shape: a flat list with two entries per organ_sex pair —
    one type="gene_set" using gene_sets_by_stat["median"], one
    type="gene" using top_genes.

    When `interpretations` is provided — a {(organ_lower, sex_lower): {
    gene_set_narrative: [...], gene_narrative: [...]}} map read from the
    per-organ×sex `_cache_interpretation_*.json` files — each entry's
    `narrative` is set to the matching LLM interpretation paragraphs (the
    gene_set entry gets gene_set_narrative, the gene entry gets gene_narrative).
    genomics_content.genomics_content_plan then emits a narrative content item
    ahead of the table.  Omitting the arg (default None) leaves `narrative`
    unset — the pre-feature behaviour, tables only.
    """
    # Group the per-(organ, sex) cache into PER-ORGAN entries that stack both
    # sexes in one table (matching the reference Tables 9–12, which show a Male
    # sub-header block then a Female block).  Two entries per organ — one
    # gene_set, one gene — each carrying an ordered `sexes` list.  Organ order
    # is Liver then Kidney (the reference order); Male before Female within.
    out: list[dict] = []
    if not isinstance(genomics_cache, dict):
        return out
    interp = interpretations or {}

    # Collect the raw per-(organ, sex) cache entries grouped by organ.
    by_organ: dict[str, dict[str, dict]] = {}
    for key in sorted(genomics_cache.keys()):
        entry = genomics_cache[key]
        if not isinstance(entry, dict):
            continue
        organ = (entry.get("organ") or "").strip()
        sex = (entry.get("sex") or "").strip()
        by_organ.setdefault(organ.lower(), {})[sex.lower()] = entry

    def _organ_rank(organ_lower: str) -> tuple[int, str]:
        # Liver first, Kidney second, then anything else alphabetically.
        order = {"liver": 0, "kidney": 1}
        return (order.get(organ_lower, 99), organ_lower)

    def _sex_rank(sex_lower: str) -> tuple[int, str]:
        order = {"male": 0, "female": 1}
        return (order.get(sex_lower, 99), sex_lower)

    for organ_lower in sorted(by_organ, key=_organ_rank):
        sexes = by_organ[organ_lower]
        # Display organ name from the first cache entry (preserves casing).
        any_entry = next(iter(sexes.values()))
        organ_disp = (any_entry.get("organ") or organ_lower).strip()

        gene_set_sexes: list[dict] = []
        gene_sexes: list[dict] = []
        for sex_lower in sorted(sexes, key=_sex_rank):
            entry = sexes[sex_lower]
            sex_disp = (entry.get("sex") or sex_lower).strip()
            interp_entry = interp.get((organ_lower, sex_lower), {})

            gene_sets = (entry.get("gene_sets_by_stat") or {}).get("median") or []
            gs_block = {"sex": sex_disp, "gene_sets": gene_sets}
            gs_narr = interp_entry.get("gene_set_narrative")
            if gs_narr:
                gs_block["narrative"] = gs_narr
            gene_set_sexes.append(gs_block)

            top_genes = [
                {**g, "gene": g.get("gene_symbol") or g.get("gene", "")}
                for g in (entry.get("top_genes", []) or [])
            ]
            gn_block = {"sex": sex_disp, "top_genes": top_genes}
            gn_narr = interp_entry.get("gene_narrative")
            if gn_narr:
                gn_block["narrative"] = gn_narr
            gene_sexes.append(gn_block)

        # Aggregate the per-sex LLM interpretation paragraphs to the entry so the
        # content plan renders them once per organ, ahead of the stacked table.
        # (The section-level intro narrative is often empty for a session; these
        # per-(organ, sex) interpretations are the substantive prose we have.)
        gs_narr_all = [p for b in gene_set_sexes for p in (b.get("narrative") or [])]
        gn_narr_all = [p for b in gene_sexes for p in (b.get("narrative") or [])]

        gene_set_entry = {
            "type": "gene_set",
            "organ": organ_disp,
            "caption": f"Top Gene Sets — {organ_disp.capitalize()}",
            "sexes": gene_set_sexes,
            "go_descriptions": [],
        }
        if gs_narr_all:
            gene_set_entry["narrative"] = gs_narr_all
        out.append(gene_set_entry)

        gene_entry = {
            "type": "gene",
            "organ": organ_disp,
            "caption": f"Top Genes — {organ_disp.capitalize()}",
            "sexes": gene_sexes,
            "gene_descriptions": [],
        }
        if gn_narr_all:
            gene_entry["narrative"] = gn_narr_all
        out.append(gene_entry)
    return out


# The PNG decoder and the chart-attach assembler moved to the shared
# genomics_charts module so BOTH this session-export path AND the web/preview
# path (report_data.marshal_export_data) attach charts identically — see that
# module's header for why the logic can't live privately in either path.  We
# re-bind them to the original private names so this module's internal callers
# (and the unit tests that import them from here) keep working unchanged.
from genomics.genomics_charts import decode_png as _decode_png
from genomics.genomics_charts import attach_genomics_charts as _attach_genomics_charts


def _collect_figure_files(data: dict) -> dict:
    """
    Decode every attached genomics chart into raw PNG bytes keyed by its
    figures/ filename, for build_overleaf_bundle to write into the zip.

    Charts are validated as decodable when attached (_attach_genomics_charts),
    so by here every chart is expected to decode; the None-guard remains as
    defense in depth.
    """
    out: dict[str, bytes] = {}
    for entry in data.get("genomics_sections", []) or []:
        for chart in entry.get("charts") or []:
            name = chart.get("filename")
            raw = _decode_png(chart.get("png_b64"))
            if name and raw is not None:
                out[name] = raw
    return out


def load_session_data(
    dtxsid: str,
    chemical_name: str = "Test Article",
    casrn: str = "000-00-0",
    version: str | None = None,
) -> dict:
    """
    Build a report data dict by overlaying a session's cached state onto
    the canonical scaffold.

    What gets overlaid (when the corresponding cache file exists):

      - data["background"]["paragraphs"]           ← background.json
      - data["abstract"]["sections"]["Background"] ← background.json:abstract_background
      - data["bmd_summary"]["endpoints"]           ← _cache_bmd_summary_*.json:apical
      - data["summary"]["paragraphs"]              ← _cache_summary_generated.json
      - data["apical_sections"]                    ← _cache_sections_*.json:sections (normalized)
      - data["unified_narratives"]                 ← _cache_sections_*.json:unified_narratives
      - data["genomics_sections"]                  ← _cache_genomics_*.json (converted)

    Anything not present in the session caches keeps the scaffold's
    placeholder content.  This way the bundle always has the full
    structure; whatever the session has gets surfaced, whatever it
    doesn't shows as a visible "[pending]" line in Overleaf.

    Args:
        dtxsid:        Session identifier (folder under sessions/).
        chemical_name: Display name for titles and captions.  Should
                       match what's in the session's metadata.
        casrn:         CASRN for the title page.

    Returns:
        A data dict the generator can consume.  Falls back to scaffold-
        only when the session folder doesn't exist.
    """
    # Import lazily — scaffold_report_data has heavy transitive deps
    # (methods_report → llm_helpers → anthropic) we don't want pulled
    # in when latex_export is imported as a library by the web app.
    from rendering.report_data import scaffold_report_data

    data = scaffold_report_data(
        chemical_name=chemical_name,
        casrn=casrn,
        dtxsid=dtxsid,
    )

    # Resolve the sessions root at call time from the canonical source
    # (session_store.SESSIONS_DIR) rather than the import-frozen _SESSIONS_DIR,
    # so a SESSIONS_DIR env override or a test's patched dir is honored.
    from pipeline.session_store import SESSIONS_DIR as _sessions_root
    session_dir = _sessions_root / dtxsid
    if not session_dir.exists():
        # No session on disk — return the scaffold unchanged.  This is
        # the same behavior the scaffold-only CLI invocation produces.
        return data

    # ── Background paragraphs + abstract Background sentence ──────────
    bg = _load_json(session_dir / "background.json")
    if isinstance(bg, dict):
        if bg.get("paragraphs"):
            data["background"] = {
                "paragraphs": bg["paragraphs"],
                # Carry references through so a future References handler
                # can pull them from the same blob.
                "references": bg.get("references", []),
            }
        # References: the LLM background pass extracts a numbered reference
        # list (each item already prefixed "[1] ...").  Surface it in the
        # References section — a plain narrative node whose handler renders
        # data["references"]["paragraphs"], one reference per paragraph.
        if bg.get("references"):
            data["references"] = {"paragraphs": bg["references"]}
        abs_bg = (bg.get("abstract_background") or "").strip()
        if abs_bg and isinstance(data.get("abstract"), dict):
            sections = data["abstract"].setdefault("sections", [])
            # Replace any existing scaffold "Background" entry rather
            # than appending a duplicate.
            replaced = False
            for s in sections:
                if isinstance(s, dict) and s.get("label") == "Background":
                    s["text"] = abs_bg
                    replaced = True
                    break
            if not replaced:
                sections.insert(0, {"label": "Background", "text": abs_bg})

    # ── BMD summary endpoints ─────────────────────────────────────────
    bmd_path = _latest(session_dir, "_cache_bmd_summary_*.json")
    bmd_cache = _load_json(bmd_path)
    if isinstance(bmd_cache, dict) and bmd_cache.get("apical"):
        data["bmd_summary"] = {
            "paragraphs": data.get("bmd_summary", {}).get("paragraphs", []),
            "endpoints": bmd_cache["apical"],
        }

    # ── Summary paragraphs ────────────────────────────────────────────
    summary_cache = _load_json(session_dir / "_cache_summary_generated.json")
    if isinstance(summary_cache, dict) and summary_cache.get("paragraphs"):
        data["summary"] = {"paragraphs": summary_cache["paragraphs"]}

    # ── Apical sections + unified narratives ──────────────────────────
    # The sections cache is the filter-AGNOSTIC superset (phase 2).  Apply THIS
    # version's apical + organ-weight filters here — the render-time analog of
    # what run_process does at presentation — so the bundle shows the version's
    # selected sexes/assays/organs.  Resolve the version's filters (falling back
    # to the global template for 'default'); {} ⇒ no filtering (full superset).
    _vf = _resolve_apical_filters(dtxsid, version)
    sections_path = _latest(session_dir, "_cache_sections_*.json")
    sections_cache = _load_json(sections_path)
    if isinstance(sections_cache, dict):
        raw_sections = sections_cache.get("sections", []) or []
        if raw_sections:
            from pipeline.processing_helpers import apply_section_filters
            raw_sections = apply_section_filters(
                raw_sections,
                sex_allow=_vf["sex_apical"],
                assay_filters=_vf["assays"],
                organ_allowlist=_vf["organ_ow"],
                ow_sex_allow=_vf["sex_ow"],
                compound_name=chemical_name,
            )
            data["apical_sections"] = [
                _normalize_apical_section(s) for s in raw_sections
            ]
        # Unified cross-platform narratives are cached in the sections blob under
        # the `unified_narratives` key (run_process writes the default-filtered
        # set there for the session-reload export path).  Overlay when present;
        # absent ⇒ the scaffold placeholders stand.  (Per-version narrative
        # regeneration is a follow-up — the default version, which the Overleaf
        # export uses today, is correct.)
        unified = sections_cache.get("unified_narratives")
        if isinstance(unified, dict) and unified:
            data["unified_narratives"] = unified

    # ── Materials & Methods prose ─────────────────────────────────────
    # The LLM Methods pass writes a bare dict with a `sections` list whose
    # entries are keyed by the SAME `methods_key`s the template uses, so
    # render_common.methods_subsection_content resolves each M&M subsection by
    # key.  scaffold_report_data already seeds the heading-only M&M tree; this
    # replaces the empty `sections` with the cached prose (mirrors the HTML
    # path at report_data.py).  Omitted ⇒ subsections stay "[Section pending]".
    methods_cache = _load_json(_latest(session_dir, "_cache_methods_*.json"))
    if isinstance(methods_cache, dict) and methods_cache.get("sections"):
        data["methods"] = {"sections": methods_cache["sections"]}

    # ── Table 1: Final Sample Counts (the sample-counts-table tree node) ──
    # Built from the cached MethodsContext; when that context lacks
    # genomics_sample_counts (a stale cache), build_sample_counts_from_context
    # reconstructs them from this session's _fingerprints.json, so an older
    # session still renders Table 1.  None ⇒ the node shows its pending stub.
    if isinstance(methods_cache, dict) and methods_cache.get("context"):
        from tables.methods_table1 import build_sample_counts_from_context
        sample_counts = build_sample_counts_from_context(
            methods_cache["context"], session_dir,
        )
        if sample_counts:
            data["sample_counts"] = sample_counts

    # ── Genomics sections ─────────────────────────────────────────────
    # The on-disk genomics cache is the FULL, filter-agnostic extraction (the
    # web pipeline saves it before filtering).  Re-apply the report-level
    # genomics allowlists HERE — the SAME filter_genomics_sections the web path
    # uses — so the Overleaf bundle and the HTML preview render the identical
    # set.  (Loaded from the active template; {} / [] ⇒ no filtering.)
    genomics_path = _latest(session_dir, "_cache_genomics_*.json")
    genomics_cache = _load_json(genomics_path)
    if isinstance(genomics_cache, dict) and genomics_cache:
        from document_model.document_tree import ACTIVE_TEMPLATE
        from document_model.document_template import (
            load_report_organs, load_report_sex,
            load_report_genes, load_report_gene_sets,
        )
        from tables.table_builder_common import filter_genomics_sections
        genomics_cache = filter_genomics_sections(
            genomics_cache,
            organ=load_report_organs(ACTIVE_TEMPLATE).get("genomics"),
            sex=load_report_sex(ACTIVE_TEMPLATE).get("genomics"),
            genes=load_report_genes(ACTIVE_TEMPLATE),
            gene_sets=load_report_gene_sets(ACTIVE_TEMPLATE),
        )
        # Genomics LLM interpretation: the per-organ×sex biology analysis lives
        # in `_cache_interpretation_<organ>_<sex>_*.json` (top-level
        # gene_set_narrative / gene_narrative paragraph lists), generated and
        # shown on the HTML preview but never carried onto the .tex entries.
        # Build a {(organ,sex): {gene_set_narrative, gene_narrative}} map keyed
        # off the SURVIVING (post-filter) genomics keys, picking the latest
        # cache per organ×sex — the same reader session_routes uses.
        interpretations = _load_genomics_interpretations(
            session_dir, genomics_cache,
        )
        converted = _convert_genomics_cache(genomics_cache, interpretations)
        if converted:
            data["genomics_sections"] = converted

    # Positional table numbers for the data-driven genomics tables — continues
    # the tree sequence (Table 8 → 9, 10, ...).  Same helper the web/marshal path
    # calls, so both surfaces number identically.  Runs after genomics_sections
    # is finalized; a no-op when there are none.
    from document_model.document_tree import DOCUMENT_TREE, assign_genomics_table_numbers
    assign_genomics_table_numbers(DOCUMENT_TREE, data.get("genomics_sections"))

    # ── Genomics charts (base64 PNG) attached to the gene_set entries ──
    # The active template's `charts:` allowlist decides WHICH chart types render
    # (None ⇒ all; [] ⇒ none) — honored here so the Overleaf bundle and the HTML
    # preview show the identical set of figures.
    charts_path = _latest(session_dir, "_cache_charts_*.json")
    charts_cache = _load_json(charts_path)
    if isinstance(charts_cache, list) and data.get("genomics_sections"):
        from document_model.document_tree import ACTIVE_TEMPLATE
        from document_model.document_template import load_report_charts
        _attach_genomics_charts(
            data["genomics_sections"], charts_cache,
            enabled_types=load_report_charts(ACTIVE_TEMPLATE),
        )

    # ── Appendix B: animal identifier roster ──────────────────────────
    animals = _load_animal_identifiers(session_dir)
    if animals:
        data["appendix_animals"] = animals

    # ── Abstract (Background + Results + Summary) ─────────────────────
    # Use the SHARED assembler (the same one the web path calls) so both
    # surfaces produce the same abstract.  We pass explicit inputs: the apical
    # endpoints come from `data["bmd_summary"]`, the Background sentence from
    # background.json, and the genomics cache we ALREADY loaded above (so it is
    # not re-read from disk, and there is no second session-path assumption).
    # The Methods abstract sentence is assembled by overlay_abstract itself; we
    # don't pass an explicit methods_context here (the M&M prose is overlaid
    # onto data["methods"] above and rendered directly by the M&M nodes).
    from rendering.report_data_overlays import overlay_abstract
    overlay_abstract(
        data,
        abstract_background=(bg.get("abstract_background") if isinstance(bg, dict) else "") or "",
        genomics_cache=genomics_cache if isinstance(genomics_cache, dict) else None,
        dose_unit="mg/kg",
    )

    # ── User-owned content overrides (ADR-0005 round-trip) ────────────
    # Edits a human made to report.tex (in Overleaf, the local stand-in, or by
    # hand) are reconciled into a per-anchor override store.  Surface them so
    # the generator emits the user's version instead of regenerating over it.
    # Keyed by the SAME anchor ids the generator emits (node.id /
    # "<node>::<item>").  Empty when the session has no edits → byte-identical
    # default.  The web/marshal path doesn't set data["overrides"], so it is
    # unaffected until that path opts in.
    from roundtrip.overrides import load_overrides
    data["overrides"] = load_overrides(dtxsid)

    # ── Per-node protection marks (ADR-0014 step 5 render channel, 4b) ─
    # Derive {node.id -> GuardLevel} from the ownership state overlaid onto
    # `data` (approved / user-edited sections), keyed by the SAME node ids the
    # generator emits. render_common.resolve_protection reads it under
    # data["protection"]; an all-OPEN result is omitted → {} → byte-identical.
    from document_model.document_tree import DOCUMENT_TREE as _DOC_TREE
    from workflow.ownership import protection_map
    _protection = protection_map(_DOC_TREE, data)
    if _protection:
        data["protection"] = _protection

    # ── Manual Table of Contents / Tables list ────────────────────────
    # The docx and HTML surfaces render a STATIC contents list from
    # data["toc_entries"] / data["table_entries"] (LaTeX uses native
    # \tableofcontents, so it doesn't need this).  The web/marshal path
    # builds these via _build_toc_entries after overlay; the session-cache
    # path must too, or the docx/HTML Contents page comes up empty.  Runs
    # after genomics table numbers are assigned so the Tables list is
    # complete.  Also serialize the tree the same way marshal does.
    from document_model.document_tree import serialize_tree
    from rendering.report_data_toc import _build_toc_entries
    data["document_tree"] = serialize_tree(DOCUMENT_TREE)
    toc_entries, table_entries = _build_toc_entries(data, tree=DOCUMENT_TREE)
    data["toc_entries"] = toc_entries
    data["table_entries"] = table_entries

    # ── Per-node layout styling (page breaks, typography) ─────────────
    # The template's `styles:` block (+ any per-session styles.yaml override) is
    # the canonical, surface-agnostic per-node style config — including page
    # breaks declared as `break_before: page` on a node id.  The WEB path wires
    # this via report_data._resolve_layout_config; the session/export path (this
    # function) did NOT, so template `styles.instances` breaks were silently
    # ignored on the docx/Overleaf output.  Resolve it here the same way (global
    # template ← per-session override), keyed by this session's dtxsid, so all
    # three surfaces see the same break/typography decisions.
    data["layout_style"] = _resolve_export_layout_style(dtxsid)

    return data


def _resolve_export_layout_style(dtxsid: str) -> dict:
    """The resolved {defaults, types, instances} layout-style config for the
    export path: the global template `styles:` block merged with an optional
    per-session `styles.yaml` override (session wins).  Mirrors
    report_data._resolve_layout_config minus the request-body layer (there is no
    live request on the export path).  Empty ⇒ {} ⇒ no per-node styling."""
    from genomics.chart_style import deep_merge
    from document_model.document_template import load_layout_style
    from document_model.document_tree import ACTIVE_TEMPLATE

    template_cfg = load_layout_style(ACTIVE_TEMPLATE)
    session_cfg = None
    if dtxsid:
        from document_model.document_config import load_session_layout_style
        session_cfg = load_session_layout_style(dtxsid)
    return deep_merge(template_cfg, session_cfg)


# Appendix B / Table B-1 reconstructs the reference's "Animal Numbers and FASTQ
# Data File Names": one row per (animal x sequenced tissue).  animal_report.json
# stores that same fact spread across THREE id-forms per physical animal — a bare
# numeric ANIMAL NUMBER ("111"), a "Plate1-111" LIVER FASTQ file id, and a
# "Plate5-111" KIDNEY FASTQ file id.  The tissue is encoded ONLY in the plate
# prefix (the reference's own Table B-1 pairs Plate1->Liver, Plate5->Kidney);
# domain_presence just says "Gene Expression".  Centralized so the mapping has
# one home if it ever grows.
_PLATE_TISSUE = {"plate1": "Liver", "plate5": "Kidney"}


def _animal_core(animal_id: str) -> str:
    """The trailing numeric run of an id — the physical ANIMAL NUMBER that joins
    the bare / Plate1- / Plate5- forms.  '' when the id has no numeric tail."""
    m = re.search(r"(\d+)$", str(animal_id or ""))
    return m.group(1) if m else ""


def _load_animal_identifiers(session_dir: Path) -> list[dict]:
    """
    Build the Appendix B FASTQ-mapping roster (reference Table B-1) from
    animal_report.json: one row per (animal x tissue), joining the three id-forms
    by their shared numeric ANIMAL NUMBER.

    Row schema: {animal_number, sex, dose, tissue, fastq_file_id}.  The bare
    numeric record supplies animal_number/sex/dose; each Plate<N>-<num> record
    supplies one tissue row (tissue from the plate prefix, fastq_file_id = the
    plate id itself).  Rows are sorted by numeric animal number, then tissue with
    Kidney before Liver (matching the reference).  Returns [] when the file is
    absent — the appendix then keeps its pending placeholder.

    Columns "Group" (Vehicle control / dose label) and "Survived to Study
    Termination" from the reference are intentionally OMITTED — neither is in our
    per-animal data ({animal_id, sex, dose, selection, domain_presence}); we do
    not fabricate them.

    NOTE: the join lives here because the roster is LaTeX-only today (the
    web/marshal path does not build appendix_animals).  Move it to a shared
    module if the HTML preview grows an Appendix B.
    """
    report = _load_json(session_dir / "animal_report.json")
    animals = report.get("animals") if isinstance(report, dict) else None
    if not isinstance(animals, dict):
        return []

    # Index the bare-numeric records by animal number to supply sex/dose to each
    # tissue row (all id-forms of one animal agree on sex/dose — verified).
    identity: dict[str, dict] = {}
    for rec in animals.values():
        if not isinstance(rec, dict):
            continue
        aid = str(rec.get("animal_id", ""))
        if aid.isdigit():
            identity[aid] = rec

    rows: list[dict] = []
    for rec in animals.values():
        if not isinstance(rec, dict):
            continue
        aid = str(rec.get("animal_id", ""))
        prefix = aid.split("-", 1)[0].lower() if "-" in aid else ""
        tissue = _PLATE_TISSUE.get(prefix)
        if tissue is None:
            continue  # bare-numeric and any unknown-prefix ids carry no tissue row
        core = _animal_core(aid)
        ident = identity.get(core, rec)
        rows.append({
            "animal_number": core or aid,
            "sex": ident.get("sex") or rec.get("sex") or "",
            "dose": ident.get("dose", rec.get("dose")),
            "tissue": tissue,
            "fastq_file_id": aid,
        })

    # Sort by numeric animal number, then Kidney before Liver within an animal.
    _tissue_rank = {"Kidney": 0, "Liver": 1}
    rows.sort(
        key=lambda r: (
            int(r["animal_number"]) if str(r["animal_number"]).isdigit() else 1 << 30,
            _tissue_rank.get(r["tissue"], 9),
        )
    )
    return rows


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_overleaf_bundle(
    data: dict,
    out_path: Path,
    *,
    include_readme: bool = True,
    strict: bool = False,
    tree: "list | None" = None,
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
        strict:         DELIVERABLE gate (issue #3).  When True, refuse to
                        write the zip if the report still contains any
                        "[... pending]" / "[Placeholder: ...]" marker
                        (raises render_common.PendingContentError).  The
                        customer-facing export route passes strict=True;
                        draft/scaffold callers leave it False.

    Returns:
        out_path, for chaining or convenience in the CLI.
    """
    # Ensure the destination directory exists.  dist/ is the canonical
    # location and is gitignored, but callers can write anywhere.
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Assemble the payload once (shared with the directory writer) then stream
    # it into the zip.  ZIP_DEFLATED is standard PKZIP — Overleaf handles it
    # without special flags; ZIP_LZMA is smaller but some importers reject it.
    # strict runs BEFORE the zip is opened, so a gated build writes nothing.
    files = _assemble_bundle_files(data, include_readme=include_readme, strict=strict, tree=tree)
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for relpath, raw in files.items():
            zf.writestr(relpath, raw)

    return out_path


# ---------------------------------------------------------------------------
# Shared payload assembly + the expanded-directory writer (ADR-0005)
# ---------------------------------------------------------------------------

def _assemble_bundle_files(
    data: dict, *, include_readme: bool = True, strict: bool = False,
    tree: "list | None" = None,
) -> "dict[str, bytes]":
    r"""
    Build the in-memory file payload shared by every bundle writer.

    Returns a mapping of POSIX-style relative path -> raw bytes, so a writer
    can either stream it into a zip (build_overleaf_bundle) or materialize it
    as real files in a directory (write_overleaf_dir) without duplicating the
    assembly.  Layout (Option B split — see generate_main_tex/generate_report_body):

        main.tex            the Overleaf ENTRY: preamble + \input{report}.
                            Matches Overleaf's default main document; app-owned.
        report.tex          the report BODY only — sections + round-trip
                            anchors.  This is the editable / reconciled file.
        niehs.cls           copied from <repo>/latex/niehs.cls
        <cover assets>      the cover subtype's images (e.g. cover-bg.jpg +
                            nih-logo.png), from cover_layouts.required_assets —
                            shipped at the root so the cover's \includegraphics
                            resolves
        figures/<name>      one PNG per attached genomics chart (each carries
                            its own filename so the \includegraphics path
                            always matches the written file) …
        figures/.gitkeep    … or an empty placeholder when there are no charts
        README.md           customer-facing instructions (when include_readme)

    strict (issue #3): when True, this is a DELIVERABLE build — scan the
    assembled report body for surviving "[... pending]" / "[Placeholder: ...]"
    markers and raise PendingContentError if any remain, rather than shipping a
    report with visible gaps.  Default False keeps the draft/preview and
    scaffold-test paths unchanged (they legitimately render stubs).  The scan
    runs on report.tex, which is where every node body lands; main.tex is just
    the preamble + \input, so it carries no node content.
    """
    files: "dict[str, bytes]" = {}
    report_body = generate_report_body(data, tree=tree)
    if strict:
        from rendering.render_common import scan_pending_markers, PendingContentError
        markers = scan_pending_markers(report_body)
        if markers:
            raise PendingContentError(markers)
    files["main.tex"] = generate_main_tex(data).encode("utf-8")
    files["report.tex"] = report_body.encode("utf-8")
    files["niehs.cls"] = _read_class_file().encode("utf-8")
    # Cover assets for whatever cover subtypes the tree uses (background, badge),
    # shipped at the bundle root so the cover's bare \includegraphics resolves.
    for asset in _cover_layouts.required_assets(_cover_subtypes_in_tree(tree)):
        files[asset] = _read_cover_asset(asset)
    figures = _collect_figure_files(data)
    if figures:
        for fig_name, raw in figures.items():
            files[f"figures/{fig_name}"] = raw
    else:
        files["figures/.gitkeep"] = b""
    if include_readme:
        files["README.md"] = _README_TEMPLATE.encode("utf-8")
    return files


def _write_files_to_dir(files: "dict[str, bytes]", out_dir: Path) -> Path:
    """
    Materialize an assembled payload as real files under out_dir.

    Clears the managed entries (_MANAGED_DIR_ENTRIES) first so stale figures or
    a renamed file don't linger across syncs, then writes each payload file
    (creating figures/ as needed).  Anything outside the managed set — .git,
    the .rlm-sync.json sidecar — is left untouched.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in _MANAGED_DIR_ENTRIES:
        target = out_dir / name
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
    for relpath, raw in files.items():
        dest = out_dir / relpath
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
    return out_dir


def write_overleaf_dir(
    data: dict, out_dir: Path, *, include_readme: bool = True, strict: bool = False,
) -> Path:
    """
    Write the Overleaf bundle as an EXPANDED DIRECTORY (not a zip).

    Same payload as build_overleaf_bundle, materialized as real files so the
    directory can be a tracked git working tree — the local copy Overleaf's
    git-bridge pushes/pulls (ADR-0005).

    v1 is OUTBOUND ONLY: every call overwrites the managed files
    (report.tex, niehs.cls, figures/, README.md) from the session cache.  It
    does NOT preserve in-place edits yet — protecting human edits is the
    ADR-0005 reconciliation step (override store + diff attribution).

    strict (issue #3): when True, the assembly raises PendingContentError
    before any file is written if the report still contains pending markers —
    so a gated sync leaves the existing directory untouched.

    Returns out_dir.
    """
    return _write_files_to_dir(
        _assemble_bundle_files(data, include_readme=include_readme, strict=strict),
        out_dir,
    )


def _content_hash(files: "dict[str, bytes]") -> str:
    """
    Deterministic fingerprint of a bundle payload.

    Hashes each file's path + bytes in sorted order — no timestamps — so the
    same cached data always yields the same hash.  The sync sidecar therefore
    only changes when the actual content changes, keeping git diffs meaningful.
    """
    digest = hashlib.sha256()
    for relpath in sorted(files):
        digest.update(relpath.encode("utf-8"))
        digest.update(b"\0")
        digest.update(files[relpath])
        digest.update(b"\0")
    return digest.hexdigest()


def sync_document(
    dtxsid: str,
    chemical_name: str = "Test Article",
    casrn: str = "000-00-0",
    *,
    docs_root: Path = DOCUMENTS_DIR,
    strict: bool = False,
) -> Path:
    """
    Materialize / refresh a session's dev document directory from its cache.

    Loads the session's cached state (load_session_data), writes the expanded
    Overleaf bundle into docs_root/<dtxsid>/, and drops a .rlm-sync.json sidecar
    recording the source session + a content fingerprint.

    On-demand (v1): call whenever you want the document brought current with the
    cache.  Outbound only — see write_overleaf_dir for the edit-preservation
    caveat.

    strict (issue #3): when True, refuse to sync if the report still contains
    "[... pending]" / "[Placeholder: ...]" markers (raises
    PendingContentError) — the existing directory + sidecar are left as they
    were.  Left False for the dev-directory refresh, which is a working draft
    that legitimately shows the gaps still to fill.

    Returns the document directory.
    """
    data = load_session_data(dtxsid, chemical_name=chemical_name, casrn=casrn)
    out_dir = docs_root / dtxsid

    # Assemble once; reuse the same payload for both the files we write and the
    # fingerprint we record, so generate_latex runs exactly once.  strict runs
    # inside the assembly (before any write), so a gated sync is a no-op on disk.
    files = _assemble_bundle_files(data, strict=strict)
    _write_files_to_dir(files, out_dir)

    sidecar = {
        "source_session": f"sessions/{dtxsid}",
        "dtxsid": dtxsid,
        "content_hash": _content_hash(files),
        # Filled in by the ADR-0005 round-trip layer once this directory is a
        # git remote: the commit representing this generated baseline, against
        # which pulled-back Overleaf edits are diffed.
        "baseline_commit": None,
    }
    (out_dir / _SYNC_SIDECAR).write_text(json.dumps(sidecar, indent=2) + "\n")
    return out_dir


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
    from rendering.report_data import scaffold_report_data

    parser = argparse.ArgumentParser(
        description="Build an Overleaf-ready zip from session or scaffold data.",
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
        help="DSSTox ID — used as a session identifier when --session is also "
             "passed; otherwise just metadata for the scaffold path.",
    )
    parser.add_argument(
        "--session",
        action="store_true",
        help="Overlay real session content from sessions/<dtxsid>/ on top of "
             "the scaffold.  Sections without cached data still render as "
             "visible [pending] placeholders.  Without this flag the bundle "
             "renders pure scaffold (no session-specific content).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_BUNDLE_PATH,
        help=f"Zip output path (default: {DEFAULT_BUNDLE_PATH})",
    )
    parser.add_argument(
        "--sync-document",
        action="store_true",
        help="Instead of writing a zip, materialize/refresh the dev document "
             "directory documents/<dtxsid>/ from the session cache (the "
             "ADR-0005 git-bridge working tree).  Implies session data.",
    )
    args = parser.parse_args()

    # Dev-document sync path: write the expanded, tracked bundle directory
    # (documents/<dtxsid>/) from session cache, instead of a zip.  Always uses
    # session data — a scaffold-only dev document would defeat the purpose.
    if args.sync_document:
        out_dir = sync_document(
            dtxsid=args.dtxsid,
            chemical_name=args.chemical_name,
            casrn=args.casrn,
        )
        written = sorted(p.relative_to(out_dir).as_posix()
                         for p in out_dir.rglob("*") if p.is_file())
        print(f"Synced dev document → {out_dir}")
        for rel in written:
            print(f"  {rel}")
        return

    # Two build paths:
    #
    #   --session   →  load_session_data overlays cached state on the
    #                  scaffold; the resulting .tex carries real prose,
    #                  real BMD summary rows, real gene-set rankings,
    #                  etc.  Used for the customer demo.
    #
    #   scaffold-only (no --session)  →  pure boilerplate front matter
    #                  + empty body stubs.  Used to demonstrate the
    #                  document structure without coupling to any
    #                  particular session.
    if args.session:
        data = load_session_data(
            dtxsid=args.dtxsid,
            chemical_name=args.chemical_name,
            casrn=args.casrn,
        )
    else:
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
