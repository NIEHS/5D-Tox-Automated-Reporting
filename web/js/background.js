/* -----------------------------------------------------------------
 * background.js — Background section generation, display, and approval
 *
 * Split from sections.js.  Implements the generate → display → edit →
 * approve lifecycle for the Background section: SSE-streamed LLM
 * generation, editable paragraph display, approval with style learning,
 * and retry/edit workflows.
 *
 * Depends on: state.js (globals), utils.js (helpers), export.js,
 *             versions.js (showVersionHistory, loadStyleProfile)
 * ----------------------------------------------------------------- */

/* ================================================================
 * Generate background — POST /api/generate with SSE progress
 * ================================================================ */

async function generateBackground() {
    if (isGenerating) return;

    // Build identity from form fields if not already resolved
    if (!currentIdentity) {
        currentIdentity = {
            name: document.getElementById('name').value.trim(),
            casrn: document.getElementById('casrn').value.trim(),
            dtxsid: document.getElementById('dtxsid').value.trim(),
            pubchem_cid: parseInt(document.getElementById('cid').value.trim()) || 0,
            ec_number: document.getElementById('ec').value.trim(),
        };
    }

    if (!currentIdentity.name && !currentIdentity.casrn) {
        showError('Enter at least a chemical name or CASRN.');
        return;
    }

    isGenerating = true;
    hideError();
    hideOutput();
    showProgress();

    const btn = document.getElementById('btn-generate');
    btn.disabled = true;
    btn.textContent = 'Generating...';

    const modelSelect = document.getElementById('model-select');
    const useOllama = modelSelect.value === 'ollama';

    try {
        const resp = await fetch('/api/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                identity: currentIdentity,
                use_ollama: useOllama,
            }),
        });

        // Read SSE stream
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });

            // Parse complete SSE events from the buffer
            const events = buffer.split('\n\n');
            // Keep the last (possibly incomplete) event in the buffer
            buffer = events.pop() || '';

            for (const eventStr of events) {
                if (!eventStr.trim()) continue;

                const lines = eventStr.trim().split('\n');
                let eventType = '';
                let eventData = '';

                for (const line of lines) {
                    if (line.startsWith('event: ')) {
                        eventType = line.slice(7);
                    } else if (line.startsWith('data: ')) {
                        eventData = line.slice(6);
                    }
                }

                // Wrap each JSON.parse in try-catch so one malformed SSE
                // event doesn't crash the entire stream parser.
                try {
                    if (eventType === 'progress') {
                        const data = JSON.parse(eventData);
                        addProgressLog(data.message);
                    } else if (eventType === 'complete') {
                        currentResult = JSON.parse(eventData);
                        displayResult(currentResult);
                        hideProgress();
                        markReportDirty();
                        // Auto-save to disk so the generation survives a
                        // page reload without requiring the user to click
                        // Approve.  Approval remains a separate UI lock.
                        autoSaveBackground(currentResult);
                    } else if (eventType === 'error') {
                        const data = JSON.parse(eventData);
                        showError(data.error);
                        hideProgress();
                    }
                } catch (parseErr) {
                    console.error('SSE parse error:', parseErr, 'raw:', eventData);
                }
            }
        }

    } catch (err) {
        showError('Generation failed: ' + err.message);
        hideProgress();
    } finally {
        isGenerating = false;
        btn.disabled = false;
        btn.textContent = 'Generate Background';
    }
}

/* ================================================================
 * Auto-save (no approval) — persist generated content to disk
 * ================================================================ */

/**
 * Write the freshly-generated background to disk with approved=false.
 *
 * Called from the SSE complete handler so a page reload always restores
 * the latest content even if the user hasn't approved yet.  Approval
 * is a separate UI concern: it locks the editor and applies style
 * learning; persistence happens automatically.
 */
async function autoSaveBackground(result) {
    if (!currentIdentity?.dtxsid) return;
    try {
        await fetch('/api/session/save-section', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                dtxsid: currentIdentity.dtxsid,
                section_type: 'background',
                approved: false,
                data: {
                    paragraphs: result.paragraphs || [],
                    references: result.references || [],
                    abstract_background: result.abstract_background || '',
                    model_used: result.model_used || '',
                    notes: result.notes || [],
                    raw_data: result.raw_data || null,
                },
            }),
        });
    } catch (e) {
        console.warn('Auto-save background failed:', e);
    }
}


/* ================================================================
 * Display the generated result
 * ================================================================ */

function displayResult(result) {
    const proseEl = document.getElementById('output-prose');
    const refsEl = document.getElementById('references-list');
    const metaEl = document.getElementById('meta-info');
    const notesPanel = document.getElementById('notes-panel');
    const notesList = document.getElementById('notes-list');

    // Clear previous output
    proseEl.innerHTML = '';
    refsEl.innerHTML = '';

    // Render paragraphs as editable blocks
    (result.paragraphs || []).forEach((para, i) => {
        const div = document.createElement('div');
        div.className = 'paragraph';
        div.contentEditable = 'true';
        // Convert [N] markers to <sup> tags for display
        div.innerHTML = para.replace(
            /\[(\d+(?:[,\-\u2013]\d+)*)\]/g,
            '<sup>[$1]</sup>'
        );
        proseEl.appendChild(div);
    });

    // Render references
    (result.references || []).forEach(ref => {
        const div = document.createElement('div');
        div.textContent = ref;
        div.contentEditable = 'true';
        refsEl.appendChild(div);
    });

    // Show metadata
    metaEl.textContent = `Model: ${result.model_used || 'unknown'} | ` +
        `~${result.prompt_tokens_approx || '?'} prompt tokens`;

    // Show notes/warnings if any
    const notes = result.notes || [];
    if (notes.length > 0) {
        notesList.innerHTML = '';
        notes.forEach(note => {
            const li = document.createElement('li');
            li.textContent = note;
            notesList.appendChild(li);
        });
        notesPanel.classList.add('visible');
    } else {
        notesPanel.classList.remove('visible');
    }

    document.getElementById('output-section').classList.add('visible');

    // Save original LLM-generated text for later comparison.
    // When the user approves, we send both original and (possibly
    // edited) text to the server so it can detect edits and learn
    // writing style preferences from the differences.
    currentResult.originalParagraphs = [...(result.paragraphs || [])];
    currentResult.originalReferences = [...(result.references || [])];

    // Show action buttons (they're hidden until generation).
    setButtons('bg', 'result');

    // Reset approval state — new generation means unapproved
    backgroundApproved = false;
    unlockSection(document.getElementById('output-section'));

    // Show the data tab now that background is done — set the Alpine
    // store flag so the Data section becomes visible via x-show.
    if (typeof Alpine !== 'undefined' && Alpine.store('app')) {
        Alpine.store('app').ready.data = true;
    }

    // Generating background also confirms identity — enable
    // Process/Export buttons if they were still disabled
    onIdentityResolved();

    // Update export button state (background is now unapproved)
    updateExportButton();
}

/* ================================================================
 * Approve / Try Again — background section
 * ================================================================ */

/**
 * Approve the background section: POST the current paragraphs and
 * references to /api/session/approve, lock the section for editing,
 * and show the green "Approved" visual state.
 */
async function approveBackground() {
    // Collect current editable text (user may have polished it)
    const refsEl = document.getElementById('references-list');
    const paragraphs = extractProse('output-prose');
    const references = Array.from(refsEl.querySelectorAll('div'))
        .map(div => div.textContent.trim());

    const result = await postApproveToServer(
        'background',
        document.getElementById('output-section'),
        'bg',
        {
            paragraphs,
            references,
            // Include originals so the server can detect edits
            // and extract writing style rules from the diff
            original_paragraphs: currentResult?.originalParagraphs || [],
            original_references: currentResult?.originalReferences || [],
            model_used: currentResult?.model_used || '',
            notes: currentResult?.notes || [],
            // Persist the LLM-generated Abstract Background distillation
            // so the abstract section survives session reloads and flows
            // into PDF/DOCX exports without re-running the LLM.
            abstract_background: currentResult?.abstract_background || '',
        },
    );
    if (!result) return;

    backgroundApproved = true;

    // If the user edited the text, show a blue "Approved (edited)"
    // badge and a toast indicating style learning is in progress
    const badge = document.getElementById('badge-bg');
    if (result.user_edited) {
        badge.textContent = 'Approved (edited)';
        badge.classList.add('edited');
        // Reload style profile after a short delay (extraction
        // runs asynchronously on the server)
        setTimeout(() => loadStyleProfile(), 3000);
    } else {
        badge.textContent = 'Approved';
        badge.classList.remove('edited');
    }

    // Show version history button with the server-assigned version number
    showVersionHistory('background', result.version);

    // Show the Materials and Methods section now that background
    // is approved — it appears between Background and Results
    showMethodsSection();

    // Also show the Summary section — it synthesizes all sections
    showSummarySection();
}

/**
 * Try Again on background: unapprove the section on the server,
 * then regenerate a fresh background.  The old approved content
 * is replaced by the new generation.
 */
async function retryBackground() {
    if (currentIdentity?.dtxsid) {
        // Tell the server to delete the saved background section
        try {
            await fetch('/api/session/unapprove', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    dtxsid: currentIdentity.dtxsid,
                    section_type: 'background',
                }),
            });
        } catch (_) {
            // Non-critical — we'll regenerate regardless
        }
    }

    // Reset approval state and unlock the section for editing
    backgroundApproved = false;
    markReportDirty();
    unlockSection(document.getElementById('output-section'));
    setButtons('bg', 'editing');

    // Hide version history — regenerating from scratch
    hideVersionHistory('background');

    updateExportButton();

    // Regenerate fresh content
    generateBackground();
}

/**
 * Edit the background section: unlock paragraphs and references
 * for editing, remove the approved state, and re-show the Approve
 * button so the user can re-approve after making changes.
 *
 * This does NOT unapprove on the server — the user can edit and
 * then re-approve, which will detect any differences from the
 * original LLM output and trigger style learning.
 */
function editBackground() {
    // Unlock the section — re-enable editing on paragraphs and references
    backgroundApproved = false;
    markReportDirty();
    unlockSection(document.getElementById('output-section'));
    setButtons('bg', 'editing');
    updateExportButton();
    showToast('Editing enabled — click Approve when done');
}
