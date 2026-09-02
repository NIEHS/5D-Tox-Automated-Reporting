"""
Integration test: graph-grounded references surface through the render path.

This exercises the SEAM between the persisted per-stratum interpretation caches
(written by the genomics narrative pass) and the report data the renderers
consume — WITHOUT the LLM or the network.  We stage a synthetic session whose
interpretation caches already carry `reference_pool` + [Pn]-citing narratives
(the shape `generate_genomics_narrative_async` persists), then assert that:

  * `data["references"]["paragraphs"]` is the assembled, globally-numbered list;
  * the genomics narratives have their inline [Pn] tokens rewritten to the
    report-wide [n] numbers so citations agree with the References section;
  * a shared paper keeps ONE number across strata, and an uncited pool paper is
    excluded.
"""

from __future__ import annotations

import json

import pytest

import pipeline.session_store as session_store
import rendering.latex_export as latex_export


DTXSID = "DTXSID_REFTEST"


def _stage_session(sessions_dir):
    sess = sessions_dir / DTXSID
    (sess / "files").mkdir(parents=True, exist_ok=True)

    genomics_cache = {
        "liver_Male": {
            "organ": "liver", "sex": "Male",
            "gene_sets_by_stat": {"median": [
                {"go_term": "steroid biosynthetic process", "go_id": "GO:1",
                 "bmd_median": 0.5, "n_genes": 4, "direction": "Down"},
            ]},
            "top_genes": [{"gene_symbol": "CYP7A1", "bmd": 0.5, "direction": "down"}],
        },
        "kidney_Male": {
            "organ": "kidney", "sex": "Male",
            "gene_sets_by_stat": {"median": [
                {"go_term": "transport", "go_id": "GO:2",
                 "bmd_median": 0.7, "n_genes": 3, "direction": "Down"},
            ]},
            "top_genes": [{"gene_symbol": "MYC", "bmd": 0.7, "direction": "up"}],
        },
    }
    (sess / "_cache_genomics_abc.json").write_text(json.dumps(genomics_cache))

    liver = {
        "context_text": "x",
        "gene_set_narrative": ["Liver sterol response cites [P2] and [P1]."],
        "gene_narrative": ["CYP7A1 was sensitive [P1]."],
        "reference_pool": [
            {"token": "P1", "paper_id": "pa", "title": "Paper A", "year": 2020,
             "venue": "VA", "doi": "10.1/a", "citation_count": 10, "genes": ["CYP7A1"]},
            {"token": "P2", "paper_id": "pb", "title": "Paper B", "year": 2021,
             "venue": "VB", "doi": "10.1/b", "citation_count": 5, "genes": ["EGR1"]},
        ],
    }
    kidney = {
        "context_text": "y",
        # local P1 == the shared paper pb; P2 (pc) is offered but NOT cited.
        "gene_set_narrative": ["Kidney cites [P1]."],
        "gene_narrative": [],
        "reference_pool": [
            {"token": "P1", "paper_id": "pb", "title": "Paper B", "year": 2021,
             "venue": "VB", "doi": "10.1/b", "citation_count": 5, "genes": ["EGR1"]},
            {"token": "P2", "paper_id": "pc", "title": "Paper C", "year": 2022,
             "venue": "VC", "doi": "10.1/c", "citation_count": 1, "genes": ["MYC"]},
        ],
    }
    (sess / "_cache_interpretation_liver_male_h1.json").write_text(json.dumps(liver))
    (sess / "_cache_interpretation_kidney_male_h2.json").write_text(json.dumps(kidney))
    return sess


@pytest.fixture
def staged_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(session_store, "SESSIONS_DIR", tmp_path)
    _stage_session(tmp_path)
    return tmp_path


def test_references_surface_and_tokens_rewritten(staged_sessions):
    data = latex_export.load_session_data(
        DTXSID, chemical_name="Test Article", casrn="0-0-0",
    )

    paras = data.get("references", {}).get("paragraphs", [])
    # Global numbering: liver gene-set prose cites P2(pb) then P1(pa) → pb=1,
    # pa=2.  pc is never cited → excluded.  So exactly two references.
    assert paras == [
        "[1] Paper B. VB. 2021. https://doi.org/10.1/b",
        "[2] Paper A. VA. 2020. https://doi.org/10.1/a",
    ]

    # Inline [Pn] tokens rewritten to report-wide [n] in the genomics narratives.
    narrs = {
        (e["type"], e["organ"], s.get("sex")): s.get("narrative")
        for e in data["genomics_sections"] for s in e.get("sexes", [])
    }
    assert narrs[("gene_set", "liver", "Male")] == ["Liver sterol response cites [1] and [2]."]
    assert narrs[("gene", "liver", "Male")] == ["CYP7A1 was sensitive [2]."]
    # Kidney's LOCAL P1 (shared paper pb) resolves to the SAME global number 1.
    assert narrs[("gene_set", "kidney", "Male")] == ["Kidney cites [1]."]


def test_no_pools_leaves_references_from_background(tmp_path, monkeypatch):
    """A session whose interpretation caches carry NO reference_pool (older or
    apical-only) must not fabricate references — background.json still governs
    that section, and here there's no genomics at all so references stays as the
    scaffold's empty list."""
    monkeypatch.setattr(session_store, "SESSIONS_DIR", tmp_path)
    (tmp_path / DTXSID / "files").mkdir(parents=True)
    data = latex_export.load_session_data(DTXSID, chemical_name="Test", casrn="0-0-0")
    # Scaffold default: empty references list (no graph pools, no background.json).
    assert data.get("references") == []


# ---------------------------------------------------------------------------
# marshal_export_data (web preview / Overleaf / Commit-Local) path
# ---------------------------------------------------------------------------
# This path reads references from the request body; when the body doesn't carry
# them (the browser doesn't round-trip graph refs), it must fall back to the
# persisted references.json — the SAME artifact the session-export path reads.

import rendering.report_data as report_data  # noqa: E402


def _persisted_refs(sess):
    (sess).mkdir(parents=True, exist_ok=True)
    (sess / "references.json").write_text(json.dumps({
        "references": [
            {"n": 1, "paper_id": "pb", "title": "Paper B", "year": 2021,
             "venue": "VB", "doi": "10.1/b", "citation_count": 5, "genes": []},
            {"n": 2, "paper_id": "pa", "title": "Paper A", "year": 2020,
             "venue": "VA", "doi": "10.1/a", "citation_count": 10, "genes": []},
        ],
        "paragraphs": [
            "[1] Paper B. VB. 2021. https://doi.org/10.1/b",
            "[2] Paper A. VA. 2020. https://doi.org/10.1/a",
        ],
    }))


def test_marshal_falls_back_to_persisted_references(tmp_path, monkeypatch):
    """With no `references` in the body, marshal_export_data populates the
    References section from references.json (the process-time artifact)."""
    monkeypatch.setattr(session_store, "SESSIONS_DIR", tmp_path)
    _persisted_refs(tmp_path / DTXSID)

    data = report_data.marshal_export_data({
        "chemical_name": "Test Article", "casrn": "1-1-1", "dtxsid": DTXSID,
    })
    assert data["references"]["paragraphs"] == [
        "[1] Paper B. VB. 2021. https://doi.org/10.1/b",
        "[2] Paper A. VA. 2020. https://doi.org/10.1/a",
    ]


def test_marshal_body_references_win_over_persisted(tmp_path, monkeypatch):
    """A body that DOES carry references (e.g. the user's own list) takes
    precedence over the persisted graph references — no silent override."""
    monkeypatch.setattr(session_store, "SESSIONS_DIR", tmp_path)
    _persisted_refs(tmp_path / DTXSID)

    data = report_data.marshal_export_data({
        "chemical_name": "Test Article", "casrn": "1-1-1", "dtxsid": DTXSID,
        "references": ["[1] My own reference."],
    })
    assert data["references"]["paragraphs"] == ["[1] My own reference."]


def test_marshal_no_session_leaves_empty_references(tmp_path, monkeypatch):
    """No body references and no references.json ⇒ the scaffold's empty list
    stands (the marshal-golden contract — a dtxsid with no session dir)."""
    monkeypatch.setattr(session_store, "SESSIONS_DIR", tmp_path)
    data = report_data.marshal_export_data({
        "chemical_name": "Test Article", "casrn": "1-1-1",
        "dtxsid": "DTXSID_NO_SESSION",
    })
    assert data["references"] == []


# ---------------------------------------------------------------------------
# Two-store hazard surfaces through build_session_references (disk override)
# ---------------------------------------------------------------------------
from narrative.references_builder import build_session_references  # noqa: E402


def test_build_session_references_surfaces_override_hazard_warnings(tmp_path):
    """A human-edited narrative (override store) carrying an out-of-pool [Pn]
    surfaces as a machine-readable warning from build_session_references — the
    detect-and-warn for the two-store hazard, read off disk end-to-end."""
    sess = tmp_path / DTXSID
    _stage_session(sess.parent)  # writes genomics + interp caches (pools P1..P2)
    # The human edited the liver gene-set narrative and added an out-of-pool [P9]
    # plus a hand-typed [7]; this lands in the SEPARATE override store.
    (sess / "genomics_narrative_overrides.json").write_text(json.dumps({
        "gene_set": {"liver": ["Human edit citing valid [P1], invented [P9], typed [7]."]},
        "gene_bmd": {},
    }))

    result = build_session_references(sess, {
        "liver_Male": {"organ": "liver", "sex": "Male"},
        "kidney_Male": {"organ": "kidney", "sex": "Male"},
    }, dtxsid=DTXSID)

    issues = {(w["issue"], tuple(w["tokens"])) for w in result["warnings"]}
    assert ("out_of_pool_token", ("P9",)) in issues
    assert ("hand_typed_citation", ("[7]",)) in issues
    # References still assemble normally (the hazard is reported, not fatal).
    assert result["references"]
