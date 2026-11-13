"""The full session reset (POST /api/session/reset/{id}) removes a session's
folder only when a person may delete it (safeguards.acts.require_deletable):
never a published book's companion, never one of the studies a report
composes; a report session may go, and its studies stay."""

import json

import pytest

from safeguards.acts import require_deletable
from safeguards.refusals import StudyRefusal, explain


@pytest.fixture
def store(sessions_dir):
    def folder(sid, **files):
        d = sessions_dir / sid
        d.mkdir(parents=True)
        (d / "meta.json").write_text("{}")
        for name, data in files.items():
            (d / name).write_text(json.dumps(data))
        return d
    folder("DTXSID1", **{"studies.json": {"rat": "DTXSID1_rat", "mouse": "DTXSID1_mouse"}})
    folder("DTXSID1_rat")
    folder("DTXSID1_mouse")
    folder("DTXSID2")
    folder("DTXSID2_published", **{"published_clone.json": {"twin": "DTXSID2"}})
    return sessions_dir


def test_the_rule(store):
    require_deletable("DTXSID2")                     # a study
    require_deletable("DTXSID1")                     # a report: its studies stay
    with pytest.raises(StudyRefusal) as e:
        require_deletable("DTXSID2_published")
    assert e.value.code == "read_only_session"
    with pytest.raises(StudyRefusal) as e:
        require_deletable("DTXSID1_rat")
    body = explain(e.value)["error"]
    assert body["code"] == "member_of_report" and body["fix"] == "study"
    assert body["details"] == {"parent": "DTXSID1", "key": "rat", "species": "rat"}
    assert body["say"] == ("This is the rat study of the report DTXSID1. "
                           "Deleting it would break that report.")


@pytest.mark.integration
def test_the_route_refuses_a_member_and_a_companion(store, client):
    for sid, code in (("DTXSID1_mouse", "member_of_report"),
                      ("DTXSID2_published", "read_only_session")):
        r = client.post(f"/api/session/reset/{sid}")
        assert r.status_code == 409 and r.json()["code"] == code and r.json()["say"]
        assert (store / sid).is_dir()


@pytest.mark.integration
def test_the_route_deletes_a_report_and_keeps_its_studies(store, client):
    r = client.post("/api/session/reset/DTXSID1")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert not (store / "DTXSID1").exists()
    assert (store / "DTXSID1_rat").is_dir() and (store / "DTXSID1_mouse").is_dir()


@pytest.mark.integration
def test_the_route_deletes_a_study(store, client):
    assert client.post("/api/session/reset/DTXSID2").status_code == 200
    assert not (store / "DTXSID2").exists()
    assert (store / "DTXSID2_published").is_dir()
