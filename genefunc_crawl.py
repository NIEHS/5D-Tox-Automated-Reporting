"""
Gene-function second-pass crawl.

Searches Semantic Scholar for each consensus/moderate gene's biological
function in its associated organs. Unlike the main citegraph crawl, this
does NOT require toxicogenomics vocabulary — it looks for papers that
explain WHY a gene matters for organ-specific biology (e.g., "MFN2
regulates mitochondrial fusion in cardiomyocytes").

Usage:
    python genefunc_crawl.py [max_papers] [consensus_path]
"""

import json
import re
import time
from pathlib import Path

import networkx as nx

from citegraph import (
    S2Client,
    Paper,
    GovernorConfig,
    tag_organs,
)


# ---------------------------------------------------------------------------
# Load gene-organ pairs from consensus JSON
# ---------------------------------------------------------------------------

# Canonical organ keywords for search queries (subset of GovernorConfig.organ_keywords)
ORGAN_SEARCH_TERMS: dict[str, list[str]] = {
    "liver": ["liver", "hepatocyte"],
    "kidney": ["kidney", "renal"],
    "heart": ["heart", "cardiomyocyte", "cardiac"],
    "lung": ["lung", "pulmonary"],
    "brain": ["brain", "neuron", "cortical"],
    "intestine": ["intestine", "gut", "enterocyte"],
    "muscle": ["muscle", "skeletal muscle"],
    "bone marrow": ["bone marrow", "hematopoietic"],
    "blood": ["blood", "leukocyte"],
    "spleen": ["spleen"],
    "thyroid": ["thyroid"],
    "adrenal": ["adrenal"],
    "testis": ["testis", "testicular"],
    "skin": ["skin", "dermal"],
    "stomach": ["stomach", "gastric"],
    "pancreas": ["pancreas", "pancreatic"],
}

# Map noisy organ names from the consensus JSON to canonical organs
ORGAN_NORMALIZE: dict[str, str] = {
    "hepatocytes": "liver",
    "hepatocyte": "liver",
    "hepatic": "liver",
    "renal": "kidney",
    "kidneys": "kidney",
    "lungs": "lung",
    "hearts": "heart",
    "brains": "brain",
    "cardiovascular system": "heart",
    "pulmonary system": "lung",
    "neurons": "brain",
    "a549 lung cells": "lung",
    "airway epithelial cells": "lung",
    "astrocytes": "brain",
    "brain cell populations": "brain",
    "immune cells": "blood",
    "mcf-7 cells": "breast",
    "fibroblasts": "skin",
}


def load_gene_organ_pairs(
    consensus_path: str = "citegraph_output/gene_consensus.json",
) -> list[tuple[str, list[str]]]:
    """
    Load genes + their organs from the consensus JSON.
    Returns list of (gene_symbol, [canonical_organ, ...]).
    Includes both consensus (3+ papers) and moderate (2 papers) genes.
    """
    with open(consensus_path) as f:
        data = json.load(f)

    pairs: list[tuple[str, list[str]]] = []

    for category in ("consensus_genes", "moderate_evidence"):
        for gene, info in data.get(category, {}).items():
            raw_organs = info.get("organs", [])
            # Normalize to canonical organ names and deduplicate
            canonical = set()
            for o in raw_organs:
                o_lower = o.lower().strip()
                normalized = ORGAN_NORMALIZE.get(o_lower, o_lower)
                if normalized in ORGAN_SEARCH_TERMS:
                    canonical.add(normalized)
            # Default to liver if no recognized organs (most tox papers are liver)
            if not canonical:
                canonical.add("liver")
            pairs.append((gene, sorted(canonical)))

    return pairs


# ---------------------------------------------------------------------------
# Build search queries
# ---------------------------------------------------------------------------

# Gene-function query templates
QUERY_TEMPLATES = [
    "{gene} {organ_term} function mechanism",
    "{gene} {organ_term} role biological",
    "{gene} expression {organ_term}",
]

# Tox-focused query templates for Tier 3 gene-tox crawls
TOX_QUERY_TEMPLATES = [
    "{gene} dose response toxicity",
    "{gene} {organ_term} toxicogenomics",
    "{gene} chemical exposure dose dependent",
]

# Genes flagged by interpretation as lacking tox dose-response evidence
GENETOX_TARGETS = [
    {"gene": "GDF15",  "bmd": 7.0,  "organs": ["liver", "kidney"],
     "focus": "GDF15 biomarker toxicity dose-response"},
    {"gene": "NLRP3",  "bmd": 13.0, "organs": ["liver", "blood"],
     "focus": "NLRP3 inflammasome chemical toxicity"},
    {"gene": "SQSTM1", "bmd": 3.0,  "organs": ["liver"],
     "focus": "p62 SQSTM1 NRF2 autophagy"},
    {"gene": "STAT3",  "bmd": 8.5,  "organs": ["liver", "blood"],
     "focus": "STAT3 JAK-STAT toxicology inflammation"},
    {"gene": "SIRT1",  "bmd": 2.5,  "organs": ["liver", "heart"],
     "focus": "SIRT1 NAD oxidative stress dose response"},
    {"gene": "HIF1A",  "bmd": 3.5,  "organs": ["kidney", "liver"],
     "focus": "HIF1A pseudo-hypoxia ROS"},
    {"gene": "HAVCR1", "bmd": 20.0, "organs": ["kidney"],
     "focus": "KIM-1 nephrotoxicity biomarker dose response"},
    {"gene": "PPARA",  "bmd": 2.0,  "organs": ["liver"],
     "focus": "PPARalpha hepatotoxicity peroxisome proliferator"},
]


def build_search_queries(gene: str, organs: list[str]) -> list[str]:
    """
    Generate S2 search strings for a gene-organ pair.
    E.g., "NFE2L2 oxidative stress liver mechanism"
    """
    queries: list[str] = []
    for organ in organs[:2]:  # limit to 2 organs to stay in budget
        terms = ORGAN_SEARCH_TERMS.get(organ, [organ])
        # Use first (most specific) organ term for each template
        organ_term = terms[0]
        for template in QUERY_TEMPLATES[:2]:  # 2 templates per organ
            q = template.format(gene=gene, organ_term=organ_term)
            queries.append(q)
    return queries


# ---------------------------------------------------------------------------
# Gene-function relevance scoring
# ---------------------------------------------------------------------------

def gene_relevance(
    paper: Paper,
    target_gene: str,
    target_organs: list[str],
    config: GovernorConfig,
) -> float:
    """
    Score relevance based on gene name + organ mention.
    NOT using tox vocabulary — this is for gene-function papers.

    Scoring:
    - Gene name in title: 0.4
    - Gene name in abstract: 0.2
    - Any target organ keyword in text: 0.2
    - Recency bonus (post-2015): up to 0.1
    - Being a review: +0.1
    """
    text_title = (paper.title or "").lower()
    text_abstract = (paper.abstract or "").lower()
    text_combined = text_title + " " + text_abstract

    if not text_combined.strip():
        return 0.0

    score = 0.0
    gene_lower = target_gene.lower()

    # Gene name match (word boundary)
    gene_pattern = re.compile(r'\b' + re.escape(gene_lower) + r'\b')
    if gene_pattern.search(text_title):
        score += 0.4
    elif gene_pattern.search(text_abstract):
        score += 0.2

    # Organ keyword match
    organ_hit = False
    for organ in target_organs:
        organ_terms = ORGAN_SEARCH_TERMS.get(organ, [organ])
        for term in organ_terms:
            if term.lower() in text_combined:
                organ_hit = True
                break
        if organ_hit:
            break
    # Also check the standard organ keywords from config
    if not organ_hit:
        for organ_name, keywords in config.organ_keywords.items():
            if any(kw in text_combined for kw in keywords):
                organ_hit = True
                break

    if organ_hit:
        score += 0.2

    # Recency bonus
    if paper.year and paper.year >= 2015:
        recency = min((paper.year - 2015) / 10, 1.0) * 0.1
        score += recency

    # Review bonus
    if paper.is_review:
        score += 0.1

    return round(min(score, 1.0), 3)


# ---------------------------------------------------------------------------
# Gene-function crawler
# ---------------------------------------------------------------------------

class GeneFuncCrawler:
    """
    Searches S2 for gene-function papers and does 1-hop expansion
    from top results.
    """

    def __init__(
        self,
        max_papers: int = 400,
        max_api_calls: int = 200,
        api_key: str | None = None,
        rate_limit_delay: float = 1.5,
    ):
        self.max_papers = max_papers
        self.max_api_calls = max_api_calls
        self.config = GovernorConfig()  # for organ keywords
        self.client = S2Client(api_key=api_key, delay=rate_limit_delay)
        self.graph = nx.DiGraph()
        self.papers: dict[str, Paper] = {}
        # Track which gene each paper was found for
        self.paper_genes: dict[str, set[str]] = {}

    def _should_stop(self) -> bool:
        if len(self.papers) >= self.max_papers:
            print(f"  [budget: {self.max_papers} papers reached]")
            return True
        if self.client.call_count >= self.max_api_calls:
            print(f"  [budget: {self.max_api_calls} API calls reached]")
            return True
        return False

    def _dict_to_paper(self, data: dict) -> Paper | None:
        pid = data.get("paperId")
        if not pid:
            return None
        ext = data.get("externalIds") or {}
        pub_types = data.get("publicationTypes") or []
        authors_raw = data.get("authors") or []
        return Paper(
            paper_id=pid,
            title=data.get("title") or "",
            authors=[a.get("name", "") for a in authors_raw[:10]],
            year=data.get("year"),
            abstract=data.get("abstract"),
            venue=data.get("venue") or "",
            citation_count=data.get("citationCount") or 0,
            reference_count=data.get("referenceCount") or 0,
            doi=ext.get("DOI"),
            arxiv_id=ext.get("ArXiv"),
            url=data.get("url"),
            is_review="Review" in pub_types,
        )

    def _add_paper(self, paper: Paper, gene: str) -> bool:
        """Add a paper to the graph. Returns True if newly added."""
        if paper.paper_id in self.papers:
            self.paper_genes.setdefault(paper.paper_id, set()).add(gene)
            return False
        self.papers[paper.paper_id] = paper
        self.graph.add_node(paper.paper_id)
        self.paper_genes.setdefault(paper.paper_id, set()).add(gene)
        return True

    def search_gene(self, gene: str, organs: list[str]) -> list[str]:
        """
        Search S2 for gene-function papers. Returns list of paper IDs
        added (for 1-hop expansion).
        """
        queries = build_search_queries(gene, organs)
        top_ids: list[str] = []

        for query in queries:
            if self._should_stop():
                break

            results = self.client.search(query, limit=10)
            for data in results:
                paper = self._dict_to_paper(data)
                if not paper:
                    continue

                rel = gene_relevance(paper, gene, organs, self.config)
                paper.relevance_score = rel
                paper.organs_tagged = tag_organs(paper, self.config)
                paper.genes_mentioned = [gene]

                # Require gene name + organ mention (the whole point of this crawl)
                if rel < 0.3:
                    continue

                if self._add_paper(paper, gene):
                    top_ids.append(paper.paper_id)
                    print(f"    [{rel:.2f}] {paper.title[:70]}... "
                          f"({paper.year}) [{paper.citation_count} cites]")

        return top_ids

    def expand_one_hop(self, paper_ids: list[str], gene: str,
                       organs: list[str], max_per_paper: int = 10):
        """
        1-hop expansion from top search results to catch related
        function papers.
        """
        for pid in paper_ids[:5]:  # limit expansion to top 5
            if self._should_stop():
                break

            refs = self.client.get_references(pid, limit=max_per_paper)
            for ref_data in refs:
                if self._should_stop():
                    return
                paper = self._dict_to_paper(ref_data)
                if not paper or paper.paper_id in self.papers:
                    continue

                rel = gene_relevance(paper, gene, organs, self.config)
                paper.relevance_score = rel
                paper.organs_tagged = tag_organs(paper, self.config)
                paper.genes_mentioned = [gene]

                if rel < 0.3:
                    continue

                if self._add_paper(paper, gene):
                    self.graph.add_edge(pid, paper.paper_id, type="references")

    def save(self, path: str = "citegraph_output_genefunc"):
        """Save graph and paper data to files."""
        outdir = Path(path)
        outdir.mkdir(exist_ok=True)

        papers_out = []
        for p in sorted(self.papers.values(),
                        key=lambda x: x.relevance_score, reverse=True):
            d = {
                "paper_id": p.paper_id,
                "title": p.title,
                "authors": p.authors,
                "year": p.year,
                "abstract": p.abstract,
                "venue": p.venue,
                "citation_count": p.citation_count,
                "reference_count": p.reference_count,
                "doi": p.doi,
                "arxiv_id": p.arxiv_id,
                "url": p.url,
                "relevance_score": p.relevance_score,
                "organs_tagged": p.organs_tagged,
                "genes_mentioned": sorted(self.paper_genes.get(p.paper_id, set())),
                "depth": p.depth,
                "is_seed": p.is_seed,
                "is_review": p.is_review,
                "expanded": p.expanded,
            }
            papers_out.append(d)

        with open(outdir / "papers.json", "w") as f:
            json.dump(papers_out, f, indent=2, default=str)

        edges = []
        for u, v, data in self.graph.edges(data=True):
            edges.append({"source": u, "target": v, "type": data.get("type", "")})
        with open(outdir / "edges.json", "w") as f:
            json.dump(edges, f, indent=2)

        # GML for Gephi/networkx
        g = self.graph.copy()
        for node in g.nodes:
            if node in self.papers:
                p = self.papers[node]
                g.nodes[node]["title"] = p.title
                g.nodes[node]["year"] = p.year or 0
                g.nodes[node]["relevance"] = p.relevance_score
                g.nodes[node]["citations"] = p.citation_count
                g.nodes[node]["organs"] = ",".join(p.organs_tagged)
                g.nodes[node]["genes"] = ",".join(
                    sorted(self.paper_genes.get(node, set())))
        nx.write_gml(g, str(outdir / "citation_graph.gml"))

        print(f"\nSaved to {outdir}/")
        print(f"  papers.json          ({len(papers_out)} papers)")
        print(f"  edges.json           ({len(edges)} edges)")
        print(f"  citation_graph.gml")


def build_tox_search_queries(gene: str, organs: list[str], focus: str) -> list[str]:
    """
    Build tox-focused search queries for a gene from its focus string
    and TOX_QUERY_TEMPLATES.
    """
    queries: list[str] = [focus]
    for organ in organs[:2]:
        terms = ORGAN_SEARCH_TERMS.get(organ, [organ])
        organ_term = terms[0]
        for template in TOX_QUERY_TEMPLATES:
            q = template.format(gene=gene, organ_term=organ_term)
            queries.append(q)
    return queries


def run_genetox_crawl(
    max_papers_per_gene: int = 100,
    api_key: str | None = None,
) -> "GeneFuncCrawler":
    """
    Tier 3: tox-focused gene deep dives for 8 interpretation-flagged genes.

    Uses the focus string + TOX_QUERY_TEMPLATES for search, scores with
    gene_relevance(), does 1-hop expansion, saves to citegraph_output_genetox/.
    """
    total_budget = max_papers_per_gene * len(GENETOX_TARGETS)
    total_api = total_budget * 2  # searches + expansion

    print("=" * 60)
    print("GENE-TOX CRAWL (Tier 3)")
    print(f"Targets: {len(GENETOX_TARGETS)} genes, "
          f"{max_papers_per_gene} papers/gene, {total_budget} total budget")
    print("=" * 60)

    crawler = GeneFuncCrawler(
        max_papers=total_budget,
        max_api_calls=total_api,
        api_key=api_key,
    )

    for i, target in enumerate(GENETOX_TARGETS):
        if crawler._should_stop():
            break
        gene = target["gene"]
        organs = target["organs"]
        focus = target["focus"]
        print(f"\n[{i+1}/{len(GENETOX_TARGETS)}] {gene} (BMD {target['bmd']}) "
              f"— {', '.join(organs)}")

        queries = build_tox_search_queries(gene, organs, focus)
        top_ids: list[str] = []

        for query in queries:
            if crawler._should_stop():
                break
            results = crawler.client.search(query, limit=10)
            for data in results:
                paper = crawler._dict_to_paper(data)
                if not paper:
                    continue
                rel = gene_relevance(paper, gene, organs, crawler.config)
                paper.relevance_score = rel
                paper.organs_tagged = tag_organs(paper, crawler.config)
                paper.genes_mentioned = [gene]
                if rel < 0.3:
                    continue
                if crawler._add_paper(paper, gene):
                    top_ids.append(paper.paper_id)
                    print(f"    [{rel:.2f}] {paper.title[:70]}... "
                          f"({paper.year}) [{paper.citation_count} cites]")

        # 1-hop expansion from top results
        if top_ids and not crawler._should_stop():
            crawler.expand_one_hop(top_ids, gene, organs)

    # Report
    print(f"\n{'='*60}")
    print(f"GENE-TOX CRAWL COMPLETE")
    print(f"{'='*60}")
    print(f"Total papers: {len(crawler.papers)}")
    print(f"Total edges:  {crawler.graph.number_of_edges()}")
    print(f"API calls:    {crawler.client.call_count}")

    genes_found = set()
    for genes in crawler.paper_genes.values():
        genes_found.update(genes)
    print(f"Genes with papers: {len(genes_found)} / {len(GENETOX_TARGETS)}")

    crawler.save("citegraph_output_genetox")
    return crawler


def run_genefunc_crawl(
    consensus_path: str = "citegraph_output/gene_consensus.json",
    max_papers: int = 400,
    max_api_calls: int = 200,
    api_key: str | None = None,
):
    """
    Orchestrator: load genes, search for function papers, expand 1-hop.
    """
    print("="*60)
    print("GENE-FUNCTION CRAWL")
    print("="*60)

    pairs = load_gene_organ_pairs(consensus_path)
    print(f"\nLoaded {len(pairs)} gene-organ pairs")
    for gene, organs in pairs[:10]:
        print(f"  {gene}: {', '.join(organs)}")
    if len(pairs) > 10:
        print(f"  ... and {len(pairs) - 10} more")

    crawler = GeneFuncCrawler(
        max_papers=max_papers,
        max_api_calls=max_api_calls,
        api_key=api_key,
    )

    for i, (gene, organs) in enumerate(pairs):
        if crawler._should_stop():
            break
        print(f"\n[{i+1}/{len(pairs)}] Searching: {gene} in {', '.join(organs)}")

        # Phase 1: direct search
        top_ids = crawler.search_gene(gene, organs)
        print(f"  Found {len(top_ids)} new papers")

        # Phase 2: 1-hop expansion from top results
        if top_ids and not crawler._should_stop():
            crawler.expand_one_hop(top_ids, gene, organs)

    # Report
    print(f"\n{'='*60}")
    print(f"GENE-FUNCTION CRAWL COMPLETE")
    print(f"{'='*60}")
    print(f"Total papers: {len(crawler.papers)}")
    print(f"Total edges:  {crawler.graph.number_of_edges()}")
    print(f"API calls:    {crawler.client.call_count}")

    # Gene coverage
    genes_found = set()
    for paper_id, genes in crawler.paper_genes.items():
        genes_found.update(genes)
    print(f"Genes with papers: {len(genes_found)} / {len(pairs)}")

    # Organ distribution
    organ_dist: dict[str, int] = {}
    for p in crawler.papers.values():
        for organ in p.organs_tagged:
            organ_dist[organ] = organ_dist.get(organ, 0) + 1
    print(f"\nOrgan distribution:")
    for organ, count in sorted(organ_dist.items(), key=lambda x: x[1], reverse=True):
        print(f"  {organ}: {count}")

    crawler.save()
    return crawler


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 2 and sys.argv[1].lower() == "tox":
        # Tier 3 gene-tox crawl
        run_genetox_crawl()
    else:
        # Original gene-function crawl
        max_papers = 400
        consensus_path = "citegraph_output/gene_consensus.json"

        for arg in sys.argv[1:]:
            if arg.isdigit():
                max_papers = int(arg)
            elif arg.endswith(".json"):
                consensus_path = arg

        run_genefunc_crawl(
            consensus_path=consensus_path,
            max_papers=max_papers,
        )
