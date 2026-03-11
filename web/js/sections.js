/* -----------------------------------------------------------------
 * sections.js — Report section generation, approval, and workflows
 *
 * Implements the generate → display → edit → approve lifecycle for
 * all report sections: Background, Materials & Methods, Apical
 * Endpoints (BM2), BMD Summary, Summary, and the Animal Report.
 * Also handles the integrated processing pipeline that creates
 * section cards from fingerprint data after pool approval.
 *
 * Depends on: state.js (globals), utils.js (helpers), export.js,
 *             genomics.js, filepool.js, versions.js
 * ----------------------------------------------------------------- */

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

                // Wrap each JSON.parse in try-catch so one malformed SSE
                // event doesn't crash the entire stream parser.
                try {
                    if (eventType === 'progress') {
                        const data = JSON.parse(eventData);
                        addProgressLog(data.message);
                    } else if (eventType === 'complete') {
                        currentResult = JSON.parse(eventData);
                        displayResult(currentResult);
                        hideProgress();
                        markReportDirty();
                    } else if (eventType === 'error') {
                        const data = JSON.parse(eventData);
                        showError(data.error);
                        hideProgress();
                    }
                } catch (parseErr) {
                    console.error('SSE parse error:', parseErr, 'raw:', eventData);
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
    setButtons('bg', 'result');

    // Reset approval state — new generation means unapproved
    backgroundApproved = false;
    unlockSection(document.getElementById('output-section'));

    // Show the data tab now that background is done
    show('data-tab-section');
    if (tabbedViewActive) buildTabBar();

    // Generating background also confirms identity — enable
    // Process/Export buttons if they were still disabled
    onIdentityResolved();

    // Update export button state (background is now unapproved)
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
    // Collect current editable text (user may have polished it)
    const refsEl = document.getElementById('references-list');
    const paragraphs = extractProse('output-prose');
    const references = Array.from(refsEl.querySelectorAll('div'))
        .map(div => div.textContent.trim());

    const result = await postApproveToServer(
        'background',
        document.getElementById('output-section'),
        'bg',
        {
            paragraphs,
            references,
            // Include originals so the server can detect edits
            // and extract writing style rules from the diff
            original_paragraphs: currentResult?.originalParagraphs || [],
            original_references: currentResult?.originalReferences || [],
            model_used: currentResult?.model_used || '',
            notes: currentResult?.notes || [],
        },
    );
    if (!result) return;

    backgroundApproved = true;

    // If the user edited the text, show a blue "Approved (edited)"
    // badge and a toast indicating style learning is in progress
    const badge = document.getElementById('badge-bg');
    if (result.user_edited) {
        badge.textContent = 'Approved (edited)';
        badge.classList.add('edited');
        // Reload style profile after a short delay (extraction
        // runs asynchronously on the server)
        setTimeout(() => loadStyleProfile(), 3000);
    } else {
        badge.textContent = 'Approved';
        badge.classList.remove('edited');
    }

    // Show version history button with the server-assigned version number
    showVersionHistory('background', result.version);

    // Show the Materials and Methods section now that background
    // is approved — it appears between Background and Results
    showMethodsSection();

    // Also show the Summary section — it synthesizes all sections
    showSummarySection();
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
    markReportDirty();
    unlockSection(document.getElementById('output-section'));
    setButtons('bg', 'editing');

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
    markReportDirty();
    unlockSection(document.getElementById('output-section'));
    setButtons('bg', 'editing');
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

    showBlockingSpinner('Generating methods...');
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
        markReportDirty();

        // Show approve/retry buttons (hide Generate)
        btn.style.display = 'none';
        setButtons('methods', 'result');

    } catch (e) {
        showError('Methods generation failed: ' + e.message);
    } finally {
        hideBlockingSpinner();
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


/**
 * Preview the full integrated BMDProject in the file preview modal.
 *
 * Streams the integrated JSON from GET /api/integrated/{dtxsid} using
 * Oboe.js for progressive parsing.  Each top-level key is rendered as
 * a collapsible sub-tree as soon as it arrives, so the user sees
 * progress instead of waiting for the full ~68 MB payload.
 * Falls back to standard fetch if Oboe.js is not loaded.
 */
async function previewIntegratedData() {
    const dtxsid = currentIdentity?.dtxsid;
    if (!dtxsid) {
        showError('DTXSID required to preview integrated data');
        return;
    }

    const badge = document.getElementById('modal-badge');
    badge.textContent = 'DATA';
    badge.className = 'file-badge bm2';

    document.getElementById('modal-title').textContent = 'Integrated BMDProject — Full Data Tree';

    const body = document.getElementById('modal-body');
    body.innerHTML = '<div class="modal-loading"><div class="spinner"></div>Streaming integrated data\u2026</div>';

    document.getElementById('file-preview-modal').style.display = 'flex';

    _previewEscapeHandler = (e) => {
        if (e.key === 'Escape') closePreviewModal();
    };
    document.addEventListener('keydown', _previewEscapeHandler);

    // Oboe uses XMLHttpRequest (not fetch), so the fetch interceptor
    // doesn't apply — append ?user= manually for the user gate.
    const _user = getStoredUser();
    const url = `/api/integrated/${dtxsid}` + (_user ? `?user=${encodeURIComponent(_user)}` : '');

    // -- Oboe streaming path --
    // Uses Oboe.js to incrementally parse the JSON response.  For each
    // top-level key we append a labeled sub-tree to the modal body as
    // soon as its value is fully parsed — gives the user progressive
    // feedback instead of a single long wait.
    if (typeof oboe === 'function') {
        // Wrapper div that will receive the .json-tree class
        const treeRoot = document.createElement('div');
        treeRoot.className = 'json-tree';

        // Opening brace line — mirrors renderJsonTree's object rendering
        const openLine = document.createElement('div');
        openLine.className = 'json-line';
        openLine.innerHTML = '<span class="json-bracket">{</span>';
        treeRoot.appendChild(openLine);

        // Container for the key-value children (always expanded at root)
        const childrenDiv = document.createElement('div');
        childrenDiv.className = 'json-children';
        treeRoot.appendChild(childrenDiv);

        // Closing brace — appended when the stream finishes
        const closeLine = document.createElement('div');
        closeLine.className = 'json-line';
        closeLine.innerHTML = '<span class="json-bracket">}</span>';

        // Track how many keys we've received
        let keyCount = 0;

        oboe(url)
            .node('!.*', function (value, path) {
                // path is an array — for top-level keys it's a single string
                // e.g. ["doseResponseExperiments"], ["_meta"], etc.
                if (path.length !== 1) return oboe.drop;

                const key = path[0];
                keyCount++;

                // On first key, replace the spinner with the tree root
                if (keyCount === 1) {
                    body.innerHTML = '';
                    body.appendChild(treeRoot);
                }

                // Build the key label line at depth 1
                const itemLine = document.createElement('div');
                itemLine.className = 'json-line';
                itemLine.style.paddingLeft = '1.2rem';

                const keySpan = document.createElement('span');
                keySpan.className = 'json-key';
                keySpan.textContent = key + ': ';
                itemLine.appendChild(keySpan);

                // Primitives render inline; objects/arrays recurse
                if (value !== null && typeof value === 'object') {
                    childrenDiv.appendChild(itemLine);
                    renderJsonTree(value, childrenDiv, 1, 2);
                } else {
                    itemLine.appendChild(_jsonValueSpan(value));
                    childrenDiv.appendChild(itemLine);
                }

                // Tell Oboe to drop this node from memory — avoids
                // accumulating the entire 68 MB structure in RAM
                return oboe.drop;
            })
            .done(function () {
                // Stream complete — append the closing brace
                treeRoot.appendChild(closeLine);
            })
            .fail(function (err) {
                if (keyCount === 0) {
                    body.innerHTML = `
                        <div class="modal-info-card">
                            <div class="info-icon">\u26a0\ufe0f</div>
                            <div class="info-text">Failed to load integrated data: ${err.statusCode || err.thrown || 'unknown error'}</div>
                        </div>`;
                } else {
                    // Partial render — append error notice below
                    const notice = document.createElement('div');
                    notice.className = 'modal-info-card';
                    notice.innerHTML = `
                        <div class="info-icon">\u26a0\ufe0f</div>
                        <div class="info-text">Stream interrupted: ${err.statusCode || err.thrown || 'unknown error'}</div>`;
                    body.appendChild(notice);
                }
            });

        return; // Oboe handles everything asynchronously
    }

    // -- Fallback: standard fetch (no Oboe available) --
    try {
        const resp = await fetch(url);
        if (!resp.ok) throw new Error(`Server returned ${resp.status}`);
        const data = await resp.json();

        body.innerHTML = '';
        renderJsonTree(data, body, 0, 2);
    } catch (err) {
        body.innerHTML = `
            <div class="modal-info-card">
                <div class="info-icon">\u26a0\ufe0f</div>
                <div class="info-text">Failed to load integrated data: ${err.message}</div>
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

        // Build HTML table — uses buildTable() with a custom cell renderer
        // to detect **bold** sex-header rows in the data.
        const tbl = buildTable(table1.headers, table1.rows, {
            className: 'methods-table1',
            cellRenderer(val, _r, _c, td, tr) {
                // Sex-header rows are marked with ** delimiters in the data
                const isBold = typeof val === 'string' && val.startsWith('**') && val.endsWith('**');
                td.textContent = isBold ? val.replace(/\*\*/g, '').trim() : val;
                if (isBold) {
                    td.classList.add('sex-header');
                    tr.classList.add('sex-header-row');
                }
            },
        });
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
    if (!container) return [];
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
    markReportDirty();
    unlockSection(document.getElementById('methods-section'));
    setButtons('methods', 'editing');
    updateExportButton();
}

/**
 * Retry methods generation — clear and re-show the generate button.
 */
function retryMethods() {
    methodsApproved = false;
    markReportDirty();
    methodsData = null;
    unlockSection(document.getElementById('methods-section'));
    document.getElementById('methods-prose').innerHTML = '';
    show('btn-generate-methods');
    setButtons('methods', 'hidden');
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

    showBlockingSpinner('Generating summary...');
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
        markReportDirty();

        btn.style.display = 'none';
        setButtons('summary', 'result');

    } catch (e) {
        showError('Summary generation failed: ' + e.message);
    } finally {
        hideBlockingSpinner();
        btn.disabled = false;
        btn.textContent = 'Generate';
    }
}

function editSummary() {
    summaryApproved = false;
    markReportDirty();
    unlockSection(document.getElementById('summary-section'));
    setButtons('summary', 'editing');
    updateExportButton();
}

function retrySummary() {
    summaryApproved = false;
    markReportDirty();
    unlockSection(document.getElementById('summary-section'));
    document.getElementById('summary-prose').innerHTML = '';
    show('btn-generate-summary');
    setButtons('summary', 'hidden');
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

    showBlockingSpinner('Generating animal report...');
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

        setButtons('pool', 'approved');

        showToast('Pool approved — animal report generated');
        updateExportButton();

        // Auto-create and process all sections from fingerprint data.
        await autoProcessPool();

    } catch (e) {
        showError('Animal report generation failed: ' + e.message);
    } finally {
        hideBlockingSpinner();
        btn.disabled = false;
        btn.textContent = 'Approve';
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
 * For each file in `uploadedFiles`:
 *   - BM2 files with non-gene-expression domain → create an apical card
 *     (createBm2Card) with config pre-filled from fingerprint, then call
 *     processBm2() to hit the server and generate tables + narrative.
 *   - CSV/TXT files with domain "gene_expression" → call processCsv()
 *     once per sex found in the fingerprint's sexes array.
 *
 * Processing is sequential to avoid UI race conditions (each processBm2
 * and processCsv is async and manipulates shared DOM / state).
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

    showBlockingSpinner('Processing integrated data...');

    // Show the results sections so cards have a container to land in
    show('bm2-results-section');
    if (tabbedViewActive) buildTabBar();

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

            // Create a section card for each domain returned by the server
            for (const section of sections) {
                const sectionId = 'integrated-' + section.domain;

                // Skip if already created (idempotent)
                if (apicalSections[sectionId]) continue;

                // Register in state
                apicalSections[sectionId] = {
                    fileId:            null,   // not tied to a single file
                    filename:          section.title,
                    processed:         true,
                    approved:          false,
                    tableData:         section.tables_json,
                    narrative:         section.narrative,
                    originalNarrative: (section.narrative || []).join('\n\n'),
                    domain:            section.domain,
                };

                // Create the visual card and populate it
                createBm2Card(sectionId, section.title);

                // Pre-fill the dose unit and compound fields
                const unitEl = document.getElementById(`bm2-unit-${sectionId}`);
                if (unitEl) unitEl.value = doseUnit;
                const compoundEl = document.getElementById(`bm2-compound-${sectionId}`);
                if (compoundEl) compoundEl.value = compoundName;

                // Render the table data and narrative directly (no processBm2 call)
                renderBm2Results(sectionId, section.tables_json, section.narrative);
            }

            // --- Gene expression: extracted from the integrated .bm2 ---
            // The process-integrated endpoint also returns genomics_sections
            // if a gene expression .bm2 was included in the integration.
            // BMDExpress's own prefilter → curve fit → BMD pipeline already
            // ran, and we read its results directly (no CSV re-analysis).
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
                }
            }

            // --- Apical BMD summary (Table 8 equivalent) ---
            // The process-integrated endpoint now returns apical_bmd_summary
            // with BMD, BMDL, LOEL, NOEL, direction for all modeled endpoints.
            // This replaces the separate /api/bmd-summary call for apical data.
            if (result.apical_bmd_summary && result.apical_bmd_summary.length > 0) {
                bmdSummaryEndpoints = result.apical_bmd_summary;
                renderBmdSummaryTable(bmdSummaryEndpoints);
                show('bmd-summary-section');
                document.getElementById('bmd-summary-section').classList.add('visible');
                markReportDirty();
            }

            // --- BMDS summary (pybmds — EPA BMDS methodology) ---
            if (result.apical_bmd_summary_bmds && result.apical_bmd_summary_bmds.length > 0) {
                renderBmdSummaryTableBmds(result.apical_bmd_summary_bmds);
                show('bmd-summary-bmds-section');
                document.getElementById('bmd-summary-bmds-section').classList.add('visible');
                markReportDirty();
            }
        } else {
            const err = await resp.json().catch(e => { console.error('JSON parse failed:', e); return {}; });
            showToast(err.error || 'Integrated processing failed');
        }
    } catch (e) {
        showToast('Integrated processing failed: ' + e.message);
    }

    // Show the genomics section if any genomics results were created
    if (Object.keys(genomicsResults).length > 0) {
        show('genomics-results-section');
        show('genomics-charts-section');
    }

    // Show the summary section now that sections exist
    showSummarySection();

    // Rebuild tabs to include any newly-created sections
    if (tabbedViewActive) buildTabBar();
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

    // Shared domain label lookup (from state.js constant)
    const domainFullLabels = DOMAIN_LABELS;

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
