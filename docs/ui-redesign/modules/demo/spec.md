# The demo path: one spec for the screens the walkthrough needs

**Written 2026-11-18 by the orchestrator. The maintainer said "proceed" the same
day: the spec stands as written, with the recommendations of §9 taken until the
maintainer says otherwise. S5 (the review page) was released on 2026-11-19 and is built.
§8 records what the first checks found; where a finding changed the plan, the
section says "As built".**

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

The start state is what a study holds once its files are checked and what the
files do not record has been stated:

- each live study is in phase **VALIDATED** with no validation error, and
  INTEGRATE is its legal next action;
- the study facts no file records (dosing days, dosing schedule) are stated, the
  analysis method is pinned and the knowledge base is assigned, each exactly as in
  the finished study;
- the report definition is **fixed** to the one the finished report renders from;
- there is no combined dataset, no result, no written section and no reference
  list; the live report has no Background.

**As built.** The copy is the finished study's artifacts of workflow steps 1 to 4
(`files/`, `_fingerprints.json`, `validation_report.json`, `precedence.json`) and
its declarations of steps 6 and 7, copied whole (HANDOFF §5 is the list). Stated
facts do sit in a study before integration without harm: integration applies
them again, as it does on every re-integration.

**Found:** a study's own report definition is looked up by its session id
(`studies/<id>/document`), so a copy under another id would render from the
default definition. `document_model.definition_pin.pin_like` (new, on `main`)
fixes the copy to the definition its source renders from.

### 3.3 The tool

`tooling/demo_copy.py` (on `main`, `0a80fa7`):

- `make REPORT`: builds the live sessions and names the pair in the partition.
  Refused when a live session already exists, and for a copy of a copy.
- `reset REPORT`: deletes the live sessions and builds them again.
- `remove REPORT`: deletes them and takes the pair out of the partition.
- `status REPORT`: what each live session holds beyond its start state.
- Only a folder that carries the tool's marker (`demo_copy.json`) is ever
  deleted; the finished report is only read.
- A running server holds part of a session in memory, so the interface resets
  through the server: `POST /api/v2/demo/{report}/reset` (with its dry run,
  `…/reset-preview`), refused while a long act runs on the copy.

**As built: no warm reset.** Integration clears every results cache of a study
(`workflow.steps.integrate_step`), so a cache put into the copy before a live
Integrate is never read: the second live run of the rat study took the same 170 s
as the first. The tool has no warm option; the way out of a slow live step is the
switch to the finished report.

### 3.4 Acceptance criteria for the copy (checked 2026-11-18 on a scratch store)

- ✓ The state read model reports the live report as `kind: report` with two
  members, each live study as `kind: member`, phase VALIDATED, `processed: false`.
- ✓ After a live Integrate and Process of both studies, every results table of the
  live studies equals the finished studies', cell for cell (the five result
  sections of each, the gene-set results, the statistics and benchmark dose
  results). The model-written text differs, as expected, and with it the reference
  list; the charts' data are the same and their drawings differ only in generated
  ids.
- ✓ The live report's Bookshelf page has the finished report's 205 headings and 46
  identical tables. The suffixed id appears once, in the address of the session's
  supplemental-data folder, which is the session's own.
- ✓ `reset` after a full live run restores the start state.
- ✓ Built in the real store on 2026-11-18 (`DTXSID6020430_live`, `_live_rat`,
  `_live_mouse`; 33 MB).

### 3.5 The "Demo" partition in the Studies list

- A declared file in the store, `sessions/_partitions.json`:
  `{"Demo": ["DTXSID6020430", "DTXSID6020430_live"]}`. It is a person's
  declaration, not a derived state; `demo_copy.py make` writes the entry and
  `remove` takes it out.
- `GET /api/v2/studies` gains `partitions: [{name, sessions: [{id, role, session,
  members}]}]`. A session named in a partition is listed there (with its member
  studies under it) and not again under its chemical. Which side a session is
  (`finished` or `live`) is read from the copy's marker, and the state read model
  carries it for every session of the pair (`demo {partition, role, counterpart,
  counterpart_exists, report}`), so no page works it out.
- **The finished side is left as it is:** every act of the interface is refused
  on it (`demo_reference`), and its pages offer none.
- **Built** (`ui-redesign` `1ab7cd7`, `3f9963a`): the block, the switch link in
  every study page's header, the reset with its consequences from the backend.
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
  per assay and sex. The chain is recorded per assay (§8, 3); where a link is
  missing, the page shows the chain as far as it is recorded and says where it
  stops.

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
| Background (report) | model, from gathered public sources | the sources gathered, the model, the reference list, the citation check's result; the exact prompt for a Background written from 2026-11-18 on, "not recorded" for an earlier one (§8, 4) |
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

### S5. Review, Bookshelf and Word (`review`) — released 2026-11-19

The maintainer released it on 2026-11-19: **approve and reopen only; the Word
download is the way to edit** (§9, 1 (a)).

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
- No edit control: Gate 0 Q1 stands (text is edited outside, in Word). The page
  says so beside the Word button.

**As built (2026-11-19, `ui/src/modules/d1`, `ui_api/review.py`,
`GET /api/v2/studies/{id}/review`):**

- The read gives the book, the downloads, whether acts are offered, and the
  sections grouped by owner (the report: front matter and Background; each study:
  the rest), each with the place in the book where it starts.
- The book and the rail fill the window; the study header is a scroll above.
  Choosing a section sets the frame's address to the section's id, which is how
  the Bookshelf page itself moves between its parts.
- A section that is never approved on its own (front matter, the Abstract, the
  group narratives, the gene-level interpretations) has no Approve button; its
  reason shows when it is chosen. One that cannot be approved yet has the button
  disabled with the backend's reason.
- The finished side offers no Approve and no Reopen (history only), with a link
  to the live copy. A study of a report shows the report's book, with that
  study's sections opened first.
- Two sections have no place to scroll to: the Abstract (it is held in the
  book's metadata) and Clinical Observations (no table in the book).
- After an approval or a reopening the book is not asked for again (neither
  changes the text); the kept copy is out of date from then on, so the next
  opening of the page, and the next Word document, are rendered again.

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
  path end to end on the live copy and records the time of every
  wait. The maintainer's done sign-off is a rehearsal of their own.
- **Dates:**

| By | What can be shown |
|---|---|
| 2026-11-20 | the live copy, the Demo partition and the switch; S1 and S2 on the live copy |
| 2026-11-24 (check-in with Scott) | S3 and S4; the path walkable end to end on the finished report, with the Bookshelf and the Word download reached by link; one timed live run |
| 2026-12-01 | S5 (if released); fixes from the check-in; rehearsals; the fallbacks of §7 tried |

## 7. What can go wrong in front of the room, and the way out

| What | The way out |
|---|---|
| A live Process (about three minutes a study) or a generation takes too long or fails | the switch link opens the same page of the finished report |
| The language model gateway or a public source is unreachable | the same |
| A live act left the copy in a state the next step refuses | `demo_copy.py reset` (seconds), then continue from Integrate |
| A report's Bookshelf page takes about 50 s every time it is opened | it is opened in its own tab before the demo and left open; a kept copy of the page is a possible fix (§9) |
| A page shows a refusal | the refusal is the demonstration: it says why, and where it is cleared |

## 8. What was verified first (2026-11-18, on a scratch store)

1. **Stated facts and pins before integration:** hold (§3.2).
2. **The live ids:** kind and members come out right; the report definition did
   not, and is now fixed to the source's (§3.2, `pin_like`).
3. **The chain from a table to its files** is recorded at the level of the assay:
   the check's coverage matrix names, per assay, the workbook, the table converted
   from it and the BMDExpress project; each converted table's sidecar names its
   workbook; the dataset records which file each assay was taken from. A row of a
   table maps to its assay and sex, so every row of one table has the same files.
4. **Prompts:** recorded for the Summary (every run) and, from `0a80fa7` on, for
   the Background (`narrative_runs/background/`); the finished NIEHS-12's
   Background has none. The gene-level interpretations record the text given to the
   model and the papers offered. The Methods record the facts the model was given,
   not the prompt. The results narrative records its text and model only.
5. **Times, NIEHS-12, one run each unless noted:**

| Step | Rat study | Mouse study |
|---|---|---|
| Integrate | 28 s, 22 s | 28 s |
| Accounting of the animals | 5 s, 2 s | 4 s |
| Process (with the result sections) | 170 s, 170 s | 132 s |
| Summary (by rule) | 2 s | 2 s |

   The report's Bookshelf page: 45 to 54 s each time it is opened (it is built on
   request and not kept). Of a Process run, about a minute is the drawing of the
   charts and about a minute and a half the model's writing.

6. **The whole live path through the real app, in a browser (2026-11-19):**
   both live studies combined and processed through the pages (mouse: Combine
   33 s, Process 161 s; rat: 35 s, 177 s); the live report's Review page then
   showed the book after 53 s; a mouse section and a rat section approved, the
   rat's reopened with a reason (refused without one), its history read, the book
   scrolled to a table; the Word document saved after 54 s (1.17 MB, 48 parts)
   and the PDF after 6 s. No error in the browser's console; one request per
   act. The finished report's Review page opened in 3 s from its kept copy. The
   live copy was reset to its start state afterwards.

## 9. Open for the maintainer

**Fixed on 2026-11-19 ("fix the rough spots", the maintainer):**

- **item 9, the rows:** every row of a results table is followed to the
  dataset's endpoints it is built from, and how where it is computed ("Heart
  Relative": Heart and Terminal Body Weight, the organ's weight divided by the
  terminal body weight). The rule is the builders' own naming read back
  (`tables/row_sources.py` on `main`); on NIEHS-12, rat and mouse, every row of
  every table is followed. A label no rule covers reads "not known for this
  row";
- **Clinical Observations:** the dataset holds no experiment for it and records
  the files it is counted from; the page follows the table to that file and to
  its workbook, and says so;
- **the words:** the stage and the next step say "check" and "combine", as the
  pages do ("Files checked, not yet combined"; "Combine the files into one
  dataset"). The refusals of the shared safeguards (`main`) still say
  "Integrate" and "Validate";
- **the shelf:** `/Bookshelf` can be reduced to the reports of one partition
  (`?only=Demo`, remembered by the browser); "Show only this block" on the
  Studies list sets the same choice, so the unpublished reports are on neither
  screen;
- **item 12, the Summary:** a report's approved Background now releases the
  Summary of each of its studies (`workflow/engine.py` on `main`).

**Answered on 2026-11-19:** item 1: (a), and S5 is released; item 6: yes, a kept
copy (`rendering/kept_render.py` on `main`: the Bookshelf page, the Word document
and the PDF are kept until anything they were rendered from changes; NIEHS-12's
page went from 53 s to 0.3 s on a repeat); item 7: yes ("Show only this block" on
the Demo block, kept in the browser); item 8: the wording changes ("Animals
accounted for"), Combine keeps the accounting.

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
6. **The Bookshelf page is built on every opening (about 50 s for NIEHS-12).** A
   kept copy, rebuilt when the report's content changes, would open at once. Not
   in the path; say if it should be.
7. **The Studies list shows every study in the store**, the unpublished ones
   (Bisphenol AF, Triclosan) among them, below the Demo block. Say if the demo's
   screen should show the Demo block alone.
8. **The stage reads "Data reviewed" as soon as the files are combined.** Combine
   runs the accounting of the animals with it (as the command line does, so the
   Methods get their counts), and that is the act the core calls the data
   approval. No person reviewed anything. Say if Combine should stop before the
   accounting, or the stage's words should change.
9. **A row of a results table is linked to its dataset endpoint by name only.**
   Clinical chemistry rows match; organ-weight rows ("Heart Absolute (g)") read
   "not recorded for this row", with the experiment's endpoints listed beside.
   Recording the link when the table is built is a change to the table builders.
10. **The acts of the Written sections page are offered on the live copy only.**
    Say if an ordinary study should have them there.
11. **The two workflow steps without a page** (BMD review, knowledge base; BOARD,
   2026-11-18): not in the path. The Process page shows the knowledge base
   read-only; a flagged benchmark dose appears in the review rail as something
   that blocks publishing.
12. **The Review page (from its build, 2026-11-19):**
    - after an approval the mark reads "Final"; after a reopening, "Kept as
      written". Say if one approval should read otherwise;
    - a study's Summary waits for "the Background or a result section" to be
      approved, and in a report of two studies the Background is the report's:
      approving it does not release the study's Summary; a result section of that
      study does. A change to the workflow core (`workflow/section_catalog.py`),
      not made;
    - a study's Methods row scrolls to that study's Study Design, not to the top
      of Materials and Methods;
    - the Bookshelf page inside the frame keeps its own links ("Compare with
      NIEHS-12", "Published content") on the finished report;
    - the delete and create dialogs of the Studies pages (M1, signed off earlier)
      still address the reader as "you" in a few messages.
