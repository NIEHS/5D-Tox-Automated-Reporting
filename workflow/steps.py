"""
workflow.steps — HTTP-free pool workflow steps (ADR-0014, step 2).

Each function is the *logic* of one pool lifecycle handler, lifted out of
`web_routes/pool_routes.py` and `pipeline/process_integrated.py` with the FastAPI
glue removed:

  * no `Request` — callers pass already-parsed inputs;
  * no `JSONResponse` — steps return plain Python and raise `StepError` on
    failure (the route translates it to a status code, a TUI shows a message);
  * no module-global dicts / direct `_session_dir` — all state goes through an
    injected `PoolStore` (ADR-0014 Q2).

The result: one place, in Python, that both the web UI and a future TUI drive.
Behavior is preserved byte-for-byte against the pre-unwrap handlers; the route
handlers become parse → call → serialize.

The pure compute transforms (`validate_pool`, `integrate_pool`,
`build_animal_report`) are called directly here — they are stateless and are what
conftest's `mock_bmdx_pipe` patches. NOTE: those patch targets move WITH the call
site — `validate_pool`/`integrate_pool` are now imported into THIS module, so the
mock patches `workflow.steps.integrate_pool` (see the route rewire + conftest).
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from bmdx_pipe import (
    build_animal_report,
    integrate_pool,
    report_to_dict,
    validate_pool,
)

from pipeline.integrated_io import _enrich_source_experiment_counts
from styling_export.llm_helpers import llm_generate_json as _llm_generate_json

from workflow.errors import StepError
from workflow.store import PoolStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

def validate_step(dtxsid: str, store: PoolStore) -> dict:
    """Re-fingerprint the pool and run full cross-validation.

    Returns the ValidationReport as a plain dict (also persisted to
    validation_report.json). Raises StepError(404) if the session has no files.
    """
    files_dir = store.session_dir(dtxsid) / "files"
    if not files_dir.exists():
        raise StepError("No files directory found for this session", status_code=404)

    # Force a full re-scan of all files in the session
    fps = store.ensure_fingerprints(dtxsid, force=True)
    report = validate_pool(dtxsid, fps)

    report_dict = {
        "dtxsid": report.dtxsid,
        "run_at": report.run_at,
        "file_count": report.file_count,
        "fingerprints": report.fingerprints,
        "issues": report.issues,
        "coverage_matrix": report.coverage_matrix,
        "is_complete": report.is_complete,
    }
    store.write_json(dtxsid, "validation_report.json", report_dict)
    return report_dict


# ---------------------------------------------------------------------------
# resolve
# ---------------------------------------------------------------------------

def resolve_step(dtxsid: str, issue_index, chosen_file_id: str, store: PoolStore) -> dict:
    """Append one precedence decision to precedence.json.

    Raises StepError(400) if any of the three inputs is missing.
    """
    if not dtxsid or issue_index is None or not chosen_file_id:
        raise StepError(
            "dtxsid, issue_index, and chosen_file_id are required", status_code=400
        )

    precedence = store.read_json(dtxsid, "precedence.json")
    if not isinstance(precedence, list):
        precedence = []

    precedence.append({
        "issue_index": issue_index,
        "chosen_file_id": chosen_file_id,
        "resolved_at": datetime.now(tz=timezone.utc).isoformat(),
    })
    store.write_json(dtxsid, "precedence.json", precedence)
    return {"ok": True}


# ---------------------------------------------------------------------------
# confirm-metadata
# ---------------------------------------------------------------------------

def confirm_metadata_step(dtxsid: str, confirmed: dict, store: PoolStore) -> dict:
    """Apply user metadata corrections to fingerprints and write txt/csv headers.

    `confirmed` maps file_id -> {platform, data_type}. Returns
    {ok, updated} where `updated` counts files whose headers were rewritten.
    """
    session_dir = store.session_dir(dtxsid)
    files_dir = session_dir / "files"

    fps = store.get_fingerprints(dtxsid)
    updated = 0

    for fid, corrections in (confirmed or {}).items():
        fp = fps.get(fid)
        if not fp:
            continue

        new_platform = corrections.get("platform")
        new_data_type = corrections.get("data_type")
        if new_platform and hasattr(fp, "platform"):
            fp.platform = new_platform
        elif new_platform and isinstance(fp, dict):
            fp["platform"] = new_platform
        if new_data_type and hasattr(fp, "data_type"):
            fp.data_type = new_data_type
        elif new_data_type and isinstance(fp, dict):
            fp["data_type"] = new_data_type

        fname = fp.filename if hasattr(fp, "filename") else fp.get("filename", "")
        ftype = fp.file_type if hasattr(fp, "file_type") else fp.get("file_type", "")

        if ftype in ("txt", "csv"):
            file_path = files_dir / fname
            if file_path.exists():
                _write_metadata_headers(
                    file_path,
                    platform=new_platform or (fp.platform if hasattr(fp, "platform") else fp.get("platform")),
                    data_type=new_data_type or (fp.data_type if hasattr(fp, "data_type") else fp.get("data_type")),
                )
                updated += 1

    # Re-persist fingerprints with corrections — same format as _persist_fingerprints
    cache: dict[str, dict] = {}
    for fp_obj in fps.values():
        fname = fp_obj.filename if hasattr(fp_obj, "filename") else fp_obj.get("filename", "")
        cache[fname] = asdict(fp_obj) if hasattr(fp_obj, "filename") else fp_obj
    store.write_json(dtxsid, "_fingerprints.json", cache)

    logger.info("Confirmed metadata for %d files in %s", updated, dtxsid)
    return {"ok": True, "updated": updated}


def _write_metadata_headers(file_path, platform: str, data_type: str) -> None:
    """
    Prepend # Provider / # Platform / # Data Type headers to a txt/csv file.

    If the file already has metadata headers (lines starting with #),
    replaces them.  Otherwise prepends before the first data line.

    These headers are parsed by ExperimentDescriptionParser in Java
    so that ExperimentDescription fields are set during import.
    """
    path = Path(file_path)
    content = path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines(keepends=True)

    headers = []
    headers.append(f"# Provider: Apical\n")
    if platform:
        headers.append(f"# Platform: {platform}\n")
    if data_type:
        headers.append(f"# Data Type: {data_type}\n")

    # Strip any existing metadata header lines (start with #)
    data_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            data_start = i
            break

    path.write_text("".join(headers + lines[data_start:]), encoding="utf-8")


# ---------------------------------------------------------------------------
# integrate
# ---------------------------------------------------------------------------

def integrate_step(dtxsid: str, identity: dict | None, store: PoolStore) -> dict:
    """Merge the pool into a unified BMDProject and cache it.

    `identity` is the resolved chemical identity from the caller (persisted to
    identity.json for LLM metadata inference), or None. Returns the lightweight
    summary payload (not the full integrated JSON — it can exceed response caps).
    Raises StepError(404) with no files, StepError(400) if validation hasn't run,
    StepError(500) if integration itself fails.
    """
    session_dir = store.session_dir(dtxsid)
    files_dir = session_dir / "files"
    if not files_dir.exists():
        raise StepError("No files directory found for this session", status_code=404)

    # Load fingerprints -- prefer cache, fall back to validation_report.json
    fps = store.get_fingerprints(dtxsid)
    if not fps:
        report = store.read_json(dtxsid, "validation_report.json")
        if isinstance(report, dict):
            fps = report.get("fingerprints", {})
    if not fps:
        raise StepError("No fingerprints found -- run validation first", status_code=400)

    # Load the coverage matrix from the validation report
    report = store.read_json(dtxsid, "validation_report.json")
    coverage_matrix = report.get("coverage_matrix", {}) if isinstance(report, dict) else {}
    if not coverage_matrix:
        raise StepError("No coverage matrix found -- run validation first", status_code=400)

    # Load user precedence decisions (may be empty if no conflicts resolved)
    precedence = store.read_json(dtxsid, "precedence.json")
    if not isinstance(precedence, list):
        precedence = []

    # Persist identity.json early so integration can find the test article
    # (integration happens before any section approve, which used to be the
    # only writer of identity.json).
    if identity:
        store.write_json(dtxsid, "identity.json", identity)

    # Load test article identity for metadata inference. Try identity.json
    # (written above or on approve), then meta.json (legacy).
    test_article = None
    for identity_file in ("identity.json", "meta.json"):
        id_data = store.read_json(dtxsid, identity_file)
        if isinstance(id_data, dict):
            name = id_data.get("name", "")
            casrn = id_data.get("casrn", "")
            dsstox = id_data.get("dtxsid", dtxsid)
            if name or casrn:
                test_article = {
                    "name": name,
                    "casrn": casrn,
                    "dsstox": dsstox,
                    "synonyms": id_data.get("synonyms", []),
                }
                break

    try:
        integrated = integrate_pool(
            dtxsid,
            str(session_dir),
            fps,
            coverage_matrix,
            precedence,
            test_article=test_article,
            llm_generate_json=_llm_generate_json,
        )
    except Exception as e:
        logger.exception("Pool integration failed for %s", dtxsid)
        raise StepError(f"Integration failed: {e}", status_code=500)

    # Cache in memory for the process-integrated endpoint
    store.set_integrated(dtxsid, integrated)

    # Invalidate all per-section caches from previous integration runs —
    # the input data has changed, so all cached results are stale.
    for pattern in ("_cache_*.json", "_processed_cache_*.json"):
        for old_cache in session_dir.glob(pattern):
            old_cache.unlink(missing_ok=True)
            logger.debug("Invalidated stale cache: %s", old_cache.name)

    # Build the lightweight summary (see the route docstring for why).
    meta = integrated.get("_meta", {})
    experiments = integrated.get("doseResponseExperiments", [])

    source_files = meta.get("source_files", {})
    if source_files and experiments:
        needs_backfill = any(
            "experiment_count" not in info for info in source_files.values()
        )
        if needs_backfill:
            _enrich_source_experiment_counts(source_files, experiments)

    return {
        "ok": True,
        "_meta": meta,
        "experiment_count": len(experiments),
        "bmd_result_count": len(integrated.get("bMDResult", [])),
        "category_analysis_count": len(integrated.get("categoryAnalysisResults", [])),
        "experiments": [
            {
                "name": exp.get("name", ""),
                "probe_count": len(exp.get("probeResponses", [])),
            }
            for exp in experiments
        ],
    }


# ---------------------------------------------------------------------------
# generate-animal-report
# ---------------------------------------------------------------------------

def generate_animal_report_step(dtxsid: str, store: PoolStore) -> dict:
    """Build the per-animal traceability report and persist it.

    Returns the AnimalReport as a plain dict. Raises StepError(404) with no
    files, StepError(400) if nothing fingerprinted, StepError(500) on failure.
    """
    session_path = store.session_dir(dtxsid)
    files_dir = session_path / "files"
    if not files_dir.exists():
        raise StepError("No files directory found for this session", status_code=404)

    fps = store.ensure_fingerprints(dtxsid)
    if not fps:
        raise StepError("No fingerprinted files found -- upload files first", status_code=400)

    try:
        report = build_animal_report(str(session_path), fps)
    except Exception as e:
        logger.exception("Failed to build animal report for %s", dtxsid)
        raise StepError(f"Animal report generation failed: {e}", status_code=500)

    report_dict = report_to_dict(report)
    store.write_json(dtxsid, "animal_report.json", report_dict)
    return report_dict
