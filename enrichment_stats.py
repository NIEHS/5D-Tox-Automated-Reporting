"""
Pure statistical core for over-representation analysis.

Extracted from interpret.py: the Benjamini-Hochberg FDR correction and the
Fisher's exact 2x2 enrichment math for pathways and GO terms.  These functions
have no DB or filesystem state of their own — they take a ToxKBQuerier purely as
a typed data source — which is why they form the lowest-blast-radius cut out of
the ~2400-line interpret module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from scipy.stats import fisher_exact

if TYPE_CHECKING:
    from interpret import ToxKBQuerier


# ---------------------------------------------------------------------------
# BH FDR correction
# ---------------------------------------------------------------------------

def benjamini_hochberg(pvalues: list[float]) -> list[float]:
    """Benjamini-Hochberg FDR correction. Returns adjusted p-values."""
    n = len(pvalues)
    if n == 0:
        return []
    indexed = sorted(enumerate(pvalues), key=lambda x: x[1])
    adjusted = [0.0] * n
    prev = 1.0
    for rank_minus_1 in range(n - 1, -1, -1):
        orig_idx, pval = indexed[rank_minus_1]
        rank = rank_minus_1 + 1
        adj = min(prev, pval * n / rank)
        adjusted[orig_idx] = adj
        prev = adj
    return adjusted


# ---------------------------------------------------------------------------
# Pathway enrichment (Fisher's exact test)
# ---------------------------------------------------------------------------

def enrich_pathways(
    responsive_genes: list[str],
    kb: "ToxKBQuerier",
    fdr_cutoff: float = 0.05,
) -> list[dict]:
    """
    Over-representation analysis for pathways using Fisher's exact test.

    For each pathway with at least one responsive gene, build a 2x2 table:
                      In pathway    Not in pathway
    Responsive           a              b
    Not responsive       c              d

    Background = all genes in the KB (genes table).
    """
    # The responsive set MUST be a subset of the background universe.  Genes
    # absent from the KB (e.g. probes with no symbol mapping) are not part of
    # the population Fisher's test draws from; counting them inflates the "not
    # in pathway" margin (b) and drives the d-cell negative.  Intersecting here
    # — and measuring bg_total from the same universe — keeps the 2x2 margins
    # consistent so every cell is non-negative by construction.
    background = kb.background_genes()
    bg_total = len(background)
    responsive_set = set(responsive_genes) & background
    n_responsive = len(responsive_set)

    pathway_counts = kb.all_pathway_gene_counts()

    # Map each responsive gene to its pathways
    gene_to_pathways: dict[str, set[str]] = {}
    for gene in responsive_set:
        pathways = kb.gene_pathways(gene)
        if pathways:
            gene_to_pathways[gene] = {p["pathway_name"] for p in pathways}

    # Count responsive genes per pathway
    pathway_responsive: dict[str, list[str]] = {}
    for gene, pnames in gene_to_pathways.items():
        for pname in pnames:
            pathway_responsive.setdefault(pname, []).append(gene)

    results = []
    pvals = []

    for pathway_name, genes_in_pathway in pathway_responsive.items():
        a = len(genes_in_pathway)
        if a < 2:
            continue  # skip singletons
        b = n_responsive - a
        pathway_size = pathway_counts.get(pathway_name, 0)
        c = pathway_size - a
        d = bg_total - pathway_size - b

        _, pval = fisher_exact([[a, b], [c, d]], alternative="greater")

        results.append({
            "pathway_name": pathway_name,
            "overlap_genes": sorted(genes_in_pathway),
            "overlap_count": a,
            "pathway_size": pathway_size,
            "pvalue": pval,
        })
        pvals.append(pval)

    # BH correction
    if pvals:
        fdrs = benjamini_hochberg(pvals)
        for i, r in enumerate(results):
            r["fdr"] = fdrs[i]
    else:
        for r in results:
            r["fdr"] = 1.0

    # Filter and sort
    results = [r for r in results if r["fdr"] < fdr_cutoff]
    results.sort(key=lambda x: x["pvalue"])
    return results


# ---------------------------------------------------------------------------
# GO term enrichment (Fisher's exact test)
# ---------------------------------------------------------------------------

def enrich_go_terms(
    responsive_genes: list[str],
    kb: "ToxKBQuerier",
    fdr_cutoff: float = 0.05,
) -> list[dict]:
    """
    Over-representation analysis for GO terms using Fisher's exact test.
    Same logic as enrich_pathways but against gene_go_terms table.
    """
    # Restrict to the background universe so the 2x2 margins stay consistent;
    # see enrich_pathways for the full rationale.
    background = kb.background_genes()
    bg_total = len(background)
    responsive_set = set(responsive_genes) & background
    n_responsive = len(responsive_set)

    go_counts = kb.all_go_term_gene_counts()

    # Map each responsive gene to its GO terms
    gene_to_go: dict[str, set[str]] = {}
    for gene in responsive_set:
        terms = kb.gene_go_terms(gene)
        if terms:
            gene_to_go[gene] = {t["go_id"] for t in terms}

    # Count responsive genes per GO term
    go_responsive: dict[str, list[str]] = {}
    for gene, go_ids in gene_to_go.items():
        for go_id in go_ids:
            go_responsive.setdefault(go_id, []).append(gene)

    results = []
    pvals = []

    for go_id, genes_in_term in go_responsive.items():
        a = len(genes_in_term)
        if a < 2:
            continue
        b = n_responsive - a
        term_size = go_counts.get(go_id, 0)
        c = term_size - a
        d = bg_total - term_size - b

        _, pval = fisher_exact([[a, b], [c, d]], alternative="greater")

        go_name = kb.go_term_name(go_id)
        results.append({
            "go_id": go_id,
            "go_term": go_name,
            "overlap_genes": sorted(genes_in_term),
            "overlap_count": a,
            "term_size": term_size,
            "pvalue": pval,
        })
        pvals.append(pval)

    if pvals:
        fdrs = benjamini_hochberg(pvals)
        for i, r in enumerate(results):
            r["fdr"] = fdrs[i]
    else:
        for r in results:
            r["fdr"] = 1.0

    results = [r for r in results if r["fdr"] < fdr_cutoff]
    results.sort(key=lambda x: x["pvalue"])
    return results
