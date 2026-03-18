// versions.js — Version history browsing/restore and style profile management
//
// Extracted from main.js. These functions manage the version history dropdown
// (browse, preview, restore past approved versions) and the style profile panel
// (load, render, delete learned writing-style rules).
//
// All functions reference globals from state.js (apicalSections, currentIdentity,
// etc.) and UI helpers from main.js (showError, showToast, showBlockingSpinner,
// hideBlockingSpinner, autoResizeTextarea, bm2Slug, tabbedViewActive, buildTabBar).

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

    showBlockingSpinner('Restoring version...');
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
    } finally {
        hideBlockingSpinner();
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
    showBlockingSpinner('Deleting rule...');
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
    } finally {
        hideBlockingSpinner();
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
