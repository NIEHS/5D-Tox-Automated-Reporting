// settings.js — Report settings panel (BMD stats, GO filters, model selection)
//
// Extracted from main.js. These functions manage the persistent configuration
// panel that controls how BMD statistics are computed and displayed, which GO
// categories pass the filter, and which dose-unit label is used throughout
// the report.
//
// Globals consumed (from state.js):
//   reportSettings, DEFAULT_SETTINGS, SETTINGS_STORAGE_KEY
//
// Globals consumed (from main.js / other modules):
//   currentIdentity, apicalSections, genomicsResults, bmdSummaryEndpoints,
//   tabbedViewActive
//
// Functions called (from main.js / other modules):
//   showToast, showBlockingSpinner, hideBlockingSpinner, show,
//   createBm2Card, renderBm2Results, createGenomicsCard,
//   renderBmdSummaryTable, renderBmdSummaryTableBmds,
//   buildTabBar, updateExportButton, markReportDirty
//
// All functions are in global scope (classic <script>, not ES modules)
// so they're accessible from inline onclick handlers in HTML templates.

/* ================================================================
 * Report Settings — persistent configuration panel
 *
 * Settings are stored in localStorage and loaded on page init.
 * When a setting changes, the new values are saved immediately.
 * API callers read from the global `reportSettings` object.
 * ================================================================ */

/**
 * Toggle the settings panel visibility.
 * Called from the gear icon in the header.
 */
function toggleSettingsPanel() {
    const panel = document.getElementById('settings-panel');
    panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
}

/**
 * Load saved settings from localStorage into the form and state.
 * Called once on page load from initApp().
 */
function loadSettings() {
    try {
        const saved = localStorage.getItem(SETTINGS_STORAGE_KEY);
        if (saved) {
            const parsed = JSON.parse(saved);
            reportSettings = { ...DEFAULT_SETTINGS, ...parsed };
        }
    } catch (e) {
        reportSettings = { ...DEFAULT_SETTINGS };
    }

    // Migrate old single-stat setting to array format
    if (reportSettings.bmd_stat && !reportSettings.bmd_stats) {
        reportSettings.bmd_stats = [reportSettings.bmd_stat];
        delete reportSettings.bmd_stat;
    }
    // Ensure bmd_stats is always an array
    if (!Array.isArray(reportSettings.bmd_stats)) {
        reportSettings.bmd_stats = ['median'];
    }

    // Populate BMD stat checkboxes from state
    const statsContainer = document.getElementById('setting-bmd-stats');
    if (statsContainer) {
        for (const cb of statsContainer.querySelectorAll('input[type="checkbox"]')) {
            cb.checked = reportSettings.bmd_stats.includes(cb.value);
        }
    }

    const doseUnit = document.getElementById('setting-dose-unit');
    if (doseUnit) doseUnit.value = reportSettings.dose_unit;

    const pStar = document.getElementById('setting-p-star');
    if (pStar) pStar.value = reportSettings.p_star;

    const pDstar = document.getElementById('setting-p-dstar');
    if (pDstar) pDstar.value = reportSettings.p_dstar;

    const goPct = document.getElementById('setting-go-pct');
    if (goPct) goPct.value = reportSettings.go_pct;

    const goMinGenes = document.getElementById('setting-go-min-genes');
    if (goMinGenes) goMinGenes.value = reportSettings.go_min_genes;

    const goMaxGenes = document.getElementById('setting-go-max-genes');
    if (goMaxGenes) goMaxGenes.value = reportSettings.go_max_genes;

    const goMinBmd = document.getElementById('setting-go-min-bmd');
    if (goMinBmd) goMinBmd.value = reportSettings.go_min_bmd;
}

/**
 * Called when any setting field changes.  Reads all fields,
 * updates the global reportSettings object, and persists to localStorage.
 */
function onSettingChanged() {
    // Read checked BMD statistics from checkboxes
    const statsContainer = document.getElementById('setting-bmd-stats');
    if (statsContainer) {
        const checked = [];
        for (const cb of statsContainer.querySelectorAll('input[type="checkbox"]')) {
            if (cb.checked) checked.push(cb.value);
        }
        // Require at least one — default to median if all unchecked
        reportSettings.bmd_stats = checked.length > 0 ? checked : ['median'];
    }

    const doseUnit = document.getElementById('setting-dose-unit');
    if (doseUnit) reportSettings.dose_unit = doseUnit.value.trim() || 'mg/kg';

    const pStar = document.getElementById('setting-p-star');
    if (pStar) reportSettings.p_star = parseFloat(pStar.value) || 0.05;

    const pDstar = document.getElementById('setting-p-dstar');
    if (pDstar) reportSettings.p_dstar = parseFloat(pDstar.value) || 0.01;

    const goPct = document.getElementById('setting-go-pct');
    if (goPct) reportSettings.go_pct = parseInt(goPct.value, 10) || 5;

    const goMinGenes = document.getElementById('setting-go-min-genes');
    if (goMinGenes) reportSettings.go_min_genes = parseInt(goMinGenes.value, 10) || 20;

    const goMaxGenes = document.getElementById('setting-go-max-genes');
    if (goMaxGenes) reportSettings.go_max_genes = parseInt(goMaxGenes.value, 10) || 500;

    const goMinBmd = document.getElementById('setting-go-min-bmd');
    if (goMinBmd) reportSettings.go_min_bmd = parseInt(goMinBmd.value, 10) || 3;

    localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(reportSettings));
}

/**
 * Map a bmd_stat key to a human-readable label for table column headers.
 * Mirrors the server-side _BMD_STAT_LABELS dict.
 */
function _bmdStatLabel(stat) {
    const labels = {
        mean: 'Mean', median: 'Median', minimum: 'Minimum',
        weighted_mean: 'Weighted Mean', fifth_pct: '5th %ile',
        tenth_pct: '10th %ile', lower95: 'Lower 95%', upper95: 'Upper 95%',
    };
    return labels[stat] || stat;
}

/**
 * Extract the best available gene_sets array from genomics data.
 * Prefers gene_sets_by_stat (picks the first stat's list),
 * falls back to legacy gene_sets field.
 */
function _flattenGeneSets(data) {
    if (data.gene_sets_by_stat) {
        const first = Object.values(data.gene_sets_by_stat).find(s => s && s.length > 0);
        if (first) return first;
    }
    return data.gene_sets || [];
}

/**
 * Apply settings and re-run the full processing pipeline.
 *
 * Saves current settings, then calls the server's process-integrated
 * endpoint directly (bypassing autoProcessPool's guards and assumptions).
 * Clears and rebuilds all apical and genomics cards with the new data.
 */
async function applySettings() {
    onSettingChanged();

    const dtxsid = currentIdentity?.dtxsid;
    if (!dtxsid) {
        showToast('Resolve a chemical first before reprocessing');
        return;
    }

    // Close the settings panel
    toggleSettingsPanel();

    // Build request body with all current settings
    const compoundName = currentIdentity?.name || 'Test Compound';
    let doseUnit = reportSettings.dose_unit || 'mg/kg';
    const processBody = {
        compound_name: compoundName,
        dose_unit: doseUnit,
        bmd_stats: reportSettings.bmd_stats || ['median'],
        go_pct: reportSettings.go_pct ?? 5,
        go_min_genes: reportSettings.go_min_genes ?? 20,
        go_max_genes: reportSettings.go_max_genes ?? 500,
        go_min_bmd: reportSettings.go_min_bmd ?? 3,
    };

    try {
        showBlockingSpinner('Reprocessing with new settings...');

        const resp = await fetch(`/api/process-integrated/${dtxsid}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(processBody),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            showToast(err.error || 'Reprocessing failed');
            return;
        }

        const result = await resp.json();

        // --- Rebuild apical section cards ---
        // Clear the platform containers and state, then recreate from response
        for (const pc of document.querySelectorAll('.platform-container')) {
            pc.querySelectorAll('.bm2-card').forEach(c => c.remove());
        }
        for (const secId of Object.keys(apicalSections)) {
            delete apicalSections[secId];
        }

        for (const section of (result.sections || [])) {
            const sectionId = 'integrated-' + section.domain;

            apicalSections[sectionId] = {
                fileId:            null,
                filename:          section.title,
                processed:         true,
                approved:          false,
                tableData:         section.tables_json,
                narrative:         section.narrative,
                originalNarrative: (section.narrative || []).join('\n\n'),
                domain:            section.domain,
                tableType:         section.table_type || null,
            };

            createBm2Card(sectionId, section.title, section.domain);

            const unitEl = document.getElementById(`bm2-unit-${sectionId}`);
            if (unitEl) unitEl.value = doseUnit;
            const compoundEl = document.getElementById(`bm2-compound-${sectionId}`);
            if (compoundEl) compoundEl.value = compoundName;

            renderBm2Results(sectionId, section.tables_json, section.narrative, section.table_type);
        }
        // Note: Alpine store readiness flags are set by getPlatformContainer()
        // when cards are created — no explicit show() needed here.

        // --- Rebuild genomics cards ---
        // Clear the genomics card containers and TOC children
        const geneSetCards = document.getElementById('genomics-gene-set-cards');
        if (geneSetCards) geneSetCards.innerHTML = '';
        const geneBmdCards = document.getElementById('genomics-gene-bmd-cards');
        if (geneBmdCards) geneBmdCards.innerHTML = '';
        const tocGeneSets = document.getElementById('toc-gene-set-children');
        if (tocGeneSets) tocGeneSets.innerHTML = '';
        const tocGeneBmd = document.getElementById('toc-gene-bmd-children');
        if (tocGeneBmd) tocGeneBmd.innerHTML = '';
        for (const key of Object.keys(genomicsResults)) {
            delete genomicsResults[key];
        }

        const statLabelsMap = result.bmd_stat_labels || null;
        if (result.chart_images) {
            chartImagesCache = result.chart_images;
        }
        if (result.genomics_sections) {
            for (const [key, gData] of Object.entries(result.genomics_sections)) {
                genomicsResults[key] = { ...gData };
                createGenomicsCard(key, gData, gData.organ, gData.sex, statLabelsMap);
            }
        }
        if (Object.keys(genomicsResults).length > 0 && typeof Alpine !== 'undefined' && Alpine.store('app')) {
            Alpine.store('app').ready.geneSets = true;
            Alpine.store('app').ready.geneBmd = true;
        }

        // --- Rebuild BMD summary from apical_bmd_summary ---
        if (result.apical_bmd_summary && result.apical_bmd_summary.length > 0) {
            bmdSummaryEndpoints = result.apical_bmd_summary;
            renderBmdSummaryTable(bmdSummaryEndpoints);
            if (typeof Alpine !== 'undefined' && Alpine.store('app')) {
                Alpine.store('app').ready.bmdSummary = true;
            }
        }
        if (result.apical_bmd_narrative) {
            apicalBmdNarrative = result.apical_bmd_narrative;
            renderBmdSummaryNarrative(result.apical_bmd_narrative);
        }

        // --- Rebuild BMDS summary (pybmds) ---
        if (result.apical_bmd_summary_bmds && result.apical_bmd_summary_bmds.length > 0) {
            renderBmdSummaryTableBmds(result.apical_bmd_summary_bmds);
            if (typeof Alpine !== 'undefined' && Alpine.store('app')) {
                Alpine.store('app').ready.bmdSummaryBmds = true;
            }
        }

        // Refresh export button
        updateExportButton();
        markReportDirty();

    } catch (e) {
        console.error('applySettings failed:', e);
        showToast('Reprocessing failed: ' + e.message);
    } finally {
        hideBlockingSpinner();
    }
}
