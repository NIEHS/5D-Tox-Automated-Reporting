/* -----------------------------------------------------------------
 * pipeline.js — Processing pipeline, BM2 approval, pool approval
 *
 * Split from sections.js.  Contains:
 *   - BM2 card approve/edit/retry workflows
 *   - Pool approval and animal report generation
 *   - autoProcessPool() and runProcessingPipeline() — the integrated
 *     processing pipeline that creates section cards from fingerprint
 *     data after pool approval
 *   - renderAnimalReport() — per-animal traceability report
 *   - approveSection() — generic section approval (methods, BMD summary, summary)
 *
 * Depends on: state.js (globals), utils.js (helpers), export.js,
 *             cards.js (createBm2Card, renderBm2Results),
 *             genomics.js (createGenomicsCard),
 *             validation.js (loadMetadataReview),
 *             methods_summary.js (showSummarySection),
 *             versions.js (showVersionHistory, loadStyleProfile)
 * ----------------------------------------------------------------- */

/* ================================================================
 * Approve / Try Again — .bm2 cards
 * ================================================================ */

/**
 * Approve a processed .bm2 card: save its narrative, table data,
 * and config fields to the server-side session.  Locks the card
 * for further editing and shows the green approved state.
 */
async function approveBm2(bm2Id) {
    if (!currentIdentity?.dtxsid) {
        showError('Resolve a chemical identity (with DTXSID) before approving.');
        return;
    }

    const info = apicalSections[bm2Id];
    if (!info) return;

    // Read current field values from the card
    const narrativeEl = document.getElementById(`bm2-narrative-${bm2Id}`);
    const narrative = narrativeEl?.value?.trim() || '';

    // Resolve the server-side file ID for the session store
    const serverFileId = info.fileId
        ? (uploadedFiles[info.fileId]?.id || info.fileId)
        : bm2Id;

    const data = {
        bm2_id: serverFileId,
        filename: info.filename,
        platform: info.platform || '',
        section_title: document.getElementById(`bm2-title-${bm2Id}`)?.value?.trim() || '',
        table_caption: document.getElementById(`bm2-caption-${bm2Id}`)?.value?.trim() || '',
        compound_name: document.getElementById(`bm2-compound-${bm2Id}`)?.value?.trim() || '',
        dose_unit: document.getElementById(`bm2-unit-${bm2Id}`)?.value?.trim() || 'mg/kg',
        narrative,
        tables_json: info.tableData || {},
        // Include original narrative so the server can detect edits
        // and learn writing style preferences from the diff
        original_narrative: info.originalNarrative || '',
        // "incidence" for clinical obs tables, null for normal apical tables.
        // Persisted so session restore can pass it to renderTablePreview.
        table_type: info.tableType || null,
    };

    const result = await postApproveToServer(
        'bm2',
        document.getElementById(`bm2-card-${bm2Id}`),
        bm2Id,
        data,
    );
    if (!result) return;

    info.approved = true;

    // If the user edited the narrative, show blue "Approved (edited)"
    // badge and trigger style profile reload after extraction completes
    const badge = document.getElementById(`badge-${bm2Id}`);
    if (result.user_edited) {
        badge.textContent = 'Approved (edited)';
        badge.classList.add('edited');
        setTimeout(() => loadStyleProfile(), 3000);
    } else {
        badge.textContent = 'Approved';
        badge.classList.remove('edited');
    }

    // Show version history button with the server-assigned version number
    showVersionHistory('bm2', result.version, bm2Id);

    // After approving a .bm2 section, load the BMD summary table.
    // This auto-derives LOEL/NOEL from all approved apical sections.
    loadBmdSummary();
}

/**
 * Try Again on a .bm2 card: unapprove on server, reset the card
 * to its unprocessed state so the user can reprocess it fresh.
 */
async function retryBm2(bm2Id) {
    const info = apicalSections[bm2Id];
    if (!info) return;

    // Build the slug from the filename for the unapprove call
    const slug = bm2Slug(info.filename);

    if (currentIdentity?.dtxsid) {
        try {
            await fetch('/api/session/unapprove', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    dtxsid: currentIdentity.dtxsid,
                    section_type: 'bm2',
                    bm2_slug: slug,
                }),
            });
        } catch (_) {
            // Non-critical
        }
    }

    // Reset card state
    info.approved = false;
    markReportDirty();
    info.processed = false;
    info.tableData = null;
    info.narrative = null;

    const card = document.getElementById(`bm2-card-${bm2Id}`);
    unlockSection(card);

    // Hide version history — regenerating from scratch
    hideVersionHistory('bm2', bm2Id);

    // Clear narrative and table preview
    const narrativeEl = document.getElementById(`bm2-narrative-${bm2Id}`);
    if (narrativeEl) narrativeEl.value = '';
    const previewEl = document.getElementById(`bm2-preview-${bm2Id}`);
    if (previewEl) previewEl.innerHTML = '';

    // Show Process button, hide all approve/edit/retry/badge buttons
    show(`btn-process-${bm2Id}`);
    document.getElementById(`btn-process-${bm2Id}`).disabled = false;
    document.getElementById(`btn-process-${bm2Id}`).textContent = 'Process';
    setButtons(bm2Id, 'hidden');

    updateExportButton();
    showToast(`${info.filename} — ready to reprocess`);
}

/**
 * Edit a .bm2 card: unlock the narrative textarea and config fields
 * for editing, remove the approved state, and re-show the Approve
 * button.  Does NOT unapprove on the server — the user can edit
 * and re-approve, triggering style learning from any differences.
 */
function editBm2(bm2Id) {
    const info = apicalSections[bm2Id];
    if (!info) return;

    // Unlock narrative textarea, config fields, and remove green border
    info.approved = false;
    markReportDirty();
    const card = document.getElementById(`bm2-card-${bm2Id}`);
    unlockSection(card);
    setButtons(bm2Id, 'editing');
    updateExportButton();
    showToast('Editing enabled — click Approve when done');
}

/**
 * Client-side .bm2 filename slugifier — mirrors the server's _bm2_slug().
 * Strips the compound prefix before the first hyphen, lowercases,
 * replaces non-alphanum runs with hyphens, removes .bm2 extension.
 */
function bm2Slug(filename) {
    let stem = filename.replace(/\.bm2$/i, '');
    if (stem.includes('-')) {
        stem = stem.split('-').slice(1).join('-');
    }
    return stem.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
}

/* ================================================================
 * Animal Report — per-animal traceability across all domains/tiers
 * ================================================================ */

/**
 * Approve the file pool — sign off on the validation and generate
 * the per-animal traceability report.
 *
 * This is the single "Approve" action in the validation workflow:
 *   1. Validate & Integrate → see issues, resolve conflicts
 *   2. Approve → generates animal report, locks the pool
 *
 * The animal report reads all files in the pool, extracts per-animal
 * data, and cross-references across tiers and domains.  The result
 * is rendered inside the validation panel and included in DOCX export.
 */
async function approvePool() {
    if (!currentIdentity?.dtxsid) {
        showError('Resolve a chemical identity first');
        return;
    }

    // Transient in-flight phase — set imperatively (not derived)
    AppStore.dispatch('pool.transition', 'APPROVING');

    showBlockingSpinner('Generating animal report...');
    try {
        const resp = await fetch(
            `/api/generate-animal-report/${currentIdentity.dtxsid}`,
            { method: 'POST' },
        );
        const result = await resp.json();

        if (result.error) {
            showError(result.error);
            // Approve failed — no animal report, derive phase (→ INTEGRATED)
            AppStore.dispatch('pool.transition', derivePoolPhase({
                hasFiles: true, hasStale: false, validationReport: lastValidationReport,
                hasValidationErrors: false, hasIntegrated: true, hasAnimalReport: false,
            }));
            return;
        }

        animalReportData = result;
        animalReportApproved = true;
        renderAnimalReport(result);

        // Approve succeeded — derive phase (→ APPROVED)
        AppStore.dispatch('pool.transition', derivePoolPhase({
            hasFiles: true, hasStale: false, validationReport: lastValidationReport,
            hasValidationErrors: false, hasIntegrated: true, hasAnimalReport: true,
        }));

        showToast('Pool approved — animal report generated');
        updateExportButton();

        // Auto-create and process all sections from fingerprint data.
        await autoProcessPool();

    } catch (e) {
        showError('Animal report generation failed: ' + e.message);
        // Approve failed — derive phase (→ INTEGRATED)
        AppStore.dispatch('pool.transition', derivePoolPhase({
            hasFiles: true, hasStale: false, validationReport: lastValidationReport,
            hasValidationErrors: false, hasIntegrated: true, hasAnimalReport: false,
        }));
    } finally {
        hideBlockingSpinner();
    }
}


/**
 * Auto-process all files in the upload pool after pool approval.
 *
 * Why this exists: after the user validates and approves the file pool,
 * the fingerprint data already tells us everything we need (file type,
 * domain, organ, sex, dose unit) to create and process every section
 * automatically.
 *
 * Data sources (all available at approval time):
 *   - uploadedFiles        — file IDs, filenames, types
 *   - lastValidationReport — fingerprints per file (domain, organ, sexes, dose_unit)
 *   - currentIdentity      — chemical name for compound field
 */
async function autoProcessPool() {
    // Fingerprint map from the last validation run — keyed by file ID.
    // Without fingerprints we can't determine section types, so bail out.
    const fingerprints = lastValidationReport?.fingerprints || {};
    if (Object.keys(fingerprints).length === 0) return;

    const dtxsid = document.getElementById('dtxsid')?.value?.trim();
    if (!dtxsid) return;

    showBlockingSpinner('Loading experiment metadata...');

    // Metadata approval is the gatekeeper: the user must review and approve
    // LLM-inferred experiment metadata (species, sex, organ, strain, etc.)
    // before we proceed to NTP stats and report section generation.
    // loadMetadataReview() shows the editable table.  If metadata is already
    // approved (restored session), it auto-proceeds to the processing pipeline.
    await loadMetadataReview();

    hideBlockingSpinner();
}


/**
 * Run the processing pipeline: NTP stats, apical section cards, genomics.
 *
 * Extracted from autoProcessPool so it can be called from two places:
 *   1. approveMetadata() — after the user approves experiment metadata
 *   2. loadMetadataReview() — when restoring a session with already-approved metadata
 *
 * This is the expensive step: it calls /api/process-integrated which runs
 * Williams trend, Dunnett's pairwise, and Jonckheere tests on the unified
 * BMDProject, then returns pre-computed sections for every domain plus
 * any genomics results from gene expression .bm2 files.
 */
async function runProcessingPipeline() {
    const fingerprints = lastValidationReport?.fingerprints || {};
    if (Object.keys(fingerprints).length === 0) return;

    const dtxsid = document.getElementById('dtxsid')?.value?.trim();
    if (!dtxsid) return;

    showBlockingSpinner('Integrating metadata...');

    // Note: results sections are shown reactively via Alpine store
    // flags — getPlatformContainer() sets ready.animalCondition,
    // ready.clinicalPath, etc. when cards are created.

    // --- Apical endpoint processing: single integrated call ---
    // Instead of processing each .bm2 file individually, call the
    // process-integrated endpoint which runs NTP stats on the unified
    // BMDProject and returns pre-computed sections for every domain.
    const compoundName = currentIdentity?.name || 'Test Compound';

    // Determine dose unit from fingerprints — pick the first one available
    let doseUnit = 'mg/kg';
    for (const fp of Object.values(fingerprints)) {
        if (fp.dose_unit) { doseUnit = fp.dose_unit; break; }
    }

    try {
        // First attempt: call process-integrated directly (uses in-memory or
        // on-disk integrated.json).  If it returns 400 (no integrated data),
        // re-run integration first, then retry.  This handles the case where
        // integrated.json was deleted or never included gene expression data.
        // Include the BMD statistic selection from settings so the server
        // can pick the right aggregate (mean, median, minimum, etc.)
        const processBody = {
            compound_name: compoundName,
            dose_unit: reportSettings.dose_unit || doseUnit,
            bmd_stats: reportSettings.bmd_stats || ['median'],
            go_pct: reportSettings.go_pct ?? 5,
            go_min_genes: reportSettings.go_min_genes ?? 20,
            go_max_genes: reportSettings.go_max_genes ?? 500,
            go_min_bmd: reportSettings.go_min_bmd ?? 3,
        };

        let resp = await fetch(`/api/process-integrated/${dtxsid}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(processBody),
        });

        if (resp.status === 400) {
            // Re-integrate the pool (regenerates integrated.json with all
            // domains including gene expression)
            const intResp = await fetch(`/api/pool/integrate/${dtxsid}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ identity: currentIdentity }),
            });
            if (intResp.ok) {
                // Retry process-integrated now that data exists
                resp = await fetch(`/api/process-integrated/${dtxsid}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(processBody),
                });
            }
        }

        if (resp.ok) {
            const result = await resp.json();
            const sections = result.sections || [];

            // Create a section card for each platform returned by the server.
            // Each card is wrapped in try/catch so one bad section doesn't
            // prevent unified narratives and BMD summary from rendering.
            for (const section of sections) {
                try {
                    const sectionId = 'integrated-' + section.platform;

                    // Skip if already created (idempotent)
                    if (apicalSections[sectionId]) continue;

                    // Register in state.  Store all fields the server sends
                    // so the export payload and HTML preview can use them.
                    // Body weight sections include extra fields from the
                    // sidecar builder (footnotes, bmd_definition, etc.)
                    // that other platforms don't have.
                    apicalSections[sectionId] = {
                        fileId:            null,   // not tied to a single file
                        filename:          section.title,
                        processed:         true,
                        approved:          false,
                        tableData:         section.tables_json,
                        narrative:         section.narrative,
                        originalNarrative: Array.isArray(section.narrative)
                        ? section.narrative.join('\n\n')
                        : (section.narrative || ''),
                        platform:          section.platform,
                        // "incidence" for clinical obs tables (n/N cells),
                        // undefined for normal apical tables (mean±SE cells).
                        tableType:         section.table_type || null,
                        // Rule-based builder fields (footnotes, caption, etc.)
                        // These flow through to the export payload and Typst.
                        footnotes:               section.footnotes || null,
                        firstColHeader:          section.first_col_header || null,
                        caption:                 section.caption || null,
                        bmdDefinition:           section.bmd_definition || null,
                        significanceExplanation:  section.significance_explanation || null,
                        significanceMarkerLegend: section.significance_marker_legend || null,
                    };

                    // Create the visual card and populate it — pass the platform
                    // so the card picks the correct NIEHS-style title/caption.
                    createBm2Card(sectionId, section.title, section.platform);

                    // Pre-fill the dose unit and compound fields
                    const unitEl = document.getElementById(`bm2-unit-${sectionId}`);
                    if (unitEl) unitEl.value = doseUnit;
                    const compoundEl = document.getElementById(`bm2-compound-${sectionId}`);
                    if (compoundEl) compoundEl.value = compoundName;

                    // Render the table data and narrative directly (no processBm2 call)
                    renderBm2Results(sectionId, section.tables_json, section.narrative, section.table_type);
                } catch (cardErr) {
                    console.error(`Failed to create card for ${section.platform}:`, cardErr);
                }
            }

            // --- Confirm platforms in pool state from actual sections ---
            // The server may produce a slightly different platform set
            // than validation predicted (e.g., clinical obs only appears
            // if categorical data was detected).  Update the pool state
            // with the confirmed set so the TOC stays accurate.
            const processedPlatforms = sections
                .map(s => s.platform)
                .filter(Boolean);
            if (processedPlatforms.length > 0) {
                AppStore.dispatch('pool.setPlatforms', processedPlatforms);
            }

            // --- Pre-rendered chart images (Layer 2.5 of pipeline) ---
            // Cached server-side during process-integrated so PDF previews
            // and exports never re-render Plotly charts or call Enrichr.
            if (result.chart_images) {
                chartImagesCache = result.chart_images;
            }

            // --- Gene expression: extracted from the integrated .bm2 ---
            // The process-integrated endpoint also returns genomics_sections
            // if a gene expression .bm2 was included in the integration.
            // BMDExpress's own prefilter → curve fit → BMD pipeline already
            // ran, and we read its results directly (no CSV re-analysis).

            // Capture the shared Gene Set / Gene BMD body narratives
            // BEFORE the per-organ cards render, so _rebuildOrganDisplays
            // can read `by_organ[organ]` when building each organ's panel.
            // The same dict round-trips to the server for PDF export, so
            // the HTML in-app view and the PDF render identical prose.
            if (result.gene_set_narrative) {
                genomicsGeneSetNarrative = result.gene_set_narrative;
            }
            if (result.gene_narrative) {
                genomicsGeneNarrative = result.gene_narrative;
            }
            // Render the methodology + caveat intro paragraphs now —
            // they live at the section level (above the per-organ
            // panels), so their rendering doesn't depend on any
            // particular organ panel existing yet.
            if (typeof _rebuildGenomicsIntros === 'function') {
                _rebuildGenomicsIntros();
            }

            if (result.genomics_sections) {
                const autoStatLabels = result.bmd_stat_labels || null;
                for (const [key, gData] of Object.entries(result.genomics_sections)) {
                    // Skip sections that were already restored and approved
                    // from a prior session — don't overwrite user-approved data.
                    // But DO create cards for new sections (e.g. liver_male
                    // missing from a session saved before all sections existed).
                    if (genomicsResults[key]?.approved) continue;

                    genomicsResults[key] = {
                        ...gData,
                        approved: false,
                    };

                    createGenomicsCard(key, gData, gData.organ, gData.sex, autoStatLabels);

                    // Pre-fill dose unit and compound fields (same as apical cards)
                    const gUnitEl = document.getElementById(`genomics-unit-${key}`);
                    if (gUnitEl) gUnitEl.value = doseUnit;
                    const gCompoundEl = document.getElementById(`genomics-compound-${key}`);
                    if (gCompoundEl) gCompoundEl.value = compoundName;
                }
            }

            // --- Apical BMD summary (Table 8 equivalent) ---
            // The process-integrated endpoint now returns apical_bmd_summary
            // with BMD, BMDL, LOEL, NOEL, direction for all modeled endpoints.
            if (result.apical_bmd_summary && result.apical_bmd_summary.length > 0) {
                bmdSummaryEndpoints = result.apical_bmd_summary;
                renderBmdSummaryTable(bmdSummaryEndpoints);
                if (typeof Alpine !== 'undefined' && Alpine.store('app')) {
                    Alpine.store('app').ready.bmdSummary = true;
                }
                markReportDirty();
            }

            // --- BMDS summary (pybmds — EPA BMDS methodology) ---
            if (result.apical_bmd_summary_bmds && result.apical_bmd_summary_bmds.length > 0) {
                renderBmdSummaryTableBmds(result.apical_bmd_summary_bmds);
                if (typeof Alpine !== 'undefined' && Alpine.store('app')) {
                    Alpine.store('app').ready.bmdSummaryBmds = true;
                }
                markReportDirty();
            }

            // --- Unified narratives ---
            // Populate group-level narrative textareas from the server response.
            // These are cross-platform narratives (e.g., one narrative covering
            // all of Clinical Pathology rather than per-endpoint).
            if (result.unified_narratives) {
                if (typeof Alpine !== 'undefined' && Alpine.store('app')) {
                    Alpine.store('app').unifiedNarratives = result.unified_narratives;
                }
                for (const [key, data] of Object.entries(result.unified_narratives)) {
                    const ta = document.getElementById(`narrative-${key}`);
                    if (ta && data.paragraphs) {
                        ta.value = data.paragraphs.join('\n\n');
                    }
                }
            }

            // --- Materials and Methods (auto-generated by pipeline) ---
            // The server generates M&M prose from fingerprints + .bm2
            // metadata during process-integrated, eliminating the need
            // for a separate "Generate" button click.  The result has
            // the same structure as /api/generate-methods: sections array,
            // context dict, and optional table1.
            if (result.methods && result.methods.sections && result.methods.sections.length > 0) {
                methodsData = result.methods;
                showMethodsSection();
                displayMethodsSections(result.methods.sections, result.methods.table1 || null);
                // Show approve/retry buttons (user can review before approving)
                document.getElementById('btn-generate-methods').style.display = 'none';
                setButtons('methods', 'result');
                markReportDirty();
            }
        } else {
            const err = await resp.json().catch(e => { console.error('JSON parse failed:', e); return {}; });
            showToast(err.error || 'Integrated processing failed');
        }
    } catch (e) {
        showToast('Integrated processing failed: ' + e.message);
    }

    // Show genomics sections if any genomics results were created
    if (Object.keys(genomicsResults).length > 0 && typeof Alpine !== 'undefined' && Alpine.store('app')) {
        Alpine.store('app').ready.geneSets = true;
        Alpine.store('app').ready.geneBmd = true;
    }

    // Show Methods and Summary sections now that processing is complete.
    // Methods may already have been populated above (if the LLM succeeded),
    // but we still call showMethodsSection() to ensure the section is
    // visible even if the user wants to generate manually.
    showMethodsSection();
    showSummarySection();

    updateExportButton();
    hideBlockingSpinner();
}


/**
 * Render the animal report data as HTML tables in the UI.
 *
 * Builds five subsections:
 *   A. Study design summary with dose × sex table
 *   B. Scrollable animal roster with domain tier presence columns
 *   C. Domain coverage matrix (reuses .coverage-matrix CSS)
 *   D. Attrition lists grouped by exclusion reason
 *   E. Consistency check results
 *
 * @param {Object} report — the AnimalReport dict from the API
 */
function renderAnimalReport(report) {
    const container = document.getElementById('animal-report-content');

    // Shared platform label lookup — platform strings are already
    // human-readable, so this is effectively a pass-through via
    // domainLabel() from state.js.
    const domainFullLabels = new Proxy({}, {
        get: (_, key) => domainLabel(key),
    });

    // Helper: build a collapsible section.  The summary line is always
    // visible; clicking it toggles the body.  Starts collapsed.
    function collapse(id, summary, bodyHtml) {
        return `<div class="ar-collapse" id="ar-${id}">` +
            `<div class="ar-collapse-header" onclick="this.parentElement.classList.toggle('ar-open')">` +
            `<span class="ar-chevron">▸</span> ${summary}</div>` +
            `<div class="ar-collapse-body">${bodyHtml}</div></div>`;
    }

    let html = '';

    // --- Top-level summary line (always visible, not collapsible) ---
    const study = report.study_number || 'Unknown study';
    const selDetail = report.biosampling_count > 0
        ? ` (${report.core_count} core, ${report.biosampling_count} biosampling)`
        : '';
    const nPlatforms = Object.keys(report.domain_coverage || {}).length;
    html += `<div class="ar-summary">`;
    html += `<strong>${study}</strong> · ${report.total_animals} animals${selDetail} · `;
    html += `${report.dose_groups?.length || 0} dose groups · ${nPlatforms} assay platforms`;
    html += `</div>`;

    // --- A. Study Design (dose × sex table) ---
    if (report.dose_design && Object.keys(report.dose_design).length > 0) {
        const allSexes = new Set();
        for (const sexes of Object.values(report.dose_design)) {
            for (const sex of Object.keys(sexes)) allSexes.add(sex);
        }
        const sexList = [...allSexes].sort();

        let tbl = `<table class="coverage-matrix">`;
        tbl += `<tr><th>Dose (mg/kg)</th>`;
        for (const sex of sexList) tbl += `<th>${sex}</th>`;
        tbl += `<th>Total</th></tr>`;
        for (const dose of report.dose_groups) {
            const doseKey = String(dose);
            const sexCounts = report.dose_design[doseKey] || {};
            let total = 0;
            const doseLabel = Number(dose) === Math.floor(Number(dose)) ? Math.floor(Number(dose)) : dose;
            tbl += `<tr><td>${doseLabel}</td>`;
            for (const sex of sexList) {
                const count = sexCounts[sex] || 0;
                total += count;
                tbl += `<td>${count}</td>`;
            }
            tbl += `<td><strong>${total}</strong></td></tr>`;
        }
        tbl += `</table>`;

        const doseRange = report.dose_groups.length > 1
            ? `${report.dose_groups[0]}–${report.dose_groups[report.dose_groups.length - 1]} mg/kg`
            : `${report.dose_groups[0]} mg/kg`;
        html += collapse('design',
            `<strong>Study Design</strong> — ${sexList.join(' & ')}, ${report.dose_groups.length} groups (${doseRange})`,
            tbl);
    }

    // --- B. Domain Coverage (compact table with attrition columns) ---
    if (report.domain_coverage && Object.keys(report.domain_coverage).length > 0) {
        let tbl = `<table class="coverage-matrix">`;
        tbl += `<tr><th>Platform</th><th>xlsx</th><th>txt/csv</th><th>bm2</th><th>Dropped</th><th>Completeness</th></tr>`;

        for (const domain of Object.keys(report.domain_coverage).sort()) {
            const cov = report.domain_coverage[domain];
            const att = report.attrition?.[domain] || {};
            const totalDropped = (att.excluded_xlsx_to_txt?.length || 0) + (att.excluded_txt_to_bm2?.length || 0);
            const comp = report.completeness?.[domain];
            const compPct = comp != null ? `${Math.round(comp * 100)}%` : '—';

            tbl += `<tr>`;
            tbl += `<td>${domainFullLabels[domain] || domain}</td>`;
            tbl += `<td>${cov.xlsx || '—'}</td>`;
            tbl += `<td>${cov.txt_csv || '—'}</td>`;
            tbl += `<td>${cov.bm2 || '—'}</td>`;
            tbl += `<td>${totalDropped || '—'}</td>`;
            tbl += `<td>${compPct}</td>`;
            tbl += `</tr>`;
        }
        tbl += `</table>`;

        // Count platforms at 100% vs those with attrition
        const fullPlatforms = Object.values(report.completeness || {}).filter(c => c >= 1.0).length;
        const partialPlatforms = nPlatforms - fullPlatforms;
        const coverageSummary = partialPlatforms > 0
            ? `${fullPlatforms} complete, ${partialPlatforms} with attrition`
            : `all ${nPlatforms} platforms complete`;

        html += collapse('coverage',
            `<strong>Platform Coverage</strong> — ${nPlatforms} platforms, ${coverageSummary}`,
            tbl);
    }

    // --- C. Attrition Detail (per-domain exclusion reasons) ---
    if (report.attrition && Object.keys(report.attrition).length > 0) {
        // Check if there's any attrition at all
        let totalExclusions = 0;
        for (const att of Object.values(report.attrition)) {
            for (const ids of Object.values(att.exclusion_reasons || {})) {
                totalExclusions += (ids?.length || 0);
            }
        }

        if (totalExclusions > 0) {
            let body = '';
            for (const domain of Object.keys(report.attrition).sort()) {
                const att = report.attrition[domain];
                const reasons = att.exclusion_reasons || {};
                if (Object.keys(reasons).length === 0) continue;

                const domainLabel = domainFullLabels[domain] || domain;
                body += `<div class="attrition-group">`;
                body += `<strong>${domainLabel}</strong>`;
                body += `<ul>`;
                for (const [reasonKey, animalIds] of Object.entries(reasons)) {
                    if (!animalIds || animalIds.length === 0) continue;
                    const transition = reasonKey.includes('xlsx_to_txt') ? 'xlsx→txt' : 'txt→bm2';
                    const reason = reasonKey
                        .replace('xlsx_to_txt_', '')
                        .replace('txt_to_bm2_', '')
                        .replace(/_/g, ' ')
                        .replace(/\b\w/g, c => c.toUpperCase());
                    const preview = animalIds.slice(0, 8).join(', ');
                    const more = animalIds.length > 8 ? `, +${animalIds.length - 8} more` : '';
                    body += `<li>${transition} ${reason}: <strong>${animalIds.length}</strong> (${preview}${more})</li>`;
                }
                body += `</ul></div>`;
            }

            html += collapse('attrition',
                `<strong>Attrition Detail</strong> — ${totalExclusions} animals excluded across platforms`,
                body);
        }
    }

    // --- D. Animal Roster (full per-animal table, collapsed by default) ---
    if (report.animals && Object.keys(report.animals).length > 0) {
        // Platform ordering derived from the document tree (single source
        // of truth) rather than a hardcoded array.  Falls back to a static
        // list if the tree hasn't loaded yet.
        const domainOrder = (typeof collectPlatformOrder === 'function' && collectPlatformOrder().length > 0)
            ? [...collectPlatformOrder(), 'Gene Expression']  // Gene Expression not in tree (genomics section, not a table)
            : ['Body Weight', 'Organ Weights', 'Clinical Chemistry', 'Hematology',
               'Hormones', 'Tissue Concentration', 'Clinical', 'Gene Expression'];
        const domainShort = {
            'Body Weight': 'BW', 'Organ Weights': 'OW', 'Clinical Chemistry': 'CC',
            'Hematology': 'Hem', 'Hormones': 'Horm', 'Tissue Concentration': 'TC',
            'Clinical': 'CO', 'Gene Expression': 'GE',
        };
        const activeDomains = domainOrder.filter(d => report.domain_coverage?.[d]);

        let tbl = `<div class="animal-roster-wrapper">`;
        tbl += `<table class="animal-roster-table">`;
        tbl += `<tr><th>ID</th><th>Sex</th><th>Dose</th><th>Sel</th>`;
        for (const d of activeDomains) {
            tbl += `<th title="${domainFullLabels[d] || d}">${domainShort[d] || d}</th>`;
        }
        tbl += `</tr>`;

        const sortedIds = Object.keys(report.animals).sort((a, b) => {
            const na = parseInt(a), nb = parseInt(b);
            if (!isNaN(na) && !isNaN(nb)) return na - nb;
            return a.localeCompare(b);
        });

        for (const aid of sortedIds) {
            const rec = report.animals[aid];
            const dose = rec.dose != null
                ? (Number(rec.dose) === Math.floor(Number(rec.dose)) ? Math.floor(Number(rec.dose)) : rec.dose)
                : '';
            tbl += `<tr>`;
            tbl += `<td>${aid}</td>`;
            tbl += `<td>${rec.sex || ''}</td>`;
            tbl += `<td>${dose}</td>`;
            tbl += `<td>${rec.selection ? rec.selection.replace('Core Animals', 'Core').replace('Biosampling Animals', 'Bio') : ''}</td>`;
            for (const domain of activeDomains) {
                const presence = rec.domain_presence?.[domain] || {};
                const x = presence.xlsx ? 'X' : '-';
                const t = presence.txt_csv ? 'T' : '-';
                const b = presence.bm2 ? 'B' : '-';
                const code = `${x}${t}${b}`;
                const cls = code === 'XTB' ? 'tier-full'
                    : code === '---' ? 'tier-absent'
                    : 'tier-partial';
                tbl += `<td class="${cls}">${code}</td>`;
            }
            tbl += `</tr>`;
        }
        tbl += `</table></div>`;

        const nAnimals = Object.keys(report.animals).length;
        html += collapse('roster',
            `<strong>Animal Roster</strong> — ${nAnimals} animals, per-animal tier presence (X=xlsx T=txt B=bm2)`,
            tbl);
    }

    // --- E. Consistency Checks ---
    const nIssues = report.consistency_issues?.length || 0;
    if (nIssues > 0) {
        let body = '<ul>';
        for (const issue of report.consistency_issues) {
            if (issue.type === 'sex_mismatch') {
                body += `<li>Animal ${issue.animal_id}: sex mismatch — ${issue.details?.sexes_found?.join(', ') || '?'}</li>`;
            } else if (issue.type === 'dose_mismatch') {
                body += `<li>Animal ${issue.animal_id}: dose mismatch — ${issue.details?.doses_found?.join(', ') || '?'}</li>`;
            } else {
                body += `<li>Animal ${issue.animal_id}: ${issue.type}</li>`;
            }
        }
        body += '</ul>';
        html += collapse('consistency',
            `<strong>Consistency Checks</strong> — <span style="color:var(--c-error)">${nIssues} issue${nIssues > 1 ? 's' : ''} found</span>`,
            body);
    } else {
        html += `<div class="ar-summary-ok">Consistency: no issues detected</div>`;
    }

    container.innerHTML = html;
}



/* ----------------------------------------------------------------
 * Generic section approve (for methods, bmd_summary, summary)
 * ---------------------------------------------------------------- */

/**
 * Approve a paragraph-based section (methods or summary) or the
 * BMD summary table.  Sends the data to the server and locks the
 * section in the UI.
 */
async function approveSection(sectionType) {
    // Build the section-specific data payload and identify the DOM
    // element + button prefix for the postApproveToServer helper.
    let data = {};
    let sectionEl, buttonPrefix;

    if (sectionType === 'methods') {
        // Save in structured format if available, with legacy flat paragraphs
        // as a fallback for the session restore path.
        const editedSections = extractMethodsSections();
        const flatParas = extractProse('methods-prose');
        // Build original_paragraphs from the stored methodsData sections
        // so the server-side style learning can detect user edits.
        const originalParas = (methodsData?.sections || [])
            .flatMap(s => s.paragraphs || []);
        data = {
            sections: editedSections.length > 0 ? editedSections : undefined,
            context: methodsData?.context || undefined,
            paragraphs: flatParas,
            original_paragraphs: originalParas,
            original_data: methodsData || undefined,
        };
        sectionEl = document.getElementById('methods-section');
        buttonPrefix = 'methods';
    } else if (sectionType === 'bmd_summary') {
        data = { endpoints: bmdSummaryEndpoints };
        sectionEl = document.getElementById('bmd-summary-section');
        buttonPrefix = 'bmd-summary';
    } else if (sectionType === 'summary') {
        data = {
            paragraphs: extractProse('summary-prose'),
            original_paragraphs: summaryParagraphs,
        };
        sectionEl = document.getElementById('summary-section');
        buttonPrefix = 'summary';
    }

    const result = await postApproveToServer(sectionType, sectionEl, buttonPrefix, data);
    if (!result) return;

    // Set the section-specific approved flag
    if (sectionType === 'methods')          methodsApproved = true;
    else if (sectionType === 'bmd_summary') bmdSummaryApproved = true;
    else if (sectionType === 'summary')     summaryApproved = true;
}
