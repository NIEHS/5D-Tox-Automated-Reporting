// layout.js — Section collapse/expand, tabbed/stacked view toggle, tab bar
//
// Extracted from main.js.  These functions manage the visual layout of the
// report page: collapsing/expanding sections, and switching between the
// default stacked layout and a tabbed layout where only one section is
// visible at a time.
//
// Globals used (defined elsewhere):
//   tabbedViewActive  — boolean from state.js
//   renderReportTab   — function from report rendering module
//   renderGenomicsCharts — function from genomics_charts.js

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
 * Tabbed view — switches between stacked (default) and tabbed
 * layout.  In tabbed mode, a tab bar shows one button per visible
 * section.  Clicking a tab shows only that section's panel.
 *
 * The .tabbed-view class on .container drives all CSS changes:
 *   - tab bar becomes visible
 *   - sections are hidden unless they have .tab-active
 *   - chevrons and collapse/expand buttons are hidden
 * ================================================================ */

/* Toggle between stacked and tabbed modes */
function toggleTabbedView() {
    tabbedViewActive = !tabbedViewActive;
    const container = document.querySelector('.container');
    const btn = document.getElementById('btn-tabbed-view');

    if (tabbedViewActive) {
        container.classList.add('tabbed-view');
        btn.classList.add('active');
        // Label tells the user what they'll switch TO on click
        btn.textContent = 'Stacked View';
        // Expand all sections so content is visible inside tabs
        document.querySelectorAll('[data-collapsible]').forEach(
            s => s.classList.remove('collapsed')
        );
        buildTabBar();
    } else {
        container.classList.remove('tabbed-view');
        btn.classList.remove('active');
        btn.textContent = 'Tabbed View';
        // Remove tab-active from all sections so normal display
        // rules (style="display:none" etc.) take over again
        document.querySelectorAll('[data-tab-section]').forEach(
            s => s.classList.remove('tab-active')
        );
    }
}

/* Build (or rebuild) the tab bar buttons from visible sections.
   Only sections that are not hidden via style="display:none" get
   a tab.  This should be called whenever a section becomes visible
   (e.g., after background generation reveals the Data tab). */
function buildTabBar() {
    const bar = document.getElementById('tab-bar');
    bar.innerHTML = '';
    const sections = document.querySelectorAll('[data-tab-section]');
    let firstVisible = null;
    let hasActive = false;

    sections.forEach(section => {
        // Skip sections hidden by the app (style.display === 'none')
        // but NOT sections hidden by tabbed-view CSS (which uses a class).
        // Check the inline style specifically.
        if (section.style.display === 'none') return;

        const label = section.getAttribute('data-tab-section');
        const btn = document.createElement('button');
        btn.textContent = label;
        btn.onclick = () => activateTab(label);
        bar.appendChild(btn);

        if (!firstVisible) firstVisible = label;

        // Preserve current active tab if it's still visible
        if (section.classList.contains('tab-active')) {
            btn.classList.add('active');
            hasActive = true;
        }
    });

    // If no tab was active (first time or previous tab hidden),
    // activate the first visible one
    if (!hasActive && firstVisible) {
        activateTab(firstVisible);
    }
}

/* Switch to a specific tab — show that section, hide all others.
   When the Report tab is activated, lazily render the NIEHS-styled
   document from current approval state (avoids re-rendering on every
   approval change when the user isn't looking at the Report tab). */
function activateTab(label) {
    document.querySelectorAll('[data-tab-section]').forEach(section => {
        if (section.getAttribute('data-tab-section') === label) {
            section.classList.add('tab-active');
        } else {
            section.classList.remove('tab-active');
        }
    });

    // Update tab bar button active states
    const bar = document.getElementById('tab-bar');
    bar.querySelectorAll('button').forEach(btn => {
        btn.classList.toggle('active', btn.textContent === label);
    });

    // Lazy-render the Report tab when the user switches to it
    if (label === 'Report') renderReportTab();

    // Lazy-render genomics charts when the Charts tab is activated.
    // renderGenomicsCharts() is defined in genomics_charts.js and
    // reads from the global genomicsResults dict.
    if (label === 'Charts' && typeof renderGenomicsCharts === 'function') {
        renderGenomicsCharts();
    }
}
