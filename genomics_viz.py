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

import chart_registry
import chart_style

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


# ---------------------------------------------------------------------------
# SVG ID namespacing
# ---------------------------------------------------------------------------
# Plotly's SVG export uses auto-generated IDs like `clip0`, `defs1`,
# `legend0` that are unique only within a single <svg> instance.  When
# we inline multiple SVGs into the same HTML page (one pair per organ
# × sex), these IDs collide: the browser resolves `url(#clip0)` to
# whichever definition was last added, and every chart ends up using
# that single clip-path.  Symptoms: all analysis points vanish, or all
# charts render with the wrong legend.
#
# Fix: rewrite every `id="..."`, `url(#...)`, `href="#..."`, and
# `xlink:href="#..."` in the SVG to carry a unique prefix per render.
# Done with a small, permissive regex — sufficient because we only
# ever consume Plotly's own SVG output, whose IDs are always simple
# alphanumerics.

import re as _re

# Matches any `xxx="some-id"` attribute where xxx is one of the
# identifier-bearing attributes.  Capture group 1 is the attribute
# name + `="`, group 2 is the ID itself, group 3 is the closing `"`.
_SVG_ID_ATTR = _re.compile(
    r'((?:id|xlink:href|href|clip-path|mask|filter)=")'
    r'(#?)'
    r'([A-Za-z_][\w\-:.]*)'
    r'(")'
)
# The `url(#xxx)` form used inside style attributes and fill/stroke
# values.  Capture group 1 is the leading `url(#`, 2 the id, 3 `)`.
_SVG_URL_REF = _re.compile(r'(url\(#)([A-Za-z_][\w\-:.]*)(\))')


def _namespace_svg_ids(svg: str, prefix: str) -> str:
    """
    Rewrite every ID reference in a Plotly SVG so it carries a unique
    prefix.  Lets multiple SVGs coexist in the same DOM without clip-
    path / mask / filter definitions stomping on each other.

    Only Plotly-style auto-generated IDs need rewriting, so we keep
    the regex permissive rather than parsing the SVG.  The prefix is
    typically "u-liver-male" or "c-kidney-female" so IDs become
    "u-liver-male-clip0", etc.
    """
    def _attr_sub(m):
        # Rewrite only when the ID isn't already namespaced.
        attr, hash_sign, ident, close = m.group(1), m.group(2), m.group(3), m.group(4)
        return f'{attr}{hash_sign}{prefix}-{ident}{close}'

    def _url_sub(m):
        return f'{m.group(1)}{prefix}-{m.group(2)}{m.group(3)}'

    out = _SVG_ID_ATTR.sub(_attr_sub, svg)
    out = _SVG_URL_REF.sub(_url_sub, out)
    return out


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


def get_cluster_color(
    cluster_id: int,
    palette: list[str] | None = None,
    outlier: str | None = None,
) -> str:
    """Return a hex color for a given HDBSCAN cluster ID.

    ``palette``/``outlier`` override the module-global defaults so a configured
    per-chart palette (WP-1/WP-3) can be threaded in.  Both default to the
    module globals, so existing callers — including the enrichment endpoints
    (api_genomics_clusters / api_genomics_cluster_enrichment) — are unaffected.
    """
    pal = palette if palette else _CLUSTER_COLORS
    out = outlier if outlier else _OUTLIER_COLOR
    if cluster_id < 0:
        return out
    return pal[cluster_id % len(pal)]


# ---------------------------------------------------------------------------
# Shared cluster enrichment logic
# ---------------------------------------------------------------------------
# Used by both render_chart_images() (for PDF/DOCX) and the
# /api/genomics-cluster-enrichment endpoint (for the web UI).
# Ensures both paths produce identical results from the same inputs.

def enrich_clusters(
    gene_sets: list[dict],
    clusters: dict[str, int],
    top_n: int = 5,
    gene_dir: dict[str, str] | None = None,
) -> list[dict]:
    """
    For each gene-overlap cluster, pool unique genes and run Enrichr
    enrichment.  Returns a list of cluster summary dicts ordered by
    y-axis rank (top of chart first, outlier last).

    Each gene_set dict must have: go_id, go_term, genes (semicolon-separated),
    bmd (float).  The clusters dict maps go_id → cluster_id (int).

    Falls back to listing our own GO terms if Enrichr is unreachable or
    a cluster has fewer than 3 genes.

    Args:
        gene_sets: GO category dicts with go_id, go_term, genes, bmd
        clusters:  go_id → cluster_id mapping
        top_n:     How many Enrichr terms to keep per cluster
        gene_dir:  Optional all-caps symbol → "up"/"down" map.  When
                   provided, each cluster row gains n_up/n_down counts
                   (same pattern as the GO BP BMD table rows).

    Returns:
        List of dicts, each with keys:
          cluster (str), terms (list[str]), n_genes (int),
          n_categories (int), source ("enrichr" | "internal"),
          adj_p_values (list[float], only when source="enrichr"),
          n_up (int, when gene_dir provided), n_down (int, when gene_dir provided)
    """
    # Normalise once so the inner helpers don't need to repeat it.
    _gene_dir: dict[str, str] = gene_dir or {}
    # Build go_id → gene set lookup
    go_id_to_genes: dict[str, set[str]] = {}
    for gs in gene_sets:
        genes_str = gs.get("genes", "")
        gene_set = set(
            g.strip().upper() for g in genes_str.split(";") if g.strip()
        )
        go_id_to_genes[gs.get("go_id", "")] = gene_set

    # Group gene_sets by cluster
    by_cluster: dict[int, list] = {}
    for gs in gene_sets:
        go_id = gs.get("go_id", "")
        cid = clusters.get(go_id, -1)
        by_cluster.setdefault(cid, []).append(gs)

    # Compute cluster min BMD for y-axis ordering (same logic as charts)
    cluster_min_bmd: dict[int, float] = {}
    for cid, gs_list in by_cluster.items():
        for gs in gs_list:
            bmd = gs.get("bmd")
            if bmd is not None:
                bmd_f = float(bmd)
                if cid not in cluster_min_bmd or bmd_f < cluster_min_bmd[cid]:
                    cluster_min_bmd[cid] = bmd_f

    # Rank: lowest min-BMD at top (highest y), outlier pinned to bottom
    non_outlier = sorted(
        (c for c in cluster_min_bmd if c != -1),
        key=lambda c: cluster_min_bmd[c],
    )
    cluster_y_rank: dict[int, int] = {}
    for rank, c in enumerate(non_outlier):
        cluster_y_rank[c] = len(non_outlier) - rank
    cluster_y_rank[-1] = 0

    ranked_clusters = sorted(
        cluster_y_rank.keys(),
        key=lambda c: cluster_y_rank[c],
        reverse=True,
    )

    # Build internal-terms fallback for a cluster
    def _internal_summary(cid: int, gs_list: list, cluster_genes: set) -> dict:
        label = "Outlier" if cid == -1 else str(cid)
        sorted_gs = sorted(gs_list, key=lambda g: float(g.get("bmd", 999)))
        row: dict = {
            "cluster": label,
            "terms": [g.get("go_term", "") for g in sorted_gs[:top_n]],
            "n_genes": len(cluster_genes),
            "n_categories": len(gs_list),
            "source": "internal",
        }
        if _gene_dir:
            row["n_up"]   = sum(1 for s in cluster_genes if _gene_dir.get(s) == "up")
            row["n_down"] = sum(1 for s in cluster_genes if _gene_dir.get(s) == "down")
        return row

    # Attempt Enrichr enrichment per cluster
    cluster_summary = []
    try:
        from enrichr_client import enrichr_enrich_genes

        for cid in ranked_clusters:
            gs_list = by_cluster.get(cid, [])

            # Pool unique genes across all GO categories in this cluster
            cluster_genes = set()
            for gs in gs_list:
                cluster_genes |= go_id_to_genes.get(gs.get("go_id", ""), set())

            label = "Outlier" if cid == -1 else str(cid)

            # Need at least 3 genes for meaningful enrichment
            if len(cluster_genes) < 3:
                cluster_summary.append(_internal_summary(cid, gs_list, cluster_genes))
                continue

            desc = f"Cluster {label} — {len(cluster_genes)} genes"
            enrichment = enrichr_enrich_genes(
                list(cluster_genes), description=desc, top_n=top_n,
            )

            # Extract top Enrichr terms from the default library results
            lib_results = list(enrichment.get("results", {}).values())
            top_terms = lib_results[0] if lib_results else []

            if top_terms:
                row: dict = {
                    "cluster": label,
                    "terms": [t["term"] for t in top_terms],
                    "adj_p_values": [t["adj_p_value"] for t in top_terms],
                    "n_genes": len(cluster_genes),
                    "n_categories": len(gs_list),
                    "source": "enrichr",
                }
                if _gene_dir:
                    row["n_up"]   = sum(1 for s in cluster_genes if _gene_dir.get(s) == "up")
                    row["n_down"] = sum(1 for s in cluster_genes if _gene_dir.get(s) == "down")
                cluster_summary.append(row)
            else:
                cluster_summary.append(_internal_summary(cid, gs_list, cluster_genes))

    except Exception as e:
        # Enrichr unavailable — fall back entirely to internal GO terms
        logger.warning("Enrichr enrichment failed, using internal terms: %s", e)
        cluster_summary = []
        for cid in ranked_clusters:
            gs_list = by_cluster.get(cid, [])
            cluster_genes = set()
            for gs in gs_list:
                cluster_genes |= go_id_to_genes.get(gs.get("go_id", ""), set())
            cluster_summary.append(_internal_summary(cid, gs_list, cluster_genes))

    return cluster_summary


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


# ---------------------------------------------------------------------------
# POST /api/genomics-chart-images — render chart PNGs for report embedding
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Built-in chart-type style defaults (layer 0)
# ---------------------------------------------------------------------------
# These reproduce TODAY's hardcoded literals exactly.  chart_style.resolve_
# chart_style merges them under the document config's chart_style block; with no
# config the resolved style equals these, so the render is byte-identical to the
# pre-feature code.  Per-type because umap and cluster legitimately differ
# (width 900 vs 1000, legend font 9 vs 12, margins, etc.).
UMAP_STYLE_DEFAULTS: dict = {
    "width": 900,
    "height": 900,
    "paper_bgcolor": "#ffffff",
    "plot_bgcolor": "#fafafa",
    "gridcolor": "#e8e8e8",
    "palette": list(_CLUSTER_COLORS),
    "outlier_color": _OUTLIER_COLOR,
    "marker": {"size": 9, "opacity": 0.85, "line_width": 0.5, "line_color": "#fff"},
    "legend": {
        "font_size": 9,
        "bgcolor": "rgba(255,255,255,0.8)",
        "bordercolor": "#ccc",
        "borderwidth": 1,
    },
    "margins": {"l": 20, "r": 20, "t": 20, "b": 20},
    "xaxis": {"title": "", "type": ""},
    "yaxis": {"title": ""},
}

# Note: no "height" key — the cluster chart's height is computed from the number
# of gene-overlap clusters, so it must stay dynamic unless a config explicitly
# overrides it.  No xaxis.title either — it carries the dose unit and is built
# per render (f"BMD ({dose_unit})").
CLUSTER_STYLE_DEFAULTS: dict = {
    "width": 1000,
    "paper_bgcolor": "#ffffff",
    "plot_bgcolor": "#fafafa",
    "gridcolor": "#e8e8e8",
    "palette": list(_CLUSTER_COLORS),
    "outlier_color": _OUTLIER_COLOR,
    "marker": {"opacity": 0.8, "line_width": 0.5, "line_color": "#fff"},
    "legend": {"font_size": 12},
    "margins": {"l": 80, "r": 30, "t": 90, "b": 60},
    "xaxis": {"type": "log"},
    "yaxis": {"title": "Gene-Overlap Cluster"},
}

UMAP_CAPTION_TEMPLATE = (
    "GO Biological Process categories from the {organ_title} ({sex_title}) "
    "gene expression analysis projected onto a pre-computed UMAP embedding "
    "of GO BP terms. Points are colored by HDBSCAN semantic cluster."
)
CLUSTER_CAPTION_TEMPLATE = (
    "GO Biological Process categories from the {organ_title} ({sex_title}) "
    "analysis plotted by BMD value (x-axis, log scale) against hierarchical "
    "gene-overlap cluster assignment (y-axis). Marker size reflects the number "
    "of genes with BMD values in each category. Points are colored by UMAP "
    "semantic cluster (same palette as the semantic map above). Categories "
    "are clustered on the y-axis by Jaccard similarity of their gene sets."
)

# Per-type SVG id-namespacing prefix (keeps umap/cluster output byte-identical:
# the pre-feature code used "u-"/"c-").  Unknown types fall back to their full
# name, which is still unique across types.
_SVG_PREFIX: dict[str, str] = {"umap": "u", "cluster": "c"}


def _compute_gene_overlap_clusters(gene_sets: list[dict]) -> dict[str, int]:
    """
    Gene-overlap clustering of GO categories (same logic as the
    /api/genomics-clusters endpoint): agglomerative clustering on pairwise
    Jaccard distance of gene sets, threshold 0.7.  Returns ``go_id → cluster_id``
    (outliers / empty gene sets get -1).  Extracted verbatim from the old inline
    block so the cluster figure builder and the enrichment summary share one
    deterministic assignment.
    """
    from scipy.cluster.hierarchy import linkage as _linkage, fcluster as _fcluster
    from scipy.spatial.distance import squareform as _squareform

    parsed_cats = []
    for gs in gene_sets:
        genes_str = gs.get("genes", "")
        gene_set = set(g.strip().lower() for g in genes_str.split(";") if g.strip())
        parsed_cats.append({"go_id": gs["go_id"], "genes": gene_set})

    valid_cats = [p for p in parsed_cats if len(p["genes"]) > 0]

    if len(valid_cats) < 3:
        return {p["go_id"]: 0 for p in parsed_cats}

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
    clusters: dict[str, int] = {}
    for i, v in enumerate(valid_cats):
        clusters[v["go_id"]] = int(labels[i]) - 1
    for p in parsed_cats:
        if p["go_id"] not in clusters:
            clusters[p["go_id"]] = -1
    return clusters


# ---------------------------------------------------------------------------
# Code-registered figure builders (contract C4)
# ---------------------------------------------------------------------------
# Each returns a plotly go.Figure; rasterization + SVG-ID namespacing happen
# once in the dispatcher (render_chart_images).  Every styled literal now reads
# from the resolved ``style`` dict with the today-value as the fallback, so with
# no config (style == that type's *_STYLE_DEFAULTS) the figure is unchanged.


def build_umap_figure(
    gene_sets: list[dict],
    *,
    organ: str,
    sex: str,
    dose_unit: str = "mg/kg",
    style: dict | None = None,
    clusters: dict | None = None,
    umap_ref: list[dict] | None = None,
    umap_lookup: dict[str, dict] | None = None,
) -> "object":
    """UMAP semantic-map scatter (contract C4).  GO categories projected onto a
    precomputed UMAP embedding, colored by HDBSCAN semantic cluster."""
    import plotly.graph_objects as go

    style = style or {}
    ref_data = umap_ref if umap_ref is not None else _UMAP_REF
    lookup = umap_lookup if umap_lookup is not None else _UMAP_LOOKUP

    palette = style.get("palette")
    outlier = style.get("outlier_color")
    mk = style.get("marker") or {}
    msize = mk.get("size", 9)
    mopac = mk.get("opacity", 0.85)
    mlw = mk.get("line_width", 0.5)
    mlc = mk.get("line_color", "#fff")

    # Backdrop: all reference points (faded)
    ref_x = [p["x"] for p in ref_data]
    ref_y = [p["y"] for p in ref_data]

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
        ref = lookup.get(go_id)
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
        color = get_cluster_color(cid, palette=palette, outlier=outlier)
        name = f"Cluster {cid}" if cid >= 0 else "Outlier"
        fig_umap.add_trace(go.Scatter(
            x=[p["x"] for p in pts],
            y=[p["y"] for p in pts],
            mode="markers",
            marker=dict(size=msize, color=color, opacity=mopac,
                        line=dict(width=mlw, color=mlc)),
            name=name,
            text=[f"{p['go_term']}<br>{p['go_id']}" for p in pts],
            hovertemplate="%{text}<extra></extra>",
        ))

    # Compute a shared axis range so the plot is square in data space.
    # Pad by 5% so edge points aren't clipped by markers.
    all_x = ref_x + [p["x"] for pts in analysis_by_cluster.values() for p in pts]
    all_y = ref_y + [p["y"] for pts in analysis_by_cluster.values() for p in pts]
    lo = min(min(all_x), min(all_y))
    hi = max(max(all_x), max(all_y))
    pad = (hi - lo) * 0.05
    axis_range = [lo - pad, hi + pad]

    mg = style.get("margins") or {}
    grid = style.get("gridcolor", "#e8e8e8")
    xa = style.get("xaxis") or {}
    ya = style.get("yaxis") or {}
    leg = style.get("legend") or {}
    xtitle = (xa.get("title", "") or "").replace("${dose_unit}", dose_unit)
    ytitle = (ya.get("title", "") or "").replace("${dose_unit}", dose_unit)

    fig_umap.update_layout(
        # Square aspect ratio — same pixel width and height
        width=style.get("width", 900), height=style.get("height", 900),
        margin=dict(l=mg.get("l", 20), r=mg.get("r", 20),
                    t=mg.get("t", 20), b=mg.get("b", 20)),
        paper_bgcolor=style.get("paper_bgcolor", "#ffffff"),
        plot_bgcolor=style.get("plot_bgcolor", "#fafafa"),
        # No axis titles, tick labels, or tick marks — UMAP coordinates
        # are arbitrary and labels would just be noise.
        xaxis=dict(
            showgrid=True, gridcolor=grid, zeroline=False,
            showticklabels=False, title=xtitle,
            range=axis_range, scaleanchor="y", scaleratio=1,
        ),
        yaxis=dict(
            showgrid=True, gridcolor=grid, zeroline=False,
            showticklabels=False, title=ytitle,
            range=axis_range,
        ),
        hovermode="closest",
        # Legend inside the plot area, top-right corner with a
        # semi-transparent background so it doesn't obscure markers.
        legend=dict(
            font=dict(size=leg.get("font_size", 9)),
            x=1, y=1,
            xanchor="right", yanchor="top",
            bgcolor=leg.get("bgcolor", "rgba(255,255,255,0.8)"),
            bordercolor=leg.get("bordercolor", "#ccc"),
            borderwidth=leg.get("borderwidth", 1),
        ),
    )
    return fig_umap


def build_cluster_figure(
    gene_sets: list[dict],
    *,
    organ: str,
    sex: str,
    dose_unit: str = "mg/kg",
    style: dict | None = None,
    clusters: dict | None = None,
    umap_ref: list[dict] | None = None,
    umap_lookup: dict[str, dict] | None = None,
) -> "object":
    """BMD × gene-overlap-cluster scatter (contract C4).  Points colored by UMAP
    semantic cluster (same palette as the UMAP map); y-axis ranks gene-overlap
    clusters by minimum BMD; marker size reflects gene count."""
    import plotly.graph_objects as go

    style = style or {}
    lookup = umap_lookup if umap_lookup is not None else _UMAP_LOOKUP

    palette = style.get("palette")
    outlier = style.get("outlier_color")
    mk = style.get("marker") or {}
    mopac = mk.get("opacity", 0.8)
    mlw = mk.get("line_width", 0.5)
    mlc = mk.get("line_color", "#fff")

    # Get or compute cluster assignments
    if not clusters:
        clusters = _compute_gene_overlap_clusters(gene_sets)

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
        ref = lookup.get(go_id)
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

    # --- Compute y-axis positions based on cluster minimum BMD ---
    # Clusters are ordered vertically by their minimum BMD value:
    # lowest min-BMD at the top (highest y), descending downward.
    # The outlier cluster (-1) is always pinned to the bottom.

    # Step 1: find the minimum BMD per gene-overlap cluster
    cluster_min_bmd: dict[int, float] = {}
    for p in all_points:
        gc = p["gene_cluster"]
        if gc not in cluster_min_bmd or p["bmd"] < cluster_min_bmd[gc]:
            cluster_min_bmd[gc] = p["bmd"]

    # Step 2: rank non-outlier clusters by min BMD ascending —
    # then reverse so lowest min-BMD gets the highest y-position (top).
    non_outlier = sorted(
        (gc for gc in cluster_min_bmd if gc != -1),
        key=lambda gc: cluster_min_bmd[gc],
    )
    # Assign y-positions: top of chart = len(non_outlier), descending.
    # Outlier cluster gets y=0 (bottom).
    cluster_y_rank: dict[int, int] = {}
    for rank, gc in enumerate(non_outlier):
        cluster_y_rank[gc] = len(non_outlier) - rank  # highest rank = top
    cluster_y_rank[-1] = 0  # outlier pinned to bottom

    # Step 3: compute per-cluster jitter offsets using ranked positions
    gene_cluster_counts: dict[int, int] = {}
    gene_cluster_index: dict[str, int] = {}
    for p in all_points:
        gene_cluster_counts[p["gene_cluster"]] = gene_cluster_counts.get(p["gene_cluster"], 0) + 1
        gene_cluster_index[p["go_id"]] = gene_cluster_counts[p["gene_cluster"]] - 1

    for p in all_points:
        gc = p["gene_cluster"]
        base_y = cluster_y_rank.get(gc, 0)
        idx = gene_cluster_index[p["go_id"]]
        count = gene_cluster_counts[gc]
        spread = min(count, 10)
        # Cycle the per-point index through [0, spread) so the jitter offset
        # is always bounded in ±0.25.  Without the modulo, idx grows up to
        # count-1 while spread caps at 10 — so for any cluster with more
        # than 10 points, idx/spread climbs past 1.0 and pushes points
        # above (and below) the cluster's band.  Those out-of-band points
        # then land outside Plotly's plotclip rect and silently vanish —
        # which is why the most responsive cluster (always the densest)
        # was missing its top-end points in the rendered chart.
        idx_norm = idx % max(spread, 1)
        p["y_jittered"] = base_y + (idx_norm / max(spread, 1) - 0.5) * 0.5

    # Group by UMAP semantic cluster for traces — each trace gets one
    # color, matching the UMAP scatter chart's legend exactly.
    by_umap_cluster: dict[int, list] = {}
    for p in all_points:
        by_umap_cluster.setdefault(p["umap_cluster"], []).append(p)

    sorted_umap_cids = sorted(by_umap_cluster.keys(), key=lambda c: (c == -1, c))

    for umap_cid in sorted_umap_cids:
        pts = by_umap_cluster[umap_cid]
        color = get_cluster_color(umap_cid, palette=palette, outlier=outlier)
        sizes = [max(6, min(30, p["n_genes"] * 0.5 + 5)) for p in pts]

        fig_cluster.add_trace(go.Scatter(
            x=[p["bmd"] for p in pts],
            y=[p["y_jittered"] for p in pts],
            mode="markers",
            marker=dict(size=sizes, color=color, opacity=mopac,
                        line=dict(width=mlw, color=mlc)),
            name=str(umap_cid) if umap_cid >= 0 else "Outlier",
            text=[f"{p['go_term']}<br>BMD: {p['bmd']:.3g} {dose_unit}<br>"
                  f"Genes: {p['n_genes']}<br>Direction: {p['direction']}<br>"
                  f"Semantic cluster: {p['umap_cluster']}"
                  for p in pts],
            hovertemplate="%{text}<extra></extra>",
        ))

    # Subtle horizontal bands behind each cluster's jitter range.
    # Uniform pale parchment color — neutral enough to not compete
    # with the multi-colored markers within each band.
    for gc, y_pos in cluster_y_rank.items():
        fig_cluster.add_shape(
            type="rect",
            xref="paper", x0=0, x1=1,
            yref="y", y0=y_pos - 0.35, y1=y_pos + 0.35,
            fillcolor="rgba(245,238,228,0.3)",
            line_width=0,
            layer="below",
        )

    # Determine chart height based on number of gene-overlap clusters
    unique_gene_clusters = set(p["gene_cluster"] for p in all_points)
    n_gene_clusters = len(unique_gene_clusters) if all_points else 1
    chart_height = max(180, n_gene_clusters * 29 + 72)

    # Build custom y-axis tick labels showing the original cluster ID
    # at each ranked position.  Outlier (-1) is labeled "Outlier".
    tick_vals = []
    tick_text = []
    for gc, y_pos in sorted(cluster_y_rank.items(), key=lambda kv: kv[1]):
        tick_vals.append(y_pos)
        tick_text.append("Outlier" if gc == -1 else str(gc))

    mg = style.get("margins") or {}
    grid = style.get("gridcolor", "#e8e8e8")
    xa = style.get("xaxis") or {}
    ya = style.get("yaxis") or {}
    leg = style.get("legend") or {}
    xtitle = xa.get("title")
    if xtitle is None:
        xtitle = f"BMD ({dose_unit})"
    else:
        xtitle = xtitle.replace("${dose_unit}", dose_unit)
    xtype = xa.get("type", "log")
    ytitle = (ya.get("title", "Gene-Overlap Cluster") or "").replace("${dose_unit}", dose_unit)

    fig_cluster.update_layout(
        width=style.get("width", 1000),
        height=style.get("height") or chart_height,
        margin=dict(l=mg.get("l", 80), r=mg.get("r", 30),
                    t=mg.get("t", 90), b=mg.get("b", 60)),
        paper_bgcolor=style.get("paper_bgcolor", "#ffffff"),
        plot_bgcolor=style.get("plot_bgcolor", "#fafafa"),
        xaxis=dict(title=xtitle, type=xtype,
                   showgrid=True, gridcolor=grid),
        yaxis=dict(
            title=ytitle,
            showgrid=True, gridcolor=grid,
            tickvals=tick_vals, ticktext=tick_text,
        ),
        hovermode="closest",
        legend=dict(
            font=dict(size=leg.get("font_size", 12)),
            orientation="h",
            x=0.5, y=1.02,
            xanchor="center", yanchor="bottom",
            itemwidth=45,
        ),
    )

    # Legend header as a centered annotation — Plotly's legend.title
    # doesn't center properly with horizontal orientation.
    fig_cluster.add_annotation(
        text="<b>GO Term Semantic Cluster</b>",
        xref="paper", yref="paper",
        x=0.5, y=1.08,
        xanchor="center", yanchor="bottom",
        showarrow=False,
        font=dict(size=13),
    )
    return fig_cluster


def build_generic_chart(
    gene_sets: list[dict],
    *,
    organ: str,
    sex: str,
    dose_unit: str = "mg/kg",
    style: dict | None = None,
    spec: dict | None = None,
    clusters: dict | None = None,
    umap_ref: list[dict] | None = None,
    umap_lookup: dict[str, dict] | None = None,
) -> "object":
    """
    Generic data-driven figure builder (contract C4 + ``spec``).  Serves any
    chart type declared purely in the document config's ``chart_types`` block —
    a trace kind (scatter|bar|line) over named gene_set columns, optional color
    grouping, size binding, sort/limit, and axes.  No per-chart Python.

    ``spec`` keys: ``trace`` (scatter|bar|line), ``x``, ``y`` (column names),
    optional ``color`` (one trace per distinct value), ``size`` (column → marker
    size), ``sort`` ({by, dir}), ``limit`` (int), ``axes`` ({x:{title,type},
    y:{title,type}}).  Visuals (palette, marker opacity, dims, bg, margins) come
    from the resolved ``style``.
    """
    import plotly.graph_objects as go

    style = style or {}
    spec = spec or {}
    trace_kind = spec.get("trace", "scatter")
    xcol = spec.get("x")
    ycol = spec.get("y")
    color_col = spec.get("color")
    size_col = spec.get("size")

    rows = [gs for gs in gene_sets
            if gs.get(xcol) is not None and gs.get(ycol) is not None]

    sort = spec.get("sort") or {}
    if sort.get("by"):
        by = sort["by"]
        rev = (sort.get("dir", "asc") == "desc")
        rows = sorted(rows, key=lambda r: (r.get(by) is None, r.get(by)), reverse=rev)

    limit = spec.get("limit")
    if limit:
        rows = rows[:int(limit)]

    groups: dict = {}
    if color_col:
        for r in rows:
            groups.setdefault(r.get(color_col), []).append(r)
    else:
        groups = {None: rows}

    palette = style.get("palette") or _CLUSTER_COLORS
    mk = style.get("marker") or {}
    mopac = mk.get("opacity", 0.85)

    fig = go.Figure()
    trace_cls = go.Bar if trace_kind == "bar" else go.Scatter
    for gi, (gname, grows) in enumerate(groups.items()):
        xs = [r.get(xcol) for r in grows]
        ys = [r.get(ycol) for r in grows]
        color = palette[gi % len(palette)]
        kwargs: dict = {"x": xs, "y": ys,
                        "name": "" if gname is None else str(gname)}
        if trace_kind == "bar":
            kwargs["marker"] = dict(color=color, opacity=mopac)
        else:
            kwargs["mode"] = "lines" if trace_kind == "line" else "markers"
            marker = dict(color=color, opacity=mopac)
            if mk.get("size") is not None:
                marker["size"] = mk["size"]
            if size_col:
                marker["size"] = [r.get(size_col) or 6 for r in grows]
            kwargs["marker"] = marker
        fig.add_trace(trace_cls(**kwargs))

    axes = spec.get("axes") or {}
    grid = style.get("gridcolor", "#e8e8e8")
    xa = {**(axes.get("x") or {}), **(style.get("xaxis") or {})}
    ya = {**(axes.get("y") or {}), **(style.get("yaxis") or {})}
    xaxis: dict = {"showgrid": True, "gridcolor": grid}
    if xa.get("title"):
        xaxis["title"] = xa["title"].replace("${dose_unit}", dose_unit)
    if xa.get("type"):
        xaxis["type"] = xa["type"]
    yaxis: dict = {"showgrid": True, "gridcolor": grid}
    if ya.get("title"):
        yaxis["title"] = ya["title"].replace("${dose_unit}", dose_unit)
    if ya.get("type"):
        yaxis["type"] = ya["type"]

    layout: dict = {
        "width": style.get("width", 1000),
        "height": style.get("height", 500),
        "paper_bgcolor": style.get("paper_bgcolor", "#ffffff"),
        "plot_bgcolor": style.get("plot_bgcolor", "#fafafa"),
        "xaxis": xaxis,
        "yaxis": yaxis,
        "hovermode": "closest",
    }
    mg = style.get("margins")
    if mg:
        layout["margin"] = dict(l=mg.get("l", 80), r=mg.get("r", 30),
                                t=mg.get("t", 90), b=mg.get("b", 60))
    fig.update_layout(**layout)
    return fig


def render_chart_images(
    gene_sets: list[dict],
    organ: str,
    sex: str,
    dose_unit: str = "mg/kg",
    clusters: dict | None = None,
    gene_dir: dict[str, str] | None = None,
    *,
    chart_style_cfg: dict | None = None,
    registry: dict | None = None,
) -> dict:
    """
    Render every chart type in ``registry`` for one (organ, sex) as base64 PNG
    + namespaced SVG, returning a flat dict keyed by type (contract C5).

    Pure function (no HTTP) so it can be called from both the API endpoint and
    the PDF export pipeline.  For each chart type it resolves the per-instance
    style (chart_style.resolve_chart_style — built-in ← defaults ← types ←
    instances), builds the figure (a registered code builder for umap/cluster, or
    the generic data-driven builder), and rasterizes via the single shared
    kaleido + SVG-ID-namespacing block.

    Args:
        gene_sets:  List of gene set dicts (go_id, go_term, bmd,
                    n_genes_with_bmd, direction, genes, …).
        organ, sex: identify the chart instance (→ instance key, C1).
        dose_unit:  Dose unit for axis labels / captions (default "mg/kg").
        clusters:   Optional pre-computed {go_id: cluster_id}.  If None and a
                    cluster chart is present, computed inline (and shared with
                    the enrichment summary).
        gene_dir:   Optional all-caps symbol → "up"/"down" map for cluster
                    summary n_up/n_down counts.
        chart_style_cfg: the document config's ``chart_style`` block (None ⇒
                    built-in defaults only ⇒ byte-identical to the old render).
        registry:   the effective chart-type registry (chart_registry.
                    build_registry(...)).  None ⇒ the built-in umap+cluster set.

    Returns:
        Dict with generic keys ``f"{type}_png"``/``f"{type}_svg"``/
        ``f"{type}_caption"`` for every type, ``types`` (the list of type names
        present), and — when a cluster chart is present — ``cluster_summary``.
        For umap/cluster with no config these keys/values match the old output.
    """
    import base64

    # Ensure reference data is loaded
    _load_umap_reference()

    organ_title = organ.capitalize() if organ else "Unknown"
    sex_title = sex.capitalize() if sex else ""

    if registry is None:
        registry = chart_registry.default_registry()
    chart_types = list(registry.values())
    type_names = [ct.name for ct in chart_types]

    # Gene-overlap clusters drive the cluster chart's y-axis AND its enrichment
    # summary — compute once, share both, so they can never disagree.
    if "cluster" in type_names and not clusters:
        clusters = _compute_gene_overlap_clusters(gene_sets)

    svg_ns_suffix = f"{organ}-{sex}".lower().replace(" ", "_") or "chart"
    result: dict = {}

    for ct in chart_types:
        style = chart_style.resolve_chart_style(
            chart_style_cfg, ct.name, organ, sex, ct.style_defaults
        )
        bad = chart_style.unknown_style_keys(style)
        if bad:
            logger.warning(
                "chart_style: unknown keys for %s (%s/%s): %s",
                ct.name, organ, sex, bad,
            )

        if ct.has_builder:
            fig = ct.builder(
                gene_sets, organ=organ, sex=sex, dose_unit=dose_unit,
                style=style, clusters=clusters,
                umap_ref=_UMAP_REF, umap_lookup=_UMAP_LOOKUP,
            )
        else:
            fig = build_generic_chart(
                gene_sets, organ=organ, sex=sex, dose_unit=dose_unit,
                style=style, spec=ct.spec, clusters=clusters,
                umap_ref=_UMAP_REF, umap_lookup=_UMAP_LOOKUP,
            )

        # ── Render to PNG + SVG from the same figure ──────────────────────
        # One render, two encodings: any divergence between the PDF (PNG) and
        # the in-app view (SVG) is limited to rasterization, never data.  SVG
        # IDs are namespaced so multiple charts coexist in one DOM without
        # Plotly's auto-generated clip-path IDs colliding across <svg>s.
        png_bytes = fig.to_image(format="png", scale=2)
        svg_raw = fig.to_image(format="svg").decode("utf-8")
        prefix = _SVG_PREFIX.get(ct.name, ct.name)
        svg = _namespace_svg_ids(svg_raw, f"{prefix}-{svg_ns_suffix}")

        template = style.get("caption_template") or ct.caption_template
        caption = (
            template.format(organ_title=organ_title, sex_title=sex_title)
            .replace("${dose_unit}", dose_unit)
            if template else ""
        )

        result[f"{ct.name}_png"] = base64.b64encode(png_bytes).decode()
        result[f"{ct.name}_svg"] = svg
        result[f"{ct.name}_caption"] = caption

    result["types"] = type_names

    # --- Cluster biology summary via Enrichr (cluster chart only) ---
    # Shares the `clusters` assignment built above so the chart and the summary
    # never disagree.
    if "cluster" in type_names:
        result["cluster_summary"] = enrich_clusters(
            gene_sets, clusters or {}, gene_dir=gene_dir
        )

    return result


# ---------------------------------------------------------------------------
# Late binding: attach the real code builders to the registry's built-in types.
# Done here (not in chart_registry) to break the import cycle — chart_registry
# imports nothing from the renderer, the renderer fills in the callables.
# ---------------------------------------------------------------------------
chart_registry.register_builder(
    "umap", build_umap_figure,
    style_defaults=UMAP_STYLE_DEFAULTS,
    caption_template=UMAP_CAPTION_TEMPLATE,
)
chart_registry.register_builder(
    "cluster", build_cluster_figure,
    style_defaults=CLUSTER_STYLE_DEFAULTS,
    caption_template=CLUSTER_CAPTION_TEMPLATE,
)


# ---------------------------------------------------------------------------
# Batch render + cache migration
# ---------------------------------------------------------------------------
# Both the process-integrated pipeline (pool_orchestrator) and the session
# load path (session_routes) need to render one chart pair per organ × sex.
# Keeping the loop here means there's one code path — if the cache shape
# or chart render contract changes, both callers pick it up automatically.

def cache_has_svg(chart_images) -> bool:
    """
    Schema probe for the chart cache: returns True when the cache is
    either empty/None (nothing to migrate) or the first entry carries
    an `umap_svg` field.  Caches written before 2026-04-24 only have
    PNG fields and need to be re-rendered so the HTML can inline SVG.
    """
    if not chart_images:
        return True
    first = chart_images[0] if isinstance(chart_images, list) else chart_images
    return isinstance(first, dict) and "umap_svg" in first


def _resolve_registry(chart_types: dict | None) -> dict:
    """
    Coerce the ``chart_types`` argument into an effective chart-type registry.

    Accepts either:
      - None / empty            → the built-in umap+cluster registry;
      - {name: ChartType}       → a pre-built registry, passed through;
      - {name: spec dict}       → raw YAML data-type specs, validated and built.
    """
    if not chart_types:
        return chart_registry.default_registry()
    if all(isinstance(v, chart_registry.ChartType) for v in chart_types.values()):
        # Already-built registry: ensure the built-ins are present too.
        merged = chart_registry.default_registry()
        merged.update(chart_types)
        return merged
    return chart_registry.build_registry(chart_types)


def render_chart_images_for_sections(
    genomics_sections: dict,
    bmd_stat: str = "median",
    dose_unit: str = "mg/kg",
    chart_style_cfg: dict | None = None,
    chart_types: dict | None = None,
) -> list[dict]:
    """
    Render one chart pair (UMAP + cluster scatter + enrichment) per
    organ × sex in a genomics_sections dict.

    Args:
        genomics_sections: organ_sex-keyed dict (same shape as
                           _cache_genomics_*.json and the
                           process-integrated response).  Each entry
                           must carry `gene_sets_by_stat[bmd_stat]`
                           with at least one gene set, else skipped.
        bmd_stat:          Which BMD statistic's gene-set list drives
                           the charts (same stat as the PDF tables).
        dose_unit:         Passed through for axis labels.
        chart_style_cfg:   the document config's ``chart_style`` block
                           (contract C6).  None ⇒ built-in defaults ⇒
                           today's render.
        chart_types:       the data-driven ``chart_types`` declarations
                           (name → spec dict OR ChartType), folded into the
                           effective registry (contract C6).  None ⇒ just the
                           built-in umap+cluster types.

    Returns:
        List of per-entry dicts as produced by render_chart_images,
        annotated with `label`, `organ`, `sex` so the consumer can
        route entries to the right display slot.  Entries for which
        rendering failed are omitted (warnings logged).

    Synchronous — callers that need async concurrency should wrap in
    run_in_executor themselves.  A single-session render (4 pairs) is
    fast enough to do inline on a page load.
    """
    # Build the effective registry ONCE for the whole batch.  chart_types may
    # arrive as raw YAML specs (name → dict) or as already-built ChartType
    # objects; build_registry handles the former, and a dict of ChartType is
    # passed through as-is.
    registry = _resolve_registry(chart_types)

    out: list[dict] = []
    for key, gen_data in genomics_sections.items():
        # Prefer the full chart set (all passing GO terms) over the top-20 table
        # slice so the UMAP and scatter plots show the complete responsive landscape.
        # Falls back to gene_sets_by_stat for caches that pre-date this field.
        chart_by_stat = gen_data.get("gene_sets_chart_by_stat") or {}
        gs_by_stat = chart_by_stat if chart_by_stat else (gen_data.get("gene_sets_by_stat") or {})
        gene_sets = gs_by_stat.get(bmd_stat) or []
        if not gene_sets:
            continue

        organ = gen_data.get("organ", "")
        sex = gen_data.get("sex", "")
        organ_title = organ.capitalize() or "Unknown"
        sex_title = sex.capitalize() or ""

        try:
            # Build all-caps direction lookup from per-gene results so that
            # cluster summary rows get n_up/n_down (same normalisation used
            # in the GO BP BMD table builder in pool_orchestrator).
            all_genes_raw = gen_data.get("all_genes") or []
            section_gene_dir: dict[str, str] = {
                g["gene_symbol"].upper(): g.get("direction", "")
                for g in all_genes_raw
                if g.get("gene_symbol")
            }

            result = render_chart_images(
                gene_sets=gene_sets,
                organ=organ,
                sex=sex,
                dose_unit=dose_unit,
                gene_dir=section_gene_dir or None,
                chart_style_cfg=chart_style_cfg,
                registry=registry,
            )
            result["label"] = f"{organ_title} ({sex_title})"
            result["organ"] = organ
            result["sex"] = sex
            out.append(result)
        except Exception as e:
            logger.warning("Chart rendering failed for %s: %s", key, e)
    return out


@router.post("/api/genomics-chart-images")
async def api_genomics_chart_images(request: Request):
    """
    Render the UMAP scatter and cluster scatter charts as PNG images.

    Thin wrapper around render_chart_images() for direct API calls.
    Used by the DOCX export pipeline and for debugging.

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
