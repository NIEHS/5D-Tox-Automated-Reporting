/* -----------------------------------------------------------------
 * filepool.js — File upload, pool management, validation, and metadata
 *
 * Handles drag-and-drop file uploads (.bm2, .csv, .txt, .xlsx, .zip),
 * the file pool list UI, pool validation and integration, BM2 card
 * creation and processing, conflict resolution, animal report rendering,
 * and experiment metadata review/approval.
 *
 * Depends on: state.js (globals), utils.js (helpers), export.js,
 *             genomics.js
 * ----------------------------------------------------------------- */

const unifiedDropZone = document.getElementById('unified-drop-zone');
const unifiedFileInput = document.getElementById('unified-file-input');

// Drag-and-drop event handlers — highlight the zone on dragover,
// then upload files on drop
unifiedDropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    unifiedDropZone.classList.add('dragover');
});

unifiedDropZone.addEventListener('dragleave', () => {
    unifiedDropZone.classList.remove('dragover');
});

unifiedDropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    unifiedDropZone.classList.remove('dragover');
    // Accept .bm2, .csv, .txt, .xlsx, and .zip files
    const validExts = ['.bm2', '.csv', '.txt', '.xlsx', '.zip'];
    const files = Array.from(e.dataTransfer.files).filter(
        f => validExts.some(ext => f.name.toLowerCase().endsWith(ext))
    );
    if (files.length > 0) uploadFiles(files);
});

// Standard file input change handler (triggered by clicking the zone)
unifiedFileInput.addEventListener('change', () => {
    const files = Array.from(unifiedFileInput.files);
    if (files.length > 0) uploadFiles(files);
    unifiedFileInput.value = '';  // reset so the same file can be re-uploaded
});

/**
 * Upload files (both .bm2 and .csv) to the server.
 *
 * Partitions the file list by extension, calls the appropriate
 * upload endpoint for each group (/api/upload-bm2 for .bm2,
 * /api/upload-csv for .csv), populates the unified uploadedFiles
 * pool, and renders compact file pool items in the UI.
 *
 * @param {File[]} fileList — array of File objects from drag-drop or input
 */
async function uploadFiles(fileList) {
    showBlockingSpinner('Uploading files...');
    try {
    // Partition files by extension — zip files are handled separately
    // because the server extracts them and returns individual file entries.
    // CSV, TXT, and XLSX are format-equivalent dose-response data (comma,
    // tab, or spreadsheet) and all go through the same /api/upload-csv
    // endpoint into the generic data pool for fingerprinting.
    const bm2List = [];
    const dataList = [];  // csv, txt, xlsx — all generic data pool files
    const zipList = [];
    for (const f of fileList) {
        const name = f.name.toLowerCase();
        if (name.endsWith('.bm2')) bm2List.push(f);
        else if (name.endsWith('.csv') || name.endsWith('.txt')) dataList.push(f);
        // .xlsx support exists in the server (same _data_uploads path)
        // but is disabled on the frontend for now.  Re-enable by adding:
        //   || name.endsWith('.xlsx')
        // to the dataList condition above.
        else if (name.endsWith('.zip')) zipList.push(f);
    }

    let totalUploaded = 0;

    // Upload .bm2 files if any
    if (bm2List.length > 0) {
        const formData = new FormData();
        for (const file of bm2List) formData.append('files', file);

        try {
            // Pass the DTXSID so the server can persist the file
            // to sessions/{dtxsid}/files/ immediately (survives reload)
            const dtxsid = currentIdentity?.dtxsid || '';
            const uploadUrl = dtxsid
                ? `/api/upload-bm2?dtxsid=${encodeURIComponent(dtxsid)}`
                : '/api/upload-bm2';
            const resp = await fetch(uploadUrl, {
                method: 'POST',
                body: formData,
            });
            if (!resp.ok) {
                const err = await resp.json();
                showError(err.error || 'BM2 upload failed');
            } else {
                const results = await resp.json();
                for (const item of results) {
                    uploadedFiles[item.id] = {
                        id: item.id,
                        filename: item.filename,
                        type: 'bm2',
                    };
                    renderFilePoolItem(item.id);
                    totalUploaded++;
                }
            }
        } catch (err) {
            showError('BM2 upload error: ' + err.message);
        }
    }

    // Upload data files (csv, txt, xlsx) if any — treated as generic
    // data pool entries (same as files extracted from zip archives).
    // The pool integrator fingerprints them to determine whether
    // they're apical or genomic.
    if (dataList.length > 0) {
        const formData = new FormData();
        for (const file of dataList) formData.append('files', file);

        try {
            // Pass DTXSID so the server can persist the file to
            // sessions/{dtxsid}/files/ and fingerprint immediately.
            const dtxsid = currentIdentity?.dtxsid || '';
            const uploadUrl = dtxsid
                ? `/api/upload-csv?dtxsid=${encodeURIComponent(dtxsid)}`
                : '/api/upload-csv';
            const resp = await fetch(uploadUrl, {
                method: 'POST',
                body: formData,
            });
            if (!resp.ok) {
                const err = await resp.json();
                showError(err.error || 'CSV upload failed');
            } else {
                const results = await resp.json();
                for (const item of results) {
                    uploadedFiles[item.id] = {
                        id: item.id,
                        filename: item.filename,
                        type: item.type || 'csv',
                    };
                    renderFilePoolItem(item.id);
                    totalUploaded++;
                }
            }
        } catch (err) {
            showError('CSV upload error: ' + err.message);
        }
    }

    // Upload .zip files — server extracts and returns individual entries
    for (const zipFile of zipList) {
        const formData = new FormData();
        formData.append('file', zipFile);

        try {
            // Pass DTXSID so .bm2 files inside the zip are persisted
            const zipDtxsid = currentIdentity?.dtxsid || '';
            const zipUploadUrl = zipDtxsid
                ? `/api/upload-zip?dtxsid=${encodeURIComponent(zipDtxsid)}`
                : '/api/upload-zip';
            const resp = await fetch(zipUploadUrl, {
                method: 'POST',
                body: formData,
            });
            if (!resp.ok) {
                const err = await resp.json();
                showError(err.error || 'ZIP upload failed');
                continue;
            }
            const result = await resp.json();

            // Register extracted .bm2 files (BMDExpress output)
            for (const item of (result.bm2_files || [])) {
                uploadedFiles[item.id] = {
                    id: item.id,
                    filename: item.filename,
                    type: 'bm2',
                };
                renderFilePoolItem(item.id);
                totalUploaded++;
            }

            // Register extracted raw data files (.csv, .txt, .xlsx)
            // These are dose-response experimental data — animal IDs
            // across columns, concentrations in row 2, endpoints in
            // subsequent rows.  Suitable for import into BMDExpress.
            for (const item of (result.other_files || [])) {
                uploadedFiles[item.id] = {
                    id: item.id,
                    filename: item.filename,
                    type: item.type,  // "csv", "txt", or "xlsx"
                };
                renderFilePoolItem(item.id);
                totalUploaded++;
            }

            // Report any skipped files
            if (result.skipped && result.skipped.length > 0) {
                showToast(`Skipped ${result.skipped.length} unsupported file(s) from zip`);
            }
        } catch (err) {
            showError('ZIP upload error: ' + err.message);
        }
    }

    if (totalUploaded > 0) {
        showToast(`Uploaded ${totalUploaded} file(s)`);
        updateClearFilesButton();
        // Show the validation panel so user knows validation is available
        showValidationPanel();
    }
    } finally { hideBlockingSpinner(); }
}

/**
 * Render a compact file pool item in the #file-pool-list container.
 *
 * Each item shows: a type badge (.bm2 / .csv), the filename, optional
 * info (row count for CSVs), and a remove button (hidden for restored files).
 *
 * @param {string} fileId — the ID of the file in uploadedFiles
 */
function renderFilePoolItem(fileId) {
    const file = uploadedFiles[fileId];
    if (!file) return;

    const listEl = document.getElementById('file-pool-list');

    const item = document.createElement('div');
    // Greyed-out for files loaded from a saved session that already
    // have an approved section (they're shown for context, not action).
    // Pending (unapproved) session files look normal so the user knows
    // they still need processing.
    item.className = 'file-pool-item' + ((file.restored || file.fromSession) ? ' restored' : '');
    item.id = `file-pool-${fileId}`;

    // Type badge — color-coded by file type
    const badge = document.createElement('span');
    badge.className = `file-badge ${file.type}`;
    const badgeLabels = { bm2: '.bm2', csv: '.csv', txt: '.txt', xlsx: '.xlsx' };
    badge.textContent = badgeLabels[file.type] || `.${file.type}`;

    // Filename — clickable to open the file preview modal.
    // The 'clickable' CSS class adds cursor:pointer and underline-on-hover.
    const nameSpan = document.createElement('span');
    nameSpan.className = 'file-name clickable';
    nameSpan.textContent = file.filename;
    nameSpan.onclick = (e) => {
        e.stopPropagation();
        openPreviewModal(fileId);
    };

    // Info — row count for CSVs
    const infoSpan = document.createElement('span');
    infoSpan.className = 'file-info';
    if (file.type === 'csv' && file.row_count) {
        infoSpan.textContent = `${file.row_count} genes`;
    }

    // Remove button — hidden for restored files (can't re-upload them)
    const removeBtn = document.createElement('button');
    removeBtn.className = 'btn-remove-file';
    removeBtn.textContent = '\u00d7';
    removeBtn.title = 'Remove file';
    removeBtn.onclick = () => removeFile(fileId);
    if (file.restored || file.fromSession || file.sessionPersisted) removeBtn.style.display = 'none';

    item.appendChild(badge);
    item.appendChild(nameSpan);
    item.appendChild(infoSpan);
    item.appendChild(removeBtn);
    listEl.appendChild(item);

    // Keep the collapsible summary line in sync with current file counts
    updateFilePoolSummary();
}

/**
 * Update the file pool collapsible header with a brief count summary.
 *
 * Counts files by type (xlsx, txt, csv, bm2) from the uploadedFiles map
 * and renders something like "28 files — 7 xlsx, 14 txt, 7 bm2".
 * Called after every add/remove so the summary stays current.
 */
function updateFilePoolSummary() {
    const el = document.getElementById('file-pool-summary');
    if (!el) return;

    const counts = {};
    let total = 0;
    for (const fid of Object.keys(uploadedFiles)) {
        const f = uploadedFiles[fid];
        if (!f) continue;
        const t = f.type || 'unknown';
        counts[t] = (counts[t] || 0) + 1;
        total++;
    }

    // Show/hide the "Reset Pool" button — visible whenever there are files
    // in the pool (regardless of whether they're from a fresh upload or
    // a restored session).  This is the only way to clear restored files.
    const resetBtn = document.getElementById('btn-reset-pool');
    if (resetBtn) resetBtn.style.display = total > 0 ? '' : 'none';

    if (total === 0) {
        el.textContent = 'Uploaded files';
        return;
    }

    // Build "7 xlsx, 14 txt, 7 bm2" with a consistent order
    const order = ['xlsx', 'txt', 'csv', 'bm2'];
    const parts = [];
    for (const t of order) {
        if (counts[t]) parts.push(`${counts[t]} ${t}`);
    }
    // Any types not in the predefined order
    for (const t of Object.keys(counts)) {
        if (!order.includes(t)) parts.push(`${counts[t]} ${t}`);
    }

    el.textContent = `${total} file${total !== 1 ? 's' : ''} — ${parts.join(', ')}`;
}

/**
 * Remove a file from the upload pool and from the DOM.
 * Also removes it from the file pool list.
 *
 * @param {string} fileId — the ID of the file to remove
 */
function removeFile(fileId) {
    delete uploadedFiles[fileId];
    const el = document.getElementById(`file-pool-${fileId}`);
    if (el) el.remove();
    updateClearFilesButton();
    updateFilePoolSummary();
}

/**
 * Remove all non-restored files from the upload pool.
 * Restored files (from a prior session) are kept because they
 * can't be re-uploaded — removing them would orphan their sections.
 */
function clearAllFiles() {
    const removable = Object.keys(uploadedFiles).filter(
        id => !uploadedFiles[id].restored && !uploadedFiles[id].fromSession && !uploadedFiles[id].sessionPersisted
    );
    for (const fileId of removable) {
        delete uploadedFiles[fileId];
        const el = document.getElementById(`file-pool-${fileId}`);
        if (el) el.remove();
    }
    updateClearFilesButton();
    updateFilePoolSummary();
}

/**
 * Show the "Clear Files" button only when there is at least one
 * removable (non-restored) file in the pool.
 */
function updateClearFilesButton() {
    const btn = document.getElementById('btn-clear-files');
    if (!btn) return;
    const hasRemovable = Object.values(uploadedFiles).some(f => !f.restored && !f.fromSession && !f.sessionPersisted);
    btn.style.display = hasRemovable ? '' : 'none';
}


/**
 * Confirm and execute a full pool reset — removes ALL files, integrated data,
 * metadata, and approved sections for the current chemical.  This is
 * irreversible: the user gets a browser confirm() dialog spelling out
 * exactly what will be lost before the reset proceeds.
 *
 * After the server wipes the session data, the client clears all in-memory
 * state (uploadedFiles, apicalSections, genomicsResults) and hides the
 * result sections so the UI returns to a fresh "upload files" state.
 */
async function confirmResetPool() {
    const dtxsid = document.getElementById('dtxsid')?.value;
    if (!dtxsid) {
        showToast('No chemical resolved — nothing to reset.');
        return;
    }

    // Explicit, detailed warning so the user knows exactly what they're losing
    const ok = confirm(
        'RESET POOL — This will permanently delete:\n\n' +
        '  • All uploaded files (.bm2, .csv, .txt, .xlsx)\n' +
        '  • Integrated data and .bm2 export\n' +
        '  • Experiment metadata and approval status\n' +
        '  • All approved apical endpoint sections\n' +
        '  • All approved genomics sections\n' +
        '  • Methods, BMD Summary, and Summary sections\n' +
        '  • Validation report and conflict resolutions\n\n' +
        'Chemical identity and version history are preserved.\n\n' +
        'This cannot be undone. Continue?'
    );
    if (!ok) return;

    try {
        const resp = await fetch(`/api/pool/reset/${dtxsid}`, { method: 'POST' });
        const data = await resp.json();
        if (!resp.ok) {
            showToast(data.error || 'Reset failed');
            return;
        }

        // --- Clear all client-side state ---

        // File pool — clear both the state dict and the DOM list
        for (const id of Object.keys(uploadedFiles)) {
            delete uploadedFiles[id];
        }
        const fileList = document.getElementById('file-pool-list');
        if (fileList) fileList.innerHTML = '';

        // Apical sections
        for (const id of Object.keys(apicalSections)) {
            delete apicalSections[id];
        }
        apicalSectionCounter = 0;

        // Genomics results
        for (const key of Object.keys(genomicsResults)) {
            delete genomicsResults[key];
        }

        // BMD summary
        bmdSummaryEndpoints = [];

        // Summary paragraphs (methods paragraphs are embedded in the section DOM)
        summaryParagraphs = null;

        // Validation state
        lastValidationReport = null;

        // --- Hide/reset UI sections ---

        // Hide the validation panel and clear its inner content
        // (coverage matrix, validation issues, animal report table)
        const validationPanel = document.getElementById('validation-panel');
        if (validationPanel) validationPanel.style.display = 'none';
        for (const innerId of ['coverage-matrix', 'validation-issues', 'animal-report-content', 'file-metadata-table', 'validation-body']) {
            const el = document.getElementById(innerId);
            if (el && innerId !== 'validation-body') el.innerHTML = '';
            if (el && innerId === 'validation-body') el.style.display = 'none';
        }
        // Hide file metadata review panel
        const fileMetaPanel = document.getElementById('file-metadata-review');
        if (fileMetaPanel) fileMetaPanel.style.display = 'none';

        // Hide integrated preview and clear its content
        const intPreview = document.getElementById('integrated-preview');
        if (intPreview) intPreview.style.display = 'none';
        const intPreviewContent = document.getElementById('integrated-preview-content');
        if (intPreviewContent) intPreviewContent.innerHTML = '';
        integratedPoolData = null;

        // Clear apical domain sub-tabs and panels
        const subTabBar = document.getElementById('apical-sub-tabs');
        if (subTabBar) { subTabBar.innerHTML = ''; subTabBar.classList.remove('visible'); }
        const bm2Cards = document.getElementById('bm2-cards');
        if (bm2Cards) bm2Cards.innerHTML = '';

        // Clear genomics organ×sex sub-tabs and panels
        const genomicsSubTabs = document.getElementById('genomics-sub-tabs');
        if (genomicsSubTabs) { genomicsSubTabs.innerHTML = ''; genomicsSubTabs.classList.remove('visible'); }
        const genomicsCards = document.getElementById('genomics-cards');
        if (genomicsCards) genomicsCards.innerHTML = '';

        // Clear charts sub-tabs and chart containers
        const chartsSubTabs = document.getElementById('charts-sub-tabs');
        if (chartsSubTabs) { chartsSubTabs.innerHTML = ''; chartsSubTabs.classList.remove('visible'); delete chartsSubTabs.dataset.keys; }
        const umapChart = document.getElementById('umap-chart');
        if (umapChart) umapChart.innerHTML = '';
        const clusterChart = document.getElementById('cluster-chart');
        if (clusterChart) clusterChart.innerHTML = '';

        // Hide apical results section and clear its content
        const apicalSection = document.getElementById('apical-results');
        if (apicalSection) apicalSection.style.display = 'none';
        const apicalContent = document.getElementById('apical-content');
        if (apicalContent) apicalContent.innerHTML = '';

        // Hide genomics results section and clear its content
        const genomicsSection = document.getElementById('genomics-results');
        if (genomicsSection) genomicsSection.style.display = 'none';
        const genomicsContent = document.getElementById('genomics-content');
        if (genomicsContent) genomicsContent.innerHTML = '';

        // Hide metadata review section
        const metadataSection = document.getElementById('metadata-review-section');
        if (metadataSection) metadataSection.style.display = 'none';

        // Hide methods, BMD summary, and summary sections
        for (const secId of ['methods-section', 'bmd-summary-section', 'summary-section']) {
            const sec = document.getElementById(secId);
            if (sec) sec.style.display = 'none';
        }

        // Reset file pool summary and buttons
        updateFilePoolSummary();
        updateClearFilesButton();

        const deleted = data.deleted || [];
        showToast(`Pool reset: ${deleted.length} items removed. Ready for fresh uploads.`);
        console.info('Pool reset complete:', deleted);

    } catch (err) {
        showToast('Reset failed: ' + err.message);
    }
}


/**
 * Confirm and execute a full session reset — deletes EVERYTHING for the
 * current chemical: background, identity, all approved sections, files,
 * integrated data, version history.  The chemical identity form stays
 * filled (from localStorage) but the server has no record of any work.
 *
 * This is the nuclear option.  Pool Reset preserves background and identity;
 * Session Reset does not.
 */
async function confirmResetSession() {
    const dtxsid = document.getElementById('dtxsid')?.value;
    if (!dtxsid) {
        showToast('No chemical resolved — nothing to reset.');
        return;
    }

    const name = document.getElementById('name')?.value || dtxsid;
    const ok = confirm(
        `RESET SESSION for ${name}\n\n` +
        'This will permanently delete ALL session data:\n\n' +
        '  • Background section and references\n' +
        '  • All uploaded files and integrated data\n' +
        '  • All approved sections (apical, genomics, methods, summary)\n' +
        '  • BMD summary and experiment metadata\n' +
        '  • Version history\n' +
        '  • Chemical identity (server-side)\n\n' +
        'The chemical identity form will stay filled (from your browser),\n' +
        'but the server will have no record of any prior work.\n\n' +
        'This CANNOT be undone. Continue?'
    );
    if (!ok) return;

    try {
        const resp = await fetch(`/api/session/reset/${dtxsid}`, { method: 'POST' });
        const data = await resp.json();
        if (!resp.ok) {
            showToast(data.error || 'Session reset failed');
            return;
        }

        // Clear everything that Pool Reset clears
        for (const id of Object.keys(uploadedFiles)) delete uploadedFiles[id];
        const fileList = document.getElementById('file-pool-list');
        if (fileList) fileList.innerHTML = '';
        for (const id of Object.keys(apicalSections)) delete apicalSections[id];
        apicalSectionCounter = 0;
        for (const key of Object.keys(genomicsResults)) delete genomicsResults[key];
        bmdSummaryEndpoints = [];
        summaryParagraphs = null;
        lastValidationReport = null;

        // Hide pool-related UI
        const validationPanel = document.getElementById('validation-panel');
        if (validationPanel) validationPanel.style.display = 'none';
        for (const innerId of ['coverage-matrix', 'validation-issues', 'animal-report-content']) {
            const el = document.getElementById(innerId);
            if (el) el.innerHTML = '';
        }
        const vBody = document.getElementById('validation-body');
        if (vBody) vBody.style.display = 'none';

        // Hide all result sections
        for (const secId of [
            'apical-results', 'genomics-results', 'metadata-review-section',
            'methods-section', 'bmd-summary-section', 'summary-section'
        ]) {
            const sec = document.getElementById(secId);
            if (sec) sec.style.display = 'none';
        }
        const apicalContent = document.getElementById('apical-content');
        if (apicalContent) apicalContent.innerHTML = '';
        const genomicsContent = document.getElementById('genomics-content');
        if (genomicsContent) genomicsContent.innerHTML = '';

        // Also clear background section — this is what distinguishes
        // Session Reset from Pool Reset
        const outputSection = document.getElementById('output-section');
        if (outputSection) outputSection.style.display = 'none';
        const bgContent = document.getElementById('output-prose');
        if (bgContent) bgContent.innerHTML = '';
        const refContent = document.getElementById('references-list');
        if (refContent) refContent.innerHTML = '';
        const metaInfo = document.getElementById('meta-info');
        if (metaInfo) metaInfo.innerHTML = '';
        // Re-enable the Generate Background button
        const btnGenerate = document.getElementById('btn-generate');
        if (btnGenerate) btnGenerate.disabled = false;
        // Hide approve/edit buttons
        for (const btnId of ['btn-edit-bg', 'btn-approve-bg', 'btn-retry-bg']) {
            const btn = document.getElementById(btnId);
            if (btn) btn.style.display = 'none';
        }

        updateFilePoolSummary();
        updateClearFilesButton();

        showToast('Session reset. All data for ' + name + ' has been deleted.');
        console.info('Session reset complete for', dtxsid);

    } catch (err) {
        showToast('Session reset failed: ' + err.message);
    }
}


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

    const btnValidate = document.getElementById('btn-validate');
    const btnIntegrate = document.getElementById('btn-integrate');
    if (btnValidate) {
        btnValidate.disabled = true;
        btnValidate.textContent = 'Validating...';
    }
    // Hide/disable Integrate until we know the result
    if (btnIntegrate) {
        btnIntegrate.disabled = true;
        btnIntegrate.style.display = 'none';
    }

    showBlockingSpinner('Validating file pool...');
    try {
        const resp = await fetch(`/api/pool/validate/${dtxsid}`, { method: 'POST' });
        if (!resp.ok) {
            const err = await resp.json();
            showToast(err.error || 'Validation failed');
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

        // Count errors — show file metadata review if no errors
        const errorCount = (report.issues || []).filter(
            i => i.severity === 'error'
        ).length;

        if (errorCount === 0) {
            // Show file metadata confirmation table — user must confirm
            // before integration is allowed.
            renderFileMetadataReview(report.fingerprints || {});
            showToast('Validation passed — confirm file metadata to integrate');
        } else {
            // Hide metadata review and disable integrate
            const metaPanel = document.getElementById('file-metadata-review');
            if (metaPanel) metaPanel.style.display = 'none';
            showToast(`${errorCount} error(s) found — fix the file pool and re-validate`);
        }

        // Integrate button starts hidden — shown only after metadata confirmed
        if (btnIntegrate) {
            btnIntegrate.style.display = 'none';
            btnIntegrate.disabled = true;
        }
    } catch (e) {
        showToast('Validation request failed: ' + e.message);
    } finally {
        hideBlockingSpinner();
        if (btnValidate) {
            btnValidate.disabled = false;
            btnValidate.textContent = 'Validate';
        }
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

    const btn = document.getElementById('btn-integrate');
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Integrating...';
    }

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
            showToast('Integration complete');

            // Show the Approve button so the user can sign off on the
            // pool and trigger animal report generation.
            show('btn-approve-pool');
        } else {
            const intErr = await intResp.json().catch(() => ({}));
            showToast(intErr.error || 'Integration failed');
        }
    } catch (e) {
        showToast('Integration failed: ' + e.message);
    } finally {
        hideBlockingSpinner();
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Integrate';
        }
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

    // Show Integrate button if validation had zero errors
    const errorCount = (report.issues || []).filter(
        i => i.severity === 'error'
    ).length;
    const btnIntegrate = document.getElementById('btn-integrate');
    if (btnIntegrate) {
        btnIntegrate.style.display = '';
        btnIntegrate.disabled = errorCount > 0;
    }
}


/**
 * Map from platform strings to human-readable section titles and
 * NIEHS-style table caption templates.  These match the platform
 * vocabulary in file_integrator.py and the caption conventions in the
 * NTP reference report (Bookshelf_NBK589955.pdf).
 *
 * {sex} and {compound} are replaced at export time with the actual
 * sex group label and compound name.
 *
 * Platform strings are already human-readable — keys match the
 * title directly.  data_type (tox_study vs inferred) is tracked
 * separately and doesn't affect the section title or caption.
 */
const _PLATFORM_DEFAULTS = {
    'Body Weight':           { title: 'Body Weight',
                               caption: 'Summary of Body Weights of {sex} Rats Administered {compound} for Five Days' },
    'Organ Weights':         { title: 'Organ Weights',
                               caption: 'Summary of Organ Weights of {sex} Rats Administered {compound} for Five Days' },
    'Clinical Chemistry':    { title: 'Clinical Chemistry',
                               caption: 'Summary of Select Clinical Chemistry Data for {sex} Rats Administered {compound} for Five Days' },
    'Hematology':            { title: 'Hematology',
                               caption: 'Summary of Select Hematology Data for {sex} Rats Administered {compound} for Five Days' },
    'Hormones':              { title: 'Hormones',
                               caption: 'Summary of Select Hormone Data for {sex} Rats Administered {compound} for Five Days' },
    'Tissue Concentration':  { title: 'Tissue Concentration',
                               caption: 'Summary of Plasma Concentration Data for {sex} Rats Administered {compound} for Five Days' },
    'Clinical': { title: 'Clinical Observations',
                  caption: 'Summary of Clinical Observations for {sex} Rats Administered {compound} for Five Days' },
    // "Clinical Observations" is the platform key used by the incidence
    // table section (from _build_clinical_obs_section in pool_orchestrator).
    'Clinical Observations': { title: 'Clinical Observations',
                  caption: 'Summary of Clinical Observations for {sex} Rats Administered {compound} for Five Days' },
};

/**
 * Canonical ordering of apical platform sub-tabs.
 * Uses platform strings directly — no suffix stripping needed.
 */
const _PLATFORM_SUB_TAB_ORDER = [
    'Body Weight', 'Organ Weights', 'Clinical Chemistry',
    'Hematology', 'Hormones', 'Tissue Concentration',
];

/**
 * Pass-through for backward compatibility.  Platform strings no longer
 * have suffixes, so this just returns the input unchanged.
 *
 * @param {string} platform — platform key (e.g. "Hormones")
 * @returns {string} — same platform key
 */
function _baseDomain(platform) {
    return platform || '';
}

/**
 * Ensure a platform sub-tab and its card container exist.
 * Called by createBm2Card() the first time a card for a platform is added.
 * Creates the sub-tab button and the panel div inside #bm2-cards.
 *
 * The sub-tab bar becomes visible once at least one platform has cards.
 * Sub-tabs are inserted in _PLATFORM_SUB_TAB_ORDER so the order is
 * stable regardless of which platform gets cards first.
 *
 * @param {string} platform — platform key (e.g. "Body Weight")
 * @returns {HTMLElement} — the panel div to append cards into
 */
function ensureDomainSubTab(platform) {
    const panelId = `apical-domain-${platform}`;
    let panel = document.getElementById(panelId);
    if (panel) return panel;

    const tabBar = document.getElementById('apical-sub-tabs');
    const container = document.getElementById('bm2-cards');

    // Create the panel — a container for this platform's cards
    panel = document.createElement('div');
    panel.id = panelId;
    panel.className = 'apical-domain-panel';
    panel.setAttribute('data-domain', platform);

    // Insert panel in canonical order among existing panels
    const myIdx = _PLATFORM_SUB_TAB_ORDER.indexOf(platform);
    let inserted = false;
    for (const existing of container.children) {
        const existDomain = existing.getAttribute('data-domain');
        const existIdx = _PLATFORM_SUB_TAB_ORDER.indexOf(existDomain);
        if (existIdx > myIdx) {
            container.insertBefore(panel, existing);
            inserted = true;
            break;
        }
    }
    if (!inserted) container.appendChild(panel);

    // Create the sub-tab button — inserted in canonical order.
    // Platform strings are already human-readable, so use directly.
    const btn = document.createElement('button');
    btn.textContent = platform;
    btn.setAttribute('data-domain', platform);
    btn.onclick = () => activateDomainSubTab(platform);

    const btnIdx = _PLATFORM_SUB_TAB_ORDER.indexOf(platform);
    let btnInserted = false;
    for (const existBtn of tabBar.children) {
        const existBtnDomain = existBtn.getAttribute('data-domain');
        const existBtnIdx = _PLATFORM_SUB_TAB_ORDER.indexOf(existBtnDomain);
        if (existBtnIdx > btnIdx) {
            tabBar.insertBefore(btn, existBtn);
            btnInserted = true;
            break;
        }
    }
    if (!btnInserted) tabBar.appendChild(btn);

    // Show the sub-tab bar now that we have at least one platform
    tabBar.classList.add('visible');

    // If this is the first platform, activate it
    if (tabBar.children.length === 1) {
        activateDomainSubTab(platform);
    }

    return panel;
}

/**
 * Switch the active platform sub-tab — show that platform's panel,
 * hide all others, and update button active states.
 *
 * @param {string} platform — platform key to activate
 */
function activateDomainSubTab(platform) {
    // Toggle panels
    document.querySelectorAll('.apical-domain-panel').forEach(p => {
        p.classList.toggle('active', p.getAttribute('data-domain') === platform);
    });

    // Toggle button states
    const tabBar = document.getElementById('apical-sub-tabs');
    tabBar.querySelectorAll('button').forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('data-domain') === platform);
    });
}

/**
 * Resolve the default section title and caption for a .bm2 card.
 *
 * Priority order:
 * 1. Platform-specific defaults from _PLATFORM_DEFAULTS (best — uses the
 *    server's platform classification to pick the right NIEHS-style title).
 * 2. The server-provided section title (used as-is if no platform match,
 *    with a generic caption built from it).
 * 3. Filename-based heuristic fallback (legacy: "clinical"/"pathology"
 *    in the filename → Clinical Pathology, otherwise generic).
 *
 * Why not just use the server title directly: the server title is
 * short ("Hormones") but the form field needs the full NIEHS-style
 * section heading, and the caption needs the full template with
 * {sex}/{compound} placeholders.
 */
function _resolveBm2Defaults(filename, platform) {
    // 1. Platform-specific lookup — best source of truth.
    if (platform && _PLATFORM_DEFAULTS[platform]) {
        const d = _PLATFORM_DEFAULTS[platform];
        return { title: d.title, caption: d.caption };
    }

    // 2. Filename-based heuristic (for manually uploaded .bm2 files
    //    that weren't routed through process-integrated and lack a platform).
    const lowerName = (filename || '').toLowerCase();
    const isClinical = lowerName.includes('clinical') || lowerName.includes('pathology');
    if (isClinical) {
        return {
            title: 'Clinical Pathology',
            caption: 'Summary of Clinical Pathology Findings of {sex} Rats Administered {compound} for Five Days',
        };
    }

    // 3. Generic fallback — use the filename/title as-is with a
    //    generic caption template.
    return {
        title: filename || 'Apical Endpoints',
        caption: 'Summary of {sex} Rats Administered {compound} for Five Days',
    };
}

/**
 * Create a card UI element for an uploaded .bm2 file.
 * The card shows the filename, config fields (section title,
 * caption template, compound name, dose unit), and Process/Remove
 * buttons.
 *
 * @param {string} bm2Id    — unique section identifier
 * @param {string} filename — display name (often the server's section.title)
 * @param {string} [platform] — server-assigned platform key (e.g. "Hormones",
 *                               "Body Weight") used to pick the correct
 *                               NIEHS-style title and caption defaults
 */
function createBm2Card(bm2Id, filename, platform) {
    // Route the card into the correct platform sub-tab panel.
    // If the platform is known and in the sub-tab order, ensure its
    // sub-tab exists and append the card there.  Otherwise fall back
    // to the flat #bm2-cards container (legacy path for manually
    // uploaded files).
    const container = (platform && _PLATFORM_SUB_TAB_ORDER.includes(platform))
        ? ensureDomainSubTab(platform)
        : document.getElementById('bm2-cards');

    // Resolve section title and caption from the platform (preferred)
    // or filename (fallback for manually uploaded files).
    const defaults = _resolveBm2Defaults(filename, platform);
    const defaultTitle = defaults.title;
    const defaultCaption = defaults.caption;

    // Process button is disabled until chemical ID is resolved —
    // we need the compound name for the narrative and table captions
    const processDisabled = !currentIdentity ? 'disabled' : '';

    const card = document.createElement('div');
    card.className = 'bm2-card';
    card.id = `bm2-card-${bm2Id}`;
    card.innerHTML = `
        <div class="card-header">
            <span class="filename">${escapeHtml(filename)}</span>
            <div class="card-actions">
                <button class="btn-small" id="btn-edit-${bm2Id}" onclick="editBm2('${bm2Id}')" style="display:none">
                    Edit
                </button>
                <button class="btn-small approve" id="btn-approve-${bm2Id}" onclick="approveBm2('${bm2Id}')" style="display:none">
                    Approve
                </button>
                <button class="btn-small" id="btn-retry-${bm2Id}" onclick="retryBm2('${bm2Id}')" style="display:none">
                    Try Again
                </button>
                <span class="approved-badge" id="badge-${bm2Id}" style="display:none">Approved</span>
                <span class="version-history" id="version-history-${bm2Id}" style="display:none">
                    <button class="version-btn" onclick="toggleVersionHistory('bm2', '${bm2Id}')">
                        v<span id="version-num-${bm2Id}">1</span> &#x25BE;
                    </button>
                    <div class="version-dropdown" id="version-dropdown-${bm2Id}" style="display:none"></div>
                </span>
                <button class="btn-small primary" onclick="processBm2('${bm2Id}')" id="btn-process-${bm2Id}" ${processDisabled}>
                    Process
                </button>
                <button class="btn-small danger" onclick="removeBm2('${bm2Id}')">
                    Remove
                </button>
            </div>
        </div>
        <details class="card-config-collapse">
            <summary>Section Config &amp; Narrative</summary>
            <div class="card-fields">
                <div class="form-group">
                    <label>Section Title</label>
                    <input type="text" id="bm2-title-${bm2Id}"
                        value="${escapeHtml(defaultTitle)}">
                </div>
                <div class="form-group">
                    <label>Table Caption</label>
                    <input type="text" id="bm2-caption-${bm2Id}"
                        value="${escapeHtml(defaultCaption)}">
                </div>
                <div class="form-group">
                    <label>Compound Name</label>
                    <input type="text" id="bm2-compound-${bm2Id}"
                        placeholder="e.g., PFHxSAm"
                        value="${escapeHtml(currentIdentity?.name || '')}">
                </div>
                <div class="form-group">
                    <label>Dose Unit</label>
                    <input type="text" id="bm2-unit-${bm2Id}" value="mg/kg">
                </div>
                <div class="form-group">
                    <label>Table Number</label>
                    <input type="number" id="bm2-table-number-${bm2Id}"
                        placeholder="e.g., 2" min="1" step="1"
                        style="width: 80px">
                </div>
            </div>
            <div class="bm2-narrative-label">Results Narrative</div>
            <textarea class="bm2-narrative" id="bm2-narrative-${bm2Id}" rows="6"
                placeholder="Results narrative will be auto-generated after processing. You can edit it here before exporting."></textarea>
        </details>
        <div class="table-preview" id="bm2-preview-${bm2Id}"></div>
    `;

    container.appendChild(card);
}

/**
 * Process an uploaded .bm2 file by calling /api/process-bm2.
 * Sends the bm2_id and user-configured fields, receives table
 * data back, caches it, and renders an HTML table preview.
 */
async function processBm2(bm2Id) {
    const btn = document.getElementById(`btn-process-${bm2Id}`);
    btn.disabled = true;
    btn.textContent = 'Processing...';
    hideError();

    const compoundName = document.getElementById(`bm2-compound-${bm2Id}`).value.trim();
    const doseUnit = document.getElementById(`bm2-unit-${bm2Id}`).value.trim();

    // Look up the file's server-side ID — the section's fileId points into
    // the uploadedFiles pool, and the pool entry's .id is the upload ID
    // that the server recognises.
    const section = apicalSections[bm2Id];
    const serverFileId = section?.fileId
        ? (uploadedFiles[section.fileId]?.id || section.fileId)
        : bm2Id;

    showBlockingSpinner('Processing .bm2 file...');
    try {
        const resp = await fetch('/api/process-bm2', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                bm2_id: serverFileId,
                compound_name: compoundName || 'Test Compound',
                dose_unit: doseUnit || 'mg/kg',
            }),
        });

        if (!resp.ok) {
            const err = await resp.json();
            showError(err.error || 'Processing failed');
            btn.disabled = false;
            btn.textContent = 'Process';
            return;
        }

        const result = await resp.json();

        // Cache the table data and narrative for export
        apicalSections[bm2Id].processed = true;
        apicalSections[bm2Id].tableData = result.tables;
        apicalSections[bm2Id].narrative = result.narrative || [];

        // Save the original auto-generated narrative so we can detect
        // user edits later when they approve the card
        apicalSections[bm2Id].originalNarrative = (result.narrative || []).join('\n\n');

        // Populate the narrative textarea with auto-generated prose.
        // Paragraphs are joined with double-newlines so the user can
        // visually distinguish them and edit freely.
        const narrativeEl = document.getElementById(`bm2-narrative-${bm2Id}`);
        if (narrativeEl && result.narrative && result.narrative.length > 0) {
            narrativeEl.value = result.narrative.join('\n\n');
            autoResizeTextarea(narrativeEl);
        }

        // Render HTML table preview
        renderTablePreview(bm2Id, result.tables, doseUnit || 'mg/kg');

        // Hide Process button, show Edit / Approve / Try Again buttons
        btn.style.display = 'none';
        show(`btn-edit-${bm2Id}`);
        show(`btn-approve-${bm2Id}`);
        show(`btn-retry-${bm2Id}`);

        showToast('Tables generated');
        markReportDirty();
        updateExportButton();

    } catch (err) {
        showError('Processing error: ' + err.message);
        btn.disabled = false;
        btn.textContent = 'Process';
    } finally {
        hideBlockingSpinner();
    }
}

/**
 * Render an NTP-style HTML table preview for the processed .bm2 data.
 * Creates one table per sex (Male/Female) showing endpoint rows,
 * dose columns, significance markers, and BMD/BMDL columns.
 */
function renderTablePreview(bm2Id, tables, doseUnit, tableType) {
    const previewEl = document.getElementById(`bm2-preview-${bm2Id}`);
    previewEl.innerHTML = '';

    const sectionTitle = document.getElementById(`bm2-title-${bm2Id}`).value.trim();
    const caption = document.getElementById(`bm2-caption-${bm2Id}`).value.trim();
    const compound = document.getElementById(`bm2-compound-${bm2Id}`).value.trim() || 'Test Compound';

    // Incidence tables (clinical observations) have a different structure:
    // - Header: "Finding" instead of "Endpoint"
    // - No "n" row (N is in the denominator of each "n/N" cell)
    // - Values are pre-formatted "n/N" strings rendered directly
    const isIncidence = tableType === 'incidence';

    let tableNum = 1;

    for (const sex of ['Male', 'Female']) {
        const rows = tables[sex];
        if (!rows || rows.length === 0) continue;

        // Get dose groups from the first row
        const doses = rows[0].doses;

        // Table caption heading
        const captionText = caption
            .replace('{sex}', sex)
            .replace('{compound}', compound);
        const h4 = document.createElement('h4');
        h4.textContent = `Table ${tableNum}. ${captionText}`;
        previewEl.appendChild(h4);

        // Build the HTML table
        const table = document.createElement('table');

        // Header row — "Finding" for incidence tables, "Endpoint" for normal
        const thead = document.createElement('thead');
        const headerRow = document.createElement('tr');
        headerRow.innerHTML = `<th>${isIncidence ? 'Finding' : 'Endpoint'}</th>`;
        for (const dose of doses) {
            const label = dose === 0 ? `0 ${doseUnit}` :
                (dose === Math.floor(dose) ? `${Math.floor(dose)} ${doseUnit}` : `${dose} ${doseUnit}`);
            headerRow.innerHTML += `<th>${label}</th>`;
        }
        // BMD/BMDL columns removed — they belong in the BMD summary table
        // (Table 8 equivalent), matching the NIEHS reference report structure.
        thead.appendChild(headerRow);
        table.appendChild(thead);

        const tbody = document.createElement('tbody');

        // "n" row — only for normal apical tables, NOT for incidence tables.
        // Incidence tables embed the denominator in each "n/N" cell.
        if (!isIncidence) {
            const nRow = document.createElement('tr');
            nRow.innerHTML = '<td class="endpoint-label">n</td>';
            for (const dose of doses) {
                const maxN = Math.max(...rows.map(r => r.n[String(dose)] || 0));
                nRow.innerHTML += `<td>${maxN > 0 ? maxN : '\u2013'}</td>`;
            }
            // No BMD/BMDL cells in domain tables (moved to BMD summary)
            tbody.appendChild(nRow);
        }

        // Data rows — one per endpoint/finding
        for (const row of rows) {
            const tr = document.createElement('tr');
            tr.innerHTML = `<td class="endpoint-label">${row.label}</td>`;
            for (const dose of doses) {
                const val = row.values[String(dose)] || '\u2013';
                tr.innerHTML += `<td>${val}</td>`;
            }
            // No BMD/BMDL cells in domain tables (moved to BMD summary)
            tbody.appendChild(tr);
        }

        table.appendChild(tbody);
        previewEl.appendChild(table);

        // --- Incidence table footnote ---
        // Explain the n/N format for clinical observation tables.
        if (isIncidence) {
            const footnoteEl = document.createElement('div');
            footnoteEl.className = 'table-footnote';
            footnoteEl.innerHTML = '<em>n/N = number of animals with finding / total animals in dose group.</em>';
            previewEl.appendChild(footnoteEl);
        }

        // --- Missing-animal footnotes (normal apical tables only) ---
        // Collect dose groups where animals are missing (died before
        // terminal sacrifice) from the xlsx study file roster.  Show a
        // compact footnote below the table for affected dose groups.
        if (!isIncidence) {
            const missingByDose = {};
            for (const row of rows) {
                if (!row.missing_animals) continue;
                for (const [doseKey, count] of Object.entries(row.missing_animals)) {
                    const dose = Number(doseKey);
                    if (!missingByDose[dose] || count > missingByDose[dose]) {
                        missingByDose[dose] = count;
                    }
                }
            }
            const missingDoses = Object.keys(missingByDose).map(Number).sort((a, b) => a - b);
            if (missingDoses.length > 0) {
                const footnoteEl = document.createElement('div');
                footnoteEl.className = 'table-footnote';
                const notes = missingDoses.map(d => {
                    const n = missingByDose[d];
                    const doseLabel = d === Math.floor(d) ? Math.floor(d) : d;
                    return `${n} animal${n > 1 ? 's' : ''} at ${doseLabel} ${doseUnit}`;
                });
                footnoteEl.innerHTML = `<em>Note: ${notes.join('; ')} did not survive to terminal sacrifice.</em>`;
                previewEl.appendChild(footnoteEl);
            }
        }

        tableNum++;
    }

    // Show a message if no data was found
    if (tableNum === 1) {
        const msg = isIncidence
            ? 'No clinical observations found (all animals were Normal).'
            : 'No endpoint data found in this .bm2 file.';
        previewEl.innerHTML = `<p style="color:#6c757d;font-size:0.8rem;">${msg}</p>`;
    }
}

/**
 * Render pre-computed table data and narrative into a BM2 section card.
 *
 * This is the "already processed" counterpart of processBm2() — instead
 * of hitting the server, it takes pre-computed results (from the integrated
 * process-integrated endpoint) and populates the card's preview and
 * narrative textarea directly.
 *
 * @param {string} sectionId   — the section ID (e.g., "integrated-body_weight")
 * @param {Object} tablesJson  — {Male: [...], Female: [...]} table data
 * @param {string[]} narrative — array of auto-generated paragraph strings
 */
function renderBm2Results(sectionId, tablesJson, narrative, tableType) {
    // Populate the narrative textarea
    const narrativeEl = document.getElementById(`bm2-narrative-${sectionId}`);
    if (narrativeEl && narrative && narrative.length > 0) {
        narrativeEl.value = narrative.join('\n\n');
        autoResizeTextarea(narrativeEl);
    }

    // Determine dose unit from the card's input field
    const unitEl = document.getElementById(`bm2-unit-${sectionId}`);
    const doseUnit = unitEl ? unitEl.value : 'mg/kg';

    // Render the table preview — pass tableType so incidence tables
    // get different column headers and no "n" row.
    renderTablePreview(sectionId, tablesJson, doseUnit, tableType);

    // Hide Process button, show Edit / Approve / Try Again buttons
    const btn = document.getElementById(`btn-process-${sectionId}`);
    if (btn) btn.style.display = 'none';
    show(`btn-edit-${sectionId}`);
    show(`btn-approve-${sectionId}`);
    show(`btn-retry-${sectionId}`);
}


/**
 * Remove an uploaded .bm2 file card from the UI and delete it
 * from the local state.  The server-side temp file is left for
 * OS cleanup (no DELETE endpoint needed for ephemeral data).
 */
function removeBm2(bm2Id) {
    delete apicalSections[bm2Id];
    const card = document.getElementById(`bm2-card-${bm2Id}`);
    if (card) card.remove();

    // Hide the results section if no cards remain
    if (Object.keys(apicalSections).length === 0) {
        hide('bm2-results-section');
    }
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
        showBlockingSpinner('Saving metadata and exporting .bm2...');

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
