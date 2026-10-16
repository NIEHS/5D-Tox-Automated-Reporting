# M2 Study files: API contract

Revised 2026-10-16 to the maintainer's answers (spec §11).

Every route is under `/api/v2/`, is a thin driver (parse → core → serialize),
answers errors in the §4.2 envelope (`MODULES.md`) and has no side effect on a
`GET` (C4). `{id}` is checked with `common.dtxsid.validate_dtxsid` (the session-id
pattern; member studies take files). Every mutating route goes through C1's guard
(`workflow.engine.require_legal`, the action named per route) and C5's run lock.
`{name}` is a file name as the person brought it in, URL-encoded. Real names hold
spaces, commas and parentheses: `Body weight.bm2`,
`BMDExpress_Project_File_(bm2_format).bm2`.

Shared contracts used as they are: the state read model (§4.1), the error envelope
(§4.2), the dry-run object (§4.3, plus M1's `preview_token` beside it, R4).

Evidence: **[V]** run on scratch copies (`/workspace/ui-team/_scratch/design-m2/`,
2026-10-15; `/workspace/ui-team/_scratch/m2-design/`, 2026-10-16); **[R]** read.
Dependencies: **[C3] [C4] [C8] [C12] [core]** as in the spec (§10).

---

## 1. Existing routes this replaces or draws on

| Existing | Where | Its use for M2 |
|---|---|---|
| `POST /api/upload-bm2`, `/api/upload-csv`, `/api/upload-zip` (`?dtxsid=`) | `web_routes/upload_routes.py:95, :301, :421` | Replaced by staging + commit (§2.2–2.4). Today: no type check on two of them; a same-name upload overwrites with no trace (:133-135); conversion at upload (units lost when the units file comes later); a temp directory without `?dtxsid=` (data analysis finding 12) |
| `GET /api/wizard/{id}/files`, `GET /api/wizard/{id}/fingerprints` | `web_routes/wizard_routes.py:48, :128` | Replaced by `GET …/files` (§2.1). The fingerprints route re-scans on a cold server and mints ids (finding 2) |
| `POST /api/pool/validate/{id}` | `web_routes/pool_routes.py:212` | Replaced by `POST …/check` (§2.5), same core |
| `POST /api/pool/confirm-metadata/{id}` | `pool_routes.py:246` | Replaced by §2.6–2.8 (by name, checked, durable [C3]) |
| `POST /api/pool/resolve` | `pool_routes.py:226` | Retired for M2: keeping a file is a removal (§2.9); `precedence.json` retires |
| `DELETE /api/pool/{id}/files/{filename}` | `web_routes/session_routes.py:1321` | Replaced by §2.10 (dry run + token [C8]) |
| `POST /api/pool/reset/{id}` | `session_routes.py:1340-1491` | Replaced by §2.12; its logic moves into the core and stops deleting `_removed/` (today :1431) [C8] |
| `GET /api/v2/studies/{id}/state` | §4.1 | read for the phase, `legal_actions`, `artifacts.integration` (C1), `run` (C5) |
| `GET /api/v2/vocabularies` | §4.5 | the `platform` labels; M2's per-kind choices are served in §2.1 |

---

## 2. Endpoints

### 2.1 `GET /api/v2/studies/{id}/files`: the files view (NEW)

**Core:** NEW `workflow.files.files_view(id, store)`. It reads, never writes:
- `files/`, `_originals/`, `_removed/*/removed.json` [C8];
- `validation_report.json`, the sidecars, `classifications.json` [C3];
- C1's integration basis;
- the line counts of `records/files.jsonl` and `records/datasets.jsonl` [C8, C12].

It maps every file id to the brought-in name [C4]. It puts the issue texts into
plain words with `workflow.refusals`-style rules (a new `workflow/file_issues.py`,
next to the codes). It decides each conflict's `settle` kind by its type, never
the front-end. Cost: one directory listing and a few small JSON reads; it never
opens `integrated.json`.

**Response 200 (`FilesView`):**
```json
{
  "id": "DTXSID9000004",
  "phase": "VALIDATION_ERRORS",
  "takes_files": {"allowed": true, "code": null, "say": null},
  "files_token": "sha256:042563ab9a742067",
  "progress": [{"step": "bring_in|check|confirm|conflicts", "status": "done|todo|blocked|waiting|not_needed", "say": "…"}],
  "next": {"act": "ADD_FILES|VALIDATE|CONFIRM_CLASSIFICATION|RESOLVE|INTEGRATE|null", "say": "…", "fix": "M2|M3"},
  "acts": {"add": Verdict, "check": Verdict, "classify": Verdict, "resolve": Verdict, "remove": Verdict, "reset": Verdict},
  "files": [ FileRow ],
  "check": null | {"run_at": "…Z", "current": true, "why_not_current": null | "…",
                   "counts": {"fix": 2, "look": 2, "expected": 6},
                   "not_shown": null | {"count": 8, "fix": "M5", "say": "…"}},
  "issues": [ Issue ],
  "conflicts": [ Conflict ],
  "coverage": [ CoverageRow ],
  "removed": [ Removed ],
  "removed_size": 6416,
  "records": {"files": {"count": 27, "last_at": "…Z"}, "datasets": {"count": 3, "current": 3}},
  "integration": null | {"state": "current|out_of_date|unrecorded", "made_at": "…Z", "say": "…", "fix": "M3"},
  "classification_choices": {"table": [Choice], "workbook": [Choice], "bm2": [Choice]},
  "limits": {"accepted": [".bm2", ".csv", ".txt", ".xlsx", ".zip", ".units.json"]}
}
```
- `Verdict` = `{allowed, code, say}`, derived from `legal_actions`, `kind` and
  `run`.
- `next.act` is null when the next step is a conflict to settle outside the app.
- `limits` has no size: there is no size limit (Q-M2-8).
- `records.datasets` is `{count: 0, current: null}` until C12; `records.files.count`
  is null until C8.

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
 "bm2_changes": null | BmChanges,
 "narrow_choices": null | [{"test_article": "PFHxSAm", "experiments": ["Kidney_PFHxSAm_Female", "…"], "matches_short_name": false}],
 "study_number": null, "checked": true,
 "classification": {"platform": "Body Weight", "data_type": "tox_study", "say": "Body Weight · the study's own measurements",
   "detected": {"platform": "Body Weight", "data_type": "tox_study", "basis": "content|file_name|bm2_experiments|none", "say": "From its content: one row per animal, with Animal ID and Sex columns"},
   "stated": null | {"platform": "…", "data_type": "…", "by": "person", "at": "…Z", "content_hash": "sha256:…"},
   "status": "not_checked|unconfirmed|confirmed|changed|needs_reconfirm|not_recognised",
   "flags": [{"code": "several_test_articles", "level": "warn", "say": "…"}]},
 "issues": ["iss_9806f3fd4a"],
 "pending": [{"what": "units|sex|contents|classification|test_articles", "say": "[units pending]", "fix": "M2"}],
 "acts": {"remove": Verdict, "classify": Verdict, "narrow": null | Verdict}}
```
- `name` is the brought-in name: a converted CSV is one row, and its pivot
  `.txt`/`.sidecar.json` and `.units.json` are `companions` [C4].
- `classification.platform`/`data_type` are the values the check will use:
  `stated` when there is one [C3], else `detected`. `basis: "content"` comes with
  Q-M2-6 [core].
- `status`:
  - `confirmed`: stated and equal to detected;
  - `changed`: stated and different;
  - `needs_reconfirm`: the statement's `content_hash` differs from the file's [C3].
- `units.state` is `stated` for a workbook whose Key sheet gives units (Q-M2-7 b)
  [core].
- `narrow_choices` and `acts.narrow` are present only on a `.bm2` with the
  `several_test_articles` issue [core].

**BmChanges** (a `.bm2` whose apical data differs from its study tables by rule;
Q-M2-3, spec §8) [core; maintainer: confirm]:
```json
{"imputed": null | {"cells": [{"platform": "Hormones", "sex": "Male", "dose": 12.0, "count": 1}], "total": 1,
                    "pairs_with": ["hormones_truth_male.csv"], "say": "…",
                    "footnoted": true, "footnote": "…the report's text…" | null,
                    "basis": "the rule of pipeline.bmd_project_schema._detect_imputed_cells (ADR-0017)", "confirm": "maintainer"},
 "dose_groups_left_out": [{"platform": "Body Weight", "sex": "Female", "doses": [333.0, 1000.0], "pairs_with": "body_weight_truth_female.csv"}],
 "aligned": true}
```
- `footnoted: false` (with `footnote: null`) for a platform whose table builder
  does not print the imputation footnote (today Body Weight and Organ Weight,
  `pipeline/processing_helpers.py:699` [R]).
- `aligned: false` when the `.bm2` and the tables could not be aligned by animal.
  Its `say` then says the imputed values could not be counted:
  `<Pending>` "[imputed values not counted: …]".

**Issue:**
```json
{"id": "iss_c2caee9b6e", "type": "dose_mismatch", "severity": "error", "group": "fix|look|expected",
 "platform": "Hormones", "data_type": "tox_study", "sex": null,
 "files": ["hormones_truth_female.csv", "hormones_truth_female_rerun.csv"],
 "tables": ["hormones_truth_female.txt", "hormones_truth_female_rerun.txt"],
 "say": "…", "what_to_do": "…|null", "feeds": "M6|null", "fix": "M2|null",
 "settle": null | "here" | "outside" | "narrow",
 "message": "…verbatim…", "details": {}}
```
`id` = `iss_` + the first 10 hex of sha256(type | platform key | sorted table names
| message): stable across re-checks and restarts [C4].

New issue types:
- `same_content` (error, `settle: outside`);
- `several_test_articles` (error, `settle: narrow`);
- `bm2_value_mismatch` (error);
- `bm2_fills_missing` (info, group `expected`);
- `bm2_dose_groups_left_out` (info, group `expected`).

`redundant_files` changes from info to error (`settle: outside`) [core].

**Conflict:**
```json
{"id": "cfl_c2caee9b6e", "issue": "iss_c2caee9b6e",
 "type": "dose_mismatch|animal_count_mismatch|redundant_files|same_content",
 "settle": "here|outside",
 "platform": "Hormones", "data_type": "tox_study", "say": "…",
 "files": [{"name": "…", "kind": "table", "data_type": "tox_study", "sexes": ["Female"], "doses": [], "animals": 40,
            "animals_by_dose": {}, "measurements": [], "added_at": "…Z", "size": 2046, "content_hash": "sha256:…"}],
 "differences": [{"what": "doses|animals_by_dose|animals|sexes|measurements", "say": "Doses", "by_file": {"<name>": "…"}}],
 "suggested": null | {"name": "…", "why": "…"},
 "outside": null | {"say": "…", "steps": ["…", "…", "…"]},
 "acts": {"keep": Verdict} | null}
```
- `settle: "here"` (`dose_mismatch`, `animal_count_mismatch` at error severity):
  `acts.keep` is present; `outside` is null.
- `settle: "outside"` (`redundant_files`, `same_content`): `acts` is null,
  `suggested` is null, and `outside.steps` holds the served instructions (spec S3-C
  Kind 2).
- `suggested` is given only for `here` conflicts between files of different kinds.
  Between two files of one kind, the backend's suggestion is just "the first one"
  [R, `bmdx_pipe/file_integrator.py:1904`] and is withheld.

**CoverageRow:**
`{"key": "Body Weight|tox_study", "platform": "Body Weight", "label": "Body Weight", "data_type": "tox_study", "data_type_say": "…", "workbook": null, "tables": ["…csv"], "bm2": null, "level": "ok|warn|block", "say": "…"}`.
`level` and `say` come from the revised completeness rule. A `.bm2` is not
required for an apical platform (`workflow/phases.py:171`, CHANGED per Q-M2-3
[core]).

**Removed** [C8]:
`{"id": "rm_20261015T122035000598Z", "removed_at": "…Z", "files": ["body_weight_truth_female.csv", "body_weight_truth_female.units.json", "body_weight_truth_female.txt", "body_weight_truth_female.sidecar.json"], "size": 30868, "why": "removed|set_aside|replaced|narrowed|reset", "by_conflict": null, "say": "Removed by you", "acts": {"restore": Verdict}}`.

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
- NEW `pipeline.intake.stage_batch(id, uploads)` streams each upload to
  `sessions/<id>/_incoming/<batch>/`. The batch is outside `files/` and never
  fingerprinted, so the phase is unchanged. There is no size limit.
- NEW `pipeline.intake.plan_batch(id, batch)`:
  - sniffs content and lists zips;
  - pairs units files with their tables;
  - matches names and full sha256 hashes against `files/` and within the batch;
  - computes the add dry run with the same code `add_files_step` runs.

**Request:** `multipart/form-data`, field `files` (repeated).

**Response 200 (`IntakePlan`):**
```json
{"batch": "b_20261015T141203Z_7f3a", "expires_at": "2026-10-15T15:12:03Z",
 "rows": [ {"name": "…", "from_zip": null | {"zip": "two_same_names.zip", "path": "a/body_weight_truth_male.csv"},
            "size": 6387, "content_hash": "sha256:…", "detected_type": "csv|txt|xlsx|bm2|zip|units|other",
            "verdict": "add|units|replace|unchanged|copy|units_missing|refused|left_out",
            "code": null | "<§3 code>", "say": "…",
            "pairs_with": null | "<name>",
            "replaces": null | {"name": "…", "size": 6387, "added_at": "…Z", "content_hash": "sha256:…"},
            "copy_of": null | {"name": "…", "where": "study|batch"},
            "needs_answer": null | "replace|copy|without_units",
            "units_check": null | {"columns_without_unit": ["…"], "unknown_columns": []}} ],
 "counts": {"add": 27, "unchanged": 0, "refused": 0, "needs_answer": 0},
 "dry_run": null | { "…§4.3…": "…" },
 "plan_token": "sha256:…"}
```
- `unchanged`: same name and same content as a file in the study; not added,
  not counted in `add`.
- `copy`: same content as a file of another name in the study or the batch
  (Q-M2-9). Answered `copy`, or the row is dropped.
- `replace`: same name, different content (Q-M2-10). Answered `replace`.
- `dry_run` is null when the study was never checked (nothing is invalidated). It
  lists the combined dataset as deleted, with "a copy is kept in the dataset
  record" when C12 keeps one.
- `plan_token` covers the rows and the study's files and derived artifacts.

**Errors:** 409 `phase_not_allowed` (never for ADD_FILES in C1), `run_in_flight`,
`read_only_session`, `takes_no_files`; 400 when no file is given.

### 2.3 `POST /api/v2/studies/{id}/files/staging/{batch}/commit`: bring them in (NEW)

**Core:** NEW `workflow.steps.add_files_step(id, batch, plan_token, answers, store)`:
1. the guard (ADD_FILES), then `plan_token` is re-derived and compared;
2. every unanswered `needs_answer` row is refused;
3. accepted rows move into `files/`:
   - replaced files go to `_removed/<stamp>/` with `why: replaced` [C8];
   - `without_units` answers are recorded in `classifications.json` [C3];
4. one line per added and replaced file is appended to `records/files.jsonl` [C8];
5. `invalidate_pool_artifacts` runs when the pool had progressed. It archives
   `animal_report.json` (C8), and keeps a copy of the combined dataset when Process
   ran on it [C12];
6. the batch is deleted.

Conversion of one-row-per-animal CSVs happens at the check, not here.

**Request:** `{"plan_token": "sha256:…", "replace": ["<name>"], "copy_anyway": ["<name>"], "without_units": ["<name>"]}`

**Response 200:**
`{"added": ["…"], "replaced": [{"name": "…", "removed_id": "rm_…"}], "invalidated": null | {"deleted": ["…"], "marked_stale": ["summary.json"], "approval_archived": "history/_data_approval/…", "dataset_kept": null | "records/datasets/3.integrated.json.gz"}}`

**Errors:** 410 `staging_expired`; 409 `changed_since_preview`; 400
`answer_required` (`details.rows`); 409 `phase_not_allowed`/`run_in_flight`.

### 2.4 `DELETE /api/v2/studies/{id}/files/staging/{batch}`: discard (NEW)

Removes `_incoming/<batch>/`. 200 `{"discarded": true}`; 404 `staging_expired`
when gone (shown as nothing to do, `noop`).

### 2.5 `POST /api/v2/studies/{id}/check`: the file check (NEW route, existing core)

**Core:** `workflow.steps.validate_step` (guard VALIDATE, C1), CHANGED [C3, core]:
- it honours `classifications.json`;
- it converts one-row-per-animal CSVs with their units files;
- it classifies one-row-per-animal files by content (Q-M2-6);
- it reads workbook units from the Key sheet (Q-M2-7 b);
- it always reads `.bm2` contents (not only when the name fails to classify,
  `bmdx_pipe/file_integrator.py:1444`);
- it raises the new issue types of §2.1:
  - `redundant_files` blocking;
  - `same_content` (by content hash);
  - `several_test_articles` (from experiment names);
  - from each `.bm2`/table pair, aligned by animal: `bm2_fills_missing`,
    `bm2_dose_groups_left_out`, `bm2_value_mismatch` (spec §8; [maintainer:
    confirm]).

It never deletes the dataset (C1 D4).

**Request:** none. **Response 200:** the `FilesView` (§2.1), freshly derived.

**Errors:** 409 `phase_not_allowed` (EMPTY), `run_in_flight`; 500
`server_setup_failed` (Java for the `.bm2` export; refusals.py) or `unexpected`.

**Timing [V]:**
- 0.2 s warm; 7.9 s with a cold cache and a 40 MB `.bm2`;
- 29.6 s for the cold read of a 251 MB `.bm2`, whose JSON does not fit the bm2
  cache (`MDB_MAP_FULL`);
- the imputation comparison for one `.bm2` and table: 0.57 s (prototype).

### 2.6 `PUT /api/v2/studies/{id}/files/{name}/classification`: say what a file is (NEW) [C3]

**Core:** CHANGED `workflow.steps.confirm_metadata_step(id, {name: {platform, data_type}}, store)`:
- keyed by name;
- checked against the vocabulary and the allowed pairs (§2.1);
- written to `classifications.json` with the file's `content_hash`, by `person`,
  at now.

The `# Platform`/`# Data Type` headers are still written into converted tables for
Java. It never rewrites `_fingerprints.json` from memory (finding 4).

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

### 2.9 `POST /api/v2/studies/{id}/conflicts/{conflict_id}/keep`: settle a conflict here (NEW) [C8]

Guard: RESOLVE. Only for conflicts with `settle: "here"` (Q-M2-1).

**Core:** NEW `workflow.steps.keep_file_step(id, conflict_id, keep, preview_token)`:
- it re-derives the conflict from the current check (by its file names);
- it refuses a conflict settled outside the app (`conflict_settled_outside`), and
  a `keep` not among the conflict's files;
- it moves the other files, with their companions, to `_removed/` with
  `why: set_aside` and `by_conflict`;
- it appends a `set_aside` line to `records/files.jsonl`.

`precedence.json` retires; `resolve_step` stays for the command line until removed.

**Request:** `{"keep": "hormones_truth_female.csv", "preview_token": "…"}`

**Response 200:**
`{"kept": "…", "set_aside": ["hormones_truth_female_rerun.csv"], "removed_id": "rm_…", "check_current": false, "invalidated": null | {…}}`

**Errors:**
- 404 `conflict_not_found`;
- 400 `conflict_choice_invalid`;
- 409 `conflict_settled_outside`, `changed_since_preview`, `phase_not_allowed`,
  `run_in_flight`.

### 2.10 `POST /api/v2/studies/{id}/files/{name}/remove`: remove a file (NEW route, CHANGED core) [C8]

Guard: REMOVE_FILE.

**Core:** `pipeline.pool_state.remove_pool_file` (`pool_state.py:307`), CHANGED:
- the guard;
- the `.units.json` moves too [V: left behind today];
- writes `_removed/<stamp>/removed.json` `{why, files, removed_at, by_conflict?}`;
- removes the statement from `classifications.json` into the record;
- appends a `removed` line to `records/files.jsonl`;
- archives the approval on invalidation, and keeps a processed dataset [C12].

**Request:** `{"preview_token": "…"}`

**Response 200:**
`{"removed_id": "rm_…", "moved": ["…"], "pool_invalidated": true, "invalidated": {"deleted": ["validation_report.json"], "marked_stale": []}}`.
The shape is today's response, plus `removed_id` [V].

**Errors:**
- 404 `file_not_found`;
- 400 `companion_not_removable`, `name_invalid`;
- 409 `changed_since_preview`, `phase_not_allowed`, `run_in_flight`.

### 2.11 `POST /api/v2/studies/{id}/removed/{removed_id}/restore`: restore (NEW) [C8]

Guard: ADD_FILES (legal in every phase, EMPTY included, so files removed by "Start
over" can be restored).

**Core:** NEW `workflow.steps.restore_file_step`:
- it moves the files back to `files/`. A converted CSV and its units file go back
  as brought in, to be converted at the next check;
- it restores the classification statement;
- it appends a `restored` line;
- it invalidates as an addition does.

**Request:** `{"preview_token": "…"}`. **Response 200:** `{"restored": ["…"], "invalidated": null | {…}}`

**Errors:** 404 `removed_not_found`; 409 `restore_name_taken`,
`changed_since_preview`.

### 2.12 `POST /api/v2/studies/{id}/files/reset`: start the files over (NEW route, moved core) [C8, C12]

Guard: RESET.

**Core:** NEW `workflow.steps.reset_files_step(id, confirm_id, preview_token)`. It
takes the logic of `session_routes.py:1340-1491`, CHANGED:
- **it keeps `_removed/`** (today it deletes it, :1431) and `records/`;
- it moves the files of `files/` (and their `_originals/`) to `_removed/<stamp>/`
  with `why: reset` **[maintainer Q-M2-12; alternative: delete them, recording
  them only]**;
- it deletes, as today:
  - the derived artifacts;
  - C1's `integration_basis.json`, `classifications.json` and `_incoming/`;
  - the caches and `session.duckdb`/`session_parquet/`;
  - the sections, archived by C2;
- it keeps a copy of the combined dataset when Process ran on it [C12];
- it appends a `reset` line;
- it clears the in-memory registries.

**Request:** `{"confirm_id": "DTXSID50469320", "preview_token": "…"}`

**Response 200:** `{"deleted": ["integrated.json", "…"], "moved": {"removed_id": "rm_…", "files": 15}, "kept": ["identity.json", "_removed/", "records/", "…"], "dataset_kept": null | "records/datasets/1.integrated.json.gz"}`

**Errors:** 400 `confirm_mismatch`; 409 `changed_since_preview`,
`phase_not_allowed`, `run_in_flight`.

### 2.13 `GET /api/v2/studies/{id}/dry-run/{act}`: the dry runs (the kit's path, NEW) [C8]

| `act` | Query | Strength |
|---|---|---|
| `remove_file` | `file=<name>` | `reversible` when the study was never checked, else `costly` |
| `restore_file` | `removed=<removed_id>` | as `add_files` |
| `classify` | `file=<name>&platform=&data_type=` | `reversible`; `costly` when `integration` is `current` |
| `keep` | `conflict=<id>&keep=<name>` | as `remove_file` |
| `narrow` | `file=<name>&test_article=<token>` | as `remove_file` |
| `reset_files` | – | `irreversible` |

`add_files` is not here: it is inside the staging plan (§2.2).

**Response 200:** `{"confirm": { …§4.3… }, "type_to_confirm": null | "<id>", "preview_token": "sha256:…"}` (M1's shape).

**Errors:** as the act's, without performing it. Side-effect-free (C4).

### 2.14 `POST /api/v2/studies/{id}/files/{name}/narrow`: keep only this study's experiments (NEW) [core, C8]

Guard: RESOLVE. Only on a `.bm2` with the `several_test_articles` issue (Q-M2-5).

**Core:** NEW `workflow.steps.narrow_bm2_step(id, name, test_article, preview_token)`:
- it checks `test_article` against the project's tokens (from the experiment names
  `<Organ>_<article>_<Sex>[_No0]`);
- it runs `bmdx_pipe.pool_integrator.subset_bm2(path, out, token)` (Java
  `SubsetBm2`) into the staging area;
- it moves the original to `_removed/<stamp>/` with `why: narrowed` and the token;
- it puts the narrowed copy in `files/` under the same name;
- it appends a `narrowed` line (both hashes);
- it invalidates as a replacement does.

[V on T3's 40,485,229-byte project: 1.5 s → 8,220,917 bytes; experiments
`Kidney_PFHxSAm_Female`, `Kidney_PFHxSAm_Male`, `Liver_PFHxSAm_Female`,
`Liver_PFHxSAm_Male`, with 4 BMD results and 8 category results.]

**Request:** `{"test_article": "PFHxSAm", "preview_token": "…"}`

**Response 200:** `{"file": FileRow, "removed_id": "rm_…", "kept_experiments": 4, "check_current": false, "invalidated": null | {…}}`

**Errors:** 400 `narrow_choice_invalid`; 409 `narrow_not_needed`,
`changed_since_preview`, `phase_not_allowed`, `run_in_flight`; 404
`file_not_found`; 500 `server_setup_failed` (Java).

### 2.15 `GET /api/v2/studies/{id}/files/record`: the record of the files (NEW) [C8]

**Core:** NEW `workflow.records.files_record(id, cursor, limit)`. It reads
`records/files.jsonl`, newest first, and never writes.

**Query:** `limit` (default 50, at most 500), `cursor` (from `next`), `name`
(exact file name, optional).

**Response 200:**
```json
{"entries": [{"at": "…Z", "act": "added|replaced|removed|set_aside|narrowed|restored|reset",
              "name": "…", "size": 6387, "content_hash": "sha256:<64 hex>", "by": "person",
              "why": null | "…", "say": "Brought in", "batch": null | "b_…", "removed_id": null | "rm_…",
              "conflict": null | "cfl_…", "test_article": null | "PFHxSAm"}],
 "next": null | "<cursor>", "count": 27}
```
**Errors:** 404 `study_not_found`. A study with no record yet answers
`{"entries": [], "next": null, "count": 0}`. The files of a study from before C8
are not recorded until they are next touched; the panel then says "Recorded since
{date}".

**On disk (C8 item 9):** `records/files.jsonl`, one JSON object per line, with the
fields of `entries[]` minus `say`. Append-only; written by the step that does the
act, in the same call; never rewritten; deleted only with the study (M1).

### 2.16 The record of combined datasets (C12; read by M3, not by M2)

M2 reads only `FilesView.records.datasets`. The shape is given here so the dry
runs can name it, and so M3 can build on it.

**On disk:**
- `records/datasets.jsonl`, one line per integration (written by `integrate_step`):
  ```json
  {"n": 1, "at": "2026-10-16T15:38:50Z", "basis": "bcd8369e4b546e81",
   "files": [{"name": "Hormones.bm2", "content_hash": "sha256:dd8c150a…"}, "…"],
   "dataset": {"sha256": "sha256:7f22c501…", "size": 137752,
               "experiments": ["hormones_truth_female", "hormones_truth_male"], "bmd_results": 2,
               "imputed_cells": {"Hormones": {"Male": {"12.0": 1}}}},
   "processed": false, "copy": null | {"path": "records/datasets/1.integrated.json.gz", "size": 22831, "kept_at": "…Z", "why": "replaced|deleted|reset"}}
  ```
- `records/datasets/<n>.integrated.json.gz`: written when that dataset is about to
  be deleted or replaced, if Process ran on it (`processed`, set by C5's run
  record) **[maintainer Q-M2-13]**. gzip level 1:
  - NIEHS-10: 77 MB → 9.4 MB in 0.32 s;
  - the largest, 169 MB → 20.5 MB in 0.71 s [V].

The read route (`GET …/datasets`) belongs to M3's contract.

---

## 3. Refusal codes

Statuses and `say` are in `spec.md` §6. New codes for `workflow/refusals.py`:
- `takes_no_files`;
- `file_type_refused`, `sidecar_refused`, `empty_file`, `name_invalid`,
  `duplicate_name_in_batch`;
- `content_mismatch`, `zip_invalid`, `zip_nested`, `zip_name_clash`;
- `units_without_table`, `units_invalid`, `units_for_converted_file`;
- `answer_required`, `staging_expired`, `files_changed`;
- `file_not_found`, `companion_not_removable`, `removed_not_found`,
  `restore_name_taken`;
- `classification_not_allowed`, `classification_unconfirmed` (raised by integrate;
  Q-M2-4);
- `conflict_not_found`, `conflict_choice_invalid`, `conflict_settled_outside`;
- `narrow_choice_invalid`, `narrow_not_needed`.

Dropped by the answers: `file_too_large` (Q-M2-8) and `same_content` as a refusal
(Q-M2-9; it is now an intake verdict and an issue type).

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
| "SubsetBm2 failed (exit …)" / "no experiment matches" (`subset_bm2`) | `server_setup_failed` / `narrow_choice_invalid` |

---

## 4. Fixtures

**Real** = built from real files, a real `validation_report.json` and the
sidecars:
- by `docs/ui-redesign/contracts/m2/_generator.py`;
- then by `/workspace/ui-team/_scratch/m2-design/fixtures/_revise.py` (the
  2026-10-16 revision, which reads the earlier fixtures read-only).

**Projected** = depends on C3/C4/C8/C12/core, and is built from real files with the
projected shape.

All revised fixtures are in `/workspace/ui-team/_scratch/m2-design/fixtures/`, for
the orchestrator to copy to `ui/src/api/mocks/fixtures/m2/` (they replace the
2026-10-15 set). Test data sets:
- T1–T6: `/workspace/ui-team/_scratch/design-m2/testdata/`;
- T7–T9: `/workspace/ui-team/_scratch/m2-design/testdata/`.

| Fixture | From | Phase | What it shows |
|---|---|---|---|
| `files.DTXSID50469320.json` | the real `sessions/DTXSID50469320` (NIEHS-10) | APPROVED | 15 rows (13 converted CSVs with units, 2 clinical-observation CSVs, the genomic `.bm2`); 32 issues (25 expected, 7 worth a look, 0 to fix); 8 method checks not shown; `integration` present. Real |
| `files.uploaded.json` | T1 brought in, not checked | UPLOADED | 15 rows "not checked", units paired, classify not allowed with its reason; next = VALIDATE. Real files; the row model is projected [C4] |
| `files.conflicts.json` | T4 checked | VALIDATION_ERRORS | 2 conflicts: Hormones females 1.4 vs 2 (`settle: here`), and a body-weight pivot copy (`redundant_files`, `settle: outside`, with the three steps); progress "Conflicts: 1 to choose here, 1 to fix outside the app". Real check; the settle kinds projected [core] |
| `files.copies.json` | T8: T1's `body_weight_truth_female.csv` and its exact copy `body_weight_truth_female_2.csv`, checked | VALIDATED today (projected: VALIDATION_ERRORS) | one `same_content` conflict, `settle: outside`, `next.act` null. Real check (today `redundant_files`, info; the verbatim message is kept in `message`); the type and blocking projected [core] |
| `files.value_mismatch.json` | T5 checked | VALIDATION_ERRORS | `value_mismatch` "1 of 243 … workbook 215.9, table 251.9". Real |
| `files.given2026.json` | T2 checked | VALIDATED | 20 rows: 6 `.bm2` with "[contents not read]", 10 apical BMDExpress input tables as gap-filled, 4 expression matrices; 13 expected issues. Real |
| `files.cebs_workbooks.json` | T3 checked | VALIDATED (projected: VALIDATION_ERRORS) | 7 workbooks with their Key-sheet units (real, `key_sheet_units`), the shared `.bm2` with the must-fix `several_test_articles` issue and its 4 `narrow_choices`; the coverage rows of the workbook-only platforms warning "Only the study workbook". Real files and units; the issue and the narrowing projected [core] |
| `files.imputed.json` | T7 brought in, checked and combined on scratch (`DTXSID9000007`) | INTEGRATED | 3 rows. `Hormones.bm2` carries `bm2_changes.imputed` (males, dose group 12: 1 value), `footnoted: true`, and the footnote text the clinical-pathology table builder printed from T7's sidecars. `integration` is current. Real dataset, real imputed cells (as read), real footnote; `bm2_changes` at the check projected [core] |
| `records.files.DTXSID9000007.json` | T7 | – | 5 "added" entries, with full sha256 hashes and sizes. Real names, sizes and hashes; the shape projected [C8] |
| `records.datasets.DTXSID9000007.json` | T7 | – | one dataset line: basis `bcd8369e4b546e81`, dataset sha256 `7f22c501…`, 137,752 bytes, 2 experiments, 2 BMD results, the imputed cells; `gzip_size_if_kept` 22,831. Real values; the shape projected [C12] |

### 4.1 `GET …/files`, the conflicts of `files.conflicts.json` (real check; `settle` projected [core])
```json
{"progress": [{"step": "bring_in", "status": "done", "say": "5 file(s) in the study"},
              {"step": "check", "status": "blocked", "say": "Checked 2026-10-15: 2 problem(s) to fix"},
              {"step": "confirm", "status": "todo", "say": "5 of 5 file(s) not yet confirmed"},
              {"step": "conflicts", "status": "todo", "say": "Conflicts: 1 to choose here, 1 to fix outside the app"}],
 "conflicts": [
  {"id": "cfl_c2caee9b6e", "issue": "iss_c2caee9b6e", "type": "dose_mismatch", "settle": "here",
   "platform": "Hormones", "data_type": "tox_study",
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
   "suggested": null, "outside": null, "acts": {"keep": {"allowed": true, "code": null, "say": null}}},
  {"id": "cfl_0ed5998d68", "issue": "iss_0ed5998d68", "type": "redundant_files", "settle": "outside",
   "platform": "Body Weight", "data_type": null,
   "say": "body_weight_truth_female_copy.txt and body_weight_truth_female.csv hold the same data (same platform, sex, doses, measurements and animals). Both would be combined, so it would count twice.",
   "files": [{"name": "body_weight_truth_female_copy.txt", "kind": "table", "size": 1722, "…": "…"},
             {"name": "body_weight_truth_female.csv", "kind": "table", "size": 6387, "…": "…"}],
   "differences": [], "suggested": null,
   "outside": {"say": "The tool can't tell which of these is the study's, and this is not chosen in the app. Settle it outside the app.",
               "steps": ["Open both files on your computer and decide which one is this study's, or correct them.",
                         "Here, remove the one that does not belong (its row's Remove…), or bring in the corrected file under the same name: it replaces the old one, which is kept among the removed files.",
                         "Check the files again."]},
   "acts": null}]}
```

### 4.2 The exact copy of `files.copies.json` (real check on T8; type and blocking projected [core])
```json
{"next": {"act": null, "say": "Settle the copy outside the app, then check the files again", "fix": "M2"},
 "issues": [{"id": "iss_23005c97d7", "type": "same_content", "severity": "error", "group": "fix", "settle": "outside",
   "platform": "Body Weight", "files": ["body_weight_truth_female_2.csv", "body_weight_truth_female.csv"],
   "tables": ["body_weight_truth_female_2.txt", "body_weight_truth_female.txt"],
   "say": "body_weight_truth_female_2.csv is an exact copy of body_weight_truth_female.csv (same content). Both would be combined, so the data would count twice.",
   "what_to_do": "Settle it outside the app: decide which file is the study's, then remove the other here or bring in a corrected file.",
   "feeds": null, "fix": "M2",
   "message": "(today: redundant_files, info) body_weight_truth_female_2.txt and body_weight_truth_female.txt appear to contain the same data (same platform, sexes, doses, endpoints)",
   "details": {"content_hash": "sha256:12c09dc24d6b2706"}}]}
```
Today this study reads VALIDATED and could be combined, with the data counted
twice [V].

### 4.3 A `FileRow` of `files.DTXSID50469320.json` (real)
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
 "bm2": null, "bm2_changes": null, "narrow_choices": null, "study_number": null, "checked": true,
 "classification": {"platform": "Body Weight", "data_type": "tox_study", "say": "Body Weight · the study's own measurements",
   "detected": {"platform": "Body Weight", "data_type": "tox_study", "basis": "file_name", "say": "From the file name"},
   "stated": null, "status": "unconfirmed", "flags": []},
 "issues": ["iss_9806f3fd4a", "iss_85742f13aa", "iss_e14d185915"], "pending": [],
 "acts": {"remove": {"allowed": true, "code": null, "say": null}, "classify": {"allowed": true, "code": null, "say": null}, "narrow": null}}
```
And its `roster_subset` issue (real):
```json
{"id": "iss_9806f3fd4a", "type": "roster_subset", "severity": "info", "group": "expected", "settle": null, "platform": "Body Weight",
 "files": ["body_weight_truth_female.csv"], "tables": ["body_weight_truth_female.txt"],
 "say": "6 of the 61 female animals in the study's roster are not in body_weight_truth_female.csv, for example 544, 545, 546, 550, 552. Animals that died early or were kept for blood sampling are often missing from some measurements; the data review accounts for each one.",
 "what_to_do": null, "feeds": "M6", "fix": null,
 "message": "body_weight_truth_female.txt (Female): 55/61 animals — missing 6 (544, 545, 546, 550, 552)",
 "details": {"sex": "Female", "file_count": 55, "roster_count": 61, "missing_count": 6}}
```

### 4.4 The shared `.bm2` row and its issue in `files.cebs_workbooks.json` (real files and experiments; issue and narrowing projected [core])
```json
{"name": "C20022-01_EPA_PFAS_Kidney_Overflow_plate_removed_S1500_Plus_Analysis_Traditional.bm2", "kind": "bm2", "size": 40485229,
 "bm2": {"experiments": ["Kidney_2,3-Benzofluorene_Female", "…16 in all…", "Liver_PFHxSAm_Male"], "species": "Rattus norvegicus",
         "test_articles": ["10-2 FTOH", "2,3-Benzofluorene", "6-1 FTOH", "PFHxSAm"]},
 "narrow_choices": [
   {"test_article": "10-2 FTOH", "experiments": ["Kidney_10-2 FTOH_Female", "Kidney_10-2 FTOH_Male", "Liver_10-2 FTOH_Female", "Liver_10-2 FTOH_Male"], "matches_short_name": false},
   {"test_article": "2,3-Benzofluorene", "experiments": ["Kidney_2,3-Benzofluorene_Female", "…"], "matches_short_name": false},
   {"test_article": "6-1 FTOH", "experiments": ["Kidney_6-1 FTOH_Female", "…"], "matches_short_name": false},
   {"test_article": "PFHxSAm", "experiments": ["Kidney_PFHxSAm_Female", "Kidney_PFHxSAm_Male", "Liver_PFHxSAm_Female", "Liver_PFHxSAm_Male"], "matches_short_name": true}],
 "classification": {"platform": null, "data_type": "gene_expression", "say": "Gene expression · gene-expression data",
   "detected": {"basis": "bm2_experiments", "say": "From the experiment names inside the BMDExpress project"}, "status": "unconfirmed",
   "flags": []},
 "acts": {"remove": {"allowed": true, "code": null, "say": null}, "classify": {"allowed": true, "code": null, "say": null},
          "narrow": {"allowed": true, "code": null, "say": null}}}
```
```json
{"id": "iss_022ec399d3", "type": "several_test_articles", "severity": "error", "group": "fix", "settle": "narrow",
 "platform": null, "data_type": "gene_expression",
 "files": ["C20022-01_EPA_PFAS_Kidney_Overflow_plate_removed_S1500_Plus_Analysis_Traditional.bm2"],
 "say": "This BMDExpress project holds experiments of 4 test articles (10-2 FTOH, 2,3-Benzofluorene, 6-1 FTOH, PFHxSAm), read from its experiment names. Combined as it is, all of them would enter this study's dataset.",
 "what_to_do": "Keep only this study's experiments (in the file's row).", "feeds": null, "fix": "M2",
 "message": "(NEW issue type; today the check does not raise it)",
 "details": {"test_articles": ["10-2 FTOH", "2,3-Benzofluorene", "6-1 FTOH", "PFHxSAm"], "basis": "experiment_names"}}
```
- `test_articles` is read from experiment names of the form
  `<Organ>_<article>_<Sex>[_No0]`. It is an inference, and empty when the names
  don't follow that form (as in RR-8's `TPHP mg_kg`).
- `matches_short_name` compares with the study's short name (M1/M4). It is
  `false` while the short name is pending.

A workbook row of the same fixture, with units from the Key sheet (real,
`key_sheet_units`):
```json
{"name": "C20022-01_Individual_Animal_Hormone_Data.xlsx", "kind": "workbook",
 "units": {"state": "stated", "values": {"Free Thyroxine": "ng/dL", "Thyroid Stimulating Hormone": "ng/ml", "Total Thyroxine": "ug/dL", "Triiodothyronine": "ng/dL"},
           "say": "4 unit(s), from the workbook's Key sheet"}}
```

### 4.5 The `.bm2` row of `files.imputed.json` (T7; real dataset and footnote, check-time shape projected [core; maintainer: confirm])
```json
{"name": "Hormones.bm2", "kind": "bm2", "size": 31108, "content_hash": "sha256:dd8c150a40878a3b",
 "bm2": {"experiments": ["female_hormone_data", "male_hormone_data"], "species": null, "test_articles": []},
 "bm2_changes": {
   "imputed": {"cells": [{"platform": "Hormones", "sex": "Male", "dose": 12.0, "count": 1}], "total": 1,
               "pairs_with": ["hormones_truth_male.csv"],
               "say": "This BMDExpress project fills 1 value that hormones_truth_male.csv leaves missing (males, dose group 12: 1 value). BMDExpress needs complete data, so a missing value is filled with its dose group's mean. This is expected.",
               "footnoted": true,
               "footnote": "Benchmark dose modeling used an inferred dataset in which 1 missing individual value was replaced with the dose-group mean (affected dose group: 12 mg/kg).",
               "basis": "the rule of pipeline.bmd_project_schema._detect_imputed_cells (ADR-0017)", "confirm": "maintainer"},
   "dose_groups_left_out": [], "aligned": true},
 "classification": {"platform": "Hormones", "data_type": "inferred", "say": "Hormones · gap-filled values prepared for BMD modelling",
   "detected": {"platform": "Hormones", "data_type": "inferred", "basis": "bm2_experiments", "say": "From the experiment names inside the BMDExpress project"},
   "stated": null, "status": "unconfirmed", "flags": []}}
```
How T7 was made: T1's `hormones_truth_male.csv` with male 161's Free Thyroxine
(dose 12, 7.23) left empty, beside the 2026 package's `Hormones.bm2`. The check
raised no error. The dataset as read gives `imputed_cells`
`{Hormones: {Male: {12.0: 1}}}`; on disk it is absent [V].

### 4.6 `POST …/files/staging` with T6, T1 and T8 files, into the T1 study (projected [C8]; real names, sizes, hashes and first bytes)
```json
{"batch": "b_20261016T141203Z_7f3a", "expires_at": "2026-10-16T15:12:03Z",
 "rows": [
  {"name": "body_weight_truth_female.csv", "size": 6387, "content_hash": "sha256:564724cca188818a", "detected_type": "csv",
   "verdict": "replace", "needs_answer": "replace",
   "replaces": {"name": "body_weight_truth_female.csv", "size": 6387, "added_at": "2026-10-12T11:37:20Z", "content_hash": "sha256:12c09dc24d6b2706"},
   "say": "Replaces body_weight_truth_female.csv already in the study (added 12 Oct 2026, 6,387 bytes; this one 6,387 bytes, different content). The old one will be kept among the removed files, where it can be restored."},
  {"name": "body_weight_truth_female.units.json", "size": 29, "content_hash": "sha256:09936eaa107ce8dd", "detected_type": "units",
   "verdict": "unchanged", "say": "Already in the study, unchanged (same name, same content). Not brought in again."},
  {"name": "body_weight_truth_female_2.csv", "size": 6387, "content_hash": "sha256:12c09dc24d6b2706", "detected_type": "csv",
   "verdict": "copy", "needs_answer": "copy", "copy_of": {"name": "body_weight_truth_female.csv", "where": "study"},
   "say": "This is an exact copy of body_weight_truth_female.csv, already in the study, under another name. Both would be combined, so the data would count twice. If you bring it in, the check will block combining until you settle it outside the app."},
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
   "say": "Will be added. Its name doesn't say what it is; the check will ask."}],
 "counts": {"add": 1, "unchanged": 1, "refused": 3, "needs_answer": 3},
 "dry_run": null, "plan_token": "sha256:…"}
```
- The `.pdf`, `.docx`, `.sidecar.json` and empty file of T6 never reach this call:
  the browser refuses them (spec §4). Sent anyway, they are rows with
  `file_type_refused`, `sidecar_refused` and `empty_file`.
- `dry_run` is shown null for brevity; on the checked T1 study it is the
  `add_files` object of §4.8.

### 4.7 `GET …/dry-run/remove_file?file=body_weight_truth_female.csv` on a checked study (projected [C8])
```json
{"confirm": {"act": "remove_file", "strength": "costly",
  "deletes": [{"what": "validation_report.json", "say": "the result of the last file check"}],
  "keeps": [{"what": "_removed/", "say": "the file, its units file, its table and its sidecar, among the removed files; they can be restored"},
            {"what": "records/files.jsonl", "say": "the record of the files, with this removal"}],
  "approvals_lost": [], "cost": {"say": "checking the files again (a few seconds)"}, "reason_required": false},
 "type_to_confirm": null, "preview_token": "sha256:…"}
```

### 4.8 The `add_files` dry run inside a plan, on a copy of NIEHS-10 (APPROVED) (projected [C8, C12]; lists from the real session and `invalidate_pool_artifacts`)
```json
{"act": "add_files", "strength": "costly",
 "deletes": [
  {"what": "validation_report.json", "say": "the result of the last file check"},
  {"what": "integrated.json", "say": "the combined dataset (77 MB); a compressed copy (about 9.4 MB) is kept in the dataset record, because it was processed"},
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
  {"what": "records/", "say": "the record of the files and of the combined datasets"},
  {"what": "history/", "say": "past versions"}],
 "approvals_lost": [],
 "cost": {"say": "checking the files again, combining them again (about 25 s), and processing again (about 3 minutes, the BMD modelling reused)"},
 "reason_required": false}
```
`approvals_lost` is empty because no section of the real session is approved
(checked); a copy with approved sections lists their keys. The 9.4 MB is the
measured gzip (level 1) size of the real 77 MB `integrated.json` [V].

### 4.9 `GET …/dry-run/reset_files` on a copy of NIEHS-10 (projected [C8, C12]; lists from `session_routes.py:1340-1491`, changed, and the real session)
```json
{"confirm": {"act": "reset_files", "strength": "irreversible",
  "deletes": [
   {"what": "integrated.json, integrated.bm2", "say": "the combined dataset; a compressed copy (about 9.4 MB) is kept in the dataset record"},
   {"what": "validation_report.json, _fingerprints.json, _category_lookup.json, genomics.sidecar.json", "say": "the file check and what was read from the files"},
   {"what": "animal_report.json", "say": "the data review"},
   {"what": "bm2_*.json (7 files)", "say": "the apical result sections (archived in history)"},
   {"what": "summary.json", "say": "the Summary (archived in history)"},
   {"what": "_cache_*.json (12 files), session.duckdb, session_parquet/", "say": "the stored results of processing"}],
  "moves": [
   {"what": "files/ (15 files and their tables), _originals/ (24 files)", "say": "every data file brought into the study, to the removed files, where each can be restored"}],
  "keeps": [
   {"what": "identity.json", "say": "the chemical's name and identifiers"},
   {"what": "study_design.json, front_matter.json, deposit.json", "say": "the study design, the authors and the deposit record: they will apply again to the next files"},
   {"what": "method_profile.json", "say": "the method pin"},
   {"what": "background.json", "say": "the Background"},
   {"what": "_removed/", "say": "the removed files, with those moved now"},
   {"what": "records/", "say": "the record of the files and of the combined datasets"},
   {"what": "history/", "say": "past versions"}],
  "approvals_lost": [], "cost": {"say": "bringing the files in again (or restoring them), checking, combining and a full Process"}, "reason_required": false},
 "type_to_confirm": "DTXSID50469320", "preview_token": "sha256:…"}
```
`moves` is a new, optional list in the §4.3 object, for acts that move rather than
delete. The kit's `<ConfirmAct>` shows it between "deletes" and "keeps"
**[request R-M2-4]**. It holds the current files under Q-M2-12's proposal.

### 4.10 `GET …/dry-run/narrow?file=C20022-01_…Traditional.bm2&test_article=PFHxSAm` (projected [core, C8]; sizes from a real `subset_bm2` run)
```json
{"confirm": {"act": "narrow", "strength": "costly",
  "deletes": [{"what": "validation_report.json", "say": "the result of the last file check"}],
  "moves": [{"what": "C20022-01_EPA_PFAS_Kidney_Overflow_plate_removed_S1500_Plus_Analysis_Traditional.bm2 (40.5 MB, 16 experiments)",
             "say": "the original, to the removed files, where it can be restored"}],
  "keeps": [{"what": "files/", "say": "a copy under the same name holding only PFHxSAm's 4 experiments and their analyses (about 8.2 MB)"}],
  "approvals_lost": [], "cost": {"say": "a few seconds, then checking the files again"}, "reason_required": false},
 "type_to_confirm": null, "preview_token": "sha256:…"}
```

### 4.11 `GET …/files/record` for the T7 study (projected [C8]; real names, sizes and hashes)
```json
{"entries": [
  {"at": "2026-10-16T15:38:20Z", "act": "added", "name": "hormones_truth_male.units.json", "size": 135,
   "content_hash": "sha256:514130439214db34f8c69abbf0a3c618143b74535b21adef8c4b76faca225de5", "by": "person", "why": null,
   "say": "Brought in", "batch": "b_20261016T153810Z_51c2", "removed_id": null, "conflict": null, "test_article": null},
  {"at": "2026-10-16T15:38:20Z", "act": "added", "name": "hormones_truth_male.csv", "size": 1718,
   "content_hash": "sha256:a74606d5ef5b868ffb9001bfebf8cb140165b25bc3a6347dba911ed318ca1320", "by": "person", "why": null,
   "say": "Brought in", "batch": "b_20261016T153810Z_51c2", "removed_id": null, "conflict": null, "test_article": null},
  {"…": "3 more: hormones_truth_female.units.json (135), hormones_truth_female.csv (2046, sha256:98f9c8c1…), Hormones.bm2 (31108, sha256:dd8c150a…)"}],
 "next": null, "count": 5}
```
The dataset line of the same study is in `records.datasets.DTXSID9000007.json` (the
§2.16 shape, real values).

### 4.12 Refusals (§4.2 envelope)
```json
{"error": {"code": "restore_name_taken", "status": 409,
           "message": "RESTORE refused for DTXSID9000004: body_weight_truth_female.csv is in files/",
           "say": "A file named body_weight_truth_female.csv is in the study now. Remove it first, then restore.",
           "fix": "M2", "details": {"name": "body_weight_truth_female.csv", "removed_id": "rm_20261015T122035000598Z"}}}
```
```json
{"error": {"code": "conflict_settled_outside", "status": 409,
           "message": "KEEP refused for DTXSID9000004: conflict cfl_0ed5998d68 is redundant_files (settled outside the app)",
           "say": "The app does not choose between these files: they hold the same data, and only you can tell which one is the study's. Fix or remove one outside the app, then check the files again.",
           "fix": "M2", "details": {"conflict": "cfl_0ed5998d68", "type": "redundant_files"}}}
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
  and conflict ids; content hashes.
- **C3:** spec §10 items 1–7:
  - `classifications.json`;
  - the vocabulary check;
  - the integration basis;
  - `check.current`;
  - `classification_unconfirmed` at integrate.

  Conflict decisions as state are retired, and so is `precedence.json`.
- **C8:** spec §10 items 1–9:
  - staging, streamed with no size limit;
  - dry runs (with `narrow` and the optional `moves` list) and tokens;
  - removal with all companions;
  - restore in every phase;
  - an archived replacement and an archived data approval;
  - the reset moved to the core, **keeping `_removed/` and `records/`**;
  - `records/files.jsonl` and `GET …/files/record`.
- **C12 (NEW, proposed):** spec §10. `records/datasets.jsonl` and kept copies of
  processed datasets. `integrate_step` writes the record, the invalidation steps
  keep the copies, and C5's run record names the dataset it ran on. M3 owns the
  read route.
- **C1:** with C3, `classification_unconfirmed` at integrate (Q-M2-4).
- **Core track** (bmdx-pipe / `workflow` / `pipeline` / `tables`):
  - the completeness rule (Q-M2-3);
  - `redundant_files` blocking and `same_content`, both `settle: outside`
    (Q-M2-2, Q-M2-9);
  - `several_test_articles` and `narrow_bm2_step` over `subset_bm2` (Q-M2-5);
  - content-based classification (Q-M2-6);
  - workbook units from the Key sheet (Q-M2-7 b);
  - `.bm2` always read at the check, and a bm2 cache that holds a 251 MB project
    (today `MDB_MAP_FULL` [V]);
  - conversion at the check;
  - **the imputation rule at the check** (spec §10 a–d: at the check; aligned by
    animal; paired by classification, not the `_truth_` name; the footnote for
    every apical table), with `bm2_value_mismatch` and
    `bm2_dose_groups_left_out` [maintainer: confirm];
  - **a table with empty cells must not be silently left out of the dataset**
    (spec §8 [V]).
- **Kit/shell:** spec §9 R-M2-1 … R-M2-11.
