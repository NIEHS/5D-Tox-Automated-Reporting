# M2 Study files: API contract

Every route is under `/api/v2/`, is a thin driver (parse → core → serialize),
answers errors in the §4.2 envelope (`MODULES.md`) and has no side effect on a
`GET` (C4). `{id}` is checked with `common.dtxsid.validate_dtxsid` (the session-id
pattern; member studies take files). Every mutating route goes through C1's guard
(`workflow.engine.require_legal`, the action named per route) and C5's run lock.
`{name}` is a file name as the person brought it in, URL-encoded (real names hold
spaces, commas and parentheses: `Body weight.bm2`,
`BMDExpress_Project_File_(bm2_format).bm2`).

Shared contracts used as they are: the state read model (§4.1), the error envelope
(§4.2), the dry-run object (§4.3, plus M1's `preview_token` beside it, R4).

Evidence: **[V]** run on scratch copies (`/workspace/ui-team/_scratch/design-m2/`);
**[R]** read. Dependencies: **[C3] [C4] [C8] [Q10]** as in the spec.

---

## 1. Existing routes this replaces or draws on

| Existing | Where | Its use for M2 |
|---|---|---|
| `POST /api/upload-bm2`, `/api/upload-csv`, `/api/upload-zip` (`?dtxsid=`) | `web_routes/upload_routes.py:78, :280, :396` | Replaced by staging + commit (§2.2–2.4). Today: no type check on two of them, same-name overwrite with no trace, conversion at upload (units lost when the units file comes later), a temp directory without `?dtxsid=` (data analysis finding 12) |
| `GET /api/wizard/{id}/files`, `GET /api/wizard/{id}/fingerprints` | `web_routes/wizard_routes.py:48, :128` | Replaced by `GET …/files` (§2.1). The fingerprints route re-scans on a cold server and mints ids (finding 2) |
| `POST /api/pool/validate/{id}` | `web_routes/pool_routes.py:212` | Replaced by `POST …/check` (§2.5), same core |
| `POST /api/pool/confirm-metadata/{id}` | `pool_routes.py:246` | Replaced by §2.6–2.8 (by name, checked, durable [C3]) |
| `POST /api/pool/resolve` | `pool_routes.py:226` | Replaced by §2.9 [Q10] |
| `DELETE /api/pool/{id}/files/{filename}` | `web_routes/session_routes.py:1479` | Replaced by §2.10 (dry run + token [C8]) |
| `POST /api/pool/reset/{id}` | `session_routes.py:1496-1631` | Replaced by §2.12; its logic moves into the core [C8] |
| `GET /api/v2/studies/{id}/state` | §4.1 | read for the phase, `legal_actions`, `artifacts.integration` (C1), `run` (C5) |
| `GET /api/v2/vocabularies` | §4.5 | the `platform` labels; M2's per-kind choices are served in §2.1 |

---

## 2. Endpoints

### 2.1 `GET /api/v2/studies/{id}/files`: the files view (NEW)

**Core:** NEW `workflow.files.files_view(id, store)`. It reads, never writes:
`files/`, `_originals/`, `_removed/*/removed.json` [C8],
`validation_report.json`, the sidecars, `classifications.json` [C3] and C1's
integration basis. It maps every file id to the brought-in name [C4], and puts the
issue texts into plain words with `workflow.refusals`-style rules (a new
`workflow/file_issues.py`, next to the codes). Cost: one directory listing and
three small JSON reads; it never opens `integrated.json`.

**Response 200 (`FilesView`):**
```json
{
  "id": "DTXSID9000004",
  "phase": "VALIDATION_ERRORS",
  "takes_files": {"allowed": true, "code": null, "say": null},
  "files_token": "sha256:042563ab9a742067",
  "progress": [{"step": "bring_in|check|confirm|conflicts", "status": "done|todo|blocked|waiting|not_needed", "say": "…"}],
  "next": {"act": "ADD_FILES|VALIDATE|CONFIRM_CLASSIFICATION|RESOLVE|INTEGRATE", "say": "…", "fix": "M2|M3"},
  "acts": {"add": Verdict, "check": Verdict, "classify": Verdict, "resolve": Verdict, "remove": Verdict, "reset": Verdict},
  "files": [ FileRow ],
  "check": null | {"run_at": "…Z", "current": true, "why_not_current": null | "…",
                   "counts": {"fix": 2, "look": 2, "expected": 6},
                   "not_shown": null | {"count": 8, "fix": "M5", "say": "…"}},
  "issues": [ Issue ],
  "conflicts": [ Conflict ],
  "coverage": [ CoverageRow ],
  "removed": [ Removed ],
  "integration": null | {"state": "current|out_of_date|unrecorded", "made_at": "…Z", "say": "…", "fix": "M3"},
  "classification_choices": {"table": [Choice], "workbook": [Choice], "bm2": [Choice]},
  "limits": {"max_file_bytes": 536870912, "accepted": [".bm2", ".csv", ".txt", ".xlsx", ".zip", ".units.json"]}
}
```
`Verdict` = `{allowed, code, say}`, derived from `legal_actions`, `kind` and
`run`.

**FileRow:**
```json
{"name": "body_weight_truth_female.csv", "kind": "table|workbook|bm2", "type": "csv",
 "size": 6387, "added_at": "2026-10-12T11:37:20Z", "content_hash": "sha256:12c09dc24d6b2706",
 "companions": [{"name": "body_weight_truth_female.units.json", "role": "units|table|sidecar", "say": "…"}],
 "units": null | {"state": "stated|missing|not_read|not_needed", "values": {"Body Weight": "grams"}, "say": "…"},
 "tables": [{"name": "body_weight_truth_female.txt", "sexes": ["Female"], "doses": [0.0, 0.15, "…"], "dose_unit": null,
             "animals": 55, "animals_by_dose": {"0.0": 10, "…": 5}, "measurements": 4,
             "measurement_sample": ["Body Weight Gain", "SD0", "SD1", "SD5"], "selection_groups": []}],
 "bm2": null | {"experiments": ["Kidney_PFHxSAm_Female", "…"], "species": "Rattus norvegicus", "test_articles": ["PFHxSAm"]},
 "study_number": null, "checked": true,
 "classification": {"platform": "Body Weight", "data_type": "tox_study", "say": "Body Weight · the study's own measurements",
   "detected": {"platform": "Body Weight", "data_type": "tox_study", "basis": "file_name|bm2_experiments|content|none", "say": "From the file name"},
   "stated": null | {"platform": "…", "data_type": "…", "by": "person", "at": "…Z", "content_hash": "sha256:…"},
   "status": "not_checked|unconfirmed|confirmed|changed|needs_reconfirm|not_recognised",
   "flags": [{"code": "several_test_articles|name_says_gap_filled", "level": "warn", "say": "…"}]},
 "issues": ["iss_9806f3fd4a"],
 "pending": [{"what": "units|sex|contents|classification", "say": "[units pending]", "fix": "M2"}],
 "set_aside": null | {"by_conflict": "cfl_…", "say": "…"},
 "acts": {"remove": Verdict, "classify": Verdict}}
```
- `name` is the brought-in name: a converted CSV is one row, and its pivot
  `.txt`/`.sidecar.json` and `.units.json` are `companions` [C4].
- `classification.platform`/`data_type` are the values the check will use:
  `stated` when there is one [C3], else `detected`.
- `status`:
  - `confirmed`: stated and equal to detected;
  - `changed`: stated and different;
  - `needs_reconfirm`: the statement's `content_hash` differs from the file's [C3].

**Issue:**
```json
{"id": "iss_c2caee9b6e", "type": "dose_mismatch", "severity": "error", "group": "fix|look|expected",
 "platform": "Hormones", "data_type": "tox_study", "sex": null,
 "files": ["hormones_truth_female.csv", "hormones_truth_female_rerun.csv"],
 "tables": ["hormones_truth_female.txt", "hormones_truth_female_rerun.txt"],
 "say": "…", "what_to_do": "…|null", "feeds": "M6|null", "fix": "M2|null",
 "message": "…verbatim…", "details": {}}
```
`id` = `iss_` + the first 10 hex of sha256(type | platform key | sorted table names
| message): stable across re-checks and restarts [C4].

**Conflict:**
```json
{"id": "cfl_c2caee9b6e", "issue": "iss_c2caee9b6e", "type": "dose_mismatch|animal_count_mismatch|redundant_files",
 "platform": "Hormones", "data_type": "tox_study", "say": "…",
 "files": [{"name": "…", "kind": "table", "data_type": "tox_study", "sexes": ["Female"], "doses": [], "animals": 40,
            "animals_by_dose": {}, "measurements": [], "added_at": "…Z", "size": 2046}],
 "differences": [{"what": "doses|animals_by_dose|animals|sexes|measurements", "say": "Doses", "by_file": {"<name>": "…"}}],
 "suggested": null | {"name": "…", "why": "…"},
 "decision": null,
 "acts": {"keep": Verdict}}
```
`suggested` is given only when the files are of different kinds; between two
files of one kind the backend's suggestion is just "the first one" [R,
`file_integrator.py:1903`] and is withheld.

**CoverageRow:**
`{"key": "Body Weight|tox_study", "platform": "Body Weight", "label": "Body Weight", "data_type": "tox_study", "data_type_say": "…", "workbook": null, "tables": ["…csv"], "bm2": null, "level": "ok|warn|block", "say": "…"}`.
`level`/`say` come from the revised completeness rule (`workflow/phases.py:206`,
CHANGED per Q10 c).

**Removed** [C8]:
`{"id": "rm_20261015T122035000598Z", "removed_at": "…Z", "files": ["body_weight_truth_female.csv", "body_weight_truth_female.units.json", "body_weight_truth_female.txt", "body_weight_truth_female.sidecar.json"], "why": "removed|set_aside|replaced|reset", "say": "Removed by you", "acts": {"restore": Verdict}}`.

**Choice** (per kind):
`{"data_type": "tox_study", "label": "The study's own measurements", "say": "…", "platforms": ["Body Weight", "Clinical Chemistry", "Hematology", "Hormones", "Organ Weight", "Tissue Concentration", "Clinical"]}`.
Allowed pairs:
- table: `tox_study` with 7 platforms; `inferred` with 6 (no Clinical);
  `gene_expression` with none;
- workbook: `tox_study` with 7;
- bm2: `inferred` with 6; `gene_expression` with none.

Platform values are `bmdx_pipe.VOCABULARIES["platform"]` values [V].

**Errors:** 400 `invalid_study_id`; 404 `study_not_found` (no folder is created,
C4).

### 2.2 `POST /api/v2/studies/{id}/files/staging`: stage a batch and plan it (NEW) [C8]

Guard: ADD_FILES, `takes_files`, run lock.

**Core:**
- NEW `pipeline.intake.stage_batch(id, uploads)` writes to
  `sessions/<id>/_incoming/<batch>/` (outside `files/`, never fingerprinted; the
  phase is unchanged);
- NEW `pipeline.intake.plan_batch(id, batch)` sniffs content, lists zips, pairs
  units, matches names and hashes against `files/`, and computes the add dry run
  with the same code `add_files_step` runs.

**Request:** `multipart/form-data`, field `files` (repeated). A request over the
size limit is refused per file, not as a whole.

**Response 200 (`IntakePlan`):**
```json
{"batch": "b_20261015T141203Z_7f3a", "expires_at": "2026-10-15T15:12:03Z",
 "rows": [ {"name": "…", "from_zip": null | {"zip": "two_same_names.zip", "path": "a/body_weight_truth_male.csv"},
            "size": 6387, "content_hash": "sha256:…", "detected_type": "csv|txt|xlsx|bm2|zip|units|other",
            "verdict": "add|units|replace|units_missing|refused|left_out",
            "code": null | "<§3 code>", "say": "…",
            "pairs_with": null | "<name>",
            "replaces": null | {"name": "…", "size": 6387, "added_at": "…Z", "content_hash": "sha256:…"},
            "needs_answer": null | "replace|without_units",
            "units_check": null | {"columns_without_unit": ["…"], "unknown_columns": []}} ],
 "counts": {"add": 27, "refused": 0, "needs_answer": 0},
 "dry_run": null | { "…§4.3…": "…" },
 "plan_token": "sha256:…"}
```
- `dry_run` is null when the study was never checked (nothing is invalidated).
- `plan_token` covers the rows and the study's files and derived artifacts.

**Errors:** 409 `phase_not_allowed` (never for ADD_FILES in C1), `run_in_flight`,
`read_only_session`, `takes_no_files`; 400 when no file is given.

### 2.3 `POST /api/v2/studies/{id}/files/staging/{batch}/commit`: bring them in (NEW)

**Core:** NEW `workflow.steps.add_files_step(id, batch, plan_token, answers, store)`:
1. the guard (ADD_FILES), then `plan_token` is re-derived and compared;
2. every unanswered `needs_answer` row is refused;
3. accepted rows move into `files/`, replaced files to `_removed/<stamp>/` with
   `why: replaced` [C8], and `without_units` answers are recorded in
   `classifications.json` [C3];
4. `invalidate_pool_artifacts` runs when the pool had progressed (archiving
   `animal_report.json`, C8);
5. the batch is deleted.

Conversion of one-row-per-animal CSVs happens at the check, not here.

**Request:** `{"plan_token": "sha256:…", "replace": ["<name>"], "without_units": ["<name>"]}`

**Response 200:**
`{"added": ["…"], "replaced": [{"name": "…", "removed_id": "rm_…"}], "invalidated": null | {"deleted": ["…"], "marked_stale": ["summary.json"], "approval_archived": "history/_data_approval/…"}}`

**Errors:** 410 `staging_expired`; 409 `changed_since_preview`; 400
`answer_required` (`details.rows`); 409 `phase_not_allowed`/`run_in_flight`.

### 2.4 `DELETE /api/v2/studies/{id}/files/staging/{batch}`: discard (NEW)

Removes `_incoming/<batch>/`. 200 `{"discarded": true}`; 404 `staging_expired`
when gone (shown as nothing to do, `noop`).

### 2.5 `POST /api/v2/studies/{id}/check`: the file check (NEW route, existing core)

**Core:** `workflow.steps.validate_step` (guard VALIDATE, C1), CHANGED:
- it honours `classifications.json` [C3];
- it converts one-row-per-animal CSVs with their units files;
- it always reads `.bm2` contents (not only when the name fails to classify,
  `file_integrator.py:1444`).

It never deletes the dataset (C1 D4).

**Request:** none. **Response 200:** the `FilesView` (§2.1), freshly derived.

**Errors:** 409 `phase_not_allowed` (EMPTY), `run_in_flight`; 500
`server_setup_failed` (Java for the `.bm2` export; refusals.py) or `unexpected`.

**Timing [V]:** 0.2 s warm; 7.9 s with a cold cache and a 40 MB `.bm2`.

### 2.6 `PUT /api/v2/studies/{id}/files/{name}/classification`: say what a file is (NEW) [C3]

**Core:** CHANGED `workflow.steps.confirm_metadata_step(id, {name: {platform, data_type}}, store)`.
It is keyed by name; checked against the vocabulary and the allowed pairs (§2.1);
written to `classifications.json` with the file's `content_hash`, by `person`, at
now. The `# Platform`/`# Data Type` headers are still written into converted
tables for Java. It never rewrites `_fingerprints.json` from memory (finding 4).

**Request:** `{"platform": "Hormones" | null, "data_type": "tox_study", "preview_token": "…|null"}`.
`preview_token` is required when `GET …/dry-run/classify` returned a costly dry run.

**Response 200:** `{"file": FileRow, "previous": null | {"platform": "…", "data_type": "…"}, "check_current": false}`

**Errors:**
- 400 `classification_not_allowed`;
- 404 `file_not_found`;
- 409 `phase_not_allowed`, `changed_since_preview`, `run_in_flight`.

### 2.7 `DELETE /api/v2/studies/{id}/files/{name}/classification`: back to detected (NEW) [C3]

Removes the statement. The response is as §2.6. A file with no statement gives
`noop` `{"code": "nothing_stated", "say": "This file has no statement to undo."}`.

### 2.8 `POST /api/v2/studies/{id}/files/classification/confirm`: confirm as shown (NEW) [C3]

**Request:** `{"files_token": "sha256:…", "files": [{"name": "…", "platform": "…", "data_type": "…"}]}`.
Each entry must equal the row's current classification; it is recorded as stated.

**Response 200:** `{"confirmed": ["…"]}`

**Errors:**
- 409 `files_changed` (the token differs);
- 400 `classification_not_allowed`;
- 409 `phase_not_allowed`.

### 2.9 `POST /api/v2/studies/{id}/conflicts/{conflict_id}/keep`: settle a conflict (NEW) [Q10, C8]

Guard: RESOLVE.

**Core, option C (recommended):** NEW `workflow.steps.keep_file_step(id, conflict_id, keep, preview_token)`.
It re-derives the conflict from the current check (by its file names), refuses a
`keep` not among them, and moves the other files (with companions) to `_removed/`
with `why: set_aside`, `by_conflict`. `precedence.json` retires; `resolve_step`
stays for the command line until removed.

**Core, option B:** records `{key: "Hormones|tox_study", keep, set_aside: [names]}`
in `precedence.json`, honoured by `validate_pool` and `integrate_pool` (C3 item 5).
The response is the same with `"removed_id": null`.

**Request:** `{"keep": "hormones_truth_female.csv", "preview_token": "…"}`

**Response 200:**
`{"kept": "…", "set_aside": ["hormones_truth_female_rerun.csv"], "removed_id": "rm_…", "check_current": false, "invalidated": null | {…}}`

**Errors:**
- 404 `conflict_not_found`;
- 400 `conflict_choice_invalid`;
- 409 `changed_since_preview`, `phase_not_allowed`, `run_in_flight`.

### 2.10 `POST /api/v2/studies/{id}/files/{name}/remove`: remove a file (NEW route, CHANGED core) [C8]

Guard: REMOVE_FILE.

**Core:** `pipeline.pool_state.remove_pool_file` (`pool_state.py:293`), CHANGED:
- the guard;
- the `.units.json` moves too [V: left behind today];
- writes `_removed/<stamp>/removed.json` `{why, files, removed_at, by_conflict?}`;
- removes the statement from `classifications.json` into the record;
- archives the approval on invalidation.

**Request:** `{"preview_token": "…"}`

**Response 200:**
`{"removed_id": "rm_…", "moved": ["…"], "pool_invalidated": true, "invalidated": {"deleted": ["validation_report.json"], "marked_stale": []}}`.
The shape is today's response, plus `removed_id` [V].

**Errors:**
- 404 `file_not_found`;
- 400 `companion_not_removable`, `name_invalid`;
- 409 `changed_since_preview`, `phase_not_allowed`, `run_in_flight`.

### 2.11 `POST /api/v2/studies/{id}/removed/{removed_id}/restore`: restore (NEW) [C8]

Guard: ADD_FILES.

**Core:** NEW `workflow.steps.restore_file_step`. It moves the files back to
`files/` (a converted CSV and its units file go back as brought in, to be
converted at the next check), restores the classification statement, and
invalidates as an addition does.

**Request:** `{"preview_token": "…"}`. **Response 200:** `{"restored": ["…"], "invalidated": null | {…}}`

**Errors:** 404 `removed_not_found`; 409 `restore_name_taken`,
`changed_since_preview`.

### 2.12 `POST /api/v2/studies/{id}/files/reset`: start the files over (NEW route, moved core) [C8]

Guard: RESET.

**Core:** NEW `workflow.steps.reset_files_step(id, confirm_id, preview_token)`:
- the logic of `session_routes.py:1496-1631`, unchanged in what it deletes and
  keeps (it deletes `_removed/` too, as today);
- it also deletes C1's `integration_basis.json`, `classifications.json` and
  `_incoming/`;
- it clears the in-memory registries.

**Request:** `{"confirm_id": "DTXSID50469320", "preview_token": "…"}`

**Response 200:** `{"deleted": ["files/", "…"], "kept": ["identity.json", "…"]}`

**Errors:** 400 `confirm_mismatch`; 409 `changed_since_preview`,
`phase_not_allowed`, `run_in_flight`.

### 2.13 `GET /api/v2/studies/{id}/dry-run/{act}`: the dry runs (the kit's path, NEW) [C8]

| `act` | Query | Strength |
|---|---|---|
| `remove_file` | `file=<name>` | `reversible` when the study was never checked, else `costly` |
| `restore_file` | `removed=<removed_id>` | as `add_files` |
| `classify` | `file=<name>&platform=&data_type=` | `reversible`; `costly` when `integration` is `current` |
| `keep` | `conflict=<id>&keep=<name>` | as `remove_file` [Q10 C] |
| `reset_files` | – | `irreversible` |

`add_files` is not here: it is inside the staging plan (§2.2).

**Response 200:** `{"confirm": { …§4.3… }, "type_to_confirm": null | "<id>", "preview_token": "sha256:…"}` (M1's shape).

**Errors:** as the act's, without performing it. Side-effect-free (C4).

---

## 3. Refusal codes

Statuses and `say` are in `spec.md` §6. New codes for `workflow/refusals.py`:
- `takes_no_files`;
- `file_type_refused`, `sidecar_refused`, `empty_file`, `file_too_large`,
  `name_invalid`, `duplicate_name_in_batch`;
- `content_mismatch`, `zip_invalid`, `zip_nested`, `zip_name_clash`,
  `same_content`;
- `units_without_table`, `units_invalid`, `units_for_converted_file`;
- `answer_required`, `staging_expired`, `files_changed`;
- `file_not_found`, `companion_not_removable`, `removed_not_found`,
  `restore_name_taken`;
- `classification_not_allowed`, `classification_unconfirmed` (raised by integrate;
  Q-M2-4);
- `conflict_not_found`, `conflict_choice_invalid`.

Reused: `phase_not_allowed`, `validation_out_of_date` (C1); `run_in_flight`,
`read_only_session`, `study_not_found`, `confirm_mismatch`, `changed_since_preview`
(M1); `not_validated`, `no_files`, `server_setup_failed`, `damaged_session_file`,
`unexpected` (kit).

Existing messages to map (the `_MESSAGE_RULES` of `workflow/refusals.py`):

| message | code |
|---|---|
| "Not a pool file name: {filename!r}" | `name_invalid` |
| "{name} is companion metadata for a data file; remove the data file instead" | `companion_not_removable` |
| "No file {name!r} in the pool for {dtxsid}" | `file_not_found` |
| "No session found for {dtxsid}" | `study_not_found` |
| "The uploaded file is not a valid .zip archive" | `zip_invalid` |
| "dtxsid, issue_index, and chosen_file_id are required" | `conflict_choice_invalid` (today `conflict_choice_missing`) |

---

## 4. Fixtures

**Real** = built by `fixtures/_generator.py` from a real `validation_report.json`,
the files and their sidecars. **Projected** = depends on C3/C4/C8 and is built from
real files with the projected shape. All are in
`/workspace/ui-team/_scratch/design-m2/fixtures/`, for the orchestrator to copy to
`ui/src/api/mocks/fixtures/m2/`. Test data sets: `…/design-m2/testdata/T1…T6`.

| Fixture | From | Phase | What it shows |
|---|---|---|---|
| `files.DTXSID50469320.json` | the real `sessions/DTXSID50469320` (NIEHS-10) | APPROVED | 15 rows (13 converted CSVs with units, 2 clinical-observation CSVs, the genomic `.bm2`); 32 issues (25 expected, 7 worth a look, 0 to fix); 8 method checks not shown; `integration` present. Real |
| `files.uploaded.json` | T1 brought in, not checked | UPLOADED | 15 rows "not checked", units paired, classify not allowed with its reason; next = VALIDATE. Real files; the row model is projected [C4] |
| `files.conflicts.json` | T4 checked | VALIDATION_ERRORS | 2 conflicts (Hormones females 1.4 vs 2; a body-weight pivot copy), 2 to fix. Real (redundant made blocking: [Q10 b]) |
| `files.value_mismatch.json` | T5 checked | VALIDATION_ERRORS | `value_mismatch` "1 of 243 … workbook 215.9, table 251.9". Real |
| `files.given2026.json` | T2 checked | VALIDATED | 20 rows: 6 `.bm2` with "[contents not read]", 10 apical BMDExpress input tables as gap-filled, 4 expression matrices; 13 expected issues. Real |
| `files.cebs_workbooks.json` | T3 checked | VALIDATED | 7 workbooks ("[units pending]"), the shared `.bm2` flagged with 4 test articles, coverage rows warning "Only the study workbook". Real |

### 4.1 `GET …/files`, excerpt of `files.conflicts.json` (real)
```json
{"id": "DTXSID9000004", "phase": "VALIDATION_ERRORS",
 "takes_files": {"allowed": true, "code": null, "say": null},
 "files_token": "sha256:042563ab9a742067",
 "progress": [{"step": "bring_in", "status": "done", "say": "5 file(s) in the study"},
              {"step": "check", "status": "blocked", "say": "Checked 2026-10-15: 2 problem(s) to fix"},
              {"step": "confirm", "status": "todo", "say": "5 of 5 file(s) not yet confirmed"},
              {"step": "conflicts", "status": "todo", "say": "2 conflict(s) to settle"}],
 "next": {"act": "CONFIRM_CLASSIFICATION", "say": "Confirm what each file is", "fix": "M2"},
 "check": {"run_at": "2026-10-15T14:37:19Z", "current": true, "why_not_current": null,
           "counts": {"fix": 2, "look": 2, "expected": 6}, "not_shown": null},
 "conflicts": [
  {"id": "cfl_c2caee9b6e", "issue": "iss_c2caee9b6e", "type": "dose_mismatch", "platform": "Hormones", "data_type": "tox_study",
   "say": "hormones_truth_female.csv and hormones_truth_female_rerun.csv are both Hormones data for females, but their doses differ: hormones_truth_female.csv has 1.4 where hormones_truth_female_rerun.csv has 2. One of them is wrong, or belongs to another study.",
   "files": [{"name": "hormones_truth_female.csv", "kind": "table", "data_type": "tox_study", "sexes": ["Female"],
              "doses": [0.0, 0.15, 0.5, 1.4, 4.0, 12.0, 37.0, 111.0], "animals": 40,
              "animals_by_dose": {"0.0": 9, "0.15": 4, "0.5": 5, "1.4": 5, "4.0": 4, "12.0": 4, "37.0": 4, "111.0": 5},
              "measurements": ["Free Thyroxine", "Thyroid Stimulating Hormone", "Total Thyroxine", "Triiodothyronine"],
              "added_at": "2026-10-15T14:37:18Z", "size": 2046},
             {"name": "hormones_truth_female_rerun.csv", "kind": "table", "data_type": "tox_study", "sexes": ["Female"],
              "doses": [0.0, 0.15, 0.5, 2.0, 4.0, 12.0, 37.0, 111.0], "animals": 40, "…": "…", "size": 2046}],
   "differences": [{"what": "doses", "say": "Doses", "by_file": {"hormones_truth_female.csv": [0.0, 0.15, 0.5, 1.4, 4.0, 12.0, 37.0, 111.0],
                                                                  "hormones_truth_female_rerun.csv": [0.0, 0.15, 0.5, 2.0, 4.0, 12.0, 37.0, 111.0]}},
                   {"what": "animals_by_dose", "say": "Animals per dose", "by_file": {"…": "…"}}],
   "suggested": null, "decision": null, "acts": {"keep": {"allowed": true, "code": null, "say": null}}},
  {"id": "cfl_0ed5998d68", "issue": "iss_0ed5998d68", "type": "redundant_files", "platform": "Body Weight",
   "say": "body_weight_truth_female_copy.txt and body_weight_truth_female.csv hold the same data (same platform, sex, doses, measurements and animals). Both would be combined, so it would count twice.",
   "files": ["…"], "differences": [], "suggested": null, "decision": null, "acts": {"keep": {"allowed": true, "code": null, "say": null}}}]}
```

### 4.2 A `FileRow` of `files.DTXSID50469320.json` (real)
```json
{"name": "body_weight_truth_female.csv", "kind": "table", "type": "csv", "size": 6387,
 "added_at": "2026-10-12T11:37:20Z", "content_hash": "sha256:12c09dc24d6b2706",
 "companions": [{"name": "body_weight_truth_female.units.json", "role": "units", "say": "its measurement units"},
                {"name": "body_weight_truth_female.txt", "role": "table", "say": "the table the check made from it, one column per animal, for BMDExpress"},
                {"name": "body_weight_truth_female.sidecar.json", "role": "sidecar", "say": "what the table can't hold: each animal's group, day and terminal flag"}],
 "units": {"state": "stated", "values": {"Body Weight": "grams"}, "say": "1 unit(s), from body_weight_truth_female.units.json"},
 "tables": [{"name": "body_weight_truth_female.txt", "sexes": ["Female"],
             "doses": [0.0, 0.15, 0.5, 1.4, 4.0, 12.0, 37.0, 111.0, 333.0, 1000.0], "dose_unit": null, "animals": 55,
             "animals_by_dose": {"0.0": 10, "0.15": 5, "0.5": 5, "1.4": 5, "4.0": 5, "12.0": 5, "37.0": 5, "111.0": 5, "333.0": 5, "1000.0": 5},
             "measurements": 4, "measurement_sample": ["Body Weight Gain", "SD0", "SD1", "SD5"], "selection_groups": []}],
 "bm2": null, "study_number": null, "checked": true,
 "classification": {"platform": "Body Weight", "data_type": "tox_study", "say": "Body Weight · the study's own measurements",
   "detected": {"platform": "Body Weight", "data_type": "tox_study", "basis": "file_name", "say": "From the file name"},
   "stated": null, "status": "unconfirmed", "flags": []},
 "issues": ["iss_9806f3fd4a", "iss_85742f13aa", "iss_e14d185915"], "pending": [],
 "acts": {"remove": {"allowed": true, "code": null, "say": null}, "classify": {"allowed": true, "code": null, "say": null}}}
```
And its `roster_subset` issue (real):
```json
{"id": "iss_9806f3fd4a", "type": "roster_subset", "severity": "info", "group": "expected", "platform": "Body Weight",
 "files": ["body_weight_truth_female.csv"], "tables": ["body_weight_truth_female.txt"],
 "say": "6 of the 61 female animals in the study's roster are not in body_weight_truth_female.csv, for example 544, 545, 546, 550, 552. Animals that died early or were kept for blood sampling are often missing from some measurements; the data review accounts for each one.",
 "what_to_do": null, "feeds": "M6", "fix": null,
 "message": "body_weight_truth_female.txt (Female): 55/61 animals — missing 6 (544, 545, 546, 550, 552)",
 "details": {"sex": "Female", "file_count": 55, "roster_count": 61, "missing_count": 6}}
```

### 4.3 The shared `.bm2` row of `files.cebs_workbooks.json` (real, abridged)
```json
{"name": "C20022-01_EPA_PFAS_Kidney_Overflow_plate_removed_S1500_Plus_Analysis_Traditional.bm2", "kind": "bm2", "size": 40485229,
 "bm2": {"experiments": ["Kidney_2,3-Benzofluorene_Female", "…16 in all…", "Liver_PFHxSAm_Male"], "species": "Rattus norvegicus",
         "test_articles": ["10-2 FTOH", "2,3-Benzofluorene", "6-1 FTOH", "PFHxSAm"]},
 "classification": {"platform": null, "data_type": "gene_expression", "say": "Gene expression · gene-expression data",
   "detected": {"basis": "bm2_experiments", "say": "From the experiment names inside the BMDExpress project"}, "status": "unconfirmed",
   "flags": [{"code": "several_test_articles", "level": "warn",
              "say": "This BMDExpress project holds experiments of 4 test articles (10-2 FTOH, 2,3-Benzofluorene, 6-1 FTOH, PFHxSAm). Only this study's belong in it."}]}}
```
`test_articles` is read from experiment names of the form
`<Organ>_<article>_<Sex>[_No0]`: an inference, empty when the names don't follow
it (as in RR-8's `TPHP mg_kg`).

### 4.4 `POST …/files/staging` with T6 and two T1 files (projected [C8]; real names, sizes, hashes and first bytes)
```json
{"batch": "b_20261015T141203Z_7f3a", "expires_at": "2026-10-15T15:12:03Z",
 "rows": [
  {"name": "body_weight_truth_female.csv", "size": 6387, "content_hash": "sha256:12c09dc24d6b2706", "detected_type": "csv",
   "verdict": "add", "code": null, "say": "Will be added.", "pairs_with": "body_weight_truth_female.units.json", "replaces": null, "needs_answer": null,
   "units_check": {"columns_without_unit": [], "unknown_columns": []}},
  {"name": "body_weight_truth_female.units.json", "size": 29, "content_hash": "sha256:09936eaa107ce8dd", "detected_type": "units",
   "verdict": "units", "say": "Units for body_weight_truth_female.csv (1 measurement: grams).", "pairs_with": "body_weight_truth_female.csv"},
  {"name": "tissue_conc_truth_female.csv", "size": 963, "content_hash": "sha256:aa7a8da50fce83ed", "detected_type": "csv",
   "verdict": "units_missing", "needs_answer": "without_units",
   "say": "This one-row-per-animal table came without a units file. Its tables will show [units pending] for every measurement."},
  {"name": "hormones_male_table.bm2", "size": 1120, "content_hash": "sha256:29c203fd87d93583", "detected_type": "txt",
   "verdict": "refused", "code": "content_mismatch",
   "say": "hormones_male_table.bm2 is named .bm2 but is a text table, not a BMDExpress project. Rename it to .txt if it is a table."},
  {"name": "body_weight_truth_male.csv", "from_zip": {"zip": "two_same_names.zip", "path": "a/body_weight_truth_male.csv"}, "size": 6140,
   "verdict": "refused", "code": "zip_name_clash",
   "say": "The zip holds two files named body_weight_truth_male.csv (in a/ and b/). Only one could be kept, and the tool can't know which. Neither is brought in; unzip it and choose."},
  {"name": "body_weight_truth_male.csv", "from_zip": {"zip": "two_same_names.zip", "path": "b/body_weight_truth_male.csv"}, "size": 6387,
   "verdict": "refused", "code": "zip_name_clash", "say": "…as above…"},
  {"name": "lab_notes.txt", "size": 32, "detected_type": "txt", "verdict": "add",
   "say": "Will be added. Its name doesn't say what it is; the check will ask."},
  {"name": "Organ_Weights_M.csv", "size": 3559, "content_hash": "sha256:4379d1bd24a51c90", "detected_type": "csv",
   "verdict": "units_missing", "needs_answer": "without_units", "say": "…as above…"}],
 "counts": {"add": 3, "refused": 3, "needs_answer": 2},
 "dry_run": null, "plan_token": "sha256:…"}
```
The `.pdf`, `.docx`, `.sidecar.json` and empty file of T6 never reach this call:
the browser refuses them (spec §4). Sent anyway, they are rows with
`file_type_refused`, `sidecar_refused` and `empty_file`.

### 4.5 `GET …/dry-run/remove_file?file=body_weight_truth_female.csv` on a checked study (projected [C8])
```json
{"confirm": {"act": "remove_file", "strength": "costly",
  "deletes": [{"what": "validation_report.json", "say": "the result of the last file check"}],
  "keeps": [{"what": "_removed/", "say": "the file, its units file, its table and its sidecar, among the removed files; they can be restored"}],
  "approvals_lost": [], "cost": {"say": "checking the files again (a few seconds)"}, "reason_required": false},
 "type_to_confirm": null, "preview_token": "sha256:…"}
```

### 4.6 The `add_files` dry run inside a plan, on a copy of NIEHS-10 (APPROVED) (projected [C8]; lists from the real session and `invalidate_pool_artifacts`)
```json
{"act": "add_files", "strength": "costly",
 "deletes": [
  {"what": "validation_report.json", "say": "the result of the last file check"},
  {"what": "integrated.json", "say": "the combined dataset (77 MB)"},
  {"what": "_category_lookup.json, genomics.sidecar.json", "say": "what was extracted from the BMDExpress project when combining"},
  {"what": "animal_report.json", "say": "the data review (kept in history)"},
  {"what": "_cache_*.json (11 files)", "say": "the stored results of processing, except the BMD modelling"},
  {"what": "session.duckdb, session_parquet/", "say": "the query copy of the study's data"},
  {"what": ".prepare_content.*, .session_db.fingerprint", "say": "markers of what was prepared"}],
 "keeps": [
  {"what": "files/", "say": "the study's 15 files"},
  {"what": "_cache_bmds_8ae93f847385c399.json", "say": "the stored BMD modelling, reused where nothing changed"},
  {"what": "bm2_*.json (7 sections), background.json", "say": "the result sections and the Background"},
  {"what": "summary.json", "say": "the Summary, marked out of date: it must be read and approved again"},
  {"what": "identity.json, study_design.json, front_matter.json, deposit.json, method_profile.json", "say": "what people stated, and the method pin"},
  {"what": "history/", "say": "past versions"}],
 "approvals_lost": [],
 "cost": {"say": "checking the files again, combining them again (about 25 s), and processing again (about 3 minutes, the BMD modelling reused)"},
 "reason_required": false}
```
`approvals_lost` is empty because no section of the real session is approved
(checked); a copy with approved sections lists their keys.

### 4.7 `GET …/dry-run/reset_files` on a copy of NIEHS-10 (projected [C8]; lists from `session_routes.py:1496-1631` and the real session)
```json
{"confirm": {"act": "reset_files", "strength": "irreversible",
  "deletes": [
   {"what": "files/ (15 files and their tables)", "say": "every data file brought into the study"},
   {"what": "_originals/ (24 files)", "say": "the one-row-per-animal files and their units files"},
   {"what": "integrated.json, integrated.bm2", "say": "the combined dataset"},
   {"what": "validation_report.json, _fingerprints.json, _category_lookup.json, genomics.sidecar.json", "say": "the file check and what was read from the files"},
   {"what": "animal_report.json", "say": "the data review"},
   {"what": "bm2_*.json (7 files)", "say": "the apical result sections"},
   {"what": "summary.json", "say": "the Summary"},
   {"what": "_cache_*.json (12 files), session.duckdb, session_parquet/", "say": "the stored results of processing"}],
  "keeps": [
   {"what": "identity.json", "say": "the chemical's name and identifiers"},
   {"what": "study_design.json, front_matter.json, deposit.json", "say": "the study design, the authors and the deposit record: they will apply again to the next files"},
   {"what": "method_profile.json", "say": "the method pin"},
   {"what": "background.json", "say": "the Background"},
   {"what": "history/", "say": "past versions"}],
  "approvals_lost": [], "cost": {"say": "bringing the files in again, checking, combining and a full Process"}, "reason_required": false},
 "type_to_confirm": "DTXSID50469320", "preview_token": "sha256:…"}
```

### 4.8 Refusals (§4.2 envelope)
```json
{"error": {"code": "restore_name_taken", "status": 409,
           "message": "RESTORE refused for DTXSID9000004: body_weight_truth_female.csv is in files/",
           "say": "A file named body_weight_truth_female.csv is in the study now. Remove it first, then restore.",
           "fix": "M2", "details": {"name": "body_weight_truth_female.csv", "removed_id": "rm_20261015T122035000598Z"}}}
```
```json
{"error": {"code": "phase_not_allowed", "status": 409,
           "message": "VALIDATE refused for DTXSID9000006: the study is in phase EMPTY (allowed now: ADD_FILES). Add the study's files first.",
           "say": "Checking the files isn't possible yet. This study has no data files yet. Add the study's files first.",
           "fix": "M2", "details": {"action": "VALIDATE", "phase": "EMPTY", "legal_actions": ["ADD_FILES"], "integration": null, "next_action": "ADD_FILES"}}}
```

---

## 5. Requests to other parties (through the orchestrator)

- **C4:** spec §10 items 1–4: `files_view` keyed by brought-in names; stable issue
  and conflict ids.
- **C3:** spec §10 items 1–7: `classifications.json`; the vocabulary check; the
  integration basis; `check.current`.
- **C8:** spec §10 items 1–8: staging; dry runs; tokens; removal with all
  companions; restore; archived replacement and approval; the reset moved to core.
- **C1:** `classification_unconfirmed` at integrate, if Q-M2-4 is accepted.
- **Core track** (bmdx-pipe / `workflow.phases`):
  - conversion at the check;
  - `redundant_files` blocking (Q10 b);
  - the completeness rule (Q10 c);
  - `.bm2` always read;
  - workbook units;
  - content-based data type (Q-M2-6);
  - investigating the workbook-only loss of 5 apical experiments [V].
- **Kit/shell:** spec §9 R-M2-1 … R-M2-9.
