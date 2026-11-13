"""
workflow.section_writes — the one gate every write to a section file goes
through, and the section history it keeps.

Every write to a section file, a person's or a machine's, calls
``write_section``, which:

  1. refuses a key that is not a section of this report (the catalog of the
     session's document tree, workflow.section_catalog);
  2. reads the prior file;
  3. does nothing when the content is unchanged (no write, no event: a Process
     that changed nothing leaves every section file untouched);
  4–6. asks its write ``policy`` what to do over content a person owns — hold
     a machine's text, knock an apical section's approval down for re-review,
     refuse a person's unforced write, require a reason for a forced one. The
     policy is the C2 safeguard ("owned content is never overwritten by a
     machine": safeguards.sections.ownership_policy); without one every write
     is made, the prior text archived;
  7. otherwise archives the prior text and writes, and records one version event.

Rules 1–3 and 7 hold for every caller (the notebook included): nothing written
here is ever lost. Every event is one line of the section's
``history/<key>/index.jsonl`` (format 2, C2 spec §5): what (section, version),
how (cause, act), by whom (actor, user), written by (author), why (reason,
review) and whether the text changed (changed, content_hash).

The state changes on sections (accept, release, restore, discard) are the steps
in workflow.steps; they call the helpers here. ``section_history`` and
``read_version`` serve the history reads.

A core refusal here is a ``SectionRefusal`` (a StepError carrying a code that
safeguards.refusals explains).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from pipeline.session_store import _VERSION_EVENT_KEY
from workflow.errors import StepError
from workflow.ownership import STATE_KEYS, content_hash, is_owned, section_content
from workflow.store import PoolStore

logger = logging.getLogger(__name__)

# The version-event line format these writers produce (absent on older lines = 1).
EVENT_FORMAT = 2

# Who wrote a version's text, by the `source` its file carries.
_AUTHORS = frozenset({"generated", "model", "person", "ingested", "client"})


class SectionRefusal(StepError):
    """A section act the gate or a section step refuses. ``code`` is a code of
    safeguards.refusals.REFUSALS; ``details`` (key, act, version …) fill its
    plain-words text and are shown beside the message."""

    def __init__(self, code: str, message: str, status_code: int, **details):
        super().__init__(message, status_code=status_code)
        self.code = code
        self.details = {k: v for k, v in details.items() if v is not None}


# ---------------------------------------------------------------------------
# Core refusals (messages verbatim from the C2 contract)
# ---------------------------------------------------------------------------

def not_found(key: str, verb: str) -> SectionRefusal:
    return SectionRefusal("section_not_found", f"No '{key}' section to {verb}", 404,
                          key=key, act=verb)


def version_not_found(key: str, version) -> SectionRefusal:
    return SectionRefusal("version_not_found", f"Version {version} of '{key}' not found", 404,
                          key=key, version=version)


def version_content_missing(key: str, version: int) -> SectionRefusal:
    return SectionRefusal(
        "version_content_missing",
        f"Version {version} of '{key}' is recorded but its text was not kept", 409,
        key=key, version=version)


def is_locked(section: dict | None) -> bool:
    """Whether a PERSON's unforced act may not replace this section: it is
    approved, a person edited it, or its text came back from outside the
    application. A released section (approved withdrawn, PROTECTED standing) is
    owned — no machine replaces it — but not locked: a person's explicit act
    (use a run, restore, regenerate) may, archiving it first."""
    from workflow.ownership import INGESTED_SOURCE
    return isinstance(section, dict) and bool(
        section.get("approved") or section.get("user_edited")
        or section.get("source") == INGESTED_SOURCE)


def already_accepted(section: dict | None, status: str | None) -> bool:
    """Whether accepting the section would change nothing: it is approved,
    carries no stale / review / wording_review marker, and its current
    version's status is blessed. The accept step answers noop then, and the
    read model does not offer accepting."""
    return isinstance(section, dict) and bool(section.get("approved")) and not any(
        section.get(k) for k in ("stale", "review", "wording_review")) and status == "blessed"


# ---------------------------------------------------------------------------
# Rule 1: the key is a section of this report
# ---------------------------------------------------------------------------

_KEY_PART_RE = re.compile(r"^[A-Za-z0-9_-]{1,120}$")


def section_key_patterns(dtxsid: str) -> tuple[frozenset[str], tuple[str, ...]]:
    """(the singleton section keys, the instance-family key prefixes) of the
    session's catalog, read off each spec's ``store`` file pattern
    (``summary.json``; ``bm2_{slug}.json`` → ``bm2_``). Derived from the
    document tree, never listed here."""
    from workflow.section_catalog import catalog_for_session

    singles: set[str] = set()
    prefixes: list[str] = []
    for spec in catalog_for_session(dtxsid):
        if not spec.store:
            continue
        if spec.instance_of is None:
            singles.add(spec.store[:-5] if spec.store.endswith(".json") else spec.store)
        else:
            prefix = spec.store.split("{", 1)[0]
            if prefix and prefix not in prefixes:
                prefixes.append(prefix)
    return frozenset(singles), tuple(prefixes)


def validate_section_key(dtxsid: str, key) -> str:
    """Return ``key`` if it names a section of this session's report, else
    raise SectionRefusal ``section_key_invalid`` (400). A family instance's
    remainder (a slug, organ_sex) may carry no separator or dot, so the key is
    also a safe file name."""
    if isinstance(key, str) and key:
        singles, prefixes = section_key_patterns(dtxsid)
        if key in singles:
            return key
        for prefix in prefixes:
            rest = key[len(prefix):]
            if key.startswith(prefix) and _KEY_PART_RE.match(rest):
                return key
    shown = str(key)[:60] if key is not None else ""
    raise SectionRefusal("section_key_invalid", f"'{shown}' is not a section of this report",
                         400, key=shown)


# ---------------------------------------------------------------------------
# Small readers
# ---------------------------------------------------------------------------

def read_prior(dtxsid: str, key: str, store: PoolStore) -> dict | None:
    """The section's current file, None when there is none. A file that exists
    but cannot be read is an error, never "absent": the gate would otherwise
    write over it."""
    data = store.read_json(dtxsid, f"{key}.json")
    if isinstance(data, dict):
        return data
    if store.artifact_exists(dtxsid, f"{key}.json"):
        from common.session_files import UnreadableSessionFile
        raise UnreadableSessionFile(store.session_dir(dtxsid) / f"{key}.json",
                                    ValueError("not a JSON object"))
    return None


def author_of(section: dict | None) -> str | None:
    """Who wrote a section's text, as its file records it: its ``source`` when
    that is one of the author kinds, ``model`` when only a model is recorded,
    else None (not recorded; never guessed)."""
    if not isinstance(section, dict):
        return None
    source = section.get("source")
    if source in _AUTHORS:
        return source
    if section.get("model_used"):
        return "model"
    return None


def version_status(dtxsid: str, key: str, version, store: PoolStore) -> str | None:
    """The status of one version: the last event about it (append order)."""
    status = None
    for event in store.read_version_history(dtxsid, key):
        if event.get("version") == version:
            status = event.get("status")
    return status


def _status_now(dtxsid: str, key: str, section: dict, store: PoolStore) -> str:
    """The current version's status for an event that leaves it as it is (a
    hold): as recorded, else what the file says (approved → blessed; owned →
    working; else draft)."""
    recorded = version_status(dtxsid, key, section.get("version"), store)
    if recorded:
        return recorded
    if section.get("approved"):
        return "blessed"
    return "working" if is_owned(section) else "draft"


def event(*, key: str, cause: str, status: str, act: str, actor: str, author: str | None,
          prior_version, changed: bool, chash: str, reason: str | None = None,
          review: dict | None = None, applied: bool = True, extra: dict | None = None) -> dict:
    """One format-2 version event (C2 spec §5). The version and the time are
    stamped where the line is written (session_store)."""
    line = {
        "v": EVENT_FORMAT, "section": key, "cause": cause, "status": status, "act": act,
        "actor": actor, "user": None, "author": author, "prior_version": prior_version,
        "changed": changed, "content_hash": chash, "applied": applied,
    }
    if reason:
        line["reason"] = reason
    if review is not None:
        line["review"] = review
    if extra:
        line.update({k: v for k, v in extra.items() if v is not None})
    return line


def record(dtxsid: str, key: str, version: int, line: dict, store: PoolStore) -> None:
    """Append an event without writing the section (a hold, a state change, a
    discard)."""
    store.record_version_event(dtxsid, key, version, line)


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------

# What a machine does when its new text meets owned content.
HOLD = "hold"          # keep the owned text; record a hold (the default)
REVIEW = "review"      # apical result sections (C2 D2/A1): the printed content
#                        has already changed (the deliverable renders it from the
#                        Process cache), so write it, knock the approval down,
#                        and mark it for re-review with a record.


@dataclass
class WriteRequest:
    """A write to a section, as the gate sees it once it is known to change the
    text: what a write policy decides on (``policy`` of write_section)."""

    dtxsid: str
    key: str
    prior: dict | None
    content: dict
    store: PoolStore
    act: str
    actor: str
    author: str | None
    force: bool
    reason: str | None
    on_owned: str
    review: dict | None
    extra_event: dict | None
    outcome: dict


def write_section(dtxsid: str, key: str, content: dict, store: PoolStore, *, act: str,
                  actor: str, author: str | None, force: bool = False,
                  reason: str | None = None, cause: str = "generate", status: str = "draft",
                  extra_event: dict | None = None, on_owned: str = HOLD,
                  review: dict | None = None, policy=None) -> dict:
    """Write ``content`` as section ``key``, by the rules of the module
    docstring. ``actor`` is ``"person"`` (an act a person asked for) or
    ``"system"`` (Process, invalidation); ``author`` who wrote the text.

    ``policy`` decides what happens to content a person owns (rules 4–6):
    called with a WriteRequest once the write would change the text, it
    returns None (write), or the outcome it chose (``hold``, ``knock_down``),
    or raises a refusal. With no policy every write is made — the prior text is
    archived first, so nothing is lost (the notebook's unguarded core);
    safeguards.sections.ownership_policy is the C2 policy the front ends use.

    Returns ``{key, outcome, version, prior_version, archived, event}`` where
    outcome is ``written`` | ``unchanged`` | ``held`` | ``needs_review``.
    Raises SectionRefusal ``section_key_invalid``, and what the policy raises.

    ``content`` is the new file as the caller wants it (its state keys
    included); it is not mutated."""
    key = validate_section_key(dtxsid, key)
    prior = read_prior(dtxsid, key, store)
    new_hash = content_hash(content)
    prior_version = prior.get("version") if prior else None
    outcome = {"key": key, "prior_version": prior_version, "archived": None, "event": None}

    # Rule 3: nothing changed, nothing written.
    if prior is not None and content_hash(prior) == new_hash:
        return {**outcome, "outcome": "unchanged", "version": prior_version}

    data = dict(content)
    if policy is not None:
        request = WriteRequest(dtxsid, key, prior, data, store, act, actor, author, force,
                               reason, on_owned, review, extra_event, outcome)
        decided = policy(request)
        if decided is not None:
            return decided
        reason = request.reason
    forced = prior is not None and is_owned(prior) and force

    # A review marker (D2/A1) stands until a person re-accepts: a later machine
    # write over the knocked-down section keeps it.
    if actor == "system" and prior is not None and isinstance(prior.get("review"), dict):
        data.setdefault("review", prior["review"])

    # Rule 7 (and 2, and 6 after its reason): archive the prior, write, record.
    line = event(key=key, cause=cause, status=status, act=act, actor=actor, author=author,
                 prior_version=prior_version, changed=True, chash=new_hash, reason=reason,
                 extra={**(extra_event or {}), **({"forced": True} if forced else {})})
    data[_VERSION_EVENT_KEY] = line
    data.pop("version", None)
    store.save_section(dtxsid, key, data, archive=True)
    return {**outcome, "outcome": "written", "version": data.get("version"),
            "archived": line.get("archived"), "event": line}


def hold(req: WriteRequest) -> dict:
    """Rule 4: keep the owned text; record that a machine had a new one it did
    not apply (the machine's text is not kept)."""
    prior, prior_version = req.prior, req.prior.get("version")
    line = event(key=req.key, cause="hold",
                 status=_status_now(req.dtxsid, req.key, prior, req.store),
                 act=req.act, actor=req.actor, author=req.author, prior_version=prior_version,
                 changed=False, chash=content_hash(prior), applied=False,
                 extra={**(req.extra_event or {}), "held_hash": content_hash(req.content)})
    record(req.dtxsid, req.key, prior_version, line, req.store)
    return {**req.outcome, "outcome": "held", "version": prior_version, "event": line}


def knock_down(req: WriteRequest) -> dict:
    """C2 D2/A1 for a write request (see _knock_down)."""
    return _knock_down(req.dtxsid, req.key, req.prior, req.content, req.store, act=req.act,
                       author=req.author, review=req.review or {},
                       extra_event=req.extra_event, outcome=req.outcome)


def _knock_down(dtxsid: str, key: str, prior: dict, data: dict, store: PoolStore, *, act: str,
                author: str | None, review: dict, extra_event: dict | None,
                outcome: dict) -> dict:
    """C2 D2/A1: an owned apical section whose printed content changed. The new
    content becomes the next version, the owned one is archived, the approval is
    withdrawn (FINAL with it; PROTECTED stands), and a ``review`` marker says
    why and since which version. Re-accepting clears it."""
    from workflow.currency import demote_for_currency
    from workflow.ownership import section_facts, store_content_facts

    prior_review = prior.get("review") if isinstance(prior.get("review"), dict) else {}
    marker = {
        "why": review.get("why", "numbers_changed"),
        # Since the version a person last stood behind, kept across repeated
        # changes until someone re-accepts.
        "since_version": prior_review.get("since_version", prior.get("version")),
        "flips": list(review.get("flips") or []),
    }
    data["approved"] = False
    data.pop("approved_at", None)
    store_content_facts(data, demote_for_currency(section_facts(prior)))
    data["review"] = marker
    if marker["flips"]:
        data["wording_review"] = marker["flips"]
    line = event(key=key, cause="reprocess", status="needs-re-bless", act=act, actor="system",
                 author=author, prior_version=prior.get("version"), changed=True,
                 chash=content_hash(data), review={"why": marker["why"], "flips": marker["flips"]},
                 extra=extra_event)
    data[_VERSION_EVENT_KEY] = line
    data.pop("version", None)
    store.save_section(dtxsid, key, data, archive=True)
    return {**outcome, "outcome": "needs_review", "version": data.get("version"),
            "archived": line.get("archived"), "event": line, "review": marker}


# ---------------------------------------------------------------------------
# Discard (behind the old route and pool reset; C2 D4)
# ---------------------------------------------------------------------------

def discard(dtxsid: str, key: str, store: PoolStore, *, act: str, actor: str,
            reason: str | None) -> dict:
    """Archive a section's current file, delete it and record ``discard``.
    The version counter stays monotonic and restore still reaches the archive.
    No checks: the callers (workflow.steps.discard_section_step, pool reset)
    make them. ``{key, archived, version}``; None when there is no file."""
    prior = read_prior(dtxsid, key, store)
    if prior is None:
        return None
    name = store.archive_section(dtxsid, key)
    version = prior.get("version")
    line = event(key=key, cause="discard", status="discarded", act=act, actor=actor,
                 author=author_of(prior), prior_version=version, changed=False,
                 chash=content_hash(prior), reason=reason, extra={"archived": name})
    store.delete_section(dtxsid, key)
    record(dtxsid, key, version, line, store)
    return {"key": key, "archived": name, "version": version}


# ---------------------------------------------------------------------------
# The genomics narrative overrides (C2 §4.12; until C9 they are no section file)
# ---------------------------------------------------------------------------

def archive_genomics_overrides(dtxsid: str, organ: str, overrides: dict, *, act: str,
                               actor: str, reason: str | None, sexes=None) -> list[dict]:
    """Archive one organ's person-written genomics narrative (both kinds) to
    ``history/genomics_<organ>_<sex>/`` for each sex the organ has (the
    overrides are kept per organ, the sections per organ and sex; with no sexes
    known, ``history/genomics_<organ>/``), and record a ``discard`` event, before
    it is cleared or replaced. Returns one ``{key, archived, version}`` per
    archive; [] when the organ has no override.
    """
    from pipeline.session_store import append_version_event, archive_document

    organ_l = organ.lower()
    held = {kind: paras for kind in ("gene_set", "gene_bmd")
            for o, paras in (overrides.get(kind) or {}).items() if o.lower() == organ_l and paras}
    if not held:
        return []
    out = []
    # The overrides are per organ; the sections (and their histories) are per
    # organ and sex. Without the sexes, the organ's history directory holds it.
    for sex in (sexes or [None]):
        key = f"genomics_{organ_l}_{sex}" if sex else f"genomics_{organ_l}"
        content = {"genomics_narrative_override": held, "organ": organ_l, "source": "person"}
        name, version = archive_document(dtxsid, key, content)
        # The person's text leaves the live store (replaced by a save, cleared
        # by a regenerate) and is kept here: a discard of that version.
        line = event(key=key, cause="discard", status="discarded", act=act, actor=actor,
                     author="person", prior_version=None, changed=False,
                     chash=content_hash(content), reason=reason, extra={"archived": name})
        append_version_event(dtxsid, key, version, line)
        out.append({"key": key, "archived": name, "version": version})
    return out


# ---------------------------------------------------------------------------
# History reads
# ---------------------------------------------------------------------------

def section_history(dtxsid: str, key: str, store: PoolStore) -> dict:
    """A section's versions and events, readable after a discard:

        {section_key, current_version, current_status,
         versions: [{version, archived, status, approved_at, current, retrievable}],
         events: [the index.jsonl lines, oldest first]}

    ``archived`` is the archive file holding that version's text (None for the
    current version when it was never archived, and for a version whose text an
    old archive-name collision lost: then ``retrievable`` is false). Raises
    section_key_invalid, or section_not_found when there is neither a file nor
    any history."""
    key = validate_section_key(dtxsid, key)
    current = read_prior(dtxsid, key, store)
    archived = store.list_archived(dtxsid, key)
    events = store.read_version_history(dtxsid, key)
    if current is None and not archived and not events:
        raise not_found(key, "show")

    by_version: dict[int, dict] = {}
    for name, data in archived:
        v = data.get("version")
        if isinstance(v, int):
            by_version[v] = {"archived": name, "approved_at": data.get("approved_at")}
    current_version = current.get("version") if current else None
    if isinstance(current_version, int):
        entry = by_version.setdefault(current_version, {"archived": None})
        entry["approved_at"] = current.get("approved_at")
    statuses: dict[int, str] = {}
    for e in events:
        v = e.get("version")
        if isinstance(v, int):
            by_version.setdefault(v, {"archived": None, "approved_at": None})
            if e.get("status"):
                statuses[v] = e["status"]
    versions = [{
        "version": v,
        "archived": info.get("archived"),
        "status": statuses.get(v),
        "approved_at": info.get("approved_at"),
        "current": v == current_version,
        "retrievable": v == current_version or info.get("archived") is not None,
    } for v, info in sorted(by_version.items())]
    return {
        "section_key": key,
        "current_version": current_version,
        "current_status": statuses.get(current_version) if current_version is not None else None,
        "versions": versions,
        "events": events,
    }


def read_version(dtxsid: str, key: str, version, store: PoolStore) -> dict:
    """One version's section JSON: the current file when it is that version,
    else its archive. version_not_found when no version by that number is
    known; version_content_missing when the events name it but its text was
    not kept."""
    key = validate_section_key(dtxsid, key)
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise version_not_found(key, version)
    current = read_prior(dtxsid, key, store)
    if current is not None and current.get("version") == version:
        return current
    found = store.read_archived(dtxsid, key, version)
    if found is not None:
        return found
    if any(e.get("version") == version for e in store.read_version_history(dtxsid, key)):
        raise version_content_missing(key, version)
    raise version_not_found(key, version)


__all__ = [
    "SectionRefusal", "write_section", "discard", "section_history", "read_version",
    "validate_section_key", "section_key_patterns", "author_of", "version_status", "is_locked",
    "already_accepted",
    "event", "record", "hold", "knock_down", "WriteRequest", "HOLD", "REVIEW", "STATE_KEYS",
    "section_content",
    "archive_genomics_overrides",
]
