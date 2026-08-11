# 0008 — Microsoft Word (.docx) as a one-way render surface

- **Status:** Accepted (2026-07-21; implemented the same day in `ee1f0dc`,
  "feat(docx): Word (.docx) render surface as the third emitter"). This record
  was written **2026-08-11** to close a dangling reference: the decision was made
  and shipped, and `docx_generator.py` plus the parity test cite "ADR-0008
  (Option B)", but the ADR file itself was never committed. Nothing here is new;
  it documents a choice already in the codebase.
- **Deciders:** Dan Svoboda
- **Related:** [ADR-0006](0006-unify-html-latex-renderers.md) (the shared
  semantic IR + `walk_tree` + node-type registry this surface plugs into — Word
  is a third *projection* of the same IR, exactly as ADR-0006 Amendment 1
  generalizes: "BITS, HTML, and LaTeX are all projections of one content model");
  [ADR-0003](0003-document-component-model.md) (the `DocNode` tree Word walks);
  [ADR-0004](0004-bits-jats-export-surface.md) (BITS/JATS, the *fourth* projection
  — same "output projection only, model stays canonical" stance as this one); the
  **docx styling bootstrap** project memory (the follow-on styling work that lets
  a Word template *seed* the shared style vocabulary — see "The styling nuance"
  below).

## Context

The report is assembled once into the canonical `DocNode` tree (ADR-0003) and
projected to output surfaces through a shared, markup-free semantic IR
(`render_common`, ADR-0006). At the time of this decision there were **two**
projections: the in-app **HTML** preview and the **LaTeX**/Overleaf bundle.

Some stakeholders' publishing workflows are **Word-driven**: track-changes
review, house `.dotx` templates, and reviewers who mark up a `.docx` rather than
edit LaTeX or an HTML pane. Handing those reviewers the LaTeX bundle or a
PDF is a poor fit for how they actually work. We need a **Word deliverable** —
a `.docx` that carries the same report, section for section, table for table.

The question is not *whether* to produce a `.docx` but *how* — and specifically
whether Word becomes a place report content can be **authored** (a source of
truth we read structure back out of) or stays a pure **output**.

## Decision

**Add a third emitter, `docx_generator.py`, that projects the same `DocNode`
tree through the same `render_common` IR — and treat Word strictly as a one-way
OUTPUT surface. Word is never a source of truth for report structure or
content.** This is "Option B" below.

Concretely:

- `generate_docx(data, tree=None)` walks the same `DOCUMENT_TREE` with the same
  `data` dict and dispatches on the same `render_common.RENDERABLE_NODE_TYPES`
  registry as the HTML and LaTeX emitters. Full node-type parity (17 types at
  landing) is **validated at import** by `assert_dispatch_covers` — a node type
  with no Word emitter is a loud `RenderDispatchError`, not a silent
  `[Section pending]`. The parity guard test (`test_renderer_dispatch_parity`)
  now checks all three dispatch tables.
- Everything **semantic** — which content source wins for a node, table rows,
  captions, the FASTQ roster, content-present-vs-absent — still comes from the
  shared `render_common` EXTRACT plans. Word cannot drift from HTML/LaTeX on
  *what* a section contains; it owns only *how* Word renders it. (ADR-0006's
  three-way boundary — semantics → IR, presentation → emitter, transport →
  emitter — holds unchanged with N=3.)

### The one deliberate structural divergence

HTML and LaTeX emitters return markup **strings** and share
`render_common.walk_emit`, which accumulates a flat list of chunks. **Word is an
object model.** A python-docx handler mutates a `Document` in place, so it can't
return a string chunk. Therefore this surface — and only this surface —

- gives each handler the signature `_render_<type>(doc, node, data) -> None`
  (mutation, not return), and
- runs its own `_walk_docx_tree` rather than `walk_emit`.

This is the single intentional asymmetry. It is a *presentation/transport*
difference (how markup is assembled), never a *semantic* one — the extract plans
are shared, so the divergence cannot make Word describe a different study.

### Why one-way (Option B), not a Word authoring surface

Round-tripping Word content **back into** the tree is a separate, already-owned
concern: `freeform_content.py` ingests an authored `.docx` *block* as inline
content on a `freeform-*` node (a bounded, opt-in escape hatch), and ADR-0005
owns committee edits via the Overleaf/LaTeX round-trip. Making the *whole* Word
document a bidirectional source of truth would mean parsing arbitrary Word back
into the semantic model — re-deriving structure the tree already owns, in
violation of Invariants #1 and #2. `docx_generator.py` is **generation only**.

## Options considered

- **Option A — derive the `.docx` from the compiled output.** Post-process the
  LaTeX/PDF deliverable into Word (e.g. a PDF→docx or LaTeX→docx conversion).
  Rejected: the result is a fragile *approximation* of a different engine's
  output, structurally lossy (tables, styles, and track-changes anchors degrade),
  and it adds a converter dependency while producing Word that reviewers can't
  cleanly mark up. It also wouldn't share the IR, so its content could silently
  disagree with the other surfaces.

- **Option B — a native third semantic emitter over the shared IR, one-way
  (CHOSEN).** Word is projected from the same tree + IR as HTML/LaTeX, with
  import-time parity coverage. Adds a real emitter (~one file) but zero new
  *semantic* surface area: the extract plans are reused verbatim, so Word gets
  the same no-drift guarantee the other two surfaces already have.

- **Option C — Word as a bidirectional authoring surface** (read structure back
  out of a `.docx`). Rejected: violates the single-source-of-truth invariants,
  duplicates the committee-edit path ADR-0005 already owns, and requires parsing
  arbitrary Word into the model. The bounded need (an externally authored block)
  is already met by `freeform_content.py`.

## The styling nuance (added retroactively, 2026-08-11)

"Word is never a source of truth" is about **content and structure**. It does
*not* forbid using a Word template to **bootstrap styling**. The follow-on
styling-bootstrap work (`e845d63`, `c5592cb`, `0ee8172`) added
`docx_style_extract.py`, which reads *style names and geometry* (never glyph
data) out of a Word/`.dotx` template into the shared `layout_style` vocabulary
that drives **all** surfaces. That is consistent with this ADR: the extractor
reads a *styling spec*, not report content — the tree + data remain the only
source of truth for *what the report says*. See the docx styling-bootstrap ADRs
(0009–0011) and project memory for that layer.

## Consequences

### Positive

- **Word reviewers get a native deliverable** that matches the HTML preview and
  the Overleaf `.tex` section-for-section, because all three read the same IR.
- **No new drift risk.** The import-time registry coverage (ADR-0006 #3) extends
  to Word for free; the three-way parity guard makes a missing Word emitter a
  build failure, not an Overleaf/Word surprise.
- **Cheap to maintain.** Adding or changing a node type is still a one-place edit
  to the extractor plus short per-surface emitters — now three emitters, all
  required by the registry.

### Negative / costs

- **python-docx object-model handlers are a second emitter style.** The
  `mutate-a-Document` shape (and its own `_walk_docx_tree`) is genuinely
  different from the string-accumulating `walk_emit` the other two share; a
  contributor must know which discipline a given surface uses.
- **Fidelity is bounded by the render engine, not by us.** The sandbox cannot
  render `.docx`→PDF, so page-for-page fidelity against NIEHS Report 10 can only
  be verified by opening the output in desktop Word on Windows. And because our
  generator writes its own prose, text length differs from the published report,
  so exact page breaks drift within sections even with perfect fonts. Realistic
  target: identical typography + table geometry + major sections starting on
  matching pages (see the docx styling-bootstrap memory).

### Neutral / scope (v1)

Shipped in v1 (`ee1f0dc`): full node-type parity, a clean typographic
cover/title page, US-Letter geometry, roman→arabic two-section page numbering,
booktabs-style tables, and inline genomics chart images. Deliberately **not** in
v1 (documented follow-ups, since addressed by later commits): the per-node
`layout_style` styling the other two surfaces honour, and a configurable-fonts
binding — v1 used the Word base styles.

The `.docx` emitter is **not** wired to an HTTP export route today; it is invoked
offline (regeneration script + the test suite). Wiring it to an
`/api/export-docx` endpoint, if wanted, is an additive follow-up with no model
change.
