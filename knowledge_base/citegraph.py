"""
Citation graph crawler with governor system.

Uses Semantic Scholar API to expand a citation graph from seed papers,
scoring relevance and stopping when the graph saturates or budget is exhausted.

Everything the crawler judges a paper by — its topic words, boosts, recency,
the tag vocabularies, the known-entity floor — comes from a named crawl query
(knowledge_base.crawl_queries, ``config_for``); the crawler knows no topic.
knowledge_base.run_crawl runs each of the query's crawls through ``run_crawl``.
"""

import os
import time
import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import requests
import networkx as nx


# ---------------------------------------------------------------------------
# Runtime configuration from environment
# ---------------------------------------------------------------------------

def resolve_s2_api_key() -> str | None:
    """Read the Semantic Scholar key from env. Returns None if unset (public pool)."""
    return os.getenv("S2_API_KEY") or None


def log_s2_auth_status(api_key: str | None) -> None:
    """Print whether the crawl is authenticated, without echoing the key."""
    if api_key:
        print(f"[S2] authenticated (key len {len(api_key)})")
    else:
        print("[S2] public pool (no key) — set S2_API_KEY for higher rate limits")


# ---------------------------------------------------------------------------
# Governor configuration
# ---------------------------------------------------------------------------

@dataclass
class GovernorConfig:
    """Controls when the crawler stops expanding and how it judges a paper.
    Built from a crawl query by ``config_for``; the defaults judge nothing
    topical (no keywords: every paper scores 0.5)."""

    max_depth: int = 2              # max hops from any seed paper
    max_papers: int = 300           # hard cap on total papers in graph
    max_api_calls: int = 500        # hard cap on API requests
    relevance_threshold: float = 0.3  # don't expand papers below this score
    saturation_window: int = 20     # check last N papers for new concepts
    saturation_threshold: float = 0.05  # stop if < 5% new concepts in window
    max_refs_per_paper: int = 30    # max references to pull per paper
    max_cites_per_paper: int = 15   # max citing papers to pull per paper
    rate_limit_delay: float = 1.5   # seconds between API calls

    # Topic words: a title hit counts three times an abstract hit.
    topic_keywords: list[str] = field(default_factory=list)
    review_bonus: float = 0.0
    # Papers from recency_from_year on gain up to recency_bonus, reached
    # recency_over_years later.
    recency_from_year: int | None = None
    recency_over_years: int = 5
    recency_bonus: float = 0.0

    # A crawl's boost words: one hit adds boost_one, two or more boost_two.
    boost_keywords: list[str] = field(default_factory=list)
    boost_one: float = 0.0
    boost_two: float = 0.0

    # Known entities (e.g. gene symbols): a paper naming one AND any word of
    # the floor's tag vocabulary scores at least floor_score.
    known_entities: set[str] = field(default_factory=set)
    floor_vocabulary: dict[str, list[str]] = field(default_factory=dict)
    floor_score: float = 0.0

    # Tag vocabularies: {vocabulary: {tag: [words]}} — a paper is tagged with
    # every tag one of whose words it contains.
    tags: dict[str, dict[str, list[str]]] = field(default_factory=dict)


_CRAWLER_KEYS = ("max_depth", "max_papers", "max_api_calls", "relevance_threshold",
                 "saturation_window", "saturation_threshold", "max_refs_per_paper",
                 "max_cites_per_paper", "rate_limit_delay")


def config_for(query: dict, crawl: dict, known_entities: set[str] | None = None) -> GovernorConfig:
    """The governor of one crawl of a query: the query's crawler defaults, its
    relevance and tags, with what the crawl states over them (its keywords,
    boost words, limits; its floor when it asks for one)."""
    rel = query.get("relevance") or {}
    cfg = GovernorConfig()
    for key in _CRAWLER_KEYS:
        if key in (query.get("crawler") or {}):
            setattr(cfg, key, query["crawler"][key])
        if key in crawl:
            setattr(cfg, key, crawl[key])
    cfg.topic_keywords = list(crawl.get("keywords", rel.get("keywords") or []))
    cfg.review_bonus = float(rel.get("review_bonus", 0.0))
    recency = rel.get("recency") or {}
    if recency:
        cfg.recency_from_year = int(recency["from_year"])
        cfg.recency_over_years = int(recency.get("over_years", 5))
        cfg.recency_bonus = float(recency.get("bonus", 0.0))
    boost = rel.get("boost") or {}
    cfg.boost_keywords = list(crawl.get("boost") or [])
    cfg.boost_one = float(boost.get("one", 0.0))
    cfg.boost_two = float(boost.get("two_or_more", boost.get("one", 0.0)))
    cfg.tags = {v: {t: list(w) for t, w in terms.items()}
                for v, terms in (query.get("tags") or {}).items()}
    floor = rel.get("floor")
    if crawl.get("floor") and floor:
        cfg.known_entities = {e.upper() for e in (known_entities or set()) if len(e) >= 3}
        cfg.floor_vocabulary = cfg.tags.get(floor["tag"], {})
        cfg.floor_score = float(floor["score"])
    return cfg


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
    tags: dict[str, list[str]] = field(default_factory=dict)   # {vocabulary: [tags]}
    entities: list[str] = field(default_factory=list)          # a follow-on crawl's entity
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
    Score how relevant a paper is to the query, 0.0 - 1.0.

    Keyword matching against title + abstract, everything from the query
    (config_for):
    - title matches count 3x abstract matches; no keywords → 0.5
    - a review adds review_bonus
    - recency: up to recency_bonus from recency_from_year on
    - a crawl's boost words: one hit adds boost_one, two or more boost_two
    - the known-entity floor: a paper naming a known entity and any word of
      the floor's vocabulary scores at least floor_score
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

    if paper.is_review:
        score = min(score + config.review_bonus, 1.0)

    if config.recency_from_year is not None and paper.year and paper.year >= config.recency_from_year:
        recency = min((paper.year - config.recency_from_year) / config.recency_over_years, 1.0)
        score = min(score + recency * config.recency_bonus, 1.0)

    if config.boost_keywords:
        boost_hits = sum(1 for kw in config.boost_keywords if kw.lower() in text_combined)
        if boost_hits >= 2:
            score = min(score + config.boost_two, 1.0)
        elif boost_hits >= 1:
            score = min(score + config.boost_one, 1.0)

    if config.known_entities:
        raw_text = (paper.title or "") + " " + (paper.abstract or "")
        has_entity = any(re.search(r'\b' + re.escape(e) + r'\b', raw_text)
                         for e in config.known_entities)
        if has_entity and any(kw in text_combined
                              for words in config.floor_vocabulary.values() for kw in words):
            score = max(score, config.floor_score)

    return round(score, 3)


def tag_paper(paper: Paper, config: GovernorConfig) -> dict[str, list[str]]:
    """{vocabulary: [tags]} — each tag one of whose words the paper contains."""
    text = ((paper.title or "") + " " + (paper.abstract or "")).lower()
    return {vocab: [tag for tag, words in terms.items() if any(w in text for w in words)]
            for vocab, terms in config.tags.items()}


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
        paper.tags = tag_paper(paper, self.config)
        self.papers[paper.paper_id] = paper
        self.graph.add_node(paper.paper_id)
        self.saturation.assess(paper)
        self.stats["papers_fetched"] += 1

        # Queue for expansion (depth 0, max relevance)
        import heapq
        heapq.heappush(self.expansion_queue, (0, -1.0, paper.paper_id))

        print(f"  Added seed: {paper.title} ({paper.year})")
        print(f"  Tags: {paper.tags}")
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
                paper.tags = tag_paper(paper, self.config)
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
        paper.tags = tag_paper(paper, self.config)

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
            print("\n>>> Queue exhausted")

        return self._report()

    def _report(self) -> dict:
        """Generate a summary report."""
        tag_dist: dict[str, int] = {}
        year_dist = {}
        top_cited = sorted(self.papers.values(),
                          key=lambda p: p.citation_count, reverse=True)[:20]
        top_relevant = sorted(self.papers.values(),
                             key=lambda p: p.relevance_score, reverse=True)[:20]
        reviews = [p for p in self.papers.values() if p.is_review]

        for p in self.papers.values():
            for vocab, tags in p.tags.items():
                for tag in tags:
                    tag_dist[f"{vocab}:{tag}"] = tag_dist.get(f"{vocab}:{tag}", 0) + 1
            if p.year:
                decade = (p.year // 5) * 5
                year_dist[decade] = year_dist.get(decade, 0) + 1

        report = {
            "stats": self.stats,
            "total_papers": len(self.papers),
            "total_edges": self.graph.number_of_edges(),
            "api_calls": self.client.call_count,
            "tag_distribution": dict(sorted(tag_dist.items(),
                                            key=lambda x: x[1], reverse=True)),
            "year_distribution": dict(sorted(year_dist.items())),
            "reviews_found": len(reviews),
            "top_cited": [
                {"title": p.title, "year": p.year, "citations": p.citation_count,
                 "relevance": p.relevance_score, "tags": p.tags}
                for p in top_cited
            ],
            "top_relevant": [
                {"title": p.title, "year": p.year, "citations": p.citation_count,
                 "relevance": p.relevance_score, "tags": p.tags}
                for p in top_relevant
            ],
        }

        print(f"\n{'='*60}")
        print("CRAWL COMPLETE")
        print(f"{'='*60}")
        print(f"Papers: {report['total_papers']}")
        print(f"Edges:  {report['total_edges']}")
        print(f"API calls: {report['api_calls']}")
        print(f"Stop reason: {self.stats['stop_reason']}")
        print(f"Skipped (low relevance): {self.stats['papers_skipped_relevance']}")
        print(f"Skipped (max depth): {self.stats['papers_skipped_depth']}")
        print(f"Reviews found: {report['reviews_found']}")
        print("\nTag distribution:")
        for tag, count in report['tag_distribution'].items():
            print(f"  {tag}: {count}")
        print("\nTop 10 most relevant papers:")
        for i, p in enumerate(report['top_relevant'][:10], 1):
            print(f"  {i}. [{p['relevance']:.2f}] {p['title'][:70]} "
                  f"({p['year']}) [{p['citations']} cites] {p['tags']}")

        return report

    def save(self, path: str = "citegraph_output"):
        """Save graph and paper data to files."""
        outdir = Path(path)
        outdir.mkdir(parents=True, exist_ok=True)

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
                g.nodes[node]["tags"] = ",".join(
                    f"{v}:{t}" for v, ts in p.tags.items() for t in ts)
                g.nodes[node]["is_review"] = p.is_review
                g.nodes[node]["depth"] = p.depth
        nx.write_gml(g, str(outdir / "citation_graph.gml"))

        print(f"\nSaved to {outdir}/")
        print(f"  papers.json     ({len(papers_out)} papers)")
        print(f"  edges.json      ({len(edges)} edges)")
        print("  citation_graph.gml (for Gephi/networkx)")


# ---------------------------------------------------------------------------
# One crawl of a query
# ---------------------------------------------------------------------------

def run_crawl(query: dict, crawl: dict, out_dir: str | Path, api_key: str | None = None,
              known_entities: set[str] | None = None) -> dict:
    """Run one of a query's crawls — its seeds and searches, expanded under its
    governor (config_for) — and save it to ``out_dir``.  Returns the report."""
    config = config_for(query, crawl, known_entities)
    log_s2_auth_status(api_key)
    crawler = CitationGraphCrawler(config=config, api_key=api_key)
    print(f"\n{'='*60}\nCRAWL: {crawl['name']}  (max {config.max_papers} papers, "
          f"{config.max_api_calls} API calls)\n{'='*60}\n")
    for seed in crawl.get("seeds") or []:
        crawler.add_seed(seed)
    for search in crawl.get("searches") or []:
        crawler.add_seed_by_search(search["query"], max_results=search.get("limit", 5))
    report = crawler.expand()
    crawler.save(str(out_dir))
    return report
