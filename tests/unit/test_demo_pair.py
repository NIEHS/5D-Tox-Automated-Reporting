"""ui_api.demo and ui_api.runs: a finished report and its live copy, as the
new interface sees them; and the record of a long act under way."""

import json

import pytest

from tooling import demo_copy

REPORT = "DTXSID0000777"


def _write(folder, name, content="{}"):
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content))


@pytest.fixture
def pair(sessions_dir):
    report = sessions_dir / REPORT
    _write(report, "studies.json", {"rat": f"{REPORT}_rat"})
    _write(report, "identity.json", {"name": "X", "dtxsid": REPORT})
    study = sessions_dir / f"{REPORT}_rat"
    _write(study, "files/data.txt", "doses")
    _write(study, "_fingerprints.json")
    _write(study, "validation_report.json")
    _write(study, "identity.json", {"name": "X", "dtxsid": REPORT})
    _write(sessions_dir / "DTXSID0000888", "identity.json", {"name": "Y"})
    demo_copy.make(REPORT)
    return sessions_dir


def test_each_side_of_the_pair_knows_its_role_and_its_counterpart(pair):
    from ui_api.demo import pair_of

    assert pair_of(REPORT) == {"partition": "Demo", "role": "finished",
                               "counterpart": f"{REPORT}_live", "counterpart_exists": True,
                               "report": REPORT}
    assert pair_of(f"{REPORT}_live_rat") == {
        "partition": "Demo", "role": "live", "counterpart": f"{REPORT}_rat",
        "counterpart_exists": True, "report": f"{REPORT}_live"}
    assert pair_of(f"{REPORT}_rat")["counterpart"] == f"{REPORT}_live_rat"
    assert pair_of("DTXSID0000888") is None


def test_the_state_carries_the_pair_and_the_list_sets_it_apart(pair):
    from ui_api.read_model import study_state
    from ui_api.studies import list_studies

    assert study_state(f"{REPORT}_live")["demo"]["role"] == "live"
    assert "demo" not in study_state("DTXSID0000888")
    listing = list_studies()
    [demo] = listing["partitions"]
    assert demo["name"] == "Demo"
    assert [(e["id"], e["role"], [m["id"] for m in e["members"]]) for e in demo["sessions"]] == [
        (REPORT, "finished", [f"{REPORT}_rat"]),
        (f"{REPORT}_live", "live", [f"{REPORT}_live_rat"])]
    listed = [s["id"] for c in listing["chemicals"] for s in c["sessions"]]
    assert listed == ["DTXSID0000888"]  # the pair is not listed twice


def test_the_finished_side_is_left_as_it_is(pair):
    from ui_api.demo import require_not_reference
    from ui_api.refusals import explain
    from ui_api.studies import StudyRefusal

    require_not_reference(f"{REPORT}_live_rat")
    require_not_reference("DTXSID0000888")
    with pytest.raises(StudyRefusal) as e:
        require_not_reference(f"{REPORT}_rat")
    body = explain(e.value)["error"]
    assert (body["code"], body["status"]) == ("demo_reference", 409)
    assert f"{REPORT}_live_rat" in body["say"] and "you" not in body["say"].lower().split()


def test_reset_puts_the_copy_back_and_is_refused_during_a_run(pair):
    from ui_api import runs
    from ui_api.demo import reset_live_copy
    from ui_api.read_model import study_state
    from ui_api.studies import StudyRefusal

    live = pair / f"{REPORT}_live_rat"
    _write(live, "integrated.json")
    with runs.running(f"{REPORT}_live_rat", "Process"):
        assert study_state(f"{REPORT}_live_rat")["run"]["what"] == "Process"
        with pytest.raises(StudyRefusal) as e:
            reset_live_copy(REPORT)
        assert e.value.code == "run_in_flight"
        with pytest.raises(StudyRefusal):
            with runs.running(f"{REPORT}_live_rat", "integration"):
                pass
    assert (live / "integrated.json").exists()
    assert study_state(f"{REPORT}_live_rat")["run"]["in_flight"] is False
    reset_live_copy(REPORT)
    assert not (live / "integrated.json").exists() and (live / "files" / "data.txt").exists()
    with pytest.raises(StudyRefusal) as e:
        reset_live_copy("DTXSID0000888")
    assert e.value.code == "demo_copy_refused"


def test_the_reset_route_answers_in_the_envelope(pair):
    from fastapi.testclient import TestClient
    from web_routes.background_server import app

    client = TestClient(app)
    ok = client.post(f"/api/v2/demo/{REPORT}/reset")
    assert ok.status_code == 200 and ok.json()["copy"] == f"{REPORT}_live"
    no = client.post("/api/v2/demo/DTXSID0000888/reset")
    assert no.status_code == 409 and no.json()["error"]["code"] == "demo_copy_refused"
