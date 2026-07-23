# 0012 — `figure` as a first-class semantic content type

- **Status:** Proposed (2026-07-23). Being implemented alongside the vocabulary
  work: a `figure` node type + subtype axis, the `fig_*` furniture roles, and
  docx/LaTeX/HTML handlers; charts stay suppressed by the template's `charts: []`
  until a report opts them in.
- **Deciders:** Dan Svoboda
- **Related:** [ADR-0003](0003-document-component-model.md) (the component
  catalog + `DocNode` tree this adds a type to); [ADR-0010](0010-semantic-type-vocabulary-system.md)
  (the semantic-type vocabulary — the figure's caption/source/note/alt-text
  *paragraphs* are roles in it); [ADR-0009](0009-complete-the-layout-style-vocabulary.md)
  (the "don't canonicalize component geometry into the paragraph vocabulary" line
  — applied here to a chart's plot-internals); the **configurable charts** project
  memory (`chart_style` / `chart_registry` — the plot-internal styling this
  composes with but does not absorb).

## Context

Charts were treated, until now, as a styling afterthought hung off figure
captions. That is wrong: **a chart is semantic content**, produced from data in
the content-creation phase and published as a lossless PNG. "This is a chart" vs.
"this is a photograph / diagram / logo" is a *meaning* distinction the document
model should carry as a first-class type — exactly like "narrative" vs. "table" —
not a formatting flag. Other pictorial representations (photographs, diagrams)
will eventually appear in reports and likewise deserve semantic definitions and
semantically-defined styles.

Today there is **no first-class figure/chart/image node.** `CONTENT_KINDS`
declares `chart`/`image` as hints, but the only node carrying them is the
`genomics-section` monolith, which buries charts inside prose+tables+charts with
no addressable figure identity, no caption/source/alt-text structure, and no
figure numbering.

Meanwhile a chart actually spans **three separable concerns**, each already owned
by a different system — and the mistake to avoid is collapsing them:

1. **Semantic content type** — "figure, of kind chart" — belongs in the catalog +
   tree (this ADR). Missing.
2. **Figure furniture** — the caption / title / source / note / alt-text
   *paragraphs* around the image — is paragraph styling, already roles in the
   vocabulary (`0-32_Fig_Caption`, `3-13_Fig_Source`, `3-13a_Fig_Note`,
   `0-32a_Fig_Graphic`; the NTP template also has `Fig_Title`, `3-11_Fig_Alt_Text`,
   `1-26_Logo_Graphic`).
3. **Plot-internal styling** — axes, palette, markers, legend, gridlines — is
   `chart_style.py` (its own `STYLE_KEY_SCHEMA` + 4-layer resolver), NOT
   paragraph typography and NOT something to force into `LAYOUT_KEY_SCHEMA` (the
   same bucket-3 discipline ADR-0009 used to keep table/ToC geometry out of the
   shared vocabulary).

The NTP template itself already encodes the semantic distinctions: a dedicated
`3-11_Fig_Alt_Text` role (accessible description of what a data chart shows — a
first-class part of "chart as content," not decoration) and a `1-26_Logo_Graphic`
role *separate from* `0-32a_Fig_Graphic` (branding image vs. content image — the
chart-vs-other-pictorial distinction, in the styles).

## Decision

### 1. One `figure` node type with a `subtype` axis

Add a first-class **`figure`** component type — captionable, orientable,
headingless — the pictorial peer of `table` (`table` = data as a grid; `figure` =
data/content as an image). The *kind* of picture is a **`subtype`** (the same
mechanism `title-page` uses: `subtype: niehs-5d-tox`), a closed but extensible
vocabulary:

- **`chart`** — a data-derived plot; artifact is a lossless PNG rendered in the
  content phase via `chart_style`/`chart_registry`; graphic role `fig_graphic`.
- **`logo`** — a branding image (supplied asset); graphic role `logo_graphic`.
- **reserved (declared, not built):** `photograph`, `diagram`, … — added when a
  report needs one. The subtype vocabulary is extensible; only `chart` + `logo`
  are implemented now (the real cases: data charts + cover/title branding).

One node, one handler, one caption/source/note/alt-text machinery; the subtype
selects the *artifact source* (chart_style-rendered PNG vs. supplied image) and
the *graphic role* (`fig_graphic` vs `logo_graphic`). This avoids duplicating the
figure furniture across per-kind handlers (the reason separate `chart`/`image`/
`diagram`/`logo` node types were rejected).

### 2. Emitted roles = the figure furniture (paragraph vocabulary)

A `figure` node `emits` (ADR-0010 crosswalk): `fig_title`, `fig_caption`,
`fig_graphic` (or `logo_graphic` for subtype=logo), `fig_source`, `fig_note`,
`fig_alt_text`. Four already resolve; `fig_title`, `fig_alt_text`, `logo_graphic`
are added to the vocabulary via the extractor's `always_include` set (their Word
styles — `Fig_Title`, `3-11_Fig_Alt_Text`, `1-26_Logo_Graphic` — exist in the
template but the example bodies don't apply them, exactly the always-include case).

### 3. The three concerns stay separate and compose at the node

- **Semantic type** → catalog `figure` + subtype (this ADR).
- **Furniture styling** → `fig_*` roles in the paragraph vocabulary (ADR-0010),
  translated per surface like any other role.
- **Plot-internal styling** → `chart_style` (unchanged), consumed only when
  `subtype: chart`.
- **The artifact** → a lossless PNG (chart) or asset (logo); the node carries a
  reference to it + (for charts) the data/chart-type provenance.

### 4. Figure numbering + caption

`figure` is captionable and gets a **positional `figure_number`**, a counter
distinct from `table_number`, assigned by the same tree-walk instantiation that
numbers tables (ADR-0003 positional numbering). The caption renders via the
`fig_caption` role.

### 5. Decompose the genomics monolith onto it

`genomics-section`'s charts become `figure` children (subtype=chart) rather than
content buried in the monolith — each an addressable, numbered, captioned figure.
This is the migration target; the genomics narrative + gene tables stay on the
section node.

## Consequences

- Charts (and future photographs/diagrams) gain semantic identity: addressable,
  numbered, captioned, alt-texted document parts — not formatting hung off a
  caption.
- The three styling systems compose cleanly at one node with no overlap, honoring
  ADR-0009's "component geometry stays out of the paragraph vocabulary."
- `chart_style` is untouched and correctly scoped to plot internals; the
  vocabulary owns only the furniture; the catalog owns the semantics.
- Accessibility is first-class (`fig_alt_text`), matching the NTP template.
- Cost: a new node type touches the catalog, the tree schema, and three
  renderers, and the genomics decomposition is a real refactor of the monolith.
  Regression surface is bounded by the `charts: []` suppression (no chart renders
  until a report opts in) and the empty-config no-op path.

## Non-goals

- **Absorbing plot-internal styling into the paragraph vocabulary** — axes /
  palette / markers stay in `chart_style` (ADR-0009 bucket-3 discipline).
- **Building photograph/diagram/... subtypes now** — declared + reserved;
  implemented when a report needs one.
- **Turning charts on for the NIEHS 5-day report** — the reference has no
  main-body figures (`charts: []` stays); this ADR makes the *capability*
  first-class, it does not change the shipped report's content.
- **Vector/interactive chart formats** — the published artifact is a lossless
  PNG; SVG/interactive output is out of scope here.
