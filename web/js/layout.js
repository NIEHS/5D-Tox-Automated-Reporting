// layout.js — Section collapse/expand, sidebar TOC navigation
//
// Manages the visual layout of the report page: collapsing/expanding
// sections, and the sidebar TOC navigation.
//
// The sidebar works like tabs — clicking a TOC node shows only that
// section in the content pane, hiding all others.  Alpine.js store
// drives visibility via x-show="$store.app.activeSection === '...'"
// on each content section.
//
// Globals used (defined elsewhere):
//   Alpine.store('app')      — Alpine store from state.js
//   renderReportTab          — function from export.js
//   renderGenomicsCharts     — function from genomics_charts.js

/* ================================================================
 * Collapsible sections — toggles the .collapsed class on the
 * nearest [data-collapsible] ancestor, hiding or showing the
 * .section-body.  Called from onclick on section headers.
 * ================================================================ */
function toggleSection(el) {
    // Walk up from the clicked element to find the collapsible container
    const section = el.closest('[data-collapsible]');
    if (section) section.classList.toggle('collapsed');
}

/* ================================================================
 * Collapse / Expand all — iterates every [data-collapsible]
 * section and adds or removes the .collapsed class.
 * ================================================================ */
function collapseAll() {
    document.querySelectorAll('[data-collapsible]').forEach(
        s => s.classList.add('collapsed')
    );
}

function expandAll() {
    document.querySelectorAll('[data-collapsible]').forEach(
        s => s.classList.remove('collapsed')
    );
}

/* ================================================================
 * Sidebar TOC Navigation — show a single section by its data-toc-id.
 *
 * Called from sidebar @click handlers.  Sets the Alpine store's
 * activeSection so only the matching content section is visible
 * (all others hide via x-show).  Also handles lazy-rendering of
 * the Report PDF and Genomics charts.
 *
 * For table-level children (e.g., "Table 2: Body Weights"), the
 * parent section is activated first, then the target sub-element
 * is scrolled into view within that section.
 * ================================================================ */

function navigateToNode(tocId) {
    if (!tocId) return;

    // Every TOC node — parent, child, or leaf — sets activeSection
    // directly to its own ID.  The HTML x-show expressions on each
    // content section decide what to display: parent groups show all
    // children, child IDs show only that one piece.
    if (typeof Alpine !== 'undefined' && Alpine.store('app')) {
        Alpine.store('app').activeSection = tocId;
    }

    // Hide the entire PDF preview pane on sections that have no
    // document content (Chemical ID, Data).  Show it on everything else.
    const noPreviewSections = ['chem-id', 'data'];
    const previewPane = document.getElementById('preview-pane');
    if (previewPane) {
        previewPane.style.display = noPreviewSections.includes(tocId) ? 'none' : '';
    }

    // --- Report PDF viewer ---
    // The PDF viewer is position:fixed and covers the viewport.
    // Expand it only when navigating to the Report section;
    // collapse it when navigating anywhere else.
    const pdfContainer = document.getElementById('report-pdf-container');
    if (pdfContainer) {
        if (tocId === 'report') {
            pdfContainer.classList.remove('collapsed');
            const btn = document.getElementById('btn-toggle-pdf');
            if (btn) { btn.innerHTML = '&#x25BC;'; btn.title = 'Collapse PDF viewer'; }
        } else {
            pdfContainer.classList.add('collapsed');
            const btn = document.getElementById('btn-toggle-pdf');
            if (btn) { btn.innerHTML = '&#x25B6;'; btn.title = 'Expand PDF viewer'; }
        }
    }

    // Lazy-render the Report PDF when navigating to it
    if (tocId === 'report' && typeof renderReportTab === 'function') {
        renderReportTab();
    }

    // Scroll the content pane to the top when switching views
    const pane = document.querySelector('.content-pane');
    if (pane) pane.scrollTop = 0;

    // --- Auto-compile PDF preview for the active TOC node ---
    // Skip non-document nodes (chem-id, data) — they have no PDF content.
    // For all document sections, compile a preview in the background.
    const NON_PREVIEW_NODES = new Set(['chem-id', 'data', 'report']);
    if (!NON_PREVIEW_NODES.has(tocId) && typeof compilePreviewForNode === 'function') {
        compilePreviewForNode(tocId);
    }
}


/**
 * Toggle the persistent PDF preview pane visibility.
 */
function togglePreviewPane() {
    if (typeof Alpine !== 'undefined' && Alpine.store('app')) {
        Alpine.store('app').previewVisible = !Alpine.store('app').previewVisible;
    }
}

/**
 * Toggle the HTML content pane visibility.
 */
function toggleContentPane() {
    if (typeof Alpine !== 'undefined' && Alpine.store('app')) {
        Alpine.store('app').contentVisible = !Alpine.store('app').contentVisible;
    }
}

/**
 * Recompile the preview for the current active section.
 */
function recompilePreview() {
    const tocId = Alpine?.store('app')?.activeSection;
    if (tocId && typeof compilePreviewForNode === 'function') {
        compilePreviewForNode(tocId, /* force */ true);
    }
}

/* ================================================================
 * initScrollSpy — no-op stub.
 *
 * Scroll spy is not needed in exclusive-section mode (only one
 * section visible at a time).  Kept as a no-op so chemical.js
 * doesn't error when calling it during init.
 * ================================================================ */
function initScrollSpy() {
    // No-op — exclusive section visibility replaces scroll spy.
}


/* ================================================================
 * Document tree fetch — load the serialized document structure
 * tree from /api/document-tree and store it in Alpine so all
 * frontend code can derive structure from the single source of
 * truth instead of hardcoding it.
 *
 * Called once on page load from initDocumentTree(), which is
 * invoked by the DOMContentLoaded handler in chemical.js.
 * ================================================================ */

/**
 * Render the TOC sidebar, Results containers, and M&M subsection stubs
 * from the document tree.  Called from alpine:init (in state.js) so the
 * DOM is populated BEFORE Alpine's first walk — this means Alpine
 * naturally processes the x-show, x-data, :class, @click, and x-collapse
 * directives without needing Alpine.initTree() on dynamic content.
 *
 * The tree is injected by the server as window.__DOCUMENT_TREE__ in a
 * <script> tag in <head>, so it's available synchronously.
 *
 * Safe to call multiple times — subsequent calls are no-ops.
 */
function initDocumentTree() {
    // Use the server-injected tree (synchronous, no fetch needed).
    // Falls back to the API endpoint if the injection is missing
    // (shouldn't happen, but defensive).
    const tree = window.__DOCUMENT_TREE__;
    if (!tree || tree.length === 0) {
        console.warn('Document tree not injected — TOC will be empty');
        return;
    }

    // Store in Alpine if available (may not be during alpine:init)
    if (typeof Alpine !== 'undefined' && Alpine.store('app')) {
        Alpine.store('app').documentTree = tree;
    }

    // Generate the TOC sidebar, Results containers, and M&M stubs.
    // These populate the DOM with Alpine-directive elements BEFORE
    // Alpine's first walk, so they get processed naturally.
    if (typeof renderTocFromTree === 'function') {
        renderTocFromTree(tree);
    }
    if (typeof renderResultsFromTree === 'function') {
        renderResultsFromTree(tree);
    }
    if (typeof renderMethodsSubsectionsFromTree === 'function') {
        renderMethodsSubsectionsFromTree(tree);
    }

    // Invalidate the PLATFORM_TO_READY cache so it rebuilds from
    // the now-loaded tree on next access.
    window._platformToReadyCache = null;
}


/* ================================================================
 * TOC sidebar rendering — generate the entire sidebar navigation
 * from the document tree, replacing ~210 lines of hardcoded HTML.
 * ================================================================ */

/**
 * Generate the complete TOC sidebar from the document tree.
 *
 * The tree is organized into visual groups that match the NIEHS
 * report structure:
 *   - Front Matter (cover, title-page, foreword, etc.) — collapsed
 *   - Body sections (background, methods, results) — methods/results collapsible
 *   - Summary, References
 *   - Appendices — collapsed
 *
 * Special behaviors:
 *   - Methods: "Full Section" link + deep H2/H3 hierarchy
 *   - Results children with sub-tables: parent highlights when any
 *     child is active (active-array pattern)
 *   - Genomics sections: preserve child UL containers for dynamic children
 *   - Table nodes: prefixed with "Table N: " from table_number
 *   - ready_key: disabled styling when the section isn't ready
 *
 * @param {Array} tree — serialized document tree from /api/document-tree
 */
function renderTocFromTree(tree) {
    const container = document.getElementById('toc-tree-container');
    if (!container) return;
    container.innerHTML = '';

    // --- Group the tree nodes into visual categories ---
    // Front matter: all nodes before "background" (level 0 or 1, types cover/title-page/front-matter/tables-list)
    // Body: background through references
    // Appendices: appendix-* nodes
    const frontMatter = [];
    const body = [];
    const appendices = [];

    // State machine: scan top-level nodes and classify
    let phase = 'front';  // front → body → appendix
    for (const node of tree) {
        if (node.id === 'background') phase = 'body';
        if (node.type === 'appendix') phase = 'appendix';

        if (phase === 'front') frontMatter.push(node);
        else if (phase === 'appendix') appendices.push(node);
        else body.push(node);
    }

    // --- Front Matter (collapsible) ---
    if (frontMatter.length > 0) {
        container.appendChild(_buildCollapsibleGroup('Front Matter', frontMatter, false));
    }

    // --- Body sections ---
    for (const node of body) {
        if (node.id === 'methods') {
            // Methods: collapsible with deep hierarchy + "Full Section" link
            container.appendChild(_buildMethodsTocNode(node));
        } else if (node.id === 'results') {
            // Results: collapsible (starts expanded), special child handling
            container.appendChild(_buildResultsTocNode(node));
        } else {
            // Simple body nodes (background, summary, references)
            container.appendChild(_buildSimpleTocNode(node));
        }
    }

    // --- Appendices (collapsible) ---
    if (appendices.length > 0) {
        // Strip "Appendix X. " prefix for shorter sidebar labels
        const shortAppendices = appendices.map(n => ({
            ...n,
            _shortTitle: n.title.replace(/^Appendix [A-Z]\.\s*/, ''),
            _prefix: n.title.match(/^(Appendix [A-Z])\./)?.[1] || '',
        }));
        const groupLi = document.createElement('li');
        groupLi.setAttribute('x-data', '{ expanded: false }');
        groupLi.innerHTML = `
            <a class="toc-node toc-parent" @click="expanded = !expanded">
                <span class="chevron" :class="{ expanded }">▸</span> Appendices
            </a>`;
        const ul = document.createElement('ul');
        ul.setAttribute('x-show', 'expanded');
        ul.setAttribute('x-collapse', '');
        for (const n of shortAppendices) {
            const li = document.createElement('li');
            const label = n._prefix ? `${n._prefix.slice(-1)}. ${n._shortTitle}` : n._shortTitle;
            li.innerHTML = `<a class="toc-leaf"
                :class="{ active: $store.app.activeSection === '${n.id}' }"
                @click="navigateToNode('${n.id}')">${_escToc(label)}</a>`;
            ul.appendChild(li);
        }
        groupLi.appendChild(ul);
        container.appendChild(groupLi);
    }

    // "Genomics Charts" is now in the document tree (charts DocNode under
    // Results) — renderTocFromTree() generates its TOC entry automatically.
    // No hardcoded extra node needed.
}

/**
 * Build a collapsible group node (Front Matter, Appendices pattern).
 * Shows a parent label with chevron; children are leaf links.
 */
function _buildCollapsibleGroup(label, nodes, startExpanded) {
    const li = document.createElement('li');
    li.setAttribute('x-data', `{ expanded: ${startExpanded} }`);
    li.innerHTML = `
        <a class="toc-node toc-parent" @click="expanded = !expanded">
            <span class="chevron" :class="{ expanded }">▸</span> ${_escToc(label)}
        </a>`;
    const ul = document.createElement('ul');
    ul.setAttribute('x-show', 'expanded');
    ul.setAttribute('x-collapse', '');
    for (const node of nodes) {
        const childLi = document.createElement('li');
        childLi.innerHTML = `<a class="toc-node"
            :class="{ active: $store.app.activeSection === '${node.id}' }"
            @click="navigateToNode('${node.id}')">${_escToc(node.title)}</a>`;
        ul.appendChild(childLi);
    }
    li.appendChild(ul);
    return li;
}

/**
 * Build a simple leaf TOC node (background, summary, references).
 * Adds disabled state if the node has a ready_key.
 */
function _buildSimpleTocNode(node) {
    const li = document.createElement('li');
    const readyGuard = node.ready_key
        ? `disabled: !$store.app.ready.${node.ready_key}`
        : '';
    const clickGuard = node.ready_key
        ? `$store.app.ready.${node.ready_key} && navigateToNode('${node.id}')`
        : `navigateToNode('${node.id}')`;
    li.innerHTML = `<a class="toc-node"
        :class="{ active: $store.app.activeSection === '${node.id}'${readyGuard ? ', ' + readyGuard : ''} }"
        @click="${clickGuard}">${_escToc(node.title)}</a>`;
    return li;
}

/**
 * Build the Materials and Methods TOC node — collapsible with
 * "Full Section" link and deep H2/H3 hierarchy matching the
 * NIEHS report structure.
 */
function _buildMethodsTocNode(node) {
    const li = document.createElement('li');
    li.setAttribute('x-data', '{ expanded: false }');
    li.innerHTML = `
        <a class="toc-node toc-parent" :class="{ disabled: !$store.app.ready.methods }"
           @click="expanded = !expanded">
            <span class="chevron" :class="{ expanded }">▸</span> ${_escToc(node.title)}
        </a>`;

    const ul = document.createElement('ul');
    ul.setAttribute('x-show', 'expanded');
    ul.setAttribute('x-collapse', '');

    // "Full Section" link — navigates to the parent methods section
    const fullLi = document.createElement('li');
    fullLi.innerHTML = `<a class="toc-node"
        :class="{ active: $store.app.activeSection === 'methods', disabled: !$store.app.ready.methods }"
        @click="$store.app.ready.methods && navigateToNode('methods')">Full Section</a>`;
    ul.appendChild(fullLi);

    // Recursively build children (H2 → H3 hierarchy)
    if (node.children) {
        _buildMethodsChildren(ul, node.children);
    }

    li.appendChild(ul);
    return li;
}

/**
 * Recursively build Methods TOC children.  Nodes with children
 * become collapsible sub-groups; leaf nodes are simple links.
 */
function _buildMethodsChildren(parentUl, children) {
    for (const child of children) {
        const li = document.createElement('li');

        if (child.children && child.children.length > 0) {
            // Heading-only node with sub-sections — collapsible
            li.setAttribute('x-data', '{ ex: false }');
            li.innerHTML = `<a class="toc-leaf toc-parent" @click="ex = !ex">
                <span class="chevron" :class="{ expanded: ex }">▸</span> ${_escToc(child.title)}</a>`;
            const subUl = document.createElement('ul');
            subUl.setAttribute('x-show', 'ex');
            subUl.setAttribute('x-collapse', '');
            _buildMethodsChildren(subUl, child.children);
            li.appendChild(subUl);
        } else {
            // Leaf M&M subsection
            li.innerHTML = `<a class="toc-leaf"
                :class="{ active: $store.app.activeSection === '${child.id}' }"
                @click="navigateToNode('${child.id}')">${_escToc(child.title)}</a>`;
        }
        parentUl.appendChild(li);
    }
}

/**
 * Build the Results TOC node — collapsible (starts expanded),
 * with special handling for narrative+tables groups that highlight
 * when any child table is active.
 */
function _buildResultsTocNode(node) {
    const li = document.createElement('li');
    li.setAttribute('x-data', '{ expanded: true }');
    li.setAttribute('data-toc-group', 'results');
    li.innerHTML = `
        <a class="toc-node toc-parent" @click="expanded = !expanded">
            <span class="chevron" :class="{ expanded }">▸</span> Results
        </a>`;

    const ul = document.createElement('ul');
    ul.setAttribute('x-show', 'expanded');
    ul.setAttribute('x-collapse', '');

    for (const child of (node.children || [])) {
        const childLi = document.createElement('li');
        const readyExpr = child.ready_key
            ? `!$store.app.ready.${child.ready_key}` : '';
        const clickGuard = child.ready_key
            ? `$store.app.ready.${child.ready_key} && navigateToNode('${child.id}')`
            : `navigateToNode('${child.id}')`;

        if (child.children && child.children.length > 0) {
            // Group node (narrative+tables) — parent highlights when
            // itself or any child table is active
            const allIds = collectGroupIds(child);
            const activeExpr = `[${allIds.map(id => `'${id}'`).join(',')}].includes($store.app.activeSection)`;

            childLi.innerHTML = `<a class="toc-node"
                :class="{ active: ${activeExpr}${readyExpr ? ', disabled: ' + readyExpr : ''} }"
                @click="${clickGuard}">${_escToc(child.title)}</a>`;

            // Child table nodes — each checks per-platform availability
            // so only tables with actual data are clickable.  If the
            // node has a `platform` field, use ready.platform['X'];
            // otherwise fall back to the group's ready_key.
            const childUl = document.createElement('ul');
            for (const tableNode of child.children) {
                const tableLi = document.createElement('li');
                // Table nodes get "Table N: Title" prefix from table_number
                const tableLabel = tableNode.table_number
                    ? `Table ${tableNode.table_number}: ${tableNode.title}`
                    : tableNode.title;

                // Per-platform check: prefer platform-specific flag over
                // group-level ready_key.  This ensures that uploading
                // Hematology alone doesn't enable Clinical Chemistry.
                let tReadyExpr, tClickGuard;
                if (tableNode.platform) {
                    // Platform names may contain spaces (e.g., "Body Weight")
                    // so we use bracket notation for the Alpine expression.
                    tReadyExpr = `, disabled: !$store.app.ready.platform['${tableNode.platform}']`;
                    tClickGuard = `$store.app.ready.platform['${tableNode.platform}'] && navigateToNode('${tableNode.id}')`;
                } else if (tableNode.ready_key) {
                    tReadyExpr = `, disabled: !$store.app.ready.${tableNode.ready_key}`;
                    tClickGuard = `$store.app.ready.${tableNode.ready_key} && navigateToNode('${tableNode.id}')`;
                } else {
                    tReadyExpr = '';
                    tClickGuard = `navigateToNode('${tableNode.id}')`;
                }

                tableLi.innerHTML = `<a class="toc-leaf"
                    :class="{ active: $store.app.activeSection === '${tableNode.id}'${tReadyExpr} }"
                    @click="${tClickGuard}">${_escToc(tableLabel)}</a>`;
                childUl.appendChild(tableLi);
            }
            childLi.appendChild(childUl);
        } else {
            // Leaf Results node (bmd-summary, genomics sections)
            childLi.innerHTML = `<a class="toc-node"
                :class="{ active: $store.app.activeSection === '${child.id}'${readyExpr ? ', disabled: ' + readyExpr : ''} }"
                @click="${clickGuard}">${_escToc(child.title)}</a>`;

            // Genomics sections get a dynamic child UL for organ/sex sub-entries
            if (child.type === 'genomics-section') {
                const dynUl = document.createElement('ul');
                dynUl.id = child.id === 'gene-sets' ? 'toc-gene-set-children'
                         : child.id === 'gene-bmd'  ? 'toc-gene-bmd-children'
                         : `toc-${child.id}-children`;
                childLi.appendChild(dynUl);
            }
        }
        ul.appendChild(childLi);
    }

    li.appendChild(ul);
    return li;
}

/**
 * Escape HTML entities in TOC labels to prevent XSS from
 * tree node titles (which come from the server).
 */
function _escToc(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}


/* ================================================================
 * Methods subsection rendering — generate individual M&M
 * subsection stubs from the document tree, replacing ~50 lines
 * of hardcoded HTML divs.
 * ================================================================ */

/**
 * Generate M&M individual subsection views from the document tree.
 *
 * Each subsection is a simple div with x-show for its node ID and
 * a heading matching the tree title.  These are the stubs that show
 * when clicking a specific M&M subsection in the TOC (e.g., "Study
 * Design", "Clinical Observations").
 *
 * @param {Array} tree — serialized document tree
 */
function renderMethodsSubsectionsFromTree(tree) {
    const container = document.getElementById('methods-subsections-container');
    if (!container) return;
    container.innerHTML = '';

    // Find the "methods" node in the tree
    const methodsNode = tree.find(n => n.id === 'methods');
    if (!methodsNode || !methodsNode.children) return;

    // Recursively collect all leaf and heading-only children
    function walkChildren(nodes) {
        for (const node of nodes) {
            // Skip the parent "methods" node itself — we only want children
            const div = document.createElement('div');
            div.className = 'front-matter-section';
            div.setAttribute('x-data', '');
            div.setAttribute('x-show', `$store.app.activeSection === '${node.id}'`);

            // Use the heading level from the tree (2 → h2, 3 → h3)
            const hTag = node.level <= 2 ? 'h2' : 'h3';
            const heading = document.createElement(hTag);
            heading.textContent = node.title;
            div.appendChild(heading);

            container.appendChild(div);

            // Recurse into children (e.g., Clinical Examinations > Clinical Observations)
            if (node.children && node.children.length > 0) {
                walkChildren(node.children);
            }
        }
    }

    walkChildren(methodsNode.children);
}


/* ================================================================
 * Results container rendering — generate the narrative+tables
 * group containers from the document tree, replacing ~60 lines
 * of hardcoded HTML per group.
 *
 * Only generates the apical results groups (narrative+tables type).
 * BMD summary, genomics, and charts sections stay as static HTML
 * because they have complex internal UI.
 * ================================================================ */

/**
 * Generate Results section containers from the document tree.
 *
 * For each "narrative+tables" group node under Results, creates:
 *   - A .results-group div with x-show visibility for group + child IDs
 *   - An h2 heading (visible only when viewing the whole group)
 *   - A unified narrative textarea (visible only at group level)
 *   - A .platform-container div for each child table node
 *   - Legacy fallback containers for known platform aliases
 *
 * @param {Array} tree — serialized document tree from /api/document-tree
 */
function renderResultsFromTree(tree) {
    const container = document.getElementById('results-apical-container');
    if (!container) return;
    container.innerHTML = '';

    // Find the "results" top-level node
    const resultsNode = tree.find(n => n.id === 'results');
    if (!resultsNode || !resultsNode.children) return;

    // Legacy platform aliases — when a child has platform "Organ Weight",
    // also create a hidden container for "Organ Weights" (plural).
    // Similarly, "Clinical Observations" also gets a "Clinical" fallback.
    const LEGACY_ALIASES = {
        'Organ Weight': ['Organ Weights'],
        'Clinical Observations': ['Clinical'],
    };

    // Map from narrative_key to the narrative ID used by the textarea.
    // The pipeline populates unified_narratives with keys like "animal_condition",
    // but the textarea IDs historically use "narrative-apical" for animal_condition.
    // This mapping preserves backward compatibility with existing session data.
    const NARRATIVE_ID_MAP = {
        'animal_condition': 'apical',
        // All other narrative_keys use their own name as the textarea ID suffix
    };

    for (const group of resultsNode.children) {
        // Only generate containers for narrative+tables groups
        if (group.type !== 'narrative+tables') continue;
        if (!group.children || group.children.length === 0) continue;

        // Build the list of IDs that should show this group
        // (the group ID + all child table IDs)
        const allIds = collectGroupIds(group);
        const showExpr = `[${allIds.map(id => `'${id}'`).join(',')}].includes($store.app.activeSection)`;

        // Create the group container div
        const groupDiv = document.createElement('div');
        groupDiv.className = 'results-group';
        groupDiv.id = `section-${group.id}`;
        groupDiv.setAttribute('data-toc-id', group.id);
        groupDiv.setAttribute('x-data', '');
        groupDiv.setAttribute('x-show', showExpr);
        groupDiv.style.display = 'none';

        // Group heading — only visible when viewing the whole group
        const h2 = document.createElement('h2');
        h2.setAttribute('x-show', `$store.app.activeSection === '${group.id}'`);
        h2.textContent = group.title;
        groupDiv.appendChild(h2);

        // Unified narrative textarea — only visible at group level
        if (group.narrative_key) {
            const narrativeId = NARRATIVE_ID_MAP[group.narrative_key] || group.narrative_key;
            const textarea = document.createElement('textarea');
            textarea.className = 'unified-narrative';
            textarea.id = `narrative-${narrativeId}`;
            textarea.rows = 6;
            textarea.setAttribute('x-show', `$store.app.activeSection === '${group.id}'`);
            textarea.placeholder = 'Unified narrative populated after processing...';
            groupDiv.appendChild(textarea);
        }

        // Platform containers for each child table node
        for (const child of group.children) {
            if (!child.platform) continue;

            const platDiv = document.createElement('div');
            platDiv.className = 'platform-container';
            platDiv.setAttribute('data-toc-id', child.id);
            platDiv.setAttribute('data-platform', child.platform);
            platDiv.setAttribute('x-show',
                `$store.app.activeSection === '${group.id}' || $store.app.activeSection === '${child.id}'`);

            // Table heading with number prefix from the tree
            const h3 = document.createElement('h3');
            h3.textContent = child.table_number
                ? `Table ${child.table_number}: ${child.title}`
                : child.title;
            platDiv.appendChild(h3);
            groupDiv.appendChild(platDiv);

            // Legacy fallback containers — hidden divs that exist so
            // getPlatformContainer() can find them by data-platform
            const aliases = LEGACY_ALIASES[child.platform] || [];
            for (const alias of aliases) {
                const fallback = document.createElement('div');
                fallback.className = 'platform-container';
                fallback.setAttribute('data-platform', alias);
                fallback.style.display = 'none';
                groupDiv.appendChild(fallback);
            }
        }

        container.appendChild(groupDiv);
    }
}


/* ================================================================
 * Tree utility functions — walk the document tree to extract
 * structural information that was previously hardcoded.
 * ================================================================ */

/**
 * Find a node by ID anywhere in the tree.
 *
 * @param {string} nodeId — the node ID to find
 * @param {Array} [tree] — tree to search (defaults to Alpine store)
 * @returns {Object|null} — the node, or null if not found
 */
function findTreeNode(nodeId, tree) {
    if (!tree) tree = Alpine.store('app').documentTree;
    for (const node of tree) {
        if (node.id === nodeId) return node;
        if (node.children) {
            const found = findTreeNode(nodeId, node.children);
            if (found) return found;
        }
    }
    return null;
}

/**
 * Walk the Results subtree and build a map from platform string
 * to the parent group's ready_key.
 *
 * Replaces the hardcoded PLATFORM_TO_READY map in cards.js.
 *
 * @param {Array} [tree] — document tree (defaults to Alpine store)
 * @returns {Object} — e.g. {"Body Weight": "animalCondition", ...}
 */
function buildPlatformToReady(tree) {
    if (!tree) tree = Alpine.store('app').documentTree;
    const map = {};
    const resultsNode = tree.find(n => n.id === 'results');
    if (!resultsNode || !resultsNode.children) return map;

    for (const group of resultsNode.children) {
        // The ready_key on the group (or its children) tells us
        // which Alpine store flag controls visibility.
        const groupReady = group.ready_key;
        if (!groupReady) continue;

        // Map each child platform to the group's ready_key
        if (group.children) {
            for (const child of group.children) {
                if (child.platform) {
                    map[child.platform] = groupReady;
                    // Legacy compat: "Clinical Observations" also matches "Clinical"
                    if (child.platform === 'Clinical Observations') {
                        map['Clinical'] = groupReady;
                    }
                    // Legacy compat: "Organ Weight" also matches "Organ Weights"
                    if (child.platform === 'Organ Weight') {
                        map['Organ Weights'] = groupReady;
                    }
                }
            }
        }
        // Non-table nodes (bmd-summary, genomics) may have ready_key
        // directly on the group node with no children platforms.
    }
    return map;
}

/**
 * Walk the Results subtree and collect platform strings in
 * document order.  Replaces the hardcoded domainOrder array
 * in pipeline.js.
 *
 * @param {Array} [tree] — document tree (defaults to Alpine store)
 * @returns {string[]} — platforms in document order
 */
function collectPlatformOrder(tree) {
    if (!tree) tree = Alpine.store('app').documentTree;
    const platforms = [];
    const resultsNode = tree.find(n => n.id === 'results');
    if (!resultsNode || !resultsNode.children) return platforms;

    for (const group of resultsNode.children) {
        if (group.children) {
            for (const child of group.children) {
                if (child.platform) {
                    platforms.push(child.platform);
                }
            }
        }
    }
    return platforms;
}

/**
 * For a given group node, collect the IDs of the node itself
 * plus all direct children — used to build x-show visibility
 * arrays for Results group containers.
 *
 * @param {Object} node — a group node from the tree
 * @returns {string[]} — [node.id, child1.id, child2.id, ...]
 */
function collectGroupIds(node) {
    const ids = [node.id];
    if (node.children) {
        for (const child of node.children) {
            ids.push(child.id);
        }
    }
    return ids;
}
