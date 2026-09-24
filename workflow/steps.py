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

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# materialize result sections (ADR-0018 Phase 1)
# ---------------------------------------------------------------------------

@step_provenance
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

@step_provenance
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

    Style-learning SEAM: /api/session/approve also compares original-vs-edited
    paragraphs and fires extract_and_merge_style_rules in a background thread.
    That needs the request payload (original_* + edited text) and an event loop,
    neither of which belongs in a headless step — it stays in the route. This
    step lifts ONLY the state change.

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
