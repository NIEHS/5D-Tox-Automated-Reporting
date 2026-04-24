// genomics.js — Genomics results cards, BMD summary tables, narrative generation
//
// Extracted from main.js.  Contains all functions related to genomics CSV
// processing, genomics results card rendering, BMD summary table rendering,
// and genomics narrative generation/approve/edit/retry workflows.
//
// Dependencies (globals from other files):
//   - state.js:   genomicsResults, bmdSummaryEndpoints, bmdSummaryApproved,
//                  reportSettings, currentIdentity, uploadedFiles, tabbedViewActive,
//                  methodsData, summaryParagraphs
//   - settings.js: _bmdStatLabel, _flattenGeneSets, applySettings
//   - layout.js:  buildTabBar
//   - utils.js:   escapeHtml, showError, showToast, show, hide,
//                  showBlockingSpinner, hideBlockingSpinner, autoResizeTextarea
//   - main.js:    markReportDirty, updateExportButton, postApproveToServer,
//                  unlockSection, setButtons, showSummarySection, apiFetch

/* ----------------------------------------------------------------
 * Genomics section containers — one panel per organ
 *
 * In the sidebar layout, genomics results are split into two
 * document-level sections: Gene Set BMD Analysis and Gene BMD
 * Analysis.  Each organ gets one panel in each section; male and
 * female data for that organ are combined into a single sex-grouped
 * table inside the panel, mirroring the PDF layout (NIEHS Tables
 * 9-12).
 *
 * Per-{organ,sex} editing controls (approve, retry, narrative,
 * config) still exist — they live inside a collapsible "Section
 * Config & Editing" block at the bottom of each organ panel so the
 * existing per-section approval flow keeps working without backend
 * changes.
 * ---------------------------------------------------------------- */

/**
 * Ensure panels exist for the given organ in both the Gene Set and
 * Gene BMD sections.  Creates the panels with their internal display
 * + controls structure on the first call; returns the panels for
 * subsequent population.  Idempotent — called once per
 * {organ, sex}, hits the already-created panels on the second call.
 *
 * Also adds a per-organ leaf to the sidebar TOC under the Gene Set
 * and Gene BMD parents.
 *
 * @param {string} organ — organ name (lowercase)
 * @returns {{geneSetPanel: HTMLElement, geneBmdPanel: HTMLElement}}
 */
function ensureGenomicsOrganPanels(organ) {
    const organKey = organ.toLowerCase();
    const organTitle = organKey.charAt(0).toUpperCase() + organKey.slice(1);

    // Each panel has a dedicated structure:
    //   .organ-display   — combined sex-grouped table + descriptions
    //                      (rebuilt every time data arrives for either sex)
    //   .organ-charts    — inline UMAP + cluster scatter charts per sex
    //                      (gene-set panel only; populated by chart code)
    //   .organ-controls  — collapsible holding the per-{organ,sex} cards
    //                      (approval/edit/narrative) so per-sex editing
    //                      stays available without cluttering the panel
    function makePanel(parentContainerId, kind, organ, organTitle) {
        const panelId = `genomics-${kind}-organ-${organ}`;
        let panel = document.getElementById(panelId);
        if (panel) return panel;

        panel = document.createElement('div');
        panel.id = panelId;
        panel.className = 'genomics-organ-panel';
        panel.setAttribute('data-organ', organ);
        // Charts block only emitted for the gene-set side — the gene-bmd
        // section in the PDF doesn't get inline charts (see task #60).
        const chartsBlock = kind === 'gene-set'
            ? `<div class="organ-charts" id="genomics-${kind}-charts-${organ}"></div>`
            : '';
        panel.innerHTML = `
            <h3>${organTitle}</h3>
            <div class="organ-display" id="genomics-${kind}-display-${organ}"></div>
            ${chartsBlock}
            <details class="organ-controls">
                <summary>Section Config &amp; Editing</summary>
                <div class="organ-cards" id="genomics-${kind}-cards-${organ}"></div>
            </details>
        `;
        const parent = document.getElementById(parentContainerId);
        if (parent) parent.appendChild(panel);
        return panel;
    }

    const geneSetPanel = makePanel('genomics-gene-set-cards', 'gene-set', organKey, organTitle);
    const geneBmdPanel = makePanel('genomics-gene-bmd-cards', 'gene-bmd', organKey, organTitle);

    // --- Sidebar TOC leaves (one per organ, deduped) ---
    // Same logic as before: each organ gets a single leaf under both
    // gene-set and gene-bmd parents.  Data arrives per-{organ,sex} so
    // this runs twice per organ; the dedup check skips the second.
    const tocGeneSetList = document.getElementById('toc-gene-set-children');
    if (tocGeneSetList && !tocGeneSetList.querySelector(`[data-organ="${organKey}"]`)) {
        const li = document.createElement('li');
        li.setAttribute('data-organ', organKey);
        li.innerHTML = `<a class="toc-leaf" onclick="navigateToNode('gene-set-${organKey}')">${organTitle}</a>`;
        tocGeneSetList.appendChild(li);
    }
    const tocGeneBmdList = document.getElementById('toc-gene-bmd-children');
    if (tocGeneBmdList && !tocGeneBmdList.querySelector(`[data-organ="${organKey}"]`)) {
        const li = document.createElement('li');
        li.setAttribute('data-organ', organKey);
        li.innerHTML = `<a class="toc-leaf" onclick="navigateToNode('gene-bmd-${organKey}')">${organTitle}</a>`;
        tocGeneBmdList.appendChild(li);
    }

    // Set Alpine store flags so sections become visible
    if (typeof Alpine !== 'undefined' && Alpine.store('app')) {
        Alpine.store('app').ready.geneSets = true;
        Alpine.store('app').ready.geneBmd = true;
    }

    return { geneSetPanel, geneBmdPanel };
}

/* ----------------------------------------------------------------
 * Genomics CSV upload and processing
 * ---------------------------------------------------------------- */

/* (Old CSV upload handlers, createCsvCard, removeCsvCard deleted —
   CSV uploads now go through the unified file pool.) */

/**
 * Process a CSV file through the genomics pipeline.
 *
 * Called from autoProcessPool() with organ and sex derived from
 * fingerprint data.  Uses the file's server-side ID from the
 * uploadedFiles pool.  Creates gene set and gene ranking tables.
 *
 * @param {string} fileId — the file pool ID (key in uploadedFiles)
 * @param {string} organ  — organ name (e.g. "liver", "kidney")
 * @param {string} sex    — "male" or "female"
 */
async function processCsv(fileId, organ, sex) {
    // Look up the server-side CSV ID from the upload pool
    const file = uploadedFiles[fileId];
    const serverCsvId = file?.id || fileId;

    showBlockingSpinner('Processing genomics...');
    try {
        const compound = currentIdentity?.name || 'Test Compound';
        const resp = await fetch('/api/process-genomics', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                csv_id: serverCsvId,
                organ: organ,
                sex: sex,
                compound_name: compound,
                dose_unit: 'mg/kg',
            }),
        });
        const result = await resp.json();

        if (result.error) {
            showError(result.error);
            return;
        }

        // Store the result keyed by organ_sex
        const key = `${organ}_${sex}`;
        genomicsResults[key] = {
            ...result,
            fileId: fileId,
            approved: false,
        };

        // Create a genomics results card
        const csvLabels = {};
        for (const s of (reportSettings.bmd_stats || ['median'])) {
            csvLabels[s] = _bmdStatLabel(s);
        }
        createGenomicsCard(key, result, organ, sex, csvLabels);

        // Show genomics results sections via Alpine store
        if (typeof Alpine !== 'undefined' && Alpine.store('app')) {
            Alpine.store('app').ready.geneSets = true;
            Alpine.store('app').ready.geneBmd = true;
        }
        markReportDirty();

        // Also show the summary section now that we have genomics
        showSummarySection();

    } catch (e) {
        showError('Genomics processing failed: ' + e.message);
    } finally {
        hideBlockingSpinner();
    }
}

/**
 * Create a card showing the genomics analysis results for one
 * organ × sex combination.  Displays the top 10 gene sets and
 * top 10 genes as HTML tables with approve/retry buttons.
 */
// Format a numeric value to fixed decimals, handling Java NaN/Infinity
// strings that survive JSON serialization from BMDExpress.
function _fmtNum(val, decimals = 3) {
    if (val == null) return '\u2013';
    const n = Number(val);
    if (!isFinite(n)) return '\u2013';
    return n.toFixed(decimals);
}

function createGenomicsCard(key, data, organ, sex, statLabels) {
    // Ensure the per-organ panels exist in both the Gene Set and Gene
    // BMD sections.  Idempotent — second call for the same organ
    // hits the existing panels.
    ensureGenomicsOrganPanels(organ);

    const organKey = organ.toLowerCase();
    const sexKey = sex.toLowerCase();
    const sexTitle = sexKey.charAt(0).toUpperCase() + sexKey.slice(1);

    // Slim per-{organ,sex} card lives in the per-organ panel's "Section
    // Config & Editing" collapsible.  The actual data table is rendered
    // by _rebuildOrganDisplays into the per-organ display block above
    // so male and female render together as one sex-grouped table
    // (mirrors PDF layout).  Calling _upsertPerSexConfigCard for both
    // 'gene-set' and 'gene-bmd' keeps the per-section approval flow on
    // both sides.
    _upsertPerSexConfigCard(key, data, organKey, sexKey, sexTitle, 'gene-set');
    _upsertPerSexConfigCard(key, data, organKey, sexKey, sexTitle, 'gene-bmd');

    _rebuildOrganDisplays(organKey, statLabels);
}


/* ----------------------------------------------------------------
 * Per-{organ,sex} config card — header + config + narrative
 *
 * This is the editing surface that survives the per-organ
 * restructure.  Each card contains:
 *   - Approve / Edit / Try Again buttons (per-section approval)
 *   - Collapsible section config (title, caption, compound, dose)
 *   - Narrative textarea + Generate button
 *
 * The card is appended into the per-organ panel's "Section Config &
 * Editing" collapsible so per-sex editing stays available without
 * cluttering the table view that mirrors the PDF.  Gene-bmd kind
 * gets a minimal header-only card (no inputs) since the editing
 * surface lives on the gene-set side.
 * ---------------------------------------------------------------- */
function _upsertPerSexConfigCard(key, data, organKey, sexKey, sexTitle, kind) {
    const organTitle = organKey.charAt(0).toUpperCase() + organKey.slice(1);
    const cardId = kind === 'gene-set' ? `genomics-card-${key}` : `genomics-gene-bmd-card-${key}`;
    const containerId = `genomics-${kind}-cards-${organKey}`;
    const container = document.getElementById(containerId);
    if (!container) return;

    // Replace any previous incarnation of this card (re-processing the
    // same key produces a fresh card)
    const existing = document.getElementById(cardId);
    if (existing) existing.remove();

    const card = document.createElement('div');
    card.className = 'bm2-card';
    card.id = cardId;

    if (kind === 'gene-set') {
        const defaultTitle = `Gene Expression — ${organTitle}`;
        const defaultCaption = `Summary of Gene Expression Findings in ${organTitle} of {sex} Rats Administered {compound} for Five Days`;
        const compoundName = currentIdentity?.name || '';
        // No narrative textarea here — the per-organ findings paragraph
        // is server-derived (see genomics_narratives.py) and rendered
        // above the organ's table by _rebuildOrganDisplays.  Keeping
        // only the per-{organ,sex} approval + title/caption/compound/
        // dose-unit inputs so per-sex approve/edit/retry still works.
        card.innerHTML = `
            <div class="card-header">
                <span class="filename">${escapeHtml(sexTitle)}
                    (${data.total_responsive_genes || 0} responsive genes)</span>
                <div class="card-actions">
                    <button class="btn-small approve" id="btn-approve-genomics-${key}"
                            onclick="approveGenomics('${key}')">Approve</button>
                    <button class="btn-small" id="btn-edit-genomics-${key}"
                            onclick="editGenomics('${key}')" style="display:none">Edit</button>
                    <button class="btn-small" id="btn-retry-genomics-${key}"
                            onclick="retryGenomics('${key}')" style="display:none">Try Again</button>
                    <span class="approved-badge" id="badge-genomics-${key}"
                          style="display:none">Approved</span>
                    <span class="stale-badge" id="stale-badge-genomics-${key}"
                          style="display:none">Data Changed — Re-process</span>
                </div>
            </div>
            <details class="card-config-collapse">
                <summary>Section Config</summary>
                <div class="card-fields">
                    <div class="form-group">
                        <label>Section Title</label>
                        <input type="text" id="genomics-title-${key}"
                            value="${escapeHtml(defaultTitle)}">
                    </div>
                    <div class="form-group">
                        <label>Table Caption</label>
                        <input type="text" id="genomics-caption-${key}"
                            value="${escapeHtml(defaultCaption)}">
                    </div>
                    <div class="form-group">
                        <label>Compound Name</label>
                        <input type="text" id="genomics-compound-${key}"
                            placeholder="e.g., PFHxSAm"
                            value="${escapeHtml(compoundName)}">
                    </div>
                    <div class="form-group">
                        <label>Dose Unit</label>
                        <input type="text" id="genomics-unit-${key}" value="mg/kg">
                    </div>
                </div>
            </details>
        `;
    } else {
        // Gene-BMD side: minimal header card.  The actual gene table
        // is rendered in the per-organ display block above.
        card.innerHTML = `
            <div class="card-header">
                <span class="filename">${escapeHtml(sexTitle)} — Gene BMD
                    (${(data.top_genes || []).length} genes shown)</span>
            </div>
        `;
    }

    container.appendChild(card);
}


/* ----------------------------------------------------------------
 * Section intro paragraphs — methodology + interpretation caveat
 *
 * The Gene Set and Gene BMD sections each carry two boilerplate
 * paragraphs at the top (NIEHS Report 10 p. 19 / p. 26).  They're
 * built deterministically by `methods_report.build_gene_set_body_intro`
 * / `build_gene_body_intro` on the server and travel in the
 * `intros` field of each narrative dict.  Independent of per-organ
 * data — they describe the statistic choice and the caveat about
 * over-interpreting the gene sets, so they belong at the section
 * level, not the organ panel level.
 *
 * Rendered into static slots in index.html (`#genomics-gene-set-intro`
 * and `#genomics-gene-bmd-intro`) so they render exactly once per
 * section, regardless of how many organs are present.
 * ---------------------------------------------------------------- */

/**
 * Render the two intro paragraphs for each genomics section.  Safe to
 * call whenever `genomicsGeneSetNarrative` / `genomicsGeneNarrative`
 * changes — idempotent, overwrites innerHTML on each call.
 */
function _rebuildGenomicsIntros() {
    const slots = [
        ['genomics-gene-set-intro', genomicsGeneSetNarrative],
        ['genomics-gene-bmd-intro', genomicsGeneNarrative],
    ];
    for (const [slotId, narr] of slots) {
        const slot = document.getElementById(slotId);
        if (!slot) continue;
        const intros = (narr && Array.isArray(narr.intros)) ? narr.intros : [];
        if (intros.length === 0) {
            slot.innerHTML = '';
            continue;
        }
        slot.innerHTML = intros
            .map(p => `<p>${escapeHtml(p)}</p>`)
            .join('');
    }
}


/* ----------------------------------------------------------------
 * Per-organ combined display — mirrors the PDF table layout
 *
 * Reads the latest genomicsResults entries for both sexes of an
 * organ and rebuilds:
 *   - Sex-grouped gene-set table (Male rows then Female rows)
 *   - Combined deduped GO descriptions
 *   - Sex-grouped gene-BMD table
 *   - Combined deduped gene descriptions
 *
 * Idempotent — overwrites the display content rather than appending,
 * so re-processing produces a clean result.
 * ---------------------------------------------------------------- */
function _rebuildOrganDisplays(organKey, statLabels) {
    const maleData = genomicsResults[`${organKey}_male`] || null;
    const femaleData = genomicsResults[`${organKey}_female`] || null;

    // Per-organ findings paragraph — server-derived, read-only.  Shared
    // with the PDF: the same `by_organ[organ]` dict that Typst renders
    // above each organ's table is what we display here.  Missing means
    // the assembler couldn't build it (e.g., no dose groups yet) — we
    // silently skip rather than showing an empty block.
    const gsPara = genomicsGeneSetNarrative?.by_organ?.[organKey] || '';
    const gnPara = genomicsGeneNarrative?.by_organ?.[organKey]    || '';

    const _findingsHtml = (text) => text
        ? `<p class="organ-findings">${escapeHtml(text)}</p>`
        : '';

    const gsDisplay = document.getElementById(`genomics-gene-set-display-${organKey}`);
    if (gsDisplay) {
        gsDisplay.innerHTML =
            _findingsHtml(gsPara) +
            _buildSexGroupedGeneSetTableHtml(maleData, femaleData, statLabels) +
            _buildCombinedGoDescriptionsHtml(maleData, femaleData);
    }

    const gbDisplay = document.getElementById(`genomics-gene-bmd-display-${organKey}`);
    if (gbDisplay) {
        gbDisplay.innerHTML =
            _findingsHtml(gnPara) +
            _buildSexGroupedGeneTableHtml(maleData, femaleData) +
            _buildCombinedGeneDescriptionsHtml(maleData, femaleData);
    }

    // Inline SVG charts — same Plotly figures the server rasterises as
    // PNG for the PDF.  See `genomics_viz.render_chart_images` for the
    // shared render path.  Only the gene-set side gets charts; the
    // gene-bmd side has no corresponding visualization in the PDF.
    _rebuildOrganCharts(organKey);
}


/* ----------------------------------------------------------------
 * Inline chart rendering — same Plotly figures as the PDF
 *
 * The server already renders UMAP + cluster scatter charts once per
 * organ×sex in `genomics_viz.render_chart_images` and returns both
 * PNG (for PDF) and SVG (for HTML) encodings of the same figures.
 * Rendering is done entirely server-side so the HTML in-app view and
 * the PDF export derive from the same graphics primitives.
 *
 * We inject the SVGs directly into the per-organ panel's
 * `.organ-charts` slot.  Plotly's SVG IDs are namespaced per chart
 * by `genomics_viz._namespace_svg_ids` so multiple SVGs can coexist
 * in the same DOM without clip-path collisions.
 * ---------------------------------------------------------------- */

/**
 * Rebuild the inline chart SVGs + cluster summaries inside a per-organ
 * panel's `.organ-charts` slot.  One block per sex present for this
 * organ in the chart cache.
 *
 * Idempotent — overwrites innerHTML rather than appending.  Falls
 * back silently when chartImagesCache is empty (e.g., the session
 * hasn't been re-processed since SVGs were added to the payload).
 */
function _rebuildOrganCharts(organKey) {
    const slot = document.getElementById(`genomics-gene-set-charts-${organKey}`);
    if (!slot) return;
    if (!chartImagesCache || !Array.isArray(chartImagesCache)) {
        slot.innerHTML = '';
        return;
    }

    // Filter to this organ, then iterate sexes in display order.  The
    // cache entries carry raw SVG text — no data-URL wrapping needed.
    const entries = chartImagesCache.filter(
        c => (c.organ || '').toLowerCase() === organKey
    );
    if (entries.length === 0) {
        slot.innerHTML = '';
        return;
    }

    // Deterministic sex order: Male then Female.  Falls back to the
    // cache's natural order for any other sex keys so we don't drop data.
    const sexOrder = (s) => ({male: 0, female: 1}[(s || '').toLowerCase()] ?? 2);
    entries.sort((a, b) => sexOrder(a.sex) - sexOrder(b.sex));

    slot.innerHTML = entries.map(_organChartBlockHtml).join('');
}

/**
 * HTML for one sex's chart block: UMAP + cluster scatter + cluster
 * summary table.  Captions come from the server payload so the HTML
 * and PDF carry identical prose under each figure.
 *
 * The `organ-chart-figure` wrapper fixes the SVG to a reasonable
 * display size via CSS (the SVG itself has an intrinsic viewBox, so
 * the browser scales without rasterization loss).
 */
function _organChartBlockHtml(entry) {
    const sexTitle = (entry.sex || '').charAt(0).toUpperCase()
                   + (entry.sex || '').slice(1);
    const umapSvg    = entry.umap_svg    || '';
    const clusterSvg = entry.cluster_svg || '';
    const umapCap    = entry.umap_caption    || '';
    const clusterCap = entry.cluster_caption || '';
    const summary    = entry.cluster_summary || [];

    // Summary table — same shape as the standalone page, kept here so
    // the per-sex block is self-contained.
    let summaryHtml = '';
    if (summary.length > 0) {
        const rows = summary.map(r => {
            const sourceNote = r.source === 'enrichr' ? '' : ' <em>(internal)</em>';
            const terms = (r.terms || []).join('; ');
            return `<tr><td>${escapeHtml(String(r.cluster))}</td>` +
                   `<td>${r.n_genes || 0}</td>` +
                   `<td>${escapeHtml(terms)}${sourceNote}</td></tr>`;
        }).join('');
        summaryHtml = `
            <details class="cluster-summary-block">
                <summary>Cluster biology summary (Enrichr)</summary>
                <table class="cluster-summary-table">
                    <thead><tr><th>Cluster</th><th>Genes</th>
                        <th>Top Enriched Terms</th></tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </details>`;
    }

    // Note: SVG is injected as raw markup — safe because it came from
    // our own server, and the IDs are already namespaced to prevent
    // cross-chart collisions.
    return `
        <div class="organ-chart-pair" data-sex="${escapeHtml(entry.sex || '')}">
            <h4>${escapeHtml(sexTitle)}</h4>
            <div class="organ-chart-figures">
                <figure class="organ-chart-figure">
                    <div class="organ-chart-svg">${umapSvg}</div>
                    <figcaption>${escapeHtml(umapCap)}</figcaption>
                </figure>
                <figure class="organ-chart-figure">
                    <div class="organ-chart-svg">${clusterSvg}</div>
                    <figcaption>${escapeHtml(clusterCap)}</figcaption>
                </figure>
            </div>
            ${summaryHtml}
        </div>`;
}


/* ----------------------------------------------------------------
 * Sex-grouped table builders — mirror the PDF sex-grouped-table
 *
 * The PDF emits one table per organ with bold "Male" / "Female"
 * row-group headers separating the male and female ranked rows.
 * These produce the equivalent HTML — a single <table> per organ
 * with full-width "Male" / "Female" header rows between the per-sex
 * blocks.
 * ---------------------------------------------------------------- */
function _buildSexGroupedGeneSetTableHtml(maleData, femaleData, statLabels) {
    const refData = maleData || femaleData;
    if (!refData) return '';

    const byStatMap = refData.gene_sets_by_stat || {};
    const statKeys = Object.keys(byStatMap);

    // Legacy flat-list fallback — a handful of pre-2026-04 cached
    // sessions were saved before the pipeline started emitting
    // `gene_sets_by_stat`.  Those sessions only have a flat `gene_sets`
    // array on each sex-keyed entry, which is strictly one-sex-at-a-
    // time (nothing to group).  Render both sexes in sequence with
    // their own header row so the structure still reads as two blocks;
    // no attempt to share column widths across them because each sex
    // ran through the statistic filter independently.
    if (statKeys.length === 0) {
        const maleSets = (maleData && maleData.gene_sets) || [];
        const femaleSets = (femaleData && femaleData.gene_sets) || [];
        if (maleSets.length === 0 && femaleSets.length === 0) {
            return '<p style="color:#6c757d; font-size:0.85rem">No qualifying gene sets found.</p>';
        }
        return `
            <h4>Top Gene Sets (by BMD)</h4>
            <table>
                <tr><th>GO Term</th><th>GO ID</th><th>BMD Median</th>
                    <th>BMDL Median</th><th># Genes</th><th>Direction</th></tr>
                ${maleSets.length > 0 ? `<tr><td colspan="6" class="sex-row-header"><b>Male</b></td></tr>` : ''}
                ${maleSets.map(_geneSetRowHtml).join('')}
                ${femaleSets.length > 0 ? `<tr><td colspan="6" class="sex-row-header"><b>Female</b></td></tr>` : ''}
                ${femaleSets.map(_geneSetRowHtml).join('')}
            </table>`;
    }

    // One sex-grouped table per stat (typically just one stat)
    let out = '';
    for (const stat of statKeys) {
        const label = (statLabels && statLabels[stat]) || _bmdStatLabel(stat);
        const maleSets = (maleData && (maleData.gene_sets_by_stat || {})[stat]) || [];
        const femaleSets = (femaleData && (femaleData.gene_sets_by_stat || {})[stat]) || [];

        if (maleSets.length === 0 && femaleSets.length === 0) {
            out += `<h4>Gene Sets — BMD ${escapeHtml(label)}</h4>
                <p style="color:#6c757d; font-size:0.85rem">No qualifying gene sets for this statistic.</p>`;
            continue;
        }

        out += `
            <h4>Gene Sets — BMD ${escapeHtml(label)}</h4>
            <table>
                <tr><th>GO Term</th><th>GO ID</th><th>BMD ${escapeHtml(label)}</th>
                    <th>BMDL ${escapeHtml(label)}</th><th># Genes</th><th>Direction</th></tr>
                ${maleSets.length > 0 ? `<tr><td colspan="6" class="sex-row-header"><b>Male</b></td></tr>` : ''}
                ${maleSets.map(_geneSetRowHtml).join('')}
                ${femaleSets.length > 0 ? `<tr><td colspan="6" class="sex-row-header"><b>Female</b></td></tr>` : ''}
                ${femaleSets.map(_geneSetRowHtml).join('')}
            </table>`;
    }
    return out;
}

function _geneSetRowHtml(gs) {
    return `
        <tr>
            <td>${escapeHtml(gs.go_term)}</td>
            <td>${escapeHtml(gs.go_id)}</td>
            <td class="bmd-col">${_fmtNum(gs.bmd != null ? gs.bmd : gs.bmd_median)}</td>
            <td class="bmd-col">${_fmtNum(gs.bmdl != null ? gs.bmdl : gs.bmdl_median)}</td>
            <td>${gs.n_genes || 0}</td>
            <td>${escapeHtml(gs.direction || '')}</td>
        </tr>`;
}

function _buildSexGroupedGeneTableHtml(maleData, femaleData) {
    const maleGenes = (maleData && maleData.top_genes) || [];
    const femaleGenes = (femaleData && femaleData.top_genes) || [];
    if (maleGenes.length === 0 && femaleGenes.length === 0) {
        return '<p style="color:#6c757d; font-size:0.85rem">No qualifying genes found.</p>';
    }
    return `
        <h4>Top Genes (by BMD)</h4>
        <table>
            <tr><th>Gene</th><th>BMD</th><th>BMDL</th>
                <th>Fold Change</th><th>Direction</th></tr>
            ${maleGenes.length > 0 ? `<tr><td colspan="5" class="sex-row-header"><b>Male</b></td></tr>` : ''}
            ${maleGenes.map(_geneRowHtml).join('')}
            ${femaleGenes.length > 0 ? `<tr><td colspan="5" class="sex-row-header"><b>Female</b></td></tr>` : ''}
            ${femaleGenes.map(_geneRowHtml).join('')}
        </table>`;
}

function _geneRowHtml(g) {
    return `
        <tr>
            <td class="endpoint-label"><i>${escapeHtml(g.gene_symbol || '')}</i></td>
            <td class="bmd-col">${_fmtNum(g.bmd)}</td>
            <td class="bmd-col">${_fmtNum(g.bmdl)}</td>
            <td>${_fmtNum(g.fold_change, 2)}</td>
            <td>${escapeHtml(g.direction || '')}</td>
        </tr>`;
}

function _buildCombinedGoDescriptionsHtml(maleData, femaleData) {
    // Merge GO descriptions from both sexes, dedupe by go_id (the
    // same GO term often appears in both top-N lists).  Same dedupe
    // logic as the PDF gene-set loop.
    const seen = new Set();
    const merged = [];
    for (const data of [maleData, femaleData]) {
        if (!data || !data.go_descriptions) continue;
        for (const d of data.go_descriptions) {
            if (!d.definition) continue;
            const id = d.go_id || '';
            if (seen.has(id)) continue;
            seen.add(id);
            merged.push(d);
        }
    }
    if (merged.length === 0) return '';
    const entries = merged
        .map(d => `<p><b>${escapeHtml(d.go_id)} ${escapeHtml(d.name)}</b>: ${escapeHtml(d.definition)}</p>`)
        .join('');
    return `
        <details class="descriptions-block">
            <summary>GO Term Descriptions (${merged.length})</summary>
            <div class="descriptions-content">${entries}</div>
        </details>`;
}

function _buildCombinedGeneDescriptionsHtml(maleData, femaleData) {
    const seen = new Set();
    const merged = [];
    for (const data of [maleData, femaleData]) {
        if (!data || !data.gene_descriptions) continue;
        for (const d of data.gene_descriptions) {
            if (!(d.description || d.name)) continue;
            const sym = d.gene_symbol || '';
            if (seen.has(sym)) continue;
            seen.add(sym);
            merged.push(d);
        }
    }
    if (merged.length === 0) return '';
    const entries = merged
        .map(d => {
            const desc = d.description || d.name || '';
            return `<p><b><i>${escapeHtml(d.gene_symbol)}</i></b>: ${escapeHtml(desc)}</p>`;
        })
        .join('');
    return `
        <details class="descriptions-block">
            <summary>Gene Descriptions (${merged.length})</summary>
            <div class="descriptions-content">${entries}</div>
        </details>`;
}




/**
 * Approve a genomics card — sends data to the server.
 *
 * The per-organ findings paragraph is server-derived (see
 * `genomics_narratives.build_genomics_body_narratives`) and is not
 * stored in the per-{organ,sex} approval payload.  It round-trips
 * through the process-integrated response and is rebuilt on export,
 * so the approval flow doesn't need to persist it.
 */
async function approveGenomics(key) {
    const data = genomicsResults[key];
    if (!data) return;

    const result = await postApproveToServer(
        'genomics',
        document.getElementById(`genomics-card-${key}`),
        `genomics-${key}`,
        {
            organ: data.organ,
            sex: data.sex,
            gene_sets: _flattenGeneSets(data),
            gene_sets_by_stat: data.gene_sets_by_stat || null,
            top_genes: data.top_genes,
            go_descriptions: data.go_descriptions || [],
            gene_descriptions: data.gene_descriptions || [],
            total_responsive_genes: data.total_responsive_genes,
            csv_id: data.fileId ? (uploadedFiles[data.fileId]?.id || data.fileId) : data.csv_id,
        },
    );
    if (!result) return;

    genomicsResults[key].approved = true;
}

function editGenomics(key) {
    genomicsResults[key].approved = false;
    markReportDirty();
    const card = document.getElementById(`genomics-card-${key}`);
    unlockSection(card);
    setButtons(`genomics-${key}`, 'editing');
    updateExportButton();
}

async function retryGenomics(key) {
    // Re-run the processing pipeline with current settings to rebuild
    // genomics cards.  Delegates to applySettings() which does a clean
    // fetch + rebuild of both apical and genomics sections.
    markReportDirty();
    await applySettings();
}

/* ----------------------------------------------------------------
 * BMD Summary — auto-populated from approved .bm2 sections
 * ---------------------------------------------------------------- */

/**
 * Fetch the BMD summary from the server and display it as a table.
 * Called after any .bm2 section is approved.
 */
async function loadBmdSummary() {
    if (!currentIdentity?.dtxsid) return;

    try {
        const resp = await fetch(`/api/session/${currentIdentity.dtxsid}/bmd-summary`);
        const result = await resp.json();

        if (result.endpoints && result.endpoints.length > 0) {
            bmdSummaryEndpoints = result.endpoints;
            renderBmdSummaryTable(result.endpoints);
            if (typeof Alpine !== 'undefined' && Alpine.store('app')) {
                Alpine.store('app').ready.bmdSummary = true;
            }
            markReportDirty();
        }
    } catch (e) {
        // BMD summary is optional — don't show error
        console.warn('BMD summary load failed:', e);
    }
}

/**
 * Render the BMD summary as an HTML table in the preview area.
 */
function renderBmdSummaryTable(endpoints) {
    const container = document.getElementById('bmd-summary-table');

    // Group by sex
    const male = endpoints.filter(e => e.sex === 'Male');
    const female = endpoints.filter(e => e.sex === 'Female');

    let html = `<table>
        <tr>
            <th>Endpoint</th>
            <th>BMD₁Std</th>
            <th>BMDL₁Std</th>
            <th>LOEL</th>
            <th>NOEL</th>
            <th>Direction</th>
        </tr>`;

    for (const [sexLabel, sexData] of [['Male', male], ['Female', female]]) {
        if (sexData.length === 0) continue;
        html += `<tr><td colspan="6" style="font-weight:bold; background:#f1f5f9">${sexLabel}</td></tr>`;
        for (const ep of sexData) {
            const fmtVal = (v) => v == null ? '—' : typeof v === 'number' ? v.toFixed(2) : String(v);
            html += `<tr>
                <td class="endpoint-label">${ep.endpoint}</td>
                <td class="bmd-col">${fmtVal(ep.bmd)}</td>
                <td class="bmd-col">${fmtVal(ep.bmdl)}</td>
                <td>${fmtVal(ep.loel)}</td>
                <td>${fmtVal(ep.noel)}</td>
                <td>${ep.direction || ''}</td>
            </tr>`;
        }
    }
    html += '</table>';

    // Footnotes matching NIEHS reference report conventions.
    // Explains abbreviations and notes the BMDExpress 3 vs BMDS 2.7.0 tool
    // difference so users understand why values may not exactly match
    // published NIEHS reports that used pybmds.
    html += `<div style="font-size:0.75rem; color:#64748b; margin-top:0.75rem; line-height:1.6; border-top:1px solid #e2e8f0; padding-top:0.5rem;">
        <p>BMD<sub>1Std</sub> = benchmark dose corresponding to a benchmark response set to one standard deviation from the mean;
        BMDL<sub>1Std</sub> = benchmark dose lower confidence limit corresponding to a benchmark response set to one standard deviation from the mean;
        LOEL = lowest-observed-effect level; NOEL = no-observed-effect level.</p>
        <p style="margin-top:0.25rem;">
        <b>NVM</b> = nonviable model (model completed but failed acceptability criteria);
        <b>UREP</b> = unreliable estimate of potency (BMD<sub>U</sub>/BMD<sub>L</sub> &gt; 40 or BMD below lower limit of extrapolation);
        <b>NA</b> = not applicable; <b>—</b> = not determined.</p>
        <p style="margin-top:0.25rem;">
        BMD modeling performed using BMDExpress 3 (Java native API). Values may differ from reports using BMDS 2.7.0 (pybmds)
        due to differences in model repertoire, model selection criteria, and outlier handling.</p>
    </div>`;

    container.innerHTML = html;
}

/**
 * Render the BMDS (pybmds) BMD summary as an HTML table.
 *
 * Same structure as renderBmdSummaryTable() but adds a "Model" column
 * showing which BMDS model was selected (e.g., "Hill", "Exponential 5").
 * This table matches the NIEHS reference report methodology (EPA BMDS).
 */
function renderBmdSummaryTableBmds(endpoints) {
    const container = document.getElementById('bmd-summary-bmds-table');

    // Group by sex
    const male = endpoints.filter(e => e.sex === 'Male');
    const female = endpoints.filter(e => e.sex === 'Female');

    let html = `<table>
        <tr>
            <th>Endpoint</th>
            <th>BMD₁Std</th>
            <th>BMDL₁Std</th>
            <th>Model</th>
            <th>LOEL</th>
            <th>NOEL</th>
            <th>Direction</th>
        </tr>`;

    for (const [sexLabel, sexData] of [['Male', male], ['Female', female]]) {
        if (sexData.length === 0) continue;
        html += `<tr><td colspan="7" style="font-weight:bold; background:#f1f5f9">${sexLabel}</td></tr>`;
        for (const ep of sexData) {
            const fmtVal = (v) => v == null ? '—' : typeof v === 'number' ? v.toFixed(2) : String(v);
            html += `<tr>
                <td class="endpoint-label">${ep.endpoint}</td>
                <td class="bmd-col">${fmtVal(ep.bmd)}</td>
                <td class="bmd-col">${fmtVal(ep.bmdl)}</td>
                <td style="font-size:0.8rem; color:#64748b">${ep.model_name || '—'}</td>
                <td>${fmtVal(ep.loel)}</td>
                <td>${fmtVal(ep.noel)}</td>
                <td>${ep.direction || ''}</td>
            </tr>`;
        }
    }
    html += '</table>';

    // Footnotes for the BMDS table
    html += `<div style="font-size:0.75rem; color:#64748b; margin-top:0.75rem; line-height:1.6; border-top:1px solid #e2e8f0; padding-top:0.5rem;">
        <p>BMD<sub>1Std</sub> = benchmark dose (1 SD BMR relative to control);
        BMDL<sub>1Std</sub> = lower confidence limit;
        LOEL = lowest-observed-effect level; NOEL = no-observed-effect level.</p>
        <p style="margin-top:0.25rem;">
        <b>NVM</b> = nonviable model; <b>UREP</b> = unreliable estimate of potency;
        <b>NR</b> = not reportable (BMD &lt; &frac13; lowest nonzero dose); <b>—</b> = not determined.</p>
        <p style="margin-top:0.25rem;">
        BMD modeling performed using EPA BMDS via pybmds. Models: Linear, Polynomial 2°–N°, Power, Hill,
        Exponential M3/M5. Model selection follows EPA guidance (lowest AIC among viable models).</p>
    </div>`;

    container.innerHTML = html;
}
