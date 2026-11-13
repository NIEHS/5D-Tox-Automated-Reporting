"""
Regression test for the Fisher 2x2 contingency bug in interpret.py's
over-representation analysis (enrich_pathways / enrich_go_terms).

The responsive gene set must be a SUBSET of the KB background universe before
a 2x2 table is built:

                  In pathway    Not in pathway
    Responsive        a              b
    Not responsive    c              d

Before the fix, n_responsive counted every responsive gene — including probes
with no symbol in the KB (the genes table).  Those out-of-universe genes
inflated b = n_responsive - a, which drove d = bg_total - pathway_size - b
negative.  The code clamped d (and c) to 0, producing a contingency table
whose cells no longer summed to bg_total — silently corrupting the p-value for
every pathway and GO term.

The fix intersects the responsive set with kb.background_genes() and derives
bg_total from that same universe, so the margins are consistent by
construction and the d-cell can never go negative.

These tests capture the exact table handed to fisher_exact and assert it is a
valid contingency table (non-negative cells that sum to bg_total) and that the
p-value matches scipy on that consistent table.  Pre-fix, the captured table
sums to less than bg_total, so the margin-consistency assertion fails.
"""

import pytest
from scipy.stats import fisher_exact

import knowledge_base.enrichment_stats as enrichment_stats
import narrative.interpret as interpret


# Background universe: 100 genes (g1..g100).
_UNIVERSE = {f"g{i}" for i in range(1, 101)}
_BG_TOTAL = 100

# 20 responsive genes live in the universe; of those, g1..g4 are in pathway
# "P1" (a = 4).  The remaining 16 are responsive but map to no pathway/term.
_IN_BG_RESPONSIVE = [f"g{i}" for i in range(1, 21)]
_HITS = ["g1", "g2", "g3", "g4"]

# 90 responsive probes have NO symbol in the KB.  Pre-fix these inflate
# n_responsive to 110, forcing d = 100 - 10 - (110 - 4) = -16 → clamped to 0.
_OUT_OF_UNIVERSE = [f"x{i}" for i in range(90)]

_RESPONSIVE = _IN_BG_RESPONSIVE + _OUT_OF_UNIVERSE

_PATHWAY_SIZE = 10
_GO_SIZE = 10


class _FakeKB:
    """Minimal ToxKBQuerier stand-in covering only the methods the two
    enrichment functions touch.  No duckdb file is opened."""

    def background_genes(self) -> set[str]:
        return set(_UNIVERSE)

    def total_gene_count(self) -> int:
        return _BG_TOTAL

    # ── pathways ──────────────────────────────────────────────────────────
    def all_pathway_gene_counts(self) -> dict[str, int]:
        return {"P1": _PATHWAY_SIZE}

    def gene_pathways(self, gene: str) -> list[dict]:
        return [{"pathway_name": "P1"}] if gene in _HITS else []

    # ── GO terms ──────────────────────────────────────────────────────────
    def all_go_term_gene_counts(self) -> dict[str, int]:
        return {"GO:0001": _GO_SIZE}

    def gene_go_terms(self, gene: str) -> list[dict]:
        return [{"go_id": "GO:0001"}] if gene in _HITS else []

    def go_term_name(self, go_id: str) -> str:
        return "test term"


@pytest.fixture
def captured_tables(monkeypatch):
    """Spy on fisher_exact, recording every 2x2 table while still returning a
    real p-value so the BH/filter tail behaves normally."""
    tables: list[list[list[int]]] = []
    real = enrichment_stats.fisher_exact

    def _spy(table, **kwargs):
        tables.append([list(table[0]), list(table[1])])
        return real(table, **kwargs)

    monkeypatch.setattr(enrichment_stats, "fisher_exact", _spy)
    return tables


def _assert_valid_contingency(table):
    (a, b), (c, d) = table
    assert a >= 0 and b >= 0 and c >= 0 and d >= 0, (
        f"contingency cell went negative: {table}"
    )
    assert a + b + c + d == _BG_TOTAL, (
        f"margins inconsistent — table sums to {a + b + c + d}, expected "
        f"bg_total={_BG_TOTAL}.  Out-of-universe responsive genes were not "
        f"excluded, so a clamped cell corrupted the table: {table}"
    )


def test_enrich_pathways_excludes_out_of_background(captured_tables):
    results = interpret.enrich_pathways(_RESPONSIVE, _FakeKB(), fdr_cutoff=1.0)

    assert len(captured_tables) == 1, "exactly one pathway should be tested"
    table = captured_tables[0]
    _assert_valid_contingency(table)

    (a, b), (c, d) = table
    # 4 responsive-in-pathway, 16 responsive-not-in-pathway (the 90
    # out-of-universe probes are gone, NOT folded into b).
    assert (a, b) == (4, 16)
    assert (c, d) == (_PATHWAY_SIZE - 4, _BG_TOTAL - _PATHWAY_SIZE - 16)

    # The reported p-value matches scipy on the consistent table.
    _, expected = fisher_exact([[4, 16], [6, 74]], alternative="greater")
    p1 = next(r for r in results if r["pathway_name"] == "P1")
    assert p1["pvalue"] == pytest.approx(expected)


def test_enrich_go_terms_excludes_out_of_background(captured_tables):
    results = interpret.enrich_go_terms(_RESPONSIVE, _FakeKB(), fdr_cutoff=1.0)

    assert len(captured_tables) == 1
    table = captured_tables[0]
    _assert_valid_contingency(table)

    (a, b), (c, d) = table
    assert (a, b) == (4, 16)
    assert (c, d) == (_GO_SIZE - 4, _BG_TOTAL - _GO_SIZE - 16)

    _, expected = fisher_exact([[4, 16], [6, 74]], alternative="greater")
    go = next(r for r in results if r["go_id"] == "GO:0001")
    assert go["pvalue"] == pytest.approx(expected)
