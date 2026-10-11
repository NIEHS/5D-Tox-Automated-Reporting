"""
Content skip-guard must not cache a degraded run.

The LLM narrative builders in pipeline/process_integrated.py are fail-soft:
a failed call leaves an empty narrative rather than aborting the process.
Before 2026-09-18, prepare_content_if_changed then persisted that run's
outputs + fingerprint unconditionally, so an unchanged fingerprint restored
the EMPTY narrative on every later process until the study data changed.
The fix records each dropped output in ProcessContext.content_errors and
skips the cache write when the list is non-empty. These tests pin that.
"""

import pytest

import pipeline.process_integrated as pi


def _ctx(dtxsid: str) -> pi.ProcessContext:
    """Minimal ProcessContext — only the required request fields."""
    return pi.ProcessContext(
        dtxsid=dtxsid,
        integrated={},
        compound_name="X",
        dose_unit="mg/kg",
        bmd_stats=["median"],
        bmd_stat="median",
        go_pct=5,
        go_min_genes=3,
        go_max_genes=250,
        go_min_bmd=0,
    )


@pytest.mark.asyncio
async def test_degraded_run_is_not_cached(sessions_dir, monkeypatch):
    """A run that records content_errors returns True (prepared) but writes
    neither the outputs cache nor the fingerprint."""
    ctx = _ctx("DTXSID_DEGRADED")
    session = sessions_dir / ctx.dtxsid
    session.mkdir()

    async def _fake_prepare(c):
        c.llm_gs_by_organ = {}
        c.content_errors.append("genomics_narrative[liver:male]: boom")

    monkeypatch.setattr(pi, "prepare_content", _fake_prepare)
    monkeypatch.setattr(pi, "_content_fingerprint", lambda c: "fp-1")

    assert await pi.prepare_content_if_changed(ctx) is True
    assert not (session / pi._CONTENT_CACHE_NAME).exists()
    assert not (session / pi._CONTENT_FP_NAME).exists()


@pytest.mark.asyncio
async def test_clean_run_is_cached_and_skips_next_time(sessions_dir, monkeypatch):
    """Control: a clean run persists the cache and the next call skips."""
    ctx = _ctx("DTXSID_CLEAN")
    session = sessions_dir / ctx.dtxsid
    session.mkdir()
    calls = []

    async def _fake_prepare(c):
        calls.append(1)
        for k in pi._CONTENT_OUTPUT_FIELDS:
            setattr(c, k, {})

    monkeypatch.setattr(pi, "prepare_content", _fake_prepare)
    monkeypatch.setattr(pi, "_content_fingerprint", lambda c: "fp-1")

    assert await pi.prepare_content_if_changed(ctx) is True
    assert (session / pi._CONTENT_CACHE_NAME).exists()
    assert await pi.prepare_content_if_changed(ctx) is False
    assert calls == [1]


@pytest.mark.asyncio
async def test_content_errors_reset_between_runs(sessions_dir, monkeypatch):
    """Errors from a previous run on the same context must not poison a
    later clean run: the guard clears the list before preparing."""
    ctx = _ctx("DTXSID_RESET")
    (sessions_dir / ctx.dtxsid).mkdir()
    ctx.content_errors.append("stale from earlier")

    async def _fake_prepare(c):
        for k in pi._CONTENT_OUTPUT_FIELDS:
            setattr(c, k, {})

    monkeypatch.setattr(pi, "prepare_content", _fake_prepare)
    monkeypatch.setattr(pi, "_content_fingerprint", lambda c: "fp-1")

    await pi.prepare_content_if_changed(ctx)
    assert ctx.content_errors == []
    assert (sessions_dir / ctx.dtxsid / pi._CONTENT_CACHE_NAME).exists()
