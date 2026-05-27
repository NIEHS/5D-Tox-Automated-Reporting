// export.js — Overleaf export, full-report preview, file preview modals
//
// Extracted from main.js.  These functions handle:
//   - Document export (exportDocument) — .tex bundle for Overleaf
//   - Shared payload builder (buildExportPayload)
//   - Genomics export payload assembly (buildGenomicsExportSections)
//   - Full report preview in the side pane (ensureFullPreview, scrollPreviewToNode)
//   - Export button gating (updateExportButton)
//   - Clipboard copying (copyToClipboard)
//   - File preview modal (openPreviewModal, closePreviewModal, render helpers)
//   - JSON tree renderer for preview modals (renderJsonTree, _jsonValueSpan)
//   - Table/XLSX preview renderers (renderModalTablePreview, renderXlsxPreview)
//   - Report dirty tracking (markReportDirty)
//
// Dependencies (globals from state.js):
//   currentIdentity, apicalSections, genomicsResults, methodsData,
//   methodsApproved, bmdSummaryApproved, bmdSummaryEndpoints,
//   summaryApproved, backgroundApproved, uploadedFiles,
//   animalReportApproved, animalReportData, _previewEscapeHandler,
//   currentResult, summaryParagraphs
//
// Dependencies (functions from other files):
//   extractProse, showToast, showError, show, hide, buildTable,
//   showBlockingSpinner, hideBlockingSpinner — from utils.js
//   extractMethodsSections — from sections.js
//   _bmdStatLabel — from settings.js
//   captureGenomicsChartImages — from genomics_charts.js


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
 * Genomics export helper — split each organ×sex result into typed
 * sections for the Typst template, which filters by "type" field:
 *   type: "gene_set" → Gene Set BMD Analysis tables + GO descriptions
 *   type: "gene"     → Gene BMD Analysis tables + gene descriptions
 * ================================================================ */
function buildGenomicsExportSections(entries, { onlyApproved = false } = {}) {
    const secs = [];
    for (const [, gData] of Object.entries(entries)) {
        if (onlyApproved && !gData.approved) continue;

        const hasByStatSets = gData.gene_sets_by_stat
            && Object.values(gData.gene_sets_by_stat).some(s => s.length > 0);
        const hasLegacySets = gData.gene_sets && gData.gene_sets.length > 0;

        if (!hasByStatSets && !hasLegacySets && !gData.top_genes) continue;

        // Gene set sections — one per selected statistic
        if (hasByStatSets) {
            for (const [stat, sets] of Object.entries(gData.gene_sets_by_stat)) {
                if (sets.length === 0) continue;
                secs.push({
                    type: 'gene_set',
                    organ: gData.organ,
                    sex: gData.sex,
                    bmd_stat: stat,
                    bmd_stat_label: _bmdStatLabel(stat),
                    gene_sets: sets,
                    go_descriptions: gData.go_descriptions || [],
                    gene_set_narrative: gData.gene_set_narrative || [],
                    dose_unit: 'mg/kg',
                });
            }
        } else if (hasLegacySets) {
            secs.push({
                type: 'gene_set',
                organ: gData.organ,
                sex: gData.sex,
                gene_sets: gData.gene_sets,
                go_descriptions: gData.go_descriptions || [],
                gene_set_narrative: gData.gene_set_narrative || [],
                dose_unit: 'mg/kg',
            });
        }
        // Gene section (with gene descriptions)
        if (gData.top_genes && gData.top_genes.length > 0) {
            secs.push({
                type: 'gene',
                organ: gData.organ,
                sex: gData.sex,
                top_genes: gData.top_genes,
                gene_descriptions: gData.gene_descriptions || [],
                gene_narrative: gData.gene_narrative || [],
                dose_unit: 'mg/kg',
            });
        }
    }
    return secs;
}

/* ================================================================
 * Export — build an Overleaf-ready .tex bundle (zip) for download
 * ================================================================ */

/**
 * Export the report as an Overleaf-ready zip via /api/export-overleaf-bundle.
 *
 * Collects all approved section data with buildExportPayload(), POSTs it,
 * and triggers a browser download of the .tex bundle (see the inline
 * comment below for the bundle contents).  The server reshapes the payload
 * and renders LaTeX; the author compiles the bundle on Overleaf.
 *
 * This is the single export entry point.  Additional output formats would
 * be added by routing to different endpoints on a format parameter.
 */
async function exportDocument() {
    // Export the report as an Overleaf-ready zip bundle.
    //
    // The bundle contains: report.tex (the rendered LaTeX), niehs.cls
    // (the document class), figures/ (genomics chart PDFs, when wired),
    // and README.md (Overleaf upload instructions).  The author drops
    // the zip into Overleaf's "Upload Project" page and compiles there.
    //
    // No PDF is produced by the server — the author compiles the bundle
    // on Overleaf.
    const btn = document.getElementById('btn-export');
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Generating...';
    }

    showBlockingSpinner('Building Overleaf bundle...');
    try {
        const payload = await buildExportPayload();
        const chemicalName = payload.chemical_name || 'Chemical';

        const resp = await fetch('/api/export-overleaf-bundle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ error: 'Overleaf bundle export failed' }));
            showError(err.error || 'Overleaf bundle export failed');
            return;
        }

        // Trigger browser download of the zip file
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `5dToxReport_${chemicalName.replace(/[^a-zA-Z0-9 _-]/g, '_')}_overleaf.zip`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        showToast('Downloaded Overleaf bundle — upload to overleaf.com to compile');
    } catch (err) {
        showError('Overleaf bundle export error: ' + err.message);
    } finally {
        hideBlockingSpinner();
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Export to Overleaf';
        }
    }
}


/* ================================================================
 * Export gating — only enable Export when all sections are approved
 * ================================================================ */

/**
 * Enable the Export button only when:
 *   1. The background section is approved
 *   2. At least one results section is approved
 *   3. All processed .bm2 files are approved
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

    // At least one results section must be available.  Genomics data
    // is no longer approval-gated — if genomicsResults has entries, the
    // tables are considered ready.  Apical .bm2 files still use the
    // per-file approval flow because their narratives are user-edited
    // prose, not deterministic tables.
    const processedBm2 = Object.values(apicalSections).filter(f => f.processed);
    const anyBm2Approved = processedBm2.some(f => f.approved);
    const hasGenomics = Object.keys(genomicsResults).length > 0;

    if (!anyBm2Approved && !hasGenomics) {
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

    // Non-restored files: fetch preview data from the server.
    // If the response is not JSON (e.g., HTML error page), catch
    // the parse failure and show the raw status instead.
    fetch(`/api/preview/${fileId}`)
        .then(res => {
            if (!res.ok) throw new Error(`Server returned ${res.status}`);
            return res.json();
        })
        .then(data => {
            // Log non-table responses so "Binary file" messages
            // are easier to diagnose from the browser console.
            if (data.type !== 'table' && data.type !== 'bm2_json' && data.type !== 'xlsx_table') {
                console.warn('[preview]', fileId, data);
            }
            _renderPreviewResponse(data, body);
        })
        .catch(err => {
            console.warn('[preview] fetch failed:', fileId, err);
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
            // XLSX or fallback — show file metadata.
            // Server sends either `message` (expected info) or `error`
            // (parse failure).  Show whichever is available, falling
            // back to a generic label only when neither is set.
            let sizeText = '';
            if (data.size_bytes != null) {
                const kb = (data.size_bytes / 1024).toFixed(1);
                sizeText = `<div class="info-size">${kb} KB</div>`;
            }
            const msg = data.message || data.error || `Binary file \u2014 preview not available.`;
            body.innerHTML = `
                <div class="modal-info-card">
                    <div class="info-icon">${data.error ? '\u26a0\ufe0f' : '\ud83d\udcc4'}</div>
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
 * apical endpoint tables in the result cards).
 *
 * @param {Object}      data      — { headers, rows, total_rows, filename }
 * @param {HTMLElement}  container — the modal body element to render into
 */
function renderModalTablePreview(data, container) {
    const wrapper = document.createElement('div');
    wrapper.className = 'table-preview';

    // Build the table — first column gets 'endpoint-label' class for sticky positioning
    const table = buildTable(data.headers, data.rows, {
        cellRenderer(val, _r, c, td) {
            td.textContent = val;
            if (c === 0) td.className = 'endpoint-label';
        },
    });
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


/* =================================================================
 * Full-report preview — dirty tracking
 *
 * reportDirty flips true on any approve/unapprove so the next navigation
 * (or the Recompile button) rebuilds the side-pane preview with fresh
 * content; ensureFullPreview() reads it to decide whether to recompile.
 * ================================================================= */

let reportDirty = true;

/**
 * Mark the report as needing a re-render.  Called from every
 * approve/unapprove action so the next navigation (or Recompile) rebuilds
 * the full side-pane preview.  ensureFullPreview() reads this flag.
 */
function markReportDirty() {
    reportDirty = true;
}


/**
 * Build the shared export payload for the report preview and Overleaf export.
 *
 * Collects all generated section data from the DOM and state objects:
 * background paragraphs, references, apical sections (with inline
 * table_data), methods, BMD summary, genomics, summary, and chart
 * images.  Returns a plain object ready to POST to /api/export-overleaf-bundle.
 *
 * Used by ensureFullPreview() (the side-pane preview) and exportDocument()
 * (the Overleaf .tex bundle), so the payload assembly isn't duplicated.
 *
 * Chart images are rendered server-side — the server calls
 * render_chart_images() in genomics_viz.py for all organ×sex combos
 * found in the genomics_sections payload.
 *
 * Returns:
 *   Object with all export fields matching the /api/export-overleaf-bundle schema.
 */
async function buildExportPayload() {
    const chemicalName = currentIdentity?.name || 'Chemical';
    const casrn = currentIdentity?.casrn || '';
    const dtxsid = currentIdentity?.dtxsid || '';

    // Background paragraphs
    const paragraphs = extractProse('output-prose');

    // References
    const refsEl = document.getElementById('references-list');
    const references = refsEl
        ? Array.from(refsEl.querySelectorAll('div')).map(div => div.textContent.trim())
        : [];

    // Apical sections — include all with table data, not just approved
    const apicalPayload = [];
    for (const [sectionId, info] of Object.entries(apicalSections)) {
        if (!info.tableData) continue;

        const narrativeEl = document.getElementById(`bm2-narrative-${sectionId}`);
        const narrativeText = narrativeEl?.value?.trim() || '';
        const narrativeParagraphs = narrativeText
            ? narrativeText.split(/\n\s*\n/).map(p => p.trim()).filter(Boolean)
            : [];

        const serverFileId = info.fileId
            ? (uploadedFiles[info.fileId]?.id || info.fileId)
            : sectionId;

        const domain = info.domain || '';
        const fallbacks = _resolveBm2Defaults(info.filename, domain);

        // Table number — optional, user-provided.  When present, the
        // Typst template prepends "Table N. " to the caption.
        const tableNumRaw = document.getElementById(`bm2-table-number-${sectionId}`)?.value;
        const tableNumber = tableNumRaw ? parseInt(tableNumRaw, 10) : null;

        const sectionEntry = {
            bm2_id: serverFileId,
            section_title: document.getElementById(`bm2-title-${sectionId}`)?.value?.trim()
                || fallbacks.title,
            table_caption_template: document.getElementById(`bm2-caption-${sectionId}`)?.value?.trim()
                || fallbacks.caption,
            compound_name: document.getElementById(`bm2-compound-${sectionId}`)?.value?.trim()
                || chemicalName,
            dose_unit: document.getElementById(`bm2-unit-${sectionId}`)?.value?.trim()
                || 'mg/kg',
            narrative_paragraphs: narrativeParagraphs,
            table_data: info.tableData || {},
            table_type: info.tableType || null,
            // Platform identifier — used by server-side section_filter
            // to select sections for per-subsection PDF previews.
            platform: info.platform || null,
        };
        // Rule-based builder fields passed through to the Typst template.
        // `footnotes` is the typed footnote list — the BMD definition line
        // is a `definition` record inside it, not a separate field.
        if (info.footnotes)      sectionEntry.footnotes = info.footnotes;
        if (info.firstColHeader) sectionEntry.first_col_header = info.firstColHeader;
        if (info.caption)        sectionEntry.caption = info.caption;
        if (tableNumber && !isNaN(tableNumber)) {
            sectionEntry.table_number = tableNumber;
        }
        apicalPayload.push(sectionEntry);
    }

    // Methods — include if generated (structured or flat)
    let methodsPayload = null;
    const methodsParas = [];
    if (methodsData && methodsData.sections && methodsData.sections.length > 0) {
        const editedSections = typeof extractMethodsSections === 'function'
            ? extractMethodsSections() : methodsData.sections;
        methodsPayload = {
            sections: editedSections,
            context: methodsData.context || {},
        };
    } else {
        const mp = extractProse('methods-prose');
        if (mp.length > 0) methodsParas.push(...mp);
    }

    // BMD Summary
    const bmdSummaryEps = bmdSummaryEndpoints;

    // Genomics — split into typed entries for the Typst template (include all, not just approved)
    const genomicsSecs = buildGenomicsExportSections(genomicsResults);

    // Summary
    const summaryParas = extractProse('summary-prose');

    // Gene Set / Gene BMD body narratives — server-derived by the shared
    // assembler (genomics_narratives.build_genomics_body_narratives) and
    // captured from the process-integrated response into state.js.  Pass
    // the whole dict through (intros + by_organ + paragraphs) so the
    // PDF's `marshal_export_data` overlay guard
    // (`if not _gs_existing.get("by_organ")`) uses this exact narrative
    // instead of rebuilding from disk — guaranteeing the PDF and the
    // HTML in-app view show identical prose.  Falls back to empty on
    // sessions processed before this wiring existed; the PDF path then
    // auto-populates on its own, same as before.
    const geneSetNarrativeExport = genomicsGeneSetNarrative || null;
    const geneNarrativeExport    = genomicsGeneNarrative    || null;

    // Chart images are read server-side from _cache_charts_{hash}.json —
    // no need to round-trip large base64 PNGs through the client payload.

    // Unified narratives — group-level prose that spans multiple platform
    // tables.  Read from the visible textareas (narrative-apical, etc.)
    // which were populated by the processing pipeline.  These are separate
    // from per-card narratives — the NIEHS reference uses one narrative for
    // the whole "Animal Condition" group, one for "Clinical Pathology", etc.
    const unifiedNarratives = {};
    for (const key of ['apical', 'clinical_pathology']) {
        const ta = document.getElementById(`narrative-${key}`);
        if (ta && ta.value.trim()) {
            unifiedNarratives[key] = {
                paragraphs: ta.value.trim().split(/\n\s*\n/).map(p => p.trim()).filter(Boolean),
            };
        }
    }

    return {
        paragraphs,
        references,
        chemical_name: chemicalName,
        casrn,
        dtxsid,
        apical_sections: apicalPayload,
        unified_narratives: unifiedNarratives,
        methods_data: methodsPayload,
        methods_paragraphs: methodsParas,
        bmd_summary_endpoints: bmdSummaryEps,
        apical_bmd_narrative: apicalBmdNarrative,
        genomics_sections: genomicsSecs,
        gene_set_narrative: geneSetNarrativeExport,
        gene_narrative: geneNarrativeExport,
        summary_paragraphs: summaryParas,
        // Abstract Background — LLM-generated alongside the body Background
        // by background_writer.py (delimited "=== ABSTRACT BACKGROUND ===" block).
        // The export pipeline appends a deterministic study-purpose sentence
        // to produce the full Abstract Background section.
        abstract_background: currentResult?.abstract_background || '',
        // Per-node page orientation {nodeId: "landscape"} for pages the user
        // flipped (tables / charts / figures).  Consumed by both renderers
        // (pdflscape in LaTeX, @page landscape in the HTML preview).
        orientations: (typeof getOrientations === 'function') ? getOrientations() : {},
    };
}


/* ================================================================
 * Full report preview (side pane)
 *
 * Per the generate-then-polish-in-Overleaf model, the side preview pane
 * always shows the FULL paginated report (never a per-section fragment).
 * The navigation scrolls it to the active section via scrollPreviewToNode().
 * ================================================================ */

// Guard against overlapping compiles (a recompile fired while one is
// already in flight).
let _fullPreviewRendering = false;

/**
 * Render the full paginated report into the side preview pane
 * (#preview-pdf-frame).
 *
 * Guarded by reportDirty: once rendered, navigating between sections does
 * NOT recompile -- the navigation just scrolls the existing preview.  Pass
 * force=true (the Recompile button) to rebuild regardless.  markReportDirty()
 * (called on every approve/unapprove) flips reportDirty so the next
 * navigation rebuilds with fresh content.
 *
 * Builds the same payload as the export bundle but WITHOUT section_filter,
 * so the server returns the whole report.  With no generated content yet,
 * the server still returns the full scaffolded structure (placeholders),
 * so the preview is always populated.
 *
 * @param {boolean} force - recompile even if the preview is current
 */
async function ensureFullPreview(force = false) {
    const frame = document.getElementById('preview-pdf-frame');
    if (!frame) return;
    // Already current (rendered + not dirty) and not forced -> nothing to do.
    if (!force && frame.srcdoc && !reportDirty) return;
    if (_fullPreviewRendering) return;
    _fullPreviewRendering = true;

    const status = document.getElementById('preview-status');
    if (status) status.textContent = 'Rendering preview\u2026';
    try {
        const payload = await buildExportPayload();  // full report (no section_filter)
        const resp = await fetch('/api/preview-latex-html', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            if (status) status.textContent = err.error || 'Preview failed';
            return;
        }
        frame.srcdoc = await resp.text();
        reportDirty = false;
        if (status) status.textContent = '';
    } catch (e) {
        if (status) status.textContent = `Preview error: ${e.message}`;
    } finally {
        _fullPreviewRendering = false;
    }
}

/**
 * Scroll the full preview to a navigation node's section anchor.
 *
 * html_generator emits a zero-height <span id="sec-<nodeId>"> before each
 * node (see _walk).  Poll briefly for it because Paged.js paginates
 * asynchronously: right after a (re)compile the anchor may not exist yet.
 * The srcdoc iframe is same-origin, so contentDocument access is allowed.
 *
 * @param {string} navId - the navigation node ID to scroll to
 */
function scrollPreviewToNode(navId) {
    const frame = document.getElementById('preview-pdf-frame');
    if (!frame || !navId) return;
    let tries = 0;
    const MAX_TRIES = 50;  // ~5s; covers a from-scratch Paged.js render
    const tick = () => {
        const doc = frame.contentDocument;
        const el = doc && doc.getElementById('sec-' + navId);
        if (el) {
            el.scrollIntoView({ behavior: 'smooth', block: 'start' });
            return;
        }
        if (tries++ < MAX_TRIES) setTimeout(tick, 100);
    };
    tick();
}
