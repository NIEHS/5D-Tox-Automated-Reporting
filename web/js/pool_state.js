/**
 * pool_state.js — Pool workflow state machine and renderer.
 *
 * Defines the discrete phases of the Data tab's pool workflow
 * (upload, validate, integrate, approve) and the exact UI configuration
 * for every control element in each phase.
 *
 * Replaces the ad-hoc button manipulation scattered across validation.js,
 * pipeline.js, upload.js, and chemical.js with a single declarative
 * registry.  Every state transition in the codebase becomes:
 *
 *   AppStore.dispatch('pool.transition', 'VALIDATED');
 *
 * The renderer (renderPoolControls) subscribes to the pool slice and
 * applies DOM changes atomically — no code path can leave the UI in
 * a half-updated state.
 *
 * Phase progression (linear with backward jumps on re-validate/reset):
 *
 *   EMPTY -> UPLOADED -> VALIDATING -> VALIDATED -> INTEGRATING
 *         -> INTEGRATED -> APPROVING -> APPROVED
 *
 * Fits into the project as: the first "slice" built on app_store.js.
 * Later slices (sections, genomics, export) will follow the same
 * pattern — a PHASES registry, a reducer, and a renderer.
 */


// ===================================================================
// Phase definitions — the single source of truth for pool UI state.
//
// Each phase maps element IDs to their visual properties.  The renderer
// iterates this map and applies every property, so it's impossible to
// forget to update a button.  Adding a new control means adding one
// key to each phase — the compiler (well, your eyes) catches omissions
// because the key count won't match.
//
// Properties:
//   visible   — whether the element is displayed (style.display)
//   enabled   — whether a button is clickable (disabled attribute)
//   text      — textContent override
//   className — full class replacement (for badge styling)
// ===================================================================

const POOL_PHASES = {
    // No files uploaded yet.  All workflow buttons visible but disabled
    // as visual cues to the steps ahead.  No status badge — nothing
    // has happened yet.
    EMPTY: {
        'btn-validate':         { visible: true,  enabled: false, text: 'Validate' },
        'btn-integrate':        { visible: true,  enabled: false, text: 'Integrate' },
        'btn-approve-pool':     { visible: true,  enabled: false, text: 'Approve' },
        'btn-reset-pool':       { visible: true,  enabled: false },
        'btn-clear-files':      { visible: false },
        'badge-pool':           { visible: false },
        'validation-summary':   { visible: false },
        'file-metadata-review': { visible: false },
        'integrated-preview':   { visible: false },
    },

    // Files exist but haven't been validated yet.  Validate is the
    // only forward action.  Integrate and Approve stay visible but
    // disabled — showing the user what comes next.
    UPLOADED: {
        'btn-validate':         { visible: true,  enabled: true,  text: 'Validate' },
        'btn-integrate':        { visible: true,  enabled: false, text: 'Integrate' },
        'btn-approve-pool':     { visible: true,  enabled: false, text: 'Approve' },
        'btn-reset-pool':       { visible: true,  enabled: false },
        'btn-clear-files':      { visible: true,  enabled: true },
        'badge-pool':           { visible: false },
        'validation-summary':   { visible: false },
        'file-metadata-review': { visible: false },
        'integrated-preview':   { visible: false },
    },

    // Validation request is in flight.  Everything disabled to prevent
    // double-submission.  Button text shows progress.
    VALIDATING: {
        'btn-validate':         { visible: true,  enabled: false, text: 'Validating...' },
        'btn-integrate':        { visible: true,  enabled: false, text: 'Integrate' },
        'btn-approve-pool':     { visible: true,  enabled: false, text: 'Approve' },
        'btn-reset-pool':       { visible: true,  enabled: false },
        'btn-clear-files':      { visible: false },
        'badge-pool':           { visible: false },
        'validation-summary':   { visible: false },
    },

    // Validation succeeded.  Integrate is the ONE forward action.
    // Re-validate is NOT active — the user just validated, no reason
    // to redo it until after they see integrated results.  File
    // metadata table stays hidden until after approval.
    VALIDATED: {
        'btn-validate':         { visible: true,  enabled: false, text: 'Validate' },
        'btn-integrate':        { visible: true,  enabled: true,  text: 'Integrate' },
        'btn-approve-pool':     { visible: true,  enabled: false, text: 'Approve' },
        'btn-reset-pool':       { visible: true,  enabled: true },
        'btn-clear-files':      { visible: false },
        'badge-pool':           { visible: false },
        'validation-summary':   { visible: true },
        'file-metadata-review': { visible: false },
    },

    // Validation found errors.  Re-validate is active so the user
    // can fix files and try again.  Integrate and Approve stay disabled.
    VALIDATION_ERRORS: {
        'btn-validate':         { visible: true,  enabled: true,  text: 'Re-validate' },
        'btn-integrate':        { visible: true,  enabled: false, text: 'Integrate' },
        'btn-approve-pool':     { visible: true,  enabled: false, text: 'Approve' },
        'btn-reset-pool':       { visible: true,  enabled: true },
        'btn-clear-files':      { visible: false },
        'badge-pool':           { visible: true,  className: 'pool-badge badge-error',
                                  text: 'Validation Errors' },
        'validation-summary':   { visible: true },
        'file-metadata-review': { visible: false },
    },

    // Integration request is in flight.  Everything locked.
    INTEGRATING: {
        'btn-validate':         { visible: true,  enabled: false, text: 'Validate' },
        'btn-integrate':        { visible: true,  enabled: false, text: 'Integrating...' },
        'btn-approve-pool':     { visible: true,  enabled: false, text: 'Approve' },
        'btn-reset-pool':       { visible: true,  enabled: false },
        'btn-clear-files':      { visible: false },
        'badge-pool':           { visible: true,  className: 'pool-badge badge-progress',
                                  text: 'Integrating...' },
        'validation-summary':   { visible: true },
    },

    // Integration succeeded.  User previews the data.  Two choices:
    //   - Approve (satisfied with the data)
    //   - Re-validate (adjust pool and try again)
    // "Waiting for Approval" badge signals the decision point.
    INTEGRATED: {
        'btn-validate':         { visible: true,  enabled: true,  text: 'Re-validate' },
        'btn-integrate':        { visible: true,  enabled: false, text: 'Integrate' },
        'btn-approve-pool':     { visible: true,  enabled: true,  text: 'Approve' },
        'btn-reset-pool':       { visible: true,  enabled: true },
        'btn-clear-files':      { visible: false },
        'badge-pool':           { visible: true,  className: 'pool-badge badge-waiting',
                                  text: 'Waiting for Approval' },
        'validation-summary':   { visible: true },
    },

    // Approval + animal report generation in flight.
    APPROVING: {
        'btn-validate':         { visible: true,  enabled: false },
        'btn-integrate':        { visible: true,  enabled: false },
        'btn-approve-pool':     { visible: true,  enabled: false, text: 'Approving...' },
        'btn-reset-pool':       { visible: true,  enabled: false },
        'btn-clear-files':      { visible: false },
        'badge-pool':           { visible: true,  className: 'pool-badge badge-progress',
                                  text: 'Generating report...' },
        'validation-summary':   { visible: true },
    },

    // Pool is fully approved.  All forward actions are locked.  Only
    // Reset Pool and Nuclear Reset remain available.
    APPROVED: {
        'btn-validate':         { visible: true,  enabled: false, text: 'Validate' },
        'btn-integrate':        { visible: true,  enabled: false, text: 'Integrate' },
        'btn-approve-pool':     { visible: true,  enabled: false, text: 'Approve' },
        'btn-reset-pool':       { visible: true,  enabled: true },
        'btn-clear-files':      { visible: false },
        'badge-pool':           { visible: true,  className: 'pool-badge badge-approved',
                                  text: 'Approved' },
        'validation-summary':   { visible: true },
    },
};


// ===================================================================
// Reducer — handles 'pool.transition' and 'pool.init' actions.
//
// The pool slice state is just { phase: string }.  Future extensions
// (error messages, file counts) can be added as additional keys
// without changing the phase machine.
// ===================================================================

/**
 * Pool reducer.  Pure function: (state, verb, payload) -> newState.
 *
 * Verbs:
 *   'init'          — return default state
 *   'transition'    — payload is the new phase name (string).
 *                     Transitioning to EMPTY also clears platforms.
 *   'setPlatforms'  — payload is string[] of platform names.
 *                     Replaces the current platform set entirely.
 *   'addPlatform'   — payload is a single platform string.
 *                     Adds it to the set (idempotent).
 *   'clearPlatforms'— clears the platform set without changing phase.
 *
 * The `platforms` Set tracks which data types (e.g., "Body Weight",
 * "Hematology") have been detected in the uploaded file pool.  It's
 * populated at validation time (from coverage_matrix), confirmed at
 * processing time (from actual sections), and cleared on reset.
 * An AppStore subscriber syncs these into Alpine's ready.platform
 * flags so the TOC can enable/disable individual table nodes.
 *
 * @param {Object} state   — Current pool slice state
 * @param {string} verb    — Action verb
 * @param {*}      payload — Action payload
 * @returns {Object} New pool slice state
 */
function poolReducer(state, verb, payload) {
    // Default state for initialization (called by registerReducer
    // with state=undefined, verb='init').
    if (state === undefined || verb === 'init') {
        return { phase: 'EMPTY', platforms: new Set() };
    }

    switch (verb) {
        case 'transition': {
            const phase = payload;
            if (!POOL_PHASES[phase]) {
                console.warn(`[pool] unknown phase: ${phase}`);
                return state;
            }
            // Transitioning to EMPTY means the pool was cleared —
            // platforms go with it.
            if (phase === 'EMPTY') {
                return { ...state, phase, platforms: new Set() };
            }
            return { ...state, phase };
        }

        case 'setPlatforms': {
            // payload: string[] — replace the platform set wholesale.
            // Used after validation (from coverage_matrix) and after
            // processing (from actual section platforms).
            const platforms = new Set(Array.isArray(payload) ? payload : []);
            return { ...state, platforms };
        }

        case 'addPlatform': {
            // payload: single platform string.  Idempotent — safe to
            // call from getPlatformContainer() on every card creation
            // (including session restore).
            if (!payload || state.platforms.has(payload)) return state;
            const platforms = new Set(state.platforms);
            platforms.add(payload);
            return { ...state, platforms };
        }

        case 'clearPlatforms': {
            // Explicit clear without changing phase — used by reset
            // flows that dispatch this before the EMPTY transition.
            return { ...state, platforms: new Set() };
        }

        default:
            console.warn(`[pool] unknown verb: ${verb}`);
            return state;
    }
}


// ===================================================================
// Renderer — subscribes to pool slice, applies POOL_PHASES to DOM.
//
// This is the ONLY place in the codebase that touches pool workflow
// buttons and badges.  All other code dispatches state transitions
// and lets the renderer handle the DOM.
// ===================================================================

/**
 * Apply the current pool phase definition to the DOM.
 *
 * Iterates every element ID in the phase config and sets visibility,
 * enabled/disabled, text content, and CSS class.  Elements that don't
 * exist in the DOM (yet) are silently skipped — this is safe because
 * the validation panel may be hidden on initial load.
 *
 * @param {Object} poolState — Pool slice state: { phase: string }
 */
function renderPoolControls(poolState) {
    const config = POOL_PHASES[poolState.phase];
    if (!config) return;

    for (const [id, props] of Object.entries(config)) {
        const el = document.getElementById(id);
        if (!el) continue;

        if ('visible' in props) {
            el.style.display = props.visible ? '' : 'none';
        }
        if ('enabled' in props) {
            el.disabled = !props.enabled;
        }
        if ('text' in props) {
            el.textContent = props.text;
        }
        if ('className' in props) {
            el.className = props.className;
        }
    }
}


// ===================================================================
// Registration — wire the reducer and renderer into the store.
//
// This runs at script load time.  The renderer fires immediately
// (via subscribe's "fire on subscribe" behavior) to set the initial
// DOM state, so we don't need a separate "apply default state" call.
// ===================================================================

AppStore.registerReducer('pool', poolReducer);
AppStore.subscribe('pool', renderPoolControls);

// Nuclear reset button — enabled when the pool has content (any phase
// beyond EMPTY), disabled when there's nothing to reset.  The button's
// visibility is still managed by chemical.js (shown when a chemical is
// resolved), but the store controls whether it's clickable.
AppStore.subscribe('pool', (poolState) => {
    const btn = document.getElementById('btn-reset-session');
    if (btn) btn.disabled = poolState.phase === 'EMPTY';
});

// --- Sync pool platforms → Alpine ready.platform flags ---
// This subscriber bridges the AppStore (source of truth for which
// platforms have data) to the Alpine store (reactive UI bindings).
// TOC table nodes bind to $store.app.ready.platform['Body Weight']
// to enable/disable themselves individually.  Group-level ready.*
// flags (animalCondition, clinicalPath, etc.) are unchanged — they
// still drive the x-show on group containers.
AppStore.subscribe('pool', (poolState) => {
    if (typeof Alpine === 'undefined' || !Alpine.store('app')) return;
    const platformFlags = Alpine.store('app').ready.platform;
    if (!platformFlags) return;

    // Set every known platform key based on whether it's in the
    // pool's platform set.  Keys were pre-populated as false in
    // state.js during alpine:init, so Alpine can track them reactively.
    for (const key of Object.keys(platformFlags)) {
        platformFlags[key] = poolState.platforms.has(key);
    }
});

// Debug: show current pool phase and platform count in a small
// overlay at the bottom-left.  Lets the user verify that what they
// see matches the declared state.
// Remove or hide via CSS (.pool-debug-overlay { display:none }) for production.
AppStore.subscribe('pool', (poolState) => {
    let el = document.getElementById('pool-debug-overlay');
    if (!el) {
        el = document.createElement('div');
        el.id = 'pool-debug-overlay';
        el.className = 'pool-debug-overlay';
        document.body.appendChild(el);
    }
    const platCount = poolState.platforms ? poolState.platforms.size : 0;
    const platList = poolState.platforms ? [...poolState.platforms].join(', ') : '';
    el.textContent = `pool: ${poolState.phase} · ${platCount} platform${platCount !== 1 ? 's' : ''}`;
    el.title = platList || '(none)';
});

// Minimal inline style so it works without a CSS file change
(() => {
    const style = document.createElement('style');
    style.textContent = `
        .pool-debug-overlay {
            position: fixed;
            bottom: 8px;
            left: 8px;
            background: rgba(0,0,0,0.75);
            color: #4ade80;
            font-family: monospace;
            font-size: 12px;
            padding: 4px 8px;
            border-radius: 4px;
            z-index: 9999;
            pointer-events: none;
        }
    `;
    document.head.appendChild(style);
})();
