# A new user interface, from scratch: the handoff

Written 2026-10-14 for an agent starting fresh on the design of a new user
interface for this application. It explains what the workflow is for, how it is
implemented, where its checkpoints are, and what the people who use it need. It
does this without describing the interfaces built before.

**The interface's most important purpose is idiot-proofing** (the maintainer,
2026-10-14). The workflow can already be driven step by step from a notebook. What
a user interface adds is keeping a person who is not a programmer from going
wrong. Judge every design choice by that first (§2).

**Read `WALL.md` first.** The existing front-ends are off limits: the design comes
from the workflow, not from them. There are two exceptions:
- the **Bookshelf**, which is kept (§8);
- the **Jupyter notebook** (`notebooks/workflow_walkthrough.ipynb`), the direct
  view of the workflow and its code.

Companion files:
- `WALL.md`: what is walled, and what is allowed;
- `TEAM.md`: the team of agents that builds the interface, its flow and sign-offs
  (`BOARD.md` is the state of the work);
- `http-api.md`: the backend routes that exist today.

Further reading, in order:
1. `CONTEXT.md`: purpose, glossary, why the architecture is shaped as it is;
2. **the notebook**, `notebooks/workflow_walkthrough.ipynb` (cells in
   `notebooks/_nb_cells_*.py`). It is the workflow one step per cell, each
   explained: purpose, implementation (module:function), reads → writes, how it
   fails. It shows the workflow and its code with none of the guarding. Run it to
   see every step's real output (§9).
3. ADRs 0014, 0015, 0018, 0020, 0021, 0027, 0029;
4. `docs/headless-report-generation.md`: the whole workflow driven from the
   command line and over HTTP.

---

## 1. What the application does

NIEHS publishes **biological potency reports** of 5-day studies. A chemical is
dosed at several levels, and two kinds of response are measured:
- **apical endpoints**: body and organ weights, clinical chemistry, hematology,
  hormones, tissue concentration, clinical observations;
- **transcriptomics**: gene-expression dose response, reduced to a benchmark dose
  (BMD) per gene and per GO gene set.

The report is long and strictly conventional:
- NTP statistical tables, BMD summaries;
- Methods, results, a transcriptomic interpretation, a summary;
- appendices.

It is published as a book on NCBI Bookshelf. **The application turns a study's
data files into that report**, delivered as Word (`.docx`), BITS XML (the
Bookshelf deliverable), HTML, and LaTeX/PDF.

Twelve real published reports (RR-8, NIEHS-02 … 10, 12, 13) are reproduced from
their public data and checked against the books. They are the test bed. The
application must also work for **new, unpublished studies**, which use the 2026
format.

## 2. Who uses it, and what they need

These are the maintainer's stated requirements. They are the brief.

### Who
- **The maintainer.** Today's primary operator generates reports and is offloading
  the report team's work to the tool. They retire in one to three years.
- **The successor**, a **toxicologist, not a programmer**. The browser
  interface is the durable, hand-off interface. Everything a step needs must be
  operable and explained in the browser.
- **Other people trying it** on their own data (§9, workspaces).

### What the interface is for: idiot-proofing

**The interface's most important purpose is idiot-proofing.** Its users are not
programmers, and the workflow's mistakes are expensive. Examples:
- a wrong file classification flows into every table;
- an unstated design fact silently becomes the standard default;
- a stale LLM section gets published;
- an approved section is overwritten;
- a session is reset by accident.

The backend already refuses much of this, through derived phases, legal actions,
guards, currency and the publish gate (§4). The interface's job:
- make the right next step obvious and the wrong ones impossible;
- check what a person enters before anything runs (controlled vocabularies,
  valid ids, required facts);
- explain every refusal and every block in the person's terms;
- confirm or undo destructive acts;
- never let a default pass silently.

The notebook is the same workflow without any of this.

### What the application is, and is not
- **Not an editor** (ADR-0018). It generates, previews, lets a person
  provisionally approve, and hands off. Human authoring happens outside, in Word
  or Overleaf, and comes back:
  - Overleaf: a round trip (ADR-0005);
  - Word: reading tracked changes is an open gap.
- **The author is the authority.** Generated text is a draft. A section a person
  has approved or edited is theirs: no machine overwrites it silently (ADR-0015).
  Regenerating is an explicit act.
- **One evolving report with history**, not a tree of versions (ADR-0020). Every
  approved section keeps its past versions, which can be restored.

### How it must behave
- **The preview must look like the deliverable** (fonts, pagination, tables): a
  PDF of the actual deliverable's own typesetting, for whichever target is being
  handed off:
  - Word: docx → PDF;
  - Overleaf: LaTeX → PDF.

  An HTML view is a content proof, not a faithful preview. In this sandbox,
  docx → PDF is LibreOffice (`docx2pdf`); the maintainer prefers OnlyOffice
  `x2t` on the host.
- **Process blocks, intentionally.** Processing (statistics, BMD modelling,
  genomics, narratives; one to four minutes cold) runs as one foreground
  operation, and the maintainer wants the interface to wait for it. Do not turn
  it into a background job as a "UX win". A progress indicator inside the wait
  was not ruled out.
- **Nothing is invented.**
  - Report facts (species, strain, route, vehicle, duration, group sizes,
    units, sex) come from the data or from a person's statement. Anything
    inferred is flagged.
  - A missing piece shows as a visible "[… pending]" placeholder, never as
    silence or a guess.
  - The one sanctioned fallback is the standard design (SD rats, gavage, corn
    oil, 5 days; inhalation for ppm), and it is logged as such.
- **Deviations are errors, sized plainly.** When a reproduction differs from the
  published book, say so as an error, with its size. Never soften it to "info".
- **Report variation is declared, not coded** (ADR-0029). Structure, phrasing,
  numbering, series facts and appendices come from YAML document definitions
  (§7). A person can see and edit these declarations; there is no per-report
  renderer code.
- **The study team states what the data can't say:**
  - authors and contributors;
  - publication details (report number, DOI, date);
  - the strain designation;
  - the study design;
  - experiment metadata a file name doesn't carry;
  - the files deposited with the report.

  A "configurator" for these, and for the document definition, the styles and
  the saved report views, was the maintainer's stated direction. Its backend
  exists (§7).
- **Data policy** (dev/test/prod split). Unpublished study data may reach only
  the walled NIEHS LLM gateway. The app's egress guard enforces this
  (`styling_export/llm_endpoints.py`, fail-closed). This sandbox is *dev*:
  published data only, by policy.
- **Naming.** Don't call the new interface a "wizard"; that was a throwaway
  word. A real name is to be chosen.
- **Component library: Ant Design** (`antd`, React; the maintainer's choice,
  2026-10-14). Its business-application components serve the idiot-proofing:
  - forms with declared validation rules;
  - `Steps` for an ordered flow;
  - tables;
  - `Popconfirm` and modals for destructive acts;
  - `Result` and `Alert` for explaining a refusal.

  npm is reachable from the sandbox, so it can be installed and built here.

---

## 3. The workflow

Two halves (see the memory note *Data vs Document seam*):
- **DATA** ingests files and computes statistics and BMDs.
- **DOCUMENT** reduces that data into a report by a declared structure.

LLMs help on both sides but decide nothing structural.

The reference driver is `tooling/generate_report.py`. Its `main()` runs every
step in order and calls the same core functions any front-end should call
(`workflow.steps`, which `workflow.engine.WorkflowEngine` drives). Each step reads
and writes files in the session directory (§5). The steps:

| # | Step | Core function | Java | LLM | Writes | Phase after |
|---|---|---|---|---|---|---|
| 1 | Bring in files | `generate_report.import_files`; HTTP upload routes | – | – | `files/` | UPLOADED |
| 2 | Validate | `workflow.steps.validate_step` (bmdx_pipe `validate_pool`) | `ExportBm2` | – | `_fingerprints.json`, `validation_report.json` (issues, coverage matrix); long-format CSVs pivoted, originals kept in `_originals/` | VALIDATED or VALIDATION_ERRORS |
| 3 | Resolve conflicts | `resolve_step(issue_index, chosen_file_id)` | – | – | `precedence.json` | – |
| 4 | Confirm each file's platform and data type | `confirm_metadata_step` | – | – | file headers, `_fingerprints.json` | – |
| 5 | Integrate | `integrate_step(identity)` | `IntegrateProject`, `ExportCategories`, `ExportGenomics`, `JsonToBm2` | fallback only (experiment metadata) | `integrated.json` (THE dataset), `integrated.bm2`, `_category_lookup.json`, `genomics.sidecar.json`, `identity.json` | INTEGRATED |
| 6 | State the facts the data lacks | `generate_report.apply_design` / `apply_experiment_metadata` / `apply_front_matter` / `record_abbreviation`; `pipeline.deposit.record_deposit`; `genomics.efdr.record_efdr` | (eFDR) | – | `study_design.json`, `metadata_approved.json`, `front_matter.json`, `identity.json`, `deposit.json`, `efdr.json` | – |
| 7 | Pin the method and the document | `generate_report.method_profile` (`pipeline.method_profile`), `generate_report.document_definition` (`document_model.definition_pin`) | – | – | `method_profile.json`, `document_definition.json` + `.yaml` | – |
| 8 | Approve the data | `generate_animal_report_step`: every animal accounted for across files | – | – | `animal_report.json` | APPROVED |
| 9 | Process | `process_step` (`pipeline.process_integrated.run_process`), then `materialize_result_sections` | `RunApicalBmds`, `ExportGenomics` | ✓ | `_cache_<unit>_<hash>.json`, `bm2_<slug>.json` result sections, `references.json`, `session.duckdb`, `session_parquet/` | – |
| 10 | Background, Summary | `generate_report.background` (LLM + PubChem/ATSDR/IRIS; optional); `materialize_summary` | – | ✓ | `background.json`, `summary.json` | – |
| 11 | Review sections | `accept_section_step` (lock), `release_section_step` (reopen, with a reason) | – | – | the section files; `history/` | – |
| 12 | Publish gate | `WorkflowEngine.publish_readiness()` | – | – | – | – |
| 13 | Render | `rendering.preview_surface.render_preview` (on demand) / `materialize_preview` (persisted); LaTeX through `rendering.latex_export` | – | – | deliverables (§8) | – |

Notes on the steps:
- **Content preparation** (ADR-0021) also exists as its own step,
  `workflow.steps.document_step`. Process runs it eagerly; `document_step`
  re-prepares the prose without recomputing the data.
- **A report over several studies** (NIEHS-12/13: rat + mouse) composes member
  study sessions; each is built on its own first. The parent session's
  `studies.json` lists them (`rendering.report_compose`, ADR-0029 §9).
- **Who writes what** (`workflow.content_origin`):
  - LLM: Background, Methods, Summary, the apical BMD narrative and the genomics
    interpretations;
  - programmatic: the apical result prose and every table.

  A reprocess treats the two differently (§4.4).
- **Expect a cold run** of three to five minutes (Process dominates). A warm run
  reuses the caches and takes about a minute.

## 4. Checkpoints: what the workflow guarantees, and where

Everything below is **derived from what is on disk, every time**; nothing is
stored as state (CONTEXT.md invariant 3). A front-end asks and renders the answer.
It never computes or sets a phase itself. Transient "in progress" states belong
to the front-end alone.

### 4.1 The data phase and its legal actions (`workflow/phases.py`, `workflow/engine.py`)

`WorkflowEngine(dtxsid).state()` returns `{phase, legal_actions, next_step,
artifacts, completeness}` (also `GET /api/workflow/{id}/state`). The phase is
`derive_phase(artifacts)`; the first rule that matches wins:

1. no files → **EMPTY**;
2. never validated (a file change deletes the validation report) → **UPLOADED**;
3. validation errors → **VALIDATION_ERRORS**;
4. not integrated, or integrated from a different validation → **VALIDATED**;
5. integrated, no `animal_report.json` → **INTEGRATED**;
6. otherwise → **APPROVED**.

Since C1 (2026-10-15) a stale section no longer moves the phase (staleness is a
section matter: currency and the publish gate, §4.4). Rule 4's "integrated from a
different validation" is `workflow/integration_basis.py`: integration records the
basis it was built from in `integration_basis.json` (step 5), and the state reads
`integration: current | out_of_date | unrecorded`.

| phase | legal actions | next step |
|---|---|---|
| EMPTY | ADD_FILES | ADD_FILES |
| UPLOADED | ADD_FILES, REMOVE_FILE, RESET, VALIDATE | VALIDATE |
| VALIDATION_ERRORS | the above, RESOLVE, CONFIRM_CLASSIFICATION | VALIDATE |
| VALIDATED | the above, INTEGRATE | INTEGRATE |
| INTEGRATED, APPROVED | all, adding STATE_DATASET_FACTS, APPROVE, PROCESS | — |

Process is legal from INTEGRATED on: the data approval informs and gates nothing
(decision Q3).

**Enforcement is the safeguards' (ADR-0031, 2026-10-23).** The table is derived
state in the core (`workflow.phases.LEGAL_ACTIONS`); refusing an act is the
`safeguards` layer's. The interface's backend (`ui_api/`, the v2 routes) calls
`safeguards.guarded` (the core steps' names and signatures), never
`workflow.steps` directly. It refuses:
- an act outside this table (`phase_not_allowed`, naming the phase, what is
  allowed now and the next step);
- Process until a person chose the method profile;
- every data act on a published book's companion or a report over several
  studies (R6, `safeguards.acts.require_data_session`: `read_only_session`,
  `report_has_no_data`; the read model serves `legal_actions: []` for them);
- a machine's write over a person's text, and a missing reason;
- facts outside the vocabularies, and a Background without its sources;
- shipping past the publish gate.

Every refusal is explained by `safeguards.refusals.explain`; the interface's
§4.2 envelope is that explanation with its `fix` (a workflow place) translated
to the module that clears it (`ui_api.refusals`).

`completeness`, from the validation coverage matrix, gives each platform's
readiness and what it is missing. For example, an apical platform needs both
study data (.csv/.txt) and a `.bm2`.

Changing the files after progress invalidates what depended on them
(`pipeline.pool_state.invalidate_pool_artifacts`), and the phase follows.

### 4.2 Section catalog and readiness (`workflow/section_catalog.py`, `workflow/section_readiness.py`)

The report's sections, as workflow units, are **derived from the document tree**,
not listed in code (`GET /api/workflow/{id}/sections`):
- singletons: background, methods, summary, bmd_summary;
- families: `bm2_<slug>` (apical), `genomics_<organ>_<sex>`;
- display-only group narratives and front-matter rows.

What unlocks what is one data table, `KIND_UNLOCK`:
- methods unlocks once processed;
- summary unlocks once the background or any result is approved;
- genomics needs the knowledge base;
- the rest have no dependency.

`GET /api/workflow/{id}/section-readiness` returns each section's derived
readiness.

### 4.3 Facts and guards: who may change what (`workflow/labels.py`, `guard.py`, `ownership.py`; ADR-0015)

People assert **facts** about content: `approved`; a maturity ratchet
first_draft → working_draft → final; `protected`; `published`. The system
derives the consequence, the **guard**, on two axes:
- **against machines:** a hard refusal (an LLM regeneration may not overwrite);
- **against people:** a soft, visible "protected" mark.

`ownership.may_machine_write` is the one predicate. Accepting a section is
`accept_section_step`; reopening it is `release_section_step` with a reason, and
the reason is kept in the version trail.

**Since C2 (2026-10-15) every write to a section file goes through one gate,**
`workflow.section_writes.write_section`. A machine's write over content a person
owns (approved, PROTECTED, edited, ingested: `ownership.is_owned`) is held and
recorded, never applied. For an apical result section whose numbers changed, the
approval is withdrawn with a `review` marker instead (the deliverable already
prints the new numbers). An unchanged write writes nothing. A person's write over
locked content needs an explicit, reasoned act. Restoring a past version is
`restore_section_step`; discarding is `discard_section_step` (old route and pool
reset only). Every event is one line of `history/<key>/index.jsonl`, the source
of the report changelog (C11). The read model serves each section's `maturity`,
`review` and `version_status`.

### 4.4 Currency and the publish gate (`workflow/currency.py`, `reprocess.py`)

When the inputs behind content change, that content is **stale**. Stale content
cannot advance to final or published until a person re-blesses it. A reprocess
then splits by authorship:
- **programmatic** sections just refresh their numbers;
- **LLM** sections are rewritten visibly, marked `regenerated` with a reason, and
  knocked below approved.

`publish_readiness()` → `{can_publish, blocking: [{section_key, reason}]}`. The
command line refuses to render while it is closed, unless given `--draft`.

### 4.5 Pins: the method and the document are fixed per study

A session pins:
- **its analysis method profile** (ADR-0027): `method_profile.json` names one of
  `profiles/*.yaml`, which are immutable and hashed;
- **its document definition** (ADR-0029 §12): `document_definition.json` and the
  composed `.yaml` snapshot.

Both have a mode:
- *track* follows the newest, recording each change in `history/`;
- *fixed* stays put.

The resolved method settings carry, per value, the layer that set it (default →
profile → study overlay → request). Anything the profile asks for that the tool
cannot do is reported as a **deviation**. A mismatch between the `.bm2`'s
recorded analysis and the profile is a warning.

### 4.6 Caches: Process recomputes only what changed

Each Process unit (`ntp`, `bmds`, `genomics`, `charts`, `methods`,
`interpretation_<organ>_<sex>`, `sections`, …) writes `_cache_<unit>_<hash>.json`.
The hash covers its inputs, including the method settings' signature, so a
re-run with nothing changed is fast. A changed pin recomputes what depends on it.
The content-preparation skip guard is `.prepare_content.*`.

### 4.7 Tests that pin these checkpoints

All of these live under `tests/unit/`, unless marked:
- `test_workflow_phase_characterization.py`, `test_workflow_legal_actions.py`,
  `test_workflow_engine.py`, `test_workflow_steps.py`,
  `test_workflow_authoring_steps.py`;
- `test_section_catalog.py`, `test_section_readiness.py`,
  `test_workflow_labels_guard.py`, `test_workflow_ownership.py`,
  `test_workflow_currency.py`, `test_reprocess.py`;
- `tests/integration/test_workflow_state_route.py`, `test_session_lifecycle.py`,
  `test_pool_*.py`;
- the byte-for-byte Process oracle, `tests/integration/test_process_integrated_golden.py`.

Run them through `.claude/skills/bmdx-tests/run-tests.sh` (`guard`, `smart`,
`full`). One failure is known and expected:
`test_docx_generator.py::test_yaml_page_breaks_land_as_page_break_before`.

---

## 5. The session on disk: the contract a front-end reads

A session is a directory, `SESSIONS_DIR/<id>/`. The id is `DTXSID` followed by up
to 64 letters, digits, `_` or `-` (`common.dtxsid.validate_dtxsid`). The list of
sessions is the directory listing.

| File | Meaning | Written at step |
|---|---|---|
| `files/`, `_originals/` | the study's input files (as imported; originals of converted ones) | 1, 2 |
| `_fingerprints.json` | each file's detected platform, data type, tier | 2, 4 |
| `validation_report.json` | issues (severity), coverage matrix | 2 |
| `precedence.json` | a person's choice where files conflict | 3 |
| `integrated.json` | **the dataset** (BMDProject format); everything reads it | 5 |
| `integrated.bm2`, `_category_lookup.json`, `genomics.sidecar.json`, `files/*.sidecar.json` | the Java-side project, GO categories, per-animal metadata the pivot loses | 5 |
| `identity.json` | test article: name, CASRN, DTXSID, abbreviation | 5, 6 |
| `study_design.json`, `metadata_approved.json`, `front_matter.json`, `deposit.json`, `efdr.json` | what people state | 6 |
| `method_profile.json`, `document_definition.json`/`.yaml` | the pins | 7 |
| `animal_report.json` | the data approval: every animal accounted for | 8 |
| `_cache_*.json`, `.prepare_content.*` | Process results, by unit and input hash | 9 |
| `bm2_<slug>.json`, `background.json`, `summary.json`, genomics sections | **report sections**: content plus `approved`, `stale`, `regenerated` … | 9–11 |
| `references.json` | the bibliography | 9 |
| `session.duckdb`, `session_parquet/` | read-only query substrate over the study (ADR-0016; `/api/query`) | 9 |
| `history/` | past versions of sections and pins | throughout |
| `studies.json` | (a report over several studies) its member sessions | – |
| `published_clone.json`, `published_content.json`, `document.yaml` | (a published book's companion, §8) | – |
| `meta.json` | per-session settings (e.g. model choices) | – |

`SESSIONS_DIR/_prompts/` holds the versioned prompt templates (the prompt
workshop).

---

## 6. Code map for front-end work

| Package or file | What a front-end uses it for |
|---|---|
| `workflow/engine.py` | `WorkflowEngine(id).state()`, `.derive_section_readiness()`, `.publish_readiness()` |
| `workflow/steps.py` | every mutating step (§3); raises `StepError(status, message)` |
| `workflow/store.py` | `PoolStore` / `DiskPoolStore`: the state seam (fake it in tests) |
| `tooling/generate_report.py` | the reference sequence; `_resolve_identity`, `apply_*`, `process_async`, `render` |
| `pipeline/process_integrated.py` | `run_process` / `run_document`: the heavy computation and content preparation |
| `pipeline/session_store.py`, `pipeline/pool_state.py` | session files, invalidation |
| `document_model/` | the `DocNode` tree; definitions (`document_template`, `document_config`, `view_config`, `definition_pin`); the component catalog (`render_capabilities`) |
| `rendering/preview_surface.py` | `render_preview(id, surface)` → docx bytes / html / bits zip / bookshelf page; `materialize_preview` persists with history |
| `rendering/latex_export.py` | `load_session_data`: the data every surface renders from; the Overleaf bundle |
| `narrative/` | LLM writers (background, methods, summary, genomics); prompt workshop; session chat (ADR-0022) |
| `common/paths.py` | `SESSIONS_DIR`, `OUTPUT_DIR` (both overridable by environment variables) |
| `web_routes/` | the existing HTTP layer (`http-api.md`); `background_server.py` assembles the app |

The house rules for a route or any other driver:
- **Thin drivers.** Parse, call the core, serialize. No workflow logic in the
  route.
- **Derived state.** Never store a phase or a readiness value.
- **One source of truth.** Read `integrated.json` and its sidecars, never the
  raw files.
- **Tree-driven structure.** Structure and numbering come from the document
  tree.

## 7. Declarations a person can see and edit (the "configurator" material)

| Declaration | Where | Backend today |
|---|---|---|
| Document definition: structure, phrasing, series facts, appendices, numbering scopes | `templates/niehs-5day-report.yaml` (base grammar) → `templates/eras/*.yaml` (2018/2022/2023/2026) → `templates/studies/<id>/document.yaml` (a study's alterations); a session's own `document.yaml` | `document_model.document_config` (validated as a full tree build before it is saved); `/api/document-config[-default]/…`; `/api/document-structure/{catalog,parse,dump,validate}` |
| Layout styles (typography, page breaks) | `styles:` blocks | `/api/layout-style[-default]/…` |
| Report views (filters by organ, sex, assay, gene; charts) | per session | `document_model.view_config`; `/api/views/{id}[/{name}]` (render-time only, no reprocess) |
| Front matter (authors, contributors, publication, strain designation) | `front_matter.json` | `/api/document/{id}/front-matter` |
| Study design, experiment metadata | `study_design.json`, `metadata_approved.json` | `generate_report.apply_design` / `apply_experiment_metadata`; `/api/experiment-metadata/{id}`; values from the controlled vocabulary (`bmdx_pipe.VOCABULARIES`, ADR-0019) |
| Method profile | `profiles/*.yaml` (immutable; pinned per session) | `pipeline.method_profile` |
| Prompts for LLM sections | `SESSIONS_DIR/_prompts/` (versioned Jinja) | `/api/prompts/…` (critique chat, runs, blind model comparison) |
| BITS grammar, vocabularies | `vocab/` | – |

## 8. Render surfaces, deliverables, and the Bookshelf (kept)

### The surfaces
`render_preview(id, surface)` produces any of:
- **`docx`**: the Word deliverable, on the NTP template's styles;
- **`html`**: a content view;
- **`jats`**: one BITS XML book;
- **`bits`**: the chunked Bookshelf bundle, zipped;
- **`bookshelf`**: a Bookshelf reader-view facsimile.

LaTeX/PDF comes from `rendering.latex_export`, compiled with `tect`. All of them
read one document tree and one data dict (ADR-0006), so they cannot disagree on
content or numbering.

### The Bookshelf (kept; extend it freely)
- **`/Bookshelf`**: the shelf.
  - Published reports appear in order of publication, labelled with the date;
    unpublished ones follow below.
  - A report over several studies is one book.
  - Each published card links its **companion** ("Published content →").
- **`/Bookshelf/<id>`**: the report as an NCBI Bookshelf reader page.
  - The right rail offers PDF (docx → PDF) and Word downloads, a Compare link,
    and the companion or twin link.
  - The page says what it is: a preview (unpublished study); a generated version
    of an already-published report, for evaluating the pipeline; or the report
    as published (a companion).
  - The "Bookshelf" wordmark and "rlm-bmdx Report Series" link back to the
    shelf.
- **The companion** (`sessions/<id>_published`, `tooling/published_clone.py`): a
  published book's own content as a session.
  - It renders through every surface.
  - `--check` compares it with the book: 99.9–100% of words match, and every
    table and figure is numbered as in the book.
- **Code:** `web_routes/bookshelf_routes.py`, `rendering/bookshelf_preview.py`,
  `rendering/bookshelf_landing.py`, `rendering/published_clone.py`;
  tests `tests/unit/test_bookshelf_*.py`, `test_published_clone.py`.

### Comparing with the published books
The engine is `rendering/bits_compare.py`, which is allowed. It aligns two BITS
books section by section and block by block, with tables compared cell by cell.
The command-line drivers are `tooling/report_compare.py` and `tooling/report_qc.py`.

## 9. Environment

- **Start the app** with `./run-server.sh` (port 9000, bound to 0.0.0.0). It sets
  up:
  - JDK 21 and `BMDX_PROJECT_ROOT` for the Java helpers;
  - the LLM gateway and the CA bundle.

  `./run-server.sh --run CMD` runs any command with that environment.
- **Forwarded ports:** 9000 9100 9200 9300 9400 (`SANDBOX_PORT`).
  - 9000: the main app;
  - 9100: the maintainer's own JupyterLab. Leave it alone.
- **Workspaces:** `tooling/workspace.sh <name>` gives another person their own
  sessions (so their own Bookshelf), their own outputs and an app on 9300.
  - It also starts a JupyterLab on 9400, on the workspace's copy of the notebook.
    That copy builds the person's own uploaded data (its `uploads/` folder).
  - The person reaches a workspace by its ports; there is no authentication.
  - `tooling/workspace.sh <name> stop` stops it.
- **Python:** `.venv/bin/python`. The venv's `jupyter*` launcher scripts point at
  an old path; use `python -m …`.
- **Sandbox rules:** no network beyond an allowlist, no `apt`, never push (see
  `/workspace/CLAUDE.md`).
- **Driving the whole workflow headless:**
  `python -m tooling.generate_report <id> --files … --surfaces docx,html,bits`.
  `python -m tooling.build_published_reports` rebuilds the twelve published
  studies.

## 10. Open design questions, for the new interface to settle

Stated neutrally; none has an agreed answer.

0. **How each step is made fool-proof** (the first question for every screen):
   - what can a person get wrong there;
   - what does the backend already refuse;
   - what must the interface prevent, check or explain on top?
1. **How the steps group for a person.** Steps 1–8 are data preparation (ending
   in the data approval), 9 is computation, and 10–13 are the document. Which
   are separate screens, which are automatic, and which need a person's
   decision:
   - the conflicts in step 3;
   - the confirmations in step 4;
   - the statements in step 6;
   - the animal accounting in step 8?
2. **Where Process sits.** It is data computation, but it also prepares all the
   prose (ADR-0021 separates content preparation as its own step). How should a
   person see the difference between recomputing the data and re-preparing the
   text?
3. **Reviewing the data.** `integrated.json` is large. What should a person see
   to trust it? Options include the coverage matrix, the animal accounting, the
   per-field provenance (each field's authority depends on which file it came
   from), and the read-only SQL view (`session.duckdb`).
4. **The review unit.** Sections are approved one by one (the facts, guards and
   currency of §4). How does that look for 20+ sections, and how is a
   regenerated LLM section shown so a person re-accepts it knowingly?
5. **Preview.** It should be a faithful PDF of the target deliverable (§2), and
   making that PDF takes seconds. When is the HTML content view enough?
6. **The configurator.** How much of §7 does the person who builds reports
   touch, and how much the person who maintains the definitions?
7. **Hand-off and return.** How are Word and Overleaf reached, and how do
   changes made there come back (ADR-0005, ADR-0018)?
8. **People.** Today a workspace is a pair of ports and there is no login. Does
   the new interface need users, roles or sharing?
9. **Comparing with the published book.** For published studies, comparison is
   how the tool is evaluated. Where does it belong?
10. **The exploratory tools** in the backend: session chat (ADR-0022), prompt
    workshop, query view, literature crawl, knowledge graph. Which belong in the
    main interface?
