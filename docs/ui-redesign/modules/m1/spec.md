# M1 Studies: create, list, open and delete a study

Module M1 (`MODULES.md` §3). Written 2026-10-14 by the interaction designer from
`modules/gate0-data/analysis.md` §2 L, finding 9 and §3, the Gate 0 decisions
(`MODULES.md` §8, Q7) and the Bookshelf's code. It builds on the shared kit and
the shared contracts of `MODULES.md` §4 and does not redefine them. The endpoints
and fixtures are in `contract.md`.

Points marked **[maintainer]** need a decision (collected in §11). Points marked
**[request]** are things M1 needs from the orchestrator (the shell, the kit, a
shared contract or another module), collected in §10.

---

## 1. The person's goal

> "I want to start a report on a chemical, find a study I'm already working on,
> and throw one away when I'm sure I no longer want it, without ever working on
> the wrong study or the wrong chemical."

In detail:
- **Start a study.** Give the chemical's DTXSID, see which chemical it is (name,
  CASRN, structure) and which report format the study will be written in, and
  confirm both before anything is written.
- **Find a study.** See every study, grouped by chemical, with where it stands
  and what to do next. Tell a study apart from the sessions the system made beside
  it: a published book's content, the rat and mouse studies of a report over
  several studies, sessions made by tools.
- **Open a study.** Land on its page: what it is, where it stands, the next step,
  its format, whether its report is on the Bookshelf.
- **Delete a study.** See exactly what goes and what stays, type the id, and
  delete it for good.

## 2. When the module is reachable

M1 is the interface's entry point. Every value it shows about the workflow comes
from the backend (`contract.md`). The browser computes no phase, readiness or
permission.

| Screen | Route in the app | Reachable when |
|---|---|---|
| S1 Studies list | `/app/studies` | always |
| S2 New study | `/app/studies/new` | always |
| S3 Study page | `/app/studies/:id` | `GET /api/v2/studies/{id}` answers 200. On `study_not_found` (404) it shows S5; on `invalid_study_id` (400) it shows S5's invalid variant |
| S4 Delete dialog | opened from S3 | `row.actions.delete.allowed` is true (derived by the backend from the session's kind and from `state.run.in_flight`) |
| S5 No such study | in place of S3 | as above |

**[request]** The routes are registered in the shell's router, which belongs to
the orchestrator (R9).

What the backend derives, and M1 only renders:
- `kind`: study / report over several studies / member study / published content /
  other session, derived from what is on disk (`studies.json`,
  `published_clone.json`, the id's shape, membership in a parent's `studies.json`);
- `stands`: the phase from `WorkflowEngine.state()`, in plain words, and the
  `next` step with the module that does it;
- `format`: the definition the session renders from, why, and what the id brings
  with it;
- `bookshelf`: on the shelf or not, and why not;
- `actions`: whether Open and Delete are allowed, and if not, why, in plain words.

---

## 3. Screens

### S1 Studies list (`/app/studies`)

**Layout:**
- a page header "Studies" with the primary button **New study** (to S2);
- a search `Input.Search` ("Find by name, CASRN or DTXSID");
- an antd `Table` with tree data (expandable rows).

**Rows.** One top-level row per **chemical**, in the order and grouping the
backend sends (`contract.md` §2.1). Sorting by last change is the default; a
column sorter on "Chemical" sorts by name.
- The top-level row shows the chemical's **primary session**: its study, or its
  report over several studies.
- If the chemical has no primary session (for example only a tool's session
  exists), the top row says "No study of this chemical yet" and offers
  **Create a study** (to S2 with the DTXSID filled in).
- Child rows are the chemical's other sessions in the backend's order: member
  studies, then published content, then other sessions.
- A last top-level group, "Sessions not tied to a chemical", holds sessions whose
  id carries no DTXSID number (`DTXSID_TEST`).
- Top-level rows start collapsed. A search hit in a child row expands its parent.
  The collapsed row shows a child count ("+ 1 published content, 1 other session").

**Columns:**

| Column | Content |
|---|---|
| Chemical | name (bold); below it, the DTXSID and CASRN in a monospace caption. A missing name or CASRN is a `<Pending>` "[name pending]" / "[CASRN pending]" linking to S3, where it can be filled in (§5) |
| Session | a `Tag` for the kind ("Study", "Report over 2 studies", "Rat study, part of a report", "Published content", "Other session") and the session id in monospace |
| Report format | `format.title_short` (for example "NIEHS Report, March 2023"); if the session reproduces a published report, a second tag "NIEHS-10 · 2023 Mar". A `Popover` on the cell shows `format.say` |
| Where it stands | `<PhaseTag>` with `stands.say` (R3); below it, "Next: " and `stands.next.say` as a link to the module `stands.next.fix`. For published content and reports over several studies, the backend sends no phase, only `stands.say` |
| Last changed | relative time ("2 days ago"); the exact time (local) in a `Tooltip` |
| Bookshelf | if `bookshelf.on_shelf`: a link "On the Bookshelf (draft)" to `bookshelf.url`, opening in a new tab. Otherwise `bookshelf.say` in secondary text ("Not yet: the study has no report, it has not been processed") |
| (actions) | **Open** (to S3). There is **no delete in the list**: deleting happens only on the study's own page |

**Other states:**
- *Loading:* `Skeleton` rows.
- *Empty store:* `Empty` "No studies yet" with **New study**.
- *Error:* the kit's `<Refusal>` with the envelope.
- *A session the backend could not read fully* (for example a corrupt
  `identity.json`) still lists. Its row carries a warning icon with `notes[].say`.

The list refreshes on window focus and after any create or delete. It keeps
nothing in browser storage.

### S2 New study (`/app/studies/new`, optional `?dtxsid=`)

An antd `Steps` with three steps: **1 The chemical's DTXSID → 2 Confirm the
chemical and the format → 3 Created.** Reloading the page returns to step 1, and
nothing has been written before step 3.

**Step 1: the chemical's DTXSID.**
- A `Form` with one field, the kit's `<IdField kind="dtxsid">`: label "The
  chemical's DTXSID".
- Help text: "Find it on the CompTox Chemicals Dashboard. The study's id is this
  DTXSID, and it can't be changed later."
- The validation rules are in §4. The field shows the first failing rule as it is
  typed.
- When the id is well formed, the screen calls `GET /api/v2/studies/{dtxsid}/creation-check`
  (on blur and on **Next**, debounced).
  - If a study of that id already exists, an `Alert` (warning) says: "A study of
    this chemical already exists: DTXSID50469320, Perfluorohexanesulfonamide."
    It has an **Open it** button, and **Next** stays disabled.
  - Other sessions of the same chemical are listed under the field in an
    `Alert` (info): "Already here for this chemical: DTXSID50469320_nb (other
    session, made by a tool)". It is information only.
- **Next** is enabled only when the format check passes and the id does not
  exist. It runs the lookup (`GET /api/v2/chemicals/{dtxsid}`) inside step 2,
  with an antd `Spin` "Looking up DTXSID7020182 in PubChem…". The lookup takes a
  few seconds; there is no background job.

**Step 2: confirm the chemical and the format.** Two cards.

1. **"The chemical"**: `Descriptions`, filled from the lookup:
   - Name;
   - CASRN;
   - DTXSID, with a check mark and "PubChem lists this DTXSID for this compound"
     when `dtxsid_matched` is true. When it is false, an `Alert` (warning): "PubChem
     found a compound, but does not list DTXSID… for it. Check the id on the
     CompTox dashboard before you go on." In that case the confirm checkbox below
     stays disabled until the person ticks a second box, "I checked the DTXSID on
     the CompTox dashboard";
   - molecular formula and molecular weight;
   - the PubChem number (CID), as a link to the PubChem page, opening in a new tab;
   - the structure, an `Image` from `GET /api/v2/chemicals/{dtxsid}/structure.png`.
     If it fails, a `<Pending>` "[structure picture unavailable: PubChem did not
     return one]".
   - Under the card, the source line from the response, for example "Looked up in
     PubChem just now. The CompTox (CTX) lookup is not set up on this server."
   - Synonyms are not shown. The chemical class is not shown (it is free text from
     the service).
2. **"The report format"**: an `Alert`.
   - *Info* when the id brings the format for new studies (`format.source == "default"`).
   - *Warning* when it brings a published book's format (`format.source == "study"`).
   - The text is `format.say`, for example: "This chemical has a published report,
     NIEHS-10 (March 2023). A study under this id is written in that book's
     format: the NIEHS Report as published in March 2023, unaltered."
   - Under it, the list `format.brings[].say` ("It also brings: the book's choice
     of organs and endpoints for its tables; the book's captions for its deposited
     files and its data DOI; Appendix A's text as published").
   - The last line: "The DTXSID decides this. It can't be changed here."
     **[maintainer]** Q-M1-2.

**The confirm checkbox** is required, and **Create study** stays disabled until it
is ticked. Its label names both facts: "This is the chemical I am studying, and the
study will be written in *the NIEHS Report format as published in March 2023
(NIEHS-10's)*."

**Buttons:** **Back** returns to step 1 with the id kept. **Create study** sends
`POST /api/v2/studies` (contract §2.6) with the confirmed identity and the format
the person saw (`format_seen`).

**When the lookup fails:**
- *`identity_not_found`*: an `Alert` (error) in place of the chemical card: "PubChem
  has no chemical with the DTXSID DTXSID0000000001. A single mistyped digit gives
  another chemical or none. Check the id on the CompTox dashboard." It has a
  **Back to the id** button. No name is shown, and none is filled in ("Test
  Article" never appears).
  - **[maintainer]** Q-M1-3: should a link "The id is right; I'll state the
    chemical myself" open a small form? The form would have the name (required,
    trimmed, not empty), the CASRN (`<IdField kind="casrn">`, §4) and a
    required tick "I checked this DTXSID on the CompTox dashboard". The identity
    would then be saved as *stated, not confirmed by a lookup* and shown that way
    everywhere. **Until the maintainer decides, the link is not built** and
    creation is impossible without a lookup.
- *`identity_lookup_unreachable`*: an `Alert` (warning): "The chemical lookup
  service (PubChem) could not be reached. Nothing was created." It has a
  **Try again** button.

**When creation is refused:** the kit's `<Refusal>` appears inside step 2 (codes in
§6).
- `study_exists`: shows **Open it**.
- `format_changed`: re-runs the creation check, shows the new format, and unticks
  the checkbox.

**Step 3: created.** An antd `Result` (success): "Study DTXSID7020182 created:
Bisphenol A (80-05-7)". It repeats the format title, and shows the next step from
the response's `stands.next` as the primary button ("Bring in the study's files").
The secondary button is **Back to studies**.

### S3 Study page (`/app/studies/:id`)

It reads `GET /api/v2/studies/{id}` (the row and the detail) and the kit's
`useStudyState(id)` (§4.1). Re-reading follows the kit's rules.

**Header:**
- the name (or `<Pending>`);
- the session id;
- the kind `Tag`;
- `<PhaseTag>`.

**A banner by kind** (`Alert`, not closable). The backend writes the text
(`detail.banner`); the cases:
- *published content:* (info) "This is the published book's own content (NIEHS-10),
  built by a tool from the published book. It can't be changed or deleted here."
  It links to "Read it on the Bookshelf" and to "The generated study:
  DTXSID50469320". The workflow modules are not offered (R1).
- *member study:* (info) "This is the rat study of the report DTXSID1020431
  (1,4-Dichlorobenzene, NIEHS-13), which also has a mouse study. Its data is
  prepared here; its report is the parent's." It links to the parent and to the
  sibling.
- *report over several studies:* (info) "A report over two studies. The data is
  prepared in each study; this report gathers them." A small `Table` of its
  members follows, with each member's `stands` and **Open**.
- *other session:* (warning) "This session's id, DTXSID50469320_nb, is not a
  chemical's DTXSID: it was made by a tool. Its report uses the 2026 format; a
  study under DTXSID50469320 would use NIEHS-10's format."

**Cards:**
1. **"Where it stands"**: `stands.say`, and the next step as a primary button to
   its module.
   - If `state.run.in_flight`, the button is replaced by the text "Process is
     running on this study since 10:42" (the kit's `<Wait>` "already running"
     state is the Process module's; here it is only a line of text).
2. **"The chemical"**: `Descriptions` with the name, CASRN, DTXSID and short name.
   - The chemical's DTXSID for a suffixed session is labelled "taken from the
     session id".
   - The short name, when missing, shows `<Pending>` "[short name pending]" with a
     link to Study facts (M4).
   - A provenance line from `identity.source`:
     - "Confirmed by a person from a PubChem lookup on 14 Oct 2026";
     - "Stated by a person, not confirmed by a lookup";
     - or "On file; how it was set is not recorded" (sessions made before M1).
   - If the session has **no identity** and its kind is study or other, the
     button **Look up the chemical** opens step 2's chemical card in a `Modal`, with
     the same confirm checkbox. It calls `PUT /api/v2/studies/{id}/identity`.
     Changing an identity that exists is not offered (Q-M1-11).
3. **"Report format"**:
   - `format.title` and `format.say`;
   - where the definition comes from (`format.source`: "this study's own definition
     under templates/studies/…", "the format for new studies", or "this
     session's own structure");
   - the pin from `state.pins.definition`: "Tracks the current definition" or
     "Fixed on 12 Oct 2026". It links to Method and document pins (M5);
   - the `format.brings` list.
4. **"Bookshelf"**: the link (new tab), or `bookshelf.say`.
5. **"Related sessions"**: a `List` of `relations` (parent, members, companion,
   twin, other sessions of the chemical), each with its kind tag and **Open**.
6. **"Delete this study"**, a card at the bottom with a red border (`danger`):
   - if `actions.delete.allowed`: the button **Delete this study…** (`danger`),
     which opens S4;
   - otherwise the button is disabled and `actions.delete.say` is written beside
     it. For example: "This is the rat study of the report DTXSID1020431. Deleting
     it would break that report."

### S4 Delete dialog (from S3)

1. Clicking **Delete this study…** calls `GET /api/v2/studies/{id}/delete-preview`.
   The button shows a loading state while it runs.
2. On 200, the kit's `<ConfirmAct strength="irreversible">` opens with the
   preview's `confirm` object (§4.3 shape):
   - the title "Delete DTXSID5032498 for good?";
   - **"What will be deleted"**: `deletes[].say`;
   - **"Approvals lost"**, in red, when not empty: the section names of
     `approvals_lost`;
   - **"What stays"**: `keeps[].say`;
   - `cost.say`, when present;
   - the input "Type DTXSID5032498 to confirm". **Delete for good** (`danger`) is
     enabled only when the typed text equals the id exactly. Leading and trailing
     spaces are ignored. Case matters.
3. **Delete for good** sends `POST /api/v2/studies/{id}/delete` with the typed id
   and the preview's `preview_token`.
   - On success: navigate to S1, with the `message` "DTXSID5032498 was deleted."
   - On `changed_since_preview`: the dialog reloads the preview, clears the typed
     id and shows an `Alert` "The study changed while this was open. Review what
     will be deleted again."
   - Any other refusal: `<Refusal>` inside the dialog.
4. A refusal of the preview itself (for example `run_in_flight`) shows
   `<Refusal>` and no dialog.

There is no undo after a delete (Q-M1-4).

### S5 No such study

An antd `Result`:
- **404** (`study_not_found`): "There is no study DTXSID7020182. It may have been
  deleted." If the id matches the strict DTXSID pattern, **Create a study of this
  chemical** links to S2 with the id filled in. **Back to studies** is always
  there.
- **400** (`invalid_study_id`): "'foo' is not a study id." **Back to studies**.
- Opening S3 for an absent id must leave no folder behind (C4). The list
  afterwards is unchanged.
- **Deleted while open:** if a tab has a study open and the study is deleted in
  another tab, the next read returns 404, and the page shows S5 with "This study
  was deleted."

---

## 4. Inputs and their validation (checked before anything runs)

| Input | Where | Rule, in the order checked; the message shown |
|---|---|---|
| Chemical DTXSID | S2 step 1 (`<IdField kind="dtxsid">`, strict) | 1. Required: "Enter the chemical's DTXSID." 2. Letters are made upper case **as typed, visibly in the field**; spaces at either end are removed on paste. 3. Must start with `DTXSID`: "A DTXSID starts with 'DTXSID', for example DTXSID50469320." 4. No suffix: if the text after `DTXSID` contains `_` or `-`: "A study's id is the DTXSID alone. Ids with a suffix (…_rat, …_published) are made by the system." 5. Look-alike letters: if it contains `O`, `I` or `L` where digits belong: "Character 14 is the letter O. A DTXSID has only digits after 'DTXSID'." The field never corrects this itself. 6. Digits only, at least one: pattern `^DTXSID\d+$` (`narrative/chem_resolver.py:52`): "After 'DTXSID' come digits only." 7. (backend) The id does not exist yet: `creation-check` |
| Pasted text containing a DTXSID | S2 step 1 | If the pasted text (for example a CompTox dashboard address) contains exactly one `DTXSID\d+`, a hint appears: "Use DTXSID7020182?" with a button that puts it in the field. The field is never filled silently |
| Confirm checkbox | S2 step 2, S3 identity modal | Required to enable the act. When `dtxsid_matched` is false, the second tick ("I checked the DTXSID on the CompTox dashboard") is required too |
| Typed id to confirm a delete | S4 | Equal to the session id, case-sensitive, ignoring spaces at either end |
| (only if Q-M1-3 is accepted) Name | S2 stated identity | Required; trimmed; not empty |
| (only if Q-M1-3 is accepted) CASRN | S2 stated identity (`<IdField kind="casrn">`) | Pattern `^\d{2,7}-\d{2}-\d$`; the CAS check digit must hold (the sum of each digit times its position counted from the right, starting at 1, modulo 10, equals the last digit). Message: "This CASRN's check digit doesn't match; a digit is probably mistyped." |

**[request]** The kit's `<IdField>` must take M1's hints for rules 4, 5 and the
paste hint, or carry them itself, and its patterns must come from the backend (R3
in §10 asks how).

The session id of a suffixed session is never typed anywhere in M1. It is opened
from the list or from links.

## 5. Actions, and what they map to

| Action | Screen | Backend (`contract.md`) | When not allowed, the person sees |
|---|---|---|---|
| List studies | S1 | `GET /api/v2/studies` | – |
| Check an id for creation | S2 | `GET /api/v2/studies/{dtxsid}/creation-check` | the rule's message (§4); "already exists" with **Open it** |
| Look up the chemical | S2, S3 | `GET /api/v2/chemicals/{dtxsid}`, `…/structure.png` | §6 |
| Create a study | S2 | `POST /api/v2/studies` → `workflow.steps.create_study_step` (NEW) | **Create study** is disabled until the checkbox is ticked; refusals in §6 |
| Open a study | S1, S3 | `GET /api/v2/studies/{id}`, `GET /api/v2/studies/{id}/state` (§4.1) | S5 |
| Go to the next step | S1, S3 | `stands.next.fix` names the module. It is a link, not an act | if a run is in flight, the text "Process is running…" replaces the button |
| Fill a missing identity | S3 | `PUT /api/v2/studies/{id}/identity` | the button is shown only when the identity is missing and the kind is study or other |
| Delete a study | S3 → S4 | `GET …/delete-preview`, `POST …/delete` → `workflow.steps.delete_study_step` (NEW) | the button is disabled with `actions.delete.say` (published content; a member study; a run in flight) |

Session delete is not one of the phase machine's legal actions. RESET and
CLEAR_FILES are pool acts, and they belong to M2. Whether deleting is allowed is
derived by the backend from the session's kind and the run lock (`actions.delete`).

## 6. Refusals the backend can return, in plain words

These are the §4.2 envelope `code`s M1 meets. The `say` text is written once in the
backend (proposed wording below). **[request]** Add the codes to the closed list (R5).

| code | status | `say` (proposed) | `fix` |
|---|---|---|---|
| `invalid_study_id` | 400 | "'{id}' is not a study id. A study's id is the chemical's DTXSID: 'DTXSID' followed by digits, for example DTXSID50469320." | – |
| `study_id_has_suffix` | 400 | "A study's id is the DTXSID alone. Ids with a suffix are made by the system." | – |
| `study_exists` | 409 | "A study of this chemical already exists ({id}). Open it instead." | M1 (open) |
| `study_not_found` | 404 | "There is no study {id}. It may have been deleted." | M1 (list) |
| `identity_not_found` | 404 | "PubChem has no chemical with the DTXSID {id}. A single mistyped digit gives another chemical or none. Check the id on the CompTox dashboard." | – |
| `identity_lookup_unreachable` | 503 | "The chemical lookup service ({service}) could not be reached. Nothing was created. Try again in a minute." | – |
| `identity_unconfirmed` | 400 | "Confirm the chemical before creating the study." | – |
| `identity_changed` | 409 | "The lookup now gives a different chemical than the one you confirmed. Look it up again." | – |
| `identity_incomplete` | 400 | "A name and a CASRN are needed." (stated path only) | – |
| `invalid_casrn` | 400 | "This CASRN's check digit doesn't match; a digit is probably mistyped." | – |
| `identity_exists` | 409 | "This study already has its chemical's identity. Changing it is not done here." | – |
| `format_changed` | 409 | "The report format this id brings changed since you looked. Review it again." | – |
| `structure_unavailable` | 404 | (shown as `<Pending>`, not as a refusal) "PubChem did not return a structure picture." | – |
| `read_only_session` | 409 | "This is the published book's own content, made by a tool. It can't be changed or deleted here." | – |
| `member_of_report` | 409 | "This is the {species} study of the report {parent}. Deleting it would break that report." | M1 (parent) |
| `run_in_flight` | 409 | "Process is running on this study (since {time}). Wait for it to finish." | P1 |
| `confirm_mismatch` | 400 | "The id you typed doesn't match this study's id. Nothing was deleted." | – |
| `changed_since_preview` | 409 | "The study changed after you reviewed what would be deleted. Nothing was deleted; review the list again." | – |
| `unreadable_session_file` | 422 | (existing, global) "A file in this study can't be read: {file}." | – |

## 7. Destructive acts

| Act | Strength | Confirm | Undo |
|---|---|---|---|
| Delete a study | irreversible (§4.3) | S4: the backend's dry run lists what goes, what stays and the approvals lost; the person types the id; the `preview_token` refuses a delete when the study changed after the person reviewed it | none (Q-M1-4) |
| Create a study | – | not destructive: creation refuses to overwrite an existing study (`study_exists`), atomically, so two tabs can't both create one | – |
| Fill a missing identity | – | the confirm checkbox; refuses when an identity exists | – |

## 8. Missing facts and inferences, shown

- Missing name, CASRN or short name: `<Pending>` "[name pending]",
  "[CASRN pending]", "[short name pending]". Each links to where it is filled: S3's
  **Look up the chemical** for name and CASRN, M4 for the short name.
- A failed lookup is a visible error (§3 S2), never a made-up name.
- The structure picture, when unavailable: `<Pending>`.
- A published report's date, when the book records none: "[publication date
  pending]".
- **Inferences, flagged:**
  - *the chemical's DTXSID of a suffixed session:* "taken from the session id";
  - *the report format:* "the DTXSID decides this", with the reason (`format.say`);
  - *the identity's provenance:* when it is unknown, "On file; how it was set is
    not recorded".
- M1 shows **no publish readiness**. Today's check says "can publish" for every
  session (verified for all 32), so M1 never shows "ready" until C6 serves real
  readiness. The next step "Publish" is offered only when the backend says so
  (contract §3).

## 9. Waits

There is no Process in M1, and nothing runs in the background.
- The lookup (a few seconds) shows a `Spin` inside step 2.
- The creation check, the creation, the delete preview and the delete are quick.
  Their buttons show a loading state and the screen waits.

## 10. Requests to the orchestrator

- **R1. `kind`, `chemical_dtxsid` and `relations` in the state read model (§4.1).**
  Every screen and the shell must know that a session is published content or a
  report over several studies, even when it is opened by its address. The shell
  must then hide the data modules for these kinds.
- **R2. `stands` (the phase in plain words, and `next: {say, fix}`) in §4.1**,
  from the same backend function as M1's list, so the shell and the list never
  disagree. The proposed rules are in `contract.md` §3.
- **R3. Kit:**
  - a `<PhaseTag>` that renders `stands.say` and colours by phase;
  - `<IdField kind="dtxsid">` with the strict pattern and M1's hints (§4);
  - `kind="casrn"` with the check digit;
  - the patterns served by the backend (`GET /api/v2/vocabularies` could carry
    `id_patterns`).
- **R4. A `preview_token` on §4.3 for irreversible acts.** An act refuses with
  `changed_since_preview` when what the dry run listed has changed. M1 carries it
  beside the §4.3 object until then.
- **R5. The error codes of §6** in the closed list.
- **R6. A backend guard** (C1's family): no upload or other data step into published
  content or into a report over several studies. Today they derive as EMPTY, and
  nothing stops an upload.
- **R7. Move the session-relation predicates to core.** `has_generated_report`,
  `clone_record`, `companion_of`, `_members` (`web_routes/bookshelf_routes.py:81-122`),
  `report_of` and `published_date` (`narrative/prompt_workshop.py:69-101`) should
  move into a core module (proposed `workflow/studies.py`), so the new routes don't
  import from a page module. `report_of` reads `tooling.build_published_reports.STUDIES`.
  This may also be the unwalled source Q17 needs for "which published report does
  this session reproduce". I have not seen the walled `published_report`, so
  whether the two agree is unverified.
- **R8. C4 must hold.** Opening S3 for an absent id must create no folder. Until C4
  lands, creation must treat an existing *empty* folder as absent.
- **R9.** Register `/app/studies`, `/app/studies/new` and `/app/studies/:id` in the
  shell's router, and M1's endpoints in the API client.

## 11. Open questions for the maintainer

- **Q-M1-1. The suffixed sessions.** Proposed:
  - *grouped under their chemical;*
  - *published content (`_published`):* opened read-only, never deleted here (a
    tool rebuilds it);
  - *member studies (`_rat`, `_mouse`):* opened and worked normally, but not
    deleted on their own;
  - *other sessions (`_nb`, `DTXSID_TEST`):* opened with a warning banner, and
    can be deleted.

  Agreed?
- **Q-M1-2. A new study of a chemical that has a published report gets that book's
  format**, and with it, from `templates/studies/<id>/`:
  - the book's organ and endpoint selections (`view.yaml`, NIEHS-10 only);
  - its deposit captions and data DOI (`deposit.yaml`);
  - its authored Appendix A (NIEHS-10).

  Is that wanted for a new, unpublished study of such a chemical? Today the id is
  the only way to choose: `definition_pin.pin_definition` can only fix or track the
  definition the id gives.
- **Q-M1-3. A DTXSID PubChem doesn't know.** Should a person be able to state the
  name and CASRN themselves (saved as "stated, not confirmed")? Or is creation
  impossible without a successful lookup? Until decided, it is impossible.
- **Q-M1-4. Delete for good, or a bin?** The brief says irreversible (`rmtree`, as
  `POST /api/session/reset` does today). A move to `sessions/_deleted/<id>-<time>/`
  with a restore would make it reversible. That would be safer for a non-programmer,
  at the cost of disk space (NIEHS-10's session is 121 MB). Which?
- **Q-M1-5. Deleting a report over several studies.** Delete the parent only (its
  members then show as "other sessions"), or the parent and its members together?
  And should a published reproduction (for example NIEHS-10's study) be deletable
  here at all? It can be rebuilt only from the command line.
- **Q-M1-6. The formats have no declared names.** The eras are described only in
  YAML comments. Proposed titles, to be declared in the era files (or in one table
  beside `DEFAULT_DEFINITION`):
  - `eras/ntp-rr-2018`: "NTP Research Report, as published in December 2018 (RR-8)";
  - `eras/niehs-2022`: "NIEHS Report, as published in October 2022 (NIEHS-02 … 06), one file";
  - `eras/niehs-2023`: "NIEHS Report, as published in March 2023 (NIEHS-07 … 10)";
  - `eras/niehs-2026`: "NIEHS Report, as published in 2026 (NIEHS-12, 13): the format for new studies".

  Agreed?
- **Q-M1-7. Should deleting a study also delete its deliverables in `output/<id>/`?**
  Proposed: keep them, and say so in the dialog.
- **Q-M1-8. How does a person start a report over several studies** (rat and mouse)?
  Out of M1 by Q7 (the system makes them), but no module creates one today.
- **Q-M1-9. `DTXSID50469320_nb` (the notebook's build) is on the Bookshelf** as an
  unpublished book in the 2026 format, and `DTXSID_TEST` is a test leftover. Both
  are in your store. Intended?
- **Q-M1-10. Should creating a study pin its document definition** (tracking), to
  record the format the person confirmed? Proposed: no; M5 pins.
- **Q-M1-11. Changing a study's identity after creation** (a re-lookup that gives a
  new name) would change every caption and, by Q2, stale AI text. Proposed: not in
  M1. M1 only fills a missing identity.
- **Q-M1-12. Data policy.** In test and prod, may the server look up an unpublished
  study's chemical in PubChem? It is a public identifier, not study data, but it
  says which chemical is under study.

## 12. Acceptance criteria

Tested in a headed browser against the app running on a **scratch copy** of the
store (`SESSIONS_DIR` set to the scratch directory). "The store as of 2026-10-14"
means a copy of the maintainer's 32 session folders.

**The list (S1)**
1. With the store as of 2026-10-14, `/app/studies` shows one top-level row for each
   of the 14 chemicals, and a last group "Sessions not tied to a chemical" holding
   `DTXSID_TEST`. The `_prompts` folder appears nowhere.
2. The list appears within 3 seconds.
3. For every session, the phase words shown in the list are the same as on that
   session's page (S3).
4. The 1,4-Dichlorobenzene row reads "Report over 2 studies" and "NIEHS-13 · 2026
   Apr". Expanded, it shows a rat study and a mouse study, each with its own "where
   it stands" and next step, and a "Published content" row. It does not say "No
   files yet" for the report itself.
5. Every "Published content" row and every report row shows no phase and no "No
   files yet".
6. The Perfluorohexanesulfonamide row, expanded, shows `DTXSID50469320_nb` as an
   "Other session". Its page warns that it uses the 2026 format and not NIEHS-10's.
7. The Bookshelf column for `DTXSID50469320` is a link labelled as a draft that
   opens `/Bookshelf/DTXSID50469320` in a new tab. A rat or mouse study's cell says
   it is part of the parent's book.
8. Searching "41997-13-1" leaves only the Perfluorohexanesulfonamide group.
   Searching "DTXSID1020431_rat" leaves the 1,4-Dichlorobenzene group, expanded,
   with the rat study visible. Clearing the search brings every row back.
9. No row in the list has a delete control.
10. With an empty store, the page says "No studies yet" and offers **New study**.
11. Each "Next:" link opens the module it names for that study.

**Creating (S2)**
12. Typing `dtxsid7020182` shows `DTXSID7020182` in the field as it is typed.
13. `DTXSID5046932O` shows a message naming the letter O and its position, and
    **Next** stays disabled.
14. `DTXSID50469320_v2` shows the message about suffixes, and **Next** stays disabled.
15. `7020182` shows "A DTXSID starts with 'DTXSID'…", and **Next** stays disabled.
16. Pasting `https://comptox.epa.gov/dashboard/chemical/details/DTXSID7020182` offers
    "Use DTXSID7020182?". Clicking it fills the field. The field is never filled
    without the click.
17. `DTXSID50469320` (which exists) shows "A study of this chemical already exists"
    with **Open it**, which opens its page. **Next** stays disabled. The list is
    unchanged afterwards.
18. `DTXSID7020182`, then **Next**, shows a "Looking up…" indicator. Then it shows
    Bisphenol A, CASRN 80-05-7, formula C15H16O2, a structure picture, the PubChem
    number as a link, and a line saying the lookup used PubChem.
19. For `DTXSID7020182`, the format notice is informational and says the study uses
    the format for new studies (2026) because no published report is on file.
20. In a scratch store **without** `DTXSID50469320`, entering it shows a warning-style
    format notice naming NIEHS-10 and the March 2023 format. It lists what the id
    also brings: the organ and endpoint selections, the deposit captions and data
    DOI, Appendix A. The checkbox label names that format.
21. **Create study** stays disabled until the confirm checkbox is ticked.
22. A well-formed DTXSID that PubChem doesn't know (for example `DTXSID0000000001`)
    shows the "PubChem has no chemical…" error with **Back to the id**. No name
    appears, "Test Article" appears nowhere, and no way to create is offered (while
    Q-M1-3 is open).
23. With the lookup service unreachable (the tester's mock, or a server without
    network), the page says the service could not be reached and that nothing was
    created, with **Try again**. The list is unchanged.
24. **Back** from step 2 returns to step 1 with the id kept. Reloading during step 2
    returns to step 1. In both cases the list is unchanged.
25. After **Create study**, the success page shows the id, name, CASRN and format,
    and a button for the next step, "Bring in the study's files". The list then has
    the new study, with "No files yet" and that next step. Its page says the identity
    was "Confirmed by a person from a PubChem lookup" with today's date.
26. With S2 at step 2 for the same id in two tabs, creating in the first and then in
    the second makes the second show "already exists" with **Open it**. Only one
    study exists.

**The study page (S3, S5)**
27. `/app/studies/DTXSID50469320` shows:
    - the identity;
    - the phase in words and the next-step button;
    - the format ("NIEHS Report, as published in March 2023", from this study's own
      definition), with its pin state and a link to the pins module;
    - the Bookshelf link;
    - related sessions (its published content and `DTXSID50469320_nb`).
28. A published-content page (`DTXSID50469320_published`) shows the read-only banner,
    links to the Bookshelf and to the generated study, and offers no data module and
    no delete.
29. `DTXSID1020431_rat`'s page names its report and its mouse sibling, with links. Its
    delete button is disabled, with the reason written beside it.
30. The report page `DTXSID1020431` lists its two member studies with their own state.
31. A study without a short name shows "[short name pending]" linking to Study facts.
32. `/app/studies/DTXSID7020182`, when absent, shows "There is no study…" and
    **Create a study of this chemical**. `/app/studies/foo` shows "not a study id".
    After either, the list is unchanged (no new entry appears).
33. A session without an identity (`DTXSID_TEST`) shows "[name pending]" and **Look up
    the chemical**. Confirming the lookup fills its name and CASRN. The button is not
    offered on a session that already has an identity.

**Deleting (S4)**
34. On a scratch copy of `DTXSID5032498`, **Delete this study…** opens a dialog
    listing:
    - what will be deleted (its files, the integrated data, the sections, the
      history, the stated facts…);
    - what stays (its deliverables in `output/`, the study definition under
      `templates/studies/` if any, other sessions of the chemical);
    - the approved sections that will be lost, by name.
35. **Delete for good** stays disabled while the typed text is `dtxsid5032498`,
    `DTXSID503249`, or anything other than `DTXSID5032498`. It becomes enabled for
    `DTXSID5032498` (with or without surrounding spaces).
36. **Cancel** closes the dialog, and the study is unchanged.
37. Confirming returns to the list with "DTXSID5032498 was deleted". The study is gone
    from the list and from `/Bookshelf`.
38. While Process runs on a study, its page shows the delete button disabled with
    "Process is running on this study since …".
39. With the dialog open, changing the study in another tab (for example bringing in
    a file) and then confirming shows "The study changed after you reviewed…". The
    lists reload, and nothing is deleted.
40. A second tab that had the deleted study open shows "This study was deleted" on its
    next read.

**Everywhere**
41. Every refusal shows plain words, and a "Details" toggle with the backend's own
    message. The word "wizard" appears on no M1 screen.
