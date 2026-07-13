/* ================================================================
 * layout_builder.js — the VISUAL style builder (Form tab of the Layout &
 * Typography panel).
 *
 * A GUI over the `styles:` CONFIG (not the document): pick a target — the
 * document-wide Defaults, a content TYPE, or one specific SECTION (node
 * instance) — then set controls generated from the layout-style schema. The
 * form holds the same {defaults, types, instances} object the YAML represents;
 * every change writes the per-session styles.yaml (via the JSON `config` path of
 * /api/layout-style/{dtxsid}) and re-renders the HTML preview live.
 *
 * Not WYSIWYG: the editing surface is a closed-vocabulary settings form, never
 * the rendered document. Data flow stays one-way — form → styles → render.
 *
 * Reads two server-injected globals (background_server.py):
 *   window.__LAYOUT_SCHEMA__  — {key: {kind, values?|units?}} (control specs)
 *   window.__CONTENT_TYPES__  — catalog node-type list (the "type" targets)
 *   window.__DOCUMENT_TREE__  — walked to id+title list (the "section" targets)
 *
 * The Form and YAML tabs share ONE in-memory config (window._layoutConfigState),
 * so switching tabs shows the same edit. Save/preview reuse layout_config.js.
 * ================================================================ */

// The single in-memory config both tabs edit: {defaults?, types?, instances?}.
// Populated on panel load (from the server) and mutated by the form controls.
window._layoutConfigState = window._layoutConfigState || {};

// Active target the form is editing: {layer, key}.
//   layer "defaults" → key null   (the defaults object)
//   layer "types"    → key <content-type>
//   layer "instances"→ key <node-id>
let _lbTarget = { layer: "defaults", key: null };

// Debounce handle for the live-preview save.
let _lbPreviewTimer = null;


/** The style dict for the active target, creating the path lazily on write. */
function _lbTargetStyle(create = false) {
    const st = window._layoutConfigState;
    if (_lbTarget.layer === "defaults") {
        if (create && !st.defaults) st.defaults = {};
        return st.defaults || {};
    }
    const bucket = _lbTarget.layer; // "types" | "instances"
    if (create && !st[bucket]) st[bucket] = {};
    if (create && !st[bucket][_lbTarget.key]) st[bucket][_lbTarget.key] = {};
    return (st[bucket] && st[bucket][_lbTarget.key]) || {};
}


/** Flat [{id, title}] list of every node in the document tree, for the picker. */
function _lbNodeList() {
    const out = [];
    const roots = window.__DOCUMENT_TREE__ || [];
    const stack = Array.isArray(roots) ? [...roots] : [];
    while (stack.length) {
        const n = stack.shift();
        if (!n) continue;
        if (n.id) out.push({ id: n.id, title: n.title || n.id });
        if (n.children) stack.unshift(...n.children);
    }
    return out;
}


/** Populate the target selector (scope radios + the dependent "which" dropdown). */
function _lbRenderTargetSelector() {
    const which = document.getElementById("lb-target-which");
    if (!which) return;
    if (_lbTarget.layer === "defaults") {
        which.innerHTML = "";
        which.style.display = "none";
        return;
    }
    which.style.display = "";
    let opts;
    if (_lbTarget.layer === "types") {
        const types = window.__CONTENT_TYPES__ || [];
        opts = types.map((t) => ({ v: t, label: t }));
    } else {
        opts = _lbNodeList().map((n) => ({
            v: n.id,
            label: `${n.title} (${n.id})`,
        }));
    }
    which.innerHTML =
        '<option value="">— choose —</option>' +
        opts
            .map(
                (o) =>
                    `<option value="${escapeHtml(o.v)}"${
                        o.v === _lbTarget.key ? " selected" : ""
                    }>${escapeHtml(o.label)}</option>`
            )
            .join("");
}


/** Build one control row for a schema key, reflecting the active target's value. */
function _lbControlRow(key, spec, value) {
    const has = value !== undefined && value !== null;
    const id = `lb-ctl-${key}`;
    let control;

    if (spec.kind === "enum") {
        const opts =
            '<option value="">(inherit)</option>' +
            spec.values
                .map(
                    (v) =>
                        `<option value="${escapeHtml(v)}"${
                            has && value === v ? " selected" : ""
                        }>${escapeHtml(v)}</option>`
                )
                .join("");
        control = `<select id="${id}" data-key="${key}" data-kind="enum">${opts}</select>`;
    } else if (spec.kind === "length") {
        // Split "11pt" → number 11 + unit pt; blank when unset (inherit).
        let num = "";
        let unit = spec.units[0];
        if (has) {
            const m = String(value).match(/^(-?\d+(?:\.\d+)?)(\w+)$/);
            if (m) {
                num = m[1];
                unit = m[2];
            }
        }
        const unitOpts = spec.units
            .map(
                (u) =>
                    `<option value="${u}"${u === unit ? " selected" : ""}>${u}</option>`
            )
            .join("");
        control =
            `<input type="number" step="0.1" id="${id}" data-key="${key}" ` +
            `data-kind="length" placeholder="(inherit)" value="${escapeHtml(num)}" ` +
            `style="width:5em"> ` +
            `<select id="${id}-unit" data-unit-for="${key}">${unitOpts}</select>`;
    } else if (spec.kind === "number") {
        control =
            `<input type="number" step="0.1" id="${id}" data-key="${key}" ` +
            `data-kind="number" placeholder="(inherit)" value="${
                has ? escapeHtml(String(value)) : ""
            }" style="width:6em">`;
    } else if (spec.kind === "color") {
        const hex = has ? String(value) : "";
        control =
            `<input type="color" id="${id}-picker" data-picker-for="${key}" ` +
            `value="${/^#[0-9a-fA-F]{6}$/.test(hex) ? hex : "#000000"}"> ` +
            `<input type="text" id="${id}" data-key="${key}" data-kind="color" ` +
            `placeholder="(inherit)" value="${escapeHtml(hex)}" style="width:7em">`;
    } else if (spec.kind === "bool") {
        // Tri-state via a select so "inherit" (absent) differs from explicit false.
        const sel = (v) => (has && value === v ? " selected" : "");
        control =
            `<select id="${id}" data-key="${key}" data-kind="bool">` +
            `<option value="">(inherit)</option>` +
            `<option value="true"${sel(true)}>true</option>` +
            `<option value="false"${sel(false)}>false</option>` +
            `</select>`;
    } else {
        control = `<span>unsupported: ${escapeHtml(spec.kind)}</span>`;
    }

    return (
        `<div class="lb-row"><label for="${id}">${escapeHtml(key)}</label>` +
        `<span class="lb-control">${control}</span></div>`
    );
}


/** Render the full control set for the active target. */
function _lbRenderControls() {
    const host = document.getElementById("lb-controls");
    if (!host) return;
    const schema = window.__LAYOUT_SCHEMA__;
    if (!schema) {
        host.innerHTML =
            '<p class="settings-hint">Style schema unavailable — reload the page, ' +
            "or use the YAML tab.</p>";
        return;
    }
    // Instance/type target with nothing chosen yet → prompt, no controls.
    if (_lbTarget.layer !== "defaults" && !_lbTarget.key) {
        host.innerHTML =
            '<p class="settings-hint">Choose a ' +
            (_lbTarget.layer === "types" ? "content type" : "section") +
            " above to style it.</p>";
        return;
    }
    const style = _lbTargetStyle(false);
    const rows = Object.keys(schema)
        .map((key) => _lbControlRow(key, schema[key], style[key]))
        .join("");
    host.innerHTML = rows;
    _lbBindControls();
}


/** Attach change listeners to every control in the active set. */
function _lbBindControls() {
    const host = document.getElementById("lb-controls");
    if (!host) return;

    // Value-bearing controls (enum/length/number/color/bool).
    host.querySelectorAll("[data-key]").forEach((el) => {
        el.addEventListener("change", () => _lbOnControlChange(el));
        if (el.dataset.kind === "color" || el.dataset.kind === "length" ||
            el.dataset.kind === "number") {
            // Text/number inputs: also react to typing (debounced by the save).
            el.addEventListener("input", () => _lbOnControlChange(el));
        }
    });
    // Length unit dropdowns re-emit their paired number.
    host.querySelectorAll("[data-unit-for]").forEach((el) => {
        el.addEventListener("change", () => {
            const key = el.dataset.unitFor;
            const numEl = document.getElementById(`lb-ctl-${key}`);
            if (numEl) _lbOnControlChange(numEl);
        });
    });
    // Color pickers mirror into their paired hex text field, then emit.
    host.querySelectorAll("[data-picker-for]").forEach((el) => {
        el.addEventListener("input", () => {
            const key = el.dataset.pickerFor;
            const txt = document.getElementById(`lb-ctl-${key}`);
            if (txt) {
                txt.value = el.value;
                _lbOnControlChange(txt);
            }
        });
    });
}


/** Read a control's current value into the config, then schedule a preview. */
function _lbOnControlChange(el) {
    const key = el.dataset.key;
    const kind = el.dataset.kind;
    const style = _lbTargetStyle(true);

    let val;
    if (kind === "length") {
        const num = el.value.trim();
        const unitEl = document.getElementById(`lb-ctl-${key}-unit`);
        const unit = unitEl ? unitEl.value : "pt";
        val = num === "" ? undefined : `${num}${unit}`;
    } else if (kind === "number") {
        val = el.value.trim() === "" ? undefined : Number(el.value);
    } else if (kind === "bool") {
        val = el.value === "" ? undefined : el.value === "true";
    } else {
        // enum / color: "" means inherit (unset).
        val = el.value.trim() === "" ? undefined : el.value.trim();
    }

    if (val === undefined) {
        delete style[key];
    } else {
        style[key] = val;
    }
    _lbPruneEmpty();
    _lbSchedulePreview();
}


/** Drop empty {} target buckets so the saved YAML stays clean. */
function _lbPruneEmpty() {
    const st = window._layoutConfigState;
    for (const bucket of ["types", "instances"]) {
        if (!st[bucket]) continue;
        for (const k of Object.keys(st[bucket])) {
            if (!st[bucket][k] || Object.keys(st[bucket][k]).length === 0) {
                delete st[bucket][k];
            }
        }
        if (Object.keys(st[bucket]).length === 0) delete st[bucket];
    }
    if (st.defaults && Object.keys(st.defaults).length === 0) delete st.defaults;
}


/** Debounced save (JSON config path) + live preview re-render. */
function _lbSchedulePreview() {
    if (_lbPreviewTimer) clearTimeout(_lbPreviewTimer);
    _lbPreviewTimer = setTimeout(_lbSaveAndPreview, 500);
}

async function _lbSaveAndPreview() {
    const dtxsid = _layoutConfigDtxsid();
    if (!dtxsid) {
        _setLayoutConfigStatus(
            "Enter a chemical first — per-report styles are keyed by report.", "err");
        return;
    }
    _setLayoutConfigStatus("Applying…", "");
    try {
        const resp = await fetch(`/api/layout-style/${encodeURIComponent(dtxsid)}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ config: window._layoutConfigState }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            _setLayoutConfigStatus(data.error || `Save failed (${resp.status})`, "err");
            return;
        }
        if (typeof ensureFullPreview === "function") {
            await ensureFullPreview(true);
        }
        _setLayoutConfigStatus("Applied and re-rendered.", "ok");
    } catch (e) {
        _setLayoutConfigStatus(`Apply error: ${e.message}`, "err");
    }
}


/** Scope radio changed (Defaults / By content type / Specific section). */
function onLayoutBuilderScopeChanged() {
    const sel = document.querySelector('input[name="lb-scope"]:checked');
    _lbTarget = { layer: sel ? sel.value : "defaults", key: null };
    _lbRenderTargetSelector();
    _lbRenderControls();
}


/** "Which" dropdown changed (a content type or a node id). */
function onLayoutBuilderWhichChanged() {
    const which = document.getElementById("lb-target-which");
    _lbTarget.key = which ? which.value || null : null;
    _lbRenderControls();
}


/**
 * Entry point: load the config from the server (JSON) into the shared state and
 * render the form. Called when the Form tab is shown (layout_config.js).
 */
async function initLayoutBuilder() {
    const dtxsid = _layoutConfigDtxsid();
    if (!dtxsid) {
        _setLayoutConfigStatus(
            "Enter a chemical first — per-report styles are keyed by report.", "err");
        window._layoutConfigState = {};
    } else {
        try {
            const resp = await fetch(
                `/api/layout-style/${encodeURIComponent(dtxsid)}`);
            const data = await resp.json().catch(() => ({}));
            window._layoutConfigState =
                data && typeof data.config === "object" && data.config
                    ? data.config
                    : {};
            _setLayoutConfigStatus(
                data.is_default
                    ? "Showing the shared default styles. Any change saves a per-report copy."
                    : "Showing this report’s saved styles.",
                "ok");
        } catch (e) {
            window._layoutConfigState = {};
            _setLayoutConfigStatus(`Load error: ${e.message}`, "err");
        }
    }
    // Reset target to Defaults on each open.
    _lbTarget = { layer: "defaults", key: null };
    const def = document.querySelector('input[name="lb-scope"][value="defaults"]');
    if (def) def.checked = true;
    _lbRenderTargetSelector();
    _lbRenderControls();
}
