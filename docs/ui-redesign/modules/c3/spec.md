# C3 — Saves merge and check: spec

Module C3 of the core-guarantees track (`MODULES.md` §2). Spec stage, 2026-10-16.
Evidence marks: **[V]** verified by running it on scratch copies of NIEHS-10
(`/workspace/ui-team/_scratch/c3-spec/sessions/DTXSID50469320_c3{A,B,C}`, copied from
the demo store; drivers in `/workspace/ui-team/_scratch/c3-spec/scripts/`, HTTP through
FastAPI's TestClient, Java through `./run-server.sh --run`); **[R]** read from the code.
A survey marked **[V, read-only]** read the real `sessions/` and wrote nothing. Citations
are `file:line` in `/workspace/ui-team/c3-spec` (branch `ui-c3-spec`, = `ui-redesign`).

## 0. What C3 changes, in one paragraph

A person tells the tool what the data cannot say. These are their **statements**: what
each file is, the study design, an experiment's organ or sex, the authors and publication
details, and the chemical's short name. Today most save paths replace the earlier
statement instead of adding to it. Most also take any value. Some lose the statement at
the next file check, and one (integration) overwrites the chemical's identity.

After C3 every statement goes through one core step per kind. Each step:
- **checks** the value against the controlled vocabulary and the rules the vocabulary
  declares, and refuses the whole request when one value fails, before anything is
  written;
- **merges** the new statement over what was stated before, field by field, so a part
  never erases the rest (`null` withdraws one field explicitly);
- **records** who stated each field, through which driver, and when;
- **leaves the rest alone**: it never writes another statement's file, and never the
  identity.

What each file is becomes a **durable record keyed by the file's name**, which the file
check honours. A change to it makes the check out of date (derived), and integration
refuses until the files are checked again. `precedence.json` retires (§3.5, D2).

## 1. The statement files, and the one writer of each after C3

| File | What a person states | Writer today | Writer after C3 |
|---|---|---|---|
| `classifications.json` (NEW) | what each file is: platform, data type | none (`confirm_metadata_step` writes `_fingerprints.json` and the file header) | `workflow.classifications.classify_step` / `unclassify_step` / `confirm_as_shown_step` |
| `metadata_approved.json` | per experiment: organ, sex, … | `pipeline.metadata_approval.approve_experiment_metadata` (HTTP and CLI) | `workflow.statements.state_experiment_metadata_step` |
| `study_design.json` | species, strain, route, means, vehicle, duration (whole study) | `tooling/generate_report.py:246` `apply_design` (CLI only) | `workflow.statements.state_design_step` |
| `front_matter.json` | authors, contributors, collaborators, publication details, strain designation | `web_routes/wizard_routes.py:108` (replaces); `generate_report.py:298` (merges) | `workflow.statements.state_front_matter_step` |
| `identity.json` `abbreviation` | the short name used in sentences | `generate_report.py:336` `record_abbreviation` | `workflow.statements.state_short_name_step` |
| `identity.json` (name, CASRN, source) | the chemical (looked up and confirmed) | M1's `create_study_step`, `record_identity_step` (`workflow/study_steps.py:240`); **also** `integrate_step` (`workflow/steps.py:432`), CLI `main` (`generate_report.py:739`), `record_studies` (`:332`), the notebook (`_nb_cells_data.py:829`) | **M1's two steps only**, plus the command line's first statement of a study that has none (D3) |
| `precedence.json` | a chosen file in a conflict | `resolve_step` (`steps.py:256`) | nobody (D2) |

Out of C3:
- `deposit.json` and `efdr.json` are records the tool computes from a folder, not values
  a person types (M4, D5).
- `meta.json` holds settings (model choices).
- The pins belong to M5.
- The dose unit is a Process parameter today; Q11 decides whether it becomes a stated
  fact (§3.8).

## 2. Every statement-save path today, and what each does wrong

### 2.1 What each file is (step 4): `confirm_metadata_step` (`workflow/steps.py:289-343`)

Drivers:
- `POST /api/pool/confirm-metadata/{id}` (`web_routes/pool_routes.py:247`), body
  `{metadata: {file_id: {platform, data_type}}}`;
- the CLI's `confirm_metadata` (`generate_report.py:226`), which maps file names to ids;
- the notebook.

What goes wrong:

| # | Defect | Evidence |
|---|---|---|
| a | Keyed by the file **id**, which changes between checks (C4 §2). An unknown id is skipped silently: `{"ok": true, "updated": 0}` | [V] |
| b | **No check on the values.** `platform: "Banana", data_type: "Kiwi"` was accepted, written into the record and into the file's header | [V] |
| c | **Lost at the next file check.** Correcting `hematology_truth_male.txt` to Hormones and then checking again set the record back to Hematology. The header written into the file still said `# Platform: Hormones` | [V] |
| d | **The header and the record then disagree, and the header wins in the dataset.** Java labels the experiment from the header (`_write_metadata_headers`, `steps.py:346`; read by BMDExpress's `ExperimentDescriptionParser`), while integration routes the file by the record. Re-integrating that copy produced two `(Hormones, male)` experiments, which the schema refuses at load | [V] |
| e | **That integration failed after it had written.** `integrated.json` and `integration_basis.json` were written and the approval was archived. Then `reapply_study_design` loaded the dataset and raised `BMDProjectValidationError`. The phase reads INTEGRATED, `integration: current`, and every read of the dataset answers 422 | [V] |
| f | A correction makes nothing out of date. After it, the phase stayed INTEGRATED with `integration: current` (C1 risk 8) | [V] |
| g | A correction of a `.xlsx` or `.bm2` writes no header, so it lives only in the record that the next check rewrites (analysis finding 4) | [R] |
| h | No record of who confirmed what, or when; "confirmed" cannot be told from "detected" | [R] |

On the real store [V, read-only]: 105 tables carry a header, and none disagrees with its
record. All 17 validation reports agree with their records, and no two tables share a
platform, data type and sex. So no session on disk is in state (d) today.

### 2.2 Experiment metadata: `approve_experiment_metadata` (`pipeline/metadata_approval.py:24-86`)

Drivers:
- `POST /api/experiment-metadata/{id}` (`web_routes/session_routes.py:1263`) calls it
  with `merge=False`;
- the CLI's `apply_experiment_metadata` (`generate_report.py:271`) calls it with
  `merge=True`, after its own checks.

| # | Defect | Evidence |
|---|---|---|
| a | **HTTP replaces the whole description with the part sent.** `{"Liver_PFHxSAm_Male": {"organ": "liver"}}` left sex, species, strain, platform, dataType and testArticle `None` | [V] |
| b | **HTTP checks no value.** `organ: "Banana"` was saved | [V] |
| c | **HTTP ignores unknown experiments.** Answer: 200 `{"updated": 0}` | [V] |
| d | **Each save replaces the record**, so only the last call's experiments are re-applied at the next integration. HTTP: after an unknown-experiment call the record was `{"metadata": {}}` (earlier approvals gone). CLI: two calls on two experiments left only the second in the record | [V] |
| e | **A malformed body breaks reads of a sound dataset.** A description sent as a string gave 500. The step had changed the in-memory dataset before the schema check refused it, so every later `GET /api/experiment-metadata` and `/api/integrated-summary` answered 422 while the file on disk was intact | [V] |
| f | **The CLI's vocabulary check refuses every strain.** The strain vocabulary is a mapping per species, so `v not in allowed` compares with the species names: "strain='Sprague-Dawley' is not in the vocabulary" | [V] |
| g | The record stores the whole description at approval time (inferred fields, `testArticle`, nulls), not what the person stated, so stated cannot be told from inferred (analysis finding 11). bmdx-pipe's `_apply_approved_metadata` then **replaces** each named experiment's description at every integration (`pool_integrator.py:1012-1029`) | [R] |

Real store [V, read-only]: 10 sessions hold approval records, all in the whole-description
shape. Every field other than organ, sex, subjectType and articleType equals the dataset's
current value or the stated design.

### 2.3 Study design: `apply_design` (`generate_report.py:246-268`), CLI and notebook only

| # | Defect | Evidence |
|---|---|---|
| a | **Replaces `study_design.json`.** Stating `{species: mouse}` alone left that one field in the file | [V] |
| b | **The dataset and the file then disagree.** `apply_design_fields` merges onto the experiments (`study_design.py:124`), so the experiments kept the strain, route and vehicle of the earlier statement. The next integration re-infers them and drops them silently | [V] |
| c | Strains are checked against all species at once: `{species: rat, strain: B6C3F1}` was accepted | [V] |
| d | No rule links route, means and vehicle: `inhaled` + `gavage` + `corn oil` was accepted | [V] |
| e | No HTTP route (M4 needs one); one `recorded_at`, no per-field record | [R] |

Real designs [V, read-only] fall in three shapes:
- oral, gavage, corn oil (rat, Sprague-Dawley);
- inhaled, whole-body, no vehicle (rat, Sprague-Dawley);
- inhaled, whole-body, no vehicle (mouse, B6D2F1).

### 2.4 Front matter: `POST /api/document/{id}/front-matter` (`wizard_routes.py:108-125`)

| # | Defect | Evidence |
|---|---|---|
| a | **Replaces.** Saving `{publication: {doi}}` after the authors erased the authors | [V] |
| b | Bad shapes dropped or coerced silently: `authors: "J. Smith"` → `[]`; `strain_designation: 7` → `"7"`; an unknown publication key dropped | [V] |
| c | `doi: "not-a-doi"`, `report_date: "yesterday"` saved as given | [V] |
| d | An unknown study: 200, and the folder was created | [V] |
| e | The CLI's `apply_front_matter` merges by top-level key (`generate_report.py:298`); the two drivers disagree | [V] |

Real store [V, read-only]: all 17 `front_matter.json` files hold a strain designation
only (no authors, no publication), so a change of semantics loses nothing on disk.

### 2.5 Conflict choice: `resolve_step` (`steps.py:256-282`), `POST /api/pool/resolve`

| # | Defect | Evidence |
|---|---|---|
| a | **No effect on apical platforms.** After choosing `body_weight_truth_female.txt`, integration still used both body-weight files: `"Body Weight|tox_study": {"file_count": 2}`, both experiments built. `integrate_pool` keys the choice by the plain platform; the coverage keys are compound (`pool_integrator.py:1079-1092` vs `:1110`) | [V] |
| b | Issue index 999, file id `no-such-file`, and the same choice twice: all appended | [V] |
| c | The choice does make the integration out of date (C1's basis): VALIDATED, `out_of_date` | [V] |
| d | It works only for the plain `gene_expression` key [R] | |

No `precedence.json` exists on the real store or in the demo store [V].

### 2.6 Identity: written by integration and by every driver

| # | Defect | Evidence |
|---|---|---|
| a | **`integrate_step` overwrites `identity.json` with the request body** (`steps.py:432-433`, M1 review finding 4). `{"name": "Test"}` replaced `{dtxsid, name, casrn}` | [V] |
| b | The CLI: `_resolve_identity` lays `--name`/`--casrn` over the file and passes the result to integration. When integration is skipped, `main` writes it directly (`:739`). The notebook does the same (`_nb_cells_data.py:829`). `record_studies` replaces a report's identity (`:332`). None of these checks what was there | [R] |
| c | `record_abbreviation` merges (`:336-343`), correctly | [V] |

M1's `record_identity_step` already does this correctly: it holds the study lock, refuses
`identity_exists`, and keeps other keys.

## 3. Behaviour after C3

### 3.1 The common rules

1. **Input checks, then the guard, then the data checks, then one write** (C1 §2.1's
   order). A request is checked whole; one bad value refuses all of it; nothing is
   written.
2. **Merge.** A field given replaces that field. A field absent is kept. A field given
   as `null` withdraws the statement, so the value goes back to recorded, inferred or
   the standard design. A list (an author roster) is one field.
3. **A save that changes nothing writes nothing** and answers `noop: already_stated`.
4. **Provenance per field:**
   - `stated_at` and `via` are kept for every stated field;
   - `via` is `"interface"`, `"command line"` or `"notebook"`, passed by the driver;
   - `user` holds the name the server's user gate carries (`?user=`) when the gate is
     on, else null. There are no logins yet (HANDOFF Q8).
5. **One study at a time.** Every save holds M1's `_study_lock`
   (`workflow/study_steps.py:203`) across read-check-write. Writes are atomic (temp file
   + `os.replace`).
6. **The dataset is never changed in place before every check passed.** A step that
   writes onto `integrated.json` works on a copy. The in-memory cache is replaced only
   after `save_integrated` succeeded (fixes §2.2 e).
7. **Refusals** are `StatementRefusal(StepError)` with a `code` from
   `workflow/refusals.py` (contract §1), so every driver explains them the same way.
   The CLI prints `say` (as C1 does).
8. **Nothing defaults.** A statement is never filled from what was detected or
   inferred. Confirming "as shown" (M2 §2.8) is a person's explicit act, recorded as
   such.

### 3.2 What each file is: the durable record (`workflow/classifications.py`, NEW)

**The key is the file's name as the person brought it in.**
- **A table converted from a one-row-per-animal CSV** is keyed by the CSV's name. Its
  pivots (`<stem>.txt`, or `<stem>_<Sex>.txt` for a two-sex CSV,
  `pool_integrator.py:824-830`) resolve to it through their sidecar's `source` field.
  Every real sidecar has one [V, read-only].
- **Any other file** is keyed by its name in `files/`.

This works with C4's D1 = A (file id = name): the step accepts either the brought-in
name or a pivot's name and keys by the former. **If C4's D1 goes to B** (name + hash in
the id), the key is unchanged. Only `classifications.name_of(file_id)` changes, to split
the id, and the contract does not change.

```json
{"version": 1,
 "files": {
   "hematology_truth_male.csv": {
     "platform": "Hormones", "data_type": "tox_study",
     "detected": {"platform": "Hematology", "data_type": "tox_study", "basis": "file_name"},
     "content_hash": "sha256:9c1e…",
     "stated_at": "2026-10-16T16:22:05Z", "via": "interface", "user": null,
     "accepted_detected": false,
     "units_missing_acknowledged_at": null}}}
```

- **`content_hash`** is over the file's **data**:
  - for a `.txt`/`.csv`, the bytes after its leading `#` lines (the header the app
    writes). The data-lines hash of a table was identical before and after two header
    rewrites, while the raw hash changed [V];
  - for a converted CSV, the original kept in `_originals/`;
  - otherwise, every byte.

  C4's record hash is over raw bytes. Request to C4: compute it the same way, or the
  first confirmation reads as "changed since the check".
- **`accepted_detected`** is true when the person confirmed "as shown" (M2 §2.8) or the
  command line accepted every detected value (D1).
- **`units_missing_acknowledged_at`** records M2's `without_units` answer (M2 contract
  §2.3).

**The allowed values** are declared once in `workflow/classifications.py` and served to
M2 as `classification_choices`:
- data types: `VOCABULARIES["dataType"]`;
- apical platforms: bmdx-pipe's declared apical list (`file_integrator.py:263-266`,
  minus `gene_expression`);
- the allowed pairs per kind of file, as M2 contract §2.1 lists them:

  | Kind of file | Data type | Platforms |
  |---|---|---|
  | table | `tox_study` | 7 apical platforms |
  | table | `inferred` | 6 (no Clinical) |
  | table | `gene_expression` | none |
  | workbook | `tox_study` | 7 apical platforms |
  | `.bm2` | `inferred` | 6 |
  | `.bm2` | `gene_expression` | none |

No list is typed into a screen.

**The checks** (`classify_step`), in order:
1. The file exists, by name or pivot name. Else `file_not_found`.
2. The pair is allowed for its kind. Else `classification_not_allowed`.
3. **No collision.** After the change, no two tables of the same kind may cover the same
   platform, data type and sex; else `classification_collides`, naming the other file.
   *Why here:* with the hematology correction honoured, `validate_pool` reported no
   error (the Hormones key held 3 tables) [V], and integration then failed at the
   schema (§2.1 d, e).
4. **When the study was combined**, the act is costly (C8's dry run). It needs the
   `preview_token` (M2 §2.6).

**Writing:**
- the step writes `classifications.json` only;
- it **no longer** writes the file's header, and never `_fingerprints.json`, which stays
  the record of what the tool *detected* (one source per fact);
- `unclassify_step` removes the entry, or answers `noop: nothing_stated`;
- `confirm_as_shown_step` records the served values, refusing `files_changed` when the
  view's token moved (M2 §2.8).

**Honoured by the check and by integration:**
- `effective(fps, statements)` overlays every statement whose `content_hash` matches the
  file's current data onto the detected fingerprints.
- `validate_step`:
  - fingerprints as today (detection);
  - converts long tables with the **effective** platform and data type;
  - rewrites the header of every table from the effective classification. The header
    becomes a copy written by the check alone, so it can no longer disagree with what
    routing used;
  - runs `validate_pool` on the effective fingerprints;
  - writes into `validation_report.json` a new `classifications` map,
    `{name: {platform, data_type, stated, detected}}`, recording what it honoured.
- `integrate_step` applies the same overlay to the fingerprints it loads before
  `integrate_pool`.
- A statement whose hash no longer matches (the file was replaced) is **not honoured**.
  The detected value is used and the file reads `needs_reconfirm` (M2 status). A
  statement about other content never applies silently.

**The check's currency** (derived, never stored): `check_currency(dtxsid, store) ->
{current, why, files}`. The check is current when the effective statements now equal the
report's `classifications` map. Otherwise `why: "classification_changed"`, with the
files' names. M2 serves it as `check.current` and `why_not_current`.

**Integration while the check is out of date** (D5, recommended): the phase is
unchanged, but the engine withholds INTEGRATE from `legal_actions`. `require_legal`
refuses it with C1's `validation_out_of_date` (`details.why =
"classification_changed"`). The served next step is VALIDATE. `derive_phase` and its
characterization oracle are untouched.

**Every file confirmed before integration** (Q-M2-4, answered yes): integration refuses
`classification_unconfirmed` while any data file has no honoured statement. Legacy
sessions and the command line: D1.

### 3.3 Experiment metadata (`workflow.statements.state_experiment_metadata_step`)

Request: `{experiment name: {field: value | null}}`. The guard is STATE_DATASET_FACTS
(C1). Checks, before anything is written:
- the dataset exists (`not_integrated`);
- the request is a non-empty object of objects (`empty_statement`, `statement_invalid`);
- every name is an experiment of the dataset. Else `experiment_not_found`, naming the
  unknown ones; the whole request is refused.
- every field is a statement field: a key of `bmdx_pipe.VOCABULARIES`.
  - `testArticle` is refused (`statement_field_unknown`, "the chemical is the study's
    identity").
  - `cellLine` and anything else is refused too.
- every value is in its vocabulary (`value_not_in_vocabulary`);
- the strain is one of the species' strains (`strain_not_of_species`). The species is
  the one stated in the same request, else the experiment's current value.
- **platform, provider and data type of an apical experiment** come from its file's
  classification: a different value is refused (`stated_on_the_file`, fix M2). A value
  equal to the current one is accepted, so an old full-description save still works. A
  gene-expression experiment's platform is its chip's and may be stated: the published
  rebuild states `S1500+_rat` (`tooling/cebs_to_pool.py:370-375`).
- **a design field** (species, strain, route, means, vehicle, duration) that differs
  from the stated study design is refused (`experiment_contradicts_design`, fix M4). The
  study design wins at integration anyway (`reapply_study_design` runs after the
  approval, `steps.py:488`), so the difference would be silent.

**Writing:**
- onto a copy of the dataset: merged into each named description, then `save_integrated`
  (schema) and the cache;
- the genomics sidecar is reconciled and `integrated.bm2` re-exported, as today;
- the record **accumulates**. Shape v2:

```json
{"version": 2,
 "experiments": {
   "Liver_PFHxSAm_Male": {"fields": {"organ": "liver"},
                          "stated": {"organ": {"at": "2026-10-16T16:15:52Z", "via": "interface", "user": null}}}},
 "legacy": {"approved_at": "…", "metadata": {"…": {"…whole description…"}}}}
```

**Legacy records** (the whole-description shape, all 10 on the real store) are read, never
rewritten (D7):
- each legacy entry keeps replacing its experiment's description at integration, as
  today, through bmdx-pipe's `approved_metadata`;
- a new statement on that experiment moves it to `experiments` (fields given, merged
  over the legacy description);
- why: a legacy `articleVehicle: null` on an inhalation study is what keeps an inferred
  vehicle out today. Merging the legacy record would let one through.

**At integration:**
- `integrate_step` passes the legacy entries as `approved_metadata` (unchanged);
- right after `integrate_pool`, it lays the v2 statements over the descriptions
  (`reapply_experiment_statements`), then the study design (`reapply_study_design`).
- Order of authority on an experiment:
  1. inferred;
  2. legacy approval;
  3. the experiment's statements;
  4. the study design (strongest).

### 3.4 Study design (`state_design_step`) and front matter (`state_front_matter_step`)

**Design.** Guard STATE_DATASET_FACTS; the dataset must exist. The fields are
`DESIGN_FIELDS` (`study_design.py:31-35`).

Checks:
- vocabulary;
- strain within species (the merged statement's species, else the dataset's single
  recorded species);
- **D4 coherence**, from a declared table beside the vocabularies (served by
  `GET /api/v2/vocabularies` as dependencies, so `<VocabField>` filters):

  | route | allowed means | allowed vehicles |
  |---|---|---|
  | `oral` | gavage, drinking water, dietary | corn oil, feed, water |
  | `gavage` | gavage | corn oil, water |
  | `inhaled` | whole-body, nose-only | aerosol, gas, or none |
  | `transdermal` | none | none |

  All real designs pass this table [V, read-only].

Writing:
- merged into `{"fields": {...}, "stated": {field: {at, via, user}}, "recorded_at"}`
  (`fields` keeps its name for its readers);
- withdrawing a field (`null`) removes it;
- then re-applied onto the dataset. A withdrawn field is put back to its inferred value
  by the next integration, and the response says so (`"until": "next integration"`),
  because inference is not re-run at a save.

**Front matter.** Not phase-guarded (C1 §2.2); refused on a companion
(`read_only_session`); refused for an absent study (`study_not_found`, no folder).

Checks:
- the keys are `authors`, `contributors`, `collaborators`, `publication`,
  `strain_designation`;
- a roster is a list of objects with a non-empty `name`, and only `name`, `affiliation`,
  `contribution` and `role`, all text;
- publication fields are `report_number` (1–3 digits, as published: "02", "8", "13"),
  `doi` (`workflow.vocabularies.DOI_RE`) and `report_date` (D8);
- `strain_designation` is text, 200 characters at most.

All problems come back at once in `front_matter_invalid.details.problems[]`.

Merging: a top-level key replaces that key; `publication` merges by field; `null`
withdraws. The stored shape is today's (`rendering/front_matter.py:15-22`) plus
`stated: {key: {at, via, user}}`. `clean_front_matter` stays the render-side cleaner.

### 3.5 Conflict choices: `precedence.json` retires (D2)

The maintainer's rulings of 2026-10-16:
- keeping one file of a real conflict moves the other to the removed files (Q-M2-1 = C:
  `keep_file_step`, C8/M2);
- redundant files and exact copies are flagged and arbitrated **outside** the app
  (Q-M2-2, Q-M2-9).

So no conflict decision is stored anywhere, and the files in `files/` are the decision.

**Does anything still need `precedence.json`?** No:
- nothing in the new design writes it;
- none exists on the real store or the demo store [V];
- its readers are inert without it:
  - `integrate_step` passes `[]`;
  - `workflow/integration_basis.py:88,103` keeps reading it. An absent file gives the
    same basis as today, so no recorded basis changes; verified on NIEHS-10's report:
    `compute_basis(report, None) == compute_basis(report, [])`, `a2e2f1307c3b9bf5` [V];
  - `GET /api/session/{id}` (`session_routes.py:609`) answers `precedence: null`;
- the deletion lists keep it (`pool_state.py:173`, `session_routes.py:1415`,
  `pool_admin.py:59`, `study_steps.py:302`) for old sessions.

`resolve_step` refuses `conflict_choice_retired` (410) for every driver. The old route
returns it. The compound-key fix in bmdx-pipe is not made.

### 3.6 Identity: written only by its own steps

- **`integrate_step` takes no identity.** Its signature becomes
  `integrate_step(dtxsid, store)`. It reads `identity.json` for the test article, as
  today.
- **`POST /api/pool/integrate/{id}`** accepts a body `identity` only when every field it
  gives equals the recorded one; it is then ignored. Anything else is refused
  `identity_not_changed_here` (409, fix M1), and nothing is integrated. This keeps a
  caller that echoes the identity working, and refuses one that would change it.
- **The command line (D3):**
  - `_resolve_identity` no longer writes or passes an identity;
  - `--name`/`--casrn` on a study with no `identity.json` name are recorded once by
    `record_identity_step(..., source={"kind": "stated", "via": "command line"})`;
  - on a study whose identity differs, they are refused `identity_exists` (M1's code);
  - `main` line 739 and the notebook cell are removed;
  - `record_studies` writes a report's identity through the same rule.
- **The short name:** `state_short_name_step(dtxsid, short | None)`:
  - 1–40 characters, one line;
  - under the study lock, merged into `identity.json` as `abbreviation` with
    `abbreviation_stated`;
  - refused on a companion.
- **Filling a pending identity after integration (D9).** The dataset was combined
  without the chemical's name: integration skips metadata inference when
  `identity.json` has no name or CASRN (`steps.py:437-449`; `pool_integrator.py:1368`)
  [R]. The recorded basis inputs (§4) therefore include the identity's name and CASRN,
  so filling it makes the integration out of date.

### 3.7 Units

- **No statement path for units exists today** [R]:
  - the dose unit is a Process parameter (`--dose-unit`), resolved stated > recorded >
    mg/kg (`study_design.py:96-105`);
  - measurement units come from `.units.json` files (M2 intake) and from workbooks
    (`stamp_sidecar_units`, `steps.py:492`).
- C3 records M2's "brought in without units" acknowledgment (§3.2).
- If Q11 makes the dose unit a stated fact, it is one more design field through
  `state_design_step`, with a declared unit list. `study_design.py` already holds the
  oral and air-concentration units (`:76-77`). Not built until Q11 is answered.

## 4. How statements join C1's integration basis

| Statement | Joins the basis? | Why |
|---|---|---|
| what each file is (`classifications.json`) | **yes** | it decides which file goes where; integration reads it |
| identity name + CASRN | **yes** (D9) | integration's inference and every experiment's `testArticle` come from it |
| study design, experiment metadata | no | written onto the dataset at the save and re-applied at every integration; C7 makes them stale AI text (Q2) |
| front matter, short name | no | read at render time only |
| precedence | unchanged code, never written | §3.5 |

**How, without moving any basis recorded today:**
- The hash (`compute_basis`) is unchanged.
- `integration_basis.json` gains `inputs: {classifications: {name: [platform,
  data_type]}, identity: {name, casrn}}`, written by `record_basis`.
- `integration_status` reads `out_of_date` when the hash differs, or when the recorded
  `inputs` exist and differ from now.
- A basis recorded before C3 has no `inputs` and is compared by hash only. No integrated
  session changes phase. The real store has no `integration_basis.json` at all [V,
  read-only].

**Sequence after a correction on an integrated study:**
1. The inputs differ, so the integration is out of date and the phase is VALIDATED
   (C1's effective `hasIntegrated`). PROCESS, APPROVE and STATE_DATASET_FACTS are
   refused.
2. The check is out of date too, so INTEGRATE is withheld (§3.2), and the next step is
   VALIDATE.
3. After checking again, INTEGRATE becomes available.
4. After integrating, the inputs match: INTEGRATED, current.

C1 risk 8 closes.

## 5. Blast radius

### 5.1 Production callers [R]

- **NEW:**
  - `workflow/classifications.py` (~250 lines);
  - `workflow/statements.py` (~350 lines);
  - `web_routes/v2_statement_routes.py` (thin; registration by the orchestrator).
- **`workflow/steps.py`:**
  - `validate_step` (overlay, header writes, `classifications` map);
  - `confirm_metadata_step` (becomes a wrapper over `classify_step`, for the old route,
    accepting ids or names);
  - `resolve_step` (retired);
  - `integrate_step` (no identity, overlay, `classification_unconfirmed`, v2 statements
    re-applied, precedence `[]`).
- **`pipeline/metadata_approval.py`:** reduced to the dataset write on a copy, called by
  the step; the legacy reader.
- **`pipeline/study_design.py`:** `design_field_errors` takes the species for the strain
  check, plus the coherence table (D4).
- **`workflow/integration_basis.py`:** `inputs`. **`workflow/engine.py`:** check
  currency, INTEGRATE withheld.
- **`workflow/refusals.py`, `workflow/errors.py`:** the codes.
- **`workflow/vocabularies.py`:** the route dependencies (D4) and
  `classification_choices`.
- **Routes:**
  - `session_routes.py:1183,1263` (experiment metadata);
  - `wizard_routes.py:108` (front matter);
  - `pool_routes.py:227,247,262` (resolve, confirm, integrate).
- **Deletion and category lists** gain `classifications.json`: `session_routes.py:1414`
  (pool reset deletes it), `pool_admin.py:59`, `study_steps.py:309` (category
  "statements"). Invalidation (`pool_state.py:173`) **keeps** it: statements are keyed
  by name and checked by hash.
- **`tooling/generate_report.py`:**
  - `confirm_metadata`, `apply_design`, `apply_experiment_metadata`,
    `apply_front_matter`, `record_abbreviation`;
  - `_resolve_identity`, `integrate`, `main` `:739`, `record_studies`;
  - a new `--accept-detected-classifications` (D1).
- **`tooling/build_published_reports.py:210-214,258-262`:** passes the new flag (D1).
  Its `--name`/`--casrn` are unchanged: it always starts from a fresh session
  (`_fresh_session`, `:145`).
- **Notebook:** `_nb_cells_data.py:748,803,808,829,906-912` (identity text and the write);
  regenerate.
- **bmdx-pipe: no change.** The overlay is applied before `validate_pool` and
  `integrate_pool`; precedence `[]`; legacy approvals pass through `approved_metadata`.

### 5.2 Tests that pin today's behaviour and must change

The baseline is green: these files hold 233 tests, all passing; `guard` passed 11 [V].

- **`tests/unit/test_workflow_steps.py`:**
  - `:159`, `:166`, `:176`: resolve. They become: the step refuses
    `conflict_choice_retired`.
  - `:215`: asserts integration persisted `identity.json == {"name": "PFHxSAm"}`.
    Becomes: integration writes no identity; the call drops the argument.
  - `:353`: confirm keyed by id `"f1"`, setting a `.bm2` to `Body Weight`/`tox_study`.
    That pair is not allowed for a `.bm2`, so the test is rewritten keyed by name with an
    allowed pair, and a refusal case is added.
- **`tests/unit/test_workflow_legality.py:214-217`:**
  - `resolve_step` leaves the inventory (it refuses in every phase);
  - `confirm_metadata_step` is called with a name;
  - `integrate_step(d, None, …)` becomes `integrate_step(d, …)`.
- **`tests/unit/test_studies.py:492`:** the same signature change.
- **`tests/integration/test_pool_integrate.py:41,64,87,134`,
  `test_approved_metadata_roundtrip.py:90`, `test_stated_design_roundtrip.py:22`:** they
  post `identity: {"name": "Test", …}` over the fixture's Perfluorohexanesulfonamide,
  which C3 refuses. They drop the body identity, and one test asserts the refusal.
- **`tests/integration/test_approved_metadata_roundtrip.py:32`:** asserts the v1 record
  shape (`record["metadata"][HE]["organ"]`). It becomes `record["experiments"][HE]
  ["fields"]["organ"]`. The sidecar reconciliation assertion is unchanged.
- **`tests/unit/test_study_design.py:162`:** `design_field_errors` gains the species; it
  is extended, not removed.
- **Unchanged, by design:**
  - `test_integration_basis.py` (the hash is untouched; `:77` still holds);
  - `test_front_matter.py` (render-side);
  - `test_wizard_routes.py`;
  - `test_studies_steps.py`;
  - the `given_pfhxsam` fixture's v0 `metadata_approved.json`
    `{approved_at, experiments_updated}` reads as "no statements".

**New tests** (fake `PoolStore` for the steps; TestClient on a scratch store for the
routes):
- every §2 scenario run above, reversed:
  - a part merges;
  - out-of-vocabulary values and unknown experiments are refused, with nothing written;
  - a malformed body leaves the cache readable;
  - a correction survives a re-check;
  - the collision is refused;
  - the identity is untouched by integration;
  - the front matter merges, and an absent study is refused with no folder;
- the basis `inputs` (none recorded → no flip; a correction → out of date; filling an
  identity → out of date);
- check currency; INTEGRATE withheld;
- `classification_unconfirmed`;
- legacy approval records still replace;
- the CLI accepts "Sprague-Dawley" for a rat.

### 5.3 The golden oracle

Process reads none of the files C3 changes:
- the design and metadata reach it through `integrated.json`;
- the identity's name through `_resolve_compound_name`;
- front matter at render time.

The golden setup writes `integrated.json` by hand and never integrates. Expected
byte-identical [R]; `guard` must show it.

## 6. Order of the changes

Each step keeps the suite green, updating its tests in the same commit. Run
`run-tests.sh smart`, then `guard`.

1. **The record.**
   - `workflow/classifications.py`: record, choices, checks, collision, the data hash,
     `effective`, `check_currency`;
   - the refusal codes;
   - unit tests on a fake store.
2. **The check and integration honour it.**
   - `validate_step`: overlay, header from the effective value, `classifications` map;
   - `integrate_step`: overlay;
   - basis `inputs`; the engine's INTEGRATE withholding;
   - `confirm_metadata_step` as a wrapper; the old confirm route;
   - the CLI's confirm by name.
   - The [V] scenario of §2.1 as an integration test: correction, re-check, integrate,
     one Hormones male experiment.
3. **Identity.**
   - `integrate_step` without identity; the integrate route's body rule;
   - the CLI's identity paths through `record_identity_step` (D3); the notebook;
   - `state_short_name_step`.
4. **Experiment statements.** The step; the v2 record and legacy reader;
   `reapply_experiment_statements`; the old route; the CLI.
5. **Study design.** The step (strain by species, D4); the CLI; re-application.
6. **Front matter.** The step; the old route; the CLI.
7. **Precedence.** `resolve_step` retired; the deletion lists.
8. **Confirmation before integration.**
   - `classification_unconfirmed` at integration (D1);
   - `--accept-detected-classifications` in the CLI;
   - `build_published_reports.py`.
9. **The v2 statement routes** (contract §2.2), the notebook text, `http-api.md`.
   Then `run-tests.sh full`.

## 7. Risks

1. **Old sessions need confirming before their next re-integration** (D1). Nothing
   changes until someone re-integrates. The published rebuild passes the explicit flag.
2. **The old front-end** (behind the wall) may rely on replace semantics for front matter
   and experiment metadata, on `resolve`, or on sending an identity with integrate. I
   cannot check it. Full-description saves still work; an echoed, unchanged identity
   still works.
3. **A `.bm2`'s restated classification** changes routing, but its experiments keep the
   labels written inside the project [R]. M3 should show the dataset's labels beside the
   statements.
4. **The header is now written by the check**, so the check changes a table's raw bytes
   when a statement changes it. C4's raw hash would read "changed". Request: C4 hashes
   data lines (§3.2).
5. **Merge needs an explicit `null` to clear a field.** A screen that wants "clear" must
   send it. The contract says so.
6. **Withdrawing a design field on an integrated study** leaves the old value on the
   experiments until the next integration. Said in the response (§3.4) and shown by M4.
7. **Found on the way, not C3's to fix:**
   - **Integration fails after writing** (§2.1 e). The dataset is written, the basis
     recorded and the approval archived before the schema load raises. The phase then
     reads "current" over a dataset no read accepts [V]. C3 removes the one cause found
     (the collision); integration should write to a temporary file and commit only after
     validation (C1 or M3).
   - **A study with its identity pending integrates without metadata inference**,
     silently (`steps.py:437-449`) [R]. M3, and D9 here.
   - **Member sessions** carry their session id as every experiment's
     `testArticle.dsstox` (`DTXSID1020431_rat`) [V, read-only]: M1's noted identity
     shape, for M3.

## 8. Decisions for the maintainer

- **D1. How the command line confirms what each file is.** You decided every file is
  confirmed before its data is combined (Q-M2-4).
  - **A (recommended):** the command line takes an explicit option, "accept every
    detected classification". It is recorded as accepted by a command, not by a person
    reading each one. The published-book rebuild passes it. A study made before C3 needs
    its files confirmed once, at its next re-combining.
  - **B:** the command line confirms silently. This is a silent default and goes against
    the "nothing defaults silently" rule.
  - **C:** every rebuild lists each file's classification by hand.
- **D2. Retire the "choose one of two files" record (`precedence.json`).** Keeping one
  file of a conflict now moves the other aside, and duplicates are settled outside the
  app.
  - **A (recommended):** retire it. The old "choose a file" request answers "retired".
  - **B:** keep it, repaired so it works for apical data. That leaves two ways to settle
    one conflict, one of them invisible in the file list.
- **D3. The chemical's name and CAS number on the command line** (`--name`, `--casrn`).
  - **A (recommended):** they are recorded only when the study has no identity yet,
    marked "stated on the command line". They never replace an identity that is already
    there.
  - **B:** the command line must look the chemical up like the interface does.
- **D4. Check that route, means and vehicle fit together.** The table in §3.4 would
  refuse "inhaled, by gavage, in corn oil". It passes every study you have built.
  - **A (recommended):** check it, with the table as written, after you confirm the
    table.
  - **B:** no check; only the vocabulary.
- **D5. After a file's classification is corrected, may the files be combined before
  they are checked again?**
  - **A (recommended):** no. The check is marked out of date and "Combine" is not
    offered until the files are checked again; the study's stage name stays as it was.
  - **B:** treat a correction like a changed file, which sends the study back to "files
    changed, not checked".
- **D6. Keep a trail of every statement** (who, when, before → after; your open Q9).
  - **A (recommended):** yes, one line per save in the study's history. It is cheap, it
    makes "undo" possible, and it can feed the report changelog.
  - **B:** no trail now; C8 decides later.
- **D7. Experiment approvals saved before C3** store the whole description.
  - **A (recommended):** they keep working exactly as now until someone re-states that
    experiment.
  - **B:** convert them into field-by-field statements. A blank vehicle on an inhalation
    study would then stop protecting it from an inferred one.
- **D8. The publication date format.** Recommended: a month and a year, "March 2023",
  which is what the BITS writer reads (`rendering/bits_book.py:200-211`). The report
  number is 1–3 digits, and the DOI starts with "10.".
- **D9. Filling a study's chemical identity after its files were combined.** Recommended:
  it marks the combined data out of date, because it was combined without the chemical's
  name, so experiment details were not inferred. The study asks for re-combining (a cold
  Process).
