"""
Characterization test for the workflow phase machine (ADR-0014).

This is the GATE for porting the pool phase logic out of web/js/pool_state.js
into a UI-agnostic Python `workflow/` package. The JS is the source of truth; the
port must reproduce its behavior byte-for-byte.

Two layers, one file:

1. Oracle-sync guard (ALWAYS runs, no Node needed). Asserts the committed
   workflow_phase_oracle.json still agrees with the hand-authored `expected`
   values in workflow_phase_cases.json. If the JS logic changes and someone
   regenerates the oracle without updating the table (or vice versa), this fails —
   the contract can't silently drift. Regenerate with:
       node tests/tools/gen_phase_oracle.mjs

2. Port comparison (auto-arms when the port exists). Drives the SAME cases
   through workflow.phases and asserts equality with the oracle. Until
   workflow/phases.py exists, these are skipped (not failed) — so committing the
   gate now doesn't redden the suite, and the day the port lands the comparison
   turns on automatically with zero test edits.

The three ported functions and their expected Python signatures:
    derive_phase(artifacts: dict) -> str
    compute_section_completeness(coverage_matrix: dict) -> dict[str, dict]
    is_node_complete(node_id: str, completeness: dict, document_tree: list) -> dict

Do NOT edit the `expected`/oracle values to make a port pass. A divergence means
the port changed behavior — fix the port, not the contract.
"""

import importlib.util
import json
from pathlib import Path

import pytest

CHAR_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "characterization"
CASES_PATH = CHAR_DIR / "workflow_phase_cases.json"
ORACLE_PATH = CHAR_DIR / "workflow_phase_oracle.json"

_CASES = json.loads(CASES_PATH.read_text(encoding="utf-8"))
_ORACLE = json.loads(ORACLE_PATH.read_text(encoding="utf-8"))

# Does the Python port exist yet? If not, skip the comparison layer cleanly.
# find_spec raises ModuleNotFoundError (not None) when the parent package
# `workflow` is itself absent, so treat any failure to resolve as "port absent".
try:
    _PORT = importlib.util.find_spec("workflow.phases")
except ModuleNotFoundError:
    _PORT = None
_needs_port = pytest.mark.skipif(
    _PORT is None,
    reason="workflow.phases not implemented yet (ADR-0014 port pending) — "
    "characterization contract is locked; comparison auto-arms when the port lands.",
)


def _oracle_index(group):
    """name -> oracle record for one group."""
    return {rec["name"]: rec for rec in _ORACLE[group]}


# ===========================================================================
# Layer 1 — oracle-sync guard. Always runs. Proves the committed oracle (built
# from the REAL pool_state.js) still matches the hand-authored expectations.
# ===========================================================================

@pytest.mark.parametrize("group", ["derive_phase", "section_completeness", "node_complete"])
def test_oracle_matches_case_table(group):
    """The committed oracle agrees with every hand-authored `expected` value.

    This is the JS-drift tripwire: it does not need Node, only the two committed
    JSON files. It is what lets the Python port trust the oracle without
    re-running the browser code in CI.
    """
    oracle = _oracle_index(group)
    cases = _CASES[group]
    assert len(cases) == len(oracle), (
        f"{group}: case table has {len(cases)} cases but oracle has {len(oracle)} — "
        "regenerate with `node tests/tools/gen_phase_oracle.mjs`"
    )
    for case in cases:
        rec = oracle.get(case["name"])
        assert rec is not None, f"{group}/{case['name']} missing from oracle"
        assert rec["output"] == case["expected"], (
            f"{group}/{case['name']}: oracle output {rec['output']!r} != "
            f"hand-authored expected {case['expected']!r}. The JS logic and the "
            "case table have diverged — reconcile before porting."
        )


def test_case_and_oracle_cover_every_group():
    """Both files carry all three groups (no silently-dropped section)."""
    for group in ("derive_phase", "section_completeness", "node_complete"):
        assert _CASES.get(group), f"case table missing group {group}"
        assert _ORACLE.get(group), f"oracle missing group {group}"


# ===========================================================================
# Layer 2 — port comparison. Auto-arms when workflow.phases exists. Drives the
# SAME inputs through the Python port and asserts equality with the oracle.
# ===========================================================================

_DERIVE_IDS = [c["name"] for c in _CASES["derive_phase"]]
_COMPLETE_IDS = [c["name"] for c in _CASES["section_completeness"]]
_NODE_IDS = [c["name"] for c in _CASES["node_complete"]]


@_needs_port
@pytest.mark.parametrize("case", _CASES["derive_phase"], ids=_DERIVE_IDS)
def test_port_derive_phase(case):
    from workflow.phases import derive_phase

    got = derive_phase(case["input"])
    assert got == case["expected"], (
        f"derive_phase({case['input']!r}) = {got!r}, expected {case['expected']!r}"
    )


@_needs_port
@pytest.mark.parametrize("case", _CASES["section_completeness"], ids=_COMPLETE_IDS)
def test_port_section_completeness(case):
    from workflow.phases import compute_section_completeness

    got = compute_section_completeness(case["input"])
    # Normalize: the port may return dataclasses or dicts. Compare as plain dicts
    # with the four contract keys.
    norm = {
        platform: {
            "hasToxStudy": _attr(v, "hasToxStudy"),
            "hasBm2": _attr(v, "hasBm2"),
            "complete": _attr(v, "complete"),
            "missing": list(_attr(v, "missing")),
        }
        for platform, v in _as_items(got)
    }
    assert norm == case["expected"], (
        f"compute_section_completeness mismatch for {case['name']}"
    )


@_needs_port
@pytest.mark.parametrize("case", _CASES["node_complete"], ids=_NODE_IDS)
def test_port_is_node_complete(case):
    from workflow.phases import is_node_complete

    tree = _CASES["document_tree"]
    got = is_node_complete(case["input"]["nodeId"], case["input"]["completeness"], tree)
    norm = {"complete": _attr(got, "complete"), "missing": list(_attr(got, "missing"))}
    assert norm == case["expected"], f"is_node_complete mismatch for {case['name']}"


# --- small tolerance helpers so the port may return dicts OR dataclasses ---

def _attr(obj, name):
    if isinstance(obj, dict):
        return obj[name]
    return getattr(obj, name)


def _as_items(obj):
    if isinstance(obj, dict):
        return obj.items()
    # a Mapping-like or object exposing .items()
    return obj.items()
