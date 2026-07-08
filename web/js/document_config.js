/* ================================================================
 * document_config.js — the Document Structure config panel (ADR-0007
 * follow-on).
 *
 * Edits the per-session YAML that defines the document structure
 * (sections, ordering, titles, orientation, freeform content).  Save
 * validates server-side; on success the structure is re-fetched and the
 * nav + previews re-render against the SAME data — no re-integration.
 *
 * The editor is a CodeMirror 5 instance (YAML mode, syntax coloring, line
 * numbers) mounted over the #doc-config-yaml <textarea>.  CodeMirror loads
 * from CDN; if it's unavailable (offline / blocked), every accessor falls
 * back to the plain textarea, so the panel still works, just uncolored.
 *
 * Routes:
 *   GET  /api/document-config/{dtxsid}  → {yaml, is_default}
 *   POST /api/document-config/{dtxsid}  → {saved} | 422 {error}
 * Then refreshDocumentTree(dtxsid) (layout.js) re-renders the structure.
 * ================================================================ */

// The CodeMirror editor instance, created lazily on first panel open (the
// textarea must be visible for CodeMirror to size itself correctly).
let _docConfigCM = null;

/**
 * Ensure the CodeMirror editor exists (idempotent).  Returns the instance, or
 * null when CodeMirror isn't loaded — callers then fall back to the textarea.
 */
function _ensureDocConfigEditor() {
    if (_docConfigCM) return _docConfigCM;
    const ta = document.getElementById('doc-config-yaml');
    if (!ta || typeof window.CodeMirror === 'undefined') return null;
    _docConfigCM = window.CodeMirror.fromTextArea(ta, {
        mode: 'yaml',
        theme: 'eclipse',
        lineNumbers: true,
        lineWrapping: false,
        indentUnit: 2,
        tabSize: 2,
        // YAML is whitespace-significant — insert spaces, never a hard tab.
        extraKeys: {
            Tab: (cm) => cm.replaceSelection('  '),
        },
        viewportMargin: Infinity,  // render all lines so the panel scrolls naturally
    });
    _docConfigCM.setSize('100%', 460);
    return _docConfigCM;
}

/** Current editor text (CodeMirror if mounted, else the raw textarea). */
function _docConfigGet() {
    if (_docConfigCM) return _docConfigCM.getValue();
    const ta = document.getElementById('doc-config-yaml');
    return ta ? ta.value : '';
}

/** Set editor text on whichever surface is active. */
function _docConfigSet(text) {
    if (_docConfigCM) {
        _docConfigCM.setValue(text || '');
        return;
    }
    const ta = document.getElementById('doc-config-yaml');
    if (ta) ta.value = text || '';
}

/** Slide-down toggle for the Document Structure panel; loads on open. */
function toggleDocConfigPanel() {
    const panel = document.getElementById('doc-config-panel');
    if (!panel) return;
    const opening = panel.style.display === 'none' || !panel.style.display;
    panel.style.display = opening ? 'block' : 'none';
    if (opening) {
        // Mount CodeMirror now that the panel (and its textarea) is visible,
        // then load content.  refresh() settles layout after the display flip.
        const cm = _ensureDocConfigEditor();
        loadDocumentConfig().then(() => { if (cm) cm.refresh(); });
    }
}

function _docConfigDtxsid() {
    // Same source the export payload uses (export.js:_currentDtxsid).
    return (typeof currentIdentity !== 'undefined' && currentIdentity
            && currentIdentity.dtxsid) || '';
}

function _setDocConfigStatus(msg, kind) {
    const el = document.getElementById('doc-config-status');
    if (!el) return;
    el.textContent = msg || '';
    el.className = 'doc-config-status' + (kind ? ` ${kind}` : '');
}

/** "session" (per-report override) or "default" (the shared template). */
function _docConfigScope() {
    const sel = document.querySelector('input[name="doc-config-scope"]:checked');
    return sel ? sel.value : 'session';
}

/** Show/hide the default-scope warning banner and reload for the new scope. */
function onDocConfigScopeChanged() {
    const banner = document.getElementById('doc-config-scope-banner');
    if (banner) banner.style.display = _docConfigScope() === 'default' ? 'block' : 'none';
    loadDocumentConfig();
}

/** Fetch the YAML for the active scope (session override, or the default). */
async function loadDocumentConfig() {
    const scope = _docConfigScope();
    if (scope === 'default') {
        _setDocConfigStatus('Loading default…', '');
        try {
            const resp = await fetch('/api/document-config-default');
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                _setDocConfigStatus(data.error || `Load failed (${resp.status})`, 'err');
                return;
            }
            _docConfigSet(data.yaml || '');
            _setDocConfigStatus('Showing the shared default (the template all reports inherit).', 'ok');
        } catch (e) {
            _setDocConfigStatus(`Load error: ${e.message}`, 'err');
        }
        return;
    }

    // session scope
    const dtxsid = _docConfigDtxsid();
    if (!dtxsid) {
        _setDocConfigStatus('Enter a chemical first — the per-report structure is keyed by report.', 'err');
        _docConfigSet('');
        return;
    }
    _setDocConfigStatus('Loading…', '');
    try {
        const resp = await fetch(`/api/document-config/${encodeURIComponent(dtxsid)}`);
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            _setDocConfigStatus(data.error || `Load failed (${resp.status})`, 'err');
            return;
        }
        _docConfigSet(data.yaml || '');
        _setDocConfigStatus(
            data.is_default
                ? 'Showing the shared default structure. Save to create a per-report copy.'
                : 'Showing this report’s saved structure.',
            'ok');
    } catch (e) {
        _setDocConfigStatus(`Load error: ${e.message}`, 'err');
    }
}

/** Load the shared default structure into the editor (session scope only). */
async function resetDocumentConfigToDefault() {
    const dtxsid = _docConfigDtxsid();
    _setDocConfigStatus('Fetching default…', '');
    try {
        // ?default=1 forces the shared default even when this session already
        // has a saved override.
        const resp = await fetch(
            `/api/document-config/${encodeURIComponent(dtxsid)}?default=1`);
        const data = await resp.json().catch(() => ({}));
        if (resp.ok && data.yaml) {
            _docConfigSet(data.yaml);
            _setDocConfigStatus('Loaded the shared default. Save to apply it to this report.', 'ok');
        } else {
            _setDocConfigStatus(data.error || 'Could not load the default structure.', 'err');
        }
    } catch (e) {
        _setDocConfigStatus(`Error: ${e.message}`, 'err');
    }
}

/** Validate + save the edited YAML for the active scope, then re-render. */
async function saveDocumentConfig() {
    const scope = _docConfigScope();
    const dtxsid = _docConfigDtxsid();

    let url;
    if (scope === 'default') {
        url = '/api/document-config-default';
    } else {
        if (!dtxsid) {
            _setDocConfigStatus('Enter a chemical first — the per-report structure is keyed by report.', 'err');
            return;
        }
        url = `/api/document-config/${encodeURIComponent(dtxsid)}`;
    }

    _setDocConfigStatus(
        scope === 'default' ? 'Validating & saving the default…' : 'Validating & saving…', '');
    try {
        const resp = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ yaml: _docConfigGet() }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            // 422 → validation error; surface the exact message from the server.
            _setDocConfigStatus(data.error || `Save failed (${resp.status})`, 'err');
            return;
        }
        _setDocConfigStatus('Saved — re-rendering the document…', 'ok');
        // Re-fetch the (possibly per-session) structure and re-render nav +
        // previews.  A default save rebuilt the global tree server-side, so this
        // refresh reflects it for the current report too (no reprocess).
        if (typeof refreshDocumentTree === 'function') {
            await refreshDocumentTree(dtxsid);
        }
        _setDocConfigStatus(
            scope === 'default'
                ? 'Saved the default and re-rendered. Commit the template + golden fixture to keep it.'
                : 'Saved and re-rendered.',
            'ok');
    } catch (e) {
        _setDocConfigStatus(`Save error: ${e.message}`, 'err');
    }
}
