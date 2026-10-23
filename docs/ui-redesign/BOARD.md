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
  - The old full reset (`/api/session/reset`) refuses only R6. It no longer
    refuses a member of a report (the delete does). Raise it on the content
    branch if wanted.
  - The bookshelf and prompt-workshop relation predicates are the content's
    again; `ui_api.studies` keeps its own strict readers.

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
