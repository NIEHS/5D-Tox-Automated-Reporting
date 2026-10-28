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
import os
import shutil
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
def materialize_summary(dtxsid: str, store: PoolStore, *, policy=None) -> dict:
    """Write the report's Summary section (summary.json) from the session's
    results — narrative.report_summary, deterministic, the same inputs as the
    Abstract — as a provisional draft (approved=False, source="generated").

    Through the section write gate (workflow.section_writes) as a system
    write: unchanged text writes nothing; under the C2 ``policy``
    (safeguards.sections.ownership_policy) text a person owns (approved,
    released with PROTECTED, edited) is never replaced — the new text is HELD
    and a `hold` event records that Process had a new Summary it did not apply.
    Its own extra rule stands: it replaces only its own earlier output
    (``source == "generated"``), never one the LLM route or a person saved.

    Returns ``{ok, written: bool, paragraphs: int, held?: {why, version}}``."""
    from narrative.report_summary import build_report_summary
    from narrative.summary_llm import summary_inputs
    from workflow import section_writes

    prior = section_writes.read_prior(dtxsid, "summary", store)
    if prior is not None and prior.get("source") != "generated":
        return {"ok": True, "written": False, "paragraphs": 0,
                "held": {"why": "not_generated_here", "version": prior.get("version")}}

    paragraphs = build_report_summary(**summary_inputs(store.session_dir(dtxsid)))
    if not paragraphs:
        return {"ok": True, "written": False, "paragraphs": 0}
    out = section_writes.write_section(
        dtxsid, "summary", {"paragraphs": paragraphs, "source": "generated", "approved": False},
        store, act="summary", actor="system", author="generated", policy=policy)
    result = {"ok": True, "written": out["outcome"] == "written",
              "paragraphs": len(paragraphs) if out["outcome"] == "written" else 0}
    if out["outcome"] == "held":
        result["held"] = {"why": "owned", "version": out["version"]}
    return result


def materialize_result_sections(dtxsid: str, store: PoolStore, *, policy=None) -> dict:
    """Write the apical result sections from the Process cache to disk as section
    files, so the document surface shows them and the deliverable renders complete.

    Process produces apical section content in `_cache_sections_*.json` (a list of
    `{platform, title, tables_json, narrative, first_col_header, caption, footnotes}`)
    but never writes the `bm2_<slug>.json` FILES the render + readiness paths read.
    This closes that gap: for each cached apical section, write `bm2_<slug>.json`
    (`slug = bm2_slug(title)`) carrying the SAME fields — a provisional, generated
    draft (`approved=False`).

    Every file goes through the section write gate (workflow.section_writes) as
    a system write, under the C2 ``policy`` (safeguards.sections.ownership_policy;
    without it every changed file is written, the prior archived):
      * content unchanged → nothing written (an approval stands; I5);
      * changed, not owned → the prior archived, the new written, a
        `generate/draft` event;
      * changed, owned (approved, or released with PROTECTED) → knocked down with
        a record (C2 D2/A1): the deliverable renders apical content from the
        Process cache, so what prints has already changed; the owned version is
        archived, the approval withdrawn (FINAL with it, PROTECTED stands), a
        `review {why, since_version, flips}` marker set, a `reprocess/
        needs-re-bless` event recorded. Re-accepting clears it. `wording_review`
        keeps its meaning (the data-derived words that flipped under approved
        wording; Phase 3b).

    Genomics is deterministic and is NOT materialized here (ADR-0018). Returns
    `{ok, materialized, unchanged, needs_review: [{key, why, prior_version,
    version, flips}], held}`; `materialized` = the files written.
    """
    from pipeline.session_db import _latest_cache
    from pipeline.session_store import bm2_slug
    from workflow import section_writes
    from workflow.reprocess import cat_signature_flips

    sdir = store.session_dir(dtxsid)
    cache = _latest_cache(sdir, "sections")
    sections = cache.get("sections") if isinstance(cache, dict) else None
    result: dict = {"ok": True, "materialized": [], "unchanged": [], "needs_review": [],
                    "held": []}
    if not sections:
        return result

    from common import provenance
    for sec in sections:
        title = sec.get("title") or sec.get("platform") or ""
        slug = bm2_slug(title)
        if not slug:
            continue
        section_key = f"bm2_{slug}"
        cat_signature = sec.get("cat_signature") or {}

        # The prior file, read BEFORE the gate replaces it: the only point where
        # the old and new categorical signatures coexist (Phase 3b flip detection).
        prior = section_writes.read_prior(dtxsid, section_key, store)
        flips = (cat_signature_flips(prior.get("cat_signature") or {}, cat_signature)
                 if prior is not None else [])

        # Carry the render-relevant fields verbatim; provisional (unapproved).
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
        out = section_writes.write_section(
            dtxsid, section_key, data, store, act="materialize", actor="system",
            author="generated", on_owned=section_writes.REVIEW,
            review={"why": "wording_changed" if flips else "numbers_changed", "flips": flips},
            policy=policy)

        if out["outcome"] == "written":
            result["materialized"].append(section_key)
        elif out["outcome"] == "unchanged":
            result["unchanged"].append(section_key)
        elif out["outcome"] == "needs_review":
            result["materialized"].append(section_key)
            result["needs_review"].append({
                "key": section_key, "why": out["review"]["why"],
                "prior_version": out["prior_version"], "version": out["version"],
                "flips": out["review"]["flips"]})
        else:
            result["held"].append(section_key)
        provenance.record(
            "materialized", dtxsid=dtxsid, section_key=section_key,
            platform=sec.get("platform"), outcome=out["outcome"],
            wording_review=bool(flips and out["outcome"] == "needs_review"),
        )

    return result


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

@step_provenance
def validate_step(dtxsid: str, store: PoolStore) -> dict:
    """Re-fingerprint the pool and run full cross-validation.

    Returns the ValidationReport as a plain dict (also persisted to
    validation_report.json). Raises StepError(404) if the session has no files.

    Never deletes the dataset or the data approval (C1 D4): a validation that
    finds errors leaves them inert (the phase refuses their use), and one that
    no longer matches the integration's basis reads "integrate again".
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
    A correction made after integration takes effect at the next integration.
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

# What integrate_pool writes over in the session folder: the dataset and the
# two sidecars read beside it.
_DATASET_FILES = ("integrated.json", "_category_lookup.json", "genomics.sidecar.json")


def _keep_dataset_files(session_dir: Path) -> dict:
    """Copy the dataset files an integration will overwrite into a scratch
    folder inside the session; ``{"dir", "had": {name: bool}}``."""
    import tempfile
    session_dir = Path(session_dir)
    if not session_dir.is_dir():                 # nothing on disk to overwrite
        return {"dir": None, "had": {}}
    keep = Path(tempfile.mkdtemp(prefix=".integrating-", dir=session_dir))
    had = {}
    for name in _DATASET_FILES:
        src = session_dir / name
        had[name] = src.is_file()
        if had[name]:
            shutil.copy2(src, keep / name)
    return {"dir": keep, "had": had}


def _restore_dataset_files(session_dir: Path, kept: dict) -> None:
    """Put back what ``_keep_dataset_files`` kept; remove what was not there."""
    session_dir = Path(session_dir)
    for name, had in kept["had"].items():
        if had:
            os.replace(kept["dir"] / name, session_dir / name)
        else:
            (session_dir / name).unlink(missing_ok=True)


def _check_dataset(dtxsid: str, integrated: dict) -> None:
    """The schema every read of the dataset applies, applied before anything
    is recorded on it (BMDProjectValidationError when it fails)."""
    from pipeline.bmd_project_schema import load_and_validate
    load_and_validate(integrated, source=f"DTXSID={dtxsid} (integration)")


@step_provenance
def integrate_step(dtxsid: str, identity: dict | None, store: PoolStore) -> dict:
    """Merge the pool into a unified BMDProject and cache it.

    `identity` is the resolved chemical identity from the caller (persisted to
    identity.json for LLM metadata inference), or None. Returns the lightweight
    summary payload (not the full integrated JSON — it can exceed response caps).
    Raises StepError(404) with no files, StepError(400) if validation hasn't run,
    StepError(500) if integration itself fails.

    Refused when the validation it would pair with the fingerprints no longer
    matches them (ValidationOutOfDate, the restart trap: a core rule, it would
    combine the wrong files); out of phase is the safeguards' refusal. A successful merge withdraws
    the data approval (archived under history/_data_approval/) and records the
    basis it was built from; it pins no method profile.
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
    _check_validation_matches(dtxsid, fps, report)

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

    # integrate_pool writes the new dataset (and its two sidecars) over the old
    # ones in place. Keep the old ones until the new dataset has passed the
    # schema: a failure puts them back, so the study is left as it was, never
    # with a dataset no read accepts behind an "integrated, current" phase.
    kept = _keep_dataset_files(session_dir)
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
        _check_dataset(dtxsid, integrated)
    except Exception as e:
        _restore_dataset_files(session_dir, kept)
        logger.exception("Pool integration failed for %s", dtxsid)
        raise StepError(f"Integration failed: {e}", status_code=500)
    finally:
        if kept["dir"] is not None:
            shutil.rmtree(kept["dir"], ignore_errors=True)

    # The dataset changed, so the data approval made on the old one no longer
    # holds (C1 D5: archived, never deleted). A failed merge leaves it alone.
    approval_withdrawn = _withdraw_data_approval(dtxsid, store)

    # Cache in memory for the process-integrated endpoint
    store.set_integrated(dtxsid, integrated)

    # What this dataset was built from (workflow.integration_basis): a later
    # validation that no longer matches it reads as "integrate again".
    from workflow.integration_basis import record_basis
    record_basis(dtxsid, store)

    # Study-design facts a person stated (generate_report --design): integration
    # re-infers every experiment's metadata, and the stated design must win.
    # After the cache is set, so the design lands on this integration, not the last.
    reapply_study_design(dtxsid, store)

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
    (session_dir / "session.duckdb").unlink(missing_ok=True)
    shutil.rmtree(session_dir / "session_parquet", ignore_errors=True)
    # NB: genomics.sidecar.json is NOT wiped here — integrate_pool (above) just
    # wrote the FRESH one for this integration. Its new mtime changes the genomics
    # cache key, so the stale _cache_genomics_*.json (wiped by the glob above)
    # re-extracts from the new sidecar on next process. (invalidate_pool_artifacts
    # DOES delete the sidecar, because that path tears down integrated.json too.)

    # The study's analysis method (ADR-0027): check what the .bm2 analyses
    # record against the profile a person pinned. Integration pins nothing
    # (C1 D1: a person chooses the method; Process refuses until they have).
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
        "approval_withdrawn": approval_withdrawn,
        "experiments": [
            {
                "name": exp.get("name", ""),
                "probe_count": len(exp.get("probeResponses", [])),
            }
            for exp in experiments
        ],
    }


def record_study_design(dtxsid: str, fields: dict, store: PoolStore) -> int:
    """Record stated study-design facts (route, vehicle, strain, …) the data
    does not carry, in study_design.json, which every later integration
    re-applies, and put them on every experiment now.  Returns the experiments
    updated.  Written as given: that the values are the vocabulary's is the
    safeguards' (safeguards.inputs)."""
    from common.clock import now_iso
    from pipeline.study_design import DESIGN_FILE

    store.write_json(dtxsid, DESIGN_FILE, {"fields": fields, "recorded_at": now_iso()})
    return reapply_study_design(dtxsid, store)


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
    """Report every recorded analysis setting that disagrees with the study's
    pinned method profile as a `method_mismatch` warning in the validation
    report (ADR-0027 §5).  Pins nothing (C1): with no profile pinned there is
    nothing to compare against, so the stale warnings are removed and the
    summary is empty.  Returns {profile, pinned_by, mode, deviations,
    mismatches}.  (The name is kept for its callers.)"""
    from pipeline.method_profile import pin_mode, read_pin, recorded_mismatches, session_method

    pin = read_pin(dtxsid)
    method = session_method(dtxsid) if pin else None
    mismatches = recorded_mismatches(integrated, method) if pin else []
    report = store.read_json(dtxsid, "validation_report.json")
    if isinstance(report, dict):
        issues = [i for i in report.get("issues", []) if i.get("issue_type") != "method_mismatch"]
        issues += [{"severity": "warning", "platform": None, "issue_type": "method_mismatch",
                    "message": m["message"], "files_involved": [], "suggested_precedence": None,
                    "details": {k: m[k] for k in ("analysis", "setting", "recorded", "profile")}}
                   for m in mismatches]
        report["issues"] = issues
        store.write_json(dtxsid, "validation_report.json", report)
    if not pin:
        return {"profile": None, "pinned_by": None, "mode": None, "deviations": [],
                "mismatches": []}
    return {"profile": pin["name"], "pinned_by": pin["pinned_by"], "mode": pin_mode(pin),
            "deviations": list(method.deviations), "mismatches": [m["message"] for m in mismatches]}


def _fp_field(fp, key: str):
    """A fingerprint field, whether a FileFingerprint or a plain dict."""
    return fp.get(key) if isinstance(fp, dict) else getattr(fp, key, None)


def _check_validation_matches(dtxsid: str, fps: dict, report: dict) -> None:
    """Refuse (ValidationOutOfDate) when the fingerprints integration would use
    no longer match the validation report it pairs them with: a file id in the
    coverage matrix is not among them (a cold re-scan minted new ids), or the
    files they name differ from the report's. Refuses; never repairs.
    Classification corrections are not compared (C1 spec §3.2; C3)."""
    from workflow.errors import ValidationOutOfDate

    cov_ids: set = set()
    for tiers in (report.get("coverage_matrix") or {}).values():
        for v in (tiers or {}).values():
            if isinstance(v, list):
                cov_ids.update(i for i in v if i)
            elif isinstance(v, str) and v:
                cov_ids.add(v)
    missing_ids = len(cov_ids - set(fps))
    added: set = set()
    missing: set = set()
    if isinstance(report.get("fingerprints"), dict):
        held = {n for n in (_fp_field(fp, "filename") for fp in fps.values()) if n}
        checked = {n for n in (_fp_field(fp, "filename")
                               for fp in report["fingerprints"].values()) if n}
        added, missing = held - checked, checked - held
    if missing_ids or added or missing:
        raise ValidationOutOfDate(dtxsid, missing_ids, sorted(added), sorted(missing))


DATA_APPROVAL_HISTORY = "history/_data_approval"


def _withdraw_data_approval(dtxsid: str, store: PoolStore) -> bool:
    """Move animal_report.json (the data approval) to
    history/_data_approval/<stamp>-animal_report.json; True when there was one.
    The approval was of the dataset integration just replaced (C1 D5)."""
    if not store.artifact_exists(dtxsid, "animal_report.json"):
        return False
    from common.clock import now_iso

    sdir = store.session_dir(dtxsid)
    archive = sdir / DATA_APPROVAL_HISTORY
    archive.mkdir(parents=True, exist_ok=True)
    stamp = now_iso().replace(":", "")
    (sdir / "animal_report.json").replace(archive / f"{stamp}-animal_report.json")
    logger.info("Data approval of %s withdrawn by re-integration (archived)", dtxsid)
    return True


# ---------------------------------------------------------------------------
# generate-animal-report
# ---------------------------------------------------------------------------

@step_provenance
def generate_animal_report_step(dtxsid: str, store: PoolStore) -> dict:
    """Build the per-animal traceability report and persist it.

    Returns the AnimalReport as a plain dict. Raises StepError(404) with no
    files, StepError(400) if nothing fingerprinted, StepError(500) on failure.
    (Refusing it before integration is the safeguards': C1.)
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
    """Approve (lock) an existing report section. A state change: its text is
    never touched (C2: accepting changes the state, never the content).

    Stamps `approved=True` + `approved_at`, promotes the facts to FINAL (which
    sets PROTECTED), and clears what a person's reading answers: `stale` (the
    pool changed after approval), `wording_review` (data-derived words flipped
    under approved wording) and `review` (Process changed what an approved
    apical section prints: C2 D2/A1). Saved in place (archive=False) with one
    `edit/blessed` event against the SAME version, so a re-accept after a
    reprocess flips needs-re-bless → blessed without minting a version.

    Accepting a section that is already approved, carries no stale/review
    marker, and whose version is blessed changes nothing: ``noop
    already_accepted``, no event.

    Returns ``{ok, section_key, approved: True, version, version_status,
    noop?}``. Raises section_key_invalid (400), section_not_found (404).
    """
    from workflow import section_writes as sw
    from workflow.ownership import content_hash

    if not dtxsid or not section_key:
        raise StepError("dtxsid and section_key are required", status_code=400)
    section_key = sw.validate_section_key(dtxsid, section_key)
    data = sw.read_prior(dtxsid, section_key, store)
    if data is None:
        raise sw.not_found(section_key, "approve")

    version = data.get("version", 1)
    result = {"ok": True, "section_key": section_key, "approved": True, "version": version,
              "version_status": "blessed"}
    if sw.already_accepted(data, sw.version_status(dtxsid, section_key, version, store)):
        return {**result, "noop": _noop("already_accepted")}

    data["approved"] = True
    data["approved_at"] = datetime.now(tz=timezone.utc).isoformat()
    for marker in ("stale", "wording_review", "review"):
        data.pop(marker, None)
    _promote_to_final(data)
    data[_VERSION_EVENT_KEY] = sw.event(
        key=section_key, cause="edit", status="blessed", act="accept", actor="person",
        author=sw.author_of(data), prior_version=version, changed=False,
        chash=content_hash(data))
    # archive=False: a lock flip is not a content change worth a history FILE;
    # save_section keeps the version and appends the event above.
    store.save_section(dtxsid, section_key, data, archive=False)
    return {**result, "version": data.get("version", version)}


@step_provenance
def release_section_step(
    dtxsid: str, section_key: str, store: PoolStore, *, reason: str = "",
) -> dict:
    """REVISE (reopen) an approved report section, preserving its content.

    The voluntary human down-ratchet: `approved=False`, FINAL withdrawn,
    PROTECTED stands (C2 D1: a released section stays protected from machines;
    only a person's explicit act replaces it). The reason is kept on the
    version trail (`revise/working`) and the `revised` marker; requiring one is
    the safeguards' (C2 D3).

    Returns ``{ok, section_key, approved: False, version, version_status,
    noop?}``; a section that is not approved changes nothing (``noop
    not_approved``, no event). Raises section_key_invalid (400),
    section_not_found (404).
    """
    from workflow import section_writes as sw
    from workflow.ownership import content_hash

    if not dtxsid or not section_key:
        raise StepError("dtxsid and section_key are required", status_code=400)
    section_key = sw.validate_section_key(dtxsid, section_key)
    data = sw.read_prior(dtxsid, section_key, store)
    if data is None:
        raise sw.not_found(section_key, "reopen")
    version = data.get("version", 1)
    result = {"ok": True, "section_key": section_key, "approved": False, "version": version}
    if not data.get("approved"):
        return {**result, "version_status": sw.version_status(dtxsid, section_key, version, store),
                "noop": _noop("not_approved")}
    reason = (reason or "").strip() or None

    data["approved"] = False
    _demote_for_revise(data, reason)
    data[_VERSION_EVENT_KEY] = sw.event(
        key=section_key, cause="revise", status="working", act="release", actor="person",
        author=sw.author_of(data), prior_version=version, changed=False,
        chash=content_hash(data), reason=reason)
    store.save_section(dtxsid, section_key, data, archive=False)
    return {**result, "version_status": "working"}


def _demote_for_revise(data: dict, reason: str) -> None:
    """Apply the HUMAN_RELEASE down-ratchet to a section dict, in place: FINAL
    withdrawn (PROTECTED stands), the human reason kept as the `revised`
    marker. Shared with the old /api/session/unapprove route's history."""
    from workflow.labels import demote_for_human_release
    from workflow.ownership import section_facts, store_content_facts

    store_content_facts(data, demote_for_human_release(section_facts(data)))
    data["revised"] = {"reason": reason}


# The no-op answers of the section steps (MODULES.md §4.2: a success that did
# nothing says so). The words are the C2 contract's.
_NOOPS = {
    "already_accepted": "This section is already accepted and nothing has changed since.",
    "not_approved": "This section isn't approved, so there is nothing to reopen.",
    "already_current": "That version is already the current one.",
}


def _noop(code: str) -> dict:
    return {"code": code, "say": _NOOPS[code]}


# The state keys a restore carries over from the CURRENT file, never from the
# version it brings back: restoring never clears currency (C2 §4.8).
_CURRENCY_KEYS = ("stale", "regenerated", "review", "wording_review")


@step_provenance
def restore_section_step(dtxsid: str, section_key: str, version, store: PoolStore, *,
                         reason: str = "", policy=None) -> dict:
    """Bring a past version of a section back as the current one (C2 §4.8, D3).

    The version is found in the archives (or is the current file); it works
    when the current file is absent (after a discard). The current file is
    archived first; the restored text becomes the next version, never its old
    number. It comes back as a DRAFT a person owns: not approved, PROTECTED
    (no machine replaces it; accepting it is a separate act). Restoring never
    clears currency: a stale or under-review current file passes its markers on.
    The reason is kept on the `restore` event with `from_version`; the C2
    ``policy`` (the safeguards) requires one.

    Returns ``{ok, section_key, version, from_version, approved: False,
    version_status: "working", noop?}``; restoring the current version is
    ``noop already_current``. Raises section_key_invalid (400),
    version_not_found (404), version_content_missing (409), and what the
    policy raises.
    """
    from workflow import section_writes as sw
    from workflow.labels import Fact
    from workflow.ownership import STATE_KEYS, store_content_facts

    section_key = sw.validate_section_key(dtxsid, section_key)
    current = sw.read_prior(dtxsid, section_key, store)
    target = sw.read_version(dtxsid, section_key, version, store)
    noop = {"ok": True, "section_key": section_key, "version": version, "from_version": version,
            "approved": bool(current and current.get("approved")),
            "version_status": sw.version_status(dtxsid, section_key, version, store),
            "noop": _noop("already_current")}
    if current is not None and current.get("version") == version:
        return noop
    reason = (reason or "").strip() or None

    data = {k: v for k, v in target.items() if k not in STATE_KEYS}
    data["approved"] = False
    store_content_facts(data, {Fact.PROTECTED})
    for k in _CURRENCY_KEYS:
        if current is not None and current.get(k):
            data[k] = current[k]
    out = sw.write_section(
        dtxsid, section_key, data, store, act="restore", actor="person",
        author=sw.author_of(target), force=True, reason=reason, cause="restore",
        status="working", extra_event={"from_version": version}, policy=policy)
    if out["outcome"] == "unchanged":
        return {**noop, "version": out["version"]}
    return {"ok": True, "section_key": section_key, "version": out["version"],
            "from_version": version, "approved": False, "version_status": "working"}


@step_provenance
def discard_section_step(dtxsid: str, section_key: str, store: PoolStore, *,
                         reason: str = "") -> dict:
    """Discard a section's current text (C2 §4.7, D4: behind the old route and
    pool reset only; the new interface does not offer it). The file is archived,
    then deleted, and a `discard/discarded` event recorded; the version counter
    stays monotonic and restore still reaches the text.

    Returns ``{ok, section_key, archived, version}``. Raises
    section_key_invalid (400), section_not_found (404). That an approved
    section is released first, and the reason, are the safeguards'.
    """
    from workflow import section_writes as sw

    section_key = sw.validate_section_key(dtxsid, section_key)
    current = sw.read_prior(dtxsid, section_key, store)
    if current is None:
        raise sw.not_found(section_key, "discard")
    reason = (reason or "").strip() or None
    out = sw.discard(dtxsid, section_key, store, act="discard", actor="person", reason=reason)
    return {"ok": True, "section_key": section_key, "archived": out["archived"],
            "version": out["version"]}
