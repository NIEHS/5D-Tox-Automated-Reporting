/* -----------------------------------------------------------------
 * upload.js — File upload, pool management, and session reset
 *
 * Split from filepool.js.  Handles drag-and-drop file uploads
 * (.bm2, .csv, .txt, .xlsx, .zip), the file pool list UI,
 * file removal, and pool/session reset operations.
 *
 * Depends on: state.js (globals), utils.js (helpers),
 *             validation.js (showValidationPanel)
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

        // Clear platform containers — remove cards from each static container
        for (const pc of document.querySelectorAll('.platform-container')) {
            // Only remove child .bm2-card elements, keep the <h3> header
            pc.querySelectorAll('.bm2-card').forEach(c => c.remove());
        }

        // Clear genomics card containers
        const geneSetCards = document.getElementById('genomics-gene-set-cards');
        if (geneSetCards) geneSetCards.innerHTML = '';
        const geneBmdCards = document.getElementById('genomics-gene-bmd-cards');
        if (geneBmdCards) geneBmdCards.innerHTML = '';

        // Clear dynamic TOC children in the sidebar
        const tocGeneSets = document.getElementById('toc-gene-set-children');
        if (tocGeneSets) tocGeneSets.innerHTML = '';
        const tocGeneBmd = document.getElementById('toc-gene-bmd-children');
        if (tocGeneBmd) tocGeneBmd.innerHTML = '';

        // Clear charts sub-tabs and chart containers
        const chartsSubTabs = document.getElementById('charts-sub-tabs');
        if (chartsSubTabs) { chartsSubTabs.innerHTML = ''; chartsSubTabs.classList.remove('visible'); delete chartsSubTabs.dataset.keys; }
        const umapChart = document.getElementById('umap-chart');
        if (umapChart) umapChart.innerHTML = '';
        const clusterChart = document.getElementById('cluster-chart');
        if (clusterChart) clusterChart.innerHTML = '';

        // Clear unified narrative textareas
        for (const ta of document.querySelectorAll('.unified-narrative')) {
            ta.value = '';
        }

        // Hide metadata review section
        const metadataSection = document.getElementById('metadata-review-section');
        if (metadataSection) metadataSection.style.display = 'none';

        // Reset all section readiness flags via Alpine store
        if (typeof Alpine !== 'undefined' && Alpine.store('app')) {
            const ready = Alpine.store('app').ready;
            ready.animalCondition = false;
            ready.clinicalPath = false;
            ready.internalDose = false;
            ready.bmdSummary = false;
            ready.bmdSummaryBmds = false;
            ready.geneSets = false;
            ready.geneBmd = false;
            ready.charts = false;
            ready.methods = false;
            ready.summary = false;
            Alpine.store('app').unifiedNarratives = {};
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

        // Clear platform containers and genomics cards
        for (const pc of document.querySelectorAll('.platform-container')) {
            pc.querySelectorAll('.bm2-card').forEach(c => c.remove());
        }
        const geneSetCards = document.getElementById('genomics-gene-set-cards');
        if (geneSetCards) geneSetCards.innerHTML = '';
        const geneBmdCards = document.getElementById('genomics-gene-bmd-cards');
        if (geneBmdCards) geneBmdCards.innerHTML = '';
        const tocGeneSets = document.getElementById('toc-gene-set-children');
        if (tocGeneSets) tocGeneSets.innerHTML = '';
        const tocGeneBmd = document.getElementById('toc-gene-bmd-children');
        if (tocGeneBmd) tocGeneBmd.innerHTML = '';
        for (const ta of document.querySelectorAll('.unified-narrative')) {
            ta.value = '';
        }

        // Hide metadata review section
        const metadataSection = document.getElementById('metadata-review-section');
        if (metadataSection) metadataSection.style.display = 'none';

        // Reset all Alpine store readiness flags
        if (typeof Alpine !== 'undefined' && Alpine.store('app')) {
            const ready = Alpine.store('app').ready;
            ready.data = false;
            ready.animalCondition = false;
            ready.clinicalPath = false;
            ready.internalDose = false;
            ready.bmdSummary = false;
            ready.bmdSummaryBmds = false;
            ready.geneSets = false;
            ready.geneBmd = false;
            ready.charts = false;
            ready.methods = false;
            ready.summary = false;
            Alpine.store('app').unifiedNarratives = {};
        }

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
