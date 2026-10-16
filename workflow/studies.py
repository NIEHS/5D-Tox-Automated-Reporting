"""
workflow.studies — the studies on disk, what each one is, and where it stands
(module M1 of the new interface; docs/ui-redesign/modules/m1/contract.md).

A study is a folder under SESSIONS_DIR. Beside the studies a person creates,
the system makes sessions of its own: a published book's content (a
companion, ``<id>_published``), the studies of a report over several studies
(``<id>_rat``, ``<id>_mouse``), and working copies made by tools. This module
is the one place that says which is which and how they relate, so the list,
a study's page, the read model (workflow.read_model) and the Bookshelf agree:

  * the session-relation predicates (moved here from the Bookshelf page and
    the prompt workshop): ``clone_record``, ``companion_of``, ``members``,
    ``has_generated_report``, ``report_of``, ``published_date``;
  * ``session_kind``: study / report / member / companion / other, with its
    relations, derived from what is on disk;
  * ``stands``: the phase in plain words and the next step, with the module
    that does it;
  * ``format_summary``: the document definition a session renders from, in a
    person's words;
  * ``study_row`` / ``list_studies`` / ``study_summary`` / ``creation_check``:
    what the M1 endpoints serve;
  * ``lookup_chemical``: the chemical a DTXSID names (PubChem; CTX when set up);
  * ``require_data_session``: the guard that keeps files and data steps out of
    a companion and a report (R6).

Everything is derived on every call and nothing is stored (CONTEXT.md
invariant 3). **Reading has no side effects**: no session folder is created,
no fingerprint scanned, nothing pinned (the read-only store of the read model).
The acts (create, fill the identity, delete) are in workflow.steps.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import common.paths
from common.paths import REPO_ROOT
from workflow.errors import StepError

logger = logging.getLogger(__name__)

# A chemical's own id: the DTXSID, digits only (Gate 0 decision Q7). A
# session id may carry a suffix (common.dtxsid.DTXSID_RE); the chemical it is
# about is the id's DTXSID-and-digits prefix.
STUDY_ID_RE = re.compile(r"^DTXSID\d+$")
_CHEMICAL_PREFIX_RE = re.compile(r"^DTXSID\d+")

# The published books' Bookshelf bundles (their breakdown holds each book's
# date and NBK number).
BOOKSHELF = REPO_ROOT / "assets" / "cebs" / "_bookshelf"


class StudyRefusal(StepError):
    """A study act or read refused with one of the M1 codes of
    workflow.refusals.REFUSALS. ``details`` is what the interface may show
    (and what the plain words name: ``{id}``, ``{parent}``, ``{service}`` …)."""

    def __init__(self, code: str, message: str, status_code: int, details: dict | None = None):
        super().__init__(message, status_code=status_code)
        self.code = code
        self.details = details or {}


def _root() -> Path:
    # Read at call time, so a redirected SESSIONS_DIR (tests, workspaces) is honoured.
    return common.paths.SESSIONS_DIR


def _read_json(path: Path):
    """A session JSON document: None when absent; UnreadableSessionFile when
    it exists but cannot be parsed (never silently empty)."""
    from common.session_files import read_json_file
    return read_json_file(path)


def session_folder(dtxsid: str) -> Path:
    """The session's folder, located and never created (the id is validated)."""
    from common.dtxsid import validate_dtxsid
    return _root() / validate_dtxsid(dtxsid)


def session_exists(dtxsid: str) -> bool:
    """Whether a session of that id exists. An empty folder does not count: a
    read before C4 may have left one behind, and it holds nothing (R8)."""
    d = session_folder(dtxsid)
    return d.is_dir() and any(d.iterdir())


def chemical_dtxsid(dtxsid: str) -> str | None:
    """The chemical a session is about: its id's ``DTXSID<digits>`` prefix,
    None when the id carries none (``DTXSID_TEST``). The ``dtxsid`` written in
    a session's identity.json is not used: a member's names its own id."""
    m = _CHEMICAL_PREFIX_RE.match(dtxsid)
    return m.group(0) if m else None


# ---------------------------------------------------------------------------
# The session-relation predicates (R7: moved from web_routes.bookshelf_routes
# and narrative.prompt_workshop, which keep their names importable)
# ---------------------------------------------------------------------------

def holds_report(dtxsid: str) -> bool:
    """Whether the session's own data was integrated and processed
    (integrated.json plus a processed-sections cache)."""
    sess = _root() / dtxsid
    return (sess / "integrated.json").is_file() and any(sess.glob("_cache_sections_*.json"))


def members(dtxsid: str) -> dict[str, str]:
    """{study key: member session} of a report over several studies
    (studies.json, rendering.report_compose); {} for a single study."""
    from rendering.report_compose import STUDIES_FILE
    data = _read_json(_root() / dtxsid / STUDIES_FILE)
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def clone_record(dtxsid: str) -> dict | None:
    """The companion record (published_clone.json: report, twin, bundle …)
    when the session is a published book's content; else None."""
    from rendering.published_clone import CLONE_FILE
    data = _read_json(_root() / dtxsid / CLONE_FILE)
    return data if isinstance(data, dict) else None


def companion_of(dtxsid: str) -> str | None:
    """The companion session of a generated report — the published book's
    content (tooling.published_clone) — when one was built for it."""
    from tooling.published_clone import companion_id
    cid = companion_id(dtxsid)
    clone = clone_record(cid)
    return cid if clone and clone.get("twin") == dtxsid else None


def has_generated_report(dtxsid: str) -> bool:
    """Whether the session holds a generated report: it was integrated and
    processed, or it is a report over several studies each of which was, or it
    is a published book's content (a companion, served beside its twin).  An
    empty, abandoned or test-made session directory is not a report, so it is
    neither shelved nor served."""
    if holds_report(dtxsid) or clone_record(dtxsid):
        return True
    ms = members(dtxsid)
    return bool(ms) and all(holds_report(m) for m in ms.values())


def report_of(dtxsid: str) -> tuple[str | None, str | None]:
    """(published report, member study) for a session: ("NIEHS-10", None), or
    ("NIEHS-13", "rat") for one study of a report over several studies (the
    composed session's studies.json names its members), or (None, None) for an
    unpublished study."""
    try:
        from tooling.build_published_reports import STUDIES
    except ImportError:  # tooling absent in a slim deployment
        return None, None
    by_dtxsid = {row[0]: r for r, row in STUDIES.items()}
    if dtxsid in by_dtxsid:
        return by_dtxsid[dtxsid], None
    for parent, report in by_dtxsid.items():
        try:
            listed = json.loads((_root() / parent / "studies.json").read_text())
        except (OSError, ValueError):
            continue
        for study, member in (listed or {}).items():
            if member == dtxsid:
                return report, study
    return None, None


def _book_meta(report: str | None) -> dict:
    """The published book's breakdown header (assets/cebs/_bookshelf/<report>/
    breakdown/report.json); {} for no report or an absent bundle."""
    if not report:
        return {}
    try:
        meta = json.loads((BOOKSHELF / report / "breakdown" / "report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


def published_date(report: str | None) -> str | None:
    """When a published report came out ("2023-03"), from its Bookshelf bundle
    breakdown; None for no report, or a bundle that is absent or undated."""
    return _book_meta(report).get("published") or None


def published_record(report: str | None) -> dict | None:
    """``{report, date, nbk}`` of a published report (date and NBK None when
    the bundle does not record them); None for an unpublished study."""
    if not report:
        return None
    meta = _book_meta(report)
    return {"report": report, "date": meta.get("published") or None, "nbk": meta.get("nbk") or None}


_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December")


def month_words(date: str | None) -> str:
    """"2023-03" as "March 2023"; a missing date is a visible placeholder."""
    if not date:
        return "[publication date pending]"
    year, _, month = date.partition("-")
    if month.isdigit() and 1 <= int(month) <= 12:
        return f"{_MONTHS[int(month) - 1]} {year}"
    return year


def _published_of(dtxsid: str, kind: str, clone: dict | None) -> dict | None:
    """The published book a session reproduces (a study, a report, a member)
    or holds (a companion)."""
    if kind == "companion":
        return published_record((clone or {}).get("report"))
    return published_record(report_of(dtxsid)[0])


# ---------------------------------------------------------------------------
# What kind of session it is
# ---------------------------------------------------------------------------

class StoreIndex:
    """One look at the store, for a read that covers many sessions: the
    session folders (non-empty, not ``_`` or ``.``), and which report lists
    which member. Built once per list; a single read builds its own."""

    def __init__(self, root: Path | None = None):
        from rendering.published_clone import CLONE_FILE
        from rendering.report_compose import STUDIES_FILE
        self.root = root or _root()
        try:
            folders = sorted(p for p in self.root.iterdir()
                             if p.is_dir() and not p.name.startswith(("_", ".")))
        except OSError:
            folders = []
        self.ids = [p.name for p in folders if any(p.iterdir())]
        self.companions = {i for i in self.ids if (self.root / i / CLONE_FILE).is_file()}
        self.parent_of: dict[str, tuple[str, str]] = {}
        for listing in sorted(self.root.glob(f"*/{STUDIES_FILE}")):
            try:
                stated = json.loads(listing.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue  # that report's own read reports its damaged file
            if isinstance(stated, dict):
                for key, member in stated.items():
                    if isinstance(member, str):
                        self.parent_of.setdefault(member, (listing.parent.name, str(key)))

    def by_chemical(self, chem: str | None) -> list[str]:
        """The sessions about one chemical, in id order."""
        return [i for i in self.ids if chem and chemical_dtxsid(i) == chem]


def session_kind(dtxsid: str, sessions_root: Path | None = None,
                 index: StoreIndex | None = None) -> dict:
    """What the session is, and the sessions it belongs with (the rule of the
    M1 contract §3, first match wins):

      * ``companion``: a published book's content (``published_clone.json``);
      * ``report``: a report over several studies (``studies.json``);
      * ``member``: listed in another session's ``studies.json``;
      * ``study``: the id is a bare DTXSID (a chemical's own study);
      * ``other``: anything else (a suffixed working copy, a test's folder).

    ``{"kind", "chemical_dtxsid", "chemical_dtxsid_from", "relations"}``, the
    relations being ``{parent, members: [{key, id}], companion, twin, others}``
    (``others``: the chemical's other sessions, those not already named as
    parent, member or companion, and no companion, which belongs with its twin;
    a member's sibling is one; a companion has none). A screen uses
    it to offer only what makes sense: a companion is read-only, a report has
    no files of its own (its members do)."""
    from rendering.published_clone import CLONE_FILE
    from rendering.report_compose import STUDIES_FILE

    index = index or StoreIndex(sessions_root)
    session = index.root / dtxsid
    chem = chemical_dtxsid(dtxsid)
    relations: dict = {"parent": None, "members": [], "companion": None, "twin": None,
                       "others": []}
    clone = _read_json(session / CLONE_FILE)
    if clone is not None:
        kind = "companion"
        twin = clone.get("twin") if isinstance(clone, dict) else None
        relations["twin"] = twin if isinstance(twin, str) else None
    elif (session / STUDIES_FILE).is_file():
        kind = "report"
        stated = _read_json(session / STUDIES_FILE)
        relations["members"] = [{"key": str(k), "id": str(v)}
                                for k, v in (stated.items() if isinstance(stated, dict) else ())]
    elif dtxsid in index.parent_of:
        kind = "member"
        relations["parent"] = index.parent_of[dtxsid][0]
    else:
        kind = "study" if STUDY_ID_RE.fullmatch(dtxsid) else "other"
    if kind != "companion":
        comp = f"{dtxsid}_published"
        if comp in index.ids:
            record = _read_json(index.root / comp / CLONE_FILE)
            if isinstance(record, dict) and record.get("twin") == dtxsid:
                relations["companion"] = comp
    if kind != "companion":   # a companion belongs with its twin alone
        named = {dtxsid, relations["parent"], relations["companion"],
                 *(m["id"] for m in relations["members"])}
        relations["others"] = [i for i in index.by_chemical(chem)
                               if i not in named and i not in index.companions]
    return {"kind": kind, "chemical_dtxsid": chem,
            "chemical_dtxsid_from": None if chem is None else ("id" if chem == dtxsid else "id_prefix"),
            "relations": relations}


def member_key(dtxsid: str, index: StoreIndex | None = None) -> tuple[str, str] | None:
    """(report, study key) of a member study ("DTXSID1020431", "rat"); None otherwise."""
    return (index or StoreIndex()).parent_of.get(dtxsid)


# ---------------------------------------------------------------------------
# Where it stands, and the next step
# ---------------------------------------------------------------------------

# The phase in plain words (MODULES.md §3 names the modules that move it on).
_PHASE_SAY = {
    "EMPTY": "No files yet",
    "UPLOADED": "Files brought in, not yet validated",
    "VALIDATION_ERRORS": "The files have problems to fix",
    "VALIDATED": "Files validated, not yet integrated",
    "INTEGRATED": "Data integrated",
    "APPROVED": "Data reviewed",
}
_PHASE_NEXT = {
    "EMPTY": ("Bring in the study's files", "M2"),
    "UPLOADED": ("Validate the files", "M2"),
    "VALIDATION_ERRORS": ("Fix the problems the validation found", "M2"),
    "VALIDATED": ("Integrate the data", "M3"),
    # The data review informs and gates nothing (decision Q3): Process is next.
    "INTEGRATED": ("Process the data", "P1"),
    "APPROVED": ("Process the data", "P1"),
}
_REVIEW = ("Review the report's sections", "D1")
_PUBLISH = ("Publish the report", "D3")


def _next(pair: tuple[str, str] | None) -> dict | None:
    return {"say": pair[0], "fix": pair[1]} if pair else None


def stands(kind: str, phase: str | None, processed: bool, *,
           member_states: list[dict] | None = None, publish: dict | None = None) -> dict:
    """Where a session stands, in plain words, and the next step with the
    module that does it (the M1 contract §3): ``{phase, say, next}``.

    * a companion has no phase and no next step;
    * a report has no phase of its own (its studies have): it waits for its
      studies, then its sections are reviewed;
    * otherwise the derived phase, and the step that moves it on. Once the
      study is processed the sections are reviewed; "Publish" is the next step
      only when the publish readiness is served complete and ready (C6), never
      before.

    ``member_states`` are the report's studies (``{exists, processed}``);
    ``publish`` the read model's ``readiness.publish``."""
    if kind == "companion":
        return {"phase": None, "say": "The published book's content (read-only)", "next": None}
    if kind == "report":
        ms = member_states or []
        n = len(ms)
        if any(not m.get("exists") or not m.get("processed") for m in ms):
            return {"phase": None, "say": f"A report over {n} studies; its studies are being prepared",
                    "next": _next(("Finish the member studies", "M1"))}
        return {"phase": None, "say": f"A report over {n} studies", "next": _next(_REVIEW)}
    say = _PHASE_SAY.get(phase or "", f"At the stage {phase}")
    if processed and phase in ("INTEGRATED", "APPROVED"):
        ready = bool(publish and publish.get("complete") and publish.get("ready"))
        return {"phase": phase, "say": say, "next": _next(_PUBLISH if ready else _REVIEW)}
    return {"phase": phase, "say": say, "next": _next(_PHASE_NEXT.get(phase or ""))}


# ---------------------------------------------------------------------------
# The guard of R6: no files and no data steps in a companion or a report
# ---------------------------------------------------------------------------

def require_data_session(dtxsid: str, store=None) -> None:
    """Refuse a data act (bringing in files, validating, integrating, the data
    approval, Process) on a session whose data is not its own: a published
    book's content (``read_only_session``: made by a tool from the book) or a
    report over several studies (``report_has_no_data``: its data is prepared
    in its studies). Reads through ``store`` when given (the step's own
    PoolStore), else the session folder, which it never creates. Cheap: two
    small files. A session that does not exist yet passes."""
    from rendering.published_clone import CLONE_FILE
    from rendering.report_compose import STUDIES_FILE

    if store is not None:
        clone = store.read_json(dtxsid, CLONE_FILE)
        listed = store.read_json(dtxsid, STUDIES_FILE)
    else:
        session = session_folder(dtxsid)
        clone = (session / CLONE_FILE).is_file() or None
        listed = _read_json(session / STUDIES_FILE) if (session / STUDIES_FILE).is_file() else None
    if clone is not None:
        raise StudyRefusal("read_only_session",
                           f"{dtxsid} is a published book's companion ({CLONE_FILE}); "
                           "no data act is done on it", 409, {"id": dtxsid})
    if listed is not None:
        ids = [str(v) for v in listed.values()] if isinstance(listed, dict) else []
        raise StudyRefusal("report_has_no_data",
                           f"{dtxsid} is a report over several studies ({STUDIES_FILE}: "
                           f"{', '.join(ids)}); its data is prepared in those studies", 409,
                           {"id": dtxsid, "members": ids})


# ---------------------------------------------------------------------------
# The report format: which definition a session renders from, in words
# ---------------------------------------------------------------------------

def _alteration_words(outline: dict) -> str:
    """"unaltered", "with 1 change", "with its own series details" … from a
    definition's outline (document_definition.definition_outline)."""
    from document_model.document_definition import ALTERATION_WORDS
    parts = []
    n = outline.get("changes") or 0
    if n:
        parts.append(f"{n} change" + ("" if n == 1 else "s"))
    alters = [ALTERATION_WORDS[k] for k in outline.get("alters") or [] if k in ALTERATION_WORDS]
    if alters:
        parts.append("its own " + ", ".join(alters))
    return ("with " + " and ".join(parts)) if parts else "unaltered"


def _report_label(published: dict | None) -> str:
    """"NIEHS-10 (March 2023)" for a published report."""
    return f"{published['report']} ({month_words(published.get('date'))})"


def format_summary(dtxsid: str, kind: str, relations: dict | None = None,
                   published: dict | None = None, *, prospective: bool = False) -> dict:
    """The report format a session is written in (the M1 contract's
    FormatSummary): ``{definition, source, era, title, title_short, changes, say}``.

    ``source`` is where the structure comes from: ``session`` (the session's own
    document.yaml, a companion's), ``pinned`` (a FIXED snapshot), ``study``
    (templates/studies/<id>/document.yaml), ``default`` (the format for new
    studies) or ``era`` (an era named some other way). The title is the era's
    declared one (document_definition.ERA_TITLES). A member study is written in
    its report's format. ``prospective`` words it for a study not yet created
    ("A study under this id is written in …")."""
    from document_model import definition_pin as dp
    from document_model.document_config import session_document_path
    from document_model.document_definition import (
        DEFAULT_DEFINITION, current_definition_name, definition_outline, era_title,
        study_definition_name)

    relations = relations or {}
    if kind == "member" and relations.get("parent"):
        parent = relations["parent"]
        out = format_summary(parent, "report", {}, published)
        out["say"] = f"Written as part of the report {parent}, in its format."
        return out

    if not prospective and session_document_path(dtxsid).is_file():
        if kind == "companion":
            whose = f"{published['report']}'s" if published else "the published book's"
            return {"definition": "session:document.yaml", "source": "session", "era": None,
                    "title": "The published book's own structure", "title_short": "As published",
                    "changes": 0,
                    "say": f"This session holds {whose} own content and structure, built from "
                           "the published book."}
        return {"definition": "session:document.yaml", "source": "session", "era": None,
                "title": "This session's own structure", "title_short": "Own structure",
                "changes": 0,
                "say": "This session renders from its own structure (the document.yaml in its "
                       "folder), not from a format's definition."}

    pin = None
    if not prospective:
        try:
            pin = dp.read_pin(dtxsid)
        except ValueError as exc:
            from common.session_files import UnreadableSessionFile
            raise UnreadableSessionFile(session_folder(dtxsid) / dp.PIN_FILE, exc) from exc
    fixed = bool(pin) and pin.get("mode") == dp.FIXED
    name = pin.get("name") if fixed else current_definition_name(dtxsid)
    outline = definition_outline(name)
    titles = era_title(outline["era"])
    if fixed:
        source = "pinned"
    elif name.startswith("studies/"):
        source = "study"
    elif name == DEFAULT_DEFINITION:
        source = "default"
    else:
        source = "era"

    subject = ("A study under this id" if prospective
               else "The report" if kind == "report" else "The study")
    if name.startswith("studies/"):
        if published:
            say = (f"This chemical has a published report, {_report_label(published)}. "
                   f"{subject} is written in that book's format: {titles['phrase']}, "
                   f"{_alteration_words(outline)}.")
        else:
            say = (f"This chemical has its own document definition (templates/{name}.yaml). "
                   f"{subject} is written in it: {titles['phrase']}, {_alteration_words(outline)}.")
    elif name == DEFAULT_DEFINITION and kind == "other":
        chem = chemical_dtxsid(dtxsid)
        say = "This session's id is not a chemical's DTXSID, so it uses the format for new studies."
        if chem and study_definition_name(chem):
            theirs = published_record(report_of(chem)[0])
            whose = f"{theirs['report']}'s" if theirs else "its own"
            say += f" A study under {chem} would use {whose} format."
    elif name == DEFAULT_DEFINITION:
        say = ("No published report is on file for this chemical, so "
               f"{subject[0].lower() + subject[1:]} uses the format for new studies: "
               f"{titles['phrase']}.")
    else:
        say = f"{subject} is written in {titles['phrase']}."
    if fixed:
        say += f" It is fixed to the copy pinned on {_day(pin.get('pinned_at'))}."
    return {"definition": name, "source": source, "era": outline["era"],
            "title": titles["title"], "title_short": titles["short"],
            "changes": outline["changes"], "say": say}


def _day(stamp: str | None) -> str:
    """"2026-10-12T…" as "12 Oct 2026"; an unrecorded time says so."""
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).strftime("%-d %b %Y")
    except ValueError:
        return "a date not recorded"


def _organ_filters(view: dict) -> str:
    """The organ selections of a study overlay, in words ("gene sets: liver,
    kidney; organ weights: liver")."""
    organs = ((view or {}).get("filters") or {}).get("organs") or {}
    words = {"genomics": "gene sets", "organ-weight": "organ weights"}
    parts = [f"{words.get(area, area.replace('-', ' '))}: {', '.join(map(str, vals))}"
             for area, vals in organs.items() if isinstance(vals, list) and vals]
    return "; ".join(parts)


def format_brings(dtxsid: str) -> list[dict]:
    """What the id brings with it from templates/studies/<id>/ besides the
    format (Q-M1-2): the book's structure, its choice of organs and endpoints,
    its deposit wording, its authored text. Read from the files there."""
    import yaml
    from document_model.document_definition import _templates_dir

    folder = _templates_dir() / "studies" / dtxsid
    if not folder.is_dir():
        return []
    rel = f"templates/studies/{dtxsid}"
    out: list[dict] = []
    if (folder / "document.yaml").is_file():
        out.append({"what": "document_definition", "path": f"{rel}/document.yaml",
                    "say": "the book's structure and wording"})
    if (folder / "view.yaml").is_file():
        organs = _organ_filters(yaml.safe_load((folder / "view.yaml").read_text(encoding="utf-8")))
        out.append({"what": "report_view", "path": f"{rel}/view.yaml",
                    "say": "the book's choice of organs and endpoints for its tables"
                           + (f" ({organs})" if organs else "")})
    if (folder / "deposit.yaml").is_file():
        deposit = yaml.safe_load((folder / "deposit.yaml").read_text(encoding="utf-8")) or {}
        doi = deposit.get("doi") if isinstance(deposit, dict) else None
        out.append({"what": "deposit", "path": f"{rel}/deposit.yaml",
                    "say": "the book's captions for its deposited files"
                           + (f" and its data DOI, {doi}" if doi else "")})
    authored: dict[str, Path] = {}
    for p in sorted(folder.iterdir()):
        if p.is_file() and p.suffix in (".html", ".tex") and p.stem not in authored:
            authored[p.stem] = p
    for stem, p in authored.items():
        m = re.fullmatch(r"appendix-([a-z])", stem)
        say = (f"Appendix {m.group(1).upper()}'s text as published" if m
               else f"the authored text “{stem}” as published")
        out.append({"what": "authored_content", "path": f"{rel}/{p.name}", "say": say})
    return out


def format_hash(dtxsid: str) -> str:
    """The content hash of the definition the files give an id now (the hash
    a pin records; document_model.definition_pin.definition_hash)."""
    from document_model.definition_pin import definition_hash
    from document_model.document_definition import current_definition_name
    from document_model.document_template import _load_raw
    return definition_hash(_load_raw(current_definition_name(dtxsid)))


# ---------------------------------------------------------------------------
# One session as a row of the list
# ---------------------------------------------------------------------------

def identity_of(session: Path) -> dict:
    """The chemical as the session records it (identity.json): name, CASRN,
    short name, and how it was set (``source``). A value not on file is None;
    a session made before M1 has no recorded provenance (``unknown``).
    ``source.casrn_from`` says who gave the CAS number: ``"lookup"``,
    ``"person"`` (typed, the lookup had none), or None (not recorded)."""
    raw = _read_json(session / "identity.json")
    raw = raw if isinstance(raw, dict) else {}
    src = raw.get("identity_source") if isinstance(raw.get("identity_source"), dict) else {}
    return {"name": raw.get("name") or None, "casrn": raw.get("casrn") or None,
            "short_name": raw.get("abbreviation") or None,
            "source": {"kind": src.get("kind") or "unknown", "service": src.get("service"),
                       "confirmed_at": src.get("confirmed_at"),
                       # "person" when the person typed the CAS number (the
                       # lookup gave none); None for a session made before M1.
                       "casrn_from": src.get("casrn_from") or (
                           "lookup" if src.get("kind") == "lookup" else None)}}


def last_changed(session: Path) -> str | None:
    """The newest modification on disk: the session's top-level entries and
    everything under files/ and history/ (ISO 8601, UTC)."""
    newest = 0.0
    for p in session.iterdir():
        newest = max(newest, p.stat().st_mtime)
    for sub in ("files", "history"):
        for p in (session / sub).rglob("*"):
            newest = max(newest, p.stat().st_mtime)
    if not newest:
        return None
    return datetime.fromtimestamp(newest, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def running_since(dtxsid: str) -> str | None:
    """When the Process run in flight on this study started, None when none is.
    C5 serves the run lock; until it does, no run is known here (the read
    model serves no ``run`` either), so this answers None."""
    return None


def _bookshelf(dtxsid: str, kind: str, relations: dict) -> dict:
    """Whether the session's report is on the Bookshelf, and if not, why."""
    if kind == "member":
        parent = relations.get("parent")
        return {"on_shelf": False, "url": f"/Bookshelf/{parent}", "say": f"Part of {parent}'s book"}
    on = has_generated_report(dtxsid)
    if kind == "companion":
        return {"on_shelf": on, "url": f"/Bookshelf/{dtxsid}" if on else None,
                "say": "The published content, on the Bookshelf" if on
                else "Not on the Bookshelf: its published study is missing"}
    if on:
        return {"on_shelf": True, "url": f"/Bookshelf/{dtxsid}", "say": "On the Bookshelf (draft)"}
    if kind == "report":
        say = "Not yet: its studies have not all been processed"
    elif kind == "study":
        say = "Not yet: the study has no report (it has not been processed)"
    else:
        say = "Not yet: the session has no report"
    return {"on_shelf": False, "url": None, "say": say}


def _refusal_say(code: str, **fields) -> str:
    from workflow.refusals import REFUSALS, _Fields
    return REFUSALS[code].say.format_map(_Fields(fields))


def delete_verdict(dtxsid: str, kind: str, relations: dict,
                   index: StoreIndex | None = None) -> dict:
    """Whether the session may be deleted here, and if not, why: a companion
    is the book's (a tool rebuilds it), a member belongs to its report, and a
    study with a run in flight is busy. ``{allowed, code, say, details}``."""
    if kind == "companion":
        return {"allowed": False, "code": "read_only_session", "say": _refusal_say("read_only_session"),
                "details": {}}
    if kind == "member":
        parent, key = member_key(dtxsid, index) or (relations.get("parent"), "")
        details = {"parent": parent, "key": key, "species": key or "member"}
        return {"allowed": False, "code": "member_of_report",
                "say": _refusal_say("member_of_report", **details), "details": details}
    since = running_since(dtxsid)
    if since:
        return {"allowed": False, "code": "run_in_flight",
                "say": _refusal_say("run_in_flight", time=since), "details": {"started_at": since}}
    return {"allowed": True, "code": None, "say": None, "details": {}}


def _phase_and_publish(dtxsid: str, kind: str, relations: dict) -> tuple[dict, bool, str | None]:
    """(stands, processed, phase) from the derived workflow state, read through
    the read-only store."""
    from workflow.engine import WorkflowEngine, _is_processed
    from workflow.read_model import ReadOnlyDiskPoolStore, publish_readiness_state

    store = ReadOnlyDiskPoolStore()
    session = store.session_dir(dtxsid)
    processed = _is_processed(session)
    engine = WorkflowEngine(dtxsid, store)
    phase = engine.state().phase.value
    member_states = None
    if kind == "report":
        member_states = [{"exists": (_root() / m["id"]).is_dir(),
                          "processed": _is_processed(_root() / m["id"])}
                         for m in relations.get("members", [])]
    publish = publish_readiness_state(engine) if processed else None
    return (stands(kind, phase, processed, member_states=member_states, publish=publish),
            processed, phase)


def _note_for(exc: Exception) -> dict:
    from workflow.refusals import explain
    err = explain(exc)["error"]
    return {"level": "error", "code": err["code"], "say": err["say"]}


def study_row(dtxsid: str, index: StoreIndex | None = None) -> dict:
    """One session as the list and its page show it (the M1 contract's
    StudyRow). A part that cannot be read (a damaged file) is left empty and
    named in ``notes``: one damaged session never hides the others."""
    index = index or StoreIndex()
    session = index.root / dtxsid
    notes: list[dict] = []
    try:
        kind_info = session_kind(dtxsid, index=index)
    except Exception as exc:  # noqa: BLE001 — named in notes, the row still lists
        notes.append(_note_for(exc))
        chem = chemical_dtxsid(dtxsid)
        kind_info = {"kind": "other", "chemical_dtxsid": chem,
                     "chemical_dtxsid_from": None if chem is None else
                     ("id" if chem == dtxsid else "id_prefix"),
                     "relations": {"parent": None, "members": [], "companion": None,
                                   "twin": None, "others": []}}
    kind, relations = kind_info["kind"], kind_info["relations"]

    def guarded(fn, empty):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — named in notes, the row still lists
            notes.append(_note_for(exc))
            return empty

    identity = guarded(lambda: identity_of(session),
                       {"name": None, "casrn": None, "short_name": None,
                        "source": {"kind": "unknown", "service": None, "confirmed_at": None,
                                   "casrn_from": None}})
    stood, processed, _phase = guarded(
        lambda: _phase_and_publish(dtxsid, kind, relations),
        ({"phase": None, "say": "Where this session stands can't be read", "next": None},
         False, None))
    clone = guarded(lambda: clone_record(dtxsid), None) if kind == "companion" else None
    published = guarded(lambda: _published_of(dtxsid, kind, clone), None)
    fmt = guarded(lambda: format_summary(dtxsid, kind, relations, published), None)
    verdict = delete_verdict(dtxsid, kind, relations, index)
    if kind == "other":
        chem = kind_info["chemical_dtxsid"]
        notes.insert(0, {"level": "warn", "code": "not_a_chemical_id",
                         "say": "Made by a tool; its id is not a chemical's DTXSID." if chem
                         else "Made by a tool or a test; its id names no chemical."})
    return {
        "id": dtxsid,
        **kind_info,
        "identity": identity,
        "stands": stood,
        "processed": processed,
        "last_changed": guarded(lambda: last_changed(session), None),
        "format": fmt,
        "published": published,
        "bookshelf": guarded(lambda: _bookshelf(dtxsid, kind, relations),
                             {"on_shelf": False, "url": None, "say": "Can't be read"}),
        "actions": {"open": {"allowed": True},
                    "delete": {k: verdict[k] for k in ("allowed", "code", "say")}},
        "notes": notes,
    }


_KIND_ORDER = {"study": 0, "report": 0, "member": 1, "companion": 2, "other": 3}


def list_studies() -> dict:
    """Every session, grouped by the chemical it is about (the M1 contract
    §2.1): ``{chemicals: [{dtxsid, name, casrn, primary, can_create,
    sessions}], unassigned, generated_at}``. Chemicals by their newest change,
    most recent first; within one, the primary session (the study, or the
    report), then its member studies, its published content, other sessions.
    Free of side effects."""
    index = StoreIndex()
    rows = [study_row(i, index) for i in index.ids]
    groups: dict[str, list[dict]] = {}
    unassigned: list[dict] = []
    for row in rows:
        chem = row["chemical_dtxsid"]
        (groups.setdefault(chem, []) if chem else unassigned).append(row)

    chemicals = []
    for chem, sessions in groups.items():
        sessions.sort(key=lambda r: (_KIND_ORDER.get(r["kind"], 9), r["id"]))
        primary = next((r for r in sessions if r["id"] == chem and r["kind"] in ("study", "report")),
                       None)
        named = primary if primary and primary["identity"]["name"] else \
            next((r for r in sessions if r["identity"]["name"]), None)
        chemicals.append({
            "dtxsid": chem,
            "name": (named or {}).get("identity", {}).get("name"),
            "casrn": (named or {}).get("identity", {}).get("casrn"),
            "primary": primary["id"] if primary else None,
            "can_create": chem not in index.ids,
            "sessions": sessions,
        })
    newest = lambda rs: max((r["last_changed"] or "" for r in rs), default="")  # noqa: E731
    chemicals.sort(key=lambda c: newest(c["sessions"]), reverse=True)
    unassigned.sort(key=lambda r: r["last_changed"] or "", reverse=True)
    return {"chemicals": chemicals, "unassigned": unassigned,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


# ---------------------------------------------------------------------------
# One session, in detail
# ---------------------------------------------------------------------------

_COUNT_WORDS = {2: "two", 3: "three", 4: "four", 5: "five"}


def _banner(row: dict, index: StoreIndex) -> dict | None:
    """What a session's page says first about what it is (None for a study)."""
    kind, rel, sid = row["kind"], row["relations"], row["id"]
    published = row.get("published")
    name = row["identity"]["name"]
    if kind == "companion":
        book = published["report"] if published else "the published book"
        links = [{"say": "Read it on the Bookshelf", "href": f"/Bookshelf/{sid}"}]
        if rel.get("twin"):
            links.append({"say": f"The generated study: {rel['twin']}",
                          "href": f"/app/studies/{rel['twin']}"})
        return {"level": "info", "links": links,
                "say": f"This is the published book's own content ({book}), built by a tool from "
                       "the published book. It can't be changed or deleted here."}
    if kind == "member":
        parent, key = member_key(sid, index) or (rel.get("parent"), "")
        about = ", ".join(x for x in (name, published["report"] if published else None) if x)
        siblings = [(k, m) for m, (p, k) in sorted(index.parent_of.items())
                    if p == parent and m != sid]
        also = ""
        if siblings:
            also = ", which also has " + " and ".join(f"a {k} study" for k, _ in siblings)
        links = [{"say": f"The report {parent}", "href": f"/app/studies/{parent}"}]
        links += [{"say": f"The {k} study {m}", "href": f"/app/studies/{m}"} for k, m in siblings]
        return {"level": "info", "links": links,
                "say": f"This is the {key or 'member'} study of the report {parent}"
                       + (f" ({about})" if about else "") + f"{also}. Its data is prepared here; "
                       "its report is the parent's."}
    if kind == "report":
        n = len(rel.get("members", []))
        return {"level": "info", "links": [],
                "say": f"A report over {_COUNT_WORDS.get(n, n)} studies. The data is prepared in "
                       "each study; this report gathers them."}
    if kind == "other":
        chem = row["chemical_dtxsid"]
        fmt = row.get("format") or {}
        if not chem:
            return {"level": "warning", "links": [],
                    "say": f"This session's id, {sid}, names no chemical: it was made by a tool or "
                           "a test."}
        suffix = sid[len(chem):].lstrip("_-").lower()
        from pipeline.deposit import SPECIES_TITLES
        if suffix in SPECIES_TITLES:
            # A report's studies are named <DTXSID>_<species>; no report lists
            # this one (else it would be a member), so its report is gone.
            say = (f"This session's id, {sid}, names a {suffix} study, as the studies of a "
                   "report over several studies are named, but no report lists it: the report "
                   "it belonged to may have been deleted.")
        else:
            say = (f"This session's id, {sid}, is not a chemical's DTXSID alone, and no report "
                   "lists it: a tool made it, or it was a study of a report that has since been "
                   "deleted.")
        if fmt.get("title_short"):
            say += f" Its report uses the format {fmt['title_short']}"
            theirs = format_summary(chem, "study", {}, published_record(report_of(chem)[0]),
                                    prospective=True)
            if theirs["definition"] != fmt.get("definition"):
                whose = published_record(report_of(chem)[0])
                say += (f"; a study under {chem} would use "
                        + (f"{whose['report']}'s format" if whose else f"the format {theirs['title_short']}"))
            say += "."
        links = ([{"say": f"The study {chem}", "href": f"/app/studies/{chem}"}]
                 if chem in index.ids else [])
        return {"level": "warning", "say": say, "links": links}
    return None


def study_summary(dtxsid: str) -> dict:
    """One session's row with its detail (the M1 contract §2.2): the banner
    by kind, the format with what the id brings and the pin, and for a report
    its member studies' rows. Refuses an absent (or empty) session with
    ``study_not_found``; creates nothing."""
    from common.dtxsid import validate_dtxsid
    from document_model import definition_pin as dp

    validate_dtxsid(dtxsid)
    if not session_exists(dtxsid):
        raise StudyRefusal("study_not_found", f"no session {dtxsid}", 404,
                           {"id": dtxsid})
    index = StoreIndex()
    row = study_row(dtxsid, index)
    fmt = dict(row["format"] or {})
    if fmt:
        try:
            pin = dp.read_pin(dtxsid) if row["kind"] != "member" else None
        except ValueError as exc:  # a damaged pin file: named, the page still opens
            from common.session_files import UnreadableSessionFile
            row["notes"].append(_note_for(UnreadableSessionFile(
                session_folder(dtxsid) / dp.PIN_FILE, exc)))
            pin = None
        fmt["brings"] = format_brings(dtxsid) if row["kind"] in ("study", "report") else []
        fmt["pin"] = {"mode": (pin or {}).get("mode"), "pinned_at": (pin or {}).get("pinned_at"),
                      "pinned_by": (pin or {}).get("pinned_by")}
        fmt["chosen_by"] = "id"
    detail: dict = {"banner": _banner(row, index), "format": fmt or None}
    if row["kind"] == "report":
        detail["members"] = [study_row(m["id"], index) if (_root() / m["id"]).is_dir()
                             else {"id": m["id"], "key": m["key"], "exists": False}
                             for m in row["relations"]["members"]]
    return {**row, "detail": detail}


# ---------------------------------------------------------------------------
# Before creating: is the id free, and which format would it bring
# ---------------------------------------------------------------------------

def require_study_id(dtxsid: str) -> str:
    """A study id a person may create: the chemical's DTXSID, digits only.
    InvalidDtxsid when it is not a session id at all; ``study_id_has_suffix``
    when it is one only the system makes."""
    from common.dtxsid import validate_dtxsid
    validate_dtxsid(dtxsid)
    if not STUDY_ID_RE.fullmatch(dtxsid):
        raise StudyRefusal("study_id_has_suffix", f"study id {dtxsid!r} must match {STUDY_ID_RE.pattern}",
                           400, {"id": dtxsid})
    return dtxsid


_RELATED_SAY = {"companion": "The published book's content",
                "other": "Other session",
                "report": "A report over several studies",
                "study": "A study"}


def creation_check(dtxsid: str) -> dict:
    """Whether a study can be created under this DTXSID, and which format it
    would be written in (the M1 contract §2.4). Side-effect-free, no network."""
    require_study_id(dtxsid)
    index = StoreIndex()
    exists = session_exists(dtxsid)
    related = []
    for sid in index.by_chemical(dtxsid):
        if sid == dtxsid:
            continue
        kind = session_kind(sid, index=index)["kind"]
        if kind == "member":
            parent, key = member_key(sid, index) or ("", "")
            say = f"The {key} study of the report {parent}"
        else:
            say = _RELATED_SAY.get(kind, kind)
        related.append({"id": sid, "kind": kind, "say": say})
    published = published_record(report_of(dtxsid)[0])
    fmt = format_summary(dtxsid, "study", {}, published, prospective=True)
    fmt["brings"] = format_brings(dtxsid)
    fmt["hash"] = format_hash(dtxsid)
    return {"dtxsid": dtxsid, "exists": exists,
            "existing": {"id": dtxsid, "kind": session_kind(dtxsid, index=index)["kind"]}
            if exists else None,
            "related_sessions": related, "format": fmt, "published": published}


# ---------------------------------------------------------------------------
# The chemical a DTXSID names (PubChem; CTX when a key is set)
# ---------------------------------------------------------------------------

# Looked-up identities, so the confirm step and the create agree (10 minutes).
_LOOKUP_TTL_S = 600
_LOOKUPS: dict[str, tuple[float, dict]] = {}
_LOOKUP_LOCK = threading.Lock()


def _now_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def lookup_chemical(dtxsid: str, *, fresh: bool = False) -> dict:
    """The chemical a DTXSID names, from PubChem (and the EPA CTX service when
    its key is set): ``{dtxsid, identity: {name, casrn, pubchem_cid,
    molecular_formula, molecular_weight, iupac_name, inchikey}, dtxsid_matched,
    service, say_source, structure_url, looked_up_at, needs, needs_say}``.

    ``needs``: what the person must type before a study can be created,
    ``["casrn"]`` when the service gives no CAS number, else ``[]``;
    ``needs_say`` says so in plain words (None when nothing is needed).

    ``dtxsid_matched``: the service lists this DTXSID for the compound (PubChem's
    full synonym list, or CTX returned it). Refuses ``identity_not_found`` when
    no compound answers, ``identity_lookup_unreachable`` when the service could
    not be asked (never a made-up name). A found result is kept 10 minutes."""
    import os
    from narrative import chem_resolver as cr

    require_study_id(dtxsid)
    with _LOOKUP_LOCK:
        hit = _LOOKUPS.get(dtxsid)
    if hit and not fresh and time.monotonic() - hit[0] < _LOOKUP_TTL_S:
        return dict(hit[1])

    ctx = bool(os.environ.get("CTX_API_KEY"))
    service = "PubChem" + (" and CTX" if ctx else "")
    with cr.recording_failures() as failures:
        found = cr.resolve_chemical(dtxsid, "dtxsid")
        synonyms = cr.pubchem_synonyms(found.pubchem_cid) if found.pubchem_cid else []
    if not found.pubchem_cid or not found.name:
        if failures:
            raise StudyRefusal("identity_lookup_unreachable",
                               f"{service} request failed: {failures[0]}", 503,
                               {"service": service, "id": dtxsid})
        raise StudyRefusal("identity_not_found",
                           "; ".join(found.resolution_notes) or f"no compound for {dtxsid}",
                           404, {"service": service, "id": dtxsid})
    matched = dtxsid in synonyms or (ctx and found.dtxsid == dtxsid and not failures)
    result = {
        "dtxsid": dtxsid,
        "identity": {"name": found.name, "casrn": found.casrn or None,
                     "pubchem_cid": found.pubchem_cid,
                     "molecular_formula": found.molecular_formula or None,
                     "molecular_weight": found.molecular_weight or None,
                     "iupac_name": found.iupac_name or None, "inchikey": found.inchikey or None},
        "dtxsid_matched": bool(matched),
        "service": service,
        "say_source": f"Looked up in {service} just now."
                      + ("" if ctx else " The CompTox (CTX) lookup is not set up on this server."),
        "structure_url": f"/api/v2/chemicals/{dtxsid}/structure.png",
        "looked_up_at": _now_z(),
        # What the person must add before a study can be created: the CAS
        # number, when the service gives none (decided 2026-10-16).
        "needs": [] if found.casrn else ["casrn"],
        "needs_say": None if found.casrn else (
            f"{service} gives no CAS number for {found.name}. Type it before going on; it "
            "will be recorded as stated by you."),
    }
    with _LOOKUP_LOCK:
        _LOOKUPS[dtxsid] = (time.monotonic(), dict(result))
    return result


def chemical_structure(dtxsid: str) -> bytes:
    """The compound's structure picture (PNG) for a DTXSID; refuses
    ``structure_unavailable`` when the service returns none."""
    from narrative import chem_resolver as cr
    found = lookup_chemical(dtxsid)
    png = cr.structure_png(found["identity"]["pubchem_cid"])
    if not png:
        raise StudyRefusal("structure_unavailable",
                           f"PubChem returned no structure picture for CID "
                           f"{found['identity']['pubchem_cid']}", 404, {"service": "PubChem"})
    return png
