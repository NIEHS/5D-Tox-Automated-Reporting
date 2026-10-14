# The new interface's team: roles, flow, sign-offs

Set up 2026-10-14, at the maintainer's request: the new interface is built by a
**team of agents under an orchestrator**, with the independent parts ("modules",
in the plain sense: pieces of the interface that can be built separately, not a
technology's modules) **coded in parallel**. Read `WALL.md` and `HANDOFF.md`
first; this file says how the team works, not what it builds.

## Roles

The role definitions are in `.claude/agents/` (tracked on `ui-redesign`).

| Role | Agent | Produces |
|---|---|---|
| Orchestrator | the main session | the plan, every brief, the board, merges, commits; the only one who talks to the maintainer |
| Workflow analyst | `ui-workflow-analyst` | `modules/<m>/analysis.md`: per step, what a person can get wrong, what the backend refuses, what the interface must add |
| Interaction designer | `ui-interaction-designer` | `modules/<m>/spec.md` + `contract.md`: screens in `antd` terms, validation, refusals explained, acceptance criteria; the endpoints and shapes |
| Backend engineer | `ui-backend-engineer` | the module's endpoints in `web_routes/` (thin), any missing core logic in `workflow/`/`pipeline/`, with tests |
| Front-end engineer | `ui-frontend-engineer` | the module's screens (React + `antd`), built against the contract, with tests |
| Adversarial tester | `ui-adversarial-tester` | `modules/<m>/test-report.md` + the browser scripts: the acceptance criteria checked, then every way to go wrong tried |
| Reviewer | `ui-reviewer` | `modules/<m>/review.md`: wall, house rules, idiot-proofing, contract, tests, bugs; a verdict |

The orchestrator relays everything between roles; agents do not talk to the
maintainer and do not take instructions from each other's files.

## The flow

### Gate 0 (blocking, once): the module map and the contracts

Parallel work needs the boundaries fixed first. Before any module is built, the
maintainer signs off:
- `MODULES.md`: the modules, the workflow steps each covers, the directories each
  owns, and their dependencies;
- **the shared kit**, which every module uses and which is built once, before the
  fan-out: the app shell; the one hook that reads the derived state
  (`WorkflowEngine.state()`, section readiness, publish readiness); the refusal
  explainer (a `StepError` or guard → plain words); the confirm-or-undo pattern
  for destructive acts; form fields bound to the controlled vocabularies; the
  "[… pending]" placeholder;
- each module's **contract** (`modules/<m>/contract.md`), so a module builds
  against mocks and waits for no one;
- the app's skeleton: its directory, its build, how FastAPI serves it.

### Per module, independently

```
analysis → spec + contract → [SIGN-OFF: spec] → backend ∥ front-end
        → adversarial test ⇄ fixes → review → [SIGN-OFF: done] → merge
```

Modules move through this at their own pace. The maintainer's sign-offs form a
**queue**: a module waiting for one holds up only itself.
- **Spec sign-off**: the maintainer gets `spec.md`, `contract.md` and a short
  summary of `analysis.md`.
- **Done sign-off**: the maintainer gets a running demo, the test report and the
  review verdict.

After both, the orchestrator merges the module into `ui-redesign`. Integration
ends with one more sign-off over the whole workflow, end to end.

A change to a contract after Gate 0 goes through the orchestrator. Every module
it touches is told; a change to a signed spec is signed again.

### The board

`BOARD.md` is the state of every module: its stage, who is on it, the sign-offs
(with dates), what blocks it. The orchestrator keeps it.

## How the work is laid out

- **Module documents:** `docs/ui-redesign/modules/<m>/`, written in the
  orchestrator's worktree (`/workspace/rlm-bmdx-ui`). Each role writes only its
  own file and does not commit; the orchestrator commits.
- **Code:** each coding agent works in **its own sparse worktree**, made by
  `tooling/ui_team_worktree.sh add <m>-<role>`: path `/workspace/ui-team/<m>-<role>`,
  branch `ui-<m>-<role>`, from `ui-redesign`, with the same sparse-checkout rules
  as the orchestrator's worktree (the old front-end is not on disk) and the same
  links to the untracked data. Coding agents commit on their own branch; the
  orchestrator merges.
- **Never use worktree isolation** (the `Agent` tool's `isolation: "worktree"`, or
  `EnterWorktree`): it branches from `main` with a full checkout, which puts the
  walled front-ends on disk.
- **Ownership:** each module owns the directories `MODULES.md` gives it. Files
  every module touches (the router, the API client, route registration in
  `web_routes/background_server.py`, the shared kit) belong to the orchestrator;
  an agent that needs a change there asks for it in its report.
- **Data:** `sessions/`, `output/` and `workspaces/` are the maintainer's real
  store, linked in. Read them; never write them. To run anything that writes, copy
  a session to `/workspace/ui-team/_scratch/<agent>/sessions/` and set
  `SESSIONS_DIR` and `OUTPUT_DIR` there.
- **Ports:** 9000 (the main app), 9100 (the maintainer's Jupyter), 9300 and 9400
  (a workspace) are not the team's. 9200 is the orchestrator's demo for the
  maintainer. Agents use the `127.0.0.1` port their brief assigns, from 9500 up.
- **Scale:** about six agents at once; four to six modules in flight.

## Every agent's report

Each agent ends with a short report to the orchestrator:
- what it did and the files it changed (and its branch, if it commits);
- what it verified by running it, separately from what it read;
- open questions for the maintainer;
- what it could not do, and why.
