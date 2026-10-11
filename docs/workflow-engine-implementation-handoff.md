# Handoff: implement the UI-agnostic workflow engine + concept model

**Audience:** an agent (or the maintainer) in a fresh session, tasked with
*planning then coding* the workflow refactor after this session is compacted.

> **✅ BUILT (2026-08-16).** This plan was executed. Steps 1, 2, 3a, 4a, 4b-narrow,
> 5, 6, 7 are implemented and pushed to `origin/package-layout-workflow-engine`
> (commit chain `1482138`→`339611e`; `main` NOT merged). Per-step DONE markers with
> SHAs are inline below. NOT done, by design: **step 3b** (the JS cutover — needs a
> browser to verify) and the **genomics content-store convergence** (the deferred
> half of step 4 / ADR-0015 §Consolidation). This doc is now a RECORD of the build,
> not a forward plan — read it for what shipped and where, and see ADR-0014's
> "Implementation status" block for the same summary. Branch/worktree were renamed
> post-build: `refactor/package-layout` → `package-layout-workflow-engine`,
> `/workspace/rlm-bmdx-refactor` → `/workspace/package-layout-workflow-engine`.

**Status:** the CONCEPTS are settled and the recon is DONE. This document converts
them into a **sequenced build plan** with per-step test gates and blast radius.
You are not starting cold. But the repo drifts — re-verify the starred (★) facts
before trusting a step.

**Read first, in this order:**
1. `docs/adr/0014-ui-agnostic-workflow-engine.md` — the engine design + the
   "framing widened" caveat at the top.
2. Memory `project_workflow_concept_model.md` — the six-kind taxonomy that is the
   *why* behind everything here. **This handoff assumes it.**
3. Memory `project_ui_workflow_decoupling.md` — succession context + branch state.
4. `CONTEXT.md` invariants 1–3 (source-of-truth, tree-drives-structure,
   phase-derived-never-set). The engine must preserve all three.

**Ground rules (from CLAUDE.md + this project's memory):**
- Solo dev, pushes on the host — the sandbox has no push token. Commit freely on
  `package-layout-workflow-engine` (the branch, renamed from `refactor/package-layout`);
  do NOT push from the sandbox. [The 8 build commits were later pushed by the user
  from the host.]
- Treat this as a **cross-cutting refactor**: map blast radius, move incrementally,
  keep the suite green at every step. Never big-bang.
- Behavior-preserving where the step says so; new behavior only where the concept
  model calls for it, and always behind a test.
- Packaged layout is live: imports are `from pipeline.x import ...`,
  `from rendering.x import ...`, etc. Entrypoint `python -m web_routes.background_server`.

---

## 0. The concept model in one screen (so the plan is legible)

Six kinds of thing, not one "phase machine":

1. **Phases** — ordered, DERIVED, one-at-a-time readiness. Two: pool
   (`EMPTY→UPLOADED→VALIDATED→INTEGRATED→APPROVED`) and section authoring. "Phase"
   belongs ONLY here.
2. **Transforms / views** — render (pure projection), preview (a view). Not phases.
3. **Report lifecycle** — one LIVING bundle, mutable forever; nothing freezes at
   FINAL/PUBLISHED. Status = guardrails + history-capture, not immutability.
4. **Labels** — an OPEN, per-content-kind set of asserted facts (`approved`,
   `final`, `protected`, `published`, …). Maturity is a **ratchet** (promote =
   add-fact, cheap; demote = remove-fact, guarded+recorded, or currency-forced).
   `final` = `protected` + "editorially done" (strict superset, NOT a synonym).
5. **Provenance** — the record of how content was built (history dimension).
6. **Currency** — is a label still valid vs. its inputs? DERIVED. Stale content is
   **BLOCKED** from advancing until a human re-blesses.

Cross-cutting rule: **humans assert FACTS; the system DERIVES consequences**
(phase, guard, currency). **Guard** = an ordered scale, `max` over live facts,
**derived-never-stored**, on two axes: enforce-against-machines (on from first
edit) / inform-humans (rises at final/published).

---

## 1. Recon findings that constrain the plan (verified this session — RE-VERIFY ★)

Five read-only agents mapped the seams. The load-bearing facts:

### 1a. Pool steps are EASY to unwrap; the real coupling is module globals
The authoring steps already delegate their real work to `bmdx_pipe.*`; the FastAPI
handlers are mostly file-IO + HTTP glue.
- `api_pool_validate` (`web_routes/pool_routes.py`★:83) → `ensure_fingerprints` +
  `validate_pool`. ~40% glue, no Request. **Easy.**
- `api_pool_resolve` (:138) → append to `precedence.json`. Pure file logic. **Easiest.**
- `api_pool_confirm_metadata` (:197) → writes txt/csv headers + `_fingerprints.json`.
  ~15% glue. **Easy.**
- `api_pool_integrate` (:309) → `integrate_pool(...)` via `run_in_executor`. ~30%
  glue; the executor call + lightweight-summary-vs-full-payload split are the two
  things to factor out. **Moderate.**
- `api_process_integrated` (`pipeline/process_integrated.py`★:962) — **already the
  cleanest**: parses into `ProcessContext` (plain HTTP-free dataclass, ADR-0002),
  runs Layer functions. HTTP glue confined to ~:991–1037 and ~:1198–1229. Port =
  wrap the Layer functions under one `run_process(ctx)`. (It mixes async
  orchestration + sync layers — the engine stays async or wraps an event loop.)
- `api_generate_animal_report` (:1233) → `build_animal_report` via executor. **Easy.**
- `api_session_approve` (`web_routes/session_routes.py`★:698) — heaviest side
  effects (bg-thread style-learning, /tmp bm2 copy). Do LAST.

**THE hazard:** every step reads/mutates module-level dicts in
`pipeline/pool_globals.py` (`_pool_fingerprints`, `_integrated_pool`,
`_data_uploads`, keyed by dtxsid). A truly UI-agnostic engine must thread these as
explicit state/params, NOT reach module globals. This is the crux of ADR-0014's
open question #2 (disk-reading vs injected store) — decide it HERE, because the
unwrap touches every step.

### 1b. Provenance: section history EXISTS, structure/style history does NOT
- `pipeline/session_store.py`★ archives each prior section version under
  `sessions/{dtxsid}/history/{section_key}/{ts}.json` before overwrite;
  `save_section(dtxsid, key, data, archive=True)` bumps `version =
  count(history)+1`; `archive=False` = in-place (flag flips / autosave). Metadata:
  `approved`, `approved_at`, `version`, `stale`.
- ★ `document.yaml` and `styles.yaml` have **ZERO** provenance —
  `document_model/document_config.py` `save_session_document_yaml` /
  `save_session_layout_style` plain-overwrite. **Structure/style history is
  build-from-scratch**, mirroring the section pattern.

### 1c. Currency gap is PRECISE and small
- `pipeline/cache_plumbing.py`★ hashes are **purely data-derived** — no
  algorithm/method version anywhere. Schema-version constants
  (`_NTP_CACHE_SCHEMA_VERSION` etc.) are the only method proxy, and are manual.
- ★ **`_hash_bmds` (:314) has NO schema-version term at all** — recomputing BMDs
  with a new algorithm on identical dose-response data yields an identical hash and
  serves stale BMDs. **This is the primary currency gap.** Fix = inject a
  `_BMDS_METHOD_VERSION` (or the pybmds/model-settings version) into `_hash_bmds`,
  cascade via `_hash_bmd_summary` (already folds `bmds_hash`) into
  `_hash_sections`/`_hash_ntp` for narrative dependents.
- Separate `stale` flag: `pipeline/pool_state.py`★:131 `invalidate_pool_artifacts`
  sets `section_data["stale"]=True` on pool mutation (preserves edits); cleared on
  re-approval (`session_routes.py`★:781); JS shows an amber badge. This is
  approval-governance, orthogonal to the content hashes, and fires on pool
  composition change ONLY — never on methodology. Currency-block must unify these:
  the hash detects the change, the `stale` flag + block enforces re-blessing.

### 1d. Render annotation has a COPY-PASTE template
- Shared IR: `rendering/render_common.py`★ `walk_emit(...)` (:1237); its `_visit`
  (:1302) is the chokepoint: `handler → emit_pre → wrap_landscape → wrap_style →
  **wrap_post** → append`. `walk` = `document_tree.walk_tree` (passed in).
- **The pattern to copy = ADR-0005 overrides + `landscape_requested`**: a
  `data[...]` map keyed by **`node.id`**, resolved in ONE helper, surfaced per
  surface. `latex_generator._apply_override`★:1348 / `html_generator._apply_override_html`★:1257
  (wraps in `.override-edited`/`.override-stale`, CSS ~:180).
- A **per-node protection/guard annotation** = twin of that: add a resolver in
  `render_common.py`, feed `data["protection"]` keyed by node.id, read it in
  `latex_generator._wrap_post`★:1566, html wrap_post + a `.protected` CSS rule,
  `docx_generator._walk_docx_tree._visit`★:1853 (docx does NOT use walk_emit —
  runs walk_tree directly), `jats_generator._append_node`★:562 (own recursion).
  `DocNode.id` (`document_model/document_node.py`:105) is globally unique.

### 1e. Guard is a CONSOLIDATION job, not greenfield (the big one)
Enforcement of "user-owned / don't silently recompute / approved" is **smeared
across ~6 sites / 5 modules / 3 stores** — NOT one gate:
- **3 stores:** ADR-0005 round-trip overrides (`sessions/<dtxsid>/_document_overrides.json`,
  clean lib `roundtrip/overrides.py`★ — real predicate `_apply_override`, real
  `clear_override`); genomics-narrative overrides
  (`genomics_narrative_overrides.json`, ad-hoc, no module); per-section `approved`/
  `approved_at`/`stale` stamped on section JSON by `session_routes.py`★.
- **Duplicated enforcement:** round-trip override checked at render time
  reimplemented per surface (latex :1348, html :1257), loaded in two more places
  (`report_data.py`★:462, `latex_export.py`★:689). Genomics "override wins" merge
  duplicated across `process_integrated.py`★:362 and `session_routes.py`★:555.
  LLM regen self-guards via a `force` flag inside `llm_routes.py`★:1026.
- **Building the guard = CONSOLIDATE these three onto one predicate.** The
  round-trip lib is the nearest-to-clean thing to converge on. This is the
  largest, riskiest piece — schedule it late and behind heavy tests.

---

## 2. Build sequence (each step: its own commit, suite green, gate named)

Ordered so each step de-risks the next. **Steps 1–3 are the ADR-0014 port
proper; 4–7 add the concept-model capabilities.** Stop-and-check with the
maintainer at the ★ decision gates.

### Step 1 — port the pool phase machine (the committed gate arms here)
> ✅ **DONE `1482138`** — `workflow/phases.py` (`Phase`/`Action`, `LEGAL_ACTIONS`,
> `derive_phase`/`compute_section_completeness`/`is_node_complete`); 34-case gate armed.
- Create `workflow/` package. Port the 3 JS functions from `web/js/pool_state.js`
  into `workflow/phases.py`: `derive_phase(artifacts) -> str`,
  `compute_section_completeness(coverage_matrix) -> dict`,
  `is_node_complete(node_id, completeness, tree) -> dict`. Signatures are fixed by
  the committed characterization gate.
- **GATE:** `tests/unit/test_workflow_phase_characterization.py` — its 34 skipped
  port-comparison cases auto-arm the moment `workflow.phases` imports. Make them
  green. Do NOT edit the case table or oracle to pass (see its
  `_EVOLVING_THIS_CONTRACT`).
- Also build `LEGAL_ACTIONS: dict[Phase, frozenset[Action]]` from the `enabled:`
  flags in `POOL_PHASES`. Add `Phase`/`Action` enums (settled phases only — drop
  the transient VALIDATING/INTEGRATING/APPROVING; those are per-UI).
- ★ **Decision gate (ADR-0014 Q2):** disk-reading engine vs injected store.
  Recommend disk-reading now (matches today), but decide before step 2 since the
  unwrap threads state either way.

### Step 2 — unwrap the pool steps into HTTP-free callables
> ✅ **DONE `783e860`** — `workflow/steps.py` (5 steps) over injectable
> `workflow/store.py`. **Q2 decided: injectable PoolStore** (not disk-reading).
- Extract each handler body (1a order: resolve → confirm-metadata → validate →
  generate-animal-report → integrate → process-integrated → approve) into
  `workflow/steps.py` functions taking explicit params (dtxsid + threaded pool
  state), returning plain results. Routes become parse → call → serialize.
- Thread `pool_globals` dicts as explicit state per the step-1 decision — this is
  the "truly UI-agnostic" payoff.
- **GATE:** existing integration tests (`test_pool_integrate.py` etc.) + the
  `bmdx-tests` guard net stay green. This step is behavior-preserving.
- Assemble `workflow/engine.py` `WorkflowEngine(dtxsid)` over steps + phases.

### Step 3 — thin the JS; wire routes to the engine
> ✅ **3a DONE `57f5c55`** — `workflow/engine.py` (`WorkflowEngine.state()`,
> derived-never-stored) + `GET /api/workflow/{dtxsid}/state`; hasIntegrated/
> hasAnimalReport de-conflated; static import-isolation guard (workflow ↛ web_routes).
> ⛔ **3b (JS cutover) NOT DONE** — deleting `derivePoolPhase` + rewiring its ~13
> call sites needs a browser to verify (E2E `page.pause()`-gated); left to the host.
> The server side is ready and tested.
- Routes call the engine. `pool_state.js` DELETES `derivePoolPhase` +
  completeness fns, consumes `legal_actions` from the server, KEEPS `POOL_PHASES`
  as a pure `action→DOM` lookup + `renderPoolControls`.
- ★ **The one intended behavior change:** feed `hasIntegrated` and
  `hasAnimalReport` SEPARATELY (integrated.json exists vs animal_report.json
  exists) instead of the JS caller's `!!animal_report` conflation. This lives in
  caller wiring, NOT the pure fn — the characterization gate does NOT cover it.
  **Add a route/integration test for it** (ADR-0014 follow-up).
- **GATE:** e2e pool flow still works; add the de-conflation test.
- Add an import-graph guard: `workflow/` never imports `web_routes/`.

### Step 4 — the label + guard model (facts → derived guard)
> ✅ **4a DONE `3581965`** — `workflow/labels.py` (facts + ratchet) +
> `workflow/guard.py` (max-over-facts, two axes) + **ADR-0015**.
> ✅ **4b-narrow DONE `24789a9`** — `workflow/ownership.py`: `may_machine_write`
> (unified machine-guard predicate) + `protection_map` (real facts → the step-5
> render mark; MACHINE-PROTECTED semantics). Adapter over existing booleans, no
> migration.
> ⛔ **4b content-store convergence NOT DONE** — migrating the genomics override
> JSON onto `roundtrip/overrides.py` + deduping the "override wins" merge; deferred
> (ADR-0015 §Consolidation, still Proposed), needs genomics render-parity tests.
- `workflow/labels.py`: per-content-kind label vocabularies; a fact record
  (asserted, with the ratchet: promote=add / demote=remove-guarded).
- `workflow/guard.py`: `guard_level(node) = max over live facts`,
  **derived-never-stored**. Implements `final = protected + editorial`;
  `final→protected` auto-set; `published` (report grain) as a floor.
- **This is where 1e's consolidation happens** — converge the 3 override stores
  onto one predicate. Heaviest step; behind the most tests. Consider its own ADR.
- **GATE:** new unit tests for the fact/guard truth table + the ratchet
  (promote-cheap / demote-guarded / demote-currency-forced); the existing
  override/approval behaviors still hold.

### Step 5 — render the guard (visual protection marks)
> ✅ **DONE `e3f8ab7`** — `data["protection"]` per node.id, resolved once in
> `render_common.resolve_protection`, surfaced in all 4 emitters (latex/html/docx/
> jats). Byte-identical when absent. Real facts wired in by 4b-narrow (`24789a9`).
- Add the `data["protection"]` annotation per 1d, keyed by node.id, resolved once
  in `render_common.py`, surfaced in all 4 emitters (copy the ADR-0005/landscape
  pattern exactly).
- **GATE:** renderer dispatch parity stays green; snapshot tests show the mark on
  a protected node across surfaces.

### Step 6 — currency (block on stale)
> ✅ **DONE `d1db206`** — `_BMDS_METHOD_VERSION` folded into `_hash_bmds` (cascades
> to the BMD-summary cache; NOT to `_hash_sections`, by design) + `workflow/currency.py`
> (`is_stale`, `can_advance`/`assert_can_advance` BLOCK, `demote_for_currency`).
- Inject `_BMDS_METHOD_VERSION` into `_hash_bmds` (the 1c gap) + cascade. Generalize
  the `stale` trigger from pool-mutation-only to any input/method change. Wire
  BLOCK: stale content cannot advance (go final / publish / render-as-final) until
  re-blessed.
- Start COARSE (stale-everything) — the dependency graph (what-derived-from-what)
  is load-bearing under block and can be refined later; log what gets staled so
  coarse ≠ silent.
- **GATE:** a methodology-version bump on identical data now invalidates dependents
  (today it does NOT — that's the proof test).

### Step 7 — structure/style provenance
> ✅ **DONE `339611e`** — `save_session_document_yaml`/`save_session_layout_style`
> archive-before-overwrite into `history/<kind>/<ts>.yaml`; list/read/restore
> helpers (restore routes through the validating save, so it's a recorded edit).
- Give `document.yaml` / `styles.yaml` the same archive-before-overwrite history
  as sections (1b), so "how the structure was built" is recorded — required by the
  reports-never-terminate model.
- **GATE:** editing structure twice leaves a history trail; restore works.

---

## 3. Still-UNDECIDED (needs maintainer input — do not guess)
- ★ ADR-0014 Q1: synchronous engine vs shared job/progress abstraction for the
  10-min `process()`. Leaning sync now; revisit when the per-section cache split
  (backlog) reshapes `process()`.
- ★ ADR-0014 Q2: disk-reading vs injected store (decide at step 1).
- Label contract must accommodate BOTH derived (`approved`-data) and asserted
  (`protected`/`final`) labels — pin the shape before step 4.
- Per-content-kind label vocabularies: enumerate them (data / narrative / report)
  before step 4.
- Does the guard consolidation (step 4) warrant its own ADR? (Recommend yes.)

## 4. Definition of done (the whole arc)
- `workflow/` owns phase derivation, step execution, labels, guard, currency;
  imports `pipeline/`+`document_model/`, never `web_routes/` (guard test).
- Web UI + a future TUI both drive the engine; phase logic exists in ONE place
  (Python), not JS. Characterization gate green.
- Facts asserted by humans; guard/currency/phase derived. Guard renders as a
  visual mark on all 4 surfaces. Stale content is blocked until re-blessed.
- Structure/style edits carry history. Reports never freeze.
- ADRs updated; memory `project_workflow_concept_model.md` reconciled to code.
