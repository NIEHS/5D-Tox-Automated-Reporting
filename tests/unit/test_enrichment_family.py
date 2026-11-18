"""The enrichment FDR is corrected across every term the knowledge base defines,
not only the terms the responsive genes happen to hit (independent review,
2026-11-16)."""

from scipy.stats import fisher_exact

from knowledge_base.enrichment_stats import benjamini_hochberg, enrich_go_terms, enrich_pathways


class _KB:
    """100 pathways of 10 genes over 1,000 genes; the 5 responsive genes are all
    in pathway P0, so it is the only pathway the data touch."""

    def __init__(self):
        self.members = {f"P{i}": [f"g{i * 10 + j}" for j in range(10)] for i in range(100)}

    def background_genes(self):
        return {g for genes in self.members.values() for g in genes}

    def all_pathway_gene_counts(self):
        return {p: len(g) for p, g in self.members.items()}

    def gene_pathways(self, gene):
        return [{"pathway_name": p} for p, g in self.members.items() if gene in g]

    all_go_term_gene_counts = all_pathway_gene_counts

    def gene_go_terms(self, gene):
        return [{"go_id": p} for p, g in self.members.items() if gene in g]

    def go_term_name(self, go_id):
        return go_id


RESPONSIVE = ["g0", "g1", "g990", "g991", "g500"]   # 2 in P0, 2 in P99, 1 in P50


def test_the_family_is_every_defined_term_not_the_hit_ones():
    [a, b] = [fisher_exact([[2, 3], [8, 987]], alternative="greater")[1]] * 2
    over_hits = benjamini_hochberg([a, b, 1.0])[0]          # the old family: 2-3 terms
    over_all = benjamini_hochberg([a, b] + [1.0] * 98)[0]   # every defined pathway
    assert over_all > over_hits * 30

    results = enrich_pathways(RESPONSIVE, _KB(), fdr_cutoff=1.0)
    assert [r["pathway_name"] for r in results] == ["P0", "P99"]   # P50: one gene, not reported
    assert all(r["family_size"] == 100 for r in results)
    assert abs(results[0]["fdr"] - over_all) < 1e-12

    go = enrich_go_terms(RESPONSIVE, _KB(), fdr_cutoff=1.0)
    assert [(r["go_id"], r["family_size"]) for r in go] == [("P0", 100), ("P99", 100)]
    assert abs(go[0]["fdr"] - over_all) < 1e-12


def test_a_cutoff_is_applied_to_the_family_corrected_fdr():
    """P0's FDR is 0.0027 over the pathways hit, 0.044 over all 100: it passes
    0.05 and no longer passes 0.01."""
    assert [r["pathway_name"] for r in enrich_pathways(RESPONSIVE, _KB(), fdr_cutoff=0.05)] \
        == ["P0", "P99"]
    assert enrich_pathways(RESPONSIVE, _KB(), fdr_cutoff=0.01) == []
