"""Bringing a batch of files into a study (workflow.steps.bring_in_step).

The step carries out what pipeline.intake planned: it writes only what was
accepted, writes nothing at all while a row still waits on an answer, and a
file it replaces is kept rather than overwritten.
"""

import pytest

from workflow.store import DiskPoolStore
from workflow.errors import StepError
from workflow.steps import bring_in_step

WIDE = "Dose\tBody Weight\n0\t188.1\n"


@pytest.fixture
def study(sessions_dir, tmp_path):
    (sessions_dir / "DTXSID9000001" / "files").mkdir(parents=True)
    batch = tmp_path / "batch"
    batch.mkdir()
    return sessions_dir / "DTXSID9000001", batch


def run(batch, **kw):
    return bring_in_step("DTXSID9000001", batch, DiskPoolStore(), **kw)


def files_of(session):
    return sorted(p.name for p in (session / "files").iterdir())


def test_the_files_the_plan_accepted_are_brought_in(study):
    session, batch = study
    (batch / "body_weight.txt").write_text(WIDE)
    (batch / "organ_weights.txt").write_text("Dose\tLiver\n0\t9.9\n")

    out = run(batch)
    assert out["applied"] is True
    assert out["brought_in"] == ["body_weight.txt", "organ_weights.txt"]
    assert files_of(session) == ["body_weight.txt", "organ_weights.txt"]
    # Nothing is left behind in the batch.
    assert list(batch.iterdir()) == []


def test_a_refused_file_is_not_written_into_the_study(study):
    session, batch = study
    (batch / "notes.pdf").write_bytes(b"%PDF-1.4")
    (batch / "body_weight.txt").write_text(WIDE)

    out = run(batch)
    assert out["brought_in"] == ["body_weight.txt"]
    assert files_of(session) == ["body_weight.txt"]
    assert out["counts"]["refused"] == 1


def test_nothing_is_brought_in_while_a_row_waits_on_an_answer(study):
    session, batch = study
    (session / "files" / "body_weight.txt").write_text(WIDE)
    (batch / "body_weight.txt").write_text("Dose\tBody Weight\n0\t999\n")
    (batch / "organ_weights.txt").write_text("Dose\tLiver\n0\t9.9\n")

    out = run(batch)
    assert out["applied"] is False
    assert out["counts"]["needs_answer"] == 1
    # Not even the file nobody had to answer for: the batch is one act.
    assert (session / "files" / "body_weight.txt").read_text() == WIDE
    assert files_of(session) == ["body_weight.txt"]


def test_a_replaced_file_is_kept_among_the_removed_files(study):
    session, batch = study
    (session / "files" / "body_weight.txt").write_text(WIDE)
    (batch / "body_weight.txt").write_text("Dose\tBody Weight\n0\t999\n")

    out = run(batch, answers={"replace": ["body_weight.txt"]})
    assert out["applied"] is True and out["replaced"] == ["body_weight.txt"]
    assert (session / "files" / "body_weight.txt").read_text().endswith("999\n")

    kept = [p for p in (session / "_removed").rglob("body_weight.txt")]
    assert len(kept) == 1 and kept[0].read_text() == WIDE


def test_what_a_person_said_a_replaced_file_was_goes_with_it(study):
    session, batch = study
    (session / "files" / "hormones.txt").write_text(WIDE)
    from pipeline.classifications import read as read_statements
    from pipeline.classifications import state
    state(session, "hormones.txt", "Hormones", "tox_study", "table")

    (batch / "hormones.txt").write_text("Dose\tT4\n0\t2.2\n")
    run(batch, answers={"replace": ["hormones.txt"]})

    assert "hormones.txt" not in read_statements(session)


def test_a_dry_run_plans_and_carries_nothing_out(study):
    session, batch = study
    (batch / "body_weight.txt").write_text(WIDE)

    out = run(batch, apply=False)
    assert out["applied"] is False
    assert out["counts"]["add"] == 1
    assert out["rows"][0]["verdict"] == "add"
    assert files_of(session) == []
    assert (batch / "body_weight.txt").exists()


def test_a_study_that_does_not_exist_is_refused(sessions_dir, tmp_path):
    with pytest.raises(StepError) as raised:
        bring_in_step("DTXSID9000002", tmp_path, DiskPoolStore())
    assert raised.value.status_code == 404
