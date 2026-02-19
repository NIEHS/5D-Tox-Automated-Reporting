"""
Build bmdx.duckdb — a normalized analytical database linking papers, genes,
GO terms, pathways, and citation networks from all crawl data.

Usage:
    python build_db.py                      # → bmdx.duckdb
    python build_db.py --output foo.duckdb  # custom path
"""

import argparse
import csv
import json
import re
import sys
from glob import glob
from pathlib import Path

import duckdb

from extract import normalize_gene, normalize_organ
from go_gene_map import parse_reference_umap

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE = Path(__file__).resolve().parent
TS_PATH = Path(
    "/home/svobodadl/Dev/Projects/BMDExpress-Web-Edition"
    "/src/main/frontend/data/referenceUmapData.ts"
)
CONSENSUS_PATH = BASE / "citegraph_output" / "gene_consensus_merged.json"
EXTRACTIONS_PATH = BASE / "citegraph_output" / "gene_consensus_merged_extractions.json"
GO_GENES_PATH = BASE / "go_term_genes.tsv"
PATHWAY_PATH = BASE / "pathway_enrichment.tsv"


def source_label(dirpath: str) -> str:
    """Derive a short source label from a citegraph_output* directory name."""
    name = Path(dirpath).name
    # "citegraph_output" → "base", "citegraph_output_800" → "800", etc.
    if name == "citegraph_output":
        return "base"
    return name.removeprefix("citegraph_output_")


def strip_html(text: str) -> str:
    """Remove HTML tags from a string."""
    return re.sub(r"<[^>]+>", "", text)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE TABLE go_terms (
    go_id        VARCHAR PRIMARY KEY,
    go_term      VARCHAR,
    cluster_id   INTEGER,
    umap_1       DOUBLE,
    umap_2       DOUBLE
);

CREATE TABLE genes (
    gene_symbol    VARCHAR PRIMARY KEY,
    evidence       VARCHAR,
    mention_count  INTEGER,
    organs         VARCHAR[]
);

CREATE TABLE papers (
    paper_id         VARCHAR PRIMARY KEY,
    title            VARCHAR,
    year             INTEGER,
    abstract         VARCHAR,
    venue            VARCHAR,
    doi              VARCHAR,
    citation_count   INTEGER,
    reference_count  INTEGER,
    relevance_score  DOUBLE,
    is_seed          BOOLEAN,
    is_review        BOOLEAN,
    source           VARCHAR
);

CREATE TABLE gene_go_terms (
    gene_symbol  VARCHAR,
    go_id        VARCHAR,
    species      VARCHAR,
    rat_symbol   VARCHAR
);

CREATE TABLE paper_genes (
    paper_id     VARCHAR,
    gene_symbol  VARCHAR
);

CREATE TABLE paper_organs (
    paper_id     VARCHAR,
    organ        VARCHAR
);

CREATE TABLE paper_claims (
    paper_id     VARCHAR,
    claim        VARCHAR
);

CREATE TABLE citation_edges (
    source_id    VARCHAR,
    target_id    VARCHAR
);

CREATE TABLE pathways (
    gene_symbol   VARCHAR,
    pathway_db    VARCHAR,
    pathway_id    VARCHAR,
    pathway_name  VARCHAR,
    species       VARCHAR
);
"""


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_go_terms(con: duckdb.DuckDBPyConnection) -> int:
    """Load go_terms from referenceUmapData.ts."""
    items = parse_reference_umap(str(TS_PATH))
    rows = []
    for item in items:
        cluster = item["cluster_id"]
        try:
            cluster = int(cluster)
        except (ValueError, TypeError):
            cluster = -1
        rows.append((
            item["go_id"],
            item["go_term"],
            cluster,
            item["UMAP_1"],
            item["UMAP_2"],
        ))
    con.executemany(
        "INSERT OR IGNORE INTO go_terms VALUES (?, ?, ?, ?, ?)", rows
    )
    return len(rows)


def load_genes(con: duckdb.DuckDBPyConnection) -> int:
    """Load genes from consensus merged JSON + supplement from go_term_genes.tsv."""
    with open(CONSENSUS_PATH) as f:
        data = json.load(f)

    rows: dict[str, tuple] = {}

    # Consensus genes (3+ papers)
    for gene, info in data["consensus_genes"].items():
        sym = gene.upper()
        rows[sym] = (sym, "consensus", info["count"], info.get("organs", []))

    # Moderate evidence (2 papers)
    for gene, info in data["moderate_evidence"].items():
        sym = gene.upper()
        if sym not in rows:
            rows[sym] = (sym, "moderate", info["count"], info.get("organs", []))

    # Single-mention genes — rebuild from extractions
    with open(EXTRACTIONS_PATH) as f:
        extractions = json.load(f)

    gene_counts: dict[str, int] = {}
    gene_organs: dict[str, set] = {}
    for ext in extractions:
        organs = set()
        for o in ext.get("organs", []):
            normed = normalize_organ(o)
            if normed:
                organs.add(normed)
        for raw_gene in ext.get("genes", []):
            g = normalize_gene(raw_gene)
            if not g:
                continue
            gene_counts[g] = gene_counts.get(g, 0) + 1
            gene_organs.setdefault(g, set()).update(organs)

    for gene, count in gene_counts.items():
        key = gene.upper()
        if key not in rows and count == 1:
            rows[key] = (key, "single", 1, sorted(gene_organs.get(gene, set())))

    # Supplement: genes from go_term_genes.tsv not yet present
    with open(GO_GENES_PATH, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            sym = row["gene_symbol"].strip().upper()
            if sym and sym not in rows:
                rows[sym] = (sym, None, None, [])

    con.executemany(
        "INSERT OR IGNORE INTO genes VALUES (?, ?, ?, ?)",
        list(rows.values()),
    )
    return len(rows)


def load_papers(con: duckdb.DuckDBPyConnection) -> int:
    """Load papers from all citegraph_output*/papers.json, deduped."""
    seen: set[str] = set()
    rows = []

    for path in sorted(glob(str(BASE / "citegraph_output*/papers.json"))):
        source = source_label(str(Path(path).parent))
        with open(path) as f:
            papers = json.load(f)
        for p in papers:
            pid = p["paper_id"]
            if pid in seen:
                continue
            seen.add(pid)
            rows.append((
                pid,
                p.get("title"),
                p.get("year"),
                p.get("abstract"),
                p.get("venue"),
                p.get("doi"),
                p.get("citation_count"),
                p.get("reference_count"),
                p.get("relevance_score"),
                p.get("is_seed"),
                p.get("is_review"),
                source,
            ))

    con.executemany(
        "INSERT OR IGNORE INTO papers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    return len(rows)


def load_gene_go_terms(con: duckdb.DuckDBPyConnection) -> int:
    """Load gene ↔ GO term mappings from go_term_genes.tsv."""
    rows = []
    with open(GO_GENES_PATH, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            sym = row["gene_symbol"].strip()
            if not sym:
                continue
            rows.append((
                sym.upper(),
                row["go_id"],
                row.get("species", ""),
                row.get("rat_symbol", ""),
            ))
    con.executemany("INSERT INTO gene_go_terms VALUES (?, ?, ?, ?)", rows)
    return len(rows)


def load_paper_genes_organs_claims(con: duckdb.DuckDBPyConnection) -> tuple[int, int, int]:
    """Load paper_genes, paper_organs, paper_claims from merged extractions."""
    with open(EXTRACTIONS_PATH) as f:
        extractions = json.load(f)

    gene_rows = []
    organ_rows = []
    claim_rows = []

    for ext in extractions:
        pid = ext["paper_id"]

        # Genes — normalize and deduplicate per paper
        seen_genes: set[str] = set()
        for raw_gene in ext.get("genes", []):
            g = normalize_gene(raw_gene)
            if g and g not in seen_genes:
                seen_genes.add(g)
                gene_rows.append((pid, g))

        # Organs — normalize and deduplicate per paper
        seen_organs: set[str] = set()
        for raw_organ in ext.get("organs", []):
            o = normalize_organ(raw_organ)
            if o and o not in seen_organs:
                seen_organs.add(o)
                organ_rows.append((pid, o))

        # Claims
        for claim in ext.get("claims", []):
            if claim and claim.strip():
                claim_rows.append((pid, claim.strip()))

    con.executemany("INSERT INTO paper_genes VALUES (?, ?)", gene_rows)
    con.executemany("INSERT INTO paper_organs VALUES (?, ?)", organ_rows)
    con.executemany("INSERT INTO paper_claims VALUES (?, ?)", claim_rows)
    return len(gene_rows), len(organ_rows), len(claim_rows)


def load_citation_edges(con: duckdb.DuckDBPyConnection) -> int:
    """Load citation edges from all citegraph_output*/edges.json, deduped."""
    seen: set[tuple[str, str]] = set()
    rows = []

    for path in sorted(glob(str(BASE / "citegraph_output*/edges.json"))):
        with open(path) as f:
            edges = json.load(f)
        for e in edges:
            pair = (e["source"], e["target"])
            if pair not in seen:
                seen.add(pair)
                rows.append(pair)

    con.executemany("INSERT INTO citation_edges VALUES (?, ?)", rows)
    return len(rows)


def load_pathways(con: duckdb.DuckDBPyConnection) -> int:
    """Load pathways from pathway_enrichment.tsv, splitting KEGG and Reactome."""
    rows = []
    with open(PATHWAY_PATH, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            gene = row["gene_symbol"].strip().upper()
            species = row.get("species", "")

            kegg_id = row.get("kegg_pathway_id", "").strip()
            reactome_id = row.get("reactome_pathway_id", "").strip()

            if kegg_id:
                rows.append((
                    gene, "kegg", kegg_id,
                    kegg_id,  # name == id in this dataset
                    species,
                ))
            if reactome_id:
                name = strip_html(row.get("reactome_pathway_name", "")).strip()
                rows.append((
                    gene, "reactome", reactome_id, name, species,
                ))

    con.executemany("INSERT INTO pathways VALUES (?, ?, ?, ?, ?)", rows)
    return len(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build(db_path: str) -> None:
    """Build the database from all sources."""
    db = Path(db_path)
    if db.exists():
        db.unlink()
        print(f"Removed existing {db}")

    con = duckdb.connect(str(db))
    con.execute("SET threads = 4")

    print("Creating schema...")
    for stmt in SCHEMA_SQL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            con.execute(stmt)

    print("Loading go_terms...")
    n = load_go_terms(con)
    print(f"  {n:,} GO terms")

    print("Loading genes...")
    n = load_genes(con)
    print(f"  {n:,} genes")

    print("Loading papers...")
    n = load_papers(con)
    print(f"  {n:,} papers")

    print("Loading gene_go_terms...")
    n = load_gene_go_terms(con)
    print(f"  {n:,} gene-GO mappings")

    print("Loading paper_genes, paper_organs, paper_claims...")
    ng, no, nc = load_paper_genes_organs_claims(con)
    print(f"  {ng:,} paper-gene links")
    print(f"  {no:,} paper-organ links")
    print(f"  {nc:,} paper claims")

    print("Loading citation_edges...")
    n = load_citation_edges(con)
    print(f"  {n:,} citation edges")

    print("Loading pathways...")
    n = load_pathways(con)
    print(f"  {n:,} pathway entries")

    con.close()
    size_mb = db.stat().st_size / 1_048_576
    print(f"\nDone — {db} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build bmdx.duckdb analytical database")
    parser.add_argument("--output", default="bmdx.duckdb", help="Output database path")
    args = parser.parse_args()
    build(args.output)
