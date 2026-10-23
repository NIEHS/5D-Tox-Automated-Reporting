"""
session_store.py — Session persistence and version history for per-chemical data.

Approved sections are persisted to disk as JSON files under sessions/{dtxsid}/.
This allows the user to close the browser, restart the server, and pick up
exactly where they left off — the UI auto-restores on DTXSID resolution.

Version history is maintained in sessions/{dtxsid}/history/{section_key}/,
where each previously-approved version is archived with a timestamped filename
before the current version is overwritten.  This provides full audit trail and
undo capability.

Layout:
    sessions/
        {dtxsid}/
            meta.json                          — created/updated timestamps
            {section_key}.json                 — current approved version
            files/                             — uploaded .bm2 files
            history/
                {section_key}/
                    v{version:04d}-{timestamp}.json — previous versions (older
                                                  sessions: {iso_timestamp}.json)
                    index.jsonl                — the version events

Note: the LMDB bm2 cache lives at /tmp/_bm2_cache (not under sessions/)
because LMDB's mmap()/flock() are incompatible with GCS FUSE mounts.
"""

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Root directory for all session data and the UTC clock now live in the
# dependency-free `common` package (so document_model/ and knowledge_base/ can
# use them without importing pipeline/). They are re-exported here because
# many modules — and tests/conftest.py's SESSIONS_DIR monkeypatch list — still
# reach them through session_store.
from common.paths import SESSIONS_DIR  # noqa: F401  (re-export)
from common.dtxsid import validate_dtxsid
from common.clock import now_iso  # noqa: F401  (re-export)
from common.session_files import read_json_file
from bmdx_pipe import bm2_cache

# Cause-tagged version-event manifest (Phase 4, dual-cause versioned snapshots).
# Append-only JSONL log, one file per section, colocated with that section's
# archived versions under history/{section_key}/.  Each line records WHICH act
# minted (or re-blessed) a version — `edit` (a human accepted) vs `reprocess`
# (the system rewrote on new data) — plus the version number, a status, and a
# timestamp.  Deliberately `.jsonl` (not `.json`): the version-count glob in
# save_section and the version-list glob in the history route both match
# `*.json`, and a `.jsonl` file is invisible to them, so the manifest can live
# beside the archives without inflating version numbers.  Absent on old sessions
# → read_version_history returns [] (missing cause = unknown, never a crash).
_VERSION_INDEX = "index.jsonl"

# The transient marker a caller stamps onto `data` to request a cause-tagged
# version event.  save_section POPS it before writing (so it never persists in
# the section JSON) and, when present, appends one manifest line for the version
# it just wrote.  Absent → save_section behaves exactly as before (no manifest
# side effect), so every existing caller (auto-save, unapprove, restore) stays
# byte-identical and old goldens are untouched.  Shape: {"cause", "status"}.
_VERSION_EVENT_KEY = "_version_event"


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def session_dir(dtxsid: str) -> Path:
    """
    Return the session directory for a given DTXSID, creating it if needed.

    Each chemical gets its own directory under sessions/ (e.g.,
    sessions/DTXSID6020430/).  The directory is created on first approve.
    """
    # validate_dtxsid is the traversal gate: ".." / "../x" / "a/b" never reach
    # the filesystem (InvalidDtxsid → 400 at the HTTP layer).
    d = SESSIONS_DIR / validate_dtxsid(dtxsid)
    d.mkdir(parents=True, exist_ok=True)
    return d


def session_path(dtxsid: str) -> Path:
    """The session directory for a DTXSID, WITHOUT creating it — for readers.
    A render or lookup for a study that has no session must not leave an empty
    session directory behind (it would list as a session)."""
    return SESSIONS_DIR / validate_dtxsid(dtxsid)


# The ADR-0005 human-edit store for the genomics narratives: the paragraphs a
# user locked, per organ, which win over generated prose on render.
NARRATIVE_OVERRIDES_FILE = "genomics_narrative_overrides.json"


def read_narrative_overrides(session: Path) -> dict:
    """The session's locked genomics-narrative edits as
    ``{"gene_set": {organ: [...]}, "gene_bmd": {organ: [...]}}`` — empty buckets
    when the store does not exist yet.

    An unreadable store raises UnreadableSessionFile instead of reading as "no
    edits": the Lock endpoint read-modify-writes this file, so treating a
    corrupt one as empty would overwrite every other organ's locked text."""
    raw = read_json_file(Path(session) / NARRATIVE_OVERRIDES_FILE) or {}
    return {
        "gene_set": raw.get("gene_set", {}) or {},
        "gene_bmd": raw.get("gene_bmd", {}) or {},
    }


def latest_session_cache(session: Path, glob_pattern: str) -> Path | None:
    """The NEWEST file in the session dir matching ``glob_pattern``, or None.

    A session accumulates one cache file per content hash (e.g. several
    ``_cache_genomics_<hash>.json`` as the inputs change), so "the current one"
    is the most recently written, not the lexically first. Every reader of a
    hashed cache resolves it here so the session load, the preview and the
    export all show the same one."""
    candidates = sorted(Path(session).glob(glob_pattern), key=lambda p: p.stat().st_mtime)
    return candidates[-1] if candidates else None


def cached_bm2_jsons(session: Path) -> dict[str, dict]:
    """The deserialized BMDProject of every uploaded .bm2 in the session's
    files/, keyed by file stem, from the bm2 cache (the BMDExpress / BMDS
    versions, models and BMR the Methods text reports).  A .bm2 not in the cache
    yet is exported (Java) and cached: fingerprinting exports only a .bm2 whose
    name does not say what it holds, so one named for its platform ("Body
    weight.bm2", "Gene Expression-….bm2") was never read.  One that cannot be
    read is left out, logged."""
    out: dict[str, dict] = {}
    files_dir = Path(session) / "files"
    if files_dir.exists():
        for bm2_path in sorted(files_dir.glob("*.bm2")):
            path = str(bm2_path.resolve())
            cached = bm2_cache.get_json(path) or _export_bm2_json(path)
            if cached:
                out[bm2_path.stem] = cached
    return out


def _export_bm2_json(path: str) -> dict | None:
    """A .bm2's BMDProject via the Java ExportBm2 helper, stored in the cache;
    None (logged) when Java is unavailable or the export fails."""
    import tempfile
    from bmdx_pipe.apical_report import export_bm2
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp = f.name
        export_bm2(path, tmp, "NONE")
        data = json.loads(Path(tmp).read_text(encoding="utf-8"))
        bm2_cache.put_json(path, data)
        return data
    except Exception as e:  # noqa: BLE001 — a project we cannot read is left out
        logger.warning("Could not read %s for its analysis settings: %s", path, e)
        return None
    finally:
        if tmp:
            Path(tmp).unlink(missing_ok=True)


def bm2_slug(filename: str) -> str:
    """
    Slugify a .bm2 filename for use as a JSON key / filename stem.

    Strips the compound prefix (everything before the first hyphen), lowercases,
    replaces spaces/non-alphanum with hyphens, and strips the .bm2 extension.

    Example:
        'P3MP-Organ and Body Weights.bm2' → 'organ-and-body-weights'
        'P3MP-Clinical Pathology.bm2'     → 'clinical-pathology'
    """
    # Remove .bm2 extension
    stem = filename.rsplit(".bm2", 1)[0]
    # Drop the compound prefix before the first hyphen (e.g. "P3MP-")
    if "-" in stem:
        stem = stem.split("-", 1)[1]
    # Lowercase, replace non-alphanumeric runs with single hyphens, strip edges
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    return slug


def safe_filename(name: str) -> str:
    """
    Sanitize a chemical name for use as a filename.

    Replaces non-alphanumeric characters (except spaces, hyphens, and
    underscores) with underscores.  Used when building download filenames
    for exported reports (the Overleaf .zip bundle).

    Args:
        name: The chemical name (e.g., "1,2-Dichlorobenzene").

    Returns:
        A filesystem-safe string (e.g., "1_2-Dichlorobenzene").
    """
    return "".join(c if c.isalnum() or c in " -_" else "_" for c in name)


# The singleton report-section files (one per session), distinct from the
# instance families discovered by glob. This is the SAME vocabulary as
# workflow.store.DiskPoolStore._BARE_SECTION_STEMS and the section catalog's
# singletons; kept here too because the reprocess/invalidate paths need the file
# stems (to write them back via save_section) without importing the workflow store.
# Fallback ONLY if the catalog cannot be imported (it should always be importable
# at call time; the import is function-local to keep session_store a low-level
# module). The catalog is the source of truth for which singleton sections exist.
_FALLBACK_SINGLETON_STEMS: tuple[str, ...] = (
    "background", "methods", "bmd_summary", "summary",
)


def singleton_section_stems() -> tuple[str, ...]:
    """The singleton report-section file stems, DERIVED from the section catalog
    (workflow.section_catalog.singleton_section_files → strip ".json"). One
    vocabulary for every consumer: reprocess/invalidate loops, the pool store's
    section readers, readiness seeding, reset. Adding a singleton to the template
    adds it everywhere."""
    try:
        from workflow.section_catalog import singleton_section_files
        return tuple(f[:-5] if f.endswith(".json") else f for f in singleton_section_files())
    except Exception:  # pragma: no cover — import failure would be a packaging bug
        return _FALLBACK_SINGLETON_STEMS


def iter_section_files(session_dir: "Path"):
    """Yield (stem, path) for every report-section JSON file in a session dir.

    The single authoritative "which files are report sections" rule: the four
    singleton sections (background/methods/bmd_summary/summary) plus the instance
    families (bm2_*, genomics_*) discovered by glob. Existence-filtered — only
    files actually on disk are yielded. Shared by the reprocess/invalidate loops
    so their section enumeration can never again drift from a hand-kept glob
    (the F4 bug: the loops globbed only bm2_*/genomics_* and silently skipped the
    singleton LLM sections, so a reprocess never demoted summary/background/etc.).
    """
    for stem in singleton_section_stems():
        p = session_dir / f"{stem}.json"
        if p.exists():
            yield stem, p
    for pattern in ("bm2_*.json", "genomics_*.json"):
        for p in sorted(session_dir.glob(pattern)):
            yield p.stem, p


# ---------------------------------------------------------------------------
# Section persistence — write/read/delete session JSON files
# ---------------------------------------------------------------------------

# A section key becomes a file name under sessions/<id>/ and a directory under
# history/. Which keys a report HAS is the section catalog's business
# (workflow.section_writes); this is only the path gate, the second layer
# behind it, so no caller can build a path out of the session from a key.
_SECTION_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,200}$")


class InvalidSectionKey(ValueError):
    """A section key that cannot name a file in the session directory."""


def validate_section_key(section_key) -> str:
    """Return ``section_key`` unchanged if it can name a section file, else
    raise InvalidSectionKey (no separator, no dot, nothing empty)."""
    if not isinstance(section_key, str) or not _SECTION_KEY_RE.match(section_key):
        raise InvalidSectionKey(f"Invalid section key: {str(section_key)[:40]!r}")
    return section_key


def _history_dir(dtxsid: str, section_key: str) -> Path:
    return SESSIONS_DIR / validate_dtxsid(dtxsid) / "history" / validate_section_key(section_key)


def _read_dict(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def list_archived(dtxsid: str, section_key: str) -> list[tuple[str, dict]]:
    """Every archived version of a section, as (archive file name, content),
    oldest first. Archives written since C2 are named ``v{version:04d}-{ts}.json``
    and so sort by version then time; older ones are named after a timestamp.
    Both are read the same way: the version is the ``version`` the content
    carries, and the list is ordered by it (then by name, which for the new
    names is the time). Unreadable archives are skipped."""
    hist = _history_dir(dtxsid, section_key)
    if not hist.is_dir():
        return []
    found = []
    for f in hist.glob("*.json"):
        data = _read_dict(f)
        if data is not None:
            v = data.get("version")
            found.append((v if isinstance(v, int) else 0, f.name, data))
    found.sort(key=lambda t: (t[0], t[1]))
    return [(name, data) for _v, name, data in found]


def read_archived(dtxsid: str, section_key: str, version: int) -> tuple[str, dict] | None:
    """The archived content of one version, as (archive file name, content), or
    None when no archive holds it. When a version was archived twice (the
    approved text, then the same version knocked down), the latest wins."""
    match = None
    for name, data in list_archived(dtxsid, section_key):
        if data.get("version") == version:
            match = (name, data)
    return match


def next_section_version(dtxsid: str, section_key: str) -> int:
    """The number the next new version of a section gets: one above every
    version already seen, in the current file, the archives and the version
    events. Monotonic: a discard or an old archive-name collision never makes a
    number come round again (a restarted counter would make the version events
    describe the wrong text)."""
    seen = [0]
    current = _read_dict(SESSIONS_DIR / validate_dtxsid(dtxsid) / f"{validate_section_key(section_key)}.json")
    if current is not None and isinstance(current.get("version"), int):
        seen.append(current["version"])
    seen += [d.get("version") for _n, d in list_archived(dtxsid, section_key)
             if isinstance(d.get("version"), int)]
    seen += [e.get("version") for e in read_version_history(dtxsid, section_key)
             if isinstance(e.get("version"), int)]
    return max(seen) + 1


def _write_archive(history_dir: Path, content: dict) -> str:
    """Write one archive under a name no other archive can take, and return the
    name: the archived content's own version, then the time to the microsecond,
    then a counter should two archives of one version land in one microsecond."""
    history_dir.mkdir(parents=True, exist_ok=True)
    version = content.get("version") if isinstance(content.get("version"), int) else 0
    stem = f"v{version:04d}-{now_iso().replace(':', '-')}"
    name, n = f"{stem}.json", 1
    while (history_dir / name).exists():
        n += 1
        name = f"{stem}-{n}.json"
    (history_dir / name).write_text(json.dumps(content, indent=2, default=str), encoding="utf-8")
    return name


def archive_current(dtxsid: str, section_key: str) -> str | None:
    """Copy a section's current file into its history, unchanged, and return the
    archive's file name; None when there is no current file. Used before a
    discard or a reset deletes the file, and by the write gate before it
    replaces it, so every version's text stays retrievable."""
    current = SESSIONS_DIR / validate_dtxsid(dtxsid) / f"{validate_section_key(section_key)}.json"
    if not current.exists():
        return None
    data = json.loads(current.read_text(encoding="utf-8"))
    return _write_archive(_history_dir(dtxsid, section_key), data)


def archive_document(dtxsid: str, history_key: str, content: dict) -> tuple[str, int]:
    """Archive a document that is not (yet) a section file under
    ``history/<history_key>/`` as that key's next version (the genomics
    narrative overrides, until C9 makes them section files). Returns
    (archive file name, version)."""
    version = next_section_version(dtxsid, history_key)
    name = _write_archive(_history_dir(dtxsid, history_key), {**content, "version": version})
    return name, version


def append_version_event(dtxsid: str, section_key: str, version: int, event: dict) -> None:
    """Append one line to a section's version events without writing the
    section (a hold, a discard). Same line format as save_section's."""
    _record_version_event(_history_dir(dtxsid, section_key), version, dict(event))


def save_section(
    dtxsid: str,
    section_key: str,
    data: dict,
    archive: bool = True,
) -> None:
    """
    Write data as JSON to sessions/{dtxsid}/{section_key}.json.

    By default ('archive=True'), the previous version is copied into
    history/ before being overwritten and the new save gets an
    incremented version number — appropriate for approve actions and
    significant content updates.

    Pass 'archive=False' for in-place updates that should NOT create a
    new history entry (e.g., flipping the 'approved' flag, auto-save
    on generation).  In that mode the existing version number is
    preserved and no history file is written.

    Cause-tagged versions (Phase 4): a caller may stamp a transient
    '_version_event' = {"cause", "status"} onto `data` to record WHY this
    version came to be — "edit" (a human accepted) born "blessed", or
    "reprocess" (the system rewrote on new data) born "needs-re-bless".
    save_section pops that marker (it never persists in the section JSON)
    and appends one line to the section's version manifest for the version it
    just wrote.  With archive=False the version number is preserved, so a
    re-accept records a status flip (needs-re-bless → blessed) against the SAME
    version rather than minting a new one.  No marker → no manifest write, so
    unmarked callers (auto-save, unapprove, restore) are byte-unaffected.

    Version history layout:
        sessions/{dtxsid}/history/{section_key}/v{version:04d}-{ts}.json — versions
        sessions/{dtxsid}/history/{section_key}/index.jsonl             — cause log

    The version number is monotonic (next_section_version): one above every
    version the section has had, so it never repeats after a discard.
    The current file ({section_key}.json) is always the latest version.
    """
    # Pull the transient cause marker off `data` before anything is written so
    # it never lands in the persisted section JSON (or an archived copy).
    version_event = data.pop(_VERSION_EVENT_KEY, None)

    validate_section_key(section_key)
    d = session_dir(dtxsid)
    current_path = d / f"{section_key}.json"
    history_dir = d / "history" / section_key

    archived_name = None
    prior_version = None
    if archive:
        # --- Archive the current version before overwriting (if it exists) ---
        # Under a name no other archive can take (its own version, then the
        # time): naming archives after `approved_at` made a later version
        # overwrite an earlier one's archive (the version keeps its approved_at
        # through an invalidation). First-ever save has nothing to archive.
        if current_path.exists():
            existing = json.loads(current_path.read_text(encoding="utf-8"))
            prior_version = existing.get("version")
            archived_name = _write_archive(history_dir, existing)

        # --- The version number for this new save: one above every version
        # seen (current file, archives, version events), never a count of the
        # archives, which restarts after a discard.
        data["version"] = next_section_version(dtxsid, section_key)
    else:
        # In-place update: keep the version number from the prior file if
        # one exists; otherwise the next number.  No history entry written.
        if current_path.exists():
            try:
                existing = json.loads(current_path.read_text(encoding="utf-8"))
                prior_version = existing.get("version")
                data.setdefault("version", existing.get("version", 1))
            except (json.JSONDecodeError, OSError):
                data.setdefault("version", next_section_version(dtxsid, section_key))
        else:
            data.setdefault("version", next_section_version(dtxsid, section_key))

    # --- Write the new version as the canonical current file ---
    current_path.write_text(
        json.dumps(data, indent=2, default=str), encoding="utf-8",
    )

    # Touch meta.json's updated_at
    meta_path = d / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    else:
        meta = {"dtxsid": dtxsid, "created_at": now_iso()}
    meta["updated_at"] = now_iso()
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    # --- Cause-tagged version event (Phase 4) ---
    # Best-effort: a manifest failure must never undo the content write above
    # (invalidate_pool_artifacts relies on the stale flip persisting even if the
    # audit line can't be appended — the caller's try/except is the outer net,
    # this is the inner one).
    if version_event:
        if archived_name:
            version_event.setdefault("archived", archived_name)
            version_event.setdefault("prior_version", prior_version)
        _record_version_event(
            history_dir, data.get("version", 1), version_event,
        )


def _record_version_event(history_dir: Path, version: int, event: dict) -> None:
    """Append one cause-tagged line to the section's version manifest.

    `event` is the caller's {"cause", "status", reason?, …} intent (the format-2
    fields of workflow.section_writes ride along as given); the line also
    carries the version number it describes and a fresh timestamp.  A `reason`
    (the human's free-text for a "revise", or the auto reason for a currency
    down-step) is recorded only when non-empty, so entries without one stay
    byte-identical to pre-reason manifests.  Append-only: the manifest is a
    timeline, so a re-accept adds a new line for the same version (status changes;
    the current status is the most-recent line for that version) rather than
    editing an earlier one.  Fully fail-soft — never raises."""
    try:
        history_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "version": version,
            "cause": event.get("cause", "unknown"),
            "status": event.get("status", "unknown"),
            "ts": now_iso(),
        }
        reason = event.get("reason")
        if reason:
            entry["reason"] = reason
        # Format 2 (C2): who did what, written by whom, to which version
        # (workflow.section_writes). Carried as the caller gives them.
        for key, value in event.items():
            if key not in ("cause", "status", "reason", "version", "ts"):
                entry[key] = value
        with (history_dir / _VERSION_INDEX).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception as e:  # pragma: no cover — defensive, audit must not abort work
        logger.warning(
            "Failed to record version event for %s: %s", history_dir, e,
        )


def read_version_history(dtxsid: str, section_key: str) -> list[dict]:
    """Return the cause-tagged version events for a section, oldest first.

    Parses history/{section_key}/index.jsonl into a list of
    {version, cause, status, ts} dicts.  Returns [] when no manifest exists
    (old, pre-Phase-4 sessions, or a section that never minted a tagged version)
    — a section with only un-tagged archives is not an error.  Corrupt lines are
    skipped, never raised."""
    idx = _history_dir(dtxsid, section_key) / _VERSION_INDEX
    if not idx.exists():
        return []
    events: list[dict] = []
    try:
        lines = idx.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # tolerate a partially-written line
    return events


def current_version_status(dtxsid: str, section_key: str) -> str | None:
    """The status of the section's CURRENT version, from the manifest.

    Reads the current file's version number, then returns the status of the most
    recent manifest event for that version (last line wins — a reprocess's
    needs-re-bless is superseded by a later re-accept's blessed against the same
    version).  None when the section or its manifest is absent, or the current
    version was never tagged (missing cause = unknown provenance, not a crash)."""
    current = SESSIONS_DIR / validate_dtxsid(dtxsid) / f"{validate_section_key(section_key)}.json"
    if not current.exists():
        return None
    try:
        version = json.loads(current.read_text(encoding="utf-8")).get("version", 1)
    except (json.JSONDecodeError, OSError):
        return None
    status = None
    for event in read_version_history(dtxsid, section_key):
        if event.get("version") == version:
            status = event.get("status")  # append order → last match is current
    return status


def delete_section(dtxsid: str, section_key: str) -> None:
    """
    Remove sessions/{dtxsid}/{section_key}.json if it exists.

    A primitive: only the gate's discard (workflow.section_writes, which
    archives the file first) and the resets call it. The .bm2 file in files/
    is kept — it's still useful for reprocessing.
    """
    d = SESSIONS_DIR / validate_dtxsid(dtxsid)
    section_path = d / f"{validate_section_key(section_key)}.json"
    if section_path.exists():
        section_path.unlink()
