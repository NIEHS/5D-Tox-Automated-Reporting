"""
process_step (ADR-0014) — the processing pipeline as an HTTP-free workflow step.

The processing pipeline used to be reachable ONLY through the FastAPI route
`api_process_integrated`. ADR-0014 lifts its core into
`pipeline.process_integrated.run_process` and exposes it as
`workflow.steps.process_step`, so a notebook / TUI / test can drive the heavy
compute with no FastAPI, no Request, no TestClient.

These tests pin that contract:
  * process_step runs the full pipeline via an injected PoolStore and returns
    the same 12-key payload the route returns — with NOTHING imported from
    web_routes / fastapi to reach it;
  * a session that was never integrated raises StepError(400) (not a 500, and
    not a swallowed exception).

Non-determinism is pinned exactly as the golden oracle pins it (Java/pybmds via
mock_bmdx_pipe; the two live LLM calls monkeypatched), so this stays fast and
offline. This file reuses the golden test's fixture builders to avoid drift.
"""

import pytest
from unittest.mock import AsyncMock

from workflow.errors import StepError
from workflow.steps import process_step
from workflow.store import DiskPoolStore

# Reuse the golden oracle's deterministic fixture builders so the two stay in
# lockstep (same integrated data, same enriched table data, same DTXSID).
from tests.integration.test_process_integrated_golden import (
    DTXSID,
    _setup_session,
    _make_enriched_table_data,
)

_TWELVE_KEYS = {
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


def _pin_llm(monkeypatch):
    """Pin the two live LLM calls to canned output (same as the golden oracle)."""
    monkeypatch.setattr(
        "pipeline.process_integrated._llm_generate_json_async",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        "web_routes.llm_routes.generate_apical_bmd_narrative_async",
        AsyncMock(return_value={
            "paragraphs": ["MOCK analytical paragraph for the BMD summary."],
            "model_used": "mock-model",
        }),
    )


@pytest.mark.asyncio
async def test_process_step_returns_twelve_key_payload_without_fastapi(
    sessions_dir, mock_bmdx_pipe, monkeypatch,
):
    """process_step drives the whole pipeline through the store and returns the
    same 12-key contract the route returns — reached with no HTTP layer."""
    _setup_session(sessions_dir)
    mock_bmdx_pipe.build_table_data.return_value = _make_enriched_table_data()
    _pin_llm(monkeypatch)

    payload = await process_step(
        DTXSID,
        {"compound_name": "TestChem", "dose_unit": "mg/kg"},
        DiskPoolStore(),
    )

    assert set(payload) == _TWELVE_KEYS
    assert payload["bmd_stats"] == ["median"]  # default when unspecified


@pytest.mark.asyncio
async def test_process_step_tolerates_empty_params(
    sessions_dir, mock_bmdx_pipe, monkeypatch,
):
    """An empty params dict behaves like the route's empty-body path (defaults
    applied), not a crash."""
    _setup_session(sessions_dir)
    mock_bmdx_pipe.build_table_data.return_value = _make_enriched_table_data()
    _pin_llm(monkeypatch)

    payload = await process_step(DTXSID, {}, DiskPoolStore())
    assert set(payload) == _TWELVE_KEYS


@pytest.mark.asyncio
async def test_process_step_raises_steperror_400_when_not_integrated(
    sessions_dir,
):
    """A session with no integrated.json raises StepError(400) — the missing-
    data guard is OUTSIDE the try/except that maps failures to 500, so callers
    get a clean 'run integration first' signal."""
    (sessions_dir / DTXSID / "files").mkdir(parents=True, exist_ok=True)
    with pytest.raises(StepError) as exc:
        await process_step(DTXSID, {}, DiskPoolStore())
    assert exc.value.status_code == 400
    assert "run integration first" in exc.value.message
