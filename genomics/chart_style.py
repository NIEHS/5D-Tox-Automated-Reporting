"""
chart_style.py — the three-layer chart-style merge (WP-1 of the configurable-
charts feature).

A chart's *effective* appearance is the deep-merge of four layers, in
increasing precedence:

    0. built-in defaults  — today's hardcoded literals, supplied by the caller
                            (the chart type's ``style_defaults`` in
                            chart_registry).  The all-config-absent path uses
                            ONLY this layer, so behaviour is byte-identical to
                            the pre-feature renderer.
    1. chart_style.defaults    — document-author defaults applied to EVERY chart.
    2. chart_style.types[T]    — overrides for every instance of chart type T.
    3. chart_style.instances[K] — overrides for ONE specific chart instance,
                            keyed by the instance key (see ``instance_key``).

Each layer is a partial dict: it overrides only the keys it names and inherits
the rest from below.  The merge is RECURSIVE (``deep_merge``) so an instance may
override a single nested leaf — e.g. ``marker.size`` — without restating the
sibling keys.

This module is the SINGLE source of truth for the merge.  Its JS mirror
(``web/js/chart_style.js``) implements the identical algorithm so the two render
surfaces (Python export + interactive browser) resolve the same effective style
from the same raw config and cannot drift.

Owns contract **C2** (the resolved-style dict shape) and **C1** (the instance
key).  Pure data — imports nothing from the render pipeline; fully unit-testable
in isolation.

The canonical key set a resolved style may contain is documented in
``STYLE_KEY_SCHEMA`` below; the concrete per-type default *values* live with each
chart type (chart_registry.ChartType.style_defaults), because umap and cluster
legitimately differ (e.g. width 900 vs 1000).
"""

from __future__ import annotations

import copy


# ---------------------------------------------------------------------------
# Canonical resolved-style key schema (contract C2)
# ---------------------------------------------------------------------------
# This documents — for authors and for the builders that read the resolved
# style — the full set of keys a style dict may carry and what each controls.
# It is descriptive (a doc + light validation aid), NOT a hard schema: an
# unknown key is tolerated (forward-compatible) but reported by
# ``unknown_style_keys`` so a typo in the YAML is catchable.
#
# Nested dicts mirror the Plotly layout/marker structure the builders emit, so
# an author can reason about "what do I set to change X" directly.
STYLE_KEY_SCHEMA: dict = {
    "width": int,                 # figure pixel width
    "height": int,                # figure pixel height (or None → computed)
    "paper_bgcolor": str,         # area outside the plot
    "plot_bgcolor": str,          # the plotting area
    "gridcolor": str,             # axis gridlines
    "palette": list,              # cluster color cycle (list[str] hex)
    "outlier_color": str,         # color for the -1 / outlier cluster
    "marker": {
        "size": (int, float),     # base marker size
        "opacity": (int, float),  # marker opacity 0..1
        "line_width": (int, float),
        "line_color": str,
    },
    "legend": {
        "font_size": (int, float),
        "bgcolor": str,
        "bordercolor": str,
        "borderwidth": (int, float),
    },
    "margins": {                  # plot margins in px
        "l": int, "r": int, "t": int, "b": int,
    },
    "xaxis": {
        "title": str,             # may contain ${dose_unit}
        "type": str,              # "log" | "linear" | "category" | ""
    },
    "yaxis": {
        "title": str,
    },
    "caption_template": str,      # may contain {organ_title}/{sex_title}/${dose_unit}
}


# ---------------------------------------------------------------------------
# Deep merge
# ---------------------------------------------------------------------------

def deep_merge(*layers: dict) -> dict:
    """
    Recursively merge ``layers`` left-to-right; later layers win.

    Merge rules (identical to the JS mirror):
      - two dicts at the same key merge recursively;
      - any non-dict value (scalar, list, None) REPLACES wholesale — notably a
        ``palette`` list is replaced, never element-merged;
      - a later dict replacing an earlier scalar (or vice-versa) replaces.

    Returns a fresh deep-copied dict; inputs are never mutated.  A ``None`` or
    non-dict layer is skipped (treated as an empty override), so callers can
    pass ``cfg.get("defaults")`` without guarding for absence.
    """
    out: dict = {}
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        for key, value in layer.items():
            existing = out.get(key)
            if isinstance(existing, dict) and isinstance(value, dict):
                out[key] = deep_merge(existing, value)
            else:
                out[key] = copy.deepcopy(value)
    return out


# ---------------------------------------------------------------------------
# Instance key (contract C1)
# ---------------------------------------------------------------------------

def instance_key(chart_type: str, organ: str, sex: str) -> str:
    """
    The per-instance config key: ``"<organ>|<sex>|<type>"`` lower-cased.

    Constructible identically on both surfaces (Python ``render_chart_images``
    receives organ/sex; the JS builders read ``data.organ``/``data.sex``), so a
    config block under ``chart_style.instances`` addresses exactly one rendered
    chart.  Empty organ/sex degrade to empty segments (e.g. ``"||umap"``) rather
    than raising — an unkeyed chart simply never matches an instance override.
    """
    return f"{(organ or '').strip()}|{(sex or '').strip()}|{(chart_type or '').strip()}".lower()


# ---------------------------------------------------------------------------
# The resolver
# ---------------------------------------------------------------------------

def resolve_chart_style(
    chart_style_cfg: dict | None,
    chart_type: str,
    organ: str,
    sex: str,
    builtin: dict | None,
) -> dict:
    """
    Resolve the effective style for one chart instance via the four-layer
    deep-merge (built-in ← defaults ← types[type] ← instances[key]).

    Args:
        chart_style_cfg: the raw ``chart_style`` block from the document config
            (``{defaults, types, instances}``); any layer may be absent.  None
            or ``{}`` ⇒ the built-in layer is returned unchanged.
        chart_type:      e.g. "umap", "cluster", "bmd-bar".
        organ, sex:      identify the instance (→ instance key, C1).
        builtin:         this chart type's layer-0 defaults
            (chart_registry.ChartType.style_defaults).  None ⇒ {}.

    Returns a fresh resolved-style dict (contract C2 shape).
    """
    cfg = chart_style_cfg or {}
    key = instance_key(chart_type, organ, sex)
    return deep_merge(
        builtin or {},
        cfg.get("defaults"),
        (cfg.get("types") or {}).get(chart_type),
        (cfg.get("instances") or {}).get(key),
    )


def unknown_style_keys(style: dict, schema: dict | None = None) -> list[str]:
    """
    Return dotted paths in ``style`` not present in ``STYLE_KEY_SCHEMA`` — a
    typo-catcher for authored config.  Recurses into the nested groups the
    schema defines (marker/legend/margins/xaxis/yaxis).  Non-fatal: callers log
    these as warnings, mirroring the loud-but-non-blocking discipline elsewhere.
    """
    schema = STYLE_KEY_SCHEMA if schema is None else schema
    bad: list[str] = []

    def _walk(s: dict, sch: dict, prefix: str) -> None:
        for k, v in s.items():
            if k not in sch:
                bad.append(f"{prefix}{k}")
                continue
            expected = sch[k]
            if isinstance(expected, dict) and isinstance(v, dict):
                _walk(v, expected, f"{prefix}{k}.")

    if isinstance(style, dict):
        _walk(style, schema, "")
    return bad
