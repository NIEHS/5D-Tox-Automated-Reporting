"""
genomics_charts.py — shared assembly of genomics chart images onto the
genomics-section entries that both rendering paths consume.

Why this module exists
----------------------
There are two content-assembly paths in this project:

  * the SESSION-export path (latex_export.load_session_data), which reads the
    session's cache files straight off disk, and
  * the WEB/preview path (report_data.marshal_export_data), which overlays the
    request body the browser sends.

Both ultimately render the SAME document tree through both renderers
(latex_generator and html_generator), and both renderers read genomics chart
images from `entry["charts"]` on each gene_set genomics section.  If only one
path attached those charts, the other surface would silently lose them — which
is exactly the drift this module removes.  The chart-attach logic therefore
lives here, in a dependency-light module (stdlib `base64` only), so BOTH paths
import the identical implementation instead of one path owning it privately.

The functions are pure: they take the already-loaded section list and the
already-loaded chart cache and mutate the sections in place.  They never read
disk or the network — each caller is responsible for loading its own cache
(from a file on the session path, or from the session dir named in the request
body on the web path) and passing it in.  This keeps the "where do the bytes
come from" decision with the caller and the "how are they shaped onto the
sections" decision here, in one place.

This module RENDERS NOTHING.  It only attaches the validated base64-PNG payload;
each renderer emits the markup (\\includegraphics for LaTeX, an inline data-URI
<img> for HTML) keyed off the attached fields.  See genomics_content.py for the
ordered content-item plan that turns each attached chart into a render item.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
# base64 is the only dependency — these helpers decode the cached PNG strings
# and never touch disk, the network, or any heavyweight reporting module, so
# both the low-level web assembler and the export surface can import them
# without dragging in extra transitive dependencies or risking an import cycle.

import base64


# ---------------------------------------------------------------------------
# Helpers (private)
# ---------------------------------------------------------------------------

def decode_png(b64: str | None) -> bytes | None:
    """
    Decode a base64 PNG (raw, or "data:image/png;base64,..." form) to bytes,
    returning None if it is missing or won't decode.

    Used both to VALIDATE a chart at attach time (so an undecodable image is
    dropped before it can reach a renderer as a figure with no backing file)
    and later to produce the raw bytes the Overleaf bundler writes into
    figures/.  A single decoder keeps those two uses from disagreeing on what
    "decodable" means.
    """
    if not b64:
        return None
    # The web path may hand us a full data-URI ("data:image/png;base64,AAAA");
    # strip the prefix so b64decode sees only the payload.
    if b64.startswith("data:"):
        b64 = b64.split(",", 1)[-1]
    try:
        return base64.b64decode(b64)
    except Exception:
        # Any malformed input (bad padding, non-base64 characters) is treated
        # as "no image" rather than raising, so one bad chart can't abort the
        # whole report assembly.
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def attach_genomics_charts(
    genomics_sections: list,
    charts_cache: list,
    enabled_types: list | None = None,
) -> None:
    """
    Attach per-(organ, sex) chart images to the matching gene_set entries.

    `charts_cache` is the `_cache_charts_*.json` list: one entry per (organ,
    sex) carrying base64-PNG fields `<type>_png` / `<type>_caption` for each
    chart type present (plus a `types` list naming them).  We index it by
    (organ, sex) and hang the images on the gene_set genomics entry as
    entry["charts"], so genomics_content_plan emits chart content items and
    build_overleaf_bundle writes the PNGs into figures/.

    The chart types are whatever the renderer produced (umap + cluster, plus any
    data-driven types declared in the document config) — read from the cache
    entry's `types` list so a new chart type rides through to both renderers
    with no edit here.  Pre-feature caches lack `types`; they fall back to the
    original umap/cluster pair.

    `enabled_types` is the document config's ``charts:`` ALLOWLIST of type keys
    (document_template.load_report_charts).  ``None`` (the default, and the
    "charts key absent" case) means no filtering — every produced type renders.
    A LIST — including the empty list — restricts rendering to those type keys,
    so ``charts: []`` in the template suppresses every genomics figure (the
    reference report carries no main-body charts).  Applied to BOTH paths here
    so the HTML preview and the Overleaf export agree on which figures appear.

    Each chart carries its OWN deterministic `filename`; both the renderer
    (the \\includegraphics path) and the bundler (the file it writes) read that
    same field, so they can never disagree on the name — a mismatch would be a
    missing-figure compile error on Overleaf.

    Mutates `genomics_sections` in place and returns None.  Called by BOTH the
    session-export path (latex_export) and the web/preview path (report_data),
    so the HTML preview and the LaTeX export attach charts identically.
    """
    if not isinstance(charts_cache, list):
        return
    allow = None if enabled_types is None else {t.lower() for t in enabled_types}
    # Index the cache by (organ, sex), lower-cased, so the lookup below is
    # case-insensitive and order-independent.
    by_os = {
        ((c.get("organ") or "").lower(), (c.get("sex") or "").lower()): c
        for c in charts_cache if isinstance(c, dict)
    }
    # Sequential figure number across ALL attached charts (positional in render
    # order: entries iterate in genomics_sections order, charts within an entry
    # iterate umap -> cluster).  Each chart's figure_number becomes the renderer's
    # "Figure N." caption prefix and the BITS <label>Figure N</label> later
    # (ADR-0004 amendment e).
    next_figure = 1
    for entry in genomics_sections:
        # Only gene_set entries carry charts; gene (top-genes) entries don't.
        if entry.get("type") != "gene_set":
            continue
        organ = (entry.get("organ") or "").lower()
        sex = (entry.get("sex") or "").lower()
        cache_entry = by_os.get((organ, sex))
        if not cache_entry:
            continue
        slug = f"{organ}-{sex}".replace(" ", "-")
        charts = []
        # Which chart types this cache entry carries.  Prefer the explicit
        # `types` list written by render_chart_images (contract C5); fall back to
        # the original umap/cluster pair for caches that pre-date it.
        chart_keys = cache_entry.get("types")
        if not isinstance(chart_keys, list) or not chart_keys:
            chart_keys = ["umap", "cluster"]
        for key in chart_keys:
            # Config allowlist (charts:): skip any type not enabled.  `allow`
            # is None when the template omits `charts:` (no filtering).
            if allow is not None and key.lower() not in allow:
                continue
            png = cache_entry.get(f"{key}_png")
            if not png:
                continue
            # Validate the base64 decodes NOW and drop a chart we can't decode,
            # so it never reaches the renderer as a \includegraphics with no
            # backing file in figures/ (which would break the Overleaf compile).
            if decode_png(png) is None:
                continue
            charts.append({
                "key": key,
                "filename": f"genomics-{slug}-{key}.png",
                "png_b64": png,
                "caption": cache_entry.get(f"{key}_caption", ""),
                "figure_number": next_figure,
            })
            next_figure += 1
        if charts:
            entry["charts"] = charts
