/* -----------------------------------------------------------------
 * validation.js — Pool validation, coverage matrix, metadata review
 *
 * Split from filepool.js.  Handles the validation panel (coverage
 * matrix, issues, conflict resolution), file metadata confirmation,
 * pool integration triggering, integrated data preview, and
 * experiment metadata review/approval.
 *
 * Depends on: state.js (globals), utils.js (helpers),
 *             upload.js (renderFilePoolItem), cards.js (createBm2Card)
 * ----------------------------------------------------------------- */

// =========================================================================
// Pool Validation — coverage matrix, issues, and conflict resolution
// =========================================================================
// The validation panel sits below the file pool list and provides:
//   1. A "Validate & Integrate" button that triggers full pool validation
//   2. A coverage matrix (domain × tier: xlsx, txt/csv, bm2)
//   3. An issues list with severity icons (error, warning, info)
//   4. Conflict resolution dialogs for error-severity issues
//
// Validation results are fetched from POST /api/pool/validate/{dtxsid}
// and cached in lastValidationReport for UI rendering.

/** Cached validation report from last full validation run */
let lastValidationReport = null;

/**
 * Show the validation panel (visible once files exist in the pool).
 * Called after file upload or session restore adds files.
 */
function showValidationPanel() {
    const panel = document.getElementById('validation-panel');
    if (panel) panel.style.display = '';
}

/**
 * Toggle the validation panel body (expand/collapse).
 * The chevron rotates to indicate state.
 */
function toggleValidationPanel() {
    const header = document.querySelector('.validation-header');
    const body = document.getElementById('validation-body');
    if (!header || !body) return;
    const isExpanded = header.classList.toggle('expanded');
    body.style.display = isExpanded ? '' : 'none';
}

/**
 * Run pool validation only (no integration).
 *
 * Calls POST /api/pool/validate/{dtxsid}, renders the coverage matrix
 * and issues list.  If validation passes with zero errors, enables the
 * Integrate button.  If errors exist, the Integrate button stays
 * disabled — the user must fix the pool (remove/replace files) and
 * re-validate.
 */
async function runPoolValidation() {
    const dtxsid = document.getElementById('dtxsid')?.value?.trim();
    if (!dtxsid) {
        showToast('Resolve a chemical identity first');
        return;
    }

    AppStore.dispatch('pool.transition', 'VALIDATING');

    showBlockingSpinner('Validating file pool...');
    try {
        const resp = await fetch(`/api/pool/validate/${dtxsid}`, { method: 'POST' });
        if (!resp.ok) {
            const err = await resp.json();
            showToast(err.error || 'Validation failed');
            AppStore.dispatch('pool.transition', 'UPLOADED');
            return;
        }
        const report = await resp.json();
        lastValidationReport = report;

        // Expand the panel to show results
        const header = document.querySelector('.validation-header');
        const body = document.getElementById('validation-body');
        if (header && !header.classList.contains('expanded')) {
            header.classList.add('expanded');
        }
        if (body) body.style.display = '';

        renderCoverageMatrix(report);
        renderValidationIssues(report);
        updateValidationSummary(report);
        updateFileStatusDots(report);

        // --- Extract detected platforms from the coverage matrix ---
        // Coverage matrix keys are compound: "Body Weight|tox_study",
        // "gene_expression", etc.  We split on '|' to get the human-
        // readable platform name, and filter out "gene_expression"
        // (genomics has its own ready flags, not per-platform).
        // This tells the pool state machine exactly what data types
        // are in the pool, so the TOC can enable/disable table nodes.
        const detectedPlatforms = [...new Set(
            Object.keys(report.coverage_matrix || {})
                .map(key => key.includes('|') ? key.split('|')[0] : key)
                .filter(p => p !== 'gene_expression')
        )];
        AppStore.dispatch('pool.setPlatforms', detectedPlatforms);

        // Compute per-platform section completeness from coverage matrix.
        // This tells the preview system which sections can render as PDF
        // (both data sources present) and which are incomplete.
        const completeness = computeSectionCompleteness(report.coverage_matrix);
        AppStore.dispatch('pool.setCompleteness', completeness);

        // Derive the settled phase from artifact state after validation
        const errorCount = (report.issues || []).filter(
            i => i.severity === 'error'
        ).length;

        const phase = derivePoolPhase({
            hasFiles:             true,
            hasStale:             false,   // just validated — stale is cleared
            validationReport:     report,
            hasValidationErrors:  errorCount > 0,
            hasIntegrated:        false,   // validation doesn't produce integrated data
            hasAnimalReport:      false,
        });
        AppStore.dispatch('pool.transition', phase);

        if (errorCount === 0) {
            showToast('Validation passed — click Integrate to proceed');
        } else {
            showToast(`${errorCount} error(s) found — fix the file pool and re-validate`);
        }
    } catch (e) {
        showToast('Validation request failed: ' + e.message);
        // Validation failed — no report exists, derive phase (→ UPLOADED)
        AppStore.dispatch('pool.transition', derivePoolPhase({
            hasFiles: true, hasStale: false, validationReport: null,
            hasValidationErrors: false, hasIntegrated: false, hasAnimalReport: false,
        }));
    } finally {
        hideBlockingSpinner();
    }
}


/**
 * Run pool integration — merge validated files into a unified BMDProject.
 *
 * Only callable when validation has passed with zero errors (the Integrate
 * button is disabled otherwise).  Calls POST /api/pool/integrate/{dtxsid}
 * and renders the integrated data preview.
 */
async function runPoolIntegration() {
    const dtxsid = document.getElementById('dtxsid')?.value?.trim();
    if (!dtxsid) return;

    AppStore.dispatch('pool.transition', 'INTEGRATING');

    showBlockingSpinner('Integrating files...');
    try {
        const intResp = await fetch(`/api/pool/integrate/${dtxsid}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ identity: currentIdentity }),
        });
        if (intResp.ok) {
            integratedPoolData = await intResp.json();
            renderIntegratedDataPreview(integratedPoolData);
            // Integration succeeded — derive phase (→ INTEGRATED)
            AppStore.dispatch('pool.transition', derivePoolPhase({
                hasFiles: true, hasStale: false, validationReport: lastValidationReport,
                hasValidationErrors: false, hasIntegrated: true, hasAnimalReport: false,
            }));
            showToast('Integration complete — approve to proceed');
        } else {
            const intErr = await intResp.json().catch(() => ({}));
            showToast(intErr.error || 'Integration failed');
            // Integration failed — no integrated data, derive phase (→ VALIDATED)
            AppStore.dispatch('pool.transition', derivePoolPhase({
                hasFiles: true, hasStale: false, validationReport: lastValidationReport,
                hasValidationErrors: false, hasIntegrated: false, hasAnimalReport: false,
            }));
        }
    } catch (e) {
        showToast('Integration failed: ' + e.message);
        AppStore.dispatch('pool.transition', derivePoolPhase({
            hasFiles: true, hasStale: false, validationReport: lastValidationReport,
            hasValidationErrors: false, hasIntegrated: false, hasAnimalReport: false,
        }));
    } finally {
        hideBlockingSpinner();
    }
}


/**
 * Render a collapsible preview of the integrated BMDProject data.
 *
 * Shows a summary of source files and experiment counts, plus a JSON tree
 * browser so the user can inspect the merged data before approving.
 * Rendered inline below the validation panel.
 *
 * @param {Object} data — the integrated BMDProject JSON from the server
 */
/**
 * Render the integrated dataset previewer in the Data tab.
 *
 * Accepts either the full integrated BMDProject JSON (from validate flow)
 * or the lightweight summary (from GET /api/integrated-summary, used on
 * session restore to avoid loading 60MB+ into the browser).
 *
 * Full format has: doseResponseExperiments[], bMDResult[], categoryAnalysisResults[]
 * Summary format has: experiment_count, experiments[{name, probe_count}],
 *                     bmd_result_count, category_analysis_count
 *
 * @param {Object} data — full integrated JSON or summary response
 */
function renderIntegratedDataPreview(data) {
    renderIntegratedPreview(data);
}

function renderIntegratedPreview(data) {
    // Target the pre-existing preview content area in the Data tab.
    const wrapper = document.getElementById('integrated-preview');
    const container = document.getElementById('integrated-preview-content');
    if (!container) return;
    if (wrapper) wrapper.style.display = '';

    const meta = data._meta || {};
    const sources = meta.source_files || {};

    // Handle both full and summary formats
    const isSummary = 'experiment_count' in data;
    const expCount = isSummary ? data.experiment_count : (data.doseResponseExperiments || []).length;
    const bmdCount = isSummary ? (data.bmd_result_count || 0) : (data.bMDResult || []).length;
    const catCount = isSummary ? (data.category_analysis_count || 0) : (data.categoryAnalysisResults || []).length;

    // Count total endpoints (probes) across all experiments
    let totalProbes = 0;
    if (isSummary) {
        for (const exp of (data.experiments || [])) {
            totalProbes += exp.probe_count || 0;
        }
    } else {
        for (const exp of (data.doseResponseExperiments || [])) {
            totalProbes += (exp.probeResponses || []).length;
        }
    }

    // Build source file rows — one per platform.
    // Platform strings are already human-readable, so domainLabel()
    // acts as a pass-through.
    const sourceRows = Object.entries(sources).map(([key, info]) => {
        // Keys may be compound: "Body Weight|tox_study" — extract platform part
        const platform = key.includes('|') ? key.split('|')[0] : key;
        const dataType = key.includes('|') ? key.split('|')[1] : '';
        const tierClass = info.tier === 'bm2' ? 'tier-bm2' :
                          info.tier === 'xlsx' ? 'tier-xlsx' : 'tier-csv';
        const label = domainLabel(platform) + (dataType ? ` (${dataType})` : '');
        const isGenomic = key === 'gene_expression';

        return `<tr class="${isGenomic ? 'genomic-row' : ''}">
            <td><strong>${escapeHtml(label)}</strong></td>
            <td><code class="filename">${escapeHtml(info.filename || '—')}</code></td>
            <td><span class="tier-badge ${tierClass}">${info.tier || '?'}</span></td>
            <td class="num">${info.experiment_count || 0}</td>
        </tr>`;
    }).join('');

    const platformCount = Object.keys(sources).length;

    container.innerHTML = `
        <div class="preview-stats">
            <div class="stat-card">
                <span class="stat-value">${platformCount}</span>
                <span class="stat-label">Platforms</span>
            </div>
            <div class="stat-card">
                <span class="stat-value">${expCount}</span>
                <span class="stat-label">Experiments</span>
            </div>
            <div class="stat-card">
                <span class="stat-value">${totalProbes.toLocaleString()}</span>
                <span class="stat-label">Endpoints</span>
            </div>
            <div class="stat-card">
                <span class="stat-value">${bmdCount}</span>
                <span class="stat-label">BMD Results</span>
            </div>
            ${catCount > 0 ? `<div class="stat-card">
                <span class="stat-value">${catCount}</span>
                <span class="stat-label">Category Analyses</span>
            </div>` : ''}
        </div>
        <table class="source-files-table">
            <thead><tr><th>Platform</th><th>Source File</th><th>Tier</th><th>Experiments</th></tr></thead>
            <tbody>${sourceRows}</tbody>
        </table>
    `;
}

/**
 * Render the coverage matrix table.
 *
 * Shows a table with one row per platform and columns for xlsx, txt/csv, bm2.
 * Each cell shows checkmarks for present files, dashes for missing,
 * and a warning icon in the rightmost column if any tier is missing.
 *
 * @param {Object} report — ValidationReport from the server
 */
function renderCoverageMatrix(report) {
    const container = document.getElementById('coverage-matrix');
    if (!container) return;

    const matrix = report.coverage_matrix || {};
    const platforms = Object.keys(matrix);

    if (platforms.length === 0) {
        container.innerHTML = '<p style="color:var(--c-text-muted);font-size:0.8rem;">No platforms detected.</p>';
        return;
    }

    // Coverage matrix keys are compound: "Body Weight|tox_study", "Body Weight|inferred",
    // "gene_expression".  Collapse to one row per conceptual platform by extracting
    // the platform part (before "|") and merging tier presence across data types.
    const collapsed = {};
    for (const key of platforms) {
        const platform = key.includes('|') ? key.split('|')[0] : key;
        if (!collapsed[platform]) {
            collapsed[platform] = { xlsx: false, txtCsvCount: 0, bm2: false };
        }
        const tiers = matrix[key];
        if (tiers.xlsx) collapsed[platform].xlsx = true;
        const txtArr = tiers.txt_csv || [];
        collapsed[platform].txtCsvCount += Array.isArray(txtArr) ? txtArr.length : (txtArr ? 1 : 0);
        if (tiers.bm2) collapsed[platform].bm2 = true;
    }

    const sortedPlatforms = Object.keys(collapsed).sort();

    let html = '<table class="coverage-matrix">';
    html += '<thead><tr><th>Platform</th><th>xlsx</th><th>txt/csv</th><th>bm2</th><th></th></tr></thead>';
    html += '<tbody>';

    for (const platform of sortedPlatforms) {
        const c = collapsed[platform];

        // Gene expression typically has no xlsx — don't show missing as a gap
        const xlsxExpected = platform !== 'Gene Expression';

        const xlsxCell = c.xlsx
            ? '<span class="coverage-check">✓</span>'
            : (xlsxExpected ? '<span class="coverage-dash">—</span>' : '<span class="coverage-dash">n/a</span>');

        let txtCell;
        if (c.txtCsvCount === 0) {
            txtCell = '<span class="coverage-dash">—</span>';
        } else if (c.txtCsvCount === 1) {
            txtCell = '<span class="coverage-check">✓</span>';
        } else {
            txtCell = '<span class="coverage-check">' + '✓'.repeat(Math.min(c.txtCsvCount, 4)) + '</span>';
        }

        const bm2Cell = c.bm2
            ? '<span class="coverage-check">✓</span>'
            : '<span class="coverage-dash">—</span>';

        const hasMissingTier = (xlsxExpected && !c.xlsx) || c.txtCsvCount === 0 || !c.bm2;
        const warnCell = hasMissingTier
            ? '<span class="coverage-warn">⚠</span>'
            : '';

        const label = domainLabel(platform);
        html += `<tr><td>${label}</td><td>${xlsxCell}</td><td>${txtCell}</td><td>${bm2Cell}</td><td>${warnCell}</td></tr>`;
    }

    html += '</tbody></table>';
    container.innerHTML = html;
}

/**
 * Render the file metadata review table — pre-integration gate.
 *
 * Shows one row per file with editable dropdowns for platform and data_type.
 * Pre-filled from fingerprint detection.  User must click "Confirm & Integrate"
 * to write metadata headers into files and proceed to integration.
 *
 * @param {Object} fingerprints — {file_id: fingerprint_dict} from validation
 */
function renderFileMetadataReview(fingerprints) {
    const panel = document.getElementById('file-metadata-review');
    const container = document.getElementById('file-metadata-table');
    if (!panel || !container) return;

    panel.style.display = '';

    // Platform vocabulary for dropdown
    const platforms = [
        'Body Weight', 'Organ Weight', 'Clinical Chemistry', 'Hematology',
        'Hormones', 'Tissue Concentration', 'Clinical',
    ];
    const dataTypes = ['tox_study', 'inferred', 'gene_expression'];

    // Sort by section: tox_study txt/csv, inferred txt/csv, bm2, gene_expression.
    // Within each section, sort by filename.
    function sortKey(fp) {
        const isBm2 = fp.file_type === 'bm2';
        const isGE = fp.data_type === 'gene_expression' && !isBm2;
        const isObs = fp.platform === 'Clinical';
        if (isBm2) return 3;           // all bm2 files together
        if (isObs) return 4;           // clinical observations (categorical)
        if (fp.data_type === 'tox_study') return 0;
        if (isGE) return 5;            // gene expression txt only
        return 1;                       // inferred txt/csv
    }
    const entries = Object.entries(fingerprints)
        .sort(([, a], [, b]) => {
            const sa = sortKey(a), sb = sortKey(b);
            if (sa !== sb) return sa - sb;
            // Within section: sort by platform, then filename, then sex
            const pa = (a.platform || '').localeCompare(b.platform || '');
            if (pa !== 0) return pa;
            const fa = (a.filename || '').localeCompare(b.filename || '');
            if (fa !== 0) return fa;
            const sexa = (a.sexes || []).join(''), sexb = (b.sexes || []).join('');
            return sexa.localeCompare(sexb);
        });

    // Section labels keyed by sortKey value
    const sectionLabels = {
        0: 'Tox Study (source data)',
        1: 'Inferred (gap-filled)',
        3: 'BMDExpress Results (.bm2)',
        4: 'Clinical Observations',
        5: 'Gene Expression',
    };

    let html = '<table class="coverage-matrix" style="font-size:0.8rem;">';
    html += '<thead><tr><th>File</th><th>Type</th><th>Platform</th><th>Data Type</th><th>Sex</th></tr></thead>';
    html += '<tbody>';

    let lastSection = -1;
    for (const [fid, fp] of entries) {
        // Insert group header when section changes
        const section = sortKey(fp);
        if (section !== lastSection) {
            lastSection = section;
            html += `<tr><td colspan="5" style="font-weight:bold; background:#f1f5f9; padding:0.4rem 0.5rem;">${sectionLabels[section]}</td></tr>`;
        }
        const isGE = fp.data_type === 'gene_expression';

        // Platform dropdown — disabled for gene expression (platform comes from chip info)
        let platformCell;
        if (isGE) {
            platformCell = `<td><em>Gene Expression</em></td>`;
        } else {
            const opts = platforms.map(p =>
                `<option value="${p}"${p === fp.platform ? ' selected' : ''}>${p}</option>`
            ).join('');
            platformCell = `<td><select data-fid="${fid}" data-field="platform" class="fm-select">${opts}</select></td>`;
        }

        // Data type dropdown
        const dtOpts = dataTypes.map(dt =>
            `<option value="${dt}"${dt === fp.data_type ? ' selected' : ''}>${dt}</option>`
        ).join('');
        const dtCell = `<td><select data-fid="${fid}" data-field="data_type" class="fm-select">${dtOpts}</select></td>`;

        // Sex (read-only display from fingerprint)
        const sexes = (fp.sexes || []).join(', ') || '—';

        html += `<tr>`;
        html += `<td><code style="font-size:0.75rem;">${escapeHtml(fp.filename || fid)}</code></td>`;
        html += `<td>${fp.file_type || '?'}</td>`;
        html += platformCell;
        html += dtCell;
        html += `<td>${sexes}</td>`;
        html += `</tr>`;
    }

    html += '</tbody></table>';
    html += `<div style="margin-top:0.75rem;">`;
    html += `<button class="btn-small primary" onclick="confirmFileMetadataAndIntegrate()">Confirm &amp; Integrate</button>`;
    html += `</div>`;

    container.innerHTML = html;
}


/**
 * Collect confirmed file metadata from the review table, POST to server
 * to write headers into files, then run integration.
 */
async function confirmFileMetadataAndIntegrate() {
    const dtxsid = document.getElementById('dtxsid')?.value?.trim();
    if (!dtxsid) return;

    // Collect metadata from all dropdowns
    const metadata = {};
    for (const sel of document.querySelectorAll('#file-metadata-table .fm-select')) {
        const fid = sel.dataset.fid;
        const field = sel.dataset.field;
        if (!metadata[fid]) metadata[fid] = {};
        metadata[fid][field] = sel.value;
    }

    try {
        showBlockingSpinner('Writing metadata headers...');

        // POST confirmed metadata to server — writes headers into file copies
        const resp = await fetch(`/api/pool/confirm-metadata/${dtxsid}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ metadata }),
        });

        if (!resp.ok) {
            const err = await resp.text();
            showToast('Metadata confirmation failed: ' + err);
            return;
        }

        showToast('Metadata confirmed — integrating...');
    } catch (e) {
        showToast('Metadata confirmation failed: ' + e.message);
        return;
    } finally {
        hideBlockingSpinner();
    }

    // Now run integration — files have headers written
    await runPoolIntegration();
}


/**
 * Render the validation issues list.
 *
 * Shows each issue with a severity icon and human-readable message.
 * Error-severity issues are clickable to expand a conflict resolution
 * dialog where the user can choose which file is authoritative.
 *
 * @param {Object} report — ValidationReport from the server
 */
function renderValidationIssues(report) {
    const container = document.getElementById('validation-issues');
    if (!container) return;

    const issues = report.issues || [];
    if (issues.length === 0) {
        container.innerHTML = '<p style="color:var(--c-success);font-size:0.8rem;margin-top:0.5rem;">No issues found — all tiers are consistent.</p>';
        return;
    }

    // Group issues by severity so each level gets its own collapsible section
    const grouped = { error: [], warning: [], info: [] };
    for (let i = 0; i < issues.length; i++) {
        const sev = issues[i].severity || 'info';
        if (!grouped[sev]) grouped[sev] = [];
        grouped[sev].push({ issue: issues[i], index: i });
    }

    // Severity display config: icon, label, CSS class suffix
    const sevConfig = {
        error:   { icon: '⛔', label: 'Errors',   cls: 'error' },
        warning: { icon: '⚠',  label: 'Warnings', cls: 'warning' },
        info:    { icon: 'ℹ️',  label: 'Info',     cls: 'info' }
    };

    let html = '';

    // One collapsible section per severity level that has issues
    for (const sev of ['error', 'warning', 'info']) {
        const items = grouped[sev];
        if (!items || items.length === 0) continue;

        const cfg = sevConfig[sev];
        const n = items.length;
        const summaryText = `${cfg.icon} ${n} ${cfg.label.toLowerCase()}`;

        // Build the list of issues inside this severity group
        let bodyHtml = '';
        for (const { issue, index } of items) {
            bodyHtml += `<div class="validation-issue severity-${sev}" data-issue-index="${index}">`;
            bodyHtml += `<span class="issue-icon">${cfg.icon}</span>`;
            bodyHtml += `<span class="issue-text">${issue.message}`;

            // For dose mismatch errors, show the conflicting dose groups
            // so the user knows what to fix.  No conflict resolution —
            // the user must update the file pool to resolve the error.
            if (sev === 'error' && issue.issue_type === 'dose_mismatch' && issue.details) {
                const d = issue.details;
                const expectedDoses = (d.expected || []).join(', ');
                const actualDoses = (d.actual || []).join(', ');
                bodyHtml += '<div class="conflict-detail" style="margin-top:0.3rem;font-size:0.75rem;color:var(--c-text-muted);">';
                bodyHtml += `<div>${escapeHtml(d.expected_file || 'File 1')}: [${expectedDoses}]</div>`;
                bodyHtml += `<div>${escapeHtml(d.actual_file || 'File 2')}: [${actualDoses}]</div>`;
                bodyHtml += '<div style="margin-top:0.2rem;font-weight:600;">Remove or replace the incorrect file to resolve.</div>';
                bodyHtml += '</div>';
            }

            bodyHtml += '</span></div>';
        }

        // Errors default open (user needs to act on them), others collapsed
        const openClass = sev === 'error' ? ' ar-open' : '';

        html += `<div class="ar-collapse issue-group-${cfg.cls}${openClass}">`;
        html += `<div class="ar-collapse-header" onclick="this.parentElement.classList.toggle('ar-open')">`;
        html += `<span class="ar-chevron">▸</span> ${summaryText}`;
        html += `</div>`;
        html += `<div class="ar-collapse-body">${bodyHtml}</div>`;
        html += `</div>`;
    }

    container.innerHTML = html;
}

/**
 * Render an inline conflict resolution panel for a dose mismatch error.
 *
 * Shows the dose groups from each file, timestamps, and radio buttons
 * for the user to choose which file is authoritative.
 *
 * @param {Object} issue — the ValidationIssue dict
 * @param {number} index — the issue index in the report
 * @param {Object} report — the full ValidationReport (for fingerprint lookup)
 * @returns {string} — HTML fragment for the conflict resolution panel
 */
function renderConflictResolution(issue, index, report) {
    const d = issue.details || {};
    const expectedDoses = (d.expected || []).join(', ');
    const actualDoses = (d.actual || []).join(', ');
    const expectedFile = d.expected_file || 'File 1';
    const actualFile = d.actual_file || 'File 2';
    const suggested = issue.suggested_precedence || '';

    // Look up timestamps from fingerprints
    const fps = report.fingerprints || {};
    const files = issue.files_involved || [];
    let tsHtml = '';
    for (const fid of files) {
        const fp = fps[fid];
        if (fp) {
            const added = fp.ts_added ? new Date(fp.ts_added).toLocaleString() : '?';
            const internal = fp.ts_internal ? new Date(fp.ts_internal).toLocaleDateString() : 'none';
            tsHtml += `<div>${escapeHtml(fp.filename)} — added: ${added}, internal date: ${internal}</div>`;
        }
    }

    let html = '<div class="conflict-resolution">';
    html += `<h4>Dose group conflict: ${issue.domain}</h4>`;
    html += `<div class="conflict-detail">${expectedFile}: [${expectedDoses}]</div>`;
    html += `<div class="conflict-detail">${actualFile}: [${actualDoses}]</div>`;

    if (tsHtml) {
        html += `<div class="conflict-timestamps">${tsHtml}</div>`;
    }

    html += '<div>Which file has the correct dose groups?</div>';
    html += '<div class="conflict-options">';

    for (const fid of files) {
        const fp = fps[fid];
        const label = fp ? `${escapeHtml(fp.filename)} (${escapeHtml(fp.file_type)})` : escapeHtml(fid);
        const isRec = fid === suggested;
        html += `<label class="${isRec ? 'recommended' : ''}">`;
        html += `<input type="radio" name="conflict-${index}" value="${escapeHtml(fid)}"`;
        html += ` onchange="resolveConflict(${index}, '${escapeHtml(fid)}')"`;
        html += `> ${label}${isRec ? ' (recommended)' : ''}`;
        html += '</label>';
    }

    html += '<label><input type="radio" name="conflict-' + index + '" value="skip"';
    html += ` onchange="resolveConflict(${index}, 'skip')"> Skip</label>`;
    html += '</div></div>';

    return html;
}

/**
 * Record a precedence decision for a conflict via POST /api/pool/resolve.
 *
 * @param {number} issueIndex — index of the issue in the validation report
 * @param {string} chosenFileId — file_id the user chose, or "skip"
 */
async function resolveConflict(issueIndex, chosenFileId) {
    const dtxsid = document.getElementById('dtxsid')?.value?.trim();
    if (!dtxsid) return;

    try {
        await fetch('/api/pool/resolve', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                dtxsid: dtxsid,
                issue_index: issueIndex,
                chosen_file_id: chosenFileId,
            }),
        });
        showToast('Precedence recorded');
    } catch (e) {
        showToast('Failed to record precedence: ' + e.message);
    }
}

/**
 * Update the summary badge in the validation panel header.
 * Shows counts like "4 errors, 2 warnings" or "No issues" in green.
 *
 * @param {Object} report — ValidationReport from the server
 */
function updateValidationSummary(report) {
    const el = document.getElementById('validation-summary');
    if (!el) return;

    const issues = report.issues || [];
    if (issues.length === 0) {
        el.textContent = '— No issues';
        el.style.color = 'var(--c-success)';
        return;
    }

    const counts = { error: 0, warning: 0, info: 0 };
    for (const issue of issues) {
        counts[issue.severity] = (counts[issue.severity] || 0) + 1;
    }

    const parts = [];
    if (counts.error > 0) parts.push(`${counts.error} error${counts.error > 1 ? 's' : ''}`);
    if (counts.warning > 0) parts.push(`${counts.warning} warning${counts.warning > 1 ? 's' : ''}`);

    el.textContent = '— ' + parts.join(', ');
    el.style.color = counts.error > 0 ? '#ef4444' : '#f59e0b';
}

/**
 * Update validation status dots on each file pool item.
 *
 * Each file gets a small colored dot before its type badge:
 *   - Green:  fingerprinted, no issues involving this file
 *   - Yellow: warnings involving this file
 *   - Red:    errors involving this file
 *   - Gray:   not fingerprinted (not in the report)
 *
 * @param {Object} report — ValidationReport from the server
 */
function updateFileStatusDots(report) {
    // Build a map of file_id → worst severity
    const fileSeverity = {};
    for (const issue of (report.issues || [])) {
        for (const fid of (issue.files_involved || [])) {
            const current = fileSeverity[fid] || 'none';
            const incoming = issue.severity;
            // Severity ranking: error > warning > info > none
            if (incoming === 'error' || current === 'none' ||
                (incoming === 'warning' && current !== 'error')) {
                fileSeverity[fid] = incoming;
            }
        }
    }

    // Update or create dots on each file pool item
    for (const fileId of Object.keys(uploadedFiles)) {
        const itemEl = document.getElementById(`file-pool-${fileId}`);
        if (!itemEl) continue;

        // Remove any existing dot
        const existingDot = itemEl.querySelector('.validation-dot');
        if (existingDot) existingDot.remove();

        // Determine dot color
        const fp = (report.fingerprints || {})[fileId];
        let dotClass;
        if (!fp) {
            dotClass = 'gray';
        } else {
            const sev = fileSeverity[fileId];
            if (sev === 'error') dotClass = 'red';
            else if (sev === 'warning') dotClass = 'yellow';
            else dotClass = 'green';
        }

        // Insert dot as the first child (before the badge)
        const dot = document.createElement('span');
        dot.className = `validation-dot ${dotClass}`;
        dot.title = dotClass === 'green' ? 'No issues' :
                    dotClass === 'gray' ? 'Not validated' :
                    dotClass === 'red' ? 'Has errors' : 'Has warnings';
        itemEl.insertBefore(dot, itemEl.firstChild);
    }
}

/**
 * Restore a cached validation report from session data.
 * Called during loadSession() if the server returned validation_report.
 *
 * @param {Object} report — the persisted validation report JSON
 */
function restoreValidationReport(report) {
    if (!report) return;
    lastValidationReport = report;
    showValidationPanel();
    renderCoverageMatrix(report);
    renderValidationIssues(report);
    updateValidationSummary(report);
    updateFileStatusDots(report);

    // --- Restore platform set from coverage matrix ---
    // Same extraction as runPoolValidation(): split compound keys on '|',
    // filter out gene_expression.  This ensures the pool state machine
    // knows which platforms have data immediately on session restore,
    // before autoProcessPool() re-creates cards.
    const detectedPlatforms = [...new Set(
        Object.keys(report.coverage_matrix || {})
            .map(key => key.includes('|') ? key.split('|')[0] : key)
            .filter(p => p !== 'gene_expression')
    )];
    AppStore.dispatch('pool.setPlatforms', detectedPlatforms);

    // Compute per-platform section completeness from coverage matrix
    // so the preview system knows which sections can render as PDF.
    const completeness = computeSectionCompleteness(report.coverage_matrix);
    AppStore.dispatch('pool.setCompleteness', completeness);

    // Phase is NOT set here — the caller (chemical.js session restore)
    // derives the correct phase from the full artifact state via
    // derivePoolPhase() after all restore data is loaded.  Setting phase
    // here would be premature since later artifacts (integrated data,
    // animal report, stale flags) can change it.
}


// =========================================================================
// Experiment Metadata Review
//
// After pool integration, the LLM infers structured metadata for each
// experiment (species, sex, organ, strain, etc.).  This panel lets the
// user review and correct those inferences before they're baked into the
// exported .bm2 file.
//
// The panel renders a horizontal table: one row per experiment, one column
// per metadata field.  Fields use <select> dropdowns constrained to the
// controlled vocabularies from BMDExpress 3's vocabulary.yml.
// =========================================================================

// Cached vocabularies from the server (populated on first load)
let _metadataVocabularies = null;

// Cached experiment data from the server (includes probe_ids for organ modals)
let _metadataExperiments = null;

// The metadata fields to show in the table, in display order.
// Each entry: [jsonKey, displayLabel, inputType]
// inputType: 'select' for vocabulary-constrained, 'text' for free-text
const METADATA_FIELDS = [
    ['species',             'Species',              'select'],
    ['strain',              'Strain',               'select'],  // dynamic: filtered by species
    ['sex',                 'Sex',                   'select'],
    ['organ',               'Organ',                 'select'],
    ['subjectType',         'Subject Type',          'select'],
    ['platform',            'Platform',              'select'],
    ['provider',            'Provider',              'select'],
    ['studyDuration',       'Duration',              'select'],
    ['articleRoute',        'Route',                 'select'],
    ['articleVehicle',      'Vehicle',               'select'],
    ['administrationMeans', 'Administration',        'select'],
    ['articleType',         'Article Type',          'select'],
    ['cellLine',            'Cell Line',             'text'],
];


/**
 * Load experiment metadata from the server and render the review table.
 *
 * Called after integration completes (from autoProcessPool).  Fetches
 * the current experimentDescription for each experiment plus the
 * controlled vocabularies, then builds the editable table.
 */
async function loadMetadataReview() {
    const dtxsid = document.getElementById('dtxsid')?.value?.trim();
    if (!dtxsid) return;

    try {
        const resp = await fetch(`/api/experiment-metadata/${dtxsid}`);
        if (!resp.ok) return;

        const data = await resp.json();
        _metadataVocabularies = data.vocabularies;
        _metadataExperiments = data.experiments;

        renderMetadataTable(data.experiments, data.vocabularies);

        // Show the metadata review inline within the data tab —
        // no separate tab, just unhide the subsection.
        document.getElementById('metadata-review-section').style.display = '';

        // If already approved (e.g. restored session), show the badge,
        // lock the form, and skip the gate — proceed directly to the
        // processing pipeline so the user doesn't have to re-approve.
        if (data.approved) {
            const section = document.getElementById('metadata-review-section');
            section.classList.add('approved');
            hide('btn-approve-metadata');
            const badge = document.getElementById('badge-metadata');
            badge.style.display = '';
            badge.textContent = 'Approved';

            // Auto-proceed: metadata was already approved in a prior session
            await runProcessingPipeline();
        }
    } catch (e) {
        console.error('Failed to load metadata:', e);
    }
}


/**
 * Build the metadata review table from experiment data and vocabularies.
 *
 * Creates a <table> with one row per experiment and one column per
 * metadata field.  Select dropdowns are populated from the controlled
 * vocabularies.  The strain dropdown is dynamically filtered by the
 * selected species.
 */
function renderMetadataTable(experiments, vocabularies) {
    const container = document.getElementById('metadata-table-container');

    // Build header row
    let headerHtml = '<th>Experiment</th>';
    for (const [key, label] of METADATA_FIELDS) {
        headerHtml += `<th>${label}</th>`;
    }

    // Build body rows — one per experiment
    let bodyHtml = '';
    for (const exp of experiments) {
        const ed = exp.experimentDescription || {};
        const name = exp.name;
        const probeCount = exp.probe_count || 0;
        // Detect organ weight experiments by platform
        const isOrganWeight = (ed.platform || '').toLowerCase().includes('organ weight');

        bodyHtml += `<tr data-exp-name="${name}">`;
        bodyHtml += `<td title="${name}">${name}<span class="meta-probe-count">${probeCount}</span></td>`;

        for (const [key, label, inputType] of METADATA_FIELDS) {
            const currentVal = ed[key] || '';

            // Organ weight experiments get a checkbox dropdown for organs,
            // populated from the same vocabulary used for single-organ selects.
            // Pre-selected values come from probe IDs extracted during integration.
            if (key === 'organ' && isOrganWeight) {
                const selectedOrgans = (currentVal || '').split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
                const organVocab = vocabularies.organ || [];
                const count = selectedOrgans.length;
                const summary = count > 0 ? `${count} organ${count > 1 ? 's' : ''}` : '— select —';

                let cbHtml = '';
                for (const org of organVocab) {
                    const chk = selectedOrgans.includes(org.toLowerCase()) ? 'checked' : '';
                    cbHtml += `<label class="cb-dropdown-item"><input type="checkbox" value="${escapeHtml(org)}" ${chk}><span>${escapeHtml(org)}</span></label>`;
                }

                bodyHtml += `<td class="cb-dropdown-cell">`;
                bodyHtml += `<div class="cb-dropdown" data-field="organ">`;
                bodyHtml += `<button type="button" class="cb-dropdown-toggle" onclick="toggleCbDropdown(this)">${summary}</button>`;
                bodyHtml += `<div class="cb-dropdown-menu">${cbHtml}</div>`;
                bodyHtml += `</div></td>`;
            } else if (inputType === 'text') {
                bodyHtml += `<td><input type="text" data-field="${key}" value="${escapeHtml(currentVal)}"></td>`;
            } else {
                // Build <select> with vocabulary options
                let options = buildVocabOptions(key, currentVal, vocabularies, ed);
                const emptyClass = currentVal ? '' : 'meta-empty';
                bodyHtml += `<td><select data-field="${key}" class="${emptyClass}" `;

                // Strain dropdowns get a special onchange on their sibling species select
                if (key === 'species') {
                    bodyHtml += `onchange="onSpeciesChange(this)"`;
                }
                bodyHtml += `>${options}</select></td>`;
            }
        }
        bodyHtml += '</tr>';
    }

    container.innerHTML = `
        <div class="metadata-table-wrap">
            <table class="metadata-table">
                <thead><tr>${headerHtml}</tr></thead>
                <tbody>${bodyHtml}</tbody>
            </table>
        </div>
    `;
}


/**
 * Build <option> elements for a vocabulary-constrained select.
 *
 * For most fields, the vocabulary is a flat list.  For 'strain', it's
 * nested by species — we filter to show only strains for the currently
 * selected species (with a fallback to all strains if no species set).
 */
function buildVocabOptions(fieldKey, currentVal, vocabularies, expDesc) {
    let vocab = vocabularies[fieldKey] || [];

    // Strain is nested: { "rat": [...], "mouse": [...] }
    if (fieldKey === 'strain' && typeof vocab === 'object' && !Array.isArray(vocab)) {
        const species = expDesc?.species || '';
        if (species && vocab[species]) {
            vocab = vocab[species];
        } else {
            // Flatten all strains
            vocab = Object.values(vocab).flat();
        }
    }

    // studyDuration: combine in vivo and in vitro durations
    // The vocabularies object has separate inVitroDurations and inVivoDurations
    // but also studyDuration as the combined list
    if (fieldKey === 'studyDuration' && (!Array.isArray(vocab) || vocab.length === 0)) {
        vocab = [
            ...(vocabularies.inVivoDurations || []),
            ...(vocabularies.inVitroDurations || []),
        ];
    }

    let html = '<option value="">—</option>';
    for (const val of vocab) {
        const selected = (val === currentVal) ? 'selected' : '';
        html += `<option value="${escapeHtml(val)}" ${selected}>${escapeHtml(val)}</option>`;
    }

    // If the current value isn't in the vocabulary (LLM hallucination or
    // legacy data), add it as a disabled option so the user can see what
    // was there and pick a valid replacement.
    if (currentVal && !vocab.includes(currentVal)) {
        html += `<option value="${escapeHtml(currentVal)}" selected disabled>${escapeHtml(currentVal)} (not in vocabulary)</option>`;
    }

    return html;
}


/**
 * Handle species change: re-populate the strain dropdown in the same row
 * with strains for the newly selected species.
 */
function onSpeciesChange(speciesSelect) {
    const row = speciesSelect.closest('tr');
    const strainSelect = row.querySelector('select[data-field="strain"]');
    if (!strainSelect || !_metadataVocabularies) return;

    const species = speciesSelect.value;
    const strainVocab = _metadataVocabularies.strain || {};
    const strains = (species && strainVocab[species]) ? strainVocab[species] : Object.values(strainVocab).flat();

    let html = '<option value="">—</option>';
    for (const s of strains) {
        html += `<option value="${escapeHtml(s)}">${escapeHtml(s)}</option>`;
    }
    strainSelect.innerHTML = html;
    strainSelect.classList.add('meta-empty');
}




/**
 * Toggle a checkbox dropdown menu open/closed.  Clicking outside closes it.
 */
function toggleCbDropdown(btn) {
    const dropdown = btn.closest('.cb-dropdown');
    const menu = dropdown.querySelector('.cb-dropdown-menu');
    const isOpen = menu.classList.toggle('open');

    if (isOpen) {
        // Close on outside click
        const closeHandler = (e) => {
            if (!dropdown.contains(e.target)) {
                menu.classList.remove('open');
                updateCbDropdownSummary(dropdown);
                document.removeEventListener('mousedown', closeHandler);
            }
        };
        // Defer so the current click doesn't immediately close it
        setTimeout(() => document.addEventListener('mousedown', closeHandler), 0);
    } else {
        updateCbDropdownSummary(dropdown);
    }
}

/**
 * Update the toggle button text to reflect how many items are checked.
 */
function updateCbDropdownSummary(dropdown) {
    const checked = dropdown.querySelectorAll('input[type="checkbox"]:checked');
    const btn = dropdown.querySelector('.cb-dropdown-toggle');
    const count = checked.length;
    if (count === 0) {
        btn.textContent = '— select —';
    } else if (count <= 3) {
        btn.textContent = [...checked].map(cb => cb.value).join(', ');
    } else {
        btn.textContent = `${count} organs`;
    }
}


/**
 * Collect the current metadata from the table and POST it to the server.
 *
 * Reads every row's select/input values, builds a metadata-by-name dict,
 * and sends it to POST /api/experiment-metadata/{dtxsid}.  On success,
 * shows the approval badge and locks the form.
 */
async function approveMetadata() {
    const dtxsid = document.getElementById('dtxsid')?.value?.trim();
    if (!dtxsid) return;

    const table = document.querySelector('.metadata-table tbody');
    if (!table) return;

    // Collect metadata from each row
    const metadata = {};
    for (const row of table.querySelectorAll('tr')) {
        const expName = row.dataset.expName;
        if (!expName) continue;

        const desc = {};
        // Standard selects and text inputs
        for (const input of row.querySelectorAll('select, input[type="text"]')) {
            const field = input.dataset.field;
            const val = input.value.trim();
            desc[field] = val || null;
        }
        // Checkbox dropdowns (organ weight multi-organ)
        for (const cbDrop of row.querySelectorAll('.cb-dropdown')) {
            const field = cbDrop.dataset.field;
            const checked = cbDrop.querySelectorAll('input[type="checkbox"]:checked');
            const vals = [...checked].map(cb => cb.value);
            desc[field] = vals.length > 0 ? vals.join(', ') : null;
        }

        // Add testArticle from currentIdentity (always the same for all experiments)
        if (currentIdentity) {
            desc.testArticle = {
                name: currentIdentity.name || null,
                casrn: currentIdentity.casrn || null,
                dsstox: currentIdentity.dtxsid || null,
            };
        }

        metadata[expName] = desc;
    }

    try {
        showBlockingSpinner('Integrating metadata...');

        const resp = await fetch(`/api/experiment-metadata/${dtxsid}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ metadata }),
        });

        hideBlockingSpinner();

        if (resp.ok) {
            const result = await resp.json();

            // Show approved state
            const section = document.getElementById('metadata-review-section');
            section.classList.add('approved');
            hide('btn-approve-metadata');
            const badge = document.getElementById('badge-metadata');
            badge.style.display = '';
            badge.textContent = 'Approved';

            const bm2Msg = result.bm2_exported
                ? ' Enriched .bm2 exported.'
                : ' (Note: .bm2 export failed — metadata saved to JSON only.)';
            showToast(`Metadata approved for ${result.updated} experiments.${bm2Msg}`);

            // Metadata approval is the gatekeeper — now proceed to the
            // processing pipeline (NTP stats, section cards, genomics).
            await runProcessingPipeline();
        } else {
            const err = await resp.json().catch(() => ({}));
            showToast(err.error || 'Failed to save metadata');
        }
    } catch (e) {
        hideBlockingSpinner();
        showToast('Failed to save metadata: ' + e.message);
    }
}


// escapeHtml() is defined in utils.js (loaded before this file)
