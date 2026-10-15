# C1 — Legal actions are enforced: contract

Against the shared error envelope (MODULES §4.2):
`{"error": {"code", "status", "message", "say", "fix", "details"}}`.
C1 adds three codes (one reserved) and changes the response of five routes.
Every `message` below is the backend's text, verbatim, with `{…}` filled in; the
`say` is written in the backend beside the code.

## 1. Refusals C1 adds

### 1.1 `phase_not_allowed`: an action outside the phase's legal actions

- **Status:** 409.
- **Raised by:** `workflow.engine.require_legal` (`PhaseRefusal`), from every
  entry point in spec §2.2.
- **message:**
  `{ACTION} refused for {dtxsid}: the study is in phase {PHASE} (allowed now: {LEGAL}). {NEXT}`
  - `{LEGAL}` is the sorted legal actions, comma-separated, or `nothing`.
  - `{NEXT}`, per state:

    | state | `{NEXT}` |
    |---|---|
    | EMPTY | `Add the study's files first.` |
    | UPLOADED | `Validate the files first.` |
    | VALIDATION_ERRORS | `Fix the validation errors, then validate again.` |
    | VALIDATED, never integrated | `Integrate first.` |
    | VALIDATED, integration out of date | `Its integration was built from a different validation; integrate again.` |

- **say:** `{Act} isn't possible yet. {phase say}`

  | `{ACTION}` | `{Act}` |
  |---|---|
  | REMOVE_FILE | Removing a file |
  | RESET | Clearing the study's files |
  | VALIDATE | Checking the files |
  | RESOLVE | Choosing between conflicting files |
  | CONFIRM_CLASSIFICATION | Correcting what a file is |
  | INTEGRATE | Combining the files into one dataset |
  | STATE_DATASET_FACTS | Stating the study design or the experiment details |
  | APPROVE | Approving the data |
  | PROCESS | Processing |

  ADD_FILES is never refused in C1.

  | state | `{phase say}` | fix |
  |---|---|---|
  | EMPTY | This study has no data files yet. Add the study's files first. | M2 |
  | EMPTY, for REMOVE_FILE or RESET (replaces the whole say) | This study has no files to remove. | M2 |
  | UPLOADED | The study's files have changed since they were last checked, or were never checked. Run the file check first. | M2 |
  | VALIDATION_ERRORS | The file check found errors. Fix what it lists (remove or replace the files it names), then run the file check again. | M2 |
  | VALIDATED, never integrated | The study's files have been checked but not yet combined into one dataset. Integrate the study first. | M3 |
  | VALIDATED, integration out of date | The study's dataset was combined from an earlier file check that no longer matches its files. Integrate the study again first. | M3 |

  INTEGRATED and APPROVED never refuse: every action is legal there.
- **details:**
  `{"action": "PROCESS", "phase": "VALIDATED", "legal_actions": [...], "integration": "current|out_of_date|unrecorded|null", "next_action": "INTEGRATE"}`

### 1.2 `validation_out_of_date`: integration's consistency check (the restart trap)

- **Status:** 409. **Raised by:** `integrate_step` (`ValidationOutOfDate`).
  **fix:** M2.
- **message:**
  `INTEGRATE refused for {dtxsid}: the validation report no longer matches the files the server holds ({DETAIL}). Validate again, then integrate.`
  `{DETAIL}` joins with `; ` whichever apply:
  - `{n} file id(s) in its coverage matrix are not among the current fingerprints`
  - `files added since validation: {names}`
  - `files missing since validation: {names}`
- **say:** The file check is out of date: it no longer matches the study's files
  as the server sees them now. This happens after the server restarts, or when
  files change outside the app. Nothing was combined and nothing was changed. Run
  the file check again, then Integrate.
- **details:** `{"missing_ids": n, "added": [names], "missing": [names]}`

### 1.3 `method_not_chosen`: reserved, only if decision D1 is option A, B or D

- **Status:** 409. **Raised by:** `run_process`, after the phase guard.
  **fix:** M5.
- **message:**
  `PROCESS refused for {dtxsid}: no method profile has been chosen (method_profile.json is {absent|pinned by default}). Pin one, then process.`
- **say:** Choose the analysis method (the method profile) this study is reported
  under before processing. Every statistic, benchmark dose and the Methods text
  depend on it, so it is never chosen for you.
- **details:** `{"pin": null | {"name", "pinned_by", "mode"}}`

## 2. Routes whose response changes

| Route | Change |
|---|---|
| `GET /api/workflow/{id}/state` (and the kit's `GET /api/v2/studies/{id}/state`) | `legal_actions` takes the values of spec §1: `PROCESS` replaces `REPROCESS`; `CLEAR_FILES` is gone; `ADD_FILES`, `REMOVE_FILE`, `RESOLVE`, `CONFIRM_CLASSIFICATION`, `STATE_DATASET_FACTS` are added; EMPTY gives `["ADD_FILES"]`. `artifacts` gains `"integration": "current" \| "out_of_date" \| "unrecorded" \| null`. `phase` is VALIDATED when the integration is out of date |
| `POST /api/pool/integrate/{id}` | adds `"approval_withdrawn": bool`. `method` becomes `{profile, pinned_by, mode, deviations, mismatches}` with nulls and empty lists when no profile is pinned; it is never `pinned_by: "default"` from integration. New refusals: 409 `phase_not_allowed` (at UPLOADED and VALIDATION_ERRORS), 409 `validation_out_of_date` |
| `POST /api/process-integrated/{id}` | outside INTEGRATED and APPROVED: 409 `phase_not_allowed` instead of 400, and nothing is written (no `method_profile.json`, `document_definition.*`, `_fingerprints.json`) |
| `POST /api/pool/validate/{id}` | at EMPTY: 409 `phase_not_allowed` instead of 404. The body on success is unchanged |
| `POST /api/generate-animal-report/{id}` | outside INTEGRATED and APPROVED: 409 `phase_not_allowed` (today it succeeds) |
| `POST /api/pool/resolve`, `POST /api/pool/confirm-metadata/{id}`, `POST /api/pool/materialize-sections/{id}`, `POST /api/experiment-metadata/{id}`, `DELETE /api/pool/{id}/files/{name}`, `POST /api/pool/reset/{id}`, the three uploads with `?dtxsid=` | can return 409 `phase_not_allowed` (uploads: never in C1). The body on success is unchanged |

Command line: on any refusal, `step failed (409): {message}` followed by
`  {say}`.

## 3. Requests to other parties (through the orchestrator)

- **Kit, `workflow/refusals.py`.** Read from the uncommitted kit worktree; it may
  change.
  - Take `say`, `fix` and `details` from the exception when it carries them
    (`PhaseRefusal`, `ValidationOutOfDate`). `phase_not_allowed` needs a `say` and
    `fix` per state, and the reserved entry today has a fixed text and
    `fix: None`.
  - Add `validation_out_of_date` and the reserved `method_not_chosen` to
    `REFUSALS`.
  - The kit's `_details` already reads `phase` and `legal_actions` from the
    exception; C1 provides them.
- **Orchestrator.**
  - How the existing routes carry the envelope: `pool_routes._step_error_response`
    and `integrated_routes` return `{"error": "<message>"}` today. C1's 409s use
    whatever shape the kit decides for wrapped routes.
  - Update the `legal_actions` example in MODULES §4.1 and the table in HANDOFF
    §4.1 (decision D3).
