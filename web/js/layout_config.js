/* ================================================================
 * layout_config.js — the Layout & Typography config panel.
 *
 * Edits the per-content-type STYLES YAML (fonts, alignment, spacing, page
 * breaks) that both renderers resolve identically (LaTeX wraps each node in a
 * font/spacing group; the HTML preview emits the same spec as an inline-styled
 * wrapper — ADR-0006 no-drift).  Save validates server-side (loud enum/length/
 * color checks); on success the HTML preview re-renders against the SAME data —
 * styles are pure presentation, so there is no re-integration.
 *
 * Sibling of document_config.js (same CodeMirror-over-textarea pattern, same
 * session/default scope toggle); this one edits `styles:`, that one `document:`.
 *
 * Routes:
 *   GET  /api/layout-style/{dtxsid}   → {yaml, is_default}
 *   POST /api/layout-style/{dtxsid}   → {saved} | 422 {error}
 *   GET  /api/layout-style-default    → {yaml}
 *   POST /api/layout-style-default    → {saved} | 422 {error}
 * Then ensureFullPreview(true) (export.js) re-renders the preview.
 * ================================================================ */

let _layoutConfigCM = null;

function _ensureLayoutConfigEditor() {
    if (_layoutConfigCM) return _layoutConfigCM;
    const ta = document.getElementById('layout-config-yaml');
    if (!ta || typeof window.CodeMirror === 'undefined') return null;
    _layoutConfigCM = window.CodeMirror.fromTextArea(ta, {
        mode: 'yaml',
        theme: 'eclipse',
        lineNumbers: true,
        lineWrapping: false,
        indentUnit: 2,
        tabSize: 2,
        extraKeys: { Tab: (cm) => cm.replaceSelection('  ') },
        viewportMargin: Infinity,
    });
    _layoutConfigCM.setSize('100%', 460);
    return _layoutConfigCM;
}

function _layoutConfigGet() {
    if (_layoutConfigCM) return _layoutConfigCM.getValue();
    const ta = document.getElementById('layout-config-yaml');
    return ta ? ta.value : '';
}

function _layoutConfigSet(text) {
    if (_layoutConfigCM) {
        _layoutConfigCM.setValue(text || '');
        return;
    }
    const ta = document.getElementById('layout-config-yaml');
    if (ta) ta.value = text || '';
}

function toggleLayoutConfigPanel() {
    const panel = document.getElementById('layout-config-panel');
    if (!panel) return;
    const opening = panel.style.display === 'none' || !panel.style.display;
    panel.style.display = opening ? 'block' : 'none';
    if (opening) {
        const cm = _ensureLayoutConfigEditor();
        loadLayoutConfig().then(() => { if (cm) cm.refresh(); });
    }
}

function _layoutConfigDtxsid() {
    return (typeof currentIdentity !== 'undefined' && currentIdentity
            && currentIdentity.dtxsid) || '';
}

function _setLayoutConfigStatus(msg, kind) {
    const el = document.getElementById('layout-config-status');
    if (!el) return;
    el.textContent = msg || '';
    el.className = 'doc-config-status' + (kind ? ` ${kind}` : '');
}

function _layoutConfigScope() {
    const sel = document.querySelector('input[name="layout-config-scope"]:checked');
    return sel ? sel.value : 'session';
}

function onLayoutConfigScopeChanged() {
    const banner = document.getElementById('layout-config-scope-banner');
    if (banner) banner.style.display = _layoutConfigScope() === 'default' ? 'block' : 'none';
    loadLayoutConfig();
}

async function loadLayoutConfig() {
    const scope = _layoutConfigScope();
    if (scope === 'default') {
        _setLayoutConfigStatus('Loading default…', '');
        try {
            const resp = await fetch('/api/layout-style-default');
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                _setLayoutConfigStatus(data.error || `Load failed (${resp.status})`, 'err');
                return;
            }
            _layoutConfigSet(data.yaml || '');
            _setLayoutConfigStatus('Showing the shared default styles (the template all reports inherit).', 'ok');
        } catch (e) {
            _setLayoutConfigStatus(`Load error: ${e.message}`, 'err');
        }
        return;
    }

    const dtxsid = _layoutConfigDtxsid();
    if (!dtxsid) {
        _setLayoutConfigStatus('Enter a chemical first — per-report styles are keyed by report.', 'err');
        _layoutConfigSet('');
        return;
    }
    _setLayoutConfigStatus('Loading…', '');
    try {
        const resp = await fetch(`/api/layout-style/${encodeURIComponent(dtxsid)}`);
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            _setLayoutConfigStatus(data.error || `Load failed (${resp.status})`, 'err');
            return;
        }
        _layoutConfigSet(data.yaml || '');
        _setLayoutConfigStatus(
            data.is_default
                ? 'Showing the shared default styles. Save to create a per-report copy.'
                : 'Showing this report’s saved styles.',
            'ok');
    } catch (e) {
        _setLayoutConfigStatus(`Load error: ${e.message}`, 'err');
    }
}

async function resetLayoutConfigToDefault() {
    const dtxsid = _layoutConfigDtxsid();
    _setLayoutConfigStatus('Fetching default…', '');
    try {
        const resp = await fetch(
            `/api/layout-style/${encodeURIComponent(dtxsid)}?default=1`);
        const data = await resp.json().catch(() => ({}));
        if (resp.ok && data.yaml) {
            _layoutConfigSet(data.yaml);
            _setLayoutConfigStatus('Loaded the shared default styles. Save to apply them to this report.', 'ok');
        } else {
            _setLayoutConfigStatus(data.error || 'Could not load the default styles.', 'err');
        }
    } catch (e) {
        _setLayoutConfigStatus(`Error: ${e.message}`, 'err');
    }
}

async function saveLayoutConfig() {
    const scope = _layoutConfigScope();
    const dtxsid = _layoutConfigDtxsid();

    let url;
    if (scope === 'default') {
        url = '/api/layout-style-default';
    } else {
        if (!dtxsid) {
            _setLayoutConfigStatus('Enter a chemical first — per-report styles are keyed by report.', 'err');
            return;
        }
        url = `/api/layout-style/${encodeURIComponent(dtxsid)}`;
    }

    _setLayoutConfigStatus(
        scope === 'default' ? 'Validating & saving the default…' : 'Validating & saving…', '');
    try {
        const resp = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ yaml: _layoutConfigGet() }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            _setLayoutConfigStatus(data.error || `Save failed (${resp.status})`, 'err');
            return;
        }
        _setLayoutConfigStatus('Saved — re-rendering the preview…', 'ok');
        // Styles don't change the tree, only presentation — re-render the HTML
        // preview (it re-reads the saved styles server-side; no re-integration).
        if (typeof ensureFullPreview === 'function') {
            await ensureFullPreview(true);
        }
        _setLayoutConfigStatus(
            scope === 'default'
                ? 'Saved the default styles and re-rendered. Commit the template to keep it.'
                : 'Saved and re-rendered.',
            'ok');
    } catch (e) {
        _setLayoutConfigStatus(`Save error: ${e.message}`, 'err');
    }
}
