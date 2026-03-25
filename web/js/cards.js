/* -----------------------------------------------------------------
 * cards.js — BM2 card creation, platform routing, and table rendering
 *
 * Split from filepool.js.  Handles platform container routing
 * (getPlatformContainer), BM2 card UI creation (createBm2Card),
 * processing (.bm2 → NTP stats), and HTML table preview rendering.
 *
 * Depends on: state.js (globals), utils.js (helpers)
 * ----------------------------------------------------------------- */

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
 * Map platform names to their parent results-group Alpine store ready flag.
 * When a card is placed into a platform container, the corresponding
 * Alpine store flag is set to true so the parent section becomes visible.
 *
 * DERIVED FROM THE DOCUMENT TREE — not hardcoded.  buildPlatformToReady()
 * (in layout.js) walks the Results subtree and maps each child platform
 * to its parent group's ready_key.  This getter lazy-builds and caches
 * the map on first access (after the tree is fetched).
 *
 * Falls back to a minimal map if the tree isn't loaded yet (e.g., during
 * session restore that runs before the fetch completes).
 */
// Cache stored on window so layout.js can invalidate it when the
// document tree loads (the tree may not be available on first access).
window._platformToReadyCache = null;
function getPlatformToReady() {
    if (window._platformToReadyCache) return window._platformToReadyCache;
    if (typeof buildPlatformToReady === 'function') {
        const map = buildPlatformToReady();
        // Only cache if the tree was actually loaded (non-empty map)
        if (Object.keys(map).length > 0) {
            window._platformToReadyCache = map;
            return map;
        }
    }
    // Minimal fallback for code that runs before tree fetch completes
    return {
        'Body Weight': 'animalCondition', 'Organ Weight': 'animalCondition',
        'Organ Weights': 'animalCondition', 'Clinical Chemistry': 'clinicalPath',
        'Hematology': 'clinicalPath', 'Hormones': 'clinicalPath',
        'Tissue Concentration': 'internalDose',
        'Clinical Observations': 'animalCondition', 'Clinical': 'animalCondition',
    };
}
// Backward-compatible constant-like accessor for existing code
// that reads PLATFORM_TO_READY[platform] directly.
const PLATFORM_TO_READY = new Proxy({}, {
    get: (_, key) => getPlatformToReady()[key],
    has: (_, key) => key in getPlatformToReady(),
});

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
 * Get the container element for a given platform.
 *
 * Looks up the platform in the static HTML containers defined by
 * data-platform attributes.  Also sets the Alpine store readiness
 * flag so the parent section becomes visible via x-show.
 *
 * Falls back to #section-animal-condition if the platform is unknown.
 *
 * @param {string} platform — platform key (e.g. "Body Weight", "Hormones")
 * @returns {HTMLElement} — the container div to append cards into
 */
function getPlatformContainer(platform) {
    // Look up by data-platform attribute — matches the static containers
    // defined in index.html (e.g., <div data-platform="Body Weight">)
    const el = document.querySelector(`[data-platform="${platform}"]`);
    if (el) {
        // Ensure parent group is visible by setting the Alpine store flag
        const readyKey = PLATFORM_TO_READY[platform];
        if (readyKey && typeof Alpine !== 'undefined' && Alpine.store('app')) {
            Alpine.store('app').ready[readyKey] = true;
        }
        return el;
    }

    // Fallback for unexpected platforms — dump into the animal condition
    // section so cards don't disappear.  Also ensure it's visible.
    if (typeof Alpine !== 'undefined' && Alpine.store('app')) {
        Alpine.store('app').ready.animalCondition = true;
    }
    return document.getElementById('section-animal-condition') || document.body;
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
    // Route the card into the correct platform container.
    // The container is a static <div data-platform="..."> in index.html.
    // getPlatformContainer also sets the Alpine store readiness flag
    // so the parent section becomes visible.  Falls back to
    // #section-animal-condition for unknown platforms.
    const container = platform
        ? getPlatformContainer(platform)
        : (document.getElementById('section-animal-condition') || document.body);

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
                <button class="btn-small" id="btn-edit-${bm2Id}" onclick="editBm2('${bm2Id}')" style="display:none"
                    title="Unlock this section for editing (unapproves it)">
                    Edit
                </button>
                <button class="btn-small approve" id="btn-approve-${bm2Id}" onclick="approveBm2('${bm2Id}')" style="display:none"
                    title="Lock this section and mark it ready for export">
                    Approve
                </button>
                <button class="btn-small" id="btn-retry-${bm2Id}" onclick="retryBm2('${bm2Id}')" style="display:none"
                    title="Unapprove and reprocess this section from scratch">
                    Try Again
                </button>
                <span class="approved-badge" id="badge-${bm2Id}" style="display:none">Approved</span>
                <span class="version-history" id="version-history-${bm2Id}" style="display:none">
                    <button class="version-btn" onclick="toggleVersionHistory('bm2', '${bm2Id}')"
                        title="View and restore previous versions of this section">
                        v<span id="version-num-${bm2Id}">1</span> &#x25BE;
                    </button>
                    <div class="version-dropdown" id="version-dropdown-${bm2Id}" style="display:none"></div>
                </span>
                <button class="btn-small primary" onclick="processBm2('${bm2Id}')" id="btn-process-${bm2Id}" ${processDisabled}
                    title="Run NTP statistics and generate results for this section">
                    Process
                </button>
            </div>
        </div>
        <!-- Table config — inline, no collapse needed -->
        <div class="card-fields">
            <div class="form-group">
                <label>Caption</label>
                <input type="text" id="bm2-caption-${bm2Id}"
                    value="${escapeHtml(defaultCaption)}">
            </div>
            <div class="form-group">
                <label>Compound</label>
                <input type="text" id="bm2-compound-${bm2Id}"
                    placeholder="e.g., PFHxSAm"
                    value="${escapeHtml(currentIdentity?.name || '')}">
            </div>
            <div class="form-group">
                <label>Dose Unit</label>
                <input type="text" id="bm2-unit-${bm2Id}" value="mg/kg">
            </div>
            <div class="form-group">
                <label>Table #</label>
                <input type="number" id="bm2-table-number-${bm2Id}"
                    placeholder="e.g., 2" min="1" step="1"
                    style="width: 80px">
            </div>
        </div>
        <!-- Hidden fields consumed by export — title kept for payload compat -->
        <input type="hidden" id="bm2-title-${bm2Id}" value="${escapeHtml(defaultTitle)}">
        <textarea class="bm2-narrative" id="bm2-narrative-${bm2Id}" style="display:none"></textarea>
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

    // Detect pre-built grid format from the sidecar body weight builder.
    // When the first row of any sex has is_n_row=true, the data contains
    // every row the table needs (n, day 0, day 5) with values pre-computed.
    // We render all rows as-is — no template-side n-row construction.
    const firstSex = tables['Male'] || tables['Female'] || [];
    const isPrebuiltGrid = firstSex.length > 0 && firstSex[0].is_n_row;

    if (isPrebuiltGrid) {
        // ── Pre-built grid (sidecar body weight path) ─────────────────
        // One combined table with Male/Female sex separator rows,
        // matching the NIEHS reference Table 2 structure.
        const doses = firstSex[0].doses;

        // Caption
        const captionText = caption
            .replace(' of {sex} Rats', ' of Male and Female Rats')
            .replace('{sex}', 'Male and Female')
            .replace('{compound}', compound);
        const h4 = document.createElement('h4');
        h4.textContent = captionText;
        previewEl.appendChild(h4);

        const table = document.createElement('table');

        // Header row — "Study Day" for body weight
        const thead = document.createElement('thead');
        const headerRow = document.createElement('tr');
        headerRow.innerHTML = '<th>Study Day</th>';
        for (const dose of doses) {
            const label = dose === 0 ? `0 ${doseUnit}` :
                (dose === Math.floor(dose) ? `${Math.floor(dose)} ${doseUnit}` : `${dose} ${doseUnit}`);
            headerRow.innerHTML += `<th>${label}</th>`;
        }
        headerRow.innerHTML += `<th>BMD₁Std (${doseUnit})</th><th>BMDL₁Std (${doseUnit})</th>`;
        thead.appendChild(headerRow);
        table.appendChild(thead);

        const tbody = document.createElement('tbody');

        for (const sex of ['Male', 'Female']) {
            const rows = tables[sex];
            if (!rows || rows.length === 0) continue;

            // Sex separator row
            const sepRow = document.createElement('tr');
            const sepCell = document.createElement('td');
            sepCell.colSpan = doses.length + 3;
            sepCell.innerHTML = `<strong>${sex}</strong>`;
            sepRow.appendChild(sepCell);
            tbody.appendChild(sepRow);

            // All rows rendered as-is (n, day 0, day 5)
            for (const row of rows) {
                const tr = document.createElement('tr');
                tr.innerHTML = `<td class="endpoint-label">${row.label}</td>`;
                const markers = row.markers || {};
                for (const dose of doses) {
                    const dk = String(dose === Math.floor(dose) ? Math.floor(dose) : dose);
                    const val = row.values[dk] || '';
                    const marker = markers[dk];
                    if (marker) {
                        tr.innerHTML += `<td>${val}<sup>${marker}</sup></td>`;
                    } else {
                        tr.innerHTML += `<td>${val}</td>`;
                    }
                }
                // BMD/BMDL columns
                tr.innerHTML += `<td>${row.bmd || ''}</td><td>${row.bmdl || ''}</td>`;
                tbody.appendChild(tr);
            }
        }

        table.appendChild(tbody);
        previewEl.appendChild(table);

        // Render footnotes from the sidecar builder (stored in apicalSections
        // state by sections.js when the process-integrated response arrives).
        const sectionInfo = apicalSections[bm2Id];
        const footnotes = sectionInfo?.footnotes;
        if (footnotes && footnotes.length > 0) {
            const fnDiv = document.createElement('div');
            fnDiv.className = 'table-footnote';
            fnDiv.style.fontSize = '0.75rem';
            fnDiv.style.marginTop = '4px';
            fnDiv.style.lineHeight = '1.4';
            const letters = 'abcdefghijklmnopqrstuvwxyz';
            fnDiv.innerHTML = footnotes.map((fn, i) =>
                `<div><sup>${letters[i]}</sup> ${fn}</div>`
            ).join('');
            previewEl.appendChild(fnDiv);
        }

        tableNum++;

    } else {
        // ── Legacy path (generic apical tables) ───────────────────────
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
            thead.appendChild(headerRow);
            table.appendChild(thead);

            const tbody = document.createElement('tbody');

            // "n" row — only for normal apical tables, NOT for incidence tables.
            if (!isIncidence) {
                const nRow = document.createElement('tr');
                nRow.innerHTML = '<td class="endpoint-label">n</td>';
                for (const dose of doses) {
                    const maxN = Math.max(...rows.map(r => (r.n || {})[String(dose)] || 0));
                    nRow.innerHTML += `<td>${maxN > 0 ? maxN : '\u2013'}</td>`;
                }
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
                tbody.appendChild(tr);
            }

            table.appendChild(tbody);
            previewEl.appendChild(table);

            // Incidence table footnote
            if (isIncidence) {
                const footnoteEl = document.createElement('div');
                footnoteEl.className = 'table-footnote';
                footnoteEl.innerHTML = '<em>n/N = number of animals with finding / total animals in dose group.</em>';
                previewEl.appendChild(footnoteEl);
            }

            // Missing-animal footnotes
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
    // Populate the narrative textarea.
    // Normalize: narrative may arrive as a string (e.g. Tissue Concentration)
    // instead of the expected string[].  Wrap scalars in an array so .join()
    // always works.
    if (narrative && !Array.isArray(narrative)) {
        narrative = [narrative];
    }
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

    // Hide Process button, show Edit / Approve / Try Again buttons.
    // For integrated sections, also show "Update PDF" inside the config
    // panel so the user can recompile after changing table number, etc.
    const btn = document.getElementById(`btn-process-${sectionId}`);
    if (btn) btn.style.display = 'none';
    show(`btn-edit-${sectionId}`);
    show(`btn-approve-${sectionId}`);
    show(`btn-retry-${sectionId}`);

    if (sectionId.startsWith('integrated-')) {
        show(`btn-update-pdf-${sectionId}`);
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

    // Hide the results sections if no cards remain
    if (Object.keys(apicalSections).length === 0 && typeof Alpine !== 'undefined' && Alpine.store('app')) {
        Alpine.store('app').ready.animalCondition = false;
        Alpine.store('app').ready.clinicalPath = false;
        Alpine.store('app').ready.internalDose = false;
    }
}
