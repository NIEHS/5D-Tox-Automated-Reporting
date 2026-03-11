"""
genomics_viz.py — Genomics visualization endpoints for 5dToxReport.

Provides:
  POST /api/genomics-clusters  — Hierarchical clustering of GO categories
                                  by Jaccard similarity of their gene sets.
  POST /api/genomics-charts    — Server-side Plotly chart rendering for
                                  UMAP scatter and cluster scatter plots,
                                  returned as PNG images for report embedding.

The clustering endpoint accepts a list of GO categories (each with a
semicolon-separated gene list) and returns cluster assignments computed
via scipy's agglomerative clustering on pairwise Jaccard distances.

The chart-rendering endpoint produces static PNG images using plotly.py
and kaleido, suitable for embedding in DOCX and PDF reports.
"""

import json
import logging
from pathlib import Path

import numpy as np
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Router — mounted by background_server.py
# ---------------------------------------------------------------------------
router = APIRouter()

# ---------------------------------------------------------------------------
# Reference UMAP data — loaded once at import time.
#
# Contains ~2,840 GO Biological Process terms with pre-computed UMAP
# coordinates and HDBSCAN cluster assignments.  Source: anc2vec
# embeddings projected via UMAP, clustered with HDBSCAN (min_cluster=40,
# min_samples=500).  Extracted from BMDExpress-Web-Edition.
# ---------------------------------------------------------------------------

_UMAP_REF_PATH = Path(__file__).parent / "web" / "data" / "umap_reference.json"
_UMAP_REF: list[dict] = []
# Lookup: go_id → {x, y, cluster}
_UMAP_LOOKUP: dict[str, dict] = {}


def _load_umap_reference():
    """Load the reference UMAP data from disk into module-level caches."""
    global _UMAP_REF, _UMAP_LOOKUP
    if _UMAP_REF:
        return  # Already loaded
    try:
        with open(_UMAP_REF_PATH) as f:
            _UMAP_REF = json.load(f)
        _UMAP_LOOKUP = {item["go_id"]: item for item in _UMAP_REF}
        logger.info("Loaded %d reference UMAP points", len(_UMAP_REF))
    except Exception:
        logger.exception("Failed to load UMAP reference data from %s", _UMAP_REF_PATH)


# Load eagerly so lookup is available for chart rendering
_load_umap_reference()


# ---------------------------------------------------------------------------
# Cluster color palette — 42 distinct colors for HDBSCAN clusters.
#
# Matches the palette from BMDExpress-Web-Edition so that cluster colors
# are visually consistent across applications.  Cluster -1 (outliers)
# gets a neutral gray.
# ---------------------------------------------------------------------------

_CLUSTER_COLORS = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
    "#42d4f4", "#f032e6", "#bfef45", "#fabed4", "#469990",
    "#dcbeff", "#9a6324", "#fffac8", "#800000", "#aaffc3",
    "#808000", "#ffd8b1", "#000075", "#a9a9a9", "#e6beff",
    "#1abc9c", "#2ecc71", "#3498db", "#9b59b6", "#e67e22",
    "#e74c3c", "#1a5276", "#7d3c98", "#2e86c1", "#a93226",
    "#196f3d", "#b9770e", "#5b2c6f", "#1b4f72", "#78281f",
    "#186a3b", "#7e5109", "#4a235a", "#154360", "#641e16",
    "#0e6251", "#7b7d7d",
]

_OUTLIER_COLOR = "#999999"


def get_cluster_color(cluster_id: int) -> str:
    """Return a hex color for a given HDBSCAN cluster ID."""
    if cluster_id < 0:
        return _OUTLIER_COLOR
    return _CLUSTER_COLORS[cluster_id % len(_CLUSTER_COLORS)]


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
# POST /api/genomics-chart-images — render chart PNGs for report embedding
# ---------------------------------------------------------------------------

@router.post("/api/genomics-chart-images")
async def api_genomics_chart_images(request: Request):
    """
    Render the UMAP scatter and cluster scatter charts as PNG images.

    Used by the DOCX and PDF export pipelines to embed static chart
    images into the report.  The charts are rendered server-side using
    plotly.py so they match the interactive frontend versions.

    Input JSON:
        {
            "gene_sets": [
                {"go_id": "GO:...", "go_term": "...", "bmd": 1.5,
                 "n_genes_with_bmd": 12, "direction": "up", "genes": "a;b;c"},
                ...
            ],
            "organ": "liver",
            "sex": "male",
            "dose_unit": "mg/kg",
            "clusters": {"GO:...": 0, ...}    // optional pre-computed clusters
        }

    Returns JSON:
        {
            "umap_png": "<base64-encoded PNG>",
            "cluster_png": "<base64-encoded PNG>",
            "umap_caption": "Figure N. ...",
            "cluster_caption": "Figure N. ..."
        }
    """
    import base64
    import plotly.graph_objects as go

    body = await request.json()
    gene_sets = body.get("gene_sets", [])
    organ = body.get("organ", "")
    sex = body.get("sex", "")
    dose_unit = body.get("dose_unit", "mg/kg")
    pre_clusters = body.get("clusters")

    if not gene_sets:
        return JSONResponse({"error": "No gene_sets provided"}, status_code=400)

    # Ensure reference data is loaded
    _load_umap_reference()

    organ_title = organ.capitalize() if organ else "Unknown"
    sex_title = sex.capitalize() if sex else ""

    # ── UMAP scatter plot ──────────────────────────────────────────────

    # Backdrop: all reference points (faded)
    ref_x = [p["x"] for p in _UMAP_REF]
    ref_y = [p["y"] for p in _UMAP_REF]

    fig_umap = go.Figure()

    fig_umap.add_trace(go.Scatter(
        x=ref_x, y=ref_y,
        mode="markers",
        marker=dict(size=3, color="#000000", opacity=0.15),
        name="Reference space",
        hoverinfo="skip",
        showlegend=True,
    ))

    # Analysis points: colored by HDBSCAN cluster
    # Group by cluster for separate legend entries
    analysis_by_cluster: dict[int, list] = {}
    for gs in gene_sets:
        go_id = gs.get("go_id", "")
        ref = _UMAP_LOOKUP.get(go_id)
        if not ref:
            continue
        cid = ref.get("cluster", -1)
        analysis_by_cluster.setdefault(cid, []).append({
            "x": ref["x"], "y": ref["y"],
            "go_id": go_id,
            "go_term": gs.get("go_term", ""),
            "bmd": gs.get("bmd"),
            "cluster": cid,
        })

    for cid in sorted(analysis_by_cluster.keys()):
        pts = analysis_by_cluster[cid]
        color = get_cluster_color(cid)
        name = f"Cluster {cid}" if cid >= 0 else "Outlier"
        fig_umap.add_trace(go.Scatter(
            x=[p["x"] for p in pts],
            y=[p["y"] for p in pts],
            mode="markers",
            marker=dict(size=9, color=color, opacity=0.85,
                        line=dict(width=0.5, color="#fff")),
            name=name,
            text=[f"{p['go_term']}<br>{p['go_id']}" for p in pts],
            hovertemplate="%{text}<extra></extra>",
        ))

    fig_umap.update_layout(
        width=1000, height=700,
        margin=dict(l=60, r=30, t=40, b=60),
        paper_bgcolor="#ffffff",
        plot_bgcolor="#fafafa",
        xaxis=dict(title="UMAP 1", showgrid=True, gridcolor="#e8e8e8", zeroline=False),
        yaxis=dict(title="UMAP 2", showgrid=True, gridcolor="#e8e8e8", zeroline=False),
        hovermode="closest",
        legend=dict(font=dict(size=10)),
    )

    # ── Cluster scatter plot ───────────────────────────────────────────

    # Get or compute cluster assignments
    if pre_clusters:
        clusters = pre_clusters
    else:
        # Compute inline (same logic as the /api/genomics-clusters endpoint)
        from scipy.cluster.hierarchy import linkage as _linkage, fcluster as _fcluster
        from scipy.spatial.distance import squareform as _squareform

        parsed_cats = []
        for gs in gene_sets:
            genes_str = gs.get("genes", "")
            gene_set = set(g.strip().lower() for g in genes_str.split(";") if g.strip())
            parsed_cats.append({"go_id": gs["go_id"], "genes": gene_set})

        valid_cats = [p for p in parsed_cats if len(p["genes"]) > 0]

        if len(valid_cats) < 3:
            clusters = {p["go_id"]: 0 for p in parsed_cats}
        else:
            nv = len(valid_cats)
            dm = np.zeros((nv, nv))
            for i in range(nv):
                for j in range(i + 1, nv):
                    a, b = valid_cats[i]["genes"], valid_cats[j]["genes"]
                    inter = len(a & b)
                    union = len(a | b)
                    dm[i, j] = dm[j, i] = 1.0 - (inter / union) if union > 0 else 1.0
            Z = _linkage(_squareform(dm), method="average")
            labels = _fcluster(Z, t=0.7, criterion="distance")
            clusters = {}
            for i, v in enumerate(valid_cats):
                clusters[v["go_id"]] = int(labels[i]) - 1
            for p in parsed_cats:
                if p["go_id"] not in clusters:
                    clusters[p["go_id"]] = -1

    # Build flat list of plottable points with both gene-overlap cluster
    # (y-axis position) and UMAP semantic cluster (color — same palette
    # as the UMAP scatter chart above).
    fig_cluster = go.Figure()
    all_points = []
    for gs in gene_sets:
        go_id = gs.get("go_id", "")
        bmd_val = gs.get("bmd")
        if bmd_val is None or not np.isfinite(float(bmd_val)):
            continue
        gene_cid = clusters.get(go_id, -1)
        n_genes = gs.get("n_genes_with_bmd", 0) or 0
        ref = _UMAP_LOOKUP.get(go_id)
        umap_cid = ref.get("cluster", -1) if ref else -1
        all_points.append({
            "go_id": go_id,
            "go_term": gs.get("go_term", ""),
            "bmd": float(bmd_val),
            "gene_cluster": gene_cid,
            "umap_cluster": umap_cid,
            "n_genes": n_genes,
            "direction": gs.get("direction", ""),
        })

    # Compute per-gene-cluster jitter offsets
    gene_cluster_counts: dict[int, int] = {}
    gene_cluster_index: dict[str, int] = {}
    for p in all_points:
        gene_cluster_counts[p["gene_cluster"]] = gene_cluster_counts.get(p["gene_cluster"], 0) + 1
        gene_cluster_index[p["go_id"]] = gene_cluster_counts[p["gene_cluster"]] - 1

    for p in all_points:
        gc = p["gene_cluster"]
        idx = gene_cluster_index[p["go_id"]]
        count = gene_cluster_counts[gc]
        spread = min(count, 10)
        p["y_jittered"] = gc + (idx / max(spread, 1) - 0.5) * 0.5

    # Group by UMAP semantic cluster for traces — each trace gets one
    # color, matching the UMAP scatter chart's legend exactly.
    by_umap_cluster: dict[int, list] = {}
    for p in all_points:
        by_umap_cluster.setdefault(p["umap_cluster"], []).append(p)

    sorted_umap_cids = sorted(by_umap_cluster.keys(), key=lambda c: (c == -1, c))

    for umap_cid in sorted_umap_cids:
        pts = by_umap_cluster[umap_cid]
        color = get_cluster_color(umap_cid)
        sizes = [max(6, min(30, p["n_genes"] * 0.5 + 5)) for p in pts]

        fig_cluster.add_trace(go.Scatter(
            x=[p["bmd"] for p in pts],
            y=[p["y_jittered"] for p in pts],
            mode="markers",
            marker=dict(size=sizes, color=color, opacity=0.8,
                        line=dict(width=0.5, color="#fff")),
            name=f"Cluster {umap_cid}" if umap_cid >= 0 else "Outlier",
            text=[f"{p['go_term']}<br>BMD: {p['bmd']:.3g} {dose_unit}<br>"
                  f"Genes: {p['n_genes']}<br>Direction: {p['direction']}<br>"
                  f"Semantic cluster: {p['umap_cluster']}"
                  for p in pts],
            hovertemplate="%{text}<extra></extra>",
        ))

    # Determine chart height based on number of gene-overlap clusters
    unique_gene_clusters = set(p["gene_cluster"] for p in all_points)
    n_gene_clusters = len(unique_gene_clusters) if all_points else 1
    chart_height = max(400, n_gene_clusters * 80 + 150)

    fig_cluster.update_layout(
        width=1000, height=chart_height,
        margin=dict(l=80, r=30, t=40, b=60),
        paper_bgcolor="#ffffff",
        plot_bgcolor="#fafafa",
        xaxis=dict(title=f"BMD ({dose_unit})", type="log",
                   showgrid=True, gridcolor="#e8e8e8"),
        yaxis=dict(title="Gene-Overlap Cluster", showgrid=True,
                   gridcolor="#e8e8e8", dtick=1),
        hovermode="closest",
        legend=dict(font=dict(size=10)),
    )

    # ── Render to PNG ──────────────────────────────────────────────────
    try:
        umap_bytes = fig_umap.to_image(format="png", scale=2)
        cluster_bytes = fig_cluster.to_image(format="png", scale=2)
    except Exception as e:
        logger.exception("Chart image rendering failed")
        return JSONResponse(
            {"error": f"Chart rendering failed: {e}"},
            status_code=500,
        )

    umap_b64 = base64.b64encode(umap_bytes).decode()
    cluster_b64 = base64.b64encode(cluster_bytes).decode()

    umap_caption = (
        f"GO Biological Process categories from the {organ_title} ({sex_title}) "
        f"gene expression analysis projected onto a pre-computed UMAP embedding "
        f"of GO BP terms. Points are colored by HDBSCAN semantic cluster."
    )
    cluster_caption = (
        f"GO Biological Process categories from the {organ_title} ({sex_title}) "
        f"analysis plotted by BMD value (x-axis, log scale) against hierarchical "
        f"gene-overlap cluster assignment (y-axis). Marker size reflects the number "
        f"of genes with BMD values in each category. Points are colored by UMAP "
        f"semantic cluster (same palette as the semantic map above). Categories "
        f"are clustered on the y-axis by Jaccard similarity of their gene sets."
    )

    return JSONResponse({
        "umap_png": umap_b64,
        "cluster_png": cluster_b64,
        "umap_caption": umap_caption,
        "cluster_caption": cluster_caption,
    })
