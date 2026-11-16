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
    from knowledge_base.toxkb import ToxKBQuerier


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
# The tested family
# ---------------------------------------------------------------------------

# A term is reported when at least this many responsive genes are in it.  A
# REPORTING rule only: the multiple-testing family is every term the knowledge
# base defines (below), fixed before the data are seen.
MIN_REPORTED_OVERLAP = 2


def _over_representation(
    responsive_by_term: dict[str, list[str]],
    term_sizes: dict[str, int],
    n_responsive: int,
    bg_total: int,
    fdr_cutoff: float,
) -> list[dict]:
    """Fisher's exact test (one-sided, over-representation) for EVERY term the
    knowledge base defines (``term_sizes``), Benjamini-Hochberg across all of
    them, then the terms with at least MIN_REPORTED_OVERLAP responsive genes
    and FDR below ``fdr_cutoff``.

    The family is the knowledge base's terms, not the terms the responsive
    genes happen to hit: a term with no responsive gene has p = 1 and still
    counts toward the correction.  Correcting only over the terms with an
    observed overlap makes the family depend on the results and understates
    the FDR (a synthetic case: 0.0039 over the hit terms, 0.388 over 100
    predefined pathways).  Each record carries ``family_size``."""
    family = [t for t, size in term_sizes.items() if size > 0]
    tested = []
    for term in family:
        genes = responsive_by_term.get(term) or []
        a = len(genes)
        size = term_sizes[term]
        if a == 0:
            pval = 1.0
        else:
            b = n_responsive - a
            c = size - a
            d = bg_total - size - b
            _, pval = fisher_exact([[a, b], [c, d]], alternative="greater")
        tested.append((term, genes, size, pval))
    fdrs = benjamini_hochberg([p for *_, p in tested])
    return [{"term": term, "overlap_genes": sorted(genes), "overlap_count": len(genes),
             "size": size, "pvalue": pval, "fdr": fdr, "family_size": len(family)}
            for (term, genes, size, pval), fdr in zip(tested, fdrs)
            if len(genes) >= MIN_REPORTED_OVERLAP and fdr < fdr_cutoff]


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

    Every pathway the knowledge base defines is tested (_over_representation);
    for each, a 2x2 table:
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

    results = _over_representation(pathway_responsive, pathway_counts, n_responsive,
                                   bg_total, fdr_cutoff)
    for r in results:
        r["pathway_name"] = r.pop("term")
        r["pathway_size"] = r.pop("size")
    results.sort(key=lambda x: (x["pvalue"], x["pathway_name"]))  # ties: by name, never set order
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

    results = _over_representation(go_responsive, go_counts, n_responsive, bg_total,
                                   fdr_cutoff)
    for r in results:
        r["go_id"] = r.pop("term")
        r["term_size"] = r.pop("size")
        r["go_term"] = kb.go_term_name(r["go_id"])
    results.sort(key=lambda x: (x["pvalue"], x["go_id"]))  # ties: by id, never set order
    return results
