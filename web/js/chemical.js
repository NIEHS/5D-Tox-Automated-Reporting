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
    // For each saved bm2 section: create a synthetic uploadedFiles entry
    // (type='bm2', restored: true), render a greyed file pool item,
    // create an apicalSections entry, and create the result card.
    if (data.bm2_sections && Object.keys(data.bm2_sections).length > 0) {
        // Show the file pool, animal report, and results section
        show('data-tab-section');


        show('bm2-results-section');

        for (const [slug, section] of Object.entries(data.bm2_sections)) {
            // Create the section card ID
            const sectionId = 'restored-' + slug;

            // Use the server-assigned file_id if the .bm2 file was
            // found on disk (re-registered in _bm2_uploads by the
            // session load endpoint).  This makes the file fully
            // functional — preview, reprocess, export all work.
            // Falls back to a synthetic ID if the file is missing.
            const fileId = section.server_file_id || ('file-restored-bm2-' + slug);
            const isServerBacked = !!section.server_file_id;

            // Create the uploadedFiles entry.  If server-backed, the
            // file is NOT marked as "restored" since it has a real
            // server-side upload entry and can be previewed/processed
            // normally.  The remove button is still hidden (restored
            // appearance) since the user didn't upload it this session.
            uploadedFiles[fileId] = {
                id: fileId,
                filename: section.filename || slug,
                type: 'bm2',
                restored: !isServerBacked,
                fromSession: true,
            };
            renderFilePoolItem(fileId);

            // Register in apicalSections state
            apicalSections[sectionId] = {
                fileId: fileId,
                filename: section.filename || slug,
                processed: true,
                approved: true,
                tableData: section.tables_json || {},
                narrative: section.narrative
                    ? section.narrative.split(/\n\s*\n/)
                    : [],
            };

            // Create the card UI
            createBm2Card(sectionId, section.filename || slug);

            // Fill in config fields from saved data
            const titleEl = document.getElementById(`bm2-title-${sectionId}`);
            if (titleEl && section.section_title) titleEl.value = section.section_title;
            const captionEl = document.getElementById(`bm2-caption-${sectionId}`);
            if (captionEl && section.table_caption) captionEl.value = section.table_caption;
            const compoundEl = document.getElementById(`bm2-compound-${sectionId}`);
            if (compoundEl && section.compound_name) compoundEl.value = section.compound_name;
            const unitEl = document.getElementById(`bm2-unit-${sectionId}`);
            if (unitEl && section.dose_unit) unitEl.value = section.dose_unit;

            // Fill in narrative textarea
            const narrativeEl = document.getElementById(`bm2-narrative-${sectionId}`);
            if (narrativeEl && section.narrative) {
                narrativeEl.value = section.narrative;
                autoResizeTextarea(narrativeEl);
            }

            // Render table preview if we have table data
            if (section.tables_json && Object.keys(section.tables_json).length > 0) {
                const doseUnit = section.dose_unit || 'mg/kg';
                renderTablePreview(sectionId, section.tables_json, doseUnit);
            }

            // Lock the card as approved (disable editing, add green border)
            const card = document.getElementById(`bm2-card-${sectionId}`);
            lockSection(card);

            // Hide Process button, show approved state (Edit + Try Again + badge)
            hide(`btn-process-${sectionId}`);
            setButtons(sectionId, 'approved');

            // Show version history with the version from the saved data
            showVersionHistory('bm2', section.version || 1, sectionId);
        }
    }

    // --- Restore pending (unapproved) files from session directory ---
    // The server scans sessions/{dtxsid}/files/ for .bm2 files that
    // don't yet have an approved section and returns them as
    // pending_files.  We add them to the file pool so the user can
    // assign them to sections without re-uploading.
    if (data.pending_files && data.pending_files.length > 0) {
        // Make sure the file pool and animal report are visible
        // so the user can assign pending files to report sections.
        show('data-tab-section');



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
            show('bmd-summary-section');
            document.getElementById('bmd-summary-section').classList.add('visible');
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
        show('data-tab-section');


        show('genomics-results-section');
        show('genomics-charts-section');

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
                setButtons(`genomics-${key}`, 'approved');
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
        setButtons('pool', 'approved');

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

    // --- Auto-process pending files if pool was approved ---
    // Always re-run autoProcessPool on restore when the pool is approved.
    // It's idempotent: approved apical sections are skipped, approved
    // genomics sections are skipped (via the ?.approved guard), and
    // createGenomicsCard / createBm2Card de-duplicate by removing existing
    // cards before creating new ones.  This ensures any sections that were
    // missing from the session (e.g. liver_male genomics added after the
    // session was last saved) get created on restore.
    if (animalReportApproved && data.pending_files?.length > 0) {
        await autoProcessPool();
    }

    updateExportButton();

    // Rebuild the tab bar so any newly-revealed sections get tabs
    if (tabbedViewActive) buildTabBar();

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

// Apply the default tabbed layout on page load.
// tabbedViewActive is true by default in state.js, so we need to
// set up the DOM to match: add the .tabbed-view class, mark the
// toggle button as active, expand all sections, and build the tab bar.
{
    const container = document.querySelector('.container');
    container.classList.add('tabbed-view');
    const btn = document.getElementById('btn-tabbed-view');
    btn.classList.add('active');
    btn.textContent = 'Stacked View';
    document.querySelectorAll('[data-collapsible]').forEach(
        s => s.classList.remove('collapsed')
    );
    buildTabBar();
}

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
