# 0020 — One evolving report with history, not a tree of coexisting versions

- **Status:** Accepted (2026-09-14) — settles a standing contradiction between
  [ADR-0014](0014-ui-agnostic-workflow-engine.md) and
  [ADR-0016](0016-canonical-query-substrate.md) on the report's version model.
- **Deciders:** Dan Svoboda
- **Related:** [ADR-0014](0014-ui-agnostic-workflow-engine.md) (its concept-model
  caveat #3 — "one living bundle, MUTABLE FOREVER … one snapshot, no version tree" —
  is the position this ADR ratifies), [ADR-0016](0016-canonical-query-substrate.md)
  (whose `versions/<name>.yaml` + "a version *is* a rendering domain" framing this
  ADR narrows), [ADR-0015](0015-label-and-guard-model.md) (labels/currency are the
  guardrails-and-history model that replaces a version tree),
  [ADR-0018](0018-app-is-not-an-editor.md) (generate/preview/approve/round-trip acts
  on the one report), `project_integrated_wizard_versioned_preview`
  (the "dual-cause snapshots" = history, consistent with this decision).

## Context — the contradiction

Two accepted ADRs assume opposite answers to one concrete question: **can two named
versions of a report be alive at the same time?**

- **[ADR-0016](0016-canonical-query-substrate.md) says yes.** It builds
  `versions/<name>.yaml`, `resolve_version_filters`, `build_version_tree`, a live
  `/api/versions/{dtxsid}` CRUD surface, and elevates the idea to a north star:
  "a version *is* a rendering domain" (a structure + a query set), with versions as
  the unit of extensibility — a branch/tag model.
- **[ADR-0014](0014-ui-agnostic-workflow-engine.md) says no.** Its concept-model
  caveat: "one living bundle, MUTABLE FOREVER — nothing freezes at FINAL/PUBLISHED …
  one snapshot, **no version tree**." Status is guardrails + history, not parallel
  copies — a Google-Doc model.

Both are partially built: the versions API exists (0016 side); the append-only
`history/` archive + "mutable forever" labels exist (0014 side). The code does not
reveal intent — it reveals that both were pursued. This is an unmade decision, and
it propagates: [ADR-0019](0019-metadata-vocabulary-policy.md) and the wizard/preview
work both had to guess which model is live.

## Decision

**The application holds ONE report per study, which evolves in place, with history
behind it. There is no tree of coexisting named report versions.**

Concretely:

1. **One current report.** A session has a single live report bundle. Generate,
   preview, provisional-approval, and hand-off/round-trip
   ([ADR-0018](0018-app-is-not-an-editor.md)) all act on *that one report* — there is
   never a question of "which version am I previewing."
2. **History is an audit/undo trail, not a branch set.** The past is reachable
   (the per-section `history/{key}/*.json` + append-only `history/{key}/index.jsonl`
   cause log; the "dual-cause snapshots" of content+preview on edit and on
   reprocess). History lets you *look back and restore*; it does not create parallel
   living reports you switch between. (Mental model: a Google Doc's revision history,
   not Git branches.)
3. **Status is guardrails, not immutability.** Nothing freezes at FINAL/PUBLISHED.
   Labels (maturity ladder, `protected`) and currency ([ADR-0015](0015-label-and-guard-model.md))
   govern what may change and flag stale content; they do not fork the report.
4. **The `versions/` mechanism is retained as single-report resolution, not a branch
   store.** `version_config` + `build_version_tree`/`resolve_version_filters` stay —
   but their role is settled as **resolving THE report** (everything already defaults
   to `DEFAULT_VERSION = "default"`, and `preview_surface`/`latex_export` render that
   default). A named non-default entry is a **saved filter/tree preset (a *view* of
   the one report)**, NOT a coexisting living report with its own approval state and
   history. The `/api/versions` CRUD is demoted accordingly (manage presets), not a
   version-control surface.

## What this rejects, and what it does NOT

**Rejected (from [ADR-0016](0016-canonical-query-substrate.md)):**
- Multiple named report versions alive at once (branch/tag model).
- "A version *is* a rendering domain" **as the unit of the report** — the report is
  not a selected node in a version tree.

**Explicitly NOT rejected — 0016's substrate and rendering-domain seam survive,
decoupled from "versions":**
- The canonical per-session **query substrate** (`session.duckdb`) and the read-only
  query layer stand entirely — they were never about versioning.
- **Rendering domains** (the `data_key`→query resolver + shape adapters, 0016 Phase
  E) remain a valid north star, but **decoupled from versioning**: a rendering domain
  is a set of query/shape bindings for the one report, not "one of many coexisting
  versions." 0016's equation "a version = a rendering domain" loses its *version*
  half; the *rendering-domain-as-binding-seam* half is unaffected. When Phase E is
  built, bind domains to the single report, not to a version tree.

## Consequences

- **[ADR-0014](0014-ui-agnostic-workflow-engine.md) caveat #3 is ratified** as the
  report-lifecycle model; [ADR-0016](0016-canonical-query-substrate.md)'s version
  framing is narrowed to "saved presets/views over the one report" (its substrate +
  rendering-domain-seam intent is preserved).
- **No version-switcher UI, no per-version approval/history.** Simpler surface: one
  report, one approval state, one history. The wizard/preview work's "dual-cause
  snapshots" are correctly understood as history, not a version tree — consistent, no
  change needed there.
- **`versions/<name>.yaml` is a filter/tree PRESET store.** If the "version"
  vocabulary proves misleading (it implies branches), a future rename to
  *preset*/*view* is warranted — flagged, not required here. No code must change to
  adopt this ADR: the default-single-report path is already what runs.
- **[ADR-0019](0019-metadata-vocabulary-policy.md) is consistent with this** — its
  "authority order settles dual-represented metadata" operates on the one report; it
  does not need a version tree.
- **Hand-off/round-trip ([ADR-0018](0018-app-is-not-an-editor.md)) has one baseline.**
  Provisional approval blesses the current report; external edits reconcile against
  that single baseline — there is no ambiguity about which version was handed off.

## Open questions

- **Rename `versions/` → presets/views?** Deferred. The mechanism is fine; only the
  noun risks implying a branch model this ADR rejects. Decide when the configurator
  or rendering-domain work next touches that surface.
- **Preset scope.** A saved preset today can carry filters + a tree + methods. Its
  boundary as a *view of the one report* (vs. accidentally re-growing into a
  quasi-version with its own state) should be pinned when presets get real UI.
