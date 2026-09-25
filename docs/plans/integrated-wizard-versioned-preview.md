# Plan — Integrated wizard + versioned preview

Target design captured in memory `project_integrated_wizard_versioned_preview.md`
(2026-09-01). Branch: `package-layout-workflow-engine`. This plan sequences the
work into phases that each land behind a test gate and are independently useful.

Guiding constraint: every readiness/lock/publish state is **DERIVED**, never
imperatively set (CONTEXT.md invariant 3 / `feedback_state_derivation`). The
ad-hoc `ready.*` + `btn.disabled` toggles are what made approve/lock/unlock feel
broken; the whole point is to replace them with derivation.

---

## Phase 0 — Section content-kind classification (foundation, server-side)

Nothing branches correctly until the system knows LLM vs programmatic per section.

- Add a `content_kind` / `llm_derived` property, sourced from the document node /
  section kind (NOT hardcoded in `pool_state`). Map today's implicit knowledge:
  Background, M&M, genomics interpretation, Summary = LLM; apical results, tables =
  programmatic.
- Single read point consulted by both the reprocess router (Phase 3) and the
  publish gate (Phase 4).
- **Gate:** unit test asserting each known section resolves to the right kind;
  no behavior change yet.

## Phase 1 — Lift section authoring into the workflow core

Give the document-structure workflow the same UI-agnostic treatment the pool
workflow already has (ADR-0014). Today section generate/edit/approve lives only in
HTTP handlers + JS.

- Add authoring steps to `workflow/steps.py` (HTTP-free, `(…, store)`):
  `generate_section_step`, `edit_section_step`, `accept_section_step`
  (approve/lock), `release_section_step` (unapprove/unlock, records a
  `DemoteReason`). These wrap logic currently in `session_routes.py`.
- Extend `WorkflowEngine` with **`derive_section_readiness()`** — the derived
  replacement for `ready.methods` / `ready.summary`: reads which sections are
  approved + the tree's declared **section dependencies**, returns per-section
  `{enabled, blocked_by, guard_level, currency}`. Dependencies become tree data,
  not JS conditionals.
- **Gate:** characterization test — feed known approved-sets, assert the derived
  readiness matches the current JS `ready.*` behavior byte-for-byte (same
  discipline as the pool-phase oracle). This LOCKS the existing dependency rules
  before moving them.

## Phase 2 — Programmatic sections as editable templates (representation)

The hard representation change from Decision 3. `unified_narrative.py` already
builds prose from `TableRow` — the slot seam half-exists.

- Introduce an explicit **template representation**: prose scaffolding + typed
  live data-slots (BMD/count/dose tokens), rendered against the section's data.
- A wording edit is captured as a **new personal template with slots intact**
  (per section + version + writer), NOT frozen prose. Edit surface must preserve
  slots (edit-the-template, never edit-the-rendered-string).
- Re-rendering a personal template against newer data = "refresh numbers, keep
  wording" for free.
- **Gate:** round-trip test — render template→edit wording→reprocess with changed
  numbers→assert wording preserved AND numbers updated. Programmatic sections with
  no edit still render identically to today (byte-identical safety).

## Phase 3 — Currency responses on reprocess (by kind)

Replace the uniform `mark_pool_stale` (`pool_state.py:193-210`) with kind-aware
routing (Decision 2), composing the existing `workflow/currency.py`.

- **Programmatic:** re-render (numbers update via Phase 2); no stale flag, no
  block.
- **LLM:** auto-**rewrite** + set a visible `regenerated_reason` marker; apply
  `currency.demote_for_currency` (`CURRENCY_FORCED`) so it drops below
  final/approved and must be re-accepted. NOT silent.
- **Report:** `currency.can_advance` refuses `published` while any LLM section
  carries a live needs-re-bless marker.
- **Gate:** unit tests over each kind's reprocess path; publish-gate test asserts
  block while any LLM section is unrefreshed, clears after re-accept.

## Phase 4 — Dual-cause versioned snapshots (content + preview)

Extend `session_store` history (Decision 4). Today it archives section content on
approve only.

- Every **accepted edit** (human) and every **data reprocess** (system) writes a
  RETAINED snapshot tagged with **cause** (`edit` / `reprocess`) + timestamp, into
  one interleaved per-section (and report-level) history.
- Snapshot content by kind: programmatic = personal template + the data it
  rendered against; LLM = accepted prose.
- Snapshot **includes the materialized preview HTML** (Phase 5) for that state.
- Version carries a **status**: reprocess-version born `needs-re-bless`
  (publish-blocked); accepted-edit version born `blessed`; re-accept transitions
  needs-re-bless→publishable WITHOUT minting a new version.
- Restyle does NOT bump a version (styling is separate — Decision 1).
- **Gate:** tests for cause-tagging, status transitions, and that a restyle
  produces no new content version.

## Phase 5 — Materialize the preview as a static HTML file

Replace the ephemeral srcdoc path (`export_routes.py:694`) with an artifact
(Decision 5).

- On each report-update event (accepted edit / reprocess / restyle), write
  `sessions/<dtxsid>/preview.html` (self-contained; protection marks already ride
  in via `data["protection"]`). Restyle regenerates the current file without a
  version bump.
- Serve at a stable URL; the frame uses `iframe src=…`, separate window uses
  `window.open(…)`. Retain per-version snapshots (Phase 4).
- Surface the LLM "regenerated, and why" marker + publish-blocked warning IN the
  HTML (Decision: both surfaces).
- Rebuild can run async/background (decoupled from the edit request).
- **Gate:** file materializes on each trigger; content matches the on-demand
  renderer for the same state; empty/unowned report stays byte-identical.

## Phase 6 — Integrate into ONE wizard UI (needs browser/host)

Bring the document-structure authoring stage into the React wizard (Decision:
merge the two UIs), consuming the derived readiness from Phase 1.

- New authoring steps after `Approve` in `wizard-ui/`, driven by
  `derive_section_readiness()` — section enable/lock/warning all rendered from
  DERIVED state, never client-side `ready.*` toggles.
- Preview panel points at the materialized `preview.html` (frame or window).
- Publish action gated by the derived report status.
- **Gate:** manual browser verification (E2E is `page.pause()`-gated in-sandbox —
  this phase is the user's to drive on the host, per prior UI-work discipline).

---

## Sequencing notes

- Phases 0–5 are server-side and testable in-sandbox; Phase 6 needs a browser.
- Phase 2 (template representation) is the riskiest/most novel — it's the
  prerequisite for the "refresh numbers, keep wording" guarantee. Consider a spike
  first.
- Each phase is independently useful: 0–1 already fix the derived-readiness bug
  that likely caused the original dissatisfaction, even before templates/preview.
