"""
test_process_integrated_golden.py — Golden-snapshot oracle for the
api_process_integrated pipeline.

This is the regression net for ADR-0002 (decompose api_process_integrated).
The endpoint's contract is its HTTP `result_payload` shape AND values; the
existing test_process_integrated.py asserts only *shape* (key presence, rough
structure).  This test freezes the full payload *values* against a committed
golden fixture and asserts byte-identical (after canonicalization) on every
run.

Why this matters for the refactor: the four Layer-2 units are nested async
closures that capture ~15 outer locals.  Lifting them to module-level
functions threads that state explicitly — and a single forgotten capture is a
silent value regression the structural smoke test cannot see.  This golden
makes such a regression a hard failure.

Determinism: the synthetic session has no gene_expression source, so the
genomics / charts / genomics-narrative layers are skipped (empty).  The only
live LLM paths are Layer 2's Materials-and-Methods and Layer 3.5c's apical
analytical paragraph; both are mocked to canned, deterministic output so the
payload is reproducible and the captured-locals paths through those closures
are still exercised.

Regenerating the golden (do this deliberately, then eyeball the diff):

    UPDATE_GOLDEN=1 .venv/bin/python -m pytest \
        tests/integration/test_process_integrated_golden.py -q

The fixture must only ever change when the payload contract *intentionally*
changes — during the behavior-preserving extraction it must not change at all.
"""

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from bmdx_pipe import TableRow

from tests.integration.test_process_integrated import (
    _make_integrated_data,
)

# tests/integration/ -> tests/ -> tests/fixtures/golden/
GOLDEN_PATH = (
    Path(__file__).parent.parent
    / "fixtures"
    / "golden"
    / "process_integrated_payload.json"
)

DTXSID = "DTXSID_TEST"


def _make_enriched_table_data():
    """
    NTP stats with BMD fields populated so the apical-BMD-summary and
    apical-narrative layers (Layers 3 and 3.5c — the first leaf-first
    extraction targets) produce non-empty values to snapshot.

    The base _make_table_data() in test_process_integrated leaves bmd_str /
    bmd_status / loel / noel at their defaults, so _build_apical_bmd_summary
    returns []; that exercises the layers' control flow but snapshots nothing.
    Here we set viable, non-anomalous BMDs (BMD ≥ NOEL/10 so _is_anomalous_bmd
    does not fire) so the summary and the apical narrative carry real content.

    This is intentionally a *local* fixture, not a change to the shared
    _make_table_data — other tests assert on that helper's exact output.
    """
    def row(label, values, marker, *, bmd, bmdl, loel, noel, direction):
        return TableRow(
            label=label,
            values_by_dose=values,
            n_by_dose={0.0: 10, 1.0: 10, 10.0: 10, 100.0: 10},
            trend_marker=marker,
            responsive=True,
            bmd_str=bmd,
            bmdl_str=bmdl,
            bmd_status="viable",
            loel=loel,
            noel=noel,
            direction=direction,
        )

    return {
        "Male": [
            row(
                "SD5",
                {0.0: "100.0 ± 5.0", 1.0: "105.0 ± 4.0", 10.0: "110.0 ± 6.0", 100.0: "120.0 ± 7.0"},
                "**", bmd="42.0", bmdl="28.0", loel=100.0, noel=10.0, direction="↑",
            ),
            row(
                "ALT",
                {0.0: "30.0 ± 2.0", 1.0: "35.0 ± 3.0", 10.0: "40.0 ± 4.0", 100.0: "50.0 ± 5.0**"},
                "**", bmd="18.5", bmdl="12.0", loel=100.0, noel=10.0, direction="↑",
            ),
            row(
                "AST",
                {0.0: "20.0 ± 1.0", 1.0: "22.0 ± 1.5", 10.0: "25.0 ± 2.0", 100.0: "30.0 ± 2.5"},
                "**", bmd="55.0", bmdl="40.0", loel=100.0, noel=10.0, direction="↑",
            ),
        ],
        "Female": [
            row(
                "SD5",
                {0.0: "90.0 ± 4.0", 1.0: "95.0 ± 3.5", 10.0: "100.0 ± 5.0", 100.0: "110.0 ± 6.0"},
                "*", bmd="63.0", bmdl="48.0", loel=100.0, noel=10.0, direction="↑",
            ),
        ],
    }


def _canonical(payload) -> str:
    """Canonical JSON for byte-stable comparison and on-disk storage."""
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)


def _setup_session(sessions_dir):
    """Write integrated.json into a fresh session dir."""
    session = sessions_dir / DTXSID
    session.mkdir(parents=True, exist_ok=True)
    (session / "files").mkdir(exist_ok=True)
    (session / "integrated.json").write_text(
        json.dumps(_make_integrated_data(), indent=2),
    )
    return session


def _run_pipeline(sessions_dir, mock_bmdx_pipe, monkeypatch):
    """
    Drive POST /api/process-integrated with all non-determinism pinned:
      - Java / pybmds blocked via mock_bmdx_pipe (conftest).
      - The two live LLM calls (methods + apical analytical) mocked to
        canned, deterministic output.

    Returns the parsed JSON payload.
    """
    from fastapi.testclient import TestClient
    from background_server import app

    _setup_session(sessions_dir)
    mock_bmdx_pipe.build_table_data.return_value = _make_enriched_table_data()

    # Layer 2 — Materials & Methods LLM.  Bound at module top in
    # process_integrated as `_llm_generate_json_async`.  Empty dict → the
    # methods report is assembled with its (deterministic) extracted context
    # and table1 but no LLM prose, so the methods closure's captured locals
    # (integrated, fingerprints, dtxsid) still drive the output.
    monkeypatch.setattr(
        "pipeline.process_integrated._llm_generate_json_async",
        AsyncMock(return_value={}),
    )

    # Layer 3.5c — apical BMD analytical paragraph.  Lazily imported inside
    # the handler as `from llm_routes import generate_apical_bmd_narrative_async`,
    # so patch it on the llm_routes module.
    monkeypatch.setattr(
        "llm_routes.generate_apical_bmd_narrative_async",
        AsyncMock(return_value={
            "paragraphs": ["MOCK analytical paragraph for the BMD summary."],
            "model_used": "mock-model",
        }),
    )

    client = TestClient(app)
    resp = client.post(
        f"/api/process-integrated/{DTXSID}",
        json={"compound_name": "TestChem", "dose_unit": "mg/kg"},
    )
    assert resp.status_code == 200, f"Pipeline failed: {resp.text}"
    return resp.json()


@pytest.mark.integration
class TestProcessIntegratedGolden:
    """Value-level regression oracle for the processing pipeline."""

    def test_payload_matches_golden(self, sessions_dir, mock_bmdx_pipe, monkeypatch):
        """
        The full result_payload must match the committed golden byte-for-byte
        (after canonicalization).  Regenerate with UPDATE_GOLDEN=1 only when
        the payload contract changes intentionally.
        """
        payload = _run_pipeline(sessions_dir, mock_bmdx_pipe, monkeypatch)
        actual = _canonical(payload)

        if os.environ.get("UPDATE_GOLDEN"):
            GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            GOLDEN_PATH.write_text(actual + "\n")
            pytest.skip(f"Golden regenerated at {GOLDEN_PATH}")

        assert GOLDEN_PATH.exists(), (
            f"Golden fixture missing at {GOLDEN_PATH}. "
            f"Generate it with: UPDATE_GOLDEN=1 .venv/bin/python -m pytest "
            f"{Path(__file__).name}"
        )
        expected = GOLDEN_PATH.read_text().rstrip("\n")

        if actual != expected:
            # dict-level diff is far more readable than a 1000-line string diff
            exp_obj = json.loads(expected)
            act_obj = payload
            diff_keys = sorted(
                k for k in set(exp_obj) | set(act_obj)
                if exp_obj.get(k) != act_obj.get(k)
            )
            pytest.fail(
                "result_payload diverged from golden.\n"
                f"  Top-level keys that differ: {diff_keys}\n"
                "  This means the pipeline's output changed. If the change is "
                "intentional, regenerate with UPDATE_GOLDEN=1 and eyeball the "
                "diff; otherwise it is a regression (e.g. a dropped closure "
                "capture during extraction)."
            )

    def test_payload_has_all_twelve_contract_keys(
        self, sessions_dir, mock_bmdx_pipe, monkeypatch,
    ):
        """
        The payload's twelve-key contract (ADR-0002) is explicit and load-
        bearing for the frontend.  Assert the exact key set independently of
        the value snapshot, so a key addition/removal fails loudly even if a
        stale golden were regenerated by mistake.
        """
        payload = _run_pipeline(sessions_dir, mock_bmdx_pipe, monkeypatch)
        assert set(payload) == {
            "sections",
            "unified_narratives",
            "genomics_sections",
            "gene_set_narrative",
            "gene_narrative",
            "chart_images",
            "apical_bmd_summary",
            "apical_bmd_summary_bmds",
            "apical_bmd_narrative",
            "bmd_stats",
            "bmd_stat_labels",
            "methods",
        }
