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

## Modules

| Module | Stage | On it | Spec signed | Done signed | Blocked by |
|---|---|---|---|---|---|
| Kit + skeleton | **merged** into `ui-redesign` (ddab30c, 2026-10-15) | | Gate 0 (MODULES §4–5) | orchestrator-verified; no maintainer demo yet | |
| C1 legal actions enforced | building (`ui-c1-be`) | ui-backend-engineer | 2026-10-15 (D1 = B) | | |
| C2 owned content protected | building (`ui-c2-be`); merges after C1 | ui-backend-engineer | 2026-10-15 | | C1 merge |
| C3 saves merge and check | not started | | | | Q10 |
| C4 side-effect-free reads | spec | ui-backend-engineer (spec stage) | | | |
| C5 Process guarded, observable | not started | | | | Q11, Q12 |
| C6 derived readiness | not started | | | | Q2–Q5 |
| C7 currency covers every input | not started | | | | Q2, Q5 |
| C8 dry-run and undo | not started | | | | Q9 |
| M1 Studies | front-end built (`ui-m1-fe` e93455b, 210 tests); backend building (`ui-m1-be`) | ui-backend-engineer | 2026-10-15 | | |
| M2 Study files | spec | ui-interaction-designer | | | C3, C4, C8 (specified against them) |
| M3 Integration and the dataset | not started | | | | |
| M4 Study facts | not started | | | | |
| M5 Method and document pins | not started | | | | |
| M6 Data approval | not started | | | | |
| P1 Process | not started | | | | |
| P2 Change impact | not started | | | | |
| D1 Review | not started | | | | |
| D2 Narrative generation | not started | | | | |
| D3 Preview and deliverables | not started | | | | |
| D4 Hand-off and return | not started | | | | |
| D5 Configurator | not started | | | | |
| D6 Bookshelf hook-up | not started | | | | Q17 |
