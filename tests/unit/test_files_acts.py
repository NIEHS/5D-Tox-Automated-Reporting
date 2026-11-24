"""Bringing a study's data files in, over HTTP (module M2).

The batch is one act. These tests go through the route, because the shape the
page reads — the plan, the counts, the refusal envelope — is what matters, and
the browser sends a multipart body, not a dict.
"""

import io
import json

import pytest

DTX = "DTXSID9000077"
WIDE = b"Dose\tBody Weight\n0\t188.1\n"
PER_ANIMAL = b"Animal ID\tDose\tSD0\n1\t0\t188.1\n"

FILES = f"/api/v2/studies/{DTX}/files"


@pytest.fixture
def study(sessions_dir):
    d = sessions_dir / DTX
    (d / "files").mkdir(parents=True)
    (d / "identity.json").write_text(json.dumps({"name": "Test chemical", "dtxsid": DTX}))
    return d


def send(client, *files, **form):
    """A multipart batch, as a browser sends it."""
    parts = [("files", (name, io.BytesIO(content), "application/octet-stream"))
             for name, content in files]
    if "answers" in form:
        form["answers"] = json.dumps(form["answers"])
    return client.post(FILES, files=parts, data={k: str(v) for k, v in form.items()})


def row(body, name):
    return next(r for r in body["rows"] if r["name"] == name)


# ---------------------------------------------------------------------------
# The working path
# ---------------------------------------------------------------------------

def test_the_files_are_brought_in_and_the_page_is_told_what_happened(client, study):
    r = send(client, ("body_weight.txt", WIDE), ("organ_weights.txt", b"Dose\tLiver\n0\t9.9\n"))
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["applied"] is True
    assert sorted(body["brought_in"]) == ["body_weight.txt", "organ_weights.txt"]
    assert body["counts"]["add"] == 2
    assert sorted(p.name for p in (study / "files").iterdir()) == [
        "body_weight.txt", "organ_weights.txt"]
    # The page's next read is against the files as they are now.
    assert body["files_token"].startswith("sha256:")


def test_a_file_that_is_not_study_data_is_refused_in_words(client, study):
    r = send(client, ("notes.pdf", b"%PDF-1.4"), ("body_weight.txt", WIDE))
    body = r.json()

    refused = row(body, "notes.pdf")
    assert refused["verdict"] == "refused" and refused["code"] == "file_type_refused"
    assert "not a data file" in refused["say"]
    # The rest of the batch still came in: a refusal is per file.
    assert body["brought_in"] == ["body_weight.txt"]


def test_a_batch_of_nothing_usable_brings_nothing_in(client, study):
    r = send(client, ("notes.pdf", b"%PDF-1.4"))
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "batch_refused"
    assert list((study / "files").iterdir()) == []


def test_no_files_sent_is_said_rather_than_crashing(client, study):
    r = client.post(FILES, data={})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "no_files_sent"


# ---------------------------------------------------------------------------
# What waits on a person
# ---------------------------------------------------------------------------

def test_nothing_is_brought_in_while_one_file_waits_on_an_answer(client, study):
    (study / "files" / "body_weight.txt").write_bytes(WIDE)

    r = send(client, ("body_weight.txt", b"Dose\tBody Weight\n0\t999\n"),
             ("organ_weights.txt", b"Dose\tLiver\n0\t9.9\n"))
    assert r.status_code == 409
    error = r.json()["error"]
    assert error["code"] == "answer_required"
    assert "the batch is one act" in error["say"]
    # The plan comes back, so the answer is given against what was found.
    waiting = next(one for one in error["details"]["rows"] if one["needs_answer"])
    assert waiting["name"] == "body_weight.txt" and waiting["verdict"] == "replace"
    assert (study / "files" / "body_weight.txt").read_bytes() == WIDE
    assert not (study / "files" / "organ_weights.txt").exists()


def test_the_answer_brings_the_whole_batch_in(client, study):
    (study / "files" / "body_weight.txt").write_bytes(WIDE)

    r = send(client, ("body_weight.txt", b"Dose\tBody Weight\n0\t999\n"),
             answers={"replace": ["body_weight.txt"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["replaced"] == ["body_weight.txt"]
    assert (study / "files" / "body_weight.txt").read_bytes().endswith(b"999\n")
    # The old one is kept, not overwritten.
    assert [p for p in (study / "_removed").rglob("body_weight.txt")]


def test_a_per_animal_table_without_units_waits_on_an_answer(client, study):
    r = send(client, ("hormones.csv", PER_ANIMAL))
    assert r.status_code == 409
    rows = r.json()["error"]["details"]["rows"]
    assert rows[0]["needs_answer"] == "without_units"
    assert "[units pending]" in rows[0]["say"]


def test_a_units_file_comes_in_with_its_table(client, study):
    units = json.dumps({"Body Weight": "grams"}).encode()
    r = send(client, ("hormones.csv", PER_ANIMAL), ("hormones.units.json", units))
    assert r.status_code == 200, r.text
    assert sorted(r.json()["brought_in"]) == ["hormones.csv", "hormones.units.json"]


# ---------------------------------------------------------------------------
# Nothing is written by a plan
# ---------------------------------------------------------------------------

def test_a_dry_run_says_what_would_happen_and_writes_nothing(client, study):
    r = send(client, ("body_weight.txt", WIDE), dry_run=True)
    body = r.json()

    assert body["applied"] is False and body["dry_run"] is True
    assert body["counts"]["add"] == 1
    assert row(body, "body_weight.txt")["verdict"] == "add"
    assert list((study / "files").iterdir()) == []


def test_a_batch_sent_against_files_that_changed_is_refused(client, study):
    r = send(client, ("body_weight.txt", WIDE), files_token="sha256:not-the-one")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "files_changed"
    assert list((study / "files").iterdir()) == []


def test_the_scratch_folder_does_not_stay_behind(client, study):
    send(client, ("body_weight.txt", WIDE))
    assert [p.name for p in study.iterdir() if p.name.startswith("_intake_")] == []


def test_a_name_with_a_path_in_it_cannot_write_outside_the_study(client, study):
    send(client, ("../../escaped.txt", WIDE))
    assert not (study.parent.parent / "escaped.txt").exists()
    assert [p.name for p in (study / "files").iterdir()] == ["escaped.txt"]


def test_a_study_that_does_not_exist_is_refused(client, sessions_dir):
    r = client.post("/api/v2/studies/DTXSID9000088/files",
                    files=[("files", ("a.txt", io.BytesIO(WIDE), "text/plain"))])
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "study_not_found"


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------

def _events(lines):
    return [json.loads(line) for line in lines if line.strip()]


def test_the_check_runs_as_one_told_act(client, study, monkeypatch):
    import safeguards.guarded as guarded

    (study / "files" / "body_weight.txt").write_bytes(WIDE)
    report = {"dtxsid": DTX, "fingerprints": {}, "issues": [
        {"severity": "warning", "issue_type": "redundant_files",
         "message": "two files hold the same data", "files_involved": []}]}
    monkeypatch.setattr(guarded, "validate_step", lambda dtxsid, store: report)

    with client.stream("POST", f"/api/v2/studies/{DTX}/check") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/x-ndjson")
        events = _events(r.iter_lines())

    assert events[0] == {"event": "step", "unit": "check", "status": "computing",
                         "say": "Checking the study's files"}
    assert events[-1]["event"] == "result" and events[-1]["ok"] is True
    assert events[-1]["summary"]["look"] == 1


def test_the_check_is_refused_on_a_study_with_no_files(client, study):
    with client.stream("POST", f"/api/v2/studies/{DTX}/check") as r:
        r.read()
        assert r.status_code == 404
        assert json.loads(r.text)["error"]["code"] == "no_files"
