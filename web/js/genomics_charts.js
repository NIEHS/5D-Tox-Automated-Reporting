/* -----------------------------------------------------------------
 * genomics_charts.js — Interactive Plotly visualizations for genomics data
 *
 * Loaded after main.js.  Provides two chart types from BMDExpress-Web-Edition,
 * adapted for the vanilla-JS 5dToxReport UI:
 *
 *   1. UMAP Scatter Plot — GO BP categories projected onto a pre-computed
 *      2D semantic embedding.  Backdrop shows the full reference space
 *      (~2,840 GO terms); analysis points are colored by HDBSCAN cluster.
 *
 *   2. Cluster Scatter Plot — GO categories plotted as BMD (x-axis, log)
 *      vs. hierarchical gene-overlap cluster (y-axis).  Marker size
 *      reflects the number of genes with BMD values.
 *
 * Both charts read from the global `genomicsResults` dict (defined in
 * state.js) and the reference UMAP data loaded from /data/umap_reference.json.
 *
 * Entry point: renderGenomicsCharts() — called by activateTab('Charts')
 * in main.js when the Charts tab is selected.
 * ----------------------------------------------------------------- */


/* ================================================================
 * Constants and module-level state
 * ================================================================ */

/**
 * Cluster color palette — 42 distinct colors for HDBSCAN clusters.
 * Matches the server-side palette in genomics_viz.py so that cluster
 * colors are visually consistent between the interactive UI and the
 * static report images.
 */
const CLUSTER_COLORS = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
    "#42d4f4", "#f032e6", "#bfef45", "#fabed4", "#469990",
    "#dcbeff", "#9a6324", "#fffac8", "#800000", "#aaffc3",
    "#808000", "#ffd8b1", "#000075", "#a9a9a9", "#e6beff",
    "#1abc9c", "#2ecc71", "#3498db", "#9b59b6", "#e67e22",
    "#e74c3c", "#1a5276", "#7d3c98", "#2e86c1", "#a93226",
    "#196f3d", "#b9770e", "#5b2c6f", "#1b4f72", "#78281f",
    "#186a3b", "#7e5109", "#4a235a", "#154360", "#641e16",
    "#0e6251", "#7b7d7d",
];

/** Neutral gray for outlier points (HDBSCAN cluster = -1). */
const OUTLIER_COLOR = "#999999";

/**
 * Cached reference UMAP data.  Loaded once from /data/umap_reference.json
 * on first chart render, then reused for all subsequent renders.
 * Each entry: {x, y, go_id, go_term, cluster}
 */
let _umapRefData = null;

/**
 * Lookup map: go_id → reference UMAP entry.
 * Built from _umapRefData on first load for O(1) lookups when joining
 * analysis GO IDs with their UMAP coordinates.
 */
let _umapLookup = null;

/**
 * Tracks which organ_sex key is currently displayed in the charts.
 * Prevents unnecessary re-renders when the user switches tabs back
 * to Charts without changing the selected organ/sex.
 */
let _currentChartKey = null;

/**
 * Shared ResizeObserver — watches chart containers and re-layouts
 * Plotly charts to match their CSS aspect-ratio on viewport resize.
 * Each observed element stores its target aspect ratio in a data
 * attribute so the callback can compute the correct dimensions.
 */
let _chartResizeObserver = null;

/**
 * Observe a chart container for resizes and re-layout Plotly to fill
 * the container while maintaining the given aspect ratio.
 *
 * The CSS aspect-ratio property on the container div controls the
 * container's shape; this observer reads the resulting clientWidth /
 * clientHeight after the browser resolves layout and tells Plotly to
 * match those dimensions exactly.
 *
 * Uses a debounce (100ms) to avoid excessive relayouts during smooth
 * window drags.
 *
 * @param {string} elementId — the chart container's DOM id
 * @param {number} aspectRatio — width / height (e.g. 1 for square, 1.25 for wide)
 */
function _observeResize(elementId, aspectRatio) {
    const el = document.getElementById(elementId);
    if (!el) return;

    // Store the aspect ratio on the element for the observer callback
    el.dataset.chartAspect = String(aspectRatio);

    if (!_chartResizeObserver) {
        let debounceTimer = null;
        _chartResizeObserver = new ResizeObserver((entries) => {
            // Debounce to avoid relayout storms during smooth resizes
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                for (const entry of entries) {
                    const target = entry.target;
                    const w = target.clientWidth;
                    const h = target.clientHeight;
                    if (w > 0 && h > 0) {
                        Plotly.relayout(target.id, { width: w, height: h });
                    }
                }
            }, 100);
        });
    }

    _chartResizeObserver.observe(el);
}


/* ================================================================
 * Helpers
 * ================================================================ */

/**
 * Return a hex color for a given HDBSCAN cluster ID.
 * Outliers (cluster_id < 0) get a neutral gray; valid clusters
 * are mapped to the palette via modular indexing.
 *
 * @param {number} clusterId — the HDBSCAN cluster assignment
 * @returns {string} hex color string
 */
function _clusterColor(clusterId) {
    if (clusterId < 0) return OUTLIER_COLOR;
    return CLUSTER_COLORS[clusterId % CLUSTER_COLORS.length];
}


/**
 * Load the reference UMAP data from the static JSON file.
 * Returns a promise that resolves when data is cached.
 * Subsequent calls return immediately (data is already loaded).
 */
async function _ensureUmapRefLoaded() {
    if (_umapRefData) return;

    const resp = await fetch('/data/umap_reference.json');
    if (!resp.ok) {
        console.error('Failed to load UMAP reference data:', resp.status);
        return;
    }
    _umapRefData = await resp.json();

    // Build lookup map for O(1) access by GO ID
    _umapLookup = {};
    for (const item of _umapRefData) {
        _umapLookup[item.go_id] = item;
    }
    console.log(`[genomics_charts] Loaded ${_umapRefData.length} reference UMAP points`);
}


/**
 * Collect all gene_sets from the selected genomics result.
 * Handles both the new gene_sets_by_stat format and the legacy
 * single gene_sets array.  When multiple stats exist, uses the
 * first one (they contain the same GO categories, just sorted
 * differently by different BMD statistics).
 *
 * @param {object} data — a genomicsResults[key] entry
 * @returns {Array} array of gene set objects
 */
function _getGeneSets(data) {
    const byStatMap = data.gene_sets_by_stat || {};
    const statKeys = Object.keys(byStatMap);
    if (statKeys.length > 0) {
        // Use the first stat's gene sets (they share the same GO categories)
        return byStatMap[statKeys[0]] || [];
    }
    // Legacy format
    return data.gene_sets || [];
}


/* ================================================================
 * Chart type tab switching — UMAP vs Cluster Scatter
 *
 * Two chart panels live inside the Charts tab.  Only the active
 * one is visible; clicking a chart-type tab toggles between them.
 * ================================================================ */

/**
 * Switch between the UMAP and Cluster Scatter chart panels.
 *
 * @param {string} type — "umap" or "cluster"
 */
function activateChartTypeTab(type) {
    // Toggle panel visibility
    document.querySelectorAll('.chart-type-panel').forEach(p => {
        p.classList.toggle('active', p.id === `chart-panel-${type}`);
    });

    // Toggle button active states
    const tabBar = document.getElementById('chart-type-tabs');
    tabBar.querySelectorAll('button').forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('data-chart-type') === type);
    });

    // Plotly renders into a zero-size container when the panel is
    // hidden.  After making it visible, tell Plotly to recalculate
    // the layout so the chart fills its container correctly.
    const chartId = type === 'umap' ? 'umap-chart' : 'cluster-chart';
    const chartEl = document.getElementById(chartId);
    if (chartEl && typeof Plotly !== 'undefined') {
        requestAnimationFrame(() => Plotly.Plots.resize(chartEl));
    }
}


/* ================================================================
 * Charts organ×sex sub-tab switching
 *
 * Each organ×sex gets a sub-tab button.  Clicking one sets the
 * active state and re-renders the shared chart containers with
 * that experiment's data.
 * ================================================================ */

/**
 * Switch the active charts sub-tab and re-render the charts for
 * the selected organ×sex key.
 *
 * Called from sub-tab button clicks AND from renderGenomicsCharts()
 * on first render to activate the default tab.  When called from a
 * button click, `fromClick=true` triggers a re-render; when called
 * internally during renderGenomicsCharts(), it just sets the active
 * state without recursing.
 *
 * @param {string} key       — organ_sex key to activate
 * @param {boolean} fromClick — true when triggered by user click
 */
function activateChartsSubTab(key, fromClick) {
    const tabBar = document.getElementById('charts-sub-tabs');
    tabBar.querySelectorAll('button').forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('data-chart-key') === key);
    });

    // When the user clicks a sub-tab, force re-render by clearing
    // the cached key and calling renderGenomicsCharts().
    if (fromClick) {
        _currentChartKey = null;
        renderGenomicsCharts();
    }
}


/* ================================================================
 * Main entry point — called from activateTab('Charts') in main.js
 * ================================================================ */

/**
 * Render (or re-render) the genomics charts for the currently selected
 * organ/sex.  Builds organ×sex sub-tabs if multiple experiments exist,
 * loads UMAP reference data, fetches cluster assignments from the
 * backend, and draws both Plotly charts.
 *
 * This function is idempotent — safe to call repeatedly.  It checks
 * whether the selected data has changed before re-rendering.
 */
async function renderGenomicsCharts() {
    const keys = Object.keys(genomicsResults);
    if (keys.length === 0) return;

    // Build organ×sex sub-tabs — mirrors the Genomics and Apical pattern.
    // Only rebuild if keys changed since last render.
    const tabBar = document.getElementById('charts-sub-tabs');
    const cachedKeys = tabBar.dataset.keys || '';
    if (cachedKeys !== keys.join(',')) {
        tabBar.innerHTML = '';
        for (const k of keys) {
            const d = genomicsResults[k];
            const organ = (d.organ || '').charAt(0).toUpperCase() + (d.organ || '').slice(1);
            const sex = (d.sex || '').charAt(0).toUpperCase() + (d.sex || '').slice(1);
            const btn = document.createElement('button');
            btn.textContent = `${organ} — ${sex}`;
            btn.setAttribute('data-chart-key', k);
            btn.onclick = () => activateChartsSubTab(k, true);
            tabBar.appendChild(btn);
        }
        tabBar.dataset.keys = keys.join(',');
        tabBar.classList.add('visible');
    }

    // Determine selected key from the active sub-tab button
    let selectedKey = _currentChartKey;
    const activeBtn = tabBar.querySelector('button.active');
    if (activeBtn) {
        selectedKey = activeBtn.getAttribute('data-chart-key');
    } else {
        // First render — activate the first tab
        selectedKey = keys[0];
        activateChartsSubTab(selectedKey);
    }

    // Skip re-render if same key is already displayed
    if (selectedKey === _currentChartKey) {
        // But still ensure charts exist (first render after tab switch)
        const umapEl = document.getElementById('umap-chart');
        if (umapEl && umapEl.children.length > 0) return;
    }

    _currentChartKey = selectedKey;
    const data = genomicsResults[selectedKey];
    if (!data) return;

    const geneSets = _getGeneSets(data);
    if (geneSets.length === 0) return;

    // Load reference data in parallel with cluster fetch
    await _ensureUmapRefLoaded();

    // Fetch cluster assignments from backend
    let clusters = {};
    try {
        const clusterResp = await fetch('/api/genomics-clusters', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                categories: geneSets.map(gs => ({
                    go_id: gs.go_id,
                    genes: gs.genes || '',
                })),
                linkage: 'average',
            }),
        });
        if (clusterResp.ok) {
            const clusterData = await clusterResp.json();
            clusters = clusterData.clusters || {};
        }
    } catch (e) {
        console.warn('[genomics_charts] Cluster fetch failed, using flat layout:', e);
    }

    // Draw both charts
    _renderUmapChart(geneSets, data);
    _renderClusterChart(geneSets, data, clusters);
}


/* ================================================================
 * UMAP Scatter Plot
 *
 * Two-layer visualization:
 *   1. Backdrop: all ~2,840 reference GO terms (tiny, faded black)
 *   2. Analysis: GO categories from this experiment, colored by
 *      HDBSCAN semantic cluster, with hover showing GO term details
 * ================================================================ */

/**
 * Render the UMAP scatter plot into the #umap-chart div.
 *
 * @param {Array} geneSets — array of gene set objects from genomicsResults
 * @param {object} data — the full genomicsResults[key] entry
 */
function _renderUmapChart(geneSets, data) {
    if (!_umapRefData) return;

    const traces = [];

    // Layer 1: reference backdrop — all GO terms in the embedding space.
    // Tiny, faded markers so the analysis points stand out clearly.
    traces.push({
        x: _umapRefData.map(p => p.x),
        y: _umapRefData.map(p => p.y),
        mode: 'markers',
        type: 'scatter',
        marker: { size: 3, color: '#000', opacity: 0.12 },
        name: 'Reference space',
        hoverinfo: 'skip',
        showlegend: true,
    });

    // Layer 2: analysis points, grouped by HDBSCAN cluster.
    // Each cluster gets its own trace so Plotly shows a color-coded legend.
    const byCluster = {};
    let matchCount = 0;
    for (const gs of geneSets) {
        const ref = _umapLookup[gs.go_id];
        if (!ref) continue;  // GO term not in reference space
        matchCount++;
        const cid = ref.cluster;
        if (!byCluster[cid]) byCluster[cid] = [];
        byCluster[cid].push({
            x: ref.x,
            y: ref.y,
            go_id: gs.go_id,
            go_term: gs.go_term || ref.go_term,
            bmd: gs.bmd,
            cluster: cid,
        });
    }

    // Sort cluster IDs: numeric ascending, outliers (-1) last
    const sortedCids = Object.keys(byCluster).map(Number).sort((a, b) => {
        if (a === -1) return 1;
        if (b === -1) return -1;
        return a - b;
    });

    for (const cid of sortedCids) {
        const pts = byCluster[cid];
        const color = _clusterColor(cid);
        const name = cid >= 0 ? `Cluster ${cid}` : 'Outlier';

        traces.push({
            x: pts.map(p => p.x),
            y: pts.map(p => p.y),
            mode: 'markers',
            type: 'scatter',
            marker: {
                size: 9,
                color: color,
                opacity: 0.85,
                line: { width: 0.5, color: '#fff' },
            },
            name: name,
            text: pts.map(p =>
                `${p.go_term}<br>GO: ${p.go_id}<br>` +
                `BMD: ${p.bmd != null ? Number(p.bmd).toFixed(3) : '—'}<br>` +
                `Cluster: ${p.cluster}`
            ),
            hovertemplate: '%{text}<extra></extra>',
        });
    }

    // Compute height from container width to maintain 1:1 aspect ratio.
    // The CSS aspect-ratio property sizes the container; we read its
    // actual dimensions so Plotly fills it exactly.
    const umapEl = document.getElementById('umap-chart');
    const umapWidth = umapEl.clientWidth || 600;
    const umapHeight = umapEl.clientHeight || umapWidth;

    const layout = {
        autosize: false,
        width: umapWidth,
        height: umapHeight,
        margin: { l: 60, r: 30, t: 30, b: 50 },
        paper_bgcolor: '#fff',
        plot_bgcolor: '#fafafa',
        xaxis: {
            title: { text: 'UMAP 1' },
            showgrid: true,
            gridcolor: '#e8e8e8',
            zeroline: false,
        },
        yaxis: {
            title: { text: 'UMAP 2' },
            showgrid: true,
            gridcolor: '#e8e8e8',
            zeroline: false,
            scaleanchor: 'x',
        },
        hovermode: 'closest',
        legend: { font: { size: 10 } },
    };

    const config = {
        responsive: false,
        displayModeBar: true,
        displaylogo: false,
        modeBarButtonsToRemove: ['lasso2d', 'select2d'],
    };

    Plotly.newPlot('umap-chart', traces, layout, config);

    // Observe container resizes and re-layout to match the CSS
    // aspect-ratio.  Uses a shared ResizeObserver (created once).
    _observeResize('umap-chart', 1);

    // Update caption with match stats
    const captionEl = document.querySelector('#genomics-charts-section .chart-panel:first-of-type .chart-caption');
    if (captionEl) {
        const organ = (data.organ || '').charAt(0).toUpperCase() + (data.organ || '').slice(1);
        const sex = (data.sex || '').charAt(0).toUpperCase() + (data.sex || '').slice(1);
        captionEl.textContent =
            `GO Biological Process categories from the ${organ} (${sex}) analysis ` +
            `projected onto a pre-computed UMAP embedding of ${_umapRefData.length.toLocaleString()} GO BP terms. ` +
            `${matchCount} of ${geneSets.length} analysis categories matched the reference space. ` +
            `Points are colored by HDBSCAN semantic cluster.`;
    }
}


/* ================================================================
 * Cluster Scatter Plot
 *
 * GO categories plotted as:
 *   X = BMD value (log scale)
 *   Y = hierarchical gene-overlap cluster ID (with jitter)
 *   Size = number of genes with BMD values
 *   Color = UMAP semantic cluster (same palette as the UMAP scatter)
 * ================================================================ */

/* ================================================================
 * Chart image capture for report export
 *
 * Called by exportDocx() and exportPdf() in main.js before sending
 * the export payload.  Captures the currently rendered Plotly charts
 * as base64 PNG images with captions suitable for report embedding.
 * ================================================================ */

/**
 * Capture the currently rendered UMAP and cluster scatter charts as
 * base64-encoded PNG images for embedding in DOCX/PDF reports.
 *
 * Returns null if no charts are rendered (no genomics data).
 * The returned object includes:
 *   - umap_png: base64 PNG string (no data: prefix)
 *   - cluster_png: base64 PNG string
 *   - umap_caption: figure caption text
 *   - cluster_caption: figure caption text
 *
 * @returns {Promise<object|null>} chart images and captions
 */
async function captureGenomicsChartImages() {
    const umapEl = document.getElementById('umap-chart');
    const clusterEl = document.getElementById('cluster-chart');

    // Skip if charts haven't been rendered yet
    if (!umapEl || umapEl.children.length === 0) return null;
    if (!clusterEl || clusterEl.children.length === 0) return null;

    try {
        // Capture both charts at 2x resolution for print quality
        const [umapDataUrl, clusterDataUrl] = await Promise.all([
            Plotly.toImage(umapEl, { format: 'png', width: 1200, height: 800, scale: 2 }),
            Plotly.toImage(clusterEl, { format: 'png', width: 1200, height: 800, scale: 2 }),
        ]);

        // Strip the "data:image/png;base64," prefix to get raw base64
        const umapB64 = umapDataUrl.replace(/^data:image\/png;base64,/, '');
        const clusterB64 = clusterDataUrl.replace(/^data:image\/png;base64,/, '');

        // Read captions from the chart panels
        const umapCaption = document.querySelector(
            '#genomics-charts-section .chart-panel:first-of-type .chart-caption'
        )?.textContent || '';
        const clusterCaption = document.querySelector(
            '#genomics-charts-section .chart-panel:last-of-type .chart-caption'
        )?.textContent || '';

        return {
            umap_png: umapB64,
            cluster_png: clusterB64,
            umap_caption: umapCaption,
            cluster_caption: clusterCaption,
        };
    } catch (e) {
        console.warn('[genomics_charts] Chart capture failed:', e);
        return null;
    }
}


/**
 * Render the cluster scatter plot into the #cluster-chart div.
 *
 * @param {Array} geneSets — array of gene set objects from genomicsResults
 * @param {object} data — the full genomicsResults[key] entry
 * @param {object} clusters — map of go_id → cluster_id from backend
 */
function _renderClusterChart(geneSets, data, clusters) {
    const doseUnit = reportSettings.dose_unit || 'mg/kg';

    // Build flat list of plottable points, each annotated with both its
    // gene-overlap cluster (y-axis position) and its UMAP semantic cluster
    // (determines color — same palette as the UMAP scatter chart).
    const points = [];
    for (const gs of geneSets) {
        const bmd = gs.bmd;
        if (bmd == null || !isFinite(Number(bmd)) || Number(bmd) <= 0) continue;
        const geneCluster = clusters[gs.go_id] ?? 0;
        // Look up the UMAP semantic cluster for this GO term so the color
        // matches the UMAP scatter plot above.  Falls back to -1 (outlier
        // gray) if the term isn't in the reference space.
        const ref = _umapLookup ? _umapLookup[gs.go_id] : null;
        const umapCluster = ref ? ref.cluster : -1;
        points.push({
            go_id: gs.go_id,
            go_term: gs.go_term || '',
            bmd: Number(bmd),
            geneCluster,
            umapCluster,
            n_genes: gs.n_genes_with_bmd || gs.n_passed || 0,
            direction: gs.direction || '',
        });
    }

    // Group by UMAP semantic cluster for legend entries — each trace gets
    // one color, matching the UMAP scatter chart's legend exactly.
    const byUmapCluster = {};
    for (const p of points) {
        const key = p.umapCluster;
        if (!byUmapCluster[key]) byUmapCluster[key] = [];
        byUmapCluster[key].push(p);
    }

    // Compute per-gene-cluster jitter offsets.  Points within the same
    // gene-overlap cluster band are spread vertically so they don't overlap.
    // We need to count how many points land in each gene cluster first.
    const geneClusterCounts = {};
    const geneClusterIndex = {};
    for (const p of points) {
        geneClusterCounts[p.geneCluster] = (geneClusterCounts[p.geneCluster] || 0) + 1;
        geneClusterIndex[p.go_id] = geneClusterCounts[p.geneCluster] - 1;
    }

    const traces = [];

    // Sort UMAP cluster IDs: numeric ascending, outliers (-1) last
    const sortedUmapCids = Object.keys(byUmapCluster).map(Number).sort((a, b) => {
        if (a === -1) return 1;
        if (b === -1) return -1;
        return a - b;
    });

    for (const umapCid of sortedUmapCids) {
        const pts = byUmapCluster[umapCid];
        const color = _clusterColor(umapCid);
        const name = umapCid >= 0 ? `Cluster ${umapCid}` : 'Outlier';

        // Compute jittered y positions based on gene-overlap cluster
        const jittered_y = pts.map(p => {
            const count = geneClusterCounts[p.geneCluster];
            const idx = geneClusterIndex[p.go_id];
            const spread = Math.min(count, 10);
            return p.geneCluster + (idx / Math.max(spread, 1) - 0.5) * 0.5;
        });

        const sizes = pts.map(p => Math.max(6, Math.min(30, p.n_genes * 0.5 + 5)));

        traces.push({
            x: pts.map(p => p.bmd),
            y: jittered_y,
            mode: 'markers',
            type: 'scatter',
            marker: {
                size: sizes,
                color: color,
                opacity: 0.8,
                line: { width: 0.5, color: '#fff' },
            },
            name: name,
            text: pts.map(p =>
                `${p.go_term}<br>` +
                `BMD: ${p.bmd.toFixed(3)} ${doseUnit}<br>` +
                `Genes: ${p.n_genes}<br>` +
                `Direction: ${p.direction}<br>` +
                `Semantic cluster: ${p.umapCluster}`
            ),
            hovertemplate: '%{text}<extra></extra>',
        });
    }

    const uniqueGeneClusters = new Set(points.map(p => p.geneCluster));
    const nGeneClusters = uniqueGeneClusters.size;

    // Compute dimensions from the CSS aspect-ratio container (1.25:1 = wider than tall).
    // The container's aspect-ratio is set in HTML; we read actual dimensions.
    const clusterEl = document.getElementById('cluster-chart');
    const clusterWidth = clusterEl.clientWidth || 600;
    const clusterHeight = clusterEl.clientHeight || Math.round(clusterWidth / 1.25);

    const layout = {
        autosize: false,
        width: clusterWidth,
        height: clusterHeight,
        margin: { l: 80, r: 30, t: 30, b: 60 },
        paper_bgcolor: '#fff',
        plot_bgcolor: '#fafafa',
        xaxis: {
            title: { text: `BMD (${doseUnit})` },
            type: 'log',
            showgrid: true,
            gridcolor: '#e8e8e8',
        },
        yaxis: {
            title: { text: 'Gene-Overlap Cluster' },
            showgrid: true,
            gridcolor: '#e8e8e8',
            dtick: 1,
        },
        hovermode: 'closest',
        legend: { font: { size: 10 } },
    };

    const config = {
        responsive: false,
        displayModeBar: true,
        displaylogo: false,
        modeBarButtonsToRemove: ['lasso2d', 'select2d'],
    };

    Plotly.newPlot('cluster-chart', traces, layout, config);

    // Observe resizes to maintain 1.25:1 aspect ratio
    _observeResize('cluster-chart', 1.25);

    // Update caption
    const captionEl = document.querySelector('#genomics-charts-section .chart-panel:last-of-type .chart-caption');
    if (captionEl) {
        const organ = (data.organ || '').charAt(0).toUpperCase() + (data.organ || '').slice(1);
        const sex = (data.sex || '').charAt(0).toUpperCase() + (data.sex || '').slice(1);
        captionEl.textContent =
            `${points.length} GO Biological Process categories from the ${organ} (${sex}) analysis ` +
            `plotted by BMD value (x-axis, log scale) against hierarchical gene-overlap cluster ` +
            `assignment (y-axis). Marker size reflects the number of genes with BMD values. ` +
            `Points are colored by UMAP semantic cluster (same palette as the semantic map above). ` +
            `Categories are clustered on the y-axis by Jaccard similarity of their gene sets ` +
            `(${nGeneClusters} cluster${nGeneClusters !== 1 ? 's' : ''}).`;
    }
}
