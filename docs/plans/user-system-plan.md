# A user system: the plan (draft, for the maintainer)

**Draft of 2026-11-19. Nothing is built, and nothing is to be built until the
maintainer agrees to this plan.** It follows `user-system-prep.md` (the purpose,
what exists, the questions) and the maintainer's five answers of the same day.

## 1. The answers, and how each is read

| # | The maintainer's answer | Read as |
|---|---|---|
| 1 | "for now, choose from a list; enter a provided OTP; maybe NIEHS login integration later." | A person picks their name from a list and enters a one-time code the administrator gave them. The institute's sign-in may replace the code later; everything else stays. |
| 2 | "any subset or entire report. maybe some set of granular roles. signoff and editing are separate subsets, based on admin-configured configuration." | A person's responsibility on a report is two sets of its parts: the parts they may **edit** and the parts they may **sign off**. Either may be anything from one part to the whole report. Named roles are bundles of such sets. An administrator configures all of it. |
| 3 | "to be decided. let's go with what we have for now" | The approvals are today's: the accounting of the animals, each section that is approved on its own, each flagged benchmark dose. The model must take more without being redone. |
| 4 | "text is editable. perhaps methods. perhaps document structure; depending on role. data is editable only by file replacement." | Report text can be edited **in the application** by a person whose role covers it. The analysis method and the report's structure may be editable by role too. Data is never edited in place: a file is replaced and the steps run again. |
| 5 | "planned now. when we implement, make it hidden so only I can reveal if i choose." | Planned now, built after. Built behind a switch that is off unless the maintainer turns it on; while it is off the application behaves exactly as it does today. |

**Three follow-up answers (the maintainer, 2026-11-19), taken into the plan
below:**

| Asked | The maintainer's answer | Read as |
|---|---|---|
| "methods" in answer 4 | "yes. analysis methods. this would, of course extend to M&M, from the change in methods." | The analysis method and its settings are editable by role. The Materials and Methods section follows a change of method; it is not a second thing to change. |
| How the switch is turned | "we could run the server on 2 ports. demo can switch by changing url" | The same reports are served at two addresses: one with the user system, one without. The address decides, so a demonstration switches by changing the address. |
| The stated study facts | "treat as data." | The facts no file records (species, strain, route, dosing days …) are changed only by replacing a file, like every other datum. They are not typed into the application. |

## 2. What answer 4 changes

**It reverses a standing decision.** ADR-0018 (accepted 2026-09-11, "The app is
not an editor") says: "There is no in-app authoring of prose." Gate 0 Q1 of the
interface's plan repeats it, and the Review page built this week says "Text is
edited in Word; the application does not edit text." Answer 4 makes the
application an editor again, for people whose role covers the text.

What ADR-0018 keeps: the round trip (a Word or Overleaf copy goes out, its
changes come back as a tracked difference) stays as the other way to edit. The
two ways meet in the same place: a person's text in a section file, with its
history.

**The core is already prepared for a person's text.** A section a person edited
is owned (`workflow.ownership.is_owned`: `user_edited`), so no machine may
replace it; every write goes through one gate with a history line
(`workflow.section_writes.write_section`, author `person`); a past version can
be restored. What is missing is the act itself (a guarded "save this text" step)
and the editor in the interface.

**Not every part's text can be edited today.** By how the text is kept:

| Text | Kept as | Editable once an editor exists |
|---|---|---|
| Background, Summary | a section file with history | yes |
| Front matter (foreword, authors, …) | the report's details (`front_matter.json`) and standard text | yes, as the report's details |
| Results tables' narrative (`bm2_*`) | a section file, rewritten by every Process | only after deciding what Process does to a person's edit (open question Q1 of the interface's plan) |
| Methods, the benchmark dose summary, the gene-level interpretations | only with the Process results, not as section files | only after they become section files (C9 of the interface's plan) |
| The Abstract; the group narratives (animal condition, clinical pathology, internal dose) | built by rule from the data and the other parts on every render | only after deciding that a person's text may stand in for a rule's |

So "text is editable" is a body of work of its own, in stages (§9).

**"Data is editable only by file replacement"** is the software's rule already
(the combined dataset is the single source of truth; a wrong value is fixed in
its file). One thing sat between data and text: the **stated study facts**
(species, strain, route, dosing days …), which no file records and a person
types today into one record (`study_design.json`, "the one place stated values
live"). The maintainer's answer: they are data. So they arrive in a **study
facts file** that belongs to the study's files, is checked on arrival like any
other (against the controlled vocabularies, and against what the workbooks do
record), and is changed only by being replaced. The step "State facts" stops
being typing and becomes bringing in that file. This also gives the facts the
formal access point the study team was asked about: the file is what the team
delivers. Its form is open (§11, 1).

**A change of method reaches Materials and Methods by itself.** The Methods
text is built from the record of the computation that ran (ADR-0036), so a
person who changes the method and runs Process again gets Methods that say so.
The person who may edit the method needs no grant on the Methods text for
that; a grant on the Methods text is for wording.

## 3. The model

**Person.** A name on the administrator's list, with an id that never changes
and a mark for active or not.

**Part.** What a responsibility refers to. A report's parts:

| Part | What editing it means | What signing it off means (today) |
|---|---|---|
| Files | add, replace or remove a file, the study facts file among them; settle a conflict between files; confirm what a file is | – |
| Method | choose the analysis method and its settings | decide a flagged benchmark dose |
| Structure | choose the report definition; later, change the report's sections and order | – |
| Report details | the front matter, the deposit, the knowledge base | – |
| Each section of the report | edit its text; ask a model to write it again | approve it, reopen it |
| The runs | Combine, Process | the accounting of the animals (done by the software with Combine today) |
| The release | – | (none today; the place for an accountable author's signature) |

A report over several studies has each study's parts and its own. "The entire
report" is every part of the report and of its studies.

**Grant.** One of two kinds on a part: **edit** or **sign off**. They are
separate: holding one says nothing about the other.

**Role.** A named bundle of grants, written by the administrator, for example
"Statistics: edits Method; signs off the result sections and the flagged
benchmark doses". The roles are configuration, not code; the first set can be
the kinds of expertise of the pre-flight checklist, to be corrected by the team.

**Assignment.** A person holds one or more roles on a report, or grants given
directly ("any subset"). Assignments belong to the report.

**Administrator.** The maintainer, and whoever the maintainer names. Keeps the
list of people, the roles and the assignments; gives out the one-time codes;
may do any act, with a reason, recorded.

**Sight.** Everyone who is signed in sees every study, every part, the whole
workflow and its progress, and who holds and who did what. A grant limits acts,
never sight.

## 4. Signing in

1. The sign-in page lists the active people. A person picks their name.
2. They enter the one-time code the administrator gave them (made on the
   administrator's page, shown once, handed over in person or by message; the
   application sends nothing).
3. A correct code is used up, and the browser is signed in for a set time
   (proposal: 12 hours, or until "Sign out"). The next sign-in needs a new code,
   unless the maintainer prefers a code that works for a set period (§11, 3).

Codes are kept as hashes, expire unused (proposal: 24 hours), and a few wrong
entries lock the name until the administrator makes a new code.

**What this protects, plainly.** It identifies people and keeps colleagues to
their own parts. It is not strong protection: the list of names is visible, the
connection is as private as the network it runs on, and anyone with access to
the files or the notebook is outside it. The institute's sign-in later replaces
step 2 and the code; the person, the roles and the records stay as they are.

## 5. Where the person is checked, and what is recorded

**Checked at the one door.** Every act of the interface and the API already
goes through `safeguards.guarded`. A new check there asks: is this act, on this
part of this report, within this person's edit or sign-off grants? If not, the
act is refused with a reason that names who holds it. The core never asks who
may; it is handed the person's id and records it (ADR-0031's rule holds).

**The name travels with the request**, the way the request id does today
(`common/provenance.py`): set once when the request arrives, read by whatever
records the act.

**One shape of record**, on every act: who (id, and the name at the time), when,
which act, on which part, and the reason where one is asked. It fills the places
that exist and are empty or missing:

| Record | Today | Gains |
|---|---|---|
| Section history | `user: null` | the person |
| Method and definition pins | `pinned_by: "user"` | the person |
| Stated facts, approved experiment descriptions, settled conflicts, reviewer's decisions | a time | the person |
| A long step under way | which step, since when | who started it |
| – | – | one list per study of every act in order (who, when, what), which the views are derived from |

Records made before there were names stay as they are ("a person").

**Derived, never stored:** what is waiting, and for whom. It comes from the
assignments and the state of the parts, like the phase.

**Outside the door.** The notebook calls the core directly and stays unguarded.
The command line is guarded; it would take the person as an option and record
it.

## 6. The switch (answer 5)

Off unless the maintainer turns it on. While it is off:

- no sign-in page, no names, no routes for people or roles, nothing on the API
  page, nothing in the interface that hints at it;
- every act is allowed as today and recorded as today;
- the tests that run today pass unchanged.

**Two addresses, one set of reports (the maintainer's answer).** The server
answers on two ports: on one the user system is on, on the other it is off. A
demonstration switches by changing the address. Only the person who runs the
server decides whether the second port exists at all.

Two things follow, and the plan takes both:

- **One server, not two.** The server keeps some things in memory (the long
  step under way on a study, the sessions it has open), so two separate servers
  on the same reports would not see each other's runs. One server listens on
  both ports and takes the mode from the port a request arrived on.
- **The port without the user system has no checks at all**, on the same
  reports: anyone who can reach it can do anything, and what they do is recorded
  without a name, as today. That is what a demonstration wants. Where the
  responsibilities are meant to hold, that port is not opened (§11, 2).

## 7. What the interface shows (when the switch is on)

- **Who is signed in**, in the header, with "Sign out".
- **On every part:** who may edit it, who may sign it off, and who last did
  what and when.
- **A control that is not this person's** stays visible and disabled, with the
  reason ("Statistics signs this off: A. Name"). This is the pattern the pages
  already use for an act that is not allowed yet.
- **One new view: what is waiting, and for whom**, for a report and across
  reports ("My work").
- **The editor**, on a section whose text this person may edit: the text, save
  with a note, the history, restore.
- **The administrator's pages:** people, roles, assignments per report, codes.

## 8. Decisions to record before code

1. **A new ADR: people and responsibilities.** Supersedes the position of
   2026-10-28 (no access control); adds the check of the person to ADR-0031's
   layer; states what is and is not protected.
2. **An amendment of ADR-0018:** text is edited in the application by a person
   whose role covers it; the round trip stays; Gate 0 Q1 of the interface's plan
   changes with it.

## 9. Build order (each stage behind the switch)

| Stage | What | Where |
|---|---|---|
| 0 | The two ADRs | `main` |
| 1 | **Tracking only.** People, codes, sign-in, the two ports; the person recorded on every act. Nothing is refused yet. | `main` (core, safeguards), interface branch (sign-in, header) |
| 2 | **Responsibilities.** Parts, grants, roles, assignments; the check at the door; the reasons. The study facts file: its form, its check, and the step that brings it in. | `main` |
| 3 | **Shown.** Who holds what on every part; disabled controls with reasons; "what is waiting for whom"; the administrator's pages. | interface branch |
| 4 | **Text editing, first parts:** Background, Summary, the report's details. The guarded save act and the editor. | `main`, then the interface branch |
| 5 | **Text editing, the rest**, as each precondition of §2 is decided: results narratives, Methods and interpretations, group narratives. | both |
| 6 | **Method and structure by role**, with the Configurator the interface's plan already has (D5). A change of method reaches Materials and Methods through Process. | both |
| 7 | **The institute's sign-in**, when it can be reached. | `main` |

Stage 1 alone answers "who works on what, who approves what" for the record;
stages 2 and 3 answer "only the user's responsibilities editable, everything
visible"; stages 4 to 6 are answer 4.

## 10. What this does not change

- The demonstration of about 2026-12-02: none of this is in it.
- The approvals themselves (answer 3).
- The notebook, which stays the workflow without safeguards.
- Workspaces (a store and ports per person), which remain for people trying the
  tool on their own data.

## 10a. A requirement beside users: text may not contradict the data

The maintainer, 2026-11-19: "if any text is altered that contradicts the data
should not be allowed." It is not about people or roles; it comes with text
editing (stages 4 and 5) and applies to every way text arrives: typed in the
application, returned from Word, written by a model. Not designed yet. What is
known:

- **Where text is built from data, it can be made impossible.** A results
  narrative is a template: wording with places that refer to the data
  (`narrative/section_template.py`), and an edit touches the wording only. A
  number or a data-derived word ("increased") cannot be typed over. Sections do
  not keep their template today (`workflow/reprocess.py`, deferred), so this is
  work, not a switch.
- **In free prose, rules can decide some contradictions** (a value that differs
  from its table, a dose, sex, species, organ, route or unit the study does not
  have, a direction against the table). A few run today on the finished
  document only (`tooling/report_qc.py`). These can refuse a save.
- **Meaning cannot be decided by rule** ("the liver was the most sensitive
  organ"). A model can flag it for a person; it cannot be the ground for a
  refusal.
- Open: whether a refusal by rule has a way through with a reason (text that
  quotes another study's value looks like a contradiction to a rule).

## 11. Still open, for the maintainer

Answered on 2026-11-19 and taken into the plan: what "methods" means, how the
switch is turned, and the stated study facts (§1).

1. **The study facts file.** Its form: a small workbook or text file the
   application hands out already filled with the study's current facts and the
   allowed values, to be changed and brought back (proposal); or a sheet the
   study team adds to its own workbooks. And the experiment descriptions a
   person approves today: data as well (proposal: yes, the same file), or a
   decision about the files like settling a conflict?
2. **The port without the user system:** for demonstrations and the
   maintainer's own use only, and not opened where the responsibilities are
   meant to hold (proposal). Until the study facts file exists, the typed form
   stays on that port.
3. **The code:** used up at each sign-in (proposal), or good for a set period?
4. **A part nobody holds:** only the administrator may act on it (proposal), or
   anyone may until someone is assigned?
5. **The runs (Combine, Process):** their own part with its own grant
   (proposal), or allowed to anyone who may edit Files or Method?
6. **A model writing a section again** (Background, Summary): counted as editing
   that section (proposal), or a grant of its own?
7. **Assignments:** per report only (proposal), or also a standing role across
   every report a person works on?
8. **May a person sign off text they edited themselves?** Left with the
   approvals (answer 3) unless the maintainer says now.
