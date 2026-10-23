"""The new interface's server side (ui_api/) is a front end over the
safeguards (ADR-0031): the core, the safeguards and the notebook never import
it, and every ``fix`` it serves is one of the interface's modules."""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

CORE = ("common", "workflow", "pipeline", "document_model", "rendering", "tables",
        "narrative", "genomics", "knowledge_base", "styling_export", "roundtrip", "pdf_text")
_IMPORT = re.compile(r"^\s*(?:from|import)\s+ui_api\b", re.M)


def _importers(roots) -> list[str]:
    return sorted(str(p.relative_to(REPO)) for root in roots for p in (REPO / root).rglob("*.py")
                  if _IMPORT.search(p.read_text(encoding="utf-8", errors="replace")))


def test_nothing_below_the_interface_imports_it():
    assert _importers(CORE + ("safeguards", "notebooks", "tooling")) == []


def test_every_place_has_a_module():
    from safeguards.refusals import PLACES
    from ui_api.refusals import PLACE_MODULE
    assert set(PLACE_MODULE) == set(PLACES)


def test_every_refusal_reaches_the_interface_with_a_module_or_none():
    """Each catalog code, the M1 codes included, explained as the interface
    shows it: ``fix`` is a module id of MODULES.md §3, or None."""
    from safeguards.refusals import REFUSALS, Refused
    from ui_api.refusals import STUDY_REFUSALS, explain
    modules = {"M1", "M2", "M3", "M4", "M5", "M6", "P1", "P2",
               "D1", "D2", "D3", "D4", "D5", "D6"}
    assert set(STUDY_REFUSALS) <= set(REFUSALS)              # registered on import
    for code in REFUSALS:
        body = explain(Refused(code, "m", 409))["error"]
        assert body["code"] == code
        assert body["fix"] is None or body["fix"] in modules, (code, body["fix"])


@pytest.mark.parametrize("code,module", [("not_validated", "M2"), ("section_owned", "D1"),
                                         ("method_not_chosen", "M5"), ("study_exists", "M1"),
                                         ("run_in_flight", "P1"), ("facts_invalid", "M4"),
                                         ("approve_content_retired", "D4")])
def test_a_place_becomes_its_module(code, module):
    from safeguards.refusals import Refused
    from ui_api.refusals import explain
    assert explain(Refused(code, "m", 409))["error"]["fix"] == module
