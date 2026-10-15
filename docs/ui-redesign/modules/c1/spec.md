# C1 — Legal actions are enforced: spec

Module C1 of the core-guarantees track (`MODULES.md` §2). Spec stage, 2026-10-14.
Evidence marks: **[V]** verified by running it, on scratch copies or in the test
suite under a scratch-only plugin (nothing in the repo changed); **[R]** read from
the code. Citations are `file:line` in `/workspace/rlm-bmdx-ui`. The scratch
drivers are in `/workspace/ui-team/_scratch/spec-c1/{scripts,audit}/`.

## 0. What C1 changes, in one paragraph

Today the legal-action table is advisory: no step and no route checks it
(data analysis finding 1 [V]). After C1 every mutating step checks the derived
phase first and refuses an illegal action with one refusal (`phase_not_allowed`,
409) that names the phase and the next step. Every driver gets that check: the
HTTP routes, `tooling/generate_report.py`, the notebook and any script. On top of
the guard:
- integration refuses when the validation it would use no longer matches the
  files (the restart trap);
- integration pins nothing;
- re-integration withdraws the data approval;
- Process is legal from INTEGRATED on and refuses before it writes anything.

## 1. The legal-action table after C1

The table stops being a transcription of the old screen's buttons
(`workflow/phases.py:61-138`, `_BUTTON_ACTIONS` / `_PHASE_BUTTON_STATE`). It
becomes one declared table of workflow acts, `LEGAL_ACTIONS`, typed directly.

| Action (wire value) | The act | Today |
|---|---|---|
| `ADD_FILES` | bring files into the study (step 1) | not an action |
| `REMOVE_FILE` | remove one file | not an action |
| `RESET` | clear the study's files and everything derived from them (pool reset) | `RESET`, plus `CLEAR_FILES` at UPLOADED (the same route; two buttons on the old screen) |
| `VALIDATE` | the file check (step 2) | `VALIDATE` |
| `RESOLVE` | choose between conflicting files (step 3) | not an action |
| `CONFIRM_CLASSIFICATION` | correct a file's platform or data type (step 4) | not an action |
| `INTEGRATE` | combine the files into one dataset (step 5) | `INTEGRATE` |
| `STATE_DATASET_FACTS` | state the study design or experiment metadata, which are written onto the dataset (part of step 6) | not an action |
| `APPROVE` | the data approval: the animal accounting (step 8) | `APPROVE` |
| `PROCESS` | Process, content preparation, materialising the result and Summary sections (step 9) | `REPROCESS` |

| phase | legal actions after C1 | today |
|---|---|---|
| EMPTY | ADD_FILES | — |
| UPLOADED | ADD_FILES, REMOVE_FILE, RESET, VALIDATE | CLEAR_FILES, VALIDATE |
| VALIDATION_ERRORS | ADD_FILES, REMOVE_FILE, RESET, VALIDATE, RESOLVE, CONFIRM_CLASSIFICATION | RESET, VALIDATE |
| VALIDATED | ADD_FILES, REMOVE_FILE, RESET, VALIDATE, RESOLVE, CONFIRM_CLASSIFICATION, INTEGRATE | INTEGRATE, RESET |
| INTEGRATED | all ten | APPROVE, REPROCESS, RESET, VALIDATE |
| APPROVED | all ten (same as INTEGRATED) | REPROCESS, RESET |

Why each difference:
- **PROCESS at INTEGRATED and APPROVED.** The approval does not gate Process
  (decision Q3). The two phases differ only in what the data-review screen (M6)
  shows.
- **VALIDATE at VALIDATED, INTEGRATED and APPROVED.** The fix for the restart-trap
  refusal is "validate again", and that refusal fires at VALIDATED. The command
  line's re-run validates every time, including at APPROVED
  (`tooling/generate_report.py:688`; the published-report rebuild passes
  `--reintegrate` for every study, `tooling/build_published_reports.py:214,262`).
  Today's table would refuse those runs; the new one allows them. *Verified on
  scratch with a prototype guard:* VALIDATE at APPROVED, then INTEGRATE at
  APPROVED (approval withdrawn), then APPROVE at INTEGRATED, ending APPROVED. §3.2
  says what a re-validation does to an existing dataset.
- **INTEGRATE at INTEGRATED and APPROVED (re-integration).** Today it is legal
  only at VALIDATED, but the command line's `--reintegrate` and the notebook's
  `REINTEGRATE` do it at APPROVED. It is now legal, it withdraws the approval
  (§3.3), and it costs a cold Process (the caches are wiped,
  `workflow/steps.py:443-454`). The interface confirms it, with the cost named
  (C8 dry run, M3).
- **APPROVE at APPROVED.** The command line re-runs the animal report on every run
  (`generate_report.py:709-710`). Approving again regenerates
  `animal_report.json` from the same files and changes nothing else.
- **RESOLVE and CONFIRM_CLASSIFICATION after validation, integration included.**
  Refusing them after integration would leave no way to change a choice:
  re-validating does not leave INTEGRATED, and they must come before the
  re-integration. A conflict choice made after integration makes the integration
  out of date (§3.2). A classification correction takes effect at the next
  integration (gap noted in §7).
- **STATE_DATASET_FACTS from INTEGRATED on.** These statements write onto
  `integrated.json` (`pipeline/metadata_approval.py:34-57`). Before integration
  there is nothing to write them onto. While validation errors stand, the old
  dataset is not to be built on.
- **`CLEAR_FILES` merged into `RESET`.** One route does both
  (`POST /api/pool/reset`, `web_routes/session_routes.py:1497`).
- **`REPROCESS` renamed `PROCESS`.** It is also the first Process. "REPROCESS"
  tells a person at INTEGRATED they have done it before, which is false. The name
  came from the old screen's button (`phases.py:61-68`; process analysis §9).
  This is decision **D3** (§8): it changes wire values.

`is_legal(phase, action)` (`phases.py:144`) keeps its signature.

## 2. The guard

### 2.1 Where it lives

| Piece | File | What |
|---|---|---|
| `Action`, `LEGAL_ACTIONS`, `NEXT_STEP` | `workflow/phases.py` | the table (§1). `NEXT_STEP[phase]` is the act that moves the phase forward (EMPTY → ADD_FILES, UPLOADED → VALIDATE, VALIDATION_ERRORS → VALIDATE after fixing, VALIDATED → INTEGRATE), as data, so the refusal and the interface's "next step" read one table |
| `PhaseRefusal(StepError)` | `workflow/errors.py` | `code = "phase_not_allowed"`, `status_code = 409`; attributes `action`, `phase`, `legal_actions`, `integration`, `next_action`, `say`, `fix`; the message per `contract.md` |
| `ValidationOutOfDate(StepError)` | `workflow/errors.py` | `code = "validation_out_of_date"`, 409; attributes `missing_ids`, `added`, `missing` |
| `WorkflowEngine.require(action) -> WorkflowState`, and `require_legal(dtxsid, action, store=None)` | `workflow/engine.py` | derives the state (the same `state()` the read model serves) and raises `PhaseRefusal` when `action ∉ state.legal_actions`. Returns the state so the caller does not derive it twice. This is ADR-0014's "every mutating method guards on legality first" (`docs/adr/0014-ui-agnostic-workflow-engine.md:170-172`), never built until now |
| integration basis | `workflow/integration_basis.py` (new, about 80 lines) | §3.2 |

`workflow/` keeps its import rule: it never imports `web_routes`
(`tests/unit/test_workflow_import_isolation.py`). `pipeline` cores import
`require_legal` lazily, as `process_integrated` already imports from `workflow`.

**Order inside a step.** Input checks first, so a malformed call stays a 400
(e.g. `resolve_step` without a file id, `workflow/steps.py:238-241`). Then
`require_legal`. Then everything else. Nothing is read from or written to the
session before the guard, apart from what `state()` reads.

**Cost.** `state()` takes 1.6 ms per call on NIEHS-10 [V]. The basis hash adds
one hash over the validation report, which is about 50 KB [R].

**C5 hook.** Every mutation goes through `require_legal`, so C5's per-session run
lock can refuse "a run is in progress" in that one function.

### 2.2 Every mutating entry point, with its guard

The guard sits in the core function, so every driver (route, command line,
notebook, `tooling/profile_process_run.py`) meets it. Where the logic still lives
in a route or in the command line, the guard call goes there, until the module
that moves the logic into the core (C3, C8) carries it along.

| # | Act | Drivers | Guard call in | Action |
|---|---|---|---|---|
| 1 | bring in files | `POST /api/upload-bm2`, `/api/upload-csv`, `/api/upload-zip` with `?dtxsid=` (`web_routes/upload_routes.py:78,280,396`); CLI `import_files` (`generate_report.py:179`) | the three routes and `import_files` (logic is inline) | ADD_FILES (never refused in C1; it is the C5 hook) |
| 2 | remove one file | `DELETE /api/pool/{id}/files/{name}` (`session_routes.py:1480`) | `pipeline.pool_state.remove_pool_file` (`pipeline/pool_state.py:293`) | REMOVE_FILE |
| 3 | pool reset | `POST /api/pool/reset/{id}` (`session_routes.py:1497`) | the route (logic inline; C8 moves it into the core with its dry run) | RESET |
| 4 | validate | `POST /api/pool/validate/{id}` (`pool_routes.py:213`); CLI `validate` (`generate_report.py:200`); notebook | `workflow.steps.validate_step` (`steps.py:187`) | VALIDATE |
| 5 | resolve a conflict | `POST /api/pool/resolve` (`pool_routes.py:227`) | `resolve_step` (`steps.py:233`) | RESOLVE |
| 6 | confirm classification | `POST /api/pool/confirm-metadata/{id}` (`pool_routes.py:247`); CLI `confirm_metadata` (`generate_report.py:223`) | `confirm_metadata_step` (`steps.py:261`) | CONFIRM_CLASSIFICATION |
| 7 | integrate | `POST /api/pool/integrate/{id}` (`pool_routes.py:262`); CLI `integrate` (`generate_report.py:340`); notebook | `integrate_step` (`steps.py:350`) | INTEGRATE |
| 8 | experiment metadata | `POST /api/experiment-metadata/{id}` (`session_routes.py:1423`); CLI `apply_experiment_metadata` (`generate_report.py:265`) | `pipeline.metadata_approval.approve_experiment_metadata` (`metadata_approval.py:24`) | STATE_DATASET_FACTS |
| 9 | study design | CLI `apply_design` (`generate_report.py:243`); notebook | `generate_report.apply_design` (its logic has no core step yet; C3/M4 create one and carry the guard) | STATE_DATASET_FACTS |
| 10 | approve the data | `POST /api/generate-animal-report/{id}` (`integrated_routes.py:208`); CLI `animal_report` (`generate_report.py:378`) | `generate_animal_report_step` (`steps.py:548`) | APPROVE |
| 11 | Process | `POST /api/process-integrated/{id}` (`integrated_routes.py:176`, calls `run_process` directly at `:201`); CLI `process`/`process_async` (`generate_report.py:386-391`); notebook; `tooling/profile_process_run.py:74` | `pipeline.process_integrated.run_process` (`process_integrated.py:1796`), as its **first line**, before `_build_process_context` | PROCESS |
| 12 | content preparation | `document_step` (`steps.py:603`; no route) | `run_document` (`process_integrated.py:1859`), first line | PROCESS |
| 13 | materialise result sections | `POST /api/pool/materialize-sections/{id}` (`pool_routes.py:286`); CLI `process_async` | `materialize_result_sections` (`steps.py:90`) | PROCESS |
| 14 | materialise the Summary | CLI `summary` (`generate_report.py:412`); notebook | `materialize_summary` (`steps.py:55`) | PROCESS |

**Not phase-guarded, on purpose** (they are not acts of the data phase):
- **session delete** (`POST /api/session/reset`): M1, with the id typed;
- **identity writes**: C3;
- **the method and document-definition pins**: M5, at any time (Q8);
- **front matter, deposit, eFDR, abbreviation**: report details with no data
  dependency;
- **section accept, release, save, restore, discard and approve**: C2 and
  section readiness;
- **the LLM generation routes** (`llm_routes.py`): section readiness, C2, D2;
- **views, structure, styles**: D5;
- **`/api/process-bm2` and `/api/process-genomics`**: they write no session state
  [R].
- **`web_routes/pool_admin.py`**: the maintainer's command-line repair tool. It
  bypasses the guard by design. It only gains `integration_basis.json` in its
  deletion list (`pool_admin.py:60`).

### 2.3 How the drivers handle the refusal

- **Routes.** They already catch `StepError` (`pool_routes.py:71`,
  `integrated_routes.py:202-203,231-232`). The refusal reaches the client as the
  §4.2 error envelope, through the kit's `workflow.refusals.explain`; see
  `contract.md` §3 for the open point on existing routes.
- **Command line.** `generate_report.py:747` already turns a `StepError` into
  `step failed (409): <message>`. C1 adds a second line with the plain-words
  `say` from the kit. No other change: its sequence (validate → confirm →
  integrate → design → pins → approve → process → summary) is legal at every
  stage under the new table. *Verified* with a prototype guard, on a scratch copy
  of an APPROVED study: `--reintegrate --stop-after integrate`.
- **Notebook.** Its cells call `generate_report` functions, so the guard applies
  unchanged. A refusal surfaces as the cell's exception, carrying the message.
  Text to update: `notebooks/_nb_cells_data.py:129-131` (legal actions described
  as the browser's buttons), `:201` (integration listed as writing
  `method_profile.json`), `:776` and `:947` ("Integration already pinned the
  newest one"). Then regenerate with `notebooks/_build_workflow_notebook.py`.

## 3. Behaviour after C1, step by step

### 3.1 Validate (step 2)

`validate_step`: guard (VALIDATE), then unchanged (`steps.py:193-225`).
**Validation never deletes the dataset or the approval.** What a re-validation
means is derived, not done (§3.2):

| re-validation at INTEGRATED or APPROVED finds | derived phase | `integrated.json`, `animal_report.json` |
|---|---|---|
| errors | VALIDATION_ERRORS | kept on disk and **inert**: PROCESS, APPROVE, STATE_DATASET_FACTS and INTEGRATE are refused until the errors are gone |
| no errors, same basis as the integration | INTEGRATED or APPROVED again | as before; nothing lost |
| no errors, a different basis | VALIDATED ("integration out of date") | kept until the re-integration overwrites the dataset and withdraws the approval |

**This is the decision the brief asked for (D4 in §8).** Why not delete the
dataset when validation finds errors: an error can come from the environment, not
the data. *Verified:* the NIEHS-10 copy re-validated without the Java environment
gave 1 `unassigned_file` error on `DTXSID50469320_genomic.bm2` (the `ExportBm2`
classification failed) and derived VALIDATION_ERRORS. Inside `run-server.sh` it
gave 0 errors and derived APPROVED. Deleting the dataset would have thrown away a
3-minute Process and staled approved text over a server misconfiguration.

The method-mismatch warnings that integration adds to the validation report
(`steps.py:530-538`) are dropped by a re-validation, as today (data finding 8).
M5 derives mismatches live.

### 3.2 The integration basis (new, derived)

**The problem.** Integration pairs fingerprints with the validation report's
coverage matrix by file id, and those ids are not stable:
- *verified:* a cold re-scan (what `GET /api/wizard/{id}/fingerprints` does) left
  12 of the 15 coverage-matrix ids of the real NIEHS-10 report absent from the
  fingerprints. This is the restart trap: on the analyst's run, 4 experiments
  instead of 16, with no refusal;
- *verified:* the 12 converted pivots get new ids on every validation.

**The basis.** A hash over the validation report with every id replaced by its
file name:
- per file, its fingerprint minus the volatile fields `file_id`, `ts_added`,
  `ts_filesystem`, `ts_internal` (the same set `pipeline/cache_plumbing.py:402-404`
  drops for the Methods cache key);
- the coverage matrix, ids mapped to file names;
- `precedence.json`, with `chosen_file_id` mapped to its file name and
  `resolved_at` dropped.

*Verified:* two consecutive validations give the same basis. The real session's
report (upload ids) and the scratch copy's cold re-validation (`scan-<name>` ids,
only 3 ids in common) give the same basis, `2a8af1f6b288137f`.

**Where it is recorded.** `integrate_step` writes `integration_basis.json`
`{"basis": …, "integrated_at": …}` after a successful merge. This records an
input, like a cache key; it is not a stored state. It lives in its own small file
because the engine must never load `integrated.json` (60 MB and more,
`engine.py:104-105`).

**How the engine uses it.** `gather_artifacts` reads `precedence.json` and
`integration_basis.json` (both small) and adds `artifacts.integration`:
- `"current"`: the recorded basis equals the basis now;
- `"out_of_date"`: it differs;
- `"unrecorded"`: an `integrated.json` without a basis file (every session on
  disk today);
- `null`: no `integrated.json`.

`state()` calls the pure `derive_phase` with
`hasIntegrated = integrated.json exists and integration != "out_of_date"`. The raw
`hasIntegrated` flag stays as it is in `artifacts`. `derive_phase` and its oracle
are untouched by this.

**Legacy sessions.** "unrecorded" counts as current: no session on disk changes
phase because of C1's basis.

**Not in the basis yet:** a classification correction (CONFIRM). Re-validation
throws corrections away (data finding 4), so making them part of the basis would
make the phase depend on that loss. C3 makes person-stated classifications a
durable file keyed by file name, and that file then joins the basis.

**Reset and invalidation** add `integration_basis.json` to their deletion lists:
`pipeline/pool_state.py:173-175`, `session_routes.py:1559-1562`,
`pool_admin.py:60`.

### 3.3 Integrate (step 5)

`integrate_step` after C1, in order:
1. **Guard** (INTEGRATE: VALIDATED, INTEGRATED, APPROVED). Refused at
   VALIDATION_ERRORS: integration is unreachable while the errors stand.
2. **Unchanged:** the files, fingerprints and coverage-matrix checks
   (`steps.py:360-377`). The 404 and the two 400s are now unreachable from the
   phases they guarded and stay as a fallback.
3. **New: the consistency check** (the restart trap). The fingerprints integrate
   would use are the in-memory ones, or the report's own when the cache is empty
   (`steps.py:365-369`). It refuses `validation_out_of_date` (409) when:
   - any file id in the coverage matrix is not among those fingerprints, or
   - the file names in those fingerprints differ from those in the report's.

   It refuses; it does not repair. *Verified:* the check passes warm and on a cold
   server with nothing re-scanned (the fallback to the report's fingerprints), and
   fails after a cold re-scan (12 ids missing). Classification differences are
   **not** checked (§3.2, C3).
4. `identity.json`: unchanged (C3 owns it).
5. `integrate_pool`: unchanged.
6. **New: withdraw the approval.** Right after a successful merge, before anything
   else, an `animal_report.json` present is moved to
   `history/_data_approval/<stamp>-animal_report.json`. The summary carries
   `approval_withdrawn: true`. A failed merge leaves the approval in place, since
   the dataset did not change.
7. **New:** write `integration_basis.json` (§3.2).
8. Unchanged: re-apply the study design, stamp sidecar units, wipe caches and the
   query substrate.
9. **Changed: pins nothing (Q8).** `_pin_and_check_method` (`steps.py:520-540`)
   reads the pin with `read_pin` and no longer calls `ensure_pin`.
   - When a profile is pinned: the `method_mismatch` warnings against it, as
     today.
   - When none is pinned: no mismatch warnings (the stale ones are removed), and
     `method: {profile: null, pinned_by: null, mode: null, deviations: [],
     mismatches: []}`.

   Comparing against an unpinned "newest" profile would mislead: 8 warnings
   against 2025.1, 0 against NIEHS-10's own 2021 (data finding 8). The function
   keeps its name and signature, so `tests/unit/test_method_profile.py:151`, which
   pins first, is untouched.

### 3.4 Approve the data (step 8)

`generate_animal_report_step`: guard (APPROVE: INTEGRATED, APPROVED), then
unchanged. Refused at VALIDATED, which removes the "approved before integration"
path (data finding 10). It checks nothing else (C6, M6).

### 3.5 Process (step 9) and content preparation

`run_process` and `run_document`: **the guard is the first line**, before
`_build_process_context`. That function pins the method (`:1580`) and the
definition (`:1673`) and rewrites `_fingerprints.json` (`:1652-1658`).

*Verified* on a VALIDATED scratch session:

| | today | with the guard first |
|---|---|---|
| response | `400 "No integrated data found -- run integration first"` | `409 phase_not_allowed` |
| files written | `_fingerprints.json`, `document_definition.json`, `document_definition.yaml`, `method_profile.json` | none |

PROCESS is legal at INTEGRATED and APPROVED (Q3). The phase VALIDATION_ERRORS,
with an inert `integrated.json` on disk, refuses it (process analysis P13). On a
legal run, Process still pins the method and the definition when none is pinned;
that is the open question, D1 (§8). The "not integrated" 400 (`:1709-1711`)
stays as a fallback for a race. `materialize_result_sections` and
`materialize_summary` are guarded with PROCESS too.

### 3.6 Resolve, confirm, dataset facts, file removal, reset

Each is guarded per §2.2 and otherwise unchanged:
- a conflict choice made after integration makes the integration out of date
  (VALIDATED), which is derived;
- a classification correction after integration takes effect at the next
  integration; the response and screen M2 say so (gap until C3).

## 4. Sessions already on disk

Survey of the real `sessions/` (read-only; flags read the way
`gather_artifacts` reads them, phase from the pure `derive_phase`) [V]: 32
sessions.
- 17 are APPROVED.
- 15 are EMPTY: the `_published` companions, the two composed report sessions,
  `DTXSID_TEST`.
- None is in VALIDATION_ERRORS. No section is marked stale. No `genomics_*`
  section file exists.
- `DTXSID5032498` and `DTXSID7037717` were validated after integration.
- `DTXSID_TEST` holds only a default `method_profile.json`.

| state on disk | derives today | after C1 | how it heals |
|---|---|---|---|
| integrated while VALIDATION_ERRORS | VALIDATION_ERRORS [V] | same; the dataset is kept and inert; Process, approval, facts and integration are refused | fix the errors and re-validate: back to INTEGRATED or APPROVED (basis unrecorded = current) |
| approved before integration | VALIDATED [V]; the approval is ignored | same | the integration archives the old approval; the person approves again |
| integrated, never validated | UPLOADED [V] | same | validate: INTEGRATED or APPROVED |
| validated after integration (2 real sessions) | APPROVED | APPROVED (unrecorded) | – |
| an LLM-written `genomics_*` section marked stale, everything else complete | UPLOADED, and still UPLOADED after re-validation [V, in the Java environment] | **a dead end under enforcement**, unless D2 | see below |
| `_published` companion, composed report (no files) | EMPTY | EMPTY; only ADD_FILES is legal; Process refused (today it pinned, then refused) | – |
| a default `method_profile.json` and nothing else | EMPTY | EMPTY; pins untouched | – |

**The stale-section dead end (decision D2).** Phase rule 2 (`phases.py:168`)
sends the phase to UPLOADED while any `bm2_*`/`genomics_*` section is stale.
- *Verified:* approved genomics section → a file change → re-validation still
  derives UPLOADED. With enforcement, integration is then refused until a person
  re-accepts prose about the old data. Re-accepting is the only way out, and it is
  the wrong act.
- Rule 2 is redundant for the case it was made for: every file change already
  deletes `validation_report.json` (`pool_state.py:173-175`), so rule 3 gives
  UPLOADED anyway.
- **Proposal:** drop rule 2. Staleness stays a section matter (currency, the
  publish gate). This edits the characterization contract, decision D2.
- No session on disk is in this state today. Only the section-approve route can
  create a `genomics_*` file (`session_routes.py:913-924`).

## 5. Blast radius

### 5.1 Callers (production) [R]

- **`workflow/steps.py`:**
  - `validate_step`, `resolve_step`, `confirm_metadata_step`, `integrate_step`,
    `_pin_and_check_method`, `generate_animal_report_step`,
    `materialize_result_sections` and `materialize_summary` gain the guard;
  - `integrate_step` gains the check, the withdrawal and the basis.
- **`pipeline/process_integrated.py:1796,1859`:** the guard in `run_process` and
  `run_document`. The file is already 1940 lines (over the 1200 rule); C1 adds
  about 4 lines.
- **`pipeline/pool_state.py`:** `:173-175` (basis file); `:293` (guard).
- **`pipeline/metadata_approval.py:24`:** the guard.
- **`workflow/phases.py`, `engine.py`, `errors.py`;** new
  `workflow/integration_basis.py`.
- **`web_routes/session_routes.py`:** `:1497` (guard in the reset route),
  `:1559` (basis file).
- **`web_routes/upload_routes.py:78,280,396`:** one guard line each.
- **`web_routes/pool_routes.py:71`, `integrated_routes.py:202,231`:** the
  envelope, per `contract.md` §3.
- **`web_routes/pool_admin.py:60`:** the basis file in its deletion list.
- **`tooling/generate_report.py`:** `:243` (guard in `apply_design`), `:747`
  (print the `say`).
- **Documentation:**
  - the notebook text (§2.3);
  - `docs/headless-report-generation.md` (the integration paragraph, about
    `:696`, says integration pins the method);
  - `docs/adr/0014-ui-agnostic-workflow-engine.md:214-222` (the table; an
    amendment);
  - `HANDOFF.md` §4.1 and the `MODULES.md` §4.1 example
    (`"legal_actions": ["REPROCESS", "RESET"]`), both the orchestrator's.
- **Not changed:** `tooling/build_published_reports.py` (it drives
  `generate_report`, whose order is legal), `tooling/profile_process_run.py`
  (guarded in the core).

### 5.2 Tests that pin today's behaviour and must change

**How these were found [V]:** the whole suite (`tests/unit` and
`tests/integration`, minus the runner's 2 known-broken) ran under a scratch
plugin. The plugin wraps every entry point of §2.2 and records each call's
derived phase against the §1 table, refusing nothing.
- Result: 1 failure, the known `test_docx_generator.py::test_yaml_page_breaks_land_as_page_break_before`.
- 34 test functions call an entry point in a phase the new table refuses: 33 at
  EMPTY, 1 at UPLOADED.
- Prototype guards then confirmed which ones fail, and why.

**A. Setup only: the session must be seeded at the right phase (intent unchanged).**

Process tests:
- `tests/integration/test_process_integrated_golden.py:121` `_setup_session`: add
  `files/.keep` and a clean `validation_report.json`. This one change also seeds:
  - `tests/unit/test_process_step.py:69, :89`;
  - `tests/unit/test_document_step.py:54, :71`

  (both import the golden `_setup_session`).
- `tests/integration/test_process_integrated.py:149` `_setup_session` (the same
  seed) serves `:161, :183, :217, :243, :260`.

*Verified:* with both seeds and a prototype guard on `run_process` and
`run_document`, all 13 tests that expect success pass.

Step tests (`tests/unit/test_workflow_steps.py`):
- `FakeStore` (`:29`) lacks `has_files`, `artifact_exists` and
  `has_stale_sections`, which the `PoolStore` protocol already declares
  (`workflow/store.py:64-75`). Add them, with a phase seed like the engine test's
  `FakeStore` (`tests/unit/test_workflow_engine.py:16`).
- Affected: `:112, :139, :148, :174, :203`.
- The materialise tests `:221, :251, :278, :305, :322` use real `sessions_dir`
  sessions and need the INTEGRATED seed.

Other:
- `tests/integration/test_approved_metadata_roundtrip.py:32`: its session has
  `integrated.json` but no files and no report. Seed it.

**B. Refusals whose status and code change (today 400 or 404; after C1, 409
`phase_not_allowed`).**
- `tests/unit/test_workflow_steps.py`:
  - `:105` (validate with no files, 404);
  - `:156` and `:163` (integrate with no fingerprints or no matrix, 400). Assert
    the 409 at UPLOADED, and keep a VALIDATED-with-empty-fingerprints case for
    the 400 that stays reachable.
- `tests/integration/test_pool_integrate.py:104` (400) and `:120` (404)
  [V: these two failed under the prototype; the other 7 integration tests
  passed].
- `tests/integration/test_pool_validate.py:147` (404).
- Process "not integrated" tests (400): `tests/unit/test_process_step.py:103`,
  `tests/unit/test_document_step.py:94`,
  `tests/integration/test_process_integrated.py:278` [V: these three failed].
  Each also gains an assertion that `method_profile.json`,
  `document_definition.json` and `_fingerprints.json` are absent afterwards.
- `tests/unit/test_workflow_steps.py:132` (resolve without inputs) is
  **unchanged**: input checks precede the guard.

**C. The table and the derivation.**
- `tests/unit/test_workflow_legal_actions.py:23-30` (`_EXPECTED`), `:63-66`
  (`REPROCESS`); docstring `:1-9`.
- `tests/unit/test_workflow_engine.py:74-77`: EMPTY's legal actions become
  `{ADD_FILES}`.
- Only if D2 is taken:
  - `tests/unit/test_workflow_engine.py:119`
    (`test_stale_regresses_over_everything`);
  - `tests/fixtures/characterization/workflow_phase_cases.json` and
    `workflow_phase_oracle.json`, the cases
    `stale_regresses_to_uploaded_over_everything` and
    `stale_beats_validation_errors`;
  - the docstring of `tests/unit/test_workflow_phase_characterization.py`.

**D. Integration's pin.** `tests/unit/test_workflow_steps.py:174` gains: no
`method_profile.json` afterwards; with an `animal_report.json` seeded, it is gone
from the session root and found under `history/_data_approval/`.

**Unchanged and verified passing under the prototype:**
- `test_pool_integrate.py:41, :64, :87`;
- `test_stated_design_roundtrip.py:22, :44`;
- `test_approved_metadata_roundtrip.py:55`;
- `test_workflow_state_route.py` (all 4: `integrated.json` written by hand is
  "unrecorded", so it counts as current);
- `test_pool_file_removal.py`;
- `test_value_provenance.py`.

**New tests:**
- `tests/unit/test_workflow_legality.py` (fake store):
  - the table;
  - refusal fields per phase;
  - a parametrised test over the §2.2 inventory, so every entry point refuses out
    of phase. This test keeps the inventory honest.
- The basis:
  - stable across validations with different ids;
  - out of date after a precedence change;
  - "unrecorded" counts as current.
- Integration:
  - refusal on the restart trap;
  - pass on the report-fingerprint fallback;
  - withdrawal and archive of the approval;
  - no pin written.
- An integration test: a guarded route returns the 409 envelope.

### 5.3 The golden oracle

`tests/fixtures/golden/process_integrated_payload.json` is **not touched**. Only
the test's `_setup_session` (`test_process_integrated_golden.py:121`) changes, so
that the session derives INTEGRATED.

*Verified* with a prototype guard in front of `run_process`:

| `_setup_session` | result |
|---|---|
| as today (the session derives EMPTY) | all 4 tests refused |
| seeded with `files/.keep` and a clean report | all 4 pass, the payload byte-identical |
| seeded, plus a person's pin of the newest profile (what D1 options A and B would need) | all 4 pass, the payload byte-identical |

The `.keep` file is not a data file: fingerprinting skips it (`pool_fingerprints.py:399-401`).

## 6. Risks

1. **Validation errors now block for real.** A conflict a person resolved still
   blocks, because validation ignores `precedence.json` (data finding 3; Q10, C3).
   An error caused by the environment blocks too: *verified*, NIEHS-10 without
   the Java environment gave an `unassigned_file` error, and its own advice
   ("Remove it or rename it") is wrong for that cause. No session on disk is
   affected today. Mitigation: M2 explains validation errors in plain words; the
   kit's `server_setup_failed` pattern could extend to validation issues. C3
   settles conflicts.
2. **Wire values change** (D3): `REPROCESS` and `CLEAR_FILES` leave
   `legal_actions`; new actions appear. Anything reading them breaks. I cannot see
   behind the wall whether the old front-end reads `legal_actions`; ADR-0014
   planned that it would (`:228`, `:295`).
3. **The characterization oracle** (D2) was generated from the walled JavaScript
   (`tests/tools/gen_phase_oracle.mjs:27`). It cannot be regenerated. Editing it
   by hand ends "the old screen is the contract" for `derive_phase`.
4. **The basis is a new input to the phase.** A bug there could flip new
   integrations to VALIDATED. Limits on the damage:
   - every legacy session counts as "unrecorded", so none can flip;
   - the stability tests (§5.2);
   - the hash keeps the fields that fingerprinting computes from the data (animal
     counts, doses). A degraded `.bm2` read (the full-LMDB case, data finding 10)
     shows as "integration out of date", which is visible, not silent.
5. **Check-then-act is not atomic.** Two tabs can both pass the guard. C5's lock,
   in the same function, closes this.
6. **The guard reads the state, and today reading the state creates the session
   folder** (`pipeline/session_store.py:84-85`). A refused act on a mistyped id
   still leaves an empty folder until C4.
7. **Re-integration is now a legal act at APPROVED.** It is costly (cold Process)
   and withdraws the approval. The interface must confirm it (M3, C8). The command
   line does it on `--reintegrate` as before.
8. **A classification correction after integration** waits for the next
   integration, and the phase does not ask for one (until C3).

## 7. Order of the changes

Each step leaves the suite green: it updates its tests in the same commit, then
runs `run-tests.sh smart` and `guard`.

1. `workflow/phases.py`: `Action` and `LEGAL_ACTIONS` as a declared table,
   `NEXT_STEP`. `workflow/errors.py`: `PhaseRefusal`, `ValidationOutOfDate`.
   `WorkflowEngine.require` and `require_legal`. Tests: legal actions, engine,
   the new legality test (table and fields).
2. `workflow/integration_basis.py`; `gather_artifacts` gains `integration` and the
   effective `hasIntegrated`. Tests.
3. `integrate_step`: guard, consistency check, withdrawal, basis, no pin. The
   basis file joins the three deletion lists. Step and integrate-route tests.
4. The guard in validate, resolve, confirm and approve. The fake store gains the
   protocol methods.
5. Process: the guard in `run_process`, `run_document` and the two materialise
   functions; the Process test setups seeded. **Run `guard`: the golden fixture
   must not change.**
6. The guard in `remove_pool_file`, `approve_experiment_metadata`, the reset
   route, the upload routes and the command line's `apply_design`. The routes'
   error envelope, once the kit has landed.
7. Rule 2 (only after D2), with the oracle cases.
8. Drivers and documentation: the command line prints the `say`; the notebook
   text and regeneration; the headless guide; the ADR-0014 amendment (the
   orchestrator relays it).
9. `run-tests.sh full`.

C1 does **not** wait on D1. It is built with today's behaviour on a legal Process
(pin when none). D1 then adds one refusal in `run_process`, already written in
`contract.md` as reserved.

## 8. Decisions for the maintainer

- **D1 (already open, MODULES §9): how the method profile is chosen before the
  first Process.** C1 makes integration pin nothing. A refused Process pins
  nothing. A *legal* Process still pins the newest profile, tracking, by
  "default", when none is chosen (`method_profile.py:630-635`). The options:
  - **A. Never defaulted.** Process refuses `method_not_chosen` until a person has
    pinned a profile (`pinned_by: user`).
    - The command line then needs `--method-profile`. The published-report
      rebuild already passes it (`build_published_reports.py:214,262`).
    - The golden setup pins one; verified byte-identical.
    - `DTXSID_TEST` and any old default pin need a person's choice.
  - **B. Pre-selected, confirmed.** The interface proposes a profile and the
    person confirms it. The proposal is the newest of the series, or the profile
    matching the `.bm2`'s recorded settings (ADR-0027 line 98). The core works as
    in A, plus a read that makes the suggestion.
  - **C. As today, made visible.** Process pins the default. P1's pre-flight shows
    "not chosen yet" and asks for an acknowledgement. The command line and the
    notebook keep defaulting, with a log line. This is the only option with a
    silent default outside the browser.
  - **D. A for new studies, existing default pins accepted.**

  The document-definition pin raises the same question in a milder form: the id
  chooses the definition (Q7), and the open part is its mode, track or fixed.
- **D2: drop phase rule 2** ("a stale section sends the phase to UPLOADED")? It is
  needed to avoid the dead end (§4) and redundant for its own case. It means
  editing the characterization case table and oracle by hand, and the JavaScript
  stops being the contract for `derive_phase`.
- **D3: rename `REPROCESS` to `PROCESS`, and merge `CLEAR_FILES` into `RESET`.**
  This changes the wire values in `legal_actions` and the example in the shared
  contract (MODULES §4.1). The alternative is to keep the old names until the old
  front-end is retired; the new interface labels actions in its own words either
  way.
- **D4: a re-validation never deletes the dataset** (§3.1). While errors stand
  the old dataset is kept but inert. A clean re-validation brings it back only
  when the basis is unchanged. This is the designer's decision; please confirm
  it.
- **D5: archive a withdrawn approval** under `history/_data_approval/` (§3.3)
  rather than deleting it. Today invalidation deletes the approval with no trace
  (`pool_state.py:173-175`); C8 may extend the archive to that path too.
