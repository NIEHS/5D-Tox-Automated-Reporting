"""
Annotation of a knowledge base's genes: GO terms and pathways.

A crawl query's ``annotate`` section (knowledge_base.crawl_queries) names the
field it annotates and its sources; a query without one is not annotated, and
its knowledge base answers no GO or pathway question (registry capabilities).

    annotate:
      field: genes
      go:
        terms: knowledge_base/data/go_terms_umap.tsv      # the GO terms (id, name,
                                                         # cluster, UMAP position)
        annotations: {rat: <GAF url or path>, human: ..} # gene ↔ term, by species
      pathways:
        kegg: {hsa: human, rno: rat}                     # KEGG organism: its label
        reactome: {Homo sapiens: human}                  # Reactome species: its label

Either source may instead be a table already built (``table: <path>``: the
TSV this module writes), e.g. to rebuild a knowledge base from its own crawl.

A source that cannot be reached raises SourceUnreachable: the stage "could
not run", and the knowledge base is not finished (knowledge_base.run_crawl) —
never built without the annotations its query asks for.
"""

from __future__ import annotations

import csv
import gzip
import io
import shutil
import time
from collections import defaultdict
from pathlib import Path

import requests

from common.paths import REPO_ROOT

GO_COLUMNS = ["go_id", "go_term", "cluster_id", "UMAP_1", "UMAP_2",
              "gene_symbol", "species", "rat_symbol"]
PATHWAY_COLUMNS = ["gene_symbol", "kegg_pathway_id", "kegg_pathway_name",
                   "reactome_pathway_id", "reactome_pathway_name", "species"]
KEGG_BASE = "https://rest.kegg.jp"
REACTOME_BASE = "https://reactome.org/ContentService"


class SourceUnreachable(RuntimeError):
    """An annotation source the run could not read (network, missing file)."""


def _local(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else REPO_ROOT / p


def _read_source(source: str) -> str:
    """A source's text: a URL fetched, or a path read; gzip unpacked."""
    try:
        if source.startswith(("http://", "https://")):
            r = requests.get(source, timeout=300)
            r.raise_for_status()
            raw = r.content
        else:
            raw = _local(source).read_bytes()
    except (requests.RequestException, OSError) as e:
        raise SourceUnreachable(f"{source}: {e}") from None
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# GO
# ---------------------------------------------------------------------------

def read_go_terms(path: str) -> list[dict]:
    with open(_local(path), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def parse_gaf(text: str, aspect: str = "P") -> dict[str, set[str]]:
    """{GO id: {gene symbol}} of a GAF's annotations in ``aspect`` (biological
    process), NOT qualifiers left out."""
    go_genes: dict[str, set[str]] = defaultdict(set)
    for line in io.StringIO(text):
        if line.startswith("!"):
            continue
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 15 or (aspect and parts[8] != aspect) or "NOT" in parts[3]:
            continue
        go_genes[parts[4]].add(parts[2])
    return dict(go_genes)


def go_table(spec: dict, out_path: Path) -> int:
    """Write the gene ↔ GO term table: every term of ``spec["terms"]`` with the
    genes each species' annotations give it (symbols compared uppercased; the
    human spelling shown when both species have the gene).  Returns its rows."""
    if spec.get("table"):
        shutil.copyfile(_local(spec["table"]), out_path)
        return sum(1 for _ in open(out_path)) - 1
    terms = read_go_terms(spec["terms"])
    by_species = {sp: parse_gaf(_read_source(src))
                  for sp, src in (spec.get("annotations") or {}).items()}
    rows = 0
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(GO_COLUMNS)
        for t in terms:
            head = [t["go_id"], t["go_term"], t["cluster_id"], t["UMAP_1"], t["UMAP_2"]]
            spelled: dict[str, str] = {}
            species_of: dict[str, list[str]] = defaultdict(list)
            rat_symbol: dict[str, str] = {}
            for sp, go in by_species.items():
                for g in go.get(t["go_id"], ()):
                    up = g.upper()
                    if sp == "rat":
                        rat_symbol[up] = g
                    if up not in spelled or sp == "human":
                        spelled[up] = g
                    species_of[up].append(sp)
            if not spelled:
                w.writerow(head + ["", "", ""])
                rows += 1
                continue
            for up in sorted(spelled):
                w.writerow(head + [spelled[up], " | ".join(sorted(species_of[up],
                                   key=lambda s: (s != "rat", s))), rat_symbol.get(up, "")])
                rows += 1
    return rows


# ---------------------------------------------------------------------------
# Pathways
# ---------------------------------------------------------------------------

def _kegg_get(path: str) -> str:
    try:
        r = requests.get(f"{KEGG_BASE}{path}", timeout=60)
        r.raise_for_status()
    except requests.RequestException as e:
        raise SourceUnreachable(f"KEGG {path}: {e}") from None
    return r.text


def kegg_pathways(organism: str) -> dict[str, list[tuple[str, str]]]:
    """{GENE SYMBOL: [(pathway id, name)]} for a KEGG organism code."""
    symbol_of: dict[str, str] = {}
    for line in _kegg_get(f"/list/{organism}").splitlines():
        parts = line.split("\t")
        if len(parts) >= 4:
            symbol = parts[3].split(",")[0].split(";")[0].strip()
            if symbol:
                symbol_of[parts[0].strip()] = symbol
    names: dict[str, str] = {}
    for line in _kegg_get(f"/list/pathway/{organism}").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            names[parts[0].strip()] = parts[1].split(" - ")[0].strip()
    out: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for line in _kegg_get(f"/link/{organism}/pathway").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1].strip() in symbol_of:
            pid = parts[0].strip()
            out[symbol_of[parts[1].strip()].upper()].append((pid, names.get(pid, pid)))
    return dict(out)


def reactome_pathways(gene: str, species: str) -> list[tuple[str, str]]:
    try:
        r = requests.get(f"{REACTOME_BASE}/search/query",
                         params={"query": gene, "species": species, "types": "Pathway"},
                         timeout=15)
        if r.status_code == 404:
            return []
        r.raise_for_status()
        data = r.json()
    except requests.ConnectionError as e:
        raise SourceUnreachable(f"Reactome: {e}") from None
    except (requests.RequestException, ValueError):
        return []
    return [(e["stId"], e["name"]) for g in data.get("results", [])
            for e in g.get("entries", []) if e.get("stId") and e.get("name")]


def pathway_table(spec: dict, genes: list[str], out_path: Path) -> int:
    """Write the gene ↔ pathway table for ``genes`` (the consensus's strong and
    moderate values): KEGG for each organism, Reactome per gene.  Returns rows."""
    if spec.get("table"):
        shutil.copyfile(_local(spec["table"]), out_path)
        return sum(1 for _ in open(out_path)) - 1
    kegg = {label: kegg_pathways(org) for org, label in (spec.get("kegg") or {}).items()}
    reactome_species = list((spec.get("reactome") or {}).items())
    rows = 0
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(PATHWAY_COLUMNS)
        for gene in sorted(genes):
            seen: dict[str, tuple[str, list[str]]] = {}
            for label, by_gene in kegg.items():
                for pid, name in by_gene.get(gene.upper(), []):
                    seen.setdefault(name, (pid, []))[1].append(label)
            reactome = []
            for species, label in reactome_species:
                reactome += [(pid, name, label) for pid, name in reactome_pathways(gene, species)]
                time.sleep(0.3)
            if not seen and not reactome:
                w.writerow([gene, "", "", "", "", ""])
                rows += 1
                continue
            for name in sorted(seen):
                pid, orgs = seen[name]
                w.writerow([gene, pid, name, "", "", " | ".join(orgs)])
                rows += 1
            for name, (pid, label) in sorted({n: (p, lb) for p, n, lb in reactome}.items()):
                w.writerow([gene, "", "", pid, name, label])
                rows += 1
    return rows
