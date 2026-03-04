/* -----------------------------------------------------------------
 * main.js — Core application logic for 5dToxReport
 *
 * Loaded after state.js (global state) and utils.js (shared helpers).
 * Contains all application functions: chemical resolution, background
 * generation, file upload handling, apical endpoint processing,
 * genomics analysis, session persistence, approval workflows,
 * version history, DOCX export, and the tabbed/stacked view toggle.
 *
 * All functions are in global scope (classic <script>, not ES modules)
 * so they're accessible from inline onclick handlers in HTML templates.
 * ----------------------------------------------------------------- */

/* ================================================================
 * Collapsible sections — toggles the .collapsed class on the
 * nearest [data-collapsible] ancestor, hiding or showing the
 * .section-body.  Called from onclick on section headers.
 * ================================================================ */
function toggleSection(el) {
    // Walk up from the clicked element to find the collapsible container
    const section = el.closest('[data-collapsible]');
    if (section) section.classList.toggle('collapsed');
}

/* ================================================================
 * Collapse / Expand all — iterates every [data-collapsible]
 * section and adds or removes the .collapsed class.
 * ================================================================ */
function collapseAll() {
    document.querySelectorAll('[data-collapsible]').forEach(
        s => s.classList.add('collapsed')
    );
}

function expandAll() {
    document.querySelectorAll('[data-collapsible]').forEach(
        s => s.classList.remove('collapsed')
    );
}

/* ================================================================
 * Tabbed view — switches between stacked (default) and tabbed
 * layout.  In tabbed mode, a tab bar shows one button per visible
 * section.  Clicking a tab shows only that section's panel.
 *
 * The .tabbed-view class on .container drives all CSS changes:
 *   - tab bar becomes visible
 *   - sections are hidden unless they have .tab-active
 *   - chevrons and collapse/expand buttons are hidden
 * ================================================================ */

/* Toggle between stacked and tabbed modes */
function toggleTabbedView() {
    tabbedViewActive = !tabbedViewActive;
    const container = document.querySelector('.container');
    const btn = document.getElementById('btn-tabbed-view');

    if (tabbedViewActive) {
        container.classList.add('tabbed-view');
        btn.classList.add('active');
        // Expand all sections so content is visible inside tabs
        document.querySelectorAll('[data-collapsible]').forEach(
            s => s.classList.remove('collapsed')
        );
        buildTabBar();
    } else {
        container.classList.remove('tabbed-view');
        btn.classList.remove('active');
        // Remove tab-active from all sections so normal display
        // rules (style="display:none" etc.) take over again
        document.querySelectorAll('[data-tab-section]').forEach(
            s => s.classList.remove('tab-active')
        );
    }
}

/* Build (or rebuild) the tab bar buttons from visible sections.
   Only sections that are not hidden via style="display:none" get
   a tab.  This should be called whenever a section becomes visible
   (e.g., after background generation reveals the File Pool). */
function buildTabBar() {
    const bar = document.getElementById('tab-bar');
    bar.innerHTML = '';
    const sections = document.querySelectorAll('[data-tab-section]');
    let firstVisible = null;
    let hasActive = false;

    sections.forEach(section => {
        // Skip sections hidden by the app (style.display === 'none')
        // but NOT sections hidden by tabbed-view CSS (which uses a class).
        // Check the inline style specifically.
        if (section.style.display === 'none') return;

        const label = section.getAttribute('data-tab-section');
        const btn = document.createElement('button');
        btn.textContent = label;
        btn.onclick = () => activateTab(label);
        bar.appendChild(btn);

        if (!firstVisible) firstVisible = label;

        // Preserve current active tab if it's still visible
        if (section.classList.contains('tab-active')) {
            btn.classList.add('active');
            hasActive = true;
        }
    });

    // If no tab was active (first time or previous tab hidden),
    // activate the first visible one
    if (!hasActive && firstVisible) {
        activateTab(firstVisible);
    }
}

/* Switch to a specific tab — show that section, hide all others */
function activateTab(label) {
    document.querySelectorAll('[data-tab-section]').forEach(section => {
        if (section.getAttribute('data-tab-section') === label) {
            section.classList.add('tab-active');
        } else {
            section.classList.remove('tab-active');
        }
    });

    // Update tab bar button active states
    const bar = document.getElementById('tab-bar');
    bar.querySelectorAll('button').forEach(btn => {
        btn.classList.toggle('active', btn.textContent === label);
    });
}


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

/* ================================================================
 * Generate background — POST /api/generate with SSE progress
 * ================================================================ */

async function generateBackground() {
    if (isGenerating) return;

    // Build identity from form fields if not already resolved
    if (!currentIdentity) {
        currentIdentity = {
            name: document.getElementById('name').value.trim(),
            casrn: document.getElementById('casrn').value.trim(),
            dtxsid: document.getElementById('dtxsid').value.trim(),
            pubchem_cid: parseInt(document.getElementById('cid').value.trim()) || 0,
            ec_number: document.getElementById('ec').value.trim(),
        };
    }

    if (!currentIdentity.name && !currentIdentity.casrn) {
        showError('Enter at least a chemical name or CASRN.');
        return;
    }

    isGenerating = true;
    hideError();
    hideOutput();
    showProgress();

    const btn = document.getElementById('btn-generate');
    btn.disabled = true;
    btn.textContent = 'Generating...';

    const modelSelect = document.getElementById('model-select');
    const useOllama = modelSelect.value === 'ollama';

    try {
        const resp = await fetch('/api/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                identity: currentIdentity,
                use_ollama: useOllama,
            }),
        });

        // Read SSE stream
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });

            // Parse complete SSE events from the buffer
            const events = buffer.split('\n\n');
            // Keep the last (possibly incomplete) event in the buffer
            buffer = events.pop() || '';

            for (const eventStr of events) {
                if (!eventStr.trim()) continue;

                const lines = eventStr.trim().split('\n');
                let eventType = '';
                let eventData = '';

                for (const line of lines) {
                    if (line.startsWith('event: ')) {
                        eventType = line.slice(7);
                    } else if (line.startsWith('data: ')) {
                        eventData = line.slice(6);
                    }
                }

                if (eventType === 'progress') {
                    const data = JSON.parse(eventData);
                    addProgressLog(data.message);
                } else if (eventType === 'complete') {
                    currentResult = JSON.parse(eventData);
                    displayResult(currentResult);
                    hideProgress();
                } else if (eventType === 'error') {
                    const data = JSON.parse(eventData);
                    showError(data.error);
                    hideProgress();
                }
            }
        }

    } catch (err) {
        showError('Generation failed: ' + err.message);
        hideProgress();
    } finally {
        isGenerating = false;
        btn.disabled = false;
        btn.textContent = 'Generate Background';
    }
}

/* ================================================================
 * Display the generated result
 * ================================================================ */

function displayResult(result) {
    const proseEl = document.getElementById('output-prose');
    const refsEl = document.getElementById('references-list');
    const metaEl = document.getElementById('meta-info');
    const notesPanel = document.getElementById('notes-panel');
    const notesList = document.getElementById('notes-list');

    // Clear previous output
    proseEl.innerHTML = '';
    refsEl.innerHTML = '';

    // Render paragraphs as editable blocks
    (result.paragraphs || []).forEach((para, i) => {
        const div = document.createElement('div');
        div.className = 'paragraph';
        div.contentEditable = 'true';
        // Convert [N] markers to <sup> tags for display
        div.innerHTML = para.replace(
            /\[(\d+(?:[,\-\u2013]\d+)*)\]/g,
            '<sup>[$1]</sup>'
        );
        proseEl.appendChild(div);
    });

    // Render references
    (result.references || []).forEach(ref => {
        const div = document.createElement('div');
        div.textContent = ref;
        div.contentEditable = 'true';
        refsEl.appendChild(div);
    });

    // Show metadata
    metaEl.textContent = `Model: ${result.model_used || 'unknown'} | ` +
        `~${result.prompt_tokens_approx || '?'} prompt tokens`;

    // Show notes/warnings if any
    const notes = result.notes || [];
    if (notes.length > 0) {
        notesList.innerHTML = '';
        notes.forEach(note => {
            const li = document.createElement('li');
            li.textContent = note;
            notesList.appendChild(li);
        });
        notesPanel.classList.add('visible');
    } else {
        notesPanel.classList.remove('visible');
    }

    document.getElementById('output-section').classList.add('visible');

    // Save original LLM-generated text for later comparison.
    // When the user approves, we send both original and (possibly
    // edited) text to the server so it can detect edits and learn
    // writing style preferences from the differences.
    currentResult.originalParagraphs = [...(result.paragraphs || [])];
    currentResult.originalReferences = [...(result.references || [])];

    // Show action buttons (they're hidden until generation).
    // Edit is always visible so the user can modify text at any time.
    show('btn-edit-bg');
    show('btn-approve-bg');
    show('btn-retry-bg');
    hide('badge-bg');

    // Reset approval state — new generation means unapproved
    backgroundApproved = false;
    unlockSection(document.getElementById('output-section'));

    // Show the file pool, animal report, and section builder now that background is done
    show('file-pool-section');

    show('section-builder');
    if (tabbedViewActive) buildTabBar();

    // Generating background also confirms identity — enable
    // Process/Export buttons if they were still disabled
    onIdentityResolved();

    // Update export button state (background is now unapproved)
    updateExportButton();
}

/* ================================================================
 * Unified file pool — drag-and-drop + file input handling.
 *
 * A single drop zone accepts both .bm2 and .csv files.  Uploaded
 * files appear in a compact list (the "file pool").  The user then
 * uses the Section Builder to create report sections from them.
 * ================================================================ */

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
    // Partition files by extension — zip files are handled separately
    // because the server extracts them and returns individual file entries.
    const bm2List = [];
    const csvList = [];
    const zipList = [];
    const lowerName = f => f.name.toLowerCase();
    for (const f of fileList) {
        const name = f.name.toLowerCase();
        if (name.endsWith('.bm2')) bm2List.push(f);
        else if (name.endsWith('.csv')) csvList.push(f);
        else if (name.endsWith('.zip')) zipList.push(f);
        // .txt and .xlsx are only supported inside zip archives —
        // direct upload of loose .txt/.xlsx files isn't handled by
        // the existing server endpoints, so we skip them here.
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

    // Upload .csv files if any
    if (csvList.length > 0) {
        const formData = new FormData();
        for (const file of csvList) formData.append('files', file);

        try {
            const resp = await fetch('/api/upload-csv', {
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
                        type: 'csv',
                        row_count: item.row_count,
                        columns: item.columns_found,
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
        // Re-populate the section builder's file picker dropdown
        // so newly uploaded files appear immediately
        onSectionTypeChange();
        updateClearFilesButton();
        // Show the validation panel so user knows validation is available
        showValidationPanel();
    }
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
 * Also removes it from the section builder's file picker.
 *
 * @param {string} fileId — the ID of the file to remove
 */
function removeFile(fileId) {
    delete uploadedFiles[fileId];
    const el = document.getElementById(`file-pool-${fileId}`);
    if (el) el.remove();
    // Refresh the file picker dropdown in case the removed file was selected
    onSectionTypeChange();
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
    onSectionTypeChange();
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
 * Run full pool validation by calling POST /api/pool/validate/{dtxsid}.
 *
 * Sends the request, receives a ValidationReport JSON, and renders
 * the coverage matrix + issues list in the validation panel.
 * Also updates status dots on each file pool item.
 */
async function runPoolValidation() {
    // Need a DTXSID to validate against — it's stored in the chem ID form
    const dtxsid = document.getElementById('dtxsid')?.value?.trim();
    if (!dtxsid) {
        showToast('Resolve a chemical identity first');
        return;
    }

    const btn = document.getElementById('btn-validate');
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Validating...';
    }

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

        // Show the Approve button so the user can sign off on the pool
        // and trigger the animal report generation.
        show('btn-approve-pool');
    } catch (e) {
        showToast('Validation request failed: ' + e.message);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Validate & Integrate';
        }
    }
}

/**
 * Render the coverage matrix table.
 *
 * Shows a table with one row per domain and columns for xlsx, txt/csv, bm2.
 * Each cell shows checkmarks (✓) for present files, dashes (—) for missing,
 * and a warning icon (⚠) in the rightmost column if any tier is missing.
 *
 * @param {Object} report — ValidationReport from the server
 */
function renderCoverageMatrix(report) {
    const container = document.getElementById('coverage-matrix');
    if (!container) return;

    const matrix = report.coverage_matrix || {};
    const domains = Object.keys(matrix).sort();

    if (domains.length === 0) {
        container.innerHTML = '<p style="color:var(--c-text-muted);font-size:0.8rem;">No domains detected.</p>';
        return;
    }

    // Human-readable domain labels
    const domainLabels = {
        body_weight: 'Body Weight',
        organ_weights: 'Organ Weights',
        clin_chem: 'Clinical Chemistry',
        hematology: 'Hematology',
        hormones: 'Hormones',
        tissue_conc: 'Tissue Concentration',
        clinical_obs: 'Clinical Observations',
        gene_expression: 'Gene Expression',
    };

    let html = '<table class="coverage-matrix">';
    html += '<thead><tr><th>Domain</th><th>xlsx</th><th>txt/csv</th><th>bm2</th><th></th></tr></thead>';
    html += '<tbody>';

    for (const domain of domains) {
        const tiers = matrix[domain];
        const hasXlsx = !!tiers.xlsx;
        const txtCsvCount = (tiers.txt_csv || []).length;
        const hasBm2 = !!tiers.bm2;

        // Gene expression typically has no xlsx — don't show missing as a gap
        const xlsxExpected = domain !== 'gene_expression';

        // Build tier cells — show ✓ count for txt_csv (may have multiple: one per sex)
        const xlsxCell = hasXlsx
            ? '<span class="coverage-check">✓</span>'
            : (xlsxExpected ? '<span class="coverage-dash">—</span>' : '<span class="coverage-dash">n/a</span>');

        let txtCell;
        if (txtCsvCount === 0) {
            txtCell = '<span class="coverage-dash">—</span>';
        } else if (txtCsvCount === 1) {
            txtCell = '<span class="coverage-check">✓</span>';
        } else {
            // Multiple txt/csv files (one per sex) — show count
            txtCell = '<span class="coverage-check">' + '✓'.repeat(Math.min(txtCsvCount, 4)) + '</span>';
        }

        const bm2Cell = hasBm2
            ? '<span class="coverage-check">✓</span>'
            : '<span class="coverage-dash">—</span>';

        // Warning indicator — show if any expected tier is missing
        const hasMissingTier = (xlsxExpected && !hasXlsx) || txtCsvCount === 0 || !hasBm2;
        const warnCell = hasMissingTier
            ? '<span class="coverage-warn">⚠</span>'
            : '';

        const label = domainLabels[domain] || domain;
        html += `<tr><td>${label}</td><td>${xlsxCell}</td><td>${txtCell}</td><td>${bm2Cell}</td><td>${warnCell}</td></tr>`;
    }

    html += '</tbody></table>';
    container.innerHTML = html;
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

            // For dose mismatch errors, add expandable conflict resolution
            if (sev === 'error' && issue.issue_type === 'dose_mismatch' && issue.details) {
                bodyHtml += renderConflictResolution(issue, index, report);
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
            tsHtml += `<div>${fp.filename} — added: ${added}, internal date: ${internal}</div>`;
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
        const label = fp ? `${fp.filename} (${fp.file_type})` : fid;
        const isRec = fid === suggested;
        html += `<label class="${isRec ? 'recommended' : ''}">`;
        html += `<input type="radio" name="conflict-${index}" value="${fid}"`;
        html += ` onchange="resolveConflict(${index}, '${fid}')"`;
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
}


/**
 * Called when the section type dropdown changes.
 * Shows/hides the appropriate config panel (apical vs genomics)
 * and repopulates the file picker with compatible files.
 */
function onSectionTypeChange() {
    const sectionType = document.getElementById('section-type-select').value;

    // Show/hide config panels
    document.getElementById('apical-config').classList.toggle('visible', sectionType === 'apical');
    document.getElementById('genomics-config').classList.toggle('visible', sectionType === 'genomics');

    // Populate file picker with files matching the selected type
    if (sectionType === 'apical') {
        populateFilePicker('bm2');
    } else if (sectionType === 'genomics') {
        populateFilePicker('csv');
    } else {
        // No type selected — clear the picker
        const select = document.getElementById('section-file-select');
        select.innerHTML = '<option value="">— select file —</option>';
    }

    updateAddButton();
}

/**
 * Fill the #section-file-select dropdown with files from the pool
 * that match the given type ('bm2' or 'csv').
 *
 * @param {string} fileType — 'bm2' or 'csv'
 */
function populateFilePicker(fileType) {
    const select = document.getElementById('section-file-select');
    select.innerHTML = '<option value="">— select file —</option>';

    for (const [fileId, file] of Object.entries(uploadedFiles)) {
        if (file.type !== fileType) continue;
        const opt = document.createElement('option');
        opt.value = fileId;
        opt.textContent = file.filename;
        select.appendChild(opt);
    }

    // Listen for selection changes to enable/disable the Add button
    // and to auto-detect section defaults from the filename
    select.onchange = () => {
        updateAddButton();
        // Auto-detect clinical pathology from filename when type is apical
        if (fileType === 'bm2' && select.value) {
            const file = uploadedFiles[select.value];
            if (file) {
                const lowerName = file.filename.toLowerCase();
                const isClinical = lowerName.includes('clinical') || lowerName.includes('pathology');
                document.getElementById('builder-title').value = isClinical
                    ? 'Clinical Pathology'
                    : 'Animal Condition, Body Weights, and Organ Weights';
                document.getElementById('builder-caption').value = isClinical
                    ? 'Summary of Clinical Pathology Findings of {sex} Rats Administered {compound} for Five Days'
                    : 'Summary of Body Weights and Organ Weights of {sex} Rats Administered {compound} for Five Days';
            }
        }
    };
}

/**
 * Enable the "Add & Process" button only when both a section type
 * and a file have been selected.
 */
function updateAddButton() {
    const sectionType = document.getElementById('section-type-select').value;
    const fileId = document.getElementById('section-file-select').value;
    const btn = document.getElementById('btn-add-section');
    btn.disabled = !(sectionType && fileId);
}

/**
 * "Add & Process" — reads the section builder form, creates a new
 * report section (apical or genomics), creates the result card in
 * the UI, and triggers processing on the server.
 *
 * For apical: creates an entry in apicalSections, calls createBm2Card()
 * and then processBm2() automatically.
 *
 * For genomics: calls processCsv() which creates a genomicsResults entry.
 */
async function addAndProcessSection() {
    const sectionType = document.getElementById('section-type-select').value;
    const fileId = document.getElementById('section-file-select').value;
    const file = uploadedFiles[fileId];

    if (!sectionType || !fileId || !file) return;

    if (sectionType === 'apical') {
        // --- Create an apical endpoint section from a .bm2 file ---
        const sectionId = 'apical-' + (++apicalSectionCounter);

        // Read config from builder form
        const sectionTitle = document.getElementById('builder-title').value.trim();
        const tableCaption = document.getElementById('builder-caption').value.trim();
        const compound = document.getElementById('builder-compound').value.trim()
            || currentIdentity?.name || '';
        const doseUnit = document.getElementById('builder-unit').value.trim() || 'mg/kg';

        // Register in apicalSections state
        apicalSections[sectionId] = {
            fileId: fileId,
            filename: file.filename,
            processed: false,
            approved: false,
            tableData: null,
            narrative: null,
            originalNarrative: '',
        };

        // Create the .bm2 result card
        createBm2Card(sectionId, file.filename);

        // Override defaults in the card with builder config values
        const titleEl = document.getElementById(`bm2-title-${sectionId}`);
        if (titleEl) titleEl.value = sectionTitle;
        const captionEl = document.getElementById(`bm2-caption-${sectionId}`);
        if (captionEl) captionEl.value = tableCaption;
        const compoundEl = document.getElementById(`bm2-compound-${sectionId}`);
        if (compoundEl) compoundEl.value = compound;
        const unitEl = document.getElementById(`bm2-unit-${sectionId}`);
        if (unitEl) unitEl.value = doseUnit;

        // Show the results section
        show('bm2-results-section');
        if (tabbedViewActive) buildTabBar();

        // Automatically trigger processing
        processBm2(sectionId);

    } else if (sectionType === 'genomics') {
        // --- Create a transcriptomic analysis section from a .csv file ---
        const organ = document.getElementById('builder-organ').value;
        const sex = document.getElementById('builder-sex').value;

        // Process using the file's server-side ID (from upload response)
        await processCsv(fileId, organ, sex);
    }
}

/**
 * Create a card UI element for an uploaded .bm2 file.
 * The card shows the filename, config fields (section title,
 * caption template, compound name, dose unit), and Process/Remove
 * buttons.
 */
function createBm2Card(bm2Id, filename) {
    const container = document.getElementById('bm2-cards');

    // Detect section type from the filename — if it contains
    // "clinical" or "pathology", use Clinical Pathology defaults;
    // otherwise default to organ/body weight section.
    const lowerName = filename.toLowerCase();
    const isClinical = lowerName.includes('clinical') || lowerName.includes('pathology');

    const defaultTitle = isClinical
        ? 'Clinical Pathology'
        : 'Animal Condition, Body Weights, and Organ Weights';
    const defaultCaption = isClinical
        ? 'Summary of Clinical Pathology Findings of {sex} Rats Administered {compound} for Five Days'
        : 'Summary of Body Weights and Organ Weights of {sex} Rats Administered {compound} for Five Days';

    // Process button is disabled until chemical ID is resolved —
    // we need the compound name for the narrative and table captions
    const processDisabled = !currentIdentity ? 'disabled' : '';

    const card = document.createElement('div');
    card.className = 'bm2-card';
    card.id = `bm2-card-${bm2Id}`;
    card.innerHTML = `
        <div class="card-header">
            <span class="filename">${filename}</span>
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
        <div class="card-fields">
            <div class="form-group">
                <label>Section Title</label>
                <input type="text" id="bm2-title-${bm2Id}"
                    value="${defaultTitle}">
            </div>
            <div class="form-group">
                <label>Table Caption</label>
                <input type="text" id="bm2-caption-${bm2Id}"
                    value="${defaultCaption}">
            </div>
            <div class="form-group">
                <label>Compound Name</label>
                <input type="text" id="bm2-compound-${bm2Id}"
                    placeholder="e.g., PFHxSAm"
                    value="${currentIdentity?.name || ''}">
            </div>
            <div class="form-group">
                <label>Dose Unit</label>
                <input type="text" id="bm2-unit-${bm2Id}" value="mg/kg">
            </div>
        </div>
        <div class="bm2-narrative-label">Results Narrative</div>
        <textarea class="bm2-narrative" id="bm2-narrative-${bm2Id}" rows="6"
            placeholder="Results narrative will be auto-generated after processing. You can edit it here before exporting."></textarea>
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
        updateExportButton();

    } catch (err) {
        showError('Processing error: ' + err.message);
        btn.disabled = false;
        btn.textContent = 'Process';
    }
}

/**
 * Render an NTP-style HTML table preview for the processed .bm2 data.
 * Creates one table per sex (Male/Female) showing endpoint rows,
 * dose columns, significance markers, and BMD/BMDL columns.
 */
function renderTablePreview(bm2Id, tables, doseUnit) {
    const previewEl = document.getElementById(`bm2-preview-${bm2Id}`);
    previewEl.innerHTML = '';

    const sectionTitle = document.getElementById(`bm2-title-${bm2Id}`).value.trim();
    const caption = document.getElementById(`bm2-caption-${bm2Id}`).value.trim();
    const compound = document.getElementById(`bm2-compound-${bm2Id}`).value.trim() || 'Test Compound';

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

        // Header row: Endpoint | dose columns | BMD1Std | BMDL1Std
        const thead = document.createElement('thead');
        const headerRow = document.createElement('tr');
        headerRow.innerHTML = '<th>Endpoint</th>';
        for (const dose of doses) {
            const label = dose === 0 ? `0 ${doseUnit}` :
                (dose === Math.floor(dose) ? `${Math.floor(dose)} ${doseUnit}` : `${dose} ${doseUnit}`);
            headerRow.innerHTML += `<th>${label}</th>`;
        }
        headerRow.innerHTML += `<th class="bmd-col">BMD1Std (${doseUnit})</th>`;
        headerRow.innerHTML += `<th class="bmd-col">BMDL1Std (${doseUnit})</th>`;
        thead.appendChild(headerRow);
        table.appendChild(thead);

        const tbody = document.createElement('tbody');

        // "n" row — sample sizes per dose group (max across endpoints)
        const nRow = document.createElement('tr');
        nRow.innerHTML = '<td class="endpoint-label">n</td>';
        for (const dose of doses) {
            const maxN = Math.max(...rows.map(r => r.n[String(dose)] || 0));
            nRow.innerHTML += `<td>${maxN}</td>`;
        }
        nRow.innerHTML += '<td class="bmd-col">NA</td><td class="bmd-col">NA</td>';
        tbody.appendChild(nRow);

        // Data rows — one per endpoint
        for (const row of rows) {
            const tr = document.createElement('tr');
            tr.innerHTML = `<td class="endpoint-label">${row.label}</td>`;
            for (const dose of doses) {
                const val = row.values[String(dose)] || '\u2013';
                tr.innerHTML += `<td>${val}</td>`;
            }
            tr.innerHTML += `<td class="bmd-col">${row.bmd}</td>`;
            tr.innerHTML += `<td class="bmd-col">${row.bmdl}</td>`;
            tbody.appendChild(tr);
        }

        table.appendChild(tbody);
        previewEl.appendChild(table);
        tableNum++;
    }

    // Show a message if no data was found
    if (tableNum === 1) {
        previewEl.innerHTML = '<p style="color:#6c757d;font-size:0.8rem;">No endpoint data found in this .bm2 file.</p>';
    }
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

/* ================================================================
 * Copy to clipboard — extracts plain text from contenteditable divs
 * ================================================================ */

function copyToClipboard() {
    const proseEl = document.getElementById('output-prose');
    const refsEl = document.getElementById('references-list');

    // Extract text from editable paragraphs
    const paragraphs = extractProse('output-prose');

    const references = Array.from(refsEl.querySelectorAll('div'))
        .map(div => div.textContent.trim());

    const fullText = paragraphs.join('\n\n') +
        '\n\nReferences\n' +
        references.join('\n');

    navigator.clipboard.writeText(fullText).then(() => {
        showToast('Copied to clipboard');
    }).catch(() => {
        // Fallback for older browsers
        const textarea = document.createElement('textarea');
        textarea.value = fullText;
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
        showToast('Copied to clipboard');
    });
}

/* ================================================================
 * Export .docx — sends background + apical sections to server
 * ================================================================ */

async function exportDocx() {
    const proseEl = document.getElementById('output-prose');
    const refsEl = document.getElementById('references-list');

    // Collect current text from editable elements (user may have polished)
    const paragraphs = extractProse('output-prose');

    const references = Array.from(refsEl.querySelectorAll('div'))
        .map(div => div.textContent.trim());

    const chemicalName = currentIdentity?.name || 'Chemical';

    // Build apical sections payload from processed sections — only
    // include sections that have been processed (have table data)
    const apicalPayload = [];
    for (const [sectionId, info] of Object.entries(apicalSections)) {
        if (!info.processed) continue;

        // Read narrative from the textarea (user may have edited it).
        // Split on double-newlines to recover individual paragraphs.
        const narrativeEl = document.getElementById(`bm2-narrative-${sectionId}`);
        const narrativeText = narrativeEl?.value?.trim() || '';
        const narrativeParagraphs = narrativeText
            ? narrativeText.split(/\n\s*\n/).map(p => p.trim()).filter(Boolean)
            : [];

        // Look up the server-side file ID from the upload pool
        const serverFileId = info.fileId
            ? (uploadedFiles[info.fileId]?.id || info.fileId)
            : sectionId;

        apicalPayload.push({
            bm2_id: serverFileId,
            section_title: document.getElementById(`bm2-title-${sectionId}`)?.value?.trim()
                || 'Animal Condition, Body Weights, and Organ Weights',
            table_caption_template: document.getElementById(`bm2-caption-${sectionId}`)?.value?.trim()
                || 'Summary of Body Weights and Organ Weights of {sex} Rats Administered {compound} for Five Days',
            compound_name: document.getElementById(`bm2-compound-${sectionId}`)?.value?.trim()
                || chemicalName,
            dose_unit: document.getElementById(`bm2-unit-${sectionId}`)?.value?.trim()
                || 'mg/kg',
            narrative_paragraphs: narrativeParagraphs,
        });
    }

    // Collect new NIEHS section data for export

    // Methods data — structured format if available, else legacy flat paragraphs.
    // When structured, we extract the edited subsection prose from the DOM
    // and merge it back into the original methodsData structure so the server
    // gets both the heading hierarchy and the (possibly edited) prose.
    let methodsPayload = {};
    if (methodsApproved && methodsData && methodsData.sections) {
        // Structured format — extract edited subsections from DOM
        const editedSections = extractMethodsSections();
        methodsPayload = {
            sections: editedSections,
            context: methodsData.context || {},
        };
    }
    const methodsParas = (methodsApproved && !methodsPayload.sections)
        ? extractProse('methods-prose') : [];

    // BMD summary endpoints (if loaded)
    const bmdSummaryEps = bmdSummaryApproved ? bmdSummaryEndpoints : [];

    // Genomics sections (all approved ones)
    const genomicsSecs = [];
    for (const [key, data] of Object.entries(genomicsResults)) {
        if (data.approved) {
            genomicsSecs.push({
                organ: data.organ,
                sex: data.sex,
                gene_sets: data.gene_sets,
                top_genes: data.top_genes,
                dose_unit: 'mg/kg',
            });
        }
    }

    // Summary paragraphs (if approved)
    const summaryParas = summaryApproved ? extractProse('summary-prose') : [];

    // Animal report — include if approved and data is available
    const animalReportPayload = (animalReportApproved && animalReportData)
        ? animalReportData : null;

    try {
        const resp = await fetch('/api/export-docx', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                paragraphs,
                references,
                chemical_name: chemicalName,
                apical_sections: apicalPayload,
                methods_data: methodsPayload.sections ? methodsPayload : null,
                methods_paragraphs: methodsParas,
                animal_report: animalReportPayload,
                bmd_summary_endpoints: bmdSummaryEps,
                genomics_sections: genomicsSecs,
                summary_paragraphs: summaryParas,
            }),
        });

        if (!resp.ok) {
            const err = await resp.json();
            showError(err.error || 'Export failed');
            return;
        }

        // Download the file
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `5dToxReport_${chemicalName.replace(/[^a-zA-Z0-9 _-]/g, '_')}.docx`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        showToast('Downloaded .docx');
    } catch (err) {
        showError('Export error: ' + err.message);
    }
}

/* ================================================================
 * UI helper functions
 * ================================================================ */

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

    // Backfill the section builder's compound name field too
    const builderCompound = document.getElementById('builder-compound');
    if (builderCompound && !builderCompound.value.trim()) {
        builderCompound.value = name;
    }

    // Enable Generate Background button (Export is gated on approvals)
    const genBtn = document.getElementById('btn-generate');
    if (genBtn) genBtn.disabled = false;

    // Update export button state — it's now gated on all sections
    // being approved, not just on identity being resolved.
    updateExportButton();
}


/* ================================================================
 * Approve / Try Again — background section
 * ================================================================ */

/**
 * Approve the background section: POST the current paragraphs and
 * references to /api/session/approve, lock the section for editing,
 * and show the green "Approved" visual state.
 */
async function approveBackground() {
    if (!currentIdentity?.dtxsid) {
        showError('Resolve a chemical identity (with DTXSID) before approving.');
        return;
    }

    // Collect current editable text (user may have polished it)
    const refsEl = document.getElementById('references-list');
    const paragraphs = extractProse('output-prose');
    const references = Array.from(refsEl.querySelectorAll('div'))
        .map(div => div.textContent.trim());

    try {
        const resp = await fetch('/api/session/approve', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                dtxsid: currentIdentity.dtxsid,
                identity: currentIdentity,
                section_type: 'background',
                data: {
                    paragraphs,
                    references,
                    // Include originals so the server can detect edits
                    // and extract writing style rules from the diff
                    original_paragraphs: currentResult?.originalParagraphs || [],
                    original_references: currentResult?.originalReferences || [],
                    model_used: currentResult?.model_used || '',
                    notes: currentResult?.notes || [],
                },
            }),
        });

        if (!resp.ok) {
            const err = await resp.json();
            showError(err.error || 'Approve failed');
            return;
        }

        const result = await resp.json();

        // Lock the section — make paragraphs and references non-editable,
        // add green "approved" border
        backgroundApproved = true;
        lockSection(document.getElementById('output-section'));
        hide('btn-approve-bg');
        show('btn-edit-bg');

        const badge = document.getElementById('badge-bg');
        badge.style.display = '';

        // If the user edited the text, show a blue "Approved (edited)"
        // badge and a toast indicating style learning is in progress
        if (result.user_edited) {
            badge.textContent = 'Approved (edited)';
            badge.classList.add('edited');
            showToast('Approved — learning from your edits...');
            // Reload style profile after a short delay (extraction
            // runs asynchronously on the server)
            setTimeout(() => loadStyleProfile(), 3000);
        } else {
            badge.textContent = 'Approved';
            badge.classList.remove('edited');
            showToast('Background approved');
        }

        updateExportButton();

        // Show version history button with the server-assigned version number
        showVersionHistory('background', result.version);

        // Show the Materials and Methods section now that background
        // is approved — it appears between Background and Results
        showMethodsSection();

        // Also show the Summary section — it synthesizes all sections
        showSummarySection();

    } catch (err) {
        showError('Approve error: ' + err.message);
    }
}

/**
 * Try Again on background: unapprove the section on the server,
 * then regenerate a fresh background.  The old approved content
 * is replaced by the new generation.
 */
async function retryBackground() {
    if (currentIdentity?.dtxsid) {
        // Tell the server to delete the saved background section
        try {
            await fetch('/api/session/unapprove', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    dtxsid: currentIdentity.dtxsid,
                    section_type: 'background',
                }),
            });
        } catch (_) {
            // Non-critical — we'll regenerate regardless
        }
    }

    // Reset approval state and unlock the section for editing
    backgroundApproved = false;
    unlockSection(document.getElementById('output-section'));
    show('btn-approve-bg');
    hide('badge-bg');

    // Hide version history — regenerating from scratch
    hideVersionHistory('background');

    updateExportButton();

    // Regenerate fresh content
    generateBackground();
}

/**
 * Edit the background section: unlock paragraphs and references
 * for editing, remove the approved state, and re-show the Approve
 * button so the user can re-approve after making changes.
 *
 * This does NOT unapprove on the server — the user can edit and
 * then re-approve, which will detect any differences from the
 * original LLM output and trigger style learning.
 */
function editBackground() {
    // Unlock the section — re-enable editing on paragraphs and references
    backgroundApproved = false;
    unlockSection(document.getElementById('output-section'));

    // Show Approve button again, hide badge
    show('btn-approve-bg');
    hide('badge-bg');

    updateExportButton();
    showToast('Editing enabled — click Approve when done');
}

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
        section_title: document.getElementById(`bm2-title-${bm2Id}`)?.value?.trim() || '',
        table_caption: document.getElementById(`bm2-caption-${bm2Id}`)?.value?.trim() || '',
        compound_name: document.getElementById(`bm2-compound-${bm2Id}`)?.value?.trim() || '',
        dose_unit: document.getElementById(`bm2-unit-${bm2Id}`)?.value?.trim() || 'mg/kg',
        narrative,
        tables_json: info.tableData || {},
        // Include original narrative so the server can detect edits
        // and learn writing style preferences from the diff
        original_narrative: info.originalNarrative || '',
    };

    try {
        const resp = await fetch('/api/session/approve', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                dtxsid: currentIdentity.dtxsid,
                identity: currentIdentity,
                section_type: 'bm2',
                data,
            }),
        });

        if (!resp.ok) {
            const err = await resp.json();
            showError(err.error || 'Approve failed');
            return;
        }

        const result = await resp.json();

        // Lock the card — make fields and narrative readonly, add green border
        info.approved = true;
        const card = document.getElementById(`bm2-card-${bm2Id}`);
        lockSection(card);
        hide(`btn-approve-${bm2Id}`);
        show(`btn-edit-${bm2Id}`);

        const badge = document.getElementById(`badge-${bm2Id}`);
        badge.style.display = '';

        // If the user edited the narrative, show blue "Approved (edited)"
        // badge and trigger style profile reload after extraction completes
        if (result.user_edited) {
            badge.textContent = 'Approved (edited)';
            badge.classList.add('edited');
            showToast(`${info.filename} approved — learning from your edits...`);
            setTimeout(() => loadStyleProfile(), 3000);
        } else {
            badge.textContent = 'Approved';
            badge.classList.remove('edited');
            showToast(`${info.filename} approved`);
        }

        updateExportButton();

        // Show version history button with the server-assigned version number
        showVersionHistory('bm2', result.version, bm2Id);

        // After approving a .bm2 section, load the BMD summary table.
        // This auto-derives LOEL/NOEL from all approved apical sections.
        loadBmdSummary();

    } catch (err) {
        showError('Approve error: ' + err.message);
    }
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

    // Show Process button, hide Approve / Try Again / badge
    show(`btn-process-${bm2Id}`);
    document.getElementById(`btn-process-${bm2Id}`).disabled = false;
    document.getElementById(`btn-process-${bm2Id}`).textContent = 'Process';
    hide(`btn-edit-${bm2Id}`);
    hide(`btn-approve-${bm2Id}`);
    hide(`btn-retry-${bm2Id}`);
    hide(`badge-${bm2Id}`);

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
    const card = document.getElementById(`bm2-card-${bm2Id}`);
    unlockSection(card);

    // Show Approve button again, hide badge
    show(`btn-approve-${bm2Id}`);
    hide(`badge-${bm2Id}`);

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
 * Version history — browse and restore past approved versions.
 *
 * Each approved section gets a "v3 ▾" button next to its badge.
 * Clicking it opens a dropdown listing all versions with timestamps.
 * Users can preview old versions or restore them (creating a new
 * version with the old content — non-destructive).
 * ================================================================ */

/**
 * Get the section key that the server uses for a given section.
 * For background it's always "background".  For bm2 it's "bm2_{slug}"
 * derived from the filename stored in apicalSections.
 *
 * @param {string} sectionType — "background" or "bm2"
 * @param {string} [bm2Id]     — the bm2 card ID (only for bm2 sections)
 * @returns {string} the section key for the server API
 */
function getSectionKey(sectionType, bm2Id) {
    if (sectionType === 'background') return 'background';
    const info = apicalSections[bm2Id];
    if (!info) return '';
    return 'bm2_' + bm2Slug(info.filename);
}

/**
 * Get the DOM element ID prefix for version history elements.
 * Background uses "bg", bm2 uses the bm2Id directly.
 *
 * @param {string} sectionType — "background" or "bm2"
 * @param {string} [bm2Id]     — the bm2 card ID
 * @returns {string} the suffix used in element IDs
 */
function getVersionElId(sectionType, bm2Id) {
    return sectionType === 'background' ? 'bg' : bm2Id;
}

/**
 * Toggle the version history dropdown open/close.
 * Clicking the "v3 ▾" button opens the dropdown and fetches the
 * version list from the server.  Clicking again closes it.
 *
 * @param {string} sectionType — "background" or "bm2"
 * @param {string} [bm2Id]     — the bm2 card ID (for bm2 sections)
 */
function toggleVersionHistory(sectionType, bm2Id) {
    const elId = getVersionElId(sectionType, bm2Id);
    const dropdown = document.getElementById(`version-dropdown-${elId}`);
    if (!dropdown) return;

    if (dropdown.style.display === 'none') {
        // Close any other open dropdowns first
        document.querySelectorAll('.version-dropdown').forEach(d => d.style.display = 'none');
        dropdown.style.display = '';
        loadVersionHistory(sectionType, bm2Id);
    } else {
        dropdown.style.display = 'none';
    }
}

/**
 * Fetch the version list from the server and render it in the dropdown.
 * Each row shows "vN  <timestamp>  (current)" or a [Restore] button.
 *
 * @param {string} sectionType — "background" or "bm2"
 * @param {string} [bm2Id]     — the bm2 card ID (for bm2 sections)
 */
async function loadVersionHistory(sectionType, bm2Id) {
    const dtxsid = currentIdentity?.dtxsid;
    if (!dtxsid) return;

    const sectionKey = getSectionKey(sectionType, bm2Id);
    const elId = getVersionElId(sectionType, bm2Id);
    const dropdown = document.getElementById(`version-dropdown-${elId}`);
    if (!dropdown) return;

    try {
        const resp = await fetch(`/api/session/${dtxsid}/history/${sectionKey}`);
        if (!resp.ok) {
            dropdown.innerHTML = '<div style="padding:0.5rem;color:#6c757d;font-size:0.8rem">No history available</div>';
            return;
        }
        const data = await resp.json();
        const versions = data.versions || [];

        if (versions.length <= 1) {
            // Only one version — no history to show
            dropdown.innerHTML = '<div style="padding:0.5rem;color:#6c757d;font-size:0.8rem">No previous versions</div>';
            return;
        }

        // Render version list in reverse order (newest first)
        let html = '';
        for (let i = versions.length - 1; i >= 0; i--) {
            const v = versions[i];
            const ts = v.approved_at ? formatTimestamp(v.approved_at) : '—';
            const isCurrent = v.is_current;
            const cls = isCurrent ? 'version-item current' : 'version-item';

            html += `<div class="${cls}" onclick="previewVersion('${sectionType}', ${v.version}, '${bm2Id || ''}')">`;
            html += `<span>v${v.version} &nbsp; ${ts}</span>`;
            if (isCurrent) {
                html += '<span style="color:#22c55e;font-size:0.7rem">(current)</span>';
            } else {
                // Stop-propagation so clicking Restore doesn't also trigger preview
                html += `<button class="version-restore-btn" onclick="event.stopPropagation(); restoreVersion('${sectionType}', ${v.version}, '${bm2Id || ''}')">Restore</button>`;
            }
            html += '</div>';
        }
        dropdown.innerHTML = html;

    } catch (err) {
        dropdown.innerHTML = '<div style="padding:0.5rem;color:#dc3545;font-size:0.8rem">Failed to load history</div>';
    }
}

/**
 * Format an ISO timestamp into a short human-readable string.
 * e.g. "2026-03-02T19:23:59.123456+00:00" → "Mar 2, 7:23 PM"
 *
 * @param {string} isoStr — ISO 8601 timestamp
 * @returns {string} formatted date/time
 */
function formatTimestamp(isoStr) {
    try {
        const d = new Date(isoStr);
        return d.toLocaleString(undefined, {
            month: 'short', day: 'numeric',
            hour: 'numeric', minute: '2-digit',
        });
    } catch {
        return isoStr;
    }
}

/**
 * Preview a specific past version's content in the UI.
 *
 * Fetches the full version data from the server, then replaces
 * the displayed content with that version's text.  Shows a yellow
 * "Previewing v1" banner so the user knows they're looking at
 * an old version, not the current one.
 *
 * For background: replaces paragraphs and references.
 * For bm2: replaces the narrative textarea content.
 *
 * @param {string} sectionType — "background" or "bm2"
 * @param {number} version     — the version number to preview
 * @param {string} [bm2Id]     — the bm2 card ID (for bm2 sections)
 */
async function previewVersion(sectionType, version, bm2Id) {
    const dtxsid = currentIdentity?.dtxsid;
    if (!dtxsid) return;

    const sectionKey = getSectionKey(sectionType, bm2Id);
    const elId = getVersionElId(sectionType, bm2Id);

    try {
        const resp = await fetch(`/api/session/${dtxsid}/history/${sectionKey}?version=${version}`);
        if (!resp.ok) {
            showError('Failed to load version ' + version);
            return;
        }
        const data = await resp.json();

        // Close the dropdown
        const dropdown = document.getElementById(`version-dropdown-${elId}`);
        if (dropdown) dropdown.style.display = 'none';

        if (sectionType === 'background') {
            // --- Preview background version ---
            const proseEl = document.getElementById('output-prose');
            const refsEl = document.getElementById('references-list');

            // Remove existing preview banner if any
            const existingBanner = document.getElementById('version-preview-banner-bg');
            if (existingBanner) existingBanner.remove();

            // Check if this is the current version — if so, just reload current
            if (data.version && data.version === parseInt(document.getElementById('version-num-bg')?.textContent)) {
                // Restore current — reload from the latest approved data
                await reloadCurrentBackground();
                return;
            }

            // Show preview banner above the prose
            const banner = document.createElement('div');
            banner.className = 'version-preview-banner';
            banner.id = 'version-preview-banner-bg';
            banner.innerHTML = `
                <span>Previewing <strong>v${data.version || version}</strong> — this is not the current version</span>
                <button onclick="reloadCurrentBackground()">Back to current</button>
            `;
            proseEl.parentNode.insertBefore(banner, proseEl);

            // Replace displayed paragraphs with the preview version
            const paragraphs = data.paragraphs || [];
            proseEl.innerHTML = paragraphs.map(p =>
                `<div class="paragraph">${p}</div>`
            ).join('');
            // Replace references
            const references = data.references || [];
            refsEl.innerHTML = references.map(r =>
                `<div>${r}</div>`
            ).join('');

        } else if (sectionType === 'bm2' && bm2Id) {
            // --- Preview bm2 version ---
            const narrativeEl = document.getElementById(`bm2-narrative-${bm2Id}`);

            // Remove existing preview banner if any
            const existingBanner = document.getElementById(`version-preview-banner-${bm2Id}`);
            if (existingBanner) existingBanner.remove();

            // Check if this is the current version
            const currentVNum = document.getElementById(`version-num-${bm2Id}`)?.textContent;
            if (data.version && data.version === parseInt(currentVNum)) {
                await reloadCurrentBm2(bm2Id);
                return;
            }

            // Show preview banner above the narrative
            if (narrativeEl) {
                const banner = document.createElement('div');
                banner.className = 'version-preview-banner';
                banner.id = `version-preview-banner-${bm2Id}`;
                banner.innerHTML = `
                    <span>Previewing <strong>v${data.version || version}</strong> — this is not the current version</span>
                    <button onclick="reloadCurrentBm2('${bm2Id}')">Back to current</button>
                `;
                narrativeEl.parentNode.insertBefore(banner, narrativeEl);

                // Replace narrative content with the preview version
                narrativeEl.value = data.narrative || '';
                autoResizeTextarea(narrativeEl);
            }
        }

    } catch (err) {
        showError('Preview error: ' + err.message);
    }
}

/**
 * Reload the current (latest) background version from the server,
 * removing any preview banner.  Called when the user clicks "Back to
 * current" in the preview banner or clicks the (current) row in the
 * version dropdown.
 */
async function reloadCurrentBackground() {
    const banner = document.getElementById('version-preview-banner-bg');
    if (banner) banner.remove();

    const dtxsid = currentIdentity?.dtxsid;
    if (!dtxsid) return;

    try {
        // Fetch the full session to get the current background
        const resp = await fetch(`/api/session/${dtxsid}`);
        if (!resp.ok) return;
        const session = await resp.json();
        if (session.background) {
            const bg = session.background;
            const proseEl = document.getElementById('output-prose');
            const refsEl = document.getElementById('references-list');
            proseEl.innerHTML = (bg.paragraphs || []).map(p =>
                `<div class="paragraph">${p}</div>`
            ).join('');
            refsEl.innerHTML = (bg.references || []).map(r =>
                `<div>${r}</div>`
            ).join('');
        }
    } catch (_) {
        // Silent fail — the user can always refresh the page
    }
}

/**
 * Reload the current (latest) bm2 narrative from the server,
 * removing any preview banner.
 *
 * @param {string} bm2Id — the bm2 card ID
 */
async function reloadCurrentBm2(bm2Id) {
    const banner = document.getElementById(`version-preview-banner-${bm2Id}`);
    if (banner) banner.remove();

    const dtxsid = currentIdentity?.dtxsid;
    if (!dtxsid) return;

    const info = apicalSections[bm2Id];
    if (!info) return;
    const slug = bm2Slug(info.filename);

    try {
        const resp = await fetch(`/api/session/${dtxsid}`);
        if (!resp.ok) return;
        const session = await resp.json();
        const section = session.bm2_sections?.[slug];
        if (section) {
            const narrativeEl = document.getElementById(`bm2-narrative-${bm2Id}`);
            if (narrativeEl) {
                narrativeEl.value = section.narrative || '';
                autoResizeTextarea(narrativeEl);
            }
        }
    } catch (_) {
        // Silent fail
    }
}

/**
 * Restore a past version by sending a POST to the server.
 *
 * This creates a NEW version with the old version's content (non-destructive).
 * After restoration, the UI reloads the section content and updates
 * the version button to show the new version number.
 *
 * @param {string} sectionType — "background" or "bm2"
 * @param {number} version     — the version number to restore
 * @param {string} [bm2Id]     — the bm2 card ID (for bm2 sections)
 */
async function restoreVersion(sectionType, version, bm2Id) {
    const dtxsid = currentIdentity?.dtxsid;
    if (!dtxsid) return;

    const sectionKey = getSectionKey(sectionType, bm2Id);
    const elId = getVersionElId(sectionType, bm2Id);

    try {
        const resp = await fetch(`/api/session/${dtxsid}/restore`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ section_key: sectionKey, version }),
        });

        if (!resp.ok) {
            const err = await resp.json();
            showError(err.error || 'Restore failed');
            return;
        }

        const result = await resp.json();
        const newVersion = result.version;

        // Update the version number display
        const versionNumEl = document.getElementById(`version-num-${elId}`);
        if (versionNumEl) versionNumEl.textContent = newVersion;

        // Close dropdown
        const dropdown = document.getElementById(`version-dropdown-${elId}`);
        if (dropdown) dropdown.style.display = 'none';

        // Remove any preview banner
        const banner = document.getElementById(`version-preview-banner-${elId === 'bg' ? 'bg' : bm2Id}`);
        if (banner) banner.remove();

        // Reload the section content from the server so the UI
        // shows the restored version's text
        if (sectionType === 'background') {
            await reloadCurrentBackground();
        } else if (sectionType === 'bm2' && bm2Id) {
            await reloadCurrentBm2(bm2Id);
        }

        showToast(`Restored v${version} as v${newVersion}`);

    } catch (err) {
        showError('Restore error: ' + err.message);
    }
}

/**
 * Show the version history button for a section after it's been approved.
 * Updates the version number display and makes the button visible.
 *
 * @param {string} sectionType — "background" or "bm2"
 * @param {number} version     — the current version number
 * @param {string} [bm2Id]     — the bm2 card ID (for bm2 sections)
 */
function showVersionHistory(sectionType, version, bm2Id) {
    const elId = getVersionElId(sectionType, bm2Id);
    const container = document.getElementById(`version-history-${elId}`);
    const versionNum = document.getElementById(`version-num-${elId}`);
    if (container) container.style.display = '';
    if (versionNum) versionNum.textContent = version || 1;
}

/**
 * Hide the version history button for a section (e.g. when retrying).
 *
 * @param {string} sectionType — "background" or "bm2"
 * @param {string} [bm2Id]     — the bm2 card ID (for bm2 sections)
 */
function hideVersionHistory(sectionType, bm2Id) {
    const elId = getVersionElId(sectionType, bm2Id);
    const container = document.getElementById(`version-history-${elId}`);
    if (container) container.style.display = 'none';
    // Also close any open dropdown
    const dropdown = document.getElementById(`version-dropdown-${elId}`);
    if (dropdown) dropdown.style.display = 'none';
    // Remove any preview banner
    const bannerId = sectionType === 'background' ? 'version-preview-banner-bg' : `version-preview-banner-${bm2Id}`;
    const banner = document.getElementById(bannerId);
    if (banner) banner.remove();
}

/* ================================================================
 * Export gating — only enable Export when all sections are approved
 * ================================================================ */

/**
 * Enable the Export .docx button only when:
 *   1. The background section is approved
 *   2. Every processed .bm2 file is also approved
 *
 * Called on every approval state change (approve, unapprove, retry,
 * new generation, session restore).
 */
function updateExportButton() {
    const btn = document.getElementById('btn-export');
    if (!btn) return;

    // Background must be approved
    if (!backgroundApproved) {
        btn.disabled = true;
        btn.title = 'Approve the background section first';
        return;
    }

    // At least one results section must be approved (apical or genomics)
    const processedBm2 = Object.values(apicalSections).filter(f => f.processed);
    const anyBm2Approved = processedBm2.some(f => f.approved);
    const anyGenomicsApproved = Object.values(genomicsResults).some(r => r.approved);

    if (!anyBm2Approved && !anyGenomicsApproved) {
        btn.disabled = true;
        btn.title = 'Approve at least one results section (apical or genomics)';
        return;
    }

    // All processed .bm2 files must be approved (can't export partial)
    const allBm2Approved = processedBm2.every(f => f.approved);
    if (!allBm2Approved) {
        btn.disabled = true;
        btn.title = 'Approve all processed .bm2 sections first';
        return;
    }

    btn.disabled = false;
    btn.title = '';
}

/* ================================================================
 * Session auto-restore — load saved session when DTXSID resolves
 * ================================================================ */

/**
 * Restore a previously-saved session from the server.
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
        // file pool, and section builder via displayResult)
        displayResult(fakeResult);

        // Now lock it as approved — disable editing and add green border
        backgroundApproved = true;
        lockSection(document.getElementById('output-section'));
        hide('btn-approve-bg');
        show('btn-edit-bg');
        show('btn-retry-bg');
        show('badge-bg');

        // Show version history with the version from the saved data
        showVersionHistory('background', bg.version || 1);
    }

    // --- Restore .bm2 sections ---
    // For each saved bm2 section: create a synthetic uploadedFiles entry
    // (type='bm2', restored: true), render a greyed file pool item,
    // create an apicalSections entry, and create the result card.
    if (data.bm2_sections && Object.keys(data.bm2_sections).length > 0) {
        // Show the file pool, animal report, section builder, and results section
        show('file-pool-section');
    
        show('section-builder');
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

            // Hide Process button, show badge + Edit + Try Again
            hide(`btn-process-${sectionId}`);
            hide(`btn-approve-${sectionId}`);
            show(`btn-edit-${sectionId}`);
            show(`btn-retry-${sectionId}`);
            show(`badge-${sectionId}`);

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
        // Make sure the file pool, animal report, and section builder are visible
        // so the user can assign pending files to report sections.
        show('file-pool-section');
    
        show('section-builder');

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
        hide('btn-approve-methods');
        show('btn-edit-methods');
        show('btn-retry-methods');
        show('badge-methods');
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
            hide('btn-approve-bmd-summary');
            show('badge-bmd-summary');
        }
    }

    // --- Restore Genomics sections ---
    // For each saved genomics section: create a synthetic uploadedFiles
    // entry (type='csv', restored: true), render a greyed file pool item,
    // create a genomicsResults entry, and create the results card.
    if (data.genomics_sections && Object.keys(data.genomics_sections).length > 0) {
        show('file-pool-section');
    
        show('section-builder');
        show('genomics-results-section');

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

            // Create the card and lock it as approved
            createGenomicsCard(key, section, organ, sex);
            const card = document.getElementById(`genomics-card-${key}`);
            if (card) {
                lockSection(card);
                hide(`btn-approve-genomics-${key}`);
                show(`btn-edit-genomics-${key}`);
                show(`btn-retry-genomics-${key}`);
                show(`badge-genomics-${key}`);
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
        hide('btn-approve-summary');
        show('btn-edit-summary');
        show('btn-retry-summary');
        show('badge-summary');
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
        hide('btn-approve-pool');
        show('badge-pool');
    }

    updateExportButton();

    // Rebuild the tab bar so any newly-revealed sections get tabs
    if (tabbedViewActive) buildTabBar();

    const name = data.meta?.name || data.identity?.name || currentIdentity?.dtxsid;
    showToast(`Restored session for ${name}`);
}

/* ================================================================
 * Style profile management — load, display, and delete learned
 * writing style rules
 * ================================================================ */

/**
 * Load the global style profile from the server and render it.
 *
 * Called on page init (to show existing rules) and after each
 * approve-with-edits (to show newly learned rules).  If no rules
 * exist, the panel is hidden.
 */
async function loadStyleProfile() {
    try {
        const resp = await fetch('/api/style-profile');
        if (!resp.ok) return;

        const profile = await resp.json();
        const rules = profile.rules || [];

        renderStyleRules(rules);
    } catch (_) {
        // Non-critical — style panel just won't show
    }
}

/**
 * Delete a style rule by its index in the rules array.
 *
 * Calls DELETE /api/style-profile/{idx} and re-renders the panel
 * with the updated profile returned by the server.
 *
 * @param {number} idx — 0-based index of the rule to delete
 */
async function deleteStyleRule(idx) {
    try {
        const resp = await fetch(`/api/style-profile/${idx}`, {
            method: 'DELETE',
        });
        if (!resp.ok) {
            const err = await resp.json();
            showError(err.error || 'Failed to delete rule');
            return;
        }

        const profile = await resp.json();
        renderStyleRules(profile.rules || []);
        showToast('Style rule removed');
    } catch (err) {
        showError('Delete error: ' + err.message);
    }
}

/**
 * Render the style rules list in the style panel.
 *
 * Each rule is displayed as a row with: a colored category badge,
 * the rule text, a confidence indicator (number of times the rule
 * was reinforced by repeated edits), and a delete (x) button.
 *
 * The panel is shown/hidden based on whether any rules exist.
 *
 * @param {Array} rules — array of rule objects from the style profile
 */
function renderStyleRules(rules) {
    const panel = document.getElementById('style-panel');
    const countEl = document.getElementById('style-count');
    const listEl = document.getElementById('style-rules-list');

    if (!rules || rules.length === 0) {
        panel.style.display = 'none';
        return;
    }

    panel.style.display = '';
    if (tabbedViewActive) buildTabBar();
    countEl.textContent = `(${rules.length} rule${rules.length !== 1 ? 's' : ''})`;

    listEl.innerHTML = '';
    rules.forEach((rule, idx) => {
        const row = document.createElement('div');
        row.className = 'style-rule';

        // Category badge — colored pill showing the rule type
        const cat = document.createElement('span');
        cat.className = `style-category ${rule.category || 'phrasing'}`;
        cat.textContent = rule.category || 'phrasing';

        // Rule text
        const text = document.createElement('span');
        text.className = 'style-rule-text';
        text.textContent = rule.rule;

        // Confidence indicator — shows reinforcement count
        const conf = document.createElement('span');
        conf.className = 'style-confidence';
        const c = rule.confidence || 1;
        conf.textContent = c > 1 ? `×${c}` : '';
        conf.title = c > 1
            ? `Reinforced ${c} times`
            : 'Seen once';

        // Delete button
        const del = document.createElement('button');
        del.className = 'style-delete';
        del.textContent = '×';
        del.title = 'Remove this rule';
        del.onclick = () => deleteStyleRule(idx);

        row.appendChild(cat);
        row.appendChild(text);
        row.appendChild(conf);
        row.appendChild(del);
        listEl.appendChild(row);
    });
}

/**
 * Toggle visibility of the style rules detail list.
 * The panel header is always visible when rules exist; this
 * controls the expandable list underneath.
 */
function toggleStyleDetails() {
    const details = document.getElementById('style-details');
    details.style.display = details.style.display === 'none' ? '' : 'none';
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
        // If a DTXSID was restored, auto-resolve to load the session.
        // Await so errors propagate (previously fire-and-forget meant
        // resolve failures were silently swallowed).
        const dtxsid = data['dtxsid'];
        if (dtxsid && dtxsid.startsWith('DTXSID')) {
            await onFieldBlur('dtxsid');
        }
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
restoreChemId();

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


/* ================================================================
 * NEW NIEHS SECTIONS — Materials & Methods, Genomics, BMD Summary, Summary
 * ================================================================
 * These functions implement the new report sections that expand the
 * 5dToxReport to match the full NIEHS report structure.
 */

/* ----------------------------------------------------------------
 * Materials and Methods section
 * ---------------------------------------------------------------- */

/**
 * Show the Materials and Methods section (called after background
 * is approved, so the user can generate M&M next).
 */
function showMethodsSection() {
    show('methods-section');
    document.getElementById('methods-section').classList.add('visible');
    if (tabbedViewActive) buildTabBar();
}

/**
 * Generate Materials and Methods via the LLM.
 * Extracts study params from the first .bm2 file's dose groups.
 */
async function generateMethods() {
    const btn = document.getElementById('btn-generate-methods');
    btn.disabled = true;
    btn.textContent = 'Generating...';

    try {
        // Send identity and study params to the server.
        // The server extracts dose groups, sample sizes, endpoints, and BMDExpress
        // metadata from the file pool fingerprints and .bm2 caches automatically.
        const resp = await fetch('/api/generate-methods', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                identity: currentIdentity,
                study_params: {
                    vehicle: 'corn oil',
                    route: 'gavage',
                    duration_days: 5,
                    species: 'Sprague Dawley',
                },
                animal_report: animalReportData,
            }),
        });
        const result = await resp.json();

        if (result.error) {
            showError(result.error);
            return;
        }

        // Store structured methods data (sections + context + table1)
        methodsData = result;

        // Render structured subsections with headings
        displayMethodsSections(result.sections, result.table1);

        // Show approve/edit buttons
        btn.style.display = 'none';
        show('btn-approve-methods');
        show('btn-retry-methods');

    } catch (e) {
        showError('Methods generation failed: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Generate';
    }
}


/**
 * Render structured M&M subsections into the methods-prose container.
 *
 * Each subsection gets:
 *   - A styled heading (<h3> or <h4>) — not editable
 *   - Editable prose paragraphs in contenteditable divs (reuses .paragraph class)
 *   - Optional Table 1 as an HTML table (read-only, data-derived)
 *
 * The data-key attribute on each subsection div enables extractMethodsSections()
 * to reassemble the edited text into the structured format for approval/export.
 *
 * @param {Array} sections - Array of {heading, level, key, paragraphs, table} objects
 * @param {Object|null} table1 - Optional Table 1 data: {caption, headers, rows, footnotes}
 */
/**
 * Preview the extracted MethodsContext data in the file preview modal.
 *
 * Fetches the context from /api/methods-context/{dtxsid} (no LLM call —
 * just data extraction from fingerprints, animal report, and .bm2 caches)
 * and renders it as a collapsible JSON tree in the existing preview modal.
 *
 * This lets the user verify what study parameters the system extracted
 * before generating the M&M prose.
 */
async function previewMethodsContext() {
    const dtxsid = currentIdentity?.dtxsid;
    if (!dtxsid) {
        showError('DTXSID required to preview methods context');
        return;
    }

    // Reuse the file preview modal
    const badge = document.getElementById('modal-badge');
    badge.textContent = 'M&M';
    badge.className = 'file-badge bm2';

    document.getElementById('modal-title').textContent = 'Methods Context — Extracted Study Data';

    const body = document.getElementById('modal-body');
    body.innerHTML = '<div class="modal-loading"><div class="spinner"></div>Extracting context\u2026</div>';

    document.getElementById('file-preview-modal').style.display = 'flex';

    // Bind Escape to close
    _previewEscapeHandler = (e) => {
        if (e.key === 'Escape') closePreviewModal();
    };
    document.addEventListener('keydown', _previewEscapeHandler);

    try {
        const resp = await fetch(`/api/methods-context/${dtxsid}`);
        if (!resp.ok) throw new Error(`Server returned ${resp.status}`);
        const data = await resp.json();

        body.innerHTML = '';
        renderJsonTree(data, body, 0, 3);
    } catch (err) {
        body.innerHTML = `
            <div class="modal-info-card">
                <div class="info-icon">\u26a0\ufe0f</div>
                <div class="info-text">Failed to load context: ${err.message}</div>
            </div>`;
    }
}


function displayMethodsSections(sections, table1) {
    const container = document.getElementById('methods-prose');
    container.innerHTML = '';

    for (const section of sections) {
        // Create a wrapper div for this subsection
        const wrapper = document.createElement('div');
        wrapper.className = 'methods-subsection';
        wrapper.dataset.key = section.key;

        // Add heading (h3 for level 3, h4 for level 4)
        const headingTag = section.level <= 3 ? 'h3' : 'h4';
        const heading = document.createElement(headingTag);
        heading.className = 'methods-heading';
        heading.textContent = section.heading;
        wrapper.appendChild(heading);

        // Add editable paragraphs
        for (const para of (section.paragraphs || [])) {
            const div = document.createElement('div');
            div.className = 'paragraph';
            div.contentEditable = 'true';
            div.textContent = para;
            wrapper.appendChild(div);
        }

        container.appendChild(wrapper);
    }

    // Append Table 1 at the end if present
    if (table1 && table1.headers && table1.rows) {
        const tableWrapper = document.createElement('div');
        tableWrapper.className = 'methods-table1-wrapper';

        // Caption
        const caption = document.createElement('p');
        caption.className = 'methods-table-caption';
        caption.textContent = `Table 1. ${table1.caption || ''}`;
        tableWrapper.appendChild(caption);

        // Build HTML table
        const tbl = document.createElement('table');
        tbl.className = 'methods-table1';

        // Header row
        const thead = document.createElement('thead');
        const headerRow = document.createElement('tr');
        for (const h of table1.headers) {
            const th = document.createElement('th');
            th.textContent = h;
            headerRow.appendChild(th);
        }
        thead.appendChild(headerRow);
        tbl.appendChild(thead);

        // Data rows
        const tbody = document.createElement('tbody');
        for (const row of table1.rows) {
            const tr = document.createElement('tr');
            for (let i = 0; i < row.length; i++) {
                const td = document.createElement('td');
                const val = row[i];
                // Bold sex-header rows (marked with ** in the data)
                const isBold = typeof val === 'string' && val.startsWith('**') && val.endsWith('**');
                td.textContent = isBold ? val.replace(/\*\*/g, '').trim() : val;
                if (isBold) {
                    td.classList.add('sex-header');
                    tr.classList.add('sex-header-row');
                }
                tr.appendChild(td);
            }
            tbody.appendChild(tr);
        }
        tbl.appendChild(tbody);
        tableWrapper.appendChild(tbl);

        // Footnotes
        if (table1.footnotes && table1.footnotes.length > 0) {
            for (const fn of table1.footnotes) {
                const fnP = document.createElement('p');
                fnP.className = 'methods-table-footnote';
                fnP.textContent = fn;
                tableWrapper.appendChild(fnP);
            }
        }

        container.appendChild(tableWrapper);
    }
}


/**
 * Extract edited methods subsections from the DOM.
 *
 * Reads the contenteditable paragraphs from each .methods-subsection div
 * and reassembles them into the structured format that matches the server's
 * MethodsSection schema.
 *
 * @returns {Array} Array of {heading, level, key, paragraphs} objects
 */
function extractMethodsSections() {
    const container = document.getElementById('methods-prose');
    const sections = [];
    for (const wrapper of container.querySelectorAll('.methods-subsection')) {
        const key = wrapper.dataset.key;
        const headingEl = wrapper.querySelector('.methods-heading');
        const heading = headingEl ? headingEl.textContent.trim() : '';
        const level = headingEl && headingEl.tagName === 'H4' ? 4 : 3;
        const paragraphs = Array.from(wrapper.querySelectorAll('.paragraph'))
            .map(p => p.textContent.trim())
            .filter(Boolean);
        sections.push({ heading, level, key, paragraphs });
    }
    return sections;
}

/**
 * Enable editing on a locked methods section.
 */
function editMethods() {
    methodsApproved = false;
    unlockSection(document.getElementById('methods-section'));
    hide('btn-edit-methods');
    show('btn-approve-methods');
    hide('badge-methods');
    updateExportButton();
}

/**
 * Retry methods generation — clear and re-show the generate button.
 */
function retryMethods() {
    methodsApproved = false;
    methodsData = null;
    unlockSection(document.getElementById('methods-section'));
    document.getElementById('methods-prose').innerHTML = '';
    show('btn-generate-methods');
    hide('btn-approve-methods');
    hide('btn-retry-methods');
    hide('btn-edit-methods');
    hide('badge-methods');
    updateExportButton();
}

/* ----------------------------------------------------------------
 * Summary section
 * ---------------------------------------------------------------- */

/**
 * Show the Summary section (available once background + at least
 * one results section is approved).
 */
function showSummarySection() {
    show('summary-section');
    document.getElementById('summary-section').classList.add('visible');
    if (tabbedViewActive) buildTabBar();
}

/**
 * Generate Summary via the LLM — synthesizes all approved sections.
 */
async function generateSummary() {
    if (!currentIdentity?.dtxsid) {
        showError('DTXSID required to generate summary');
        return;
    }

    const btn = document.getElementById('btn-generate-summary');
    btn.disabled = true;
    btn.textContent = 'Generating...';

    try {
        const resp = await fetch('/api/generate-summary', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                dtxsid: currentIdentity.dtxsid,
                identity: currentIdentity,
            }),
        });
        const result = await resp.json();

        if (result.error) {
            showError(result.error);
            return;
        }

        summaryParagraphs = result.paragraphs;
        displayProse('summary-prose', result.paragraphs);

        btn.style.display = 'none';
        show('btn-approve-summary');
        show('btn-retry-summary');

    } catch (e) {
        showError('Summary generation failed: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Generate';
    }
}

function editSummary() {
    summaryApproved = false;
    unlockSection(document.getElementById('summary-section'));
    hide('btn-edit-summary');
    show('btn-approve-summary');
    hide('badge-summary');
    updateExportButton();
}

function retrySummary() {
    summaryApproved = false;
    unlockSection(document.getElementById('summary-section'));
    document.getElementById('summary-prose').innerHTML = '';
    show('btn-generate-summary');
    hide('btn-approve-summary');
    hide('btn-retry-summary');
    hide('btn-edit-summary');
    hide('badge-summary');
    updateExportButton();
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

    const btn = document.getElementById('btn-approve-pool');
    btn.disabled = true;
    btn.textContent = 'Generating report...';

    try {
        const resp = await fetch(
            `/api/generate-animal-report/${currentIdentity.dtxsid}`,
            { method: 'POST' },
        );
        const result = await resp.json();

        if (result.error) {
            showError(result.error);
            return;
        }

        animalReportData = result;
        animalReportApproved = true;
        renderAnimalReport(result);

        // Hide Approve button, show badge
        hide('btn-approve-pool');
        show('badge-pool');

        showToast('Pool approved — animal report generated');
        updateExportButton();

    } catch (e) {
        showError('Animal report generation failed: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Approve';
    }
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

    // Shared domain label lookup
    const domainFullLabels = {
        body_weight: 'Body Weight', organ_weights: 'Organ Weights',
        clin_chem: 'Clinical Chemistry', hematology: 'Hematology',
        hormones: 'Hormones', tissue_conc: 'Tissue Concentration',
        clinical_obs: 'Clinical Observations', gene_expression: 'Gene Expression',
    };

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
    const nDomains = Object.keys(report.domain_coverage || {}).length;
    html += `<div class="ar-summary">`;
    html += `<strong>${study}</strong> · ${report.total_animals} animals${selDetail} · `;
    html += `${report.dose_groups?.length || 0} dose groups · ${nDomains} assay domains`;
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
        tbl += `<tr><th>Domain</th><th>xlsx</th><th>txt/csv</th><th>bm2</th><th>Dropped</th><th>Completeness</th></tr>`;

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

        // Count domains at 100% vs those with attrition
        const fullDomains = Object.values(report.completeness || {}).filter(c => c >= 1.0).length;
        const partialDomains = nDomains - fullDomains;
        const coverageSummary = partialDomains > 0
            ? `${fullDomains} complete, ${partialDomains} with attrition`
            : `all ${nDomains} domains complete`;

        html += collapse('coverage',
            `<strong>Domain Coverage</strong> — ${nDomains} domains, ${coverageSummary}`,
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
                `<strong>Attrition Detail</strong> — ${totalExclusions} animals excluded across domains`,
                body);
        }
    }

    // --- D. Animal Roster (full per-animal table, collapsed by default) ---
    if (report.animals && Object.keys(report.animals).length > 0) {
        const domainOrder = [
            'body_weight', 'organ_weights', 'clin_chem', 'hematology',
            'hormones', 'tissue_conc', 'clinical_obs', 'gene_expression',
        ];
        const domainShort = {
            body_weight: 'BW', organ_weights: 'OW', clin_chem: 'CC',
            hematology: 'Hem', hormones: 'Horm', tissue_conc: 'TC',
            clinical_obs: 'CO', gene_expression: 'GE',
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
 * Genomics CSV upload and processing
 * ---------------------------------------------------------------- */

/* (Old CSV upload handlers, createCsvCard, removeCsvCard deleted —
   CSV uploads now go through the unified file pool.) */

/**
 * Process a CSV file through the genomics pipeline.
 *
 * Called from addAndProcessSection() with organ and sex from the
 * section builder form.  Uses the file's server-side ID from the
 * uploadedFiles pool.  Creates gene set and gene ranking tables.
 *
 * @param {string} fileId — the file pool ID (key in uploadedFiles)
 * @param {string} organ  — organ name from the section builder
 * @param {string} sex    — sex from the section builder
 */
async function processCsv(fileId, organ, sex) {
    // Look up the server-side CSV ID from the upload pool
    const file = uploadedFiles[fileId];
    const serverCsvId = file?.id || fileId;

    // Disable the Add & Process button while processing
    const addBtn = document.getElementById('btn-add-section');
    addBtn.disabled = true;
    addBtn.textContent = 'Processing...';

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
        createGenomicsCard(key, result, organ, sex);

        // Show genomics results section
        show('genomics-results-section');
        if (tabbedViewActive) buildTabBar();

        // Also show the summary section now that we have genomics
        showSummarySection();

    } catch (e) {
        showError('Genomics processing failed: ' + e.message);
    } finally {
        addBtn.disabled = false;
        addBtn.textContent = 'Add & Process';
    }
}

/**
 * Create a card showing the genomics analysis results for one
 * organ × sex combination.  Displays the top 10 gene sets and
 * top 10 genes as HTML tables with approve/retry buttons.
 */
function createGenomicsCard(key, data, organ, sex) {
    const cardsDiv = document.getElementById('genomics-cards');

    // Remove existing card for same key if re-processing
    const existing = document.getElementById(`genomics-card-${key}`);
    if (existing) existing.remove();

    const card = document.createElement('div');
    card.className = 'bm2-card';
    card.id = `genomics-card-${key}`;

    const organTitle = organ.charAt(0).toUpperCase() + organ.slice(1);
    const sexTitle = sex.charAt(0).toUpperCase() + sex.slice(1);

    // Build gene sets table HTML
    let geneSetHtml = '';
    if (data.gene_sets && data.gene_sets.length > 0) {
        geneSetHtml = `
            <h4>Top Gene Sets (by BMD)</h4>
            <table>
                <tr><th>GO Term</th><th>GO ID</th><th>BMD Median</th>
                    <th>BMDL Median</th><th># Genes</th><th>Direction</th></tr>
                ${data.gene_sets.map(gs => `
                    <tr>
                        <td>${gs.go_term}</td>
                        <td>${gs.go_id}</td>
                        <td class="bmd-col">${gs.bmd_median?.toFixed(3) || '—'}</td>
                        <td class="bmd-col">${gs.bmdl_median?.toFixed(3) || '—'}</td>
                        <td>${gs.n_genes}</td>
                        <td>${gs.direction}</td>
                    </tr>
                `).join('')}
            </table>
        `;
    } else {
        geneSetHtml = '<p style="color:#6c757d; font-size:0.85rem">No qualifying gene sets found.</p>';
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
                        <td class="endpoint-label">${g.gene_symbol}</td>
                        <td class="bmd-col">${g.bmd?.toFixed(3) || '—'}</td>
                        <td class="bmd-col">${g.bmdl?.toFixed(3) || '—'}</td>
                        <td>${g.fold_change?.toFixed(2) || '—'}</td>
                        <td>${g.direction}</td>
                    </tr>
                `).join('')}
            </table>
        `;
    } else {
        genesHtml = '<p style="color:#6c757d; font-size:0.85rem">No qualifying genes found.</p>';
    }

    card.innerHTML = `
        <div class="card-header">
            <span class="filename">${organTitle} — ${sexTitle}
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
        <div class="table-preview">
            ${geneSetHtml}
            ${genesHtml}
        </div>
    `;
    cardsDiv.appendChild(card);
}

/**
 * Approve a genomics card — sends data to the server.
 */
async function approveGenomics(key) {
    if (!currentIdentity?.dtxsid) {
        showError('DTXSID required to approve');
        return;
    }
    const data = genomicsResults[key];
    if (!data) return;

    try {
        const resp = await fetch('/api/session/approve', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                dtxsid: currentIdentity.dtxsid,
                identity: currentIdentity,
                section_type: 'genomics',
                data: {
                    organ: data.organ,
                    sex: data.sex,
                    gene_sets: data.gene_sets,
                    top_genes: data.top_genes,
                    total_responsive_genes: data.total_responsive_genes,
                    csv_id: data.fileId ? (uploadedFiles[data.fileId]?.id || data.fileId) : data.csv_id,
                },
            }),
        });
        const result = await resp.json();
        if (result.ok) {
            genomicsResults[key].approved = true;
            const card = document.getElementById(`genomics-card-${key}`);
            lockSection(card);
            hide(`btn-approve-genomics-${key}`);
            show(`btn-edit-genomics-${key}`);
            show(`btn-retry-genomics-${key}`);
            show(`badge-genomics-${key}`);
            updateExportButton();
        }
    } catch (e) {
        showError('Approve failed: ' + e.message);
    }
}

function editGenomics(key) {
    genomicsResults[key].approved = false;
    const card = document.getElementById(`genomics-card-${key}`);
    unlockSection(card);
    show(`btn-approve-genomics-${key}`);
    hide(`btn-edit-genomics-${key}`);
    hide(`badge-genomics-${key}`);
    updateExportButton();
}

function retryGenomics(key) {
    // Remove the card — user needs to re-process the CSV
    const card = document.getElementById(`genomics-card-${key}`);
    if (card) card.remove();
    delete genomicsResults[key];
    updateExportButton();
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
    if (!currentIdentity?.dtxsid) {
        showError('DTXSID required to approve');
        return;
    }

    let data = {};

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
    } else if (sectionType === 'bmd_summary') {
        data = { endpoints: bmdSummaryEndpoints };
    } else if (sectionType === 'summary') {
        data = {
            paragraphs: extractProse('summary-prose'),
            original_paragraphs: summaryParagraphs,
        };
    }

    try {
        const resp = await fetch('/api/session/approve', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                dtxsid: currentIdentity.dtxsid,
                identity: currentIdentity,
                section_type: sectionType,
                data: data,
            }),
        });
        const result = await resp.json();

        if (result.ok) {
            // Lock the section UI — disable editing and add green border
            if (sectionType === 'methods') {
                methodsApproved = true;
                lockSection(document.getElementById('methods-section'));
                hide('btn-approve-methods');
                show('btn-edit-methods');
                show('btn-retry-methods');
                show('badge-methods');
            } else if (sectionType === 'bmd_summary') {
                bmdSummaryApproved = true;
                lockSection(document.getElementById('bmd-summary-section'));
                hide('btn-approve-bmd-summary');
                show('badge-bmd-summary');
            } else if (sectionType === 'summary') {
                summaryApproved = true;
                lockSection(document.getElementById('summary-section'));
                hide('btn-approve-summary');
                show('btn-edit-summary');
                show('btn-retry-summary');
                show('badge-summary');
            }

            if (result.user_edited) {
                showToast('Approved (style learning triggered)');
            } else {
                showToast('Section approved');
            }
            updateExportButton();
        }
    } catch (e) {
        showError('Approve failed: ' + e.message);
    }
}

/* ----------------------------------------------------------------
 * File preview modal — open/close + content renderers
 * ----------------------------------------------------------------
 * The modal lets users inspect uploaded files before assigning
 * them to report sections.  Content rendering varies by file type:
 *   - .bm2 (processed): collapsible JSON tree of tables_json
 *   - .bm2 (unprocessed): info message prompting processing
 *   - .csv/.txt: scrollable HTML table (first 50 rows)
 *   - .xlsx: file metadata (name + size)
 * ---------------------------------------------------------------- */

/**
 * Reference to the Escape key handler so we can add/remove it
 * when the modal opens/closes (avoids stale listeners).
 */

/**
 * Open the file preview modal and fetch preview data from the server.
 *
 * Steps:
 *   1. Look up the file in uploadedFiles for metadata (filename, type)
 *   2. Set the modal header (badge + title)
 *   3. Show a loading spinner in the body
 *   4. Display the modal (flex layout)
 *   5. Fetch GET /api/preview/{fileId}
 *   6. Render the response based on its `type` field
 *   7. Bind Escape key to close
 *
 * @param {string} fileId — key in the uploadedFiles object
 */
function openPreviewModal(fileId) {
    const file = uploadedFiles[fileId];
    if (!file) return;

    // Set header badge — reuse the same type-based badge classes
    const badge = document.getElementById('modal-badge');
    const badgeLabels = { bm2: '.bm2', csv: '.csv', txt: '.txt', xlsx: '.xlsx' };
    badge.textContent = badgeLabels[file.type] || `.${file.type}`;
    badge.className = `file-badge ${file.type}`;

    // Set title to the filename
    document.getElementById('modal-title').textContent = file.filename;

    // Show loading spinner while we fetch
    const body = document.getElementById('modal-body');
    body.innerHTML = '<div class="modal-loading"><div class="spinner"></div>Loading preview\u2026</div>';

    // Show the modal
    document.getElementById('file-preview-modal').style.display = 'flex';

    // Bind Escape key to close the modal
    _previewEscapeHandler = (e) => {
        if (e.key === 'Escape') closePreviewModal();
    };
    document.addEventListener('keydown', _previewEscapeHandler);

    // Restored files don't exist on the server (their IDs are synthetic
    // client-side keys like "file-restored-bm2-*").  Instead of hitting
    // the server and getting a 404, render their data directly from the
    // client-side section state (apicalSections / genomicsResults).
    if (file.restored) {
        _renderRestoredPreview(fileId, file, body);
        return;
    }

    // Non-restored files: fetch preview data from the server
    fetch(`/api/preview/${fileId}`)
        .then(res => {
            if (!res.ok) throw new Error(`Server returned ${res.status}`);
            return res.json();
        })
        .then(data => {
            _renderPreviewResponse(data, body);
        })
        .catch(err => {
            body.innerHTML = `
                <div class="modal-info-card">
                    <div class="info-icon">\u26a0\ufe0f</div>
                    <div class="info-text">Failed to load preview: ${err.message}</div>
                </div>`;
        });
}

/**
 * Render the server response into the modal body.
 *
 * Shared by the server-fetch path (non-restored files) and could
 * also be reused if we later add other preview sources.
 *
 * @param {Object}      data — the JSON response from /api/preview
 * @param {HTMLElement}  body — the #modal-body element
 */
function _renderPreviewResponse(data, body) {
    body.innerHTML = '';

    switch (data.type) {
        case 'bm2_json':
            // Processed .bm2 — render a collapsible JSON tree
            renderJsonTree(data.data, body);
            break;

        case 'bm2_raw':
            // Unprocessed .bm2 — show an info card
            body.innerHTML = `
                <div class="modal-info-card">
                    <div class="info-icon">\u2699\ufe0f</div>
                    <div class="info-text">${data.message}</div>
                </div>`;
            break;

        case 'table':
            // CSV/TXT — render as a scrollable HTML table
            renderModalTablePreview(data, body);
            break;

        case 'xlsx_table':
            // XLSX — render sheet tabs (if multiple) + table preview
            renderXlsxPreview(data, body);
            break;

        case 'info':
            // XLSX or fallback — show file metadata
            let sizeText = '';
            if (data.size_bytes != null) {
                const kb = (data.size_bytes / 1024).toFixed(1);
                sizeText = `<div class="info-size">${kb} KB</div>`;
            }
            const msg = data.message || `Binary file \u2014 preview not available.`;
            body.innerHTML = `
                <div class="modal-info-card">
                    <div class="info-icon">\ud83d\udcc4</div>
                    <div class="info-text">${msg}</div>
                    ${sizeText}
                </div>`;
            break;

        default:
            body.innerHTML = `
                <div class="modal-info-card">
                    <div class="info-text">Unknown file type.</div>
                </div>`;
    }
}

/**
 * Render a preview for a restored file using client-side data.
 *
 * Restored files were loaded from a saved session — their temp files
 * no longer exist on the server, so we can't fetch /api/preview.
 * Instead, we pull the data from the client-side state objects:
 *   - apicalSections: for .bm2 files (has tableData + narrative)
 *   - genomicsResults: for .csv gene-level BMD files
 *
 * @param {string}      fileId — the synthetic file pool ID
 * @param {Object}      file   — the uploadedFiles entry
 * @param {HTMLElement}  body   — the #modal-body element
 */
function _renderRestoredPreview(fileId, file, body) {
    body.innerHTML = '';

    if (file.type === 'bm2') {
        // Find the apicalSections entry that references this fileId.
        // The section was registered during session restore with
        // { fileId, tableData, narrative, processed, approved }.
        const section = Object.values(apicalSections).find(
            s => s.fileId === fileId
        );

        if (section && section.tableData && Object.keys(section.tableData).length > 0) {
            // Render the tables_json as a collapsible JSON tree —
            // same as the server's "bm2_json" response path
            renderJsonTree({
                tables_json: section.tableData,
                narrative: section.narrative || [],
            }, body);
        } else {
            body.innerHTML = `
                <div class="modal-info-card">
                    <div class="info-icon">\u2699\ufe0f</div>
                    <div class="info-text">
                        This .bm2 file was loaded from a saved session.
                        Table data is not available for preview.
                    </div>
                </div>`;
        }
        return;
    }

    if (file.type === 'csv') {
        // Find the genomicsResults entry that references this fileId.
        // The section has gene_sets, genes, organ, sex, etc.
        const result = Object.values(genomicsResults).find(
            r => r.fileId === fileId
        );

        if (result) {
            // Show the genomics result data as a JSON tree
            const previewData = {};
            if (result.organ) previewData.organ = result.organ;
            if (result.sex) previewData.sex = result.sex;
            if (result.gene_sets) previewData.gene_sets = result.gene_sets;
            if (result.genes) previewData.genes = result.genes;
            renderJsonTree(previewData, body);
        } else {
            body.innerHTML = `
                <div class="modal-info-card">
                    <div class="info-icon">\ud83d\udcc4</div>
                    <div class="info-text">
                        This CSV file was loaded from a saved session.
                        Raw data is not available for preview.
                    </div>
                </div>`;
        }
        return;
    }

    // Fallback for other restored file types (.txt, .xlsx)
    body.innerHTML = `
        <div class="modal-info-card">
            <div class="info-icon">\ud83d\udcc4</div>
            <div class="info-text">
                This file was loaded from a saved session.
                Preview is not available.
            </div>
        </div>`;
}

/**
 * Close the file preview modal.
 *
 * Hides the modal, clears the body (to avoid stale content on
 * next open), and removes the Escape key listener.
 */
function closePreviewModal() {
    hide('file-preview-modal');
    document.getElementById('modal-body').innerHTML = '';

    // Remove the Escape key listener to avoid accumulating handlers
    if (_previewEscapeHandler) {
        document.removeEventListener('keydown', _previewEscapeHandler);
        _previewEscapeHandler = null;
    }
}

/**
 * Render a collapsible, navigable JSON tree inside a container element.
 *
 * Recursively walks the data structure (objects, arrays, primitives)
 * and builds DOM nodes with expand/collapse toggles.  Objects and
 * arrays expand to show their children; primitives render inline
 * with type-specific color coding (green strings, blue numbers, etc.).
 *
 * Expand behavior:
 *   - Nodes at depth < maxExpandDepth start expanded
 *   - Large arrays (>20 items) start collapsed regardless of depth
 *   - Collapsed nodes show a count badge: "{3 keys}" or "[5 items]"
 *
 * @param {*}           data            — the JSON data to render
 * @param {HTMLElement} container       — DOM element to append the tree into
 * @param {number}      [depth=0]       — current nesting depth (for indentation)
 * @param {number}      [maxExpandDepth=2] — auto-expand nodes shallower than this
 */
function renderJsonTree(data, container, depth, maxExpandDepth) {
    if (depth == null) depth = 0;
    if (maxExpandDepth == null) maxExpandDepth = 2;

    // Wrap the entire tree in a .json-tree container at the root level
    const wrapper = depth === 0
        ? (() => { const d = document.createElement('div'); d.className = 'json-tree'; container.appendChild(d); return d; })()
        : container;

    // Indentation: 1.2rem per depth level
    const indent = (depth * 1.2) + 'rem';

    if (data === null || data === undefined) {
        // Null / undefined — render as a gray "null" span
        const line = document.createElement('div');
        line.className = 'json-line';
        line.style.paddingLeft = indent;
        line.innerHTML = '<span class="json-null">null</span>';
        wrapper.appendChild(line);

    } else if (Array.isArray(data)) {
        // Array — collapsible with indexed children
        const count = data.length;
        // Start collapsed if past max depth or if the array is large (>20 items)
        const startCollapsed = depth >= maxExpandDepth || count > 20;

        // Opening bracket line with toggle
        const toggleLine = document.createElement('div');
        toggleLine.className = 'json-line';
        toggleLine.style.paddingLeft = indent;

        const toggle = document.createElement('span');
        toggle.className = 'json-toggle' + (startCollapsed ? ' collapsed' : '');
        toggle.innerHTML = '<span class="json-bracket">[</span>';
        toggleLine.appendChild(toggle);

        // Count badge — visible when collapsed
        const countBadge = document.createElement('span');
        countBadge.className = 'json-count';
        countBadge.textContent = `${count} item${count !== 1 ? 's' : ''}`;
        countBadge.style.display = startCollapsed ? 'inline' : 'none';
        toggleLine.appendChild(countBadge);

        // Closing bracket inline when collapsed
        const closingInline = document.createElement('span');
        closingInline.className = 'json-bracket';
        closingInline.textContent = ']';
        closingInline.style.display = startCollapsed ? 'inline' : 'none';
        toggleLine.appendChild(closingInline);

        wrapper.appendChild(toggleLine);

        // Children container
        const children = document.createElement('div');
        children.className = 'json-children' + (startCollapsed ? ' collapsed' : '');

        // Render each array element recursively
        for (let i = 0; i < count; i++) {
            const itemLine = document.createElement('div');
            itemLine.className = 'json-line';
            itemLine.style.paddingLeft = ((depth + 1) * 1.2) + 'rem';

            // Show index as a dim label, plus the object's name field
            // (if it has one) so users can identify array members at a
            // glance — e.g. "0: ClinChemFemale" instead of just "0:"
            const indexLabel = document.createElement('span');
            indexLabel.className = 'json-key';
            indexLabel.style.opacity = '0.5';
            const elem = data[i];
            const elemName = (elem && typeof elem === 'object' && !Array.isArray(elem))
                ? elem.name || elem.Name || ''
                : '';
            indexLabel.textContent = elemName
                ? i + ': ' + elemName + ' '
                : i + ': ';
            itemLine.appendChild(indexLabel);

            // Primitive values render inline; objects/arrays recurse
            if (data[i] !== null && typeof data[i] === 'object') {
                children.appendChild(itemLine);
                renderJsonTree(data[i], children, depth + 1, maxExpandDepth);
            } else {
                itemLine.appendChild(_jsonValueSpan(data[i]));
                children.appendChild(itemLine);
            }
        }

        wrapper.appendChild(children);

        // Closing bracket on its own line (visible when expanded)
        const closingLine = document.createElement('div');
        closingLine.className = 'json-line';
        closingLine.style.paddingLeft = indent;
        closingLine.innerHTML = '<span class="json-bracket">]</span>';
        closingLine.style.display = startCollapsed ? 'none' : '';
        wrapper.appendChild(closingLine);

        // Toggle click handler — expands/collapses children + swaps badges
        toggle.onclick = () => {
            const isCollapsed = toggle.classList.toggle('collapsed');
            children.classList.toggle('collapsed', isCollapsed);
            countBadge.style.display = isCollapsed ? 'inline' : 'none';
            closingInline.style.display = isCollapsed ? 'inline' : 'none';
            closingLine.style.display = isCollapsed ? 'none' : '';
        };

    } else if (typeof data === 'object') {
        // Object — collapsible with key-value children
        const keys = Object.keys(data);
        const count = keys.length;
        const startCollapsed = depth >= maxExpandDepth;

        // Opening brace with toggle
        const toggleLine = document.createElement('div');
        toggleLine.className = 'json-line';
        toggleLine.style.paddingLeft = indent;

        const toggle = document.createElement('span');
        toggle.className = 'json-toggle' + (startCollapsed ? ' collapsed' : '');
        toggle.innerHTML = '<span class="json-bracket">{</span>';
        toggleLine.appendChild(toggle);

        const countBadge = document.createElement('span');
        countBadge.className = 'json-count';
        countBadge.textContent = `${count} key${count !== 1 ? 's' : ''}`;
        countBadge.style.display = startCollapsed ? 'inline' : 'none';
        toggleLine.appendChild(countBadge);

        const closingInline = document.createElement('span');
        closingInline.className = 'json-bracket';
        closingInline.textContent = '}';
        closingInline.style.display = startCollapsed ? 'inline' : 'none';
        toggleLine.appendChild(closingInline);

        wrapper.appendChild(toggleLine);

        // Children container
        const children = document.createElement('div');
        children.className = 'json-children' + (startCollapsed ? ' collapsed' : '');

        for (const key of keys) {
            const val = data[key];
            const itemLine = document.createElement('div');
            itemLine.className = 'json-line';
            itemLine.style.paddingLeft = ((depth + 1) * 1.2) + 'rem';

            const keySpan = document.createElement('span');
            keySpan.className = 'json-key';
            keySpan.textContent = key + ': ';
            itemLine.appendChild(keySpan);

            // Primitive values render inline; objects/arrays recurse
            if (val !== null && typeof val === 'object') {
                children.appendChild(itemLine);
                renderJsonTree(val, children, depth + 1, maxExpandDepth);
            } else {
                itemLine.appendChild(_jsonValueSpan(val));
                children.appendChild(itemLine);
            }
        }

        wrapper.appendChild(children);

        // Closing brace line
        const closingLine = document.createElement('div');
        closingLine.className = 'json-line';
        closingLine.style.paddingLeft = indent;
        closingLine.innerHTML = '<span class="json-bracket">}</span>';
        closingLine.style.display = startCollapsed ? 'none' : '';
        wrapper.appendChild(closingLine);

        toggle.onclick = () => {
            const isCollapsed = toggle.classList.toggle('collapsed');
            children.classList.toggle('collapsed', isCollapsed);
            countBadge.style.display = isCollapsed ? 'inline' : 'none';
            closingInline.style.display = isCollapsed ? 'inline' : 'none';
            closingLine.style.display = isCollapsed ? 'none' : '';
        };

    } else {
        // Primitive value (string, number, boolean) at the top level
        const line = document.createElement('div');
        line.className = 'json-line';
        line.style.paddingLeft = indent;
        line.appendChild(_jsonValueSpan(data));
        wrapper.appendChild(line);
    }
}

/**
 * Create a colored <span> for a JSON primitive value.
 *
 * Applies type-specific CSS classes so strings appear green,
 * numbers blue, booleans orange, and null gray.  String values
 * are quoted to match standard JSON display.
 *
 * @param {*} val — a primitive JSON value (string, number, bool, null)
 * @returns {HTMLSpanElement} — the styled span element
 */
function _jsonValueSpan(val) {
    const span = document.createElement('span');
    if (typeof val === 'string') {
        span.className = 'json-string';
        // Truncate very long strings to keep the tree readable
        const display = val.length > 120 ? val.slice(0, 120) + '\u2026' : val;
        span.textContent = `"${display}"`;
    } else if (typeof val === 'number') {
        span.className = 'json-number';
        span.textContent = String(val);
    } else if (typeof val === 'boolean') {
        span.className = 'json-bool';
        span.textContent = String(val);
    } else {
        span.className = 'json-null';
        span.textContent = 'null';
    }
    return span;
}

/**
 * Render a tabular data preview inside the modal body.
 *
 * Builds an HTML table from headers + rows arrays returned by the
 * /api/preview endpoint for .csv and .txt files.  The table reuses
 * the existing .table-preview CSS class.  If only a subset of rows
 * is shown (total_rows > rows.length), a footer note is appended.
 *
 * Named "renderModalTablePreview" to avoid colliding with the
 * existing "renderTablePreview" function (which renders BM2
 * apical endpoint tables in the section builder cards).
 *
 * @param {Object}      data      — { headers, rows, total_rows, filename }
 * @param {HTMLElement}  container — the modal body element to render into
 */
function renderModalTablePreview(data, container) {
    const wrapper = document.createElement('div');
    wrapper.className = 'table-preview';

    const table = document.createElement('table');

    // Header row — column names from the first line of the file
    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    for (const h of data.headers) {
        const th = document.createElement('th');
        th.textContent = h;
        headerRow.appendChild(th);
    }
    thead.appendChild(headerRow);
    table.appendChild(thead);

    // Data rows — up to 50 rows from the server
    const tbody = document.createElement('tbody');
    for (const row of data.rows) {
        const tr = document.createElement('tr');
        for (let i = 0; i < row.length; i++) {
            const td = document.createElement('td');
            td.textContent = row[i];
            // First column is the endpoint/row label — make it sticky
            if (i === 0) td.className = 'endpoint-label';
            tr.appendChild(td);
        }
        tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    wrapper.appendChild(table);
    container.appendChild(wrapper);

    // Footer showing row count if we're only showing a subset
    if (data.total_rows > data.rows.length) {
        const footer = document.createElement('div');
        footer.className = 'modal-table-footer';
        footer.textContent = `Showing ${data.rows.length} of ${data.total_rows} rows`;
        container.appendChild(footer);
    }
}

/**
 * renderXlsxPreview — Renders an xlsx file preview with sheet tabs.
 *
 * If the workbook has a single sheet, it delegates directly to
 * renderModalTablePreview.  For multi-sheet workbooks, a horizontal
 * tab bar is rendered above the table so the user can switch sheets.
 *
 * @param {Object}      data      — { sheets: [{ name, headers, rows, total_rows }] }
 * @param {HTMLElement}  container — the modal body element to render into
 */
function renderXlsxPreview(data, container) {
    const sheets = data.sheets || [];
    if (sheets.length === 0) {
        container.innerHTML = `
            <div class="modal-info-card">
                <div class="info-text">No sheets found in this workbook.</div>
            </div>`;
        return;
    }

    // Single sheet — skip the tab bar entirely
    if (sheets.length === 1) {
        renderModalTablePreview(sheets[0], container);
        return;
    }

    // Multi-sheet — create a tab bar and a content area
    const tabBar = document.createElement('div');
    tabBar.className = 'xlsx-sheet-tabs';

    const contentArea = document.createElement('div');
    contentArea.className = 'xlsx-sheet-content';

    /**
     * switchSheet — swaps the visible table to the sheet at `index`.
     * Updates the active tab highlight and re-renders the table.
     */
    function switchSheet(index) {
        // Update active tab styling
        tabBar.querySelectorAll('button').forEach((btn, i) => {
            btn.classList.toggle('active', i === index);
        });
        // Clear previous table and render the selected sheet
        contentArea.innerHTML = '';
        renderModalTablePreview(sheets[index], contentArea);
    }

    // Build one tab button per worksheet
    sheets.forEach((sheet, i) => {
        const btn = document.createElement('button');
        btn.textContent = sheet.name;
        btn.addEventListener('click', () => switchSheet(i));
        tabBar.appendChild(btn);
    });

    container.appendChild(tabBar);
    container.appendChild(contentArea);

    // Show the first sheet by default
    switchSheet(0);
}

/* (displayProse moved to utils.js)
   (Old MutationObserver that showed #genomics-upload-section deleted —
   the unified file pool + section builder are shown directly by
   displayResult() when background generation completes.) */

