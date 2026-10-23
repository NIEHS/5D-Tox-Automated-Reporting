# 0031: Safeguards — idiot-proofing as a layer of its own

- **Status:** Accepted (2026-10-23).
- **Deciders:** Dan Svoboda
- **Supersedes:** the deferred "guarantees extraction" (C1, C2, R6 built on
  `ui-redesign`, 2026-10-19), which this lands in its final shape.
- **Related:**
  - `safeguards/` (`acts`, `sections`, `inputs`, `sources`, `publish`,
    `refusals`, `guarded`);
  - `workflow/section_writes.py` (the write policy seam);
  - `tests/unit/test_safeguards_layering.py`,
    `tests/unit/test_safeguards_inputs_sources_publish.py`,
    `tests/unit/test_workflow_legality.py`, `tests/unit/test_section_writes.py`,
    `tests/unit/test_refusals.py`.

## Context

The maintainer: idiot-proofing is the most important purpose of the user
interface, and the notebook is "the workflow and its code without all the
complexities of idiot-proofing". Until now idiot-proofing had no home:

- **On the content branch** it was scattered over `workflow/`, `pipeline/`,
  `web_routes/` and the command line. The legal actions were advisory (no step
  checked them). Some rules lived in one front end only: the vocabulary checks,
  the Background source refusal and the publish gate's `--draft` were the
  command line's; the web routes re-checked state by hand. Several refusals
  (`GuardViolation`, `MethodProfileError`, `DefinitionPinError`,
  `LLMEgressBlocked`) had no handler and reached a person as a 500.
- **On `ui-redesign`** the interface team built C1 (acts refused outside their
  phase; Process refused until a person chose the method), C2 (owned content
  never overwritten by a machine; a reason to force or release), R6 (no data act
  on a companion or report session), atomic integration and a refusal catalog
  in plain words. These were woven into the steps (`require_legal` inside each),
  next to UI-only code.

## Decision

### 1. Two layers

| the core (holds for every caller, the notebook included) | `safeguards` (keeps a person from going wrong) |
|---|---|
| derived state: the phase, the act table (what is legal in each phase), readiness, currency, publish readiness, the integration basis | refusing an act its state forbids (`acts.require`) |
| atomic integration (keep → merge → schema check → restore on failure); `ValidationOutOfDate` (it would combine the wrong files) | refusing Integrate after validation errors or out of date (the phase) |
| every section write archives the prior version and records one history event | refusing a machine's write over owned content; a reason to force, release, restore or discard (`sections.ownership_policy`) |
| path safety, the LLM egress guard, the BMD divergence hard-stop | the method chosen by a person before Process; R6 (`acts`) |
| | the vocabulary checks on stated facts (`inputs`); no Background without ATSDR/IRIS or references (`sources`); the publish gate (`publish`) |
| | the refusal catalog: `code`, `say` (plain words), `fix` (the place in the workflow that clears it), `details` (`refusals.explain`, `error_body`) |

### 2. One entry point for front ends

`safeguards.guarded` has the names and signatures of the core steps
(`validate_step`, `integrate_step`, `run_process`, `accept_section_step`, …).
Each runs its checks, then calls the core step. The web routes and the
command line call it; **the notebook calls the core directly, unguarded**, and
its text says which checks the app and the command line add.

### 3. The import rule

The core packages never import `safeguards` (a test enforces it, for the
notebook's cells too); `safeguards` imports no web or tooling code. Where a core
step writes sections itself (Process materialising its content, the Summary),
it takes a write `policy` (default: permit, still archived); the front ends pass
`safeguards.sections.ownership_policy`.

### 4. The command line is guarded, with named overrides

Each act is checked before it runs. The deliberate bypasses are flags, each
logged:

- `--method-profile NAME`: the person's method choice. Process refuses on a
  study whose profile was pinned automatically until a run states one.
- `--force --reason TEXT`: replace owned content (the Background).
- `--draft`: render past the publish gate.

### 5. Refusals reach a person explained

A FastAPI exception handler maps every refusal to `{"error": message, "code",
"say", "fix", "details"}`, with the status the refusal carries. The `error`
field is the message clients read before, so an old client keeps working.

## Consequences

- The legal actions now refuse. `GET /api/workflow/{id}/state` returns the new
  act names (`REPROCESS`, `CLEAR_FILES` are gone) and `next_step`.
- New refusals on the web: experiment metadata outside the vocabulary
  (`facts_invalid`), a Background without its sources
  (`background_sources_unreachable`, `background_no_references`).
- `ui-redesign` merges this branch, content winning. Its in-step
  `require_legal` calls and `section_writes` policy now live in `safeguards`;
  the interface calls `safeguards.guarded`.
- Not done, pending the maintainer: `pool_admin.invalidate_downstream` and
  `integrate_step`'s cache wipe differ from
  `pool_state.invalidate_pool_artifacts` in what they delete, so they were not
  merged. The unused predicates `phases.is_legal`, `ownership.may_machine_write`,
  `reprocess.can_publish_report` and `currency.assert_can_advance` are kept.
