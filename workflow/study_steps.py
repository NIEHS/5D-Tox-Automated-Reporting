"""
workflow.study_steps — the study acts of module M1 of the new interface:
create a study, fill a missing chemical identity, and delete a study (its dry
run and the delete itself). docs/ui-redesign/modules/m1/contract.md §2.6–2.9.

HTTP-free, like workflow.steps (which re-exports these names, so callers keep
importing them from there). They work on the session folder directly, not
through a PoolStore: creating and deleting are acts on the folder itself.
Refusals are ``workflow.studies.StudyRefusal`` with the M1 codes of
workflow.refusals.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from common.provenance import step_provenance

logger = logging.getLogger(__name__)


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
