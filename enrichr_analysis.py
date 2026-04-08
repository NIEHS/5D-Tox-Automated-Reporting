"""
enrichr_analysis.py — CLI tool for running Enrichr enrichment analysis on
genes from a rlm-bmdx genomics session file.

Standalone script for ad-hoc exploration.  Uses enrichr_client.py for the
actual API calls — this file only handles CLI argument parsing, session
file reading, and output formatting.

Usage:
    uv run enrichr_analysis.py [--session PATH] [--libraries LIB1,LIB2,...]

Defaults to the DTXSID50469320 kidney/female session and a curated set of
libraries relevant to toxicogenomics.
"""

import argparse
import json
import sys
import time

from enrichr_client import enrichr_submit, enrichr_fetch, API_DELAY

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Default gene-set libraries to query — chosen for toxicogenomics relevance.
# Full catalog: https://maayanlab.cloud/Enrichr/#libraries
DEFAULT_LIBRARIES = [
    "GO_Biological_Process_2023",
    "GO_Molecular_Function_2023",
    "GO_Cellular_Component_2023",
    "KEGG_2021_Human",
    "Reactome_2022",
    "WikiPathway_2023_Human",
    "MSigDB_Hallmark_2020",
]

# How many top terms to keep per library (by combined score)
TOP_N = 20


# ---------------------------------------------------------------------------
# Gene list extraction from genomics session JSON
# ---------------------------------------------------------------------------

def extract_genes(session_path: str) -> tuple[list[str], dict]:
    """
    Read a genomics session JSON and return:
      - a sorted list of unique uppercase gene symbols
      - the session metadata (organ, sex, total_responsive_genes)
    """
    with open(session_path) as f:
        data = json.load(f)

    genes = set()

    # Genes from GO-category gene sets (semicolon-separated, lowercase)
    for gs in data.get("gene_sets", []):
        for g in gs.get("genes", "").split(";"):
            g = g.strip()
            if g:
                genes.add(g.upper())

    # Genes from top individual genes list
    for tg in data.get("top_genes", []):
        sym = tg.get("gene_symbol", "").strip()
        if sym:
            genes.add(sym.upper())

    meta = {
        "organ": data.get("organ"),
        "sex": data.get("sex"),
        "total_responsive_genes": data.get("total_responsive_genes"),
        "n_gene_sets": len(data.get("gene_sets", [])),
        "n_top_genes": len(data.get("top_genes", [])),
    }

    return sorted(genes), meta


# ---------------------------------------------------------------------------
# Run enrichment against multiple libraries
# ---------------------------------------------------------------------------

def run_enrichment(
    gene_symbols: list[str],
    description: str,
    libraries: list[str],
    top_n: int = TOP_N,
) -> dict:
    """
    Run the full Enrichr workflow using enrichr_client.py:
      1. Submit gene list via enrichr_submit()
      2. Query each library via enrichr_fetch()
      3. Parse and rank results by combined score

    Returns a structured data object with all results, including the
    Enrichr viewer URL for interactive exploration.
    """
    # Step 1: submit gene list
    print(f"  Submitting {len(gene_symbols)} genes to Enrichr...", file=sys.stderr)
    user_list_id = enrichr_submit(gene_symbols, description)
    print(f"  Got userListId={user_list_id}", file=sys.stderr)

    # Step 2: query each library
    library_results = {}
    for i, lib in enumerate(libraries):
        if i > 0:
            time.sleep(API_DELAY)

        print(f"  Querying library: {lib}...", file=sys.stderr)
        try:
            # enrichr_fetch returns parsed dicts, not raw arrays
            terms = enrichr_fetch(user_list_id, lib)
        except Exception as e:
            print(f"    ERROR querying {lib}: {e}", file=sys.stderr)
            library_results[lib] = {"error": str(e), "terms": []}
            continue

        # Sort by combined score descending, take top N
        terms.sort(key=lambda t: t["combined_score"], reverse=True)
        top = terms[:top_n]

        library_results[lib] = {
            "total_terms": len(terms),
            "top_n": len(top),
            "terms": top,
        }
        print(
            f"    {len(terms)} terms total, keeping top {len(top)}",
            file=sys.stderr,
        )

    # Step 3: assemble the final data object
    return {
        "enrichr_user_list_id": user_list_id,
        "enrichr_url": f"https://maayanlab.cloud/Enrichr/enrich?userListId={user_list_id}",
        "input_genes": gene_symbols,
        "n_input_genes": len(gene_symbols),
        "libraries_queried": libraries,
        "results": library_results,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Run Enrichr enrichment analysis on rlm-bmdx genomics genes"
    )
    parser.add_argument(
        "--session",
        default="sessions/DTXSID50469320/genomics_kidney_female.json",
        help="Path to a genomics session JSON file",
    )
    parser.add_argument(
        "--libraries",
        default=",".join(DEFAULT_LIBRARIES),
        help="Comma-separated Enrichr library names",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=TOP_N,
        help=f"Number of top terms to keep per library (default {TOP_N})",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output file path (default: stdout)",
    )
    args = parser.parse_args()

    libraries = [lib.strip() for lib in args.libraries.split(",")]

    # Extract genes from session
    print(f"Reading session: {args.session}", file=sys.stderr)
    gene_symbols, meta = extract_genes(args.session)
    print(
        f"  {meta['organ']}/{meta['sex']}: {len(gene_symbols)} unique genes "
        f"(from {meta['n_gene_sets']} GO sets + {meta['n_top_genes']} top genes; "
        f"{meta['total_responsive_genes']} total responsive)",
        file=sys.stderr,
    )

    description = (
        f"rlm-bmdx {meta['organ']} {meta['sex']} — "
        f"{len(gene_symbols)} genes from genomics BMD analysis"
    )

    # Run enrichment
    result = run_enrichment(gene_symbols, description, libraries, args.top_n)

    # Attach session metadata
    result["session"] = {
        "source_file": args.session,
        **meta,
    }

    # Output
    output_json = json.dumps(result, indent=2)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output_json)
        print(f"\nWrote results to {args.output}", file=sys.stderr)
    else:
        print(output_json)

    print("\nDone.", file=sys.stderr)


if __name__ == "__main__":
    main()
