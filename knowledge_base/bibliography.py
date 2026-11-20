"""
knowledge_base/bibliography.py — what a named knowledge base's own crawl
records say about a paper beyond its ``papers`` table: the authors (and, for
the check of the whole knowledge base's DOIs, every DOI it recorded).

The ``papers`` table (the toxkb contract) has no authors.  The crawl that
built the knowledge base recorded them (``crawl/<source>/papers.json``, one
list per source the manifest names), and a reference list needs them.  This
reads those records; it changes nothing in a knowledge base, which is
immutable once finished, and sends nothing anywhere.
"""

from __future__ import annotations

import json
from functools import lru_cache

from knowledge_base import registry


@lru_cache(maxsize=8)
def _records(name: str) -> tuple[dict[str, tuple[str, ...]], tuple[str, ...]]:
    """({paper id: authors}, every DOI) of the named knowledge base's crawl."""
    authors_by_id: dict[str, tuple[str, ...]] = {}
    dois: dict[str, None] = {}
    crawl = registry.kb_dir(name) / "crawl"
    for source in registry.manifest(name).get("sources") or []:
        path = crawl / str(source) / "papers.json"
        try:
            papers = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for paper in papers if isinstance(papers, list) else papers.values():
            if not isinstance(paper, dict):
                continue
            authors = tuple(a.strip() for a in paper.get("authors") or []
                            if isinstance(a, str) and a.strip())
            if authors and paper.get("paper_id") and paper["paper_id"] not in authors_by_id:
                authors_by_id[paper["paper_id"]] = authors
            doi = str(paper.get("doi") or "").strip().lower()
            if doi:
                dois.setdefault(doi)
    return authors_by_id, tuple(dois)


def _authors(name: str) -> dict[str, tuple[str, ...]]:
    return _records(name)[0]


def dois_of(name: str) -> list[str]:
    """Every DOI the named knowledge base's crawl recorded, each once
    (lower-cased).  Raises registry.KnowledgeBaseError for an unknown name."""
    return list(_records(name)[1])


def authors_of(name: str | None, paper_id: str | None) -> list[str]:
    """The authors the named knowledge base's crawl recorded for a paper, as
    it recorded them; [] when it recorded none, or the name is not a
    knowledge base."""
    if not name or not paper_id:
        return []
    try:
        return list(_authors(name).get(paper_id, ()))
    except registry.KnowledgeBaseError:
        return []
