# Gate 0, data preparation (HANDOFF §3 steps 1–8) and the session lifecycle: workflow analysis

Written 2026-10-14 by the workflow analyst for Gate 0. The scope:
- creating a session, listing sessions, opening one, CLEAR_FILES and RESET;
- steps 1–8: bring in files, validate, resolve conflicts, confirm each file's
  platform and data type, integrate, state the facts the data lacks, pin the
  method and the document, approve the data.

Process (step 9) and the document steps (10–13) belong to other analysts. Where
the data steps feed them, this file says so.

**Evidence marks.**
- **[V]** means verified: I ran it against scratch sessions built from
  `sessions/DTXSID50469320` (PFHxSAm, NIEHS-10) and saw the result.
- **[R]** means read from the code only.

The scratch work is in `/workspace/ui-team/_scratch/analyst-data/`. The drivers
are `scripts/walk1.py` … `walk5.py`, and the sessions are `sessions/DTXSID50469320_an*`.
The real `sessions/` was never written.

Citations are `file:line` in this worktree. The `bmdx_pipe` citations are in
`/workspace/bmdx-pipe/src/bmdx_pipe/`.

---

## 0. The findings that matter most

Each one below is a way a careful person ends up with a wrong report, and the
backend gives no refusal and no error.

1. **Legal actions are advisory only.** No step in `workflow/steps.py` checks the
   phase, and neither does any route. I ran several steps in phases where they are
   not legal, and every one went through:
   - integrate at VALIDATION_ERRORS: `integrated.json` is written and the phase
     stays VALIDATION_ERRORS [V];
   - validate at APPROVED [V];
   - the animal report at VALIDATED [V].

   Whatever the interface does not offer, the backend still allows.
2. **A server restart between validate and integrate can silently drop the
   apical data.** [V]
   - Validation gives each converted pivot a fresh random file id
     (`pipeline/pool_fingerprints.py:159`).
   - On a cold server, anything that calls `ensure_fingerprints` re-scans the
     files and gives them different ids (`scan-<name>`, `pool_fingerprints.py:372-377`).
     `GET /api/wizard/{id}/fingerprints` does this.
   - `integrate_step` then pairs those in-memory fingerprints with the validation
     report's coverage matrix, which holds the old ids.
   - Result: every apical platform is skipped with only a log warning ("File not
     found for platform … — skipping"). Integration succeeds with 4 experiments
     instead of 16, and the phase becomes INTEGRATED (session `_anb`).
3. **Conflict resolution (step 3) has no effect on apical platforms.** [V]
   - `integrate_pool` keys a decision by the plain platform ("Body Weight")
     (`pool_integrator.py:1079-1092`).
   - The coverage matrix keys are compound ("Body Weight|tox_study"), so the
     lookup at `:1121` never matches.
   - I chose one body-weight file. Integration still used both (`file_count=2`).

   Two more things go wrong here:
   - `resolve_step` accepts any issue index and any file id, and appends
     duplicate decisions (`workflow/steps.py:233-253`) [V].
   - Validation ignores `precedence.json`, so a resolved error stays an error and
     the phase stays VALIDATION_ERRORS [R]: `validate_pool(dtxsid, fps)` takes no
     precedence (`file_integrator.py:2341`).
4. **Confirming a file's classification (step 4) is unchecked, and it is lost.** [V]
   - Any string is accepted. "Banana"/"Kiwi" were written into the file header,
     and Java then put "Banana" into the experiment's `platform`.
   - The coverage matrix that integration routes by comes from the validation
     *before* the confirmation. So a reclassified file is routed under its old
     platform but labelled with the new one.
   - Re-validating restores the filename-derived classification in the
     fingerprints (`file_integrator.py:1109`, headers skipped at `:1118-1124`).
     The header written into the file stays, so the two now disagree.
   - On a cold server, `confirm_metadata_step` reads the empty in-memory
     fingerprints and rewrites `_fingerprints.json` as `{}`. That emptied a
     15-entry file (`steps.py:270`, `:303-307`).
5. **The HTTP route that approves experiment metadata does damage.** [V]
   (`POST /api/experiment-metadata/{id}` → `pipeline/metadata_approval.py`)
   - It has no vocabulary check: `organ: "Banana"` was accepted.
   - A partial description *replaces* the whole one: species, sex, strain,
     platform and test article became null (`metadata_approval.py:44-45`).
   - Unknown experiment names are ignored without a word.
   - Each approval *replaces* `metadata_approved.json`, so only the last call's
     experiments are re-applied at the next integration (`:67-77`).
   - The command-line path checks the vocabulary and merges
     (`tooling/generate_report.py:265-289`). The two paths disagree.
6. **Front matter: the HTTP save replaces where the command line merges.** [V]
   - Saving `{publication}` alone erased the authors (`web_routes/wizard_routes.py:107-125`;
     compare `generate_report.py:292-305`).
   - Bad shapes are dropped silently: `authors: "J. Smith"` was saved as `[]`.
     `doi: "not-a-doi"` and `report_date: "yesterday"` were saved as given
     (`rendering/front_matter.py:115-141`).
7. **Integration overwrites `identity.json` with whatever the caller passes.** [V]
   An identity without the CASRN and the short name deleted both
   (`steps.py:387-388`). The short name ("abbreviation") is the name the generated
   sentences use.
8. **The method profile is chosen by default, out of sight.** [V]
   - Integration pins the newest profile (`ntp-5day-2025.1`, "pinned_by: default")
     and warns only in the server log (`pipeline/method_profile.py:630-647`).
     NIEHS-10's method is `ntp-5day-2021`.
   - Re-pinning afterwards leaves stale `method_mismatch` warnings in
     `validation_report.json`: 8 warnings name 2025.1, but against the pinned 2021
     there are 0. Mismatches are written only at integration (`steps.py:520-540`).
   - The eFDR records the `go_display` it was computed with
     (`genomics/efdr.py:135`), so a later re-pin leaves it stale. Nothing derives
     that staleness.
9. **The session id decides more than the folder name.** [V]
   - The document definition, the study's method overlay and its deposit
     wording are found by the id (`document_model/document_definition.py:213-221`,
     `method_profile.py:650-658`, `pipeline/deposit.py:175-191`).
   - `DTXSID50469320_ana` was pinned to `eras/niehs-2026`. The real id gets
     `studies/DTXSID50469320/document`.
   - A typo'd or suffixed id silently gets the wrong era. There is no rename.
10. **The data approval (step 8) checks nothing and gates nothing.** It is
    simply the act of writing `animal_report.json`.
    - An approval made before integration survives integration: the session goes
      straight from VALIDATED to APPROVED [V].
    - Process requires only `integrated.json` (`pipeline/process_integrated.py:1707-1711`) [R].
    - The same files gave 301 animals in one session and 122 in a copy of it.
      The copy logged a `bmdx_pipe.bm2_cache` "MDB_MAP_FULL" write failure, so
      the cause is probably the full `/tmp/_bm2_cache` (cause not proven).
      Nothing flagged the difference.
11. **The study-design check accepts contradictions.** [V]
    - Strains are checked against all species at once, so a rat with the mouse
      strain B6C3F1 passes (`pipeline/study_design.py:117`).
    - `articleRoute: inhaled` with `administrationMeans: gavage` and
      `articleVehicle: corn oil` passes.
    - Inferred metadata carries no provenance. A species the LLM inferred cannot
      be told apart from one a person stated (`integrated.json`
      `experimentDescription`) [V].
12. **Uploads don't refuse wrong files.** [V]
    - `/api/upload-csv` accepted a `.pdf` and a `.units.json`.
    - `/api/upload-bm2` accepted a `.txt`, which was then fingerprinted as a
      `.bm2` and blocked validation.
    - A long-format CSV uploaded before its `.units.json` is converted at once,
      without units. The units are lost for good (sidecar `units: None`).
    - A zip holding two files of the same name in different folders keeps only
      the second, but reports both.
    - Without `?dtxsid=` the file goes to a temp directory and is lost, with no
      error.

---

## 1. The derived state these steps live in

`WorkflowEngine(id).state()` → `{phase, legal_actions, artifacts, completeness}`,
served at `GET /api/workflow/{id}/state` (`web_routes/pool_routes.py:81`).

Phase rules, first match wins (`workflow/phases.py:156-188`):

| # | condition | phase |
|---|---|---|
| 1 | `files/` empty or absent | EMPTY |
| 2 | a `bm2_*`/`genomics_*` section is marked `stale` | UPLOADED |
| 3 | no `validation_report.json` | UPLOADED |
| 4 | the report has an error-severity issue | VALIDATION_ERRORS |
| 5 | no `integrated.json` | VALIDATED |
| 6 | no `animal_report.json` | INTEGRATED |
| 7 | otherwise | APPROVED |

Legal actions (`phases.py:76-125`):

| phase | legal actions |
|---|---|
| EMPTY | none |
| UPLOADED | CLEAR_FILES, VALIDATE |
| VALIDATION_ERRORS | RESET, VALIDATE |
| VALIDATED | INTEGRATE, RESET |
| INTEGRATED | APPROVE, REPROCESS, RESET, VALIDATE |
| APPROVED | REPROCESS, RESET |

Facts about this machine that the interface needs:
- **Nothing enforces it.** The engine has no mutators (`workflow/engine.py`). The
  steps and routes never call `is_legal`. Finding 1 lists what I ran in the wrong
  phase [V].
- **Rule 2 looks only at `bm2_*` and `genomics_*`** (`workflow/store.py:149-159`).
  Invalidation also marks stale the singletons written by the LLM: background,
  methods, summary, bmd_summary (`pipeline/pool_state.py:244-276`). A stale
  Summary does not send the phase back [R].
- **A corrupt JSON file counts as missing.** `DiskPoolStore.read_json` returns
  None on a parse error (`store.py:161-168`). A corrupt `validation_report.json`
  derives as UPLOADED, and an empty `animal_report.json` still counts as APPROVED
  (presence check only) [R].
- **Reading the state creates the session directory.** `store.session_dir`
  creates it on every call (`pipeline/session_store.py:75-86`).
  `GET /api/workflow/DTXSID5046932O/state` (letter O for a zero) created an empty
  folder, which returned 200 EMPTY [V]. The listing skips empty folders, so it
  does not show up.
- **`completeness` says apical platforms are incomplete.** For NIEHS-10 it said
  every apical platform is `complete: false, "Requires .bm2 for BMD/BMDL values"`
  (`phases.py:239-243`) [V]. Yet Process computes the apical BMDs itself (ToxicR)
  and the published study builds from exactly these files. Shown as it stands,
  the derived state would alarm a person for no reason (open question Q3).
- **One more action is missing.** There is no action for "change a stated fact"
  or "re-pin". Steps 6 and 7 have no phase. Their state is their files.

---

## 2. Per step

### L. Session lifecycle: create, list, open, CLEAR_FILES, RESET

**What the person does.**
- Starts a study: chooses its id (the DTXSID) and confirms which chemical it is
  (name, CASRN).
- Finds a study already in progress and opens it.
- Throws away the files, or the whole session.

**What they can get wrong, and the consequence.**
- **A typo'd DTXSID.**
  - With a letter for a digit, resolution returns an empty name [V]. The report
    then has no test-article name, unless one is typed in.
  - A plausible but wrong number either fails to resolve or resolves to another
    chemical. That chemical's name then goes through every caption and the title.
  - The id also chooses the document definition, the method overlay and the
    deposit wording (finding 9). A wrong id renders the wrong era.
- **A suffixed id for a second attempt** (`_v2`, `_test`): it silently loses the
  study's own definition, method overlay and deposit wording [V].
- **Opening the wrong session** of two that look alike: for example a study and
  its `_published` companion, or a member study of a report over several
  (`studies.json`). Work then lands in the wrong one.
- **RESET mistaken for CLEAR_FILES, or a session reset mistaken for a pool reset.**
  Both are irreversible (below). A pool reset deletes:
  - the approved Methods, Summary and BMD summary sections, and every `bm2_*`
    and `genomics_*` section;
  - `metadata_approved.json`;
  - everything derived from the data.
- **Resetting the files, then expecting the stated facts to be gone too.** They
  survive (below), and the next upload quietly re-applies the old study design.

**What the backend refuses or derives.**
- Id format: `common.dtxsid.validate_dtxsid` (`common/dtxsid.py:30`, `:44-54`).
  The pattern is `^DTXSID[A-Za-z0-9_-]{1,64}$`. On a mismatch it raises
  `InvalidDtxsid`, a 400 at the route [V]:
  > invalid session id 'dtxsid123': expected 'DTXSID' followed by 1-64 letters, digits, '_' or '-'

  It is case-sensitive. It does not check that the id is a real DTXSID: `DTXSID_MY_STUDY` passes.
- Identity: `POST /api/resolve` (`web_routes/background_server.py:426-454`).
  - It refuses only an empty identifier, with "No identifier provided" (400) [V].
  - Otherwise it always answers 200, with empty fields and `resolution_notes` such
    as "PubChem lookup failed for name 'DTXSID5046932O'" [V].
  - Without `CTX_API_KEY` (unset here) a DTXSID is resolved through PubChem only
    [V, it resolved NIEHS-10 correctly]. The resolver never writes the session.
- **No route creates a session.** A session comes into being when any call
  creates its directory. The upload routes with `?dtxsid=` create it, and so does
  any read (above).
- **Listing.**
  - `GET /api/admin/sessions/summary` (`background_server.py:498-541`) lists
    non-empty, non-underscore folders [V].
  - Its `sections` count is every `*.json` except `meta`. It counted
    `_fingerprints`, `integrated` and `validation_report` as "sections" [V].
  - It carries no phase and no identity.
  - The Bookshelf lists only sessions that hold a generated report
    (`web_routes/bookshelf_routes.py:113-131`).
- **Opening.**
  - `GET /api/session/{id}` (`web_routes/session_routes.py:224`) returns the
    sections.
  - It has a side effect: it registers every file in `files/` in the in-memory
    upload registries under new random ids (`:343-360`). That changes which ids
    `ensure_fingerprints` uses next [R]. This is the mechanism behind finding 2.
- **CLEAR_FILES** (legal only at UPLOADED) has no route of its own. The routes
  that exist:
  - `POST /api/pool/reset/{id}` (`session_routes.py:1496-1631`);
  - per-file `DELETE /api/pool/{id}/files/{filename}` (`:1479-1493`).
- **Pool reset** (RESET):
  - It checks only that the session exists: "No session found for {dtxsid}"
    (404) [V]. It does not check the phase.
  - It deletes `files/`, `_originals/`, `_removed/`, `integrated.json`/`.bm2`,
    `metadata_approved.json`, `validation_report.json`, `precedence.json`,
    `animal_report.json`, `_fingerprints.json`, every cache, `session.duckdb`,
    `preview/`, every `bm2_*`/`genomics_*` section, and the singleton sections
    except `background.json`.
  - It keeps [V]: `identity.json`, `study_design.json`, `front_matter.json`,
    `method_profile.json`, `document_definition.json`/`.yaml`, `deposit.json`,
    `history/`.
  - It uses `rmtree`/`unlink`: **no undo**.
- **Session reset**, `POST /api/session/reset/{id}` (`:1634-1678`):
  - `rmtree` of the whole session, `history/` included. **No undo.**
  - It answers 200 `{"ok": true, "message": "No session to reset"}` when the
    session is absent [V].
- **Removing one file**, `DELETE /api/pool/{id}/files/{name}`
  (`pipeline/pool_state.py:293-362`):
  - It moves the file and its companions to `_removed/<stamp>/` [V].
  - If the pool had progressed, it invalidates.
  - The refusals [V]:
    - "{name} is companion metadata for a data file; remove the data file instead";
    - "No file '{name}' in the pool for {dtxsid}";
    - "Not a pool file name: {filename!r}" [R].
  - **No route restores** from `_removed/`.

**Gaps the interface must cover.**
- *Prevent:*
  - Validate the id format as it is typed, with the same pattern.
  - Distinguish a real DTXSID (`DTXSID` + digits) from a free-form study id, and
    say what a free-form id costs (no lookup, the 2026 definition).
  - Refuse to create a session over an existing one.
- *Check before running:*
  - Resolve the identity and show name, CASRN and structure for the person to
    confirm before anything is written.
  - Show which document definition the id will get. If `templates/studies/<id>/`
    exists, say "this study's own definition"; otherwise "the 2026 definition".
- *Explain:*
  - Say why a session is missing from the Bookshelf (no report yet).
  - Show each session's phase and identity in the list.
- *Confirm or undo:*
  - CLEAR_FILES and RESET need an explicit confirmation that lists what will be
    deleted and what will be kept (the lists above), including approved sections
    and stated facts.
  - A session reset should need the id typed in.
  - Per-file removal is reversible on disk only. The interface needs a restore,
    and that is missing.
- *Never default silently:* the test article's name and CASRN; which session is
  the study and which the companion.

**What the screen reads and calls.**

| need | core | route |
|---|---|---|
| validate id | `common.dtxsid.validate_dtxsid` | (client-side mirror + any route's 400) |
| resolve identity | `narrative.chem_resolver.resolve_chemical` | `POST /api/resolve` (exists) |
| create session (id + confirmed identity → `identity.json`) | none | **missing** |
| list sessions with phase, identity, last change | `WorkflowEngine.state` per folder | **missing** (`/api/admin/sessions/summary` is close but miscounts and has no phase) |
| identity of a session | — | `GET /api/wizard/{id}/identity` (exists); **PUT missing** |
| state | `WorkflowEngine.state` | `GET /api/workflow/{id}/state` (exists; creates the folder) |
| clear files / reset pool | — | `POST /api/pool/reset/{id}` (exists; no phase check, no undo) |
| delete session | — | `POST /api/session/reset/{id}` (exists; no undo) |
| a list of what a reset would delete and keep (dry run) | — | **missing** |

### Step 1. Bring in files

**What the person does.** Gives the study's data files:
- `.bm2` BMDExpress projects;
- long-format NTP `.csv` files with their `.units.json` companions;
- wide `.txt` pivots;
- `.xlsx` workbooks;
- a `.zip` of these.

They decide what belongs to the study.

**What they can get wrong, and the consequence.**
- **A file of another study or another chemical.**
  - Validation catches a roster mismatch only between tox_study files of one sex
    (`roster_subset` / Level 0).
  - Nothing catches a whole platform from another study. Its numbers flow into
    every table of that platform.
- **A file named so that the filename rules misclassify it** (step 4). For
  example, a CSV with no `_truth`/`_tox_study` in its name becomes `inferred`, not
  `tox_study` (`file_integrator.py:77-129`). That changes which tier wins and
  which statistics run.
- **A long-format CSV without its `.units.json`, or uploaded before it.** The
  pivot is made at upload and the units are never recorded [V]. The tables then
  print no units: a missing fact, with no placeholder that names the cause.
- **The wrong kind of file** (PDF, Word, a units file through the CSV route): it
  is stored in `files/`.
  - A `.pdf` or `.json` is skipped by the scan [V].
  - A non-`.bm2` sent through the `.bm2` route is fingerprinted as a `.bm2`, and
    validation then fails with `unassigned_file` [V].
- **Re-uploading a corrected file under the same name** overwrites the old one
  with no confirmation (`upload_routes.py:115-118`) [R].
- **Two same-named files in one zip:** the last one wins, and the response lists
  both [V].
- **Adding a file to a validated, integrated or approved study** invalidates
  validation, integration, the approval and every Process cache except BMDS
  (`pool_state.py:148-278`). It also marks the LLM sections stale [V for the
  phase drop and the list of deletions; session `_anf`].
  - Gone: `validation_report.json`, `integrated.json`, `_category_lookup.json`,
    `genomics.sidecar.json`, `animal_report.json`.
  - Kept: the stated facts and the pins, and also `integrated.bm2` and
    `_fingerprints.json` from the old pool [V].

**What the backend refuses or derives.**
- Uploads: `POST /api/upload-bm2`, `/api/upload-csv`, `/api/upload-zip`, each
  with `?dtxsid=` (`web_routes/upload_routes.py:78`, `:280`, `:396`).
  - Extensions:
    - only the zip route filters them (`.bm2 .csv .txt .xlsx`, `:64`);
      everything else is reported in `skipped` [V];
    - the CSV route takes any extension and the `.bm2` route takes anything [V].
  - Refusal [V]: "The uploaded file is not a valid .zip archive" (400).
  - Each upload fingerprints the file at once. It returns `validation_issues` from
    `lightweight_validate` (a check against the existing pool) and
    `pool_invalidated` when downstream artifacts were deleted [V].
  - Without `?dtxsid=` the file goes to a temp directory and is lost on restart,
    and the response is still 200 [V].
- Command line: `generate_report.import_files` (`tooling/generate_report.py:179-197`).
  - It copies with no fingerprinting, so `.units.json` order does not matter
    there.
  - It invalidates when the pool has progressed.
  - "input file not found: {p}" (SystemExit) [R].
- Derived: the phase becomes UPLOADED [V]. `pool_has_progressed` decides whether
  invalidation runs (`pool_state.py:77-92`).

**Gaps the interface must cover.**
- *Prevent:*
  - Accept only `.bm2 .csv .txt .xlsx .zip` and the companions `.units.json`.
    Refuse `.sidecar.json` (the app writes those).
  - Send each file to the right route by its real type.
  - Never upload without the session id.
- *Check before running:*
  - Pair every long-format `X.csv` with `X.units.json` before sending, and send
    the pair together. The backend should take both in one call and convert after
    (**missing**).
  - Warn about a same-name replacement and about duplicate names inside a zip.
  - Before adding a file to a pool that has progressed, show what will be thrown
    away: validation, integration, approval, caches, stale LLM sections. Ask for
    confirmation.
- *Explain:*
  - Show each file's immediate `validation_issues`.
  - Say what `skipped` means.
- *Confirm or undo:* removal moves files to `_removed/`. Give an undo (restore is
  **missing**).
- *Never default silently:* the units of each measurement. Flag a pivot whose
  sidecar has no `units`.

**What the screen reads and calls.**

| need | route |
|---|---|
| upload | `POST /api/upload-{bm2,csv,zip}?dtxsid=` (exist; see the gaps) |
| one upload route that checks type, pairs companions, reports replacements and invalidation before committing | **missing** |
| list files | `GET /api/wizard/{id}/files` (exists; lists sidecars and stray files too, without saying which are inputs) |
| remove one file | `DELETE /api/pool/{id}/files/{name}` (exists) |
| restore a removed file | **missing** |
| derived state | `GET /api/workflow/{id}/state` |

### Step 2. Validate

**What the person does.**
- Asks the tool what each file is and whether the files agree.
- Reads the issues and the coverage matrix.
- Decides whether the pool is right.

**What they can get wrong, and the consequence.**
- **Reading warnings as noise.** NIEHS-10 itself gives 32 issues: 10 info
  `roster_subset`, 8 warning `missing_tier`, 7 info `missing_tier` and 7 warning
  `unverified_derived_data` [V]. With that many, a real problem passes unseen:
  - a `sex_mismatch` warning;
  - an `animal_count_mismatch` warning ("excluded");
  - a `method_mismatch` (added at integration).
- **Taking "complete: false — Requires .bm2" as a blocker** when it isn't (§1),
  or fixing it by uploading an unrelated `.bm2`.
- **Not noticing that "unverified_derived_data" means no workbook backs the
  values.** The published package's own workbooks were converted, not uploaded,
  so this warning is expected there. A new study with real workbooks should not
  show it.
- **Re-validating after a classification correction.** This throws the
  correction away (finding 4).
- **Re-validating at INTEGRATED** (legal there) leaves `integrated.json` and the
  phase as they were, even when the files changed through some path that skipped
  invalidation [V]. A fresh validation report then sits beside an integration
  built from the old one.

**What the backend refuses or derives.**
- `workflow.steps.validate_step` (`workflow/steps.py:187-225`):
  - `StepError(404)` "No files directory found for this session" (`:195`) [V].
  - It re-fingerprints every file (`ensure_fingerprints(force=True)`), which
    converts long-format CSVs to pivots and moves the originals to `_originals/`
    [V].
  - It runs `validate_pool`, then the value check against the source workbooks
    (`pipeline/value_validation.py`), and writes `validation_report.json`.
- The issue types and their severities. Errors block; the phase is
  VALIDATION_ERRORS.

  | severity | `issue_type` | source | blocks |
  |---|---|---|---|
  | error | `unassigned_file`: "{file} could not be assigned to a recognized platform. Remove it or rename it so the system can identify its purpose." | `file_integrator.py:2388-2399` | yes |
  | error | `dose_mismatch`: "{platform}: dose groups differ between {a} ({type}) and {b} ({type})" (carries `suggested_precedence`) | `:1903-1915`, `:2518` | yes |
  | error | `animal_count_mismatch`: "…txt/csv files have N unique animals but xlsx has only M (k extra)" | `:1970-1985` | yes |
  | error | `value_mismatch`, `value_dose_mismatch`, `value_selection_mismatch`, `value_terminal_mismatch`, `value_missing_in_csv`, `value_missing_in_xlsx`: "{platform}: n of N records in the derived CSV differ from the source NTP xlsx (…). Derived data must trace back to the source study." | `pipeline/value_validation.py:80-135` | yes |
  | warning | `missing_tier`, `animal_count_mismatch` ("excluded"), `sex_mismatch`, `unverified_derived_data`, `method_mismatch` (added at integration) | various | no |
  | info | `roster_subset` (lists the missing animals), `missing_tier`, `redundant_files` | `:2202`, `:2119`, `:2540` | no |
- `files_involved` holds file *ids*. Those ids change on every validation for the
  converted pivots: 12 of 15 changed between two validations [V]. They are not
  stable references.

**Gaps the interface must cover.**
- *Check before running:* refuse VALIDATE outside UPLOADED, VALIDATION_ERRORS and
  INTEGRATED. The backend does not refuse.
- *Explain:*
  - Group the issues: blocking, to look at, expected for a converted package.
  - Say each issue in plain words, with the file *names*, never the ids.
  - Turn `roster_subset` into "these animals are missing from this platform"
    (they feed step 8).
  - Say what `unverified_derived_data` means for trust.
  - Explain the misleading completeness message, or the backend fixes it (Q3).
- *Prevent:* while VALIDATION_ERRORS stands, integration must be unreachable
  (finding 1).
- *Never default silently:* the platform and data type of every file (step 4).

**What the screen reads and calls.**

| need | core | route |
|---|---|---|
| run | `workflow.steps.validate_step` | `POST /api/pool/validate/{id}` (exists; returns the report) |
| read the last report without re-running | `store.read_json(id, "validation_report.json")` | **missing** |
| per-platform readiness | `WorkflowState.completeness` | in `GET /api/workflow/{id}/state` |

### Step 3. Resolve conflicts

**What the person does.** Where two files cover the same thing and disagree, the
person chooses which one counts.

**What they can get wrong, and the consequence.**
- **Choosing the wrong file:** its doses or animals become the study's.
- **Choosing at all, as things stand.** For apical platforms the choice is
  ignored (finding 3) [V]. Both files of the winning tier go into the merge.
- **Expecting a choice to clear an error.** It does not. `dose_mismatch` and
  `animal_count_mismatch` stay errors because validation ignores precedence [R].
  The only way out is to fix or remove a file.
- **Leaving `redundant_files` (info) alone.** Both files are merged [R]
  (`pool_integrator.py:1129-1145` routes all files of the winning tier).

**What the backend refuses or derives.**
- `workflow.steps.resolve_step` (`steps.py:233-253`): `StepError(400)` "dtxsid,
  issue_index, and chosen_file_id are required" (`:239-241`) [V].
- Nothing else is refused. These were all accepted [V]:
  - issue index 999;
  - file id `no-such-file`;
  - a second, contradicting choice for the same issue.
- The route `POST /api/pool/resolve` takes `{dtxsid, issue_index, chosen_file_id}`
  in the body (`pool_routes.py:226-239`). A bad id there gives the
  `InvalidDtxsid` 400 [V].
- `precedence.json` is deleted by invalidation and by a pool reset.
- `issue_index` is not used by integration at all [R]. Only `chosen_file_id`
  counts, and it is a per-validation id.

**Gaps the interface must cover.**
- The backend must be fixed before this step can be offered:
  - key decisions by the compound platform key;
  - reference files by name;
  - one decision per conflict;
  - say whether a decision clears the error (Q1).
- Until then, the interface must not present a choice that has no effect.
- *Prevent:* offer only the files the conflict involves. Allow one decision per
  conflict, replaceable.
- *Explain:*
  - Show both files side by side: doses, animals per dose, endpoints, sex, tier.
    The fingerprints have all of these.
  - Show the backend's `suggested_precedence` and why.
- *Confirm or undo:* a decision must be visible and changeable until integration.

**What the screen reads and calls.**

| need | route |
|---|---|
| the conflicts (issues with `files_involved` ≥ 2) | from the validation report (read route **missing**) |
| record a decision | `POST /api/pool/resolve` (exists; ineffective for apical; unchecked) |
| list or replace or withdraw decisions | **missing** |

### Step 4. Confirm each file's platform and data type

**What the person does.** Checks the tool's guess of each file's platform and
data type, and corrects the ones that are wrong. The data types are `tox_study`
(the study's measured values, gaps included), `inferred` (gap-filled for BMD
modelling) and `gene_expression`.

**What they can get wrong, and the consequence.**
- **Accepting a misclassification:** a wrong file classification flows into
  every table (HANDOFF §2). Two examples:
  - a `tox_study` file taken as `inferred` loses the NTP statistics;
  - a clinical-chemistry file taken as hematology lands in the wrong table.
- **"Correcting" a right one into a wrong one.** I relabelled the male hematology
  file as Hormones [V]. The experiment's platform became "Hormones", while
  integration still routed the file as Hematology.
- **Typing a value outside the vocabulary.** It is accepted and travels into the
  merged project [V].
- **Correcting, then re-validating.** The fingerprints revert to the detected
  values while the file header keeps the correction (finding 4) [V].
- **Correcting a `.xlsx` or a `.bm2`.** No header is written for these, so the
  correction lives only in the in-memory fingerprints and `_fingerprints.json`
  (`steps.py:292-300`) [R]. A server restart or a re-validation loses it.

**What the backend refuses or derives.**
- `workflow.steps.confirm_metadata_step(dtxsid, {file_id: {platform, data_type}})`
  (`steps.py:261-310`):
  - no `StepError`;
  - unknown file ids are skipped silently [V];
  - values are not checked [V];
  - for txt/csv it writes `# Provider: Apical`, `# Platform:` and `# Data Type:`
    headers (`:313-342`). The provider is "Apical" whatever the platform.
- The route is `POST /api/pool/confirm-metadata/{id}` with body `{metadata}`. A
  missing `metadata` answers 200 `{"ok": true, "updated": 0}` [V].
- The confirmation does not change the phase. It writes no record that a person
  confirmed anything (no "confirmed" flag, no who or when).
- The command line keys corrections by file *name* and refuses unknown names:
  "--metadata names an unknown file: {fname!r}" (`generate_report.py:223-240`).
- The vocabularies exist (`bmdx_pipe.VOCABULARIES`, ADR-0019) [V]:
  - `platform`: "Body Weight", "Clinical Chemistry", "Hematology", "Hormones",
    "Organ Weight", "Tissue Concentration", "Clinical", "IVIVE", "Generic", and
    the transcriptomic chip names;
  - `dataType`: "tox_study", "inferred", "gene_expression".

  Fingerprints use `platform: None` with `data_type: "gene_expression"` for the
  genomic `.bm2` [V], which is not a vocabulary value.

**Gaps the interface must cover.**
- *Prevent:*
  - Offer selects bound to `VOCABULARIES.platform` and `VOCABULARIES.dataType`.
  - Never take free text.
  - Key each correction by file name.
- *Check before running:*
  - A correction changes the coverage matrix, so validation must re-run on the
    corrected classification before integration.
  - The backend must keep person-stated classifications in a file keyed by file
    name, which fingerprinting honours (**missing core logic**). Today the order
    validate → confirm → integrate is the only one that partly works, and only
    within one server process.
- *Explain:*
  - Say why the tool guessed what it guessed: from the file name, by rule
    (`detect_platform_and_type`), or from the `.bm2`'s experiment names.
  - Say what each data type means for the report.
- *Confirm or undo:* show the detected value beside the stated one, and allow a
  return to the detected value.
- *Never default silently:* each file's platform and data type. The detected
  values must be confirmed, not just passed through.

**What the screen reads and calls.**

| need | route |
|---|---|
| the classification table | `GET /api/wizard/{id}/fingerprints` (exists). On a cold server it re-scans files and mints new ids (finding 2); its ids do not match the validation report's. |
| apply corrections | `POST /api/pool/confirm-metadata/{id}` (exists; unchecked, not durable) |
| vocabularies | in `GET /api/experiment-metadata/{id}` (needs integration); a route for the vocabularies alone is **missing** |

### Step 5. Integrate

**What the person does.** Asks for the merge into one dataset, then looks at what
came out:
- the source chosen per platform;
- the experiments and their metadata;
- the method mismatches.

**What they can get wrong, and the consequence.**
- **Integrating while validation errors stand.** It works, and the phase hides it
  (finding 1) [V].
- **Integrating after a server restart, or after opening the session elsewhere.**
  Apical data is dropped silently (finding 2) [V].
- **Integrating with no identity or a wrong one.**
  - The test article feeds the LLM's metadata inference and is written into every
    experiment's `testArticle` [V].
  - An identity passed in the body replaces `identity.json`, deleting the CASRN
    and the short name (finding 7) [V].
- **Re-integrating casually.**
  - It deletes every Process cache, `session.duckdb` and `session_parquet/`
    (`steps.py:443-454`), so the next Process is cold (minutes).
  - It re-infers every experiment's metadata. Only the stated design and the
    *last* approval come back (finding 5).
  - It keeps `animal_report.json`, so an earlier approval rides over a changed
    dataset [V, session `_and`].
- **Trusting the inferred metadata.**
  - The LLM fills species, organ and sex from experiment names.
  - It left strain, route, vehicle and duration null for NIEHS-10 [V].
  - An organ it proposed outside the vocabulary was logged as "dropping to null",
    yet "heart, kidney, liver" was still on the organ-weight experiments [V].
  - Without the gateway the descriptions are left empty with only a log line
    (`_nb_cells_data.py` §8) [R].
- **Missing the method-profile pin** made at this moment (finding 8).

**What the backend refuses or derives.**
- `workflow.steps.integrate_step(dtxsid, identity, store)` (`steps.py:350-491`),
  all [V]:
  - `StepError(404)` "No files directory found for this session" (`:362`);
  - `StepError(400)` "No fingerprints found -- run validation first" (`:371`),
    seen at UPLOADED;
  - `StepError(400)` "No coverage matrix found -- run validation first" (`:377`),
    seen after an invalidation;
  - `StepError(500)` f"Integration failed: {e}" (`:426`). Usually the
    environment: JDK 21, `BMDX_PROJECT_ROOT`.
- There is no check of the phase, the validation errors, or whether the file ids
  match.
- After the merge:
  - `reapply_study_design` (`:434`, `:494-517`);
  - `stamp_sidecar_units`;
  - cache wipe;
  - `_pin_and_check_method` (`:463`, `:520-540`): it pins the newest profile if
    none is pinned, and writes the `method_mismatch` warnings into the validation
    report.
- It returns a summary: `_meta.source_files` (chosen file per platform, tier,
  count), `experiment_count`, `bmd_result_count`, `method {profile, pinned_by,
  mode, deviations, mismatches}`, and the experiments [V].
- The route is `POST /api/pool/integrate/{id}`, body `{identity?}`
  (`pool_routes.py:261-282`). It runs in a thread, about 15–20 s here [V].
- The phase becomes INTEGRATED. Legal: APPROVE, REPROCESS, RESET, VALIDATE [V].

**Gaps the interface must cover.**
- *Prevent:*
  - Offer integrate only at VALIDATED.
  - Never send a partial identity. Better: the backend stops taking an identity in
    this call, since identity has its own step.
- *Check before running:*
  - The backend should refuse when the fingerprints don't match the coverage
    matrix (**missing**). Until it does, the interface must re-validate
    immediately before integrating.
  - Say that re-integration throws away Process results.
- *Explain:*
  - Show the source chosen per platform, and how many files per platform. Use
    file names.
  - Show every experiment with its metadata. Mark which fields are stated (from
    `study_design.json` / `metadata_approved.json`) and which are inferred.
    Today that has to be derived by comparing those files. No per-field
    provenance is stored (**missing**).
  - Show the method profile that was pinned, by whom, and the mismatches and
    deviations.
  - Name the failure in plain words when Java is missing.
- *Confirm or undo:* re-integration needs a confirmation naming the cost (a cold
  Process).
- *Never default silently:* organ, sex, species and test article per experiment;
  the method profile.

**What the screen reads and calls.**

| need | route |
|---|---|
| run | `POST /api/pool/integrate/{id}` (exists) |
| summary afterwards, without re-running | `GET /api/integrated-summary/{id}` (exists) |
| experiments + metadata + vocabularies | `GET /api/experiment-metadata/{id}` (exists) |
| stated-vs-inferred per field | **missing** |

### Step 6. State the facts the data lacks

Six kinds of statement, kept in session files and re-applied at every
integration where it applies.

**What the person does.**
- **Study design** (`study_design.json`):
  - species, strain, route (`articleRoute`), means (`administrationMeans`),
    vehicle, duration;
  - each from a controlled vocabulary;
  - applied to *every* experiment.
- **Experiment metadata** (`metadata_approved.json`): per experiment, organ, sex
  and so on, where the name doesn't say ("EDHP mg_kg").
- **Front matter** (`front_matter.json`):
  - authors, contributors, collaborators;
  - publication (report number, DOI, date);
  - the title's strain designation ("(Hsd:Sprague Dawley® SD®)").
- **The short name** (`identity.json` `abbreviation`), used by every sentence
  written from the tables.
- **The deposit** (`deposit.json`): the files deposited with the report, for the
  Supplemental Data appendix.
- **The eFDR** (`efdr.json`): from the synthetic-null analyses in the deposit
  (2026 studies).

**What they can get wrong, and the consequence.**
- **Not stating the design.**
  - Process falls back to the standard design for every missing fact (SD rats,
    gavage, corn oil, 5 days; inhalation for ppm), and the report prints it.
  - The fallback is "logged", but only in the server log and in Process's methods
    context (`generate_report.py:398-402`). A person sees nothing unless the
    interface shows it.
  - `study_design_facts` / `missing_design_facts` (`study_design.py:144-221`) can
    say in advance which facts would fall back. No route serves them
    (**missing**).
- **Stating an inconsistent design** (finding 11): the title, Methods and
  captions then contradict each other or the study.
- **Approving one experiment's metadata through HTTP:**
  - it wipes the other fields of that description;
  - it forgets earlier approvals (finding 5);
  - the next integration re-applies only the last set.
- **Saving the front matter in parts:** the earlier part is lost (finding 6).
- **A malformed DOI or date:** saved as given, printed in the publication details
  [V].
- **The strain designation:** free text that can contradict the stated strain.
  Nothing checks it.
- **Losing the short name:** a later integration call with an identity deletes
  it (finding 7). The sentences then use the long name.
- **The deposit:**
  - `record_deposit` reads a *server-side folder*. A person in a browser has no
    way to name one [R].
  - With no deposit recorded, the appendix lists `sessions/<id>/supplemental/`
    and links to `http://127.0.0.1:9000/…` (`deposit.py:226-261`): a local
    address that would print in the report.
  - File kinds are read from file names, with a per-study override only in
    `templates/studies/<id>/deposit.yaml`.
- **The eFDR:**
  - It is computed with the method profile's `go_display` *at that moment*. A
    re-pin afterwards leaves it stale (finding 8).
  - A missing or wrong zip raises a bare `FileNotFoundError` [V].
- **Stating facts before integration:** the design is refused [V]. The
  experiment-metadata path gives a misleading message (below).

**What the backend refuses or derives.**
- `generate_report.apply_design` (`generate_report.py:243-262`) [V for each]:
  - "--design needs an integrated session";
  - "--design: unsupported field 'route'; use ['species', 'strain',
    'articleRoute', 'administrationMeans', 'articleVehicle', 'studyDuration']";
  - "--design: strain='Sprague Dawley' is not in the vocabulary ['Sprague-Dawley',
    'Wistar', …, 'B6D2F1']". The strain list mixes rat and mouse strains, and the
    pair is never checked against the species.
  - It writes `{fields, recorded_at}` and re-applies to every experiment, and
    re-exports `integrated.bm2`.
- `generate_report.apply_experiment_metadata` (`:265-289`) [V]:
  - "--experiment-metadata: unknown experiment 'Liver_Male'";
  - "--experiment-metadata: Liver_PFHxSAm_Male: organ='Liver' is not in the
    vocabulary";
  - on a session not yet integrated: "unknown experiment 'x'". A wrong reason: the
    real one is "not integrated".
  - Passing a list instead of a mapping crashes with `TypeError` instead of giving
    its own message.
- `POST /api/experiment-metadata/{id}` (`session_routes.py:1422-1476`):
  - "No metadata provided" (400);
  - "No integrated data found" (404, from `LookupError`);
  - otherwise accepts anything (finding 5) [V].
  - Note: `GET` returns `approved: true` once any approval exists.
- Front matter: `POST /api/document/{id}/front-matter`
  (`wizard_routes.py:107-125`) refuses only "invalid JSON body" and
  "front_matter object required" (400). It replaces the whole file.
- Short name: `generate_report.record_abbreviation` (`:330-337`). No route.
- Deposit: `pipeline.deposit.record_deposit(dtxsid, directory, exclude)`
  (`deposit.py:201-213`):
  - a nonexistent folder raises `FileNotFoundError` [V];
  - `deposit.yaml` errors are `ValueError`s with plain messages (`:175-191`).

  No route. `GET /api/sessions/{id}/supplemental/` serves the local folder
  (`supplemental_routes.py:34-49`).
- eFDR: `genomics.efdr.record_efdr(dtxsid, zips)` (`efdr.py:138-148`).
  - It needs Java.
  - "{name}: not a '<Species> <Tissue> … Synthetic Null Analysis' file"
    (`ValueError`, `:77`).
  - With no zips it writes `{"tissues": [], …}` [V].
  - No route.
- Survival:
  - Invalidation keeps every statement [V].
  - A pool reset keeps all except `metadata_approved.json` [V].
  - A session reset removes everything.

**Gaps the interface must cover.**
- *Prevent:*
  - Bind every design field to its vocabulary.
  - Make the strain depend on the species: the vocabulary already holds strains
    per species.
  - Make the route depend on the dose unit and the means: inhalation → no
    vehicle; gavage → oral.
  - Send experiment metadata merged into the full description, never a part
    (until the route merges).
  - Save the front matter as a whole form, never in parts.
  - Validate the DOI pattern (`10.…`) and the date (a year and month).
- *Check before running:* before the approval (step 8) and before Process, show
  every design fact as one of:
  - **stated** (`study_design.json`);
  - **recorded** (the data);
  - **standard design (fallback)**;
  - **in conflict**.

  The facts come from `study_design.study_design_facts` (`fallback` and
  `conflicts` lists). A route for this is **missing**.
- *Explain:*
  - Say that a stated design overrides the data for every experiment, and why.
  - Say that `metadata_approved.json` and `study_design.json` are re-applied at
    every integration.
- *Confirm or undo:*
  - Statements are overwritten in place with no history. Keep the previous value,
    or confirm before replacing a stated design (no history exists today, unlike
    the pins).
- *Never default silently:*
  - species, strain, route, vehicle, duration;
  - sex and organ per experiment;
  - the strain designation;
  - authors and publication details;
  - the short name;
  - the deposit's address (local vs DOI);
  - the eFDR (absent → the appendix needs a "[… pending]").
- *Placement:* the **dose unit**, a fact the data often lacks, has no home in
  steps 1–8. All NIEHS-10 fingerprints have `dose_unit: None` [V]. The unit is a
  Process parameter, resolved stated > recorded > "mg/kg" (`study_design.py:96-105`).
  The process analyst should pick this up. See Q5.

**What the screen reads and calls.**

| need | core | route |
|---|---|---|
| design: read / state | `pipeline.study_design`, `generate_report.apply_design` | **missing** (GET and POST) |
| which facts are stated / recorded / fallback / conflicting | `study_design.study_design_facts`, `missing_design_facts` | **missing** |
| vocabularies | `bmdx_pipe.VOCABULARIES` | inside `GET /api/experiment-metadata/{id}`; standalone **missing** |
| experiment metadata | `pipeline.metadata_approval.approve_experiment_metadata` | `GET`/`POST /api/experiment-metadata/{id}` (exist; POST needs vocab check, merge, approval merge) |
| front matter | `rendering.front_matter.clean_front_matter` | `GET`/`POST /api/document/{id}/front-matter` (exist; POST replaces) |
| short name | `generate_report.record_abbreviation` | **missing** |
| deposit: upload into `supplemental/`, record, list | `pipeline.deposit.record_deposit`, `load_deposit` | listing exists (`/api/sessions/{id}/supplemental/`); upload + record **missing** |
| eFDR | `genomics.efdr.record_efdr` | **missing** |

### Step 7. Pin the method and the document

**What the person does.**
- Chooses the analysis method the study is reported under: a method profile, in
  one of two modes:
  - *fixed*: stay on it;
  - *track*: follow the newest of its series.
- Chooses whether the document definition is *tracked* (follows the templates) or
  *fixed* (a snapshot).

**What they can get wrong, and the consequence.**
- **Leaving the default profile.** Integration pinned `ntp-5day-2025.1` (track)
  on NIEHS-10 [V]; the published method is `ntp-5day-2021`. Every statistical
  test, the BMD settings, the GO cutoffs and the Methods text follow the profile.
- **Not seeing the deviations.** NIEHS-10's profile asks for two things this tool
  can't do here [V]:
  - `apical.bmd.engine: bmds_2_7_high_dose_drop`;
  - `apical.bmd.eligibility: all_endpoints`.

  Substitutes are used instead. Per HANDOFF §2, deviations are errors sized
  plainly.
- **Not seeing the mismatches** between what the `.bm2` records and the profile
  (8 against 2025.1 for NIEHS-10, 0 against 2021) [V]. Two traps:
  - the validation report keeps the old ones after a re-pin [V];
  - re-pinning changes the Process cache keys, so everything recomputes.
- **Fixing the definition too early.** The report then ignores template fixes
  until re-pinned. Or *tracking* a finished report, which then changes when the
  templates change.
- **The wrong definition through the session id** (finding 9). There is no way to
  pick an era by hand. A study gets its own definition if one exists, else the
  2026 one [R] (`document_definition.py:208-221`).
- **Re-pinning after the eFDR was recorded** (finding 8).

**What the backend refuses or derives.**
- `pipeline.method_profile` [V for each]:
  - `MethodProfileError` "no method profile 'ntp-5day-2099' in …/profiles"
    (`:337`);
  - `MethodProfileError` "bad profile name '../x'" (`:325`);
  - `MethodProfileError` "{id}: method profile {name!r} changed since it was
    pinned (hash … → …); profiles are immutable — write a new profile and re-pin"
    (`:670-673`) [R].
  - `pin_profile(id, name)` fixes; `pin_profile(id, "newest")` tracks;
    `ensure_pin` pins the newest when none is pinned. It writes even on an EMPTY
    session [V].
  - The previous pin goes to `history/_method_profile/` (`:587-610`).
  - `list_profiles()` → `[{name, series, effective, reference, hash}]` [V]:
    `ntp-5day-2021`, `ntp-5day-2025`, `ntp-5day-2025.1`.
  - `session_method(id)` gives the resolved settings, each with the layer that set
    it, plus `deviations`.
  - `recorded_mismatches(integrated, method)` lists the mismatches.
- `document_model.definition_pin`:
  - `DefinitionPinError` "mode must be one of ('track', 'fixed'), got 'frozen'"
    (`:120-121`) [V];
  - "{id}: no pinned document definition" and "{id}: document_definition.yaml no
    longer matches its pin (hash … → …); pinned definitions are immutable —
    re-pin instead" (`:86-92`) [R];
  - `ensure_pin` tracks by default [V]. `drift(id)` says when a fixed pin's
    templates have moved on (`:151-162`).
- No route exists for either pin.

**Gaps the interface must cover.**
- *Prevent:*
  - Offer only the listed profiles.
  - Make the mode an explicit choice.
- *Check before running:* show, before approval and before Process:
  - the pin and who set it (`pinned_by: default` must read as "not chosen yet");
  - the deviations, as errors;
  - the *current* mismatches. Compute them live, not from the validation report.
- *Explain:*
  - Say what each profile is (series, effective date, reference).
  - Say what changes between them. The resolved settings with their sources are
    there: 49 settings for NIEHS-10 in the notebook.
  - Say what "track" and "fixed" mean.
  - Say which definition the session renders from, and why (its own, or the 2026
    default).
- *Confirm or undo:*
  - A re-pin must be confirmed, naming the cost: a recompute, a stale eFDR, and
    LLM sections regenerated on the next Process.
  - The history exists, so a "return to the previous pin" is feasible.
- *Never default silently:* the method profile; the definition (era) and its
  mode.

**What the screen reads and calls.**

| need | core | route |
|---|---|---|
| profiles | `method_profile.list_profiles` | **missing** |
| pin, settings + sources, deviations, mismatches | `read_pin`, `session_method`, `recorded_mismatches` | **missing** |
| pin / track | `pin_profile`, `track_newest` | **missing** |
| definition pin + drift | `definition_pin.read_pin`, `drift`, `current_definition_name` | **missing** |
| pin definition | `definition_pin.pin_definition` | **missing** |

### Step 8. Approve the data

**What the person does.** Accounts for every animal:
- dose, sex and cohort;
- which files and tiers it appears in;
- who drops out between files, and why.

Then declares the data ready for Process.

**What they can get wrong, and the consequence.**
- **Approving without reading.** The act *is* the generation of the report
  [R, `steps.py:548-571`]. Nothing asks for a review, and nothing records who
  approved.
- **Approving at the wrong moment.** Before integration, the approval carries
  over into APPROVED [V].
- **A wrong count passed as approved.** The same data gave 301 animals in one
  session and 122 in a copy that logged an LMDB write failure [V]. The
  biosampling count is always 0, a known gap: G9 in the manual, `_nb_cells_data.py`
  §11 [V].

  NIEHS-10's 301 is 122 animals plus 179 gene-expression samples, which are
  counted as animals of their own [R, notebook].
- **Leaving facts open.** Approving with:
  - unstated design facts (fallback);
  - a default method pin;
  - unresolved warnings.

  Process then runs on all of them.
- **Expecting the approval to protect the data.** It doesn't:
  - Process does not require it [R];
  - re-integration keeps it [V];
  - only an invalidation deletes it.

**What the backend refuses or derives.**
- `workflow.steps.generate_animal_report_step` (`steps.py:548-571`):
  - `StepError(404)` "No files directory found for this session" (`:557`);
  - `StepError(400)` "No fingerprinted files found -- upload files first"
    (`:561`) [R; at EMPTY the 404 fires first, V];
  - `StepError(500)` f"Animal report generation failed: {e}" (`:567`).
- There is no check of the phase, of integration or of validation errors.
- The route is `POST /api/generate-animal-report/{id}` (`integrated_routes.py:207-238`).
- The phase becomes APPROVED. Legal: REPROCESS, RESET [V].
- `animal_report.json` holds:
  - `study_number`;
  - `total_animals`, `core_count`, `biosampling_count`;
  - `dose_groups`, `dose_design` (dose × sex);
  - `domain_coverage` (platform × tier);
  - `attrition` (per platform, with the classified reasons);
  - `completeness`;
  - `consistency_issues` (0 for NIEHS-10) [V].

  `animals` is the roster itself.

**Gaps the interface must cover.**
- *Prevent:*
  - Offer approval only at INTEGRATED.
  - The backend should refuse elsewhere, and integration should drop a prior
    approval (**missing**).
- *Check before running:* the approval should be a checklist that cannot be
  passed while:
  - validation errors stand;
  - a classification is unconfirmed;
  - a design fact is on fallback and not acknowledged;
  - the method pin is a default;
  - deviations are unacknowledged;
  - the animal counts differ from what validation saw (the `roster_subset` lists);
  - units are missing from a sidecar.

  Each of these is derivable from files on disk. None is derived today
  (**missing**: a readiness derivation in `workflow/`, served as a route).
- *Explain:*
  - Show the study design as a dose × sex table.
  - Show who is missing from each platform, and the classified reason.
  - Explain the 301/122 kind of difference: plate wells vs animals.
  - Say that biosampling is not counted yet.
- *Confirm or undo:*
  - Approval is reversible only by an invalidation.
  - An explicit "withdraw approval" (delete `animal_report.json`) is **missing**.
- *Never default silently:* group sizes per dose and sex (HANDOFF §2 names group
  sizes); the cohort of each animal.

**What the screen reads and calls.**

| need | route |
|---|---|
| generate (= approve) | `POST /api/generate-animal-report/{id}` (exists) |
| read the existing report | **missing** (only re-generation) |
| readiness checklist | **missing** |
| withdraw approval | **missing** |

---

## 3. Shared-kit needs (from these steps)

### 3.1 The refusal explainer

It must map the following to plain words. The status alone is not enough: the
same 400 means "validate first" in one place and "bad id" in another.

- **`StepError` from `workflow/steps.py`** (status, message verbatim):
  - 404 "No files directory found for this session" (`:195`, `:362`, `:557`): "This study has no files yet."
  - 400 "dtxsid, issue_index, and chosen_file_id are required" (`:239-241`)
  - 400 "No fingerprints found -- run validation first" (`:371`)
  - 400 "No coverage matrix found -- run validation first" (`:377`)
  - 500 "Integration failed: {e}" (`:426`): the explainer needs to tell the
    environment (Java, `BMDX_PROJECT_ROOT`) apart from the data.
  - 400 "No fingerprinted files found -- upload files first" (`:561`)
  - 500 "Animal report generation failed: {e}" (`:567`)
- **`InvalidDtxsid`** → 400 `{"error": "invalid session id …: expected 'DTXSID' followed by 1-64 letters, digits, '_' or '-'"}`.
- **Route errors** `{"error": …}`:
  - "No identifier provided" (400);
  - "No session found for {dtxsid}" (404);
  - "No integrated data found" (404);
  - "No metadata provided" (400);
  - "The uploaded file is not a valid .zip archive" (400);
  - "invalid JSON body" / "front_matter object required" (400);
  - the `PoolFileError` texts (400);
  - `UnreadableSessionFile` and `BMDProjectValidationError` (422; a corrupt
    session file or a schema-violating dataset, mapped globally in
    `background_server.py`).
- **Python exceptions with no route yet**, which the new routes must turn into
  messages:
  - `MethodProfileError` (three texts);
  - `DefinitionPinError` (three texts);
  - the design and experiment-metadata vocabulary errors (today `SystemExit`
    strings in `generate_report.py`; the core function `design_field_errors`
    returns the list);
  - the `deposit.yaml` `ValueError`s;
  - the eFDR `ValueError`;
  - `FileNotFoundError`.
- **Validation issues are not refusals, but they need the same treatment.** The
  12 issue types (§2, step 2) each need a plain-words explanation and a "what to
  do". The blocking ones are the 3 structural errors plus the 6 `value_*`. Their
  `files_involved` are ids that must be shown as file names.
- **Phase refusals the backend doesn't make.** The explainer must also produce
  its own "not available now, because …", from the phase, for every action
  outside `legal_actions`.

### 3.2 Confirm-or-undo

What each destructive or costly act deletes, and whether it can be undone:

| act | deletes | undo in backend |
|---|---|---|
| upload into a pool that has progressed | validation, precedence, integration, `_category_lookup`, genomics sidecar, approval, caches except BMDS, `session.duckdb`; marks LLM sections stale | none |
| same-name re-upload | the previous file | none |
| remove one file | moves to `_removed/<stamp>/`; invalidates as above | on disk only; **no restore route** |
| re-validate | nothing; replaces the report and forgets classification corrections | none |
| re-integrate | every cache, `session.duckdb`, `session_parquet/`; re-infers the metadata | none |
| state design / approve metadata / save front matter | the previous statement (overwritten) | none |
| re-pin method / definition | nothing (old pin kept in `history/`); recomputes on next Process | history exists; **no restore route** |
| CLEAR_FILES / pool reset | §2 L | none |
| session reset | everything | none |

The pattern needs two variants:
- **confirm-with-consequences:** the list of what goes;
- **type-to-confirm:** for a session reset.

The backend should offer a *dry run* that returns the list (**missing**). The
alternative is the interface hard-coding these lists, which would break the
"derived, never hard-coded" rule.

### 3.3 Vocabulary-bound fields

- **The source.** `bmdx_pipe.VOCABULARIES` (ADR-0019) [V] has these keys: sex,
  organ (about 40), species, strain (*a mapping species → strains*), platform,
  provider, subjectType, articleRoute, articleVehicle, administrationMeans,
  studyDuration, articleType, dataType.
- **Dependent fields:**
  - strain ← species;
  - articleVehicle and administrationMeans ← articleRoute (and the dose unit);
  - the file `platform` ← `dataType` (gene_expression has no apical platform).
- **Not in the vocabulary, and must be handled:**
  - `platform: None` for a genomic `.bm2`;
  - the organ "Whole Body" the integration writes [V];
  - multi-organ values ("heart, kidney, liver") [V].
- **Id formats:**
  - the session id `^DTXSID[A-Za-z0-9_-]{1,64}$`;
  - a real DTXSID `^DTXSID\d+$` (a stricter, advisory check);
  - CASRN, `\d{2,7}-\d\d-\d`;
  - DOI, `10.` prefix (as `deposit.py:186-187` checks);
  - the report date (`report_date` free text today; Q6).
- **The vocabulary is served only after integration**, inside
  `GET /api/experiment-metadata/{id}`. A standalone route is needed for steps 4
  and 6 (**missing**).

### 3.4 The "[… pending]" placeholder, in these steps

- A design fact on fallback: "standard design".
- A missing unit.
- A missing test-article name, CASRN or short name.
- Unconfirmed classification.
- No deposit: "will be listed from the local folder", with the address.
- No eFDR for a 2026 study.
- No authors or publication details.
- Biosampling not counted.

### 3.5 The derived-state hook

It must carry, beyond `WorkflowEngine.state()`:
- the last validation report: issues grouped, coverage, ids → names;
- the classification table (one source, with stable ids);
- the design facts with stated / recorded / fallback / conflict;
- the method pin, deviations and *live* mismatches;
- the definition pin and drift;
- the identity;
- the readiness checklist for approval.

All of these are derived from disk (CONTEXT.md invariant 3). None should be
cached in the browser.

It must never call a route that creates the session folder or mints file ids as
a side effect:
- `GET /api/workflow/{id}/state` creates the folder;
- `GET /api/wizard/{id}/fingerprints` re-scans on a cold server;
- `GET /api/session/{id}` registers uploads.

Until the backend fixes them, the hook must avoid them or tolerate them.

---

## 4. Proposed module cut

The cut follows **what a person decides, and when**:
- *which study*;
- *which files, and what each one is*;
- *what the data can't say*;
- *which method and which document*;
- *is the data right*.

Each module below is one of these decisions. It can be built against mocks of the
routes it lists.

| # | module | steps | the person decides | depends on | routes it needs (existing / **missing**) |
|---|---|---|---|---|---|
| M1 | **Study sessions** | lifecycle: create, list, open, delete | which study, which chemical, under which id; what to throw away | shared kit | `POST /api/resolve`; `GET /api/wizard/{id}/identity`; `POST /api/session/reset/{id}`; **`POST /api/sessions` (create, with identity)**, **`GET /api/sessions` (list with phase + identity)**, **`PUT /api/sessions/{id}/identity` (incl. short name)**, **reset dry-run** |
| M2 | **Study files** | 1 bring in, 2 validate, 3 conflicts, 4 classification; CLEAR_FILES, RESET | which files belong, and what each one is | M1 (a session), shared kit | `POST /api/upload-*`; `GET /api/wizard/{id}/files`; `DELETE /api/pool/{id}/files/{name}`; `POST /api/pool/validate/{id}`; `GET /api/wizard/{id}/fingerprints`; `POST /api/pool/resolve`; `POST /api/pool/confirm-metadata/{id}`; `POST /api/pool/reset/{id}`; **one checked upload**, **restore a removed file**, **`GET` validation report**, **precedence list/replace**, **durable, name-keyed classifications**, **vocabularies** |
| M3 | **Integration and the dataset** | 5 integrate; review the experiments and their metadata (per-experiment approval) | is the merged dataset what the files say | M2 (VALIDATED), shared kit | `POST /api/pool/integrate/{id}`; `GET /api/integrated-summary/{id}`; `GET`/`POST /api/experiment-metadata/{id}` (POST fixed); **stated-vs-inferred per field**; **refuse on id mismatch / wrong phase** |
| M4 | **Study facts** | 6: design, short name, front matter, deposit, eFDR | what the data can't say | M3 for the design and eFDR (they need integration); front matter and deposit need only M1 | `GET`/`POST /api/document/{id}/front-matter` (POST to merge or be whole-form); `GET /api/sessions/{id}/supplemental/`; **design GET/POST**, **design facts (stated/recorded/fallback/conflict)**, **deposit upload + record**, **eFDR record**, **short name** |
| M5 | **Method and document pins** | 7 | which method, which document, fixed or tracking | M1; mismatches need M3 | **profiles list**, **method pin GET/POST with settings, deviations, live mismatches**, **definition pin GET/POST with drift** |
| M6 | **Data approval** | 8 | is the data right; go on to Process | M2–M5 (it reads their state; it writes none of theirs) | `POST /api/generate-animal-report/{id}`; **`GET` animal report**, **readiness checklist (derived)**, **withdraw approval** |

Why this cut:
- **Steps 2–4 belong in one module (M2).** They are one judgement about the same
  objects (the files), and the backend makes them interdependent: a
  classification changes the coverage matrix, which needs a re-validation, which
  today forgets the classification. Splitting them across modules would put that
  coupling on a contract boundary.
- **Experiment metadata belongs in M3, not M4.** It reviews what integration
  inferred, experiment by experiment, and it is stored as the integration's
  approval. The study design is a statement about the whole study; it lives in M4
  but shows in M3's review as "stated".
- **Front matter and the deposit sit in M4, but nothing in the data needs them.**
  The document steps need them. They could move to the document group, the
  "configurator" (HANDOFF §10.6). I kept them with the other statements because
  HANDOFF §3 puts them at step 6, and the person who knows the design usually
  knows the authors. Open question Q7.
- **M5 stands apart.** Its decisions recompute everything and have their own
  history. It also has no route at all yet, so it is mostly backend work.
- **M6 only reads.** It composes the others' derived state into one gate, so it
  can be built last against their contracts.

**Backend work this cut implies.** The orchestrator will route these to the
backend engineer.
1. Enforce `legal_actions` in the steps (or one guard in the engine).
2. Integration refuses when the fingerprints don't match the coverage matrix, and
   drops a prior approval.
3. Precedence keyed by compound key and file name.
4. Classifications durable and name-keyed.
5. The experiment-metadata POST merges and checks the vocabulary, and the
   approval file accumulates.
6. The front-matter POST is whole-form or merges, and checks its fields.
7. Integration stops overwriting the identity.
8. Mismatches are derived live, not stored in the validation report.
9. Reads have no side effects (folder creation, re-scan, upload registration).
10. The upload checks file types and pairs companions.
11. Dry-run lists for destructive acts; a file restore.
12. The missing routes in the table.

---

## 5. Open questions for the maintainer

Only the ones the code can't settle.

- **Q1. Conflicts.** Should a person's choice between two disagreeing files clear
  a `dose_mismatch` or `animal_count_mismatch` error, or must the files always be
  fixed? Today the choice clears nothing, and for apical platforms it has no
  effect. What should happen to `redundant_files` (both are merged today)?
- **Q2. One study, one id?** A session's id picks its document definition, its
  method overlay and its deposit wording. Is the session id always the chemical's
  DTXSID, so that a second attempt replaces the first? Or should a session name
  its study (and its definition) separately from its id?
- **Q3. Is a `.bm2` still required for apical platforms?** The completeness rule
  says each apical platform "Requires .bm2 for BMD/BMDL values", but Process
  computes apical BMDs itself, and NIEHS-10 builds without one. Should the rule
  change, or the message?
- **Q4. What does "approve the data" assert, and does it gate Process?** Today it
  is the generation of the animal report: no review, no name. It survives
  re-integration and gates nothing. Should it record who approved, require the
  readiness checklist, and be required before Process?
- **Q5. Where is the dose unit stated?** The data often lacks it (NIEHS-10's
  fingerprints all have none), and today it is a Process parameter that falls back
  to mg/kg. Should it be a stated study fact (step 6) like the route and vehicle?
- **Q6. Stated facts with history?** Pins keep their history; the design, the
  experiment-metadata approval and the front matter are overwritten in place.
  Should they keep versions (ADR-0020's "one evolving report with history")?
- **Q7. Where do front matter and the deposit belong?** With the data statements
  (step 6, as HANDOFF §3 has it), or with the document configurator? Do the same
  people state them?
- **Q8. Deposits from a browser.** `record_deposit` reads a folder on the server.
  For a person in a browser, is the deposit the files they upload into the
  session's `supplemental/` folder? And until the DOI exists, may the report print
  the local address `http://127.0.0.1:9000/…`, or should it be a "[… pending]"?
- **Q9. Should the method profile be chosen before integration?** Integration pins
  the newest by default today, and the eFDR depends on the pin. Should a new study
  have to choose (no default), given that the profile also fixes the Methods text?

---

## Appendix: what was run

Scratch sessions under `/workspace/ui-team/_scratch/analyst-data/sessions/`:

| session | what was done |
|---|---|
| `DTXSID50469320_ana` (A) | the main walk, EMPTY → APPROVED |
| `_anb` (B) | restart trap → integration with 4 of 16 experiments |
| `_anc` (C) | precedence, wrong classifications, inconsistent design, HTTP metadata approval |
| `_and` (D) | approval before integration → APPROVED; 122 animals |
| `_ane` (E) | statements on an EMPTY session |
| `_anf` (F) | upload at APPROVED → what invalidation keeps |
| `_ang` (G) | uploads over HTTP |
| `_anh` (H) | integration at VALIDATION_ERRORS; identity overwrite |
| `_anr` | pool reset |
| `_ans` | session reset |

The HTTP checks used FastAPI's `TestClient` (no port opened).

The checkpoint tests for these steps passed: 112 tests in
`test_workflow_legal_actions`, `_steps`, `_engine`, `test_dtxsid_validation`,
`test_study_design`, `test_definition_pin`, `test_method_profile`,
`tests/integration/test_pool_file_removal` and `test_workflow_state_route`. None
of them covers the defects in §0. They pin the behaviour as it is.
