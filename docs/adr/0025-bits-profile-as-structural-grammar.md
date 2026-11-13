# 0025 — The document grammar is a BITS profile; provenance is a binding attribute

- **Status:** Accepted (2026-09-25); **migration phases 0–5 implemented the same day,
  phase 6 closed** (see "Implementation notes" at the end). Amends
  [ADR-0004](0004-bits-jats-export-surface.md): its "BITS is a projection only"
  clause stays true for *storage* (the `DocNode` tree + YAML remain canonical; no XML
  is stored or authored) but is withdrawn for *grammar* — the catalog's structural
  vocabulary and containment rules are henceforth taken from BITS 2.1, not invented.
- **Deciders:** Dan Svoboda
- **Related:** [ADR-0003](0003-document-component-model.md) (the component catalog +
  validator this re-expresses), [ADR-0004](0004-bits-jats-export-surface.md) (the BITS
  investigation + emitter; amended here), [ADR-0017](0017-content-provenance-data-classification.md)
  and [ADR-0023](0023-figure-provenance-boundary.md) (provenance as the classifying
  principle — this ADR makes provenance an explicit axis of every node),
  [ADR-0021](0021-three-concerns-data-content-rendering.md) (data / content / rendering
  — role is a rendering-structure concern, binding is a content concern),
  [ADR-0012](0012-semantic-figure-content-type.md) (figure subtype → becomes a binding),
  [ADR-0018](0018-app-is-not-an-editor.md) (authored content is supplied, not edited —
  governs the `authored` binding), the section catalog
  (`workflow/section_catalog.py`, 2026-09-22/23: its `kind` vocabulary is reused here),
  and the reference-structure extraction
  (`docs/reference/niehs-10-structure.faithful.yaml` + `findings.md`, 2026-09-25).

## Context

### The trigger: the reference report does not fit our grammar

On 2026-09-25 the structure of the reference report (NIEHS Report 10, read from its
Word file) was written down as a document YAML, one node per heading / table / figure,
and validated against the component catalog. Result: 84 nodes, **37 violations**.
The body fits exactly. Nothing else does:

| reference construct | why the grammar rejects it |
|---|---|
| About This Report → Authors, Contributors | `front-matter` is a leaf |
| appendix with numbered sub-sections, two levels deep (C.2 → C.2.1, C.2.2) | `appendix` admits only `freeform-*`; `narrative` is a leaf |
| appendix data tables with no dose-response platform (B-1, C-1, D-1) | `table` *requires* `platform` |
| figures inside appendices and sub-sections | `figure` is an allowed child of **no** type |
| per-appendix ToC and lists of tables / figures | `toc` / `tables-list` allowed only at a region root; no figures-list |
| 55 supplementary data files listed under Appendix F | no node for a supplied-file list |
| "Table B-1" numbering | one positional sequence; the letter prefix is a string literal in three emitters |

### The diagnosis: our types fuse document role with content provenance

Every catalog type names *where its content comes from*, and the containment rules
follow from that. `table` means "a platform data table from `integrated.json`", hence
`platform` is required. `narrative` means "pipeline-bound prose with a `data_key`",
hence it cannot nest. `appendix` means "an authored file", hence it cannot hold
structure. The reference breaks the grammar precisely where **provenance differs from
what we generate** — a table we do not compute, prose we do not write, figures we do
not plot — while the *document roles* involved (section, table, figure, list) are
entirely ordinary.

A second, sharper diagnosis: **one document is an instance, not a grammar.** Extracting
the reference's outline tells us what the grammar must be able to express (it is an
acceptance test) but cannot tell us what the concepts should be. Growing the catalog
rule-by-rule until that one instance validates would produce a grammar overfitted to
Report 10 and still fused on the wrong axis.

### The mature solution already exists, and it is the customer's target format

Structured scholarly documents are an old, solved problem. The relevant solution is
**BITS 2.1** (NLM Book Interchange Tag Suite, the book extension of NISO JATS): it is
what NCBI Bookshelf ingests, and NTP reports are published on Bookshelf. ADR-0004
already targets it as an export surface. Its content models, verified against the
BITS 2.1 tag library on 2026-09-25, cover every violation above:

| our violation | BITS 2.1 |
|---|---|
| nested front matter | `front-matter-part` → `named-book-part-body` → `sec` (recursive) |
| structured appendix | `app` → `(blocks)*, (sec)*`; `sec` → `(blocks)*, (sec)*` |
| figures / tables anywhere | `fig`, `table-wrap` are block content of `body`, `sec`, `app` |
| non-platform table | `table-wrap` = `label?, caption?, table` — no notion of data source |
| supplementary files | `supplementary-material` (`xlink:href`, `mimetype`), allowed in `app` and `sec` |
| lists of tables / figures | `toc` with `toc-title-group` + `toc-entry`, distinguished by `content-type` |
| landscape | `orientation` attribute on `table-wrap` / `fig` |
| appendix-scoped numbers | `label` is stored text on every captioned element; numbering is the producer's job |

(The vendored DTD in `assets/bits-dtd/` is BITS **2.0**; the content models cited here are unchanged between 2.0 and 2.1 for these elements, and the profile must `dtd_validate()` against the vendored 2.0 as ADR-0004's gate already does.)

Two nuances. BITS does not allow `toc` directly inside `app` (Bookshelf either makes
each appendix its own `book-part` with front matter, or generates the mini-ToC). And
BITS has **no computed numbering** at all — it stores "Table B-1" as a label, which is
exactly consistent with our positional-numbering rule (the walk assigns labels).

What BITS gets right that we got wrong is the separation of axes: **elements name
document roles only; provenance and kind live in attributes** (`content-type`,
`specific-use`, present on nearly every element as the sanctioned extension points).

### Why ADR-0004 rejected "BITS as internal representation", and why this is different

ADR-0004 considered adopting BITS as the internal model and rejected it: an archival
XML format with hundreds of elements; adopting it "would discard render-dispatch,
capabilities, and data-wiring". That reasoning still holds and this ADR does not
overturn it. **We are not adopting BITS as the representation. We are adopting its
role vocabulary and containment grammar as the structural axis of our own catalog** —
a profile of about a dozen elements — while dispatch, capabilities and data-wiring
survive intact as the *binding* axis. The tree stays `DocNode`/YAML. Nothing is
stored as XML.

## Decision

### 1. Every node has two orthogonal axes: `role` and `binding`

- **`role`** — the document role, drawn from a closed **BITS profile** (§2). Roles
  carry the structural facts: allowed children (copied from the BITS content model,
  never invented), whether the node is headingless, captionable, orientable,
  breakable. Roles are what the emitters lay out.
- **`binding`** — how the node's content is produced, drawn from a closed vocabulary
  (§3). Bindings carry `requires` (which fields must be present) and the workflow
  facts the section catalog needs: generated-vs-supplied, approvable, data-dependent.
  Bindings are what the pipeline fills and the workflow tracks.

Containment is decided by **role alone**. A `table-wrap` is allowed under `app`
whether its binding is a platform table or an authored one. That single change
dissolves all 37 violations without a new containment rule being authored by us.

### 2. The BITS profile (structural axis)

The catalog's roles, their BITS element, and their allowed children **as given by
BITS 2.1**. Flow content (`blocks`) = `table-wrap | fig | supplementary-material | p`
in BITS terms; in our tree a node's own content items are its flow phase and its
child nodes are its subsection phase, which is the `(blocks)*, (sec)*` ordering rule
ADR-0004 already noted.

| role | BITS element | allowed children (per BITS) | notes |
|---|---|---|---|
| `book` (root; regions `front`/`body`/`back`) | `book` → `front-matter`, `book-body`, `book-back` | region-specific below | the three region containers already in the YAML |
| `title-page` | `book-meta` / `title-group` | — | headingless; unchanged |
| `front-matter-part` | `front-matter-part` → `named-book-part-body` | `sec`* | **replaces leaf `front-matter`**; may nest |
| `toc` | `toc` | — (generated) | `content-type` = `contents` \| `tables` \| `figures`; replaces `toc` and `tables-list`, adds figures |
| `sec` | `sec` | blocks*, `sec`* | **the** recursive container; replaces `heading-only`, `narrative`, `narrative+tables` and the heading part of `bmd-summary` / `genomics-section` |
| `table-wrap` | `table-wrap` | — | captionable, orientable, headingless; replaces `table`, `incidence-table`, `sample-counts-table` |
| `fig` | `fig` | — | captionable, orientable, headingless; replaces `figure`; legal wherever blocks are |
| `supplementary-material` | `supplementary-material` | — | new: a supplied data file (title + href + mimetype) |
| `abstract`, `ack`, `ref-list` | same | `sec`* / — | named BITS front/back components; today's `abstract` / `acknowledgments` / `references` narratives |
| `app` | `app` (in `app-group`) | blocks*, `sec`*, **+ `toc`** | replaces `appendix`; the `toc` child is a deliberate profile extension (see §7) |

Not in the profile, by decision:

- **`page-break`** is not a document role (BITS has none). It becomes a presentation
  directive (`break_before: true` on the following node, the mechanism ADR-0003 Part B
  already has for per-node break overrides). The node form stays accepted during
  migration and is rewritten by the loader.
- **`cover`** stays a fixed, headingless front page (it is a `book-meta` role in
  BITS terms and needs no children).

### 3. The binding vocabulary (content axis)

The section catalog's `kind` (`llm | programmatic | derived | authored`) is already
the provenance vocabulary this ADR needs; it is promoted from a derived property to
the declared `binding` and given the fields each binding requires:

| binding | meaning | requires | typical roles |
|---|---|---|---|
| `container` | no own content; children carry it | — | `sec`, `app`, `front-matter-part` |
| `programmatic` | built from `integrated.json` by code | `data_key` **or** `platform` (+ `table_kind`: `apical` \| `incidence` \| `sample-counts` \| `bmd-summary`) | `table-wrap`, `sec` (methods prose, body-weight narrative) |
| `llm` | generated by a narrative generator, reviewable | `data_key` / `narrative_key` / `methods_key` as today | `sec`, `abstract` |
| `authored` | supplied content (ADR-0018): a `content_file`, or a supplied figure (ADR-0023 `photograph`/`diagram`), or a supplied data table | `content_file` (or `href` for `fig` / `supplementary-material`) | `sec`, `fig`, `table-wrap`, `supplementary-material` |
| `derived` | computed from the tree or the session's artifacts, never authored or approved | — | `toc`, labels, `ref-list`, the supplementary-material list of Appendix F |

Consequences of this table:

- `platform` is required by the **`programmatic` binding of an apical table**, not by
  the `table-wrap` role. An authored table (`Table D-1`) is `table-wrap` +
  `authored`. A pipeline matrix (`Table 1`) is `table-wrap` + `programmatic` with a
  `data_key`.
- The figure `subtype` of ADR-0012/0023 collapses into the binding: `chart` is
  `programmatic`, `photograph`/`diagram` are `authored`, `logo` is `authored` with a
  fixed source. The provenance boundary of ADR-0023 is now the same rule that governs
  tables and prose.
- The workflow derives readiness, approvability and staleness from `binding` (as it
  does today from `kind`), and `data_dependent` from the binding's fields — nothing
  hangs off the role.

### 4. `type` survives as a preset (compatibility bridge)

Templates, sessions, the section catalog and the structure editor all speak `type`.
Rather than rewrite them at once, **every existing type becomes a named preset for a
(role, binding) pair**, resolved by the loader:

| today's `type` | role | binding |
|---|---|---|
| `heading-only` | `sec` | `container` |
| `narrative` | `sec` | `llm` or `programmatic` (decided by `data_key`, as the section catalog does today) |
| `narrative+tables` | `sec` | `programmatic` — the group narratives are built from the tables by code (children are `table-wrap`s) |
| `front-matter` | `front-matter-part` | `llm` / `programmatic` per `data_key` |
| `table`, `incidence-table` | `table-wrap` | `programmatic`, `table_kind` apical / incidence |
| `sample-counts-table` | `table-wrap` | `programmatic`, `table_kind` sample-counts |
| `data-table` (new) | `table-wrap` | `programmatic` — any pipeline-built `{caption, headers, rows, footnotes}` matrix at a `data_key` (an appendix roster, an eFDR count); same emitters as sample-counts |
| `authored-table` (new) | `table-wrap` | `authored` — caption + supplied markup |
| `figures-list` (new) | `toc` | `derived` (content-type figures) |
| `supplementary-material` (new) | `supplementary-material` | `authored` (a `derived` session manifest is the follow-on) |
| `bmd-summary` | `sec` with one `table-wrap` content item | `programmatic`, `table_kind` bmd-summary |
| `genomics-section` | `sec` | `llm` (+ its programmatic tables and charts as content items) |
| `figure` | `fig` | from subtype (§3) |
| `appendix` | `app` | `container` |
| `freeform-page`, `freeform-block` | `sec` / block | `authored` |
| `toc`, `tables-list` | `toc` | `derived` (content-type contents / tables) |
| `page-break` | — | rewritten to `break_before` on the next sibling |

An entry may also state `role:` and `binding:` explicitly; presets are sugar. The
validator, the render dispatch and the editor key on the resolved pair. New
combinations (an authored `table-wrap` in an `app`, a `fig` in a `sec`) need **no new
type** — that is the point.

### 5. Numbering is a tree-walk over scoped containers

Labels ("Table 3", "Figure C-2") are computed, never authored (invariant #2 stands).
The change is *scope*: the walk numbers sequentially through `body`, and **each `app`
opens a new sequence with its letter prefix** (`Table B-1`, `Figure D-2`). Figures get
the `compute_figure_numbers` the ADR-0004 gap list calls for. The literal "B-1" in the
three emitters is deleted; labels reach the emitters as data, and reach BITS as
`<label>` text — the projection ADR-0004 planned, now with correct scoping.

### 6. Validation: BITS containment plus two acceptance instances

`document_template.instantiate` keeps its shape (loud, first-error) but its
`allowed_children` come from the profile table, and the flow-then-subsections order
is enforced. Two fixtures must validate from the day the profile lands, and stay
green forever:

1. `docs/reference/niehs-10-structure.faithful.yaml` — the reference report as an
   instance of the profile (all bindings honest: authored where we do not generate).
2. `templates/niehs-5day-report.yaml` — the shipped template, expressed through the
   presets, byte-for-byte compatible.

The difference between the two is then a difference in **bindings**, not in what
the grammar can express — which is the property we wanted.

### 7. Where the profile knowingly extends BITS

- **`toc` inside `app`.** The reference has per-appendix mini-ToCs and lists. BITS
  puts those in a `book-part`'s own front matter. Our profile allows a `derived` `toc`
  as the first child of `app`; the BITS emitter either promotes such an appendix to a
  `book-part` or omits the generated `toc` (Bookshelf regenerates it). Either way the
  profile stays a strict projection onto valid BITS.
- **Content items vs. child nodes.** ADR-0003 Part B's sub-addressable content items
  are our flow phase; BITS has only the flat `(blocks)*`. This is a refinement, not a
  conflict.

### 8. Surfaces

All four emitters dispatch on the resolved `(role, binding)` — the `assert_dispatch_covers`
guard is extended to the pair. HTML and LaTeX change least (roles map onto today's
handlers). **DOCX gains a principled style map**: the reference's NTP paragraph styles
are a pure role vocabulary (`3-02a_Head1` … `3-04a_Head3` for `sec` depth 1–3,
`4-05`/`4-06_Appendix_Head_*` for `sec` under `app`, `0-25_Table_Title`,
`0-32_Fig_Caption`, `4-09a_Supplementary_Material_Title`, `1-23_FrontMatter_Head1`,
`NTP Contents Heading`, `NTP Appendix List of Tables Heading`), i.e. one style per
(role, depth, region) — exactly what a role axis makes expressible. **JATS/BITS**
becomes a near-identity mapping, and its three `ADR-0004 gap` handlers (`appendix`,
`freeform-*`) close as a consequence.

## Consequences

**Gained.** The reference report is expressible. Appendices, figures in prose, authored
tables and supplementary files stop being "outside the model". Provenance is explicit
on every node and reviewable in the editor. Containment rules are no longer ours to
get wrong. The BITS export stops being a lossy projection. The docx surface gets a
style map that mirrors the customer's own template.

**Paid.** The catalog, the validator and the four emitters change — the largest
cross-cutting change since ADR-0013, to be done leaf-first with the two acceptance
fixtures as the gate (`constraints_cross_cutting_refactor`). Two features that today
lean on type identity move to binding identity: the section catalog (`kind` becomes
declared) and reprocess staleness (`data_dependent` from binding fields). The
structure editor's catalog payload grows a second axis.

**Unchanged.** Invariants #1–#3. The tree and YAML as the single source of truth.
Positional numbering. ADR-0018 (authored content is supplied, not edited in-app).
ADR-0023's provenance boundary — now enforced by the same mechanism for all content.

## Alternatives considered

- **Grow the current grammar rule-by-rule until Report 10 validates** *(rejected)*.
  Reinvents BITS's containment model piecemeal, keeps the role/provenance fusion, and
  overfits one instance.
- **Declare the boundary: appendices and nested front matter are out of scope**
  *(rejected)*. The customer's Bookshelf target requires exactly those parts, and
  the app would remain unable to express its own reference document.
- **DocBook 5, TEI, DITA, Pandoc AST, LaTeX classes** *(rejected)*. DocBook is
  equally mature but publishing-generic (no supplementary-material, no Bookshelf
  ingestion). TEI is for humanities texts. DITA is topic-based, wrong for a linear
  report. Pandoc's AST has no front-matter parts or appendix scoping. LaTeX classes
  carry numbering semantics but no data model. BITS is the only candidate that is
  both mature and the customer's actual target.
- **BITS as the stored representation** *(rejected, still, per ADR-0004)*. Storage
  stays `DocNode`/YAML; only the grammar is borrowed.

## Migration (sequence, not schedule)

0. This ADR; the reference YAML rewritten as an instance of the profile (bindings
   honest); it and the shipped template registered as validator acceptance tests.
1. Catalog: `role` + `binding` axes, presets for every existing `type`, allowed
   children from the profile table. Validator resolves presets. Both fixtures green.
2. Numbering: scoped walk + figure numbers; emitters take labels as data; "B-1"
   literals deleted.
3. Emitters: `app`/`sec`/`fig`/`table-wrap` (authored) /`supplementary-material`
   handlers on all four surfaces; JATS gap handlers close.
4. `front-matter-part` nesting; `toc` content-types (tables, figures; per-`app`).
5. Section catalog and reprocess read `binding` instead of inferring `kind`.
6. Structure editor: second axis in the inspector; presets remain the default
   authoring path.

## Not decided here

- Whether each appendix is projected to BITS as `app` or as its own `book-part`
  (an emitter choice to settle with the PMC Style Checker).
- The submission profile details (journal `article` vs. `book`) — ADR-0004's open
  question, unchanged.
- Any authoring UI for `authored` content: ADR-0018 governs; content is supplied.

## Implementation notes (phases 0–1, 2026-09-25)

What landed, and where the code deviates from the text above:

- **Catalog** (`document_model/render_capabilities.py`): `RoleSpec` + `ROLE_PROFILE`
  (9 roles: book-meta, front-matter-part, toc, sec, table-wrap, fig,
  supplementary-material, app, page-break), `BINDINGS`, and `role` / `bindings`
  on every `ComponentType`. `allowed_children` is no longer written per type; it
  is derived from the role profile (`allowed_children_for`, `is_allowed_child`).
- **Profile simplifications.** `abstract`, `ack` and `ref-list` are not separate
  roles yet: the abstract and acknowledgments are `front-matter-part` (their
  `data_key` picks the BITS element on export), References is a `sec` with
  `binding: derived`. `page-break` stays an authored node (a tolerated
  non-BITS role) rather than becoming a `break_before` attribute; that rewrite
  is deferred.
- **Validator** (`document_model/document_template.py`): an entry names a
  `type` or an explicit `role` + `binding` pair (`preset_for`); an explicit
  `role` must match the preset; an explicit `binding` must be one the preset
  lists; the tree carries both (`DocNode.role`, `DocNode.binding`).
  `authored-table` validates like the freeform types; `supplementary-material`
  and the authored figure subtypes (`diagram`, `photograph`) take a single
  `content_file` whose existence is not checked at load.
- **Presets added** with emitters on all four surfaces: `figures-list`,
  `data-table`, `authored-table`, `supplementary-material` (the last is a
  near-identity BITS projection). `figures-list` renders a pending note on
  HTML/DOCX until the figure-entry walk (phase 4) exists; LaTeX gets
  `\listoffigures`.
- **Acceptance instances** (`tests/unit/test_bits_profile.py`): the shipped
  template and `docs/reference/niehs-10-structure.faithful.yaml` (139 nodes,
  including Appendix F's 55 supplementary files read from the docx) both
  validate. The reference's 37 violations are gone with no per-type rule added.
- **Phase 2 (same day): appendix-scoped numbering.** `document_tree._number_scoped`
  numbers tables and figures per appendix (`table_label` / `figure_label` =
  "B-1", `appendix_scope` on every node in the subtree; body sequences are
  unaffected, and the data-driven genomics numbers continue the BODY sequence
  only). `render_common.table_caption` / `figure_prefix`, the lists
  (`table_entries[].label`), the HTML cross-reference resolver and the DOCX
  list field all display the label. The LaTeX appendix emitter opens the scope
  (`\setcounter` + `\renewcommand{\thetable}{B-\arabic{table}}`) so `\ref`
  resolves to "B-1" natively. **The Appendix B roster is now a `data-table`
  node** (`table-b-1`, `data_key: appendix_animals_matrix`) in the shipped
  template; `build_animal_roster_matrix` feeds it on both the LaTeX export and
  the marshal path (the HTML/DOCX preview gains the roster), the three
  appendix emitters lost their roster special case, and the "Table B-1"
  literal is gone from the codebase. A `breakable` matrix renders as a
  longtable on LaTeX. Golden fixtures were regenerated for the new node.
- **Phase 3 (same day): authored content channels.** `render_common.figure_payload`
  is the one extract every figure emitter reads: a data figure's payload at its
  `data_key`, or an authored figure's image file (`content_file`, read from
  templates/, MIME type by extension; a missing file is a visible pending note,
  never a load error). The LaTeX bundle (`_collect_figure_files`) now ships
  tree figures' bytes too, data and authored alike (data figures used to be
  referenced but never bundled). `render_common.authored_table_matrix` parses
  a supplied HTML `<table>` into the neutral matrix, so an authored table is a
  real grid on Word and BITS and a tabular on LaTeX when no LaTeX source was
  given; a LaTeX-only source stays verbatim on LaTeX and leaves a tracer on
  BITS. Tests: `tests/unit/test_authored_content_channels.py`.
- **Phase 4 (same day): scoped lists.** `report_data_toc._build_toc_entries`
  walks appendix subtrees and tags every contents / table / figure entry with
  its `scope` (the appendix letter, or None for the body); it now also builds
  `figure_entries` (tree figures + genomics charts). `render_common.list_entries`
  gives a `toc` / `tables-list` / `figures-list` node exactly the entries of
  its own scope, so the front-matter lists show the body and each appendix's
  mini-Contents / Tables / Figures show that appendix — as the reference lays
  them out. HTML filters; Word emits plain entries for scoped lists (a field
  cannot be restricted to one appendix without a bookmark region); LaTeX keeps
  the native `\tableofcontents` / `\listoftables` for the body, emits itemized
  lists for appendix scopes and for every figures list (figures are placed
  with caption text, not `\caption`), and niehs.cls gained `\ifniehsunlisted`
  so appendix tables take `\caption[]{…}` and stay out of the front list.
  The reference fixture's titles were made bare (labels are computed, never
  authored). `bmd-summary`'s caption stays on the node (content items are a
  later refactor, not needed for reference fidelity).
- **Phase 5 (same day): the workflow reads `binding`.** `section_catalog`
  takes each section's `kind` from the feeding node's declared `binding`; the
  content-origin inference (`_kind_for`) is now only the fallback for nodes
  built without a template, and for a `container` binding (a heading that
  merely carries a section's data_key). `heading-only` may declare `llm` /
  `programmatic` for that case, and the shipped template does so on Materials
  and Methods. `bmd-summary` defaults to `derived`, the workflow's long-standing
  classification (approvable, auto-derived), so the Sections screen is
  unchanged. Readiness, approvability and reprocess staleness therefore hang
  off the declared axis, as §3 intended.
- **Phase 6 (closed as is).** The editor exposes each preset's role and
  bindings in the inspector and offers a `binding` picker limited to what the
  preset admits; the validator accepts an explicit `role` + `binding` pair in
  place of `type`. Presets remain the authoring path — a pair-first authoring
  UI is not planned while every needed combination has a preset.
