// export.js — PDF export, PDF preview, file preview modals, report tab
//
// Extracted from main.js.  These functions handle:
//   - Document export (exportDocument) — PDF/UA-1 via Typst
//   - Shared payload builder (buildExportPayload)
//   - Genomics export payload assembly (buildGenomicsExportSections)
//   - Per-tab section PDF preview (compileSectionPdf, refreshSectionPdf)
//   - Export button gating (updateExportButton)
//   - Clipboard copying (copyToClipboard)
//   - File preview modal (openPreviewModal, closePreviewModal, render helpers)
//   - JSON tree renderer for preview modals (renderJsonTree, _jsonValueSpan)
//   - Table/XLSX preview renderers (renderModalTablePreview, renderXlsxPreview)
//   - Report tab PDF preview (renderReportTab, compilePdfPreview, compileScaffoldPreview)
//   - PDF viewer toggle/resize (togglePdfViewer, initPdfResize)
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
 * Export .docx — sends background + apical sections to server
 * ================================================================ */

/**
 * Export the report as a tagged PDF/UA-1 file via /api/export-pdf.
 *
 * Uses buildExportPayload() to collect all approved section data,
 * POSTs to the server, and triggers a browser download of the
 * compiled PDF.  The server-side marshal_export_data() reshapes the
 * payload into the Typst template schema and compiles it to PDF/UA-1.
 *
 * This is the single export entry point — format-agnostic by design.
 * Currently only PDF is implemented; additional formats (e.g., HTML,
 * LaTeX) can be added by routing to different endpoints based on a
 * format parameter.
 */
async function exportDocument() {
    const btn = document.getElementById('btn-export');
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Generating...';
    }

    showBlockingSpinner('Generating PDF...');
    try {
        const payload = await buildExportPayload({ includeCharts: true });
        const chemicalName = payload.chemical_name || 'Chemical';

        const resp = await fetch('/api/export-pdf', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ error: 'PDF export failed' }));
            showError(err.error || 'PDF export failed');
            return;
        }

        // Trigger browser download of the PDF file
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `5dToxReport_${chemicalName.replace(/[^a-zA-Z0-9 _-]/g, '_')}.pdf`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        showToast('Downloaded tagged PDF (PDF/UA-1)');
    } catch (err) {
        showError('PDF export error: ' + err.message);
    } finally {
        hideBlockingSpinner();
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Export PDF';
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
 * Report tab — NIEHS-styled read-only aggregation view
 *
 * Assembles all approved report sections into a single flowing HTML
 * document styled to match the NIEHS Report 10 PDF (NBK589955).
 * Designed for window.print() / "Save as PDF" output.
 *
 * renderReportTab() is called lazily when the Report tab is activated,
 * and re-called whenever approval state changes while the tab is visible.
 * ================================================================= */

/* --- Dirty flag: set true when any approval changes so the Report
       tab re-renders on next activation.  Prevents unnecessary DOM
       thrashing when the user is on other tabs. --- */
let reportDirty = true;

/* showReportTab() removed — the Report tab is always visible in the
   tab bar.  renderReportTab() handles the empty state with a
   placeholder message when no sections are approved yet. */

/**
 * Mark the report as needing a re-render.  Called from every
 * approve/unapprove action so the next tab switch picks up changes.
 */
function markReportDirty() {
    reportDirty = true;
    // Don't auto-refresh the PDF preview on every change — it requires
    // a server round-trip to compile.  The user clicks "Refresh" to update.
}

/**
 * Render the Report tab by compiling a real PDF on the server and
 * displaying it in the browser's native PDF viewer via an iframe.
 *
 * Collects all generated section data (same payload as exportPdf),
 * POSTs to /api/export-pdf, receives the compiled PDF/UA-1 bytes,
 * and sets the iframe src to a blob URL.  The browser's built-in
 * PDF renderer handles pages, zoom, scrolling, and text selection.
 */
/**
 * Track the current PDF blob URL so we can revoke it when a new
 * PDF is loaded (prevents memory leaks from accumulating blob URLs).
 */
let currentPdfBlobUrl = null;

async function renderReportTab() {
    // Skip re-render if nothing changed since last render
    if (!reportDirty) return;
    reportDirty = false;

    const emptyEl = document.getElementById('report-empty');
    const iframe = document.getElementById('report-pdf-frame');

    // --- Check if any section has generated content ---
    const bgProseEl = document.getElementById('output-prose');
    const hasBg = bgProseEl && bgProseEl.textContent.trim().length > 0;
    const hasMethods = methodsData && methodsData.sections && methodsData.sections.length > 0;
    const methodsProseEl = document.getElementById('methods-prose');
    const hasMethodsProse = methodsProseEl && methodsProseEl.textContent.trim().length > 0;
    const hasApical = Object.values(apicalSections).some(s => s.tableData);
    const hasBmd = bmdSummaryEndpoints.length > 0;
    const hasGenomics = Object.values(genomicsResults).some(g => g.gene_sets_by_stat || g.gene_sets || g.top_genes);
    const summaryProseEl = document.getElementById('summary-prose');
    const hasSummary = summaryProseEl && summaryProseEl.textContent.trim().length > 0;

    const hasAnyContent = hasBg || hasMethods || hasMethodsProse ||
        hasApical || hasBmd || hasGenomics || hasSummary;

    if (!hasAnyContent) {
        // No generated content yet — show the scaffold PDF instead.
        // The scaffold has every section populated with placeholder text
        // (wrapped in «angle quotes»), showing the full NIEHS report
        // structure: title page, TOC, front matter, all body sections,
        // landscape tables, genomics, references.  This gives the user
        // a preview of what the final report will look like before any
        // content has been generated.
        //
        // The scaffold uses the current test article identity (if set)
        // so the title page, running header, and name forms are correct.
        await compileScaffoldPreview();
        return;
    }

    // --- Compile the real PDF on the server and display it ---
    await compilePdfPreview();
}


/**
 * Build the shared export payload for PDF compilation.
 *
 * Collects all generated section data from the DOM and state objects:
 * background paragraphs, references, apical sections (with inline
 * table_data), methods, BMD summary, genomics, summary, and chart
 * images.  Returns a plain object ready to POST to /api/export-pdf.
 *
 * Used by both compilePdfPreview() (full report) and compileSectionPdf()
 * (per-tab filtered preview) to avoid duplicating the payload assembly.
 *
 * Args:
 *   options.includeCharts: Whether to capture and include genomics
 *       chart images (base64 PNGs).  Default true.  Set to false for
 *       section previews that don't need charts (avoids Plotly overhead).
 * Returns:
 *   Object with all export fields matching the /api/export-pdf schema.
 */
async function buildExportPayload({ includeCharts = true } = {}) {
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
        };
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

    // Aggregate top-level narrative arrays across all genomics sections
    // (Typst template reads gene_set_narrative / gene_narrative from root, not per-section)
    const allGsNarr = genomicsSecs.flatMap(s => s.gene_set_narrative || []);
    const allGeneNarr = genomicsSecs.flatMap(s => s.gene_narrative || []);

    // Capture genomics chart images for report embedding (optional —
    // skipped for section previews that don't need them)
    let chartImages = null;
    if (includeCharts && typeof captureGenomicsChartImages === 'function') {
        chartImages = await captureGenomicsChartImages();
    }

    return {
        paragraphs,
        references,
        chemical_name: chemicalName,
        casrn,
        dtxsid,
        apical_sections: apicalPayload,
        methods_data: methodsPayload,
        methods_paragraphs: methodsParas,
        bmd_summary_endpoints: bmdSummaryEps,
        genomics_sections: genomicsSecs,
        gene_set_narrative: { paragraphs: allGsNarr },
        gene_narrative: { paragraphs: allGeneNarr },
        summary_paragraphs: summaryParas,
        genomics_chart_images: chartImages,
    };
}


/**
 * Compile the PDF via /api/export-pdf and display it in the iframe.
 *
 * Collects all generated section data (same payload as exportPdf but
 * includes non-approved content too), POSTs to the server, receives
 * the compiled PDF/UA-1 bytes, creates a blob URL, and sets the
 * iframe src.  The browser's native PDF renderer handles everything:
 * pages, zoom, scrolling, text selection, accessibility.
 */
async function compilePdfPreview() {
    const emptyEl = document.getElementById('report-empty');
    const iframe = document.getElementById('report-pdf-frame');
    const refreshBtn = document.getElementById('btn-refresh-report');

    if (refreshBtn) {
        refreshBtn.disabled = true;
        refreshBtn.textContent = 'Compiling...';
    }

    try {
        // Build the shared export payload (all sections, with charts)
        const payload = await buildExportPayload({ includeCharts: true });

        // --- POST to server for Typst compilation ---
        const resp = await fetch('/api/export-pdf', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ error: 'PDF compilation failed' }));
            showError(err.error || 'PDF compilation failed');
            return;
        }

        // --- Display the PDF in the iframe ---
        const blob = await resp.blob();

        // Revoke the previous blob URL to free memory
        if (currentPdfBlobUrl) {
            URL.revokeObjectURL(currentPdfBlobUrl);
        }
        currentPdfBlobUrl = URL.createObjectURL(blob);

        iframe.src = currentPdfBlobUrl;
        iframe.classList.remove('hidden');
        emptyEl.classList.add('hidden');

    } catch (err) {
        showError('PDF preview error: ' + err.message);
    } finally {
        if (refreshBtn) {
            refreshBtn.disabled = false;
            refreshBtn.textContent = 'Refresh';
        }
    }
}


/* ================================================================
 * Per-tab section PDF preview
 *
 * Each results tab (Apical, Genomics, Charts) has an embedded PDF
 * preview that compiles only the relevant section of the NIEHS report.
 * Uses the same Typst template and pipeline as the full Report tab,
 * but with a section_filter parameter that strips everything except
 * the requested section.
 * ================================================================ */

/**
 * Track per-section blob URLs so we can revoke them when a new PDF
 * is compiled (prevents memory leaks from accumulating blob URLs).
 * Keyed by section filter name ("apical", "genomics", "charts").
 */
const _sectionPdfBlobUrls = {};


/**
 * Compile a section-filtered PDF and return a blob URL for iframe display.
 *
 * Builds a payload scoped to the currently active sub-tab within the
 * requested section.  For example, if the Apical tab's "Clinical Pathology"
 * sub-tab is active, only that domain's dose-response tables are included.
 * The backend section_filter strips everything else (front matter, other
 * body sections), so the resulting PDF shows exactly one document section.
 *
 * Sub-tab context is read from the DOM:
 *   - Apical: active button in #apical-sub-tabs → data-domain attribute
 *   - Genomics: active button in #genomics-sub-tabs → data-key attribute
 *   - Charts: always includes all chart images (no sub-filtering)
 *
 * Args:
 *   sectionFilter: "apical", "genomics", or "charts"
 *
 * Returns:
 *   Blob URL string if successful, null on error.
 */
async function compileSectionPdf(sectionFilter) {
    // Only capture chart images when the Charts tab needs them
    const needCharts = sectionFilter === 'charts';
    const payload = await buildExportPayload({ includeCharts: needCharts });
    payload.section_filter = sectionFilter;

    const resp = await fetch('/api/export-pdf', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });

    if (!resp.ok) {
        const err = await resp.json().catch(() => ({ error: 'Section PDF compilation failed' }));
        showError(err.error || 'Section PDF compilation failed');
        return null;
    }

    const blob = await resp.blob();

    // Revoke previous blob URL for this section to free memory
    if (_sectionPdfBlobUrls[sectionFilter]) {
        URL.revokeObjectURL(_sectionPdfBlobUrls[sectionFilter]);
    }
    const blobUrl = URL.createObjectURL(blob);
    _sectionPdfBlobUrls[sectionFilter] = blobUrl;

    return blobUrl;
}


/**
 * Compile and display a section-specific PDF preview in a tab's iframe.
 *
 * Called by the "Compile PDF" button in each tab's PDF preview container.
 * Shows the preview container, clears the old iframe content, compiles
 * the section PDF on the server, and loads the result into the iframe.
 *
 * Args:
 *   sectionFilter: "apical", "genomics", or "charts"
 */
async function refreshSectionPdf(sectionFilter) {
    const frameId = `${sectionFilter}-pdf-frame`;
    const previewId = `${sectionFilter}-pdf-preview`;
    const frame = document.getElementById(frameId);
    const btn = document.querySelector(`#${previewId} .btn-compile-section-pdf`);

    if (!frame) return;

    // Show the preview container and clear old content
    show(previewId);
    frame.src = '';

    // Disable button and show compiling state
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Compiling...';
    }

    try {
        const blobUrl = await compileSectionPdf(sectionFilter);
        if (blobUrl) {
            frame.src = blobUrl;
        }
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Compile PDF';
        }
    }
}


/**
 * Toggle the section PDF preview for Apical or Genomics tabs.
 *
 * Hides the HTML card content and shows the PDF preview container
 * (or vice versa).  For Charts, this is handled by activateChartTypeTab()
 * since the PDF preview is a chart-type panel.
 *
 * The toggle button gets an "active" class when the PDF preview is visible,
 * matching the visual style of other sub-tab buttons.
 *
 * @param {string} sectionFilter — "apical" or "genomics"
 */
function toggleSectionPdfPreview(sectionFilter) {
    const previewId = `${sectionFilter}-pdf-preview`;
    const preview = document.getElementById(previewId);
    if (!preview) return;

    const isShowing = preview.style.display !== 'none';

    // Map section filter → the HTML content container to show/hide.
    // For top-level tabs (apical, genomics), this is the cards container.
    // For BMD summary sections, it's the table-preview div inside the
    // collapsible section body.
    const contentMap = {
        apical: 'bm2-cards',
        genomics: 'genomics-cards',
        bmd_summary: 'bmd-summary-table',
        bmd_summary_bmds: 'bmd-summary-bmds-table',
    };
    const contentId = contentMap[sectionFilter];
    const content = contentId ? document.getElementById(contentId) : null;

    // Toggle the PDF preview button's active state.
    // Look in the closest section container (bm2-section or output-section).
    const tabBtn = (preview.closest('.bm2-section') || preview.closest('.section-body'))
        ?.querySelector('.section-pdf-tab-btn');

    if (isShowing) {
        // Hide PDF preview, show HTML cards
        preview.style.display = 'none';
        if (content) content.style.display = '';
        if (tabBtn) tabBtn.classList.remove('active');
    } else {
        // Show PDF preview, hide HTML cards
        preview.style.display = '';
        if (content) content.style.display = 'none';
        if (tabBtn) tabBtn.classList.add('active');
        // Auto-compile if the iframe is empty (first time)
        const frame = document.getElementById(`${sectionFilter}-pdf-frame`);
        if (frame && !frame.src) {
            refreshSectionPdf(sectionFilter);
        }
    }
}


/**
 * Compile a scaffold PDF — full NIEHS report structure with placeholder
 * content — and display it in the Report tab iframe.
 *
 * Called when no sections have been generated yet.  Uses the current
 * test article identity (if set) so the title page, running header,
 * and name forms show the real chemical name rather than defaults.
 *
 * The scaffold endpoint is a simple GET request with query parameters
 * for the chemical identity fields.
 */
async function compileScaffoldPreview() {
    const emptyEl = document.getElementById('report-empty');
    const iframe = document.getElementById('report-pdf-frame');
    const refreshBtn = document.getElementById('btn-refresh-report');

    if (refreshBtn) {
        refreshBtn.disabled = true;
        refreshBtn.textContent = 'Loading scaffold...';
    }

    try {
        // Build query string from current test article identity
        const chemicalName = currentIdentity?.name || 'Test Article';
        const casrn = currentIdentity?.casrn || '';
        const dtxsid = currentIdentity?.dtxsid || '';

        const params = new URLSearchParams({
            chemical_name: chemicalName,
            casrn: casrn,
            dtxsid: dtxsid,
        });

        const resp = await fetch(`/api/export-pdf-scaffold?${params}`);
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ error: resp.statusText }));
            showError('Scaffold preview error: ' + (err.error || resp.statusText));
            return;
        }

        const blob = await resp.blob();

        // Revoke previous blob URL to prevent memory leaks
        if (currentPdfBlobUrl) {
            URL.revokeObjectURL(currentPdfBlobUrl);
        }
        currentPdfBlobUrl = URL.createObjectURL(blob);

        iframe.src = currentPdfBlobUrl;
        iframe.classList.remove('hidden');
        emptyEl.classList.add('hidden');

    } catch (err) {
        showError('Scaffold preview error: ' + err.message);
    } finally {
        if (refreshBtn) {
            refreshBtn.disabled = false;
            refreshBtn.textContent = 'Refresh';
        }
    }
}


/**
 * Manual refresh button handler — forces a re-compile of the PDF
 * preview from the current state of all generated sections.
 */
async function refreshReportPreview() {
    reportDirty = true;
    await renderReportTab();
}


/* ================================================================
 * PDF viewer collapse/expand toggle
 *
 * Toggles the .collapsed class on the PDF container, which CSS
 * animates to height: 0.  The toggle button arrow rotates to
 * indicate the current state.
 * ================================================================ */
function togglePdfViewer() {
    const container = document.getElementById('report-pdf-container');
    const btn = document.getElementById('btn-toggle-pdf');
    if (!container) return;

    container.classList.toggle('collapsed');
    // Rotate the arrow: ▼ when expanded, ▶ when collapsed
    const isCollapsed = container.classList.contains('collapsed');
    btn.innerHTML = isCollapsed ? '&#x25B6;' : '&#x25BC;';
    btn.title = isCollapsed ? 'Expand PDF viewer' : 'Collapse PDF viewer';
}


/* ================================================================
 * PDF viewer resize handle
 *
 * Allows the user to drag the bottom edge of the PDF container to
 * change its height.  Uses pointer events for smooth cross-browser
 * dragging (works with mouse and touch).
 *
 * During drag:
 *   - pointer is captured on the handle element
 *   - pointermove updates the container height
 *   - pointerup releases capture and cleans up
 *   - an overlay covers the iframe to prevent it from stealing events
 * ================================================================ */
(function initPdfResize() {
    // Wait for DOM — this IIFE runs when main.js is parsed, but the
    // elements may not exist yet.  Use DOMContentLoaded if needed.
    function setup() {
        const handle = document.getElementById('report-resize-handle');
        const container = document.getElementById('report-pdf-container');
        if (!handle || !container) return;

        let startY = 0;
        let startHeight = 0;

        handle.addEventListener('pointerdown', (e) => {
            // Only respond to primary button (left click / touch)
            if (e.button !== 0) return;

            e.preventDefault();
            handle.setPointerCapture(e.pointerId);
            handle.classList.add('dragging');

            // Disable the CSS transition during drag for instant feedback
            container.style.transition = 'none';

            startY = e.clientY;
            startHeight = container.getBoundingClientRect().height;

            // Create a transparent overlay to prevent the iframe from
            // capturing pointer events during the drag operation.
            // Without this, moving the cursor over the iframe would
            // cause pointermove events to stop firing on the handle.
            const overlay = document.createElement('div');
            overlay.id = 'pdf-resize-overlay';
            overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;cursor:ns-resize;';
            document.body.appendChild(overlay);

            function onMove(ev) {
                // Handle is at the top — dragging UP (negative delta)
                // should GROW the viewer, dragging DOWN should shrink it.
                // Max height is the full viewport.
                const delta = startY - ev.clientY;
                const maxHeight = window.innerHeight - 12; // leave room for handle
                const newHeight = Math.min(maxHeight, Math.max(80, startHeight + delta));
                container.style.height = newHeight + 'px';
            }

            function onUp(ev) {
                handle.releasePointerCapture(ev.pointerId);
                handle.classList.remove('dragging');
                // Restore the CSS transition for collapse animation
                container.style.transition = '';
                handle.removeEventListener('pointermove', onMove);
                handle.removeEventListener('pointerup', onUp);
                // Remove the overlay
                const ov = document.getElementById('pdf-resize-overlay');
                if (ov) ov.remove();
            }

            handle.addEventListener('pointermove', onMove);
            handle.addEventListener('pointerup', onUp);
        });
    }

    // Run setup after DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', setup);
    } else {
        setup();
    }
})();
