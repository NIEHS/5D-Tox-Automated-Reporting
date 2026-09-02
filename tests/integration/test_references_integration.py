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
