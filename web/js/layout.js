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

    // Lazy-render genomics charts when navigating to the Charts section
    if (tocId === 'charts' && typeof renderGenomicsCharts === 'function') {
        renderGenomicsCharts();
    }

    // Scroll the content pane to the top when switching views
    const pane = document.querySelector('.content-pane');
    if (pane) pane.scrollTop = 0;
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
