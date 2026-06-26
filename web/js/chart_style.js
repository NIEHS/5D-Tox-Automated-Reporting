/* -----------------------------------------------------------------
 * chart_style.js — JS mirror of chart_style.py (WP-1).
 *
 * The interactive ("Charts" tab) render path resolves a chart's effective
 * style with the IDENTICAL four-layer deep-merge the Python export path uses
 * (built-in <- chart_style.defaults <- types[type] <- instances[key]), so the
 * browser and the PDF can never diverge.  The primary in-app view consumes
 * server-pre-resolved SVG and needs no merge; these helpers exist for the live
 * Plotly tab and for any client-side restyle.
 *
 * Classic <script> — functions are global so genomics_charts.js can call them.
 * Mirrors: chart_style.deep_merge / instance_key / resolve_chart_style.
 * ----------------------------------------------------------------- */


/**
 * Recursively merge layer objects left-to-right; later layers win.  Two plain
 * objects at the same key merge recursively; any non-object value (scalar,
 * array, null) replaces wholesale (so a `palette` array is replaced, never
 * element-merged).  Inputs are not mutated.  Non-object layers are skipped.
 */
function deepMergeStyle(...layers) {
    const isObj = (v) =>
        v !== null && typeof v === 'object' && !Array.isArray(v);
    const out = {};
    for (const layer of layers) {
        if (!isObj(layer)) continue;
        for (const key of Object.keys(layer)) {
            const value = layer[key];
            if (isObj(out[key]) && isObj(value)) {
                out[key] = deepMergeStyle(out[key], value);
            } else if (isObj(value)) {
                out[key] = deepMergeStyle({}, value);   // deep copy
            } else if (Array.isArray(value)) {
                out[key] = value.slice();
            } else {
                out[key] = value;
            }
        }
    }
    return out;
}


/**
 * The per-instance config key: "<organ>|<sex>|<type>" lower-cased (contract
 * C1).  Matches chart_style.instance_key exactly.
 */
function chartInstanceKey(chartType, organ, sex) {
    const norm = (s) => (s || '').trim();
    return `${norm(organ)}|${norm(sex)}|${norm(chartType)}`.toLowerCase();
}


/**
 * Resolve the effective style for one chart instance.  `cfg` is the raw
 * chart_style block (window.__CHART_STYLE__); `builtin` is the chart type's
 * layer-0 defaults.  Any layer may be absent.  Returns a fresh object.
 * Mirrors chart_style.resolve_chart_style.
 */
function resolveChartStyle(cfg, chartType, organ, sex, builtin) {
    cfg = cfg || {};
    const key = chartInstanceKey(chartType, organ, sex);
    const types = cfg.types || {};
    const instances = cfg.instances || {};
    return deepMergeStyle(
        builtin || {},
        cfg.defaults,
        types[chartType],
        instances[key],
    );
}
