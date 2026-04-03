"""
enrichr_analysis.py — Call the Enrichr web service to run gene set enrichment
analysis on genes from a rlm-bmdx genomics session file.

Two-step workflow mirrors the Enrichr REST API:
  1. POST /addList  — submit a newline-separated gene list, get back a userListId
  2. GET  /enrich   — fetch enrichment results for that list against one or more
                       Enrichr gene-set libraries (e.g. GO_Biological_Process_2023)

The assembled data object is written to stdout as JSON so the caller can inspect
the shape before deciding what to do with it.

Usage:
    uv run enrichr_analysis.py [--session PATH] [--libraries LIB1,LIB2,...]

Defaults to the DTXSID50469320 kidney/female session and a curated set of
libraries relevant to toxicogenomics.
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.parse

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Enrichr REST API base URL (Ma'ayan Lab, Mount Sinai)
ENRICHR_BASE = "https://maayanlab.cloud/Enrichr"

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
# Enrichr API helpers
# ---------------------------------------------------------------------------

def enrichr_add_list(gene_symbols: list[str], description: str) -> dict:
    """
    Submit a gene list to Enrichr.  Returns the JSON response which includes
    'userListId' (int) and 'shortId' (str) — both needed for subsequent queries.

    Enrichr requires multipart/form-data with 'list' and 'description' fields.
    We build the multipart body manually since urllib has no native multipart
    support and we don't want to pull in requests as a dependency.
    """
    import uuid
    boundary = uuid.uuid4().hex

    # Build multipart body by hand — two fields: 'list' and 'description'
    parts = []
    for field_name, field_value in [
        ("list", "\n".join(gene_symbols)),
        ("description", description),
    ]:
        parts.append(f"--{boundary}".encode())
        parts.append(
            f'Content-Disposition: form-data; name="{field_name}"'.encode()
        )
        parts.append(b"")  # blank line separates headers from value
        parts.append(field_value.encode("utf-8"))
    parts.append(f"--{boundary}--".encode())

    payload = b"\r\n".join(parts)

    req = urllib.request.Request(
        f"{ENRICHR_BASE}/addList",
        data=payload,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    if "userListId" not in body:
        raise RuntimeError(f"Enrichr /addList failed: {body}")

    return body


def enrichr_enrich(user_list_id: int, library: str) -> list[list]:
    """
    Fetch enrichment results for a previously submitted gene list against a
    single Enrichr library.

    Returns a list of term rows.  Each row is a list:
        [rank, term_name, p_value, z_score, combined_score,
         overlapping_genes, adj_p_value, old_p_value, old_adj_p_value]
    """
    url = (
        f"{ENRICHR_BASE}/enrich"
        f"?userListId={user_list_id}"
        f"&backgroundType={urllib.parse.quote(library)}"
    )
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    # Response shape: { "LibraryName": [ [row], [row], ... ] }
    return body.get(library, [])


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
# Assemble enrichment analysis data object
# ---------------------------------------------------------------------------

def run_enrichment(
    gene_symbols: list[str],
    description: str,
    libraries: list[str],
    top_n: int = TOP_N,
) -> dict:
    """
    Run the full Enrichr workflow:
      1. Submit gene list
      2. Query each library
      3. Parse and rank results by combined score

    Returns a structured data object with all results.
    """
    # Step 1: submit gene list
    print(f"  Submitting {len(gene_symbols)} genes to Enrichr...", file=sys.stderr)
    add_resp = enrichr_add_list(gene_symbols, description)
    user_list_id = add_resp["userListId"]
    short_id = add_resp.get("shortId", "")
    print(
        f"  Got userListId={user_list_id}, shortId={short_id}",
        file=sys.stderr,
    )

    # Step 2: query each library
    library_results = {}
    for lib in libraries:
        print(f"  Querying library: {lib}...", file=sys.stderr)
        try:
            raw_terms = enrichr_enrich(user_list_id, lib)
        except Exception as e:
            print(f"    ERROR querying {lib}: {e}", file=sys.stderr)
            library_results[lib] = {"error": str(e), "terms": []}
            continue

        # Parse each term row into a readable dict and sort by combined score
        # descending (higher = more significant)
        parsed = []
        for row in raw_terms:
            parsed.append({
                "rank": row[0],
                "term": row[1],
                "p_value": row[2],
                "z_score": row[3],
                "combined_score": row[4],
                "genes": row[5],            # list of overlapping gene symbols
                "adj_p_value": row[6],
                "old_p_value": row[7],
                "old_adj_p_value": row[8],
            })

        # Sort by combined score descending, take top N
        parsed.sort(key=lambda t: t["combined_score"], reverse=True)
        top = parsed[:top_n]

        library_results[lib] = {
            "total_terms": len(parsed),
            "top_n": len(top),
            "terms": top,
        }
        print(
            f"    {len(parsed)} terms total, keeping top {len(top)}",
            file=sys.stderr,
        )

        # Be polite to the public API — small delay between requests
        time.sleep(0.3)

    # Step 3: assemble the final data object
    return {
        "enrichr_user_list_id": user_list_id,
        "enrichr_short_id": short_id,
        "enrichr_url": f"https://maayanlab.cloud/Enrichr/enrich?dataset={short_id}",
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
