# 0010 — A semantic-type vocabulary (design) system

- **Status:** Proposed (2026-07-23). Phase 0 landed this session (`vocabulary.py`,
  `vocab/base.yaml` + `vocab/ntp-report{,-generated}.yaml`, `docx_style_extract
  --emit-vocabulary`, the `render_capabilities` `emits` crosswalk, tests); Phases
  1–2 (render the three surfaces from the vocabulary) not yet wired.
- **Deciders:** Dan Svoboda
- **Related:** [ADR-0006](0006-unify-html-latex-renderers.md) (the single tree
  walk + shared per-key `layout_style` vocabulary the three surfaces resolve
  identically — this ADR adds a *semantic-type* layer above those per-key styles);
  [ADR-0009](0009-complete-the-layout-style-vocabulary.md) (the bounded per-node
  key schema a resolved type's `style` delta is written in); [ADR-0011](0011-lossless-canonical-dotx-layer.md)
  (the lossless canonical `.dotx` layer — this vocabulary is the *agnostic lossy
  projection* that sits beneath it); [ADR-0003](0003-document-component-model.md)
  (the `COMPONENT_CATALOG` "ad-hoc language" this reconciles with Word's named-
  style model); the **docx styling bootstrap** / **docx governance** project
  memories (the "author the look in Word, drive all surfaces" model and the
  reverse-engineered `.dotx` / example docs the vocabulary is generated from).

## Context

We render one `DocNode` tree to three surfaces (docx, LaTeX, HTML) from one
abstract style config (ADR-0006). Two problems surfaced when reconciling that
config with the real NTP Word templates:

1. **Wrong granularity.** Our styling key is the `node_type` (`narrative`,
   `front-matter`, `bmd-summary`). That is *coarser* than a semantic role: a
   single `narrative` node emits a **heading paragraph** and **body paragraphs**,
   which in Word are two different named styles (`3-02a_Head1_NoNumber` vs
   `0-03_Paragraph`). Word styles at the PARAGRAPH level; we styled at the node
   level. The title page had already hit this and grown a bespoke per-role sub-
   layer — the canary, not the exception.

2. **No declared, extensible type system.** The style names in the NTP examples
   (`1-03_Report_Title`, `0-25_Table_Title`, `4-13_References`, …) are a real
   semantic-role vocabulary with a `basedOn` inheritance graph rooted at
   `Base_Text`/`Base_Heading`. Our `COMPONENT_CATALOG` was ~70% of the same idea
   (a type catalog, a `CONTENT_KINDS` vocabulary, an `allowed_children` DAG, a
   `requires` mini-schema) but had no per-role types and no type inheritance.

This is a solved problem in the descriptive-markup tradition (Scribe 1980,
SGML/DTD, LaTeX document classes, CSS, later DITA *specialization* and TEI *ODD*):
a document is a tree of TYPED parts; parts are styled by their TYPE; the type
system is a declared, extensible artifact — the "prior agreement" between
producer and consumer. **Word's named-style system IS an instance of this**
(named styles = element types, `pStyle` = the type tag, `basedOn` =
specialization, `styles.xml` = the stylesheet). The decision (user, this session):
adopt the paradigm with a **medium-neutral house vocabulary we can define per
problem domain** (5-day tox reports here; aircraft engines elsewhere) — NOT adopt
a framework (DITA-OT etc.), because we already have the document models (the tree
+ the three translators); we need only the vocabulary *design* layer. Flat types
+ a specialization graph now; a containment grammar deferred.

## Decision

### The data model — a vocabulary is a flat set of TYPE RECORDS

`vocabulary.py`. Each type carries the three things Word's named styles bundle:

```yaml
report_title:
  specializes: title              # the ONE inheritance edge (Word basedOn / DITA specializes / a CSS class)
  style: {font_size: "20pt", align: center, space_after: "6pt"}  # OWN delta only (an ADR-0009 layout_style dict)
  bind:                           # per-surface concrete name — AUTO-DERIVED unless overridden
    docx: "1-03_Report_Title"
```

- **`specializes`** — one parent-type edge; the resolver walks it root→leaf and
  deep-merges each record's `style` delta (child wins), yielding ONE flat
  `layout_style` dict — the exact shape `resolve_layout_style` produces, so the
  three surface translators consume it unchanged.
- **`style`** — the type's OWN delta (only keys it overrides vs its parent), NOT
  the resolved absolute — so the specialization GRAPH is preserved, not frozen.
- **`bind`** — the concrete name each surface uses: docx Word-style name (applied
  as `pStyle` + emitted as `<w:style>`), LaTeX control sequence, HTML CSS class,
  BITS/JATS element. **Auto-derived** from the type name (html kebab-case, latex
  alnum-lower, docx the name as-is, bits a suffix→element table) unless an
  explicit `bind` overrides — the "auto-derived, override stubbed" decision.
- **`extends`** — a vocabulary may extend another (base ← domain ← curated); a
  child vocabulary's type of the same name overrides the parent's wholesale.

Loud validation at load: every `specializes` names a present type, the graph is
acyclic, every `style` value is a valid `layout_style` value, every `bind` names
a known surface.

### The vocabulary files — two-layer so regeneration never clobbers curation

- `vocab/base.yaml` — the **medium-neutral roots** (`document ← text ← {block,
  heading, title, caption, note, list_item, table_part}`). The load-bearing root
  is **`text`: Times New Roman 12pt with NO line-spacing key**, so everything
  inheriting it renders single-spaced by construction. This is the reference's
  neutral `docDefaults` baseline expressed as data, and it is what fixes the docx
  title's line spacing WITHOUT any per-title value (the bug that motivated this
  work: the title looked mis-spaced only because our generated `docDefaults`
  injected python-docx's 1.15× default; the reference specifies nothing → single).
- `vocab/ntp-report-generated.yaml` — **auto-generated** from an example `.docx`
  by the extractor; one type per Word paragraph style, `specializes` = the
  `basedOn` parent, `style` = the delta, `bind.docx` = the real style name.
  Regenerate when the template changes; do not hand-edit.
- `vocab/ntp-report.yaml` — the **curated** layer: `extends` the generated one and
  adds a handful of stable CANONICAL-ROLE aliases (`body_para`,
  `section_heading[_1..3]`, `appendix_heading[_1..2]`, `table_body_cell`, …) that
  the crosswalk references by stable name, each specializing the concrete
  auto-generated NTP type. This decouples the crosswalk's stable vocabulary from
  the template's incidental style names.

### The generator — `docx_style_extract --emit-vocabulary`

Walks a Word template's paragraph-style graph → a vocabulary dict. Emits DELTAS
(child props minus the parent's RESOLVED props) so inheritance is preserved, and
bridges the NTP roots (`Base_Text`/`Base_Heading`/`Normal`) into the neutral base
types. Defaults to `used_only` (styles referenced by body paragraphs + their
`basedOn` ancestors — the real ~50-role vocabulary, not all ~230 built-in Word
styles), which also excludes 100% of the PDF-import contamination by construction
(ADR-0011's noise; the contamination warning in `--coverage` names it).

### The granularity bridge — `emits` on the catalog

`render_capabilities.COMPONENT_CATALOG` gains an `emits` field: each node_type
declares the ordered vocabulary ROLE TYPES it produces (`narrative` →
`(section_heading, body_para)`; `table` → `(table_title, table_body_cell,
table_footnote)`; `title-page` → the title-page roles — the original role-emitting
node, now the general case). `node_type` stays the structural key; styling
attaches to the emitted role. A test guards that every emitted role resolves in
the shipped vocabulary.

### Rendering (Phases 1–2, not yet wired)

Each surface translates a resolved type its own way, preserving ADR-0006's
no-drift invariant: docx emits the `specializes` graph as native `<w:style
basedOn=…>` and applies `pStyle` by role (so a co-author sees the real NTP
palette — the governance model); LaTeX flattens the chain to a per-role macro;
HTML emits a CSS class and lets the cascade inherit. The empty-config path stays
byte-identical (the no-op guarantee).

## Consequences

- The Word template's `basedOn` graph becomes a resolvable, medium-neutral
  semantic-type vocabulary the three surfaces share — the reconciliation the user
  asked for. A different problem domain is a different vocabulary over the same
  `base` and the same engine; no engine code changes.
- The docx title spacing is fixed **by construction** (the neutral `base.text`
  root), not by a hardcoded value — the anti-pattern (`_TITLE_PAGE_ROLE_DEFAULTS`)
  this replaces.
- The vocabulary is the **agnostic lossy projection** of ADR-0011: bounded to
  `LAYOUT_KEY_SCHEMA`, it drops Word-only properties by design. Losslessness is
  the canonical layer's job (ADR-0011), portability is this layer's — neither is
  forced to be both.
- Two-layer vocab files keep auto-generation and hand-curation from colliding;
  `extends` + `specializes` are the same edge Word/DITA/CSS use, so the model is
  standard, not idiosyncratic.

## Non-goals

- A containment grammar (which types may nest in which) — deferred; the DocNode
  tree still carries structure, and `allowed_children` remains the nesting check.
- Losslessly capturing the `.dotx` — that is ADR-0011's canonical layer; this
  vocabulary is a deliberately bounded projection.
- Rendering from the vocabulary in this ADR — Phases 1–2 land as their own change;
  this records the design and the Phase-0 mechanism.
- Reconciling every one of the ~57 example style names into canonical roles up
  front — the generator emits them all; the curated canonical-role layer grows as
  sections gain role-addressable rendering.
