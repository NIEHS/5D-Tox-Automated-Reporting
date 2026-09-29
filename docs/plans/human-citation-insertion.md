# Human citation insertion — design (PINNED, not scheduled)

Status: DESIGN, pinned 2026-09-02. Not scheduled — belongs with the Phase 4/6
editing-surface work (the "citations are protected tokens" note in
`project_integrated_wizard_versioned_preview.md`). Written up so it is addressed
deliberately, not rediscovered.

## The problem

A human editor needs to insert a literature citation into a narrative that the
system otherwise owns. The report's References section is DERIVED: the reference
list is auto-numbered in document order from a machine-built candidate pool
(graph-grounded, `narrative/references_builder.py`), and inline `[Pn]` tokens are
rewritten to report-wide `[n]` at render. So a human-authored citation collides
with a value the system re-derives on every render.

The concrete human workflow we must support (user's words): the editor inserts an
inline `[4]` in concordance with the narrative so far, adds reference entry #4 to
the References section, increments the subsequent entries (5→6→7…), and saves.

- **If that is the LAST action before a final export:** fine, it renders as typed.
- **If the document goes BACK to the app** (re-render or reprocess): it breaks,
  because numbering re-derives and the reference list is rebuilt — overwriting the
  human's #4 and their bumps; and on reprocess the human's paper (never in the
  graph pool) simply vanishes. Inline and list desync, or the citation is lost.

## Key correction (why this IS recoverable)

The inline `[4]` is NOT a bare number — it is an INDEX into a list the human also
authored, and reference-list entry #4 carries the actual PAPER IDENTITY
(title / journal / year / ideally DOI). So the PAIR *(inline `[4]`, list-entry #4)*
is a complete citation the reconciler can lift. The number is the human's ad-hoc
POINTER; the list entry is the IDENTITY. What the human is doing is
HAND-IMPLEMENTING AN ANCHOR — and the reconciler's job is to lift that pointer+
identity pair back into a proper anchor, after which numbering re-derives
automatically. (An in-app citation picker produces the same anchor directly. Both
paths END AT ANCHORS; the number was never stored truth — only transport.)

## The model: humans author ANCHORS, the system derives NUMBERS

Reference NUMBERS are positional/derived — same class as table numbers (CLAUDE.md
invariant 2: "Table numbers are positional, auto-assigned by tree walk, never
user-provided") and the same "humans may not edit data-derived content" rule from
Phase 2. A human must never OWN a number; they own an ANCHOR = a citation keyed to
a stable PAPER IDENTITY (DOI, or a pick from the pool, or full metadata for an
off-graph paper).

Core mechanism once anchors exist:

- **Unified pool** = graph papers ∪ human-supplied papers, deduped by DOI.
- **One numbering pass** over ALL citation anchors — machine `[Pn]` AND human
  anchors — in document order, emitting the inline `[n]` AND the reference list
  TOGETHER, so they CANNOT disagree (two outputs of one computation).
- Human anchors live in the USER-OWNED store, so a reprocess that regenerates the
  MACHINE narrative must preserve + re-merge them (the "user-owned content is never
  silently recomputed" rule) rather than clobber them.

## The reconciler (Word round-trip path)

On a document returning from human editing, reconstruct intent BEFORE any
re-derivation:

1. Parse the human's edited reference list → extract each entry's IDENTITY.
   DOI present ⇒ deterministic. No DOI ⇒ fuzzy match (title + year) against the
   pool / graph.
2. Map each inline `[n]` → the list entry at position n → that entry's identity.
3. Diff the human's list against the machine's list. Entries matching pool papers
   map back to their `[Pn]`; entries with NO match are the human's NEW papers.
4. Lift the new papers into USER-OWNED anchors; merge into the unified pool.
5. Re-derive numbering over the whole set in document order → inline `[n]` + list
   emitted together. The human's paper lands wherever document order puts it (maybe
   `[4]`, maybe `[6]`) — the human never needed `4`, they needed "cite THIS paper
   here," and the number now tracks automatically.

Ordering discipline (ADR-0005): reconcile the human's edits against the BASELINE
they edited from FIRST (capture anchors), THEN reprocess/re-derive. Reprocess first
and the baseline the diff needs is destroyed. Same rule as the round-trip override
store.

## Fragilities (where it is fragile, not broken)

1. **Identity extraction from a free-text entry.** DOI ⇒ clean; title-only ⇒ fuzzy,
   can mis-hit/miss. This is the SAME gap as the structured `<element-citation>`
   need in the BITS/JATS work (`project_bits_export`) — references need structured
   identity, not just prose, for robust matching.
2. **The reconciler trusts the human's numbering as-saved.** A bungled renumber
   (insert #4 but forget to bump a downstream `[6]`) reproduces the inconsistent
   intent — GIGO. The system should DETECT the inconsistency, not silently
   propagate it.
3. **Off-graph papers** never appear in the graph pool, so they exist ONLY as
   user-owned anchors — the reprocess-preserve rule (above) is what keeps them
   alive across a regenerate.

## Insertion paths (increasing round-trip safety)

1. **Type a bare number `[4]` + list entry #4 in Word** — recoverable via the
   reconciler ABOVE, IF the human edits BOTH halves and the entry has extractable
   identity (prefer DOI). Valid as the last action before export; survives the app
   only through reconciliation.
2. **Type a KEYED token in Word** (e.g. `[@doi:10.1234/xyz]`) — survives directly
   if the human uses the convention; the reconciler parses the key to an anchor.
   Requires discipline/training.
3. **Insert via the app** (a citation picker: search the pool, or add a new paper
   with metadata) — cleanest: the anchor is authored as DATA, never as text to be
   parsed back. Citation insertion happens in the app, not by free-typing in Word.

Recommendation: support **(1)** because the user's real workflow is exactly that
(number + list entry) and it IS reconcilable; **STRONGLY PREFER / require DOI** in
human-added entries to make step-1 matching deterministic (kills the fuzzy layer);
keep **(3) an in-app picker** as the clean primary for those who'd rather not
hand-edit the list. All three converge on the same core: anchor + unified pool +
single numbering pass.

## Sharpened detect-and-warn (supersedes the current bare-`[n]` warning)

The shipped warning (`detect_override_citation_hazards`, merged 2026-09-02) flags
any bare `[n]` in an override → FALSE-POSITIVES on legitimate "…as reported [1]".
Replace it, once this design lands, with a PAIRING-CONSISTENCY check:

- inline `[k]` with NO corresponding new list entry AND no pool `[Pn]` → incomplete
  anchor (a genuinely unrecoverable dangling pointer) → warn.
- a human list entry that NO inline cites → orphan → warn.
- inline numbers that don't form a consistent sequence with the list (the bungled
  renumber) → warn.

This checks PAIRING CONSISTENCY, not the presence of a number — so the
false-positive problem disappears.

## What this touches (blast radius, when scheduled)

- `narrative/references_builder.py` — unified pool (graph ∪ user), single numbering
  pass over all anchors, `load_persisted_references`.
- A new USER-OWNED anchor store (or extend `genomics_narrative_overrides.json` /
  `roundtrip/overrides.py`) — human anchors, preserved across reprocess.
- The reconciler — new; the ADR-0005 round-trip machinery (diff vs baseline) is the
  template.
- Structured reference identity (DOI-bearing entries) — overlaps
  `project_bits_export`'s `<element-citation>` need; do them together.
- The editing surface (Phase 4/6) — citation Slots as protected tokens; the in-app
  picker (path 3).

Related: `project_integrated_wizard_versioned_preview.md` (Phase 2 data-derived
rule + the merged detect-and-warn hazard note), `project_bits_export`,
ADR-0005 (round-trip override reconciliation).
