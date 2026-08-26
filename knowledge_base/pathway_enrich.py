"""
Pathway enrichment: cross-reference consensus/moderate genes with
KEGG and Reactome pathway databases.

KEGG: Bulk download human + rat gene-pathway links via REST API.
Reactome: Per-gene pathway lookup via REST API.

Usage:
    python pathway_enrich.py [consensus_path] [output_path]

Output:
    pathway_enrichment.tsv — one row per gene-pathway pair
"""

import csv
import json
import time
from collections import defaultdict

import requests


# ---------------------------------------------------------------------------
# KEGG REST API
# ---------------------------------------------------------------------------

KEGG_BASE = "https://rest.kegg.jp"


def _kegg_get(path: str) -> str:
    """Fetch a KEGG REST endpoint. Returns raw text."""
    url = f"{KEGG_BASE}{path}"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.text


def fetch_kegg_gene_symbol_map(species: str = "hsa") -> dict[str, str]:
    """
    Build KEGG gene ID -> gene symbol mapping.
    Uses rest.kegg.jp/list/{species} which returns 4-column TSV:
        hsa:123    CDS    17    SYMBOL1, SYMBOL2; description
    Gene symbols are in the 4th column, comma-separated before the semicolon.
    We take the first symbol.
    """
    print(f"  Fetching KEGG gene list for {species}...")
    text = _kegg_get(f"/list/{species}")

    gene_map: dict[str, str] = {}
    for line in text.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        kegg_id = parts[0].strip()  # e.g. "hsa:123"
        desc = parts[3].strip()     # e.g. "SYMBOL1, SYMBOL2; description"
        # First symbol before comma or semicolon
        symbol = desc.split(",")[0].split(";")[0].strip()
        if symbol:
            gene_map[kegg_id] = symbol

    print(f"    {len(gene_map)} genes")
    return gene_map


def fetch_kegg_pathway_names(species: str = "hsa") -> dict[str, str]:
    """
    Fetch pathway ID -> pathway name mapping.
    Uses rest.kegg.jp/list/pathway/{species}
    """
    print(f"  Fetching KEGG pathway names for {species}...")
    text = _kegg_get(f"/list/pathway/{species}")

    names: dict[str, str] = {}
    for line in text.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        pathway_id = parts[0].strip()  # e.g. "path:hsa00010"
        name = parts[1].strip()
        # Remove species suffix like " - Homo sapiens (human)"
        if " - " in name:
            name = name.split(" - ")[0].strip()
        names[pathway_id] = name

    print(f"    {len(names)} pathways")
    return names


def fetch_kegg_gene_pathway_links(species: str = "hsa") -> dict[str, list[str]]:
    """
    Bulk download all gene-pathway links.
    Uses rest.kegg.jp/link/{species}/pathway
    Returns: {kegg_gene_id: [pathway_id, ...]}
    """
    print(f"  Fetching KEGG gene-pathway links for {species}...")
    text = _kegg_get(f"/link/{species}/pathway")

    links: dict[str, list[str]] = defaultdict(list)
    for line in text.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        pathway_id = parts[0].strip()  # e.g. "path:hsa00010"
        gene_id = parts[1].strip()     # e.g. "hsa:10"
        links[gene_id].append(pathway_id)

    print(f"    {sum(len(v) for v in links.values())} links across "
          f"{len(links)} genes")
    return dict(links)


def fetch_kegg_pathways(
    species: str = "hsa",
) -> dict[str, list[tuple[str, str]]]:
    """
    Build gene_symbol -> [(pathway_id, pathway_name)] for a species.
    Combines gene list, pathway names, and gene-pathway links.
    """
    gene_map = fetch_kegg_gene_symbol_map(species)
    pathway_names = fetch_kegg_pathway_names(species)
    gene_pathway_links = fetch_kegg_gene_pathway_links(species)

    result: dict[str, list[tuple[str, str]]] = defaultdict(list)

    for kegg_gene_id, pathway_ids in gene_pathway_links.items():
        symbol = gene_map.get(kegg_gene_id, "")
        if not symbol:
            continue
        symbol_upper = symbol.upper()
        for pathway_id in pathway_ids:
            name = pathway_names.get(pathway_id, pathway_id)
            result[symbol_upper].append((pathway_id, name))

    print(f"  KEGG {species}: {len(result)} genes with pathway annotations")
    return dict(result)


# ---------------------------------------------------------------------------
# Reactome REST API
# ---------------------------------------------------------------------------

REACTOME_BASE = "https://reactome.org/ContentService"


def fetch_reactome_pathways(
    gene_symbol: str,
    species: str = "Homo sapiens",
) -> list[tuple[str, str]]:
    """
    Query Reactome for pathways associated with a gene.
    Returns [(pathway_id, pathway_name), ...].
    """
    url = f"{REACTOME_BASE}/search/query"
    params = {
        "query": gene_symbol,
        "species": species,
        "types": "Pathway",
    }

    try:
        r = requests.get(url, params=params, timeout=15)
        if r.status_code == 404:
            return []
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError):
        return []

    pathways: list[tuple[str, str]] = []
    for group in data.get("results", []):
        for entry in group.get("entries", []):
            pid = entry.get("stId", "")
            name = entry.get("name", "")
            if pid and name:
                pathways.append((pid, name))

    return pathways


# ---------------------------------------------------------------------------
# Load consensus genes
# ---------------------------------------------------------------------------

def load_consensus_genes(
    consensus_path: str,
) -> dict[str, dict]:
    """
    Load consensus + moderate genes from gene_consensus.json.
    Returns: {gene_symbol: {evidence, count, organs}}
    """
    with open(consensus_path) as f:
        data = json.load(f)

    genes: dict[str, dict] = {}
    for gene, info in data.get("consensus_genes", {}).items():
        genes[gene] = {
            "evidence": "consensus",
            "count": info["count"],
            "organs": info.get("organs", []),
        }
    for gene, info in data.get("moderate_evidence", {}).items():
        genes[gene] = {
            "evidence": "moderate",
            "count": info["count"],
            "organs": info.get("organs", []),
        }
    return genes


# ---------------------------------------------------------------------------
# Build pathway enrichment TSV
# ---------------------------------------------------------------------------

def build_pathway_tsv(
    consensus_path: str = "citegraph_output/gene_consensus.json",
    output_path: str = "pathway_enrichment.tsv",
):
    """
    Orchestrator: fetch KEGG + Reactome pathways for all consensus/moderate
    genes and write a combined TSV.
    """
    print("="*60)
    print("PATHWAY ENRICHMENT")
    print("="*60)

    # Load our genes
    genes = load_consensus_genes(consensus_path)
    print(f"\nLoaded {len(genes)} genes "
          f"({sum(1 for g in genes.values() if g['evidence'] == 'consensus')} consensus, "
          f"{sum(1 for g in genes.values() if g['evidence'] == 'moderate')} moderate)")

    # Fetch KEGG (bulk — 3 API calls per species)
    print("\n--- KEGG (Human) ---")
    kegg_hsa = fetch_kegg_pathways("hsa")
    print("\n--- KEGG (Rat) ---")
    kegg_rno = fetch_kegg_pathways("rno")

    # Fetch Reactome (per-gene — ~1 call per gene)
    print(f"\n--- Reactome (per-gene, {len(genes)} queries) ---")
    reactome_cache: dict[str, list[tuple[str, str]]] = {}
    for i, gene in enumerate(genes):
        pathways = fetch_reactome_pathways(gene)
        if pathways:
            reactome_cache[gene] = pathways
        if (i + 1) % 10 == 0:
            print(f"  [{i+1}/{len(genes)}] {gene}: {len(pathways)} pathways")
        time.sleep(0.3)  # be polite to Reactome

    print(f"  Reactome: {len(reactome_cache)} genes with pathway hits")

    # Write TSV
    rows_written = 0
    genes_with_pathways = 0

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow([
            "gene_symbol",
            "kegg_pathway_id", "kegg_pathway_name",
            "reactome_pathway_id", "reactome_pathway_name",
            "tox_evidence", "tox_organs", "species",
        ])

        for gene, info in sorted(genes.items()):
            gene_upper = gene.upper()
            kegg_human = kegg_hsa.get(gene_upper, [])
            kegg_rat = kegg_rno.get(gene_upper, [])
            reactome = reactome_cache.get(gene, [])

            has_any = bool(kegg_human or kegg_rat or reactome)
            if has_any:
                genes_with_pathways += 1

            tox_evidence = info["evidence"]
            tox_organs = " | ".join(info.get("organs", []))

            # Emit one row per pathway hit
            # Combine KEGG human + rat (deduplicate by pathway name)
            kegg_all: dict[str, tuple[str, str]] = {}
            for pid, name in kegg_human:
                kegg_all[name] = (pid, "human")
            for pid, name in kegg_rat:
                if name in kegg_all:
                    kegg_all[name] = (kegg_all[name][0], "human | rat")
                else:
                    kegg_all[name] = (pid, "rat")

            reactome_dict: dict[str, str] = {}
            for pid, name in reactome:
                reactome_dict[name] = pid

            # If gene has both KEGG and Reactome, try to align rows
            # Otherwise emit separate rows
            kegg_names = sorted(kegg_all.keys())
            reactome_names = sorted(reactome_dict.keys())

            if not kegg_names and not reactome_names:
                # Gene with no pathway hits — still emit a row
                writer.writerow([
                    gene, "", "", "", "",
                    tox_evidence, tox_organs, "",
                ])
                rows_written += 1
                continue

            # Emit KEGG rows
            for name in kegg_names:
                pid, species = kegg_all[name]
                writer.writerow([
                    gene, pid, name, "", "",
                    tox_evidence, tox_organs, species,
                ])
                rows_written += 1

            # Emit Reactome rows
            for name in reactome_names:
                pid = reactome_dict[name]
                writer.writerow([
                    gene, "", "", pid, name,
                    tox_evidence, tox_organs, "human",
                ])
                rows_written += 1

    print(f"\n{'='*60}")
    print(f"PATHWAY ENRICHMENT COMPLETE")
    print(f"{'='*60}")
    print(f"Genes queried:        {len(genes)}")
    print(f"Genes with pathways:  {genes_with_pathways}")
    print(f"Rows written:         {rows_written}")
    print(f"Output:               {output_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    consensus_path = "citegraph_output/gene_consensus.json"
    output_path = "pathway_enrichment.tsv"

    for arg in sys.argv[1:]:
        if arg.endswith(".json"):
            consensus_path = arg
        elif arg.endswith(".tsv"):
            output_path = arg

    build_pathway_tsv(consensus_path=consensus_path, output_path=output_path)
