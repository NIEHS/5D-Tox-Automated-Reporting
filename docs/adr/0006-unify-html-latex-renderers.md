# 0006 — Unify the HTML and LaTeX renderers behind one tree walk

- **Status:** Implemented (2026-06-10). Proposed 2026-06-09; **Amended 1**
  2026-06-09 (reframes the shared layer as a semantic IR — see Amendment 1).
  Fully landed on `latex/tracer-bullet`: `walk_tree` (step 1) → extract/emit
  (step 2) → node-type registry (step 3) → the table handlers and the rest of
  the IR for every data-bearing node type (steps 4a–4c + Amendment 1) →
  cross-surface semantic-parity guard → the three latent inconsistencies
  converged in the IR → the last `_walk` duplicate folded onto `walk_tree`
  (step 5). Every refactor commit verified byte-identical old-vs-new on the real
  DTXSID50469320 session; every deliberate convergence covered by a parity test.
- **Deciders:** Dan Svoboda
- **Related:** [ADR-0003](0003-document-component-model.md) (the `DocNode`
  document-component model whose tree both renderers walk — this ADR is about
  *how* that single canonical tree is traversed and turned into output);
  [ADR-0005](0005-overleaf-round-trip-content-sync.md) (the `.tex` export is the
  Overleaf hand-off surface — a renderer desync silently corrupts that surface,
  which is the failure mode this ADR removes); the **LaTeX/Overleaf pivot**
  project memory (LaTeX is now a first-class output, not a throwaway, so the two
  renderers are permanent peers and their duplication is permanent debt).

## Context

The report is assembled once, into the canonical `DocNode` tree (ADR-0003), and
then rendered to **two** surfaces:

- **HTML** (`html_generator.py`, ~1,364 lines) — the in-app paged preview
  (Paged.js), the surface the author actually looks at.
- **LaTeX** (`latex_generator.py`, ~1,416 lines) — the `.tex` bundle handed off
  to Overleaf for committee sign-off (ADR-0005).

Both renderers are built the same way, because they do the same job: each keeps
a module-level `_DISPATCH` table mapping `node_type → handler`, and each defines
a `_walk(node, data)` that looks up the handler, renders the node, and recurses
into `node.children`. The two `_walk` functions are identical control flow —
`html_generator.py:1163` even says so in its own docstring: *"Same flow as
latex_generator._walk; only the handlers differ."*

The problem is that **"only the handlers differ" is mostly false at the level
that matters.** The handlers overwhelmingly share their *logic* and differ only
in their final *string assembly*. Concretely, `_render_front_matter` and
`_render_labeled_sections` are line-for-line identical in both files —

- same `node.data_key` lookup,
- same `content.get("sections")` → labeled-sections branch,
- same `_render_paragraphs(content.get("paragraphs", []))` fallback,
- same "Section pending" placeholder decision (ADR-0003 decision #8),

and diverge **only** at the leaf: `<p><strong>{label}.</strong> {text}</p>`
versus `\textbf{{{label}.}} {text}`, and `_esc` versus `_escape_latex`. The same
pattern holds across the table handlers (`_render_apical_table`,
`_render_incidence_table`, `_render_genomics_section`): the row iteration, dose
formatting, gatekeeper checks, and footnote-letter logic are the same in both;
the `<table>`/`tabular` wrapping is not. An audit puts the overlap around **75%
(~500 lines of duplicated logic)**.

### Why this is a structural defect, not incidental similarity

Two independent signals say this duplication is real debt and is already biting:

1. **We wrote a test whose only job is to detect drift between the two copies.**
   `tests/unit/test_renderer_dispatch_parity.py` exists because *"Nothing
   structurally forces the two `_DISPATCH` tables to agree, so a node_type added
   to one renderer but not the other would render fine in one output surface and
   silently fall through to `_render_unimplemented` ('[Section pending]') in the
   other — a desync the author would only notice on Overleaf."* That is a guard
   bolted onto a problem the structure should make unrepresentable. A test that
   asserts two hand-maintained lists stay equal is a standing admission that
   they should be one list.

2. **The desync is invisible exactly where it's most expensive.** Per ADR-0005,
   the `.tex` is the committee sign-off surface. The author validates against the
   HTML preview; a handler that's correct in HTML and stale in LaTeX produces a
   correct-looking preview and a broken hand-off — caught late, in Overleaf, by
   the people we least want to expose to tooling bugs.

### What is already shared, and what is genuinely format-specific

This is not a greenfield split — the renderers already pull their data-domain
logic from common modules: `table_builder_common` (`format_display_number`,
`format_mean_se_display`), `render_capabilities` (`landscape_requested`,
`content_item_landscape_requested`), and `document_tree` (`DOCUMENT_TREE`,
`find_node`). The duplication that remains is the **per-node decision logic**
("which shape does this node's data carry, and what rows/labels/captions come
out of it") that currently lives twice, once per renderer.

What is *irreducibly* format-specific and must stay per-renderer:

- **Escaping:** `_esc` (HTML entities) vs `_escape_latex` (LaTeX specials). Not
  shareable — different grammars.
- **Element/markup assembly:** `<table>…</table>` vs `\begin{tabular}…`,
  `<h2>` vs `\section`, the Paged.js `.landscape-block` div + `sec-anchor` span
  vs the LaTeX landscape environment.
- **The one documented divergence:** LaTeX deliberately omits `cover` /
  `title-page` because it builds the title with `\maketitle`; HTML renders them.
  This is the single intentional asymmetry the parity test already whitelists.

### Aside — `_walk` is forked five ways, not two

The same traversal is independently reimplemented in `html_generator.py`,
`latex_generator.py`, `report_data.py`, `data_gatherer.py`, and
`document_tree.py` (plus a partial in `genomics_narratives.py`). The `DocNode`
tree is the canonical structure (Invariant #2) but its *traversal* is not owned
anywhere — every consumer re-derives "look at node, recurse into children."
That is the broader shape of the same defect and is in scope here.

## Decision

**Split each renderer into a format-agnostic `extract` step and a
format-specific `emit` step, and give the `DocNode` tree a single shared walk
that everyone calls.**

### 1. One walk, owned by `document_tree`

Add a visitor/walk to `document_tree.py` (the module that already owns the
tree):

```python
def walk_tree(nodes, visit):
    """Pre-order walk of the DocNode forest; calls visit(node) on each."""
    for node in nodes:
        visit(node)
        walk_tree(node.children, visit)
```

The five ad-hoc `_walk` reimplementations collapse onto this. Each renderer's
walk becomes "register the per-node anchor/landscape wrapping, then dispatch" —
the recursion is no longer its concern.

### 2. `extract` (shared) → `emit` (per-format)

Introduce `render_common.py` holding **extractors**: pure functions that take a
`DocNode` + the `data` dict and return a small, format-neutral intermediate
describing *what* to render — not *how*. For example:

```python
# render_common.py  — format-agnostic, returns plain data
def extract_front_matter(node, data) -> FrontMatter | None:
    """The labeled-sections-vs-paragraphs decision, once."""

def extract_apical_table(node, data) -> TableModel | None:
    """Rows, doses, BMD columns, footnote letters — no markup."""
```

Each renderer keeps a thin **emitter** per node type that consumes the
intermediate and produces markup:

```python
# latex_generator.py
def _render_front_matter(node, data):
    fm = extract_front_matter(node, data)
    if fm is None:
        return _pending_latex(node.title)
    return _emit_front_matter_latex(fm)   # \textbf{...}, _escape_latex
```

The decision logic (the part that drifts and the part the parity test guards)
lives once in the extractor. The emitters are short, obviously-format-specific,
and cannot silently disagree about *which* node types exist (see #3).

### 3. One dispatch registry, two emitter maps

Replace the two independently-maintained `_DISPATCH` dicts with a single
registry of node types in `render_common`, against which each renderer supplies
an emitter map. A node type with no emitter in a given format is a **loud
construction-time error**, not a silent `_render_unimplemented` fall-through.
The `cover`/`title-page` omission becomes an explicit, declared exception in the
registry (LaTeX maps them to `None` with a comment) rather than a difference the
parity test has to know to forgive.

### 4. Retire the drift test as a guarantee, keep it as a smoke check

Once node-type coverage is enforced by the registry (#3), the parity test stops
being load-bearing. Keep a trimmed version as a cheap smoke check, but the
structural guarantee replaces the assertion that two hand-edited lists are
equal.

## Consequences

### Positive

- **~500 duplicated lines deleted**, replaced by extractors written once. Adding
  or changing a node type is a one-place edit to the extractor plus two short
  emitters — and the registry *makes you* write both emitters or fail the build.
- **The ADR-0005 hand-off stops silently desyncing.** HTML preview and `.tex`
  export render from the same extracted model, so "looks right in preview,
  broken in Overleaf" is no longer reachable for shared node types.
- **The tree gets a real traversal owner.** `walk_tree` in `document_tree`
  reifies Invariant #2 in code, not convention; `report_data`/`data_gatherer`
  stop re-deriving it.
- **Extractors are unit-testable without rendering** — assert on the
  `TableModel` directly instead of grepping generated HTML/LaTeX.

### Negative / costs

- **A real refactor of two 1,400-line hot files** (both flagged as god objects:
  `generate_html` in=28, `generate_latex` in=32). High blast radius — this is a
  cross-cutting change and must follow the cross-cutting profile: map callers,
  keep the existing `test_html_generator`, `test_latex_smoke`, and
  `test_renderer_dispatch_parity` green throughout, and land it incrementally
  (one node type migrated to extract/emit at a time) rather than as a big-bang
  rewrite.
- **An intermediate-model layer is new surface area.** `TableModel`,
  `FrontMatter`, etc. must be defined well enough to serve both formats without
  leaking format assumptions; getting that boundary wrong trades duplication for
  a leaky abstraction. Mitigation: extract the easy, provably-identical handlers
  first (`front_matter`, `labeled_sections`, `narrative`) to validate the shape
  before touching the table handlers.
- **Escaping must not leak into extractors.** Extractors return *raw* text;
  each emitter escapes. A raw string that reaches an emitter pre-escaped, or an
  extractor that emits markup, reintroduces the coupling. This is the one
  invariant the new boundary must hold.

### Neutral

- The table *builders* (`*_table.py`, `table_builder_common`) are out of scope —
  that family is healthy and intentionally per-table (NIEHS Report 10 contract).
  This ADR is about the *render* of already-built content, not its construction.

## Migration sketch (non-binding)

1. Add `walk_tree` to `document_tree`; point both renderers' `_walk` at it
   (behavior-preserving; tests stay green).
2. Stand up `render_common` with the three provably-identical extractors
   (`front_matter`, `labeled_sections`, `narrative`); migrate those handlers in
   both renderers; delete their duplicated bodies.
3. Introduce the node-type registry + per-format emitter maps; convert the
   `_DISPATCH` dicts to it; turn missing coverage into a build-time error.
4. Migrate the table handlers (`apical_table`, `incidence_table`,
   `genomics_section`) to extract/emit one at a time.
5. Trim the parity test to a smoke check; collapse the remaining `_walk`
   reimplementations in `report_data`/`data_gatherer` onto `walk_tree`.

## Amendment 1 (2026-06-09) — the shared layer is a semantic IR, not a dedup trick

Steps 1–3 and 4a/4b shipped as written, and in building them the real thesis of
this ADR became clear — sharper than "remove ~500 duplicated lines." Recording
it here because it changes what *correct* means and re-scopes the remaining work.

### The thesis

The `render_common` "plans" (`FrontMatterPlan`, `IncidenceTablePlan`,
`ApicalTablePlan`, …) are not refactoring helpers that happen to be shared. They
are fragments of **one thing: a markup-free, semantic description of the
report** — an intermediate representation (IR). HTML and LaTeX are two
**projections** of that IR.

The most important property of emitting HTML and LaTeX in parallel is **not**
that the code is deduplicated — it is that both surfaces are provably *describing
the same study*, because they read from the same description. A drift between the
two outputs is not a code smell; it is a **semantic inconsistency** — the two
artifacts making different claims about the data. Deduplication is a side effect.
Semantic fidelity across surfaces is the goal.

### The boundary rule (supersedes the narrower "escaping stays in emit")

There are **three** concerns, not two, and each has a home:

1. **Semantics → the IR.** Anything where a disagreement between surfaces would
   mean they describe *different studies*: which endpoints, which rows, which
   dose grid, which figure (identity, number, caption text), and crucially
   *whether a section has content at all*.
2. **Presentation → the emitter.** Anything two surfaces may legitimately render
   differently while still agreeing on meaning: escaping, `<table>` vs
   `tabular`, the `~`-vs-space dose label, `\adjustbox` vs CSS, the `n-row` CSS
   hook, a chart *embedded* as base64 (HTML) vs *referenced* as `figures/<file>`
   (LaTeX).
3. **Transport → the emitter.** Concerns that belong to one surface's downstream
   pipeline, not to meaning: the ADR-0005 per-item override substitution and
   round-trip anchor sentinels are LaTeX-only because only the `.tex` round-trips
   through Overleaf. These correctly stay in the LaTeX emitter and never enter
   the IR.

Litmus test: *if two surfaces could legitimately disagree on it, it is not
semantics.* If a disagreement would make them describe different studies, it is.

### What the rule re-decides

- **The empty-string-paragraph divergence (noted under step 2) is a semantic
  bug, not an edge case.** Today HTML renders `<p></p>` (content present) where
  LaTeX renders `[Section pending]` (content absent) — the two surfaces *disagree
  about whether the section has content*. The "content present / absent"
  decision must move *into* the IR (a `front_matter_plan` that resolves to
  `kind="none"` identically for both), so both surfaces answer it the same way.
  It was deliberately preserved during the refactor (never change behavior inside
  a structural refactor); it should now be fixed as its own change.
- **`is_n_row`, dose-label spacing, table wrapping, chart embed-vs-reference,
  the override/anchor wrapping**: all correctly *outside* the IR — presentation
  or transport. Both surfaces already agree on the underlying meaning.
- **The genomics handler (step 4c) is not a "partial migration compromise."** It
  is the rule applied correctly: the **semantic core** (intro/entries/role
  selection, the gene-set and gene table *rows*, each chart's identity + number
  + caption text) moves to the IR; the **presentation** (embed vs file
  reference, `\subsubsection` vs `<h4>`, adjustbox) and **transport** (per-item
  override + anchor) stay in the emitters. A "fully shared genomics handler"
  would be wrong — it would force transport concerns into the IR.

### How correctness is judged (changes the test strategy)

Per-renderer byte-stability ("this renderer matches its old self," which is how
steps 1–4b were verified) is the *weak* guarantee — right for a behavior-
preserving refactor, but it cannot catch the two surfaces drifting *together*
away from the data. The **strong** guarantee is **cross-surface semantic
parity**: extract the semantic facts from each output (endpoint set, captions,
figure numbers, row counts, content-present decisions) and assert the two
surfaces — and the IR — agree. The node-type registry (step 3) is the semantic
**vocabulary**; the parity test is the proof both projections honor it. This
parity test should replace "trust the byte-diff" as the standing guard.

### Why this is a prerequisite, not competing cleanup

This is the [ADR-0004](0004-bits-jats-export-surface.md) framing — "BITS/JATS as
a projection only" — generalized: **BITS, HTML, and LaTeX are all projections of
one content model.** The BITS export surface ADR-0004 envisions cannot be built
while the semantic description is re-derived inside each renderer; it needs the
IR to exist as a first-class artifact to project from. Completing this IR is
therefore the enabler for ADR-0004, not a refactor that competes with it.

### Re-scoped remaining work (replaces the line-count framing of steps 4–5)

The goal is no longer "dedupe the handlers" but "make the IR complete and
provably faithful":

- **Complete the IR.** Every node type still reading the `data` dict directly
  inside a renderer — `bmd-summary`, `toc`, `tables-list`, `narrative+tables`,
  `appendix`, and the genomics semantic core — gets a plan in `render_common`.
  Only then is the architecture truly "one model, N projections."
- **Add the cross-surface semantic-parity test** and demote byte-diffing to a
  refactor-time check.
- **Fix the empty-paragraph semantic inconsistency** in the IR (deliberately,
  outside any refactor).
- **Genomics (4c):** extract the semantic core per the boundary rule above;
  leave presentation + the ADR-0005 transport in the emitters, and add a
  targeted test that the per-item override + stale-hash attribution still fires
  (the byte/parity diffs won't exercise that branch).
