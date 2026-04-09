/* -----------------------------------------------------------------
 * chemical.js — Chemical identity resolution and session restore
 *
 * Handles the chemical ID form: blur/Enter resolves via /api/resolve,
 * populates fields, persists to localStorage, and auto-restores
 * saved sessions when a known DTXSID is entered.
 *
 * Depends on: state.js (globals), utils.js (helpers), versions.js,
 *             settings.js, layout.js, export.js, genomics.js
 * ----------------------------------------------------------------- */

/* ================================================================
 * Auto-resolve on blur — when user tabs out of any ID field,
 * resolve via /api/resolve and populate the other fields
 * ================================================================ */


// Attach blur, keydown, and input handlers to each ID field.
// - blur/Enter: trigger resolve
// - input: clear stale resolved values from other fields so the
//   user sees a clean form when typing a new chemical
fields.forEach(fieldId => {
    const input = document.getElementById(fieldId);
    input.addEventListener('blur', () => onFieldBlur(fieldId));
    input.addEventListener('keydown', e => {
        if (e.key === 'Enter') {
            e.preventDefault();
            onFieldBlur(fieldId);
        }
    });
    // When the user starts typing in any field, clear the other
    // fields' resolved values.  This prevents stale data from the
    // previous chemical lingering while the user enters a new one.
    input.addEventListener('input', () => {
        // Only clear if the fields were previously resolved —
        // avoid clearing during programmatic population.
        if (!lastResolvedValue) return;
        const currentValue = input.value.trim();
        // If the user changed the value away from what was resolved,
        // clear the other fields and reset the resolved state.
        if (currentValue !== lastResolvedValue) {
            fields.forEach(f => {
                if (f !== fieldId) {
                    document.getElementById(f).value = '';
                }
                document.getElementById(f).classList.remove('resolved');
            });
            lastResolvedValue = null;
            currentIdentity = null;
            document.getElementById('btn-generate').disabled = true;
        }
    });
});

/**
 * Called when a user tabs out of or presses Enter in an ID field.
 * If the field has a value, we send it to /api/resolve and fill in
 * the other fields with the resolved data.
 */
async function onFieldBlur(fieldId) {
    const input = document.getElementById(fieldId);
    const value = input.value.trim();

    // Skip if empty or if we already resolved this exact value
    if (!value) return;
    if (value === lastResolvedValue) return;

    // Increment the generation counter so any in-flight resolve
    // from a previous onFieldBlur call knows it's been superseded.
    // For example: page loads → restoreChemId() triggers resolve
    // for the old DTXSID → user types a new name and blurs →
    // this new resolve supersedes the old one.
    const thisGeneration = ++resolveGeneration;

    isResolving = true;
    hideError();

    // Mark all fields as "resolving" (visual indicator)
    fields.forEach(f => document.getElementById(f).classList.add('resolving'));

    try {
        const resp = await fetch('/api/resolve', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                identifier: value,
                id_type: idTypeMap[fieldId] || 'auto',
            }),
        });

        // If a newer resolve was started while this one was
        // in-flight, discard this result — the newer one wins.
        if (thisGeneration !== resolveGeneration) return;

        if (!resp.ok) {
            const err = await resp.json();
            showError(err.error || 'Resolution failed');
            return;
        }

        currentIdentity = await resp.json();

        // Populate fields with resolved values
        document.getElementById('name').value = currentIdentity.name || '';
        document.getElementById('casrn').value = currentIdentity.casrn || '';
        document.getElementById('dtxsid').value = currentIdentity.dtxsid || '';
        document.getElementById('cid').value = currentIdentity.pubchem_cid || '';
        document.getElementById('ec').value = currentIdentity.ec_number || '';
        document.getElementById('iupac').value = currentIdentity.iupac_name || '';

        // Track what we just resolved so the input listener can
        // detect when the user changes it to something new
        lastResolvedValue = value;

        // Persist the resolved values to localStorage so they
        // survive page reloads without re-resolving
        saveChemId();

        // Mark fields as resolved (green border)
        fields.forEach(f => {
            const el = document.getElementById(f);
            el.classList.remove('resolving');
            if (el.value) el.classList.add('resolved');
            else el.classList.remove('resolved');
        });

        // Enable Process buttons and backfill compound name
        onIdentityResolved();

        // Show the data tab immediately — file upload and pool management
        // should be available as soon as a chemical is resolved, without
        // waiting for background generation.
        if (typeof Alpine !== 'undefined' && Alpine.store('app')) {
            Alpine.store('app').ready.data = true;
        }

        // Show Reset Session button now that a chemical is resolved
        const btnResetSession = document.getElementById('btn-reset-session');
        if (btnResetSession) btnResetSession.style.display = '';

        // Auto-restore: if the DTXSID has a previously saved session,
        // load it and restore all approved sections (background + bm2 cards).
        // This lets the user close the browser and pick up right where
        // they left off just by re-entering the same chemical.
        if (currentIdentity.dtxsid) {
            try {
                const sessionResp = await fetch(`/api/session/${currentIdentity.dtxsid}`);
                const sessionData = await sessionResp.json();
                // Double-check we're still the active resolve — a new
                // resolve could have started during the session fetch.
                if (thisGeneration !== resolveGeneration) return;
                if (sessionData.exists) {
                    await restoreSession(sessionData);
                }
            } catch (_) {
                // Non-critical — session restore is a convenience, not required
            }
        }

    } catch (err) {
        // Only show error if this is still the active resolve
        if (thisGeneration === resolveGeneration) {
            showError('Network error during resolution: ' + err.message);
            fields.forEach(f => document.getElementById(f).classList.remove('resolving'));
        }
    } finally {
        // Only clear the flag if this is the latest resolve
        if (thisGeneration === resolveGeneration) {
            isResolving = false;
        }
    }
}

/**
 * Called after chemical identity is resolved.  Enables Process
 * buttons on all .bm2 cards (they're disabled until we have a
 * compound name), backfills the compound name field on cards
 * that haven't been processed yet, and enables the Export button.
 */
function onIdentityResolved() {
    const name = currentIdentity?.name || '';

    // Enable Process buttons and fill compound name on unprocessed cards
    for (const [sectionId, info] of Object.entries(apicalSections)) {
        const btn = document.getElementById(`btn-process-${sectionId}`);
        if (btn && !info.processed) {
            btn.disabled = false;
        }
        // Backfill compound name if the field is still empty
        const compoundEl = document.getElementById(`bm2-compound-${sectionId}`);
        if (compoundEl && !compoundEl.value.trim()) {
            compoundEl.value = name;
        }
    }

    // Enable Generate Background button (Export is gated on approvals)
    const genBtn = document.getElementById('btn-generate');
    if (genBtn) genBtn.disabled = false;

    // Update export button state — it's now gated on all sections
    // being approved, not just on identity being resolved.
    updateExportButton();

    // Update front matter sections that contain the test article name.
    // The peer review boilerplate inserts the full title dynamically.
    updateFrontMatterIdentity();
}


/**
 * Update front matter HTML sections that reference the test article.
 *
 * The peer review section contains a .ta-insert span that shows the
 * full report title.  This function fills it with the resolved chemical
 * name + CASRN + strain, matching what the Typst template produces.
 */
function updateFrontMatterIdentity() {
    if (!currentIdentity) return;

    const name = currentIdentity.name || 'the test article';
    const casrn = currentIdentity.casrn || '';
    const strain = '(Hsd:Sprague Dawley\u00ae SD\u00ae)';

    // Build the italicized full title for peer review insertion
    let fullTitle = `In Vivo Repeat Dose Biological Potency Study of ${name}`;
    if (casrn) fullTitle += ` (CASRN ${casrn})`;
    fullTitle += ` in Sprague Dawley ${strain} Rats (Gavage Studies)`;

    // Update all .ta-insert spans in front matter
    for (const el of document.querySelectorAll('.ta-insert')) {
        el.textContent = fullTitle;
    }
}


/**
 * Restore a previously-saved session for the current chemical.
 *
 * Populates the background section and/or .bm2 cards from the
 * saved JSON data, marks them as approved, and locks them for
 * editing.  Called after DTXSID resolution when the server returns
 * a saved session.
 *
 * @param {Object} data — the response from GET /api/session/{dtxsid}
 */
async function restoreSession(data) {
    // --- Restore background section ---
    if (data.background) {
        const bg = data.background;
        // Build a "result" object compatible with displayResult()
        const fakeResult = {
            paragraphs: bg.paragraphs || [],
            references: bg.references || [],
            model_used: bg.model_used || '',
            notes: bg.notes || [],
        };
        currentResult = fakeResult;

        // Display the content (this also shows the output section,
        // file pool via displayResult)
        displayResult(fakeResult);

        // Now lock it as approved — disable editing and add green border
        backgroundApproved = true;
        lockSection(document.getElementById('output-section'));
        setButtons('bg', 'approved');

        // Show version history with the version from the saved data
        showVersionHistory('background', bg.version || 1);
    }

    // --- Restore .bm2 sections ---
    // Determine whether the integrated pipeline will re-run on this restore.
    // If the pool is approved, autoProcessPool will create fresh domain-split
    // section cards (one per endpoint domain: body_weight, organ_weights,
    // hormones, etc.).  In that case, we should NOT restore old bm2 section
    // cards — they used a single monolithic card per .bm2 file which lumped
    // all domains together under one (wrong) header like "Body Weights and
    // Organ Weights" even for hormones or clinical chem data.
    //
    // We still register the files in uploadedFiles so they're available for
    // the integrated pipeline to find, and we stash the saved section data
    // (narratives, compound name, dose unit) in _restoredBm2Data so the
    // pipeline can carry forward user edits.
    const poolWillReprocess = !!data.animal_report;

    if (data.bm2_sections && Object.keys(data.bm2_sections).length > 0) {
        if (typeof Alpine !== 'undefined' && Alpine.store('app')) {
            Alpine.store('app').ready.data = true;
        }

        for (const [slug, section] of Object.entries(data.bm2_sections)) {
            const sectionId = 'restored-' + slug;

            // Register the .bm2 file in the upload pool so it's available
            // for reprocessing by the integrated pipeline.
            const fileId = section.server_file_id || ('file-restored-bm2-' + slug);
            const isServerBacked = !!section.server_file_id;
            uploadedFiles[fileId] = {
                id: fileId,
                filename: section.filename || slug,
                type: 'bm2',
                restored: !isServerBacked,
                fromSession: true,
            };
            renderFilePoolItem(fileId);

            // If the integrated pipeline will re-run, skip creating old
            // monolithic section cards — the pipeline will create proper
            // domain-split cards.  We stash saved data (compound name,
            // dose unit) so it can be carried forward.
            if (poolWillReprocess) continue;

            // --- Fallback: no pool approval, restore cards as before ---
            // This path handles sessions where the pool was never approved
            // (e.g., user uploaded a single .bm2 manually without using
            // the integrated pipeline).
            apicalSections[sectionId] = {
                fileId: fileId,
                filename: section.filename || slug,
                processed: true,
                approved: true,
                tableData: section.tables_json || {},
                narrative: section.narrative
                    ? section.narrative.split(/\n\s*\n/)
                    : [],
                domain: section.domain || '',
            };

            createBm2Card(sectionId, section.filename || slug, section.domain);

            // Fill in config fields from saved data
            const titleEl = document.getElementById(`bm2-title-${sectionId}`);
            if (titleEl && section.section_title) titleEl.value = section.section_title;
            const captionEl = document.getElementById(`bm2-caption-${sectionId}`);
            if (captionEl && section.table_caption) captionEl.value = section.table_caption;
            const compoundEl = document.getElementById(`bm2-compound-${sectionId}`);
            if (compoundEl && section.compound_name) compoundEl.value = section.compound_name;
            const unitEl = document.getElementById(`bm2-unit-${sectionId}`);
            if (unitEl && section.dose_unit) unitEl.value = section.dose_unit;
            const tableNumEl = document.getElementById(`bm2-table-number-${sectionId}`);
            if (tableNumEl && section.table_number) tableNumEl.value = section.table_number;

            const narrativeEl = document.getElementById(`bm2-narrative-${sectionId}`);
            if (narrativeEl && section.narrative) {
                narrativeEl.value = section.narrative;
                autoResizeTextarea(narrativeEl);
            }

            if (section.tables_json && Object.keys(section.tables_json).length > 0) {
                const doseUnit = section.dose_unit || 'mg/kg';
                renderTablePreview(sectionId, section.tables_json, doseUnit);
            }

            const card = document.getElementById(`bm2-card-${sectionId}`);
            lockSection(card);
            hide(`btn-process-${sectionId}`);
            // If the pool changed after this section was approved, the server
            // marks it stale — show amber badge instead of green Approved.
            setButtons(sectionId, section.stale ? 'stale' : 'approved');
            showVersionHistory('bm2', section.version || 1, sectionId);
        }
    }

    // --- Restore pending (unapproved) files from session directory ---
    // The server scans sessions/{dtxsid}/files/ for .bm2 files that
    // don't yet have an approved section and returns them as
    // pending_files.  We add them to the file pool so the user can
    // assign them to sections without re-uploading.
    if (data.pending_files && data.pending_files.length > 0) {
        // Make sure the data section is visible so the user can
        // assign pending files to report sections.
        if (typeof Alpine !== 'undefined' && Alpine.store('app')) {
            Alpine.store('app').ready.data = true;
        }



        for (const pf of data.pending_files) {
            // Skip if this file was already registered by the
            // bm2_sections restore above (it would have been matched
            // by server_file_id).
            if (uploadedFiles[pf.id]) continue;

            // Register the file in the client-side file map.
            // sessionPersisted=true hides the remove button (the file
            // lives in the session directory, removing it from the
            // pool would be confusing — it'd reappear on next load).
            // Unlike fromSession, we do NOT grey it out — it's an
            // actionable file the user still needs to process.
            uploadedFiles[pf.id] = {
                id:          pf.id,
                filename:    pf.filename,
                type:        pf.type || 'bm2',
                sessionPersisted: true,
            };
            renderFilePoolItem(pf.id);
        }
    }

    // --- Restore validation report (if any) ---
    // The server includes the last validation_report.json in the session
    // response.  If present, render the coverage matrix and issues list
    // so the user sees the validation state immediately on load.
    if (data.validation_report) {
        restoreValidationReport(data.validation_report);
    } else if (Object.keys(uploadedFiles).length > 0) {
        // Files exist but no validation report — show the panel with
        // gray dots so the user knows validation is available.
        showValidationPanel();
    }

    // --- Restore Materials and Methods section ---
    if (data.methods) {
        const methods = data.methods;
        showMethodsSection();

        // Detect structured vs legacy format.
        // Structured: has "sections" array from the new NIEHS-style generation.
        // Legacy: has "paragraphs" array from the old 5-paragraph generation.
        if (methods.sections && methods.sections.length > 0) {
            // Structured format — restore with headings and subsections
            methodsData = methods.original_data || methods;
            displayMethodsSections(
                methods.sections,
                methods.original_data?.table1 || methodsData?.table1 || null,
            );
        } else {
            // Legacy flat format — fall back to simple prose display
            methodsData = methods;
            const paras = methods.paragraphs || [];
            displayProse('methods-prose', paras);
        }

        // Lock as approved (disable editing, add green border)
        methodsApproved = true;
        lockSection(document.getElementById('methods-section'));
        hide('btn-generate-methods');
        setButtons('methods', 'approved');
    } else if (backgroundApproved) {
        // Show methods section even if not yet generated
        showMethodsSection();
    }

    // --- Restore BMD Summary ---
    if (data.bmd_summary) {
        const summary = data.bmd_summary;
        bmdSummaryEndpoints = summary.endpoints || [];
        if (bmdSummaryEndpoints.length > 0) {
            renderBmdSummaryTable(bmdSummaryEndpoints);
            if (typeof Alpine !== 'undefined' && Alpine.store('app')) {
                Alpine.store('app').ready.bmdSummary = true;
            }
            bmdSummaryApproved = true;
            lockSection(document.getElementById('bmd-summary-section'));
            setButtons('bmd-summary', 'approved');
        }
    }

    // --- Restore Genomics sections ---
    // For each saved genomics section: create a synthetic uploadedFiles
    // entry (type='csv', restored: true), render a greyed file pool item,
    // create a genomicsResults entry, and create the results card.
    if (data.genomics_sections && Object.keys(data.genomics_sections).length > 0) {
        if (typeof Alpine !== 'undefined' && Alpine.store('app')) {
            Alpine.store('app').ready.data = true;
            Alpine.store('app').ready.geneSets = true;
            Alpine.store('app').ready.geneBmd = true;
            Alpine.store('app').ready.charts = true;
        }

        for (const [slug, section] of Object.entries(data.genomics_sections)) {
            const organ = section.organ || '';
            const sex = section.sex || '';
            const key = `${organ}_${sex}`;

            // Create a synthetic uploadedFiles entry for the CSV
            const fileId = 'file-restored-csv-' + slug;
            if (!uploadedFiles[fileId]) {
                uploadedFiles[fileId] = {
                    id: fileId,
                    filename: section.filename || `${organ}_${sex}.csv`,
                    type: 'csv',
                    restored: true,
                };
                renderFilePoolItem(fileId);
            }

            genomicsResults[key] = {
                ...section,
                fileId: fileId,
                approved: true,
            };

            // Create the card and lock it as approved.
            // Build stat labels dict from current settings for column headers.
            const restoreLabels = {};
            for (const s of (reportSettings.bmd_stats || ['median'])) {
                restoreLabels[s] = _bmdStatLabel(s);
            }
            createGenomicsCard(key, section, organ, sex, restoreLabels);
            const card = document.getElementById(`genomics-card-${key}`);
            if (card) {
                lockSection(card);
                setButtons(`genomics-${key}`, section.stale ? 'stale' : 'approved');
            }
        }
    }

    // --- Restore Summary section ---
    if (data.summary) {
        const summary = data.summary;
        showSummarySection();
        summaryParagraphs = summary.original_paragraphs || summary.paragraphs || [];
        displayProse('summary-prose', summary.paragraphs || []);

        summaryApproved = true;
        lockSection(document.getElementById('summary-section'));
        hide('btn-generate-summary');
        setButtons('summary', 'approved');
    } else if (backgroundApproved) {
        showSummarySection();
    }

    // --- Restore Animal Report (if previously generated) ---
    // The animal report is persisted as animal_report.json in the session
    // directory.  If present in the restore data, render it inside the
    // validation panel and mark the pool as approved.
    if (data.animal_report) {
        animalReportData = data.animal_report;
        animalReportApproved = true;
        renderAnimalReport(animalReportData);

        // Fetch the lightweight integrated data summary for the previewer.
        // This avoids loading the full 60MB+ integrated.json into the browser.
        try {
            const summaryResp = await fetch(`/api/integrated-summary/${currentIdentity.dtxsid}`);
            if (summaryResp.ok) {
                const summaryData = await summaryResp.json();
                renderIntegratedPreview(summaryData);
            }
        } catch (_) { /* non-critical — previewer just stays hidden */ }
    }

    // --- Derive pool phase from artifact state ---
    // Phase is a function of what exists, not a variable we set.  This
    // single derivation replaces scattered imperative dispatch calls that
    // were fragile on restore (e.g., setting APPROVED without checking
    // whether the pool had been invalidated by new uploads).
    const hasStale = Object.values(data.bm2_sections || {}).some(s => s.stale)
        || Object.values(data.genomics_sections || {}).some(s => s.stale);
    const hasValidationErrors = (data.validation_report?.issues || [])
        .some(i => i.severity === 'error');

    const restoredPhase = derivePoolPhase({
        hasFiles:             Object.keys(uploadedFiles).length > 0,
        hasStale:             hasStale,
        validationReport:     data.validation_report,
        hasValidationErrors:  hasValidationErrors,
        hasIntegrated:        !!data.animal_report,  // animal_report implies integration succeeded
        hasAnimalReport:      !!data.animal_report,
    });
    AppStore.dispatch('pool.transition', restoredPhase);

    // --- Re-run integrated pipeline if pool was approved ---
    // Always re-run autoProcessPool on restore when the pool is approved,
    // even if there are no pending files.  This recreates domain-split
    // apical section cards (body_weight, organ_weights, hormones, etc.)
    // from the integrated data, replacing the old monolithic per-file
    // sections that had wrong headers.  The pipeline is idempotent:
    // sections already in apicalSections are skipped.
    if (animalReportApproved) {
        await autoProcessPool();
    }

    updateExportButton();

    const name = data.meta?.name || data.identity?.name || currentIdentity?.dtxsid;
    showToast(`Restored session for ${name}`);
}

/* ================================================================
 * Chemical ID localStorage persistence — save form contents on
 * every keystroke so they survive page reloads.  The key
 * '5dtox-chem-id' holds a JSON object with field values.
 * ================================================================ */

/** Save current form values to localStorage */
function saveChemId() {
    const data = {};
    CHEM_ID_FIELDS.forEach(id => {
        const el = document.getElementById(id);
        if (el) data[id] = el.value;
    });
    try { localStorage.setItem(CHEM_ID_STORAGE_KEY, JSON.stringify(data)); }
    catch (e) { /* localStorage full or unavailable — ignore */ }
}

/** Restore saved form values from localStorage on page load */
async function restoreChemId() {
    try {
        const raw = localStorage.getItem(CHEM_ID_STORAGE_KEY);
        if (!raw) return;
        const data = JSON.parse(raw);
        CHEM_ID_FIELDS.forEach(id => {
            const el = document.getElementById(id);
            if (el && data[id]) el.value = data[id];
        });

        const dtxsid = data['dtxsid'];
        if (!dtxsid || !dtxsid.startsWith('DTXSID')) return;

        // Fast path: if localStorage already has a complete identity
        // (dtxsid + name), skip the expensive /api/resolve network call
        // (PubChem + CTX APIs).  Instead, reconstruct currentIdentity from
        // the saved form values and go straight to session restore.
        // This cuts ~2-5 seconds from every page refresh.
        if (data['name']) {
            currentIdentity = {
                name: data['name'] || '',
                casrn: data['casrn'] || '',
                dtxsid: data['dtxsid'] || '',
                pubchem_cid: data['cid'] || '',
                ec_number: data['ec'] || '',
                iupac_name: data['iupac'] || '',
            };
            // Mark the DTXSID as "already resolved" so typing in the same
            // value doesn't trigger a redundant server call.
            lastResolvedValue = dtxsid;

            // Visual: mark populated fields as resolved (green border)
            const fields = ['name', 'casrn', 'dtxsid', 'cid', 'ec', 'iupac'];
            fields.forEach(f => {
                const el = document.getElementById(f);
                if (el && el.value) el.classList.add('resolved');
            });

            // Enable buttons that depend on a resolved identity
            onIdentityResolved();

            // Show the data tab immediately — file upload and pool
            // management should not wait for background generation.
            if (typeof Alpine !== 'undefined' && Alpine.store('app')) {
                Alpine.store('app').ready.data = true;
            }

            // Show Reset Session button
            const btnResetSession = document.getElementById('btn-reset-session');
            if (btnResetSession) btnResetSession.style.display = '';

            // Go straight to session restore — no /api/resolve needed
            const sessionResp = await fetch(`/api/session/${dtxsid}`);
            const sessionData = await sessionResp.json();
            if (sessionData.exists) {
                await restoreSession(sessionData);
            }
            return;
        }

        // Slow path: localStorage has a DTXSID but no name — need full
        // resolve to populate all fields.
        await onFieldBlur('dtxsid');
    } catch (e) {
        console.error('restoreChemId failed:', e);
    }
}

// Attach input listeners to persist every keystroke and selection change
CHEM_ID_FIELDS.forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    const event = el.tagName === 'SELECT' ? 'change' : 'input';
    el.addEventListener(event, saveChemId);
});

// Restore saved values on page load
loadSettings();
restoreChemId();

// Initialize the sidebar TOC scroll spy after Alpine has had a chance
// to initialize.  The scroll spy observes [data-toc-id] elements and
// highlights the corresponding sidebar node when a section scrolls
// into view.  We defer this slightly to ensure Alpine has processed
// the x-show directives first.
requestAnimationFrame(() => {
    initScrollSpy();
});

// Load the style profile on page init so existing rules are
// visible immediately (e.g., after a page refresh)
loadStyleProfile();

// Close version history dropdowns when clicking outside them.
// Without this, the dropdown stays open forever unless the user
// clicks the same "v3 ▾" button again.
document.addEventListener('click', (e) => {
    if (!e.target.closest('.version-history')) {
        document.querySelectorAll('.version-dropdown').forEach(d => d.style.display = 'none');
    }
});
