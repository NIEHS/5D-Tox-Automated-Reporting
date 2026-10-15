"""
Unit tests for workflow.read_model — one study's derived state (MODULES.md §4.1).

The phase, sections and publish readiness are driven through a fake PoolStore;
the pins, the identity, the version manifest and the member studies are files
in a scratch SESSIONS_DIR (the `sessions_dir` fixture). The read must leave no
trace, so several tests compare the directory before and after.
"""

import json
from pathlib import Path

import pytest

from workflow.read_model import (
    PUBLISH_CHECKS,
    PUBLISH_CHECKS_COMPLETE,
    ReadOnlyDiskPoolStore,
    ReadOnlyStoreError,
    study_state,
)

ID = "DTXSID9000001"


def _snapshot(root: Path) -> dict:
    """Every path under root with its size and mtime (dotfiles included)."""
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*"))}


class FakeStore:
    """In-memory PoolStore for the read model: presence flags, the validation
    report, and the section dicts. The session folder is a real scratch folder
    (the pins and the version manifest are files)."""

    def __init__(self, session: Path, *, files=True, present=(), report=None, sections=None):
        self._session = session
        self._files = files
        self._present = set(present)
        self._report = report
        self._sections = sections or {}

    def session_dir(self, dtxsid):
        return self._session.parent / dtxsid

    def has_files(self, dtxsid):
        return self._files

    def has_stale_sections(self, dtxsid):
        return any(d.get("stale") for k, d in self._sections.items()
                   if k.startswith(("bm2_", "genomics_")))

    def artifact_exists(self, dtxsid, name):
        return name in self._present

    def read_json(self, dtxsid, name):
        return self._report if name == "validation_report.json" else None

    def read_section_states(self, dtxsid):
        return {k: bool(v.get("approved")) for k, v in self._sections.items()}

    def read_section_dicts(self, dtxsid):
        return dict(self._sections)

    def _no_write(self, *a, **k):
        raise AssertionError("the read model wrote through the store")

    ensure_fingerprints = set_fingerprints = set_integrated = write_json = save_section = _no_write


@pytest.fixture
def session(sessions_dir):
    d = sessions_dir / ID
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# No side effects
# ---------------------------------------------------------------------------

def test_a_study_that_does_not_exist_reads_as_absent_and_is_not_created(sessions_dir):
    before = _snapshot(sessions_dir)
    assert study_state(ID) == {"id": ID, "exists": False}
    assert not (sessions_dir / ID).exists()
    assert _snapshot(sessions_dir) == before


def test_a_malformed_id_is_refused_before_any_path_is_built(sessions_dir):
    from common.dtxsid import InvalidDtxsid
    with pytest.raises(InvalidDtxsid):
        study_state("../sessions")


def test_the_read_only_store_neither_creates_nor_writes(sessions_dir):
    store = ReadOnlyDiskPoolStore()
    assert store.session_dir(ID) == sessions_dir / ID
    assert not (sessions_dir / ID).exists()
    for write in (lambda: store.write_json(ID, "x.json", {}),
                  lambda: store.save_section(ID, "summary", {}),
                  lambda: store.ensure_fingerprints(ID, force=True),
                  lambda: store.set_fingerprints(ID, {}),
                  lambda: store.set_integrated(ID, {})):
        with pytest.raises(ReadOnlyStoreError):
            write()
    assert not (sessions_dir / ID).exists()


def test_reading_a_full_study_changes_nothing_on_disk(session, sessions_dir):
    (session / "files").mkdir()
    (session / "files" / "bw.txt").write_text("x")
    (session / "identity.json").write_text(json.dumps({"name": "Chem", "casrn": "1-11-1"}))
    (session / "summary.json").write_text(json.dumps(
        {"approved": True, "facts": ["final", "protected"], "version": 2, "source": "generated"}))
    (session / "_cache_ntp_abc.json").write_text("{}")
    before = _snapshot(sessions_dir)
    state = study_state(ID)
    assert state["exists"] is True
    assert _snapshot(sessions_dir) == before


# ---------------------------------------------------------------------------
# Phase, identity, processed
# ---------------------------------------------------------------------------

def test_phase_and_legal_actions_come_from_the_engine(session):
    store = FakeStore(session, present={"integrated.json"},
                      report={"issues": [], "coverage_matrix": {}})
    state = study_state(ID, store)
    assert state["phase"] == "INTEGRATED"
    assert state["legal_actions"] == sorted([
        "ADD_FILES", "APPROVE", "CONFIRM_CLASSIFICATION", "INTEGRATE", "PROCESS",
        "REMOVE_FILE", "RESET", "RESOLVE", "STATE_DATASET_FACTS", "VALIDATE"])
    assert state["processed"] is False
    assert state["identity"] is None          # never written: absent, not guessed


def test_identity_short_name_is_the_abbreviation(session):
    (session / "identity.json").write_text(json.dumps(
        {"name": "1,4-Dichlorobenzene", "casrn": "106-46-7", "abbreviation": "1,4-DCB"}))
    state = study_state(ID, FakeStore(session))
    assert state["identity"] == {"name": "1,4-Dichlorobenzene", "casrn": "106-46-7",
                                 "dtxsid": None, "short_name": "1,4-DCB"}


def test_a_damaged_identity_is_an_error_not_an_empty_identity(session):
    from common.session_files import UnreadableSessionFile
    (session / "identity.json").write_text("{trunc")
    with pytest.raises(UnreadableSessionFile):
        study_state(ID, FakeStore(session))


def test_processed_follows_the_ntp_cache(session):
    (session / "_cache_ntp_0123.json").write_text("{}")
    assert study_state(ID, FakeStore(session))["processed"] is True


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def _row(state, key):
    return next(r for r in state["sections"] if r["key"] == key)


def test_section_rows_carry_what_is_on_disk(session):
    sections = {
        "summary": {"approved": False, "stale": True, "regenerated": {"reason": "data_changed"},
                    "facts": ["protected"], "version": 3, "source": "generated"},
        "background": {"approved": True, "facts": ["final", "protected"], "version": 2,
                       "model_used": "claude-sonnet-4-6"},
        "bm2_body-weight": {"approved": False, "version": 1, "source": "generated",
                            "title": "Body Weight", "wording_review": ["Male|Liver.direction_adj"]},
    }
    # The version manifest is a file (session_store.current_version_status).
    for key, d in sections.items():
        (session / f"{key}.json").write_text(json.dumps(d))
    hist = session / "history" / "summary"
    hist.mkdir(parents=True)
    (hist / "index.jsonl").write_text(
        json.dumps({"version": 3, "cause": "reprocess", "status": "needs-re-bless", "ts": "t"}) + "\n")

    state = study_state(ID, FakeStore(session, sections=sections))
    summary = _row(state, "summary")
    assert summary["has_file"] and summary["stale"]
    assert summary["regenerated"]["reason"] == "data_changed"
    assert "data changed" in summary["regenerated"]["say"]     # words, not the code
    assert summary["version"] == 3 and summary["version_status"] == "needs-re-bless"
    assert summary["machine_may_write"] is False       # PROTECTED stands after the demote
    assert summary["facts"] == ["protected"]

    background = _row(state, "background")
    assert background["approved"] and background["facts"] == ["approved", "final", "protected"]
    assert background["machine_may_write"] is False
    assert background["model"] == "claude-sonnet-4-6"
    assert background["version_status"] is None        # no manifest: unknown, not guessed

    bw = _row(state, "bm2_body-weight")
    assert bw["instance_of"] == "bm2" and bw["kind"] == "programmatic"
    assert bw["title"] == "Body Weight"
    assert bw["wording_review"] == ["Male|Liver.direction_adj"]
    assert bw["machine_may_write"] is True

    methods = _row(state, "methods")                   # catalog row, no file
    assert methods["has_file"] is False and methods["version"] is None
    assert methods["enabled"] is False and methods["blocked_by"] == ["processed"]


def test_accept_says_whether_a_person_may_approve_now_and_why_not(session):
    sections = {"background": {"approved": False, "version": 1},
                "bm2_body-weight": {"version": 1}}
    (session / "_cache_ntp_0.json").write_text("{}")   # processed: Methods unlocks
    state = study_state(ID, FakeStore(session, sections=sections))

    assert _row(state, "background")["accept"] == {"allowed": True, "code": None, "say": None}
    assert _row(state, "bm2_body-weight")["accept"]["allowed"] is True

    # Approvable in the catalog, unlocked, but no section file: never offered (C9).
    for key in ("methods", "bmd_summary"):
        row = _row(state, key)
        assert row["approvable"] and row["enabled"] and not row["has_file"]
        assert row["accept"]["allowed"] is False
        assert row["accept"]["code"] == "not_saved_as_section" and row["accept"]["say"]

    summary = _row(state, "summary")                    # waits on an approval
    assert summary["accept"]["code"] == "blocked"
    assert "Background is approved" in summary["accept"]["say"]

    foreword = _row(state, "foreword")                  # supplied front matter
    assert foreword["accept"]["code"] == "not_approvable" and "supplied" in foreword["accept"]["say"]


def test_sections_follow_the_rendering_tree_and_list_cache_only_interpretations(session):
    (session / "_cache_interpretation_liver_male_0a1b.json").write_text("{}")
    state = study_state(ID, FakeStore(session, sections={"bm2_hematology": {"version": 1}}))
    keys = [r["key"] for r in state["sections"]]
    assert "genomics_liver_male" in keys
    assert _row(state, "genomics_liver_male")["has_file"] is False
    # Instances sit where their family sits in the document, not at the end.
    assert keys.index("bm2_hematology") < keys.index("summary")
    # Family names themselves are not rows.
    assert "bm2" not in keys and "genomics" not in keys


# ---------------------------------------------------------------------------
# Publish readiness
# ---------------------------------------------------------------------------

def test_publish_readiness_is_a_checklist_of_stale_llm_sections(session):
    sections = {"summary": {"stale": True, "regenerated": {"reason": "data_changed"}},
                "methods": {"stale": True},
                "bm2_body-weight": {"stale": True}}   # programmatic: never blocks
    state = study_state(ID, FakeStore(session, sections=sections))
    publish = state["readiness"]["publish"]
    assert publish["ready"] is False
    # What "ready" covered, in words, and that it is not everything (until C6).
    assert [c["id"] for c in publish["checks"]] == list(PUBLISH_CHECKS) == ["stale_llm_sections"]
    assert all(c["say"] for c in publish["checks"])
    assert publish["complete"] is PUBLISH_CHECKS_COMPLETE is False
    by_section = {i["section"]: i for i in publish["items"]}
    assert set(by_section) == {"methods", "summary"}
    for item in publish["items"]:
        assert item["id"] == "section.stale" and item["level"] == "block" and item["fix"] == "D1"
        assert item["say"]
    assert by_section["summary"]["reason"] == "data_changed"
    assert by_section["methods"]["reason"] == "stale"
    assert by_section["summary"]["say"] != by_section["methods"]["say"]
    # Not served yet: absent, never guessed.
    assert "data_approval" not in state["readiness"]
    assert "run" not in state


# ---------------------------------------------------------------------------
# The method pin
# ---------------------------------------------------------------------------

def _pin_method(session, name, *, by="user", mode="fixed", hash_=None):
    from pipeline import method_profile as mp
    pin = {"name": name, "hash": hash_ or mp.content_hash(mp.profile_path(name)),
           "mode": mode, "series": "ntp-5day", "pinned_at": "2026-10-14T00:00:00+00:00",
           "pinned_by": by}
    (session / mp.PIN_FILE).write_text(json.dumps(pin))


def test_method_pin_reports_deviations_without_running_the_machine_check(session, monkeypatch):
    from pipeline import bmds27
    bmds27._status.cache_clear()

    def no_probe(*a, **k):
        raise AssertionError("the read model ran the BMDS 2.7 machine check")
    monkeypatch.setattr(bmds27, "_wine_executor", no_probe)
    monkeypatch.setattr(bmds27, "unavailable_reason", no_probe)

    _pin_method(session, "ntp-5day-2021")
    method = study_state(ID, FakeStore(session))["pins"]["method"]
    assert method["pinned"] and method["name"] == "ntp-5day-2021"
    assert method["mode"] == "fixed" and method["pinned_by"] == "person"
    assert any("apical.bmd.eligibility" in d for d in method["deviations"])
    assert any("apical.bmd.engine" in u for u in method["unchecked"])
    assert method["mismatches"] == []                  # no dataset: nothing recorded


def test_an_unpinned_method_says_which_profile_would_be_used(session):
    from pipeline.method_profile import newest_profile
    method = study_state(ID, FakeStore(session))["pins"]["method"]
    assert method["pinned"] is False and method["name"] is None and method["pinned_by"] is None
    assert any(newest_profile() in d and "no profile pinned" in d for d in method["deviations"])
    assert not (session / "method_profile.json").exists()   # read, never pinned


def test_until_a_person_chooses_the_method_a_suggestion_is_served(session):
    """C1 D1 = B: no person's pin → `suggestion` {name, why} (for M5 to
    propose); a default pin is not a person's choice; a person's pin has none.
    Reading it pins nothing."""
    from pipeline.method_profile import newest_profile
    method = study_state(ID, FakeStore(session))["pins"]["method"]
    assert method["suggestion"]["name"] == newest_profile()
    assert "newest" in method["suggestion"]["why"]
    assert not (session / "method_profile.json").exists()

    _pin_method(session, "ntp-5day-2025", mode="track", by="default")
    method = study_state(ID, FakeStore(session))["pins"]["method"]
    assert method["pinned_by"] == "default" and method["suggestion"]["name"]

    _pin_method(session, "ntp-5day-2021")
    assert "suggestion" not in study_state(ID, FakeStore(session))["pins"]["method"]


def test_the_suggestion_follows_the_recorded_analyses(session):
    """With a dataset, the profile whose expectations its recorded analyses
    contradict least is suggested (here the 2021 one: 10% relative deviation)."""
    integrated = {"bMDResult": [{"name": "rat_4D_LI_No0_BMD", "analysisInfo": {"notes": [
        "Data Source: rat_4D_LI_No0", "BMR Type: Relative Deviation", "BMR Factor: 0.1",
        "Model Averaging Method: x"]}}]}
    (session / "integrated.json").write_text(json.dumps(integrated))
    from pipeline import method_profile as mp
    expected = {p["name"]: len(mp.recorded_mismatches(integrated, mp.resolve(p["name"], probe=False)))
                for p in mp.list_profiles()}
    best = min(expected.values())
    suggestion = study_state(ID, FakeStore(session))["pins"]["method"]["suggestion"]
    assert expected[suggestion["name"]] == best
    if suggestion["name"] != mp.newest_profile():
        assert "matches the analysis settings" in suggestion["why"]


def test_a_changed_profile_is_reported_not_raised(session):
    _pin_method(session, "ntp-5day-2021", hash_="0000000000000000")
    method = study_state(ID, FakeStore(session))["pins"]["method"]
    assert method["error"]["code"] == "method_profile_changed"
    assert "deviations" not in method and "mismatches" not in method


def test_live_mismatches_are_memoized_on_the_dataset_and_the_method(session, monkeypatch):
    from pipeline import method_profile as mp
    calls = []

    def fake_mismatches(integrated, method):
        calls.append(method.profile)
        return [{"analysis": "x", "message": f"{len(integrated['bMDResult'])} analyses"}]
    monkeypatch.setattr(mp, "recorded_mismatches", fake_mismatches)
    _pin_method(session, "ntp-5day-2025")
    integrated = session / "integrated.json"
    integrated.write_text(json.dumps({"bMDResult": [{}]}))

    first = study_state(ID, FakeStore(session))["pins"]["method"]["mismatches"]
    again = study_state(ID, FakeStore(session))["pins"]["method"]["mismatches"]
    assert first == again == [{"analysis": "x", "message": "1 analyses"}]
    assert len(calls) == 1
    integrated.write_text(json.dumps({"bMDResult": [{}, {}]}))      # re-integrated
    assert study_state(ID, FakeStore(session))["pins"]["method"]["mismatches"][0]["message"] == "2 analyses"
    _pin_method(session, "ntp-5day-2021")                            # re-pinned
    study_state(ID, FakeStore(session))
    assert calls == ["ntp-5day-2025", "ntp-5day-2025", "ntp-5day-2021"]


# ---------------------------------------------------------------------------
# The document definition
# ---------------------------------------------------------------------------

def test_an_unpinned_new_study_renders_from_the_era(session):
    from document_model.document_definition import DEFAULT_DEFINITION
    d = study_state(ID, FakeStore(session))["pins"]["definition"]
    assert d["pinned"] is False and d["name"] == DEFAULT_DEFINITION
    assert d["source"] == "era" and d["snapshot"] is False and d["drift"] is None


def test_a_fixed_definition_renders_from_its_snapshot(session):
    from document_model import definition_pin as dp
    dp.pin_definition(ID, dp.FIXED)
    d = study_state(ID, FakeStore(session))["pins"]["definition"]
    assert d["pinned"] and d["mode"] == "fixed" and d["snapshot"] is True
    assert d["pinned_by"] == "person" and d["drift"] is None


def test_a_broken_snapshot_is_reported_and_the_sections_still_list(session):
    from document_model import definition_pin as dp
    dp.pin_definition(ID, dp.FIXED)
    snap = session / dp.SNAPSHOT_FILE
    snap.write_text(snap.read_text() + "\nedited: true\n")
    state = study_state(ID, FakeStore(session))
    assert state["pins"]["definition"]["error"]["code"] == "definition_pin_changed"
    assert any(r["key"] == "summary" for r in state["sections"])


def test_a_session_document_yaml_is_the_source(session):
    from document_model.document_config import session_document_path
    from document_model.document_definition import DEFAULT_DEFINITION
    from document_model.document_template import load_template
    import yaml
    session_document_path(ID).write_text(yaml.safe_dump(load_template(DEFAULT_DEFINITION)))
    assert study_state(ID, FakeStore(session))["pins"]["definition"]["source"] == "session"


# ---------------------------------------------------------------------------
# A report over several studies
# ---------------------------------------------------------------------------

def test_members_are_listed_with_their_own_publish_readiness(sessions_dir, session):
    rat = sessions_dir / f"{ID}_rat"
    rat.mkdir()
    (rat / "summary.json").write_text(json.dumps({"stale": True, "regenerated": {"reason": "data_changed"}}))
    (session / "studies.json").write_text(json.dumps({"rat": f"{ID}_rat", "mouse": f"{ID}_mouse"}))

    state = study_state(ID)
    rat_m, mouse_m = state["members"]
    assert (rat_m["key"], rat_m["id"], rat_m["exists"]) == ("rat", f"{ID}_rat", True)
    assert rat_m["phase"] == "EMPTY" and rat_m["processed"] is False
    assert rat_m["readiness"]["publish"]["ready"] is False
    assert [i["section"] for i in rat_m["readiness"]["publish"]["items"]] == ["summary"]
    assert mouse_m == {"key": "mouse", "id": f"{ID}_mouse", "exists": False}
    # Not folded into the report's own verdict (that is C6).
    assert state["readiness"]["publish"]["ready"] is True
    assert not (sessions_dir / f"{ID}_mouse").exists()


def test_a_single_study_has_no_members_key(session):
    assert "members" not in study_state(ID, FakeStore(session))


# ---------------------------------------------------------------------------
# The kind of session
# ---------------------------------------------------------------------------

def test_the_kind_of_session_and_its_relations(sessions_dir, session):
    assert study_state(ID)["kind"] == "study"
    assert study_state(ID)["relations"] == {"parent": None, "twin": None}

    (session / "studies.json").write_text(json.dumps({"rat": f"{ID}_rat"}))
    (sessions_dir / f"{ID}_rat").mkdir()
    assert study_state(ID)["kind"] == "report"
    member = study_state(f"{ID}_rat")
    assert member["kind"] == "member" and member["relations"]["parent"] == ID

    companion = sessions_dir / f"{ID}_published"
    companion.mkdir()
    (companion / "published_clone.json").write_text(json.dumps({"report": "NIEHS-10", "twin": ID}))
    clone = study_state(f"{ID}_published")
    assert clone["kind"] == "companion" and clone["relations"]["twin"] == ID

    (sessions_dir / f"{ID}_nb").mkdir()
    assert study_state(f"{ID}_nb")["kind"] == "other"
