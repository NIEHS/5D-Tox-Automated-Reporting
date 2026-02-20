"""
Citation graph crawler with governor system.

Uses Semantic Scholar API to expand a citation graph from seed papers,
scoring relevance and stopping when the graph saturates or budget is exhausted.
"""

import time
import json
import hashlib
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import requests
import networkx as nx


# ---------------------------------------------------------------------------
# Governor configuration
# ---------------------------------------------------------------------------

@dataclass
class GovernorConfig:
    """Controls when the crawler stops expanding."""

    max_depth: int = 2              # max hops from any seed paper
    max_papers: int = 300           # hard cap on total papers in graph
    max_api_calls: int = 500        # hard cap on API requests
    relevance_threshold: float = 0.3  # don't expand papers below this score
    saturation_window: int = 20     # check last N papers for new concepts
    saturation_threshold: float = 0.05  # stop if < 5% new concepts in window
    max_refs_per_paper: int = 30    # max references to pull per paper
    max_cites_per_paper: int = 15   # max citing papers to pull per paper
    rate_limit_delay: float = 1.5   # seconds between API calls

    # Topic keywords for relevance scoring (set by user)
    topic_keywords: list[str] = field(default_factory=lambda: [
        "toxicogenomics", "toxicogenomic",
        "gene expression", "transcriptomics", "transcriptomic",
        "rat", "rattus",
        "liver", "hepat", "kidney", "renal", "nephro",
        "heart", "cardiac", "lung", "pulmonary",
        "organ", "tissue",
        "hallmark", "biomarker", "signature",
        "toxicity", "toxic", "adverse",
        "human health", "translational",
        "drug-induced", "chemical exposure",
    ])

    # Organ-boost keywords: extra terms that get bonus scoring for organ-specific crawls
    # When set, papers matching these keywords get +0.15 relevance boost
    organ_boost_keywords: list[str] = field(default_factory=list)

    # Known gene symbols for hybrid scoring: if a paper mentions a known gene
    # AND any organ keyword, it gets a relevance floor of 0.35.
    # This retains gene-function papers that lack tox vocabulary.
    known_genes: set[str] = field(default_factory=set)

    # Organ-specific keywords for tagging
    organ_keywords: dict[str, list[str]] = field(default_factory=lambda: {
        "liver": ["liver", "hepat", "hepatocyte", "hepatotoxic", "hepatic"],
        "kidney": ["kidney", "renal", "nephro", "nephrotoxic", "tubular"],
        "heart": ["heart", "cardiac", "cardiotoxic", "myocard", "cardiovascular"],
        "lung": ["lung", "pulmonary", "pneumo", "respiratory", "alveol"],
        "brain": ["brain", "neuro", "cerebr", "hippocamp", "cortical"],
        "bone_marrow": ["bone marrow", "hematopoiet", "myelotoxic"],
        "intestine": ["intestin", "gut", "gastro", "colonic", "entero"],
        "spleen": ["spleen", "splenic"],
        "muscle": ["muscle", "myotoxic", "skeletal muscle"],
        "thyroid": ["thyroid"],
        "adrenal": ["adrenal"],
        "testis": ["testis", "testicular", "spermat"],
    })


# ---------------------------------------------------------------------------
# Known-gene loader (for hybrid scoring)
# ---------------------------------------------------------------------------

def load_known_genes(
    consensus_path: str = "citegraph_output/gene_consensus.json",
) -> set[str]:
    """
    Load all gene symbols + aliases from the consensus JSON.
    Returns a set of uppercase gene names suitable for word-boundary matching.
    Short names (<3 chars) are excluded to avoid false positives.
    """
    with open(consensus_path) as f:
        data = json.load(f)

    genes: set[str] = set()
    for category in ("consensus_genes", "moderate_evidence"):
        for gene in data.get(category, {}):
            if len(gene) >= 3:
                genes.add(gene.upper())
    return genes


# ---------------------------------------------------------------------------
# Paper representation
# ---------------------------------------------------------------------------

@dataclass
class Paper:
    paper_id: str                   # Semantic Scholar paper ID
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: Optional[int] = None
    abstract: Optional[str] = None
    venue: str = ""
    citation_count: int = 0
    reference_count: int = 0
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None
    url: Optional[str] = None
    pmid: Optional[str] = None
    pmcid: Optional[str] = None
    open_access_pdf: Optional[str] = None  # URL from S2 openAccessPdf

    # Computed fields
    relevance_score: float = 0.0
    organs_tagged: list[str] = field(default_factory=list)
    genes_mentioned: list[str] = field(default_factory=list)
    depth: int = 0                  # hops from nearest seed paper
    is_seed: bool = False
    is_review: bool = False
    expanded: bool = False          # have we fetched refs/cites?


# ---------------------------------------------------------------------------
# Semantic Scholar API client
# ---------------------------------------------------------------------------

S2_BASE = "https://api.semanticscholar.org/graph/v1"
S2_FIELDS = "paperId,title,authors,year,abstract,venue,citationCount,referenceCount,externalIds,url,publicationTypes,openAccessPdf"

class S2Client:
    """Thin wrapper around Semantic Scholar API with rate limiting."""

    def __init__(self, api_key: Optional[str] = None, delay: float = 1.0):
        self.session = requests.Session()
        if api_key:
            self.session.headers["x-api-key"] = api_key
        self.delay = delay
        self.call_count = 0

    def _get(self, url: str, params: dict | None = None,
             _retries: int = 3) -> dict | None:
        time.sleep(self.delay)
        self.call_count += 1
        try:
            r = self.session.get(url, params=params or {}, timeout=30)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 10))
                print(f"  [rate limited, waiting {wait}s]")
                time.sleep(wait)
                if _retries > 0:
                    return self._get(url, params, _retries - 1)
                return None
            if r.status_code != 200:
                print(f"  [API error {r.status_code} for {url}]")
                if r.status_code >= 500 and _retries > 0:
                    time.sleep(5)
                    return self._get(url, params, _retries - 1)
                return None
            data = r.json()
            if data is None:
                return None
            return data
        except requests.RequestException as e:
            print(f"  [request error: {e}]")
            if _retries > 0:
                time.sleep(3)
                return self._get(url, params, _retries - 1)
            return None

    def get_paper(self, paper_id: str) -> dict | None:
        """Fetch a single paper by ID (S2 ID, DOI, ArXiv:xxxx, etc.)."""
        url = f"{S2_BASE}/paper/{paper_id}"
        return self._get(url, {"fields": S2_FIELDS})

    def search(self, query: str, limit: int = 20) -> list[dict]:
        """Search for papers by query string."""
        url = f"{S2_BASE}/paper/search"
        data = self._get(url, {"query": query, "limit": limit, "fields": S2_FIELDS})
        if data and "data" in data:
            return data["data"]
        return []

    def get_references(self, paper_id: str, limit: int = 50) -> list[dict]:
        """Get papers referenced by this paper."""
        url = f"{S2_BASE}/paper/{paper_id}/references"
        data = self._get(url, {"fields": S2_FIELDS, "limit": limit})
        if not data or not isinstance(data.get("data"), list):
            return []
        return [r["citedPaper"] for r in data["data"]
                if isinstance(r, dict) and isinstance(r.get("citedPaper"), dict)
                and r["citedPaper"].get("paperId")]

    def get_citations(self, paper_id: str, limit: int = 50) -> list[dict]:
        """Get papers that cite this paper."""
        url = f"{S2_BASE}/paper/{paper_id}/citations"
        data = self._get(url, {"fields": S2_FIELDS, "limit": limit})
        if not data or not isinstance(data.get("data"), list):
            return []
        return [c["citingPaper"] for c in data["data"]
                if isinstance(c, dict) and isinstance(c.get("citingPaper"), dict)
                and c["citingPaper"].get("paperId")]


# ---------------------------------------------------------------------------
# Relevance scoring
# ---------------------------------------------------------------------------

def score_relevance(paper: Paper, config: GovernorConfig) -> float:
    """
    Score how relevant a paper is to the topic, 0.0 - 1.0.

    Uses keyword matching against title + abstract. Weighted:
    - Title matches count 3x
    - Abstract matches count 1x
    - Being a review adds 0.1
    - Recency bonus: papers after 2020 get up to +0.1
    """
    text_title = (paper.title or "").lower()
    text_abstract = (paper.abstract or "").lower()
    text_combined = text_title + " " + text_abstract

    if not text_combined.strip():
        return 0.0

    keywords = config.topic_keywords
    total_kw = len(keywords)
    if total_kw == 0:
        return 0.5

    title_hits = sum(1 for kw in keywords if kw.lower() in text_title)
    abstract_hits = sum(1 for kw in keywords if kw.lower() in text_abstract)

    # Weighted score: title matches matter more
    raw = (title_hits * 3 + abstract_hits) / (total_kw * 4)
    score = min(raw * 3, 1.0)  # scale up since most papers won't hit all keywords

    # Review bonus
    if paper.is_review:
        score = min(score + 0.1, 1.0)

    # Recency bonus
    if paper.year and paper.year >= 2020:
        recency = min((paper.year - 2020) / 5, 1.0) * 0.1
        score = min(score + recency, 1.0)

    # Organ-boost bonus: papers matching organ-specific keywords get +0.15
    if config.organ_boost_keywords:
        text_lower = text_title + " " + text_abstract
        boost_hits = sum(1 for kw in config.organ_boost_keywords if kw.lower() in text_lower)
        if boost_hits >= 2:
            score = min(score + 0.15, 1.0)
        elif boost_hits >= 1:
            score = min(score + 0.08, 1.0)

    # Gene-aware relevance floor: if a paper mentions a known gene AND any
    # organ keyword, set a minimum score of 0.35. This retains gene-function
    # papers that lack toxicogenomics vocabulary.
    if config.known_genes:
        raw_text = (paper.title or "") + " " + (paper.abstract or "")
        has_gene = False
        for gene in config.known_genes:
            if re.search(r'\b' + re.escape(gene) + r'\b', raw_text):
                has_gene = True
                break
        if has_gene:
            has_organ = any(
                kw in text_combined
                for organ_kws in config.organ_keywords.values()
                for kw in organ_kws
            )
            if has_organ:
                score = max(score, 0.35)

    return round(score, 3)


def tag_organs(paper: Paper, config: GovernorConfig) -> list[str]:
    """Tag which organs a paper is relevant to."""
    text = ((paper.title or "") + " " + (paper.abstract or "")).lower()
    organs = []
    for organ, keywords in config.organ_keywords.items():
        if any(kw in text for kw in keywords):
            organs.append(organ)
    return organs


# ---------------------------------------------------------------------------
# Governor: saturation detection
# ---------------------------------------------------------------------------

class SaturationTracker:
    """Tracks whether new papers are contributing new concepts."""

    def __init__(self, config: GovernorConfig):
        self.config = config
        self.seen_concepts: set[str] = set()
        self.window: list[float] = []  # novelty score per recent paper

    def assess(self, paper: Paper) -> float:
        """Return novelty score (0-1) for this paper. Updates internal state."""
        text = ((paper.title or "") + " " + (paper.abstract or "")).lower()
        # Extract concept tokens: bigrams from title + abstract
        words = re.findall(r'[a-z]{3,}', text)
        bigrams = {f"{words[i]}_{words[i+1]}" for i in range(len(words) - 1)}
        # Also include any gene-like tokens (uppercase, 2-8 chars)
        raw = (paper.title or "") + " " + (paper.abstract or "")
        gene_tokens = {m for m in re.findall(r'\b[A-Z][A-Z0-9]{1,7}\b', raw)}

        concepts = bigrams | gene_tokens
        new = concepts - self.seen_concepts
        novelty = len(new) / max(len(concepts), 1)

        self.seen_concepts.update(concepts)
        self.window.append(novelty)

        return novelty

    @property
    def is_saturated(self) -> bool:
        """True if recent papers are adding very few new concepts."""
        w = self.config.saturation_window
        if len(self.window) < w:
            return False
        recent_avg = sum(self.window[-w:]) / w
        return recent_avg < self.config.saturation_threshold


# ---------------------------------------------------------------------------
# Main crawler
# ---------------------------------------------------------------------------

class CitationGraphCrawler:
    """
    Builds a citation graph from seed papers, expanding outward
    with governor-controlled stopping.
    """

    def __init__(self, config: GovernorConfig | None = None,
                 api_key: str | None = None):
        self.config = config or GovernorConfig()
        self.client = S2Client(api_key=api_key, delay=self.config.rate_limit_delay)
        self.graph = nx.DiGraph()
        self.papers: dict[str, Paper] = {}
        self.saturation = SaturationTracker(self.config)
        self.expansion_queue: list[tuple[int, float, str]] = []  # (depth, -relevance, paper_id)

        # Stats
        self.stats = {
            "papers_fetched": 0,
            "papers_expanded": 0,
            "papers_skipped_relevance": 0,
            "papers_skipped_depth": 0,
            "saturation_triggered": False,
            "stop_reason": "",
        }

    def _dict_to_paper(self, data: dict, depth: int = 0) -> Paper | None:
        """Convert S2 API response dict to Paper object."""
        pid = data.get("paperId")
        if not pid:
            return None

        ext = data.get("externalIds") or {}
        pub_types = data.get("publicationTypes") or []
        authors_raw = data.get("authors") or []

        p = Paper(
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
            pmid=ext.get("PubMed"),
            pmcid=ext.get("PubMedCentral"),
            open_access_pdf=(data.get("openAccessPdf") or {}).get("url"),
            is_review="Review" in pub_types,
            depth=depth,
        )
        return p

    def _should_stop(self) -> tuple[bool, str]:
        """Check all governor conditions."""
        if len(self.papers) >= self.config.max_papers:
            return True, f"max_papers ({self.config.max_papers})"
        if self.client.call_count >= self.config.max_api_calls:
            return True, f"max_api_calls ({self.config.max_api_calls})"
        if self.saturation.is_saturated:
            return True, "saturation detected"
        return False, ""

    def add_seed(self, paper_id: str):
        """Add a seed paper by S2 ID, DOI, or ArXiv ID."""
        print(f"Fetching seed paper: {paper_id}")
        data = self.client.get_paper(paper_id)
        if not data:
            print(f"  Could not fetch: {paper_id}")
            return

        paper = self._dict_to_paper(data, depth=0)
        if not paper:
            return

        paper.is_seed = True
        paper.relevance_score = 1.0  # seeds are maximally relevant by definition
        paper.organs_tagged = tag_organs(paper, self.config)
        self.papers[paper.paper_id] = paper
        self.graph.add_node(paper.paper_id)
        self.saturation.assess(paper)
        self.stats["papers_fetched"] += 1

        # Queue for expansion (depth 0, max relevance)
        import heapq
        heapq.heappush(self.expansion_queue, (0, -1.0, paper.paper_id))

        print(f"  Added seed: {paper.title} ({paper.year})")
        print(f"  Organs: {paper.organs_tagged}")
        print(f"  Refs: {paper.reference_count}, Cited by: {paper.citation_count}")

    def add_seed_by_search(self, query: str, max_results: int = 5):
        """Search for papers and add top results as seeds."""
        print(f"Searching: {query}")
        results = self.client.search(query, limit=max_results)
        for data in results:
            paper = self._dict_to_paper(data, depth=0)
            if paper:
                paper.is_seed = True
                paper.relevance_score = score_relevance(paper, self.config)
                paper.organs_tagged = tag_organs(paper, self.config)
                if paper.relevance_score >= self.config.relevance_threshold:
                    self.papers[paper.paper_id] = paper
                    self.graph.add_node(paper.paper_id)
                    self.saturation.assess(paper)
                    self.stats["papers_fetched"] += 1
                    import heapq
                    heapq.heappush(self.expansion_queue, (0, -paper.relevance_score, paper.paper_id))
                    print(f"  Seed: [{paper.relevance_score:.2f}] {paper.title} ({paper.year})")

    def _ingest_neighbor(self, data: dict, source_id: str,
                         depth: int, is_reference: bool) -> bool:
        """Process a reference or citation, return True if added."""
        paper = self._dict_to_paper(data, depth=depth)
        if not paper or not paper.paper_id:
            return False

        # Already seen?
        if paper.paper_id in self.papers:
            # Just add the edge
            existing = self.papers[paper.paper_id]
            existing.depth = min(existing.depth, depth)
            if is_reference:
                self.graph.add_edge(source_id, paper.paper_id, type="references")
            else:
                self.graph.add_edge(paper.paper_id, source_id, type="references")
            return False

        # Score relevance
        paper.relevance_score = score_relevance(paper, self.config)
        paper.organs_tagged = tag_organs(paper, self.config)

        if paper.relevance_score < self.config.relevance_threshold:
            self.stats["papers_skipped_relevance"] += 1
            return False

        # Add to graph
        self.papers[paper.paper_id] = paper
        self.graph.add_node(paper.paper_id)
        if is_reference:
            self.graph.add_edge(source_id, paper.paper_id, type="references")
        else:
            self.graph.add_edge(paper.paper_id, source_id, type="references")

        self.saturation.assess(paper)
        self.stats["papers_fetched"] += 1

        # Queue for expansion if worth it
        if depth < self.config.max_depth:
            import heapq
            heapq.heappush(self.expansion_queue, (depth, -paper.relevance_score, paper.paper_id))

        return True

    def expand(self):
        """
        Expand the graph from the queue, governed by stopping conditions.
        Papers are expanded in priority order: lowest depth first,
        then highest relevance.
        """
        import heapq

        print(f"\n{'='*60}")
        print(f"Starting expansion (max_depth={self.config.max_depth}, "
              f"max_papers={self.config.max_papers})")
        print(f"{'='*60}\n")

        while self.expansion_queue:
            stop, reason = self._should_stop()
            if stop:
                self.stats["stop_reason"] = reason
                print(f"\n>>> GOVERNOR STOP: {reason}")
                break

            depth, neg_rel, paper_id = heapq.heappop(self.expansion_queue)

            if paper_id not in self.papers:
                continue
            paper = self.papers[paper_id]
            if paper.expanded:
                continue
            if depth >= self.config.max_depth and not paper.is_seed:
                self.stats["papers_skipped_depth"] += 1
                continue

            paper.expanded = True
            self.stats["papers_expanded"] += 1
            rel = paper.relevance_score
            print(f"[depth={depth} rel={rel:.2f} #{len(self.papers)}] "
                  f"Expanding: {paper.title[:80]}...")

            # Fetch references
            refs = self.client.get_references(
                paper_id, limit=self.config.max_refs_per_paper)
            added_refs = 0
            for ref_data in refs:
                stop, reason = self._should_stop()
                if stop:
                    self.stats["stop_reason"] = reason
                    print(f"\n>>> GOVERNOR STOP: {reason}")
                    return self._report()
                if self._ingest_neighbor(ref_data, paper_id, depth + 1, is_reference=True):
                    added_refs += 1

            # Fetch citations (who cites this paper)
            cites = self.client.get_citations(
                paper_id, limit=self.config.max_cites_per_paper)
            added_cites = 0
            for cite_data in cites:
                stop, reason = self._should_stop()
                if stop:
                    self.stats["stop_reason"] = reason
                    print(f"\n>>> GOVERNOR STOP: {reason}")
                    return self._report()
                if self._ingest_neighbor(cite_data, paper_id, depth + 1, is_reference=False):
                    added_cites += 1

            print(f"  -> +{added_refs} refs, +{added_cites} cites "
                  f"(total: {len(self.papers)} papers, "
                  f"{self.graph.number_of_edges()} edges)")

        if not self.stats["stop_reason"]:
            self.stats["stop_reason"] = "queue exhausted"
            print(f"\n>>> Queue exhausted")

        return self._report()

    def _report(self) -> dict:
        """Generate a summary report."""
        organ_dist = {}
        year_dist = {}
        top_cited = sorted(self.papers.values(),
                          key=lambda p: p.citation_count, reverse=True)[:20]
        top_relevant = sorted(self.papers.values(),
                             key=lambda p: p.relevance_score, reverse=True)[:20]
        reviews = [p for p in self.papers.values() if p.is_review]

        for p in self.papers.values():
            for organ in p.organs_tagged:
                organ_dist[organ] = organ_dist.get(organ, 0) + 1
            if p.year:
                decade = (p.year // 5) * 5
                year_dist[decade] = year_dist.get(decade, 0) + 1

        report = {
            "stats": self.stats,
            "total_papers": len(self.papers),
            "total_edges": self.graph.number_of_edges(),
            "api_calls": self.client.call_count,
            "organ_distribution": dict(sorted(organ_dist.items(),
                                              key=lambda x: x[1], reverse=True)),
            "year_distribution": dict(sorted(year_dist.items())),
            "reviews_found": len(reviews),
            "top_cited": [
                {"title": p.title, "year": p.year, "citations": p.citation_count,
                 "relevance": p.relevance_score, "organs": p.organs_tagged}
                for p in top_cited
            ],
            "top_relevant": [
                {"title": p.title, "year": p.year, "citations": p.citation_count,
                 "relevance": p.relevance_score, "organs": p.organs_tagged}
                for p in top_relevant
            ],
        }

        print(f"\n{'='*60}")
        print(f"CRAWL COMPLETE")
        print(f"{'='*60}")
        print(f"Papers: {report['total_papers']}")
        print(f"Edges:  {report['total_edges']}")
        print(f"API calls: {report['api_calls']}")
        print(f"Stop reason: {self.stats['stop_reason']}")
        print(f"Skipped (low relevance): {self.stats['papers_skipped_relevance']}")
        print(f"Skipped (max depth): {self.stats['papers_skipped_depth']}")
        print(f"Reviews found: {report['reviews_found']}")
        print(f"\nOrgan distribution:")
        for organ, count in report['organ_distribution'].items():
            print(f"  {organ}: {count}")
        print(f"\nTop 10 most relevant papers:")
        for i, p in enumerate(report['top_relevant'][:10], 1):
            print(f"  {i}. [{p['relevance']:.2f}] {p['title'][:70]} "
                  f"({p['year']}) [{p['citations']} cites] {p['organs']}")

        return report

    def save(self, path: str = "citegraph_output"):
        """Save graph and paper data to files."""
        outdir = Path(path)
        outdir.mkdir(exist_ok=True)

        # Save papers as JSON
        papers_out = []
        for p in sorted(self.papers.values(),
                       key=lambda x: x.relevance_score, reverse=True):
            papers_out.append(asdict(p))
        with open(outdir / "papers.json", "w") as f:
            json.dump(papers_out, f, indent=2, default=str)

        # Save graph as edge list
        edges = []
        for u, v, data in self.graph.edges(data=True):
            edges.append({"source": u, "target": v, "type": data.get("type", "")})
        with open(outdir / "edges.json", "w") as f:
            json.dump(edges, f, indent=2)

        # Save graph in GML format (loadable by networkx, Gephi, etc.)
        # Label nodes with titles for readability
        g = self.graph.copy()
        for node in g.nodes:
            if node in self.papers:
                p = self.papers[node]
                g.nodes[node]["title"] = p.title
                g.nodes[node]["year"] = p.year or 0
                g.nodes[node]["relevance"] = p.relevance_score
                g.nodes[node]["citations"] = p.citation_count
                g.nodes[node]["organs"] = ",".join(p.organs_tagged)
                g.nodes[node]["is_review"] = p.is_review
                g.nodes[node]["depth"] = p.depth
        nx.write_gml(g, str(outdir / "citation_graph.gml"))

        print(f"\nSaved to {outdir}/")
        print(f"  papers.json     ({len(papers_out)} papers)")
        print(f"  edges.json      ({len(edges)} edges)")
        print(f"  citation_graph.gml (for Gephi/networkx)")


# ---------------------------------------------------------------------------
# Convenience runner
# ---------------------------------------------------------------------------

def run_toxicogenomics_crawl(
    max_depth: int = 2,
    max_papers: int = 200,
    api_key: str | None = None,
):
    """
    Run a targeted crawl for toxicogenomics hallmark genes.
    """
    config = GovernorConfig(
        max_depth=max_depth,
        max_papers=max_papers,
        rate_limit_delay=1.0,
    )

    crawler = CitationGraphCrawler(config=config, api_key=api_key)

    # Seed 1: The 2025 Nature Reviews Genetics review (anchor paper)
    crawler.add_seed("DOI:10.1038/s41576-024-00767-1")

    # Seed 2: TXG-MAP liver modules
    crawler.add_seed("DOI:10.1038/tpj.2017.17")

    # Seed 3: Human hepatocyte TXG-MAPr
    crawler.add_seed("DOI:10.1007/s00204-021-03141-w")

    # Seed 4: Open TG-GATEs database paper
    crawler.add_seed("DOI:10.1093/nar/gku955")

    # Seed 5: TransTox multi-organ (2024)
    crawler.add_seed("DOI:10.1038/s41746-024-01317-z")

    # Seed 6: Reconciled rat-human metabolic networks
    crawler.add_seed("DOI:10.1038/ncomms14250")

    # Seed 7: MSigDB hallmark gene sets
    crawler.add_seed("DOI:10.1016/j.cels.2015.12.004")

    # Search-based seeds for organ-specific coverage
    crawler.add_seed_by_search(
        "toxicogenomics rat kidney gene expression biomarkers", max_results=3)
    crawler.add_seed_by_search(
        "toxicogenomics rat heart cardiac gene signatures", max_results=3)
    crawler.add_seed_by_search(
        "toxicogenomics organ-specific hallmark genes rat human", max_results=3)

    # Expand
    report = crawler.expand()

    # Save
    crawler.save("citegraph_output")

    return crawler, report


# ---------------------------------------------------------------------------
# Organ-specific crawl configurations
# ---------------------------------------------------------------------------

ORGAN_CRAWL_CONFIGS = {
    "heart": {
        "seeds": [
            # Open TG-GATEs (multi-tissue including heart)
            "DOI:10.1093/nar/gku955",
            # Meier et al. 2024 review (anchor)
            "DOI:10.1038/s41576-024-00767-1",
            # Multiscale mapping of cardiotoxic drug transcriptomic signatures (2024)
            "DOI:10.1038/s41467-024-52145-4",
            # Pharmacogenomics in drug-induced cardiotoxicity review (2022)
            "DOI:10.3389/fcvm.2022.966261",
            # Anthracycline shared cardiac gene expression signature (2024)
            "DOI:10.1371/journal.pgen.1011164",
            # Rat cardiac genomic biomarkers, preclinical (2013)
            "DOI:10.1016/j.tox.2012.09.012",
        ],
        "searches": [
            ("cardiotoxicity transcriptomics gene expression rat", 5),
            ("drug-induced cardiotoxicity biomarker gene signature", 5),
            ("cardiac toxicogenomics rat heart gene expression profiling", 3),
            ("doxorubicin cardiotoxicity transcriptomic rat", 3),
            ("myocardial toxicity gene expression rat preclinical", 3),
        ],
        "boost_keywords": [
            "cardiac", "cardiotoxic", "cardiotoxicity", "heart",
            "myocardial", "myocardium", "cardiomyocyte", "cardiomyopathy",
            "doxorubicin", "anthracycline", "troponin",
            "cardiovascular", "arrhythm", "qtc",
        ],
    },
    "brain": {
        "seeds": [
            # Meier et al. 2024 review (anchor)
            "DOI:10.1038/s41576-024-00767-1",
            # Toxicogenomics review - broad coverage (2018)
            "DOI:10.1039/c8mo00042e",
            # High-throughput transcriptomics platform (2021)
            "DOI:10.1093/toxsci/kfab009",
            # Rat brain polymyxin B neurotoxicity transcriptomics (2023)
            "DOI:10.1007/s12035-022-03140-7",
            # ML brain transcriptomics organophosphate ester (2023)
            "DOI:10.1093/toxsci/kfad062",
        ],
        "searches": [
            ("neurotoxicogenomics gene expression brain rat", 5),
            ("neurotoxicity transcriptomic biomarker rat brain", 5),
            ("drug-induced neurotoxicity gene expression profiling", 3),
            ("developmental neurotoxicity transcriptomics rat", 3),
            ("neurodegeneration toxicogenomics gene signature", 3),
        ],
        "boost_keywords": [
            "brain", "neurotoxic", "neurotoxicity", "neurotoxicogenomics",
            "neurodegeneration", "neurodegenerative",
            "cerebral", "cortical", "hippocampal", "hippocampus",
            "dopaminergic", "serotonergic", "glutamatergic",
            "cns", "blood-brain", "astrocyte", "microglia", "neuron",
            "seizure", "encephalopathy",
        ],
        },
    "lung": {
        "seeds": [
            # Meier et al. 2024 review (anchor)
            "DOI:10.1038/s41576-024-00767-1",
            # Meta-analysis pulmonary nanomaterial transcriptomics (2016)
            "DOI:10.1186/s12989-016-0137-5",
            # MWCNT AOP framework with transcriptomics (2016)
            "DOI:10.1186/s12989-016-0125-9",
            # Rat TiO2 inhalation transcriptomics (2018)
            "DOI:10.1016/j.taap.2018.07.013",
            # MWCNT rat inhalation gene expression (2022)
            "DOI:10.1080/08958378.2022.2081386",
        ],
        "searches": [
            ("pulmonary toxicogenomics gene expression rat lung", 5),
            ("inhalation toxicology transcriptomics rat respiratory", 5),
            ("lung toxicity biomarker gene expression profiling", 3),
            ("nanoparticle pulmonary toxicity transcriptomic rat", 3),
            ("drug-induced pulmonary toxicity gene signature", 3),
        ],
        "boost_keywords": [
            "lung", "pulmonary", "respiratory", "inhalation",
            "pneumotoxic", "alveolar", "bronchial", "bronchiolar",
            "fibrosis", "pneumonitis",
            "nanoparticle", "nanotube", "aerosol",
            "surfactant", "clara cell", "type ii pneumocyte",
        ],
    },
}


def run_organ_crawl(
    organ: str,
    max_depth: int = 2,
    max_papers: int = 400,
    api_key: str | None = None,
):
    """
    Run an organ-specific toxicogenomics crawl.

    Supported organs: heart, brain, lung
    """
    if organ not in ORGAN_CRAWL_CONFIGS:
        print(f"Unknown organ: {organ}. Available: {list(ORGAN_CRAWL_CONFIGS.keys())}")
        return None, None

    organ_cfg = ORGAN_CRAWL_CONFIGS[organ]

    config = GovernorConfig(
        max_depth=max_depth,
        max_papers=max_papers,
        max_api_calls=500,
        rate_limit_delay=1.5,
        organ_boost_keywords=organ_cfg["boost_keywords"],
    )

    crawler = CitationGraphCrawler(config=config, api_key=api_key)

    print(f"\n{'='*60}")
    print(f"ORGAN-SPECIFIC CRAWL: {organ.upper()}")
    print(f"Max papers: {max_papers}, Boost keywords: {len(organ_cfg['boost_keywords'])}")
    print(f"{'='*60}\n")

    # Add DOI seeds
    for doi in organ_cfg["seeds"]:
        crawler.add_seed(doi)

    # Add search-based seeds
    for query, limit in organ_cfg["searches"]:
        crawler.add_seed_by_search(query, max_results=limit)

    # Expand
    report = crawler.expand()

    # Save to organ-specific directory
    output_dir = f"citegraph_output_{organ}"
    crawler.save(output_dir)

    return crawler, report


if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 2 and sys.argv[1] in ORGAN_CRAWL_CONFIGS:
        # Organ-specific crawl: python citegraph.py heart|brain|lung [max_papers]
        organ = sys.argv[1]
        max_papers = int(sys.argv[2]) if len(sys.argv) > 2 else 400
        crawler, report = run_organ_crawl(organ, max_papers=max_papers)
    else:
        # Original general crawl: python citegraph.py [max_papers]
        max_papers = int(sys.argv[1]) if len(sys.argv) > 1 else 200
        crawler, report = run_toxicogenomics_crawl(max_papers=max_papers)
