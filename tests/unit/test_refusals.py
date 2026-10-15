"""
Unit tests for workflow.refusals — the error envelope (MODULES.md §4.2).

Every refusal the Gate 0 analyses quote (data §3.1, Process §6.1, document
§9.1) maps to its code, keeps the backend's message verbatim and its status, and
says something a toxicologist can act on. The pin, guard, id and damaged-file
refusals are produced by the real code that raises them, not by retyped texts.
"""

import json

import pytest

from workflow.errors import GuardViolation, StepError
from workflow.refusals import REFUSALS, classify, explain

# The modules a refusal may point at (MODULES.md §3), or None (the maintainer).
_MODULES = {"M1", "M2", "M3", "M4", "M5", "M6", "P1", "P2", "D1", "D2", "D3", "D4", "D5", "D6", None}


@pytest.mark.parametrize("message,status,code", [
    # data §3.1 (workflow/steps.py)
    ("No files directory found for this session", 404, "no_files"),
    ("dtxsid, issue_index, and chosen_file_id are required", 400, "conflict_choice_missing"),
    ("No fingerprints found -- run validation first", 400, "not_validated"),
    ("No coverage matrix found -- run validation first", 400, "not_validated"),
    ("Integration failed: Experiment BodyWeightMale has no doses", 500, "integration_failed"),
    ("No fingerprinted files found -- upload files first", 400, "files_not_recognised"),
    ("Animal report generation failed: KeyError 'animal_id'", 500, "animal_report_failed"),
    # Process §6.1 (pipeline/process_integrated.py)
    ("No integrated data found -- run integration first", 400, "not_integrated"),
    ("Processing failed: RunApicalBmds failed with exit code 1", 500, "calculation_program_failed"),
    ("Processing failed: ExportGenomics failed: NullPointerException", 500, "calculation_program_failed"),
    ("2 apical BMD endpoint(s) diverge between the .bm2 and the ToxicR recompute beyond 20% — "
     "Male ALT (Clinical Chemistry): bm2=12.3 vs ToxicR=30.1 (Δ145%)", 500, "bmd_divergence"),
    ("Processing failed: 1 apical BMD endpoint(s) diverge between the .bm2 and …", 500, "bmd_divergence"),
    ("Processing failed: division by zero", 500, "processing_failed"),
    ("Content preparation failed: template missing", 500, "content_preparation_failed"),
    # document §2 / §9.1 (workflow/steps.py accept/release)
    ("dtxsid and section_key are required", 400, "section_key_missing"),
    # the environment, not the data
    ("Integration failed: java.lang.UnsupportedClassVersionError: …", 500, "server_setup_failed"),
    ("Processing failed: BMDX_PROJECT_ROOT is not set", 500, "server_setup_failed"),
])
def test_step_errors_map_to_their_code(message, status, code):
    body = explain(StepError(message, status_code=status))["error"]
    assert body["code"] == code
    assert body["status"] == status          # the backend's advisory status, kept
    assert body["message"] == message        # verbatim
    assert body["say"] == REFUSALS[code].say  # these codes take no fields
    assert body["fix"] == REFUSALS[code].fix
    assert body["details"] == {}


def test_section_not_found_names_the_section():
    body = explain(StepError("No 'methods' section to approve", status_code=404))["error"]
    assert body["code"] == "section_not_found"
    assert body["status"] == 404
    assert "“methods”" in body["say"]
    assert body["fix"] == "D1"


def test_every_code_says_something_and_points_at_a_module():
    for code, refusal in REFUSALS.items():
        assert refusal.say.strip(), code
        assert refusal.fix in _MODULES, code
        assert 400 <= refusal.status <= 599, code
        # plain words: no exception names, no file paths of the code base
        assert "Error" not in refusal.say and ".py" not in refusal.say, code


def test_guard_violations_from_the_real_guards():
    from workflow.currency import assert_can_advance
    from workflow.labels import Fact, demote

    with pytest.raises(GuardViolation) as release:
        demote(frozenset({Fact.FINAL, Fact.PROTECTED}), Fact.FINAL)
    body = explain(release.value)["error"]
    assert (body["code"], body["status"], body["fix"]) == ("release_reason_required", 409, "D1")
    assert body["message"] == str(release.value)

    with pytest.raises(GuardViolation) as stale:
        assert_can_advance(frozenset(), is_stale=True)
    assert classify(stale.value)[0] == "stale_content"

    assert classify(GuardViolation("some future rule"))[0] == "guard_refused"


def test_method_profile_errors_from_the_real_resolver(sessions_dir):
    from pipeline import method_profile as mp

    (sessions_dir / "DTXSID1").mkdir()
    pin = {"name": "ntp-5day-2021", "hash": "0000000000000000", "mode": "fixed",
           "series": "ntp-5day", "pinned_at": "2026-10-14T00:00:00+00:00", "pinned_by": "user"}
    (sessions_dir / "DTXSID1" / mp.PIN_FILE).write_text(json.dumps(pin))
    with pytest.raises(mp.MethodProfileError) as changed:
        mp.session_method("DTXSID1", probe=False)
    body = explain(changed.value)["error"]
    assert (body["code"], body["status"], body["fix"]) == ("method_profile_changed", 409, "M5")

    with pytest.raises(mp.MethodProfileError) as missing:
        mp.load_profile("no-such-profile")
    assert classify(missing.value)[0] == "method_profile_invalid"


def test_definition_pin_errors_from_the_real_pin(sessions_dir):
    from document_model import definition_pin as dp

    (sessions_dir / "DTXSID1").mkdir()
    with pytest.raises(dp.DefinitionPinError) as bad_mode:
        dp.pin_definition("DTXSID1", "sometimes")
    assert classify(bad_mode.value)[0] == "definition_pin_invalid"

    with pytest.raises(dp.DefinitionPinError) as none:
        dp.load_snapshot("DTXSID1")
    assert classify(none.value)[0] == "definition_not_pinned"

    dp.pin_definition("DTXSID1", dp.FIXED)
    snapshot = sessions_dir / "DTXSID1" / dp.SNAPSHOT_FILE
    snapshot.write_text(snapshot.read_text() + "\nedited_by_hand: true\n")
    with pytest.raises(dp.DefinitionPinError) as changed:
        dp.load_snapshot("DTXSID1")
    body = explain(changed.value)["error"]
    assert (body["code"], body["status"], body["fix"]) == ("definition_pin_changed", 409, "M5")


def test_invalid_id_and_damaged_file(sessions_dir):
    from common.dtxsid import InvalidDtxsid, validate_dtxsid
    from common.session_files import UnreadableSessionFile, read_session_json

    with pytest.raises(InvalidDtxsid) as bad:
        validate_dtxsid("../etc")
    body = explain(bad.value)["error"]
    assert (body["code"], body["status"], body["fix"]) == ("invalid_study_id", 400, "M1")
    assert body["message"] == str(bad.value)

    (sessions_dir / "DTXSID1").mkdir()
    (sessions_dir / "DTXSID1" / "identity.json").write_text("{not json")
    with pytest.raises(UnreadableSessionFile) as damaged:
        read_session_json("DTXSID1", "identity.json")
    body = explain(damaged.value)["error"]
    assert (body["code"], body["status"]) == ("damaged_session_file", 422)
    assert body["details"] == {"file": "DTXSID1/identity.json"}
    assert "DTXSID1/identity.json" in body["say"]


def test_anything_else_is_unexpected_and_keeps_its_text():
    body = explain(RuntimeError("boom"))["error"]
    assert (body["code"], body["status"], body["fix"]) == ("unexpected", 500, None)
    assert body["message"] == "RuntimeError: boom"


def test_a_foreign_status_code_is_not_passed_to_the_client():
    class UpstreamError(Exception):
        status_code = 401
    assert explain(UpstreamError("gateway said no"))["error"]["status"] == 500


def test_an_exception_naming_a_listed_code_is_taken_at_its_word():
    exc = StepError("Process is not legal in phase UPLOADED (legal: RESET, VALIDATE)", 409)
    exc.code = "phase_not_allowed"
    exc.phase = "UPLOADED"
    exc.legal_actions = ["RESET", "VALIDATE"]
    body = explain(exc)["error"]
    assert (body["code"], body["status"]) == ("phase_not_allowed", 409)
    assert body["details"] == {"phase": "UPLOADED", "legal_actions": ["RESET", "VALIDATE"]}

    exc.code = "not_a_listed_code"
    assert classify(exc)[0] != "not_a_listed_code"
