# C3 — Saves merge and check: contract

Against the shared error envelope (MODULES §4.2):
`{"error": {"code", "status", "message", "say", "fix", "details"}}`.
Old routes keep their `{"error": "<message>", "code": "<code>"}` shape
(`session_routes._step_refusal`); new routes use the envelope. A success that changes
nothing carries `"noop": {"code", "say"}`. `{…}` are filled in from the request. Every
claim is marked [V] or [R] as in spec.md; refusals not yet built are specified, not
verified.

## 1. Refusals C3 adds or takes over

All are raised by `StatementRefusal(StepError)` with their `code`, from the core steps,
so every driver (route, command line, notebook) meets them.

| code | status | message (verbatim) | say | fix | raised by |
|---|---|---|---|---|---|
| `file_not_found` (M2's) | 404 | `"No file {name!r} in {dtxsid}"` | "There is no file {name} in this study. It may have been removed in another tab." | M2 | classify, unclassify, confirm-as-shown, old confirm route (today: skipped, `updated: 0` [V]) |
| `classification_not_allowed` (M2's) | 400 | `"{name}: {field}={value!r} is not allowed for a {kind}"` | "{value} is not a {field} the tool knows." / "A BMDExpress project can't be 'the study's own measurements'." | M2 | classify (today: "Banana"/"Kiwi" accepted [V]) |
| `classification_collides` | 409 | `"{name} as {platform}/{data_type} would cover the same {platform} {sex} data as {other}"` | "{other} is already {platform} data for {sex} animals. Two tables of the same measurements for the same sex can't be combined: one of them is wrong, or both belong to another study. Correct the other file first, or remove one." | M2 | classify (today: integration fails at the schema [V]) |
| `classification_unconfirmed` (M2's) | 409 | `"INTEGRATE refused for {dtxsid}: {n} file(s) not confirmed: {names}"` | "{n} files haven't been confirmed: {names}. Say what each one is first." | M2 | integrate (D1) |
| `validation_out_of_date` (C1's) | 409 | C1's text, with `{DETAIL}` = `classification of {names} changed since the check` | C1's say | M2 | INTEGRATE while the check is out of date; `details.why: "classification_changed"`, `details.files` |
| `conflict_choice_retired` | 410 | `"Conflict choices are no longer recorded; keep one file of the conflict instead"` | "Choosing a file this way is no longer done. Open the conflict and keep one file: the other is set aside and can be restored." | M2 | `resolve_step`, `POST /api/pool/resolve` (D2) |
| `not_integrated` (existing) | 400 | `"No integrated data found"` | existing | M3 | experiment metadata, design (today 404 from `LookupError` on HTTP) |
| `empty_statement` | 400 | `"Nothing to state"` | "Nothing was given to save." | – | every statement step (today "No metadata provided") |
| `statement_invalid` | 400 | `"{what} must be an object of field: value"` | "This was not sent in a form the tool can read. This is a fault in the interface; tell the maintainer." | – | every statement step (today: 500 and a broken cache [V]) |
| `experiment_not_found` | 404 | `"No experiment(s) {names} in {dtxsid}"` | "The dataset has no experiment named {names}. The list may be out of date: the files were combined again." | M3 | experiment metadata (today: ignored, 200 [V]) |
| `statement_field_unknown` | 400 | `"{field!r} is not a field that can be stated here; use {allowed}"` | "{label} can't be stated here." For `testArticle`: "The chemical is the study's identity; it is set on the study's page." | M3 / M4 | experiment metadata, design |
| `value_not_in_vocabulary` | 400 | `"{field}={value!r} is not in the vocabulary"` | "{value} is not a {label} the tool knows. Choose one from the list." | M3 / M4 | experiment metadata, design (today unchecked on HTTP [V]) |
| `strain_not_of_species` | 400 | `"strain={strain!r} is not a {species} strain"` | "{strain} is not a strain of {species}." | M3 / M4 | experiment metadata, design (today accepted [V]) |
| `design_incoherent` | 400 | `"articleRoute={route!r} does not allow {field}={value!r}"` | "A study by {route say} can't be given {value}. {what fits}." | M4 | design (D4; today accepted [V]) |
| `stated_on_the_file` | 409 | `"{experiment}: {field} comes from the classification of its file"` | "An apical experiment's platform and data type are those of its file. Correct what the file is instead." | M2 | experiment metadata |
| `experiment_contradicts_design` | 409 | `"{experiment}: {field}={value!r} differs from the study design ({design!r})"` | "The study design says {design} for every experiment. Change the study design instead, or leave this field out." | M4 | experiment metadata |
| `front_matter_invalid` | 400 | `"front matter: {problems}"` | "Some of the report details can't be saved: {problems say}. Nothing was saved." | D5 | front matter (today: silently dropped or coerced [V]) |
| `short_name_invalid` | 400 | `"short name must be 1-40 characters on one line"` | "The short name must be a few characters on one line, like PFHxSAm." | M4 | short name |
| `identity_not_changed_here` | 409 | `"INTEGRATE refused for {dtxsid}: the request's identity differs from identity.json ({fields}); identity is not written by integration"` | "Combining the files never changes the chemical's identity. The study's page holds it." | M1 | `POST /api/pool/integrate` (today: overwrites [V]) |
| `identity_exists` (M1's) | 409 | M1's | M1's | M1 | CLI `--name`/`--casrn` on a study with another identity (D3) |
| `study_not_found` (M1's) | 404 | M1's | M1's | M1 | front matter, short name on an absent study (today: 200 and a folder [V]) |
| `read_only_session` (M1's) | 409 | M1's | M1's | – | every statement step on a companion |
| `changed_since_preview` (M1's) | 409 | M1's | M1's | – | classify on a combined study (costly; C8's dry run) |
| `files_changed` (M2's) | 409 | M2's | M2's | M2 | confirm-as-shown |
| `phase_not_allowed` (C1's) | 409 | C1's | C1's | per C1 | STATE_DATASET_FACTS (design, experiment metadata), CONFIRM_CLASSIFICATION |

`front_matter_invalid.details.problems`: `[{"field": "publication.doi", "value": "not-a-doi",
"say": "A DOI starts with “10.”, then the registrant, a slash and the rest."}]`.

**No-ops** (200 with `noop`):

| code | say | from |
|---|---|---|
| `already_stated` | "That is already what is stated. Nothing changed." | every statement step |
| `nothing_stated` (M2's) | "This file has no statement to undo." | unclassify |

## 2. Routes

### 2.1 Existing routes whose response changes

| Route | Change |
|---|---|
| `POST /api/experiment-metadata/{id}` | merges per field (`null` withdraws); checked (§1); refuses unknown experiments; the record accumulates; on a refusal, nothing changes on disk or in memory. Success body `{ok, updated, bm2_exported}` unchanged, plus `noop` when nothing changed |
| `GET /api/experiment-metadata/{id}` | each experiment gains `stated: {field: {value, at, via, legacy}}`; `approved` stays (true when any statement exists) |
| `POST /api/document/{id}/front-matter` | merges by key (`publication` by field); checked; 404 `study_not_found` with no folder created; success body `{ok, front_matter}` unchanged |
| `POST /api/pool/confirm-metadata/{id}` | keys of `metadata` may be file ids or names (ids mapped through the record); unknown → 404 `file_not_found`; values checked; writes `classifications.json`, no header, no `_fingerprints.json`. Body `{ok, updated}` where `updated` counts statements written |
| `POST /api/pool/resolve` | 410 `conflict_choice_retired` (D2) |
| `POST /api/pool/integrate/{id}` | body `identity` accepted only when equal to the recorded fields (then ignored); else 409 `identity_not_changed_here`. New refusals `classification_unconfirmed` (D1) and `validation_out_of_date` (`why: classification_changed`). Writes no `identity.json` |
| `GET /api/workflow/{id}/state`, `GET /api/v2/studies/{id}/state` | `artifacts.check: "current" \| "out_of_date" \| null` (+ `check_out_of_date_files`); INTEGRATE absent from `legal_actions` while the check is out of date; `integration` reads `out_of_date` when the basis inputs (classifications, identity) changed; `stands.next` = VALIDATE then |
| `GET /api/wizard/{id}/fingerprints` | `platform`/`data_type` are the effective values (stated over detected); each row adds `stated: bool` |
| `GET /api/session/{id}` | `precedence` is null for every new session |

### 2.2 New routes (`web_routes/v2_statement_routes.py`; registration by the orchestrator)

The classification routes are M2's (contract §2.6–2.8), built on C3's core. The others are
proposed by C3 for M3, M4 and D5, which may restyle them in their specs. All thin: parse →
step → serialize. Every response carries the saved statement with its provenance.

| Route | Body | 200 | Refusals |
|---|---|---|---|
| `PUT /api/v2/studies/{id}/files/{name}/classification` | `{platform, data_type, preview_token?}` | M2 §2.6 | `file_not_found`, `classification_not_allowed`, `classification_collides`, `changed_since_preview`, `phase_not_allowed` |
| `DELETE /api/v2/studies/{id}/files/{name}/classification` | – | M2 §2.7 | `file_not_found`, `noop nothing_stated` |
| `POST /api/v2/studies/{id}/files/classification/confirm` | M2 §2.8 | M2 §2.8 | `files_changed`, `classification_not_allowed`, `classification_collides` |
| `GET /api/v2/studies/{id}/statements` | – | `{classifications, design, experiments, front_matter, short_name}`, each field `{value, stated_at, via, user, legacy?}`; plus `check {current, why, files}` | `study_not_found` |
| `PATCH /api/v2/studies/{id}/design` | `{fields: {field: value \| null}}` | `{fields, stated, applied_to: n, withdrawn: [{field, until: "next integration"}], noop?}` | `not_integrated`, `statement_field_unknown`, `value_not_in_vocabulary`, `strain_not_of_species`, `design_incoherent`, `phase_not_allowed` |
| `PATCH /api/v2/studies/{id}/experiments/metadata` | `{experiments: {name: {field: value \| null}}}` | `{updated: [names], bm2_exported, noop?}` | `not_integrated`, `experiment_not_found`, `statement_field_unknown`, `value_not_in_vocabulary`, `strain_not_of_species`, `stated_on_the_file`, `experiment_contradicts_design`, `phase_not_allowed` |
| `PATCH /api/v2/studies/{id}/front-matter` | `{authors?, contributors?, collaborators?, publication?, strain_designation?}` (each `null` to withdraw) | `{front_matter, stated, noop?}` | `study_not_found`, `read_only_session`, `front_matter_invalid` |
| `PUT /api/v2/studies/{id}/short-name` | `{short_name: "PFHxSAm" \| null}` | `{short_name, stated_at, noop?}` | `study_not_found`, `read_only_session`, `short_name_invalid` |

`GET /api/v2/vocabularies` adds (D4) `articleVehicle` and `administrationMeans` as
`{depends_on: "articleRoute", by: {...}}`, and `classification_choices` per kind of file.

### 2.3 Command line

- `--design`, `--experiment-metadata`, `--front-matter`, `--compound-name` and
  `--metadata` call the same steps.
- On a refusal the command line prints `step failed ({status}): {message}`, then the
  `say` (C1's form).
- `--name`/`--casrn` follow D3.
- New: `--accept-detected-classifications` (D1).

## 3. Files on disk

| File | Change |
|---|---|
| `classifications.json` | **NEW.** `{"version": 1, "files": {<brought-in name>: {platform, data_type, detected: {platform, data_type, basis}, content_hash, stated_at, via, user, accepted_detected, units_missing_acknowledged_at}}}`. Deleted by the pool reset; kept by invalidation; moved into `_removed/<stamp>/removed.json` with its file (C8) |
| `metadata_approved.json` | **CHANGED (v2)**: `{"version": 2, "experiments": {name: {"fields": {…}, "stated": {field: {at, via, user}}}}, "legacy": {"approved_at", "metadata"}?}`. A v1 file (`{approved_at, experiments_updated, metadata}`) and a v0 file (`{approved_at, experiments_updated}`, the `given_pfhxsam` fixture) are read as they are and never rewritten until a new statement is made |
| `study_design.json` | additive: `stated: {field: {at, via, user}}`; `fields` and `recorded_at` kept |
| `front_matter.json` | same shape (`rendering/front_matter.py:15-22`), plus `stated: {key: {at, via, user}}`; now merged |
| `identity.json` | written only by M1's steps and the command line's first statement (D3); additive `abbreviation_stated: {at, via, user}`; a command-line identity has `identity_source: {"kind": "stated", "via": "command line", "stated_at"}` |
| `validation_report.json` | additive `classifications: {name: {platform, data_type, stated: bool, detected: {platform, data_type}}}` (what the check honoured); `fingerprints` hold effective values |
| `integration_basis.json` | additive `inputs: {classifications: {name: [platform, data_type]}, identity: {name, casrn}}`; `basis` hash unchanged |
| `_fingerprints.json` | detection only: never holds a person's statement (today `confirm_metadata_step` writes one into it [V]) |
| `files/<table>.txt` | the `# Provider/# Platform/# Data Type` header is written by the check from the effective classification, never by a confirmation |
| `precedence.json` | never written (D2); still read if present |
| `history/_statements/index.jsonl` | **NEW if D6 = A**: one line per save, `{"file", "key", "before", "after", "at", "via", "user"}` |

## 4. Requests to other parties (through the orchestrator)

- **C4:**
  - hash a `.txt`/`.csv` over its data lines (after the leading `#` lines), so a header
    the app writes is not a content change (spec §3.2, risk 4);
  - expose `name_of(file_id)` from the record, so C3 maps ids to names in one place.
- **C1 / M3:** integration writes `integrated.json`, records the basis and archives the
  approval before the schema load that can refuse. Make it write-then-commit (spec §7.7)
  [V].
- **M2:** `classification_unconfirmed` is raised by C3's integration check (M2 contract
  §5 listed it under C1).
- **Kit (`workflow/refusals.py`):** the codes of §1; `conflict_choice_missing` becomes
  `conflict_choice_retired`.
- **Orchestrator:**
  - register `v2_statement_routes`;
  - `http-api.md`;
  - the notebook text (identity at integration, `resolve_step`).
