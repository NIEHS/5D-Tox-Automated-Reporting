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

        // Show genomics results section
        show('genomics-results-section');
        show('genomics-charts-section');
        if (tabbedViewActive) buildTabBar();
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
    const cardsDiv = document.getElementById('genomics-cards');

    // Remove existing card for same key if re-processing
    const existing = document.getElementById(`genomics-card-${key}`);
    if (existing) existing.remove();

    const card = document.createElement('div');
    card.className = 'bm2-card';
    card.id = `genomics-card-${key}`;

    const organTitle = organ.charAt(0).toUpperCase() + organ.slice(1);
    const sexTitle = sex.charAt(0).toUpperCase() + sex.slice(1);

    // Build gene sets tables — one per selected BMD statistic.
    // gene_sets_by_stat is a dict keyed by stat name (e.g. "median", "mean").
    // Legacy data has a single gene_sets array (no stat key).
    let geneSetHtml = '';
    const byStatMap = data.gene_sets_by_stat || {};
    const statKeys = Object.keys(byStatMap);

    if (statKeys.length > 0) {
        // One table per statistic
        for (const stat of statKeys) {
            const sets = byStatMap[stat] || [];
            const label = (statLabels && statLabels[stat]) || _bmdStatLabel(stat);
            if (sets.length === 0) {
                geneSetHtml += `<h4>Gene Sets — BMD ${escapeHtml(label)}</h4>
                    <p style="color:#6c757d; font-size:0.85rem">No qualifying gene sets for this statistic.</p>`;
                continue;
            }
            geneSetHtml += `
                <h4>Gene Sets — BMD ${escapeHtml(label)}</h4>
                <table>
                    <tr><th>GO Term</th><th>GO ID</th><th>BMD ${escapeHtml(label)}</th>
                        <th>BMDL ${escapeHtml(label)}</th><th># Genes</th><th>%age</th><th>Direction</th></tr>
                    ${sets.map(gs => {
                        const nTotal = gs.n_genes || 0;
                        const nBmd = gs.n_genes_with_bmd || 0;
                        const pct = nTotal > 0 ? Math.round(nBmd / nTotal * 100) : 0;
                        return `
                        <tr>
                            <td>${escapeHtml(gs.go_term)}</td>
                            <td>${escapeHtml(gs.go_id)}</td>
                            <td class="bmd-col">${_fmtNum(gs.bmd)}</td>
                            <td class="bmd-col">${_fmtNum(gs.bmdl)}</td>
                            <td>${nTotal}</td>
                            <td>${pct}%</td>
                            <td>${escapeHtml(gs.direction)}</td>
                        </tr>`;
                    }).join('')}
                </table>
            `;
        }
    } else if (data.gene_sets && data.gene_sets.length > 0) {
        // Legacy single-list format
        geneSetHtml = `
            <h4>Top Gene Sets (by BMD)</h4>
            <table>
                <tr><th>GO Term</th><th>GO ID</th><th>BMD Median</th>
                    <th>BMDL Median</th><th># Genes</th><th>%age</th><th>Direction</th></tr>
                ${data.gene_sets.map(gs => {
                    const nTotal = gs.n_genes || 0;
                    const nBmd = gs.n_genes_with_bmd || gs.n_passed || 0;
                    const pct = nTotal > 0 ? Math.round(nBmd / nTotal * 100) : 0;
                    return `
                    <tr>
                        <td>${escapeHtml(gs.go_term)}</td>
                        <td>${escapeHtml(gs.go_id)}</td>
                        <td class="bmd-col">${_fmtNum(gs.bmd_median)}</td>
                        <td class="bmd-col">${_fmtNum(gs.bmdl_median)}</td>
                        <td>${nTotal}</td>
                        <td>${pct}%</td>
                        <td>${escapeHtml(gs.direction)}</td>
                    </tr>`;
                }).join('')}
            </table>
        `;
    } else {
        geneSetHtml = '<p style="color:#6c757d; font-size:0.85rem">No qualifying gene sets found.</p>';
    }

    // Build GO term descriptions collapsible block (dense 9pt, matching NIEHS)
    let goDescHtml = '';
    if (data.go_descriptions && data.go_descriptions.length > 0) {
        const entries = data.go_descriptions
            .filter(d => d.definition)
            .map(d => `<p><b>${escapeHtml(d.go_id)} ${escapeHtml(d.name)}</b>: ${escapeHtml(d.definition)}</p>`)
            .join('');
        if (entries) {
            goDescHtml = `
                <details class="descriptions-block">
                    <summary>GO Term Descriptions (${data.go_descriptions.filter(d => d.definition).length})</summary>
                    <div class="descriptions-content">${entries}</div>
                </details>`;
        }
    }

    // Build genes table HTML
    let genesHtml = '';
    if (data.top_genes && data.top_genes.length > 0) {
        genesHtml = `
            <h4>Top Genes (by BMD)</h4>
            <table>
                <tr><th>Gene</th><th>BMD</th><th>BMDL</th>
                    <th>Fold Change</th><th>Direction</th></tr>
                ${data.top_genes.map(g => `
                    <tr>
                        <td class="endpoint-label">${escapeHtml(g.gene_symbol)}</td>
                        <td class="bmd-col">${_fmtNum(g.bmd)}</td>
                        <td class="bmd-col">${_fmtNum(g.bmdl)}</td>
                        <td>${_fmtNum(g.fold_change, 2)}</td>
                        <td>${escapeHtml(g.direction)}</td>
                    </tr>
                `).join('')}
            </table>
        `;
    } else {
        genesHtml = '<p style="color:#6c757d; font-size:0.85rem">No qualifying genes found.</p>';
    }

    // Build gene descriptions collapsible block
    let geneDescHtml = '';
    if (data.gene_descriptions && data.gene_descriptions.length > 0) {
        const entries = data.gene_descriptions
            .filter(d => d.description || d.name)
            .map(d => {
                const desc = d.description || d.name || '';
                return `<p><b><i>${escapeHtml(d.gene_symbol)}</i></b>: ${escapeHtml(desc)}</p>`;
            })
            .join('');
        if (entries) {
            geneDescHtml = `
                <details class="descriptions-block">
                    <summary>Gene Descriptions (${data.gene_descriptions.filter(d => d.description || d.name).length})</summary>
                    <div class="descriptions-content">${entries}</div>
                </details>`;
        }
    }

    // Pre-populate narrative if already generated (e.g., from session restore)
    const existingNarrative = _buildGenomicsNarrativeText(data);

    card.innerHTML = `
        <div class="card-header">
            <span class="filename">${escapeHtml(organTitle)} \u2014 ${escapeHtml(sexTitle)}
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
            </div>
        </div>
        <div class="bm2-narrative-label">
            Results Narrative
            <button class="btn-small primary" id="btn-gen-narrative-${key}"
                    onclick="generateGenomicsNarrative('${key}')">Generate Narrative</button>
        </div>
        <textarea class="bm2-narrative" id="genomics-narrative-${key}" rows="4"
            placeholder="Click 'Generate Narrative' to create narrative paragraphs for this section.">${escapeHtml(existingNarrative)}</textarea>
        <div class="table-preview">
            ${geneSetHtml}
            ${goDescHtml}
            ${genesHtml}
            ${geneDescHtml}
        </div>
    `;
    cardsDiv.appendChild(card);

    // Auto-resize the narrative textarea if it has content
    const narrativeEl = document.getElementById(`genomics-narrative-${key}`);
    if (narrativeEl && existingNarrative) autoResizeTextarea(narrativeEl);
}


/**
 * Combine gene_set_narrative and gene_narrative arrays into a single
 * text block for the narrative textarea.  Used both when creating the
 * card and when restoring from session.
 */
function _buildGenomicsNarrativeText(data) {
    const parts = [];
    if (data.gene_set_narrative && data.gene_set_narrative.length > 0) {
        parts.push(data.gene_set_narrative.join('\n\n'));
    }
    if (data.gene_narrative && data.gene_narrative.length > 0) {
        parts.push(data.gene_narrative.join('\n\n'));
    }
    return parts.join('\n\n');
}


/**
 * Call the LLM to generate narrative paragraphs for a genomics card.
 * Populates the narrative textarea and stores the result in genomicsResults.
 */
async function generateGenomicsNarrative(key) {
    const data = genomicsResults[key];
    if (!data) return;

    const btn = document.getElementById(`btn-gen-narrative-${key}`);
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Generating...';
    }

    try {
        const result = await apiFetch('/api/generate-genomics-narrative', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                identity: currentIdentity,
                organ: data.organ,
                sex: data.sex,
                // Flatten gene_sets_by_stat into a single array for the
                // narrative generator (it just needs representative GO terms).
                // Use the first stat's list, or fall back to legacy gene_sets.
                gene_sets: _flattenGeneSets(data),
                top_genes: data.top_genes,
                total_responsive_genes: data.total_responsive_genes,
                dose_unit: 'mg/kg',
            }),
        });

        // Store narrative arrays in the genomics result
        genomicsResults[key].gene_set_narrative = result.gene_set_narrative || [];
        genomicsResults[key].gene_narrative = result.gene_narrative || [];

        // Populate the textarea
        const text = _buildGenomicsNarrativeText(genomicsResults[key]);
        const textarea = document.getElementById(`genomics-narrative-${key}`);
        if (textarea) {
            textarea.value = text;
            autoResizeTextarea(textarea);
        }
        markReportDirty();
        showToast('Narrative generated');

    } catch (e) {
        showError('Narrative generation failed: ' + e.message);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Generate Narrative';
        }
    }
}

/**
 * Approve a genomics card — sends data to the server.
 */
async function approveGenomics(key) {
    const data = genomicsResults[key];
    if (!data) return;

    // Capture the current narrative text from the textarea — the user may
    // have edited it after generation.
    const narrativeEl = document.getElementById(`genomics-narrative-${key}`);
    const narrativeText = narrativeEl ? narrativeEl.value.trim() : '';

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
            gene_set_narrative: data.gene_set_narrative || [],
            gene_narrative: data.gene_narrative || [],
            narrative_text: narrativeText,
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
            show('bmd-summary-section');
            document.getElementById('bmd-summary-section').classList.add('visible');
            if (tabbedViewActive) buildTabBar();
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
