# 0015 — Label + guard model: facts humans assert, consequences the system derives

- **Status:** Accepted (2026-08-16) for the model + `workflow/labels.py` +
  `workflow/guard.py`. **Proposed** for the store consolidation (§Consolidation,
  step 4b) — that part changes render-surface behavior and is deferred.
- **Deciders:** Dan Svoboda
- **Related:** [ADR-0014](0014-ui-agnostic-workflow-engine.md) (the engine this is
  a layer of; its concept-model caveat enumerates the six kinds — labels are #4,
  currency #6); [ADR-0005](0005-overleaf-round-trip-content-sync.md) (the
  round-trip override store this consolidates onto); `CONTEXT.md` invariant 3
  (derived-never-stored — guard obeys the same discipline). Full rationale +
  the rubber-duck history: memory `project_workflow_concept_model.md`.

## Context

Report content carries human judgements — "this narrative is done," "don't let the
LLM touch this," "this report is published." The codebase expressed these as a
scatter of ad-hoc marks: a per-section `approved` boolean stamped in
`session_routes.py`, an ADR-0005 round-trip override store
(`roundtrip/overrides.py`), a separate genomics-narrative override JSON, and a
`force` flag inside `llm_routes.py`. Enforcement of "user-owned / don't silently
recompute" is duplicated across ~6 sites in 5 modules over 3 stores.

The concept-nailing session (memory `project_workflow_concept_model.md`)
established that these marks are not one enum. The word `approved` alone was doing
double duty (data readiness vs narrative maturity), and `protected` / `final` /
`published` were being treated as interchangeable when they are not.

## Decision

Split label handling into **two layers**, and make the whole thing an **open,
per-content-kind** system.

### 1. Facts (asserted) vs guard (derived)

- **Facts** — what a human asserts (or, for `approved`, what the system derives
  from artifacts): `final`, `protected`, `published`, `approved`, plus the
  narrative maturity rungs. Independently settable; each carries meaning the
  others don't. Live in `workflow/labels.py`, grouped into per-content-kind
  **vocabularies** (data / narrative / report). Adding a future adjective is one
  vocabulary entry + one guard-contribution row — never a reshape.
- **Guard** — the single CONSEQUENCE the facts point at: "how hard to edit, by
  whom." An ordered scale (`OPEN < GUARDED < PUBLISHED`), computed as **`max` over
  the live facts**, **derived-never-stored**. Lives in `workflow/guard.py`.

Why derived-never-stored: clearing `protected` must drop the guard only if `final`
isn't also holding it up. Recomputing `max` over live facts gets this clear-order
case right for free; a stored `guarded` boolean would not (same reason as
invariant 3).

### 2. `final` = `protected` + editorial (strict superset, not a synonym)

Promoting to `final` **auto-sets** `protected` (an implication, `final → protected`).
The reverse is false — manual-lock (`protected` alone) reaches the same GUARDED
rung *without* the editorial claim, so it must be able to exist without `final`.
Synonymy would require the biconditional; only the forward direction holds. The
"+ editorial" is the top rung of the maturity ladder (first → working → **final**);
collapsing the two would destroy it.

### 3. Two guard AXES (projections of the fact set, not the scalar)

1. **against machines** (LLM/regeneration) — hard, deterministic refusal. ON as
   early as the first user edit (a "user-owned" working draft), *below* `final`.
2. **against humans** — the soft/inform guard (the visual "protected" mark). ~nil
   on a working draft, rises at `final`, highest at `published`. Never a wall: a
   human with rights always overrides (recorded, per the ratchet).

Principle: **enforce against actors that can't reason; inform the actors that can.**
Axis 2 is what the renderer surfaces (step 5 pulls a per-node guard signal into the
render IR).

### 4. `published` is a report-grain FLOOR, not a node label

`published` is a real-world release event at REPORT grain. It sets a floor that
propagates onto every node (`with_published_floor`); node-grain facts can only
RAISE from there. A report→node derivation, not a label copied down. Labels at
different grains can never be synonyms.

### 5. Maturity is a RATCHET, not a ladder

Up and down are DIFFERENT operations, not one reversed:

- **promote** = ADD a fact — cheap, default-OK, moves *with* the guard.
- **demote** = REMOVE a fact — moves *against* the guard, so it is REFUSED
  (`GuardViolation`) unless a `DemoteReason` is supplied: `HUMAN_RELEASE`
  (voluntary, recorded) or `CURRENCY_FORCED` (involuntary, system). A removal
  counts as a reversal when it lowers the derived guard OR drops the top maturity
  rung; a removal that changes neither consequence is free.

Hence the engine models transitions as add-fact/remove-fact with different
permission checks — **not** a symmetric `set_maturity(level)`. The ratchet framing
also captures currency (§6): stale content is knocked down with nobody choosing
it — the pawl force-released.

### 6. Currency BLOCK (relationship, implemented later)

When currency flips to stale (new data OR new derived-quantity methodology), stale
content is **BLOCKED** from advancing (can't go final/publish/render-as-final)
until a human re-blesses — a correctness invariant, not coordination, so "inform
humans" does not soften it here. `CURRENCY_FORCED` is the demote reason the block
uses. The trigger generalization (method-version in the hash) + the dependency
graph are handoff step 6, not this ADR.

## Consequences

- One place defines what each fact means (`labels.py`) and what edit-hardness it
  contributes (`guard.py`). A new adjective is additive.
- Guard becomes a **renderable property of content** (axis 2) — a new deliberate
  coupling workflow-core → render surface, realized in step 5.
- The model is pure and fully unit-tested (`tests/unit/test_workflow_labels_guard.py`,
  30 cases) with no I/O — it composes with any store.

## Consolidation (step 4b — Proposed, deferred)

The three existing override stores must converge onto this one predicate, with
`roundtrip/overrides.py` (the cleanest — real `set/clear/get_override` +
`region_hash` for currency) as the convergence target:

1. per-section `approved`/`stale` stamped in `session_routes.py`,
2. the ADR-0005 round-trip override store,
3. the ad-hoc genomics-narrative override JSON (duplicated across
   `process_integrated.py`, `session_routes.py`, `llm_routes.py`).

This is the largest, riskiest piece — it changes behavior at render time across
four surfaces and touches the LLM regen `force` path. It is deferred to pair with
step 5 (render the guard) so the consolidation and its visible effect land and are
tested together, behind the render snapshot tests. The pure model (this ADR's
accepted part) is a prerequisite and stands alone until then.
