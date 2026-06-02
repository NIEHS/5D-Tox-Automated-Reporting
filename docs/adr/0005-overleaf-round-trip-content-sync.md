# 0005 — Overleaf round-trip: human-in-the-loop content sync

- **Status:** Proposed (2026-06-01)
- **Deciders:** Dan Svoboda
- **Related:** [ADR-0001](0001-bmdproject-schema-as-load-barrier.md) (the
  integrated dataset every component reads through);
  [ADR-0003](0003-document-component-model.md) (the document-component model and
  its **sub-addressable content items with stable IDs** — the anchor grain this
  layer round-trips against); [ADR-0004](0004-bits-jats-export-surface.md) (the
  BITS/Bookshelf projection that must consume *reconciled* content so committee
  edits reach the published product); the **LaTeX/Overleaf pivot** project memory
  (Overleaf is the chosen sign-off surface); the **genomics user-owned narrative
  store** (commit `551be0a`) — the provenance pattern this ADR generalizes from
  one section to the whole report.

## Context

The application already does the hard upstream work: it ingests a study's data,
runs the analysis, builds every table and figure, drafts the narrative, and
assembles a complete, publication-formatted report from the canonical `DocNode`
tree (ADR-0003). Today that report leaves the system as a **one-way `.tex`
export**: we can *push* a bundle toward Overleaf, but we have no way to *absorb*
what a human does to it afterward.

That one-way boundary is the wrong shape for how the report actually gets
finalized:

1. **A committee finalizes the report in Overleaf.** Overleaf is their familiar
   environment and the sign-off surface; we are not going to build a WYSIWYG
   editor to replace it.
2. **After sign-off, we are not done.** The signed-off content must be projected
   to **BITS/JATS** for NCBI Bookshelf (ADR-0004) — which produces the published
   web product and the hosted PDF. NCBI owns that *rendering*; we own the
   *content*. So committee edits must live in **our content model**, not only in
   an Overleaf project, or they never reach publication.
3. **The application must stay the system of record** for data and generated
   content, iterating with Overleaf edits, **with the author in the middle** — so
   that regenerating a section from fresh data does not silently destroy a
   human's wording.

### The precedent we are generalizing

We already solved this exact problem once, narrowly. The **genomics user-owned
narrative store** (`551be0a`) made an LLM-generated narrative, once a human owns
it, **never silently recomputed** on data drift: the override is authoritative,
regeneration is explicit (a per-organ *Regenerate* button + `force` flag), and
the stored override surfaces instead of fresh machine text. This ADR is that
pattern **promoted from one section to every node in the report**, with Overleaf
as the editing surface and `git` as the transport.

### What makes this tractable (and what does not)

Syncing a *generated* artifact with a *hand-edited* one is the classic
round-trip problem, and LaTeX — a Turing-complete macro language — is the
worst-case input for it. It is tractable **only because we own the generator**:
we can emit the `.tex` as a *parseable interchange format* with stable per-node
anchors, and reconcile edits inside those anchored regions. Outside them (new
macros, restructuring, preamble edits) faithful reverse-mapping is the
WYSIWYG-LaTeX swamp, and we will not attempt it — we detect and surface such
edits rather than guess. The design therefore stands or falls on **disciplined
anchoring + a constrained editability contract**, not on a clever parser.

## Decision

**Add a bidirectional Overleaf sync layer that promotes the `.tex` from a
one-way export to a round-trip interchange format, with per-node edit
provenance.** The `DocNode` tree remains the single source of truth for
*structure and data* (invariant #2); committee edits become *per-node content
overrides* on that tree. Four parts:

### 1. Transport — Overleaf git-bridge

Treat the Overleaf project as a **git remote** (Personal Access Token auth). The
app **pushes** the generated bundle and **pulls** the committee's edits as
commits. `git` is not only the transport — its diff is the change-detection
substrate (part 3). Each push records a **generated-baseline commit**; each pull
is the **human-edited commit** to diff against that baseline.

git-bridge is available on **Overleaf Cloud premium** plans and **Server Pro
4.0+** (where it must be explicitly enabled). Tier availability is the
feasibility gate — see Open Questions. If unavailable, the layer degrades to a
**manual import/export** round-trip (documented as the degraded path, not the
optimal one).

### 2. Anchored projection — stable per-node sentinels

`latex_generator` wraps each **editable region** in sentinel **comments** keyed
to the ADR-0003 sub-addressable content-item IDs (e.g. `liver-male-narrative`):

```latex
%% rlm:begin liver-male-narrative
… generated prose …
%% rlm:end liver-male-narrative
```

Because they are LaTeX comments, the sentinels are **invisible in the compiled
PDF** (the rendered output is byte-identical), they survive ordinary editing, and
they provide a **region ↔ node map**. The preamble, `niehs.cls`, and structural
scaffolding lie *outside* any editable region.

### 3. Reconciliation — git-diff × sentinel map

On **pull**, diff the human-edited commit against the last generated-baseline
commit. For each changed hunk, locate the **enclosing sentinel region** → the
owning node. Extract that region's current text; if it differs from what we
generated, record a **user override** for that node. Attribution granularity is
the content-item (the ID grain). The engine is a bounded *diff-and-attribute*
pass, not a LaTeX parser.

### 4. Provenance / merge — generalize the genomics store

Track, per node / content-item:

```
{ generated, user_override?, edited_at, source_commit }
```

- **Override wins and is never silently recomputed** (the genomics rule).
- The UI badges the node **"edited in Overleaf."**
- **Explicit regenerate** clears the override (the genomics escape hatch).
- If fresh data *would* change a region currently under an override, the system
  **flags "underlying data changed — review,"** it does not clobber.
- **Both** the LaTeX and BITS projections render from the *reconciled* content
  (generated ∪ overrides), so a committee edit propagates to the Overleaf PDF
  **and** to the Bookshelf publication from one source.

### The three policy calls this layer pins

These define the editability contract that keeps reconciliation bounded:

- **(A) Editability scope.** v1: **prose / narrative regions are
  Overleaf-editable and round-tripped; data-derived regions (tables, computed
  numbers) are app-owned.** An edit *inside* a data region is a *data correction*,
  not a prose edit — it is detected and **surfaced as a warning, not absorbed**.
  (A sentinel comment can tell editors "edit this in the application.")
- **(B) Structural edits.** v1: **structure is app-owned.** Adding, removing, or
  reordering sections, and preamble/`cls` changes, are **not** round-tripped;
  structural drift (missing / extra / reordered sentinels) is **detected and
  surfaced as an unreconciled-structure warning** for a human, never auto-applied.
  Structure changes happen in the app (the DocNode template).
- **(C) Conflict policy.** **Override-wins + review-flag** whenever regeneration
  would change an overridden region.

## Migration shape (when implementation is approved)

Design only; no code changes here. A plausible sequence, each step independently
landable:

1. **Anchored projection.** Emit sentinels around content-item regions in
   `latex_generator`; assert the compiled PDF is byte-identical (comments are
   invisible). Landable now, independent of transport.
2. **Override / provenance store.** Generalize the genomics per-`(organ, sex)`
   store to a per-node content store keyed by content-item ID; the read path
   prefers an override over generated text.
3. **Transport.** A git-bridge client (push baseline, pull commit), PAT config,
   and baseline-commit bookkeeping.
4. **Reconciliation engine.** git-diff × sentinel map → attribute hunks → write
   overrides; plus the structural-drift detector.
5. **UI.** "Edited in Overleaf" badges; per-node regenerate (extend the genomics
   *Regenerate* control); the "data changed under an override — review" flag.
6. **Round-trip oracle.** A fixture report: push → simulate an edit in one prose
   region → pull → assert exactly that node gains an override and others do not;
   assert a simulated table edit and a structural change surface as **warnings**,
   not silent absorption (ADR-0002 golden-discipline spirit).

## Consequences

### Positive

- **One source of truth from raw data to the Bookshelf page**, with committee
  edits captured, attributed, and carried through to **both** the PDF and BITS.
- **Reuses `git`** (transport *and* change detection) and the **genomics
  provenance pattern** — minimal net-new machinery for a large capability.
- **`.tex` becomes interchange, consistent with invariant #2:** edits become
  per-node overrides; structure stays tree-owned.
- **No custom editor to build** — the committee stays in Overleaf, their trusted
  surface.
- **Closes the "regeneration silently clobbers human work" risk** for the whole
  report, not just genomics narratives.

### Negative / risks

- **The round-trip ceiling is real and must be honest.** Reliable only inside
  anchored prose regions; free-form edits (new macros, restructuring, anything
  outside the sentinels) degrade to *unreconciled-diff-for-a-human*. We surface,
  we do not guess.
- **Depends on ADR-0003 IDs being stable and complete.** An unanchored region
  cannot round-trip; coverage of editable content by content-item IDs is a
  prerequisite.
- **Sentinel discipline.** An editor who deletes or relocates a sentinel comment
  breaks attribution for that region — mitigated by detecting missing/!moved
  sentinels and warning, but it is a sharp edge.
- **Tier dependency.** git-bridge requires Overleaf premium / Server Pro 4.0+;
  the optimal loop is unavailable on free Cloud / Community Edition.
- **Two-writer hazard.** If the app regenerates *and* a human edits between sync
  points, correct attribution depends on faithful **baseline bookkeeping** (the
  last-pushed commit). Mis-tracking the baseline mis-attributes edits.
- **Data edits are intentionally not absorbed.** A committee member who "fixes" a
  number directly in an Overleaf table will see it flagged/reverted on the next
  sync — this needs clear UX messaging so it is not surprising, and a v2 path
  (capture it as a *data-correction proposal*) is worth considering.

## Alternatives considered

- **Build a WYSIWYG / in-app editor instead of using Overleaf** *(rejected).*
  Reinvents an editor, discards the surface the committee already trusts, and
  removes Overleaf as the sign-off venue.

- **Keep one-way export; edits live in Overleaf forever** *(rejected).* The app
  stops being the system of record, edits never reach BITS/Bookshelf, and
  regeneration either clobbers or permanently diverges from the human copy.

- **Round-trip arbitrary LaTeX with a full parser** *(rejected).* LaTeX is
  Turing-complete; faithfully reverse-mapping free-form edits is the
  WYSIWYG-LaTeX swamp. The sentinel-anchored prose-region approach captures the
  tractable 90% and is honest about the rest.

- **Edit a structured form (JSON/markdown) in the app, treat Overleaf as
  read-only** *(rejected for v1).* The committee wants to edit *in Overleaf*
  directly. App-side structured editing remains a possible complement later, not
  the primary loop.

- **Manual import/export (zip up / zip down) as the sync** *(fallback only).*
  The degraded path if git-bridge is unavailable on the client's tier; recorded
  so the workflow fails gracefully rather than breaking.

## Open questions

- **Overleaf tier / git-bridge availability** — the feasibility gate. Confirm
  Cloud premium vs Server Pro 4.0+ (git-bridge enabled) vs an unsupported tier.
- **Sentinel format robust to editor reflow** — comment syntax that survives
  reformatting and is hard to clobber accidentally.
- **Project lifecycle** — one Overleaf project per report recreated each push, or
  a persistent project updated in place? This drives the commit-baseline
  bookkeeping in part 3.
- **v2: capture data/table edits as data-correction proposals** rather than
  discarding them — closing the loop on policy (A) without re-keying.
