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
from pipeline.session_store import _VERSION_EVENT_KEY
from styling_export.llm_helpers import llm_generate_json as _llm_generate_json

from common.provenance import step_provenance
from workflow.errors import StepError
from workflow.store import PoolStore
from workflow.studies import require_data_session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# materialize result sections (ADR-0018 Phase 1)
# ---------------------------------------------------------------------------

@step_provenance
def materialize_summary(dtxsid: str, store: PoolStore) -> dict:
    """Write the report's Summary section (summary.json) from the session's
    results — narrative.report_summary, deterministic, the same inputs as the
    Abstract — as a provisional draft (approved=False, source="generated").

    Never overwrites a Summary a person approved or wrote (or one the LLM route
    saved): only an absent or previously generated, unapproved summary.json is
    (re)written.  Returns ``{ok, written: bool, paragraphs: int}``."""
    require_data_session(dtxsid, store)  # R6: no data act on a companion or a report
    import json

    from narrative.report_summary import build_report_summary
    from narrative.summary_llm import summary_inputs
    from pipeline.session_store import save_section

    sdir = store.session_dir(dtxsid)
    prior_path = sdir / "summary.json"
    if prior_path.exists():
        try:
            prior = json.loads(prior_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            prior = {}
        if prior.get("approved") or prior.get("source") != "generated":
            return {"ok": True, "written": False, "paragraphs": 0}

    paragraphs = build_report_summary(**summary_inputs(sdir))
    if not paragraphs:
        return {"ok": True, "written": False, "paragraphs": 0}
    save_section(dtxsid, "summary", {
        "paragraphs": paragraphs,
        "source": "generated",
        "approved": False,
    }, archive=False)
    return {"ok": True, "written": True, "paragraphs": len(paragraphs)}


def materialize_result_sections(dtxsid: str, store: PoolStore) -> dict:
    """Write the apical result sections from the Process cache to disk as section
    files, so the document surface shows them and the deliverable renders complete.

    Process produces apical section content in `_cache_sections_*.json` (a list of
    `{platform, title, tables_json, narrative, first_col_header, caption, footnotes}`)
    but never writes the `bm2_<slug>.json` FILES the render + readiness paths read.
    This closes that gap: for each cached apical section, write `bm2_<slug>.json`
    (`slug = bm2_slug(title)`) carrying the SAME fields plus `approved=False` — a
    provisional, generated draft. The narrative is already a paragraph list (kept as
    `narrative`, which report_data reads directly); no transform needed beyond the
    key + approval stamp.

    Idempotent: re-materializing overwrites with archive=False (a regenerate, not a
    new blessed version). Genomics is deterministic and is NOT materialized here (it
    is read-only, not an authorable/approvable section — ADR-0018). Returns
    `{ok, materialized: [section_key, ...]}`.
    """
    require_data_session(dtxsid, store)  # R6: no data act on a companion or a report
    import json

    from pipeline.session_db import _latest_cache
    from pipeline.session_store import bm2_slug, save_section
    from workflow.reprocess import cat_signature_flips

    sdir = store.session_dir(dtxsid)
    cache = _latest_cache(sdir, "sections")
    sections = cache.get("sections") if isinstance(cache, dict) else None
    if not sections:
        return {"ok": True, "materialized": []}

    materialized: list[str] = []
    for sec in sections:
        title = sec.get("title") or sec.get("platform") or ""
        slug = bm2_slug(title)
        if not slug:
            continue
        section_key = f"bm2_{slug}"
        cat_signature = sec.get("cat_signature") or {}

        # Read the PRIOR section file (if any) BEFORE overwriting it — this is the
        # only point where the old and new categorical signatures coexist, so it is
        # where Phase 3b flip detection must run (invalidate ran at upload and kept
        # no new binding; the reprocess that produced `sec` deleted the old cache).
        # Capture whether the human had APPROVED the prior wording and its signature.
        prior_path = sdir / f"{section_key}.json"
        was_approved = False
        old_signature: dict = {}
        if prior_path.exists():
            try:
                prior = json.loads(prior_path.read_text(encoding="utf-8"))
                was_approved = bool(prior.get("approved"))
                old_signature = prior.get("cat_signature") or {}
            except (json.JSONDecodeError, OSError, ValueError):
                pass

        # Carry the render-relevant fields verbatim; stamp provisional (unapproved).
        data = {
            "platform": sec.get("platform"),
            "title": title,
            "tables_json": sec.get("tables_json"),
            "narrative": sec.get("narrative", []) or [],
            "cat_signature": cat_signature,
            "first_col_header": sec.get("first_col_header"),
            "caption": sec.get("caption"),
            "footnotes": sec.get("footnotes"),
            "approved": False,
            "source": "generated",
        }

        # Wording-review inform-signal (Phase 3b): only when the human had APPROVED
        # the prior wording AND a data-derived WORD flipped under it. Not a block —
        # programmatic content asserts no LLM judgement; it flags that the author's
        # committed wording may now contradict the refreshed data. Fail-soft: no
        # prior / never approved / no flip → no marker → byte-identical to before.
        if was_approved:
            flips = cat_signature_flips(old_signature, cat_signature)
            if flips:
                data["wording_review"] = flips

        # archive=False: a regenerate/materialize is not a new blessed version.
        save_section(dtxsid, section_key, data, archive=False)
        materialized.append(section_key)
        from common import provenance
        provenance.record(
            "materialized", dtxsid=dtxsid, section_key=section_key,
            platform=sec.get("platform"), was_approved=was_approved,
            wording_review=bool(data.get("wording_review")),
        )

    return {"ok": True, "materialized": materialized}


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

@step_provenance
def validate_step(dtxsid: str, store: PoolStore) -> dict:
    """Re-fingerprint the pool and run full cross-validation.

    Returns the ValidationReport as a plain dict (also persisted to
    validation_report.json). Raises StepError(404) if the session has no files.
    """
    require_data_session(dtxsid, store)  # R6: no data act on a companion or a report
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

    # Value-level provenance cross-check (xlsx ↔ derived CSV). Lazy import to
    # avoid the pipeline↔workflow import cycle. Runs here (not in validate_pool)
    # because it needs the session files dir. Appends blocking errors when a
    # derived CSV diverges from its source xlsx, or a warning when derived data
    # has no original to check against.
    try:
        from pipeline.value_validation import check_value_provenance
        report_dict["issues"] = report_dict["issues"] + check_value_provenance(
            dtxsid, fps, report.coverage_matrix, store.session_dir(dtxsid)
        )
    except Exception:
        logger.exception("Value provenance check failed for %s (skipped)", dtxsid)

    store.write_json(dtxsid, "validation_report.json", report_dict)
    return report_dict


# ---------------------------------------------------------------------------
# resolve
# ---------------------------------------------------------------------------

@step_provenance
def resolve_step(dtxsid: str, issue_index, chosen_file_id: str, store: PoolStore) -> dict:
    """Append one precedence decision to precedence.json.

    Raises StepError(400) if any of the three inputs is missing.
    """
    if not dtxsid or issue_index is None or not chosen_file_id:
        raise StepError(
            "dtxsid, issue_index, and chosen_file_id are required", status_code=400
        )

    require_data_session(dtxsid, store)  # R6: no data act on a companion or a report

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

@step_provenance
def confirm_metadata_step(dtxsid: str, confirmed: dict, store: PoolStore) -> dict:
    """Apply user metadata corrections to fingerprints and write txt/csv headers.

    `confirmed` maps file_id -> {platform, data_type}. Returns
    {ok, updated} where `updated` counts files whose headers were rewritten.
    """
    require_data_session(dtxsid, store)  # R6: no data act on a companion or a report
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
    headers.append("# Provider: Apical\n")
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

@step_provenance
def integrate_step(dtxsid: str, identity: dict | None, store: PoolStore) -> dict:
    """Merge the pool into a unified BMDProject and cache it.

    `identity` is the resolved chemical identity from the caller (persisted to
    identity.json for LLM metadata inference), or None. Returns the lightweight
    summary payload (not the full integrated JSON — it can exceed response caps).
    Raises StepError(404) with no files, StepError(400) if validation hasn't run,
    StepError(500) if integration itself fails.
    """
    require_data_session(dtxsid, store)  # R6: no data act on a companion or a report
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

    # Metadata the user approved for an earlier integration: integration
    # re-infers every experiment's metadata, and the approval must win.
    approval = store.read_json(dtxsid, "metadata_approved.json")
    approved_metadata = approval.get("metadata") if isinstance(approval, dict) else None

    try:
        integrated = integrate_pool(
            dtxsid,
            str(session_dir),
            fps,
            coverage_matrix,
            precedence,
            test_article=test_article,
            llm_generate_json=_llm_generate_json,
            approved_metadata=approved_metadata or None,
        )
    except Exception as e:
        logger.exception("Pool integration failed for %s", dtxsid)
        raise StepError(f"Integration failed: {e}", status_code=500)

    # Cache in memory for the process-integrated endpoint
    store.set_integrated(dtxsid, integrated)

    # Study-design facts a person stated (generate_report --design): integration
    # re-infers every experiment's metadata, and the stated design must win.
    # After the cache is set, so the design lands on this integration, not the last.
    reapply_study_design(dtxsid, store)

    # Measurement units onto the sidecars from any original study workbook in
    # the pool (the truth CSVs they were derived from carry none).
    from pipeline.sidecar_units import stamp_sidecar_units
    stamp_sidecar_units(fps, session_dir)

    # Invalidate all per-section caches from previous integration runs —
    # the input data has changed, so all cached results are stale.
    for pattern in ("_cache_*.json", "_processed_cache_*.json"):
        for old_cache in session_dir.glob(pattern):
            old_cache.unlink(missing_ok=True)
            logger.debug("Invalidated stale cache: %s", old_cache.name)

    # The query substrate (ADR-0016) is derived from those caches + integrated,
    # so re-integration makes it stale too. Remove it (rebuilt on next process)
    # so a re-integrated-but-not-yet-reprocessed session can't be queried against
    # old data.
    import shutil
    (session_dir / "session.duckdb").unlink(missing_ok=True)
    shutil.rmtree(session_dir / "session_parquet", ignore_errors=True)
    # NB: genomics.sidecar.json is NOT wiped here — integrate_pool (above) just
    # wrote the FRESH one for this integration. Its new mtime changes the genomics
    # cache key, so the stale _cache_genomics_*.json (wiped by the glob above)
    # re-extracts from the new sidecar on next process. (invalidate_pool_artifacts
    # DOES delete the sidecar, because that path tears down integrated.json too.)

    # The study's analysis method (ADR-0027): pin the newest profile when the
    # study has none, and check what the .bm2 analyses record against it.
    method_summary = _pin_and_check_method(dtxsid, integrated, store)

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
        "method": method_summary,
        "experiments": [
            {
                "name": exp.get("name", ""),
                "probe_count": len(exp.get("probeResponses", [])),
            }
            for exp in experiments
        ],
    }


def reapply_study_design(dtxsid: str, store: PoolStore) -> int:
    """Put the session's stated design (study_design.json) on every experiment of
    the integrated project and save it, keeping the .bm2 copy in step as the
    metadata step does.  Returns the experiments updated (0: no stated design)."""
    from pipeline.integrated_io import load_integrated, save_integrated
    from pipeline.study_design import DESIGN_FILE, apply_design_fields

    stated = store.read_json(dtxsid, DESIGN_FILE)
    fields = stated.get("fields") if isinstance(stated, dict) else None
    if not fields:
        return 0
    integrated = load_integrated(dtxsid)
    if integrated is None:
        return 0
    count = apply_design_fields(integrated, fields)
    save_integrated(dtxsid, integrated)
    try:
        from bmdx_pipe import export_integrated_bm2
        sd = store.session_dir(dtxsid)
        export_integrated_bm2(str(sd / "integrated.json"), str(sd / "integrated.bm2"))
    except Exception as e:  # noqa: BLE001 — the JSON is the source of truth
        logger.warning("integrated.bm2 not re-exported after the study design: %s", e)
    logger.info("Study design restored on %d experiment(s): %s", count, fields)
    return count


def _pin_and_check_method(dtxsid: str, integrated: dict, store: PoolStore) -> dict:
    """Pin a method profile if the study has none, and report every recorded
    analysis setting that disagrees with it as a `method_mismatch` warning in
    the validation report (ADR-0027 §5).  Returns {profile, pinned_by,
    deviations, mismatches}."""
    from pipeline.method_profile import ensure_pin, pin_mode, recorded_mismatches, session_method

    pin = ensure_pin(dtxsid)
    method = session_method(dtxsid)
    mismatches = recorded_mismatches(integrated, method)
    report = store.read_json(dtxsid, "validation_report.json")
    if isinstance(report, dict):
        issues = [i for i in report.get("issues", []) if i.get("issue_type") != "method_mismatch"]
        issues += [{"severity": "warning", "platform": None, "issue_type": "method_mismatch",
                    "message": m["message"], "files_involved": [], "suggested_precedence": None,
                    "details": {k: m[k] for k in ("analysis", "setting", "recorded", "profile")}}
                   for m in mismatches]
        report["issues"] = issues
        store.write_json(dtxsid, "validation_report.json", report)
    return {"profile": pin["name"], "pinned_by": pin["pinned_by"], "mode": pin_mode(pin),
            "deviations": list(method.deviations), "mismatches": [m["message"] for m in mismatches]}


# ---------------------------------------------------------------------------
# generate-animal-report
# ---------------------------------------------------------------------------

@step_provenance
def generate_animal_report_step(dtxsid: str, store: PoolStore) -> dict:
    """Build the per-animal traceability report and persist it.

    Returns the AnimalReport as a plain dict. Raises StepError(404) with no
    files, StepError(400) if nothing fingerprinted, StepError(500) on failure.
    """
    require_data_session(dtxsid, store)  # R6: no data act on a companion or a report
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


# ---------------------------------------------------------------------------
# process
# ---------------------------------------------------------------------------

@step_provenance
async def process_step(dtxsid: str, params: dict, store: PoolStore) -> dict:
    """Turn the integrated project into report content (the heavy compute).

    Runs NTP statistics, BMDS dose-response modeling, genomics extraction,
    section cards, and LLM narratives, returning the assembled `result_payload`
    dict. `params` is the settings dict a UI would post (compound_name,
    dose_unit, bmd_stats, go_* cutoffs); template-derived filters are resolved
    inside the core. Raises StepError(400) if the session has not been
    integrated, StepError(500) on a processing failure.

    The core lives in `pipeline.process_integrated.run_process` (it owns the
    ProcessContext + layer orchestration). We import it lazily because that
    module imports this one at module load (it reuses generate_animal_report_step
    for the animal-report route) — a top-level import here would be a cycle.
    """
    from pipeline.process_integrated import run_process
    return await run_process(dtxsid, params or {}, store)


# ---------------------------------------------------------------------------
# document (content preparation) — concern [2], ADR-0021
# ---------------------------------------------------------------------------

@step_provenance
async def document_step(dtxsid: str, params: dict, store: PoolStore) -> dict:
    """Prepare the document CONTENT from processed data + declarations (ADR-0021).

    The content-preparation concern as its own UI-agnostic step, sibling to
    `process_step`: it (re)builds the prose reductions — genomics narratives,
    apical BMD narrative, unified/section narratives, Materials & Methods — and
    returns the CONTENT subset of the process payload (`_CONTENT_PAYLOAD_KEYS`:
    unified_narratives, genomics_sections, gene_set_narrative, gene_narrative,
    apical_bmd_narrative, methods, sections). `params` is the same settings dict
    process_step takes; raises StepError(400) if not integrated, StepError(500)
    on failure.

    EAGER model (ADR-0021 E, maintainer's decision): today process_step already
    runs content preparation as part of the full pass, so after a process the
    content is present. This step exposes that SAME work (via the shared run_data
    + prepare_content building blocks in the core — NOT the standalone regenerate
    endpoints, which can drift) as a separately-invocable phase, so a driver can
    re-prepare content without re-posting the whole process, and content prep has
    a named home for a future lazy/on-demand path. It reuses the concern-[2]
    skip-guard, so an unchanged session returns instantly.

    Lazy import for the same reason process_step uses one (module import cycle).
    """
    from pipeline.process_integrated import run_document
    return await run_document(dtxsid, params or {}, store)


# ---------------------------------------------------------------------------
# accept / release a report section (authoring approve-lock state transitions)
#
# These lift the STATE TRANSITION half of web_routes/session_routes.py's
# /api/session/approve and /api/session/unapprove into the UI-agnostic core.
# Text generation stays in llm_routes (the LLM tier); style learning stays in
# the route (it needs the original-vs-edited paragraph payloads and fires an
# executor task — see the seam note below). What moves here is the durable
# lock/unlock transition on a section that already exists on disk.
# ---------------------------------------------------------------------------

def _promote_to_final(data: dict) -> None:
    """Assert the FINAL content fact on an approved section, in place (ADR-0015).

    Approve = the human's editorial "done", the top maturity rung — so it promotes
    the section's facts to FINAL (which auto-sets PROTECTED). Serialized to the
    section's `facts` list so a later reprocess can demote_for_currency (drop FINAL,
    leave PROTECTED) — the fact-ratchet the on-disk `approved` bool alone could not
    express. Idempotent: re-approving a demoted section restores FINAL.
    """
    from workflow.labels import Fact, promote
    from workflow.ownership import section_facts, store_content_facts

    store_content_facts(data, promote(section_facts(data), Fact.FINAL))

@step_provenance
def accept_section_step(dtxsid: str, section_key: str, store: PoolStore) -> dict:
    """Approve (lock) an existing report section.

    Mirrors the persistence half of POST /api/session/approve: stamp
    `approved=True` + `approved_at`, and clear any `stale` flag (set by
    invalidate_pool_artifacts when the pool mutated after approval — re-approval
    clears it). Re-saved in place (archive=False) so a lock flip is not a new
    history version, exactly as /api/session/unapprove already does for the
    reverse flip; the approve route's own archiving happens when the CONTENT is
    saved, not on this pure lock transition.

    /api/session/approve also reports whether the approved text differs from
    the generated original (`user_edited`); that needs the request payload, so
    it stays in the route. This step lifts ONLY the state change.

    Raises StepError(400) with no dtxsid/section_key, StepError(404) if the
    section file does not exist (nothing to approve — content is written by the
    generation/save path first).
    """
    if not dtxsid or not section_key:
        raise StepError("dtxsid and section_key are required", status_code=400)

    data = store.read_json(dtxsid, f"{section_key}.json")
    if not isinstance(data, dict):
        raise StepError(
            f"No '{section_key}' section to approve", status_code=404
        )

    data["approved"] = True
    data["approved_at"] = datetime.now(tz=timezone.utc).isoformat()
    data.pop("stale", None)
    # The Phase 3b wording-review inform-signal is answered by exactly this act:
    # the human has read the prose against the refreshed data and re-blessed it.
    # Clearing it here (and in the route twin) is what lets a LATER flip be a
    # fresh signal instead of noise that never goes away.
    data.pop("wording_review", None)
    _promote_to_final(data)

    # Phase 4: record this acceptance as an "edit"/"blessed" version event. This
    # is the pure re-bless path — the content already exists on disk and only the
    # lock flips — so it uses archive=False: save_section PRESERVES the version
    # number and the manifest line lands against the SAME version. That is exactly
    # what "re-accept transitions needs-re-bless → blessed WITHOUT minting a new
    # version" needs: after a reprocess minted (say) v2 born needs-re-bless, the
    # human re-accept appends a v2/edit/blessed line, so v2's current status flips
    # to blessed with no duplicate version. The marker is transient (save_section
    # pops it); stamping it on `data` keeps this step store-mediated — no direct
    # disk I/O and no new store-method signature (the injected store just persists
    # `data`).
    data[_VERSION_EVENT_KEY] = {"cause": "edit", "status": "blessed"}

    # archive=False: a lock flip is not a content change worth a new history
    # FILE (matches how unapprove flips the flag). save_section stamps `version`
    # and appends the manifest line above.
    store.save_section(dtxsid, section_key, data, archive=False)

    return {
        "ok": True,
        "section_key": section_key,
        "approved": True,
        "version": data.get("version", 1),
    }


@step_provenance
def release_section_step(
    dtxsid: str, section_key: str, store: PoolStore, *, reason: str = "",
) -> dict:
    """REVISE (reopen) a report section for editing, preserving its content.

    This is the VOLUNTARY human down-ratchet — the "Revise" action, renamed from
    the old bare "Unapprove". It:
      * flips `approved=False` (unlocks the editor),
      * runs the HUMAN_RELEASE demote on the section's facts
        (labels.demote_for_human_release: FINAL withdrawn, PROTECTED stands — the
        content stops claiming finality but stays guarded until re-accepted), and
      * records the human's free-text `reason` on a Phase-4 version-trail entry
        (cause="revise"), so WHY a person reopened a blessed section is auditable
        alongside the system's cause="reprocess" entries.

    The reason is provenance (the version trail + `revised` marker), NOT a fact —
    facts are categorical. Content is preserved (archive=False for the flag flip;
    the trail entry captures the transition). No-op-safe: absent section → ok.

    Raises StepError(400) with no dtxsid/section_key.
    """
    if not dtxsid or not section_key:
        raise StepError("dtxsid and section_key are required", status_code=400)

    data = store.read_json(dtxsid, f"{section_key}.json")
    if isinstance(data, dict):
        data["approved"] = False
        _demote_for_revise(data, reason)
        store.save_section(dtxsid, section_key, data, archive=False)

    return {"ok": True, "section_key": section_key, "approved": False}


def _demote_for_revise(data: dict, reason: str) -> None:
    """Apply the HUMAN_RELEASE down-ratchet to a section dict, in place, and stamp
    the version-trail event. Withdraws FINAL (PROTECTED stands), records the human
    reason as provenance (`revised` marker + the trail entry's reason). A no-op on
    a section holding no maturity fact leaves facts untouched but STILL records the
    reopen on the trail — reopening an un-blessed draft is a real, auditable act."""
    from workflow.labels import demote_for_human_release
    from workflow.ownership import section_facts, store_content_facts

    store_content_facts(data, demote_for_human_release(section_facts(data)))
    data["revised"] = {"reason": reason} if reason else {"reason": ""}
    data[_VERSION_EVENT_KEY] = {
        "cause": "revise", "status": "working", "reason": reason,
    }


# ---------------------------------------------------------------------------
# Studies: create, fill a missing identity, delete (module M1)
# ---------------------------------------------------------------------------

def _casrn_check_digit_holds(casrn: str) -> bool:
    """A CASRN's last digit is the sum of the other digits, each times its
    position counted from the right (from 1), modulo 10."""
    digits = casrn.replace("-", "")
    body, check = digits[:-1], digits[-1]
    return sum(int(d) * i for i, d in enumerate(reversed(body), start=1)) % 10 == int(check)


def _confirmed_identity(dtxsid: str, identity: dict | None, confirmed: bool,
                        dtxsid_checked_by_person: bool) -> dict:
    """The identity a person confirmed, checked against the lookup it came from
    (workflow.studies.lookup_chemical, cached for 10 minutes), as identity.json
    holds it. Only a looked-up identity is accepted (Q-M1-3: no stated one).

    Refuses ``identity_unconfirmed`` without the confirmation (and, when the
    service does not list the DTXSID for the compound, without the person's
    check of it), ``identity_incomplete`` / ``invalid_casrn`` for a malformed
    one, and ``identity_changed`` when the lookup now gives another chemical."""
    from narrative.chem_resolver import CASRN_PATTERN
    from workflow.studies import StudyRefusal, lookup_chemical

    if not confirmed:
        raise StudyRefusal("identity_unconfirmed", "the identity was not confirmed", 400)
    identity = identity if isinstance(identity, dict) else {}
    source = identity.get("source") if isinstance(identity.get("source"), dict) else {}
    if source.get("kind") != "lookup":
        raise StudyRefusal("identity_unconfirmed",
                           f"identity source {source.get('kind')!r}: only a looked-up identity "
                           "is accepted", 400)
    name = str(identity.get("name") or "").strip()
    casrn = str(identity.get("casrn") or "").strip()
    if not name or not casrn:
        raise StudyRefusal("identity_incomplete", "the identity needs a name and a CASRN", 400)
    if not CASRN_PATTERN.match(casrn) or not _casrn_check_digit_holds(casrn):
        raise StudyRefusal("invalid_casrn", f"CASRN {casrn!r} fails its check digit", 400,
                           {"casrn": casrn})
    found = lookup_chemical(dtxsid)
    seen = found["identity"]
    if (name, casrn) != (seen["name"], seen["casrn"]):
        raise StudyRefusal("identity_changed",
                           f"confirmed {name!r} ({casrn}); the lookup gives {seen['name']!r} "
                           f"({seen['casrn']})", 409,
                           {"looked_up": {"name": seen["name"], "casrn": seen["casrn"]}})
    if not found["dtxsid_matched"] and not dtxsid_checked_by_person:
        raise StudyRefusal("identity_unconfirmed",
                           f"{found['service']} does not list {dtxsid} for {seen['name']}; the "
                           "person did not say they checked the DTXSID", 400)
    return {"dtxsid": dtxsid, "name": seen["name"], "casrn": seen["casrn"],
            "pubchem_cid": seen["pubchem_cid"],
            "identity_source": {"kind": "lookup", "service": found["service"],
                                "looked_up_at": found["looked_up_at"],
                                "confirmed_at": datetime.now(timezone.utc).strftime(
                                    "%Y-%m-%dT%H:%M:%SZ"),
                                "dtxsid_matched": found["dtxsid_matched"]}}


@step_provenance
def create_study_step(dtxsid: str, identity: dict | None, format_seen: dict | None,
                      *, confirmed: bool, dtxsid_checked_by_person: bool = False) -> dict:
    """Create a study under the chemical's DTXSID, with the identity and the
    report format a person confirmed (module M1). Writes identity.json and
    meta.json and nothing else: no files, no pins (Q-M1-10). The phase after is
    EMPTY. Returns ``{"id": dtxsid}``.

    In order: the id is a bare DTXSID (``study_id_has_suffix``); the format the
    person saw is the one the id gives now (``format_changed``); the identity
    is confirmed and is the lookup's (``_confirmed_identity``); the folder is
    created atomically, so two people cannot both create one (``study_exists``).
    An existing EMPTY folder counts as absent (a read before C4 may leave one)."""
    import json
    import os
    import shutil

    from pipeline.session_store import session_path
    from workflow.studies import StudyRefusal, format_hash, require_study_id

    require_study_id(dtxsid)
    seen = (format_seen or {}).get("hash") if isinstance(format_seen, dict) else None
    now_hash = format_hash(dtxsid)
    if seen != now_hash:
        raise StudyRefusal("format_changed",
                           f"format seen {seen!r}; the id now gives {now_hash}", 409,
                           {"hash": now_hash})
    record = _confirmed_identity(dtxsid, identity, confirmed, dtxsid_checked_by_person)

    # The study appears whole or not at all: written under a hidden name, then
    # renamed into place. A rename replaces an EMPTY folder (a read before C4
    # may have left one, R8) and fails on a non-empty one, so of two people
    # creating the same study at once exactly one succeeds.
    import uuid
    folder = session_path(dtxsid)
    folder.parent.mkdir(parents=True, exist_ok=True)
    staging = folder.parent / f".creating-{dtxsid}-{uuid.uuid4().hex[:8]}"
    staging.mkdir()
    try:
        stamp = datetime.now(timezone.utc).isoformat()
        for name, data in (("identity.json", record),
                           ("meta.json", {"dtxsid": dtxsid, "created_at": stamp,
                                          "updated_at": stamp})):
            (staging / name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        try:
            os.rename(staging, folder)
        except OSError:
            raise StudyRefusal("study_exists", f"session {dtxsid} already exists", 409,
                               {"existing_id": dtxsid, "id": dtxsid}) from None
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    logger.info("Created study %s (%s, %s)", dtxsid, record["name"], record["casrn"])
    return {"id": dtxsid}


@step_provenance
def record_identity_step(dtxsid: str, identity: dict | None, *, confirmed: bool,
                         dtxsid_checked_by_person: bool = False) -> dict:
    """Fill a study's missing chemical identity from a confirmed lookup (module
    M1). The chemical looked up is the one the session's id names. Refuses a
    session that does not exist (``study_not_found``), a companion or a report
    (``read_only_session``), and one whose identity.json already names the
    chemical (``identity_exists``: changing it is not done here, Q-M1-11).
    Keeps what identity.json already holds besides (the short name).
    Returns ``{"id": dtxsid}``."""
    import json
    import os

    from common.session_files import read_json_file
    from workflow.studies import (
        StudyRefusal, chemical_dtxsid, session_exists, session_folder, session_kind)

    folder = session_folder(dtxsid)
    if not session_exists(dtxsid):
        raise StudyRefusal("study_not_found", f"no session {dtxsid}", 404, {"id": dtxsid})
    kind = session_kind(dtxsid)["kind"]
    if kind in ("companion", "report"):
        raise StudyRefusal("read_only_session",
                           f"{dtxsid} is a {kind}; its identity is not filled here", 409)
    current = read_json_file(folder / "identity.json")
    current = current if isinstance(current, dict) else {}
    if current.get("name"):
        raise StudyRefusal("identity_exists", f"{dtxsid}/identity.json already names "
                           f"{current['name']!r}", 409)
    chem = chemical_dtxsid(dtxsid)
    if not chem:
        raise StudyRefusal("invalid_study_id", f"{dtxsid} names no chemical to look up", 400,
                           {"id": dtxsid})
    record = _confirmed_identity(chem, identity, confirmed, dtxsid_checked_by_person)
    record = {**current, **record, "dtxsid": dtxsid}
    tmp = folder / ".identity.json.tmp"
    tmp.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, folder / "identity.json")
    return {"id": dtxsid}


# What a session holds, by plain category, for the delete dry run: (category,
# test on a top-level name, words). First match wins; what matches none is
# "other". The words take the count of entries found.
_DELETE_CATEGORIES: tuple[tuple[str, object, str], ...] = (
    ("dataset", lambda n: n in ("integrated.json", "integrated.bm2", "_category_lookup.json",
                                "genomics.sidecar.json", "_fingerprints.json",
                                "validation_report.json", "precedence.json",
                                "animal_report.json", "session.duckdb", "session_parquet",
                                "references.json", "integration_basis.json",
                                ".session_db.fingerprint")
     or n.startswith(("_cache_", ".prepare_content")),
     "The integrated dataset and everything computed from it (statistics, BMDs, genomics, "
     "the query database)"),
    ("statements", lambda n: n in ("study_design.json", "metadata_approved.json",
                                   "front_matter.json", "deposit.json", "efdr.json"),
     "What people stated: {names}"),
    ("identity", lambda n: n == "identity.json",
     "The chemical's identity as recorded for this study"),
    ("pins", lambda n: n in ("method_profile.json", "document_definition.json",
                             "document_definition.yaml"),
     "{names}"),
    ("views", lambda n: n in ("views", "document.yaml", "styles.yaml"),
     "The study's saved report views and its own structure or styles"),
    ("runs", lambda n: n in ("narrative_runs", "narrative_comparisons", "summary"),
     "The saved language-model runs and comparisons of its texts"),
    ("log", lambda n: n == _PROVENANCE_LOG,
     "The record of what was done to the study and when"),
)
# The per-request log the HTTP layer appends to (common.provenance.flush).
_PROVENANCE_LOG = ".provenance.jsonl"

_STATEMENT_WORDS = {"study_design.json": "study design", "metadata_approved.json":
                    "experiment metadata", "front_matter.json": "front matter",
                    "deposit.json": "deposit list", "efdr.json": "eFDR"}


def _count_files(path: Path) -> int:
    return sum(1 for p in path.rglob("*") if p.is_file()) if path.is_dir() else 0


def _dir_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _megabytes(n: int) -> str:
    return f"{n / 1_000_000:.0f} MB" if n >= 1_000_000 else f"{max(1, round(n / 1000))} kB"


def _pin_words(folder: Path) -> str:
    """"The method profile pin (ntp-5day-2021, fixed) and the document
    definition pin (eras/niehs-2026, tracking)" from the pin files."""
    import json
    parts = []
    for file, what in (("method_profile.json", "method profile"),
                       ("document_definition.json", "document definition")):
        try:
            pin = json.loads((folder / file).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(pin, dict):
            mode = {"fixed": "fixed", "track": "tracking"}.get(pin.get("mode"), pin.get("mode"))
            facts = ", ".join(str(x) for x in (pin.get("name") or pin.get("profile"), mode) if x)
            parts.append(f"the {what} pin" + (f" ({facts})" if facts else ""))
    return (" and ".join(parts) or "the pins").capitalize()


def delete_study_dry_run(dtxsid: str) -> dict:
    """What deleting the study would delete, keep and lose (module M1; the C8
    dry run, MODULES.md §4.3), with the token the delete must present. Reads
    only: nothing is created or changed.

    Refuses an absent (or empty) session (``study_not_found``), a published
    book's content (``read_only_session``), a member of a report
    (``member_of_report``) and a study with a run in flight (``run_in_flight``).

    ``{"confirm": {act, strength, deletes, keeps, approvals_lost, cost,
    reason_required}, "type_to_confirm", "preview_token"}``. The token is a hash
    of every path in the folder with its size and modification time, so any
    change after the review refuses the delete (``changed_since_preview``)."""
    import hashlib

    import common.paths
    from workflow.studies import (
        StoreIndex, StudyRefusal, delete_verdict, published_record, report_of, session_exists,
        session_folder, session_kind)

    folder = session_folder(dtxsid)
    if not session_exists(dtxsid):
        raise StudyRefusal("study_not_found", f"no session {dtxsid}", 404, {"id": dtxsid})
    index = StoreIndex()
    info = session_kind(dtxsid, index=index)
    kind, relations = info["kind"], info["relations"]
    verdict = delete_verdict(dtxsid, kind, relations, index)
    if not verdict["allowed"]:
        raise StudyRefusal(verdict["code"], f"{dtxsid}: delete refused ({kind})", 409,
                           verdict["details"])

    names = sorted(p.name for p in folder.iterdir())
    deletes: list[dict] = []
    n_files = _count_files(folder / "files")
    n_orig = _count_files(folder / "_originals")
    if n_files or n_orig:
        say = f"The study's {n_files} data file" + ("" if n_files == 1 else "s")
        if n_orig:
            say += f", and the {n_orig} original" + ("" if n_orig == 1 else "s") + \
                   " they were converted from"
        deletes.append({"what": "files", "say": say})
    # The sections as the read model lists them (their titles, as D1 shows them).
    from workflow.read_model import study_state
    on_disk = [r for r in study_state(dtxsid).get("sections", []) if r.get("has_file")]
    section_keys = {r["key"] for r in on_disk}
    approved = [r.get("title") or r["key"] for r in on_disk if r.get("approved")]
    if on_disk:
        n = len(on_disk)
        state = ("none is approved" if not approved else
                 "all approved" if len(approved) == n else f"{len(approved)} approved")
        titles = ", ".join(r.get("title") or r["key"] for r in on_disk)
        deletes.append({"what": "sections",
                        "say": f"{n} report section" + ("" if n == 1 else "s")
                               + f" ({titles}); {state}"})
    seen_cats: dict[str, list[str]] = {}
    for name in names:
        if name in ("files", "_originals", "history", "meta.json") or \
                name[:-5] in section_keys:
            continue
        cat = next((c for c, test, _ in _DELETE_CATEGORIES if test(name)), "other")
        seen_cats.setdefault(cat, []).append(name)
    for cat, test, words in _DELETE_CATEGORIES:
        if cat not in seen_cats:
            continue
        if cat == "statements":
            say = words.format(names=", ".join(_STATEMENT_WORDS.get(n, n) for n in seen_cats[cat]))
        elif cat == "pins":
            say = _pin_words(folder)
        else:
            say = words
        deletes.append({"what": cat, "say": say})
    if "other" in seen_cats:
        deletes.append({"what": "other",
                        "say": "Everything else in the study's folder: " +
                               ", ".join(seen_cats["other"])})
    n_hist = _count_files(folder / "history")
    if n_hist:
        deletes.append({"what": "history",
                        "say": f"The history of every section and pin ({n_hist} "
                               + ("entry" if n_hist == 1 else "entries") + ")"})
    if kind == "report":
        deletes.insert(0, {"what": "report",
                           "say": "The report's list of its studies (studies.json); its studies "
                                  "stay and then show as sessions of their own"})

    keeps: list[dict] = []
    out_dir = common.paths.OUTPUT_DIR / dtxsid
    n_out = _count_files(out_dir)
    if n_out:
        keeps.append({"what": "output",
                      "say": f"The deliverables already written to output/{dtxsid}/ "
                             f"({n_out} file" + ("" if n_out == 1 else "s") + ")"})
    from document_model.document_definition import _templates_dir
    if (_templates_dir() / "studies" / dtxsid).is_dir():
        pub = published_record(report_of(dtxsid)[0])
        whose = f"{pub['report']}'s study definition" if pub else "The study definition"
        keeps.append({"what": "study_definition",
                      "say": f"{whose} under templates/studies/{dtxsid}/ (not part of the study)"})
    if relations.get("companion"):
        keeps.append({"what": "companion",
                      "say": f"The published book's content, {relations['companion']}"})
    for m in relations.get("members", []):
        keeps.append({"what": "member", "say": f"The {m['key']} study {m['id']}"})
    others = relations.get("others", [])
    if others:
        keeps.append({"what": "others",
                      "say": ("The other session of this chemical, " if len(others) == 1
                              else "The other sessions of this chemical, ") + ", ".join(others)})

    size = _dir_bytes(folder)
    cost = f"{_megabytes(size)} will be freed."
    pub = published_record(report_of(dtxsid)[0])
    if pub and kind in ("study", "report"):
        cost = (f"This {'report' if kind == 'report' else 'study'} reproduces {pub['report']}. "
                "It can be rebuilt only from the command line (tooling.build_published_reports), "
                "not from this interface. " + cost)

    # The token covers the study's content. The request log (.provenance.jsonl)
    # is left out: every request that reaches a step appends to it, a refused
    # delete included, so it would refuse the retry that follows.
    listing = hashlib.sha256()
    for p in sorted(folder.rglob("*")):
        if p.name == _PROVENANCE_LOG and p.parent == folder:
            continue
        st = p.lstat()
        listing.update(f"{p.relative_to(folder)}\0{st.st_size}\0{st.st_mtime_ns}\n".encode())
    return {"confirm": {"act": "delete_study", "strength": "irreversible",
                        "deletes": deletes, "keeps": keeps,
                        "approvals_lost": approved, "cost": {"say": cost},
                        "reason_required": False},
            "type_to_confirm": dtxsid,
            "preview_token": "sha256:" + listing.hexdigest()}


@step_provenance
def delete_study_step(dtxsid: str, confirm_id: str, preview_token: str) -> dict:
    """Delete a study for good, after a person reviewed the dry run and typed
    its id (module M1; Q-M1-4: permanent). Re-runs the dry run (so its refusals
    hold here too), then checks the typed id (``confirm_mismatch``: equal to
    the id, case-sensitive, spaces at either end ignored) and the token
    (``changed_since_preview``). Removes the session's folder and forgets what
    the server holds in memory for it. What lies outside the folder (its
    deliverables in output/, a study definition, other sessions) stays.
    Returns ``{"deleted", "kept", "say"}``."""
    import shutil

    from pipeline.pool_globals import forget_session
    from workflow.studies import StudyRefusal, session_folder

    preview = delete_study_dry_run(dtxsid)
    if (confirm_id or "").strip() != dtxsid:
        raise StudyRefusal("confirm_mismatch", f"typed {confirm_id!r}, the study is {dtxsid}", 400)
    if preview_token != preview["preview_token"]:
        raise StudyRefusal("changed_since_preview",
                           f"preview token {preview_token} does not match {preview['preview_token']}",
                           409)
    # Renamed away first, so the study leaves the list in one step; then removed.
    import uuid
    folder = session_folder(dtxsid)
    doomed = folder.parent / f".deleting-{dtxsid}-{uuid.uuid4().hex[:8]}"
    folder.rename(doomed)
    shutil.rmtree(doomed, ignore_errors=True)
    if doomed.exists():
        logger.warning("Deleted study %s: %s could not be fully removed", dtxsid, doomed)
    forget_session(dtxsid, folder / "files")
    logger.info("Deleted study %s (folder removed)", dtxsid)
    return {"deleted": dtxsid, "kept": preview["confirm"]["keeps"],
            "say": f"{dtxsid} was deleted."}
