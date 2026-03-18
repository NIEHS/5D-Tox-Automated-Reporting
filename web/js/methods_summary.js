/* -----------------------------------------------------------------
 * methods_summary.js — Materials & Methods and Summary sections
 *
 * Split from sections.js.  Handles generation, display, editing,
 * and approval for both the Materials and Methods section (structured
 * subsections with Table 1) and the Summary section (synthesized
 * prose from all approved sections).
 *
 * Also contains the integrated data preview modal (previewIntegratedData)
 * and the methods context preview modal (previewMethodsContext) since
 * these are part of the M&M workflow.
 *
 * Depends on: state.js (globals), utils.js (helpers), export.js,
 *             versions.js
 * ----------------------------------------------------------------- */

/* ----------------------------------------------------------------
 * Materials and Methods section
 * ---------------------------------------------------------------- */

/**
 * Show the Materials and Methods section (called after background
 * is approved, so the user can generate M&M next).
 */
function showMethodsSection() {
    // Set the Alpine store flag so the Methods section becomes visible
    if (typeof Alpine !== 'undefined' && Alpine.store('app')) {
        Alpine.store('app').ready.methods = true;
    }
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
    // Set the Alpine store flag so the Summary section becomes visible
    if (typeof Alpine !== 'undefined' && Alpine.store('app')) {
        Alpine.store('app').ready.summary = true;
    }
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
