"""
knowledge_base/crawl_queries.py — named crawl queries: text documents a person
edits, directly or with the query agent (knowledge_base.query_agent).

A query is the whole recipe of a knowledge base, as YAML text in
``crawl_queries/<name>.yaml``: what to crawl (seeds, searches), how to judge a
paper (relevance, tag vocabularies), what to extract from each paper, what to
count (consensus), what to crawl next from that (follow-on crawls) and what to
annotate (GO, pathways).  Every stage of knowledge_base.run_crawl reads its own
section; a stage whose section is absent is skipped.  Nothing in the code knows
the topic: ``crawl_queries/baseline.yaml`` holds the toxicogenomics query
behind the May 2026 knowledge base, stated in full.

The text is the source of truth.  It is checked loosely before it is saved
(``check``): the YAML parses, the sections the stages read have the shapes they
read — the content is never judged.  A saved query is never lost: saving over
an existing name archives the old text first (``crawl_queries/.history/``).

Format 1 (every key optional unless marked):

    format: 1                                   # required
    description: text
    crawler: {max_depth, relevance_threshold, saturation_window,
              saturation_threshold, max_refs_per_paper, max_cites_per_paper,
              rate_limit_delay}                 # every crawl's defaults
    relevance:
      keywords: [..]                            # topic words, title counts 3x
      review_bonus: 0.1
      recency: {from_year, over_years, bonus}
      boost: {one, two_or_more}                 # a crawl's boost words
      floor: {entities_from, entity, tag, score}  # a known entity + a tag word
    tags: {<vocabulary>: {<tag>: [words]}}      # paper tags, e.g. organ
    crawls:                                     # required, at least one
      - name: ..                                # required
        seeds: ["DOI:..", ..]
        searches: [{query, limit}, ..]
        keywords: [..]                          # replaces relevance.keywords
        boost: [..]
        floor: true                             # apply relevance.floor
        max_papers / max_api_calls / any crawler key
    extract:
      system: text
      fields: [{name, type: list|text|number, describe, describe_fulltext,
                fulltext_only, normalize: {case, strip, drop_containing, aliases}}]
      chunk: {max_chars, overlap}
      model / workers
    consensus: {field, by, strong, moderate,
                count: papers | mentions}       # papers (default): each paper once
                                                # per value; mentions: every
                                                # mention (the May 2026 run's way)
    follow_on: [{name, entities: consensus | [{entity, tags, focus}], ...}]
    annotate: {field, go: {terms, annotations: {species: source}},
               pathways: {kegg: {<organism code>: <label>},
                          reactome: {<species>: <label>}}}
              (go or pathways may instead be {table: <a TSV already built>})
"""

from __future__ import annotations

import difflib
import hashlib
import os
import re
from pathlib import Path

import yaml

from common.clock import now_iso
from common.paths import REPO_ROOT

# The format as the docstring states it: what the query agent is told.
FORMAT_DOC = __doc__[__doc__.index("Format 1"):]

QUERIES_DIR = Path(os.environ.get("CRAWL_QUERIES_DIR", REPO_ROOT / "crawl_queries"))
HISTORY_DIR = ".history"
FORMAT = 1

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_CRAWLER_INTS = ("max_depth", "max_papers", "max_api_calls", "saturation_window",
                 "max_refs_per_paper", "max_cites_per_paper")
_CRAWLER_FRACTIONS = ("relevance_threshold", "saturation_threshold")
_FIELD_TYPES = ("list", "text", "number")
# How the consensus counts a value (consensus.count).
COUNTS = ("papers", "mentions")
_TOP_KEYS = {"format", "description", "crawler", "relevance", "tags", "crawls",
             "extract", "consensus", "follow_on", "annotate"}


class QueryError(ValueError):
    """A query text the stages could not read, or a name that is not one."""


# The one rule for a name that becomes a file or directory: a query's, a
# crawl's, a knowledge base's (knowledge_base.registry).
NAME_RULE = "letters, digits, '.', '_', '-'; at most 64 characters"


def is_name(name) -> bool:
    return isinstance(name, str) and bool(_NAME.match(name))


def check_name(name: str) -> str:
    if not is_name(name):
        raise QueryError(f"{name!r} is not a query name ({NAME_RULE})")
    return name


# ---------------------------------------------------------------------------
# Reading and checking the text
# ---------------------------------------------------------------------------

def parse(text: str) -> dict:
    """The query a text states, checked (``check``)."""
    try:
        query = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise QueryError(f"the query is not valid YAML: {e}") from None
    check(query)
    return query


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _strings(v, where: str) -> None:
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise QueryError(f"{where} must be a list of strings")


def _crawler_keys(d: dict, where: str) -> None:
    for key in _CRAWLER_INTS:
        if key in d and (not isinstance(d[key], int) or isinstance(d[key], bool) or d[key] <= 0):
            raise QueryError(f"{where}.{key} must be a positive whole number (got {d[key]!r})")
    for key in _CRAWLER_FRACTIONS:
        if key in d and not (_is_number(d[key]) and 0 <= d[key] <= 1):
            raise QueryError(f"{where}.{key} must be a number from 0 to 1 (got {d[key]!r})")
    if "rate_limit_delay" in d and not (_is_number(d["rate_limit_delay"])
                                        and d["rate_limit_delay"] >= 0):
        raise QueryError(f"{where}.rate_limit_delay must be a number of seconds")


def check(query) -> None:
    """Raise QueryError when the stages could not read ``query``.  Only shapes
    are checked — never what the query is about."""
    if not isinstance(query, dict):
        raise QueryError("a query is a mapping of sections")
    if query.get("format") != FORMAT:
        raise QueryError(f"format must be {FORMAT}")
    unknown = set(query) - _TOP_KEYS
    if unknown:
        raise QueryError(f"unknown section(s) {sorted(unknown)}; a query has {sorted(_TOP_KEYS)}")
    if "crawler" in query:
        if not isinstance(query["crawler"], dict):
            raise QueryError("crawler must be a mapping")
        _crawler_keys(query["crawler"], "crawler")

    rel = query.get("relevance") or {}
    if not isinstance(rel, dict):
        raise QueryError("relevance must be a mapping")
    if "keywords" in rel:
        _strings(rel["keywords"], "relevance.keywords")
    floor = rel.get("floor")
    if floor is not None and not (isinstance(floor, dict) and floor.get("entity")
                                  and floor.get("tag") and _is_number(floor.get("score"))):
        raise QueryError("relevance.floor needs entity, tag and score")

    tags = query.get("tags") or {}
    if not isinstance(tags, dict):
        raise QueryError("tags must be a mapping of vocabularies")
    for vocab, terms in tags.items():
        if not isinstance(terms, dict):
            raise QueryError(f"tags.{vocab} must map each tag to its words")
        for tag, words in terms.items():
            _strings(words, f"tags.{vocab}.{tag}")

    crawls = query.get("crawls")
    if not isinstance(crawls, list) or not crawls:
        raise QueryError("crawls must list at least one crawl")
    names: set[str] = set()
    for i, crawl in enumerate(crawls):
        where = f"crawls[{i}]"
        if not isinstance(crawl, dict) or not isinstance(crawl.get("name"), str):
            raise QueryError(f"{where} needs a name")
        check_name(crawl["name"])
        if crawl["name"] in names:
            raise QueryError(f"two crawls are named {crawl['name']!r}")
        names.add(crawl["name"])
        _strings(crawl.get("seeds", []), f"{where}.seeds")
        for s in crawl.get("searches", []) or []:
            if not (isinstance(s, dict) and isinstance(s.get("query"), str)
                    and isinstance(s.get("limit", 5), int)):
                raise QueryError(f"{where}.searches: each is {{query, limit}}")
        if not crawl.get("seeds") and not crawl.get("searches"):
            raise QueryError(f"{where} ({crawl['name']}) has no seeds and no searches")
        for key in ("keywords", "boost"):
            if key in crawl:
                _strings(crawl[key], f"{where}.{key}")
        if crawl.get("floor") and not floor:
            raise QueryError(f"{where} asks for the relevance floor; relevance.floor states none")
        _crawler_keys(crawl, where)

    extract = query.get("extract")
    if extract is not None:
        fields = extract.get("fields") if isinstance(extract, dict) else None
        if not isinstance(fields, list) or not fields:
            raise QueryError("extract.fields must list the fields to extract")
        seen: set[str] = set()
        for f in fields:
            if not (isinstance(f, dict) and isinstance(f.get("name"), str)
                    and f.get("type", "list") in _FIELD_TYPES and isinstance(f.get("describe"), str)):
                raise QueryError("extract.fields: each is {name, type: list|text|number, describe}")
            if f["name"] in seen:
                raise QueryError(f"extract.fields names {f['name']!r} twice")
            seen.add(f["name"])
        list_fields = {f["name"] for f in fields if f.get("type", "list") == "list"}
        cons = query.get("consensus")
        if cons is not None:
            if not isinstance(cons, dict) or cons.get("field") not in list_fields:
                raise QueryError("consensus.field must name a list field of extract")
            if cons.get("by") is not None and cons["by"] not in list_fields:
                raise QueryError("consensus.by must name a list field of extract")
            for key in ("strong", "moderate"):
                if key in cons and (not isinstance(cons[key], int) or cons[key] < 1):
                    raise QueryError(f"consensus.{key} must be a whole number of papers")
            if cons.get("count", "papers") not in COUNTS:
                raise QueryError(f"consensus.count is one of {list(COUNTS)}")
    elif query.get("consensus") is not None:
        raise QueryError("consensus counts an extracted field; the query extracts nothing")

    for i, fo in enumerate(query.get("follow_on") or []):
        if not (isinstance(fo, dict) and isinstance(fo.get("name"), str)):
            raise QueryError(f"follow_on[{i}] needs a name")
        check_name(fo["name"])
        if fo["name"] in names:
            raise QueryError(f"follow_on {fo['name']!r} has a crawl's name")
        names.add(fo["name"])
        entities = fo.get("entities")
        if entities == "consensus":
            if not query.get("consensus"):
                raise QueryError(f"follow_on {fo['name']!r} starts from the consensus; "
                                 "the query states none")
        elif not (isinstance(entities, list) and all(
                isinstance(e, dict) and isinstance(e.get("entity"), str) for e in entities)):
            raise QueryError(f"follow_on {fo['name']!r}: entities is 'consensus' or a list "
                             "of {entity, tags, focus}")
        _strings(fo.get("templates", []), f"follow_on {fo['name']}.templates")

    ann = query.get("annotate")
    if ann is not None:
        if not isinstance(ann, dict) or not ann.get("field"):
            raise QueryError("annotate needs the field it annotates")
        if not (ann.get("go") or ann.get("pathways")):
            raise QueryError("annotate names no source (go, pathways)")


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

def _path(name: str) -> Path:
    return QUERIES_DIR / f"{check_name(name)}.yaml"


def list_queries() -> list[dict]:
    out = []
    for path in sorted(QUERIES_DIR.glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        try:
            desc = (yaml.safe_load(text) or {}).get("description", "")
        except yaml.YAMLError:
            desc = ""
        out.append({"name": path.stem, "description": " ".join(str(desc or "").split()),
                    "hash": text_hash(text)})
    return out


def read(name: str) -> str:
    path = _path(name)
    if not path.exists():
        raise QueryError(f"no query named {name!r}")
    return path.read_text(encoding="utf-8")


def save(name: str, text: str) -> dict:
    """Check and save ``text`` as the query ``name``; an existing text under that
    name is archived first.  Returns {name, hash, archived}."""
    parse(text)
    path = _path(name)
    archived = None
    if path.exists():
        old = path.read_text(encoding="utf-8")
        if old == text:
            return {"name": name, "hash": text_hash(text), "archived": None}
        hist = QUERIES_DIR / HISTORY_DIR / name
        hist.mkdir(parents=True, exist_ok=True)
        archived = hist / f"{now_iso().replace(':', '-')}.yaml"
        archived.write_text(old, encoding="utf-8")
    QUERIES_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return {"name": name, "hash": text_hash(text),
            "archived": str(archived.relative_to(QUERIES_DIR)) if archived else None}


def history(name: str) -> list[str]:
    hist = QUERIES_DIR / HISTORY_DIR / check_name(name)
    return sorted(p.name for p in hist.glob("*.yaml")) if hist.exists() else []


def diff(old: str, new: str, old_name: str = "current", new_name: str = "proposed") -> str:
    return "".join(difflib.unified_diff(old.splitlines(keepends=True),
                                        new.splitlines(keepends=True),
                                        fromfile=old_name, tofile=new_name))
