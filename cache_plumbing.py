"""
Per-section disk cache + hash inputs + platform-table (de)serializers.

The processing pipeline (api_process_integrated) is expensive — BMDS
modeling alone takes minutes — so each pipeline stage caches its output
to sessions/{dtxsid}/_cache_{unit}_{hash_val}.json.  When inputs change,
the hash changes, the old cache file is replaced, and only the affected
stages re-run.

This module owns the whole caching apparatus:

  - _load_cache / _save_cache  — disk I/O against a per-(dtxsid, unit)
    cache file, with stale-hash cleanup on write
  - the _hash_* family         — one per cache unit (ntp, sections,
    bmds, genomics, bmd_summary, methods).  Each hashes the *inputs that
    actually affect that stage's output*, so e.g. switching the primary
    BMD statistic doesn't invalidate the BMDS cache (it hashes raw
    dose-response numbers, not the stat selection).
  - schema-version constants   — bumped by hand when a stage's output
    schema changes in a way the hash inputs alone wouldn't catch
  - _serialize_platform_tables / _deserialize_platform_tables — TableRow
    dataclass <-> JSON round-trip used by the NTP cache, with the float-
    keyed-dict-key dance and dynamically-attached _bmds_input preservation
  - _restore_category_lookup   — reconstruct the (prefix, endpoint) tuple
    keys from the pipe-separated string keys stored in integrated.json,
    and re-pick BMD/BMDL/BMDU from the stored stat blocks for a given
    bmd_stat selection (lets the UI flip stats without re-running Java)

The functions read state via pool_globals._session_dir (and have no
state of their own).  The original monolithic pool_orchestrator.py
re-exports everything here for backward compatibility.

Cache hash design table — see the HIGH priority TODO in CLAUDE.md for
the full hash-input matrix showing which input changes invalidate which
caches.
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

import hashlib
import json
import logging
import os
from dataclasses import asdict

import orjson

from bmdx_pipe import TableRow

from pool_globals import _session_dir


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Disk I/O: per-section cache files
# ---------------------------------------------------------------------------
# Cache file naming: sessions/{dtxsid}/_cache_{unit}_{hash_val}.json
# Units (one cache file per unit per session): ntp, sections, bmds,
# genomics, bmd_summary, methods, charts.

def _load_cache(dtxsid: str, unit: str, hash_val: str) -> dict | None:
    """
    Load a per-section cache file from disk.

    Returns the cached data dict, or None on cache miss / corruption.
    Uses orjson for fast deserialization (10-50x faster than json.loads
    on the multi-MB NTP stats cache).

    Args:
        dtxsid:   Session identifier — cache lives in sessions/{dtxsid}/.
        unit:     Cache unit name (ntp, sections, bmds, genomics, bmd_summary).
        hash_val: 16-char hex hash of the inputs that affect this unit.
    """
    cache_path = _session_dir(dtxsid) / f"_cache_{unit}_{hash_val}.json"
    if not cache_path.exists():
        return None
    try:
        data = orjson.loads(cache_path.read_bytes())
        logger.info("Cache hit: %s for %s (hash %s)", unit, dtxsid, hash_val)
        return data
    except Exception:
        logger.warning("Corrupted %s cache for %s, recomputing", unit, dtxsid)
        return None


def _save_cache(dtxsid: str, unit: str, hash_val: str, data: dict) -> None:
    """
    Persist a per-section cache to disk, cleaning up old hashes for the
    same unit.

    Each unit keeps at most one cache file on disk.  When the hash changes
    (because an input changed), the old file is deleted and the new one
    written.  Errors are logged but not raised — caching is a performance
    optimization, not a correctness requirement.

    Args:
        dtxsid:   Session identifier.
        unit:     Cache unit name.
        hash_val: 16-char hex hash of current inputs.
        data:     The payload to cache (must be JSON-serializable).
    """
    session = _session_dir(dtxsid)
    cache_path = session / f"_cache_{unit}_{hash_val}.json"
    try:
        # Remove stale caches for this unit (different hash = different inputs)
        for old in session.glob(f"_cache_{unit}_*.json"):
            if old != cache_path:
                old.unlink(missing_ok=True)
        # OPT_NON_STR_KEYS: some payloads carry dicts keyed by floats (e.g. the
        # methods context's per-dose pk_concentrations / genomics_sample_counts),
        # which orjson rejects by default with "Dict key must be str".  This
        # option coerces such keys to their string form on the way out — a
        # no-op for the all-string payloads (consumers only look these dicts up
        # / iterate them, never do arithmetic on the keys).  Without it the
        # methods cache write silently failed, so M&M re-ran the LLM on every
        # reload instead of being served from cache.
        cache_path.write_bytes(orjson.dumps(data, option=orjson.OPT_NON_STR_KEYS))
        logger.info("Cached %s for %s (%s)", unit, dtxsid, cache_path.name)
    except Exception:
        logger.warning("Failed to cache %s for %s", unit, dtxsid, exc_info=True)


# ---------------------------------------------------------------------------
# Per-unit hash functions
# ---------------------------------------------------------------------------
# Each returns a 16-char hex string.  The hash inputs are chosen so that
# each unit only invalidates when its actual inputs change.  For example,
# BMDS hashes the raw dose-response data (doses/means/SEs/Ns), NOT the
# bmd_stat — so switching from "median" to "mean" doesn't re-run the
# 8-minute pybmds session.

# Bump when something OTHER than the hashed inputs changes how NTP
# TableRows come out — e.g. a change in bmd_project_schema that alters
# the integrated dict at load time.  _hash_ntp deliberately hashes only
# experiment identity (names + count), so a change like the bMDResult
# repointing in `_repoint_bmd_results_to_truth` — which mutates refs but
# not experiment names — is invisible to the hash and would otherwise
# serve a stale cache.  Bumping this forces a miss.  Because _hash_sections
# folds in ntp_hash, bumping here also cascades the sections cache.
_NTP_CACHE_SCHEMA_VERSION = 2  # bumped: schema repoints bMDResult refs onto truth siblings


def _hash_ntp(integrated: dict, bmd_stat: str) -> str:
    """
    Hash inputs that affect NTP stats computation.

    Inputs: integrated data identity (experiment names + count) and
    the primary BMD statistic (affects category lookup → BMD/BMDL
    values on TableRows).  xlsx_rosters are part of _meta and only
    change on re-integration, which deletes all caches anyway.

    A schema_version is folded in so that changes in how the integrated
    dict is normalized at load time (e.g. the bMDResult repointing in
    bmd_project_schema) force a cache miss even when experiment identity
    is unchanged.
    """
    experiments = integrated.get("doseResponseExperiments", [])
    key = json.dumps({
        "schema_version": _NTP_CACHE_SCHEMA_VERSION,
        "bmd_stat": bmd_stat,
        "n_experiments": len(experiments),
        "experiment_names": sorted(e.get("name", "") for e in experiments),
    }, sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# Bump when the sections cache schema changes (new fields on row dicts,
# renamed keys, etc.).  Changing this forces all existing sections caches
# to miss on the next reprocess even if NTP inputs are unchanged.
_SECTIONS_CACHE_SCHEMA_VERSION = 8  # bumped: sidecar + imputed_cells folded into the key (stale-sidecar fix)


def _fingerprint_files(paths) -> list[list]:
    """
    Fingerprint a set of files by (basename, size, mtime_ns) for cache keying.

    Used to detect edits to inputs the sections stage reads straight off disk
    (sidecar JSONs, clinical-obs CSVs) but that are NOT reflected in the
    integrated dict — so a content change wouldn't otherwise move any hash.
    Cheap (one stat() per file, no read) and order-independent (sorted).
    Missing/unstattable files are skipped, so deleting an input also moves the
    fingerprint.  Returns a JSON-serializable list of [name, size, mtime_ns].
    """
    fp = []
    for p in paths:
        try:
            st = os.stat(p)
        except OSError:
            continue
        fp.append([os.path.basename(p), st.st_size, st.st_mtime_ns])
    fp.sort()
    return fp


def _hash_sidecars(session_dir: str, extra_paths=None) -> str:
    """
    Fingerprint the on-disk inputs the sections stage reads directly.

    The sections stage builds apical/clinical-pathology tables and the
    body-weight mortality + tissue-concentration sections from sidecar JSON
    files in {session_dir}/files/ and from the clinical-obs CSVs recorded in
    _meta.clinical_obs_files.  None of those flow through ntp_hash, so before
    this was folded in, editing a sidecar served a stale report silently
    (bug: stale-sidecar cache key).

    Hashes every *.sidecar.json under files/ plus any extra_paths (the
    clinical-obs CSVs) by (name, size, mtime).  Returns 16-char hex.
    """
    paths = []
    files_dir = os.path.join(session_dir, "files")
    if os.path.isdir(files_dir):
        paths.extend(
            os.path.join(files_dir, f)
            for f in os.listdir(files_dir)
            if f.endswith(".sidecar.json")
        )
    if extra_paths:
        paths.extend(extra_paths)
    fp = _fingerprint_files(paths)
    return hashlib.sha256(json.dumps(fp, sort_keys=True).encode()).hexdigest()[:16]


def _hash_sections(
    ntp_hash: str,
    compound_name: str,
    dose_unit: str,
    sidecar_hash: str = "",
    imputed_cells=None,
    organ_allowlist=None,
    sex_allowlist=None,
    assay_filters=None,
) -> str:
    """
    Hash inputs that affect section card building.

    Depends on NTP stats output (via ntp_hash) plus display parameters
    that affect narrative text.  dtxsid is implicit (cache directory).

    Also folds in:
      - sidecar_hash: a fingerprint of the sidecar JSONs + clinical-obs CSVs
        the sections stage reads straight off disk (see _hash_sidecars).
        Without it, editing a sidecar left the cache key unchanged and a
        stale report was served.
      - imputed_cells: the _meta.imputed_cells map, which the
        clinical-pathology builder uses to footnote imputation-backed BMDs;
        it is not otherwise reflected in ntp_hash.
      - organ_allowlist: the "organ-weight" area allowlist (a list of organ
        tokens) — the Organ Weight table AND its narrative are baked into the
        sections blob, so editing the allowlist MUST force a fresh build.
        Unlike the genomics allowlist (post-filtered, no hash), this one is
        folded here.  None/empty ⇒ no effect on the key (backward compatible).
      - sex_allowlist: the "apical" area sex allowlist, and assay_filters: the
        per-platform clinical-chemistry/hematology endpoint allowlists.  Both
        narrow the apical tables + narratives that live in the sections blob
        (via apply_apical_filters upstream of the build), so a change MUST force
        a fresh build.  Same injected-only-when-set rule as organ_allowlist.

    A schema_version is folded in so that adding/renaming row-dict fields
    (e.g. the `responsive` flag for clinical-pathology bolding) forces a
    miss even when the upstream inputs haven't changed.
    """
    payload = {
        "schema_version": _SECTIONS_CACHE_SCHEMA_VERSION,
        "ntp": ntp_hash,
        "compound_name": compound_name,
        "dose_unit": dose_unit,
        "sidecars": sidecar_hash,
        "imputed_cells": imputed_cells,
    }
    # Only inject the organ-weight allowlist when one is set, so an unfiltered
    # report hashes byte-identically to the pre-feature key (existing on-disk
    # sections caches stay valid).  When set, a different list → a different key
    # → a fresh build (the Organ Weight table + narrative live in this blob).
    if organ_allowlist:
        payload["organ_allowlist"] = sorted(organ_allowlist)
    # Same injected-only-when-set rule for the sibling apical allowlists, so an
    # unfiltered report hashes byte-identically to the pre-feature key.
    if sex_allowlist:
        payload["sex_allowlist"] = sorted(sex_allowlist)
    if assay_filters:
        # Sort both the area keys and each token list for an order-stable key.
        payload["assay_filters"] = {
            area: sorted(tokens)
            for area, tokens in sorted(assay_filters.items())
            if tokens
        } or None
        if payload["assay_filters"] is None:
            del payload["assay_filters"]
    key = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _hash_bmds(bmds_inputs: list[dict]) -> str:
    """
    Hash the raw dose-response data for BMDS modeling.

    Uses CONTENT of _bmds_input dicts (doses, means, SEs, Ns) — NOT the
    ntp_hash.  This means BMDS stays cached even when bmd_stat changes,
    because the underlying dose-response data hasn't changed.
    """
    # Sort by endpoint key for deterministic hashing
    content = []
    for inp in sorted(bmds_inputs, key=lambda x: x.get("key", "")):
        content.append({
            "key": inp.get("key", ""),
            "doses": inp.get("doses", []),
            "ns": inp.get("ns", []),
            "means": inp.get("means", []),
            "stdevs": inp.get("stdevs", []),
        })
    key = json.dumps(content, sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# Bump this when the genomics cache schema changes (new fields added/removed).
# Changing this constant forces all existing caches to be regenerated on the
# next reprocess, even when the input data and filter parameters are identical.
_GENOMICS_CACHE_SCHEMA_VERSION = 3  # bumped: added adversity_signatures

# Bump when the chart-rendering algorithm changes (jitter formula,
# axis configuration, etc.) without changing the underlying gene-set
# inputs.  Mixed into charts_hash on top of genomics_hash, so the
# chart cache invalidates while the (slow + LLM-costed) genomics
# pipeline cache stays warm.
_CHARTS_CACHE_SCHEMA_VERSION = 2  # bumped: bounded jitter (no clipped top-cluster points)


def _hash_genomics(
    bmd_stats: list[str],
    go_pct: float,
    go_min_genes: int,
    go_max_genes: int,
    go_min_bmd: int,
    ge_filename: str,
) -> str:
    """
    Hash inputs that affect genomics extraction.

    bmd_stats (the full array) matters because each stat gets its own
    GO table.  GO filter cutoffs and the GE filename determine which
    categories pass and from which file.

    _GENOMICS_CACHE_SCHEMA_VERSION is included so that schema changes
    (new fields, renamed fields) force a cache miss even when the input
    data and filter parameters are unchanged.
    """
    key = json.dumps({
        "schema_version": _GENOMICS_CACHE_SCHEMA_VERSION,
        "bmd_stats": list(bmd_stats),
        "ge_filename": ge_filename,
        "go_max_genes": go_max_genes,
        "go_min_bmd": go_min_bmd,
        "go_min_genes": go_min_genes,
        "go_pct": go_pct,
    }, sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _hash_bmd_summary(ntp_hash: str, bmds_hash: str) -> str:
    """
    Hash inputs for the BMD summary tables.

    Depends on NTP stats (apical BMD summary uses platform_tables) and
    BMDS results (BMDS BMD summary merges pybmds output with TableRows).
    """
    key = f"{ntp_hash}:{bmds_hash}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# Per-session fields that change every server process / file load and must
# NOT enter the methods hash, or the cache misses on every restart.  file_id
# is a fresh uuid4 minted per session load (session_routes); the ts_* stamps
# are wall-clock.  None of them affect the M&M prose, which is a pure function
# of which files exist (by name) and their study content.
_METHODS_VOLATILE_FP_FIELDS = frozenset({
    "file_id", "ts_added", "ts_filesystem", "ts_internal",
})


def _hash_methods(dtxsid: str, fingerprints: dict) -> str:
    """
    Hash inputs for the Materials and Methods section.

    Depends on the DTXSID (chemical identity) and which files are in the
    pool (filenames determine which M&M subsections appear — e.g.,
    Transcriptomics only if gene expression exists).  Content of
    fingerprints matters too (dose groups, endpoints, etc. feed into the
    LLM prompt).

    The hash must be STABLE across server restarts so the cached M&M prose
    survives a reload instead of re-running the LLM.  The incoming dict is
    keyed by file_id (a fresh uuid4 each session load) and its values carry
    the same volatile id plus wall-clock timestamps — hashing those made the
    key change on every restart, permanently missing the cache.  We therefore
    re-key by the stable filename and drop the volatile fields, hashing only
    the study-relevant content that actually shapes the prompt.
    """
    stable: dict[str, dict] = {}
    for fp in fingerprints.values():
        # Tolerate both plain dicts (the process-integrated path) and any
        # dataclass-shaped fallback by normalizing to a dict first.
        fp_dict = fp if isinstance(fp, dict) else {
            k: getattr(fp, k) for k in getattr(fp, "__dataclass_fields__", {})
        }
        fname = str(fp_dict.get("filename") or "")
        stable[fname] = {
            k: str(v)
            for k, v in sorted(fp_dict.items())
            if k not in _METHODS_VOLATILE_FP_FIELDS
        }
    fp_key = json.dumps(stable, sort_keys=True)
    key = f"methods:{dtxsid}:{fp_key}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# TableRow serialization for NTP cache
# ---------------------------------------------------------------------------
# The NTP stats cache stores platform_tables: {platform -> {sex -> [TableRow]}}.
# TableRow is a dataclass, so we use asdict() for serialization.  Two wrinkles:
#   1. Float dict keys (values_by_dose, n_by_dose, missing_animals_by_dose)
#      must be converted to strings for JSON, then back to floats on load.
#   2. _bmds_input is dynamically attached (not a dataclass field), so
#      asdict() won't capture it — we handle it manually.

def _serialize_platform_tables(platform_tables: dict[str, dict[str, list]]) -> dict:
    """
    Convert platform_tables ({platform -> {sex -> [TableRow]}}) to a
    JSON-serializable dict for caching.

    Preserves all TableRow fields plus the dynamically-attached _bmds_input
    dict.  Float dict keys are converted to strings for JSON compatibility.

    Args:
        platform_tables: The partitioned NTP stats output.

    Returns:
        Nested dict structure safe for orjson serialization.
    """
    result = {}
    for platform, sex_rows in platform_tables.items():
        result[platform] = {}
        for sex, rows in sex_rows.items():
            serialized = []
            for row in rows:
                # asdict() handles all dataclass fields
                d = asdict(row)
                # Float keys → string keys for JSON roundtrip
                for fk_field in ("values_by_dose", "n_by_dose", "missing_animals_by_dose"):
                    if d.get(fk_field):
                        d[fk_field] = {str(k): v for k, v in d[fk_field].items()}
                # Coerce numpy scalar types to native Python types so orjson
                # can serialize them.  The Java stats pipeline (Williams/Dunnett)
                # returns numpy.bool_ for the responsive flag and occasionally
                # numpy.float64/numpy.int64 for other fields.  asdict() preserves
                # these numpy types rather than converting them.
                for key, val in d.items():
                    if hasattr(val, "item"):  # numpy scalar → .item() → native
                        d[key] = val.item()
                # Preserve dynamically-attached _bmds_input (not a dataclass field)
                if hasattr(row, "_bmds_input") and row._bmds_input:
                    d["_bmds_input"] = row._bmds_input
                serialized.append(d)
            result[platform][sex] = serialized
    return result


def _deserialize_platform_tables(data: dict) -> dict[str, dict[str, list]]:
    """
    Reconstruct platform_tables from a cached dict back to
    {platform -> {sex -> [TableRow]}} with proper types.

    String dict keys are converted back to floats.  _bmds_input is
    re-attached as a dynamic attribute.  Unknown keys (from future
    schema changes) are filtered out to avoid TypeError.

    Args:
        data: The cached dict from _serialize_platform_tables().

    Returns:
        platform_tables with live TableRow objects.
    """
    # Known dataclass fields — filter out _bmds_input and any future extras
    known_fields = {f.name for f in TableRow.__dataclass_fields__.values()}

    result = {}
    for platform, sex_rows in data.items():
        result[platform] = {}
        for sex, rows in sex_rows.items():
            deserialized = []
            for d in rows:
                # Pop _bmds_input before constructing TableRow (not a field)
                bmds_input = d.pop("_bmds_input", None)
                # String keys → float keys
                for fk_field in ("values_by_dose", "n_by_dose", "missing_animals_by_dose"):
                    if d.get(fk_field):
                        d[fk_field] = {float(k): v for k, v in d[fk_field].items()}
                # Filter to known fields only (forward compat)
                filtered = {k: v for k, v in d.items() if k in known_fields}
                row = TableRow(**filtered)
                if bmds_input:
                    row._bmds_input = bmds_input
                deserialized.append(row)
            result[platform][sex] = deserialized
    return result


def _restore_category_lookup(integrated: dict, bmd_stat: str) -> dict[tuple[str, str], dict]:
    """
    Restore the category lookup from the serialized pipe-separated keys in
    the integrated BMDProject.

    integrate_pool() stored this as _category_lookup with "prefix|endpoint"
    string keys; we restore them to (prefix, endpoint) tuple keys that
    build_table_data() expects.

    Also re-selects BMD/BMDL/BMDU values using the requested bmd_stat.
    build_category_lookup() stores the full stat blocks (bmd_stats,
    bmdl_stats, bmdu_stats) alongside the pre-selected values, so we can
    re-pick the statistic without re-running Java.

    Args:
        integrated: The merged BMDProject dict.
        bmd_stat:   The first (primary) BMD statistic key to select.

    Returns:
        Dict mapping (experiment_prefix, endpoint_name) to category info dicts.
    """
    flat_cat = integrated.get("_category_lookup", {})
    cat_lookup: dict[tuple[str, str], dict] = {}

    # Collect experiment names so we can resolve BMDExpress pipeline
    # suffixes in category keys.  Old integrated.json files may have
    # keys like "female_clin_chem_williams_0.05_NOMTC_nofoldfilter|endpoint"
    # but build_table_data() queries with "female_clin_chem".
    all_exp_names = sorted(
        [exp.get("name", "") for exp in integrated.get("doseResponseExperiments", [])],
        key=len, reverse=True,
    )

    for k, v in flat_cat.items():
        entry = dict(v)
        # Re-select from stored stat blocks if they exist.
        cat_bmd_blk = entry.get("bmd_stats", {})
        cat_bmdl_blk = entry.get("bmdl_stats", {})
        cat_bmdu_blk = entry.get("bmdu_stats", {})
        if cat_bmd_blk:
            entry["bmd"] = cat_bmd_blk.get(bmd_stat, cat_bmd_blk.get("mean", ""))
        if cat_bmdl_blk:
            entry["bmdl"] = cat_bmdl_blk.get(bmd_stat, cat_bmdl_blk.get("mean", ""))
        if cat_bmdu_blk:
            entry["bmdu"] = cat_bmdu_blk.get(bmd_stat, cat_bmdu_blk.get("mean", ""))

        prefix, endpoint = k.split("|", 1) if "|" in k else (k, "")

        # Resolve suffixed prefix to raw experiment name.
        # This handles both new (already resolved) and old (suffixed) keys.
        resolved = prefix
        for exp_name in all_exp_names:
            if prefix == exp_name:
                resolved = exp_name
                break
            if prefix.startswith(exp_name) and prefix[len(exp_name):len(exp_name) + 1] == "_":
                resolved = exp_name
                break

        cat_lookup[(resolved, endpoint)] = entry
        # Also keep the original key for backward compat
        if resolved != prefix:
            cat_lookup[(prefix, endpoint)] = entry

    return cat_lookup
