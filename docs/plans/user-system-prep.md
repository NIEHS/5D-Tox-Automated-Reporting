# A user system: preparation for planning

**Written 2026-11-19. Nothing here is decided and nothing is built.** This note
gathers what a plan will need: the purpose as the maintainer stated it, what the
software records about people today, what earlier decisions it touches, and the
questions to settle before a plan can be written.

## 1. The purpose (the maintainer, 2026-11-19)

> keep track of who works on what, who approves of what, and making only the
> user's responsibilities editable, while keeping the entire
> document/workflow/progress visible

Four requirements are in that sentence:

1. **Who works on what** is tracked.
2. **Who approves what** is tracked.
3. **A person can change only what is theirs.**
4. **Everyone sees everything**: the whole document, the whole workflow and its
   progress. Responsibility limits acts, never sight.

## 2. What it reopens

| Earlier position | Where | What changes |
|---|---|---|
| No login, no roles; "we may need that in future, not now" | maintainer, 2026-10-28 | now |
| "People. … Does the new interface need users, roles or sharing?" | `docs/ui-redesign/HANDOFF.md` §10, question 8 | answered yes |
| The safeguards layer checks the **act** (phase, inputs, ownership by person or machine, publish gate), not the **person** | ADR-0031, `safeguards/` | a check of the person joins it |
| An approval records when, not who | `workflow/section_writes.py`, `metadata_approved.json`, `study_design.json` | records who |
| "Sign each part where it is stored" was a proposal to the study team, which would reverse ADR-0018 and needs sign-in | team presentation, 2026-11-17 | this is the sign-in it needs; ADR-0018 itself is a separate question (§5, E) |
| Text is edited outside, in Word (Gate 0 Q1) | `docs/ui-redesign/MODULES.md` §8 | not touched: "editable" below means the acts and the stated values, not report text, unless the maintainer says otherwise |

## 3. What exists today that a plan can build on

**One door for every act that changes something.** The interface's routes and
the command line call `safeguards.guarded`, which checks the act and then calls
the core step. A check of the person belongs at that door. The notebook calls
the core directly, by design, and whoever can reach the files can change them:
a user system holds for the interface and the API, not for the notebook or the
file store.

**The acts are a short, closed list.** `workflow.phases.Action` (add files,
remove a file, reset, check, settle a conflict, confirm a classification,
combine, state facts, account for the animals, process), the section acts
(approve, reopen, restore), the reviewer's decision on a flagged benchmark dose,
the choice of method and report definition, the writing acts (Background,
Summary), creating and deleting a study, and the report's details. A table of
"which responsibility may do which act" is small.

**What is recorded about the doer today:**

| Record | Says | Does not say |
|---|---|---|
| Section history (`history/<key>/index.jsonl`) | `actor`: person or system; when; the reason on a reopening; **a `user` field that is always empty** | who |
| Method and report-definition pins | `pinned_by`: "user", "default", or a tool's name | who |
| Stated study facts (`study_design.json`) | when | who |
| Experiment descriptions approved (`metadata_approved.json`) | when | who |
| Reviewer's decisions on flagged benchmark doses (`bmd_reviews.json`) | decision, reason, when | who |
| Conflicts between files settled (`precedence.json`) | the choice, when | who |
| Data approval (the animal accounting) | when | who; and no person reads anything, the software accounts |
| A long step under way (`ui_api/runs.py`, interface branch) | which step, since when | who started it |

The section history already has the place for a name. The other records need
one.

**Every request already carries a record of its own.** The server gives each
request an id, and every workflow step is wrapped so that its start, end and
failure are written to the study's `.provenance.jsonl` under that id
(`common/provenance.py`, `step_provenance`). It is kept for diagnosis and names
nobody, but it is the mechanism a name per request would travel by: set once
when the request arrives, read by whatever records the act.

**The interface already says "not allowed, and why".** The read model serves,
per section and per act, whether it is allowed and the reason in words
(`accept: {allowed, code, say}`), and the pages show a disabled control with the
reason, or none. "This part is not assigned to this person" is one more reason
of the same shape. The demo pair already has an instance: the finished report
shows everything and offers no act (`demo_reference`).

**Sections already have owners of a kind.** The catalog knows, for each section,
who writes it (the program, a model, supplied text) and whether it is approved
on its own; the Review page groups sections by the report and by each study.

**A first draft of the responsibilities exists**, made for the study team
(`output/presentation/report-preflight-checklist.md`, and the slide "A first
draft: who does what, in what order"). It names kinds of expertise, not people:

| Expertise | Signs, in the draft |
|---|---|
| Data handling | the package is complete; the file check's notes; conflicts between files; values marked inferred; the deposited files |
| Study conduct | the study facts as in the protocol; every animal accounted for; what the text says about the animals |
| Statistics | the method; deviations from it; flagged benchmark doses; the analysis part of the Methods |
| Genomics | the genomic settings; claims about genes and gene sets |
| Toxicology | interpretive claims; whether a flagged value is plausible |
| Report policy | authors and report number; whether a deviation may be published; the final document |
| The accountable author | the release: name and date |

"Every line is a guess made from reports and data": the team has not confirmed
it.

**Workspaces** (`tooling/workspace.sh`) give a person their own store and
ports. That separates people; it is the opposite of several people on one
report.

## 4. What does not exist

- Any notion of a person: no accounts, no sign-in, no session, no name on a
  request.
- Assignment: nothing says who is to do what on a study.
- An approval by more than one person, or by a named kind of expertise.
- A release act by an accountable author. The publish gate is derived; nobody
  signs.
- A view of "what is waiting for whom".

## 5. Questions to settle before a plan

**A. Who a person is**

1. How is a person known: the institute's sign-in (NIH login, on the NIEHS
   deployment), accounts kept by the application, or a name chosen from a list
   without a password? The first cannot be reached from this sandbox; the last
   tracks but does not protect.
2. Where will it run when several people use it: one shared deployment, or
   still one port per person?
3. Who adds people and gives them responsibilities: the maintainer alone, or a
   role for it?

**B. What a responsibility is**

4. The unit: a kind of expertise (the table in §3), a step of the workflow, a
   section of the report, or a whole study? The draft suggests expertise, which
   maps onto both steps and sections.
5. The scope: per study, per report, or across every study a person works on?
6. May one person hold several, and may two people hold the same one on a
   study?
7. Is there one person who answers for the whole report (the accountable
   author), and what may that person alone do?

**C. Approval**

8. Which approvals exist? Today: the data (by the software's accounting), each
   section, each flagged benchmark dose. The checklist adds: the study facts,
   the file check's notes, the method, the deviations, the final document, the
   release.
9. Does a section need one approval, or one per kind of expertise it takes
   (the Methods: study conduct and statistics)?
10. May a person approve what they wrote or stated themselves?
11. Does the publish gate wait for named approvals, and for the release?

**D. "Works on"**

12. Is "who works on what" the assignment (who is to do it), the record (who
    did it), or also the present (who has it open now)?
13. Is a part taken (claimed) by a person, or given by someone else?

**E. "Editable"**

14. What is covered: the acts and the stated values only, or also report text
    in the application (which reverses Gate 0 Q1 and ADR-0018)?
15. What does a person see on a part that is not theirs: the control disabled
    with the reason, or no control?
16. Is there an override (the maintainer, with a reason, recorded), as the
    command line has for other safeguards?
17. The long steps (Combine, Process) change the whole study. Whose are they?

**F. Visible**

18. Does everyone signed in see every study, the unpublished ones included, or
    is sight limited by study while everything within a study stays visible?
19. Is anything visible without signing in (the Bookshelf, the API page)?

**G. The record**

20. What is done with what was recorded before there were names ("by a
    person")? Left as it is, or attributed?
21. Is the record of who did what part of the report (a changelog, C11), or
    only kept beside it?

**H. Reach and order**

22. The notebook and the file store stay outside it. Is that acceptable for the
    use intended, or must the notebook also name its user?
23. Does the demonstration of about 2026-12-02 show any of it? If not, this is
    planned now and built after.
24. Has the study team answered "who does what, in what order" since the
    presentation? Their answer decides B and C more than any design here.

## 6. Constraints a plan must respect

- A guard in the interface alone does not hold: the API is open, so the person
  is checked at the door (`safeguards.guarded`), and the interface shows what the
  door would say.
- State is derived, never stored imperatively (invariant 3): "what is waiting
  for whom" is derived from the assignments and the artifacts, like the phase.
- Core packages do not import the safeguards layer (ADR-0031); the core records
  the name it is given, the layer decides whether the act is the person's.
- Content and core changes go on `main`; the interface branch is interface only.
- An ADR records the decision before code: it supersedes the "no access
  control" position and names what ADR-0018 keeps.

## 7. A suggested order for the planning

1. The maintainer answers A1, B4, C8, E14 and H23: they shape everything else.
2. The responsibilities and their acts are written as one table (who may do
   which act, who approves what), on NIEHS-12 as the worked example.
3. The record: one shape for "who, when, what, why" on every act, and where each
   existing record gains it.
4. The read model: what the state serves about the person and the assignments,
   and the reasons for a refusal.
5. The pages: what each existing page shows differently, and the one new view
   (what is waiting for whom).
6. The ADR, then the build order.
