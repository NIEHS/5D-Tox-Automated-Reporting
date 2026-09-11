# 0018 — The app is not an editor: generate, preview, provisionally approve, round-trip

- **Status:** Accepted (2026-09-11) — governing model; supersedes the in-app
  section-editor direction. Generalizes [ADR-0005](0005-overleaf-round-trip-content-sync.md)
  (Overleaf round-trip) from "one modality" to "the app's role."
- **Deciders:** Dan Svoboda
- **Related:** [ADR-0005](0005-overleaf-round-trip-content-sync.md) (the `roundtrip/` package this
  builds on), [ADR-0015](0015-label-and-guard-model.md) (provisional vs final via
  the fact/guard model), [ADR-0014](0014-ui-agnostic-workflow-engine.md) (derived
  readiness), [ADR-0008](0008-docx-render-surface.md) (the four output surfaces).

## Context — the "aha"

We were fixing a live symptom: in the new UI's Author step, after Process the
Background section generated, but Materials & Methods and Summary showed "Blocked…"
and Results showed "No result sections yet" despite a fully processed pool. Chasing
it surfaced a half-ported authoring lifecycle: nothing materializes Process output
into the section files the Author step reads, and the Author paragraph-editor's
content shape doesn't match the table+narrative shape of the result sections.

The **realization that reframed everything**: we were about to build in-app editors
to close that gap — but **the app should not be a document editor at all.** All human
authoring happens OUTSIDE the app: **MS Word, Overleaf, and future modalities not yet
defined.** A human editing externally can do anything to the document. The app's job
is not to host the editing; it is to stand at the two boundaries of each handoff and
keep them honest.

This is not a new idea bolted on — it is the generalization of what
[ADR-0005](0005-overleaf-round-trip-content-sync.md) already built for Overleaf. ADR-0005 framed
round-trip as one feature; this ADR promotes it to **the app's identity**.

## Decision

**The app is a document GENERATOR, PREVIEW surface, PROVISIONAL-APPROVAL gate, and
HANDOFF CHANGE-TRACKER — not a text editor.** There is no in-app authoring of prose.

Two consequences define every document-side feature:

1. **Editing is external and unconstrained.** The app generates a deliverable
   (docx, Overleaf `.tex`, JATS, …), hands it off, and a human edits it in their tool
   of choice. The app never assumes it knows or controls what happened to the prose
   between handoffs.

2. **Every handoff is tracked in both directions.** app→human (what the app generated
   / provisionally blessed) and human→app (what the human changed). The app must be
   able to **read and record the delta at each boundary** — including reading **MS
   Word tracked changes** (`w:ins`/`w:del` with author/date) during the document
   cycle, not just clean text.

Around those, two obligations:

- **Safeguards** against a human "doing something stupid": detect when an external
  edit broke document structure vs. merely changed prose, and flag/refuse rather than
  silently ingest garbage. (LaTeX: the sentinel-anchor scheme degrades a mangled
  region to a parse warning. Word: OOXML structural validation.)
- **Provisional vs final approval** (per [ADR-0015](0015-label-and-guard-model.md)):
  the app blesses a version as *provisionally* approved — its own generated,
  known-good state. External edits return as a *tracked delta against that baseline*,
  reviewed on the way back in, never silently trusted. Promotion to final is a
  deliberate act, not an implicit consequence of a human having touched the file.

## What this builds on (already exists) vs. the gap

**Exists — the LaTeX/Overleaf round-trip** (`roundtrip/` package, ADR-0005): a clean,
domain-agnostic set — `transport` (git clone + Overleaf push/pull, stand-in), `reconcile`
(baseline↔edited diff attributed to the innermost anchored region), `anchors` (the
sentinel safeguard), `lock` (single-writer handoff baton), `overrides` + `region_hash`
(per-region edit store + stale detection). Generate → hand off → edit externally →
reconcile back is BUILT for this modality.

**Gap — MS Word tracked changes** (unbuilt): `rendering/docx_generator.py` writes
clean docx (no `w:ins`/`w:del`); docx-*reading* exists only for style extraction. Word
does not use the LaTeX sentinel scheme — it carries native OOXML revision markup. The
Word strategy is to PARSE those revision elements directly (who changed what, when) to
reach the same outcome the LaTeX `reconcile` reaches: attribute and record the handoff
delta. Mapping a Word revision back to a report node/region (for attribution) is an
open mechanism question — reuse anchors inside the docx (bookmarks) or attribute by
heading/section.

## Consequences

- **The in-app Author editor (SectionCard draft→edit→accept) is the wrong surface.**
  Re-scope the document workstream to generate / preview / hand-off / ingest-and-
  reconcile / provisionally-approve — not edit. The section-dependency model still
  matters (what to generate when: Background←identity, M&M←post-Process data,
  Summary←approved sections, genomics=deterministic/read-only), because it decides
  what is generated and what is even editable-externally vs frozen.
- **The live bug's real fix** is generate + materialize + preview those sections, with
  external editing as the round-trip — not building editors.
- **Word round-trip is a first-class, sizeable new capability**, parallel to the
  Overleaf path, feeding the same provisional-approval + change-record model.
- Ties the document workstream's actions to derived readiness
  ([ADR-0014](0014-ui-agnostic-workflow-engine.md)): the actions become generate /
  preview / hand off / ingest / provisionally approve.

## Open questions

- Word: read-only (record what the human did) first, or also WRITE tracked changes
  (app proposes edits as Word suggestions the human accepts)?
- Word revision → report node attribution: hidden bookmarks/anchors in the docx, or
  by section/heading?
- Does the Word exchange reuse the git/Overleaf transport (versioned artifact store
  per handoff) or a plainer upload/download?
- What promotes provisional → final: a clean reconcile, an in-app human sign-off, or a
  git merge?
