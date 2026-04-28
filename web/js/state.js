/* -----------------------------------------------------------------
 * state.js — Global application state for 5dToxReport
 *
 * Loaded first via <script> so that utils.js and main.js can
 * reference these variables directly (classic script sharing,
 * not ES modules).
 *
 * Contains all top-level mutable state (let) and configuration
 * constants (const) that are shared across the application.
 * No DOM access or function definitions — purely data declarations.
 * ----------------------------------------------------------------- */


// --- User gate ---
// Lightweight access control: if the server has ALLOWED_USERS set, every
// /api/ request must include ?user=<name>.  The username is stored in
// localStorage and prompted on first visit.  This is security-through-
// obscurity — no passwords, no tokens, just a shared secret username.
const USER_STORAGE_KEY = '5dtox-user';

/**
 * Get the stored username from localStorage.
 * @returns {string|null} The username, or null if not set.
 */
function getStoredUser() {
    return localStorage.getItem(USER_STORAGE_KEY);
}

/**
 * Wrap the browser's native fetch() to automatically append ?user=<name>
 * to every /api/ request.  This avoids editing 35+ individual fetch call
 * sites — the wrapper intercepts at the single global entry point and
 * delegates to the real fetch after adding the query parameter.
 *
 * Non-API requests (static assets, external URLs) pass through unchanged.
 * If no user is stored, API fetches proceed without the param — the
 * server returns 403, and the UI shows the login prompt.
 */
const _originalFetch = window.fetch;
window.fetch = function(input, init) {
    const user = getStoredUser();
    if (user && typeof input === 'string' && input.startsWith('/api/')) {
        // Append ?user= (or &user= if query params already exist)
        const sep = input.includes('?') ? '&' : '?';
        input = input + sep + 'user=' + encodeURIComponent(user);
    }
    return _originalFetch.call(this, input, init);
};


// --- Alpine.js store initialization ---
// The Alpine store is the single source of truth for section visibility
// and sidebar state.  Existing globals (apicalSections, genomicsResults,
// currentIdentity, etc.) stay as-is — they hold complex nested data that
// doesn't need reactivity.  Only the visibility flags and sidebar state
// go into the Alpine store because those are what the UI needs to react to.
//
// Alpine is loaded from CDN before this script runs (via <script defer>).
// We use document.addEventListener('alpine:init', ...) to register the
// store — this fires before Alpine processes x-data directives, so the
// store is available when the DOM initializes.
document.addEventListener('alpine:init', () => {
    Alpine.store('app', {
        // --- Sidebar collapse state (persisted to localStorage) ---
        // When true, the sidebar is hidden; when false, it's visible.
        sidebarCollapsed: JSON.parse(localStorage.getItem('5dtox-sidebar') || 'false'),

        /**
         * Toggle the sidebar open/closed and persist the choice.
         * Called from the sidebar toggle button via @click.
         */
        toggleSidebar() {
            this.sidebarCollapsed = !this.sidebarCollapsed;
            localStorage.setItem('5dtox-sidebar', JSON.stringify(this.sidebarCollapsed));
        },

        // --- Section readiness flags ---
        // Each flag indicates whether a section has data and should be visible.
        // Sidebar TOC nodes bind to these to toggle .disabled styling.
        // Content sections bind via x-show for automatic show/hide.
        ready: {
            chemId:          true,   // always visible — the identity form
            background:      true,   // always visible (may be empty initially)
            data:            false,  // shown after chemical resolved
            methods:         false,  // shown after background approved
            animalCondition: false,  // shown after process-integrated (body weight, organ weight)
            clinicalPath:    false,  // shown after process-integrated (clin chem, hematology, hormones)
            internalDose:    false,  // shown after process-integrated (tissue concentration)
            bmdSummary:      false,  // shown after BMD summary loaded
            bmdSummaryBmds:  false,  // shown after BMDS summary loaded
            geneSets:        false,  // shown after genomics processed
            geneBmd:         false,  // shown after genomics processed
            summary:         false,  // shown after other sections exist
            report:          true,   // always in DOM (lazy-rendered on navigate)

            // --- Per-platform availability flags ---
            // Drives individual TOC table node enable/disable.  Synced
            // from the pool slice's `platforms` Set by a subscriber in
            // pool_state.js.  Pre-populated here with all known platform
            // strings set to false so Alpine can track them reactively
            // (dynamic key addition doesn't trigger Alpine's proxy).
            //
            // Keys match the `platform` field on DocNode table nodes in
            // document_tree.py (e.g., "Body Weight", "Hematology").
            // The pool_state subscriber sets each to true/false based on
            // whether the pool contains data for that platform.
            platform: (() => {
                // Walk the server-injected document tree to discover all
                // platform strings.  This runs at alpine:init time, before
                // the first DOM walk, so the keys are available for the
                // first reactive pass.
                const flags = {};
                const tree = window.__DOCUMENT_TREE__ || [];
                function walk(nodes) {
                    for (const n of nodes) {
                        if (n.platform) flags[n.platform] = false;
                        if (n.children) walk(n.children);
                    }
                }
                walk(tree);
                return flags;
            })(),
        },

        // --- Currently active section ---
        // Only the section matching this ID is visible in the content pane.
        // Set by navigateToNode() on sidebar click.  Sidebar TOC nodes
        // bind to this for .active highlighting.  Defaults to 'chem-id'
        // so the Chemical ID form is visible on page load.
        activeSection: 'chem-id',

        // --- PDF preview pane visibility ---
        // Starts expanded.  Auto-collapsed when viewing Chemical ID or
        // Data sections (no PDF to preview there), auto-expanded on
        // navigation to any results section.  See layout.js navigateToNode().
        previewVisible: true,

        // --- Content pane visibility ---
        // Always visible — the content pane is the primary editing surface.
        contentVisible: true,

        // --- Unified narratives ---
        // Populated from the process-integrated response.  Keyed by section
        // name (e.g. "apical", "clinical_pathology"), values are
        // {paragraphs: [...]} objects from the server.
        unifiedNarratives: {},

        // --- Document structure tree ---
        // Injected by the server as window.__DOCUMENT_TREE__ in <head>.
        // This is the serialized form of document_tree.py's DOCUMENT_TREE
        // — the single source of truth for the report's organization.
        // The frontend derives TOC sidebar, Results containers, platform-
        // to-section routing, and domain ordering from this tree instead
        // of hardcoding them.
        documentTree: window.__DOCUMENT_TREE__ || [],
    });

    // If a chemical identity was already restored from localStorage
    // (by restoreChemId in chemical.js, which runs before Alpine init),
    // the Data tab should be visible.  restoreChemId's own ready.data=true
    // was a no-op because Alpine wasn't alive yet — fix that here.
    // Phase 3 will eliminate this race by moving visibility into the store.
    if (typeof currentIdentity !== 'undefined' && currentIdentity?.dtxsid) {
        Alpine.store('app').ready.data = true;
    }

    // --- Generate DOM from the document tree ---
    // Must run inside alpine:init (BEFORE Alpine processes x-data
    // directives) so the dynamically created elements with Alpine
    // directives (x-show, x-data, :class, @click, x-collapse) get
    // processed naturally by Alpine's first DOM walk.
    // The tree is available synchronously via window.__DOCUMENT_TREE__
    // (injected by the server in <head>).
    if (typeof initDocumentTree === 'function') {
        initDocumentTree();
    }
});


// --- Chemical identity ---
// currentIdentity holds the resolved ChemicalIdentity JSON from /api/resolve.
// currentResult holds the generation result from /api/generate.
let currentIdentity  = null;
let currentResult    = null;
let isResolving      = false;   // True while a resolve is in-flight
let resolveGeneration = 0;      // Incremented on each resolve; stale resolves check this
let isGenerating     = false;   // Prevents concurrent background generations
let lastResolvedValue = null;   // Tracks last resolved input to skip duplicate resolves


// --- Approval locks ---
// Each flag tracks whether a report section has been approved
// (saved to server-side session) and is locked for editing.
let backgroundApproved  = false;
let methodsApproved     = false;
let bmdSummaryApproved  = false;
let summaryApproved     = false;


// --- Section data ---
// methodsData holds the structured M&M output from /api/generate-methods:
//   { sections: [{heading, level, key, paragraphs, table}, ...],
//     context: {MethodsContext fields},
//     table1: {caption, headers, rows, footnotes} }
// Falls back to legacy format {paragraphs: [...]} for old sessions.
let methodsData          = null;
let bmdSummaryEndpoints  = [];     // derived from approved .bm2 data
let apicalBmdNarrative   = null;   // {descriptive, analytical, paragraphs} from process-integrated
let summaryParagraphs    = null;


// --- File pool & sections ---
// Unified file pool: maps fileId → {id, filename, type: 'bm2'|'csv', row_count, columns, restored}
// All uploaded files live here regardless of type.
const uploadedFiles = {};

// Apical endpoint sections: maps sectionId → {fileId, filename, processed, approved, tableData, ...}
const apicalSections = {};

// Counter for generating unique apical section IDs
let apicalSectionCounter = 0;

// Genomics results: maps "organ_sex" → {gene_sets, top_genes, approved, fileId}
const genomicsResults = {};

// Pre-rendered chart images from process-integrated (Layer 2.5).
// Array of dicts per organ×sex, each with umap_png, cluster_png, captions,
// cluster_summary.  Set during process-integrated, passed through to
// /api/export-pdf so the export never re-renders charts or calls Enrichr.
let chartImagesCache = null;

// --- Gene Set / Gene BMD body narratives (shared with PDF) ---
// Populated from /api/process-integrated.  Each is the full dict produced
// by `genomics_narratives.build_genomics_body_narratives`:
//   { intros: [...], by_organ: {organ: paragraph}, paragraphs: [...] }
// The HTML renders `by_organ[organ]` above each organ's table via
// `_rebuildOrganDisplays` in genomics.js; the same dict round-trips to
// the server for PDF export so both outputs stay in lockstep.
let genomicsGeneSetNarrative = null;
let genomicsGeneNarrative    = null;


// --- Form field config ---
// The six chemical identity fields in the form, and how each maps
// to the id_type parameter sent to /api/resolve.
const fields = ['name', 'casrn', 'dtxsid', 'cid', 'ec', 'iupac'];
const idTypeMap = {
    name:  'name',
    casrn: 'casrn',
    dtxsid: 'dtxsid',
    cid:   'cid',
    ec:    'name',   // EC number resolved through name lookup
    iupac: 'name',   // IUPAC name resolved through name lookup
};


// --- LocalStorage keys ---
// Used to persist the chemical identity across page reloads so the
// user doesn't have to re-enter and re-resolve the test article.
const CHEM_ID_STORAGE_KEY = '5dtox-chem-id';
const CHEM_ID_FIELDS = ['name', 'casrn', 'dtxsid', 'cid', 'ec', 'iupac', 'model-select'];


// --- Animal report ---
// Whether the animal report has been approved (included in DOCX export).
let animalReportApproved = false;
// Cached animal report data from /api/generate-animal-report/{dtxsid}.
let animalReportData = null;


// --- Integrated pool data ---
// Holds the merged BMDProject JSON from /api/pool/integrate/{dtxsid}.
// Set after validation + integration, consumed by autoProcessPool() to
// generate section cards from the unified data.
let integratedPoolData = null;


// --- Preview modal state ---
// Holds the Escape-key handler so it can be removed when the modal closes.
let _previewEscapeHandler = null;


// --- Platform label constants ---
// Human-readable labels for experimental platforms.  Used in coverage matrix
// rendering, animal report display, and integrated pool sections.
// Platform strings are already human-readable, so PLATFORM_LABELS is an
// identity map — kept for backward compatibility with code that calls
// domainLabel() / baseDomain().
// --- Report settings ---
// Persisted to localStorage.  Loaded on startup, sent to the server
// with process-integrated and other endpoints that need them.
const SETTINGS_STORAGE_KEY = '5dtox-settings';
const DEFAULT_SETTINGS = {
    bmd_stats: ['median'],   // BMD aggregates to show (each = separate GO table)
    dose_unit: 'mg/kg',      // Dose unit for table headers and narratives
    p_star: 0.05,            // Single-star significance threshold
    p_dstar: 0.01,           // Double-star significance threshold
    go_pct: 5,               // Min % of genes in a GO category that must have BMD values
    go_min_genes: 20,        // Min total genes annotated to a GO category
    go_max_genes: 500,       // Max total genes annotated to a GO category
    go_min_bmd: 3,           // Min genes with a BMD value in a GO category
};
// Live settings object — mutated by onSettingChanged(), read by API callers
let reportSettings = { ...DEFAULT_SETTINGS };


/**
 * Pass-through for backward compatibility.  Platform strings no longer
 * have _tox_study / _inferred suffixes, so this is essentially identity.
 * Kept so existing callers (filepool.js, sections.js) don't break.
 *
 * @param {string} platform — platform key (e.g., "Body Weight")
 * @returns {string} — same platform key, unchanged
 */
function baseDomain(platform) {
    return platform || '';
}

/**
 * Look up a human-readable label for a platform string.
 * Since platform strings are already human-readable (e.g., "Body Weight"),
 * this is a pass-through.  Kept for backward compatibility.
 *
 * @param {string} platform — platform key (e.g., "Body Weight")
 * @returns {string} — human-readable label (same as input)
 */
function domainLabel(platform) {
    return PLATFORM_LABELS[platform] || platform || '';
}

const PLATFORM_LABELS = {
    'Body Weight':           'Body Weight',
    'Organ Weights':         'Organ Weights',
    'Clinical Chemistry':    'Clinical Chemistry',
    'Hematology':            'Hematology',
    'Hormones':              'Hormones',
    'Tissue Concentration':  'Tissue Concentration',
    'Clinical':              'Clinical Observations',
    'Gene Expression':       'Gene Expression',
    'Unknown':               'Unknown',
};
