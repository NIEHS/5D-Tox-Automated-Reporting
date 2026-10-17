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

## Modules

| Module | Stage | On it | Spec signed | Done signed | Blocked by |
|---|---|---|---|---|---|
| Kit + skeleton | **merged** into `ui-redesign` (ddab30c, 2026-10-15) | | Gate 0 (MODULES §4–5) | orchestrator-verified; no maintainer demo yet | |
| C1 legal actions enforced | **merged** into `ui-redesign` (623f003, wave 1) | – | 2026-10-15 (D1 = B) | orchestrator-verified (full suite: only the known docx failure; guard 11/11); maintainer demo pending | |
| C2 owned content protected | **merged** (623f003, wave 1); its section tests now seed INTEGRATED studies (C1 refuses Process before integration) | – | 2026-10-15 | orchestrator-verified; maintainer demo pending | |
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
