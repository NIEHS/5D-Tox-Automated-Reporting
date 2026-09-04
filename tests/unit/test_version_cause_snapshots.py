"""
test_version_cause_snapshots.py — Phase 4: dual-cause versioned snapshots.

Every retained version of a section records WHICH act minted it:
  * an ACCEPTED EDIT (human approve)   → cause="edit",      status="blessed"
  * a DATA REPROCESS (system rewrite)  → cause="reprocess",  status="needs-re-bless"

The motivation is AUDITABILITY: a reprocess that changes what the report says must
leave a mark on the timeline even before re-acceptance. These tests pin:

  1. cause tagging on each act (approve → edit/blessed; reprocess → reprocess/
     needs-re-bless);
  2. a reprocess of an approved LLM section now PRODUCES a history entry (it
     produced none before Phase 4);
  3. re-accept after a reprocess flips status to blessed WITHOUT minting a new
     version;
  4. a programmatic (bm2_*) section reprocess still does NOT stale (Phase 3a) and
     so records no needs-re-bless event;
  5. back-compat: a section whose history predates the cause manifest still reads.

The representation is an append-only JSONL manifest per section at
history/{section_key}/index.jsonl — queryable without loading every archive, and
`.jsonl` so it stays invisible to the `*.json` version-count / history globs.
"""

import json

import pytest

from pipeline.session_store import (
    save_section,
    read_version_history,
    current_version_status,
    _VERSION_EVENT_KEY,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def approved_llm_section(sessions_dir):
    """A session with one approved LLM (genomics) section carrying the FINAL/
    PROTECTED facts an approve would have written, plus an integrated.json so the
    reprocess delete branch has something to do. Returns (dtxsid, session_dir)."""
    dtxsid = "DTXSID_PHASE4"
    d = sessions_dir / dtxsid
    d.mkdir(parents=True)
    (d / "genomics_liver_male.json").write_text(
        json.dumps({
            "approved": True,
            "version": 1,
            "approved_at": "2026-01-01T00:00:00+00:00",
            "gene_set_narrative": ["genomics prose"],
            "facts": ["final", "protected"],
        })
    )
    (d / "bm2_organ-and-body-weights.json").write_text(
        json.dumps({
            "approved": True,
            "version": 1,
            "paragraphs": ["body weight prose"],
        })
    )
    (d / "integrated.json").write_text("{}")
    return dtxsid, d


def _load(d, name):
    return json.loads((d / name).read_text())


# ---------------------------------------------------------------------------
# 1. save_section primitive — the transient marker records a cause event and is
#    NOT persisted into the section JSON.
# ---------------------------------------------------------------------------

class TestSaveSectionCauseMarker:

    def test_edit_marker_records_blessed_event(self, sessions_dir):
        dtxsid = "DTX"
        save_section(dtxsid, "background", {
            "paragraphs": ["hi"],
            _VERSION_EVENT_KEY: {"cause": "edit", "status": "blessed"},
        })
        events = read_version_history(dtxsid, "background")
        assert len(events) == 1
        assert events[0]["cause"] == "edit"
        assert events[0]["status"] == "blessed"
        assert events[0]["version"] == 1
        assert "ts" in events[0]

    def test_marker_not_persisted_in_section_json(self, sessions_dir):
        dtxsid = "DTX"
        save_section(dtxsid, "background", {
            "paragraphs": ["hi"],
            _VERSION_EVENT_KEY: {"cause": "edit", "status": "blessed"},
        })
        current = _load(sessions_dir / dtxsid, "background.json")
        assert _VERSION_EVENT_KEY not in current

    def test_no_marker_writes_no_manifest(self, sessions_dir):
        # An unmarked save (auto-save / unapprove / restore) is byte-unaffected:
        # no manifest is written at all.
        dtxsid = "DTX"
        save_section(dtxsid, "background", {"paragraphs": ["hi"]}, archive=False)
        assert read_version_history(dtxsid, "background") == []

    def test_manifest_is_jsonl_invisible_to_version_glob(self, sessions_dir):
        # The manifest must not inflate the version counter (which globs *.json).
        dtxsid = "DTX"
        save_section(dtxsid, "s", {"x": 1,
                                   _VERSION_EVENT_KEY: {"cause": "edit", "status": "blessed"}})
        save_section(dtxsid, "s", {"x": 2,
                                   _VERSION_EVENT_KEY: {"cause": "edit", "status": "blessed"}})
        current = _load(sessions_dir / dtxsid, "s.json")
        # v1 archived, v2 current — the index.jsonl beside them is not counted.
        assert current["version"] == 2
        hist = sessions_dir / dtxsid / "history" / "s"
        assert (hist / "index.jsonl").exists()
        assert len(list(hist.glob("*.json"))) == 1  # one archived version, not two


# ---------------------------------------------------------------------------
# 2. Reprocess of an approved LLM section now produces a cause-tagged snapshot.
# ---------------------------------------------------------------------------

class TestReprocessSnapshot:

    def test_reprocess_records_needs_re_bless_event(self, approved_llm_section):
        from pipeline.pool_state import invalidate_pool_artifacts
        dtxsid, d = approved_llm_section

        invalidate_pool_artifacts(dtxsid)

        events = read_version_history(dtxsid, "genomics_liver_male")
        assert len(events) == 1
        assert events[0]["cause"] == "reprocess"
        assert events[0]["status"] == "needs-re-bless"

    def test_reprocess_now_produces_a_history_entry(self, approved_llm_section):
        # Before Phase 4 a reprocess archived nothing (plain write_text); now it
        # archives the prior blessed version AND records the manifest line.
        from pipeline.pool_state import invalidate_pool_artifacts
        dtxsid, d = approved_llm_section

        hist = d / "history" / "genomics_liver_male"
        assert not hist.exists()  # nothing before the reprocess

        invalidate_pool_artifacts(dtxsid)

        assert hist.exists()
        archived = list(hist.glob("*.json"))
        assert len(archived) == 1  # the pre-reprocess blessed snapshot, retained
        # The archived snapshot is the blessed version, not the demoted one.
        assert json.loads(archived[0].read_text())["facts"] == ["final", "protected"]
        assert (hist / "index.jsonl").exists()

    def test_pool_admin_path_records_same_event(self, approved_llm_section):
        # The standalone CLI path must not diverge from the server path.
        from web_routes.pool_admin import invalidate_downstream
        dtxsid, d = approved_llm_section

        invalidate_downstream(d)

        events = read_version_history(dtxsid, "genomics_liver_male")
        assert [e["cause"] for e in events] == ["reprocess"]
        assert events[0]["status"] == "needs-re-bless"

    def test_pool_admin_dry_run_records_nothing(self, approved_llm_section):
        from web_routes.pool_admin import invalidate_downstream
        dtxsid, d = approved_llm_section

        invalidate_downstream(d, dry_run=True)

        assert read_version_history(dtxsid, "genomics_liver_male") == []


# ---------------------------------------------------------------------------
# 3. Re-accept after a reprocess flips status to blessed WITHOUT a new version.
# ---------------------------------------------------------------------------

class TestReAcceptFlipsStatus:

    def test_reaccept_blesses_same_version(self, approved_llm_section):
        from pipeline.pool_state import invalidate_pool_artifacts
        from workflow.steps import accept_section_step
        from workflow.store import DiskPoolStore

        dtxsid, d = approved_llm_section
        store = DiskPoolStore()

        # Reprocess mints v2, born needs-re-bless.
        invalidate_pool_artifacts(dtxsid)
        reprocessed = _load(d, "genomics_liver_male.json")
        v_after_reprocess = reprocessed["version"]
        assert v_after_reprocess == 2
        assert current_version_status(dtxsid, "genomics_liver_male") == "needs-re-bless"

        # Human re-accepts → status flips to blessed on the SAME version.
        accept_section_step(dtxsid, "genomics_liver_male", store)

        reblessed = _load(d, "genomics_liver_male.json")
        assert reblessed["version"] == v_after_reprocess  # NO new version minted
        assert current_version_status(dtxsid, "genomics_liver_male") == "blessed"

        # The manifest is an append-only timeline: both events for v2 are retained.
        events = read_version_history(dtxsid, "genomics_liver_male")
        assert [(e["cause"], e["status"]) for e in events] == [
            ("reprocess", "needs-re-bless"),
            ("edit", "blessed"),
        ]
        assert all(e["version"] == 2 for e in events)

    def test_reaccept_clears_stale_and_restores_final(self, approved_llm_section):
        # Sanity that the Phase 4 wiring did not regress the ADR-0015 ratchet.
        from pipeline.pool_state import invalidate_pool_artifacts
        from workflow.steps import accept_section_step
        from workflow.store import DiskPoolStore

        dtxsid, d = approved_llm_section
        invalidate_pool_artifacts(dtxsid)
        assert _load(d, "genomics_liver_male.json")["facts"] == ["protected"]

        accept_section_step(dtxsid, "genomics_liver_male", DiskPoolStore())
        reblessed = _load(d, "genomics_liver_male.json")
        assert reblessed["facts"] == ["final", "protected"]
        assert "stale" not in reblessed


# ---------------------------------------------------------------------------
# 4. Programmatic sections never mint a needs-re-bless event.
# ---------------------------------------------------------------------------

class TestProgrammaticNoEvent:

    def test_bm2_reprocess_records_no_event(self, approved_llm_section):
        from pipeline.pool_state import invalidate_pool_artifacts
        dtxsid, d = approved_llm_section

        invalidate_pool_artifacts(dtxsid)

        # Programmatic bm2 is not staled (Phase 3a) → no version minted, no event.
        bm2 = _load(d, "bm2_organ-and-body-weights.json")
        assert "stale" not in bm2
        assert read_version_history(dtxsid, "bm2_organ-and-body-weights") == []


# ---------------------------------------------------------------------------
# 5. Back-compat: a section with old, un-tagged history still reads.
# ---------------------------------------------------------------------------

class TestBackCompat:

    def test_untagged_history_reads_empty(self, sessions_dir):
        dtxsid = "DTX_OLD"
        d = sessions_dir / dtxsid
        hist = d / "history" / "background"
        hist.mkdir(parents=True)
        # A pre-Phase-4 archived version — a bare timestamped JSON, no manifest.
        (hist / "2026-01-01T00-00-00+00-00.json").write_text(
            json.dumps({"version": 1, "paragraphs": ["old"]})
        )
        (d / "background.json").write_text(
            json.dumps({"version": 2, "paragraphs": ["new"]})
        )

        # Missing cause = unknown, never a crash.
        assert read_version_history(dtxsid, "background") == []
        assert current_version_status(dtxsid, "background") is None

    def test_untagged_section_then_edit_starts_a_manifest(self, sessions_dir):
        # An old un-tagged section that later gets an accepted edit begins tagging
        # from that point forward — no migration, no crash on the gap.
        dtxsid = "DTX_OLD"
        d = sessions_dir / dtxsid
        d.mkdir(parents=True)
        (d / "background.json").write_text(
            json.dumps({"version": 1, "paragraphs": ["old"]})
        )
        save_section(dtxsid, "background", {
            "paragraphs": ["edited"],
            _VERSION_EVENT_KEY: {"cause": "edit", "status": "blessed"},
        })
        events = read_version_history(dtxsid, "background")
        assert len(events) == 1
        assert events[0]["cause"] == "edit"
        # v1 archived, v2 current — the tagged event describes v2.
        assert events[0]["version"] == 2


# ---------------------------------------------------------------------------
# 6. Live approve route records an edit/blessed event (integration).
# ---------------------------------------------------------------------------

class TestLiveApproveRoute:

    def test_approve_route_records_edit_event(self, client, sessions_dir):
        dtxsid = "DTXSID_ROUTE"
        resp = client.post("/api/session/approve", json={
            "dtxsid": dtxsid,
            "section_type": "background",
            "data": {"paragraphs": ["a body paragraph"]},
        })
        assert resp.status_code == 200

        events = read_version_history(dtxsid, "background")
        assert len(events) == 1
        assert events[0]["cause"] == "edit"
        assert events[0]["status"] == "blessed"
        # And the transient marker never reaches disk.
        current = _load(sessions_dir / dtxsid, "background.json")
        assert _VERSION_EVENT_KEY not in current


# ---------------------------------------------------------------------------
# 6. Revise-with-reason (HUMAN_RELEASE) — the human down-step records its reason.
# ---------------------------------------------------------------------------

class TestReviseWithReason:

    def test_revise_records_reason_on_trail_and_demotes(self, approved_llm_section):
        from workflow.steps import accept_section_step, release_section_step
        from workflow.store import DiskPoolStore
        dtxsid, d = approved_llm_section
        store = DiskPoolStore()

        # Reopen the blessed genomics section with a human reason.
        release_section_step(dtxsid, "genomics_liver_male", store,
                             reason="rework the interpretation")

        section = _load(d, "genomics_liver_male.json")
        assert section["approved"] is False
        assert section["facts"] == ["protected"]            # FINAL withdrawn
        assert section["revised"] == {"reason": "rework the interpretation"}

        events = read_version_history(dtxsid, "genomics_liver_male")
        revise = [e for e in events if e["cause"] == "revise"]
        assert len(revise) == 1
        assert revise[0]["status"] == "working"
        assert revise[0]["reason"] == "rework the interpretation"

        # Re-accept climbs back to FINAL.
        accept_section_step(dtxsid, "genomics_liver_male", store)
        assert _load(d, "genomics_liver_male.json")["facts"] == ["final", "protected"]

    def test_revise_without_reason_still_records_the_reopen(self, approved_llm_section):
        from workflow.steps import release_section_step
        from workflow.store import DiskPoolStore
        dtxsid, _d = approved_llm_section

        release_section_step(dtxsid, "genomics_liver_male", DiskPoolStore())

        events = read_version_history(dtxsid, "genomics_liver_male")
        revise = [e for e in events if e["cause"] == "revise"]
        assert len(revise) == 1
        # No reason given → the key is simply absent (byte-identical to a
        # pre-reason manifest), but the reopen is still on the trail.
        assert "reason" not in revise[0]
