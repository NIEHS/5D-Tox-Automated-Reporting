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
| C1 legal actions enforced | **stopped (budget)** at step 7 of 9; steps 1–6 committed on `ui-c1-be`, step 7 uncommitted in the worktree | – | 2026-10-15 (D1 = B) | | API budget |
| C2 owned content protected | **built** (`ui-c2-be` f44c6b0, 8 commits; smart/guard/full green but the known failure); merges after C1 | – | 2026-10-15 | | C1 merge |
| C3 saves merge and check | not started | | | | Q10 |
| C4 side-effect-free reads | **stopped (budget)** before writing the spec; resume to get it | – | | | API budget |
| C5 Process guarded, observable | not started | | | | Q11, Q12 |
| C6 derived readiness | not started | | | | Q2–Q5 |
| C7 currency covers every input | not started | | | | Q2, Q5 |
| C8 dry-run and undo | not started | | | | Q9 |
| M1 Studies | front-end built (`ui-m1-fe` e93455b); backend **stopped (budget)**: wip commit on `ui-m1-be`, fixtures uncommitted | – | 2026-10-15 | | API budget |
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
