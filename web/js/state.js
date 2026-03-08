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


// --- UI mode ---
// Whether the tabbed (vs. stacked) layout is active.
// Defaults to true — tabs are the primary layout.  The user can
// toggle back to the stacked (scrollable) view via the toolbar button.
let tabbedViewActive = true;


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


// --- Domain label constants ---
// Human-readable labels for experimental domains.  Used in coverage matrix
// rendering, animal report display, and integrated pool sections.
// Defined once here to avoid duplicated mappings in main.js.
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


const DOMAIN_LABELS = {
    body_weight:    'Body Weight',
    organ_weights:  'Organ Weights',
    clin_chem:      'Clinical Chemistry',
    hematology:     'Hematology',
    hormones:       'Hormones',
    tissue_conc:    'Tissue Concentration',
    clinical_obs:   'Clinical Observations',
    gene_expression: 'Gene Expression',
    unknown:        'Unknown',
};
