"""
Follow-on crawls: a second pass seeded from entities rather than papers.

Where the citation crawl (citegraph) expands a graph from seed papers, a
follow-on crawl searches Semantic Scholar for each entity — every entity of
the run's consensus (``entities: consensus``), or a stated list — paired with
its tags ("NFE2L2 liver function mechanism"), keeps the papers that name the
entity, and expands one hop from the best of them.  Its query section
(knowledge_base.crawl_queries, ``follow_on``) states everything:

    entities:          consensus | [{entity, tags: [..], focus: text}]
    templates:         ["{entity} {tag_term} function mechanism", ..]
                       (a stated entity's ``focus`` is searched as well)
    tag_terms:         {tag: [search terms]}  — the first is searched
    tag_aliases:       {noisy tag: tag}        — a consensus tag's spelling
    default_tag:       the tag of an entity the consensus tags with none known
    tags_per_entity:   how many of an entity's tags are searched
    results_per_search, threshold, expand: {top, refs}
    scoring:           {title, abstract, tag, review,
                        recency: {from_year, over_years, bonus}}
    max_papers, max_api_calls, rate_limit_delay
"""

import json
import re
from pathlib import Path

import networkx as nx

from knowledge_base.citegraph import (
    S2Client,
    Paper,
    GovernorConfig,
    config_for,
    tag_paper,
    log_s2_auth_status,
)


def consensus_targets(spec: dict, consensus: dict) -> list[tuple[str, list[str], str]]:
    """(entity, [tags], focus) for every strong and moderate entity of the run's
    consensus, its tags spelled as the spec's tag_terms know them."""
    known = spec.get("tag_terms") or {}
    aliases = {k.strip().lower(): v for k, v in (spec.get("tag_aliases") or {}).items()}
    targets = []
    for level in ("strong", "moderate"):
        for entity, info in (consensus.get(level) or {}).items():
            tags = set()
            for t in info.get("by") or []:
                t = t.strip().lower()
                t = aliases.get(t, t)
                if t in known:
                    tags.add(t)
            if not tags and spec.get("default_tag"):
                tags.add(spec["default_tag"])
            targets.append((entity, sorted(tags), ""))
    return targets


def stated_targets(spec: dict) -> list[tuple[str, list[str], str]]:
    return [(e["entity"], list(e.get("tags") or []), e.get("focus") or "")
            for e in spec["entities"]]


def search_queries(spec: dict, entity: str, tags: list[str], focus: str) -> list[str]:
    queries = [focus] if focus else []
    known = spec.get("tag_terms") or {}
    for tag in tags[: spec.get("tags_per_entity", 2)]:
        tag_term = (known.get(tag) or [tag])[0]
        for template in spec.get("templates") or []:
            queries.append(template.format(entity=entity, tag_term=tag_term))
    return queries


def entity_relevance(paper: Paper, entity: str, tags: list[str], spec: dict,
                     config: GovernorConfig) -> float:
    """How well a paper fits an entity and its tags: the entity named in the
    title or the abstract, a tag's term (or any word of the query's tag
    vocabularies) in the text, recency and a review bonus — weights from the
    spec's ``scoring``."""
    text_title = (paper.title or "").lower()
    text_abstract = (paper.abstract or "").lower()
    text_combined = text_title + " " + text_abstract
    if not text_combined.strip():
        return 0.0
    w = spec.get("scoring") or {}
    score = 0.0
    pattern = re.compile(r'\b' + re.escape(entity.lower()) + r'\b')
    if pattern.search(text_title):
        score += w.get("title", 0.0)
    elif pattern.search(text_abstract):
        score += w.get("abstract", 0.0)

    known = spec.get("tag_terms") or {}
    tag_hit = any(term.lower() in text_combined for tag in tags for term in known.get(tag, [tag]))
    if not tag_hit:
        tag_hit = any(word in text_combined for terms in config.tags.values()
                      for words in terms.values() for word in words)
    if tag_hit:
        score += w.get("tag", 0.0)

    recency = w.get("recency") or {}
    if recency and paper.year and paper.year >= recency["from_year"]:
        score += min((paper.year - recency["from_year"]) / recency.get("over_years", 10), 1.0) \
            * recency.get("bonus", 0.0)
    if paper.is_review:
        score += w.get("review", 0.0)
    return round(min(score, 1.0), 3)


class EntityCrawler:
    """Searches S2 for each entity's papers and expands one hop from the best."""

    def __init__(self, spec: dict, config: GovernorConfig, api_key: str | None = None):
        self.spec = spec
        self.config = config
        self.max_papers = spec.get("max_papers", 400)
        self.max_api_calls = spec.get("max_api_calls", 200)
        self.client = S2Client(api_key=api_key, delay=spec.get("rate_limit_delay",
                                                                config.rate_limit_delay))
        self.graph = nx.DiGraph()
        self.papers: dict[str, Paper] = {}
        self.paper_entities: dict[str, set[str]] = {}

    def _should_stop(self) -> bool:
        if len(self.papers) >= self.max_papers:
            print(f"  [budget: {self.max_papers} papers reached]")
            return True
        if self.client.call_count >= self.max_api_calls:
            print(f"  [budget: {self.max_api_calls} API calls reached]")
            return True
        return False

    @staticmethod
    def _dict_to_paper(data: dict) -> Paper | None:
        pid = data.get("paperId")
        if not pid:
            return None
        ext = data.get("externalIds") or {}
        return Paper(
            paper_id=pid,
            title=data.get("title") or "",
            authors=[a.get("name", "") for a in (data.get("authors") or [])[:10]],
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
            is_review="Review" in (data.get("publicationTypes") or []),
        )

    def _consider(self, data: dict, entity: str, tags: list[str],
                  source: str | None = None) -> str | None:
        """Keep a paper that fits the entity; returns its id when newly kept."""
        paper = self._dict_to_paper(data)
        if not paper:
            return None
        paper.relevance_score = entity_relevance(paper, entity, tags, self.spec, self.config)
        if paper.relevance_score < self.spec.get("threshold", 0.3):
            return None
        paper.tags = tag_paper(paper, self.config)
        if paper.paper_id in self.papers:
            self.paper_entities[paper.paper_id].add(entity)
            return None
        self.papers[paper.paper_id] = paper
        self.paper_entities[paper.paper_id] = {entity}
        self.graph.add_node(paper.paper_id)
        if source:
            self.graph.add_edge(source, paper.paper_id, type="references")
        return paper.paper_id

    def crawl_entity(self, entity: str, tags: list[str], focus: str) -> None:
        top: list[str] = []
        for query in search_queries(self.spec, entity, tags, focus):
            if self._should_stop():
                return
            for data in self.client.search(query, limit=self.spec.get("results_per_search", 10)):
                pid = self._consider(data, entity, tags)
                if pid:
                    top.append(pid)
        expand = self.spec.get("expand") or {}
        for pid in top[: expand.get("top", 5)]:
            if self._should_stop():
                return
            for data in self.client.get_references(pid, limit=expand.get("refs", 10)):
                if self._should_stop():
                    return
                self._consider(data, entity, tags, source=pid)

    def save(self, path: str | Path) -> None:
        outdir = Path(path)
        outdir.mkdir(parents=True, exist_ok=True)
        papers_out = []
        for p in sorted(self.papers.values(), key=lambda x: x.relevance_score, reverse=True):
            p.entities = sorted(self.paper_entities.get(p.paper_id, set()))
            d = {k: getattr(p, k) for k in p.__dataclass_fields__}
            papers_out.append(d)
        (outdir / "papers.json").write_text(json.dumps(papers_out, indent=2, default=str))
        edges = [{"source": u, "target": v, "type": d.get("type", "")}
                 for u, v, d in self.graph.edges(data=True)]
        (outdir / "edges.json").write_text(json.dumps(edges, indent=2))
        print(f"\nSaved {len(papers_out)} papers, {len(edges)} edges to {outdir}/")


def run_follow_on(query: dict, spec: dict, consensus: dict | None, out_dir: str | Path,
                  api_key: str | None = None) -> dict:
    """Run one follow-on crawl of a query and save it.  Returns a report."""
    log_s2_auth_status(api_key)
    config = config_for(query, {"name": spec["name"]})
    targets = (consensus_targets(spec, consensus or {}) if spec["entities"] == "consensus"
               else stated_targets(spec))
    crawler = EntityCrawler(spec, config, api_key)
    print(f"\n{'='*60}\nFOLLOW-ON CRAWL: {spec['name']}  ({len(targets)} entities)\n{'='*60}")
    for i, (entity, tags, focus) in enumerate(targets):
        if crawler._should_stop():
            break
        print(f"[{i + 1}/{len(targets)}] {entity}: {', '.join(tags) or '-'}")
        crawler.crawl_entity(entity, tags, focus)
    crawler.save(out_dir)
    found = set().union(*crawler.paper_entities.values()) if crawler.paper_entities else set()
    return {"papers": len(crawler.papers), "edges": crawler.graph.number_of_edges(),
            "api_calls": crawler.client.call_count, "entities": len(targets),
            "entities_with_papers": len(found)}
