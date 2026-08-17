# 0003 — Composable document-component model: catalog, data-driven templates, generated ToC

- **Status:** Proposed (2026-05-26). **Mostly realized (verified part-by-part
  2026-08-17):** this ADR records a design ("no code is changed by this ADR"), but
  most of the model is now live —
  - **Part A (component catalog)** — DONE: `COMPONENT_CATALOG` + `CONTENT_ITEM_KINDS`
    in `render_capabilities.py`.
  - **Part C (data-driven templates)** — DONE: `document_template.instantiate()` /
    `build_tree()`; `DOCUMENT_TREE` is instantiated from YAML, not hand-written.
  - **Part D (generated ToC)** — DONE: `report_data_toc._build_toc_entries` walks
    the tree; distinct from the nav panel.
  - **Migration step 1 (nav/ToC rename)** — DONE: JS uses `data-nav-id` / `nav-*`;
    zero `data-toc-id` remain.
  - **Amendment 1 (declarative layout)** — DONE: the `landscape_requested` resolver
    + YAML `orientation`/`break_before`/`break_after` + capability-gated validation
    (this line of work also became ADR-0009).
  - **Part B (sub-addressable content items)** — ⚠ **HALF-BUILT, and the rest is a
    CONFIRMED LIVE REQUIREMENT (user 2026-08-17), NOT superseded.** The
    `component_id::item_id` addressing scheme exists and drives per-content-item
    ORIENTATION today (`render_capabilities.content_item_landscape_requested`,
    :506). STILL TO BUILD: (1) per-content-item BREAKS (orientation half shipped,
    breaks half not); (2) a renderer-consumed `content_items` list on `DocNode`
    (today `DocNode` carries no content-item structure and no emitter iterates one);
    (3) decomposing the `genomics-section` MONOLITH (one `data_key="genomics_sections"`
    node that expands at render time) into that declared content-item iteration.
    Note this is authoring/tree tidiness + a real breaks feature — it is NOT a BITS
    prerequisite: BITS containment is entirely the `jats_generator` emitter's job
    (the StyleChecker/DTD gate is already green on the current monolith), and tree
    granularity does not touch it.
  - **Migration step 6 (transcriptomics greenfield)** — a validation exercise for
    the model, never a shipped deliverable; author it as a template selection if/when
    a transcriptomics section is actually needed.

  Kept as **Proposed** because it is a design record, not an implementation ticket;
  the residual work is Part B (above).
- **Amended:** 2026-05-29 — Amendment 1 (declarative layout settings + the
  YAML / UI coordination model); see the end of this document.
- **Deciders:** Dan Svoboda
- **Related:** [ADR-0001](0001-bmdproject-schema-as-load-barrier.md) (the
  integrated dataset every component reads through); the
  [LaTeX/Overleaf pivot](../../) project memory (the renderer this structure
  feeds); commit `3411634` (per-node orientation overlay — the first overlay
  this model generalizes).

## Context

Report structure today is a **hand-written tree of `DocNode`s**
(`document_tree.py:DOCUMENT_TREE`). The tree is the single source of truth for
heading hierarchy, section ordering, positional table numbering
(`compute_table_numbers`), the front-matter/body split, and platform→section
mapping. Both renderers (`html_generator`, `latex_generator`) walk it, and the
frontend derives the left navigation panel from its serialized form
(`window.__DOCUMENT_TREE__` / `/api/document-tree`). This is architectural
invariant #2 — "the document tree drives all structure" — and it stays true.

Three pressures have accumulated that the hand-written tree does not serve well:

### 1. "ToC" means two different things, and the code has conflated them

The left navigation panel was originally intended to be *derived from* the
document's Table of Contents, so the two terms drifted into synonyms. The code
now bakes that conflation in: `data-toc-id` attributes, `toc-gene-set-children`
/ `toc-gene-bmd-children` element IDs, and "sidebar TOC" / "sidebar TOC scroll
spy" comments throughout `web/js/state.js`, `chemical.js`, `genomics.js`, and
`settings.js`. But they are distinct concerns:

- **Navigation panel** — a UI projection of the document structure, for moving
  around the app. Not part of the rendered report.
- **Table of Contents** — a *document component* that appears in the rendered
  report (front matter), with entries and page numbers.

Both are projections of the same document structure; neither *is* the
structure. This ADR fixes the vocabulary and frees "ToC" for the real
component.

### 2. Sub-entry orientation/breaks need finer granularity than a node

The orientation overlay shipped in `3411634` is keyed by **node id**. That
works where the structure is already decomposed — apical tables are separate
child `table` nodes under `narrative+tables`, so each is independently
orientable. It does **not** work for **`genomics-section`**, which is a
*monolith*: a single node (`document_tree.py` ~351–362, `data_key=
"genomics_sections"`) whose handler emits narrative + tables + descriptions
together. Its sub-parts have no id, so they cannot be independently oriented or
set to break after. The requirement is that **each content item inside a
combined entry — text, table, chart, figure — be independently orientable and
independently page-breakable**, even though it is not its own navigation/ToC
entry.

### 3. Structure is hardcoded; new sections are improvised

The genomics section was never in the reference report (NIEHS Report 10); its
structure and ToC were defined on the fly. A **transcriptomics** section does
not exist in the implementation at all. Every new section type today means
hand-editing `DOCUMENT_TREE` and teaching the renderers a new `node_type`.
There is no separation between *what component types exist* and *which ones a
given report uses, in what order*.

### What already points the right way

The pieces of the target model are present in embryo:

- `render_capabilities.CAPABILITIES_BY_TYPE` is a **type→metadata registry**
  keyed by `node_type` — the seed of a component catalog. Today it carries only
  render capabilities (`orientable`, `breakable`, `editable`).
- `tables-list` is a node type whose content is **generated by walking the
  tree** (a "List of Tables") — a working precedent for a generated ToC.
- `compute_table_numbers` already does a **pre-pass over the tree** to assign
  positional numbers — the same shape a ToC generator needs.
- `narrative+tables` is **already decomposed** into a parent plus child `table`
  / `incidence-table` nodes — the precedent for breaking a combined entry into
  independently addressable parts.

## Decision

Adopt a **composable document-component model** with four parts. Status is
Proposed; **no code is changed by this ADR** — it records the design before the
structure layer (a load-bearing invariant) is touched.

### A. A component-type catalog (the "collection")

An unordered registry of **component types**. Each entry declares:

- its **render capabilities** (today's `orientable` / `breakable` /
  `editable` — generalize `render_capabilities.CAPABILITIES_BY_TYPE` into this
  catalog rather than keeping a parallel dict), and
- its **content types** — the kinds of content the component can hold: text
  (boilerplate / AI-generated / ad-hoc), ToC entries, tables, charts/graphs,
  images. A text component sources its text per content-type; a section
  component holds a heading plus an ordered list of content items.

The catalog is the **one coupling point** between document semantics and
rendering semantics, exactly as `render_capabilities` is for orientation today:
a new section built from existing component types needs **zero renderer
changes**; only a genuinely new content type requires code.

### B. Content items are sub-addressable within a component

Per the deciding choice: a component (e.g. `genomics-section`) **stays one
component** but contains an **ordered collection of addressable content items**
(a chart, a table, a text block). Each content item gets a stable id within its
component, and the orientation/breaks overlays move from keying on **node id**
to keying on **(component id, content-item id)**.

This is the more faithful reading of "a component has a collection of content
types," at the cost of a new addressing scheme: the overlay maps, the preview's
`data-*` hooks, and both renderers' walk must thread content-item ids, not just
node ids. `genomics-section` is the **refactor target** — its monolithic
handler becomes an iteration over declared content items. The existing
`narrative+tables` decomposition is the shape to converge on, but expressed as
content items *inside* a component rather than child nodes beside it.

### C. Templates are data-driven from the start

Per the deciding choice: a **template** is **data** (JSON/DB), not hand-written
Python. A template **selects component types from the catalog and orders them**.
`DOCUMENT_TREE` becomes the *output* of instantiating a template against the
catalog, not a hand-maintained literal. Initially templates are authored by the
developer; the data-driven representation is chosen now (rather than deferred)
so the future **power-user / administrator** authoring path exists without a
second migration.

The runtime structure remains a `DocNode` tree — **invariant #2 is preserved**.
The template is an *authoring layer above* the tree; instantiation produces the
same canonical tree the renderers and nav panel already consume. Everything the
current hardcoded tree drives (nav panel, positional table numbering,
front/body split, platform→section mapping) must be reproduced by the
instantiated tree, byte-for-byte where observable.

### D. The Table of Contents is a generated component

A `toc` component type whose content is **generated from the template's
components and their order** — the same pre-pass shape as `compute_table_numbers`
and `tables-list`. It is a *document* component (front matter), distinct from
the navigation panel. The nav panel remains a separate UI projection of the
same instantiated tree.

Page numbers are the one asymmetry: in the LaTeX export `\tableofcontents` is
native and two-pass; in the Paged.js preview, ToC page numbers require a
target-counter pass and will be approximate or deferred. The generated ToC's
*entries and order* are exact in both; only preview page numbers lag.

## Migration shape (when implementation is approved)

This ADR records design only. A plausible leaf-first sequence, each step
independently landable:

1. **Rename nav identifiers** (`data-toc-id` → `data-nav-id`, `toc-*` element
   ids → `nav-*`, "sidebar TOC" comments → "navigation panel") to free the
   "ToC" name. Pure rename, no behavior change.
2. **Promote `render_capabilities` into the catalog**: add content-type
   declarations per component type. Still type-keyed; no template change yet.
3. **Sub-addressable content items**, proven on `genomics-section` first
   (decompose the monolith into declared content items; extend the
   orientation/breaks overlay to `(component, content-item)` ids). This is the
   smallest real test of part B.
4. **Generated `toc` component**, reusing the `tables-list` / table-numbering
   pre-pass.
5. **Data-driven templates**: introduce the template format and an instantiator
   that emits the current `DOCUMENT_TREE`; cut over once the instantiated tree
   matches the hand-written one (a golden-tree equality test, mirroring
   ADR-0002's golden-snapshot discipline).
6. **Transcriptomics as the greenfield validation**: author the new section
   purely as a template selection from the catalog. If it needs no renderer
   changes, the model is proven.

## Consequences

### Positive

- **Composability.** New sections are catalog selections, not renderer edits.
  Transcriptomics becomes a template, not a code project.
- **Genomics and the reference report unify.** The on-the-fly genomics monolith
  becomes a normal composed section; nothing is "special-cased" in a handler.
- **Independent per-content-item orientation/breaks** — the actual requirement
  that motivated this — falls out of sub-addressing, generalizing the overlay
  already shipped.
- **Terminology stops misleading readers**; "ToC" means the document component,
  the nav panel is named for what it is.
- **An authoring surface for power users/admins** exists by construction, once
  templates are data.

### Negative

- **High blast radius on a load-bearing invariant.** The structure layer drives
  the nav panel, table numbering, front/body split, and platform mapping; a
  regression ships wrong reports. This is cross-cutting-refactor territory (map
  blast radius, test the full flow). The golden-tree equality test at the
  data-driven cutover is the required oracle — same discipline ADR-0002
  mandates for the pipeline.
- **A new addressing scheme.** `(component, content-item)` ids touch the overlay
  maps, the preview `data-*` hooks, and both renderer walks. A dropped id is a
  silent regression in orientation/breaks.
- **Data-driven-from-the-start is more upfront design** than dev-authored Python
  templates: a template schema, an instantiator, and validation that an
  instantiated template reproduces today's tree. Chosen deliberately to avoid a
  second migration, but it front-loads risk.
- **Preview/export ToC asymmetry** (page numbers) is a standing limitation, not
  a bug to be fixed once.

## Alternatives considered

- **(Granularity) Each content item is its own tree node** *(rejected in favor
  of sub-addressing).* Would reuse the existing by-node-id overlay machinery
  with no new addressing scheme, and matches the `narrative+tables`
  decomposition. Rejected because the deciding preference is the richer
  "component owns a collection of content types" model, where a chart is content
  *within* a section rather than a sibling node — at the cost of the
  `(component, content-item)` addressing scheme.

- **(Templates) Dev-authored Python templates now, data-driven later**
  *(rejected in favor of data-driven from the start).* Lower upfront risk;
  keeps `DOCUMENT_TREE`-style literals until the model is proven. Rejected
  because it would require a second migration to reach the power-user/admin
  authoring path that is an explicit goal; doing it once is preferred even
  though it front-loads the template-schema design.

- **Do nothing / keep hand-editing the tree.** Rejected: every new section
  (transcriptomics next) is then a renderer change, genomics stays a
  special-cased monolith, and per-content-item orientation/breaks remains
  impossible.

- **Plan only / ADR, no edits** *(this document).* Record the design for review
  before touching the structure layer. Chosen for this commit; it does not
  preclude the migration sequence above as the subsequent implementation.

---

## Amendment 1 (2026-05-29): Declarative layout settings + the YAML/UI coordination model

### Why this amendment

The base ADR made *structure* declarative (template YAML → instantiated tree).
But two **layout** decisions were left as runtime-only concerns:

- **Page orientation** (portrait/landscape) lived solely in a per-session UI
  overlay (`data["orientations"]`, browser `localStorage`, web-export only).
- **Page breaks** were a declared-but-**unconsumed** catalog capability
  (`breakable`): nothing reads it and no renderer emits a break.

Two problems followed. First, the **UI-less CLI/session export** — the actual
Overleaf deliverable — has an empty orientation overlay, so it renders
*everything portrait*; the wide multi-column tables then overflow the margin (a
real `tectonic` compile confirmed this). The deliverable literally cannot
express landscape today. Second, more fundamentally: as the report becomes
declarative, layout must be expressible **in the spec (the YAML)**, while the
interactive preview must still let a user **override** it for a given export.
Without a coordination model, the YAML and the UI become two parallel,
conflicting sources of layout truth.

### The model: three distinct layers

Keep these separate — conflating them is what creates parallel-truth bugs:

1. **Capability** — *Can* a component type be oriented / broken? Lives in the
   **catalog** (`render_capabilities`: `orientable`, `breakable`). Already exists.
2. **Setting** — *Is* this instance landscape / does a break go here? Authored
   in the **template YAML** as optional per-node fields. **New.**
3. **Override** — Did the user change it this session? The **UI overlay**
   (per-session, client-side). Exists for orientation; to be added for breaks.

### The coordination rule (the heart of this amendment)

- The **YAML is the durable baseline; the UI overlay is a delta on top of it.**
- A single **effective-setting resolver** —
  `effective = override if present else template-default`, **gated on the
  catalog capability** — is used by **both renderers AND both export paths**.
  This is the one source of "is this landscape / does it break."
- **Precedence: UI override > YAML default > none.** A UI export therefore
  reflects the user's intent; a no-touch export equals the YAML spec exactly;
  the CLI deliverable (empty overlay) renders the pure YAML defaults.
- The **served tree carries the template defaults** (not just the capability),
  so the UI shows the *effective* state and writes only **deltas**. The UI
  never invents layout — it overrides a server-provided baseline.

### General principle (beyond layout)

The UI is an **override layer over server-provided baselines**: layout baselines
come from the YAML, content baselines from the pipeline (the `editable` prose
case is the same shape — the UI edits a server-provided draft). Every UI change
is a delta carried in the export payload and merged server-side by a shared
rule. This is what keeps the YAML system and the UI **complementary rather than
parallel**, and it is the durable answer to "how do the spec and the app relate."

### Template schema additions

```yaml
- id: table-clin-chem
  type: table
  platform: "Clinical Chemistry"
  orientation: landscape     # default; the UI may override it per session
  break_before: true         # emit a page break before this component
```

- `orientation`: `portrait | landscape`. Valid only on `orientable` types.
- `break_before` / `break_after`: boolean. Valid only on `breakable` types.
- The instantiator validates these against the catalog capability — a
  `landscape` on a non-orientable type, or a break on a non-breakable type, is a
  **loud load-time error**, exactly like the required-bindings check. Hand-edits
  stay honest.

### Two instances, two costs

- **Orientation — extends an existing mechanism.** The
  overlay → `landscape_requested` → renderer-wrap path already runs end-to-end;
  this adds the YAML default and makes the resolver merge default + override. It
  is also the *only* way the UI-less deliverable can render landscape — i.e. the
  fix for the wide-table overflow.
- **Breaks — builds the mechanism.** `breakable` currently has no consumer. This
  adds the break setting/overlay plus the renderer emission (`\clearpage` in
  LaTeX, `break-before: page` in HTML/Paged.js), finally giving the capability a
  consumer.

### Migration shape (amendment)

1. Add `orientation` to the template schema + `DocNode` + capability-gated
   instantiator validation. Introduce the shared resolver
   `effective_orientation(node, overlay)`, called by both renderers and both
   export paths. Serialize the default into the served tree.
2. Make the UI orientation overlay a **delta over the served default** (the
   toggle reflects the effective state; it writes only deltas).
3. Author the wide tables `orientation: landscape` in the YAML → fixes the
   deliverable's margin overflow.
4. Build the breaks mechanism: `break_before` / `break_after` template fields +
   `DocNode` + capability-gated validation + renderer emission, then (later) a
   UI breaks overlay following the same delta model.

### Consequences

**Positive**

- Layout joins the declarative spec; the deliverable can express landscape /
  breaks with no UI.
- The YAML and the UI are complementary (baseline + override, one resolver) —
  no parallel layout truths.
- Fixes the wide-table margin overflow in the Overleaf deliverable.
- The `breakable` capability stops being dead metadata.
- Hand-edited layout is validated against capability (loud errors).

**Negative / cost**

- The UI orientation overlay must move from a free-floating `localStorage` store
  to a **delta over the served default** (the toggle must show the effective
  state; serialization must carry defaults). Touches `web/js/layout.js` and the
  served tree.
- The shared resolver wants **one** assembly path; until the two assemblers
  (`marshal_export_data` vs `load_session_data`) converge, the resolver must be
  called from both — another reason to unify them.
- Breaks are net-new renderer surface (both renderers + overlay +, later, a UI
  control).
- A user override is keyed by node id; if the YAML default later flips, a stale
  per-session override still wins. Acceptable because overrides are ephemeral
  (session-scoped), but noted.

### Alternatives considered (amendment)

- **Keep orientation UI-only (no YAML setting).** Rejected: the UI-less CLI
  deliverable then cannot express landscape at all (the wide tables overflow with
  no recourse), and layout stays outside the declarative spec.
- **YAML-only (no UI override).** Rejected: the user explicitly wants a UI
  export to reflect per-session intent; a pure-spec model loses the interactive
  preview's value.
- **Persist UI changes back into the YAML ("save to template").** *Deferred, not
  rejected.* For the foreseeable future the admin authors durable layout by
  editing the YAML and UI changes are ephemeral session deltas (per the
  2026-05-29 "no admin authoring tooling" decision). A future "promote this
  override to the template default" action fits this model without changing it.
