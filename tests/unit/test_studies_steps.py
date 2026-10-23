"""
Unit tests for the study acts of ui_api.study_steps (module M1): create a study,
fill a missing identity, the delete's dry run, and the delete.

Sessions are folders in a scratch SESSIONS_DIR; OUTPUT_DIR points at a scratch
folder too. The chemical lookup is replaced (no network).
"""

import json
from pathlib import Path

import pytest

from ui_api import studies
from ui_api.study_steps import (
    create_study_step,
    delete_study_dry_run,
    delete_study_step,
    record_identity_step,
)
from ui_api.studies import StudyRefusal

NEW = "DTXSID7020182"
DEFAULT_HASH = None   # filled by the fixture: the hash the id's format has now

LOOKUP = {"dtxsid": NEW,
          "identity": {"name": "Bisphenol A", "casrn": "80-05-7", "pubchem_cid": 6623,
                       "molecular_formula": "C15H16O2", "molecular_weight": 228.29,
                       "iupac_name": None, "inchikey": None},
          "dtxsid_matched": True, "service": "PubChem", "say_source": "…",
          "structure_url": f"/api/v2/chemicals/{NEW}/structure.png",
          "looked_up_at": "2026-10-15T12:00:00Z"}


@pytest.fixture
def lookup(monkeypatch):
    """lookup_chemical replaced: answers the dict in `found` (a copy of
    LOOKUP), or refuses identity_not_found when it is set to None."""
    state = {"found": json.loads(json.dumps(LOOKUP))}

    def fake(dtxsid, *, fresh=False):
        if state["found"] is None:
            raise StudyRefusal("identity_not_found", "nothing", 404, {"id": dtxsid})
        return {**state["found"], "dtxsid": dtxsid}

    monkeypatch.setattr(studies, "lookup_chemical", fake)
    return state


@pytest.fixture
def output_dir(tmp_path, monkeypatch):
    import common.paths
    out = tmp_path / "output"
    out.mkdir()
    monkeypatch.setattr(common.paths, "OUTPUT_DIR", out)
    return out


def _identity(**over):
    base = {"name": "Bisphenol A", "casrn": "80-05-7", "pubchem_cid": 6623,
            "source": {"kind": "lookup", "service": "PubChem", "looked_up_at": "2026-10-15T12:00:00Z"}}
    return {**base, **over}


def _seen(dtxsid=NEW):
    return {"definition": "eras/niehs-2026", "hash": studies.format_hash(dtxsid)}


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def test_create_writes_identity_and_meta_only(sessions_dir, lookup):
    assert create_study_step(NEW, _identity(), _seen(), confirmed=True) == {"id": NEW}
    folder = sessions_dir / NEW
    assert sorted(p.name for p in folder.iterdir()) == ["identity.json", "meta.json"]
    ident = json.loads((folder / "identity.json").read_text())
    assert ident["name"] == "Bisphenol A" and ident["casrn"] == "80-05-7"
    assert ident["dtxsid"] == NEW and ident["pubchem_cid"] == 6623
    assert ident["identity_source"]["kind"] == "lookup"
    assert ident["identity_source"]["confirmed_at"]
    meta = json.loads((folder / "meta.json").read_text())
    assert meta["dtxsid"] == NEW and meta["created_at"] == meta["updated_at"]
    assert not [p for p in sessions_dir.iterdir() if p.name.startswith(".")]   # no staging left

    from ui_api.read_model import study_state
    state = study_state(NEW)
    assert state["phase"] == "EMPTY" and state["stands"]["next"]["fix"] == "M2"
    assert studies.study_row(NEW)["identity"]["source"]["kind"] == "lookup"


def test_create_takes_over_an_empty_folder(sessions_dir, lookup):
    (sessions_dir / NEW).mkdir()
    create_study_step(NEW, _identity(), _seen(), confirmed=True)
    assert (sessions_dir / NEW / "identity.json").is_file()


def test_create_refuses_an_existing_study(sessions_dir, lookup):
    (sessions_dir / NEW).mkdir()
    (sessions_dir / NEW / "meta.json").write_text("{}")
    with pytest.raises(StudyRefusal) as e:
        create_study_step(NEW, _identity(), _seen(), confirmed=True)
    assert e.value.code == "study_exists" and e.value.status_code == 409
    assert e.value.details["existing_id"] == NEW
    assert (sessions_dir / NEW / "meta.json").read_text() == "{}"     # untouched


def test_create_twice_makes_one_study(sessions_dir, lookup):
    create_study_step(NEW, _identity(), _seen(), confirmed=True)
    with pytest.raises(StudyRefusal) as e:
        create_study_step(NEW, _identity(), _seen(), confirmed=True)
    assert e.value.code == "study_exists"


@pytest.mark.parametrize("sid,code", [("DTXSID7020182_v2", "study_id_has_suffix")])
def test_create_needs_a_bare_dtxsid(sessions_dir, lookup, sid, code):
    with pytest.raises(StudyRefusal) as e:
        create_study_step(sid, _identity(), _seen(), confirmed=True)
    assert e.value.code == code
    assert not (sessions_dir / sid).exists()


def test_create_refuses_a_format_that_changed(sessions_dir, lookup):
    with pytest.raises(StudyRefusal) as e:
        create_study_step(NEW, _identity(), {"definition": "eras/niehs-2026", "hash": "0" * 16},
                          confirmed=True)
    assert e.value.code == "format_changed" and e.value.details["hash"] == studies.format_hash(NEW)
    with pytest.raises(StudyRefusal):
        create_study_step(NEW, _identity(), None, confirmed=True)
    assert not (sessions_dir / NEW).exists()


@pytest.mark.parametrize("identity,confirmed,code", [
    (_identity(), False, "identity_unconfirmed"),
    (_identity(source={"kind": "stated"}), True, "identity_unconfirmed"),
    (_identity(name="  "), True, "identity_incomplete"),
    (_identity(casrn="80-05-8"), True, "invalid_casrn"),
    (_identity(casrn="80-5-7"), True, "invalid_casrn"),
    (_identity(name="Bisphenol B", casrn="77-40-7"), True, "identity_changed"),
])
def test_create_refuses_an_identity_not_confirmed_or_not_the_lookups(
        sessions_dir, lookup, identity, confirmed, code):
    with pytest.raises(StudyRefusal) as e:
        create_study_step(NEW, identity, _seen(), confirmed=confirmed)
    assert e.value.code == code
    assert not (sessions_dir / NEW).exists()


def test_an_unmatched_dtxsid_needs_the_persons_check(sessions_dir, lookup):
    lookup["found"]["dtxsid_matched"] = False
    with pytest.raises(StudyRefusal) as e:
        create_study_step(NEW, _identity(), _seen(), confirmed=True)
    assert e.value.code == "identity_unconfirmed"
    create_study_step(NEW, _identity(), _seen(), confirmed=True, dtxsid_checked_by_person=True)
    ident = json.loads((sessions_dir / NEW / "identity.json").read_text())
    assert ident["identity_source"]["dtxsid_matched"] is False


def test_create_with_no_lookup_creates_nothing(sessions_dir, lookup):
    lookup["found"] = None
    with pytest.raises(StudyRefusal) as e:
        create_study_step(NEW, _identity(), _seen(), confirmed=True)
    assert e.value.code == "identity_not_found"
    assert not (sessions_dir / NEW).exists()


# ---------------------------------------------------------------------------
# The CAS number never blocks: the lookup's, a typed one, or none (2026-10-16,
# revised: only the DTXSID is required)
# ---------------------------------------------------------------------------

def test_create_with_a_typed_casrn_when_the_lookup_has_none(sessions_dir, lookup):
    lookup["found"]["identity"]["casrn"] = None
    create_study_step(NEW, _identity(casrn=" 80-05-7 "), _seen(), confirmed=True)
    ident = json.loads((sessions_dir / NEW / "identity.json").read_text())
    assert ident["casrn"] == "80-05-7" and ident["name"] == "Bisphenol A"
    assert ident["identity_source"]["casrn_from"] == "person"
    row = studies.study_row(NEW)
    assert row["identity"]["source"]["casrn_from"] == "person" and row["notes"] == []


def test_a_looked_up_casrn_is_recorded_as_the_lookups(sessions_dir, lookup):
    create_study_step(NEW, _identity(), _seen(), confirmed=True)
    ident = json.loads((sessions_dir / NEW / "identity.json").read_text())
    assert ident["casrn"] == "80-05-7" and ident["identity_source"]["casrn_from"] == "lookup"


def test_a_looked_up_casrn_left_out_of_the_identity_sent_is_still_recorded(sessions_dir, lookup):
    create_study_step(NEW, _identity(casrn=""), _seen(), confirmed=True)
    ident = json.loads((sessions_dir / NEW / "identity.json").read_text())
    assert ident["casrn"] == "80-05-7" and ident["identity_source"]["casrn_from"] == "lookup"


@pytest.mark.parametrize("sent", [None, "", "  "])
def test_create_without_a_casrn_when_the_lookup_has_none(sessions_dir, lookup, sent):
    lookup["found"]["identity"]["casrn"] = None
    create_study_step(NEW, _identity(casrn=sent), _seen(), confirmed=True)
    ident = json.loads((sessions_dir / NEW / "identity.json").read_text())
    assert ident["name"] == "Bisphenol A" and ident["casrn"] is None
    assert ident["identity_source"]["kind"] == "lookup"
    assert ident["identity_source"]["casrn_from"] is None
    row = studies.study_row(NEW)
    assert row["identity"]["casrn"] is None and row["identity"]["source"]["casrn_from"] is None
    assert [n["code"] for n in row["notes"]] == ["casrn_pending"]
    assert row["notes"][0]["level"] == "warn" and "CAS number is pending" in row["notes"][0]["say"]


def test_a_missing_name_says_to_look_up_again(sessions_dir, lookup):
    from ui_api.refusals import explain
    with pytest.raises(StudyRefusal) as e:
        create_study_step(NEW, _identity(name=""), _seen(), confirmed=True)
    assert e.value.code == "identity_incomplete"
    assert "look the chemical up again" in explain(e.value)["error"]["say"]
    assert not (sessions_dir / NEW).exists()


@pytest.mark.parametrize("typed", ["80-05-8", "80-5-7", "8005-7", "CAS 80-05-7"])
def test_a_typed_casrn_is_checked(sessions_dir, lookup, typed):
    lookup["found"]["identity"]["casrn"] = None
    with pytest.raises(StudyRefusal) as e:
        create_study_step(NEW, _identity(casrn=typed), _seen(), confirmed=True)
    assert e.value.code == "invalid_casrn"
    assert not (sessions_dir / NEW).exists()


def test_a_typed_casrn_other_than_the_lookups_is_refused(sessions_dir, lookup):
    with pytest.raises(StudyRefusal) as e:
        create_study_step(NEW, _identity(casrn="50-00-0"), _seen(), confirmed=True)
    assert e.value.code == "identity_changed"
    assert e.value.details["looked_up"] == {"name": "Bisphenol A", "casrn": "80-05-7"}
    assert not (sessions_dir / NEW).exists()


def test_a_wrong_name_is_refused_even_with_a_typed_casrn(sessions_dir, lookup):
    lookup["found"]["identity"]["casrn"] = None
    with pytest.raises(StudyRefusal) as e:
        create_study_step(NEW, _identity(name="Bisphenol B", casrn="80-05-7"), _seen(),
                          confirmed=True)
    assert e.value.code == "identity_changed"


def test_record_identity_with_a_typed_casrn_or_none(sessions_dir, lookup):
    lookup["found"]["identity"]["casrn"] = None
    d = _folder(sessions_dir, f"{NEW}_nb", meta__json={"dtxsid": NEW})
    record_identity_step(f"{NEW}_nb", _identity(casrn="80-05-7"), confirmed=True)
    ident = json.loads((d / "identity.json").read_text())
    assert ident["casrn"] == "80-05-7" and ident["identity_source"]["casrn_from"] == "person"
    d2 = _folder(sessions_dir, f"{NEW}_x", meta__json={"dtxsid": NEW})
    record_identity_step(f"{NEW}_x", _identity(casrn=""), confirmed=True)
    ident = json.loads((d2 / "identity.json").read_text())
    assert ident["name"] == "Bisphenol A" and ident["casrn"] is None
    assert ident["identity_source"]["casrn_from"] is None


# ---------------------------------------------------------------------------
# Create with the identity pending: the lookup does not know the DTXSID, or
# cannot be reached (2026-10-16, revised)
# ---------------------------------------------------------------------------

@pytest.fixture
def no_cached_lookup(monkeypatch):
    """The 10-minute lookup cache, empty (and emptied again after)."""
    monkeypatch.setattr(studies, "_LOOKUPS", {})


def test_create_with_the_identity_pending(sessions_dir, lookup, no_cached_lookup):
    lookup["found"] = None    # the lookup knows nothing; it is not consulted anyway
    assert create_study_step(NEW, None, _seen(), confirmed=False,
                             identity_pending=True) == {"id": NEW}
    folder = sessions_dir / NEW
    assert sorted(p.name for p in folder.iterdir()) == ["identity.json", "meta.json"]
    ident = json.loads((folder / "identity.json").read_text())
    assert set(ident) == {"dtxsid", "identity_source"} and ident["dtxsid"] == NEW
    assert ident["identity_source"]["kind"] == "pending"
    assert ident["identity_source"]["pending_since"]
    row = studies.study_row(NEW)
    assert row["kind"] == "study" and row["stands"]["phase"] == "EMPTY"
    assert row["identity"]["name"] is None and row["identity"]["casrn"] is None
    assert row["identity"]["source"]["kind"] == "pending"
    assert row["identity"]["source"]["casrn_from"] is None
    assert row["notes"] == [{"level": "warn", "code": "identity_pending",
                             "say": "The chemical's name and CAS number are pending: look it "
                                    "up when the service can be reached."}]
    chem = next(c for c in studies.list_studies()["chemicals"] if c["dtxsid"] == NEW)
    assert chem["name"] is None and chem["casrn"] is None and chem["primary"] == NEW


def test_a_pending_create_keeps_the_other_refusals(sessions_dir, lookup, no_cached_lookup):
    with pytest.raises(StudyRefusal) as e:
        create_study_step(f"{NEW}_v2", None, _seen(), confirmed=False, identity_pending=True)
    assert e.value.code == "study_id_has_suffix"
    with pytest.raises(StudyRefusal) as e:
        create_study_step(NEW, None, {"definition": "x", "hash": "0" * 16}, confirmed=False,
                          identity_pending=True)
    assert e.value.code == "format_changed"
    with pytest.raises(StudyRefusal) as e:   # pending, or an identity: not both
        create_study_step(NEW, _identity(), _seen(), confirmed=True, identity_pending=True)
    assert e.value.code == "bad_request" and e.value.status_code == 422
    assert not (sessions_dir / NEW).exists()
    create_study_step(NEW, None, _seen(), confirmed=False, identity_pending=True)
    with pytest.raises(StudyRefusal) as e:
        create_study_step(NEW, None, _seen(), confirmed=False, identity_pending=True)
    assert e.value.code == "study_exists"


def test_a_chemical_just_found_is_confirmed_not_left_pending(sessions_dir, no_cached_lookup,
                                                             monkeypatch):
    from ui_api.refusals import explain
    monkeypatch.setattr(studies.time, "monotonic", lambda: 1000.0)
    studies._LOOKUPS[NEW] = (990.0, {**json.loads(json.dumps(LOOKUP))})
    with pytest.raises(StudyRefusal) as e:
        create_study_step(NEW, None, _seen(), confirmed=False, identity_pending=True)
    assert e.value.code == "identity_unconfirmed"
    assert "Confirm it instead" in explain(e.value)["error"]["say"]
    assert not (sessions_dir / NEW).exists()
    # A compound the service found but does not list the DTXSID for may be left pending.
    studies._LOOKUPS[NEW][1]["dtxsid_matched"] = False
    create_study_step(NEW, None, _seen(), confirmed=False, identity_pending=True)
    assert (sessions_dir / NEW / "identity.json").is_file()
    # So may one looked up more than 10 minutes ago.
    monkeypatch.setattr(studies.time, "monotonic", lambda: 1000.0 + studies._LOOKUP_TTL_S)
    assert studies.cached_lookup(NEW) is None


def test_a_pending_identity_is_filled_later(sessions_dir, lookup, no_cached_lookup):
    create_study_step(NEW, None, _seen(), confirmed=False, identity_pending=True)
    record_identity_step(NEW, _identity(), confirmed=True)
    ident = json.loads((sessions_dir / NEW / "identity.json").read_text())
    assert ident["dtxsid"] == NEW and ident["name"] == "Bisphenol A"
    assert ident["casrn"] == "80-05-7" and ident["identity_source"]["kind"] == "lookup"
    assert "pending_since" not in ident["identity_source"]
    row = studies.study_row(NEW)
    assert row["identity"]["source"]["kind"] == "lookup" and row["notes"] == []
    with pytest.raises(StudyRefusal) as e:
        record_identity_step(NEW, _identity(), confirmed=True)
    assert e.value.code == "identity_exists"


def test_a_pending_identity_filled_from_a_lookup_with_no_casrn(sessions_dir, lookup,
                                                               no_cached_lookup):
    create_study_step(NEW, None, _seen(), confirmed=False, identity_pending=True)
    lookup["found"]["identity"]["casrn"] = None
    record_identity_step(NEW, _identity(casrn=None), confirmed=True)
    row = studies.study_row(NEW)
    assert row["identity"]["name"] == "Bisphenol A" and row["identity"]["casrn"] is None
    assert [n["code"] for n in row["notes"]] == ["casrn_pending"]


def test_a_pending_identity_still_cannot_be_filled_while_the_lookup_fails(sessions_dir, lookup,
                                                                          no_cached_lookup):
    create_study_step(NEW, None, _seen(), confirmed=False, identity_pending=True)
    lookup["found"] = None
    with pytest.raises(StudyRefusal) as e:
        record_identity_step(NEW, _identity(), confirmed=True)
    assert e.value.code == "identity_not_found"
    ident = json.loads((sessions_dir / NEW / "identity.json").read_text())
    assert ident["identity_source"]["kind"] == "pending"


def test_a_session_made_before_m1_without_a_name_is_noted(sessions_dir):
    _folder(sessions_dir, NEW, identity__json={"dtxsid": NEW})
    row = studies.study_row(NEW)
    assert row["identity"]["source"]["kind"] == "unknown"
    assert [n["code"] for n in row["notes"]] == ["identity_pending"]
    assert "not recorded" in row["notes"][0]["say"]


def test_no_identity_note_for_a_companion_a_report_or_an_id_with_no_chemical(sessions_dir):
    _folder(sessions_dir, "DTXSID8_published", published_clone__json={"twin": "DTXSID8"})
    _folder(sessions_dir, "DTXSID8", studies__json={"rat": "DTXSID8_rat"})
    _folder(sessions_dir, "DTXSID_TEST", meta__json={})
    for sid in ("DTXSID8_published", "DTXSID8", "DTXSID_TEST"):
        codes = [n["code"] for n in studies.study_row(sid)["notes"]]
        assert "identity_pending" not in codes and "casrn_pending" not in codes, sid


def test_the_casrn_check_digit():
    from ui_api.study_steps import _casrn_check_digit_holds
    for good in ("80-05-7", "41997-13-1", "106-46-7", "3380-34-5", "7732-18-5"):
        assert _casrn_check_digit_holds(good), good
    assert not _casrn_check_digit_holds("41997-13-2")


# ---------------------------------------------------------------------------
# Fill a missing identity
# ---------------------------------------------------------------------------

def _folder(root: Path, sid: str, **files) -> Path:
    d = root / sid
    d.mkdir(parents=True)
    for name, data in files.items():
        (d / name.replace("__", ".")).write_text(json.dumps(data))
    return d


def test_record_identity_fills_a_missing_one(sessions_dir, lookup):
    d = _folder(sessions_dir, f"{NEW}_nb", meta__json={"dtxsid": NEW},
                identity__json={"abbreviation": "BPA"})
    record_identity_step(f"{NEW}_nb", _identity(), confirmed=True)
    ident = json.loads((d / "identity.json").read_text())
    assert ident["name"] == "Bisphenol A" and ident["abbreviation"] == "BPA"
    assert ident["dtxsid"] == f"{NEW}_nb"


def test_record_identity_refusals(sessions_dir, lookup):
    with pytest.raises(StudyRefusal) as e:
        record_identity_step(NEW, _identity(), confirmed=True)
    assert e.value.code == "study_not_found"
    _folder(sessions_dir, NEW, identity__json={"name": "Bisphenol A"})
    with pytest.raises(StudyRefusal) as e:
        record_identity_step(NEW, _identity(), confirmed=True)
    assert e.value.code == "identity_exists"
    _folder(sessions_dir, "DTXSID8_published", published_clone__json={"twin": "DTXSID8"})
    with pytest.raises(StudyRefusal) as e:
        record_identity_step("DTXSID8_published", _identity(), confirmed=True)
    assert e.value.code == "read_only_session"
    _folder(sessions_dir, "DTXSID_TEST", meta__json={})
    with pytest.raises(StudyRefusal) as e:
        record_identity_step("DTXSID_TEST", _identity(), confirmed=True)
    assert e.value.code == "invalid_study_id"


def test_simultaneous_identity_fills_give_one_success(sessions_dir, monkeypatch):
    """F4: three people save the identity at once. All three pass the first
    check (the lookup holds them until all have), so only the per-study lock
    keeps the check-then-write atomic: one fills it, two are refused
    identity_exists, no server error, no temp file left behind."""
    import threading

    d = _folder(sessions_dir, f"{NEW}_nb", meta__json={"dtxsid": NEW},
                identity__json={"abbreviation": "BPA"})
    gate = threading.Barrier(3, timeout=10)

    def held_lookup(dtxsid, *, fresh=False):
        gate.wait()
        return {**json.loads(json.dumps(LOOKUP)), "dtxsid": dtxsid}

    monkeypatch.setattr(studies, "lookup_chemical", held_lookup)
    results: list = []

    def save():
        try:
            results.append(record_identity_step(f"{NEW}_nb", _identity(), confirmed=True))
        except StudyRefusal as exc:
            results.append(exc.code)
        except Exception as exc:   # the failure F4 found: a FileNotFoundError
            results.append(repr(exc))

    threads = [threading.Thread(target=save) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    assert sorted(map(str, results)) == sorted(
        [str({"id": f"{NEW}_nb"}), "identity_exists", "identity_exists"]), results
    ident = json.loads((d / "identity.json").read_text())
    assert ident["name"] == "Bisphenol A" and ident["abbreviation"] == "BPA"
    assert not [p for p in d.iterdir() if p.name.endswith(".tmp")]


def test_record_identity_on_a_study_deleted_meanwhile(sessions_dir, lookup, monkeypatch):
    """The study is deleted (renamed away) between the checks and the write:
    study_not_found, and nothing is written where it was."""
    from ui_api import study_steps

    d = _folder(sessions_dir, f"{NEW}_nb", meta__json={"dtxsid": NEW})
    real = study_steps._confirmed_identity

    def then_deleted(*a, **k):
        out = real(*a, **k)
        d.rename(sessions_dir / ".deleting-x")
        return out

    monkeypatch.setattr(study_steps, "_confirmed_identity", then_deleted)
    with pytest.raises(StudyRefusal) as e:
        record_identity_step(f"{NEW}_nb", _identity(), confirmed=True)
    assert e.value.code == "study_not_found" and e.value.status_code == 404
    assert not d.exists()


# ---------------------------------------------------------------------------
# Delete: the dry run, then the act
# ---------------------------------------------------------------------------

@pytest.fixture
def study(sessions_dir, output_dir):
    """A study with files, a dataset, statements, a pin, two sections (one
    approved), history, and deliverables in output/."""
    d = _folder(sessions_dir, "DTXSID5032498",
                identity__json={"name": "Triclosan", "casrn": "3380-34-5"},
                meta__json={"dtxsid": "DTXSID5032498"},
                integrated__json={}, study_design__json={}, front_matter__json={},
                method_profile__json={"name": "ntp-5day-2025", "mode": "track"},
                **{"bm2_body-weight__json": {"title": "Body Weight", "approved": True},
                   "summary__json": {"approved": False}})
    (d / "files").mkdir()
    (d / "files" / "a.txt").write_text("x")
    (d / "files" / "b.bm2").write_text("y")
    (d / "_originals").mkdir()
    (d / "_originals" / "a.xlsx").write_text("z")
    (d / "_cache_ntp_0.json").write_text("{}")
    (d / "history").mkdir()
    (d / "history" / "summary_v1.json").write_text("{}")
    (output_dir / "DTXSID5032498").mkdir()
    (output_dir / "DTXSID5032498" / "report.docx").write_text("doc")
    return d


def test_the_dry_run_lists_what_goes_and_what_stays(study):
    before = sorted(str(p) for p in study.rglob("*"))
    out = delete_study_dry_run("DTXSID5032498")
    assert sorted(str(p) for p in study.rglob("*")) == before     # read only
    c = out["confirm"]
    assert c["act"] == "delete_study" and c["strength"] == "irreversible"
    assert c["reason_required"] is False
    whats = [d["what"] for d in c["deletes"]]
    assert whats[:2] == ["files", "sections"]
    assert {"dataset", "statements", "identity", "pins", "history"} <= set(whats)
    files = c["deletes"][0]["say"]
    assert "2 data files" in files and "1 original" in files
    assert c["approvals_lost"] == ["Body Weight"]
    # The study's own definition (templates/studies/DTXSID5032498/) is kept too.
    assert [k["what"] for k in c["keeps"]] == ["output", "study_definition"]
    assert "output/DTXSID5032498/ (1 file)" in c["keeps"][0]["say"]
    assert c["cost"]["say"].endswith("will be freed.")
    assert out["type_to_confirm"] == "DTXSID5032498"
    assert out["preview_token"].startswith("sha256:")
    assert delete_study_dry_run("DTXSID5032498")["preview_token"] == out["preview_token"]


def test_the_dry_run_refusals(sessions_dir):
    with pytest.raises(StudyRefusal) as e:
        delete_study_dry_run("DTXSID404")
    assert e.value.code == "study_not_found"
    assert not (sessions_dir / "DTXSID404").exists()
    _folder(sessions_dir, "DTXSID1", studies__json={"rat": "DTXSID1_rat"})
    _folder(sessions_dir, "DTXSID1_rat", meta__json={})
    with pytest.raises(StudyRefusal) as e:
        delete_study_dry_run("DTXSID1_rat")
    assert e.value.code == "member_of_report" and e.value.details["parent"] == "DTXSID1"
    _folder(sessions_dir, "DTXSID1_published", published_clone__json={"twin": "DTXSID1"})
    with pytest.raises(StudyRefusal) as e:
        delete_study_dry_run("DTXSID1_published")
    assert e.value.code == "read_only_session"


def test_a_report_keeps_its_studies(sessions_dir, output_dir):
    _folder(sessions_dir, "DTXSID1", studies__json={"rat": "DTXSID1_rat"}, identity__json={})
    _folder(sessions_dir, "DTXSID1_rat", meta__json={})
    c = delete_study_dry_run("DTXSID1")["confirm"]
    assert c["deletes"][0]["what"] == "report"
    assert {"what": "member", "say": "The rat study DTXSID1_rat"} in c["keeps"]


def test_delete_removes_the_folder_and_keeps_the_deliverables(study, output_dir):
    from pipeline.pool_globals import get_integrated_pool, get_pool_fingerprints
    get_integrated_pool()["DTXSID5032498"] = {}
    get_pool_fingerprints()["DTXSID5032498"] = {}
    token = delete_study_dry_run("DTXSID5032498")["preview_token"]
    out = delete_study_step("DTXSID5032498", "  DTXSID5032498 ", token)
    assert out["deleted"] == "DTXSID5032498" and out["say"] == "DTXSID5032498 was deleted."
    assert out["kept"][0]["what"] == "output"
    assert not study.exists()
    assert not [p for p in study.parent.iterdir() if p.name.startswith(".deleting")]
    assert (output_dir / "DTXSID5032498" / "report.docx").is_file()
    assert "DTXSID5032498" not in get_integrated_pool()
    assert "DTXSID5032498" not in get_pool_fingerprints()


@pytest.mark.parametrize("typed", ["dtxsid5032498", "DTXSID503249", "", "DTXSID5032498x"])
def test_delete_refuses_a_typed_id_that_does_not_match(study, typed):
    token = delete_study_dry_run("DTXSID5032498")["preview_token"]
    with pytest.raises(StudyRefusal) as e:
        delete_study_step("DTXSID5032498", typed, token)
    assert e.value.code == "confirm_mismatch" and e.value.status_code == 400
    assert study.is_dir()


def test_delete_refuses_after_a_change(study):
    token = delete_study_dry_run("DTXSID5032498")["preview_token"]
    (study / "files" / "c.txt").write_text("new file")
    with pytest.raises(StudyRefusal) as e:
        delete_study_step("DTXSID5032498", "DTXSID5032498", token)
    assert e.value.code == "changed_since_preview"
    assert study.is_dir()


def test_delete_refuses_a_member_even_with_a_token(sessions_dir):
    _folder(sessions_dir, "DTXSID1", studies__json={"rat": "DTXSID1_rat"})
    _folder(sessions_dir, "DTXSID1_rat", meta__json={})
    with pytest.raises(StudyRefusal) as e:
        delete_study_step("DTXSID1_rat", "DTXSID1_rat", "sha256:anything")
    assert e.value.code == "member_of_report"
    assert (sessions_dir / "DTXSID1_rat").is_dir()


def test_the_request_log_does_not_change_the_token(study):
    """A refused delete appends to the request log (.provenance.jsonl); the
    retry that follows must still be accepted."""
    token = delete_study_dry_run("DTXSID5032498")["preview_token"]
    (study / ".provenance.jsonl").write_text('{"event": "step_error"}\n')
    assert delete_study_dry_run("DTXSID5032498")["preview_token"] == token
    delete_study_step("DTXSID5032498", "DTXSID5032498", token)
    assert not study.exists()


# ---------------------------------------------------------------------------
# Delete races (F3): a folder that vanishes under the dry run or the delete
# ---------------------------------------------------------------------------

def _deleted_while_walking(monkeypatch, folder: Path, *, raise_after: bool):
    """The dry run's section read replaced: the folder is renamed away (another
    request deleted it) in the middle of the walk; then the walk fails as the
    real one did (FileNotFoundError) or carries on over nothing."""
    import ui_api.read_model as rm

    def walk(dtxsid, store=None):
        folder.rename(folder.parent / f".deleting-{dtxsid}-other")
        if raise_after:
            raise FileNotFoundError(str(folder / "narrative_runs" / "summary" / "r1.json"))
        return {"sections": []}

    monkeypatch.setattr(rm, "study_state", walk)


@pytest.mark.parametrize("raise_after", [True, False])
def test_a_dry_run_of_a_folder_deleted_meanwhile_is_not_found(study, monkeypatch, raise_after):
    _deleted_while_walking(monkeypatch, study, raise_after=raise_after)
    with pytest.raises(StudyRefusal) as e:
        delete_study_dry_run("DTXSID5032498")
    assert e.value.code == "study_not_found" and e.value.status_code == 404


def test_a_dry_run_failing_on_a_folder_still_there_is_not_hidden(study, monkeypatch):
    """Only a vanished folder becomes study_not_found; any other failure stays."""
    import ui_api.read_model as rm

    def broken(dtxsid, store=None):
        raise FileNotFoundError("something else")

    monkeypatch.setattr(rm, "study_state", broken)
    with pytest.raises(FileNotFoundError):
        delete_study_dry_run("DTXSID5032498")


def test_the_second_of_two_deletes_is_not_found(study, monkeypatch):
    """A double click: the second request opens the study, then waits for the
    lock while the first deletes it. Forced: the second request's wait for
    the lock runs the whole first delete."""
    import fcntl

    token = delete_study_dry_run("DTXSID5032498")["preview_token"]
    real_flock = fcntl.flock
    first: list = []

    def flock_after_the_other_deleted(fd, op):
        if not first:
            monkeypatch.setattr(fcntl, "flock", real_flock)
            first.append(delete_study_step("DTXSID5032498", "DTXSID5032498", token))
        return real_flock(fd, op)

    monkeypatch.setattr(fcntl, "flock", flock_after_the_other_deleted)
    with pytest.raises(StudyRefusal) as e:
        delete_study_step("DTXSID5032498", "DTXSID5032498", token)
    assert first and first[0]["deleted"] == "DTXSID5032498"
    assert e.value.code == "study_not_found" and e.value.status_code == 404
    assert not study.exists()
    assert not [p for p in study.parent.iterdir() if p.name.startswith(".deleting")]


def test_a_delete_whose_folder_vanishes_at_the_rename_is_not_found(study, monkeypatch):
    """A route that takes no lock removed the folder after the checks."""
    from ui_api import study_steps

    token = delete_study_dry_run("DTXSID5032498")["preview_token"]
    real = study_steps.delete_study_dry_run

    def then_removed(dtxsid):
        out = real(dtxsid)
        import shutil
        shutil.rmtree(study)
        return out

    monkeypatch.setattr(study_steps, "delete_study_dry_run", then_removed)
    with pytest.raises(StudyRefusal) as e:
        delete_study_step("DTXSID5032498", "DTXSID5032498", token)
    assert e.value.code == "study_not_found"


# ---------------------------------------------------------------------------
# The old full reset (F2): the same rule as the delete
# ---------------------------------------------------------------------------

def test_reset_refuses_what_the_delete_refuses(sessions_dir, monkeypatch):
    from ui_api.study_steps import reset_session_step

    _folder(sessions_dir, "DTXSID1", studies__json={"rat": "DTXSID1_rat"})
    _folder(sessions_dir, "DTXSID1_rat", meta__json={})
    _folder(sessions_dir, "DTXSID1_published", published_clone__json={"twin": "DTXSID1"})
    for sid, code in (("DTXSID1_rat", "member_of_report"),
                      ("DTXSID1_published", "read_only_session")):
        with pytest.raises(StudyRefusal) as e:
            reset_session_step(sid)
        assert e.value.code == code and e.value.status_code == 409
        assert (sessions_dir / sid).is_dir()
        with pytest.raises(StudyRefusal) as d:
            delete_study_dry_run(sid)
        assert d.value.code == code


def test_reset_refuses_a_run_in_flight(sessions_dir, monkeypatch):
    from ui_api.study_steps import reset_session_step

    _folder(sessions_dir, "DTXSID2", meta__json={})
    monkeypatch.setattr(studies, "running_since", lambda sid: "2026-10-15T12:00:00Z")
    with pytest.raises(StudyRefusal) as e:
        reset_session_step("DTXSID2")
    assert e.value.code == "run_in_flight"
    assert e.value.details == {"started_at": "2026-10-15T12:00:00Z"}
    assert (sessions_dir / "DTXSID2").is_dir()


def test_reset_removes_a_study_and_forgets_it(sessions_dir):
    from pipeline.pool_globals import get_integrated_pool
    from ui_api.study_steps import reset_session_step

    d = _folder(sessions_dir, "DTXSID2_nb", meta__json={})
    get_integrated_pool()["DTXSID2_nb"] = {}
    assert reset_session_step("DTXSID2_nb") == {"deleted": "DTXSID2_nb"}
    assert not d.exists() and "DTXSID2_nb" not in get_integrated_pool()
    assert not [p for p in sessions_dir.iterdir() if p.name.startswith(".deleting")]
    with pytest.raises(StudyRefusal) as e:
        reset_session_step("DTXSID2_nb")
    assert e.value.code == "study_not_found"


# ---------------------------------------------------------------------------
# The dialog's words (F5)
# ---------------------------------------------------------------------------

def test_a_section_with_no_name_is_named_plainly(study):
    """bm2_unknown.json (Process names a table "unknown" when its endpoints
    match no data type) is not listed as "unknown"."""
    (study / "bm2_unknown.json").write_text(json.dumps(
        {"platform": "unknown", "title": "unknown", "approved": True}))
    c = delete_study_dry_run("DTXSID5032498")["confirm"]
    sections = next(d["say"] for d in c["deletes"] if d["what"] == "sections")
    assert "an unnamed result section saved as bm2_unknown" in sections
    assert "Body Weight" in sections and "(Body Weight, unknown" not in sections
    assert ", unknown," not in sections
    assert "An unnamed result section saved as bm2_unknown" in c["approvals_lost"]


def test_the_dry_run_always_says_what_stays(sessions_dir, output_dir):
    _folder(sessions_dir, "DTXSID3", identity__json={"name": "X"}, meta__json={})
    c = delete_study_dry_run("DTXSID3")["confirm"]
    assert c["keeps"] == [{"what": "nothing_else", "say": "Nothing outside the study is affected"}]
