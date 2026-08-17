# 0007 — In-app HTML live view + PDF view (local compile + reference compare)

- **Status:** **Partially implemented (verified 2026-08-17).** The in-app HTML
  live view shipped — `/api/preview-latex-html` renders the editable HTML from the
  same tree walk as the `.tex` (ADR-0006). The title page shipped as `\maketitle`
  (its page-1 branded cover remains deferred). Deferred per the body: shipping the
  reference-compare PDF through the server (not chosen for P1). Was Proposed
  2026-07-07.
- **Deciders:** Dan Svoboda
- **Related:** [ADR-0005](0005-overleaf-round-trip-content-sync.md) (Overleaf is
  the committee-review surface; this ADR reduces the number of round trips to
  it by giving the author a faithful local view of both the editable HTML and
  the *compiled* deliverable before they ever push); [ADR-0006](0006-unify-html-latex-renderers.md)
  (the single tree walk that produces both the HTML preview and the `.tex` —
  this ADR consumes both outputs, it does not add a third renderer); the
  **LaTeX/Overleaf pivot** and **HTML/PDF alignment** project memories (the
  in-app PDF preview was removed on the pivot to a pure Overleaf hand-off; this
  ADR brings a preview back, but as a *compile of our own LaTeX* rather than the
  old Typst→PDF path).

## Context

Today the author edits the report in the app (the HTML content pane) and, to
see how the **deliverable** actually looks, exports an Overleaf `.zip`, uploads
it, and waits for Overleaf to compile. Every LaTeX-only problem — an overfull
table, a float that jumps a page, a missing glyph, a caption that wraps wrong —
is invisible until that round trip completes. The author discovers it in
Overleaf, comes back to the app, fixes the data/prose, re-exports, re-uploads.
That loop is the single biggest friction in producing a report.

Two facts make a better loop possible now:

1. **We already generate the exact LaTeX bundle Overleaf compiles.**
   `latex_export._assemble_bundle_files(data)` returns `{relpath: bytes}` for
   `main.tex` + `report.tex` + `niehs.cls` + `figures/*.png` — the same payload
   `/api/export-overleaf-bundle` ships. Nothing about it is Overleaf-specific.

2. **A local, offline TeX engine is available.** The sandbox ships `tect`
   (`/usr/local/bin/tect`), a wrapper around `tectonic -X compile --bundle
   /opt/tectonic/texlive` against a seeded TeXLive directory bundle — fully
   offline, no package-CDN network. Proven 2026-07-06: compiling the real
   `documents/DTXSID50469320/{main,report}.tex` produced a valid **4.1 MiB PDF
   in ~14 s**, exit 0. (See the `tect-offline-compile` tooling memory. Plain
   `tectonic` must NOT be used — its bundle CDN is firewalled.)

There is also a recurring *fidelity-checking* need: the report is authored to
mirror NIEHS Report 10 (the gold-standard reference PDF, `docs/NIEHS-Report-10-Reference.pdf`).
Comparing our output to a reference today means opening the reference in a
separate window and eyeballing back and forth. Doing it side-by-side inside the
app removes that.

### What exists to build on

The in-app preview pane was removed on the Overleaf pivot (commit `f594aa8`,
"drop in-app preview, hand off to Overleaf"). Its parts are recoverable
verbatim from `f594aa8^`:

- `#preview-pane` + `#pane-splitter` markup (`web/index.html`).
- `initPaneSplitter()` (draggable, edge-snap-collapse, width persisted to
  localStorage), `ensureFullPreview()` (POST `buildExportPayload()` →
  `/api/preview-latex-html` → `iframe.srcdoc`), `scrollPreviewToNode()`,
  `togglePreviewPane()`/`toggleContentPane()` (`web/js/layout.js`,
  `web/js/export.js`).
- The `/api/preview-latex-html` route + `html_generator.py` (Paged.js paginated
  HTML, geometry matched to `niehs.cls`) are **still live** — only the front-end
  was unwired.

So the HTML side is a *re-wire*, not a rebuild. The PDF side is new (the compile
route) but small (it reuses the bundle assembler).

## Decision

Add an in-app preview region with **two top-level, independently collapsible
views**, laid out beside the editing content pane:

```
┌─────────┬───────────────────────────────────────────────┬───────────────┐
│ sidebar │              PREVIEW REGION                     │  content pane │
│  (TOC)  │  ┌───────────────┐  ┌───────────────────────┐  │  (editing —   │
│         │  │  HTML view     │  │  PDF view              │  │   always the  │
│         │  │  (collapsible) │  │  (collapsible)         │  │   work        │
│         │  │                │  │  ┌────────┬─────────┐  │  │   surface)    │
│         │  │  Paged.js HTML │  │  │ live   │ compare │  │  │               │
│         │  │  live preview  │  │  │ PDF    │ PDF     │  │  │               │
│         │  │  (editable-doc │  │  │(tect   │(chosen  │  │  │               │
│         │  │   feedback)    │  │  │ compile│ from FS)│  │  │               │
│         │  │                │  │  └────────┴─────────┘  │  │               │
│         │  └───────────────┘  └───────────────────────┘  │  │               │
└─────────┴───────────────────────────────────────────────┴───────────────┘
```

- **HTML view** — the existing Paged.js `/api/preview-latex-html` render in an
  iframe. This is the *interaction* surface: fast (near-instant), re-renders as
  the author edits, and is where they watch the document take shape. Collapsible.

- **PDF view** — collapsible; contains two side-by-side PDF iframes:
  - **Live preview** — the author's report compiled locally via `tect`
    (new `POST /api/compile-pdf`). This is the *truth*: byte-identical LaTeX to
    what Overleaf gets, rendered by the same class of engine. Compile-on-demand
    (~14 s), triggered by a "Compile PDF" button, not on every keystroke.
  - **Comparison PDF** — any PDF the user chooses from the filesystem (a file
    picker; P1 is purely client-side via `URL.createObjectURL`). Its purpose is
    fidelity-checking against a reference (e.g. NIEHS Report 10).

Collapsibility is the load-bearing UX property: the author works in HTML most of
the time (PDF view collapsed), expands the PDF view for a truth check before an
Overleaf push, and expands the comparison side only when doing reference work.
Each boundary is a draggable splitter that can snap-collapse either side.

### Why not the alternatives

- **A second/third semantic renderer (`docx_generator`, or a richer HTML
  approximation) to "look like" the PDF.** Rejected. Any re-walk of the tree is
  an *approximation* of the LaTeX, rendered by a different engine than the
  deliverable. Compiling the actual `.tex` is not an approximation — it is the
  deliverable. It also adds zero rendering code (no new `_DISPATCH`, no
  `assert_dispatch_covers` entry, no parity tests). The renderer count stays at
  two (ADR-0006 holds).

- **Live-compile the PDF on every edit.** Rejected. A real LaTeX compile is
  seconds, not milliseconds. The HTML view already gives instant feedback; the
  PDF is the deliberate "show me the real thing" step. Compile-on-demand keeps
  the loop responsive and avoids hammering the engine.

- **Reintroduce a full TeX distribution / a PDF.js viewer.** Rejected/unneeded.
  `tect` + the seeded bundle is a single offline binary; browsers render PDF in
  an `<iframe>` natively, so no client PDF library is required.

- **Ship the comparison PDF through the server.** Deferred, not chosen for P1.
  A local file → object URL never touches the server and is the simplest thing
  that works. A server-known reference list (`docs/*.pdf`, `output/*.pdf`) is a
  small P2 add for picking the canonical reference without re-locating it.

## Architecture

```
buildExportPayload()  ──POST /api/preview-latex-html──▶ html_generator ──▶ HTML  ──▶ HTML view iframe (srcdoc)
       (existing)
buildExportPayload()  ──POST /api/compile-pdf────────▶ _assemble_bundle_files
                                                        → tmpdir → tect → report.pdf ──▶ live PDF iframe (blob:)
       (new route)
filesystem file       ──URL.createObjectURL──────────────────────────────────────────▶ comparison PDF iframe (blob:)
       (client only, P1)
```

### Backend — `POST /api/compile-pdf` (in `export_routes.py`)

- Same JSON payload as `/api/export-overleaf-bundle`; `_resolve_bm2_into_body`
  first, exactly like the sibling routes.
- `marshal_export_data(body)` → `_assemble_bundle_files(data, strict=False)`.
  **`strict=False`** deliberately: this is a *draft preview*, not a deliverable,
  so pending markers should be visible in the compiled PDF, not gate it (the
  opposite of the bundle export's `strict=True`).
- Materialize the payload into a `tempfile.TemporaryDirectory` via the existing
  `_write_files_to_dir`, run `tect main.tex --outdir <tmp>/out` as a subprocess
  (`subprocess.run`, `cwd=tmpdir`, captured output, a bounded timeout), read
  `out/main.pdf`, return it as `application/pdf`. Clean up the tmpdir.
- On non-zero exit: return the tail of the compile log as JSON (a 422-style
  "compile failed, here's why"), so the UI can show *what* broke — which is the
  whole point of catching it before Overleaf.
- The engine command is indirected behind one constant/env (`TECT_CMD`, default
  `tect`) so the HPC/prod deployment can point at its own wrapper if needed.

### Frontend (`web/index.html`, `web/js/layout.js`, `web/js/export.js`, `web/js/state.js`, `web/css`)

- Restore `#preview-pane` from `f594aa8^` as the **preview region**, reworked to
  hold two collapsible sub-views (`#html-view`, `#pdf-view`); `#pdf-view` holds
  two iframes (`#live-pdf-frame`, `#compare-pdf-frame`) with a splitter between.
- Reuse `initPaneSplitter()` (generalize it to take a pane id so the outer
  region↔content splitter and the inner live↔compare splitter share one
  implementation) and `ensureFullPreview()` (HTML view) verbatim.
- New: `compileLivePdf()` (POST `/api/compile-pdf` → blob → `#live-pdf-frame.src`,
  with a spinner + error surface for the compile-log case) and
  `chooseComparisonPdf()` (file input → object URL → `#compare-pdf-frame.src`).
- State slices on the Alpine `app` store, each persisted to localStorage like
  `sidebarCollapsed`: `htmlViewVisible`, `pdfViewVisible`, `compareVisible`.
  Visibility is genuine user-driven UI state (the sanctioned exception to the
  derive-don't-set rule, same status the old `previewVisible` had); the *content*
  of each view is still derived from the report payload, never hand-set.

## Consequences

**Positive**

- The author sees the true compiled deliverable — with real LaTeX pagination,
  float placement, and overflow — without an Overleaf round trip. This is the
  stated goal: fewer round trips.
- HTML view keeps the fast edit loop; PDF view is the on-demand truth check.
  Two speeds, each fit for purpose.
- Side-by-side reference comparison makes NIEHS-fidelity work a single-window
  task.
- No new renderer; ADR-0006's two-renderer invariant is preserved. The compile
  path is pure reuse of the bundle assembler + `tect`.

**Negative / risks**

- **Engine dependency at runtime.** The server host now needs `tect` + the
  seeded bundle on every environment that offers the preview (dev sandbox ✓;
  HPC/prod must seed it — `seed-tectonic.sh` per the `tect` wrapper's own error
  message). The route degrades gracefully: if `tect` is absent, `/api/compile-pdf`
  returns an error the UI shows, and the HTML view still works.
- **Compile latency (~14 s).** Acceptable for on-demand; must not be on the edit
  path. A per-payload-hash cache (skip recompile when the payload is unchanged)
  is an obvious follow-up.
- **Fidelity gaps surfaced by the proof compile are real work, not preview bugs:**
  missing glyphs (superscript `⁻`/`⁷`, `α`) in Latin Modern under the default
  mapping, and overfull boxes. The preview *reveals* these; fixing them
  (font/mapping in `niehs.cls`, table sizing) is downstream. Precedent: commit
  `42facab` already translated superscript exponents for FDR values.
- **Concurrency/temp cleanup.** Each compile spawns a subprocess and a tmpdir;
  needs a timeout and reliable cleanup so a stuck/looping compile can't pile up.

**Neutral**

- `/api/preview-latex-html` and `html_generator.py` come back into active use
  (they were orphaned-but-live since `f594aa8`). No change to them.
- The comparison pane is deliberately dumb (display only). If server-hosted
  references are wanted later, that's an additive P2 route.

## Rollout

1. **P1 (this ADR):** `/api/compile-pdf`; restore + rework the preview region
   into collapsible HTML view and PDF view (live + client-side comparison
   picker); splitters + toggles + persisted state.
2. **P2:** server reference list (`GET /api/reference-pdfs`, `GET
   /api/reference-pdf/{name}`) + dropdown, so the canonical NIEHS reference is
   one click away.
3. **P3 (optional):** per-payload-hash compile cache; page-jump alignment on the
   comparison pane; extend the semantic-parity guard to assert the compiled PDF
   page count/section presence against the HTML preview.

## Amendment 1 (2026-07-07) — branded cover + inner title page in LaTeX

The side-by-side compare surfaced that the compiled **deliverable** (Overleaf)
had no cover page and no title page. Root cause: the tracer-bullet "decision #6"
(skip the NIEHS cover in v1, build the title page with `\maketitle`) shipped as
permanent behavior, and because `niehs.cls` loads `article` without the
`titlepage` option, `\maketitle` didn't even produce a standalone page — the
title sat atop the first content page. The `cover` and `title-page` tree nodes
rendered nothing (`render_common.LATEX_OMITS = {cover, title-page}`).

**Decision #6 is reversed.** Both node types now have real LaTeX emitters,
porting the already-approved Typst cover (`report.typ:452-618`):

- `latex_generator._render_cover` — a full-bleed branded cover (page 1): a
  `tikzpicture` overlay anchored to `current page` drawing the sage-green field,
  the white institution band, the bicolor accent bar, the `cover-bg.jpg`
  hexagon-pattern background, and the title / report-number / date. Unnumbered,
  no running header.
- `latex_generator._render_title_page` — the centered inner title page (page 2),
  mirroring `html_generator._render_cover` (title block + publisher/ISSN block).
- `_document_skeleton` no longer emits `\maketitle` / `\title` / `\author`; the
  nodes own the front pages (rendered into `report.tex`). `\pagenumbering{roman}`
  stays before the body; the cover keeps page i unnumbered via `\thispagestyle{empty}`.
- `render_common.LATEX_OMITS` is now empty — both renderers cover every node
  type, closing the one documented HTML↔LaTeX divergence (ADR-0006).
- `latex_export` ships `cover-bg.jpg` at the bundle root (same static-asset
  pattern as `niehs.cls`; added to `_MANAGED_DIR_ENTRIES`).
- Side fix: `®` (U+00AE), present in the default strain, was absent from
  `_UNICODE_TO_LATEX` and silently dropped by pdflatex; now mapped to
  `\textregistered{}`.

Verified: `tect` compiles the bundle (cover-bg.jpg embeds, 20-page document);
smoke/parity/gate/export tests updated. The HTML surface still folds both nodes
into a single inner title page (its page-1 branded cover remains deferred) — the
LaTeX deliverable is the fidelity target here.

## Amendment 2 (2026-07-07) — cover as a subtype + layout registry

Follow-up fixes surfaced by compiling the deliverable: the TOC heading read
"Contents" (article's default `\contentsname` — renamed to "Table of Contents" in
`niehs.cls`); the cover was missing the NIH hexagon badge (top-left of the header
band) and the accent bar's diagonal break. The badge isn't a raster in the
reference PDF (it's vector) and no logo asset existed, so it was extracted via
PyMuPDF (`get_drawings` bbox → transparent PNG) into `nih-logo.png`; the accent
bar is now two parallelograms (exact reference path vertices) with a slanted white
gap, not two rectangles.

More structurally: everything that makes it the NIEHS cover was hardcoded in
`_render_cover` (assets, colors, geometry, title lines), duplicated in
`html_generator`, with colors in `niehs.cls` and images loose at the repo root.
That is now encoded as a **subtype + layout registry**:

- New `cover_layouts.py` — a frozen-dataclass `CoverLayout` registry (same
  discipline as `chart_registry`), keyed by subtype. The `niehs-5d-tox` entry owns
  the assets, brand palette, institution lines, `title_builder` /
  `publisher_builder` (the single source of the title/publisher text for BOTH
  surfaces), and the reference-derived geometry `metrics` (band/bg/accent-bar
  vertices/positions). Imports nothing from the renderers.
- `DocNode.subtype` (auto-forwarded via `_BINDING_FIELDS`), gated to
  `{cover, title-page}` in `_validate_entry`; NOT serialized to the frontend
  (pure render concern). The template's cover + title-page nodes carry
  `subtype: niehs-5d-tox`.
- `_render_cover` / `_render_title_page` (LaTeX) and `_render_cover` (HTML) now
  consume `get_cover_layout(node.subtype)` — palette emitted as `\definecolor`,
  geometry read from `metrics`, text from the shared builders — instead of
  hardcoding. `niehs.cls` keeps `tikz`/`xcolor` but no longer defines the palette.
- Assets moved to `assets/`; `latex_export` ships them driven by
  `cover_layouts.required_assets(subtypes-in-tree)`, not a hardcoded pair, so a new
  report cover ships its own assets with no renderer/exporter edit.

Behavior-preserving: the compiled cover is visually identical to Amendment 1's
(verified by rendering page 1 with PyMuPDF). The golden document-tree fixture is
unchanged (subtype isn't serialized). Adding a second report type's cover is now a
new registry entry + assets. HTML's title lines were unified onto the shared
7-line builder (the one visible preview change).
