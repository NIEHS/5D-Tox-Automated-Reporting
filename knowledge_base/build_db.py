"""
Build a knowledge base's database (kb.duckdb) from its crawl.

``build(db_path, crawl_dir, query)`` reads what knowledge_base.run_crawl left in
``crawl_dir``:

    sources.json             the crawl directories, in the order they are read
    <source>/papers.json     each crawl's papers (the first source to hold a
    <source>/edges.json      paper names it: papers.source)
    extractions_merged.json  one extraction record per paper
    consensus.json           the consensus of the query's ``consensus`` field
    go_term_genes.tsv        the GO annotation (when the query annotates GO)
    pathways.tsv             the pathway annotation (when it annotates pathways)

and writes two layers:

* generic, from any query: ``papers``, ``citation_edges``, ``paper_claims``
  (an extracted ``claims`` field) and ``paper_entities(paper_id, field,
  value)`` — every other list field, normalised by the query's rules;
* the toxicogenomics tables, the contract knowledge_base.toxkb reads, written
  when the query counts genes by organ (``consensus: {field: genes, by:
  organs}``): ``genes``, ``paper_genes``, ``paper_organs``; and from its
  annotations ``go_terms``, ``gene_go_terms``, ``pathways``.

What a database can answer is read off the tables it holds
(knowledge_base.registry.capabilities_of), never declared.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import duckdb
import pandas as pd

from knowledge_base.extract import field_spec, normalizer

GENERIC_SQL = """
CREATE TABLE papers (
    paper_id VARCHAR PRIMARY KEY, title VARCHAR, year INTEGER, abstract VARCHAR,
    venue VARCHAR, doi VARCHAR, citation_count INTEGER, reference_count INTEGER,
    relevance_score DOUBLE, is_seed BOOLEAN, is_review BOOLEAN, source VARCHAR);
CREATE TABLE citation_edges (source_id VARCHAR, target_id VARCHAR);
CREATE TABLE paper_claims (paper_id VARCHAR, claim VARCHAR);
CREATE TABLE paper_entities (paper_id VARCHAR, field VARCHAR, value VARCHAR);
"""

TOX_SQL = """
CREATE TABLE genes (gene_symbol VARCHAR PRIMARY KEY, evidence VARCHAR,
                    mention_count INTEGER, organs VARCHAR[]);
CREATE TABLE paper_genes (paper_id VARCHAR, gene_symbol VARCHAR);
CREATE TABLE paper_organs (paper_id VARCHAR, organ VARCHAR);
CREATE TABLE go_terms (go_id VARCHAR PRIMARY KEY, go_term VARCHAR, cluster_id INTEGER,
                       umap_1 DOUBLE, umap_2 DOUBLE);
CREATE TABLE gene_go_terms (gene_symbol VARCHAR, go_id VARCHAR, species VARCHAR,
                            rat_symbol VARCHAR);
CREATE TABLE pathways (gene_symbol VARCHAR, pathway_db VARCHAR, pathway_id VARCHAR,
                       pathway_name VARCHAR, species VARCHAR);
"""

_PAPER_COLUMNS = ["paper_id", "title", "year", "abstract", "venue", "doi", "citation_count",
                  "reference_count", "relevance_score", "is_seed", "is_review", "source"]


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


def _insert(con, table: str, rows: list[tuple], columns: list[str]) -> int:
    """Bulk insert (a DataFrame scan; row-by-row executemany takes minutes)."""
    if not rows:
        return 0
    frame = pd.DataFrame(rows, columns=columns)
    con.register("_rows", frame)
    con.execute(f"INSERT INTO {table} SELECT {', '.join(columns)} FROM _rows")
    con.unregister("_rows")
    return len(rows)


def sources(crawl_dir: Path) -> list[Path]:
    order = json.loads((crawl_dir / "sources.json").read_text())
    return [crawl_dir / name for name in order]


def is_toxicogenomic(query: dict) -> bool:
    cons = query.get("consensus") or {}
    return cons.get("field") == "genes" and cons.get("by") == "organs"


# ---------------------------------------------------------------------------
# Generic layer
# ---------------------------------------------------------------------------

def load_papers(con, dirs: list[Path]) -> int:
    seen: set[str] = set()
    rows = []
    for d in dirs:
        for p in json.loads((d / "papers.json").read_text()):
            pid = p["paper_id"]
            if pid in seen:
                continue
            seen.add(pid)
            rows.append((pid, p.get("title"), p.get("year"), p.get("abstract"), p.get("venue"),
                         p.get("doi"), p.get("citation_count"), p.get("reference_count"),
                         p.get("relevance_score"), p.get("is_seed"), p.get("is_review"), d.name))
    return _insert(con, "papers", rows, _PAPER_COLUMNS)


def load_citation_edges(con, dirs: list[Path]) -> int:
    seen: set[tuple[str, str]] = set()
    rows = []
    for d in dirs:
        path = d / "edges.json"
        if not path.exists():
            continue
        for e in json.loads(path.read_text()):
            pair = (e["source"], e["target"])
            if pair not in seen:
                seen.add(pair)
                rows.append(pair)
    return _insert(con, "citation_edges", rows, ["source_id", "target_id"])


def load_extracted(con, extractions: list[dict], extract_spec: dict) -> tuple[int, int]:
    """paper_claims (a ``claims`` field) and paper_entities (every other list
    field), values normalised and deduplicated per paper."""
    list_fields = [f for f in extract_spec.get("fields") or [] if f.get("type", "list") == "list"]
    norms = {f["name"]: normalizer(f) for f in list_fields}
    claims, entities = [], []
    for rec in extractions:
        pid = rec["paper_id"]
        for f in list_fields:
            name = f["name"]
            if name == "claims":
                claims += [(pid, c.strip()) for c in rec.get(name) or [] if c and c.strip()]
                continue
            seen: set[str] = set()
            for raw in rec.get(name) or []:
                v = norms[name](raw)
                if v and v not in seen:
                    seen.add(v)
                    entities.append((pid, name, v))
    return (_insert(con, "paper_claims", claims, ["paper_id", "claim"]),
            _insert(con, "paper_entities", entities, ["paper_id", "field", "value"]))


# ---------------------------------------------------------------------------
# Toxicogenomics layer
# ---------------------------------------------------------------------------

def load_genes(con, consensus: dict, extractions: list[dict], extract_spec: dict,
               go_table: Path | None) -> int:
    """Every gene: the consensus's strong ("consensus") and moderate genes, the
    genes named once ("single"), then the GO annotation's other genes (no
    evidence)."""
    norm_gene = normalizer(field_spec(extract_spec, "genes"))
    norm_organ = normalizer(field_spec(extract_spec, "organs"))
    rows: dict[str, tuple] = {}
    for level, label in (("strong", "consensus"), ("moderate", "moderate")):
        for gene, info in consensus.get(level, {}).items():
            sym = gene.upper()
            rows.setdefault(sym, (sym, label, info["count"], info.get("by") or []))

    counts: dict[str, int] = {}
    organs: dict[str, set[str]] = {}
    for rec in extractions:
        rec_organs = {norm_organ(o) for o in rec.get("organs") or []} - {""}
        for raw in rec.get("genes") or []:
            g = norm_gene(raw)
            if g:
                counts[g] = counts.get(g, 0) + 1
                organs.setdefault(g, set()).update(rec_organs)
    for gene, n in counts.items():
        if gene.upper() not in rows and n == 1:
            rows[gene.upper()] = (gene.upper(), "single", 1, sorted(organs.get(gene, set())))

    if go_table is not None:
        with open(go_table, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                sym = row["gene_symbol"].strip().upper()
                if sym and sym not in rows:
                    rows[sym] = (sym, None, None, [])
    return _insert(con, "genes", list(rows.values()),
                   ["gene_symbol", "evidence", "mention_count", "organs"])


def load_paper_genes_organs(con, extractions: list[dict], extract_spec: dict) -> tuple[int, int]:
    norm_gene = normalizer(field_spec(extract_spec, "genes"))
    norm_organ = normalizer(field_spec(extract_spec, "organs"))
    gene_rows, organ_rows = [], []
    for rec in extractions:
        pid = rec["paper_id"]
        for raw_values, norm, out in ((rec.get("genes"), norm_gene, gene_rows),
                                      (rec.get("organs"), norm_organ, organ_rows)):
            seen: set[str] = set()
            for raw in raw_values or []:
                v = norm(raw)
                if v and v not in seen:
                    seen.add(v)
                    out.append((pid, v))
    return (_insert(con, "paper_genes", gene_rows, ["paper_id", "gene_symbol"]),
            _insert(con, "paper_organs", organ_rows, ["paper_id", "organ"]))


def load_go(con, terms_path: Path, go_table: Path) -> tuple[int, int]:
    from knowledge_base.annotate import read_go_terms
    terms = []
    for t in read_go_terms(str(terms_path)):
        try:
            cluster = int(t["cluster_id"])
        except (TypeError, ValueError):
            cluster = -1
        terms.append((t["go_id"], t["go_term"], cluster, float(t["UMAP_1"]), float(t["UMAP_2"])))
    seen: set[str] = set()
    terms = [t for t in terms if not (t[0] in seen or seen.add(t[0]))]
    links = []
    with open(go_table, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            sym = row["gene_symbol"].strip()
            if sym:
                links.append((sym.upper(), row["go_id"], row.get("species", ""),
                              row.get("rat_symbol", "")))
    return (_insert(con, "go_terms", terms, ["go_id", "go_term", "cluster_id", "umap_1", "umap_2"]),
            _insert(con, "gene_go_terms", links, ["gene_symbol", "go_id", "species", "rat_symbol"]))


def load_pathways(con, table: Path) -> int:
    rows = []
    with open(table, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            gene = row["gene_symbol"].strip().upper()
            species = row.get("species", "")
            kegg_id = (row.get("kegg_pathway_id") or "").strip()
            reactome_id = (row.get("reactome_pathway_id") or "").strip()
            if kegg_id:
                rows.append((gene, "kegg", kegg_id,
                             (row.get("kegg_pathway_name") or "").strip() or kegg_id, species))
            if reactome_id:
                rows.append((gene, "reactome", reactome_id,
                             strip_html(row.get("reactome_pathway_name", "")).strip(), species))
    return _insert(con, "pathways", rows,
                   ["gene_symbol", "pathway_db", "pathway_id", "pathway_name", "species"])


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build(db_path: Path, crawl_dir: Path, query: dict) -> dict:
    """Write the database from a crawl directory; returns the rows per table."""
    db_path, crawl_dir = Path(db_path), Path(crawl_dir)
    if db_path.exists():
        db_path.unlink()
    dirs = sources(crawl_dir)
    extract_spec = query.get("extract") or {}
    merged = crawl_dir / "extractions_merged.json"
    extractions = json.loads(merged.read_text()) if merged.exists() else []

    con = duckdb.connect(str(db_path))
    counts: dict[str, int] = {}
    try:
        for stmt in GENERIC_SQL.strip().split(";"):
            if stmt.strip():
                con.execute(stmt)
        counts["papers"] = load_papers(con, dirs)
        counts["citation_edges"] = load_citation_edges(con, dirs)
        counts["paper_claims"], counts["paper_entities"] = load_extracted(
            con, extractions, extract_spec)

        if is_toxicogenomic(query):
            for stmt in TOX_SQL.strip().split(";"):
                if stmt.strip():
                    con.execute(stmt)
            annotate = query.get("annotate") or {}
            go_table = crawl_dir / "go_term_genes.tsv"
            go_table = go_table if (annotate.get("go") and go_table.exists()) else None
            consensus = json.loads((crawl_dir / "consensus.json").read_text())
            counts["genes"] = load_genes(con, consensus, extractions, extract_spec, go_table)
            counts["paper_genes"], counts["paper_organs"] = load_paper_genes_organs(
                con, extractions, extract_spec)
            if go_table is not None:
                from knowledge_base.annotate import _local
                counts["go_terms"], counts["gene_go_terms"] = load_go(
                    con, _local(annotate["go"].get("terms", "")), go_table)
            pathways = crawl_dir / "pathways.tsv"
            if annotate.get("pathways") and pathways.exists():
                counts["pathways"] = load_pathways(con, pathways)
    finally:
        con.close()
    return counts
