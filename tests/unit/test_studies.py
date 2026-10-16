"""
Unit tests for workflow.studies — the studies on disk, their kinds, relations,
where they stand, their report format, the lookup, and the R6 guard (module M1).

Sessions are small folders in a scratch SESSIONS_DIR (the `sessions_dir`
fixture). The R6 guard is also driven through a fake PoolStore. The chemical
lookup never reaches the network: the resolver is replaced.
"""

import json
from pathlib import Path

import pytest

from workflow import studies
from workflow.refusals import explain
from workflow.studies import (
    StudyRefusal,
    chemical_dtxsid,
    creation_check,
    format_summary,
    list_studies,
    require_data_session,
    session_kind,
    stands,
    study_row,
    study_summary,
)


def _session(root: Path, sid: str, *, name=None, casrn=None, files=False, integrated=False,
             processed=False, **extra) -> Path:
    d = root / sid
    d.mkdir(parents=True, exist_ok=True)
    if name or casrn:
        (d / "identity.json").write_text(json.dumps({"dtxsid": sid, "name": name, "casrn": casrn}))
    if files:
        (d / "files").mkdir(exist_ok=True)
        (d / "files" / "a.txt").write_text("x")
    if integrated:
        (d / "integrated.json").write_text("{}")
    if processed:
        (d / "_cache_ntp_0.json").write_text("{}")
        (d / "_cache_sections_0.json").write_text("{}")
    for file, data in extra.items():
        (d / file.replace("__", ".")).write_text(json.dumps(data))
    return d


def _snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*"))}


@pytest.fixture
def store(sessions_dir):
    """A small store with every kind of session: a report over two studies
    with its companion, a study with its companion and a tool's copy, a plain
    study, a test folder, an empty folder and the prompts folder."""
    _session(sessions_dir, "DTXSID1", name="Dichloro", casrn="106-46-7",
             studies__json={"rat": "DTXSID1_rat", "mouse": "DTXSID1_mouse"})
    _session(sessions_dir, "DTXSID1_rat", name="Dichloro", files=True, integrated=True, processed=True)
    _session(sessions_dir, "DTXSID1_mouse", name="Dichloro", files=True)
    _session(sessions_dir, "DTXSID1_published", name="Dichloro",
             published_clone__json={"report": "NIEHS-13", "twin": "DTXSID1"})
    _session(sessions_dir, "DTXSID2", name="Perfluoro", casrn="41997-13-1", files=True)
    _session(sessions_dir, "DTXSID2_published", name="Perfluoro",
             published_clone__json={"report": "NIEHS-10", "twin": "DTXSID2"})
    _session(sessions_dir, "DTXSID2_nb", name="Perfluoro", files=True)
    _session(sessions_dir, "DTXSID3", name="Triclosan", casrn="3380-34-5")
    (sessions_dir / "DTXSID_TEST").mkdir()
    (sessions_dir / "DTXSID_TEST" / "method_profile.json").write_text("{}")
    (sessions_dir / "DTXSID9").mkdir()               # an empty folder: not a session
    (sessions_dir / "_prompts").mkdir()
    (sessions_dir / "_prompts" / "x.json").write_text("{}")
    return sessions_dir


# ---------------------------------------------------------------------------
# Kind and relations (the M1 contract §3)
# ---------------------------------------------------------------------------

def test_the_kind_of_each_session(store):
    kinds = {sid: session_kind(sid)["kind"] for sid in
             ("DTXSID1", "DTXSID1_rat", "DTXSID1_published", "DTXSID2", "DTXSID2_nb", "DTXSID_TEST")}
    assert kinds == {"DTXSID1": "report", "DTXSID1_rat": "member", "DTXSID1_published": "companion",
                     "DTXSID2": "study", "DTXSID2_nb": "other", "DTXSID_TEST": "other"}


def test_relations(store):
    report = session_kind("DTXSID1")["relations"]
    assert report["members"] == [{"key": "rat", "id": "DTXSID1_rat"},
                                 {"key": "mouse", "id": "DTXSID1_mouse"}]
    assert report["companion"] == "DTXSID1_published" and report["others"] == []

    rat = session_kind("DTXSID1_rat")["relations"]
    assert rat["parent"] == "DTXSID1" and rat["others"] == ["DTXSID1_mouse"]   # its sibling

    study = session_kind("DTXSID2")["relations"]
    assert study["companion"] == "DTXSID2_published" and study["others"] == ["DTXSID2_nb"]

    clone = session_kind("DTXSID2_published")["relations"]
    assert clone["twin"] == "DTXSID2" and clone["others"] == []

    nb = session_kind("DTXSID2_nb")["relations"]
    assert nb["others"] == ["DTXSID2"]         # the companion belongs with its twin


def test_a_companion_names_its_twin_only_when_the_record_says_so(sessions_dir):
    _session(sessions_dir, "DTXSID5")
    _session(sessions_dir, "DTXSID5_published", published_clone__json={"twin": "DTXSID6"})
    assert session_kind("DTXSID5")["relations"]["companion"] is None


def test_the_chemical_of_a_session_is_its_id_prefix():
    assert chemical_dtxsid("DTXSID50469320") == "DTXSID50469320"
    assert chemical_dtxsid("DTXSID1020431_rat") == "DTXSID1020431"
    assert chemical_dtxsid("DTXSID_TEST") is None


def test_the_read_model_uses_the_same_derivation(store):
    from workflow.read_model import study_state
    state = study_state("DTXSID1_rat")
    assert state["kind"] == "member" and state["chemical_dtxsid"] == "DTXSID1"
    assert state["relations"] == session_kind("DTXSID1_rat")["relations"]
    assert state["stands"] == study_row("DTXSID1_rat")["stands"]


# ---------------------------------------------------------------------------
# Where it stands
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("phase,say,fix", [
    ("EMPTY", "No files yet", "M2"),
    ("UPLOADED", "Files brought in, not yet validated", "M2"),
    ("VALIDATION_ERRORS", "The files have problems to fix", "M2"),
    ("VALIDATED", "Files validated, not yet integrated", "M3"),
    ("INTEGRATED", "Data integrated", "P1"),
    ("APPROVED", "Data reviewed", "P1"),
])
def test_stands_by_phase(phase, say, fix):
    out = stands("study", phase, False)
    assert out["phase"] == phase and out["say"] == say and out["next"]["fix"] == fix


def test_a_processed_study_is_reviewed_and_never_published_before_c6():
    assert stands("study", "APPROVED", True)["next"]["fix"] == "D1"
    incomplete = {"ready": True, "complete": False}
    assert stands("study", "APPROVED", True, publish=incomplete)["next"]["fix"] == "D1"
    complete = {"ready": True, "complete": True}
    assert stands("study", "APPROVED", True, publish=complete)["next"]["fix"] == "D3"


def test_a_companion_and_a_report_have_no_phase():
    assert stands("companion", "EMPTY", False) == {
        "phase": None, "say": "The published book's content (read-only)", "next": None}
    waiting = stands("report", "EMPTY", False,
                     member_states=[{"exists": True, "processed": True}, {"exists": True, "processed": False}])
    assert waiting["phase"] is None and "being prepared" in waiting["say"]
    assert waiting["next"]["fix"] == "M1"
    done = stands("report", "EMPTY", False,
                  member_states=[{"exists": True, "processed": True}] * 2)
    assert done["say"] == "A report over 2 studies" and done["next"]["fix"] == "D1"


# ---------------------------------------------------------------------------
# The format
# ---------------------------------------------------------------------------

def test_a_new_chemical_gets_the_format_for_new_studies(sessions_dir):
    fmt = format_summary("DTXSID7020182", "study", prospective=True)
    assert fmt["source"] == "default" and fmt["era"] == "eras/niehs-2026"
    assert fmt["title"].startswith("NIEHS Report, as published in 2026")
    assert "No published report is on file" in fmt["say"]


def test_a_published_chemical_brings_its_book_format_and_files(sessions_dir):
    check = creation_check("DTXSID50469320")
    fmt = check["format"]
    assert fmt["source"] == "study" and fmt["era"] == "eras/niehs-2023"
    assert fmt["title_short"] == "NIEHS Report, March 2023"
    assert check["published"]["report"] == "NIEHS-10"
    assert "NIEHS-10" in fmt["say"] and "unaltered" in fmt["say"]
    assert [b["what"] for b in fmt["brings"]] == ["document_definition", "report_view", "deposit",
                                                 "authored_content"]
    assert check["exists"] is False and check["existing"] is None
    assert len(fmt["hash"]) == 16


def test_every_era_has_a_declared_title():
    from document_model.document_definition import ERA_TITLES, _templates_dir
    eras = {f"eras/{p.stem}" for p in (_templates_dir() / "eras").glob("*.yaml")}
    assert eras == set(ERA_TITLES)


def test_the_outline_counts_changes_and_alterations():
    from document_model.document_definition import definition_outline
    assert definition_outline("studies/DTXSID1020431/document") == {
        "era": "eras/niehs-2026", "changes": 1, "alters": []}
    assert definition_outline("studies/DTXSID00190950/document")["alters"] == ["book_meta"]
    assert definition_outline("eras/niehs-2023") == {"era": "eras/niehs-2023", "changes": 0, "alters": []}


def test_a_tool_copy_says_what_its_chemical_would_get(sessions_dir):
    _session(sessions_dir, "DTXSID50469320_nb", name="Perfluoro")
    fmt = format_summary("DTXSID50469320_nb", "other")
    assert fmt["source"] == "default"
    assert "would use" in fmt["say"] and "DTXSID50469320" in fmt["say"]


def test_a_member_is_written_in_its_reports_format(store):
    fmt = study_row("DTXSID1_rat")["format"]
    assert fmt["say"] == "Written as part of the report DTXSID1, in its format."


# ---------------------------------------------------------------------------
# The list
# ---------------------------------------------------------------------------

def test_the_list_groups_by_chemical(store):
    out = list_studies()
    by_chem = {c["dtxsid"]: c for c in out["chemicals"]}
    assert set(by_chem) == {"DTXSID1", "DTXSID2", "DTXSID3"}
    assert [r["id"] for r in by_chem["DTXSID1"]["sessions"]] == [
        "DTXSID1", "DTXSID1_mouse", "DTXSID1_rat", "DTXSID1_published"]
    assert [r["id"] for r in by_chem["DTXSID2"]["sessions"]] == [
        "DTXSID2", "DTXSID2_published", "DTXSID2_nb"]
    assert by_chem["DTXSID1"]["primary"] == "DTXSID1" and by_chem["DTXSID1"]["can_create"] is False
    assert by_chem["DTXSID1"]["name"] == "Dichloro" and by_chem["DTXSID1"]["casrn"] == "106-46-7"
    assert [r["id"] for r in out["unassigned"]] == ["DTXSID_TEST"]   # no empty folder, no _prompts


def test_a_chemical_with_only_a_tool_copy_offers_creation(sessions_dir):
    _session(sessions_dir, "DTXSID4_nb", name="X")
    chem = list_studies()["chemicals"][0]
    assert chem["primary"] is None and chem["can_create"] is True


def test_delete_is_refused_for_companions_and_members(store):
    rows = {r["id"]: r for c in list_studies()["chemicals"] for r in c["sessions"]}
    assert rows["DTXSID1_published"]["actions"]["delete"]["code"] == "read_only_session"
    rat = rows["DTXSID1_rat"]["actions"]["delete"]
    assert rat["allowed"] is False and rat["code"] == "member_of_report"
    assert rat["say"] == "This is the rat study of the report DTXSID1. Deleting it would break that report."
    assert rows["DTXSID2"]["actions"]["delete"] == {"allowed": True, "code": None, "say": None}


def test_a_damaged_file_names_itself_and_the_list_goes_on(store):
    (store / "DTXSID3" / "identity.json").write_text("{not json")
    rows = {r["id"]: r for c in list_studies()["chemicals"] for r in c["sessions"]}
    row = rows["DTXSID3"]
    assert row["identity"]["name"] is None
    assert row["notes"][0]["code"] == "damaged_session_file"
    assert rows["DTXSID2"]["notes"] == []


def test_the_bookshelf_cell(store):
    rows = {r["id"]: r for c in list_studies()["chemicals"] for r in c["sessions"]}
    assert rows["DTXSID1_rat"]["bookshelf"] == {"on_shelf": False, "url": "/Bookshelf/DTXSID1",
                                               "say": "Part of DTXSID1's book"}
    assert rows["DTXSID2_published"]["bookshelf"]["on_shelf"] is True
    assert rows["DTXSID2"]["bookshelf"]["say"].startswith("Not yet")


def test_reading_leaves_the_store_as_it_was(store):
    before = _snapshot(store)
    list_studies()
    for sid in ("DTXSID1", "DTXSID1_rat", "DTXSID2_published", "DTXSID_TEST"):
        study_summary(sid)
    creation_check("DTXSID50469320")
    creation_check("DTXSID7")
    assert _snapshot(store) == before


# ---------------------------------------------------------------------------
# One session in detail
# ---------------------------------------------------------------------------

def test_an_absent_or_empty_study_is_not_found_and_not_created(store):
    for sid in ("DTXSID9", "DTXSID77"):
        with pytest.raises(StudyRefusal) as e:
            study_summary(sid)
        assert e.value.code == "study_not_found"
    assert not (store / "DTXSID77").exists()


def test_banners(store):
    rat = study_summary("DTXSID1_rat")["detail"]["banner"]
    assert "rat study of the report DTXSID1" in rat["say"] and "mouse study" in rat["say"]
    assert {"/app/studies/DTXSID1", "/app/studies/DTXSID1_mouse"} == {x["href"] for x in rat["links"]}
    clone = study_summary("DTXSID2_published")["detail"]["banner"]
    assert "can't be changed or deleted" in clone["say"]
    assert {"/Bookshelf/DTXSID2_published", "/app/studies/DTXSID2"} == {x["href"] for x in clone["links"]}
    assert study_summary("DTXSID2")["detail"]["banner"] is None
    assert study_summary("DTXSID_TEST")["detail"]["banner"]["level"] == "warning"
    report = study_summary("DTXSID1")
    assert [m["id"] for m in report["detail"]["members"]] == ["DTXSID1_rat", "DTXSID1_mouse"]


def test_the_other_banner_is_true_of_a_former_member(store):
    """F6: a report deleted, its studies are kind other; their banner must not
    say a tool made them. A tool's copy is told apart from a former member
    only by the id's suffix naming a species; nothing is invented."""
    import shutil
    shutil.rmtree(store / "DTXSID1")
    rat = study_summary("DTXSID1_rat")
    assert rat["kind"] == "other"
    say = rat["detail"]["banner"]["say"]
    assert "made by a tool" not in say and "a tool made it" not in say
    assert "names a rat study" in say and "no report lists it" in say
    tool = study_summary("DTXSID2_nb")["detail"]["banner"]["say"]
    assert tool.startswith("This session's id, DTXSID2_nb, is not a chemical's DTXSID alone")
    assert "a tool made it, or it was a study of a report that has since been deleted" in tool


# ---------------------------------------------------------------------------
# Creation check
# ---------------------------------------------------------------------------

def test_creation_check_on_an_existing_id(store):
    check = creation_check("DTXSID2")
    assert check["exists"] is True and check["existing"] == {"id": "DTXSID2", "kind": "study"}
    assert {r["id"]: r["kind"] for r in check["related_sessions"]} == {
        "DTXSID2_nb": "other", "DTXSID2_published": "companion"}


def test_an_empty_folder_counts_as_absent(store):
    assert creation_check("DTXSID9")["exists"] is False


def test_creation_needs_a_bare_dtxsid(sessions_dir):
    with pytest.raises(StudyRefusal) as e:
        creation_check("DTXSID50469320_v2")
    assert e.value.code == "study_id_has_suffix"
    from common.dtxsid import InvalidDtxsid
    with pytest.raises(InvalidDtxsid):
        creation_check("7020182")


# ---------------------------------------------------------------------------
# The lookup
# ---------------------------------------------------------------------------

@pytest.fixture
def resolver(monkeypatch):
    """The resolver replaced: `answers` maps a DTXSID to a ChemicalIdentity
    dict (absent: nothing found); `synonyms` maps a CID to its synonyms."""
    from narrative import chem_resolver as cr

    studies._LOOKUPS.clear()
    answers, synonyms = {}, {}

    def resolve(query, query_type="auto", ctx_api_key=""):
        found = cr.ChemicalIdentity(dtxsid=query)
        if query in answers:
            for k, v in answers[query].items():
                setattr(found, k, v)
        else:
            found.resolution_notes.append(f"PubChem lookup failed for name '{query}'")
        return found

    monkeypatch.setattr(cr, "resolve_chemical", resolve)
    monkeypatch.setattr(cr, "pubchem_synonyms", lambda cid: synonyms.get(cid, []))
    monkeypatch.delenv("CTX_API_KEY", raising=False)
    yield answers, synonyms
    studies._LOOKUPS.clear()


BPA = {"name": "Bisphenol A", "casrn": "80-05-7", "pubchem_cid": 6623,
       "molecular_formula": "C15H16O2", "molecular_weight": 228.29}


def test_a_lookup_found(resolver):
    answers, synonyms = resolver
    answers["DTXSID7020182"] = BPA
    synonyms[6623] = ["Bisphenol A"] + [f"syn{i}" for i in range(40)] + ["DTXSID7020182"]
    out = studies.lookup_chemical("DTXSID7020182")
    assert out["identity"]["name"] == "Bisphenol A" and out["identity"]["casrn"] == "80-05-7"
    assert out["dtxsid_matched"] is True          # found past the resolver's cap of 20
    assert out["service"] == "PubChem" and "not set up" in out["say_source"]
    assert out["needs"] == [] and out["needs_say"] is None
    answers.clear()                                # the cached answer stands for 10 minutes
    assert studies.lookup_chemical("DTXSID7020182")["identity"]["name"] == "Bisphenol A"


def test_a_lookup_with_no_casrn_needs_one_typed(resolver):
    answers, _ = resolver
    answers["DTXSID7020182"] = {**BPA, "casrn": ""}
    out = studies.lookup_chemical("DTXSID7020182")
    assert out["identity"]["casrn"] is None and out["needs"] == ["casrn"]
    assert out["needs_say"] == ("PubChem gives no CAS number for Bisphenol A. Type it if you "
                                "have it; it is recorded as stated by you. Otherwise it "
                                "shows as pending.")


def test_a_lookup_that_does_not_list_the_dtxsid(resolver):
    answers, synonyms = resolver
    answers["DTXSID7020182"] = BPA
    assert studies.lookup_chemical("DTXSID7020182")["dtxsid_matched"] is False


def test_nothing_found_is_not_an_unreachable_service(resolver):
    with pytest.raises(StudyRefusal) as e:
        studies.lookup_chemical("DTXSID0000000001")
    err = explain(e.value)["error"]
    assert err["code"] == "identity_not_found" and err["status"] == 404
    assert err["say"].startswith("PubChem has no chemical with the DTXSID DTXSID0000000001")


def test_an_unreachable_service_is_said_so(monkeypatch):
    """The real resolver over a network that fails: the cause is kept."""
    import requests

    from narrative import chem_resolver as cr

    studies._LOOKUPS.clear()
    monkeypatch.setattr(cr, "RATE_LIMIT", 0)
    monkeypatch.delenv("CTX_API_KEY", raising=False)

    def down(*a, **k):
        raise requests.ConnectTimeout("timed out")

    monkeypatch.setattr(cr.requests, "get", down)
    with pytest.raises(StudyRefusal) as e:
        studies.lookup_chemical("DTXSID7020182")
    err = explain(e.value)["error"]
    assert err["code"] == "identity_lookup_unreachable" and err["status"] == 503
    assert "ConnectTimeout" in err["message"] and "(PubChem)" in err["say"]


def test_recording_failures_separates_404_from_errors(monkeypatch):
    from narrative import chem_resolver as cr

    class R:
        def __init__(self, code):
            self.status_code = code

        def json(self):
            return {}

    monkeypatch.setattr(cr, "RATE_LIMIT", 0)
    monkeypatch.setattr(cr.requests, "get", lambda *a, **k: R(404))
    with cr.recording_failures() as failures:
        assert cr._pubchem_get("/x") is None
    assert failures == []
    monkeypatch.setattr(cr.requests, "get", lambda *a, **k: R(503))
    with cr.recording_failures() as failures:
        assert cr._pubchem_get("/x") is None
    assert failures == ["PubChem answered HTTP 503"]
    assert cr._pubchem_get("/x") is None          # outside the block: nothing recorded


# ---------------------------------------------------------------------------
# R6: no data act on a companion or a report
# ---------------------------------------------------------------------------

class FakeStore:
    def __init__(self, docs):
        self.docs = docs

    def read_json(self, dtxsid, name):
        return self.docs.get(name)


def test_the_data_guard_through_a_store():
    require_data_session("DTXSID1", FakeStore({}))
    with pytest.raises(StudyRefusal) as e:
        require_data_session("DTXSID1", FakeStore({"published_clone.json": {"twin": "DTXSID2"}}))
    assert e.value.code == "read_only_session" and e.value.status_code == 409
    with pytest.raises(StudyRefusal) as e:
        require_data_session("DTXSID1", FakeStore({"studies.json": {"rat": "DTXSID1_rat"}}))
    assert e.value.code == "report_has_no_data" and e.value.details["members"] == ["DTXSID1_rat"]


def test_the_data_guard_on_disk(store):
    require_data_session("DTXSID2")
    require_data_session("DTXSID404")              # not there yet: the act's own checks apply
    assert not (store / "DTXSID404").exists()
    for sid, code in (("DTXSID1", "report_has_no_data"), ("DTXSID2_published", "read_only_session")):
        with pytest.raises(StudyRefusal) as e:
            require_data_session(sid)
        assert e.value.code == code


def test_the_data_steps_refuse_a_companion(store):
    from workflow.steps import generate_animal_report_step, integrate_step, validate_step
    from workflow.store import DiskPoolStore
    for step in (validate_step, generate_animal_report_step):
        with pytest.raises(StudyRefusal):
            step("DTXSID2_published", DiskPoolStore())
    with pytest.raises(StudyRefusal):
        integrate_step("DTXSID1", None, DiskPoolStore())
