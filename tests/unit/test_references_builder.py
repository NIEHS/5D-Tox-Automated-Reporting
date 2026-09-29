"""
Unit tests for the graph-grounded references builder.

Two concerns are pinned:
  * the candidate POOL is a pure, deterministic graph computation (same genes ->
    same pool, stable [Pn] token order, full metadata resolution) — tested
    against the real bmdx.duckdb shipped in the worktree, with NO network;
  * report-wide ASSEMBLY merges per-stratum [Pn] citations into ONE globally
    numbered list and rewrites inline tokens to [n] — tested with tiny in-memory
    fixtures so it needs no DB and no LLM.
"""

from __future__ import annotations

import pathlib

import pytest

from narrative.references_builder import (
    assemble_report_references,
    build_reference_pool,
    build_reference_pool_for_genes,
    cited_tokens_in_order,
    detect_override_citation_hazards,
    format_reference_entry,
    references_paragraphs,
)

DB_PATH = pathlib.Path(__file__).resolve().parents[2] / "bmdx.duckdb"

# A gene set with known KB coverage (liver/male PFHxSAm responsive genes).
_GENES = ["CYP7A1", "EGR1", "MYC", "NFKBIA", "PRLR", "ABCB1A"]


# ---------------------------------------------------------------------------
# Fake KB — assembly/pool logic tests that don't need the real DB
# ---------------------------------------------------------------------------
class _FakeKB:
    """Minimal ToxKBQuerier stand-in: gene_papers + papers_metadata only."""

    def __init__(self, gene_papers: dict, meta: dict):
        self._gp = gene_papers
        self._meta = meta

    def gene_papers(self, gene):
        return self._gp.get(gene, [])

    def papers_metadata(self, ids):
        return {pid: self._meta[pid] for pid in ids if pid in self._meta}


def test_pool_ranks_multi_gene_papers_first_and_is_deterministic():
    gp = {
        "A": [
            {"paper_id": "shared", "title": "Shared", "year": 2020, "citation_count": 5},
            {"paper_id": "solo_a", "title": "Solo A", "year": 2019, "citation_count": 99},
        ],
        "B": [
            {"paper_id": "shared", "title": "Shared", "year": 2020, "citation_count": 5},
        ],
    }
    meta = {
        "shared": {"title": "Shared", "year": 2020, "venue": "V1", "doi": "10.1/s", "citation_count": 5},
        "solo_a": {"title": "Solo A", "year": 2019, "venue": "V2", "doi": "10.1/a", "citation_count": 99},
    }
    kb = _FakeKB(gp, meta)
    pool = build_reference_pool(["A", "B"], kb, pool_size=10)

    # The 2-gene paper outranks the higher-cited 1-gene paper.
    assert [p["token"] for p in pool] == ["P1", "P2"]
    assert pool[0]["paper_id"] == "shared"
    assert pool[0]["genes"] == ["A", "B"]
    assert pool[0]["doi"] == "10.1/s" and pool[0]["venue"] == "V1"
    # Deterministic: rebuilding yields the identical token order.
    again = build_reference_pool(["A", "B"], kb, pool_size=10)
    assert [p["paper_id"] for p in again] == [p["paper_id"] for p in pool]


def test_pool_gene_symbols_are_uppercased_before_lookup():
    gp = {"CYP7A1": [{"paper_id": "x", "title": "T", "year": 2021, "citation_count": 1}]}
    meta = {"x": {"title": "T", "year": 2021, "venue": "V", "doi": "10.1/x", "citation_count": 1}}
    kb = _FakeKB(gp, meta)
    # lower-case input must still hit the upper-case graph symbol
    pool = build_reference_pool(["cyp7a1"], kb, pool_size=5)
    assert len(pool) == 1 and pool[0]["paper_id"] == "x"


def test_cited_tokens_in_order_dedup_and_combined_brackets():
    gs = ["Claim one [P3] and two [P1].", "Again [P3]."]
    gn = ["Combined [P1, P5] citation."]
    assert cited_tokens_in_order(gs, gn) == ["P3", "P1", "P5"]


def test_assemble_numbers_papers_globally_and_rewrites_tokens():
    strata = [
        {
            "organ": "liver", "sex": "male",
            "reference_pool": [
                {"token": "P1", "paper_id": "pa", "title": "Paper A", "year": 2020,
                 "venue": "VA", "doi": "10.1/a", "citation_count": 10, "genes": ["CYP7A1"]},
                {"token": "P2", "paper_id": "pb", "title": "Paper B", "year": 2021,
                 "venue": "VB", "doi": "10.1/b", "citation_count": 5, "genes": ["EGR1"]},
            ],
            "gene_set_narrative": ["Liver sets cite [P2] and [P1]."],
            "gene_narrative": ["Liver genes cite [P1]."],
        },
        {
            "organ": "kidney", "sex": "male",
            "reference_pool": [
                # Same physical paper pb, but a DIFFERENT local token in this stratum.
                {"token": "P1", "paper_id": "pb", "title": "Paper B", "year": 2021,
                 "venue": "VB", "doi": "10.1/b", "citation_count": 5, "genes": ["EGR1"]},
                {"token": "P2", "paper_id": "pc", "title": "Paper C", "year": 2022,
                 "venue": "VC", "doi": "10.1/c", "citation_count": 1, "genes": ["MYC"]},
            ],
            "gene_set_narrative": ["Kidney cites [P1] and [P2]."],
            "gene_narrative": [],
        },
    ]
    references, rewritten = assemble_report_references(strata)

    # Global numbering: liver gene-set prose cites P2(pb) first, then P1(pa);
    # so pb -> 1, pa -> 2; kidney's pc -> 3.  pb keeps its number across strata.
    by_pid = {r["paper_id"]: r["n"] for r in references}
    assert by_pid == {"pb": 1, "pa": 2, "pc": 3}
    assert [r["n"] for r in references] == [1, 2, 3]

    # Inline tokens rewritten to the report-wide numbers.
    assert rewritten[0]["gene_set_narrative"] == ["Liver sets cite [1] and [2]."]
    assert rewritten[0]["gene_narrative"] == ["Liver genes cite [2]."]
    # Kidney's LOCAL P1 (pb) -> global 1, local P2 (pc) -> global 3.
    assert rewritten[1]["gene_set_narrative"] == ["Kidney cites [1] and [3]."]
    # Organ/sex carried through.
    assert rewritten[1]["organ"] == "kidney" and rewritten[1]["sex"] == "male"


def test_assemble_drops_out_of_pool_tokens():
    strata = [{
        "organ": "liver", "sex": "male",
        "reference_pool": [
            {"token": "P1", "paper_id": "pa", "title": "A", "year": 2020,
             "venue": "V", "doi": "10.1/a", "citation_count": 1, "genes": []},
        ],
        "gene_set_narrative": ["Valid [P1] but invented [P9] token."],
        "gene_narrative": [],
    }]
    references, rewritten = assemble_report_references(strata)
    assert len(references) == 1
    # The invented [P9] (not in the pool) is dropped, not left dangling.
    assert rewritten[0]["gene_set_narrative"] == ["Valid [1] but invented token."]


def test_format_and_paragraphs():
    refs = [{"n": 1, "paper_id": "x", "title": "A Study.", "year": 2024,
             "venue": "Nature", "doi": "10.1/x", "citation_count": 3, "genes": []}]
    line = format_reference_entry(refs[0])
    assert line == "[1] A Study. Nature. 2024. https://doi.org/10.1/x"
    assert references_paragraphs(refs) == [line]


# ---------------------------------------------------------------------------
# Two-store hazard: detect (don't fix) citations in human-edited narratives
# ---------------------------------------------------------------------------
def test_detect_override_citation_hazards_flags_out_of_pool_and_hand_typed():
    """A human edit (in the override store) that carries an out-of-pool [Pn] AND
    a hand-typed final-form [12] must be FLAGGED — the assembly reads the cache,
    not the override, so these would otherwise be silently dropped/collide."""
    pools_by_organ = {"liver": {"P1", "P2", "P3"}}
    overrides = {
        "gene_set": {
            # [P2] is valid; [P9] is out of pool; [12] is a hand-typed citation.
            "Liver": ["Human edit citing [P2], invented [P9], and hand-typed [12]."],
        },
        "gene_bmd": {},
    }
    warnings = detect_override_citation_hazards(overrides, pools_by_organ)
    issues = {(w["issue"], tuple(w["tokens"])) for w in warnings}
    assert ("out_of_pool_token", ("P9",)) in issues
    assert ("hand_typed_citation", ("[12]",)) in issues
    # The valid in-pool [P2] alone raises nothing.
    assert all(w["organ"] == "liver" and w["kind"] == "gene_set" for w in warnings)


def test_detect_override_citation_hazards_clean_when_no_edits():
    """No overrides ⇒ no warnings (byte-identical to the no-edit path)."""
    assert detect_override_citation_hazards({}, {"liver": {"P1"}}) == []
    assert detect_override_citation_hazards(
        {"gene_set": {}, "gene_bmd": {}}, {"liver": {"P1"}},
    ) == []


def test_detect_override_in_pool_tokens_do_not_warn():
    """An override that only re-uses valid in-pool [Pn] tokens is NOT flagged."""
    overrides = {"gene_set": {"liver": ["Edit cites [P1] and [P2] only."]}, "gene_bmd": {}}
    assert detect_override_citation_hazards(overrides, {"liver": {"P1", "P2"}}) == []


# ---------------------------------------------------------------------------
# Real-DB tests — the pool against the shipped bmdx.duckdb (no network)
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not DB_PATH.exists(), reason="bmdx.duckdb not present")
class TestRealDB:
    def test_pool_from_real_graph_is_deterministic_and_resolved(self):
        pool_a = build_reference_pool_for_genes(_GENES, str(DB_PATH), pool_size=20)
        pool_b = build_reference_pool_for_genes(_GENES, str(DB_PATH), pool_size=20)
        assert pool_a, "expected a non-empty pool for known liver genes"
        # Same genes -> byte-identical pool (id + token order).
        assert [(p["token"], p["paper_id"]) for p in pool_a] == \
               [(p["token"], p["paper_id"]) for p in pool_b]
        # Tokens are P1..Pn in order.
        assert [p["token"] for p in pool_a] == [f"P{i}" for i in range(1, len(pool_a) + 1)]
        # Metadata resolved from the papers table (most have a DOI).
        assert any(p["doi"] for p in pool_a)
        for p in pool_a:
            assert p["title"] and p["paper_id"]

    def test_pool_respects_size_cap(self):
        pool = build_reference_pool_for_genes(_GENES, str(DB_PATH), pool_size=5)
        assert len(pool) <= 5

    def test_empty_gene_set_yields_empty_pool(self):
        assert build_reference_pool_for_genes([], str(DB_PATH)) == []
