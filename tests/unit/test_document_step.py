"""
document_step (ADR-0021 E) — content preparation as an HTTP-free workflow step.

process_step runs the whole pipeline (data + content) and returns the 12-key
payload; document_step is its concern-[2] sibling: it prepares the document
CONTENT and returns just the content subset of that payload. The maintainer's
decision is EAGER-but-separated — content prep stays part of the process pass,
and this step exposes the SAME work (via the shared run_data + prepare_content
building blocks, NOT the standalone regenerate endpoints) as a separately
invocable phase.

These tests pin that contract:
  * document_step returns exactly the content-payload keys, reached with no HTTP;
  * for those keys, document_step's output is byte-identical to process_step's —
    proving the separated step can't drift from the eager pass;
  * a session that was never integrated raises StepError(400).

Non-determinism is pinned exactly as the golden oracle / process_step tests pin
it, so this stays fast and offline; fixture builders are reused to avoid drift.
"""

import pytest
from unittest.mock import AsyncMock

from workflow.errors import StepError
from workflow.steps import process_step, document_step
from workflow.store import DiskPoolStore

from pipeline.process_integrated import _CONTENT_PAYLOAD_KEYS

from tests.integration.test_process_integrated_golden import (
    DTXSID,
    _setup_session,
    _make_enriched_table_data,
)


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
async def test_document_step_returns_content_subset(
    sessions_dir, mock_bmdx_pipe, monkeypatch,
):
    """document_step returns exactly the content-payload keys — no HTTP layer."""
    _setup_session(sessions_dir)
    mock_bmdx_pipe.build_table_data.return_value = _make_enriched_table_data()
    _pin_llm(monkeypatch)

    payload = await document_step(
        DTXSID,
        {"compound_name": "TestChem", "dose_unit": "mg/kg"},
        DiskPoolStore(),
    )
    assert set(payload) == set(_CONTENT_PAYLOAD_KEYS)


@pytest.mark.asyncio
async def test_document_step_matches_process_step_for_content_keys(
    sessions_dir, mock_bmdx_pipe, monkeypatch,
):
    """The separated content step must produce, for every content key, the SAME
    value the eager process pass produces — the anti-drift guarantee that makes
    'eager-but-separated' safe (ADR-0021 E). Both are driven against the same
    session with identical pinned non-determinism."""
    _setup_session(sessions_dir)
    mock_bmdx_pipe.build_table_data.return_value = _make_enriched_table_data()
    _pin_llm(monkeypatch)

    full = await process_step(
        DTXSID, {"compound_name": "TestChem", "dose_unit": "mg/kg"}, DiskPoolStore(),
    )
    content = await document_step(
        DTXSID, {"compound_name": "TestChem", "dose_unit": "mg/kg"}, DiskPoolStore(),
    )

    for key in _CONTENT_PAYLOAD_KEYS:
        assert content[key] == full[key], f"content-step drift on {key!r}"


@pytest.mark.asyncio
async def test_document_step_raises_steperror_400_when_not_integrated(
    sessions_dir,
):
    """A session with no integrated.json raises StepError(400) — the missing-data
    guard is shared with process_step (both build the ctx via the same
    _build_process_context), so callers get a clean 'run integration first'."""
    (sessions_dir / DTXSID / "files").mkdir(parents=True, exist_ok=True)
    with pytest.raises(StepError) as exc:
        await document_step(DTXSID, {}, DiskPoolStore())
    assert exc.value.status_code == 400
    assert "run integration first" in exc.value.message
