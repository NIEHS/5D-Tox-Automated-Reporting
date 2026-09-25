"""
Pool-state mutation: progression checks, file replacement, and artifact
invalidation.

These functions encode "what changes when a user uploads, replaces, or
re-integrates files after the pool has already progressed past the
UPLOADED phase."  They sit between the upload routes (which ask "should
I invalidate?") and the cache/disk layer (which the invalidator clears).

Three functions live here:

  - pool_has_progressed(dtxsid)        — true if the session has any
    server-authoritative downstream artifact (validation_report.json
    or integrated.json on disk).  Used by upload paths to decide
    whether a new file requires cascading invalidation.
  - remove_old_file_entries(dtxsid, filename) — when a re-upload uses
    the same filename, drop the stale fingerprint + upload-dict entry
    by filename (file_ids change each upload, so filename is the
    stable key).  Persists fingerprints back to disk.
  - invalidate_pool_artifacts(dtxsid)  — clear all downstream artifacts
    that depend on pool composition.  Surgical about what it keeps:
    BMDS caches survive (content-hash keyed, so unchanged endpoints
    still hit cache after re-integration) and approved-section
    narratives are marked stale rather than deleted (preserves user
    edits while flagging that the data may have shifted underneath).

All state lives in pool_globals (_pool_fingerprints, _data_uploads,
_integrated_pool, _session_dir, _get_bm2_uploads).  remove_old_file_entries
also calls _save_fingerprints_to_disk from pool_fingerprints to keep the
on-disk cache consistent.

pool_orchestrator.py re-exports the three names so the original API
(used by background_server, session_routes, upload_routes) keeps working.
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

import json
import logging

from pipeline.pool_globals import (
    _session_dir,
    _pool_fingerprints,
    _data_uploads,
    _integrated_pool,
    _get_bm2_uploads,
)
from pipeline.pool_fingerprints import _save_fingerprints_to_disk
from pipeline.session_store import _VERSION_EVENT_KEY


logger = logging.getLogger(__name__)


def _demote_section_facts(section_data: dict) -> None:
    """Currency-forced down-ratchet of a section's on-disk facts, in place.

    Drops the top maturity rung (FINAL) via workflow.currency.demote_for_currency
    and re-serializes — the involuntary reversal the fact ratchet permits with
    DemoteReason.CURRENCY_FORCED. PROTECTED (auto-set by FINAL) stays, so the
    content stops claiming finality but remains guarded. A no-op when the section
    holds no maturity fact, so older sections are byte-unaffected. Kept fail-soft
    by the caller's try/except (a demote failure must not abort invalidation)."""
    from workflow.currency import demote_for_currency
    from workflow.ownership import section_facts, store_content_facts

    store_content_facts(section_data, demote_for_currency(section_facts(section_data)))


# ---------------------------------------------------------------------------
# Pool progression check
# ---------------------------------------------------------------------------

def pool_has_progressed(dtxsid: str) -> bool:
    """Check whether the pool has progressed past UPLOADED.

    Uses the existence of validation_report.json or integrated.json on disk
    as a server-authoritative signal — no client trust required.  If either
    file exists, the pool has been validated or integrated and any new upload
    requires invalidation.

    Args:
        dtxsid: The DTXSID identifying the session.

    Returns:
        True if the pool has downstream artifacts that need invalidation.
    """
    d = _session_dir(dtxsid)
    return (d / "validation_report.json").exists() or (d / "integrated.json").exists()


# ---------------------------------------------------------------------------
# File-replacement cleanup
# ---------------------------------------------------------------------------

def remove_old_file_entries(dtxsid: str, filename: str) -> str | None:
    """Remove fingerprint and upload dict entry for a file being replaced.

    When the user uploads a file with the same name as an existing one,
    the old file's metadata is stale.  This function finds the old entry
    by filename (not file_id — IDs change across uploads) and removes:
      - The fingerprint from _pool_fingerprints[dtxsid]
      - The entry from _bm2_uploads or _data_uploads

    Args:
        dtxsid:   The DTXSID identifying the session.
        filename: The filename being replaced (e.g., "Body Weight.bm2").

    Returns:
        The old file_id if found and removed, None otherwise.
    """
    fps = _pool_fingerprints.get(dtxsid, {})
    old_file_id = None

    # Find the fingerprint entry that matches this filename
    for fid, fp in list(fps.items()):
        if fp.filename == filename:
            old_file_id = fid
            del fps[fid]
            logger.info("Removed old fingerprint for %s (file_id=%s)", filename, fid)
            break

    if not old_file_id:
        return None

    # Remove from the appropriate upload dict
    bm2_uploads = _get_bm2_uploads()
    if old_file_id in bm2_uploads:
        del bm2_uploads[old_file_id]
        logger.info("Removed old bm2_upload entry for %s", filename)
    elif old_file_id in _data_uploads:
        del _data_uploads[old_file_id]
        logger.info("Removed old data_upload entry for %s", filename)

    # Persist updated fingerprints to disk so session restore stays consistent
    _save_fingerprints_to_disk(dtxsid)

    return old_file_id


# ---------------------------------------------------------------------------
# Cascading invalidation
# ---------------------------------------------------------------------------

def invalidate_pool_artifacts(dtxsid: str) -> dict:
    """Clear all downstream artifacts that depend on the file pool composition.

    Called when a file is added or replaced after the pool has already been
    validated, integrated, or approved.  Preserves:
      - Fingerprints for unchanged files (still valid)
      - BMDS caches (_cache_bmds_*.json) — content-hash keyed, so unchanged
        endpoints still hit cache after re-integration
      - Approved section narrative text — marked stale but not deleted, so
        user edits are preserved

    Args:
        dtxsid: The DTXSID identifying the session.

    Returns:
        A summary dict of what was cleared/marked, suitable for logging
        or including in the API response.
    """
    d = _session_dir(dtxsid)
    summary = {"deleted": [], "marked_stale": []}

    # --- Delete validation, integration, and approval artifacts from disk ---
    # animal_report.json is included because it was generated from the
    # integrated data that is now stale — the user must re-approve after
    # re-integrating.
    for name in ("validation_report.json", "precedence.json",
                 "integrated.json", "_category_lookup.json",
                 "genomics.sidecar.json", "animal_report.json"):
        p = d / name
        if p.exists():
            p.unlink()
            summary["deleted"].append(name)
            logger.info("Deleted %s for %s", name, dtxsid)

    # --- Delete processing caches (except BMDS — content-hash keyed) ---
    # BMDS caches survive because their hash is computed from actual data
    # content (doses, means, stdevs), not from pool identity.  After
    # re-integration, endpoints whose data didn't change will produce the
    # same hash and hit the existing cache.
    for cache_file in d.glob("_cache_*.json"):
        if cache_file.name.startswith("_cache_bmds_"):
            continue  # keep — content-hash keyed, survives re-integration
        cache_file.unlink()
        summary["deleted"].append(cache_file.name)
        logger.info("Deleted cache %s for %s", cache_file.name, dtxsid)

    # --- Delete the query substrate (ADR-0016) — derived from the now-deleted
    # integrated.json + caches, so it is stale; rebuilt on next process. ---
    import shutil
    qdb = d / "session.duckdb"
    if qdb.exists():
        qdb.unlink()
        summary["deleted"].append("session.duckdb")
    if (d / "session_parquet").exists():
        shutil.rmtree(d / "session_parquet", ignore_errors=True)
        summary["deleted"].append("session_parquet/")
    # The skip-guard fingerprint is derived from the now-deleted inputs — drop it
    # so it can't survive to falsely skip the next rebuild.
    fp = d / ".session_db.fingerprint"
    if fp.exists():
        fp.unlink()
        summary["deleted"].append(".session_db.fingerprint")
    # Same for the content skip-guard (ADR-0021 Phase C): its fingerprint +
    # cached outputs are derived from the now-deleted caches, so drop both or a
    # stale fingerprint could falsely skip content preparation next process.
    for name in (".prepare_content.fingerprint", ".prepare_content.outputs.json"):
        cf = d / name
        if cf.exists():
            cf.unlink()
            summary["deleted"].append(name)

    # --- Clear in-memory integrated pool ---
    if dtxsid in _integrated_pool:
        del _integrated_pool[dtxsid]
        logger.info("Cleared in-memory integrated pool for %s", dtxsid)

    # --- Mark sections stale by CONTENT ORIGIN (Phase 3a) ---
    # The old behavior staled EVERY bm2_*/genomics_* section uniformly. That is
    # too blunt: workflow.reprocess routes by how the content was authored —
    #   * programmatic (bm2_*): a deterministic data projection whose numbers just
    #     refresh on the next render (Phase 2 templates) — NOT staled, so the user
    #     is not forced to re-approve numbers that recompute themselves;
    #   * LLM (genomics_*): model-authored narrative that must be rewritten-with-
    #     reason and re-blessed — still staled, and stamped with a `regenerated`
    #     intent so the next genomics pass rewrites visibly + attributed and the
    #     publish gate can block until a human re-accepts.
    # should_stale_on_reprocess is the single predicate (fail-safe: unknown -> LLM
    # -> staled). See docs/plans/phase3-reprocess-currency.md.
    from workflow.reprocess import should_stale_on_reprocess
    from pipeline.session_store import save_section, iter_section_files

    # Iterate EVERY report-section file — the four singletons (background/methods/
    # bmd_summary/summary) as well as the bm2_*/genomics_* instances. The old
    # bm2_*/genomics_*-only glob silently skipped the singleton LLM sections, so a
    # reprocess never demoted summary/background/methods/bmd_summary even though
    # they are LLM-origin and must be re-blessed (F4).
    for section_stem, section_file in iter_section_files(d):
        try:
            section_data = json.loads(section_file.read_text(encoding="utf-8"))
            if not should_stale_on_reprocess(section_stem, section_data):
                continue  # programmatic (or nothing to act on) — refresh, don't stale
            if not section_data.get("stale"):
                section_data["stale"] = True
                # Record WHY it went stale so the LLM rewrite is attributed and
                # the publish gate can require a human re-accept (fail-soft:
                # absent on programmatic/older sections).
                section_data["regenerated"] = {"reason": "data_changed"}
                # Involuntary down-ratchet (ADR-0015): the SYSTEM withdraws the
                # FINAL maturity claim (currency-forced) while leaving PROTECTED
                # standing, so the section stops asserting "editorially done"
                # but stays guarded until a human re-accepts. No-op on a section
                # holding no maturity fact (older/never-finalized).
                _demote_section_facts(section_data)
                # Phase 4: a reprocess that changes what the report says must
                # leave an AUDITABLE mark on the timeline before re-acceptance.
                # Route the write through save_section (not a bare write_text)
                # so the prior blessed version is archived and a cause-tagged
                # version is minted, born "needs-re-bless" (publish-blocked
                # until a human re-accepts — see accept_section_step). The
                # marker is transient: save_section pops it, so it never
                # persists in the section JSON.
                section_data[_VERSION_EVENT_KEY] = {
                    "cause": "reprocess", "status": "needs-re-bless",
                }
                save_section(dtxsid, section_stem, section_data)
                summary["marked_stale"].append(section_file.name)
                logger.info("Marked %s as stale for %s", section_file.name, dtxsid)
        except Exception as e:
            logger.warning("Failed to mark %s as stale: %s", section_file.name, e)

    return summary
