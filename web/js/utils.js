/* -----------------------------------------------------------------
 * utils.js — Shared UI helpers for 5dToxReport
 *
 * Loaded after state.js and before main.js.  Provides small,
 * reusable functions that replace dozens of duplicated inline
 * patterns throughout the application:
 *
 *   show / hide          — toggle element visibility (style.display)
 *   lockSection / unlock — disable/enable editing in a section
 *   setButtons           — switch action-button visibility per state
 *   apiFetch             — fetch() wrapper with uniform error handling
 *   extractProse         — pull paragraph text from contentEditable divs
 *   showProgress / etc.  — progress panel and toast helpers
 * ----------------------------------------------------------------- */


/* ==================================================================
 * escapeHtml — prevent XSS when interpolating user data into innerHTML
 *
 * Any user-supplied string (filenames, chemical names, identifiers)
 * must pass through this function before being inserted into HTML
 * template literals.  Replaces the 5 dangerous characters with their
 * HTML entity equivalents.
 * ================================================================== */

/**
 * Escape a string for safe insertion into innerHTML / template literals.
 *
 * Replaces &, <, >, ", and ' with their HTML entity equivalents to
 * prevent script injection from user-supplied data (filenames,
 * chemical names, form values, etc.).
 *
 * @param {string} str — The untrusted string to escape
 * @returns {string} — HTML-safe string
 */
function escapeHtml(str) {
    if (typeof str !== 'string') return '';
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}


/* ==================================================================
 * show / hide — replace 100+ bare `style.display` toggles
 *
 * These accept either a string element ID or an HTMLElement.
 * Passing an element directly avoids a redundant getElementById
 * lookup when the caller already has a reference.
 * ================================================================== */

/**
 * Show an element by clearing its inline display style.
 * @param {string|HTMLElement} idOrEl — element ID string or DOM element
 */
function show(idOrEl) {
    const el = typeof idOrEl === 'string' ? document.getElementById(idOrEl) : idOrEl;
    if (el) el.style.display = '';
}

/**
 * Hide an element by setting display to 'none'.
 * @param {string|HTMLElement} idOrEl — element ID string or DOM element
 */
function hide(idOrEl) {
    const el = typeof idOrEl === 'string' ? document.getElementById(idOrEl) : idOrEl;
    if (el) el.style.display = 'none';
}


/* ==================================================================
 * lockSection / unlockSection — replace 11+ duplicated patterns
 *
 * A "section" can be:
 *   1. A prose section (Background, Methods, Summary) with
 *      contentEditable .paragraph divs and .output-references divs
 *   2. A .bm2 card with readOnly .bm2-narrative textareas
 *      and readOnly .card-fields inputs
 *   3. A genomics card with contentEditable .paragraph divs
 *
 * The helpers query for ALL of these element types within the
 * given container and lock/unlock whatever they find.
 * ================================================================== */

/**
 * Lock a section after approval — disable all editing, add green border.
 * @param {HTMLElement} sectionEl — the section container element
 */
function lockSection(sectionEl) {
    sectionEl.classList.add('approved');
    // Prose sections: contentEditable paragraphs and reference divs
    sectionEl.querySelectorAll('.paragraph').forEach(p => p.contentEditable = 'false');
    sectionEl.querySelectorAll('.output-references div').forEach(d => d.contentEditable = 'false');
    // Bm2 cards: readOnly textareas and inputs
    sectionEl.querySelectorAll('.bm2-narrative').forEach(el => el.readOnly = true);
    sectionEl.querySelectorAll('.card-fields input').forEach(inp => inp.readOnly = true);
}

/**
 * Unlock a section for editing — re-enable all editing, remove green border.
 * @param {HTMLElement} sectionEl — the section container element
 */
function unlockSection(sectionEl) {
    sectionEl.classList.remove('approved');
    // Prose sections: contentEditable paragraphs and reference divs
    sectionEl.querySelectorAll('.paragraph').forEach(p => p.contentEditable = 'true');
    sectionEl.querySelectorAll('.output-references div').forEach(d => d.contentEditable = 'true');
    // Bm2 cards: readOnly textareas and inputs
    sectionEl.querySelectorAll('.bm2-narrative').forEach(el => el.readOnly = false);
    sectionEl.querySelectorAll('.card-fields input').forEach(inp => inp.readOnly = false);
}


/* ==================================================================
 * setButtons — replace 15+ button visibility toggle blocks
 *
 * Each report section has up to three action buttons named with
 * a common prefix: btn-approve-{prefix}, btn-edit-{prefix},
 * btn-retry-{prefix}.  This helper sets their visibility based
 * on the section's current state.
 *
 * Also handles the "badge-{prefix}" element if present (the green
 * "Approved" / blue "Approved (edited)" label).
 * ================================================================== */

/**
 * Set button visibility for a section's action buttons.
 *
 * @param {string} prefix — Section button prefix (e.g., 'bg', 'methods',
 *                          a bm2Id like 'bm2-abc123', or 'genomics-liver_m')
 * @param {string} state  — One of:
 *   'generating' — all buttons hidden (spinner is showing)
 *   'result'     — show Approve + Edit + Retry (fresh generation result)
 *   'approved'   — hide Approve, show Edit + Retry, show badge
 *   'editing'    — show Approve + Retry, hide Edit
 *   'hidden'     — hide all buttons AND badge
 */
function setButtons(prefix, state) {
    const approve = document.getElementById(`btn-approve-${prefix}`);
    const edit    = document.getElementById(`btn-edit-${prefix}`);
    const retry   = document.getElementById(`btn-retry-${prefix}`);
    const badge   = document.getElementById(`badge-${prefix}`);

    // Default: hide everything
    if (approve) approve.style.display = 'none';
    if (edit)    edit.style.display    = 'none';
    if (retry)   retry.style.display   = 'none';

    switch (state) {
        case 'result':
            // Fresh result — user can approve, edit, or retry
            if (approve) approve.style.display = '';
            if (edit)    edit.style.display    = '';
            if (retry)   retry.style.display   = '';
            break;
        case 'approved':
            // Locked — can edit or retry, but Approve is replaced by badge
            if (edit)  edit.style.display  = '';
            if (retry) retry.style.display = '';
            if (badge) badge.style.display = '';
            break;
        case 'editing':
            // Unlocked for editing — can re-approve or retry
            if (approve) approve.style.display = '';
            if (retry)   retry.style.display   = '';
            break;
        case 'generating':
        case 'hidden':
            // All hidden (default state above already handles this)
            if (badge) badge.style.display = 'none';
            break;
    }
}


/* ==================================================================
 * apiFetch — replace 16+ duplicated fetch + error handling blocks
 *
 * Wraps the Fetch API with:
 *   - Automatic JSON parsing of successful responses
 *   - Uniform error extraction (tries to parse error.detail from
 *     JSON response body, falls back to HTTP status text)
 *   - Throws an Error with a user-friendly message on failure
 * ================================================================== */

/**
 * Wrapper around fetch() with standardized error handling.
 * Returns the parsed JSON response, or throws with a user-friendly message.
 *
 * @param {string} url — The API endpoint URL
 * @param {object} options — fetch() options (method, headers, body, etc.)
 * @returns {Promise<any>} — Parsed JSON response data
 * @throws {Error} — With a descriptive message on non-OK responses
 */
async function apiFetch(url, options = {}) {
    const resp = await fetch(url, options);
    if (!resp.ok) {
        let msg = `Server error (${resp.status})`;
        try {
            const err = await resp.json();
            msg = err.detail || err.error || msg;
        } catch {
            // Response body wasn't JSON — use the generic message
        }
        throw new Error(msg);
    }
    return resp.json();
}


/* ==================================================================
 * extractProse — replace 5-6 inline paragraph extraction patterns
 *
 * Several functions (approve, export, compare) need to collect the
 * current text from contentEditable paragraph divs.  This helper
 * centralizes that pattern.
 * ================================================================== */

/**
 * Extract paragraph text from contentEditable divs within a container.
 *
 * @param {string} containerId — ID of the container element holding .paragraph divs
 * @returns {string[]} — Array of trimmed paragraph text strings
 */
function extractProse(containerId) {
    const el = document.getElementById(containerId);
    if (!el) return [];
    return Array.from(el.querySelectorAll('.paragraph'))
        .map(p => p.textContent.trim());
}


/* ==================================================================
 * Progress panel helpers — show/hide the progress spinner and
 * append log messages during background generation.
 * ================================================================== */

/**
 * Show the progress panel and clear any previous log entries.
 * Called at the start of a generation or processing operation.
 */
function showProgress() {
    document.getElementById('progress-panel').classList.add('visible');
    document.getElementById('progress-log').innerHTML = '';
}

/**
 * Hide the progress panel.  Called when generation completes or fails.
 */
function hideProgress() {
    document.getElementById('progress-panel').classList.remove('visible');
}

/**
 * Append a timestamped log message to the progress panel.
 * Auto-scrolls to keep the latest message visible.
 *
 * @param {string} message — The progress message to display
 */
function addProgressLog(message) {
    const log = document.getElementById('progress-log');
    const div = document.createElement('div');
    div.textContent = message;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
}


/* ==================================================================
 * Error panel helpers — show/hide a red error banner at the top.
 * ================================================================== */

/**
 * Display an error message in the error panel.
 * @param {string} message — The error text to show
 */
function showError(message) {
    const el = document.getElementById('error-panel');
    el.textContent = message;
    el.classList.add('visible');
}

/**
 * Hide the error panel.
 */
function hideError() {
    document.getElementById('error-panel').classList.remove('visible');
}

/**
 * Hide both the output section and notes panel.
 * Used when starting a fresh generation to clear stale results.
 */
function hideOutput() {
    document.getElementById('output-section').classList.remove('visible');
    document.getElementById('notes-panel').classList.remove('visible');
}


/* ==================================================================
 * Toast notifications — brief non-blocking messages at the bottom.
 * ================================================================== */

/**
 * Show a toast message for 2 seconds.
 * @param {string} message — The notification text
 */
function showToast(message) {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 2000);
}


/* ==================================================================
 * Textarea auto-resize — eliminates scrollbars by matching height
 * to content.
 * ================================================================== */

/**
 * Auto-resize a textarea to fit its content, eliminating scrollbars.
 * Attaches an input listener (once) so it stays fitted as the user edits.
 *
 * @param {HTMLElement} el — The textarea element to resize
 */
function autoResizeTextarea(el) {
    el.style.height = 'auto';
    el.style.height = el.scrollHeight + 'px';
    // Attach listener once — idempotent via a data attribute flag
    if (!el.dataset.autoResize) {
        el.dataset.autoResize = '1';
        el.addEventListener('input', () => {
            el.style.height = 'auto';
            el.style.height = el.scrollHeight + 'px';
        });
    }
}


/* ==================================================================
 * displayProse — render an array of paragraph strings as editable
 * content divs.  Used by Methods, Summary, and session restore.
 * ================================================================== */

/**
 * Render paragraphs as contentEditable divs inside a container.
 * Clears the container first, then creates one div.paragraph per string.
 *
 * @param {string} containerId — ID of the target container element
 * @param {string[]} paragraphs — Array of paragraph text strings
 */
function displayProse(containerId, paragraphs) {
    const container = document.getElementById(containerId);
    container.innerHTML = '';
    for (const para of paragraphs) {
        const div = document.createElement('div');
        div.className = 'paragraph';
        div.contentEditable = 'true';
        div.textContent = para;
        container.appendChild(div);
    }
}


/* ==================================================================
 * buildTable — create a DOM <table> from headers + rows arrays
 *
 * Replaces 3+ near-identical createElement('table') / createElement('thead')
 * / createElement('tbody') blocks scattered across main.js.  Returns
 * a bare <table> element that callers can append to any container.
 *
 * Options allow per-cell customization (CSS classes, bold rows) without
 * the caller needing to manually iterate rows/cells.
 * ================================================================== */

/**
 * Build a DOM <table> element from parallel arrays of headers and rows.
 *
 * @param {string[]}   headers — Column header strings
 * @param {Array[]}    rows    — Array of row arrays (each row is an array of cell values)
 * @param {object}     [opts]  — Optional configuration:
 *   @param {string}   [opts.className]     — CSS class for the <table> element
 *   @param {Function} [opts.cellRenderer]  — (value, rowIdx, colIdx, td) => void
 *                                            Custom renderer called for each <td>.
 *                                            Receives the cell value, indices, and the
 *                                            <td> element.  Default: sets textContent.
 *   @param {Function} [opts.headerRenderer] — (value, colIdx, th) => void
 *                                            Custom renderer for <th> cells.
 *                                            Default: sets textContent.
 * @returns {HTMLTableElement} — The constructed table element (not yet in the DOM)
 */
function buildTable(headers, rows, opts = {}) {
    const table = document.createElement('table');
    if (opts.className) table.className = opts.className;

    // --- <thead> ---
    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    for (let i = 0; i < headers.length; i++) {
        const th = document.createElement('th');
        if (opts.headerRenderer) {
            opts.headerRenderer(headers[i], i, th);
        } else {
            th.textContent = headers[i];
        }
        headerRow.appendChild(th);
    }
    thead.appendChild(headerRow);
    table.appendChild(thead);

    // --- <tbody> ---
    const tbody = document.createElement('tbody');
    for (let r = 0; r < rows.length; r++) {
        const tr = document.createElement('tr');
        const row = rows[r];
        for (let c = 0; c < row.length; c++) {
            const td = document.createElement('td');
            if (opts.cellRenderer) {
                opts.cellRenderer(row[c], r, c, td, tr);
            } else {
                td.textContent = row[c];
            }
            tr.appendChild(td);
        }
        tbody.appendChild(tr);
    }
    table.appendChild(tbody);

    return table;
}


/* ==================================================================
 * postApproveToServer — centralized POST to /api/session/approve
 *
 * Every section type (background, bm2, methods, genomics, summary,
 * bmd_summary) follows the same core pattern when the user clicks
 * "Approve":
 *   1. POST the section data to the server
 *   2. Lock the section UI (contentEditable=false, readOnly, green border)
 *   3. Update button visibility via setButtons()
 *   4. Mark the report tab dirty and update the export button
 *   5. Show a toast notification
 *
 * Section-specific logic (e.g., style learning badge, triggering
 * downstream sections) runs *after* this helper returns.
 *
 * Returns the server response JSON so callers can inspect result.ok,
 * result.user_edited, result.version, etc.  Returns null on error
 * (after showing an error toast).
 * ================================================================== */

/**
 * POST section data to /api/session/approve and apply common post-approve
 * UI updates (lock, buttons, dirty flag, export check, toast).
 *
 * @param {string} sectionType   — Server section_type key ('background', 'bm2', etc.)
 * @param {HTMLElement} sectionEl — The DOM element to lock after approval
 * @param {string} buttonPrefix  — Prefix for setButtons() (e.g., 'bg', 'methods', bm2Id)
 * @param {object} data          — Section-specific payload for the server
 * @param {string} [toastMsg]    — Optional custom toast message (default: "{sectionType} approved")
 * @returns {Promise<object|null>} — Server response JSON, or null on error
 */
async function postApproveToServer(sectionType, sectionEl, buttonPrefix, data, toastMsg) {
    if (!currentIdentity?.dtxsid) {
        showError('Resolve a chemical identity (with DTXSID) before approving.');
        return null;
    }

    try {
        const result = await apiFetch('/api/session/approve', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                dtxsid: currentIdentity.dtxsid,
                identity: currentIdentity,
                section_type: sectionType,
                data,
            }),
        });

        // Common post-approve UI: lock section, update buttons, mark dirty
        lockSection(sectionEl);
        setButtons(buttonPrefix, 'approved');
        markReportDirty();
        updateExportButton();

        if (!toastMsg) {
            toastMsg = result.user_edited
                ? 'Approved — learning from your edits...'
                : `${sectionType} approved`;
        }
        showToast(toastMsg);

        return result;

    } catch (err) {
        showError('Approve failed: ' + err.message);
        return null;
    }
}
