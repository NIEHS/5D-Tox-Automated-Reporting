"""
enrichr_client.py — Minimal client for the Enrichr REST API.

Enrichr (https://maayanlab.cloud/Enrichr) is a gene set enrichment analysis
web service from the Ma'ayan Lab at Mount Sinai.  This module wraps the
two-step workflow:

  1. POST /addList  — submit a gene list, receive a userListId
  2. GET  /enrich   — fetch enrichment results for that list against a library

No external dependencies — uses only Python stdlib (urllib, json, uuid).
Designed to be imported by genomics_viz.py for per-cluster enrichment of
the gene-overlap scatter plot.

Usage:
    from enrichr_client import enrichr_submit, enrichr_fetch, enrichr_enrich_genes

    # Low-level: submit then fetch
    list_id = enrichr_submit(["BRCA1", "TP53", ...], "my genes")
    terms   = enrichr_fetch(list_id, "GO_Biological_Process_2023")

    # High-level: one call, multiple libraries, parsed output
    result  = enrichr_enrich_genes(["BRCA1", "TP53"], libraries=[...], top_n=5)
"""

import json
import logging
import time
import urllib.parse
import urllib.request
import uuid

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Enrichr REST API base URL (Ma'ayan Lab, Mount Sinai)
ENRICHR_BASE = "https://maayanlab.cloud/Enrichr"

# Default library for cluster summaries — GO Biological Process is the most
# interpretable for a biology-audience summary table.  Additional libraries
# can be passed explicitly when richer context is needed.
DEFAULT_LIBRARY = "GO_Biological_Process_2023"

# Polite delay between consecutive API calls (seconds) to avoid rate limiting
# on the public Enrichr service.
API_DELAY = 0.3


# ---------------------------------------------------------------------------
# Low-level API calls
# ---------------------------------------------------------------------------

def enrichr_submit(gene_symbols: list[str], description: str) -> int:
    """
    Submit a gene list to Enrichr and return the userListId.

    Enrichr requires multipart/form-data with 'list' and 'description' fields.
    We build the multipart body manually since urllib has no native multipart
    support and we want zero external dependencies.

    Args:
        gene_symbols: List of uppercase gene symbols (e.g. ["BRCA1", "TP53"])
        description: Human-readable label for this gene list

    Returns:
        userListId (int) used to fetch enrichment results

    Raises:
        RuntimeError: if Enrichr rejects the submission
        urllib.error.URLError: on network failure
    """
    boundary = uuid.uuid4().hex

    # Build multipart body — two fields: 'list' and 'description'
    parts = []
    for field_name, field_value in [
        ("list", "\n".join(gene_symbols)),
        ("description", description),
    ]:
        parts.append(f"--{boundary}".encode())
        parts.append(
            f'Content-Disposition: form-data; name="{field_name}"'.encode()
        )
        parts.append(b"")  # blank line between headers and value
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

    return body["userListId"]


def enrichr_fetch(user_list_id: int, library: str) -> list[dict]:
    """
    Fetch enrichment results for a previously submitted gene list.

    Args:
        user_list_id: from enrichr_submit()
        library: Enrichr library name (e.g. "GO_Biological_Process_2023")

    Returns:
        List of term dicts, each with keys:
          rank, term, p_value, z_score, combined_score,
          genes (list[str]), adj_p_value

    Enrichr's raw response per term is a positional array:
      [rank, term_name, p_value, z_score, combined_score,
       overlapping_genes, adj_p_value, old_p_value, old_adj_p_value]
    We parse it into named dicts for clarity.
    """
    url = (
        f"{ENRICHR_BASE}/enrich"
        f"?userListId={user_list_id}"
        f"&backgroundType={urllib.parse.quote(library)}"
    )
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    raw_terms = body.get(library, [])

    parsed = []
    for row in raw_terms:
        parsed.append({
            "rank": row[0],
            "term": row[1],
            "p_value": row[2],
            "z_score": row[3],
            "combined_score": row[4],
            "genes": row[5],        # list of overlapping gene symbols
            "adj_p_value": row[6],
        })

    return parsed


# ---------------------------------------------------------------------------
# High-level: enrich a gene list against one or more libraries
# ---------------------------------------------------------------------------

def enrichr_enrich_genes(
    gene_symbols: list[str],
    description: str = "",
    libraries: list[str] | None = None,
    top_n: int = 5,
) -> dict:
    """
    Submit genes to Enrichr and return top enriched terms per library.

    This is the main entry point for callers that just want enrichment
    results without managing the two-step API flow themselves.

    Args:
        gene_symbols: Uppercase gene symbols
        description: Label for the Enrichr submission
        libraries: Which Enrichr libraries to query (default: GO BP 2023 only)
        top_n: How many top terms to keep per library (by combined score)

    Returns:
        Dict with keys:
          user_list_id: int
          results: {library_name: [top_n term dicts sorted by combined_score]}
    """
    if not gene_symbols:
        return {"user_list_id": None, "results": {}}

    if libraries is None:
        libraries = [DEFAULT_LIBRARY]

    # Step 1: submit gene list
    logger.info("Enrichr: submitting %d genes", len(gene_symbols))
    user_list_id = enrichr_submit(gene_symbols, description)
    logger.info("Enrichr: got userListId=%d", user_list_id)

    # Step 2: query each library
    results = {}
    for i, lib in enumerate(libraries):
        if i > 0:
            time.sleep(API_DELAY)

        logger.info("Enrichr: querying %s", lib)
        try:
            terms = enrichr_fetch(user_list_id, lib)
        except Exception as e:
            logger.warning("Enrichr: failed to query %s: %s", lib, e)
            results[lib] = []
            continue

        # Sort by combined score descending (higher = more significant),
        # keep top N
        terms.sort(key=lambda t: t["combined_score"], reverse=True)
        results[lib] = terms[:top_n]
        logger.info("Enrichr: %s → %d terms, keeping top %d",
                     lib, len(terms), min(top_n, len(terms)))

    return {
        "user_list_id": user_list_id,
        "results": results,
    }
