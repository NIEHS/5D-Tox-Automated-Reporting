"""
workflow.read_model — one study's derived state, in one read (MODULES.md §4.1).

The new interface learns everything about a study's workflow from this one read
model (``GET /api/v2/studies/{id}/state``; the command line and the notebook can
call ``study_state`` directly). It composes what the core already derives:

  * what kind of session it is (a study, a report over several studies, a
    member of one, a published book's companion), the chemical it is about and
    its relations, and where it stands with the next step (``stands``): the
    derivations of workflow.studies, the same the studies list serves;
  * the phase and its legal actions (``WorkflowEngine.state``);
  * the identity (``identity.json``; the abbreviation is the short name);
  * the two pins: the method profile (``pipeline.method_profile``: the pin, the
    deviations, the LIVE mismatches between the dataset's recorded analyses and
    the profile, and, until a person has chosen one, the ``suggestion`` to
    propose) and the document definition (``document_model.definition_pin``:
    the pin, its drift, and which definition renders);
  * whether the study was processed;
  * the sections: the catalog of the tree that renders, the readiness, and per
    section what is on disk (approved, facts, maturity, stale, regenerated,
    wording_review, review, source, version, the version's status, the machine
    guard: workflow.ownership, C2);
  * the publish readiness (``WorkflowEngine.publish_readiness``) as a checklist,
    with what it checked (``checks``) and whether that is everything publishing
    needs (``complete``: not until C6);
  * for a report over several studies (``studies.json``), each member's publish
    readiness, side by side (not folded into the report's verdict: that is C6).

Everything is derived on every call; nothing here is stored (CONTEXT.md
invariant 3). What the core cannot derive yet (the data-approval checklist, the
run record) is ABSENT from the result, never guessed.

**No side effects.** Reading the state must not change the study: no session
folder created (``session_store.session_dir`` creates one), no fingerprints
re-scanned or file ids minted, no upload registered, nothing pinned, no machine
check run (the BMDS 2.7 availability check starts Wine). So the store is
``ReadOnlyDiskPoolStore``, the pins are read and never ensured, and the method is
resolved with ``probe=False``. A study that does not exist reads as
``{"id": …, "exists": false}``.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from workflow.store import DiskPoolStore, PoolStore

logger = logging.getLogger(__name__)


class ReadOnlyStoreError(RuntimeError):
    """A write was attempted through the read-only store."""


class ReadOnlyDiskPoolStore(DiskPoolStore):
    """``DiskPoolStore`` for reads that must leave no trace: the session folder
    is located, never created, and every state-changing method refuses."""

    def session_dir(self, dtxsid: str) -> Path:
        from pipeline.session_store import session_path
        return session_path(dtxsid)

    def _refuse(self, *_args, **_kwargs):
        raise ReadOnlyStoreError("the read model's store is read-only")

    # Fingerprint scans mint file ids; the rest write.
    ensure_fingerprints = _refuse
    set_fingerprints = _refuse
    set_integrated = _refuse
    write_json = _refuse
    save_section = _refuse
    archive_section = _refuse
    delete_section = _refuse
    record_version_event = _refuse


# ---------------------------------------------------------------------------
# Small readers
# ---------------------------------------------------------------------------

# On disk a pin records who made it as "user" or "default"; the interface says
# "person" (MODULES.md §4.1). Anything else passes through as recorded.
_PINNED_BY = {"user": "person", "default": "default"}


def _read_json(path: Path):
    """A session JSON document: None when absent; UnreadableSessionFile when it
    exists but cannot be parsed (never silently empty)."""
    from common.session_files import read_json_file
    return read_json_file(path)


def _identity(session: Path) -> dict | None:
    """The test article as stated (identity.json), None when never written.
    A value the file does not hold is None: not stated, not guessed."""
    raw = _read_json(session / "identity.json")
    if not isinstance(raw, dict):
        return None
    return {"name": raw.get("name"), "casrn": raw.get("casrn"),
            "dtxsid": raw.get("dtxsid"), "short_name": raw.get("abbreviation")}


# ---------------------------------------------------------------------------
# The method pin
# ---------------------------------------------------------------------------

# Live mismatches need the dataset's recorded analyses, so integrated.json
# (tens of MB). The result is memoized per process on what it depends on: the
# file's identity (path, mtime, size) and the resolved method's signature. A
# re-integration or a re-pin changes the key. Small: one entry per study.
_MISMATCH_MEMO: dict[tuple, list] = {}
_MISMATCH_LOCK = threading.Lock()
_MISMATCH_MEMO_MAX = 32


def _live_mismatches(integrated_path: Path, settings) -> list[dict]:
    """Where the dataset's recorded analyses disagree with the method the study
    resolves to now (pipeline.method_profile.recorded_mismatches), [] when the
    study has no dataset yet (nothing recorded to disagree)."""
    if not integrated_path.is_file():
        return []
    st = integrated_path.stat()
    key = (str(integrated_path), st.st_mtime_ns, st.st_size, settings.profile,
           settings.signature())
    with _MISMATCH_LOCK:
        if key in _MISMATCH_MEMO:
            return _MISMATCH_MEMO[key]
    from pipeline.method_profile import recorded_mismatches
    integrated = _read_json(integrated_path)
    result = recorded_mismatches(integrated if isinstance(integrated, dict) else {}, settings)
    with _MISMATCH_LOCK:
        if len(_MISMATCH_MEMO) >= _MISMATCH_MEMO_MAX:
            _MISMATCH_MEMO.clear()
        _MISMATCH_MEMO[key] = result
    return result


def method_pin_state(dtxsid: str, session: Path) -> dict:
    """The study's method profile: the pin (or none), the deviations the
    resolved method carries, what could not be checked without running a
    machine check, and the live mismatches with the recorded analyses.

    A profile that no longer resolves (edited after pinning, missing) is reported
    as ``error`` (the §4.2 envelope's body), and its deviations and mismatches
    are absent."""
    from pipeline import method_profile as mp
    from workflow.refusals import explain

    try:
        pin = mp.read_pin(dtxsid)
    except ValueError as exc:  # a damaged pin file is a damaged session file
        from common.session_files import UnreadableSessionFile
        raise UnreadableSessionFile(session / mp.PIN_FILE, exc) from exc
    out: dict = {
        "pinned": bool(pin),
        "name": (pin or {}).get("name"),
        "hash": (pin or {}).get("hash"),
        "series": (pin or {}).get("series"),
        "mode": mp.pin_mode(pin) if pin else None,
        "pinned_by": _PINNED_BY.get((pin or {}).get("pinned_by"), (pin or {}).get("pinned_by")),
        "pinned_at": (pin or {}).get("pinned_at"),
    }
    try:
        settings = mp.session_method(dtxsid, probe=False)
    except mp.MethodProfileError as exc:
        out["error"] = explain(exc)["error"]
        return out
    out["deviations"] = list(settings.deviations)
    out["unchecked"] = list(settings.unchecked)
    out["mismatches"] = _live_mismatches(session / "integrated.json", settings)
    if not mp.chosen_by_person(pin):
        # C1 D1: Process waits for a person's choice; the interface (M5)
        # proposes this one and the person confirms it.
        out["suggestion"] = _method_suggestion(dtxsid, session)
    return out


def _method_suggestion(dtxsid: str, session: Path) -> dict | None:
    """``{name, why}``: the profile to propose (pipeline.method_profile.
    suggest_profile), comparing each candidate with the dataset through the
    memoized live mismatches. None when no profile can be suggested."""
    from pipeline import method_profile as mp

    integrated = session / "integrated.json"
    if not integrated.is_file():
        def count(settings):               # no dataset: nothing recorded to compare
            return None
    else:
        def count(settings):
            return len(_live_mismatches(integrated, settings))
    try:
        return mp.suggest_profile(dtxsid, count_mismatches=count)
    except mp.MethodProfileError as exc:
        logger.warning("No method profile to suggest for %s: %s", dtxsid, exc)
        return None


# ---------------------------------------------------------------------------
# The document definition, and the tree that renders
# ---------------------------------------------------------------------------

def _definition_source(dtxsid: str, name: str) -> str:
    """Which declaration gives the report its structure: the session's own
    document.yaml, the study's definition, an era's, or another template."""
    from document_model.document_config import session_document_path
    if session_document_path(dtxsid).is_file():
        return "session"
    if name.startswith("studies/"):
        return "study"
    if name.startswith("eras/"):
        return "era"
    return "template"


def definition_pin_state(dtxsid: str, session: Path) -> dict:
    """The study's document definition: which one renders, from where, the pin
    (or none), and how the files have drifted from a FIXED pin."""
    from document_model import definition_pin as dp
    from document_model.document_definition import current_definition_name
    from workflow.refusals import explain

    try:
        pin = dp.read_pin(dtxsid)
    except ValueError as exc:
        from common.session_files import UnreadableSessionFile
        raise UnreadableSessionFile(session / dp.PIN_FILE, exc) from exc
    fixed = bool(pin) and pin.get("mode") == dp.FIXED
    name = pin.get("name") if fixed else current_definition_name(dtxsid)
    out: dict = {
        "pinned": bool(pin),
        "name": name,
        "hash": (pin or {}).get("hash"),
        "mode": (pin or {}).get("mode"),
        "pinned_by": _PINNED_BY.get((pin or {}).get("pinned_by"), (pin or {}).get("pinned_by")),
        "pinned_at": (pin or {}).get("pinned_at"),
        "source": _definition_source(dtxsid, name or ""),
        # A FIXED study renders from the composed copy saved with its pin.
        "snapshot": fixed,
    }
    try:
        out["drift"] = dp.drift(dtxsid)
    except Exception as exc:  # noqa: BLE001 — reported, not swallowed
        out["error"] = explain(exc)["error"]
    return out


def _rendering_catalog(dtxsid: str) -> tuple[list, list | None, dict | None]:
    """(catalog, tree, error): the workflow catalog of the tree the report
    renders from (the view tree: a session document.yaml, else the study's
    definition, pinned or current), in its document order. When that tree
    cannot be built, the workflow's own catalog (catalog_for_session) and the
    reason, so the sections still list and the reason is shown."""
    from workflow.refusals import explain
    from workflow.section_catalog import catalog_for_session, catalog_for_tree

    try:
        from document_model.view_config import build_view_tree
        tree = build_view_tree(dtxsid, "")
        return catalog_for_tree(tree), tree, None
    except Exception as exc:  # noqa: BLE001 — reported on pins.definition
        return catalog_for_session(dtxsid), None, explain(exc)["error"]


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def _family_of(key: str) -> str:
    if key.startswith("bm2_"):
        return "bm2"
    if key.startswith("genomics_"):
        return "genomics"
    return key


def _node_titles(tree) -> dict[str, str]:
    """{node id: title} of a tree, for the sections' display titles."""
    if not tree:
        return {}
    from document_model.document_tree import walk_tree
    titles: dict[str, str] = {}
    walk_tree(tree, lambda n: titles.setdefault(n.id, n.title) if getattr(n, "title", None) else None)
    return titles


def _interpretation_instances(session: Path) -> list[str]:
    """genomics_<organ>_<sex> keys whose interpretation exists only in the
    Process cache (_cache_interpretation_<organ>_<sex>_<hash>.json): no section
    file, but report content a person reads."""
    keys = set()
    for p in session.glob("_cache_interpretation_*.json"):
        organ_sex = p.stem.removeprefix("_cache_interpretation_").rsplit("_", 1)[0]
        if organ_sex:
            keys.add(f"genomics_{organ_sex}")
    return sorted(keys)


# Why a section cannot be accepted now, in the order they are checked. The
# unlock groups of workflow.section_catalog.KIND_UNLOCK, in plain words.
_UNLOCK_SAY = {
    "processed": "the study has been processed",
    "knowledge_base": "the knowledge base is available",
    "background": "the Background is approved",
    "results": "at least one result section is approved",
}
# Why a section is not approved on its own, by who writes it (the catalog's kind).
_NOT_APPROVABLE_SAY = {
    "authored": ("This is supplied or standard text, not text the application writes, so "
                 "it is not approved here."),
    "llm": ("This text can't be approved yet: it is kept only with the Process results, "
            "not as a section of its own."),
    "programmatic": ("This text is built from the data by the program and shown with its "
                     "tables; it is not approved on its own."),
}
_NOT_APPROVABLE_DEFAULT = "This part of the report is not approved on its own."
# A section with no saved text has nothing to accept (accept_section_step
# refuses it). Methods and the apical BMD summary are approvable in the catalog
# but are never saved as sections today (their text lives only in the Process
# cache, MODULES.md C9), so for them it is not "not yet written".
_CACHE_ONLY_KEYS = frozenset({"methods", "bmd_summary"})
_CACHE_ONLY_SAY = ("This section can't be approved yet: its text is kept only with the "
                   "Process results, not as a section of its own.")
_NO_SAVED_TEXT_SAY = "There is no text for this section yet, so there is nothing to approve."


_ALREADY_ACCEPTED_SAY = "This section is already accepted and nothing has changed since."


def _accept_verdict(key: str, kind: str, approvable: bool, enabled: bool, blocked_by: list[str],
                    has_file: bool, accepted: bool = False) -> dict:
    """Whether a person may accept (approve) the section now, and if not, why:
    ``{"allowed", "code", "say"}``. Derived from the catalog (kind, approvable),
    the readiness (enabled, blocked_by) and whether there is a saved text to
    accept (accept_section_step refuses a section with no file). The interface
    offers "approve" only when ``allowed``, and shows ``say`` otherwise."""
    if not approvable:
        return {"allowed": False, "code": "not_approvable",
                "say": _NOT_APPROVABLE_SAY.get(kind, _NOT_APPROVABLE_DEFAULT)}
    if not enabled:
        waits = " or ".join(_UNLOCK_SAY.get(g, g) for g in blocked_by) or "what it depends on is ready"
        return {"allowed": False, "code": "blocked",
                "say": f"This section can be approved only once {waits}."}
    if not has_file:
        if key in _CACHE_ONLY_KEYS:
            return {"allowed": False, "code": "not_saved_as_section", "say": _CACHE_ONLY_SAY}
        return {"allowed": False, "code": "no_saved_text", "say": _NO_SAVED_TEXT_SAY}
    if accepted:
        # accept_section_step would change nothing (C2: noop already_accepted).
        # A section under review, stale, or approved under an unrecorded
        # status IS acceptable: accepting answers it.
        return {"allowed": False, "code": "already_accepted", "say": _ALREADY_ACCEPTED_SAY}
    return {"allowed": True, "code": None, "say": None}


def _regenerated(raw) -> dict | None:
    """Why the machine rewrote a section, as recorded (``{"reason": code}``,
    pipeline.pool_state), with the plain words for that reason (``say``): the
    interface shows ``say`` and never the code. None when it was not rewritten."""
    if not isinstance(raw, dict):
        return None
    reason = raw.get("reason")
    return {**raw, "say": _STALE_SAY.get(reason, _STALE_SAY_DEFAULT)}


def _maturity(d: dict | None) -> str | None:
    """The section's maturity rung (workflow.labels): "final", "working_draft",
    "first_draft", or None when it holds none."""
    from workflow.labels import maturity_rung
    from workflow.ownership import section_facts
    rung = maturity_rung(section_facts(d))
    return rung.value if rung is not None else None


def _review(raw) -> dict | None:
    """Why an approved section's printed content changed under it (C2 D2/A1:
    ``{why, since_version, flips}``), with the plain words (``say``). None
    when there is no such marker."""
    if not isinstance(raw, dict):
        return None
    return {**raw, "say": _REVIEW_SAY.get(raw.get("why"), _REVIEW_SAY_DEFAULT)}


_REVIEW_SAY = {
    "numbers_changed": ("The study's data changed the numbers this section prints since it "
                        "was approved. Read it again, then approve it again."),
    "wording_changed": ("The study's data changed words this section's text depends on since "
                        "it was approved. Read it again, then approve it again."),
}
_REVIEW_SAY_DEFAULT = "This section changed since it was approved. Read it again, then approve it again."


def _section_row(dtxsid: str, key: str, spec, section: dict | None, readiness: dict,
                 title: str | None) -> dict:
    """One section as the interface sees it: the catalog's identity, the
    readiness, and what its file on disk says (nothing, when it has none)."""
    from pipeline.session_store import current_version_status
    from workflow.ownership import may_machine_write, section_facts
    from workflow.section_writes import already_accepted

    r = readiness.get(key, {})
    d = section if isinstance(section, dict) else None
    regenerated = (d or {}).get("regenerated")
    wording = (d or {}).get("wording_review")
    status = current_version_status(dtxsid, key) if d else None
    return {
        "key": key,
        "title": (d or {}).get("title") or title,
        "kind": spec.kind,
        "approvable": spec.approvable,
        "instance_of": spec.instance_of,
        "region": spec.region,
        "has_file": d is not None,
        "enabled": r.get("enabled", True),
        "blocked_by": list(r.get("blocked_by", [])),
        "approved": bool((d or {}).get("approved")),
        "facts": sorted(f.value for f in section_facts(d)),
        "user_edited": bool((d or {}).get("user_edited")),
        "stale": bool((d or {}).get("stale")),
        "regenerated": _regenerated(regenerated),
        "wording_review": list(wording) if isinstance(wording, list) else [],
        "source": (d or {}).get("source"),
        "model": (d or {}).get("model_used"),
        "version": (d or {}).get("version") if d else None,
        "version_status": status,
        "maturity": _maturity(d),
        "review": _review((d or {}).get("review")),
        "machine_may_write": may_machine_write(d),
        "accept": _accept_verdict(key, spec.kind, spec.approvable, r.get("enabled", True),
                                  list(r.get("blocked_by", [])), d is not None,
                                  already_accepted(d, status)),
    }


def sections_state(dtxsid: str, engine, store: PoolStore, session: Path,
                   catalog: list, tree) -> list[dict]:
    """Every section of the report, in the rendering tree's document order: the
    singletons and group narratives from the catalog, and each instance family
    (bm2_*, genomics_*) replaced by its instances on disk (genomics also by
    the interpretations that exist only in the Process cache)."""
    dicts = store.read_section_dicts(dtxsid)
    states = {k: bool(v.get("approved")) for k, v in dicts.items()}
    readiness = engine.derive_section_readiness(section_states=states, catalog=catalog)
    titles = _node_titles(tree)

    instances: dict[str, list[str]] = {"bm2": [], "genomics": []}
    for key in sorted(dicts):
        fam = _family_of(key)
        if fam in instances:
            instances[fam].append(key)
    for key in _interpretation_instances(session):
        if key not in instances["genomics"]:
            instances["genomics"].append(key)
    instances["genomics"].sort()

    rows: list[dict] = []
    for spec in catalog:
        if spec.instance_of is None:
            title = next((titles[n] for n in spec.node_ids if n in titles), None)
            rows.append(_section_row(dtxsid, spec.key, spec, dicts.get(spec.key), readiness, title))
        else:
            for key in instances.get(spec.instance_of, []):
                rows.append(_section_row(dtxsid, key, spec, dicts.get(key), readiness, None))
    return rows


# ---------------------------------------------------------------------------
# Publish readiness as a checklist
# ---------------------------------------------------------------------------

# What the publish verdict covers today (WorkflowEngine.publish_readiness): only
# the LLM sections a data change left stale. Served so the interface can say what
# "ready" has and has not checked; C6 adds the rest.
PUBLISH_CHECKS: dict[str, str] = {
    "stale_llm_sections": ("Whether any section written by the language model is out of "
                           "date with the study's data."),
}

# Whether PUBLISH_CHECKS is everything publishing needs. It is not, until C6
# (unapproved sections, pending placeholders, member studies, pins and
# deviations are not checked). While it is False, ``ready`` means only "nothing
# found by these checks", and the interface must never say "ready to publish".
PUBLISH_CHECKS_COMPLETE = False

_STALE_SAY = {
    "data_changed": ("The study's data changed after this section was written. Read it "
                     "again against the current data, then approve it again."),
}
_STALE_SAY_DEFAULT = ("This section is out of date with the study's data. Read it again, "
                      "then approve it again.")


def publish_readiness_state(engine) -> dict:
    """``publish_readiness()`` as the checklist the interface shows: one block
    item per stale LLM section, each saying why and where it is cleared."""
    verdict = engine.publish_readiness()
    items = [{
        "id": "section.stale",
        "level": "block",
        "section": b["section_key"],
        "reason": b.get("reason"),
        "say": _STALE_SAY.get(b.get("reason"), _STALE_SAY_DEFAULT),
        "fix": "D1",
    } for b in verdict.get("blocking", [])]
    return {"ready": bool(verdict.get("can_publish")), "complete": PUBLISH_CHECKS_COMPLETE,
            "checks": [{"id": k, "say": v} for k, v in PUBLISH_CHECKS.items()],
            "items": items}


def members_state(dtxsid: str, store: PoolStore) -> list[dict] | None:
    """For a report over several studies: each member study (studies.json, in
    its order), whether it exists, its phase and its own publish readiness.
    None for a single-study session."""
    from common.dtxsid import is_valid_dtxsid
    from rendering.report_compose import member_sessions
    from workflow.engine import WorkflowEngine, _is_processed

    members = member_sessions(dtxsid)
    if not members:
        return None
    out = []
    for key, member_id in members:
        entry: dict = {"key": key, "id": member_id}
        if not is_valid_dtxsid(member_id) or not store.session_dir(member_id).is_dir():
            entry["exists"] = False
        else:
            engine = WorkflowEngine(member_id, store)
            entry["exists"] = True
            entry["phase"] = engine.state().phase.value
            entry["processed"] = _is_processed(store.session_dir(member_id))
            entry["readiness"] = {
                "publish": publish_readiness_state(engine)}
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# What kind of session this is (one derivation, workflow.studies)
# ---------------------------------------------------------------------------

def session_kind(dtxsid: str, sessions_root: Path) -> dict:
    """What the session is and the sessions it belongs with: the derivation of
    ``workflow.studies.session_kind`` (the M1 contract §3), kept importable here.
    ``{"kind", "chemical_dtxsid", "chemical_dtxsid_from", "relations"}``."""
    from workflow.studies import session_kind as derive
    return derive(dtxsid, sessions_root)


# ---------------------------------------------------------------------------
# The read model
# ---------------------------------------------------------------------------

def study_state(dtxsid: str, store: PoolStore | None = None) -> dict:
    """One study's derived state (MODULES.md §4.1), read without side effects.

    Raises InvalidDtxsid for a malformed id and UnreadableSessionFile for a
    damaged identity or pin file (the §4.2 envelope explains both). The
    default store is ``ReadOnlyDiskPoolStore``; a caller passing its own store
    answers for that store's side effects.
    """
    from common.dtxsid import validate_dtxsid
    from workflow.engine import WorkflowEngine, _is_processed
    from workflow.studies import stands

    validate_dtxsid(dtxsid)
    store = store if store is not None else ReadOnlyDiskPoolStore()
    session = store.session_dir(dtxsid)
    if not session.is_dir():
        return {"id": dtxsid, "exists": False}

    engine = WorkflowEngine(dtxsid, store)
    wf = engine.state()
    catalog, tree, tree_error = _rendering_catalog(dtxsid)
    definition = definition_pin_state(dtxsid, session)
    if tree_error is not None and "error" not in definition:
        definition["error"] = tree_error

    state: dict = {
        "id": dtxsid,
        "exists": True,
        **session_kind(dtxsid, session.parent),
        "phase": wf.phase.value,
        "legal_actions": sorted(a.value for a in wf.legal_actions),
        "identity": _identity(session),
        "pins": {"method": method_pin_state(dtxsid, session), "definition": definition},
        "processed": _is_processed(session),
        "sections": sections_state(dtxsid, engine, store, session, catalog, tree),
        "readiness": {"publish": publish_readiness_state(engine)},
    }
    members = members_state(dtxsid, store)
    if members is not None:
        state["members"] = members
    state["stands"] = stands(state["kind"], state["phase"], state["processed"],
                             member_states=members, publish=state["readiness"]["publish"])
    return state


def to_json(state: dict) -> str:
    """The read model as JSON text (stable key order, for files and fixtures)."""
    return json.dumps(state, indent=2, ensure_ascii=False, default=str) + "\n"
