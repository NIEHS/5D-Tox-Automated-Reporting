/* -----------------------------------------------------------------
 * main.js — DEPRECATED — split into domain modules
 *
 * This file previously contained all 135 application functions (7,037 lines).
 * It has been split into focused domain modules:
 *
 *   state.js          — global state variables and constants
 *   utils.js          — shared DOM helpers and utility functions
 *   login.js          — login gate and access control
 *   settings.js       — settings panel (BMD stats, dose unit, GO filters)
 *   layout.js         — tabbed/stacked view toggle, collapse/expand
 *   versions.js       — version history and style profile management
 *   export.js         — DOCX/PDF export, report preview, clipboard
 *   genomics.js       — genomics cards, GO term analysis, BMD summary
 *   genomics_charts.js — Plotly UMAP and cluster scatter charts
 *   filepool.js       — file upload, validation, BM2 cards, metadata
 *   sections.js       — section generation, approval, and workflows
 *   chemical.js       — chemical identity resolution and session restore
 *
 * This file is no longer loaded by index.html.  It is kept only as a
 * reference — it can be safely deleted.
 * ----------------------------------------------------------------- */
