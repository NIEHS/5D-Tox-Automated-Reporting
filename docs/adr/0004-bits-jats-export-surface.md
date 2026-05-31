# 0004 — BITS/JATS export surface for PMC/Bookshelf submission

- **Status:** Proposed (2026-05-27)
- **Status update:** 2026-05-29 — BITS-readiness assessed after ADR-0003
  Phases 0–5 + the declarative-layout amendment (see "BITS-readiness status" at
  the end).
- **Deciders:** Dan Svoboda
- **Related:** [ADR-0001](0001-bmdproject-schema-as-load-barrier.md) (the
  integrated dataset every component reads through); [ADR-0002](0002-decompose-api-process-integrated.md)
  (the golden-snapshot oracle discipline this export's validation reuses);
  [ADR-0003](0003-document-component-model.md) (the internal
  document-component model this surface *projects from* — several model changes
  named here are amendments that extend ADR-0003); the LaTeX/Overleaf pivot
  project memory (the two existing export surfaces this one joins).

## Context

A new requirement has landed: **NIEHS reports must be submittable to PMC / the
NCBI Bookshelf (LitArch).** Submission means producing XML that

1. conforms to **BITS** (Book Interchange Tag Suite), the NLM book tag suite,
2. passes the **PMC Style Checker** (the profile validator), and
3. satisfies the **File Submission Specifications** (NCBI Bookshelf doc
   NBK554845) — mandatory metadata, file packaging, accessibility, rights.

### Our export surfaces today

We support **exactly two** output surfaces: the in-app **HTML preview** and the
**`.tex` Overleaf export**. There is no PDF and no Typst anywhere in the system,
and we do not frame fidelity in terms of any compiled artifact. This ADR adds a
**third** surface — BITS XML — peer to the other two, not a replacement.

### What BITS / PMC / NBK554845 are, and why the stack matters

The three resources form a four-layer stack, and the *shape* of that stack is
the most important contextual fact:

| Layer | Resource | Role |
|---|---|---|
| Base schema | **BITS** (jats.nlm.nih.gov/extensions/bits) | A *permissive superset* of JATS Archiving for books. One tag set (no Green/Blue/Authoring flavors). Built for "interchange, archiving, conversion" — explicitly **not** authoring; "reproducing a particular book format is not a goal." |
| Strict profile | **PMC book tagging guidelines** | A *constraining profile* on BITS; overrides the base where they conflict ("Bookshelf's preferred style"), re-imposes required fields, forbids constructs, normalizes presentation. |
| Submission contract | **NBK554845 — File Submission Specifications** | BITS preferred; 7 mandatory metadata fields; file-naming/packaging; accessibility; rights declared *in the XML*. |
| Validator | **PMC Style Checker** | Runs the profile as errors (must-fix) vs warnings (suggested). |

**This is the same two-layer architecture ADR-0003 already chose** for our
internal model: a permissive **component catalog** + a constraining **template**
+ a **golden-tree/validation oracle**. The most mature document model in this
domain independently validates our direction. That alignment is why BITS export
is a tractable projection rather than a rewrite.

### Findings from the deep dive that shape this decision

A faithful extraction of the BITS 2.2 tag library and the PMC profile produced
these load-bearing facts (full comparison archived in the design discussion):

- **Heading depth is positional** in BITS (nesting depth; no structural level
  attribute — `disp-level` is only a display override). We already plan to
  derive `level` from depth. **Aligned.**
- **Numbering is author-supplied** in BITS (`<label>` holds the verbatim printed
  number; PMC *forbids inventing* labels) because BITS captures *already
  published* books. We **generate** and number positionally
  (`compute_table_numbers`). These reconcile cleanly: on export, our positional
  number is **materialized into `<label>` text** — we are the "publisher"
  supplying it. No internal change.
- **Strict label / caption / title separation:** `<label>` = number only,
  `<caption>` = `(title?, p*)`, `<title>` = section heading *only* and
  **forbidden on figures/tables**. Our `DocNode.title` is *overloaded* (section
  heading **and** table title), and our caption lives in the **data overlay**,
  not on the node. **Model change required** (amendment a).
- **Containment is a strict tree** with a per-element allowed-children grammar
  (`table-wrap` has many legal parents) — exactly the adjacency-list DAG
  ADR-0003 step 5 plans. And **flow content cannot interleave with subsections**
  (`(blocks)*, (sec)*`), which gives a principled basis for ADR-0003's
  content-item-vs-child-node split: content items are the flow phase, child
  nodes are the subsection phase. **Aligned; informs the validator.**
- **`@orientation` (portrait/landscape) and `@position` (float/anchor) are
  per-element attributes** on `table-wrap`/`fig` — independently validating
  ADR-0003 Part B's move of orientation to `(component, content-item)`.
- **Cross-references are a separate ID/IDREF graph** (`<xref ref-type rid>` →
  target `id`). **We have no cross-reference mechanism at all** (verified:
  the only `xref` in the code is Plotly chart coordinates). This matters
  acutely *because our numbering is positional* — any narrative that hardcodes
  "Table 3" breaks silently on reorder. **Net-new capability required**
  (amendment c).
- **PMC generates the ToC** from the heading hierarchy (no `<toc>` element in
  the profile) — matching ADR-0003 Part D's generated ToC. **Aligned.**
- **`sec-type`/`book-part-type` are inert free-text labels**; our `node_type`
  drives render dispatch + capabilities. Justified divergence — BITS
  interchanges, we render. Keep `node_type`.
- **`compute_figure_numbers()` is declared in `document_tree.py` but does not
  exist** (only `compute_table_numbers` is implemented). Figures need positional
  numbers to materialize into `<label>`. **Implementation gap** (amendment e).

## Decision

**Add BITS XML as a third export surface, projected from the canonical `DocNode`
tree.** The internal representation stays `DocNode`/JSON; BITS is an **output
projection only**. Architectural invariant #2 holds: the tree is the single
source of truth, and the BITS document is *derived*, never authored upstream of
the tree.

Concretely:

### 1. A `bits_generator.py` renderer, peer to the existing two

A renderer module with a `_DISPATCH` table over `node_type`, mirroring
`html_generator` and `latex_generator`. The dispatch-parity guard
(`tests/unit/test_renderer_dispatch_parity.py`) extends from a two-way to a
**three-way** check: every `DocNode` `node_type` must have a handler in all
three surfaces, modulo documented per-surface omissions (LaTeX already omits
`cover`/`title-page`; BITS will have its own documented set).

### 2. The DocNode → BITS mapping contract

| DocNode | BITS target | Notes |
|---|---|---|
| top-level body node | `<book-part>` (`book-part-type` from node) | `book-body` holds only book-parts |
| nested section node | `<sec>` (recursive) | depth positional; requires `<title>` or `<label>` (we always have `title`) |
| front-matter node (`cover`, `title-page`, `tables-list`, foreword…) | `<front-matter>` / named parts (`foreword`, `preface`, `dedication`) | narrative front matter — *not* `book-meta` |
| document metadata (chemical, casrn, dtxsid, report #/date) | `<book-meta>` | must carry the 7 NBK554845-mandatory fields |
| `table` / `incidence-table` node | `<table-wrap>` | XHTML `<table>` (not CALS); **`<th>` required**; `<label>` = materialized positional number; caption → `<caption>`; footnotes → `<table-wrap-foot>` |
| `bmd-summary` table | `<table-wrap>` | same as above |
| chart / figure content item | `<fig>` + `<graphic>` | **`<alt-text>` required**; `<label>` = materialized figure number |
| references | `<ref-list>` → `<ref>` → `<element-citation>` (structured) or `<mixed-citation>` | |
| appendices (`appendix-a..f`) | `<book-back>` / `<book-app>` | book-level back matter (not `<back>`) |
| in-text reference to a table/figure | `<xref ref-type rid>` | depends on amendment c |

### 3. Metadata-completeness gate

`<book-meta>` must carry the **7 mandatory fields** (author/editor, book title,
edition, publisher, place of publication, date, language) and a rights/license
declaration **in the XML** (open access declared explicitly with a license
URI). The marshal/metadata layer must guarantee these before export; a missing
field is a hard Style-Checker error, not a soft default.

### 4. Validation strategy — the Style Checker is the golden gate

Emitted XML is validated against the **BITS schema** (DTD/RNG/XSD) and the **PMC
Style Checker** as the export's oracle, in the spirit of ADR-0002's
golden-snapshot discipline: a fixture report is rendered to BITS in CI/tests and
checked; **errors must be zero**, warnings are tracked. This oracle is stronger
than a self-authored golden file because it is the *authoritative external
validator* of the submission target.

### 5. Numbering reconciliation

No change to internal positional numbering. Our positional table/figure numbers
are **materialized into `<label>` text** at export time. This is exactly what
BITS expects of a publisher and resolves the apparent author-supplied-vs-
positional conflict with zero loss.

### Required internal-model changes (amendments that extend ADR-0003)

Per the decision to keep ADR-0003 focused on the internal model, the model
changes the export depends on are recorded **here as dependencies** and folded
into ADR-0003 when implemented. They are improvements on their own merits,
independent of BITS:

- **(a) Split content-item identity into `label` / `title` / `caption`.** Adopt
  BITS' three roles on the sub-addressable content item (ADR-0003 Part B):
  de-overload `DocNode.title`, and move `caption` from the data overlay onto the
  addressable item. On export, a section's `title` → `<title>`; a table's
  `title` → `<caption><title>` (never a bare `<title>`, which PMC forbids on
  tables).
- **(b) Per-content-item orientation (already ADR-0003 Part B);** additionally
  evaluate BITS' `@position = float | anchor` ("does this table relocate or stay
  anchored?"), which we do not currently model and which affects the LaTeX
  export too.
- **(c) Cross-reference mechanism (`xref`/`rid`).** In-text references carry a
  *target id* + ref-type; the **positional number is resolved at render time**
  in all three surfaces (HTML `<a>`, LaTeX `\ref{}`, BITS `<xref>`). The LLM
  narrative prompts must emit *reference tokens*, not literal numbers. This is
  the one genuinely net-new capability, and it fixes a current latent fragility
  regardless of export.
- **(d) Front/body/back as explicit template regions** (replace the
  `FRONT_MATTER_NODE_TYPES` membership test), and a validator rule enforcing
  "content items before child sections, no interleave" (BITS' `(blocks)*,
  (sec)*`).
- **(e) Implement `compute_figure_numbers()`** (declared in `document_tree.py`
  but never written) so figures receive positional numbers to materialize into
  `<label>`.

## Migration shape (when implementation is approved)

This ADR records design only; no code is changed. A plausible sequence, each
step independently landable, interleaving with ADR-0003's own sequence (the
export depends on ADR-0003's content-item addressing, so they must coordinate):

1. **Metadata completeness.** Audit the marshal/request-body layer; guarantee
   the 7 mandatory `book-meta` fields + rights declaration. Needed by every
   later step; landable now.
2. **Cross-reference mechanism (amendment c).** Highest value — also removes the
   current hardcoded-"Table N" fragility. Touches the model, all renderers, and
   the narrative prompts.
3. **label/title/caption split + caption relocation (amendment a).**
4. **`compute_figure_numbers()` (amendment e).**
5. **`bits_generator.py` skeleton** + DocNode→BITS dispatch; extend the parity
   guard to three-way.
6. **Validation harness:** render a fixture report to BITS, validate against the
   BITS schema + PMC Style Checker (ADR-0002 discipline).
7. **Conformance pass:** drive Style-Checker errors to zero; track warnings.

## Consequences

### Positive

- **Reports become PMC/Bookshelf-submittable** and archival-interoperable via
  the domain-standard format.
- **BITS is a renderer, not an internal model** — invariant #2 is untouched, and
  we reuse the existing multi-renderer + dispatch-parity architecture rather
  than inventing one.
- **The cross-reference gap gets closed** (amendment c), fixing a current latent
  bug — positional numbers hardcoded in narrative prose — independent of export.
- **The label/caption/title split and front/body/back regions improve the
  internal model on their own merits**, sharpening ADR-0003.
- **The external validator is a free, authoritative oracle** — stronger than a
  self-authored golden file, in the exact spirit of ADR-0002.

### Negative

- **A third renderer to keep in parity.** Every `node_type` now needs three
  handlers (modulo documented omissions); the parity guard grows a dimension.
- **BITS conformance is exacting:** mandatory metadata, XHTML tables with
  `<th>`, alt-text on figures, MathML for math, no Private-Use characters, no
  whole-element formatting. Satisfying the Style Checker is real work.
- **Coupling between ADR-0003 and ADR-0004.** Several changes (a, c, d, e) touch
  the internal model and must land *before* a faithful export; the two ADRs'
  sequences interlock.
- **The cross-reference mechanism is net-new surface** across the model, all
  three renderers, and the LLM narrative prompts — a dropped reference token is
  a silent regression.
- **Overloaded-field mapping needs care:** `DocNode.title` maps to `<title>` for
  sections but to `<caption><title>` for tables; a wrong mapping is a
  Style-Checker error.

## Alternatives considered

- **Adopt BITS as the internal representation** *(rejected).* BITS is an
  interchange/archival XML format, not a working model; adopting it would
  discard render-dispatch, capabilities, and data-wiring, and bloat the model to
  hundreds of elements. Keep `DocNode`/JSON canonical; BITS is a projection.

- **Author BITS directly / hand-tag the XML** *(rejected).* Defeats the
  generative pipeline and invariant #2, and reintroduces the
  hand-maintained-structure problem ADR-0003 exists to remove.

- **Adopt author-supplied numbering and an authored `<toc>` to match base BITS**
  *(rejected).* Correct only for *capturing already-published* books; wrong for
  a generative system. The PMC profile itself *generates* the ToC, and our
  positional numbers materialize into `<label>` on export with no loss.

- **Pull in the full BITS vocabulary now** *(rejected, YAGNI).* Borrow the
  *shape* (label/caption/title separation, the xref graph, the containment
  grammar) and only the element kinds we actually emit; expand when a real
  content kind needs it.

- **Defer / do not target BITS** *(rejected given the confirmed submission
  requirement).* PMC/Bookshelf submission is the stated driver; deferring leaves
  the model with the latent cross-reference fragility unaddressed and pushes a
  second migration later.

---

## BITS-readiness status (as of ADR-0003 Phase 5, 2026-05-29)

The deliverable-driven ADR-0003 implementation (Phases 0–5 + the declarative-
layout amendment) was built to keep this export surface *additive*.  Where it
stands against the plan above:

### Holding — the "BITS is a projection" discipline is intact

- **The canonical model stayed canonical.** `DocNode`/JSON + the YAML template
  remain the single source of truth; nothing made BITS (or LaTeX) an *internal*
  concern.  Invariant #2 and this ADR's projection principle both hold.
- **Renderer-specific concerns stayed in the renderer.** The Unicode→LaTeX
  translation (`≤`→`\ensuremath{\le}`, subscript digits→`\textsubscript`),
  table scaling, and the landscape wraps all live in `latex_generator` /
  `niehs.cls`.  The *data* still carries clean Unicode (`≤` stays `≤`) — exactly
  what a BITS projection wants (UTF-8 / MathML).  Had any of that gone into the
  data/marshal layer it would have polluted the semantic baseline; it did not.

### Advanced toward BITS

- **Phase 1 catalog = the BITS structural vocabulary.** `headingless` ↔ BITS
  positional heading depth; `allowed_children` ↔ the BITS containment grammar
  (a DAG); `content_kinds` ↔ BITS block-content kinds.  The instantiator
  validating nesting against `allowed_children` is the BITS containment check in
  embryo.
- **Phase 4 content items + declarative orientation = amendment (b),
  substantially done.** Sub-addressable `(component, content-item)` items ↔ BITS
  addressable `<table-wrap>` / `<fig>` inside a `<sec>`; orientation-as-an-
  attribute ↔ BITS `@orientation`.  (BITS `@position` float|anchor is still
  unbuilt.)
- **Structured abstract** (Background / Methods / Results / Summary labeled
  sections) ↔ BITS `<abstract>`; **generated ToC** ↔ the PMC profile (generated,
  not authored).

### Still pending — the Decision-section amendments

- **(a) label / title / caption split** — **shipped.** `DocNode.caption` is
  now a separate field, gated by a `captionable` catalog flag (only on
  table-like types); both renderers prefer it over the data-overlay caption
  when set.  Byte-identical until a template sets `caption:`; ready to
  carry `<caption><p>` independently of `<label>`/`<title>`.
- **(c) cross-reference mechanism (`xref`/`rid`)** — **shipped (renderer
  half).** `[[xref:id]]` tokens survive both LaTeX/HTML escaping and
  resolve post-escape to `Table~\ref{tab:id}` / `<a class="xref"
  href="#sec-id">Table N</a>`; unknown ids surface a visible broken
  marker `[[xref:??id]]` (not re-matched).  The upstream half — LLM
  prompts emitting tokens instead of hardcoded "Table 2" — is still to
  do, owned by the content pipeline.
- **(d) front/body/back as explicit regions** — **shipped.** Template top-
  level is now three region containers (`region: front|body|back`,
  `children:`); the instantiator inherits `region` onto every descendant;
  `DocNode.region` projects directly to BITS `<front-matter>` / `<book-body>`
  / `<book-back>` on a future BITS render; the type-membership
  `FRONT_MATTER_NODE_TYPES` set is retired in favour of `node.region`.  The
  page-numbering switch in both renderers now reads `top.region == "body"`.
  Byte-identical `report.tex` confirmed against the (e) baseline render.
  The "content items before child sections, no interleave" containment rule
  (BITS' `(blocks)*, (sec)*`) is **not yet enforced** by the validator and
  remains a separate amendment-d follow-up.
- **(e) `compute_figure_numbers()` + figure `<alt-text>`** — **shipped for
  genomics charts.** Charts gain a positional `figure_number` (assigned at
  attach time in `latex_export`); both renderers prefix the chart caption
  with "Figure N." and emit BITS-aligned alt-text (HTML `<img alt="…">` =
  the descriptive caption alone, independent of the label).  `DocNode.
  figure_number` stays declared but unused — content-item figures own their
  numbers now (figures are not DocNode-typed in our tree); a tree-walk
  `compute_figure_numbers()` would only matter once DocNode-figures exist.

### One semantic-baseline caveat to track

**References are semantically flat.** They render as paragraphs (`[1] …`), and
the underlying data is a list of pre-formatted strings, not structured
`<element-citation>` fields — the upstream LLM extracts strings, not citations.
This is *not* a regression introduced by the LaTeX work, but it is a genuine
BITS gap: `<ref-list>` / `<ref>` / `<element-citation>` need structured citation
data we do not currently produce.  It is the place the deliverable sits furthest
from BITS structure.

**Net:** the catalog / content-item / orientation work moved the model *toward*
Bookshelf rather than away.  The export surface itself and prerequisites
(a)/(c)/(d)/(e) remain this ADR's roadmap — with **(c) cross-references** the
priority.
