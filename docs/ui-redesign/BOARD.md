# The board

The state of every module of the new interface (see `TEAM.md`). Kept by the
orchestrator.

## Gate 0: the module map and the contracts

In progress (2026-10-14). Stage 1: three workflow analysts, in parallel:

| Step group | Analysis | On it |
|---|---|---|
| Data preparation (steps 1–8) | `modules/gate0-data/analysis.md` | done 2026-10-14 (two key findings re-checked by the orchestrator) |
| Process (step 9) | `modules/gate0-process/analysis.md` | done 2026-10-14 (pin-before-refusal re-checked by the orchestrator) |
| Document (steps 10–13) | `modules/gate0-document/analysis.md` | done 2026-10-14 (two key findings re-checked by the orchestrator) |

Stage 2: `MODULES.md` drafted 2026-10-14 (modules, shared kit, shared contracts,
skeleton, core track, 18 merged questions). **Signed 2026-10-14** (decisions in `MODULES.md` §8; still open: §9).

## Data-integrity findings (outside any one module)

- **FIXED 2026-10-17 (bmdx-pipe a32498d, on its `master`, not pushed):** a study table
  with empty cells was silently left out of the combined dataset. The workbook
  converter wrote a missing value as an empty cell; BMDExpress's parser refuses an
  empty cell and the Java helper then skipped the whole table with a warning. Now
  the converter writes NaN (as the CSV converter already did), and the Java helper
  stops with an error on any table it can't read. NIEHS-10's six workbooks alone now
  give all 12 experiments (before: 7). No session in the store holds a workbook in
  `files/`, so no existing dataset was affected.
- **FIXED 2026-10-17 (rlm-bmdx 0dec6e3, merged e8b9816):** integration could fail
  after writing, leaving "integrated, current" over a dataset no read accepts. The
  merged dataset is now checked against the schema before anything is recorded, and
  a failure puts the old dataset back. Reproduced and verified on a scratch NIEHS-10.
- **Open:** the `.bm2` read cache (LMDB, 1 GB map) cannot hold a 251 MB project
  (`MDB_MAP_FULL` on an empty cache), so that project is re-read at every check.

## Core track: the safeguards (2026-10-23)

- **C1, C2 and R6 now live in the content branch's `safeguards/` layer** (ADR-0031),
  merged here with content winning everywhere (`git diff
  package-layout-workflow-engine ui-redesign` outside the interface's paths shows
  only the additions below). The core steps no longer guard themselves. The
  interface acts through `safeguards.guarded`; the v2 section routes do.
- **The interface's backend is `ui_api/`** (moved from `workflow/`: `read_model`,
  `studies`, `study_steps`, `vocabularies`). It is a front end: it may import
  `safeguards`, and nothing below it imports it (`tests/unit/test_ui_api_layering.py`).
- **Refusals:** `ui_api.refusals` registers the M1 codes into the shared catalog and
  translates `fix` (a workflow place) into the module (`PLACE_MODULE`). The §4.2
  envelope and the TypeScript are unchanged.
- **Kind-2 additions to core files, still open for the maintainer's ruling:**
  - `document_definition`: `ERA_TITLES` (now with `eras/niehs-proposed`, words not
    signed), `ALTERATION_WORDS`, `era_title`, `definition_outline`;
  - `chem_resolver`: the lookup additions;
  - `pool_globals`: `_csv_uploads`, `forget_session`;
  - `background_server`: the v2, studies and app routers.
- **Lost in the merge (content wins):**
  - (Fixed 2026-10-24, content b2916e4.) The old full reset briefly refused only
    R6. Deleting a session now has one rule for every route,
    `safeguards.acts.require_deletable`: never a companion, never a member of a
    report; a report session may go. `ui_api.studies.delete_verdict` uses it and
    adds the run in flight. `reset_session_step` is gone (nothing called it).
  - The bookshelf and prompt-workshop relation predicates are the content's
    again; `ui_api.studies` keeps its own strict readers.

## Picked up again (2026-11-18)

No interface work since 2026-10-24. The content branch moved on meanwhile; `main`
(through `9b28fa3`) was merged here on 2026-11-18 with no conflict and no change
to `ui/` or `ui_api/` (tag `pre-merge-main-2026-11-18` is the state before). The
app runs from this worktree on 9000; 9100 opens the interface and 9300 the
Bookshelf (`tooling/port_alias.py`); the notebook is on 9200. The port list in
`TEAM.md` is out of date on this point.

What the content branch added that the plan below does not yet cover:

- **Two workflow places have no module** (`safeguards.refusals.PLACES` gained
  `bmd_review` and `knowledge_base`; `ui_api.refusals.PLACE_MODULE` has neither).
  `tests/unit/test_ui_api_layering.py::test_every_place_has_a_module` fails on it.
  - BMD review: a reviewer rejects a flagged apical BMD (UREP); the publish gate
    waits on a pending flag (ADR-0033).
  - Knowledge base: which named knowledge base a study's interpretation reads
    (ADR-0034).
  - **Open for the maintainer:** a module each, or folded into D1 and M5.
- **Study parameters are recorded or stated, never assumed** (ADR-0035). Process
  is refused (`study_parameters_incomplete`, fix: the facts place, so M4) until
  species, strain, route, vehicle, duration, dosing days, dosing schedule and dose
  unit are each recorded by the data or stated. The engine derives them
  (`GET /api/workflow/{id}/study-parameters`); stating merges, and null withdraws
  (`workflow.steps.record_study_design`). M4 has no screen, so today a fact can
  be stated only from the command line or the notebook. BPAF and Triclosan are
  stopped on dosing days and schedule.
- **The read model does not know about them.** `stands.next` for BPAF reads
  "Review the report's sections" while its report is refused and two facts are
  missing.
- **A report states the computation that ran** (ADR-0036); a study processed
  before it is refused until processed again. The Bookshelf shows the reason.
- `tests/unit/test_read_model.py::test_a_broken_snapshot_is_reported_and_the_sections_still_list`
  fails: the engine's knowledge-base check raises on a broken definition pin
  before the read model can report it.
- The C3, C4 and M2 specs were written on 2026-10-15/16 against the code of that
  day. ADR-0031, 0032 and 0035 have since done part of C3 (design saves merge and
  are checked against the vocabulary). **Each needs a re-check against today's
  code before it is signed.**

## The demo path (2026-11-18): the two weeks to about 2026-12-02

The maintainer's goal: a **demo of this interface** to the study team on NIEHS-12
(1,2-dichlorobenzene), data brought in and checked beforehand. Decided by the
maintainer on 2026-11-18:

- one **demo path spec** stands in for the per-module specs and sign-offs:
  `modules/demo/spec.md` (**draft, awaiting the maintainer; nothing is built, and
  nothing is to be started until the maintainer says so**);
- two setups to switch between, a finished report and a live copy; the live copy
  is **in the same store under another id**, and the pair is set apart in the
  Studies list as **"Demo"**;
- the review page follows the maintainer's idea (the Bookshelf view with controls
  beside it, and a "make the Word document" button): **yes, but not started yet**;
- source files and code paths are shown on the API page (`/docs`, by workflow
  step and in plain words since main `54de38d`; this branch adds
  `web_routes/api_guide_v2.yaml`, `1be3f31`) and in the notebook.

**Built and merged on 2026-11-18** (the maintainer said "proceed"):

| Part | State |
|---|---|
| The live copy (`tooling/demo_copy.py`, on `main`) | in the real store: `DTXSID6020430_live`, `_live_rat`, `_live_mouse`, at its start state |
| The Demo block, the switch link, the reset | merged (`1ab7cd7`, `3f9963a`) |
| S1 Combined data, S2 Process (`ui/src/modules/m3`, `p1`; `ui_api/dataset.py`, `process_run.py`, `long_acts.py`) | merged (`ef672ca`); one live run through the real app: Combine 34 s, Process 189 s |
| S3 Written sections, S4 Citations (`ui/src/modules/d2`; `ui_api/writing*.py`) | merged; the Background written live once on the real live copy (48 s) |
| S5 Review with the Bookshelf and Word (`ui/src/modules/d1`; `ui_api/review.py`) | merged 2026-11-19 (approve and reopen only); the whole live path run through the real app, both studies, then approve, reopen, Word (54 s) and PDF |
| "Show only this block" on the Demo block; the stage reads "Animals accounted for"; the Bookshelf page, Word and PDF kept until the report changes (`main` `977a9f7`) | merged 2026-11-19 |
| The adversarial pass over the whole path, the rehearsals | not done |

`ui_api/runs.py` records the long act under way on a study in this process (it
stands in for C5's run lock); the state serves `run` and, for the pair, `demo`.
The built pages are mapped in `ui/src/shell/ModulePage.tsx`.

Open, from the build (for the maintainer; details in `modules/demo/spec.md` §9):
- a row of a results table is not linked to its endpoint in the dataset by
  record, only by name: organ-weight rows read "not recorded for this row";
- the Clinical Observations table stops at the experiment (the dataset holds no
  experiment under that assay's name);
- the Background's public sources (ATSDR) answer only some of the time from here;
- `test_read_model::test_a_broken_snapshot…` and
  `test_ui_api_layering::test_every_place_has_a_module` still fail, as before.

A route added from now on needs an entry in `web_routes/api_guide*.yaml`
(`tests/unit/test_api_guide.py` refuses one without).

The module table below is the long plan; for these two weeks the demo path
outranks it.

## Modules

| Module | Stage | On it | Spec signed | Done signed | Blocked by |
|---|---|---|---|---|---|
| Kit + skeleton | **merged** into `ui-redesign` (ddab30c, 2026-10-15) | | Gate 0 (MODULES §4–5) | orchestrator-verified; no maintainer demo yet | |
| C1 legal actions enforced | **merged** into `ui-redesign` (623f003, wave 1); **enforced by `safeguards` since 2026-10-23** | – | 2026-10-15 (D1 = B) | orchestrator-verified (full suite: only the known docx failure; guard 11/11); maintainer demo pending | |
| C2 owned content protected | **merged** (623f003, wave 1); **policy in `safeguards.sections` since 2026-10-23**; its section tests now seed INTEGRATED studies (C1 refuses Process before integration) | – | 2026-10-15 | orchestrator-verified; maintainer demo pending | |
| C3 saves merge and check | spec ready (`modules/c3/`), **awaiting the maintainer** (D1–D9) | – | | | |
| C4 side-effect-free reads | spec ready (`modules/c4/`), **awaiting the maintainer** (D1–D7) | | | | C1 merged ✓ |
| C5 Process guarded, observable | not started | | | | Q11, Q12 |
| C6 derived readiness | not started | | | | Q2–Q5 |
| C7 currency covers every input | not started | | | | Q2, Q5 |
| C8 dry-run and undo | not started | | | | Q9 |
| M1 Studies | **merged with its fix round** (2e3bfcd): test (`modules/m1/test.md`) and review (`modules/m1/review.md`) findings fixed; a missing CAS number is asked for (2026-10-16); demo on 9200 | – | 2026-10-15 | **awaiting the maintainer's done sign-off**; open: delete during Process (C5 or stopgap) | |
| M2 Study files | spec **revised** to the 2026-10-16 answers (`modules/m2/`); awaiting the maintainer on Q-M2-3a, 12–15 | – | | | C3, C4, C8 (specified against them) |
| M3 Integration and the dataset | not started; **carry:** `integrate_step` overwrites a confirmed `identity.json` with the request body (`workflow/steps.py:432`, M1 review 4) | | | | |
| M4 Study facts | not started | | | | |
| M5 Method and document pins | not started | | | | |
| M6 Data approval | not started | | | | |
| P1 Process | not started; **carry:** a pending identity becomes "Test Compound" in Process (`pipeline/process_integrated.py:1554-1562`); must be "[name pending]", never a silent default | | | | |
| P2 Change impact | not started | | | | |
| D1 Review | not started | | | | |
| D2 Narrative generation | not started | | | | |
| D3 Preview and deliverables | not started; **carry:** a pending identity previews as "Test Article" / "000-00-0" (`rendering/preview_surface.py:139-140`); must be "[… pending]" | | | | |
| D4 Hand-off and return | not started | | | | |
| D5 Configurator | not started | | | | |
| D6 Bookshelf hook-up | not started | | | | Q17 |
