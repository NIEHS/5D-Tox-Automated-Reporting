"""
Run a named crawl: a saved crawl query, run through every stage, into a named
knowledge base (knowledge_base.registry).

    python -m knowledge_base.run_crawl <query> --as <crawl name> [--resume]

The stages, each reading its section of the query (knowledge_base.crawl_queries);
a stage whose section is absent is skipped:

    crawl       each of the query's crawls (citegraph)       -> crawl/<name>/papers.json
    fulltext    open full text where it can be had           -> .fulltext_cache/
    extract     each paper's fields (the model, via the gateway) -> crawl/<name>/extractions.json
    consensus   the counted field over every paper          -> crawl/consensus.json
    follow_on   entity crawls from the consensus (then fulltext, extract, consensus again)
    annotate    GO and pathway tables                        -> crawl/*.tsv
    build       the database                                 -> kb.duckdb

The manifest records each stage's status — ran, skipped, could not run (and
why) — and the knowledge base is ``complete`` only when no stage the query asks
for failed.  An unfinished knowledge base is never read (registry.usable); it
can be resumed (``--resume``: a stage's outputs already on disk are reused).
A finished knowledge base's name is never reused.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from common.clock import now_iso
from knowledge_base import crawl_queries, registry


class StageCouldNotRun(RuntimeError):
    """A stage the query asks for that cannot run here (a source unreachable,
    no model endpoint): the knowledge base stays unfinished."""


# ---------------------------------------------------------------------------
# Stage helpers
# ---------------------------------------------------------------------------

def s2_reachable() -> str | None:
    """None when Semantic Scholar answers; else why not."""
    import requests
    from knowledge_base.citegraph import S2_BASE
    try:
        r = requests.get(f"{S2_BASE}/paper/search", params={"query": "test", "limit": 1},
                         timeout=20)
    except requests.RequestException as e:
        return f"Semantic Scholar unreachable: {type(e).__name__}"
    if r.status_code not in (200, 429):
        return f"Semantic Scholar answered {r.status_code}"
    return None


def known_entities(name: str | None, field: str) -> set[str]:
    """A knowledge base's strong and moderate values of a field — the relevance
    floor's known entities (relevance.floor.entities_from)."""
    if not name:
        return set()
    import duckdb
    con = duckdb.connect(str(registry.db_path(name)), read_only=True)
    try:
        tables = {t for (t,) in con.execute("SHOW TABLES").fetchall()}
        if field == "genes" and "genes" in tables:
            rows = con.execute("SELECT gene_symbol FROM genes "
                               "WHERE evidence IN ('consensus', 'moderate')").fetchall()
        elif "paper_entities" in tables:
            rows = con.execute("SELECT value FROM paper_entities WHERE field = ? GROUP BY value "
                               "HAVING COUNT(DISTINCT paper_id) >= 2", [field]).fetchall()
        else:
            rows = []
    finally:
        con.close()
    return {r[0] for r in rows if r[0]}


def extraction_engine(spec: dict):
    from knowledge_base.extract import ParallelExtractionEngine, build_claude_endpoints
    from styling_export.llm_endpoints import resolve_anthropic_api_key
    if not resolve_anthropic_api_key():
        raise StageCouldNotRun("no model endpoint: the gateway's API key is not set")
    kwargs = {"model": spec["model"]} if spec.get("model") else {}
    return ParallelExtractionEngine(spec, build_claude_endpoints(spec.get("workers", 6), **kwargs))


def fetch_fulltext(papers: list[dict]) -> dict:
    from knowledge_base.fulltext import FullTextFetcher
    fetcher = FullTextFetcher()
    results = fetcher.fetch_batch(papers, max_workers=4)
    fetcher.print_stats()
    return results


def extract_dir(engine, source: Path, resume: bool) -> int:
    out = source / "extractions.json"
    if resume and out.exists():
        return len(json.loads(out.read_text()))
    papers = json.loads((source / "papers.json").read_text())
    failed_before = engine.stats["failed"]
    records = engine.process_papers(papers, fulltext_results=fetch_fulltext(papers))
    failed = engine.stats["failed"] - failed_before
    if failed:
        # A paper the model did not answer for would be missing from the
        # knowledge base without a trace: nothing of this crawl is kept, and a
        # resume extracts it again.
        raise StageCouldNotRun(f"{failed} of {len(papers)} papers of {source.name} could not "
                               "be extracted (the model did not answer)")
    out.write_text(json.dumps(records, indent=2, default=str))
    return len(records)


def merge(crawl_dir: Path, order: list[str]) -> list[dict]:
    """One extraction record per paper over every crawl so far (what the build
    and the consensus read)."""
    from knowledge_base.extract import merge_extractions
    merged = merge_extractions([crawl_dir / name / "extractions.json" for name in order])
    (crawl_dir / "extractions_merged.json").write_text(json.dumps(merged, indent=2, default=str))
    return merged


def count(query: dict, crawl_dir: Path) -> dict:
    from knowledge_base.extract import consensus
    merged = json.loads((crawl_dir / "extractions_merged.json").read_text())
    result = consensus(merged, query["extract"], query["consensus"])
    (crawl_dir / "consensus.json").write_text(json.dumps(result, indent=2, default=list))
    return result


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

class Run:
    def __init__(self, query_name: str, kb_name: str, resume: bool = False):
        self.query_name = crawl_queries.check_name(query_name)
        self.kb_name = registry.check_name(kb_name)
        self.text = crawl_queries.read(query_name)
        self.query = crawl_queries.parse(self.text)
        self.dir = registry.kb_dir(kb_name)
        self.crawl_dir = self.dir / registry.CRAWL_DIR
        self.resume = resume
        self.stages: list[dict] = []
        self.order: list[str] = []

    def check(self) -> None:
        """Refuse a name that cannot take this run: a finished knowledge base,
        or an unfinished one not resumed from the same text."""
        manifest = self.dir / registry.MANIFEST_FILE
        if manifest.exists():
            m = json.loads(manifest.read_text())
            if m.get("complete"):
                raise registry.KnowledgeBaseError(
                    f"knowledge base {self.kb_name!r} is finished; a name is never reused")
            if not self.resume:
                raise registry.KnowledgeBaseError(
                    f"knowledge base {self.kb_name!r} exists, unfinished: --resume to continue it")
            if (m.get("query") or {}).get("hash") != crawl_queries.text_hash(self.text):
                raise registry.KnowledgeBaseError(
                    f"knowledge base {self.kb_name!r} was started from another text of "
                    f"{self.query_name!r}; resume it with that text or start a new name")

    def _open(self) -> None:
        self.check()
        self.crawl_dir.mkdir(parents=True, exist_ok=True)
        self.started = now_iso()

    def _record(self, stage: str, status: str, detail: str = "", **counts) -> None:
        self.stages.append({"stage": stage, "status": status, "detail": detail, **counts})
        print(f"[{stage}] {status}{': ' + detail if detail else ''} {counts or ''}")
        self._write_manifest(complete=False)

    def _write_manifest(self, complete: bool) -> dict:
        return registry.write_manifest(self.kb_name, {
            "query": {"name": self.query_name, "hash": crawl_queries.text_hash(self.text),
                      "text": self.text},
            "started": getattr(self, "started", now_iso()), "finished": now_iso() if complete else None,
            "stages": self.stages, "sources": self.order, "complete": complete,
        })

    # -- stages ------------------------------------------------------------

    def crawl(self, api_key) -> None:
        from knowledge_base.citegraph import run_crawl
        floor = (self.query.get("relevance") or {}).get("floor") or {}
        entities = known_entities(floor.get("entities_from"), floor.get("entity", "")) \
            if floor else set()
        papers = 0
        for crawl in self.query["crawls"]:
            out = self.crawl_dir / crawl["name"]
            if not (self.resume and (out / "papers.json").exists()):
                run_crawl(self.query, crawl, out, api_key, entities)
            n = len(json.loads((out / "papers.json").read_text()))
            if n == 0:
                raise StageCouldNotRun(f"crawl {crawl['name']!r} found no papers")
            papers += n
            self.order.append(crawl["name"])
        self._record("crawl", "ran", crawls=len(self.query["crawls"]), papers=papers)

    def extract(self, names: list[str], stage: str = "extract") -> None:
        engine = extraction_engine(self.query["extract"])
        n = sum(extract_dir(engine, self.crawl_dir / name, self.resume) for name in names)
        merged = merge(self.crawl_dir, self.order)
        self._record(stage, "ran", papers=n, merged=len(merged))

    def consensus(self, stage: str = "consensus") -> dict:
        result = count(self.query, self.crawl_dir)
        self._record(stage, "ran", strong=len(result.get("strong", {})),
                     moderate=len(result.get("moderate", {})))
        return result

    def follow_on(self, consensus: dict, api_key) -> None:
        from knowledge_base.entity_crawl import run_follow_on
        names = []
        for spec in self.query["follow_on"]:
            out = self.crawl_dir / spec["name"]
            if not (self.resume and (out / "papers.json").exists()):
                run_follow_on(self.query, spec, consensus, out, api_key)
            names.append(spec["name"])
            self.order.append(spec["name"])
        self._record("follow_on", "ran", crawls=len(names))
        if self.query.get("extract"):
            self.extract(names, stage="follow_on.extract")
            if self.query.get("consensus"):
                self.consensus(stage="follow_on.consensus")

    def annotate(self, consensus: dict) -> None:
        from knowledge_base.annotate import SourceUnreachable, go_table, pathway_table
        ann = self.query["annotate"]
        try:
            counts = {}
            if ann.get("go"):
                counts["go_rows"] = go_table(ann["go"], self.crawl_dir / "go_term_genes.tsv")
            if ann.get("pathways"):
                genes = list(consensus.get("strong", {})) + list(consensus.get("moderate", {}))
                counts["pathway_rows"] = pathway_table(ann["pathways"], genes,
                                                       self.crawl_dir / "pathways.tsv")
        except SourceUnreachable as e:
            raise StageCouldNotRun(str(e)) from None
        self._record("annotate", "ran", **counts)

    def build(self) -> dict:
        from knowledge_base.build_db import build
        (self.crawl_dir / "sources.json").write_text(json.dumps(self.order, indent=2))
        counts = build(self.dir / registry.DB_FILE, self.crawl_dir, self.query)
        self._record("build", "ran", **counts)
        return counts

    # -- driver ------------------------------------------------------------

    def run(self) -> dict:
        from knowledge_base.citegraph import resolve_s2_api_key
        self._open()
        q = self.query
        plan = ["crawl", "extract", "consensus", "follow_on", "annotate", "build"]
        wanted = {"crawl": True, "extract": bool(q.get("extract")),
                  "consensus": bool(q.get("consensus")), "follow_on": bool(q.get("follow_on")),
                  "annotate": bool(q.get("annotate")), "build": True}
        api_key = resolve_s2_api_key()
        consensus: dict = {}
        try:
            reason = s2_reachable()
            if reason and not (self.resume and self._crawled()):
                raise StageCouldNotRun(reason)
            for stage in plan:
                if not wanted[stage]:
                    self._record(stage, "skipped", "the query has no section for it")
                    continue
                if stage == "crawl":
                    self.crawl(api_key)
                elif stage == "extract":
                    self.extract(list(self.order))
                elif stage == "consensus":
                    consensus = self.consensus()
                elif stage == "follow_on":
                    self.follow_on(consensus, api_key)
                    if q.get("consensus"):
                        consensus = json.loads((self.crawl_dir / "consensus.json").read_text())
                elif stage == "annotate":
                    self.annotate(consensus)
                elif stage == "build":
                    self.build()
        except StageCouldNotRun as e:
            done = {s["stage"] for s in self.stages}
            current = next(s for s in plan if s not in done)
            self._record(current, "could_not_run", str(e))
            for s in plan[plan.index(current) + 1:]:
                self._record(s, "not_run", f"after {current}")
            return self._write_manifest(complete=False)
        return self._write_manifest(complete=True)

    def _crawled(self) -> bool:
        return all((self.crawl_dir / c["name"] / "papers.json").exists()
                   for c in self.query["crawls"])


def run(query_name: str, kb_name: str, resume: bool = False) -> dict:
    return Run(query_name, kb_name, resume).run()


def discard(kb_name: str) -> None:
    """Remove an unfinished knowledge base (a finished one is kept)."""
    m = registry.manifest(kb_name)
    if m.get("complete"):
        raise registry.KnowledgeBaseError(f"knowledge base {kb_name!r} is finished; it is kept")
    shutil.rmtree(registry.kb_dir(kb_name))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run a named crawl query into a named knowledge base.")
    ap.add_argument("query", help="a query in crawl_queries/ (its name, without .yaml)")
    ap.add_argument("--as", dest="name", required=True, help="the knowledge base's name")
    ap.add_argument("--resume", action="store_true",
                    help="continue an unfinished knowledge base of this name")
    a = ap.parse_args(argv)
    # The gateway's CA and the model key, as the server and the report CLI have them.
    from tooling.generate_report import _bootstrap_env
    _bootstrap_env()
    m = run(a.query, a.name, a.resume)
    print(json.dumps({k: m[k] for k in ("name", "complete", "capabilities") if k in m}, indent=2))
    return 0 if m.get("complete") else 1


if __name__ == "__main__":
    sys.exit(main())
