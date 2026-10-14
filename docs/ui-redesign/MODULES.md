# Gate 0: the module map, the shared kit and the contracts

Drafted 2026-10-14 by the orchestrator from the three Gate 0 analyses, for the
maintainer's sign-off (`TEAM.md`, Gate 0):
- `modules/gate0-data/analysis.md`: steps 1–8 and the session lifecycle;
- `modules/gate0-process/analysis.md`: step 9, content preparation, reprocess;
- `modules/gate0-document/analysis.md`: steps 10–13, the configurator, the
  hand-off, the Bookshelf.

The analyses are the evidence. Each of their claims is marked *verified* (run on a
scratch copy) or *read* (from the code). The orchestrator re-checked the headline
claims in the code.

**What signing this means:** the module list, the shared kit, the shared contracts
(§4) and the app skeleton (§5) are fixed. Modules can then be specified and built
in parallel. Each module's own `contract.md` (its endpoints and shapes) is signed
with its spec, against the shared contracts fixed here. This is a refinement of
`TEAM.md`, which put every module's contract at Gate 0. Writing fourteen contracts
before any spec would have designed the screens twice.

---

## 1. What the analyses changed

HANDOFF §4 describes guarantees the backend makes. Many of them it does not make.
The interface cannot idiot-proof on top of a backend that lets every wrong act
through, or that silently undoes a person's decisions. Each claim below was
verified by running it, unless marked:
- **Legal actions are advisory only.** No step and no route checks them.
  Integrate runs with validation errors standing; Process runs before the data
  approval; the approval runs before integration.
- **Approvals are not protected.**
  - Every Process run un-approves the apical result sections and discards edits to
    them, with no archive.
  - `may_machine_write` has no production caller.
  - Saving a section over an approved Background lost the approved text for good.
  - Restoring a version brings it back already approved.
- **The publish gate checks only stale LLM sections.** It said "can publish" with
  0 of 9 sections approved, with pending placeholders, and in phase UPLOADED with no
  `integrated.json`. For a report over two studies it ignored the member studies.
- **Currency fires only on a change to the files.** Re-pinning the method or
  changing a stated fact rewrites Methods and changes the numbers, and stales
  nothing.
- **A stale Summary keeps its old text**, so re-accepting it blesses text written
  from the old data.
- **Three of the five LLM-written parts can never be approved:** Methods, the
  apical-BMD narrative and the genomics interpretations. They live only in caches.
- **Silent defaults:**
  - Integration and Process pin the newest method profile and the 2026 definition
    when none is chosen. Process does it even when it then refuses.
  - A suffixed session id silently changes the report's era.
  - The dose unit falls back to mg/kg.
- **Saves that destroy:**
  - Saving the front matter in parts erased the authors.
  - Approving part of an experiment's metadata blanked its other fields.
  - Integration overwrote the identity, dropping the CASRN and the short name.
  - Opening the structure editor and saving it unchanged replaced NIEHS-10's own
    definition (78 → 67 nodes).
- **Data loss without an error:**
  - Conflict choices never reach apical platforms (plain vs compound coverage key).
  - Classification corrections are lost on re-validation.
  - A server restart between validate and integrate dropped 12 of 16 experiments.
  - An LLM failure during Process returns success.
- **No run lock.** Two tabs both run Process, and the last writer wins.

So the plan has **two tracks**:
- **the interface modules (§3):** the screens;
- **the core guarantees (§2):** backend work in `workflow/`, `pipeline/` and
  `web_routes/` that makes §4 of HANDOFF true.

A screen is "done" only when the guarantees it relies on hold. Until then, its spec
names the gap and the screen covers it as far as a screen can.

Several guarantees are decisions, not bugs. For example, should Process keep an
approval? The tests pin today's behaviour. Those are the questions in §7. The core
track touches behaviour the golden tests pin, so it works under the cross-cutting
refactor constraints: map the blast radius first, test the full flow.

---

## 2. The core-guarantees track (backend)

Each item is a backend module: built by a backend engineer in its own worktree,
reviewed, and signed off like any other. They are independent of each other except
where noted.

| # | Guarantee | Today | Fix (summary) | Waits on |
|---|---|---|---|---|
| C1 | **Legal actions are enforced** | advisory only | one guard used by every step and route (refuse with a `StepError` that names the phase); integrate refuses when the fingerprints don't match the coverage matrix; re-integration withdraws the data approval; Process refuses outside its phases and pins nothing before refusing | Q3 (does Process need APPROVED?) |
| C2 | **Owned content is never overwritten by a machine** | no caller of `may_machine_write`; materialize un-approves; save-section destroys; restore re-approves silently | `may_machine_write` on every machine write path; archive before any overwrite of owned content; restore and discard become `workflow.steps` steps that record a version event; accept becomes state-only | Q1, Q6 |
| C3 | **Saves merge and check** | experiment-metadata and front-matter saves replace; vocabularies unchecked on HTTP; identity overwritten; classifications not durable; precedence key mismatch | merge + vocabulary check on every statement save; identity written only by its own step; person-stated classifications durable and keyed by file name; precedence keyed by compound key and file name | Q10 |
| C4 | **Reads have no side effects; ids are stable** | `GET …/state` creates the session folder; fingerprints re-scan and mint new ids on a cold server; `GET /api/session/{id}` registers uploads | side-effect-free reads; file ids stable across validations and restarts | – |
| C5 | **Process is one guarded, observable act** | no lock; HTTP process and materialize are two calls; no progress across requests; LLM failure = success; run parameters forgotten | per-session run lock + in-flight record; one endpoint that runs process + materialize and streams events (§4.4); `content_errors` and fallbacks in the result; run parameters become saved declarations | Q11, Q12 |
| C6 | **Readiness is derived, complete and explained** | the data approval checks nothing; the publish gate checks stale LLM sections only | a derived data-approval checklist (§3 M6) and a derived publish checklist (§3 D1), both folding in member studies, pending markers, pins and deviations | Q2, Q3, Q4, Q5 |
| C7 | **Currency covers every input** | only file changes stale | re-pins, stated-fact changes and a tracking pin's move stale the dependent LLM sections; a stale section gets a fresh draft beside the approved text | Q2, Q5 |
| C8 | **Destructive acts can be previewed and undone** | resets and invalidations delete with no list; no restore for a removed file | a dry-run that returns what an act will delete and keep (feeds the confirm pattern, §4.3); restore a removed file; history for stated facts | Q9 |

C1, C2 and C4 protect every module, so they go first. Each is small enough for one
engineer.

---

## 3. The interface modules

One row per module. "Owns" is the directory under the app (§5) plus any backend files
it adds. "Needs" lists the guarantees and modules it depends on. The endpoint
inventories (existing vs missing) are in the analyses' module-cut sections; the
designer turns them into the module's `contract.md`.

### Data preparation

| # | Module | Steps | The person decides | Needs |
|---|---|---|---|---|
| M1 | **Studies** | create, list, open, delete a session | which study, which chemical, under which id | kit; C4 |
| M2 | **Study files** | 1 bring in, 2 validate, 3 conflicts, 4 classification; clear files, reset | which files belong, and what each one is | M1; C3, C4, C8 |
| M3 | **Integration and the dataset** | 5 integrate; review each experiment's metadata (stated vs inferred) | is the merged dataset what the files say | M2; C1, C3 |
| M4 | **Study facts** | 6: design, dose unit, short name, eFDR | what the data cannot say | M3 (design and eFDR need integration); C3 |
| M5 | **Method and document pins** | 7 | which method, which document definition, fixed or tracking | M1; C7 for the re-pin consequences |
| M6 | **Data approval** | 8: the animal accounting and a derived readiness checklist | is the data right to compute on | reads M2–M5; C6 |

### Computation

| # | Module | Steps | The person decides | Needs |
|---|---|---|---|---|
| P1 | **Process** | 9: pre-flight check (facts, pins, dose unit, deviations, what will recompute), the blocking wait with progress, the outcome (recomputed / reused / rewritten / failed / approvals affected) | when the data is ready to compute on | M6; C1, C5 |
| P2 | **Change impact** | the consequences of a file change, a re-pin or a changed fact on a study that has progressed, shown before the act is confirmed | whether to make the change | C7, C8; used by M2, M4, M5, P1 |

### Document

| # | Module | Steps | The person decides | Needs |
|---|---|---|---|---|
| D1 | **Review** | 11 + the publish checklist of 12: sections grouped by what needs attention; per section, what a person needs to approve knowingly (document analysis §8); accept, release with a reason, history, restore | is each section right; is the report ready | C2, C6; D3 for the per-section preview |
| D2 | **Narrative generation** | 10: Background, Summary (deterministic or a model run), Methods and genomics re-preparation; each produces a draft beside the approved text | which text stands | D1; C2 |
| D3 | **Preview and deliverables** | 13: a faithful preview per target (Word → PDF, LaTeX → PDF), the HTML content view, downloads labelled draft or final | is this what goes out | D1 (the gate) |
| D4 | **Hand-off and return** | Overleaf (bind, commit, push, pull, the edits that came back); Word (one-way until Q15 is settled) | where authoring happens; what came back | D3 |
| D5 | **Configurator** | §7: the document definition and its pin, views, layout styles; the report details (front matter, deposit) | how this report is structured and presented; who wrote it | kit vocabulary fields; C3, C8 |
| D6 | **Bookshelf hook-up** | links to `/Bookshelf/<id>` and the companion; a draft/approval notice on the facsimile and its downloads; where the Compare link points | – | D1, D3; Q16, Q17 |

**Placement calls, open to the maintainer (Q13):**
- **Front matter and the deposit sit in D5, not M4.** They are details of the
  report, not of the data. Nothing in the data steps needs them. They are stated
  once per report, often by different people than the design.
- **The dose unit sits in M4 as a stated fact**, no longer a Process parameter
  (Q11).
- **Content preparation has no screen of its own.** Today it does nothing that
  Process doesn't. Its per-section act ("rewrite this narrative") belongs to D2.

### The order of work

Four to six modules in flight. Specs can start for everything at once; building
follows the dependencies.

| Wave | Interface | Core |
|---|---|---|
| 0 | the shared kit and the skeleton (§4, §5) | C1, C2, C4 |
| 1 | M1, M2, D1, D5 | C3, C5, C6 |
| 2 | M3, M4, M5, M6, P1, D3 | C7, C8 |
| 3 | P2, D2, D4, D6 | – |

---

## 4. The shared kit and the shared contracts

Built once, before the fan-out, by the orchestrator with one front-end and one
backend engineer. Every module uses these and none forks them.

### 4.1 The derived-state hook

**Front-end:** `useStudyState(id)`. It is the only way a screen learns about the
workflow. It reads and never computes. The backend serves one read model per study:
`GET /api/v2/studies/{id}/state` (NEW; side-effect-free, C4):

```json
{
  "id": "DTXSID50469320",
  "exists": true,
  "phase": "APPROVED",
  "legal_actions": ["REPROCESS", "RESET"],
  "identity": {"name": "…", "casrn": "…", "dtxsid": "…", "short_name": "…"},
  "pins": {
    "method":     {"name": "ntp-5day-2021", "mode": "fixed", "pinned_by": "person|default", "deviations": [], "mismatches": []},
    "definition": {"name": "studies/DTXSID50469320/document", "mode": "track", "drift": null, "source": "study|era|session"}
  },
  "processed": true,
  "run": {"in_flight": false, "started_at": null, "last": {"ok": true, "finished_at": "…", "content_errors": []}},
  "sections": [{"key": "summary", "kind": "llm", "approvable": true, "approved": true, "stale": false,
                "regenerated": null, "wording_review": [], "source": "generated", "version": 2,
                "version_status": "blessed", "machine_may_write": false, "blocked_by": []}],
  "readiness": {
    "data_approval": {"ready": false, "items": [{"id": "design.fallback", "level": "block|warn", "say": "…", "fix": "M4"}]},
    "publish":       {"ready": false, "items": [{"id": "section.unapproved", "level": "block|warn", "section": "bm2_body-weight", "say": "…", "fix": "D1"}]}
  }
}
```

The shape is fixed at Gate 0; the backend fills it in stages:
- today's fields first (phase, legal actions, sections, publish readiness);
- the rest as C5–C7 land.

Fields not served yet are absent, not guessed. The hook re-reads after every
mutating call and after a run ends. `readiness.*.items[].fix` names the module that
fixes the item, so every block links to the place it is cleared.

### 4.2 The refusal explainer

**One error envelope** for every new or changed route (NEW; existing routes are
wrapped):

```json
{"error": {"code": "phase_not_allowed", "status": 409, "message": "…the backend's verbatim text…",
           "say": "…plain words for a toxicologist…", "fix": "M2", "details": {}}}
```

- `code` comes from a closed list kept in one backend module.
- `say` is the plain-words text, written once in the backend next to the code, so
  the CLI and the notebook can use it too.
- The front-end's `<Refusal>` renders `say`, a link to `fix`, and `message` and
  `details` behind a toggle.
- A "success that did nothing" (releasing a missing section; a summary not
  rewritten) is an error or carries `"noop": {"code", "say"}`. It is never a bare
  `ok: true`.
- The analyses list every existing message to map: data §3.1, Process §6.1,
  document §9.1.

### 4.3 Confirm-or-undo

`<ConfirmAct>`, three strengths:
- **reversible:** an Undo link after the act;
- **costly:** a dialog listing the consequences;
- **irreversible:** the same dialog, and the person types the study id.

The consequences always come from the backend's dry run (C8; P2's impact for file,
pin and fact changes), never from a list kept in the front-end.

```json
{"act": "reset_pool", "strength": "irreversible", "deletes": [{"what": "…", "say": "…"}],
 "keeps": [{"what": "…"}], "approvals_lost": ["bm2_body-weight"], "cost": {"say": "a full Process, about 3 minutes"},
 "reason_required": false}
```

### 4.4 The wait

`<Wait>`, for Process, integration (about 25 s), renders (10–25 s) and Background
generation. It is a foreground block with:
- the elapsed time;
- a step list fed by the run's event stream;
- no cancel (Q12);
- an "already running since …" state, from `state.run.in_flight`, for a reload or a
  second tab.

**The stream format** (NDJSON; NEW with C5):

```
{"event":"step","unit":"bmds","status":"computing|reused|done|failed","say":"Apical BMD modelling","ms":…}
{"event":"result","ok":true,"summary":{…}}   or   {"event":"error","error":{…the §4.2 envelope…}}
```

### 4.5 The fields and marks

- **`<VocabField>`:** a select bound to one `bmdx_pipe.VOCABULARIES` key, with
  dependent fields (strain ← species; vehicle and means ← route). Served by
  `GET /api/v2/vocabularies` (NEW). There is never a free-text fallback.
- **`<IdField>`:** session id, DTXSID, CASRN, DOI, date. Each is validated as it is
  typed with the backend's pattern. A free-form study id says what it costs.
- **`<Pending>`:** the "[… pending]" placeholder. It shows the cause and links to
  the field or module that fills it. The marker list is served by the publish
  readiness.
- **`<Provenance>`:** stated / recorded / inferred / standard design (fallback) /
  in conflict, on every fact.
- **`<SectionStatus>`:** one mark built from `machine_may_write`, maturity, stale
  and regenerated. It replaces the two "protected" meanings that disagree today.

### 4.6 The API client

`ui/src/api/`, owned by the orchestrator. Typed functions over the routes, and the
MSW mock handlers that serve each module's contract fixtures. A module adds its
endpoints through a request in its report, not by editing the client.

---

## 5. The app skeleton

| Item | Proposal |
|---|---|
| Directory | `ui/` at the repo root: `ui/src/kit/` (the kit), `ui/src/modules/<m>/` (one per module, owned by it), `ui/src/api/`, `ui/src/shell/` |
| Toolchain | Node 22 (in the image); Vite 8; React 19; TypeScript; **antd 6** (current major; HANDOFF names antd without a version); TanStack Query 5 for reads; MSW 3 for the contract mocks; Vitest + React Testing Library; ESLint |
| Routes in the app | `/<prefix>/studies`, `/<prefix>/studies/<id>/<module>`; the shell shows the study's phase and the next step derived from `legal_actions` |
| Served by | FastAPI mounts `ui/dist` at a new prefix. **Not** `/` or `/workflow…`, which belong to walled routes. Provisional prefix: `/app`, until the interface has a name (HANDOFF §2) |
| Backend routes | new routes under `/api/v2/…`, in new `web_routes/` modules per area; existing routes are reused where they serve, wrapped in the §4.2 envelope where they don't |
| Dev | `npm run dev` proxies `/api` to the agent's own server port (9500+); the orchestrator's demo for the maintainer is on 9200 |
| Browser tests | the adversarial tester's Playwright scripts in `tests/ui/<module>/` (headed) |

---

## 6. What this asks of the maintainer now

Gate 0 needs answers to the **blocking** questions (§7, marked ●). Each of the rest
can wait for the spec of the module it belongs to. A sign-off can also take the
proposals as they stand and leave the ● questions with the core-track items that
wait on them.

---

## 7. Open questions, merged from the three analyses

The source is in brackets: the data, Process or document analysis, and its
question number.

**Approval, currency and the gate:**
- **Q1 ●** Should Process keep an approved apical result section approved? If its
  wording flipped, keep it approved with a flag, or knock it down? Should a person
  be able to edit `bm2_*` text at all, given the deliverable renders from the cache?
  Today every Process un-approves it and drops edits, and tests pin that. [Process Q1, document Q3]
- **Q2 ●** Should a re-pin, a changed stated fact, or a tracking pin moving to a new
  profile stale the approved LLM sections, as ADR-0027 says? [Process Q2, document Q5]
- **Q3 ●** Must Process wait for the data approval? What does the approval assert:
  a derived checklist, and who approved? [Process Q3, data Q4]
- **Q4 ●** Should Methods, the apical-BMD narrative and the genomics interpretations
  become approvable sections, under the same ownership and currency rules?
  [Process Q4, document Q2]
- **Q5 ●** What blocks publishing, and what only warns? Candidates:
  - unapproved sections;
  - "[… pending]" placeholders;
  - phase not APPROVED;
  - the member studies of a report over several studies.

  Is "published" an act in the interface? [document Q1, Q8, Q14]
- **Q6** Should a stale Summary get a fresh draft beside the approved text? Should a
  restore return the version as approved, or as a draft? Is a release reason
  required? [Process Q5, document Q4, Q6, Q7]

**Data preparation:**
- **Q7 ●** Is a session's id always the chemical's DTXSID? Today the id silently
  chooses the report's definition, method overlay and deposit wording. [data Q2]
- **Q8 ●** Should the method profile have to be chosen by a person, with no default,
  before integration? [data Q9]
- **Q9** Should stated facts (design, metadata, front matter) keep a history, as the
  pins do? [data Q6]
- **Q10** Conflicts:
  - should choosing a file clear a conflict error?
  - what happens to redundant files?
  - is a `.bm2` still required for apical platforms (the completeness message says so)?

  [data Q1, Q3]
- **Q11** Is the dose unit a stated study fact? Should Process take no run parameters
  at all, only saved declarations? [data Q5, Process Q6]
- **Q12** Is a cancel button wanted inside the Process wait? The core cannot cancel
  today. [Process Q7]

**Document:**
- **Q13** Placement: front matter and the deposit in the configurator (D5), as
  proposed? How does a deposit come in from a browser, and may the report print a
  local address before the DOI exists? [data Q7, Q8]
- **Q14** The structure editor: should it edit the study's own definition, a session
  copy, or only views? Who may edit the default templates (they rewrite the golden
  fixture)? [document Q9]
- **Q15** Hand-off:
  - what priority has the Word return, and should it read tracked changes only?
  - may the Overleaf commit render from disk instead of the browser's posted body?

  [document Q12, Q13]
- **Q16** Preview:
  - is LibreOffice acceptable for the Word preview here?
  - are 10–25 s per faithful preview acceptable?
  - should the Bookshelf downloads be gated or labelled draft?

  [document Q10, Q11]

**The wall and the skeleton:**
- **Q17 ●** The kept Bookshelf calls `published_report` from the walled
  `web_routes/compare_routes.py`. May it move to an unwalled module? The new
  interface needs to know which published report a session reproduces. Where should
  the Bookshelf's Compare link point? [document Q15, Q11]
- **Q18 ●** Skeleton:
  - antd 6;
  - the app under `ui/`, served at `/app` until it has a name;
  - new routes under `/api/v2/`.

  Agreed?
