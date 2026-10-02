#!/usr/bin/env python3
"""tooling/generate_report.py — generate a report end-to-end without the web UI.

One command that drives the SAME UI-agnostic workflow core the browser drives
(ADR-0014: `workflow.steps` over a `DiskPoolStore`), then renders the
deliverables from the session on disk:

    import files → validate → confirm metadata → integrate → animal report
      → process → materialize result sections → [background] → render

Every step reads and writes `sessions/<DTXSID>/`, so a session produced here is
indistinguishable from one produced in the browser — you can open it in the web
UI afterwards, or re-run this command and the cache-keyed steps finish in seconds.

The env the Java + LLM layers need (JDK 21 first on PATH, BMDX_PROJECT_ROOT,
SSL_CERT_FILE for the NIEHS LiteLLM proxy) is defaulted here the same way
run-server.sh does it, BEFORE any first-party import (bmdx_pipe.java_bridge
reads BMDX_PROJECT_ROOT at import time). Shell-set values win.

Usage (from the repo root):
    python -m tooling.generate_report DTXSID50469320 \
        --files /data/pfhxsam/*.bm2 /data/pfhxsam/*.txt \
        --name "Perfluorohexanesulfonamide" --casrn 41997-13-1 --dose-unit mg/kg

    # re-render an already-processed session, no pipeline work
    python -m tooling.generate_report DTXSID50469320 --render-only --surfaces docx,pdf

See docs/headless-report-generation.md for the full manual.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Render surfaces this script can write, mapped to their output filename suffix.
#   docx/html/jats/bookshelf — rendering.preview_surface (the Preview step's emitters)
#   latex — the Overleaf bundle zip (same as POST /api/export-overleaf-bundle)
#   pdf   — that bundle compiled locally with `tect` (same as POST /api/compile-pdf)
SURFACE_SUFFIX = {
    "docx": ".docx",
    "html": ".html",
    "jats": ".xml",
    "bookshelf": ".bookshelf.html",
    "latex": "-overleaf.zip",
    "pdf": ".pdf",
}
STEPS = ("validate", "integrate", "process")


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

def _bootstrap_env() -> None:
    """Default the Java + LLM env exactly as run-server.sh does; shell wins."""
    jdk21 = Path(os.environ.get("BMDX_JDK_HOME", "/opt/liberica-jdk-21"))
    if (jdk21 / "bin" / "java").exists():
        # The Java bridge invokes a BARE `java`, so JDK 21 must lead PATH.
        os.environ["JAVA_HOME"] = str(jdk21)
        os.environ["PATH"] = f"{jdk21 / 'bin'}:{os.environ.get('PATH', '')}"

    if not os.environ.get("BMDX_PROJECT_ROOT"):
        for cand in (Path("/workspace/BMDExpress-3"), Path.home() / "Dev/Projects/BMDExpress-3"):
            if (cand / "target").is_dir():
                os.environ["BMDX_PROJECT_ROOT"] = str(cand)
                break

    # The Python SDK honors SSL_CERT_FILE, not Node's NODE_EXTRA_CA_CERTS.
    ca = os.environ.get("SSL_CERT_FILE") or os.environ.get("NODE_EXTRA_CA_CERTS") \
        or "/usr/local/share/ca-certificates/extra/nih-ca-bundle.crt"
    if ca and Path(ca).is_file():
        os.environ["SSL_CERT_FILE"] = ca
        os.environ.setdefault("REQUESTS_CA_BUNDLE", ca)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        _log("WARNING: ANTHROPIC_API_KEY is not set — LLM narratives will fail")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    print(msg, flush=True)


class _Timer:
    """`with _Timer("integrate"):` — prints the step name and its wall time."""

    def __init__(self, label: str):
        self.label = label

    def __enter__(self):
        self.t0 = time.monotonic()
        _log(f"▶ {self.label} …")
        return self

    def __exit__(self, exc_type, *_):
        if exc_type is None:
            _log(f"  ✓ {self.label} ({time.monotonic() - self.t0:.1f}s)")


def _fp(fp, key: str) -> str:
    """Read a fingerprint field whether it is a FileFingerprint or a plain dict."""
    val = getattr(fp, key, None) if hasattr(fp, key) else (fp.get(key) if isinstance(fp, dict) else None)
    return val or ""


def _phase(dtxsid: str, store) -> str:
    from workflow.engine import WorkflowEngine
    return WorkflowEngine(dtxsid, store).state().phase.value


def _resolve_identity(dtxsid: str, args, store) -> dict:
    """Identity for integration: CLI flags over identity.json. When neither gives
    a name, try the network resolver (PubChem/CTX) — best-effort, like the UI."""
    identity = dict(store.read_json(dtxsid, "identity.json") or {})
    identity["dtxsid"] = dtxsid
    if args.name:
        identity["name"] = args.name
    if args.casrn:
        identity["casrn"] = args.casrn
    if not identity.get("name"):
        try:
            from narrative.chem_resolver import resolve_chemical
            resolved = resolve_chemical(dtxsid, "auto", "").to_dict()
            identity = {**resolved, **{k: v for k, v in identity.items() if v}}
            _log(f"  resolved identity from {dtxsid}: {identity.get('name')!r}")
        except Exception as e:  # network-dependent
            _log(f"  WARNING: could not resolve a name for {dtxsid} ({e}); "
                 "pass --name/--casrn")
    return identity


# ---------------------------------------------------------------------------
# Pipeline steps (each one call into workflow.steps)
# ---------------------------------------------------------------------------

def import_files(dtxsid: str, paths: list[Path], store) -> None:
    """Copy input files into sessions/<id>/files/ — the equivalent of the Upload
    step. Validation's disk scan fingerprints them (and converts long-format NTP
    CSVs to the wide pivot + sidecar), so no upload registry is needed. Adding
    files to a pool that has already progressed invalidates its downstream
    artifacts, exactly as an upload through the API does."""
    from pipeline.pool_state import invalidate_pool_artifacts, pool_has_progressed

    files_dir = store.session_dir(dtxsid) / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    progressed = pool_has_progressed(dtxsid)
    for p in paths:
        if not p.is_file():
            raise SystemExit(f"input file not found: {p}")
        shutil.copy2(p, files_dir / p.name)
        _log(f"  + {p.name}")
    if progressed:
        summary = invalidate_pool_artifacts(dtxsid)
        _log(f"  pool had progressed — invalidated {len(summary.get('deleted', []))} artifact(s)")


def validate(dtxsid: str, store) -> dict:
    from workflow.steps import validate_step

    report = validate_step(dtxsid, store)
    issues = report.get("issues", [])
    errors = [i for i in issues if (i or {}).get("severity") == "error"]
    _log(f"  {report.get('file_count')} files, {len(issues)} issue(s) "
         f"({len(errors)} error), platforms: {sorted(report.get('coverage_matrix', {}))}")
    for i in issues:
        _log(f"    [{i.get('severity')}] {i.get('issue_type', '')}: {i.get('message', '')}")
    if errors:
        raise SystemExit("validation found errors — fix the input files and re-run")
    return report


def confirm_metadata(dtxsid: str, corrections_path: Path | None, store) -> None:
    """Apply (platform, data_type) overrides. The JSON file is keyed by FILENAME
    (file ids are minted per scan, so they are not stable across runs)."""
    from workflow.steps import confirm_metadata_step

    fps = store.get_fingerprints(dtxsid)
    by_name = {_fp(fp, "filename"): fid for fid, fp in fps.items()}
    corrections: dict = {}
    if corrections_path:
        for fname, fix in json.loads(corrections_path.read_text()).items():
            if fname not in by_name:
                raise SystemExit(f"--metadata names an unknown file: {fname!r}")
            corrections[by_name[fname]] = fix
    for fp in sorted(fps.values(), key=lambda fp: _fp(fp, "filename")):
        _log(f"    {_fp(fp, 'filename'):<50.50} {_fp(fp, 'platform'):<22} {_fp(fp, 'data_type')}")
    result = confirm_metadata_step(dtxsid, corrections, store)
    _log(f"  {len(corrections)} override(s) applied, {result.get('updated')} header(s) written")


def integrate(dtxsid: str, identity: dict, store) -> None:
    from workflow.steps import integrate_step

    summary = integrate_step(dtxsid, identity, store)
    _log(f"  {summary.get('experiment_count')} experiments, "
         f"{summary.get('bmd_result_count')} BMD results")


def animal_report(dtxsid: str, store) -> None:
    from workflow.steps import generate_animal_report_step

    ar = generate_animal_report_step(dtxsid, store)
    _log(f"  {ar.get('total_animals')} animals "
         f"(core {ar.get('core_count')} / biosampling {ar.get('biosampling_count')})")


def process(dtxsid: str, params: dict, store) -> None:
    from workflow.steps import materialize_result_sections, process_step

    payload = asyncio.run(process_step(dtxsid, params, store))
    _log(f"  {len(payload.get('sections') or [])} apical section(s), "
         f"{len(payload.get('genomics_sections') or [])} genomics section(s), "
         f"methods={'yes' if payload.get('methods') else 'no'}")
    mat = materialize_result_sections(dtxsid, store)
    _log(f"  materialized {len(mat.get('materialized', []))} result section file(s)")


def background(dtxsid: str, identity: dict, model: str, store) -> None:
    """Generate + save the Background section (LLM over ATSDR/IRIS/PubChem data),
    mirroring POST /api/generate + /api/session/save-section. Saved UNAPPROVED,
    as the UI does."""
    from narrative.background_writer import DEFAULT_CLAUDE_MODEL, generate_background
    from narrative.chem_resolver import ChemicalIdentity
    from narrative.data_gatherer import gather_all
    from narrative.style_learning import load_style_profile

    bg_data = gather_all(ChemicalIdentity.from_dict(identity), lambda m: _log(f"    {m}"))
    rules = [r["rule"] for r in load_style_profile().get("rules", [])] or None
    result = generate_background(bg_data, model or DEFAULT_CLAUDE_MODEL, rules)
    paragraphs = result.get("paragraphs") or []
    if not paragraphs:
        _log("  WARNING: background generation returned no paragraphs — not saved")
        return
    store.save_section(dtxsid, "background", {
        "paragraphs": paragraphs,
        "references": result.get("references", []),
        "citation_report": result.get("citation_report"),
        "abstract_background": result.get("abstract_background", ""),
        "model_used": result.get("model_used", model),
        "approved": False,
    }, archive=False)
    _log(f"  {len(paragraphs)} paragraph(s), {len(result.get('references', []))} reference(s)")


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render(dtxsid: str, surfaces: list[str], out_dir: Path, view: str | None,
           strict: bool) -> list[Path]:
    """Write each requested surface to out_dir as <DTXSID><suffix>."""
    from rendering.preview_surface import _identity, render_preview

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for surface in surfaces:
        out = out_dir / f"{dtxsid}{SURFACE_SUFFIX[surface]}"
        if surface in ("latex", "pdf"):
            chemical_name, casrn = _identity(dtxsid)
            _render_latex(dtxsid, chemical_name, casrn, view, out, pdf=(surface == "pdf"),
                          strict=strict)
        else:
            content = render_preview(dtxsid, surface=surface, view=view)
            if isinstance(content, bytes):
                out.write_bytes(content)
            else:
                out.write_text(content, encoding="utf-8")
        _log(f"  → {out} ({out.stat().st_size / 1024:.0f} KB)")
        written.append(out)
    return written


def _render_latex(dtxsid: str, chemical_name: str, casrn: str, view: str | None,
                  out: Path, *, pdf: bool, strict: bool) -> None:
    from document_model.view_config import DEFAULT_VIEW, build_view_tree
    from rendering.latex_export import (
        _assemble_bundle_files, _write_files_to_dir, build_overleaf_bundle, load_session_data,
    )

    view = view or DEFAULT_VIEW
    data = load_session_data(dtxsid, chemical_name=chemical_name, casrn=casrn, view=view)
    tree = build_view_tree(dtxsid, view)
    if not pdf:
        build_overleaf_bundle(data, out, strict=strict, tree=tree)
        return

    tect = os.environ.get("TECT_CMD", "tect")
    if shutil.which(tect) is None:
        raise SystemExit(f"pdf surface needs the offline LaTeX engine {tect!r} on PATH")
    files = _assemble_bundle_files(data, strict=strict, tree=tree)
    with tempfile.TemporaryDirectory(prefix="5dtox_compile_") as tmp:
        tmp_path = Path(tmp)
        _write_files_to_dir(files, tmp_path)
        (tmp_path / "out").mkdir()
        proc = subprocess.run([tect, "main.tex", "--outdir", str(tmp_path / "out")],
                              cwd=tmp_path, capture_output=True, text=True)
        built = tmp_path / "out" / "main.pdf"
        if proc.returncode != 0 or not built.exists():
            tail = "\n".join(((proc.stdout or "") + (proc.stderr or "")).splitlines()[-40:])
            raise SystemExit(f"LaTeX compilation failed:\n{tail}")
        shutil.copy2(built, out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="python -m tooling.generate_report",
        description="Generate a 5-day report end-to-end without the web UI.",
    )
    ap.add_argument("dtxsid", help="session id (folder under sessions/)")
    ap.add_argument("--files", nargs="+", type=Path, default=[],
                    help="input files to import into sessions/<id>/files/ first "
                         "(.bm2, .txt/.csv, .xlsx, .sidecar.json)")
    ap.add_argument("--name", help="test-article name (else identity.json, else resolved)")
    ap.add_argument("--casrn", help="test-article CASRN")
    ap.add_argument("--compound-name",
                    help="short name used in captions/narratives (default: identity name)")
    ap.add_argument("--dose-unit", default=None,
                    help="dose unit for table headers (default: mg/kg — state it explicitly)")
    ap.add_argument("--metadata", type=Path,
                    help="JSON {filename: {platform, data_type}} classification overrides")
    ap.add_argument("--bmd-stats", default="median",
                    help="comma list of BMD statistics for GO tables (default: median)")
    ap.add_argument("--go-pct", type=float, default=5)
    ap.add_argument("--go-min-genes", type=int, default=20)
    ap.add_argument("--go-max-genes", type=int, default=500)
    ap.add_argument("--go-min-bmd", type=float, default=3)
    ap.add_argument("--reintegrate", action="store_true",
                    help="re-run integration even if integrated.json exists "
                         "(wipes process caches → full recompute)")
    ap.add_argument("--background", action="store_true",
                    help="also generate the Background section (LLM + external lookups)")
    ap.add_argument("--model", default="", help="LLM model for --background")
    ap.add_argument("--stop-after", choices=STEPS,
                    help="stop after this pipeline step (no render)")
    ap.add_argument("--render-only", action="store_true",
                    help="skip the pipeline; just render the session as it is on disk")
    ap.add_argument("--surfaces", default="docx,html",
                    help=f"comma list from {','.join(SURFACE_SUFFIX)} (default: docx,html)")
    ap.add_argument("--view", help="report view to render (default: the default view)")
    ap.add_argument("--out", type=Path, help="output directory (default: output/<DTXSID>/)")
    ap.add_argument("--strict", action="store_true",
                    help="latex/pdf: refuse to build while any '[... pending]' marker remains")
    ap.add_argument("--draft", action="store_true",
                    help="render even if the publish gate is closed (stale sections)")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="show pipeline logging (incl. per-cache provenance events)")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    surfaces = [s.strip() for s in args.surfaces.split(",") if s.strip()]
    unknown = [s for s in surfaces if s not in SURFACE_SUFFIX]
    if unknown:
        raise SystemExit(f"unknown surface(s): {unknown}; choose from {list(SURFACE_SUFFIX)}")
    # Resolve user paths BEFORE chdir: the app is cwd-relative (bmdx.duckdb, templates).
    files = [p.resolve() for p in args.files]
    metadata = args.metadata.resolve() if args.metadata else None
    out_dir = (args.out.resolve() if args.out else REPO_ROOT / "output" / args.dtxsid)
    os.chdir(REPO_ROOT)
    sys.path.insert(0, str(REPO_ROOT))

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    _bootstrap_env()
    if not args.verbose:
        # common.provenance pins its own logger to INFO at import; quiet it after.
        from common import provenance
        provenance.logger.setLevel(logging.WARNING)

    from common.dtxsid import validate_dtxsid
    from rendering.render_common import PendingContentError
    from workflow.engine import WorkflowEngine
    from workflow.errors import StepError
    from workflow.store import DiskPoolStore

    dtxsid = validate_dtxsid(args.dtxsid)
    store = DiskPoolStore()
    _log(f"session: {store.session_dir(dtxsid)}")

    try:
        if not args.render_only:
            if files:
                with _Timer(f"import {len(files)} file(s)"):
                    import_files(dtxsid, files, store)
            if not store.has_files(dtxsid):
                raise SystemExit(f"sessions/{dtxsid}/files/ is empty — pass --files")

            with _Timer("validate"):
                validate(dtxsid, store)
            with _Timer("confirm metadata"):
                confirm_metadata(dtxsid, metadata, store)
            if args.stop_after == "validate":
                return 0

            identity = _resolve_identity(dtxsid, args, store)
            if args.reintegrate or not store.artifact_exists(dtxsid, "integrated.json"):
                with _Timer("integrate (Java)"):
                    integrate(dtxsid, identity, store)
            else:
                store.write_json(dtxsid, "identity.json", identity)
                _log("▶ integrate — skipped, integrated.json exists (--reintegrate to force)")
            with _Timer("animal report"):
                animal_report(dtxsid, store)
            if args.stop_after == "integrate":
                return 0

            dose_unit = args.dose_unit or "mg/kg"
            if not args.dose_unit:
                _log("  NOTE: dose unit defaulted to 'mg/kg' — pass --dose-unit to state it")
            params = {
                "compound_name": args.compound_name or identity.get("name") or dtxsid,
                "dose_unit": dose_unit,
                "bmd_stats": [s.strip() for s in args.bmd_stats.split(",") if s.strip()],
                "go_pct": args.go_pct,
                "go_min_genes": args.go_min_genes,
                "go_max_genes": args.go_max_genes,
                "go_min_bmd": args.go_min_bmd,
            }
            with _Timer("process (stats + BMDS + genomics + narratives; minutes when cold)"):
                process(dtxsid, params, store)
            if args.background:
                with _Timer("background (LLM)"):
                    background(dtxsid, identity, args.model, store)
            if args.stop_after == "process":
                return 0

        _log(f"phase: {_phase(dtxsid, store)}")
        readiness = WorkflowEngine(dtxsid, store).publish_readiness()
        if not readiness.get("can_publish", True):
            keys = ", ".join(b["section_key"] for b in readiness.get("blocking", []))
            msg = f"publish gate closed — re-accept the regenerated sections: {keys}"
            if not args.draft:
                raise SystemExit(msg + " (or pass --draft)")
            _log(f"  WARNING: {msg} (rendering anyway: --draft)")

        with _Timer(f"render {', '.join(surfaces)}"):
            render(dtxsid, surfaces, out_dir, args.view, args.strict)
    except StepError as e:
        raise SystemExit(f"step failed ({e.status_code}): {e.message}")
    except PendingContentError as e:
        raise SystemExit(f"--strict: report still has pending sections: {e.markers}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
