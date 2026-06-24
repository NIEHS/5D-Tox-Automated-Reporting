// models_modal.js — LLM model selection modal.
//
// Lets the user pick which model drives each generation concern:
//   - background        → Background section (/api/generate)
//   - methods_summary   → Methods + Summary sections
//   - analysis          → genomics narrative (labeled "Analysis")
//
// The category lists are populated live from GET /api/models (the LiteLLM
// proxy catalog).  Picks are held in the `selectedModels` global (state.js),
// seeded from the session's meta.models on restore, and persisted back to
// meta.json via POST /api/session/{dtxsid}/models on Save.
//
// Globals consumed (from state.js): selectedModels, DEFAULT_MODEL, currentIdentity
// Helpers consumed (from utils.js): apiFetch, showToast
//
// Classic <script> — all functions are global so inline onclick handlers
// in index.html can reach them.

// The three concerns, in display order, with their panel titles.
const MODEL_CONCERNS = [
    { key: 'background', title: 'Background' },
    { key: 'methods_summary', title: 'Methods + Summary' },
    { key: 'analysis', title: 'Analysis' },
];

// Cached /api/models response so reopening the modal doesn't refetch.
let _modelCatalog = null;

/**
 * Seed `selectedModels` from a session's meta.models (called on restore).
 * Missing concerns keep their current value (DEFAULT_MODEL on first load).
 */
function seedSelectedModels(metaModels) {
    if (!metaModels || typeof metaModels !== 'object') return;
    for (const { key } of MODEL_CONCERNS) {
        if (typeof metaModels[key] === 'string' && metaModels[key]) {
            selectedModels[key] = metaModels[key];
        }
    }
}

/** Fetch the proxy model catalog once and cache it. */
async function _loadModelCatalog() {
    if (_modelCatalog) return _modelCatalog;
    _modelCatalog = await apiFetch('/api/models');
    return _modelCatalog;
}

/**
 * Build the radio list for one concern.  Each option is a model id; the
 * currently-selected id (from selectedModels) is checked.  If the selected
 * id isn't in the catalog (e.g. a stale saved pick), it's added under an
 * "Current" group so the user still sees what's active.
 */
function _renderConcern(concern, categories) {
    const selected = selectedModels[concern.key];
    const allIds = categories.flatMap(c => c.models);

    const parts = [
        `<div class="models-concern">`,
        `<div class="models-concern-title">${escapeHtml(concern.title)}</div>`,
        `<div class="models-concern-list">`,
    ];

    // Surface a saved pick the catalog no longer lists so it's not lost.
    if (selected && !allIds.includes(selected)) {
        parts.push(`<div class="models-category-label">Current</div>`);
        parts.push(_renderOption(concern.key, selected, true));
    }

    for (const cat of categories) {
        parts.push(`<div class="models-category-label">${escapeHtml(cat.name)}</div>`);
        for (const id of cat.models) {
            parts.push(_renderOption(concern.key, id, id === selected));
        }
    }

    parts.push(`</div></div>`);
    return parts.join('');
}

function _renderOption(concernKey, modelId, checked) {
    const safeId = escapeHtml(modelId);
    return (
        `<label class="models-option">` +
        `<input type="radio" name="model-${escapeHtml(concernKey)}" ` +
        `value="${safeId}"${checked ? ' checked' : ''}>` +
        `<span>${safeId}</span></label>`
    );
}

/** Open the modal, lazy-loading the catalog on first open. */
async function openModelsModal() {
    const modal = document.getElementById('models-modal');
    const container = document.getElementById('models-modal-concerns');
    const degraded = document.getElementById('models-modal-degraded');
    if (!modal || !container) return;

    container.innerHTML = '<p>Loading models&hellip;</p>';
    modal.style.display = 'flex';

    let catalog;
    try {
        catalog = await _loadModelCatalog();
    } catch (e) {
        // The endpoint itself is fail-safe (returns a fallback), so a throw
        // here means a transport error — show the fallback inline.
        catalog = { categories: [{ name: 'Anthropic (Claude)', models: [DEFAULT_MODEL] }], degraded: true };
    }

    degraded.style.display = catalog.degraded ? '' : 'none';
    container.innerHTML = MODEL_CONCERNS
        .map(c => _renderConcern(c, catalog.categories || []))
        .join('');
}

function closeModelsModal() {
    const modal = document.getElementById('models-modal');
    if (modal) modal.style.display = 'none';
}

/**
 * Read the checked radio per concern into selectedModels, persist to the
 * session's meta.json (when a DTXSID is resolved), and close.
 */
async function saveModelsModal() {
    for (const { key } of MODEL_CONCERNS) {
        const checked = document.querySelector(`input[name="model-${key}"]:checked`);
        if (checked) selectedModels[key] = checked.value;
    }

    const dtxsid = currentIdentity && currentIdentity.dtxsid;
    if (dtxsid) {
        try {
            await apiFetch(`/api/session/${dtxsid}/models`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(selectedModels),
            });
        } catch (e) {
            showToast(`Could not save model selection: ${e.message}`);
            // Keep the in-memory picks even if persistence failed.
        }
    }

    closeModelsModal();
    showToast('Model selection saved');
}
