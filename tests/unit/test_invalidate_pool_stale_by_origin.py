"""
Characterization + behavior-change test for invalidate_pool_artifacts staling
(Phase 3a). PINS the deliberate change from the old "stale everything" behavior:

  BEFORE: every bm2_*.json AND genomics_*.json got stale=True uniformly.
  AFTER:  only LLM sections (genomics_*) are staled + stamped `regenerated`;
          programmatic sections (bm2_*) are NOT staled (their numbers refresh).

This is a real behavior change across invalidate_pool_artifacts' callers
(upload x3, pool_admin, orchestrator) — pinned here so it is explicit, per the
same discipline as the Phase 1 unlock-tightening.
"""

import json

import pytest

import pipeline.session_store as session_store


@pytest.fixture
def staged_session(tmp_path, monkeypatch):
    """Point SESSIONS_DIR at a tmp dir with an approved bm2 + genomics section,
    plus the pool artifacts invalidate deletes. Returns the dtxsid + dir."""
    monkeypatch.setattr(session_store, "SESSIONS_DIR", tmp_path)
    dtxsid = "DTXSID_TEST_PHASE3"
    d = tmp_path / dtxsid
    d.mkdir()
    # An approved programmatic section and an approved LLM section.
    (d / "bm2_organ-and-body-weights.json").write_text(
        json.dumps({"approved": True, "paragraphs": ["body weight prose"]})
    )
    (d / "genomics_liver_male.json").write_text(
        json.dumps({"approved": True, "gene_set_narrative": ["genomics prose"]})
    )
    # integrated.json so the delete branch has something to do (not asserted).
    (d / "integrated.json").write_text("{}")
    return dtxsid, d


def _load(d, name):
    return json.loads((d / name).read_text())


def test_programmatic_not_staled_llm_staled(staged_session):
    from pipeline.pool_state import invalidate_pool_artifacts

    dtxsid, d = staged_session
    summary = invalidate_pool_artifacts(dtxsid)

    bm2 = _load(d, "bm2_organ-and-body-weights.json")
    gen = _load(d, "genomics_liver_male.json")

    # Programmatic bm2: NOT staled (the behavior change), content intact.
    assert "stale" not in bm2
    assert bm2["approved"] is True
    assert "bm2_organ-and-body-weights.json" not in summary["marked_stale"]

    # LLM genomics: staled AND stamped with the regenerated reason.
    assert gen["stale"] is True
    assert gen["regenerated"]["reason"] == "data_changed"
    assert gen["approved"] is True  # content preserved, just flagged
    assert "genomics_liver_male.json" in summary["marked_stale"]


def test_regenerated_marker_only_on_llm(staged_session):
    from pipeline.pool_state import invalidate_pool_artifacts

    dtxsid, d = staged_session
    invalidate_pool_artifacts(dtxsid)

    assert "regenerated" not in _load(d, "bm2_organ-and-body-weights.json")
    assert "regenerated" in _load(d, "genomics_liver_male.json")


def test_pool_admin_standalone_path_matches(staged_session):
    # pool_admin.invalidate_downstream is the standalone-CLI duplicate of the same
    # logic — it must route by content-origin identically (no divergence).
    from web_routes.pool_admin import invalidate_downstream

    _dtxsid, d = staged_session
    invalidate_downstream(d)

    bm2 = _load(d, "bm2_organ-and-body-weights.json")
    gen = _load(d, "genomics_liver_male.json")
    assert "stale" not in bm2 and "regenerated" not in bm2
    assert gen["stale"] is True
    assert gen["regenerated"]["reason"] == "data_changed"
