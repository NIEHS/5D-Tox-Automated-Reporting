# M2 Study files: bring in, check, confirm, settle

Module M2 (`MODULES.md` §3). Written 2026-10-15 by the interaction designer from
`modules/gate0-data/analysis.md` §2 (steps 1–4, lifecycle L), findings 2, 3, 4,
12 and §3; the signed C1 and M1 specs; and the backend code. **Revised 2026-10-16
to the maintainer's answers** (§11, "Answered 2026-10-16"). It builds on the
shared kit and contracts of `MODULES.md` §4 and does not redefine them. The
endpoints and fixtures are in `contract.md`.

It is written **as M2 should work once C3, C4, C8 and C12 hold** and the core-track
items of §10 are done. Every behaviour that depends on one of them is marked
**[C3]**, **[C4]**, **[C8]**, **[C12]** or **[core]**, so it can be built against
the mocks now. §10 lists what M2 needs from each. C12 (the record of combined
datasets) is a new core item this revision proposes (§10).

Evidence marks: **[V]** verified by running it on scratch copies, in
`/workspace/ui-team/_scratch/design-m2/` (2026-10-15) or
`/workspace/ui-team/_scratch/m2-design/` (2026-10-16; the real `sessions/` was
never written); **[R]** read from the code.

Markers: **[maintainer]** needs a decision (§11); **[maintainer: confirm]** is a
reading of an answer that the maintainer should confirm; **[request]** is something
M2 needs from the orchestrator (§9).

---

## 1. The person's goal

> "I want to put this study's data files in, find out whether the tool understood
> each one, fix what is wrong, and know for sure that what gets combined is
> exactly my study's data: nothing missing, nothing twice, nothing from another
> study. And I want to be able to find out later which files a report was built
> from."

In detail:
- **Bring in files.** Choose files or a zip. Before anything changes, see:
  - what each file is taken to be;
  - which ones are refused, and why;
  - which ones replace a file already in the study;
  - what adding them does to work already done.
- **Check them.** Run the file check. See plainly what must be fixed, what is
  worth a look, and what is expected for this kind of package. This includes what a
  BMDExpress project fills in or leaves out, by rule.
- **Say what each file is.** Confirm or correct each file's platform and data
  type from a fixed list. A correction is never lost. Every file is confirmed
  before the files can be combined.
- **Settle conflicts.** Two kinds, each plainly labelled:
  - **choose here:** two files disagree (their doses, their animals). Compare them
    side by side and keep the right one;
  - **fix outside the app:** two files hold the same data (redundant files, or an
    exact copy under another name). Fix or remove them yourself, then check again.
- **Narrow a shared BMDExpress project** to this study's experiments.
- **Remove a file, or start the files over.** See what goes and what stays, and
  confirm. A removed file can be restored, even after starting over.
- **See the record.** Every file ever brought in, removed or replaced, and every
  dataset combined from them, can be found again.

## 2. When the module is reachable

Route: `/app/studies/:id/files` (the kit's `moduleRoute('M2', id)`, slug `files`).

Everything the screen shows about the workflow comes from the backend: the kit's
`useStudyState(id)` (§4.1) and M2's own read, `GET /api/v2/studies/{id}/files`
(contract §2.1). The browser computes nothing of its own: no phase, no permission,
no readiness, no classification, no conflict kind.

| Condition (served) | What M2 shows |
|---|---|
| `state.exists == false` | M1's S5 ("There is no study …"); M2 renders nothing of its own |
| `files.takes_files.allowed == false` (a companion, or a report over several studies; M1 R6) | an `Alert` (info) with `takes_files.say`, for example "This is the published book's own content. It takes no data files." and a link to the study it belongs to. No control of M2 is shown |
| `state.run.in_flight` (C5) | every act is disabled with "Process is running on this study since 10:42. Files can't change while it runs." The page stays readable |
| otherwise | the page (§3), with each act enabled or disabled from `files.acts.<act>` |

Which acts are allowed comes from C1's legal actions. The backend serves them per
act in `files.acts` (`{allowed, code, say}`), so no screen maps phases to buttons:

| Act on screen | Legal action (C1) | Allowed in |
|---|---|---|
| Bring in files | ADD_FILES | every phase |
| Check the files | VALIDATE | UPLOADED and later |
| Confirm or correct what a file is | CONFIRM_CLASSIFICATION | VALIDATION_ERRORS and later |
| Keep one file of a conflict settled here | RESOLVE | VALIDATION_ERRORS and later |
| Keep only this study's experiments (a shared `.bm2`) | RESOLVE | VALIDATION_ERRORS and later |
| Remove a file | REMOVE_FILE | UPLOADED and later |
| Restore a removed file | ADD_FILES | every phase (also after "Start over") |
| Start the files over | RESET | UPLOADED and later |
| Read the record | – | always |

A conflict settled outside the app has no act: the screen says what to do, and
the person does it with the acts above (remove, bring in a corrected file, check
again).

M2 ends where M3 begins. `files.next` points to M3, "Combine the files into one
dataset", only when all of these hold:
- the phase is VALIDATED or later;
- no conflict is open, of either kind;
- every file is confirmed.

The link is the only way M2 leads to integration: M2 has no Combine button.

---

## 3. Screens

One page with six parts, in a fixed order. Each part says why it is inactive
when it is.

### S0 Header and progress

- The kit's study header (identity, `<PhaseTag>`), from the shell.
- An antd `Steps` (horizontal; vertical below 768 px) built from `files.progress`
  (served):
  1. **Bring in files**: "15 files in the study";
  2. **Check**: "Checked 12 Oct 2026: nothing blocks", or "2 problems to fix";
  3. **Say what each file is**: "15 of 15 not yet confirmed";
  4. **Settle conflicts**: "No conflicts", or "Conflicts: 1 to choose here, 1 to
     fix outside the app".

  Each step's `status` maps to the `Steps` status: `done` → finish, `todo` →
  process, `blocked` → error, `waiting` and `not_needed` → wait. A step is a
  link that scrolls to its part. The `Steps` only show where things stand and
  are not a sequence the person clicks through: the backend decides what is
  allowed.
- Under it, the **next step** from `files.next`, as the primary button. For
  example, "Confirm what each file is" scrolls to S2; "Combine the files into one
  dataset" goes to M3. When the next step is to settle a conflict outside the app,
  `next.act` is null and the line is not a button but an `Alert` (warning) with
  `next.say`: "Settle the copy outside the app, then check the files again". It
  links to the conflict's card.
- **When the study was combined before.** `files.integration` (served, from C1's
  `artifacts.integration`):
  - `current`: an `Alert` (info): "These files were combined into one dataset on
    12 Oct 2026. Changing the files means combining them again, and processing
    again." Shown so that every act below is read in that light.
  - `out_of_date`: an `Alert` (warning): "The files have changed since they were
    combined on 12 Oct 2026. The dataset is kept but is not used until it is
    combined again." It links to M3.

### S1 Bring in files

A `Card` titled "Bring in files".

**The drop zone.** An antd `Upload.Dragger`:
- `multiple`, `directory` off;
- `beforeUpload` returns `false`, so nothing is sent on drop;
- `accept` is `.bm2,.csv,.txt,.xlsx,.zip,.json`.

Help text:
- "BMDExpress projects (.bm2), study tables (.csv, .txt), study workbooks (.xlsx),
  or a .zip of these. There is no size limit; a large file takes longer to send
  and to check.";
- "A one-row-per-animal .csv brings its units in a file of the same name ending
  in .units.json. Bring both together."

**Step A: checked in the browser, as soon as files are chosen** (§4, rules
1–7). The chosen files appear in a `Table` "About to bring in", one row per
file. Each row has its name, size and a verdict `Tag`:
- "Will be added";
- "Units file for …";
- "Refused" (red), with the reason;
- "Needs your answer" (orange).

A refused row can be dropped from the list. Nothing is sent while a row is
refused: **Send to the server for checking** stays disabled, with "Remove the
refused files from the list first."

**Step B: checked on the server, before the files join the study.** **Send to
the server for checking** uploads the batch to a staging area, not into the study
(`POST …/files/staging`, contract §2.2) **[C8]**.
- The upload shows a `Progress` per file (bytes sent of the file's size). It is a
  foreground wait: the page warns on leaving (`beforeunload`), and the button is
  replaced by **Cancel upload**. There is no size limit, so a 251 MB project
  simply takes longer.
- The server answers with the **intake plan**, shown in place of the table:
  - one row per file, with what the server found:
    - its real type, from the content;
    - the zip's contents: each entry a row, with the folder it came from;
    - the pairing of each `.units.json` with its table;
    - a same-name match with a file already in the study;
    - an identical copy, under another name, of a file in the study or in the
      batch;
  - for every row, `verdict` and `say`:

| Verdict | Row shows | The person must |
|---|---|---|
| `add` | "Will be added." | – |
| `units` | "Units for body_weight_truth_female.csv (1 measurement: grams)." | – |
| `replace` | "Replaces body_weight_truth_female.csv already in the study (added 12 Oct 2026, 6,387 bytes; this one 6,387 bytes, different content). The old one will be kept among the removed files, where it can be restored." | tick **Replace it** in the row; otherwise the row is not added |
| `unchanged` | "Already in the study, unchanged (same name, same content). Not brought in again." | nothing; the row is not added and is not counted |
| `copy` | "This is an exact copy of body_weight_truth_female.csv, already in the study, under another name. Both would be combined, so the data would count twice. If you bring it in, the check will block combining until you settle it outside the app." | either drop the row (back to Step A), or tick **Bring it in anyway** |
| `units_missing` | "This one-row-per-animal table came without a units file. Its tables will show [units pending] for every measurement." | either add the `.units.json` to the batch (back to Step A), or tick **Bring it in without units** |
| `refused` | the reason (§6) | nothing; the row is not added |
| `left_out` (zip entries that aren't data) | "Left out: not a data file (C20022-01_Hormone_Summary.docx)." | nothing |

  - **What adding them does.** Shown only when the study has been checked or
    combined. The plan carries the backend's dry run, the §4.3 object **[C8]**.
    It appears inside the plan as the kit's consequences list:
    - "It will delete: the result of the last file check; the combined dataset (a
      copy is kept in the dataset record); the data review; the stored results of
      processing (11 files) …";
    - "Approvals that will be lost";
    - "It will keep …";
    - `cost.say`: "checking the files again, combining them again (about 25 s),
      and processing again (about 3 minutes)".
- **Buttons:**
  - **Bring in N files** (primary). N counts the rows that will be added; it does
    not count `unchanged`, `refused` or `left_out` rows. The button is disabled
    while any `replace`, `copy` or `units_missing` row is unanswered, with "Answer
    the rows marked 'Needs your answer' first." When the plan's dry run is costly,
    it first opens the kit's `<ConfirmAct strength="costly">` with that list. It
    sends `POST …/staging/{batch}/commit` with the plan's `plan_token` and the
    answers.
  - **Discard** throws the staged batch away (`DELETE …/staging/{batch}`). Nothing
    in the study changed.
- **After the commit:** a `message`, for example "12 files brought in; 1 replaced
  (the old one is among the removed files). Check the files next." The page re-reads
  the files view and the state, and **Check the files** becomes the next step.

A staged batch is never committed by itself. It expires after 1 hour; a stale plan
refuses with `staging_expired`.

### S2 The files

A `Card` titled "The study's files". It holds an antd `Table`, one row per
**file the person brought in**. A one-row-per-animal CSV is one row: the table
and sidecar the check makes from it are its companions, shown in the expanded
row, never as rows of their own **[C4]**.

| Column | Content |
|---|---|
| File | the name (monospace), the kind as a `Tag` ("Workbook", "Table", "BMDExpress project"), the size |
| What it is | `classification.say` ("Body Weight · the study's own measurements"). Below it, a status `Tag`: "Detected, not confirmed" (orange), "Confirmed by you" (green), "Changed by you" (blue; detected value in a tooltip), "Not checked yet" (grey), "Not recognised" (red), "File changed since you confirmed it" (orange) **[C3]**. A `classification.flags[]` entry shows as a warning icon with its `say`. The **Change…** link opens S2-M |
| Contents | from `tables[]`: sex ("Female"), number of doses, animals ("55 animals, 10 doses"). A `.bm2` shows its experiment count and species. Each missing fact is a `<Pending>`: "[sex pending]", "[contents not read: …]". A `.bm2` whose apical data fills values or leaves out dose groups (`bm2_changes`, §8) shows an info `Tag`: "Fills 1 missing value" / "2 dose groups left out" **[core]** |
| Units | `units.say`; `<Pending>` "[units pending]" when `units.state` is `missing` or `not_read`; nothing for a `.bm2` or gene-expression data |
| Problems | a `Badge` per group from the issues that name the file (must fix, worth a look); a click scrolls to the issue in S3 |
| (acts) | **Remove…** (S4), disabled with `acts.remove.say` when not allowed. On a `.bm2` holding several test articles, **Keep only this study's experiments…** (S2-N) |

**The expanded row** (`expandable`), in `Descriptions`:
- what the file was made into (companions, with each one's `say`);
- the full contents per table:
  - doses, with the animals per dose;
  - sexes;
  - measurements (the first five, then "and 12 more");
  - selection groups (core, biosampling);
  - study number, species;
- a `.bm2`'s experiment names;
- **what a BMDExpress project fills in or leaves out** (`bm2_changes`), as an
  `Alert` (info), with its exact `say`. For example:
  - "This BMDExpress project fills 1 value that hormones_truth_male.csv leaves
    missing (males, dose group 12: 1 value). BMDExpress needs complete data, so a
    missing value is filled with its dose group's mean. This is expected.";
  - "The report footnotes it: 'Benchmark dose modeling used an inferred dataset in
    which 1 missing individual value was replaced with the dose-group mean (affected
    dose group: 12 mg/kg).'";

  or, where the report does not yet footnote it (§8), "The report does not footnote
  this yet for Body Weight." **[core] [maintainer: confirm]**;
- **why the tool thinks so**: `classification.detected.say`, for example "From its
  content: one row per animal, with Animal ID and Sex columns", "From the file
  name", or "From the experiment names inside the BMDExpress project";
- the person's statement, when there is one, with its time **[C3]**.

**Bulk confirm.** Above the table: **Confirm the N files as shown…** It opens a
`Modal` listing every file it will confirm, with its classification. Left out of
the list, and named under it with their reason, are the files that:
- are not recognised;
- carry a flag (`several_test_articles`);
- were changed since they were confirmed.

The person confirms those one by one in S2-M. The `Modal`'s button reads
"Confirm these N" and sends the list with the view's `files_token`; it refuses
with `files_changed` if the view changed meanwhile. Every file must be confirmed
before the files can be combined (Q-M2-4): `files.next` does not point to M3 while
one is not, and integration refuses `classification_unconfirmed` **[C1/C3]**.

**Empty study:** `Empty` "No files yet. Bring in the study's data files above."
When there are removed files (for example after "Start over"), it adds: "Files you
removed are kept below and can be restored."

#### S2-M "What is this file?" (Modal)

Opened from **Change…** or from a "Not recognised" row.
- The file's name and kind, and its contents summary (as the expanded row).
- A `Form` with two fields. The choices are served per kind of file
  (`classification_choices[kind]`, contract §2.1); the screen never offers a
  value the backend did not list:
  1. **Data type**: a `Radio.Group` of the served choices, each with its `label`
     and `say`. For a table, for example:
     - "The study's own measurements": "Each animal's values as measured, gaps
       included. The NTP statistics are computed from these.";
     - "Gap-filled for BMD modelling": "Values prepared for BMDExpress: gaps
       filled, dose groups with no survivors dropped. Used for benchmark doses,
       never for the NTP statistics.";
     - "Gene expression".

     A workbook offers only the first, a `.bm2` only the last two.
  2. **Platform**: the kit's `<VocabField vocab="platform">`, restricted to the
     platforms served for the chosen data type **[request R-M2-6]**. The field is
     hidden for gene expression, which has no apical platform; its value is then
     "none", by rule, not by default.
- Under the fields: "The tool detected: Body Weight · the study's own
  measurements, from its content." and a link **Use what the tool detected** (it
  fills the fields; nothing is sent).
- **Save** sends `PUT …/files/{name}/classification` **[C3]**. When the backend's
  dry run for that change is costly (the study was combined),
  `<ConfirmAct strength="costly">` shows its consequences first: "The combined
  dataset was built with this file as Hematology. After this change it must be
  combined again, and Process run again."
- After saving: a `message` "Saved. Check the files again so the check uses it."
  The progress step "Check" then shows "Out of date: a file's classification
  changed" (`check.current == false`, `check.why_not_current`) **[C3]**.
- **Undo** (the kit's reversible pattern): puts back the previous statement, or
  the detected value.

#### S2-N "Keep only this study's experiments" (Modal) [core]

Opened from the row of a `.bm2` that holds experiments of several test articles
(the must-fix issue `several_test_articles`, §5; Q-M2-5).
- The question: "This BMDExpress project holds experiments of 4 test articles, read
  from its experiment names. Which one is this study's?"
- A `Radio.Group`, one option per test article from `narrow_choices` (served), each
  listing its experiments ("PFHxSAm: Kidney_PFHxSAm_Female, Kidney_PFHxSAm_Male,
  Liver_PFHxSAm_Female, Liver_PFHxSAm_Male"). Nothing is preselected. When one
  matches the study's short name (M1/M4), a `Tag` "Matches this study's short name"
  is shown on it; it is still not preselected.
- **Keep only these…** stays disabled until one is chosen. It opens `<ConfirmAct>`
  with the dry run (`GET …/dry-run/narrow?file=…&test_article=…`) **[C8]**:
  - "It will replace C20022-01_…Traditional.bm2 (40.5 MB, 16 experiments) with a
    copy holding only PFHxSAm's 4 experiments and their analyses.";
  - "The original is kept among the removed files, where it can be restored.";
  - the cost ("checking the files again").
- It sends `POST …/files/{name}/narrow`. It is a foreground wait, about 1.5 s for
  the 40 MB project [V]. After it, the row shows the new size (8.2 MB [V]), and the
  original is among the removed files with "Narrowed to PFHxSAm". The next step is
  "Check the files".
- A project whose experiment names don't follow `<Organ>_<article>_<Sex>` gives no
  test articles, so no choice is offered and the issue is not raised. The row then
  shows `<Pending>` "[test articles not read from the experiment names]".

### S3 The check

A `Card` titled "The file check".

**Header line:** "Checked 12 Oct 2026, 11:37". When `check.current == false`, an
`Alert` (warning) says `check.why_not_current` ("2 files were brought in since",
"A file's classification changed since") **[C3]**. Never checked: "Not checked
yet."

**Check the files** (primary when it is `files.next`, else default) sends
`POST …/check`.
- It is a foreground wait: a `Modal` (not closable) with a `Spin`, the elapsed
  time and "Checking 15 files. A large BMDExpress project can take half a minute
  the first time."
  - The check took 0.2 s with its cache warm and 7.9 s cold with a 40 MB `.bm2`
    [V].
  - Reading the 251 MB project of NIEHS-12/13 took 29.6 s cold [V].
- When done, the view re-reads and the `Modal` closes.
- At INTEGRATED or APPROVED, the button's tooltip says "Checking again never
  deletes the combined dataset" (C1 D4).

**The result**, when there is one:
- **A summary `Alert`:**
  - error: "2 problems must be fixed before the files can be combined.";
  - success: "Nothing blocks. 7 points are worth a look; 25 are expected for this
    kind of package."
- **The issues**, in an antd `Collapse` with three panels, from `issue.group`
  (served; §5 lists the rule per issue type):
  1. **Must fix** (open, red header, count) and 2. **Worth a look** (open, count).
     Each issue is a `List.Item`:
     - `say` in plain words, file names as links to their rows (never ids);
     - `what_to_do` in bold;
     - for an issue that feeds the data review (`feeds: "M6"`), the line "The data
       review accounts for these animals.";
     - a "Details" toggle with the backend's `message` and `details` (the kit's
       `<Refusal>` toggle style).
  3. **Expected for this kind of package** (collapsed, count). The same items. For
     example:
     - "No study workbook (.xlsx) for Hematology. Its tables are used as they
       are.";
     - "Hormones.bm2 fills 1 value that hormones_truth_male.csv leaves missing …
       The report footnotes it." (the same text as the row's `bm2_changes`).
- **Not shown here:** when `check.not_shown` is present, one line: "8 checks of
  the analysis method are shown with the method, in Method and report
  definition", as a link to M5.
- **"What the report will be built from"**: a `Table` from `coverage[]` (served),
  one row per platform and data type:
  - columns: platform, data type (with `data_type_say`), workbook, tables, `.bm2`,
    and status (`level` as a `Tag`: ok, warn, block) with `say`;
  - file names link to their rows.

  A `.bm2` is not required for an apical platform (Q-M2-3): the row of a platform
  with study data and no `.bm2` is "ok", "Process computes its benchmark doses."
  The message "Requires .bm2 for BMD/BMDL values" never appears **[core]**.

### S3-C Conflicts

Inside S3, above the issues, when `conflicts[]` is not empty: a `Card` per
conflict. **The two kinds look different, and the kind comes from the backend
(`conflict.settle`), never from the screen.**

**Kind 1: "Choose here"** (`settle: "here"`: `dose_mismatch`, and
`animal_count_mismatch` at error severity). Q-M2-1.
- The card's title has a blue `Tag` **Choose here**: "Conflict: Hormones,
  females".
- **The question:** `say`, for example "hormones_truth_female.csv and
  hormones_truth_female_rerun.csv are both Hormones data for females, but their
  doses differ: hormones_truth_female.csv has 1.4 where
  hormones_truth_female_rerun.csv has 2. One of them is wrong, or belongs to
  another study."
- **Side by side:** a `Table` with one column per file and one row per property:
  - kind, data type, sexes, doses, animals per dose, animals, measurements, when
    added, size;
  - the rows in `differences[]` are highlighted (bold, warning background); the
    others are dimmed.
- **The check's suggestion**, when `suggested` is present: a `Tag` "The check
  suggests" on that column, with `suggested.why` in a tooltip ("… It does not know
  which is right."). It is never preselected.
- **The choice:** a `Radio.Group` "Keep:" with one option per file and no default.
  **Keep this file** stays disabled until one is chosen.
- **What keeping does:**
  - The other file is set aside: moved to the removed files, restorable (S4), with
    the reason recorded.
  - The button opens `<ConfirmAct>` with the backend's dry run: "It will set
    aside: hormones_truth_female_rerun.csv (and its units file and tables). It
    stays among the removed files and can be restored. Check the files again
    afterwards."
  - It sends `POST …/conflicts/{id}/keep` **[C8]**.
- **After it:** the conflict leaves the list (the check is now out of date, which
  is derived), and the next step is "Check the files". A decision is undone by
  restoring the set-aside file, which brings the conflict back at the next check.

**Kind 2: "Fix outside the app"** (`settle: "outside"`: `redundant_files` and
`same_content`). Q-M2-2, Q-M2-9.
- An `Alert` of type error, not a choice card. Its title has a red `Tag` **Fix
  outside the app**: "Two files hold the same Body Weight data".
- **The question:** `say`. For example:
  - "body_weight_truth_female_copy.txt and body_weight_truth_female.csv hold the
    same data (same platform, sex, doses, measurements and animals). Both would be
    combined, so it would count twice."; or
  - "body_weight_truth_female_2.csv is an exact copy of
    body_weight_truth_female.csv (same content)."
- **The files**, side by side as in Kind 1 (name, kind, size, when added, content
  hash), for information. The file names link to their rows.
- **What to do**, as a numbered `Steps` (vertical, all "wait"; not clickable), from
  `outside.steps` (served):
  1. "Open both files on your computer and decide which one is this study's, or
     correct them."
  2. "Here, remove the one that does not belong (its row's Remove…), or bring in
     the corrected file under the same name: it replaces the old one, which is kept
     among the removed files."
  3. "Check the files again."
- **No choice control and no keep button.** The line "The app does not choose
  between these files: only you can tell which one is the study's." says why.
- The conflict clears only at a check that no longer finds it.

The progress step 4 counts the two kinds separately ("1 to choose here, 1 to fix
outside the app").

### S4 Remove, restore, start over

**Remove a file** (the row's **Remove…**). Always through `<ConfirmAct>` with the
backend's dry run (`GET …/dry-run/remove_file?file=…`) **[C8]**:
- *Study not checked yet:* strength `reversible`. The file is removed at once, and
  a `message` with **Undo** follows ("body_weight_truth_female.csv removed.
  Undo").
- *Study checked or combined:* strength `costly`. The dialog lists what goes:
  - "the file and its companions (its units file, the table made from it, its
    sidecar), to the removed files";
  - "the result of the last file check";
  - "the combined dataset (a copy is kept in the dataset record), the data review,
    the stored results of processing" (when present) **[C12]**;
  - the approvals lost;
  - what is kept;
  - the cost.

  **Remove** sends `POST …/files/{name}/remove` with the `preview_token`.

**Removed files.** A `Collapse` panel under the table, titled with the count and
total size from `removed[]` and `removed_size` (served), for example "Removed
files (3, 6.4 kB)" **[C8]**:
- Each entry has its files, when, and why it was removed:
  - "Removed by you";
  - "Set aside when you kept hormones_truth_female.csv";
  - "Replaced by a newer body_weight_truth_female.csv";
  - "Narrowed to PFHxSAm";
  - "Removed when the files were started over".
- **Restore…** goes through `<ConfirmAct>` with the restore's dry run. Adding a
  file back changes the files, so it costs the same as bringing it in.
- **Restore…** is disabled, with the reason, when a file of that name is in the
  study now: "A file named body_weight_truth_female.csv is in the study now. Remove
  it first."
- Removed files are never deleted by M2, not even by "Start over" (Q-M2-11). Only
  deleting the whole study (M1) deletes them.

**Start the files over.** A `Card` at the bottom with a red border, "Start the
files over": "Takes every data file out of the study and deletes everything made
from them. The files go to the removed files and can be restored. What people
stated (the design, the authors, the pins), the Background, the removed files and
the records are kept."
- **Start over…** (danger) opens `<ConfirmAct strength="irreversible">` with the
  reset's dry run (`GET …/dry-run/reset_files`) **[C8]**:
  - what will be deleted: the combined dataset (a copy is kept in the dataset
    record), the file check, the data review, the result sections, the Summary,
    the stored processing results;
  - what moves: "the 15 files, to the removed files (restorable)"
    **[maintainer]** (Q-M2-12);
  - the approvals lost;
  - what is kept, with the lines:
    - "These stay and will apply again to the next files you bring in: the study
      design, the experiment details, the method and the report definition.";
    - "The removed files (3, 6.4 kB), the record of the files, and the record of
      the combined datasets are kept."
- The person types the study id, as in M1.
- It sends `POST …/files/reset` with the typed id and the `preview_token`.
- Deleting the whole study is not here; it is M1's.

### S5 The record

A `Collapse` panel at the bottom, "Record of the files (27 entries)" **[C8]**. It is
read-only: nothing in it can be edited or deleted.
- An antd `Table` from `GET …/files/record` (paged, newest first), one row per
  event. Columns:
  - When;
  - What: a `Tag`: brought in, replaced, removed, set aside, narrowed, restored,
    started over;
  - File;
  - Size;
  - Content: the first 12 characters of the hash, with a copy button for the
    whole;
  - Why: for example "Replaced by a newer file of the same name", "Set aside when
    you kept hormones_truth_female.csv".
- A filter by file name (`Input.Search`, client-side over the loaded page) and by
  what.
- Under it, one line from `records.datasets` (served) **[C12]**: "3 datasets were
  combined from these files; the current one on 12 Oct 2026. See the record of the
  combined datasets." The link goes to M3, which shows that record. M2 does not
  show it.

---

## 4. Inputs and their validation (before anything runs)

**In the browser, as files are chosen (Step A).** The rules come from the served
`files.limits` (the accepted endings) and the files view (names already in the
study). Nothing is sent until every row passes or is dropped. Rules in the order
checked; the first failing one is shown. **There is no size limit (Q-M2-8).**

| # | Rule | Message |
|---|---|---|
| 1 | Not empty (size > 0) | "This file is empty." |
| 2 | The name is a plain name: no leading `.`, no `/` or `\`, no control characters, at most 200 characters | "This file name can't be used: it starts with a dot." |
| 3 | Ending is `.bm2`, `.csv`, `.txt`, `.xlsx`, `.zip`, or `.units.json` (case-insensitive) | "A .pdf is not a data file. The study's data comes as .bm2, .csv, .txt, .xlsx, or a .zip of these." `.docx`, `.pdf` and every other `.json` are refused this way |
| 4 | Not `*.sidecar.json` | "This is a file the application writes itself (a sidecar). Bring in the table it belongs to instead." |
| 5 | No two chosen files share a name | "Two of the chosen files are named body_weight_truth_male.csv. Keep one." |
| 6 | A `.units.json` has a table of the same stem among the chosen files, or an unchecked one in the study | "This units file has no table: there is no body_weight_truth_female.csv. Bring them in together." |
| 7 | A name already in the study | not refused; marked "Needs your answer: replaces a file already in the study" (answered in the plan) |

**On the server, before the files join the study (Step B; contract §2.2).** These
rules need the content; each failure is a `refused` row with its `say`, and each
finding a row verdict:

| Rule | Code / verdict | `say` |
|---|---|---|
| The content matches the ending. A `.bm2` begins with BMDExpress's saved-project signature (`AC ED 00 05`); an `.xlsx` or `.zip` is a zip archive; a `.csv`/`.txt` is text [V: real files' first bytes] | `content_mismatch` | "hormones_male_table.bm2 is named .bm2 but is a text table, not a BMDExpress project. Rename it to .txt if it is a table." |
| A `.zip` opens, has no zip inside it, and no two entries share a name in different folders | `zip_invalid`, `zip_nested`, `zip_name_clash` | "The zip holds two files named body_weight_truth_male.csv (in a/ and b/). Only one could be kept, and the tool can't know which. Neither is brought in; unzip it and choose." |
| Same name and same content as a file in the study | verdict `unchanged` | "Already in the study, unchanged …" (not added; not a refusal) |
| Same content as a file in the study or the batch, under another name | verdict `copy` | as §3 S1. Not refused (Q-M2-9): the person answers, and the check flags it |
| Same name, different content | verdict `replace` | as §3 S1. The person ticks **Replace it** (Q-M2-10) |
| A `.units.json` is a JSON object of text to text, and its keys are columns of its table | `units_invalid` | "The units file isn't a list of measurement → unit." / "It names 'Albumen', which is not a column of clin_chem_truth_female.csv." (columns of the table without a unit are listed as a warning in the row) |
| A `.units.json` for a table already converted by a check | `units_for_converted_file` | "body_weight_truth_female.csv has already been checked without units. Bring the .csv in again together with its units file; it will replace the old one." |
| Staging and commit match: the batch exists, its plan is unchanged, and the study is unchanged since | `staging_expired`, `changed_since_preview` | §6 |

**Classification (S2-M):** platform and data type are only ever chosen from the
served lists. The backend checks them again against `bmdx_pipe.VOCABULARIES` and
the allowed pairs (`classification_not_allowed`, §6) **[C3]**.

**Narrowing (S2-N):** the test article is one of the served `narrow_choices`;
nothing is chosen by default.

**Typed id for "Start over":** equal to the study id, case-sensitive, spaces at
either end ignored (as M1).

**Conflict choice (Kind 1 only):** one of the conflict's own files; nothing is
chosen by default.

---

## 5. Actions and what they map to

| Act | Legal action (C1) | Endpoint (contract) | Core | When not allowed, the person sees |
|---|---|---|---|---|
| Read the page | – | `GET …/files` | NEW `workflow.files.files_view` | – |
| Stage a batch | ADD_FILES | `POST …/files/staging` | NEW `pipeline.intake.stage_batch` | the act's `say` |
| Bring in the batch | ADD_FILES | `POST …/files/staging/{batch}/commit` | NEW `workflow.steps.add_files_step` | the act's `say`; refusals §6 |
| Discard a batch | – | `DELETE …/files/staging/{batch}` | `pipeline.intake.discard_batch` | – |
| Check the files | VALIDATE | `POST …/check` | `workflow.steps.validate_step` (CHANGED, §10) | "Bring in the study's files first." |
| Say what a file is | CONFIRM_CLASSIFICATION | `PUT …/files/{name}/classification` | CHANGED `confirm_metadata_step` **[C3]** | "Run the file check first: it says what each file is." |
| Confirm several as shown | CONFIRM_CLASSIFICATION | `POST …/files/classification/confirm` | same | same |
| Back to the detected value | CONFIRM_CLASSIFICATION | `DELETE …/files/{name}/classification` | same | same |
| Keep one file of a conflict settled here | RESOLVE | `GET …/dry-run/keep`, `POST …/conflicts/{id}/keep` | NEW `workflow.steps.keep_file_step` **[C8]** | "Run the file check first: conflicts are found by the check." |
| Keep only this study's experiments | RESOLVE | `GET …/dry-run/narrow`, `POST …/files/{name}/narrow` | NEW `workflow.steps.narrow_bm2_step` over `bmdx_pipe.pool_integrator.subset_bm2` **[core, C8]** | same |
| Remove a file | REMOVE_FILE | `GET …/dry-run/remove_file`, `POST …/files/{name}/remove` | CHANGED `pipeline.pool_state.remove_pool_file` **[C8]** | "This study has no files to remove." |
| Restore a removed file | ADD_FILES | `GET …/dry-run/restore_file`, `POST …/removed/{rid}/restore` | NEW `workflow.steps.restore_file_step` **[C8]** | the name-taken reason |
| Start the files over | RESET | `GET …/dry-run/reset_files`, `POST …/files/reset` | NEW `workflow.steps.reset_files_step` (logic moved from `web_routes/session_routes.py:1340-1491`, changed to keep `_removed/`) **[C8]** | "This study has no files to remove." |
| Read the record of the files | – | `GET …/files/record` | NEW `workflow.records.files_record` **[C8]** | – |

Every act's button reads `files.acts.<act>`, never the phase. A refusal from the
backend still comes back as the §4.2 envelope and is shown with `<Refusal>`.

**Issue groups** (served as `issue.group`; the rule lives in the backend, next to
the plain words):

| Issue type (severity) | Group | Plain words (served `say`), example from real reports |
|---|---|---|
| `unassigned_file` (error) | must fix | "The tool can't tell what lab_notes.txt is, from its name or its content." To do: "Say what it is … or remove it if it isn't study data." |
| `dose_mismatch` (error) | must fix; conflict **settled here** | as S3-C Kind 1 |
| `animal_count_mismatch` (error) | must fix; conflict **settled here** | "Hematology: the tables have 95 animals but the workbook only 90: 5 animals are not in the study workbook." |
| `redundant_files` (info today → **error**) | must fix; conflict **settled outside the app** **[core]** | "body_weight_truth_female_copy.txt and body_weight_truth_female.csv hold the same data … Both would be combined, so it would count twice." [V] |
| `same_content` (NEW, error) | must fix; conflict **settled outside the app** **[core]** | "body_weight_truth_female_2.csv is an exact copy of body_weight_truth_female.csv (same content). Both would be combined, so the data would count twice." [V: today an exact copy with a recognisable name is `redundant_files`, info, and the phase reads VALIDATED; with an unrecognisable name it is `unassigned_file`] |
| `several_test_articles` (NEW, error) | must fix; settled here by narrowing (S2-N) **[core]** | "This BMDExpress project holds experiments of 4 test articles (10-2 FTOH, 2,3-Benzofluorene, 6-1 FTOH, PFHxSAm), read from its experiment names. Combined as it is, all of them would enter this study's dataset." [V: integrating NIEHS-10's CEBS project combined all 16 experiments] |
| `value_*` (error) | must fix | "Body Weight: 1 of 243 values in the tables differ from the study workbook (for example animal 111, SD0, Body Weight: workbook 215.9, table 251.9). A table must be an exact copy of the workbook's data." [V] |
| `bm2_value_mismatch` (NEW, error) | must fix **[core] [maintainer: confirm]** | "Hormones.bm2 and hormones_truth_male.csv disagree on 2 values both have (for example animal 161, Free Thyroxine: project 7.3, table 7.23)." Only values present in both; never a value the table leaves missing (§8) |
| `unverified_derived_data` (warning) | worth a look | "Body Weight: there is no study workbook (.xlsx) to check the tables' values against, so they are used as given, unverified." |
| `sex_mismatch` (warning) | worth a look | the files' sexes, plainly |
| `animal_count_mismatch` (warning) | worth a look; feeds M6 | "Body Weight: the workbook has 122 animals and the tables 110, so 12 … are not in the tables. The data review accounts for each one." [V] |
| `missing_tier` "no txt/csv" (warning; workbook only) | worth a look | as served; the coverage row warns too (§8) |
| `roster_subset` (info) | expected; feeds M6 | "6 of the 61 female animals in the study's roster are not in body_weight_truth_female.csv, for example 544, 545 …" [V] |
| `missing_tier` "no .bm2" / "no xlsx" / gene expression | expected | "No BMDExpress project (.bm2) for Body Weight. Process computes its benchmark doses itself." |
| `bm2_fills_missing` (NEW, info) | expected **[core] [maintainer: confirm]** | "Hormones.bm2 fills 1 value that hormones_truth_male.csv leaves missing (males, dose group 12: 1 value) … The report footnotes it." [V on T7] |
| `bm2_dose_groups_left_out` (NEW, info) | expected **[core] [maintainer: confirm]** | "Body weight.bm2 holds no values for dose groups 333 and 1000, which body_weight_truth_female.csv has. BMDExpress is given only the dose groups it can model. This is expected." [V: the 2026 package] |
| `method_mismatch` | not in M2 | counted in `check.not_shown`, linked to M5 |

An issue type the backend adds later and does not know how to say is served with
its `message` as `say` and the group "worth a look", never dropped.

---

## 6. Refusals, in plain words

The §4.2 envelope's codes M2 meets. The `say` is written once, in the backend
(`workflow/refusals.py`). **[request R-M2-5]** adds the new ones. `fix` is M2
unless stated.

| code | status | `say` |
|---|---|---|
| `phase_not_allowed` (C1) | 409 | C1's text per state, for example "Checking the files isn't possible yet. This study has no data files yet. Add the study's files first." |
| `validation_out_of_date` (C1, raised by integrate) | 409 | C1's text; it links back here |
| `run_in_flight` (M1/C5) | 409 | "Process is running on this study (since {time}). Files can't change while it runs." (P1) |
| `read_only_session` (M1) | 409 | "This is the published book's own content. It takes no data files." (M1) |
| `takes_no_files` (NEW, R6) | 409 | "A report over several studies takes no files: its studies do. Bring the files into the rat or mouse study." (M1) |
| `study_not_found` (M1) | 404 | M1's text |
| `file_type_refused` | 400 | "{name}: a {ending} is not a data file. The study's data comes as .bm2, .csv, .txt, .xlsx, or a .zip of these." |
| `sidecar_refused` | 400 | "{name} is a file the application writes itself. Bring in the table it belongs to instead." |
| `empty_file` | 400 | "{name} is empty." |
| `name_invalid` | 400 | "This file name can't be used: {why}." (today: "Not a pool file name: …") |
| `duplicate_name_in_batch` | 400 | "Two files in this batch are named {name}. Keep one." |
| `content_mismatch` | 400 | as §4 |
| `zip_invalid` | 400 | "This .zip can't be opened; it may be damaged or only partly downloaded." (today: "The uploaded file is not a valid .zip archive") |
| `zip_nested` | 400 | "This .zip holds another .zip. Unzip the inner one and bring its files in." |
| `zip_name_clash` | 400 | as §4 |
| `units_without_table` | 400 | "This units file has no table: there is no {stem}.csv. Bring them in together." |
| `units_invalid` | 400 | as §4 |
| `units_for_converted_file` | 409 | as §4 |
| `answer_required` | 400 | "Answer the rows marked 'Needs your answer' first: {names}." |
| `staging_expired` | 410 | "These files were waiting too long and were dropped. Nothing was brought in. Choose them again." |
| `changed_since_preview` (M1) | 409 | "The study's files changed after you reviewed this. Nothing was done; review it again." |
| `files_changed` | 409 | "The files changed while this list was open. Nothing was confirmed; look at the list again." |
| `file_not_found` | 404 | "There is no file {name} in this study. It may have been removed in another tab." (today: "No file '{name}' in the pool for {id}") |
| `companion_not_removable` | 400 | "{name} belongs to {table}. Remove {table} instead." (today: "… is companion metadata for a data file …") |
| `removed_not_found` | 404 | "That removed file is no longer kept." |
| `restore_name_taken` | 409 | "A file named {name} is in the study now. Remove it first, then restore." |
| `not_validated` (existing) | 400 | "The study's files haven't been checked yet. Run the file check first, then try again." |
| `classification_not_allowed` | 400 | "{value} is not a {field} the tool knows." / "A BMDExpress project can't be 'the study's own measurements'." |
| `classification_unconfirmed` (NEW; raised by integrate, Q-M2-4) | 409 | "{n} files haven't been confirmed: {names}. Say what each one is first." (M2) |
| `conflict_not_found` | 404 | "This conflict is no longer there: the files changed. Check the files again." |
| `conflict_choice_invalid` | 400 | "Choose one of the two files of this conflict." (today: "dtxsid, issue_index, and chosen_file_id are required") |
| `conflict_settled_outside` (NEW) | 409 | "The app does not choose between these files: they hold the same data, and only you can tell which one is the study's. Fix or remove one outside the app, then check the files again." |
| `narrow_choice_invalid` (NEW) | 400 | "Choose one of the test articles found in this project." |
| `narrow_not_needed` (NEW) | 409 | "This BMDExpress project holds only one test article's experiments. There is nothing to narrow." |
| `server_setup_failed` (kit) | 500 | for a narrowing or a check whose Java helper failed; the kit's text |
| `no_files` (existing) | 404 | existing text |
| `damaged_session_file` (existing) | 422 | existing text (none) |

`file_too_large` and `same_content` are no longer refusals (Q-M2-8, Q-M2-9).

## 7. Destructive and costly acts

| Act | Strength (from the dry run) | Confirm | Undo |
|---|---|---|---|
| Bring in files, study never checked | – | the plan (§3 S1) | remove the file (reversible, to the removed files) |
| Bring in files, study checked or combined | costly | the plan, then `<ConfirmAct>` listing what goes (NIEHS-10's real list: contract §4.6) | none for what was deleted (a processed dataset is kept as a copy, C12); the files can be removed again |
| Replace a same-name file | part of the plan | **Replace it** ticked per row, before anything is written (Q-M2-10) | the old file is among the removed files, restorable **[C8]** |
| Bring in an exact copy under another name | part of the plan | **Bring it in anyway** ticked per row | remove it |
| Remove a file, never checked | reversible | none | **Undo** in the message (= restore) |
| Remove a file, checked or combined | costly | `<ConfirmAct>` | restore (itself costly) |
| Restore a removed file | as bringing it in | `<ConfirmAct>` | remove again |
| Keep one file of a conflict settled here | costly or reversible, as remove | `<ConfirmAct>` | restore the set-aside file |
| Keep only this study's experiments | costly or reversible, as remove | `<ConfirmAct>` | restore the original (it replaces the narrowed copy only after the narrowed one is removed) |
| Confirm or correct a classification | reversible; costly once combined | in S2-M | **Undo** (previous statement) |
| Check the files | none | – | – (never deletes the dataset, C1 D4) |
| Start the files over | irreversible (the work done from the files) | `<ConfirmAct>`, type the id | the files themselves can be restored from the removed files **[maintainer]** Q-M2-12; the processed dataset is kept as a copy (C12) |

Every consequence list comes from the backend's dry run; the front-end keeps no
list of its own **[C8]**. Every act carries the dry run's `preview_token`, and the
backend refuses with `changed_since_preview` when the study changed in between (M1
R4). Every act that changes the files writes one line to the record of the files
(§3 S5) **[C8]**.

## 8. Missing facts and inferences, shown

- **Units:**
  - a table brought in without its units file: `<Pending>` "[units pending]" in
    the row, and the plan's `units_missing` answer recorded with it (Q-M2-7 a);
  - a workbook: its units are read from its "Key to Column Labels" sheet (Q-M2-7 b)
    **[core]**. The row shows "17 units, from the workbook's Key sheet".
    `bmdx_pipe.pool_integrator.key_sheet_units` read the CEBS workbooks: Body
    Weight 1, Clinical Chemistry 17, Hematology 16, Hormones 4, Organ Weight 5,
    Tissue Concentration 4 [V]. A column the Key sheet gives no unit for stays
    `<Pending>` "[unit pending: Albumin]". Clinical observations have none, by
    rule ("Observations are counted; they have no units").
- **Sex:** a table whose sex is not detected: "[sex pending]". [V: a
  one-row-per-animal `Organ_Weights_M.csv` was made into `Organ_Weights_M.txt` with
  no sex.] With classification by content (below), the sex is read from the file's
  `Sex` column **[core]**.
- **A `.bm2` whose contents were not read:** "[contents not read: its doses and
  animals were not compared with the other files]". [V: the 2026 PFHxSAm package's
  six `.bm2` files, on a cold cache; `fingerprint_bm2` skips the read when the
  name already classifies the file, `bmdx_pipe/file_integrator.py:1444`.] Until
  every `.bm2` is read at the check **[core]**.
- **Not recognised:** "[what this file is: pending]".
- **Every classification is shown as detected until a person confirms it.** The
  tag and the "why" line are the inference flag. The line names the basis: its
  content, its file name, or the project's experiment names. Nothing passes as
  confirmed by default, and every file is confirmed before combining (Q-M2-4).
- **One-row-per-animal files are classified by their content** (Q-M2-6) **[core]**:
  a file with one row per animal and `Animal ID` and `Sex` columns is "the study's
  own measurements", whatever its name. The flag `name_says_gap_filled` retires.
  [V: today `body_weight_female.csv` is taken as gap-filled by its name.]
- **Several test articles in one `.bm2`:** the test articles are read from the
  experiment names, an inference said as such ("read from its experiment names").
  It is a must-fix issue with its act (S2-N) (Q-M2-5).
- **What a BMDExpress project fills in or leaves out (Q-M2-3) [core] [maintainer:
  confirm this is the rule meant].** A `.bm2`'s apical data is BMDExpress's input:
  - a missing value is filled with its dose group's mean (**cell imputation**);
  - a dose group BMDExpress cannot model is left out (**dose-group drop**).

  ADR-0017 ("Two distinct inference mechanisms") names both. The rule M2 applies,
  per `.bm2` and per study table of the same platform and sex, aligned by animal:
  1. a value the study table leaves missing and the `.bm2` holds is **imputed**:
     information, never a mismatch. It is counted per dose group and served as
     `bm2_changes.imputed` (§3 S2) and as the expected item `bm2_fills_missing`.
     [V on T7: one Free Thyroxine value of male 161, dose 12, left out of the table
     and present in `Hormones.bm2`. The check raised nothing, and the dataset reads
     `imputed_cells = {Hormones: {Male: {12.0: 1}}}`.]
  2. a dose group the table has and the `.bm2` lacks is **left out**: information
     (`bm2_dose_groups_left_out`). [V: the 2026 package's `Body weight.bm2` lacks
     333 and 1000, which the body-weight tables have.]
  3. a value both hold, and that differs, is a **mismatch**: must fix
     (`bm2_value_mismatch`). [V: 6 table/`.bm2` pairs of the 2026 package (clinical
     chemistry, hematology, hormones; both sexes), aligned by animal: 0 such
     values.]

  The screen also says whether the report footnotes the imputed values (served
  `footnoted` per platform). Today the clinical-pathology tables (Clinical
  Chemistry, Hematology, Hormones) footnote them: "Benchmark dose modeling used an
  inferred dataset in which 1 missing individual value was replaced with the
  dose-group mean (affected dose group: 12 mg/kg)." [V on T7's sidecars, through
  `tables/clinical_pathology_table.py`]. Body Weight and Organ Weight tables are
  not given the imputation map (`pipeline/processing_helpers.py:699`) [R], so the
  screen says "The report does not footnote this yet for Body Weight." It never
  claims a footnote that the report won't print.

  The rule as built differs from this in four ways (§10, core). The built rule:
  - runs only when the dataset is read, not at the check;
  - pairs files by the `_truth_` name;
  - gives up whenever a dose group was also left out;
  - is footnoted for three platforms only.
- **Coverage warns when a platform has only its workbook**, until the cause below
  is fixed. The coverage row says: "Only the study workbook … bring in the tables
  made from it too." **The cause is found [V]: a table with empty cells is left out
  of the combined dataset, silently.**
  - A workbook is made into tables that leave a missing value empty
    (`bmdx_pipe/pool_integrator.py:377` [R]). The CEBS workbooks give 6 empty
    cells in male Clinical Chemistry, 16 and 15 in Hematology, and 40 and 40 in
    Organ Weight [V]. Those are exactly the 5 experiments missing from the earlier
    run.
  - A table with `NaN` for a missing value is kept [V on T9: of two body-weight
    tables, the one with 61 empty cells was not in the dataset, the one with `NaN`
    was; no error, no warning].
  - Integrating the 2026 package also dropped its own body-weight and organ-weight
    tables (empty cells) [V].

  This is for the core track and M3 (§10). M2's check must not pass a table that
  integration would drop.

## 9. Waits

- **Upload** (Step B): a per-file `Progress` in the page. Foreground; the page
  warns on leaving. No size limit.
- **The check:** a blocking `Modal` with `Spin` and elapsed time. It is one call,
  with no stream. **[request R-M2-7]** asks for the kit's short-wait form (a
  `<Wait>` that takes a promise), so the look is shared.
  - First read of a 251 MB project: 29.6 s [V].
  - Reading imputed values at the check: about 0.6 s for one project and table
    [V, prototype].
- **Narrowing a shared project:** the same blocking form; 1.5 s for the 40 MB
  project [V].
- Everything else takes about a second or less, and its button shows a loading
  state: the plan's commit, classification, remove, restore, reset, the record.
  - The commit of a batch into a combined study deletes many files: still under a
    second [R].
  - Keeping a dataset copy adds 0.3–0.7 s (gzip of 77–169 MB) [V].
- Nothing runs in the background.

---

## 10. What M2 needs from C3, C4, C8, C12 and the core track (precisely)

**C4: stable ids, reads with no side effects**
1. `GET …/files` reads only. It must not create the session folder, re-scan the
   files, mint ids or register uploads. Today `GET /api/wizard/{id}/fingerprints`
   re-scans on a cold server (finding 2).
2. **The id of a file is the name the person brought it in under.** A converted
   CSV is one entry; its pivot `.txt`, `.sidecar.json` and `.units.json` are its
   companions. Every issue's and conflict's files are given as these names
   (served), never as `file_id`.
3. Issue and conflict ids are deterministic: a hash of the type, the platform and
   the sorted file names (and the message, so new content gives a new id). They
   are stable across re-checks and restarts [V: the fixture generator does it].
4. `content_hash` per file, so a same-name replacement and an exact copy are
   recognised, and a statement about the old content is marked "changed since you
   confirmed it".

**C3: saves merge and check**
1. Person-stated classifications live in a durable file keyed by file name (say
   `classifications.json`: `{name: {platform, data_type, content_hash, stated_at}}`).
   Fingerprinting honours it on every check; a re-check never reverts it (finding
   4); `.xlsx` and `.bm2` included.
2. The values are checked against `bmdx_pipe.VOCABULARIES` and the allowed pairs
   (data type × kind × platform) on the backend. Unknown names are refused, not
   skipped.
3. The statement file joins C1's integration basis, so a correction after
   integration makes the integration out of date (C1 §3.2 named this gap).
4. The check's result is "out of date" when the statement file or the files
   changed since it ran (`check.current`, `why_not_current`), derived.
5. The confirmation is recorded per file: who stated it (`person`) and when.
6. Classifications are offered per kind of file (served `classification_choices`).
7. Integration refuses `classification_unconfirmed` while a file is not confirmed
   (with C1's guard; Q-M2-4).

Retired by the answers: conflict decisions as recorded state
(Q-M2-1 = C). Keeping a file is a removal, so `precedence.json` retires, and the
precedence part of C1's integration basis is always empty. `resolve_step` stays for
the command line until removed.

**C8: dry runs of destructive acts; restore; the record of the files**
1. A dry run (§4.3 object + `preview_token`) for each act:
   - `add_files` (inside the staging plan);
   - `remove_file`;
   - `restore_file`;
   - `keep` (a conflict settled here);
   - `narrow` (a shared `.bm2`);
   - `classify` (when combined);
   - `reset_files`.

   Each is computed by the same code that does the act. The approvals lost come
   from the section files and from `animal_report.json`.
2. Every act takes the `preview_token` and refuses `changed_since_preview`.
3. Removal moves **every** companion, the `.units.json` included [V: today it is
   left in `_originals/`]. It records why and when in `_removed/<stamp>/removed.json`.
4. Restore from `_removed/`; refuse when the name is taken. Restore works in every
   phase, EMPTY included.
5. A same-name replacement moves the old file to `_removed/` with `why: replaced`.
   Today it is overwritten (`web_routes/upload_routes.py:133-135` [R]).
6. Invalidation archives the data approval (as C1 D5 does at integration), rather
   than deleting it.
7. The pool reset moves into a core step with its dry run.
   - **It keeps `_removed/`** (Q-M2-11). Today it deletes it
     (`web_routes/session_routes.py:1431` [R]).
   - It moves the current files there with `why: reset` **[maintainer]** (Q-M2-12).
   - It keeps `records/`.
8. The staging area (`sessions/<id>/_incoming/<batch>/`): outside `files/`, so no
   phase changes; expires after 1 hour; never scanned by fingerprinting. An upload
   is streamed to disk, whatever its size.
9. **The record of the files** (Q-M2-11): `records/files.jsonl` in the study.
   - It is append-only: one JSON line per event, each with: when, what (added,
     replaced, removed, set_aside, narrowed, restored, reset), the file name, its
     size, its full sha256, by (`person`), why, and the batch, removed-entry or
     conflict id.
   - Every act of rows 2–7 writes it, from the same code that does the act.
   - Nothing rewrites or deletes it but M1's delete of the whole study.
   - Read by `GET …/files/record`.
   - Storage: a few hundred bytes per event.

**C12 (NEW, proposed): the record of combined datasets** (Q-M2-11). Proposed as a
new core item, not part of C8. It is written by integration and read by M3 and the
deliverables, and it outlives every undo. `MODULES.md` §2 needs the row.
1. `records/datasets.jsonl`: one line per integration, written by `integrate_step`:
   - its number and time;
   - its basis (C1's `integration_basis`);
   - the input files with their sha256;
   - the dataset's sha256 and size;
   - its experiments, BMD-result count and imputed cells (`_meta.imputed_cells` as
     read).
2. **A kept copy** of a dataset, `records/datasets/<n>.integrated.json.gz`. It is
   written when that dataset is about to be deleted or replaced (invalidation,
   re-integration, Start over), **if Process ran on it**: the data a report could
   have been built from. A dataset never processed keeps only its line.
   **[maintainer]** Q-M2-13.
   - The current dataset needs no copy: it is `integrated.json`.
   - Storage, with gzip at level 1: NIEHS-10's 77 MB dataset → 9.4 MB in 0.32 s;
     the largest, 169 MB → 20.5 MB in 0.71 s [V]. The 17 datasets in the store
     total 1.78 GB uncompressed [V]. A study that is reprocessed after every file
     change grows by about 10–20 MB each time. Nothing purges these copies (Q-M2-14).
3. Process (C5) records, in its run record, the number and sha256 of the dataset
   it ran on, so each deliverable can name its dataset (D3, C10).
4. M2 reads only `{count, current}` (served in `FilesView.records`); M3 shows the
   record.

**The core track (bmdx-pipe, `workflow`, `pipeline`, `tables`)**
- the completeness rule for apical platforms: a `.bm2` is not required (Q-M2-3; the
  rule is `workflow/phases.py:171`, the message at :208);
- `redundant_files` as a blocking error (Q-M2-2). Today it is info, and raised only
  between files of one tier (`bmdx_pipe/file_integrator.py:2079`);
- `same_content`, exact copies by content hash across names, as a blocking error
  (Q-M2-9);
- both of these, served with `settle: "outside"` and refused by the keep step;
- `several_test_articles` as a blocking error, and `narrow_bm2_step` over
  `subset_bm2` (Q-M2-5). [V: 40,485,229 → 8,220,917 bytes in 1.5 s; the narrowed
  project holds the 4 PFHxSAm experiments, 4 BMD results and 8 category results];
- classification of one-row-per-animal files by content (Q-M2-6), the sex read
  from the content;
- workbook units from the Key sheet (Q-M2-7 b);
- every `.bm2` read at the check (§8). **The bm2 cache cannot hold the 251 MB
  project:** its JSON fails with `MDB_MAP_FULL` on an empty cache [V], so such a
  project would be read again (about 30 s) at every check;
- conversion of one-row-per-animal CSVs at the check, not at upload, so a units
  file is paired whatever the order (as `generate_report.import_files` already
  behaves [R]);
- **the imputation rule at the check** (Q-M2-3; §8). What is built
  (`pipeline/bmd_project_schema.py:324` `_detect_imputed_cells`, called by the
  pre-validator at :861) needs four changes:
  - (a) it runs only when the dataset is read, never at the check, and is not
    written to `integrated.json` on disk [V on T7: on disk absent, as read
    `{Hormones: {Male: {12.0: 1}}}`]. A check-time version over the `.bm2`'s JSON
    and the table took 0.57 s [V, prototype];
  - (b) it aligns by position and gives up when the dose vectors differ, so a
    `.bm2` that also drops a dose group hides all its imputed values [V: T7's
    dataset with the 111 group removed from the project → none detected]. Align by
    animal instead (the treatment name);
  - (c) it pairs by the `_truth_` name. A study table named otherwise is not
    paired, and loading the dataset then fails with "Apical experiments must be
    unique per (platform, sex)" [V, on a renamed copy of T7's dataset]. Pair by
    classification (with Q-M2-6);
  - (d) only the clinical-pathology tables get the footnote
    (`pipeline/processing_helpers.py:699` [R]);
- `bm2_value_mismatch` and `bm2_dose_groups_left_out` from the same comparison
  (§8, **[maintainer: confirm]**);
- **a table with empty cells must never be silently left out of the dataset** (§8
  [V]). Either the tables write `NaN` for a missing value, or integration accepts
  an empty cell, or it refuses loudly. This is for M3 and the core track. M2's
  check must not pass a table that integration would drop.

## 9. Requests to the orchestrator

- **R-M2-1.** Register `/app/studies/:id/files` (slug `files`, already in
  `kit/modules.ts`) in the shell's router.
- **R-M2-2.** M2's endpoints in the API client, and MSW handlers serving the
  fixtures of `contract.md` §4.
- **R-M2-3.** Kit `Action` type and `ACTION_WORDS` to C1's table: ADD_FILES,
  REMOVE_FILE, RESOLVE, CONFIRM_CLASSIFICATION, STATE_DATASET_FACTS, PROCESS (no
  REPROCESS, no CLEAR_FILES).
- **R-M2-4.** `<ConfirmAct>`: a dry run with parameters (`loadDryRun` exists),
  and passing the dry run's `preview_token` to `perform` (M1 R4).
- **R-M2-5.** The codes of §6 in `workflow/refusals.py`.
- **R-M2-6.** `<VocabField>`: an `allowed` prop restricting the values to a
  served subset.
- **R-M2-7.** The kit's `<Wait>` in a form for a single blocking call (spin +
  elapsed, no stream).
- **R-M2-8.** The shell hides M2 for companions and reports (M1 R1/R6).
- **R-M2-9.** `files.next` and `files.progress` may feed the shell's next step
  (`shell/nextStep.ts`), so the two never disagree. `files.next.act` may be null
  (a conflict to settle outside the app).
- **R-M2-10.** C12 as a new core item in `MODULES.md` §2 (or folded into C8, if the
  orchestrator prefers; §10 says why it is proposed apart). M3's spec shows the
  dataset record.
- **R-M2-11.** The empty-cell finding (§8) to M3 and the core track.

## 11. Open questions for the maintainer

### Answered 2026-10-16 (the maintainer)

- **Q-M2-1: C, yes.** Keeping one file of a conflict moves the other to the removed
  files (restorable, with the reason recorded).
- **Q-M2-2: no in-app choice.** Redundant files are flagged as a conflict; the person
  arbitrates **outside the app** (fixes the files, then brings them in again or
  removes one). The app offers no "keep one" for them.
- **Q-M2-3: A, yes,** a `.bm2` is not required for apical platforms. **But:** when
  apical data is in a `.bm2`, it may hold imputed values for doses missing in the
  corresponding study file. That is intentional, and there is a rule for what to do
  (the orchestrator found it built as `pipeline.bmd_project_schema._detect_imputed_cells`
  + `_meta.imputed_cells` + the imputation footnote, ADR-0017 §"Two distinct
  inference mechanisms"; to be confirmed by the maintainer as the rule meant). The
  check must not flag such imputed values as a mismatch.
- **Q-M2-4: yes.** Every file is confirmed before integration.
- **Q-M2-5: A, yes.** A `.bm2` holding several test articles blocks, with "Keep only
  this study's experiments".
- **Q-M2-6: yes.** One-row-per-animal files are classified by content.
- **Q-M2-7: yes to both.** (a) Allowed with the acknowledgment and "[units pending]";
  (b) workbook units read from the Key sheet.
- **Q-M2-8: no size limit.**
- **Q-M2-9: flag, as Q-M2-2.** An exact copy under another name is flagged as a
  conflict, not refused; the person arbitrates outside the app.
- **Q-M2-10: yes, and flag it as it happens.** A same-name replacement keeps the old
  file among the removed files; the person is told, while bringing the file in, that
  it replaces one, and confirms.
- **Q-M2-11: no.** "Start over" does not delete the removed files. **Keep a record of
  the files, and keep a record of the integrated data.**

How this spec applies them: Q-M2-1 in S3-C Kind 1. Q-M2-2 and Q-M2-9 in S3-C Kind
2, §5, and S1's `copy` row. Q-M2-3 in §8 and §10. Q-M2-4 in S2 and §6. Q-M2-5 in
S2-N. Q-M2-6 and Q-M2-7 in §8. Q-M2-8 in §4. Q-M2-10 in S1 and §7. Q-M2-11 in S4,
S5, C8 item 9, and C12.

### Still open

- **Q-M2-3a [maintainer: confirm this is the rule meant].** §8's three-part rule.
  Per `.bm2` and per study table of the same platform and sex, aligned by animal:
  - imputed values: information, footnoted;
  - dose groups left out: information;
  - a value both hold that differs: must fix.

  Two consequences of the code as built are on screen:
  - it misses imputed values whenever a dose group was also left out;
  - only the Clinical Chemistry, Hematology and Hormones tables footnote them.

  Proposed: fix both (§10). Until then, the screen says "The report does not
  footnote this yet" where that is so.
- **Q-M2-12. "Start over" and the current files.** Proposed: they move to the
  removed files (why "Start over"), so the person can restore them; this costs
  their own size. The alternative is that they are deleted and only recorded (name,
  hash, size) in the record of the files.
- **Q-M2-13. Which combined datasets keep a copy.** Proposed: a dataset Process ran
  on, kept compressed when it is replaced or deleted (about 10–20 MB each). The
  alternatives:
  - every dataset;
  - none, keeping only the hash and summary. The data a report was built from
    could then be rebuilt only from the recorded files.
- **Q-M2-14. Purging.** Removed files and dataset copies are never purged in the
  app; their total size is shown. Proposed: no purge act for now. Only deleting
  the study (M1) removes them.
- **Q-M2-15. The `copy` row at intake.** An exact copy under another name is not
  refused, but the plan asks "Bring it in anyway?" before it is written. The
  question warns as it happens; the check then flags it. Is the extra answer
  wanted, or should the copy just come in with a warning?

## 12. Acceptance criteria

Tested in a headed browser against the app on a **scratch store**, with
`SESSIONS_DIR`, `OUTPUT_DIR` and `BM2_CACHE_DIR` in the tester's scratch
directory. The test files:
- in `/workspace/ui-team/_scratch/design-m2/testdata/`:
  - T1: NIEHS-10's inputs, 27 files;
  - T2: the 2026 PFHxSAm package, 21 files;
  - T3: NIEHS-10's CEBS workbooks and the shared `.bm2`;
  - T4: conflicts;
  - T5: a value mismatch;
  - T6: wrong files;
- in `/workspace/ui-team/_scratch/m2-design/testdata/`:
  - T7: `Hormones.bm2` with the hormone tables, one male value left out of
    `hormones_truth_male.csv`;
  - T8: `body_weight_truth_female.csv` with one value edited (215.9 → 999.9, same
    size), and `body_weight_truth_female_2.csv`, an exact copy of T1's
    `body_weight_truth_female.csv`, each with its units file;
  - T9: two body-weight tables, one with empty cells.

Each study is created first in M1, for example `DTXSID9000001` … `DTXSID9000009`
(created as other sessions). "A copy of NIEHS-10" means `sessions/DTXSID50469320`
copied into the scratch store. A criterion marked [C3], [C4], [C8], [C12] or
[core] is tested against the mocks until that holds.

**Reaching the page**
1. `/app/studies/DTXSID50469320_published/files` shows "This is the published
   book's own content. It takes no data files." and no control.
2. On a new, empty study, the page shows "No files yet", the next step "Bring in
   the study's files", and Check, Remove and Start over disabled, each with its
   reason on hover.

**Bringing in: in the browser**
3. Choosing every file of T6 lists them before anything is sent.
   - The `.pdf`, the `.docx` and `body_weight_truth_female.sidecar.json` are
     refused with plain reasons.
   - `empty.csv` says "This file is empty."
   - **Send to the server for checking** stays disabled until the refused rows are
     removed from the list.
4. Choosing T1's `body_weight_truth_female.units.json` alone is refused: "This
   units file has no table …".
5. Choosing two files of the same name (from two folders) is refused before
   sending.
6. No file is refused for its size; no size limit is mentioned anywhere on the
   page except "There is no size limit".

**Bringing in: on the server**
7. Sending `hormones_male_table.bm2` (T6) gives "… is named .bm2 but is a text
   table …", and it is not added.
8. Sending `two_same_names.zip` (T6) refuses both entries with the "two files
   named body_weight_truth_male.csv (in a/ and b/)" message. Nothing is added.
9. Sending T6's `tissue_conc_truth_female.csv` without its units file marks it
   "Needs your answer". **Bring in** stays disabled until **Bring it in without
   units** is ticked. Afterwards its row shows "[units pending]".
10. Sending all of T1 shows 27 rows:
    - 13 tables, each with its units file paired ("Units for …");
    - 2 clinical-observation tables;
    - 1 `.bm2`.

    **Bring in 27 files** adds them. The table then has **15 rows**, each
    `.units.json` shown in its table's expanded row, never as a row of its own
    [C4].
11. **Discard** after the server's plan leaves the study unchanged (the files
    table is as before, and the phase is unchanged).
12. A plan left open for over an hour, then committed, says "These files were
    waiting too long … Nothing was brought in." [C8]
13. In the T1 study, sending T1's `body_weight_truth_female.csv` again, unchanged,
    shows "Already in the study, unchanged" and is not counted in **Bring in N
    files**.
14. In the T1 study, sending T8's edited `body_weight_truth_female.csv` shows
    "Replaces body_weight_truth_female.csv already in the study (added …, 6,387
    bytes; this one 6,387 bytes, different content). The old one will be kept
    among the removed files …".
    - Without **Replace it** ticked, **Bring in** is disabled.
    - With it ticked, the new file is in, and the old one is among the removed
      files: "Replaced by a newer body_weight_truth_female.csv".
    - The record shows a "replaced" line and an "added" line with different content
      hashes [C8].
15. In the T1 study, sending T8's `body_weight_truth_female_2.csv` shows "This is an
    exact copy of body_weight_truth_female.csv, already in the study, under another
    name …". **Bring in** stays disabled until **Bring it in anyway** is ticked or
    the row is dropped.
16. On a copy of NIEHS-10 (APPROVED), bringing in any file first shows what will
    be deleted.
    - The list includes the file check, the combined dataset (with "a copy is kept
      in the dataset record"), the data review and the stored processing results.
    - It says the Summary will be marked out of date, and gives the cost.
    - **Cancel** changes nothing [C8, C12].

**Checking**
17. On the T1 study, **Check the files** shows a blocking wait with elapsed time,
    then: "Nothing blocks. 7 points are worth a look; 25 are expected for this
    kind of package." Every issue names files by their names; no id like
    `9a196bfd-…` or `scan-…` appears anywhere.
18. The "Expected" panel is collapsed. It holds the ten "… animals in the study's
    roster are not in …" items, each saying the data review accounts for them.
19. On a copy of NIEHS-10, the page says the analysis-method checks are shown in
    Method and report definition, with a link. No method message appears in the
    issue lists.
20. The coverage table of the T1 study shows 8 rows (gene expression and 7
    platforms), each "ok". The words "Requires .bm2" appear nowhere [core].
21. On a copy of NIEHS-10, checking again leaves the phase APPROVED and the
    combined dataset in place. The tooltip of **Check the files** says checking
    never deletes it.
22. The T5 study's check shows under "Must fix": "Body Weight: 1 of 243 values …
    animal 111, SD0 … workbook 215.9, table 251.9 …". **Combine** is not offered
    anywhere on the page.
23. The T3 study's check shows one item under "Must fix": "This BMDExpress project
    holds experiments of 4 test articles (10-2 FTOH, 2,3-Benzofluorene, 6-1 FTOH,
    PFHxSAm) …". In the same study:
    - the coverage rows of the workbook-only platforms warn "Only the study
      workbook …";
    - the Clinical Chemistry workbook shows "17 units, from the workbook's Key
      sheet", not "[units pending]" [core].
24. The T2 study's six `.bm2` rows show "[contents not read …]" when their
    contents were not read, and never show empty doses as if they were data.
25. The T7 study's check shows no "Must fix" and no value mismatch. The
    `Hormones.bm2` row shows the tag "Fills 1 missing value". Its expanded row
    says:
    - that it fills 1 value hormones_truth_male.csv leaves missing (males, dose
      group 12: 1 value), and that this is expected;
    - that the report footnotes it, with the footnote's text.

    The "Expected" panel holds the same item [core; maintainer: confirm].
26. In the T2 study, once its `.bm2` contents are read, `Body weight.bm2` shows "2
    dose groups left out" as information (333 and 1000), with no "Must fix", and
    says the report does not footnote imputed values for Body Weight if it finds
    any [core; maintainer: confirm].

**Saying what each file is**
27. Every checked row shows "Detected, not confirmed" and, in its expanded row,
    why: "From its content …", "From the file name" or "From the experiment names
    inside the BMDExpress project".
28. In "What is this file?", a table offers three data types, each with its
    explanation; a workbook offers one; a `.bm2` offers two. The platform list
    holds only the platforms offered for the chosen data type, with no free-text
    entry. Choosing gene expression hides the platform.
29. Correcting `hematology_truth_male.csv` to Hormones, then checking again,
    keeps "Changed by you: Hormones". The correction survives a server restart
    [C3].
30. After a correction, the Check step says the check is out of date because a
    file's classification changed [C3].
31. **Use what the tool detected** fills the detected values. **Undo** after
    saving restores the previous statement.
32. On a copy of NIEHS-10, correcting a file first shows that the dataset must be
    combined and processed again. After saving, the page says the files changed
    since they were combined (integration out of date) [C3].
33. **Confirm the N files as shown…** lists exactly the files it will confirm, and
    leaves out the flagged and unrecognised ones, naming them. After confirming,
    those rows read "Confirmed by you".
34. In a T6 study, `Organ_Weights_M.csv` is detected from its content as "Organ
    Weight · the study's own measurements", for males. It carries no gap-filled
    flag and is in the bulk confirm list [core].
35. With the files table open in two tabs, removing a file in one and then bulk
    confirming in the other says "The files changed while this list was open.
    Nothing was confirmed."
36. On the checked T1 study, while any file is unconfirmed, the next step is
    "Confirm what each file is" and the page offers no way to Combine. Once all
    are confirmed, the next step is "Combine the files into one dataset" [C3].

**Conflicts**
37. The T4 study's check shows two conflicts under "Must fix", visibly of two
    kinds:
    - Hormones (females: doses 1.4 vs 2), tagged **Choose here**, with the files
      side by side, the differing rows highlighted, and a "Keep:" choice;
    - Body Weight (`body_weight_truth_female_copy.txt` and
      `body_weight_truth_female.csv`), tagged **Fix outside the app**, with the
      three numbered steps and no choice and no keep button.

    The progress step reads "Conflicts: 1 to choose here, 1 to fix outside the
    app".
38. In the Hormones conflict, no file is preselected. **Keep this file** is
    disabled until one is chosen. The check's suggestion, when shown, says it does
    not know which is right.
39. Keeping `hormones_truth_female.csv` shows what will be set aside (the rerun
    file and its units file and tables) and that it can be restored. After it:
    - the conflict is gone;
    - the rerun file is among the removed files, "Set aside when you kept
      hormones_truth_female.csv";
    - the record shows a "set aside" line;
    - the next step is "Check the files".

    Checking again clears the dose error [C8].
40. Restoring the set-aside file brings the conflict back at the next check [C8].
41. Removing `body_weight_truth_female_copy.txt` from its row (**Remove…**) and
    checking again clears the Body Weight conflict. Until then, the next step is
    the warning "Settle … outside the app, then check the files again", and no
    Combine is offered [core].
42. A study holding T1's `body_weight_truth_female.csv` and T8's
    `body_weight_truth_female_2.csv`, once checked, shows "… is an exact copy of
    …" under "Must fix", as a **Fix outside the app** conflict, and offers no
    Combine [core].
43. In the T3 study, **Keep only this study's experiments…** on the `.bm2` row
    lists the 4 test articles, each with its 4 experiments, none preselected.
    Choosing PFHxSAm shows the dry run (replaced by a copy with 4 experiments; the
    original kept among the removed files). After it:
    - the row shows about 8.2 MB and 4 experiments;
    - the original is among the removed files, "Narrowed to PFHxSAm";
    - checking again clears the issue [core, C8].

**Removing, restoring, starting over**
44. On an unchecked study, **Remove…** removes the file at once with an **Undo**.
    **Undo** brings it back, its units file included [C8].
45. On a checked study, **Remove…** first lists what goes: the file, its units
    file, its table and sidecar, and the check. **Cancel** changes nothing.
    **Remove** moves it to "Removed files", with when and why [C8].
46. **Restore…** is disabled, with the reason, while a file of the same name is
    in the study.
47. On a copy of NIEHS-10, **Start over…** lists:
    - what goes: the converted originals, the combined dataset (a copy kept in the
      dataset record), the data review, the result sections, the Summary, the
      stored processing results;
    - what moves: the 15 files, to the removed files;
    - what stays: the identity, the study design, the authors, the method pin, the
      deposit record, the Background, the history, the removed files, the record
      of the files, the record of the combined datasets;
    - the line that the stated facts will apply again to the next files.

    **Start over for good** stays disabled until `DTXSID50469320` is typed exactly
    [C8, C12].
48. After **Start over**:
    - the page shows "No files yet … Files you removed are kept below and can be
      restored", and the phase is EMPTY;
    - the study is still in the studies list;
    - "Removed files" lists the study's former files ("Removed when the files were
      started over") and every file removed before;
    - restoring one brings it back;
    - the record shows a "started over" line [C8].
49. Changing the files in another tab while a removal or "Start over" dialog is
    open, then confirming, says the files changed after review. Nothing is done
    [C8].
50. In the T1 study, after bringing in, removing one file and restoring it, "Record
    of the files" lists every event. Each line shows when, what, the file, its
    size, a short content hash with a copy button, and why. Nothing in it can be
    edited or deleted. Under it, the line about the combined datasets links to M3
    [C8, C12].

**Everywhere**
51. Every refusal shows plain words and a "Details" toggle with the backend's own
    message. No file id and no internal key (`Body Weight|tox_study`,
    `issue_index`) is shown outside "Details".
52. While Process runs on the study (another tab), every M2 act is disabled with
    "Process is running on this study since …" [C5].
53. Reloading the page at any point shows the same state. The browser stores
    nothing; a reload during an upload loses the staged batch and nothing in the
    study.
54. The word "wizard" appears nowhere on M2's screens.
