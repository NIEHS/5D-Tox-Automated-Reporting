"""
C1 on the command line (tooling/generate_report.py): a refusal prints the
backend's message and, under it, the plain-words advice; a study whose method
profile no person chose needs --method-profile, and the run names the profile
it suggests (D1 = B). Nothing is pinned for the person.
"""

from __future__ import annotations

import json

import pytest


def test_method_profile_is_required_until_a_person_chooses_one(sessions_dir):
    from pipeline import method_profile as mp
    from tooling.generate_report import _require_method_choice, method_profile

    (sessions_dir / "DTXSIDX").mkdir()
    with pytest.raises(SystemExit) as ei:
        _require_method_choice("DTXSIDX")
    msg = str(ei.value)
    assert msg.startswith("--method-profile is needed: no one has chosen the analysis "
                          "method for DTXSIDX yet")
    assert f"Suggested: --method-profile {mp.newest_profile()}" in msg
    assert not (sessions_dir / "DTXSIDX" / mp.PIN_FILE).exists()

    mp.pin_profile("DTXSIDX", "newest", by="default")           # an old default pin
    with pytest.raises(SystemExit) as ei:
        _require_method_choice("DTXSIDX")
    assert "(its current one was set by default)" in str(ei.value)

    method_profile("DTXSIDX", "ntp-5day-2021")                  # a person's choice
    assert mp.read_pin("DTXSIDX")["pinned_by"] == "user"
    _require_method_choice("DTXSIDX")                           # kept, no question
    method_profile("DTXSIDX", None)


def test_a_refusal_prints_the_message_and_the_plain_words(sessions_dir, monkeypatch, capsys):
    import tooling.generate_report as gr

    monkeypatch.setattr(gr, "_bootstrap_env", lambda: None)
    d = sessions_dir / "DTXSIDY"
    (d / "files").mkdir(parents=True)
    (d / "files" / "bw.csv").write_text("x")
    (d / "validation_report.json").write_text(json.dumps({"issues": [], "coverage_matrix": {}}))
    monkeypatch.setattr(gr, "validate", lambda dtxsid, store: None)
    monkeypatch.setattr(gr, "confirm_metadata", lambda *a: None)
    monkeypatch.setattr(gr, "_resolve_identity", lambda *a: {"name": "X"})
    monkeypatch.setattr(gr, "integrate", lambda *a: None)       # leave it VALIDATED
    with pytest.raises(SystemExit) as ei:
        gr.main(["DTXSIDY", "--method-profile", "ntp-5day-2021", "--stop-after", "integrate"])
    lines = str(ei.value).splitlines()
    assert lines[0] == (
        "step failed (409): APPROVE refused for DTXSIDY: the study is in phase VALIDATED "
        "(allowed now: ADD_FILES, CONFIRM_CLASSIFICATION, INTEGRATE, REMOVE_FILE, RESET, "
        "RESOLVE, VALIDATE). Integrate first.")
    assert lines[1] == (
        "  Approving the data isn't possible yet. The study's files have been checked but "
        "not yet combined into one dataset. Integrate the study first.")
