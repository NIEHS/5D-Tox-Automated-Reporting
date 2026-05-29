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

    from report_data import scaffold_report_data
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
import base64
import json
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


# ---------------------------------------------------------------------------
# Session cache loader — turns a session directory into a data dict
# ---------------------------------------------------------------------------

# Where session caches live.  This module assumes the conventional repo
# layout: sessions/<DTXSID>/ holds the per-chemical state.
_SESSIONS_DIR = REPO_ROOT / "sessions"


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
    from report_data import normalize_apical_section_for_render
    return normalize_apical_section_for_render(sec)


def _convert_genomics_cache(genomics_cache: dict) -> list[dict]:
    """
    Convert the `_cache_genomics_*.json` shape into the list-of-sections
    form data["genomics_sections"] expects.

    Input shape:  {"<organ>_<sex>": {organ, sex, gene_sets_by_stat,
                  top_genes, ...}, ...}.
    Output shape: a flat list with two entries per organ_sex pair —
    one type="gene_set" using gene_sets_by_stat["median"], one
    type="gene" using top_genes.
    """
    out: list[dict] = []
    if not isinstance(genomics_cache, dict):
        return out
    for key in sorted(genomics_cache.keys()):
        entry = genomics_cache[key]
        if not isinstance(entry, dict):
            continue
        organ = entry.get("organ", "")
        sex = entry.get("sex", "")
        # Gene-set entry — pull from gene_sets_by_stat using the median
        # statistic (the canonical default; the UI lets users switch
        # but the LaTeX path renders one view).
        gene_sets = (
            (entry.get("gene_sets_by_stat") or {}).get("median")
            or []
        )
        out.append({
            "type": "gene_set",
            "organ": organ,
            "sex": sex,
            "caption": f"Top Gene Sets — {organ.capitalize()}, {sex.capitalize()}",
            "gene_sets": gene_sets,
            "go_descriptions": [],
        })
        # Gene entry — map gene_symbol → gene to match generator's expected key
        top_genes_raw = entry.get("top_genes", []) or []
        top_genes = [
            {**g, "gene": g.get("gene_symbol") or g.get("gene", "")}
            for g in top_genes_raw
        ]
        out.append({
            "type": "gene",
            "organ": organ,
            "sex": sex,
            "caption": f"Top Genes — {organ.capitalize()}, {sex.capitalize()}",
            "top_genes": top_genes,
            "gene_descriptions": [],
        })
    return out


def _decode_png(b64: str | None) -> bytes | None:
    """
    Decode a base64 PNG (raw, or "data:image/png;base64,..." form) to bytes,
    returning None if it is missing or won't decode.
    """
    if not b64:
        return None
    if b64.startswith("data:"):
        b64 = b64.split(",", 1)[-1]
    try:
        return base64.b64decode(b64)
    except Exception:
        return None


def _attach_genomics_charts(genomics_sections: list, charts_cache: list) -> None:
    """
    Attach per-(organ, sex) chart images to the matching gene_set entries.

    `charts_cache` is the `_cache_charts_*.json` list: one entry per (organ,
    sex) carrying base64-PNG fields umap_png / cluster_png (+ captions).  We
    index it by (organ, sex) and hang the images on the gene_set genomics entry
    as entry["charts"], so genomics_content_plan emits chart content items and
    build_overleaf_bundle writes the PNGs into figures/.

    Each chart carries its OWN deterministic `filename`; both the renderer
    (the \\includegraphics path) and the bundler (the file it writes) read that
    same field, so they can never disagree on the name — a mismatch would be a
    missing-figure compile error on Overleaf.
    """
    if not isinstance(charts_cache, list):
        return
    by_os = {
        ((c.get("organ") or "").lower(), (c.get("sex") or "").lower()): c
        for c in charts_cache if isinstance(c, dict)
    }
    for entry in genomics_sections:
        if entry.get("type") != "gene_set":
            continue
        organ = (entry.get("organ") or "").lower()
        sex = (entry.get("sex") or "").lower()
        cache_entry = by_os.get((organ, sex))
        if not cache_entry:
            continue
        slug = f"{organ}-{sex}".replace(" ", "-")
        charts = []
        for key in ("umap", "cluster"):
            png = cache_entry.get(f"{key}_png")
            if not png:
                continue
            # Validate the base64 decodes NOW and drop a chart we can't decode,
            # so it never reaches the renderer as a \includegraphics with no
            # backing file in figures/ (which would break the Overleaf compile).
            if _decode_png(png) is None:
                continue
            charts.append({
                "key": key,
                "filename": f"genomics-{slug}-{key}.png",
                "png_b64": png,
                "caption": cache_entry.get(f"{key}_caption", ""),
            })
        if charts:
            entry["charts"] = charts


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
    from report_data import scaffold_report_data

    data = scaffold_report_data(
        chemical_name=chemical_name,
        casrn=casrn,
        dtxsid=dtxsid,
    )

    session_dir = _SESSIONS_DIR / dtxsid
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
    sections_path = _latest(session_dir, "_cache_sections_*.json")
    sections_cache = _load_json(sections_path)
    if isinstance(sections_cache, dict):
        raw_sections = sections_cache.get("sections", []) or []
        if raw_sections:
            data["apical_sections"] = [
                _normalize_apical_section(s) for s in raw_sections
            ]
        unified = sections_cache.get("unified_narratives")
        if isinstance(unified, dict) and unified:
            data["unified_narratives"] = unified

    # ── Genomics sections ─────────────────────────────────────────────
    genomics_path = _latest(session_dir, "_cache_genomics_*.json")
    genomics_cache = _load_json(genomics_path)
    if isinstance(genomics_cache, dict) and genomics_cache:
        converted = _convert_genomics_cache(genomics_cache)
        if converted:
            data["genomics_sections"] = converted

    # ── Genomics charts (base64 PNG) attached to the gene_set entries ──
    charts_path = _latest(session_dir, "_cache_charts_*.json")
    charts_cache = _load_json(charts_path)
    if isinstance(charts_cache, list) and data.get("genomics_sections"):
        _attach_genomics_charts(data["genomics_sections"], charts_cache)

    # ── Appendix B: animal identifier roster ──────────────────────────
    animals = _load_animal_identifiers(session_dir)
    if animals:
        data["appendix_animals"] = animals

    return data


def _load_animal_identifiers(session_dir: Path) -> list[dict]:
    """
    Flatten animal_report.json into a roster of {animal_id, sex, dose} rows for
    Appendix B (Animal Identifiers), sorted by sex, then dose, then id.  Returns
    [] when the file is absent — the appendix then keeps its pending placeholder.
    """
    report = _load_json(session_dir / "animal_report.json")
    animals = report.get("animals") if isinstance(report, dict) else None
    if not isinstance(animals, dict):
        return []
    rows = [
        {
            "animal_id": rec.get("animal_id", ""),
            "sex": rec.get("sex") or "",
            "dose": rec.get("dose"),
        }
        for rec in animals.values()
        if isinstance(rec, dict)
    ]
    # Numeric doses sort ahead of missing ones; ids break ties.
    rows.sort(
        key=lambda r: (
            r["sex"],
            r["dose"] if isinstance(r["dose"], (int, float)) else float("inf"),
            r["animal_id"],
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
        # Genomics chart images (base64 PNG attached to gene_set entries by
        # load_session_data) become real files under figures/, referenced by
        # \includegraphics in report.tex.  Each chart carries its own filename
        # so the .tex path and the written file always match.  Falls back to an
        # empty .gitkeep (so the dir still materializes) when there are no
        # charts — e.g. a scaffold-only export.
        figures = _collect_figure_files(data)
        if figures:
            for fig_name, raw in figures.items():
                zf.writestr(f"figures/{fig_name}", raw)
        else:
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
    from report_data import scaffold_report_data

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
    args = parser.parse_args()

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
