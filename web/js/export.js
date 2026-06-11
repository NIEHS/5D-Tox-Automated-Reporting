// export.js — bundle export + GitHub repo hand-off, file preview modals
//
// Extracted from main.js.  These functions handle:
//   - Document export (exportDocument) — .tex bundle (zip) for offline/first-time
//   - Shared payload builder (buildExportPayload)
//   - Genomics export payload assembly (buildGenomicsExportSections)
//   - Report tab GitHub-repo hand-off (initReportTab, commitLocal, pushToGitHub,
//     pullFromGitHub, refreshRepoStatus, saveRepoBinding) — the app commits and
//     pushes the rendered working copy to the report's GitHub repo (ADR-0005 Am.3)
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
            btn.textContent = 'Export Bundle (.zip)';
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
 * Report dirty tracking (vestigial)
 *
 * markReportDirty() is still called from every approve/unapprove action
 * across the app.  With the in-app preview removed it no longer drives a
 * re-render, but it is kept as a harmless no-op so those many call sites
 * keep working — and as a hook a future "report changed since last sent to
 * Overleaf" indicator could read.
 * ================================================================= */

let reportDirty = true;

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
 * Used by exportDocument() (the Overleaf .tex bundle); kept as the single
 * payload assembler so the export isn't duplicated.
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
 * Report tab \u2014 GitHub repo hand-off (ADR-0005 Am.3)
 *
 * The app talks only to the report's GitHub repo; Overleaf is a downstream
 * consumer the human wires up via Overleaf's own GitHub sync.  Commit Local
 * commits the rendered working copy to the local clone; Push to GitHub ships
 * those commits; Pull from GitHub brings committee edits back + reconciles.
 * initReportTab() (called from navigateToNode when the Report tab opens) loads
 * the per-report repo binding and derives which controls to enable from
 * /api/repo-status.
 * ================================================================ */

/**
 * Current session dtxsid, or "" when no chemical is entered yet.
 */
function _currentDtxsid() {
    return (typeof currentIdentity !== 'undefined' && currentIdentity && currentIdentity.dtxsid) || '';
}

/**
 * Load the report's repo binding and reflect it in the Report tab: a bound repo
 * enables the controls (their finer state is derived in refreshRepoStatus); an
 * unbound one shows the link-a-repo prompt.
 */
async function initReportTab() {
    const setup = document.getElementById('repo-link-setup');
    if (!setup) return;

    const dtxsid = _currentDtxsid();
    if (!dtxsid) {
        // No session yet \u2192 nothing to link.
        setup.style.display = 'none';
        return;
    }

    let binding = {};
    try {
        const resp = await fetch(`/api/repo-binding/${encodeURIComponent(dtxsid)}`);
        if (resp.ok) binding = await resp.json();
    } catch (e) {
        /* unbound / offline \u2192 treat as no binding */
    }

    const hasRemote = !!(binding && binding.git_remote);
    // Unbound \u2192 show the paste-a-remote prompt; bound \u2192 hide it.
    setup.style.display = hasRemote ? 'none' : '';

    // Export works from the working copy regardless of repo binding.
    const exportBtn = document.getElementById('btn-export');
    if (exportBtn) exportBtn.disabled = false;

    // Derive Commit/Push/Pull enable-states from the clone's git status.
    await refreshRepoStatus(hasRemote);
}

/**
 * Set the Send/Fetch result line with a visible state.
 * state: '' (in-progress, neutral) | 'ok' (green success) | 'err' (red).
 */
function _setSyncStatus(msg, state) {
    const el = document.getElementById('sync-status');
    if (!el) return;
    el.textContent = msg;
    el.className = 'sync-status' + (state ? ' ' + state : '');
}

/**
 * Create or adopt the report's GitHub repo and bind it (init only — no content
 * is pushed here). Run once per report; content lands later via Commit Local →
 * Push to GitHub, after which the human does the one-time Import from GitHub in
 * Overleaf.
 */
async function provisionReport() {
    const dtxsid = _currentDtxsid();
    if (!dtxsid) { _setSyncStatus('Enter a chemical first.', 'err'); return; }
    const btn = document.getElementById('btn-provision');
    if (btn) btn.disabled = true;
    _setSyncStatus('Creating / linking GitHub repo…', '');
    try {
        const resp = await fetch(`/api/provision-report/${encodeURIComponent(dtxsid)}`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            _setSyncStatus(data.error || 'Provision failed.', 'err');
        } else {
            const verb = data.created ? 'Created' : 'Linked';
            _setSyncStatus(
                `✓ ${verb} ${data.repo}. Next: Commit Local, then Push to GitHub. ` +
                `Once pushed, in Overleaf do New Project → Import from GitHub → ${data.slug}.`,
                'ok');
        }
    } catch (e) {
        _setSyncStatus(`Provision error: ${e.message}`, 'err');
    } finally {
        if (btn) btn.disabled = false;
    }
    initReportTab();  // refresh binding-derived button states
}

/**
 * Commit Local: render the current working copy (the same payload the HTML view
 * uses) and commit it to the local clone. No network — Push to GitHub ships it.
 */
async function commitLocal() {
    const dtxsid = _currentDtxsid();
    if (!dtxsid) { _setSyncStatus('Enter a chemical first.', 'err'); return; }
    const btn = document.getElementById('btn-commit');
    if (btn) btn.disabled = true;
    _setSyncStatus('Rendering working copy + committing locally…', '');
    try {
        // Same payload the HTML view / Export Bundle render from — this is the
        // single source of truth (ADR-0005 Am.3 §B).
        const payload = await buildExportPayload();
        const resp = await fetch(`/api/commit-local/${encodeURIComponent(dtxsid)}`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            _setSyncStatus(data.error || 'Commit failed.', 'err');
        } else if (data.committed) {
            const n = data.ahead || 0;
            _setSyncStatus(
                `✓ Committed locally (${String(data.head).slice(0, 8)}). ` +
                `${n} local commit${n === 1 ? '' : 's'} ready to Push to GitHub.`,
                'ok');
        } else {
            _setSyncStatus('Working copy already committed — nothing new to record.', 'ok');
        }
    } catch (e) {
        _setSyncStatus(`Commit error: ${e.message}`, 'err');
    } finally {
        if (btn) btn.disabled = false;
    }
    refreshRepoStatus(true);
}

/**
 * Push to GitHub: ship the clone's accumulated local commits to the bound remote.
 * The server refuses (409) if the committee has pushed edits past our baseline —
 * then run Pull from GitHub first.
 */
async function pushToGitHub() {
    const dtxsid = _currentDtxsid();
    if (!dtxsid) { _setSyncStatus('Enter a chemical first.', 'err'); return; }
    const btn = document.getElementById('btn-push');
    if (btn) btn.disabled = true;
    _setSyncStatus('Pushing to GitHub…', '');
    try {
        const resp = await fetch(`/api/push-to-github/${encodeURIComponent(dtxsid)}`, { method: 'POST' });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            _setSyncStatus(data.error || 'Push failed.', 'err');
        } else {
            _setSyncStatus(
                `✓ Pushed to GitHub (commit ${String(data.pushed).slice(0, 8)}). ` +
                `In Overleaf, Menu → GitHub → “Pull GitHub changes” to see it.`,
                'ok');
        }
    } catch (e) {
        _setSyncStatus(`Push error: ${e.message}`, 'err');
    } finally {
        if (btn) btn.disabled = false;
    }
    refreshRepoStatus(true);
}

/**
 * Pull from GitHub: pull the bound remote and reconcile the committee's edits
 * (made in Overleaf, synced up to GitHub) into per-region overrides (preserved
 * on the next render).
 */
async function pullFromGitHub() {
    const dtxsid = _currentDtxsid();
    if (!dtxsid) { _setSyncStatus('Enter a chemical first.', 'err'); return; }
    const btn = document.getElementById('btn-pull');
    if (btn) btn.disabled = true;
    _setSyncStatus('Pulling committee edits from GitHub…', '');
    try {
        const resp = await fetch(`/api/pull-from-github/${encodeURIComponent(dtxsid)}`, { method: 'POST' });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            _setSyncStatus(data.error || 'Pull failed.', 'err');
        } else {
            const written = data.written || [];
            let msg = written.length
                ? `✓ Pulled — ${written.length} region(s) updated from committee edits: ${written.join(', ')}.`
                : '✓ Pulled — no committee edits to reconcile.';
            if ((data.structural || []).length) {
                msg += ` ⚠ ${data.structural.length} structural change(s) need review (not auto-applied).`;
            }
            _setSyncStatus(msg, 'ok');
        }
    } catch (e) {
        _setSyncStatus(`Pull error: ${e.message}`, 'err');
    } finally {
        if (btn) btn.disabled = false;
    }
    refreshRepoStatus(true);
}

/**
 * Derive the Commit/Push/Pull control states from the clone's git status
 * (ADR-0005 Am.3 §F) — the phase is read from artifacts, never set imperatively.
 *
 *   - Commit Local : enabled whenever a repo is bound (the working copy can
 *                    always be (re)committed; a no-op commit just reports so).
 *   - Push to GitHub: enabled when there are unpushed local commits AND the
 *                     remote hasn't moved past our baseline.
 *   - Pull from GitHub: enabled once a clone exists; highlighted when the remote
 *                     has advanced (committee edits await reconcile).
 *
 * `hasRemote` is passed by the caller (it already has the binding) to avoid a
 * redundant fetch.
 */
async function refreshRepoStatus(hasRemote) {
    const commitBtn = document.getElementById('btn-commit');
    const pushBtn = document.getElementById('btn-push');
    const pullBtn = document.getElementById('btn-pull');
    const dtxsid = _currentDtxsid();

    // Unbound or no session → every repo control is disabled.
    if (!dtxsid || !hasRemote) {
        if (commitBtn) commitBtn.disabled = true;
        if (pushBtn) pushBtn.disabled = true;
        if (pullBtn) pullBtn.disabled = true;
        return;
    }

    if (commitBtn) commitBtn.disabled = false;

    let status = { has_clone: false, ahead: 0, needs_pull: false };
    try {
        const resp = await fetch(`/api/repo-status/${encodeURIComponent(dtxsid)}`);
        if (resp.ok) status = await resp.json();
    } catch (e) {
        /* network hiccup → leave Push/Pull disabled below */
    }

    // Push only when there's something unpushed and the remote hasn't moved.
    if (pushBtn) pushBtn.disabled = !(status.ahead > 0) || status.needs_pull;
    // Pull once a clone exists; emphasise when the remote has advanced.
    if (pullBtn) {
        pullBtn.disabled = !status.has_clone;
        pullBtn.classList.toggle('primary', !!status.needs_pull);
    }
}

/**
 * Save the git remote the user pasted, then refresh the Report tab so the
 * Commit/Push/Pull controls activate.
 */
async function saveRepoBinding() {
    const status = document.getElementById('repo-link-status');
    const dtxsid = _currentDtxsid();
    if (!dtxsid) {
        if (status) status.textContent = 'Enter a chemical first.';
        return;
    }
    const gitRemote = (document.getElementById('repo-git-remote')?.value || '').trim();
    if (!gitRemote) {
        if (status) status.textContent = 'Paste the GitHub repo URL.';
        return;
    }
    if (status) status.textContent = 'Saving\u2026';
    try {
        const resp = await fetch(`/api/repo-binding/${encodeURIComponent(dtxsid)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ git_remote: gitRemote }),
        });
        if (!resp.ok) {
            if (status) status.textContent = 'Save failed.';
            return;
        }
        if (status) status.textContent = '';
        await initReportTab();  // activate the controls
    } catch (e) {
        if (status) status.textContent = `Error: ${e.message}`;
    }
}
