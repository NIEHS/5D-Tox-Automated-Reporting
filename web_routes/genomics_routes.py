"""
web_routes/genomics_routes.py — HTTP transport for the genomics visualization
helpers in genomics/genomics_viz.py.

Routes:
  POST /api/genomics-clusters            hierarchical clustering of GO categories
  POST /api/genomics-cluster-enrichment  Enrichr enrichment per cluster
  POST /api/genomics-chart-images        render chart PNGs for report embedding

MOVED 2026-09-18 out of genomics/genomics_viz.py, which had grown to mix
compute, plotting, offline-kaleido setup and three FastAPI handlers. The
handler bodies are unchanged; the compute they call (`enrich_clusters`,
`render_chart_images`, and the clustering helpers) stays in genomics_viz.
"""

import logging

import numpy as np
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from genomics.genomics_viz import enrich_clusters, render_chart_images

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# POST /api/genomics-clusters — hierarchical clustering of GO categories
# ---------------------------------------------------------------------------

@router.post("/api/genomics-clusters")
async def api_genomics_clusters(request: Request):
    """
    Cluster GO categories by gene-set overlap (Jaccard distance).

    Input JSON:
        {
            "categories": [
                {"go_id": "GO:0006629", "genes": "acox1;cyp2b1;..."},
                ...
            ],
            "linkage": "average"   // optional: average|complete|single|ward
        }

    Returns:
        {
            "clusters": {"GO:0006629": 0, "GO:0008150": 1, ...},
            "n_clusters": 5
        }

    Requires at least 3 categories with non-empty gene lists.
    Categories with empty gene lists are assigned cluster -1.
    """
    from scipy.cluster.hierarchy import linkage, fcluster
    from scipy.spatial.distance import squareform

    body = await request.json()
    categories = body.get("categories", [])
    linkage_method = body.get("linkage", "average")

    if linkage_method not in ("average", "complete", "single", "ward"):
        linkage_method = "average"

    # Parse gene sets — split semicolon-separated strings into sets
    parsed = []
    for cat in categories:
        go_id = cat.get("go_id", "")
        genes_str = cat.get("genes", "")
        gene_set = set(g.strip().lower() for g in genes_str.split(";") if g.strip())
        parsed.append({"go_id": go_id, "genes": gene_set})

    # Filter to categories with at least one gene
    valid = [p for p in parsed if len(p["genes"]) > 0]

    if len(valid) < 3:
        # Not enough categories for meaningful clustering — assign all to cluster 0
        result = {p["go_id"]: 0 for p in parsed}
        return JSONResponse({"clusters": result, "n_clusters": 1})

    n = len(valid)

    # Compute pairwise Jaccard distances.
    # Jaccard distance = 1 - |A ∩ B| / |A ∪ B|
    # This measures how dissimilar two gene sets are: 0 = identical,
    # 1 = completely disjoint.
    dist_matrix = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            a, b = valid[i]["genes"], valid[j]["genes"]
            intersection = len(a & b)
            union = len(a | b)
            jaccard_dist = 1.0 - (intersection / union) if union > 0 else 1.0
            dist_matrix[i, j] = jaccard_dist
            dist_matrix[j, i] = jaccard_dist

    # Convert to condensed form for scipy
    condensed = squareform(dist_matrix)

    # Ward linkage requires euclidean-like distances — use average for
    # Jaccard since it's a proper metric.
    if linkage_method == "ward":
        linkage_method = "average"

    # Run hierarchical clustering
    Z = linkage(condensed, method=linkage_method)

    # Cut the dendrogram to produce a reasonable number of clusters.
    # Use a distance threshold of 0.7 (categories sharing ≥30% of genes
    # are grouped together).  This typically yields 3-15 clusters for
    # the 20 GO categories we display.
    cluster_labels = fcluster(Z, t=0.7, criterion="distance")

    # Build result dict — assign valid categories their cluster IDs,
    # empty-gene categories get cluster -1
    result = {}
    valid_go_ids = {p["go_id"] for p in valid}
    for i, v in enumerate(valid):
        result[v["go_id"]] = int(cluster_labels[i]) - 1  # 0-indexed

    for p in parsed:
        if p["go_id"] not in valid_go_ids:
            result[p["go_id"]] = -1

    n_clusters = len(set(cluster_labels))

    return JSONResponse({"clusters": result, "n_clusters": n_clusters})


# ---------------------------------------------------------------------------
# POST /api/genomics-cluster-enrichment — Enrichr enrichment per cluster
# ---------------------------------------------------------------------------

@router.post("/api/genomics-cluster-enrichment")
async def api_genomics_cluster_enrichment(request: Request):
    """
    Run Enrichr enrichment analysis for each gene-overlap cluster.

    Pools unique genes per cluster, submits each to the Enrichr web service,
    and returns top enriched GO Biological Process terms per cluster.  This
    gives an independent, cross-validated description of what biology each
    horizontal band in the cluster scatter plot represents.

    Input JSON:
        {
            "gene_sets": [
                {"go_id": "GO:...", "genes": "acox1;cyp2b1;...", "bmd": 1.5, ...},
                ...
            ],
            "clusters": {"GO:...": 0, "GO:...": 1, ...}
        }

    Returns JSON:
        {
            "cluster_summary": [
                {
                    "cluster": "0",
                    "terms": ["SREBP Signaling Pathway (GO:0032933)", ...],
                    "adj_p_values": [0.0003, ...],
                    "n_genes": 10,
                    "n_categories": 4,
                    "source": "enrichr"
                },
                ...
            ]
        }
    """
    body = await request.json()
    gene_sets = body.get("gene_sets", [])
    clusters = body.get("clusters", {})
    # Optional: pre-computed all-caps symbol → "up"/"down" sent by the client
    # so cluster summary rows carry n_up/n_down without needing all_genes server-side.
    gene_dir: dict[str, str] | None = body.get("gene_dir") or None

    if not gene_sets or not clusters:
        return JSONResponse(
            {"error": "gene_sets and clusters are required"}, status_code=400
        )

    # Delegate to shared function — runs Enrichr per cluster with
    # automatic fallback to internal GO terms on failure.
    import asyncio
    from functools import partial
    loop = asyncio.get_running_loop()
    cluster_summary = await loop.run_in_executor(
        None,
        partial(enrich_clusters, gene_sets, clusters, gene_dir=gene_dir),
    )

    return JSONResponse({"cluster_summary": cluster_summary})


@router.post("/api/genomics-chart-images")
async def api_genomics_chart_images(request: Request):
    """
    Render the UMAP scatter and cluster scatter charts as PNG images.

    Thin wrapper around render_chart_images() for direct API calls.
    Used by the report export pipeline and for debugging.

    Input JSON:
        {
            "gene_sets": [...],
            "organ": "liver",
            "sex": "male",
            "dose_unit": "mg/kg",
            "clusters": {"GO:...": 0, ...}    // optional
        }

    Returns JSON:
        {
            "umap_png": "<base64>",
            "cluster_png": "<base64>",
            "umap_caption": "...",
            "cluster_caption": "..."
        }
    """
    body = await request.json()
    gene_sets = body.get("gene_sets", [])
    if not gene_sets:
        return JSONResponse({"error": "No gene_sets provided"}, status_code=400)

    try:
        result = render_chart_images(
            gene_sets=gene_sets,
            organ=body.get("organ", ""),
            sex=body.get("sex", ""),
            dose_unit=body.get("dose_unit", "mg/kg"),
            clusters=body.get("clusters"),
        )
        return JSONResponse(result)
    except Exception as e:
        logger.exception("Chart image rendering failed")
        return JSONResponse(
            {"error": f"Chart rendering failed: {e}"},
            status_code=500,
        )
