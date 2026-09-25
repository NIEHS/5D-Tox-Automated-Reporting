"""
Regression tests for the 2026-09-24 review of the section-catalog change set.

Each test names the defect it pins; see the commit message for the review
finding numbers.
"""

import json
import types


from pipeline.processing_helpers import _signature_rows
from pipeline.session_store import singleton_section_stems
from workflow.section_catalog import (
    approvable_section_types,
    catalog_for_tree,
    is_data_dependent,
    resolve_section_key,
    singleton_section_files,
)
from workflow.steps import accept_section_step
from workflow.store import DiskPoolStore


# --- F2: re-approval answers the wording-review signal ----------------------

def test_accept_clears_wording_review_marker(sessions_dir):
    d = sessions_dir / "DTXSID_WR"
    d.mkdir()
    (d / "bm2_body-weight.json").write_text(json.dumps({
        "platform": "Body Weight", "narrative": ["p"], "approved": False,
        "stale": True, "wording_review": ["Male|Body Weight.direction_adj"],
    }))
    accept_section_step("DTXSID_WR", "bm2_body-weight", DiskPoolStore())
    saved = json.loads((d / "bm2_body-weight.json").read_text())
    assert saved["approved"] is True
    assert "stale" not in saved and "wording_review" not in saved


def test_approve_route_strips_wording_review(client, sessions_dir):
    (sessions_dir / "DTXSID_WR2").mkdir()
    resp = client.post("/api/session/approve", json={
        "dtxsid": "DTXSID_WR2", "section_type": "background",
        "data": {"paragraphs": ["p"], "references": [], "wording_review": ["x"]},
    })
    assert resp.status_code == 200
    saved = json.loads((sessions_dir / "DTXSID_WR2" / "background.json").read_text())
    assert saved["approved"] is True and "wording_review" not in saved


# --- F3: a data reprocess does not stale identity-only sections -------------

def test_catalog_declares_data_dependency():
    from document_model.document_tree import DOCUMENT_TREE
    by_key = {s.key: s for s in catalog_for_tree(DOCUMENT_TREE)}
    assert by_key["background"].data_dependent is False
    assert by_key["methods"].data_dependent is True
    assert by_key["summary"].data_dependent is True
    assert by_key["bm2"].data_dependent is True
    assert all(s.data_dependent is False for s in by_key.values() if s.kind == "authored")


def test_is_data_dependent_resolves_families_and_unknowns():
    assert is_data_dependent("background") is False
    assert is_data_dependent("bm2_liver") is True
    assert is_data_dependent("genomics_liver_male") is True
    assert is_data_dependent("mystery") is True   # fail-safe: treat as data-derived


# --- F7: one section vocabulary, derived from the catalog -------------------

def test_singleton_stems_come_from_the_catalog():
    stems = singleton_section_stems()
    assert set(stems) == {f[:-5] for f in singleton_section_files()}
    assert {"background", "methods", "bmd_summary", "summary"} <= set(stems)


def test_store_iterates_sections_through_session_store_rule(sessions_dir):
    d = sessions_dir / "DTXSID_ST"
    d.mkdir()
    for name in ("background.json", "bm2_a.json", "genomics_liver_male.json", "identity.json", "meta.json"):
        (d / name).write_text(json.dumps({"approved": name == "background.json"}))
    states = DiskPoolStore().read_section_states("DTXSID_ST")
    assert states == {"background": True, "bm2_a": False, "genomics_liver_male": False}


def test_readiness_seeds_singletons_from_catalog_without_a_literal():
    from workflow.section_readiness import derive_section_readiness
    r = derive_section_readiness({})
    assert {"background", "methods", "bmd_summary", "summary"} <= set(r)


# --- F9: approve path — one tree walk, memoized allowlist --------------------

def test_approvable_types_memoized_and_reused_by_resolver():
    a = approvable_section_types()
    assert a is approvable_section_types()          # same frozenset object: cached
    assert resolve_section_key({"section_type": "background"}, a) == ("background", None)
    assert resolve_section_key({"section_type": "nope"}, a) == (None, "Unknown section_type: nope")
    # Without the pre-computed set it still works (and hits the memo).
    assert resolve_section_key({"section_type": "bm2", "bm2_slug": "x"}) == ("bm2_x", None)


# --- F8: the wording signature covers only what the prose describes ----------

def _row(label):
    return types.SimpleNamespace(label=label)


def test_signature_rows_apply_organ_weight_allowlists():
    rows = {
        "Male": [_row("Liver Absolute"), _row("Kidney Relative"), _row("n")],
        "Female": [_row("Liver Absolute")],
    }
    # Other platforms: untouched.
    assert _signature_rows("Body Weight", rows, ["liver"], ["male"]) is rows
    # Organ Weight: sex + organ pruned exactly like the prose builder's inputs.
    out = _signature_rows("Organ Weight", rows, ["liver"], ["male"])
    assert list(out) == ["Male"]
    assert [r.label for r in out["Male"]] == ["Liver Absolute"]
    # No allowlists ⇒ no-op.
    assert _signature_rows("Organ Weight", rows, None, None) is rows


# --- F1: the publish gate is enforced by the server ------------------------

def _stale_session(sessions_dir, dtxsid):
    d = sessions_dir / dtxsid
    d.mkdir()
    (d / "summary.json").write_text(json.dumps({
        "paragraphs": ["p"], "approved": True, "stale": True,
        "regenerated": {"reason": "data_changed"},
    }))
    return d


def test_preview_download_refuses_stale_report(client, sessions_dir):
    d = _stale_session(sessions_dir, "DTXSID_GATE")
    resp = client.get("/api/preview/DTXSID_GATE/download?surface=docx")
    assert resp.status_code == 409
    body = resp.json()
    assert "not publishable" in body["error"]
    assert [b["section_key"] for b in body["blocking"]] == ["summary"]
    # Re-accept (clears stale) ⇒ the gate opens; the next failure is the honest
    # "no preview materialized" 404, proving the gate runs before the file check.
    accept_section_step("DTXSID_GATE", "summary", DiskPoolStore())
    resp = client.get("/api/preview/DTXSID_GATE/download?surface=docx")
    assert resp.status_code == 404
    assert d.exists()


def test_overleaf_bundle_refuses_stale_report(client, sessions_dir):
    _stale_session(sessions_dir, "DTXSID_GATE2")
    resp = client.post("/api/export-overleaf-bundle", json={"dtxsid": "DTXSID_GATE2"})
    assert resp.status_code == 409
    assert "not publishable" in resp.json()["error"]


# --- F6: the sections route builds the tree once and reports presence -------

def test_workflow_sections_route_reports_presence_from_states(client, sessions_dir, monkeypatch):
    d = sessions_dir / "DTXSID_SEC"
    d.mkdir()
    (d / "background.json").write_text(json.dumps({"paragraphs": ["p"], "approved": False}))
    (d / "bm2_body-weight.json").write_text(json.dumps({"approved": True}))
    import workflow.section_catalog as sc
    calls = {"n": 0}
    real = sc.catalog_for_session
    def counted(dtxsid=None):
        calls["n"] += 1
        return real(dtxsid)
    monkeypatch.setattr(sc, "catalog_for_session", counted)
    resp = client.get("/api/workflow/DTXSID_SEC/sections")
    assert resp.status_code == 200
    by_key = {e["key"]: e for e in resp.json()["sections"]}
    assert by_key["background"]["present"] is True
    assert by_key["bm2_body-weight"]["present"] is True and by_key["bm2_body-weight"]["approved"] is True
    assert by_key["methods"]["present"] is False
    assert calls["n"] == 1, "the per-session catalog must be built once per request"
