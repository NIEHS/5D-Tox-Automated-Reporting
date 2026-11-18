# The demo path: one spec for the screens the walkthrough needs

**Draft, 2026-11-18, by the orchestrator. Not signed. Nothing in it is built, and
nothing is to be built until the maintainer says so.**

The maintainer's goal for the two weeks to about 2026-12-02 is a **demo of this
interface** to the study team, on the 1,2-dichlorobenzene inhalation report
(NIEHS-12). This spec replaces, for those two weeks, the module-by-module flow of
`TEAM.md` with one spec and one sign-off for a thin path through five pages.

Points marked **[maintainer]** need a decision (collected in §9). Points marked
**[verify first]** are facts the build must establish before anything rests on
them (collected in §8).

---

## 1. What was decided (the maintainer, 2026-11-18)

1. **The walkthrough is a demo of the interface**, not a talk about the pipeline.
   The data is brought in and checked beforehand, because that takes long. The
   demo then steps through the emphasized steps:
   - where the source of each table comes from;
   - how the written sections are generated, and under which prompts
     (Background, the results narratives);
   - how citations work;
   - the report on the Bookshelf;
   - then the Word document.
2. **Two setups, to switch between:** a fully realized report, and one stepped
   through in real time. The realized one is also the way out when real-time
   generation misbehaves.
3. **The live copy is in the same store, under another id.** The pair is set
   apart in the Studies list as **"Demo"**.
4. **Source files and code paths** are shown, when asked for, on the API page
   (`/docs`, arranged by workflow step since `54de38d`) and in the notebook. The
   interface does not have to show code.
5. **One "demo path" spec** stands in for the per-module specs and sign-offs.
6. **The review page follows the maintainer's idea from the meeting:** the
   Bookshelf view with controls beside it, and a button that makes the Word
   document. **It is not to be started yet.**

From the meeting itself (Scott Auerbach, 2026-11-18), binding on how to work: put
a product in front of people, let them take it apart, fix, repeat. Start from the
core that already works. Do not over-plan.

## 2. What the path is, and is not

**It is** five pages, thin, on top of what the backend already does. Each shows
what the software did and lets the presenter do the next step. Everything a page
shows about the workflow comes from the backend (the state read model, `MODULES.md`
§4.1); the browser computes no phase, readiness or permission.

**It is not** the full modules. Left out, and how the demo covers each:

| Left out | In the demo |
|---|---|
| Adding and checking files (M2) | done beforehand; the Studies page shows the study as "checked" |
| Stating study facts (M4), choosing the method and definition (M5) | done beforehand; the Process page shows them, each with its source, and cannot change them |
| The animal accounting (M6) | not shown |
| What a change affects (P2), the configurator (D5), Word and Overleaf return (D4) | not shown |
| The core-track items not yet built (C5 run lock and event stream, C6 full readiness, C7, C9 every written part as a section, C10 draft marks) | the pages state what is checked today and claim no more (§7) |

Nothing left out is faked. A page that cannot do something says so.

## 3. The pair, and the "Demo" partition

### 3.1 The two reports

NIEHS-12 is one report over two studies. Each setup is therefore three sessions:

| | Report | Rat study | Mouse study |
|---|---|---|---|
| **Finished** (exists) | `DTXSID6020430` | `DTXSID6020430_rat` | `DTXSID6020430_mouse` |
| **Live** (to be made) | `DTXSID6020430_live` | `DTXSID6020430_live_rat` | `DTXSID6020430_live_mouse` |

The live sessions are made by the system (Gate 0 Q7: a person creates a study
only under a bare DTXSID). The finished report is not touched by anything in this
spec.

### 3.2 The live copy's start state

The start state is defined by what must be true, not by a list of files:

- each live study is in phase **VALIDATED** with no validation error, and
  INTEGRATE is its legal next action;
- the study facts no file records (dosing days, dosing schedule) are stated, the
  analysis method and the report definition are pinned, and the knowledge base is
  assigned, each exactly as in the finished study;
- there is no combined dataset, no result, no written section and no reference
  list;
- the live report has no Background.

**[verify first]** whether the workflow can hold stated facts and pins before
integration (stating a fact is legal only from INTEGRATED on). If it cannot, the
start state is rebuilt by the tool below from the finished study's own stated-fact
and pin files, and the acceptance criteria of §3.4 decide whether that is sound.

### 3.3 The tool

`tooling/demo_copy.py` (new, on `main`: it is about sessions, not the interface):

- `make`: builds the three live sessions from the finished study's **input
  files**, by running the workflow's own steps (import, validate, confirm) through
  `safeguards.guarded`, then carrying over the stated facts, the pins and the
  knowledge-base assignment. It refuses when a live session already exists.
- `reset`: puts the three live sessions back to the start state from a snapshot
  `make` took (kept outside `sessions/`). Two strengths:
  - `reset` (default): the results cache is kept beside the snapshot and put back,
    so a live Process reuses what did not change and finishes fast;
  - `reset --cold`: no cache. Process computes everything and calls the language
    model again.
- `remove`: deletes the three live sessions and the snapshot, after listing them.
- It never writes a session whose id is not one of the three live ids. No file of
  a session is deleted by hand-picked name: the tool uses the core's own
  invalidation, or replaces a whole session folder from the snapshot.

### 3.4 Acceptance criteria for the copy

- The state read model reports the live report as `kind: report` with two members,
  and each live study as `kind: member` of it, phase VALIDATED, `processed: false`.
- After a live Integrate and Process of both studies, every results table of the
  live report equals the finished report's, cell for cell. (The written sections
  differ: a model writes them again.)
- The live report's Bookshelf page uses NIEHS-12's own report definition and prints
  the substance's DTXSID without the suffix.
- `reset` after a full live run restores the start state; a second live run gives
  the same tables.
- Run on a scratch store first; the real store is written only by the orchestrator,
  once, with the maintainer's go.

### 3.5 The "Demo" partition in the Studies list

- A declared file in the store, `sessions/_partitions.json`:
  `{"Demo": ["DTXSID6020430", "DTXSID6020430_live"]}`. It is a person's
  declaration, not a derived state; `demo_copy.py make` writes the entry and
  `remove` takes it out.
- `GET /api/v2/studies` gains `partitions: [{name, sessions: [id, …]}]`. A session
  named in a partition is listed there (with its member studies under it) and not
  again under its chemical.
- The Studies list shows a partition as a titled block above the chemicals, with
  the two reports side by side: **"Finished"** and **"Live"**, each with where it
  stands and its next step. The study header of either carries a **"Switch to the
  live copy" / "Switch to the finished report"** link that opens the same page of
  the other. That link is the switch the presenter uses.
- A partition that names a session that does not exist shows it as missing; it is
  not hidden.

## 4. The pages, in demo order

Routes are the existing ones (`/app/studies/:id/<slug>`); each page replaces a
placeholder. On the report, a page that works per study shows a choice of the two
studies first.

### S1. Combined data (`dataset`): where every table's source comes from

**The presenter shows:** the files of a study become one dataset, and every table
of the report can be followed back to the files it was built from.

- **Before integration** (live copy): the study's files (name, what each was
  recognized as) and one button, **"Combine the files into one dataset"**, enabled
  when INTEGRATE is legal. The wait is the kit's `<Wait>` with the elapsed time.
- **After integration:** a table of the experiments in the dataset: assay, sex,
  organ or tissue, number of endpoints, number of animals, the files it came from,
  and whether the study's own benchmark dose analysis is among them.
- **"Follow a table back"**: a list of the report's results tables. Choosing one
  shows, per row of the table, the endpoint, the experiment and the source file,
  and for its benchmark dose whether it is the study's own analysis or was fit
  here (the record of ADR-0036).
- A link, **"See this step on the API page"**, opens `/docs` at the group.

Backend:
- `POST /api/v2/studies/{id}/integrate` (new, thin): `safeguards.guarded.integrate_step`,
  answering in the error envelope (`MODULES.md` §4.2).
- `GET /api/v2/studies/{id}/dataset` (new): the experiments with their source
  files, from `integrated.json`.
- `GET /api/v2/studies/{id}/sections/{key}/sources` (new): for a results section,
  its rows → endpoints → experiments → source files, and the benchmark dose source
  per assay and sex. **[verify first]** that the session database written by
  Process (`source_file`, `experiment`, `endpoint`, `apical_result`) carries the
  chain end to end; if a link is missing, the page shows the chain as far as it is
  recorded and says where it stops.

### S2. Process (`process`): the analysis

**The presenter shows:** what Process is about to compute from, runs it, and sees
what it did.

- **Before:** a short pre-flight, read-only: the study's parameters, each with its
  source (recorded / stated), the pinned method and report definition, the
  knowledge base. A missing parameter is shown as the refusal it will cause.
- **Run:** one button, **"Run the analysis"**, enabled when PROCESS is legal. The
  wait is a foreground block with the elapsed time. No step list: the event stream
  is C5 and is not built. The page says "this takes about N minutes" with N from
  the rehearsal (§6).
- **After:** what was computed and what was reused, the result sections written,
  the citations the check removed (a count, linking to S4), and the next step.
- A second tab, or a reload during the run, cannot be told that a run is in
  flight (C5). The demo runs Process from one tab; the page says so in its help
  text.

Backend:
- `POST /api/v2/studies/{id}/process` (new, thin): `guarded.process_step`, then
  `guarded.materialize_result_sections`, in one request; the envelope on refusal.
  It takes no run parameters: the study's declarations decide (Gate 0 Q11's
  direction).
- `GET /api/workflow/{id}/study-parameters` (exists).

### S3. Written sections (`writing`): how each was written, and under which prompt

**The presenter shows:** which text is built from the data and which a model
wrote, and for the model's text exactly what it was given.

A list of the written parts of the report, each marked **built from the data** or
**written by a language model**:

| Part | How it is written | What the page shows |
|---|---|---|
| Background (report) | model, from gathered public sources | the sources gathered, the model, the reference list, the citation check's result; the prompt as rebuilt from the same sources **[verify first]** |
| Materials and Methods | study design, dose selection, chemistry, benchmark dose analysis and eFDR built from the data; the rest by a model | per subsection, which of the two; the facts the model was given (the recorded Methods context) |
| Results tables and their sentences | built from the data | says so; links to S1's "Follow a table back" |
| Gene-level interpretation, per organ and sex | model, from the knowledge base | the text given to the model (recorded with the result), the papers offered to it, the knowledge base's name, the model |
| Summary | facts picked by rule, worded by a model under a versioned template | the template, the exact prompt sent (recorded with each run), the numbers in the text that were not among the facts given |

Acts on this page, live copy only:
- **"Write the Background"** (report): the existing generation, with its wait;
  then the text is saved as a draft section through the section write gate.
- **"Write the Summary"**: the existing generation.

Neither act is offered on the finished report in the demo; its page is read-only.

Backend:
- `GET /api/v2/studies/{id}/writing` (new): the list above, as data.
- `GET /api/v2/studies/{id}/sections/{key}/writing` (new): for one part, what the
  model was given and how the text was made. Each field is what is recorded; a
  field nothing recorded is absent and the page says "not recorded", never a
  reconstruction presented as the record.
- `POST /api/generate`, `POST /api/generate-summary`, `POST /api/session/save-section`
  (exist), behind thin v2 wrappers if the envelope is needed.

### S4. Citations (a tab of `writing`): how they work

**The presenter shows:** every citation points at a paper that was actually
supplied, where that paper came from, and what the check does and does not claim.

- The report's reference list, numbered as printed. Each entry: title, year,
  venue, DOI as a link, which sections cite it, and for a knowledge-base paper the
  genes it was offered for.
- Choosing a citation in a section's text shows the sentence, the paper, and for a
  knowledge-base paper the statements extracted from it.
- The check's result, in its own words: how many citations could not be traced to
  a supplied source (and were removed), and **"The check establishes that a
  citation points at a source. It does not judge whether the source supports the
  sentence."**

Backend:
- `GET /api/session/{id}/citation-warnings` (exists).
- `GET /api/v2/studies/{id}/references` (new): `references.json` joined, per paper,
  to the knowledge base's record of it (`knowledge_base.registry.kb_for`).

Not in the path: the assertion check Scott asked for (does the cited paper support
the sentence). It is listed in §9 as the first extra.

### S5. Review, Bookshelf and Word (`review`) — **not to be started yet**

**The presenter shows:** the report as the Bookshelf would show it, approves a
section, and makes the Word document.

- The Bookshelf page of the report (`/Bookshelf/{id}`, as it is) in the main
  pane.
- A side rail: the sections in order, each with the kit's `<SectionStatus>`.
  Choosing one scrolls the Bookshelf view to it. Per section: **Approve** (as it
  stands) and **Reopen** (with a reason), through the existing v2 section routes;
  the history.
- What stands between the report and publishing, from the read model. The rail
  never says "ready to publish" while the readiness is incomplete (`MODULES.md`
  §4.1).
- **"Make the Word document"**: the existing download
  (`/Bookshelf/{id}/report.docx`), with its wait; then PDF.
- **[maintainer]** "Edit": Gate 0 Q1 says text is edited outside, in Word or
  Overleaf, and the application has no editor. The meeting's idea named an edit
  control. See §9.

## 5. Wording

Every word a page shows follows the rules for team-facing text
(`feedback_team_facing_wording`): nobody is addressed as "you"; American
spelling. The pages use the titles of `ui/src/kit/modules.ts` and the plain titles
of the API page's guide (`web_routes/api_guide.yaml`), so a step has one name
everywhere. A lint test on the pages' strings enforces the two rules, as the API
guide's test does.

## 6. How it is built and signed

- **One spec sign-off** (this document, with §9 answered), then build.
- **Build:** the copy tool and the partition first (everything else is rehearsed
  on them); then S1 and S2 in parallel; then S3 and S4 in parallel; S5 when the
  maintainer releases it. Each page is built by a front-end and a backend agent in
  their own worktrees (`tooling/ui_team_worktree.sh`), against this spec; the
  orchestrator owns the router, the API client and route registration, and merges.
- **Test:** one adversarial pass over the whole path, on a scratch copy of the
  live sessions: every act at the wrong moment, a reload in every wait, both
  studies, the switch link on every page.
- **Rehearsal** replaces the per-module done sign-offs: the orchestrator runs the
  path end to end on the live copy, cold and warm, and records the time of every
  wait. The maintainer's done sign-off is a rehearsal of their own.
- **Dates:**

| By | What can be shown |
|---|---|
| 2026-11-20 | the live copy, the Demo partition and the switch; S1 and S2 on the live copy |
| 2026-11-24 (check-in with Scott) | S3 and S4; the path walkable end to end on the finished report, with the Bookshelf and the Word download reached by link; one timed live run |
| 2026-12-01 | S5 (if released); fixes from the check-in; cold and warm rehearsals; the fallbacks of §7 tried |

## 7. What can go wrong in front of the room, and the way out

| What | The way out |
|---|---|
| A live Process or generation takes too long or fails | the switch link opens the same page of the finished report |
| The language model gateway or a public source is unreachable | the same. A warm `reset` is meant to let Process reuse the model's earlier answers for what did not change; whether it does after a fresh Integrate is checked at rehearsal (§8, 5) |
| A live act left the copy in a state the next step refuses | `demo_copy.py reset` (seconds), then continue from Integrate |
| The first load of a report's Bookshelf page is slow (about 50 s today) | both reports are opened once before the demo; **[verify first]** whether the second load is fast |
| A page shows a refusal | the refusal is the demonstration: it says why, and where it is cleared |

## 8. To verify first (before anything rests on it)

1. Stated facts and pins before integration (§3.2).
2. The live ids: `kind`, members, the report definition and the printed DTXSID
   come out right for `…_live`, `…_live_rat`, `…_live_mouse` (§3.4).
3. The session database carries the row → endpoint → experiment → file chain (S1).
4. What is recorded of the Background's and the Methods' prompts (S3).
5. Times: Integrate and Process of each study, cold and warm; Background; the
   Bookshelf page and the Word document, first and second load.

## 9. Open for the maintainer

1. **"Edit" on the review page.** Three readings of the meeting's idea:
   - (a) no edit control; approve and reopen only (Gate 0 Q1 as it stands);
   - (b) "Edit in Word": downloads the document for editing. The way back
     (C11) is not built, so the demo would say the edits return in a later version;
   - (c) editing text in the application, which reverses Gate 0 Q1.
   The orchestrator's recommendation: (a) for the demo, with (b)'s button shown
   as the Word download it is.
2. **Whether Integrate is run live**, or the live copy starts with the dataset
   combined and the demo starts at "Follow a table back". This spec assumes live.
3. **One study or both in the live run.** Running one (rat) halves the waits; the
   live report then shows the mouse study as not yet processed.
4. **The Background live.** It depends on public sources that are not always
   reachable from here. This spec offers it on the live copy and relies on the
   switch.
5. **Scott's extras**, only if time is left, in this order: the assertion check
   on citations; the notebook that recapitulates a report's tables and figures;
   the overall integrity check.
6. **The two workflow steps without a page** (BMD review, knowledge base; BOARD,
   2026-11-18): not in the path. The Process page shows the knowledge base
   read-only; a flagged benchmark dose appears in the review rail as something
   that blocks publishing.
