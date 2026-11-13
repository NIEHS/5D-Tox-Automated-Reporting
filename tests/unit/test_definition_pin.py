"""A session's document definition, pinned (document_model.definition_pin,
ADR-0029 §12): TRACK records the definition and its changes; FIXED renders
from the snapshot whatever the templates say later."""

import json
import textwrap

import pytest

from document_model import definition_pin as dp
from document_model import document_template as dt

BASE = """
document:
- region: body
  children:
  - {id: methods, type: heading-only, title: Methods}
phrasing:
  term: "{go_term} ({go_id})"
"""


@pytest.fixture()
def study(tmp_path, monkeypatch):
    import common.paths
    import document_model.document_config  # noqa: F401 — builds the shared tree first
    from document_model import document_definition
    templates, sessions = tmp_path / "templates", tmp_path / "sessions"
    (templates / "eras").mkdir(parents=True)
    (sessions / "DTXSIDX").mkdir(parents=True)
    monkeypatch.setattr(dt, "TEMPLATES_DIR", templates)
    monkeypatch.setattr(common.paths, "SESSIONS_DIR", sessions)
    monkeypatch.setattr(document_definition, "DEFAULT_DEFINITION", "eras/new")

    def era(text: str) -> None:
        (templates / "eras" / "new.yaml").write_text(textwrap.dedent(text), encoding="utf-8")
    era(BASE)
    return era, sessions / "DTXSIDX"


def _title(dtxsid="DTXSIDX"):
    from document_model.view_config import build_view_tree
    return build_view_tree(dtxsid, "default")[0].title


def test_tracking_records_the_definition_and_each_change(study):
    era, session = study
    pin = dp.ensure_pin("DTXSIDX")
    assert (pin["name"], pin["mode"]) == ("eras/new", dp.TRACK)
    assert dp.ensure_pin("DTXSIDX") == pin                       # unchanged: no re-pin
    era(BASE.replace("title: Methods", "title: Materials and Methods"))
    moved = dp.ensure_pin("DTXSIDX")
    assert moved["hash"] != pin["hash"]
    assert _title() == "Materials and Methods"                   # TRACK renders the files
    history = sorted((session / "history" / dp.HISTORY).iterdir())
    assert [p.suffix for p in history] == [".json", ".yaml"]
    assert json.loads(history[0].read_text())["hash"] == pin["hash"]


def test_a_fixed_definition_renders_from_its_snapshot(study):
    era, _ = study
    pin = dp.pin_definition("DTXSIDX", dp.FIXED)
    era(BASE.replace("title: Methods", "title: Materials and Methods")
        .replace("({go_id})", "[{go_id}]"))
    assert _title() == "Methods"
    from document_model.view_config import study_document_facts
    assert study_document_facts("DTXSIDX")["phrasing"]["term"] == "{go_term} ({go_id})"
    assert pin["hash"] in dp.drift("DTXSIDX")
    assert dp.ensure_pin("DTXSIDX")["hash"] == pin["hash"]        # FIXED is never moved
    dp.pin_definition("DTXSIDX", dp.FIXED)                       # re-pin takes it up
    assert _title() == "Materials and Methods" and dp.drift("DTXSIDX") is None


def test_an_edited_snapshot_is_refused(study):
    _, session = study
    dp.pin_definition("DTXSIDX", dp.FIXED)
    snap = session / dp.SNAPSHOT_FILE
    snap.write_text(snap.read_text().replace("Methods", "Edited"), encoding="utf-8")
    with pytest.raises(dp.DefinitionPinError, match="immutable"):
        _title()


def test_an_unpinned_session_renders_the_files(study):
    assert dp.read_pin("DTXSIDX") is None and dp.drift("DTXSIDX") is None
    assert _title() == "Methods"
    assert dp.read_pin("DTXSIDX") is None                         # rendering never pins
