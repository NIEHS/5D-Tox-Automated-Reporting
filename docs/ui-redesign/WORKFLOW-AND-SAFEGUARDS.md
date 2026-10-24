# The workflow, the safeguards, and how the new interface uses them

*Written 2026-10-24 from the code on `ui-redesign` (after merging
`package-layout-workflow-engine` at b2916e4). Every name below is a real module,
function, file or code; where something is not built yet, it says so.*

This document explains, from the bottom up:

1. **the workflow core**: what a study is on disk, every step, and the state the
   workflow derives (phase, legal acts, pins, sections, publish readiness);
2. **the safeguards** (`safeguards/`, ADR-0031): the separate layer that refuses
   what a person should not do, and explains every refusal in plain words;
3. **the front ends** that sit on top: the shared web routes, the command line,
   the Jupyter notebook;
4. **the new interface**: its backend (`ui_api/`, the `/api/v2` routes) and its
   React/antd front end (`ui/`), and how each screen reads the derived state and
   shows the safeguards' refusals.

---

## Part 0 — The picture in one page

```
                ┌──────────────────────────────────────────────────────────┐
  people        │  new interface (ui/, React + antd, served at /app)       │
                │    reads GET /api/v2/studies/{id}/state, never computes  │
                └───────────────┬──────────────────────────────────────────┘
                                │ HTTP (fetch), §4.2 error envelope
                ┌───────────────▼──────────────────────────────────────────┐
  front ends    │  web_routes/                                             │
                │    v2_routes, v2_section_routes, studies_routes  (new UI)│
                │    pool_routes, upload_routes, session_routes,           │
                │    integrated_routes, llm_routes, preview_routes, …      │
                │  ui_api/  (the new interface's server side)              │
                │  tooling/generate_report.py  (the command line)          │
                │  notebooks/  (the workflow, one step per cell)  ─────┐   │
                └───────────────┬──────────────────────────────────────┼───┘
                                │ calls safeguards.guarded / acts / …  │
                ┌───────────────▼────────────────────────────┐         │
  idiot-proofing│  safeguards/  acts · sections · inputs ·   │         │ calls the
                │  sources · publish · refusals · guarded    │         │ core
                └───────────────┬────────────────────────────┘         │ directly,
                                │ then calls the core step              │ unguarded
                ┌───────────────▼───────────────────────────────────────▼─────┐
  the core      │  workflow/  (steps, engine, phases, store, section_writes,  │
                │             ownership, labels, guard, currency, reprocess,  │
                │             section_catalog, section_readiness,             │
                │             integration_basis, errors)                      │
                │  pipeline/  (process_integrated, method_profile,            │
                │             pool_state, session_store, metadata_approval…)  │
                │  document_model/, rendering/, tables/, narrative/, …        │
                │  bmdx_pipe (sibling package) + Java (BMDExpress-3)          │
                └─────────────────────────────────────────────────────────────┘
                                │
                         sessions/<DTXSID>/   (the state IS the files)
```

Three rules hold the picture together:

- **The state is derived, never stored.** The phase, the legal acts, a
  section's readiness, the publish readiness: every one is recomputed from the
  files in `sessions/<id>/` on every call (CONTEXT.md invariant 3). No front
  end stores or sets any of them.
- **The core holds the invariants; the safeguards hold the idiot-proofing.**
  What must be true for *every* caller (nothing written is ever lost, a merge
  either completes or leaves the study as it was, unpublished data never leave
  for a public model) is in the core. What keeps a *person* from going wrong
  (doing a step out of order, letting a machine overwrite their approved text,
  stating a value outside the vocabulary, shipping a stale report) is in
  `safeguards/`.
- **The import direction is one-way.** No core package imports `safeguards`;
  `safeguards` imports no front end; nothing below the new interface imports
  `ui_api`. Tests enforce all three (`tests/unit/test_safeguards_layering.py`,
  `tests/unit/test_ui_api_layering.py`).

The **notebook** (`notebooks/workflow_walkthrough.ipynb`) is the one front end
that calls the core directly: it is "the workflow and its code without the
idiot-proofing" (the maintainer, 2026-10-14). The **browser** and the
**command line** go through the safeguards.

---

## Part 1 — The workflow core

### 1.1 A study is a folder

Everything about a study lives in `sessions/<DTXSID>/` (`common.paths.SESSIONS_DIR`,
overridable with the `SESSIONS_DIR` environment variable). There is no database
of sessions and no in-memory state that matters: restart the server and
everything is still there. The files, grouped by what produces them:

| File | Written by | What it is |
|---|---|---|
| `files/` | uploads, `generate_report.import_files` | the input data files (.bm2, .txt, .csv, .xlsx and their `.sidecar.json`) |
| `_fingerprints.json` | `store.ensure_fingerprints` | one fingerprint per file: platform, data type, file type, hashes, a per-scan `file_id` |
| `validation_report.json` | `validate_step` | the file check: `issues` (each with a `severity`), the `coverage_matrix`, `is_complete`, the fingerprints it checked |
| `precedence.json` | `resolve_step` | a person's choices between conflicting files |
| `integrated.json` (+ `integrated.bm2`, `_category_lookup.json`, `genomics.sidecar.json`) | `integrate_step` | **the dataset**: the merged BMDProject, the single source of truth for every report |
| `integration_basis.json` | `integrate_step` | the hash of the validation the dataset was built from |
| `identity.json` | create, integrate, `record_abbreviation` | the chemical: name, CASRN, DTXSID, abbreviation, where it came from |
| `study_design.json` | `record_study_design` | design facts a person stated (route, vehicle, strain…) |
| `metadata_approved.json` | `approve_experiment_metadata` | experiment details a person stated (organ, sex…) |
| `animal_report.json` | `generate_animal_report_step` | **the data approval**: every animal accounted for |
| `method_profile.json` | `pin_profile`, `track_newest`, `ensure_pin` | the analysis method pin (ADR-0027) |
| `document_definition.json` (+ `.yaml` snapshot) | `definition_pin.pin_definition` | the document definition pin (ADR-0029) |
| `_cache_<unit>_<hash>.json` | Process | each Process unit's output, keyed by a hash of its inputs |
| `bm2_<slug>.json`, `genomics_*.json`, `background.json`, `summary.json`, … | Process, LLM routes, a person | **the sections** |
| `history/<section>/v0007-<ts>.json`, `history/<section>/index.jsonl` | `save_section` | every earlier version of a section, and one line per act on it |
| `history/_data_approval/` | `integrate_step` | data approvals withdrawn by a re-integration |
| `session.duckdb`, `session_parquet/` | end of Process | the query substrate (ADR-0016) |
| `published_clone.json` | `tooling/published_clone` | marks a **companion**: a published book's own content |
| `studies.json` | `--studies` | marks a **report over several studies** (NIEHS-12/13): `{key: member session}` |

Session ids are validated everywhere (`common.dtxsid.validate_dtxsid`): a bad id
never reaches the filesystem (it is what stops `/api/session/reset/%2e%2e` from
deleting `sessions/`).

### 1.2 The store

Every step reads and writes through an injected `PoolStore`
(`workflow/store.py`, ADR-0014): `session_dir`, `read_json`/`write_json`,
`has_files`, `artifact_exists`, `get_fingerprints`/`ensure_fingerprints`,
`set_integrated`, `read_section_dicts`/`read_section_states`,
`has_stale_sections`, `save_section`, `archive_section`, `delete_section`.
`DiskPoolStore` is the real one. Tests pass fakes; the new interface's reads
pass `ui_api.read_model.ReadOnlyDiskPoolStore`, which refuses every write (see
Part 6).

### 1.3 The steps, in order

The workflow is thirteen steps (the notebook's numbering). Each core step is a
plain Python function: no HTTP, plain arguments, a plain dict back, a
`workflow.errors.StepError(message, status_code)` on failure.

**Data preparation**

1. **Create the study.** A folder with `identity.json` and `meta.json`.
   (In the new interface: `ui_api.study_steps.create_study_step`, Part 6.)
2. **Bring in files.** Uploads land in `files/`. If the study had already been
   validated, integrated or approved, the upload calls
   `pipeline.pool_state.invalidate_pool_artifacts` (see 1.8): the validation,
   the dataset, the data approval and the caches go, so the phase falls back.
   Removing one file (`pool_state.remove_pool_file`) moves it to
   `_removed/<timestamp>/` (reversible) and invalidates the same way.
3. **Validate** — `workflow.steps.validate_step`. Re-fingerprints every file
   (a full re-scan), runs `bmdx_pipe.validate_pool` (cross-file checks,
   coverage per platform), adds the value-level provenance check
   (`pipeline.value_validation`: a derived CSV must equal its source workbook),
   writes `validation_report.json`. It never deletes the dataset or the data
   approval: a validation that finds errors leaves them inert (the phase says
   so), and one that no longer matches the dataset reads "integrate again".
   Core refusal: no `files/` → `StepError(404)`.
4. **Resolve conflicts** — `resolve_step` appends `{issue_index,
   chosen_file_id, resolved_at}` to `precedence.json`.
5. **Confirm classification** — `confirm_metadata_step`: a person's
   `{file_id: {platform, data_type}}` corrections go onto the fingerprints and,
   for .txt/.csv, into the files' `# Platform` / `# Data Type` headers.
6. **Integrate** — `integrate_step`, the heart of data preparation:
   - refuses without fingerprints or a coverage matrix (`StepError(400)`,
     "run validation first");
   - **`_check_validation_matches`**: refuses with `ValidationOutOfDate` (409)
     when the fingerprints it would merge no longer match the validation it
     pairs them with — a file id in the coverage matrix that a cold re-scan
     re-minted, or files added/removed since. This is a *core* refusal: going
     ahead would combine the wrong files;
   - writes `identity.json` if the caller passed one; reads the test article
     and any `metadata_approved.json` (the stated details win over inference);
   - **atomic merge**: `_keep_dataset_files` copies the current dataset files
     aside, `bmdx_pipe.integrate_pool` merges (Java `IntegrateProject`; an LLM
     may infer experiment metadata through the gateway), `_check_dataset` runs
     the BMDProject schema over the result; on *any* failure
     `_restore_dataset_files` puts the old dataset back and the step raises
     `StepError(500, "Integration failed: …")`. A study is never left "integrated"
     over a dataset no read accepts;
   - withdraws the data approval (`_withdraw_data_approval`: `animal_report.json`
     moves to `history/_data_approval/`, never deleted);
   - records the basis (`workflow.integration_basis.record_basis`);
   - re-applies the stated study design (`reapply_study_design`) and stamps
     measurement units onto the sidecars;
   - deletes every Process cache and the query substrate (their inputs changed);
   - compares the dataset's recorded analysis settings with the pinned method
     profile and writes each disagreement into the validation report as a
     `method_mismatch` warning. **It pins nothing**: the method is a person's
     choice (C1 D1).
7. **State the facts the data don't carry.**
   - Study design: `workflow.steps.record_study_design(dtxsid, fields, store)`
     writes `study_design.json` and puts the fields on every experiment
     (`apply_design_fields`), saving `integrated.json` and re-exporting
     `integrated.bm2`. Without a stated design, the report uses the sanctioned
     standard design and says so in the log (`pipeline.study_design`).
   - Experiment details: `pipeline.metadata_approval.approve_experiment_metadata`
     lays `{experiment: {organ, sex, …}}` over the descriptions, reconciles the
     genomics sidecar, re-exports the .bm2 and records `metadata_approved.json`
     (which every later integration re-applies).
   - Front matter, abbreviation, the data deposit, the eFDR: command-line helpers.
8. **Data approval** — `generate_animal_report_step` builds the per-animal
   traceability report (`bmdx_pipe.build_animal_report`) and writes
   `animal_report.json`. Its existence is what the phase calls APPROVED. It
   informs; it gates nothing (decision Q3): Process is legal from INTEGRATED on.

**The report**

9. **Process** — `pipeline.process_integrated.run_process` (also as
   `workflow.steps.process_step`, and in two halves `run_data` +
   `run_document`/`document_step`, ADR-0021):
   - `_build_process_context` calls `method_profile.ensure_pin` (a study with
     no pin gets one written `pinned_by: "default"`, tracking the newest
     profile; a TRACK pin moves to a newer profile) and the definition pin's
     `ensure_pin`;
   - **concern [1], `run_data`**: NTP statistics, the BMDS/ToxicR modelling,
     genomics extraction, charts, the BMD summary. Each unit writes
     `_cache_<unit>_<hash>.json`, the hash covering every input of that unit,
     so an unchanged unit is not recomputed;
   - **the BMD hard-stop** (`_BMD_HARD_STOP = True`): where both the .bm2 and the
     ToxicR recompute give a numeric BMD and they differ beyond 25%, the run
     halts with `BmdDivergenceError` naming each endpoint and both values;
   - **concern [2], `prepare_content_if_changed`**: the prose (genomics
     narratives, apical BMD narrative, unified narratives, Materials & Methods),
     skipped when its inputs are unchanged;
   - the payload, then the query substrate (`session.duckdb`).
   Every LLM call goes through `styling_export.llm_endpoints`, whose **egress
   guard** raises `LLMEgressBlocked` for any endpoint but the NIEHS gateway: a
   core invariant (study data never go to a public model).
10. **Materialize the sections** — `workflow.steps.materialize_result_sections`
    writes one `bm2_<slug>.json` per apical platform from the sections cache;
    `materialize_summary` writes `summary.json` (deterministic,
    `narrative.report_summary`). Both write through the section write gate
    (1.7), taking a `policy` argument (Part 2).
11. **Background** (LLM): `narrative.data_gatherer.gather_all` (PubChem, CTX,
    ATSDR, IRIS, OSHA/NIOSH, drinking water, mechanism papers, CPDat) then
    `narrative.background_writer.generate_background`, saved through the gate.
12. **Review the sections**: accept, release, restore, discard (1.7).
13. **Render**: `rendering.preview_surface.render_preview` (html, docx, jats,
    bookshelf) or the LaTeX/PDF path, from `integrated.json` + the sections + the
    document tree.

### 1.4 The derived state: phase, legal acts, next step

`workflow.engine.WorkflowEngine(dtxsid, store).state()` gathers presence flags
(`gather_artifacts`: `hasFiles`, `hasStale`, the validation report and
`hasValidationErrors`, `hasIntegrated`, `hasAnimalReport`, `integration`,
`hasQuerySubstrate`, `hasKnowledgeBase`) and returns a `WorkflowState`:
`phase`, `legal_actions`, `artifacts`, `completeness`, `next_step`.

**The phase** (`workflow.phases.derive_phase`, first rule wins):

| # | Condition | Phase |
|---|---|---|
| 1 | no files in `files/` | `EMPTY` |
| 2 | no `validation_report.json` | `UPLOADED` |
| 3 | the validation report has an error-severity issue | `VALIDATION_ERRORS` |
| 4 | no `integrated.json`, **or** one whose basis is out of date | `VALIDATED` |
| 5 | no `animal_report.json` | `INTEGRATED` |
| 6 | otherwise | `APPROVED` |

A stale section does **not** move the phase (C1 D2): staleness is a section's
matter (its currency and the publish gate).

**The integration basis** (`workflow/integration_basis.py`): file ids are not
stable (a cold re-scan mints new ones), so "is the dataset still the one this
validation describes?" is asked *by file name*: a SHA over each file's
fingerprint minus its volatile fields (`file_id`, the timestamps), the coverage
matrix with ids mapped to names, and `precedence.json` with ids mapped to
names. `integration_status` answers `current`, `out_of_date` (the phase reads
VALIDATED), `unrecorded` (a pre-C1 session: counted as current) or None (no
dataset). The engine passes the effective `hasIntegrated` to `derive_phase`;
the raw flag stays in `artifacts`.

**The legal acts** (`workflow.phases.LEGAL_ACTIONS`, the workflow's own declared
table, C1):

| Phase | Legal acts | `NEXT_STEP` |
|---|---|---|
| EMPTY | ADD_FILES | ADD_FILES |
| UPLOADED | ADD_FILES, REMOVE_FILE, RESET, VALIDATE | VALIDATE |
| VALIDATION_ERRORS | the above + RESOLVE, CONFIRM_CLASSIFICATION | VALIDATE |
| VALIDATED | the above + INTEGRATE | INTEGRATE |
| INTEGRATED | all ten | — |
| APPROVED | all ten | — |

The ten acts (`workflow.phases.Action`): ADD_FILES, REMOVE_FILE, RESET,
VALIDATE, RESOLVE, CONFIRM_CLASSIFICATION, INTEGRATE, STATE_DATASET_FACTS,
APPROVE, PROCESS. Why each entry is where it is: ADD_FILES is always legal;
VALIDATE stays legal after validation (the cure for an out-of-date
integration is "validate again"); RESOLVE/CONFIRM follow a validation and stay
changeable after integration; INTEGRATE at INTEGRATED/APPROVED is
re-integration (it withdraws the data approval); STATE_DATASET_FACTS writes
onto the dataset, so it needs one; PROCESS is not gated on the data approval.

**In the core this table is derived state only.** No core step checks it. The
safeguards enforce it (Part 2).

`completeness` (`compute_section_completeness`) turns the coverage matrix into
per-platform readiness ("an apical platform needs both study data and a .bm2").

### 1.5 The pins: the method and the document are fixed per study

**The method profile** (`pipeline/method_profile.py`, ADR-0027). A profile
(`profiles/ntp-5day-*.yaml`) declares how the numbers are made: tests, alphas,
BMD acceptance, BMR, GO ranking, internal-dose rules. A study is pinned to one
in `method_profile.json`: `{name, hash, series, mode, pinned_at, pinned_by}`.
- `mode`: `fixed` (`pin_profile`) or `track` (`track_newest`: follows the
  newest profile of its series).
- `pinned_by`: who chose it. `ensure_pin` writes `pinned_by: "default"` when a
  study had none.
- `chosen_by_person(pin)`: true only for a pin a person made (not `default`,
  not absent). This is the fact the safeguards' Process check reads.
- `suggest_profile(dtxsid)`: the profile to *propose*: the one of the study's
  series whose expectations the dataset's recorded analyses contradict least;
  `{name, why}`; a read, never applied.
- A pinned profile whose file changed since pinning raises
  `MethodProfileError("… changed since it was pinned")`; an implementation that
  cannot run here (BMDS 2.7 under Wine, ADR-0030) is substituted and recorded
  as a deviation.

**The document definition** (`document_model/definition_pin.py`, ADR-0029):
`fixed` (the composed definition is snapshotted and rendered from, whatever
the templates say later) or `track`. `drift()` says how the files have moved
away from a fixed pin; a missing or edited snapshot raises
`DefinitionPinError`.

### 1.6 Sections: catalog, kinds and readiness

The report's sections are **derived from the document tree**
(`workflow.section_catalog.catalog_for_tree` / `catalog_for_session`): each
`SectionSpec` has a `key`, a `kind` (`llm`, `programmatic`, `authored`),
whether it is `approvable`, its `instance_of` family (`bm2`, `genomics`), its
region. `validate_section_key` refuses a key that is not a section of *this*
report (`section_key_invalid`).

**Readiness** (`workflow.section_readiness.derive_section_readiness`, from
`KIND_UNLOCK`): methods waits for `processed`; summary waits for the
`background` and at least one `results` section to be approved; genomics waits
for the `knowledge_base`; the others are always enabled. Recomputed every
call: `{key: {enabled, blocked_by, approved}}`.

### 1.7 The section write gate and the history

**Every** write to a section file, a person's or a machine's, goes through
`workflow.section_writes.write_section(dtxsid, key, content, store, *, act,
actor, author, force, reason, cause, status, extra_event, on_owned, review,
policy)`:

1. the key must be a section of this report (`section_key_invalid`);
2. the prior file is read;
3. **unchanged content writes nothing**: the content hash
   (`workflow.ownership.content_hash`, the dict without its STATE_KEYS:
   approved, approved_at, facts, stale, regenerated, wording_review, review,
   revised, version, saved_at) equals the prior's → outcome `unchanged`, no
   event. A Process that changed nothing leaves every section file untouched;
4–6. **the policy** decides what happens over content a person owns. It is
   called with a `WriteRequest` and returns None (write), an outcome (`hold`,
   `knock_down`), or raises. **With no policy, every write is made**;
7. otherwise the prior file is archived, the new one written with the next
   version number, and one event recorded.

Rules 1–3 and 7 are core: whoever calls, nothing written is ever lost. Rules
4–6 are the safeguards' policy (Part 2).

**The history** (`pipeline.session_store.save_section`): the prior version goes
to `history/<key>/v<NNNN>-<ts>.json` under a name no other archive can take;
version numbers are monotonic (one above every version the section ever had,
so they never repeat after a discard); each act appends one line (format 2) to
`history/<key>/index.jsonl`: section, version, `cause` (generate, edit,
revise, reprocess, restore, discard, hold), `status` (draft, working, blessed,
needs-re-bless, discarded), `act`, `actor` (person/system), `author` (who wrote
the text: generated, model, person, ingested, client), `reason`, `review`,
`changed`, `content_hash`, `forced`, `from_version`. `section_history` and
`read_version` serve them; `current_version_status` gives the current
version's status.

**Facts, the ladder and the guard** (ADR-0015). A section carries content facts
(`workflow.labels.Fact`): the maturity ladder FIRST_DRAFT → WORKING_DRAFT →
FINAL, and the orthogonal PROTECTED. FINAL implies PROTECTED. Facts only move
down with a recorded reason (`DemoteReason.HUMAN_RELEASE`,
`CURRENCY_FORCED`). `workflow.guard.GuardLevel` (OPEN, GUARDED, PUBLISHED) is
the max over the facts.

**Ownership** — `workflow.ownership.is_owned(section)`, the one predicate: a
machine may not replace this text when a person approved it, a person edited
it (`user_edited`), its text came back from outside (`source: "ingested"`), or
it holds FINAL or PROTECTED. `workflow.section_writes.is_locked`: the stronger
condition under which even a person's *unforced* write is refused (approved,
edited, or ingested; a released section is owned but not locked).

**The state changes on a section** (core steps, `workflow/steps.py`):

| Step | What it does | Its own answers |
|---|---|---|
| `accept_section_step` | `approved=True`, `approved_at`, FINAL (+PROTECTED); clears `stale`, `wording_review`, `review`; saved in place (`archive=False`) with one `edit/blessed` event against the **same** version. The text never changes. | `noop already_accepted` when nothing would change; `section_not_found`, `section_key_invalid` |
| `release_section_step` | `approved=False`, FINAL withdrawn, **PROTECTED stays** (a released section is still kept from machines); the reason on the event and in `revised`. | `noop not_approved` |
| `restore_section_step` | brings a past version back as the **next** version: not approved, PROTECTED; the current file is archived first; currency markers (stale, review…) carry over from the current file. Takes a `policy`. | `noop already_current`; `version_not_found`, `version_content_missing` |
| `discard_section_step` | archives, deletes the file, records `discard/discarded`; restore still reaches it. | `section_not_found` |

In the core the reason is optional on all of them. Requiring it is the
safeguards'.

### 1.8 What a data change does to the sections, and the publish readiness

`pipeline.pool_state.invalidate_pool_artifacts` (called when files change after
progress) deletes the validation, the dataset and its sidecars, the data
approval, the basis, every cache except the content-hash-keyed BMDS caches, the
query substrate and its skip-guard fingerprints. Then, per section
(`iter_section_files`), it asks `workflow.reprocess.should_stale_on_reprocess`:
- **programmatic** sections (`bm2_*`) are not staled: their numbers refresh;
- **LLM** sections that depend on the data (genomics, methods, summary,
  bmd_summary; not the Background, which is about the chemical) are marked
  `stale: true`, `regenerated: {reason: "data_changed"}`, FINAL withdrawn
  (`demote_for_currency`, PROTECTED stays), and saved through `save_section`
  with a `reprocess/needs-re-bless` event (the blessed version is archived).

When Process later materializes an **apical** section a person approved and
its printed content changed, the gate knocks the approval down (C2 D2/A1,
`section_writes.knock_down`): the new content becomes the next version, the
approval goes, a `review: {why, since_version, flips}` marker is set
(`wording_changed` when a categorical data-derived word flipped,
`numbers_changed` otherwise), and a `reprocess/needs-re-bless` event is
recorded. Accepting it again clears it.

**Publish readiness** (`WorkflowEngine.publish_readiness`) is derived the same
way: `workflow.reprocess.blocking_llm_sections` lists every LLM section still
carrying `stale`; `{can_publish, blocking: [{section_key, reason}]}`.
Re-accepting a section clears its `stale`, and it stops blocking.

### 1.9 The core's own refusals (invariants)

These refuse for every caller, the notebook included:

| Refusal | Where | Why it is core |
|---|---|---|
| `ValidationOutOfDate` (`validation_out_of_date`) | `integrate_step` | going ahead would merge files the validation never saw |
| integration failure + restore | `integrate_step` | a study is never left over a dataset no read accepts |
| `SectionRefusal("section_key_invalid")` | `write_section` and every section step | a key outside this report's catalog would write an arbitrary file |
| `InvalidDtxsid` | everywhere an id becomes a path | path safety |
| `LLMEgressBlocked` | `styling_export.llm_endpoints` | unpublished study data never go to a public model |
| `BmdDivergenceError` | Process | shipping either of two disagreeing BMDs would assert an unvalidated number |
| `MethodProfileError`, `DefinitionPinError` | the pins | a pin that changed under a study must never be used silently |
| `UnreadableSessionFile` | `common.session_files` | a damaged file is reported, never read as absent |
| `BMDProjectValidationError` | every dataset read | the dataset barrier (ADR-0001) |

---

## Part 2 — The safeguards (`safeguards/`, ADR-0031)

### 2.1 Why a separate layer

The interface's most important purpose is idiot-proofing (the maintainer,
2026-10-14). Before 2026-10-23 that idiot-proofing had no home: some rules
lived in one front end only, some were woven into the core steps, some had no
handler and surfaced as a 500. The decision (2026-10-23): a **separate layer**
that front ends go through; it checks the act, explains a refusal in a
person's words, then calls the core step. The core keeps the invariants; the
notebook calls the core unguarded.

The package:

| Module | What it guards |
|---|---|
| `safeguards/refusals.py` | the catalog of every refusal: code, status, plain words, where it is fixed; `explain`, `error_body`, `register`; the refusal classes |
| `safeguards/acts.py` | whether an act may run now: R6 (session kind), C1 (the phase), the person's method choice, deleting a session |
| `safeguards/sections.py` | C2: the ownership write policy; reasons |
| `safeguards/inputs.py` | facts a person states: vocabularies, the dataset's experiments |
| `safeguards/sources.py` | no Background without its sources |
| `safeguards/publish.py` | the publish gate |
| `safeguards/guarded.py` | **the one entry point for front ends**: the core steps' names and signatures, each with its checks first |

### 2.2 The refusal catalog (`safeguards/refusals.py`)

**The envelope.** `explain(exc)` turns any exception into:

```json
{"error": {"code": "phase_not_allowed", "status": 409,
           "message": "INTEGRATE refused for DTXSID…: the study is in phase VALIDATION_ERRORS (allowed now: …). Fix the validation errors, then validate again.",
           "say": "Combining the files into one dataset isn't possible yet. The file check found errors. Fix what it lists (remove or replace the files it names), then run the file check again.",
           "fix": "files",
           "details": {"action": "INTEGRATE", "phase": "VALIDATION_ERRORS", "legal_actions": [...], "integration": null, "next_action": "VALIDATE"}}}
```

- `code` — from the closed list `REFUSALS`. A refusal the list does not know is
  `unexpected`, never a guess at a nearer one.
- `status` — the refusal's own HTTP status when it is a workflow refusal
  (`StepError` or one that names its code), else the code's default. An
  upstream HTTP client's `status_code` is never taken as this request's.
- `message` — the backend's own text, verbatim (for the technical details).
- `say` — the plain words, written once, next to the code. Placeholders
  (`{key}`, `{act}`, `{sources}`, `{keys}`, `{parent}`, `{species}`, `{what}`…)
  are filled from the refusal's `details` and from what a message rule
  captured; a missing one gets a neutral default (`_FIELD_DEFAULTS`), never a
  KeyError.
- `fix` — **the place in the workflow where the cause is cleared**, one of
  `PLACES`, or None when nothing a person does clears it ("tell the
  maintainer"):

  | Place | Meaning |
  |---|---|
  | `study` | the study itself (which study, its identity) |
  | `files` | the study's files and the file check |
  | `dataset` | combining the files into one dataset |
  | `data_review` | the data review (every animal accounted for) |
  | `method_and_document` | the analysis method and the document definition |
  | `process` | Process |
  | `sections` | the report's sections (accept, reopen, restore) |
  | `handoff` | editing in Word or Overleaf and bringing the edits back |
  | `facts` | the facts a person states (design, experiment details) |
  | `publish` | the report's readiness to publish |

  A front end maps a place to its own screen (Part 6 shows the new interface's
  map).
- `details` — what a screen may show beside the words: the refusal's own
  `details` when it names its code, the damaged file's name, a request's field
  errors, the phase and the legal acts.

**How an exception becomes a code** (`classify`):
1. an exception that carries a `code` attribute naming a listed code is taken
   at its word (and its own `say`/`fix`, when it knows its case better: the
   phase guard words each phase differently);
2. otherwise the first matching `_MESSAGE_RULES` entry: (exception class name
   anywhere in its MRO, a regex over the message, the code). For example
   `StepError` + `^No fingerprints found` → `not_validated`;
   `StepError` + `^Integration failed:` → `integration_failed` (unless the
   message shows a Java/BMDExpress setup failure → `server_setup_failed`);
   `GuardViolation` + `currency BLOCK` → `stale_content`;
   `MethodProfileError` + `changed since it was pinned` → `method_profile_changed`;
   `LLMEgressBlocked` → `llm_egress_blocked`; `InvalidDtxsid` →
   `invalid_study_id`; `UnreadableSessionFile` → `damaged_session_file`;
   FastAPI's `RequestValidationError` → `bad_request`;
3. otherwise `unexpected`.

**The refusal classes the safeguards raise themselves:**
- `PhaseRefusal(dtxsid, action, phase, legal_actions, integration, next_action)`
  — code `phase_not_allowed`, 409. Its `say` is "<the act, in words> isn't
  possible yet." + the phase's own sentence (`_PHASE_REFUSAL`: EMPTY, UPLOADED,
  VALIDATION_ERRORS, VALIDATED, and VALIDATED-out-of-date, which says "integrate
  again"); its `fix` is the phase's place (`files` or `dataset`). Removing a
  file or resetting in EMPTY says "This study has no files to remove."
- `MethodNotChosen(dtxsid, pin)` — `method_not_chosen`, 409; when a pin exists
  but was set by default it names it and says it "must be confirmed or changed".
- `Refused(code, message, status_code, details)` — any catalog code.
- `StudyRefusal` — a `Refused` for R6 and the study acts.
- Core classes it explains: `StepError`, `ValidationOutOfDate`,
  `SectionRefusal`, `GuardViolation`, the pin errors, `LLMEgressBlocked`,
  `InvalidDtxsid`, `UnreadableSessionFile`, `BMDProjectValidationError`.

**`error_body(exc)`** — the shape the application's existing routes answer:
`{"error": message, "code", "say", "fix", "details"}` with the status. It is
additive: a client that read only `error` keeps working.

**`register(codes)`** — a front end adds its own codes (the new interface's
study acts, Part 6). An existing code is never redefined (ValueError); a `fix`
must be a place or None; registering the same definition again is a no-op.

**The whole catalog** (as served on 2026-10-24; "module" is the new
interface's translation, Part 6):

| Code | Status | Place | Module | Plain words |
|---|---|---|---|---|
| `invalid_study_id` | 400 | study | M1 | That is not a valid study id. A study is named by its chemical's DTXSID: "DTXSID" followed by digits, for example DTXSID50469320. |
| `read_only_session` | 409 | — | — | This is the published book's own content, made by a tool. It can't be changed or deleted here. |
| `member_of_report` | 409 | study | M1 | This is the {species} study of the report {parent}. Deleting it would break that report. |
| `report_has_no_data` | 409 | study | M1 | This is a report over several studies: it has no files or data of its own. Its data is prepared in each of its studies; open one of them. |
| `no_files` | 404 | files | M2 | This study has no data files yet. Add the study's files first. |
| `files_not_recognised` | 400 | files | M2 | None of this study's files has been recognised yet. Add the files and run the file check, then try again. |
| `not_validated` | 400 | files | M2 | The study's files haven't been checked yet. Run the file check (validation) first, then try again. |
| `conflict_choice_missing` | 400 | files | M2 | To settle a conflict between files, choose the file to keep for that conflict. |
| `integration_failed` | 500 | dataset | M3 | Combining the study's files into one dataset failed. The details say which file or value it stopped at. … |
| `not_integrated` | 400 | dataset | M3 | The study's files haven't been combined into one dataset yet. Finish the Integrate step first. |
| `dataset_invalid` | 422 | dataset | M3 | The study's combined dataset doesn't have the form the report needs. Integrate the study again; … |
| `animal_report_failed` | 500 | data_review | M6 | Accounting for every animal across the files failed. … |
| `bmd_divergence` | 500 | process | P1 | Some apical benchmark doses computed here differ from the values recorded in the study's .bm2 files … send the list of endpoints in the details to the data team. |
| `calculation_program_failed` | 500 | — | — | A calculation program failed while processing … Tell the maintainer. |
| `processing_failed` | 500 | process | P1 | Processing stopped with an error before it finished. … |
| `content_preparation_failed` | 500 | process | P1 | Writing the report's text from the processed results failed. … |
| `server_setup_failed` | 500 | — | — | A program the server needs could not run (Java or the BMDExpress tools). … Tell the maintainer. |
| `section_not_found` | 404 | sections | D1 | There is no saved section "{key}", so there is nothing to {act}. … |
| `section_key_missing` | 400 | — | — | The request didn't say which section it is about. This is a fault in the interface … |
| `release_reason_required` | 409 | sections | D1 | Reopening an approved section needs a reason. … |
| `stale_content` | 409 | sections | D1 | This section was written before the study's data changed, so it can't be marked final or published. … |
| `guard_refused` | 409 | sections | D1 | This change to a section was refused to protect content a person owns. … |
| `section_owned` | 409 | sections | D1 | This section has been approved, or you chose to keep it, so it can't be replaced automatically. To replace it, reopen it and say why. |
| `section_key_invalid` | 400 | sections | D1 | There is no section by that name in this report. |
| `reason_required` | 400 | sections | D1 | Please say why. The reason is kept with the section's history. |
| `version_not_found` | 404 | sections | D1 | That version of the section doesn't exist. |
| `version_content_missing` | 409 | — | — | This version is listed in the history, but its text was lost before history was kept reliably. … |
| `approve_content_retired` | 409 | handoff | D4 | Approving can't change the text. Accept the section as it is, or edit it in Word or Overleaf and bring that version back. |
| `approve_via_accept` | 400 | sections | D1 | Saving doesn't approve. Use Accept. |
| `method_profile_changed` | 409 | method_and_document | M5 | The analysis method this study is pinned to … was edited after the study was pinned … |
| `method_profile_invalid` | 422 | method_and_document | M5 | The analysis method (method profile) named for this study is missing or not valid. … |
| `definition_pin_changed` | 409 | method_and_document | M5 | The saved copy of the document definition this study is fixed to no longer matches its pin … |
| `definition_not_pinned` | 409 | method_and_document | M5 | … its saved copy is missing. Pin the document definition again. |
| `definition_pin_invalid` | 400 | method_and_document | M5 | A document definition can be pinned in two ways only: fixed … or track … |
| `phase_not_allowed` | 409 | (per phase) | (per phase) | (per phase; the fallback: "This step isn't available at the study's current stage. …") |
| `validation_out_of_date` | 409 | files | M2 | The file check is out of date: it no longer matches the study's files as the server sees them now. … Run the file check again, then Integrate. |
| `method_not_chosen` | 409 | method_and_document | M5 | Choose the analysis method (the method profile) this study is reported under before processing. … it is never chosen for you. |
| `llm_egress_blocked` | 503 | — | — | The language model this needs is not one the study's data may be sent to (only the NIEHS gateway is allowed). Nothing was sent. … |
| `facts_invalid` | 422 | facts | M4 | Some of what was stated about {what} can't be used, so nothing was saved. The details list each problem … |
| `background_sources_unreachable` | 503 | sections | D1 | The Background can't be written now: {sources} could not be reached … |
| `background_empty` | 502 | sections | D1 | The language model wrote no Background. Nothing was saved; try again. |
| `background_no_references` | 502 | sections | D1 | The Background the language model wrote cites no sources … |
| `publish_blocked` | 409 | sections | D1 | The report can't be published yet: sections were written again after the study's data changed ({keys}). Read each one and accept it again, then publish. |
| `damaged_session_file` | 422 | — | — | One of this study's saved files is damaged and can't be read ({file}). … |
| `bad_request` | 422 | — | — | The request was malformed. This is a fault in the interface … |
| `unexpected` | 500 | — | — | The application hit an error it has no explanation for. … |
| *(registered by `ui_api.refusals`)* | | | | |
| `invalid_casrn` | 400 | — | — | This CASRN's check digit doesn't match; a digit is probably mistyped. |
| `study_exists` | 409 | study | M1 | A study of this chemical already exists ({id}). Open it instead. |
| `study_not_found` | 404 | study | M1 | There is no study {id}. It may have been deleted. |
| `study_id_has_suffix` | 400 | — | — | A study's id is the DTXSID alone. … |
| `identity_changed` | 409 | — | — | The lookup now gives a different chemical than the one you confirmed. … |
| `identity_exists` | 409 | — | — | This study already has its chemical's identity. … |
| `identity_incomplete` | 400 | — | — | The chemical's name is missing from what was confirmed. … |
| `identity_lookup_unreachable` | 503 | — | — | The chemical lookup service ({service}) could not be reached. … |
| `identity_not_found` | 404 | — | — | {service} has no chemical with the DTXSID {id}. … |
| `identity_unconfirmed` | 400 | — | — | Confirm the chemical before going on … |
| `run_in_flight` | 409 | process | P1 | Process is running on this study (since {time}). Wait for it to finish. |
| `confirm_mismatch` | 400 | — | — | The id you typed doesn't match this study's id. Nothing was deleted. |
| `changed_since_preview` | 409 | — | — | The study changed after you reviewed what would be deleted. … |
| `format_changed` | 409 | — | — | The report format this id brings changed since you looked. … |
| `list_failed` | 500 | — | — | The list of studies can't be read … |
| `structure_unavailable` | 404 | — | — | PubChem did not return a structure picture. |

(Long texts are shortened with "…"; the full words are in the code.)

### 2.3 `safeguards/acts.py` — whether an act may run now

- **`require_data_session(dtxsid, store=None)`** — **R6**: no data act on a
  session whose data is not its own. A companion (`published_clone.json`) →
  `read_only_session`; a report over several studies (`studies.json`) →
  `report_has_no_data` (details: the members). A session that does not exist
  yet passes (the act's own checks apply). Reads two small files; never creates
  the folder.
- **`require_legal(dtxsid, act, store=None)`** — **C1**: derives
  `WorkflowEngine.state()` and raises `PhaseRefusal` when `act` is not in its
  `legal_actions`, naming the phase, what is allowed and `NEXT_STEP`. Returns
  the state.
- **`require_method_chosen(dtxsid)`** — **C1 D1**: `MethodNotChosen` unless
  `chosen_by_person(read_pin(dtxsid))`. Writes nothing.
- **`require(dtxsid, act, store=None, *, method=False)`** — all of them, in
  order: R6 (every act in `Action` is a data act), the phase, then, with
  `method=True`, the method choice. Only *running Process* passes `method=True`
  (the statistics, the BMDs and the text depend on the method); materializing
  sections from an existing Process cache does not.
- **`require_deletable(dtxsid)`** — removing a session's folder: never a
  companion (`read_only_session`), never one of the studies a report composes
  (`member_of_report`, found through `document_definition.report_of_member`,
  with the study's key from the report's `studies.json`). A report session may
  be deleted: its studies stay.

### 2.4 `safeguards/sections.py` — C2: owned content is never overwritten by a machine

`ownership_policy(req: WriteRequest)` is the write policy the front ends pass to
the section write gate. Called only when a write would change the text:

| Prior section | Who writes | Forced? | Outcome |
|---|---|---|---|
| absent, or not owned | anyone | — | written (prior archived) |
| owned | anyone | yes | the reason is required (`reason_required` if empty); then written, the event marked `forced` |
| owned | **system** (Process) | no | apical section with `on_owned=REVIEW`: **knocked down** (written, approval withdrawn, `review` marker, `needs-re-bless`); any other: **held** (not applied; a `hold` event with the held text's hash) |
| owned **and locked** (approved, edited, ingested) | person | no | refused: `section_owned` ("reopen it and say why") |
| owned, not locked (released, PROTECTED stands) | person | no | written: a person's explicit act is what releasing it was for |

Plus the acts' own preconditions: `require_reason(reason, key, verb)` (empty
→ `reason_required`), `owned(key, act)`, `reason_required(key, verb)`.

### 2.5 `safeguards/inputs.py` — what a person states

- `require_valid_design(dtxsid, fields)` — every field must be a design field
  and every value in its controlled vocabulary
  (`pipeline.study_design.design_field_errors` over `bmdx_pipe.VOCABULARIES`).
- `require_valid_experiment_metadata(dtxsid, given)` —
  `experiment_metadata_errors`: the shape `{experiment: {field: value}}`;
  every experiment must be one the dataset has; every *new* value must be in
  its vocabulary. A value the experiment already carries is not a new
  statement (the dataset's own inferred values pass through). Strain's
  vocabulary is per species, so a strain is checked against every species'
  strains.
- A refusal is `facts_invalid` (422) listing **every** problem at once, and
  nothing is written.

### 2.6 `safeguards/sources.py` — no Background without its sources

- `require_sources(dtxsid, bg_data)` — before the model runs: ATSDR and IRIS
  must have been reached (`bg_data.unreachable_sources`), else
  `background_sources_unreachable` (503, details: which).
- `require_references(dtxsid, result)` — after: paragraphs
  (`background_empty`) and references (`background_no_references`): prose with
  no references has nothing behind its `[n]` citations.

### 2.7 `safeguards/publish.py` — the publish gate

`require_publishable(dtxsid, store=None, *, draft=False)` — the publish
readiness (1.8); when it is closed, `publish_blocked` (409, details: the keys
and the blocking list), unless `draft=True`, the named override, which logs a
warning and returns the readiness.

### 2.8 `safeguards/guarded.py` — the front ends' entry point

Same names and signatures as the core, each with its checks first:

| Guarded function | Checks | Then calls |
|---|---|---|
| `require_add_files(dtxsid)` | R6, ADD_FILES | — (the upload routes write the files) |
| `require_reset(dtxsid)` | R6, RESET | — (the pool-reset route) |
| `remove_pool_file(dtxsid, filename)` | R6, REMOVE_FILE | `pipeline.pool_state.remove_pool_file` |
| `validate_step` | R6, VALIDATE | `workflow.steps.validate_step` |
| `resolve_step` | R6, RESOLVE | `workflow.steps.resolve_step` |
| `confirm_metadata_step` | R6, CONFIRM_CLASSIFICATION | `workflow.steps.confirm_metadata_step` |
| `integrate_step` | R6, INTEGRATE | `workflow.steps.integrate_step` |
| `approve_experiment_metadata` | R6, STATE_DATASET_FACTS, `require_valid_experiment_metadata` | `pipeline.metadata_approval.approve_experiment_metadata` |
| `record_study_design` | R6, STATE_DATASET_FACTS, `require_valid_design` | `workflow.steps.record_study_design` |
| `require_state_dataset_facts` | R6, STATE_DATASET_FACTS | — |
| `generate_animal_report_step` | R6, APPROVE | `workflow.steps.generate_animal_report_step` |
| `run_process`, `run_document`, `process_step`, `document_step` | R6, PROCESS, **method chosen** | the core's Process |
| `materialize_result_sections`, `materialize_summary` | R6, PROCESS | the core step with `policy=ownership_policy` |
| `write_section(…, **kw)` | — | `workflow.section_writes.write_section(…, policy=ownership_policy)` |
| `accept_section_step` | — | the core step |
| `release_section_step` | a reason when the section is approved | the core step |
| `restore_section_step` | a reason unless restoring the current version | the core step with `policy=ownership_policy` |
| `discard_section_step` | the section exists; not locked (`section_owned`); a reason | the core step |

### 2.9 What the core does without the safeguards (the notebook's view)

| Situation | Through the safeguards | Core alone (notebook) |
|---|---|---|
| Integrate while the validation found errors | `phase_not_allowed` | merges (the dataset is then inert: the phase still reads VALIDATION_ERRORS) |
| Process before integration | `phase_not_allowed` | Process fails on the missing dataset |
| Process with a method set by default | `method_not_chosen` | runs under the default pin |
| Process materializes over an approved apical section | knocked down for re-review | overwritten, the prior archived |
| Summary over a person's Summary | held | written, the prior archived (its own rule still keeps it off a Summary it did not generate) |
| Reopen / restore / discard without a reason | `reason_required` | done, no reason recorded |
| Design value outside the vocabulary | `facts_invalid` | written as given |
| Background with ATSDR/IRIS unreachable | `background_sources_unreachable` | drafted without them |
| Render with stale LLM sections | `publish_blocked` (CLI: `--draft` overrides) | rendered |
| Any data act on a companion or a multi-study report | `read_only_session` / `report_has_no_data` | done |

What is the same for both: every write archived, the atomic merge,
`ValidationOutOfDate`, the egress guard, the BMD hard-stop, the pins' integrity.

---

## Part 3 — The shared web routes

The FastAPI app (`web_routes/background_server.py`) serves the old front-end's
routes (behind the wall, not described here), the Bookshelf, and the new
interface's `/api/v2` routes. Every data route acts through the safeguards:

| Route | Safeguard |
|---|---|
| `POST /api/upload-bm2`, `/api/upload-csv`, `/api/upload-zip` (with `?dtxsid=`) | `require_add_files` (R6, ADD_FILES), then `invalidate_pool_artifacts` when the study had progressed |
| `POST /api/pool/validate/{id}` | `guarded.validate_step` |
| `POST /api/pool/resolve` | `guarded.resolve_step` |
| `POST /api/pool/confirm-metadata/{id}` | `guarded.confirm_metadata_step` |
| `POST /api/pool/integrate/{id}` | `guarded.integrate_step` |
| `POST /api/pool/materialize-sections/{id}` | `guarded.materialize_result_sections` |
| `DELETE /api/pool/{id}/files/{filename}` | `guarded.remove_pool_file` |
| `POST /api/pool/reset/{id}` | `guarded.require_reset` |
| `POST /api/session/reset/{id}` (delete the whole folder) | `acts.require_deletable` |
| `POST /api/experiment-metadata/{id}` | `guarded.approve_experiment_metadata` (vocabularies included) |
| `POST /api/generate-animal-report/{id}` | `guarded.generate_animal_report_step` |
| `POST /api/process-integrated/{id}` | `guarded.run_process` (method chosen) |
| `POST /api/generate` (Background, SSE) | `sources.require_sources` before the model, `require_references` after; a refusal is an `error` event carrying `error_body` |
| `POST /api/generate-genomics-narrative` with `force` | `sections.require_reason` |
| regenerate a genomics organ over a person's text | `sections.require_reason` |
| `POST /api/session/save-section`, `/api/session/approve`, `/api/session/unapprove`, `/api/session/discard-section`, `/api/session/{id}/restore` | `guarded.write_section`, `accept_section_step`, `release_section_step`, `discard_section_step`, `restore_section_step` |
| `POST /api/prompts/{section}/runs/{id}/{run_id}/use` (a prompt-workshop run becomes the section) | `guarded.write_section` |
| `GET /api/preview/{id}/download`, `POST /api/export-overleaf-bundle` (with a `dtxsid`) | `publish.require_publishable` (409 with `blocking`) |
| `GET /api/workflow/{id}/state`, `/section-readiness`, `/publish-readiness` | reads: the derived state, nothing refused |

A refusal a route does not catch is caught by the app's exception handler
(`refusal_handler` for `StepError`, `GuardViolation`, `MethodProfileError`,
`DefinitionPinError`, `LLMEgressBlocked`) and answered with
`web_routes.refusal_response.refusal_response(exc)` = `error_body(exc)` with its
status. Never a bare 500 for a refusal.

---

## Part 4 — The command line (`tooling/generate_report.py`)

The reference driver of the whole workflow. **Guarded**, like the browser: in
`main()`, before each step, `safeguards.acts.require(dtxsid, Action.X, store)`:

| Step | Check |
|---|---|
| import files | ADD_FILES |
| validate | VALIDATE |
| confirm metadata | CONFIRM_CLASSIFICATION |
| integrate | INTEGRATE |
| `--design` | `apply_design(…, guarded=True)` → `guarded.record_study_design` |
| `--experiment-metadata` | `apply_experiment_metadata(…, guarded=True)` → `guarded.approve_experiment_metadata` |
| method | without `--method-profile`: `_require_method_choice` (refuses unless a person chose the pin, and prints the suggested profile) |
| animal report | APPROVE |
| process | PROCESS with `method=True`; `process(…, policy=ownership_policy)` |
| `--background` | `background(…, policy=ownership_policy, guarded=True)`: an owned Background is refused before the model runs; the sources are required |
| summary | `summary(…, policy=ownership_policy)` |
| render | `publish.require_publishable(…, draft=args.draft)` |

**The named, logged overrides**:
- `--method-profile NAME` (or `newest`) — the person's method choice;
- `--force --reason TEXT` — replace a Background a person owns (archived first,
  the reason in its history);
- `--draft` — render past the publish gate (logged as a warning).

A refusal ends the run as `SystemExit("step failed (<status>): <message>\n
<plain words>")`, with "(or pass --draft)" for `publish_blocked`.

The same helpers (`gr.validate`, `gr.integrate`, `gr.apply_design`, …) are what
the notebook calls, **without** `guarded=True` or a policy.

---

## Part 5 — The notebook

`notebooks/workflow_walkthrough.ipynb` (built from `_nb_cells_data.py` and
`_nb_cells_report.py`): the workflow one step per cell, each preceded by its
purpose, its implementation, what it reads and writes, how it fails. It calls
`tooling.generate_report` helpers and `workflow.steps` directly. Its §0 lists the
safeguards as a layer and says it bypasses them; the cells for the study
design, the experiment metadata, the Background and the publish gate each say
what the app and the command line refuse that the notebook does not. After
every cell that changes the session it prints the derived phase and legal
acts: shown, not enforced.

---

## Part 6 — The new interface

### 6.1 Its parts

| Part | Where | What it is |
|---|---|---|
| The front end | `ui/` (React 19, antd 6, TanStack Query, react-router), built to `ui/dist`, served at `/app` by `web_routes/app_mount.py` | the screens |
| Its server side | `ui_api/` | the read model, the studies, the study acts, the vocabularies, the refusals in the interface's terms |
| Its routes | `web_routes/v2_routes.py`, `v2_section_routes.py`, `studies_routes.py` under `/api/v2` | thin: parse, call `ui_api` or `safeguards.guarded`, serialize |
| The contracts | `docs/ui-redesign/MODULES.md` §4, `modules/*/contract.md`, `contracts/` (captured real answers) | what the routes serve |

`ui_api` is a front end like `web_routes`: it may import `safeguards`; nothing
below it may import it.

**Every `/api/v2` route** uses the route class `V2Route`
(`web_routes/v2_routes.py`): any exception the handler raises (including
FastAPI's own path and body validation) is answered by `envelope_response`
with the **§4.2 envelope** `{"error": {code, status, message, say, fix,
details}}` from `ui_api.refusals.explain`. Unexpected ones are logged.

### 6.2 `ui_api.refusals` — the safeguards' explanations in the interface's terms

- `STUDY_REFUSALS`: the codes of the Studies module's own acts (Part 2's last
  rows), each with a place; `register(STUDY_REFUSALS)` runs at import, so
  `explain` takes them at their word.
- `PLACE_MODULE`: the module that clears each place:

  | Place | Module | The module's screen |
  |---|---|---|
  | study | M1 | Studies |
  | files | M2 | Study files |
  | dataset | M3 | Combined data |
  | facts | M4 | Study facts |
  | method_and_document | M5 | Method and report definition |
  | data_review | M6 | Data review |
  | process | P1 | Process |
  | sections | D1 | Review the report |
  | publish | D1 | Review the report |
  | handoff | D4 | Word and Overleaf |

- `explain(exc)` = `safeguards.refusals.explain(exc)` with `fix` translated to
  the module. **The read model, the studies list and every v2 envelope use it**,
  so the TypeScript always receives a module id (`M1`…`D6`) or null, never a
  place. A test checks every catalog code reaches the interface that way
  (`tests/unit/test_ui_api_layering.py`).
- `say(code, **fields)` — a code's plain words before it is raised (a delete
  the screen will not offer).

### 6.3 The read model: `GET /api/v2/studies/{id}/state`

`ui_api.read_model.study_state(dtxsid)` is **the only source of a study's
workflow state for the interface**. It composes what the core derives, and
**has no side effects**: `ReadOnlyDiskPoolStore` refuses every write (no folder
created, no fingerprint re-scanned, no file id minted), the pins are read and
never ensured, the method is resolved with `probe=False` (no Wine check). A
malformed id is a 400 `invalid_study_id` envelope; an unknown one answers
`{"id": …, "exists": false}`.

Its fields:

| Field | From | Meaning |
|---|---|---|
| `kind`, `chemical_dtxsid`, `chemical_dtxsid_from`, `relations` | `ui_api.studies.session_kind` | study / report / member / companion / other; parent, members, companion, twin, other sessions of the chemical |
| `phase` | `WorkflowEngine.state()` | the derived phase |
| `legal_actions` | the same | the acts legal now. **`[]` on a companion or a report** (R6 refuses them all, so the interface offers none) |
| `identity` | `identity.json` | name, CASRN, DTXSID, `short_name` (the abbreviation); null fields are "not stated" |
| `pins.method` | `method_pin_state` | `pinned`, `name`, `hash`, `series`, `mode`, `pinned_by` (a person / default), `pinned_at`, `deviations`, `unchecked`, live `mismatches` with the dataset's recorded analyses; **`suggestion: {name, why}` until a person has chosen**; `error` (an envelope body) if the profile no longer resolves |
| `pins.definition` | `definition_pin_state` | which definition renders (`name`, `source`: session/study/era/template), the pin, `snapshot`, `drift`, `error` |
| `processed` | the NTP cache exists | whether Process has run |
| `sections[]` | `sections_state` | one row per section, in the rendering tree's order (instance families expanded from disk, genomics also from interpretation caches): `key`, `title`, `kind`, `approvable`, `instance_of`, `region`, `has_file`, `enabled`, `blocked_by`, `approved`, `facts`, `user_edited`, `stale`, `regenerated` (+ `say`), `wording_review`, `source`, `model`, `version`, `version_status`, `maturity`, `review` (+ `say`), `machine_may_write`, and **`accept: {allowed, code, say}`** |
| `readiness.publish` | `publish_readiness_state` | `ready`, **`complete: false`** (until C6), `checks` (what was looked at), `items` (one `block` per stale LLM section, with `say` and `fix: "D1"`) |
| `members[]` | `members_state` | for a report: each study's key, id, existence, phase, processed, own publish readiness |
| `stands` | `ui_api.studies.stands` | `{phase, say, next: {say, fix}}`: where it stands in plain words and the next step with its module |

**The accept verdict** (`_accept_verdict`), in order: not approvable
(`not_approvable`: supplied text, cache-only LLM text, or programmatic text
shown with its tables) → not enabled (`blocked`: "can be approved only once the
study has been processed / the Background is approved / …") → no saved file
(`not_saved_as_section` for Methods and the BMD summary, `no_saved_text`
otherwise) → already accepted with nothing changed (`already_accepted`) →
allowed. The interface offers Accept only when `allowed`, and shows `say`
otherwise.

**`stands`** (one derivation, shared with the studies list): a companion has no
phase and no next step; a report waits for its studies ("Finish the member
studies", M1) then "Review the report's sections" (D1); a study's next step is
by phase (EMPTY/UPLOADED/VALIDATION_ERRORS → M2, VALIDATED → M3,
INTEGRATED/APPROVED → "Process the data", P1); once processed, "Review the
report's sections" (D1). "Publish the report" (D3) is offered only when the
publish readiness is served **complete and ready**, which it never is before
C6: the interface never says "ready to publish" on a partial check.

### 6.4 The Studies module's backend (M1)

`ui_api.studies` (reads) and `ui_api.study_steps` (acts), behind
`web_routes/studies_routes.py`:

| Route | Function | What it does |
|---|---|---|
| `GET /api/v2/studies` | `list_studies` | every session, grouped by chemical (newest change first; primary session, members, companion, others); each row a `study_row` |
| `GET /api/v2/studies/{id}` | `study_summary` | one row plus its detail (banner, format, relations) |
| `GET /api/v2/studies/{dtxsid}/creation-check` | `creation_check` | is the id free, which sessions of the chemical exist, which report format it would be written in (`format.hash`) |
| `GET /api/v2/chemicals/{dtxsid}` | `lookup_chemical` | PubChem (CTX when configured); cached 10 minutes so the confirm and the create agree |
| `GET /api/v2/chemicals/{dtxsid}/structure.png` | `chemical_structure` | the picture |
| `POST /api/v2/studies` | `create_study_step` | create |
| `PUT /api/v2/studies/{id}/identity` | `record_identity_step` | fill a missing identity |
| `GET /api/v2/studies/{id}/delete-preview` | `delete_study_dry_run` | what a delete deletes, keeps, loses; the token |
| `POST /api/v2/studies/{id}/delete` | `delete_study_step` | delete for good |

A **study row** (`study_row`) carries `kind`, `relations`, `identity`, `stands`,
`processed`, `last_changed`, `format`, `published`, `bookshelf`, and
**`actions.delete: {allowed, code, say}`**, plus `notes`: a part that cannot be
read (a damaged file) is named in `notes` and the row still lists. One damaged
session never hides the others.

**The delete verdict** (`delete_verdict`) asks **`safeguards.acts.require_deletable`**
(never a companion, never a member of a report) and adds the interface's own
`run_in_flight` (`running_since`, which answers None until C5 serves a run
lock). The same verdict feeds the row (so the button is disabled with the
reason), the dry run and the delete.

**Creating a study** (`create_study_step`), in order:
1. the id is a bare DTXSID (`study_id_has_suffix`);
2. the format the person saw is still the one the id gives (`format_seen.hash`
   vs `format_hash`, else `format_changed`);
3. the identity: either **confirmed** (`_confirmed_identity`: the person ticked
   the confirmation (`identity_unconfirmed`), only a *looked-up* identity is
   accepted, the name is present (`identity_incomplete`), a typed CASRN passes
   its pattern and check digit (`invalid_casrn`), the lookup still gives the same
   chemical (`identity_changed`), and, if the service does not list this DTXSID
   for the compound, the person said they checked it) — or explicitly
   **pending** (`_pending_identity`: the DTXSID alone; refused if a lookup in
   the last 10 minutes *did* find the chemical: confirm it instead);
4. **atomic creation**: `identity.json` and `meta.json` written in a hidden
   `.creating-…` folder, then renamed into place. A rename fails on a non-empty
   folder, so of two people creating the same study exactly one succeeds; the
   other gets `study_exists`. No files, no pins: the phase after is EMPTY.

**Filling an identity later** (`record_identity_step`): refuses a missing study,
a companion or a report, and an identity already named (`identity_exists`);
the check and the write are one act under a per-study lock (`_study_lock`), so
of two people saving at once one wins and the other is refused.

**Deleting** (`delete_study_dry_run` then `delete_study_step`):
- the dry run reads only; it lists by plain category what goes (files, sections,
  dataset, statements, identity, pins, views, runs, log), what stays (the
  deliverables in `output/<id>/`, the study's own definition, a report's member
  studies), the approvals lost and the disk freed; `strength: "irreversible"`;
  `type_to_confirm` = the id; `preview_token` = a SHA over every path, size and
  modification time;
- the delete runs under the study lock: re-runs the dry run (so every refusal
  holds), checks the typed id (`confirm_mismatch`; case-sensitive, outer
  spaces ignored) and the token (`changed_since_preview`: anything changed after
  the review refuses), renames the folder out of the store in one step
  (`.deleting-…`), forgets what the server holds in memory for it
  (`pipeline.pool_globals.forget_session`), then removes it. A study that
  vanishes mid-read is `study_not_found`, never a server error.

### 6.5 The section routes (C2)

`web_routes/v2_section_routes.py`, all through **`safeguards.guarded`**:

| Route | Calls | Safeguard |
|---|---|---|
| `POST /api/v2/studies/{id}/sections/{key}/accept` | `guarded.accept_section_step` | — (the text never changes) |
| `POST …/{key}/release` `{reason}` | `guarded.release_section_step` | a reason when approved |
| `POST …/{key}/restore` `{version, reason}` | `guarded.restore_section_step` | a reason; the ownership policy |
| `GET …/{key}/history` | `section_writes.section_history` (read-only store) | — |
| `GET …/{key}/history/{version}` | `section_writes.read_version` | — |

Each answers the fields the screen needs, plus `noop: {code, say}` for a
success that did nothing (`already_accepted`, `not_approved`,
`already_current`). A study that does not exist answers `section_not_found`
and nothing is created. Discard is not offered here (C2 D4).

### 6.6 `GET /api/v2/vocabularies`

`ui_api.vocabularies.vocabularies_payload`: every controlled vocabulary of
`bmdx_pipe.VOCABULARIES` as one self-describing entry (`{label, values}`, or
`{label, depends_on, by}` for strain by species), labelled with the names
BMDExpress gives these fields in a data file's header; plus the identifier
patterns a field checks as it is typed (study id, session id, DTXSID, CASRN,
DOI). The browser keeps no copy of either.

### 6.7 The TypeScript: how the screens use all this

**The client** (`ui/src/api/client.ts`, `errors.ts`). Every call resolves with
the typed body or rejects with an `ApiError` carrying the §4.2 body: a non-2xx
answer is parsed into the envelope; a body that is not one becomes
`unexpected`; a server that cannot be reached becomes `unreachable` with its
own plain words; a broken run stream has its own. Screens render the error
with `<Refusal>`, never by reading `message`. `noopOf(body)` reads a "success
that did nothing".

**`useStudyState(id)`** (`kit/useStudyState.ts`) — the only reader of a study's
workflow state: a TanStack query on `GET …/state`. A screen learns the phase,
the legal acts, the sections, the readiness and the next step **from here
only, and never computes, guesses or stores any of them**.
`useStudyMutation(id, fn)` re-reads the study's state after **every** mutating
call, whether it succeeded or was refused (a refusal may follow a change made
elsewhere). While a run is in flight (once C5 serves `run`) it polls every 3 s.

**`<Refusal error|noop studyId>`** (`kit/Refusal.tsx`) — the refusal explainer:
an antd error Alert with the backend's **`say`** first; a link **"Go to
<module> to fix this"** built from `fix` (`kit/modules.ts`: module id → title →
route `/studies/{id}/{slug}`); the code, status, verbatim message and details
behind "Show the technical details". A noop renders as an info Alert "Nothing
was changed". It never shows a bare technical message first.

**The modules map** (`kit/modules.ts`): M1 Studies (`/studies`), M2 Study files
(`files`), M3 Combined data (`dataset`), M4 Study facts (`facts`), M5 Method and
report definition (`pins`), M6 Data review (`data-review`), P1 Process
(`process`), P2 What a change affects (`impact`), D1 Review the report
(`review`), D2 Written sections (`writing`), D3 Preview and downloads
(`preview`), D4 Word and Overleaf (`handoff`), D5 Report setup (`setup`), D6
Bookshelf (`bookshelf`). This is how every `fix` becomes a link.

**The study frame** (`shell/StudyFrame.tsx`, `StudyHeader.tsx`,
`StudyOverview.tsx`, `nextStep.ts`):
- the header shows the name, the id, the kind (a companion: "read-only:
  nothing here is processed or approved", with its twin; a member: "part of a
  report", with the report; a report: its studies and each one's stage), the
  stage in plain words (`stands.say`), and **the next step** from
  `stands.next` as a button to its module; a report names its studies not yet
  processed;
- a missing fact (chemical name, CASRN, short name) is a **`<Pending>`** mark
  "[name pending]" whose popover says why and links to the module that fills
  it: never silence, never a guess;
- **the Steps card** lists all ten acts in the workflow's order
  (`kit/words.ts` `ACTION_ORDER`, `ACTION_WORDS`: plain label, module,
  destructive). An act in `legal_actions` is a link to its module; the first
  legal act of the next step's module is the primary button, tagged "Next";
  **every other act is visibly disabled with the reason** ("Not available now:
  the study is at "Files checked"."). A phase this page does not know offers
  nothing. A report and a companion get no Steps card (a report's files are its
  studies'; a companion is read-only);
- **"What stops the report being published"** (`kit/PublishReadiness.tsx`)
  lists the readiness items (Blocks / Check, each with its module link); while
  `complete` is not true, an empty list reads "Nothing found by the checks
  below", followed by a warning naming what was checked and what was not
  (approval of every section, "[… pending]" details, member studies, pins):
  **never "ready to publish" on a partial check**;
- **the Method and report definition card** shows the pin as the backend
  reports it: "not chosen" in gold, or the name with "fixed" / "follows the
  newest", and **"chosen by default, not by a person"** when `pinned_by` says
  so (that study's Process would be refused with `method_not_chosen`);
  deviations and unchecked items; the live mismatches as a warning; the
  definition's source and drift. Never a silent default.

**Section marks** (`kit/SectionStatus.tsx`, `sectionMark.ts`): one tag per
section from what the backend serves (stale, regenerated, version status,
approved, facts, `machine_may_write`, the `accept` verdict); the worst news
wins the mark (stale > regenerated > needs re-approval > final > approved >
owned > not approvable > waiting > cannot approve yet > draft), the rest is in
its tooltip; changed data-derived words are counted and their codes shown as
details. Whether a section can be approved is never worked out in the
browser: it is `accept.allowed`.

**Fields** (`kit/VocabField.tsx`, `IdField.tsx`, `checkId.ts`):
- a vocabulary field offers only the served values: no free text; a dependent
  field (strain) is closed until its parent is chosen; a value that no longer
  fits is flagged, never silently cleared; it never starts with a value the
  person did not choose; if the vocabularies cannot be loaded, nothing can be
  chosen. This mirrors on the screen what `safeguards.inputs` enforces on the
  server: the screen prevents, the server refuses;
- an id field checks as it is typed with the backend's pattern, explains why a
  value is wrong (a suffixed study id, a DOI pasted as a link, a CAS check
  digit), upper-cases a DTXSID visibly, offers "Use DTXSID…?" for a pasted
  CompTox address (never fills it without the click), and is never reported
  good when its rule could not load.

**Confirm-or-undo** (`kit/ConfirmAct.tsx`): for an act that changes or
destroys something, the consequences come from the **backend's dry run**,
fetched when the person clicks: reversible (done, then Undo), costly (a dialog
listing what goes, what stays, the approvals lost, the cost), irreversible (the
same, and the person types the study id). An unknown strength is treated as
irreversible; if the dry run cannot be had, the act is not offered. A
`preview_token` is passed to the act; `changed_since_preview` re-reads the dry
run and says why. `disabled` + `disabledReason` show why an act is not
available.

**Provenance** (`kit/Provenance.tsx`): every fact a screen shows says where it
comes from: Stated, From the files, Inferred, Standard design (assumed), In
conflict, with a link to state or settle it; an unknown origin is shown in red
as unchecked.

### 6.8 End to end: the Studies module (built)

**S1, the studies list** (`modules/m1/StudiesList.tsx`): one row per chemical
from `GET /api/v2/studies`, its sessions as child rows; each value (kind,
stands, next step, format, Bookshelf) is the backend's; a missing name or CASRN
is a Pending mark linking to the study; "Create a study" appears only where
the backend says `can_create`. There is no delete in the list.

**S2, a new study** (`modules/m1/NewStudy.tsx`):
1. the DTXSID is typed into an `IdField` (study id); `creation-check` says
   whether the id is free and which format it brings; a refusal
   (`study_id_has_suffix`, `invalid_study_id`) is a `<Refusal>`;
2. the chemical is looked up (`useChemicalLookup`, no automatic retry): an
   unreachable service (`identity_lookup_unreachable`) offers "Try again" or
   creating with the identity pending (`PendingCreate`); a DTXSID the service
   does not know (`identity_not_found`) offers the same;
3. the person sees the chemical (`ChemicalCard`: name, CASRN, structure), the
   format, and must tick the confirmation (and, where the service does not
   list the DTXSID for the compound, say they checked it); the Create button
   stays closed until everything required is in;
4. the create posts `confirmed`, `dtxsid_checked_by_person`, `format_seen`;
   every refusal of 6.4 comes back as a `<Refusal>` (`study_exists` adds an
   "Open it" button; `identity_changed` clears the confirmation and re-runs the
   lookup; `format_changed` re-reads the creation check and says the format
   changed).

**S3, a study's page** (`modules/m1/StudyPage.tsx` + the shell's panels): the
row and its detail, the sessions it belongs with, the workflow panels of 6.7,
and **the delete card**: `<ConfirmAct act="delete_study" disabled={!actions.delete.allowed}
disabledReason={actions.delete.say}>` — so on a companion or a member the button
is disabled with the safeguards' own words ("This is the rat study of the
report DTXSID1020431. Deleting it would break that report."); otherwise the
dry run lists what goes and stays, the person types the id, and the delete
presents the token. A study deleted while its page is open reads as "deleted".

### 6.9 Worked examples: one refusal, all the way through

**Process before the method is chosen.** A study whose `method_profile.json`
says `pinned_by: "default"`:
1. its state serves `pins.method.pinned_by: "default"` and a `suggestion`; the
   Method card shows "chosen by default, not by a person";
2. a Process request reaches `safeguards.guarded.run_process` →
   `require(dtxsid, PROCESS, method=True)` → R6 passes, the phase allows
   PROCESS, `require_method_chosen` raises `MethodNotChosen`;
3. `ui_api.refusals.explain` → `{code: "method_not_chosen", status: 409, say:
   "Choose the analysis method … The one it has now (ntp-5day-2021) was set
   automatically, not chosen by a person, so it must be confirmed or changed. …",
   fix: "M5", details: {pin: {name, pinned_by, mode}}}`;
4. the browser's `ApiError` → `<Refusal>` shows the words and "Go to Method and
   report definition to fix this"; `useStudyMutation` re-reads the state.
   The command line prints the same words and the suggested
   `--method-profile`.

**Integrating while the file check found errors.** `guarded.integrate_step` →
`require_legal` → `PhaseRefusal(INTEGRATE, VALIDATION_ERRORS)` → `say`:
"Combining the files into one dataset isn't possible yet. The file check found
errors. Fix what it lists (remove or replace the files it names), then run the
file check again.", place `files` → module M2.

**Process over an approved apical section.** `guarded.materialize_result_sections`
passes `ownership_policy`; the gate sees the printed content changed under an
approved `bm2_body-weight` → knocked down: new version, approval withdrawn,
`review: {why: "numbers_changed", since_version: 3}`, event
`reprocess/needs-re-bless`. The state then serves that section with
`approved: false`, `review.say` ("The study's data changed the numbers this
section prints since it was approved. Read it again, then approve it again."),
`accept.allowed: true`; its mark reads "needs re-approval".

**Reopening an approved section without a reason.** `POST
…/sections/summary/release {}` → `guarded.release_section_step` →
`require_reason` → `reason_required` (400), `fix: "D1"`: "Please say why. The
reason is kept with the section's history." Nothing changed.

**Deleting a member study.** Its row's `actions.delete` is `{allowed: false,
code: "member_of_report", say: "This is the rat study of the report …"}` from
`require_deletable`; the Delete button is disabled with those words. A direct
`POST …/delete` re-runs the dry run and is refused the same way. The old
`/api/session/reset` route applies the same rule.

### 6.10 What is built, and what is not yet

Built and merged: the kit and the shell (Gate 0), **M1 Studies**, the backend of
**C1** (the act table, enforced by the safeguards) and **C2** (owned content,
section history, the v2 section routes), the read model, the vocabularies.

Not built yet (the screens are placeholders, `shell/ModulePlaceholder.tsx`
"This page is not built yet"): M2 Study files, M3 Combined data, M4 Study facts,
M5 Method and report definition, M6 Data review, P1 Process, P2 What a change
affects, D1–D6. Their backend acts exist (the shared routes of Part 3, all
guarded); the `/api/v2` routes for them do not. Two client functions are
**proposed and mocked only**: the generic dry run `GET …/dry-run/{act}` (C8) and
the guarded Process event stream `POST …/process` (C5). Not served yet: the run
record and lock (C5; `run_in_flight` answers nothing until then), the
data-approval readiness and a complete publish check (C6), currency over every
input (C7), undo (C8). The board (`BOARD.md`) tracks each.

---

## Part 7 — The tests that pin all this

| Test | What it pins |
|---|---|
| `tests/unit/test_safeguards_layering.py` | no core package and no notebook cell imports `safeguards`; `safeguards` imports no front end |
| `tests/unit/test_ui_api_layering.py` | nothing below the interface imports `ui_api`; every place has a module; every catalog code reaches the interface with a module or null |
| `tests/unit/test_workflow_legality.py` | each guarded entry point refuses outside its phase; the core step does not |
| `tests/unit/test_workflow_legal_actions.py`, `test_workflow_engine.py`, `test_workflow_phase_characterization.py` (+ fixtures) | the act table, `NEXT_STEP`, the phase derivation |
| `tests/unit/test_integration_basis.py` | the basis and `out_of_date` |
| `tests/unit/test_section_writes.py`, `test_section_history_primitive.py`, `test_workflow_steps.py`, `test_version_cause_snapshots.py` | the gate's rules, hold/knock-down, history, accept/release/restore/discard |
| `tests/unit/test_refusals.py` | every code explained with words and a place; `register` |
| `tests/unit/test_method_profile.py`, `test_generate_report_c1.py`, `test_process_step.py`, `test_document_step.py` | the method choice, CLI and steps |
| `tests/unit/test_safeguards_inputs_sources_publish.py` | vocabularies, the Background's sources, the publish gate and `--draft` |
| `tests/unit/test_c2_cli_and_genomics.py` | the CLI's Background and the genomics overrides never lose a person's text |
| `tests/integration/test_session_reset_deletable.py` | the delete rule on the old reset route |
| `tests/unit/test_read_model.py`, `test_studies.py`, `test_studies_steps.py`, `test_vocabularies.py`, `tests/integration/test_v2_routes.py`, `test_v2_section_routes.py`, `test_studies_routes.py` | the interface's backend and its envelopes |
| `ui/src/**/*.test.ts(x)` (252 tests) | the kit, the shell, M1, and the mocks against the backend's real answers (`contracts/`, `fixtures/real/`) |

---

## Appendix — Where to look

| Question | File |
|---|---|
| What phase is this study in, and why? | `workflow/engine.py` `state`, `workflow/phases.py` `derive_phase` |
| What is allowed now? | `workflow/phases.py` `LEGAL_ACTIONS`, `NEXT_STEP` |
| Who refuses it? | `safeguards/acts.py` `require` |
| What does the refusal say? | `safeguards/refusals.py` `REFUSALS`, `explain` |
| Which screen fixes it? | `ui_api/refusals.py` `PLACE_MODULE`, `ui/src/kit/modules.ts` |
| Can a machine overwrite this section? | `workflow/ownership.py` `is_owned`, `safeguards/sections.py` `ownership_policy` |
| What happened to this section, and why? | `history/<key>/index.jsonl`, `workflow/section_writes.py` `section_history` |
| What does the interface know about a study? | `ui_api/read_model.py` `study_state` |
| What may the person do on the Studies screens? | `ui_api/studies.py` `study_row` (`actions`), `ui_api/study_steps.py` |
