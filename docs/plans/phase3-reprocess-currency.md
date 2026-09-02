# Phase 3 design — kind-aware reprocess currency

Status: DRAFT for review (2026-09-02). Depends on Phase 0 (`workflow/content_origin`)
and Phase 2 (`narrative/section_template.categorical_flips`), both committed.
Design source: memory `project_integrated_wizard_versioned_preview.md` Decision 2.

## The problem this fixes

On a data reprocess, `pipeline/pool_state.py:invalidate_pool_artifacts` today marks
**every** `bm2_*.json` and `genomics_*.json` `stale=True`, uniformly. That is too
blunt in three ways:

1. **Programmatic sections don't need re-blessing.** A `bm2_*` apical section is a
   deterministic projection of data (Phase 2 templates). Its numbers should just
   refresh; there is no human LLM judgement to protect. Marking it stale forces a
   pointless re-approval.
2. **LLM sections need a *loud, attributed* rewrite, not a silent flag.** A
   `genomics_*` narrative embodies model output the human blessed. On new data it
   should be **rewritten** — but visibly ("regenerated because the data changed"),
   and knocked below approved so a human re-accepts before publish.
3. **Publishing is not gated on currency at all.** Nothing stops a report with
   stale LLM conclusions from advancing.

The pure machinery to fix this already exists (`workflow/currency.py`: `is_stale`,
`can_advance`, `demote_for_currency`) but is **not called** by the reprocess path.
Phase 3 is the wiring: route the reprocess by content-origin, and gate publish.

## Design

### The three responses (Decision 2), by content-origin

`workflow.content_origin.is_llm_section(section_key)` is the router.

| Origin | Reprocess response |
|---|---|
| **Programmatic** (`bm2_*`) | **Do NOT mark stale.** Numbers refresh by re-rendering the section's template (Phase 2) against new data. Author wording (personal template) preserved. A CATEGORICAL slot flip is the one exception — see below. |
| **LLM** (`genomics_*`, background, methods, summary, bmd_summary) | **Rewrite + attribute + demote.** Regenerate the narrative, stamp a `regenerated: {reason: "data_changed", at: <ts>, prior_version: n}` marker, and `demote_for_currency` so it drops below approved/final. NOT silent. |
| **Report (whole)** | **Block publish** while any LLM section carries a live un-re-accepted `regenerated`/stale marker. |

### The programmatic categorical-flip caveat (from the Phase 2 spike)

"Programmatic auto-updates silently" is true for NUMERIC deltas but NOT for a
CATEGORICAL slot flip (direction increased↔decreased, trend positive↔negative) —
an author's hand-written wording can contradict a flipped word. So the
programmatic path is:

- re-render the template against new data;
- run `section_template.categorical_flips(template, old_binding, new_binding)`;
- if flips exist AND the section carries author wording edits (a personal
  template), stamp a lightweight `wording_review: [flipped_keys]` marker so the
  UI can flag "a data-derived word changed under your wording." NOT a hard block
  (programmatic content asserts no LLM judgement); it is an inform-signal.
- if no author edits (default template), no marker — the default wording is
  regenerated wholesale anyway.

NOTE: this requires the section to persist its template + the binding it last
rendered against, so a reprocess can diff old-vs-new bindings. That persistence
is **not yet in place** — see "Prerequisite" below. Until it is, the programmatic
path degrades to "refresh, no flip detection" (still better than today's
mark-everything-stale).

### Where it goes

A new pure router in the workflow core, called by the reprocess seam:

- **`workflow/reprocess.py`** (new, pure): `classify_section_reprocess(section_key,
  section_dict, *, old_binding=None, new_binding=None, template=None) ->
  ReprocessAction`, where `ReprocessAction` is one of
  `REFRESH_NUMBERS` / `REFRESH_WITH_WORDING_REVIEW` / `REWRITE_LLM` / `LEAVE`.
  Pure decision over origin + flip detection; no I/O. Unit-testable in isolation.
- **`pipeline/pool_state.py:invalidate_pool_artifacts`** stops the blanket
  `stale=True` loop and instead, per section, consults the router:
  - programmatic → do not stale (mark for numeric refresh on next process);
  - LLM → keep the stale flag (its current meaning) AND record the
    `regenerated` intent so the next genomics/LLM pass rewrites-with-reason.
  - This keeps `invalidate_pool_artifacts` doing disk work but delegating the
    *decision* to the pure router.
- **Publish gate**: wherever the report-grain `published` fact is asserted (the
  future publish action — not yet built; for now the gate lives as a function
  `workflow/currency.py` can host or a new `can_publish_report(sections) -> bool`
  that returns False if any LLM section is stale/regenerated-unaccepted). Compose
  with the existing `assert_can_advance`.

### Composition with existing model (no new concepts)

- programmatic refresh = `content_origin` PROGRAMMATIC + `blocks_machine_regen` is
  already False for it → machine may rewrite freely. Consistent.
- LLM rewrite-with-reason = `demote_for_currency` (CURRENCY_FORCED) + a
  `regenerated` provenance marker. The demote already exists and is tested.
- publish block = `can_advance(..., is_stale=True)` returning False, lifted to
  report grain over the section set.
- re-acceptance = the human re-approves (Phase 1 `accept_section_step` clears
  `stale`), which flips the section fresh and clears the publish block — no new
  mechanism.

## Prerequisite (may split into Phase 2.5)

Full programmatic flip-detection needs each `bm2_*` section to persist **(a)** its
template and **(b)** the binding it last rendered against. Today the section JSON
stores rendered `paragraphs`, not template+binding. Options:

1. **Phase 3a (no persistence):** ship origin-based routing + LLM
   rewrite-with-reason + publish gate NOW; programmatic path just "don't stale +
   refresh", no flip detection. Delivers the main value, unblocks publish
   correctness.
2. **Phase 3b (persistence):** add template+binding persistence to `bm2_*`
   sections, enabling `categorical_flips` at reprocess. Larger — touches how
   `unified_narrative` output is persisted in `process_integrated`.

Recommend **3a first** (small, high-value, fully testable), **3b** as a follow-up
once the template representation is persisted rather than rendered-then-stored.

## Test plan

- `workflow/reprocess.py` pure unit tests: each origin → correct `ReprocessAction`;
  flip present/absent → REVIEW vs REFRESH; unknown key → fail-safe to REWRITE_LLM
  (conservative, matches `content_origin` fail-safe).
- `invalidate_pool_artifacts` characterization: assert programmatic sections are
  NO LONGER marked stale, LLM sections still are — a deliberate behavior change,
  pin it. (This CHANGES existing behavior; add the before/after to a test so the
  change is explicit, like the Phase 1 unlock tightening.)
- publish gate: report with a stale LLM section → cannot publish; after
  re-accept → can. Composes `can_advance`.
- Regression: existing `invalidate_pool_artifacts` callers (upload_routes x3,
  pool_admin, pool_orchestrator) still behave; the `stale-badge` UI still fires
  for LLM sections.

## Blast radius / risk

- `invalidate_pool_artifacts` is called from 5+ sites (upload add/replace/zip,
  pool_admin reset, orchestrator). Changing WHICH sections it marks stale is a
  real behavior change — must be pinned by characterization test and flagged to
  the maintainer (same discipline as the Phase 1 unlock change).
- The `regenerated` marker is new section-JSON state — additive, fail-safe
  (absent = today's behavior).
- Merge note: touches `pipeline/pool_state.py` + new `workflow/reprocess.py`.
  DISJOINT from the references branch (`report_data`, `process_integrated`
  genomics-persist, `llm_routes`, `latex_export`) EXCEPT possibly
  `process_integrated` if the LLM rewrite-with-reason hooks into the genomics
  pass. Sequence Phase 3 AFTER the references branch merges to avoid the overlap.
```
