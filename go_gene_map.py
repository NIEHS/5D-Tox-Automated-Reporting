"""
Build a GO term → gene member mapping and inner join with referenceUmapData.ts.

Merges rat and human GO annotations. Each gene is tagged with species:
  "rat"       — only in rat GAF
  "human"     — only in human GAF
  "rat | human" — in both (ortholog pair sharing the same GO annotation)

Cross-references with toxicogenomics consensus gene analysis.

Outputs a TSV: go_id, go_term, cluster_id, UMAP_1, UMAP_2, gene_symbol,
               species, rat_symbol, tox_evidence, tox_papers, tox_organs
"""

import csv
import json
import re
from collections import defaultdict


def parse_reference_umap(ts_path: str) -> list[dict]:
    """Parse the TypeScript file to extract GO term data."""
    with open(ts_path) as f:
        text = f.read()

    items = []
    pattern = re.compile(
        r'\{\s*'
        r'UMAP_1:\s*([-\d.]+),\s*'
        r'UMAP_2:\s*([-\d.]+),\s*'
        r'go_id:\s*"(GO:\d+)",\s*'
        r'go_term:\s*"([^"]+)",\s*'
        r'cluster_id:\s*([-\d]+|"[^"]+")'
        r'\s*\}',
        re.DOTALL
    )
    for m in pattern.finditer(text):
        cluster_raw = m.group(5).strip('"')
        items.append({
            "UMAP_1": float(m.group(1)),
            "UMAP_2": float(m.group(2)),
            "go_id": m.group(3),
            "go_term": m.group(4),
            "cluster_id": cluster_raw,
        })
    return items


def parse_gaf(gaf_path: str, aspect: str = "P") -> dict[str, set[str]]:
    """
    Parse a GAF file. Returns: {GO_ID: {gene_symbol, ...}}
    Filters to Biological Process (aspect="P") and excludes NOT qualifiers.
    """
    go_genes: dict[str, set[str]] = defaultdict(set)

    with open(gaf_path) as f:
        for line in f:
            if line.startswith("!"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 15:
                continue

            go_id = parts[4]
            gene_symbol = parts[2]
            line_aspect = parts[8]
            qualifier = parts[3]

            if aspect and line_aspect != aspect:
                continue
            if "NOT" in qualifier:
                continue

            go_genes[go_id].add(gene_symbol)

    return dict(go_genes)


def build_tox_lookup(
    extractions_path: str,
    consensus_path: str,
) -> dict[str, dict]:
    """
    Build a lookup: uppercase gene symbol → {evidence, papers, organs}

    Uses the normalized gene names from extract.py.
    evidence = "consensus" (3+), "moderate" (2), "single" (1)
    """
    # Load the consensus JSON for pre-categorized consensus/moderate genes
    with open(consensus_path) as f:
        consensus_data = json.load(f)

    lookup: dict[str, dict] = {}

    for gene, info in consensus_data["consensus_genes"].items():
        lookup[gene.upper()] = {
            "evidence": "consensus",
            "papers": info["count"],
            "organs": info["organs"],
        }

    for gene, info in consensus_data["moderate_evidence"].items():
        lookup[gene.upper()] = {
            "evidence": "moderate",
            "papers": info["count"],
            "organs": info["organs"],
        }

    # For single-mention genes, rebuild from extractions with normalization
    # Import the normalizer from extract.py
    import sys
    sys.path.insert(0, ".")
    from extract import normalize_gene, normalize_organ

    with open(extractions_path) as f:
        extractions = json.load(f)

    # Build full gene → paper count and organs from extractions
    gene_counts: dict[str, int] = defaultdict(int)
    gene_organs: dict[str, set] = defaultdict(set)

    for ext in extractions:
        organs = {normalize_organ(o) for o in ext.get("organs", [])}
        organs.discard("")
        for raw_gene in ext.get("genes", []):
            gene = normalize_gene(raw_gene)
            if not gene:
                continue
            gene_counts[gene] += 1
            gene_organs[gene].update(organs)

    # Add single-mention genes not already in lookup
    for gene, count in gene_counts.items():
        key = gene.upper()
        if key not in lookup and count == 1:
            lookup[key] = {
                "evidence": "single",
                "papers": 1,
                "organs": sorted(gene_organs.get(gene, set())),
            }

    return lookup


def build_tsv(
    ts_path: str,
    rat_gaf_path: str,
    human_gaf_path: str,
    output_path: str,
    tox_lookup: dict[str, dict] | None = None,
):
    """
    Inner join referenceUmapData GO terms with rat + human GAF annotations.
    A GO term is included if it has annotations in EITHER species.
    Gene symbols are uppercased for cross-species comparison.
    """

    print("Parsing referenceUmapData.ts...")
    umap_items = parse_reference_umap(ts_path)
    print(f"  Found {len(umap_items)} GO terms")

    print("Parsing rat GAF (Biological Process)...")
    rat_go = parse_gaf(rat_gaf_path, aspect="P")
    print(f"  Rat: {len(rat_go)} GO terms with annotations")

    print("Parsing human GAF (Biological Process)...")
    human_go = parse_gaf(human_gaf_path, aspect="P")
    print(f"  Human: {len(human_go)} GO terms with annotations")

    umap_go_ids = {item["go_id"] for item in umap_items}
    rat_go_ids = set(rat_go.keys())
    human_go_ids = set(human_go.keys())
    all_gaf_go_ids = rat_go_ids | human_go_ids
    overlap = umap_go_ids & all_gaf_go_ids

    print(f"\n  UMAP GO terms:       {len(umap_go_ids)}")
    print(f"  Rat GAF GO terms:    {len(rat_go_ids)}")
    print(f"  Human GAF GO terms:  {len(human_go_ids)}")
    print(f"  Inner join (either): {len(overlap)}")
    print(f"  Rat only join:       {len(umap_go_ids & rat_go_ids)}")
    print(f"  Human only join:     {len(umap_go_ids & human_go_ids)}")
    print(f"  Unmatched:           {len(umap_go_ids - all_gaf_go_ids)}")

    # For each GO term, merge genes from both species.
    # Uppercase gene symbols so we can detect shared orthologs.
    # Track which species each (go_id, gene_upper) pair comes from.

    row_count = 0
    tox_hits = 0
    species_counts = {"rat": 0, "human": 0, "rat | human": 0}

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow([
            "go_id", "go_term", "cluster_id", "UMAP_1", "UMAP_2",
            "gene_symbol", "species", "rat_symbol",
            "tox_evidence", "tox_papers", "tox_organs"
        ])

        for item in umap_items:
            go_id = item["go_id"]

            rat_genes_raw = rat_go.get(go_id, set())
            human_genes_raw = human_go.get(go_id, set())

            # Outer join: emit a row even if no genes found
            if not rat_genes_raw and not human_genes_raw:
                writer.writerow([
                    go_id,
                    item["go_term"],
                    item["cluster_id"],
                    f"{item['UMAP_1']:.6f}",
                    f"{item['UMAP_2']:.6f}",
                    "", "", "", "", "", "",
                ])
                row_count += 1
                continue

            # Build uppercased → species mapping
            rat_upper = {g.upper(): g for g in rat_genes_raw}
            human_upper = {g.upper() for g in human_genes_raw}
            all_genes_upper = set(rat_upper.keys()) | human_upper

            # Choose best-cased symbol: prefer human (standard HGNC uppercase)
            # then rat. Build a lookup: upper -> display symbol
            display = {}
            for g in rat_genes_raw:
                display[g.upper()] = g
            for g in human_genes_raw:
                # Human symbols overwrite rat since HGNC is the standard
                display[g.upper()] = g

            for gene_upper in sorted(all_genes_upper):
                in_rat = gene_upper in rat_upper
                in_human = gene_upper in human_upper

                if in_rat and in_human:
                    species = "rat | human"
                elif in_rat:
                    species = "rat"
                else:
                    species = "human"

                # rat_symbol: original rat GAF symbol for rat and rat|human rows
                rat_symbol = rat_upper.get(gene_upper, "")

                # Toxicogenomics cross-reference
                tox_evidence = ""
                tox_papers = ""
                tox_organs = ""
                if tox_lookup and gene_upper in tox_lookup:
                    tox = tox_lookup[gene_upper]
                    tox_evidence = tox["evidence"]
                    tox_papers = str(tox["papers"])
                    tox_organs = " | ".join(tox["organs"])
                    tox_hits += 1

                species_counts[species] += 1

                writer.writerow([
                    go_id,
                    item["go_term"],
                    item["cluster_id"],
                    f"{item['UMAP_1']:.6f}",
                    f"{item['UMAP_2']:.6f}",
                    display[gene_upper],
                    species,
                    rat_symbol,
                    tox_evidence,
                    tox_papers,
                    tox_organs,
                ])
                row_count += 1

    print(f"\nWrote {row_count} rows to {output_path}")
    print(f"  rat only:       {species_counts['rat']}")
    print(f"  human only:     {species_counts['human']}")
    print(f"  rat | human:    {species_counts['rat | human']}")
    if tox_lookup:
        print(f"  tox hits:       {tox_hits} rows matched a toxicogenomics gene")

    # Stats
    genes_per_term = []
    for item in umap_items:
        go_id = item["go_id"]
        n = len(rat_go.get(go_id, set())) + len(human_go.get(go_id, set()))
        if n > 0:
            genes_per_term.append(n)

    if genes_per_term:
        print(f"\n  Genes per GO term (combined): min={min(genes_per_term)}, "
              f"median={sorted(genes_per_term)[len(genes_per_term)//2]}, "
              f"max={max(genes_per_term)}, "
              f"mean={sum(genes_per_term)/len(genes_per_term):.1f}")


if __name__ == "__main__":
    ts_path = "/home/svobodadl/Dev/Projects/BMDExpress-Web-Edition/src/main/frontend/data/referenceUmapData.ts"
    rat_gaf = "/tmp/goa_rat.gaf"
    human_gaf = "/tmp/goa_human.gaf"
    extractions_path = "/home/svobodadl/AI/bmdx/citegraph_output_800/extractions.json"
    consensus_path = "/home/svobodadl/AI/bmdx/citegraph_output/gene_consensus.json"
    output_path = "/home/svobodadl/AI/bmdx/go_term_genes.tsv"

    print("Building toxicogenomics lookup...")
    tox_lookup = build_tox_lookup(extractions_path, consensus_path)
    print(f"  {len(tox_lookup)} genes in tox lookup")
    print(f"  Consensus: {sum(1 for v in tox_lookup.values() if v['evidence']=='consensus')}")
    print(f"  Moderate:  {sum(1 for v in tox_lookup.values() if v['evidence']=='moderate')}")
    print(f"  Single:    {sum(1 for v in tox_lookup.values() if v['evidence']=='single')}")
    print()

    build_tsv(ts_path, rat_gaf, human_gaf, output_path, tox_lookup=tox_lookup)
