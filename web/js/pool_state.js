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
        return { phase: 'EMPTY', platforms: new Set(), completeness: new Map() };
    }

    switch (verb) {
        case 'transition': {
            const phase = payload;
            if (!POOL_PHASES[phase]) {
                console.warn(`[pool] unknown phase: ${phase}`);
                return state;
            }
            // Transitioning to EMPTY means the pool was cleared —
            // platforms and completeness go with it.
            if (phase === 'EMPTY') {
                return { ...state, phase, platforms: new Set(), completeness: new Map() };
            }
            // Regression to UPLOADED means the pool was mutated (new files
            // added or replaced after validation/integration).  Platforms
            // and completeness are cleared because the coverage matrix is
            // now stale — re-validation will re-populate them.
            if (phase === 'UPLOADED') {
                return { ...state, phase, platforms: new Set(), completeness: new Map() };
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

        case 'setCompleteness': {
            // payload: Map<string, {hasToxStudy, hasBm2, complete, missing}>
            // Derived from coverage matrix via computeSectionCompleteness().
            // Set after validation and updated after processing.
            return { ...state, completeness: payload instanceof Map ? payload : new Map() };
        }

        default:
            console.warn(`[pool] unknown verb: ${verb}`);
            return state;
    }
}


// ===================================================================
// Phase derivation — the settled pool phase is a function of artifact
// state, not a variable you set.
//
// derivePoolPhase() examines what artifacts exist and returns the
// correct phase.  All code that needs to set the settled pool phase
// calls this function and dispatches the result.
//
// Transient in-flight phases (VALIDATING, INTEGRATING, APPROVING)
// are the one exception — they represent async operations and are
// set imperatively.  When the operation completes, the result handler
// calls derivePoolPhase() to determine the settled phase.
// ===================================================================

/**
 * Derive the correct pool phase from the current artifact state.
 *
 * This is the single source of truth for "what phase should the pool
 * be in?"  Evaluated top-to-bottom, first match wins.
 *
 * @param {Object} artifacts — Artifact presence flags:
 *   @param {boolean} hasFiles           — files exist in the pool
 *   @param {boolean} hasStale           — any approved section is stale
 *                                         (pool mutated after approval)
 *   @param {Object|null} validationReport — the validation report object,
 *                                           or null if not yet validated
 *   @param {boolean} hasValidationErrors — validation found errors
 *   @param {boolean} hasIntegrated       — integrated.json exists
 *   @param {boolean} hasAnimalReport     — pool was approved (animal report
 *                                           generated)
 * @returns {string} The phase name (e.g., 'EMPTY', 'UPLOADED', 'VALIDATED')
 */
function derivePoolPhase(artifacts) {
    // No files → nothing to do
    if (!artifacts.hasFiles)              return 'EMPTY';

    // Pool was mutated after approval (stale sections exist) or after
    // validation (validation report was deleted) → must re-validate.
    // This handles both: new files added AND files replaced.
    if (artifacts.hasStale)               return 'UPLOADED';

    // Files exist but haven't been validated yet
    if (!artifacts.validationReport)      return 'UPLOADED';

    // Validation ran but found errors
    if (artifacts.hasValidationErrors)    return 'VALIDATION_ERRORS';

    // Validated but not yet integrated
    if (!artifacts.hasIntegrated)         return 'VALIDATED';

    // Integrated but not yet approved
    if (!artifacts.hasAnimalReport)       return 'INTEGRATED';

    // All present — fully approved
    return 'APPROVED';
}


// ===================================================================
// Section completeness — derived from the coverage matrix.
//
// Each platform needs specific data sources to produce a complete
// report section.  "Complete" means the section can render as PDF
// with all required columns populated (not "—" placeholders).
//
// Completeness requirements per platform:
//   - Apical (Body Weight, Organ Weight, Clin Chem, Hematology,
//     Hormones): need BOTH tox_study data (txt/csv for NTP stats)
//     AND .bm2 (for BMD/BMDL columns).
//   - Tissue Concentration: needs xlsx sidecar (Biosampling Animals).
//     No BMD columns, so .bm2 not required.
//   - Clinical Observations: needs CSV files (incidence data).
//     No BMD columns, so .bm2 not required.
//   - BMD Summary: needs .bm2 (IS the BMD data).
//   - Gene Sets / Gene BMD: needs .bm2 with gene_expression data.
//
// The coverage matrix from validation provides the tier information.
// ===================================================================

/**
 * Platforms that require both tox_study (txt/csv) and .bm2 data to
 * be complete.  These are the apical endpoint tables with BMD columns.
 */
const APICAL_PLATFORMS = new Set([
    'Body Weight', 'Organ Weight', 'Clinical Chemistry',
    'Hematology', 'Hormones',
]);

/**
 * Derive per-platform completeness from the coverage matrix.
 *
 * Returns a Map of platform name → completeness object:
 *   {
 *     hasToxStudy: boolean,  // txt/csv or xlsx data present
 *     hasBm2: boolean,       // .bm2 modeling data present
 *     complete: boolean,     // all required sources present
 *     missing: string[],     // human-readable list of what's missing
 *   }
 *
 * @param {Object} coverageMatrix — The coverage_matrix from validation
 *   report, with compound keys like "Body Weight|tox_study".
 * @returns {Map<string, Object>} Per-platform completeness
 */
// Normalize platform names from the fingerprinter to match the document
// tree's canonical names.  The fingerprinter (bmdx-pipe) returns short
// names like "Clinical" but the document tree uses "Clinical Observations".
// Without this mapping, isNodeComplete() can't find the platform in the
// completeness map and shows "No data for platform: Clinical Observations".
const PLATFORM_ALIASES = {
    'Clinical': 'Clinical Observations',
};

function computeSectionCompleteness(coverageMatrix) {
    if (!coverageMatrix) return new Map();

    // Collapse compound keys ("Body Weight|tox_study") into per-platform
    // presence, same logic as renderCoverageMatrix in validation.js.
    const collapsed = {};
    for (const key of Object.keys(coverageMatrix)) {
        const raw = key.includes('|') ? key.split('|')[0] : key;
        const platform = PLATFORM_ALIASES[raw] || raw;
        if (!collapsed[platform]) {
            collapsed[platform] = { xlsx: false, txtCsvCount: 0, bm2: false };
        }
        const tiers = coverageMatrix[key];
        if (tiers.xlsx) collapsed[platform].xlsx = true;
        const txtArr = tiers.txt_csv || [];
        collapsed[platform].txtCsvCount += Array.isArray(txtArr) ? txtArr.length : (txtArr ? 1 : 0);
        if (tiers.bm2) collapsed[platform].bm2 = true;
    }

    const result = new Map();

    for (const [platform, tiers] of Object.entries(collapsed)) {
        const hasToxStudy = tiers.xlsx || tiers.txtCsvCount > 0;
        const hasBm2 = tiers.bm2;
        const missing = [];

        if (APICAL_PLATFORMS.has(platform)) {
            // Apical tables need both NTP stats data AND BMD modeling
            if (!hasToxStudy) missing.push('Requires study data (.txt/.csv) for NTP statistics');
            if (!hasBm2) missing.push('Requires .bm2 for BMD/BMDL values');
        } else if (platform === 'Tissue Concentration') {
            // Tissue concentration needs xlsx sidecar only — no BMD columns
            if (!tiers.xlsx) missing.push('Requires .xlsx with Biosampling Animal data');
        } else if (platform === 'Clinical Observations') {
            // Clinical observations needs CSV incidence data
            if (!hasToxStudy) missing.push('Requires clinical observation CSV data');
        } else if (platform === 'gene_expression' || platform === 'Gene Expression') {
            // Genomics needs .bm2 with gene expression experiments
            if (!hasBm2) missing.push('Requires .bm2 with gene expression data');
        }

        result.set(platform, {
            hasToxStudy,
            hasBm2,
            complete: missing.length === 0,
            missing,
        });
    }

    return result;
}

/**
 * Check whether a document tree node is complete for PDF preview.
 *
 * A leaf table node is complete if its platform is complete.
 * A group node (narrative+tables) is complete only if ALL its child
 * table nodes are complete.
 *
 * @param {string} nodeId       — The TOC node ID (e.g., "animal-condition",
 *                                "table-body-weight")
 * @param {Map} completeness    — Per-platform completeness from
 *                                computeSectionCompleteness()
 * @param {Object} documentTree — Serialized document tree (array of nodes
 *                                with children)
 * @returns {{ complete: boolean, missing: string[] }}
 */
function isNodeComplete(nodeId, completeness, documentTree) {
    if (!completeness || completeness.size === 0) {
        return { complete: false, missing: ['No completeness data — validate the pool first'] };
    }

    const node = _findNodeInTree(nodeId, documentTree);
    if (!node) return { complete: true, missing: [] };  // non-data node (e.g., background)

    // Leaf table node — check its platform
    if (node.platform) {
        const status = completeness.get(node.platform);
        if (!status) return { complete: false, missing: [`No data for platform: ${node.platform}`] };
        return { complete: status.complete, missing: status.missing };
    }

    // Group node — complete only if ALL child table nodes are complete
    if (node.children && node.children.length > 0) {
        const allMissing = [];
        for (const child of node.children) {
            if (child.platform) {
                const status = completeness.get(child.platform);
                if (!status || !status.complete) {
                    const label = child.title || child.platform;
                    const reasons = status ? status.missing : [`No data for ${child.platform}`];
                    allMissing.push(`${label}: ${reasons.join('; ')}`);
                }
            }
        }
        return { complete: allMissing.length === 0, missing: allMissing };
    }

    // Non-table node (narrative, front matter, etc.) — always complete
    return { complete: true, missing: [] };
}

/**
 * Find a node by ID in the serialized document tree (recursive search).
 *
 * @param {string} nodeId — The node ID to find
 * @param {Array|Object} tree — The document tree (array of root nodes or
 *   a single node with children)
 * @returns {Object|null} The matching node, or null
 */
function _findNodeInTree(nodeId, tree) {
    if (!tree) return null;
    const nodes = Array.isArray(tree) ? tree : [tree];
    for (const node of nodes) {
        if (node.id === nodeId) return node;
        if (node.children) {
            const found = _findNodeInTree(nodeId, node.children);
            if (found) return found;
        }
    }
    return null;
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
