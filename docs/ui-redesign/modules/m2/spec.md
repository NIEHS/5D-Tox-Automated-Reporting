# M2 Study files: bring in, check, confirm, settle

Module M2 (`MODULES.md` §3). Written 2026-10-15 by the interaction designer from
`modules/gate0-data/analysis.md` §2 (steps 1–4, lifecycle L), findings 2, 3, 4,
12 and §3; the signed C1 and M1 specs; and the backend code. It builds on the
shared kit and contracts of `MODULES.md` §4 and does not redefine them. The
endpoints and fixtures are in `contract.md`.

It is written **as M2 should work once C3, C4 and C8 hold**. Every behaviour that
depends on one of them is marked **[C3]**, **[C4]** or **[C8]**, so it can be built
against the mocks now. §10 lists what M2 needs from each. Behaviour that depends
on the open question Q10 is marked **[Q10]**: the screens are specified for the
recommended option, and §11 says what changes under the others.

Evidence marks: **[V]** verified by running it on scratch copies in
`/workspace/ui-team/_scratch/design-m2/` (the real `sessions/` was never
written); **[R]** read from the code.

Markers: **[maintainer]** needs a decision (§11); **[request]** is something M2
needs from the orchestrator (§9).

---

## 1. The person's goal

> "I want to put this study's data files in, find out whether the tool understood
> each one, fix what is wrong, and know for sure that what gets combined is
> exactly my study's data: nothing missing, nothing twice, nothing from another
> study."

In detail:
- **Bring in files.** Choose files or a zip. See, before anything changes, what
  each file is taken to be, which ones are refused and why, and what adding them
  does to work already done.
- **Check them.** Run the file check. See plainly what must be fixed, what is
  worth a look, and what is expected for this kind of package.
- **Say what each file is.** Confirm or correct each file's platform and data
  type from a fixed list. A correction is never lost.
- **Settle conflicts.** Where two files disagree or duplicate each other, compare
  them side by side and keep the right one.
- **Remove a file, or start the files over.** See what goes and what stays, and
  confirm. A removed file can be restored.

## 2. When the module is reachable

Route: `/app/studies/:id/files` (the kit's `moduleRoute('M2', id)`, slug `files`).

Everything the screen shows about the workflow comes from the backend: the kit's
`useStudyState(id)` (§4.1) and M2's own read, `GET /api/v2/studies/{id}/files`
(contract §2.1). The browser computes no phase, no permission, no readiness and
no classification.

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
| Keep one file of a conflict | RESOLVE | VALIDATION_ERRORS and later |
| Remove a file; restore a removed file | REMOVE_FILE (restore is ADD_FILES) | UPLOADED and later |
| Start the files over | RESET | UPLOADED and later |

M2 ends where M3 begins. Once the phase is VALIDATED (or later), no conflict is
open and every file is confirmed, `files.next` points to M3, "Combine the files
into one dataset". The link is the only way M2 leads to integration: M2 has no
Integrate button.

---

## 3. Screens

One page with five parts, in a fixed order. Each part says why it is inactive
when it is.

### S0 Header and progress

- The kit's study header (identity, `<PhaseTag>`), from the shell.
- An antd `Steps` (horizontal; vertical below 768 px) built from `files.progress`
  (served):
  1. **Bring in files**: "15 files in the study";
  2. **Check**: "Checked 12 Oct 2026: nothing blocks", or "2 problems to fix";
  3. **Say what each file is**: "15 of 15 not yet confirmed";
  4. **Settle conflicts**: "2 conflicts to settle", or "No conflicts".

  Each step's `status` maps to the `Steps` status: `done` → finish, `todo` →
  process, `blocked` → error, `waiting` and `not_needed` → wait. A step is a
  link that scrolls to its part. The `Steps` only show where things stand and
  are not a sequence the person clicks through: the backend decides what is
  allowed.
- Under it, the **next step** from `files.next`, as the primary button: "Confirm
  what each file is" (scrolls to S2) or "Combine the files into one dataset" (to
  M3).
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

**The drop zone.** An antd `Upload.Dragger` with `multiple`, `directory` off,
`beforeUpload` returning `false`, so nothing is sent on drop. Its `accept` is
`.bm2,.csv,.txt,.xlsx,.zip,.json`. Help text:
- "BMDExpress projects (.bm2), study tables (.csv, .txt), study workbooks (.xlsx),
  or a .zip of these.";
- "A one-row-per-animal .csv brings its units in a file of the same name ending
  in .units.json. Bring both together."

**Step A: checked in the browser, as soon as files are chosen** (§4, rules
1–8). The chosen files appear in a `Table` "About to bring in", one row per
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
- The upload shows a `Progress` per file. It is a foreground wait: the page warns
  on leaving (`beforeunload`), and the button is replaced by **Cancel upload**.
- The server answers with the **intake plan**, shown in place of the table:
  - one row per file, with what the server found: its real type from the
    content, the zip's contents (each entry a row, with the folder it came from),
    the pairing of each `.units.json` with its table, and a same-name match with
    a file already in the study;
  - for every row, `verdict` and `say`:

| Verdict | Row shows | The person must |
|---|---|---|
| `add` | "Will be added." | – |
| `units` | "Units for body_weight_truth_female.csv (1 measurement: grams)." | – |
| `replace` | "Replaces body_weight_truth_female.csv already in the study (added 12 Oct 2026, 6,387 bytes; this one 6,402 bytes, different content). The old one is kept among the removed files." | tick **Replace it** in the row; otherwise the row is not added |
| `units_missing` | "This one-row-per-animal table came without a units file. Its tables will show [units pending] for every measurement." | either add the `.units.json` to the batch (back to Step A), or tick **Bring it in without units** |
| `refused` | the reason (§6) | nothing; the row is not added |
| `left_out` (zip entries that aren't data) | "Left out: not a data file (C20022-01_Hormone_Summary.docx)." | nothing |

  - **What adding them does** (only when the study has been checked or
    combined). The plan carries the backend's dry run, the §4.3 object
    **[C8]**. It is shown inside the plan as the kit's consequences list: "It
    will delete: the result of the last file check; the combined dataset; the
    data review; the stored results of processing (11 files) …", "Approvals that
    will be lost", "It will keep …", and `cost.say`: "checking the files again,
    combining them again (about 25 s), and processing again (about 3 minutes)".
- **Buttons:**
  - **Bring in N files** (primary; N counts the rows that will be added). It is
    disabled while any `replace` or `units_missing` row is unanswered, with "Answer
    the rows marked 'Needs your answer' first." When the plan's dry run is costly,
    the button opens the kit's `<ConfirmAct strength="costly">` with that list
    before it commits. It sends `POST …/staging/{batch}/commit` with the plan's
    `plan_token` and the answers.
  - **Discard** throws the staged batch away (`DELETE …/staging/{batch}`). Nothing
    in the study changed.
- **After the commit:** a `message`: "12 files brought in. Check the files next."
  The page re-reads the files view and the state, and **Check the files** becomes
  the next step.

A staged batch is never committed by itself. It expires after 1 hour; a stale plan
refuses with `staging_expired`.

### S2 The files

A `Card` titled "The study's files". It holds an antd `Table`, one row per
**file the person brought in**. A one-row-per-animal CSV is one row: the table
and sidecar the check makes from it are its companions, shown in the expanded
row, never as rows of their own **[C4]**.

| Column | Content |
|---|---|
| File | the name (monospace), the kind as a `Tag` ("Workbook", "Table", "BMDExpress project"), the size. A "set aside" `Tag` when a conflict decision excluded it **[Q10]** |
| What it is | `classification.say` ("Body Weight · the study's own measurements"). Below it, a status `Tag`: "Detected, not confirmed" (orange), "Confirmed by you" (green), "Changed by you" (blue; detected value in a tooltip), "Not checked yet" (grey), "Not recognised" (red), "File changed since you confirmed it" (orange) **[C3]**. A `classification.flags[]` entry shows as a warning icon with its `say`. The **Change…** link opens S2-M |
| Contents | from `tables[]`: sex ("Female"), number of doses, animals ("55 animals, 10 doses"). A `.bm2` shows its experiment count and species. Each missing fact is a `<Pending>`: "[sex pending]", "[contents not read: …]" |
| Units | `units.say`; `<Pending>` "[units pending]" when `units.state` is `missing` or `not_read`; nothing for a `.bm2` or gene-expression data |
| Problems | a `Badge` per group from the issues that name the file (must fix, worth a look); a click scrolls to the issue in S3 |
| (acts) | **Remove…** (S4), disabled with `acts.remove.say` when not allowed |

**The expanded row** (`expandable`), in `Descriptions`:
- what the file was made into (companions, with each one's `say`);
- the full contents per table: doses with animals per dose, sexes, measurements
  (the first five, then "and 12 more"), selection groups (core, biosampling),
  study number, species;
- a `.bm2`'s experiment names;
- **why the tool thinks so**: `classification.detected.say` ("From the file name",
  "From the experiment names inside the BMDExpress project");
- the person's statement, when there is one, with its time **[C3]**.

**Bulk confirm.** Above the table: **Confirm the N files as shown…** It opens a
`Modal` listing every file it will confirm, with its classification. Left out of
the list, and named under it with their reason, are the files that:
- are not recognised;
- carry a flag (`several_test_articles`, `name_says_gap_filled`);
- were changed since they were confirmed.

The person confirms those one by one in S2-M. The `Modal`'s button reads
"Confirm these N" and sends the list with the view's `files_token`; it refuses
with `files_changed` if the view changed meanwhile. **[maintainer]** Q-M2-4 asks
whether confirmation is required before integration.

**Empty study:** `Empty` "No files yet. Bring in the study's data files above."

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
  measurements, from the file name." and a link **Use what the tool detected**
  (it fills the fields; nothing is sent).
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

### S3 The check

A `Card` titled "The file check".

**Header line:** "Checked 12 Oct 2026, 11:37". When `check.current == false`, an
`Alert` (warning) says `check.why_not_current` ("2 files were brought in since",
"A file's classification changed since") **[C3]**. Never checked: "Not checked
yet."

**Check the files** (primary when it is `files.next`, else default) sends
`POST …/check`.
- It is a foreground wait: a `Modal` (not closable) with a `Spin`, the elapsed
  time and "Checking 15 files. A large BMDExpress project can take a minute the
  first time." The check took 0.2 s with its cache warm and 7.9 s cold with a
  40 MB `.bm2` [V]; the packages hold `.bm2` files up to 251 MB.
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
  3. **Expected for this kind of package** (collapsed, count). The same items,
     for example "No study workbook (.xlsx) for Hematology. Its tables are used as
     they are."
- **Not shown here:** when `check.not_shown` is present, one line: "8 checks of
  the analysis method are shown with the method, in Method and report
  definition", as a link to M5.
- **"What the report will be built from"**: a `Table` from `coverage[]` (served),
  one row per platform and data type:
  - columns: platform, data type (with `data_type_say`), workbook, tables, `.bm2`,
    and status (`level` as a `Tag`: ok, warn, block) with `say`;
  - file names link to their rows.

  The completeness message "Requires .bm2 for BMD/BMDL values" never appears:
  `say` comes from the backend's revised rule **[Q10, C6]**.

### S3-C Conflicts

Inside S3, above the issues, when `conflicts[]` is not empty: a `Card` per
conflict, titled "Conflict: Hormones, females".
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
- **What keeping does [Q10, recommended option C]:**
  - The other file is set aside: moved to the removed files, restorable (S4).
  - The button opens `<ConfirmAct>` with the backend's dry run: "It will set
    aside: hormones_truth_female_rerun.csv (and its units file and tables). It
    stays among the removed files and can be restored. Check the files again
    afterwards."
  - It sends `POST …/conflicts/{id}/keep` **[C8]**.
- **After it:** the conflict leaves the list (the check is now out of date, which
  is derived), and the next step is "Check the files". A decision is undone by
  restoring the set-aside file, which brings the conflict back at the next check.

### S4 Remove, restore, start over

**Remove a file** (the row's **Remove…**). Always through `<ConfirmAct>` with the
backend's dry run (`GET …/dry-run/remove_file?file=…`) **[C8]**:
- *Study not checked yet:* strength `reversible`. The file is removed at once, and
  a `message` with **Undo** follows ("body_weight_truth_female.csv removed.
  Undo").
- *Study checked or combined:* strength `costly`. The dialog lists what goes:
  - "the file and its companions (its units file, the table made from it, its
    sidecar)";
  - "the result of the last file check";
  - "the combined dataset, the data review, the stored results of processing"
    (when present);
  - the approvals lost;
  - what is kept;
  - the cost.

  **Remove** sends `POST …/files/{name}/remove` with the `preview_token`.

**Removed files.** A `Collapse` panel "Removed files (3)" under the table, from
`removed[]` (served) **[C8]**:
- each entry has its files, when and why it was removed ("Removed by you", "Set
  aside when you kept hormones_truth_female.csv", "Replaced by a newer
  body_weight_truth_female.csv");
- **Restore…** goes through `<ConfirmAct>` with the restore's dry run (adding a
  file back changes the files, so it costs the same as bringing it in);
- it is disabled, with the reason, when a file of that name is in the study now:
  "A file named body_weight_truth_female.csv is in the study now. Remove it
  first."

**Start the files over.** A `Card` at the bottom with a red border, "Start the
files over": "Removes every data file and everything made from them. What people
stated (the design, the authors, the pins) and the Background are kept."
- **Start over…** (danger) opens `<ConfirmAct strength="irreversible">` with the
  reset's dry run (`GET …/dry-run/reset_files`) **[C8]**:
  - what will be deleted, including the removed files, since they can't be
    restored afterwards;
  - the approvals lost;
  - what is kept, with the line "These stay and will apply again to the next files
    you bring in: the study design, the experiment details, the method and the
    report definition."
- The person types the study id, as in M1.
- It sends `POST …/files/reset` with the typed id and the `preview_token`.
- Deleting the whole study is not here; it is M1's.

---

## 4. Inputs and their validation (before anything runs)

**In the browser, as files are chosen (Step A).** The rules come from the served
`files.limits` (the accepted endings and the size limit) and the files view
(names already in the study). Nothing is sent until every row passes or is
dropped. Rules in the order checked; the first failing one is shown:

| # | Rule | Message |
|---|---|---|
| 1 | Not empty (size > 0) | "This file is empty." |
| 2 | Size ≤ `limits.max_file_bytes` (proposed 512 MB **[maintainer]** Q-M2-8) | "This file is 612 MB; the limit is 512 MB." |
| 3 | The name is a plain name: no leading `.`, no `/` or `\`, no control characters, at most 200 characters | "This file name can't be used: it starts with a dot." |
| 4 | Ending is `.bm2`, `.csv`, `.txt`, `.xlsx`, `.zip`, or `.units.json` (case-insensitive) | "A .pdf is not a data file. The study's data comes as .bm2, .csv, .txt, .xlsx, or a .zip of these." `.docx`, `.pdf` and every other `.json` are refused this way |
| 5 | Not `*.sidecar.json` | "This is a file the application writes itself (a sidecar). Bring in the table it belongs to instead." |
| 6 | No two chosen files share a name | "Two of the chosen files are named body_weight_truth_male.csv. Keep one." |
| 7 | A `.units.json` has a table of the same stem among the chosen files, or an unchecked one in the study | "This units file has no table: there is no body_weight_truth_female.csv. Bring them in together." |
| 8 | A name already in the study | not refused; marked "Needs your answer: replaces a file already in the study" (answered in the plan) |

**On the server, before the files join the study (Step B; contract §2.2).** These
rules need the content; each failure is a `refused` row with its `say`:

| Rule | Code | `say` |
|---|---|---|
| The content matches the ending. A `.bm2` begins with BMDExpress's saved-project signature (`AC ED 00 05`); an `.xlsx` or `.zip` is a zip archive; a `.csv`/`.txt` is text [V: real files' first bytes] | `content_mismatch` | "hormones_male_table.bm2 is named .bm2 but is a text table, not a BMDExpress project. Rename it to .txt if it is a table." |
| A `.zip` opens, has no zip inside it, and no two entries share a name in different folders | `zip_invalid`, `zip_nested`, `zip_name_clash` | "The zip holds two files named body_weight_truth_male.csv (in a/ and b/). Only one could be kept, and the tool can't know which. Neither is brought in; unzip it and choose." |
| Not an identical copy (same content) of a file in the study or in the batch | `same_content` | "This file is an exact copy of body_weight_truth_female.csv, which is already in the study. It would be counted twice." |
| A `.units.json` is a JSON object of text to text, and its keys are columns of its table | `units_invalid` | "The units file isn't a list of measurement → unit." / "It names 'Albumen', which is not a column of clin_chem_truth_female.csv." (columns of the table without a unit are listed as a warning in the row) |
| A `.units.json` for a table already converted by a check | `units_for_converted_file` | "body_weight_truth_female.csv has already been checked without units. Bring the .csv in again together with its units file; it will replace the old one." |
| Staging and commit match: the batch exists, its plan is unchanged, and the study is unchanged since | `staging_expired`, `changed_since_preview` | §6 |

**Classification (S2-M):** platform and data type are only ever chosen from the
served lists. The backend checks them again against `bmdx_pipe.VOCABULARIES` and
the allowed pairs (`classification_not_allowed`, §6) **[C3]**.

**Typed id for "Start over":** equal to the study id, case-sensitive, spaces at
either end ignored (as M1).

**Conflict choice:** one of the conflict's own files; nothing is chosen by default.

---

## 5. Actions and what they map to

| Act | Legal action (C1) | Endpoint (contract) | Core | When not allowed, the person sees |
|---|---|---|---|---|
| Read the page | – | `GET …/files` | NEW `workflow.files.files_view` | – |
| Stage a batch | ADD_FILES | `POST …/files/staging` | NEW `pipeline.intake.stage_batch` | the act's `say` |
| Bring in the batch | ADD_FILES | `POST …/files/staging/{batch}/commit` | NEW `workflow.steps.add_files_step` | the act's `say`; refusals §6 |
| Discard a batch | – | `DELETE …/files/staging/{batch}` | `pipeline.intake.discard_batch` | – |
| Check the files | VALIDATE | `POST …/check` | `workflow.steps.validate_step` | "Bring in the study's files first." |
| Say what a file is | CONFIRM_CLASSIFICATION | `PUT …/files/{name}/classification` | CHANGED `confirm_metadata_step` **[C3]** | "Run the file check first: it says what each file is." |
| Confirm several as shown | CONFIRM_CLASSIFICATION | `POST …/files/classification/confirm` | same | same |
| Back to the detected value | CONFIRM_CLASSIFICATION | `DELETE …/files/{name}/classification` | same | same |
| Keep one file of a conflict | RESOLVE | `POST …/conflicts/{id}/keep` | CHANGED `resolve_step` **[Q10, C3, C8]** | "Run the file check first: conflicts are found by the check." |
| Remove a file | REMOVE_FILE | `GET …/dry-run/remove_file`, `POST …/files/{name}/remove` | CHANGED `pipeline.pool_state.remove_pool_file` **[C8]** | "This study has no files to remove." |
| Restore a removed file | ADD_FILES | `GET …/dry-run/restore_file`, `POST …/removed/{rid}/restore` | NEW `workflow.steps.restore_file_step` **[C8]** | the name-taken reason |
| Start the files over | RESET | `GET …/dry-run/reset_files`, `POST …/files/reset` | NEW `workflow.steps.reset_files_step` (logic moved from `session_routes.py:1496-1631`) **[C8]** | "This study has no files to remove." |

Every act's button reads `files.acts.<act>`, never the phase. A refusal from the
backend still comes back as the §4.2 envelope and is shown with `<Refusal>`.

**Issue groups** (served as `issue.group`; the rule lives in the backend, next to
the plain words):

| Issue type (severity) | Group | Plain words (served `say`), example from real reports |
|---|---|---|
| `unassigned_file` (error) | must fix | "The tool can't tell what lab_notes.txt is, from its name or its content." To do: "Say what it is … or remove it if it isn't study data." |
| `dose_mismatch` (error) | must fix, and a conflict | as S3-C |
| `animal_count_mismatch` (error) | must fix, and a conflict | "Hematology: the tables have 95 animals but the workbook only 90: 5 animals are not in the study workbook." |
| `value_*` (error) | must fix | "Body Weight: 1 of 243 values in the tables differ from the study workbook (for example animal 111, SD0, Body Weight: workbook 215.9, table 251.9). A table must be an exact copy of the workbook's data." [V] |
| `redundant_files` (info today) | must fix, and a conflict **[Q10 b]** | "body_weight_truth_female_copy.txt and body_weight_truth_female.csv hold the same data … Both would be combined, so it would count twice." [V] |
| `unverified_derived_data` (warning) | worth a look | "Body Weight: there is no study workbook (.xlsx) to check the tables' values against, so they are used as given, unverified." |
| `sex_mismatch` (warning) | worth a look | the files' sexes, plainly |
| `animal_count_mismatch` (warning) | worth a look; feeds M6 | "Body Weight: the workbook has 122 animals and the tables 110, so 12 … are not in the tables. The data review accounts for each one." [V] |
| `missing_tier` "no txt/csv" (warning; workbook only) | worth a look | as served; the coverage row warns too (§8) |
| `roster_subset` (info) | expected; feeds M6 | "6 of the 61 female animals in the study's roster are not in body_weight_truth_female.csv, for example 544, 545 …" [V] |
| `missing_tier` "no .bm2" / "no xlsx" / gene expression | expected | "No BMDExpress project (.bm2) for Body Weight. Process computes its benchmark doses itself." |
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
| `file_too_large` | 413 | "{name} is {size}; the limit is {limit}." |
| `name_invalid` | 400 | "This file name can't be used: {why}." (today: "Not a pool file name: …") |
| `duplicate_name_in_batch` | 400 | "Two files in this batch are named {name}. Keep one." |
| `content_mismatch` | 400 | as §4 |
| `zip_invalid` | 400 | "This .zip can't be opened; it may be damaged or only partly downloaded." (today: "The uploaded file is not a valid .zip archive") |
| `zip_nested` | 400 | "This .zip holds another .zip. Unzip the inner one and bring its files in." |
| `zip_name_clash` | 400 | as §4 |
| `same_content` | 409 | as §4 |
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
| `no_files` (existing) | 404 | existing text |
| `damaged_session_file` (existing) | 422 | existing text (none) |

## 7. Destructive and costly acts

| Act | Strength (from the dry run) | Confirm | Undo |
|---|---|---|---|
| Bring in files, study never checked | – | the plan (§3 S1) | remove the file (reversible, to the removed files) |
| Bring in files, study checked or combined | costly | the plan, then `<ConfirmAct>` listing what goes (NIEHS-10's real list: contract §4.6) | none for what was deleted; the files can be removed again |
| Replace a same-name file | part of the plan | **Replace it** ticked per row | the old file is among the removed files, restorable **[C8]** |
| Remove a file, never checked | reversible | none | **Undo** in the message (= restore) |
| Remove a file, checked or combined | costly | `<ConfirmAct>` | restore (itself costly) |
| Restore a removed file | as bringing it in | `<ConfirmAct>` | remove again |
| Keep one file of a conflict | costly or reversible, as remove **[Q10 C]** | `<ConfirmAct>` | restore the set-aside file |
| Confirm or correct a classification | reversible; costly once combined | in S2-M | **Undo** (previous statement) |
| Check the files | none | – | – (never deletes the dataset, C1 D4) |
| Start the files over | irreversible | `<ConfirmAct>`, type the id | none |

Every consequence list comes from the backend's dry run; the front-end keeps no
list of its own **[C8]**. Every act carries the dry run's `preview_token`, and the
backend refuses with `changed_since_preview` when the study changed in between (M1
R4).

## 8. Missing facts and inferences, shown

- **Units:**
  - a table brought in without its units file: `<Pending>` "[units pending]" in
    the row, and the plan's `units_missing` answer recorded with it;
  - a workbook: "[units pending]: the workbook states them in its Key sheet, but
    they are not read from a workbook yet" [V: `xlsx_to_pivot_txt` records no
    units] (**[maintainer]** Q-M2-7).
- **Sex:** a table whose sex is not detected: "[sex pending]". [V: a
  one-row-per-animal `Organ_Weights_M.csv` was made into `Organ_Weights_M.txt` with
  no sex.]
- **A `.bm2` whose contents were not read:** "[contents not read: its doses and
  animals were not compared with the other files]". [V: the 2026 PFHxSAm package's
  six `.bm2` files, on a cold cache; `fingerprint_bm2` skips the read when the
  name already classifies the file, `file_integrator.py:1444`.]
- **Not recognised:** "[what this file is: pending]".
- **Every classification is shown as detected until a person confirms it.** The
  tag and the "why" line (file name, or the project's experiment names) are the
  inference flag. Nothing passes as confirmed by default.
- **Flags on inferences** (served `classification.flags`):
  - `name_says_gap_filled`: a one-row-per-animal file named without `_truth` or
    `_tox_study` was taken as gap-filled data. [V: `body_weight_female.csv` →
    Body Weight · inferred.] The row says: "This file has one row per animal,
    like the study's own measurements, but its name doesn't say so, so it was
    taken as gap-filled data. Check its data type." **[maintainer]** Q-M2-6;
  - `several_test_articles`: a `.bm2` with experiments of several test articles,
    read from the experiment names (an inference, said as such). [V: NIEHS-10's
    CEBS project holds PFHxSAm, 6-1 FTOH, 10-2 FTOH and 2,3-Benzofluorene.
    Integration combined all 16 experiments into one dataset.] **[maintainer]**
    Q-M2-5.
- **Coverage warns when a platform has only its workbook.** [V: integrating
  NIEHS-10's CEBS workbooks alone produced no male Clinical Chemistry, no
  Hematology and no Organ Weight experiments (5 of 12 apical experiments missing)
  with no error and no log warning. The cause was not investigated; it is
  reported to the orchestrator for M3 and the core track.] The coverage row says:
  "Only the study workbook … bring in the tables made from it too."

## 9. Waits

- **Upload** (Step B): a per-file `Progress` in the page. Foreground; the page
  warns on leaving.
- **The check:** a blocking `Modal` with `Spin` and elapsed time. It is one call,
  with no stream. **[request R-M2-7]** asks for the kit's short-wait form (a
  `<Wait>` that takes a promise), so the look is shared.
- Everything else (the plan's commit, classification, remove, restore, reset)
  takes about a second or less; its button shows a loading state. The commit of a
  batch into a combined study deletes many files: still under a second [R].
- Nothing runs in the background.

---

## 10. What M2 needs from C3, C4 and C8 (precisely)

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
4. `content_hash` per file, so a same-name replacement is recognised and a
   statement about the old content is marked "changed since you confirmed it".

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
5. **[Q10 B only]** Conflict decisions keyed by the compound key and file names,
   honoured by validation (the error clears) and by integration (finding 3). Under
   option C, decisions are removals and `precedence.json` retires.
6. The confirmation is recorded per file: who stated it (`person`) and when.
7. Classifications are offered per kind of file (served `classification_choices`).

**C8: dry runs of destructive acts; restore**
1. A dry run (§4.3 object + `preview_token`) for each act:
   - `add_files` (inside the staging plan);
   - `remove_file`;
   - `restore_file`;
   - `keep` (a conflict decision);
   - `classify` (when combined);
   - `reset_files`.

   Each is computed by the same code that does the act. The approvals lost come
   from the section files and from `animal_report.json`.
2. Every act takes the `preview_token` and refuses `changed_since_preview`.
3. Removal moves **every** companion, the `.units.json` included [V: today it is
   left in `_originals/`]. It records why and when in `_removed/<stamp>/removed.json`.
4. Restore from `_removed/`; refuse when the name is taken.
5. A same-name replacement moves the old file to `_removed/` (today: overwritten,
   `upload_routes.py:115-118` [R]).
6. Invalidation archives the data approval (as C1 D5 does at integration), rather
   than deleting it.
7. The pool reset moves into a core step with its dry run. It lists the removed
   files it deletes.
8. The staging area (`sessions/<id>/_incoming/<batch>/`): outside `files/`, so no
   phase changes; expires after 1 hour; never scanned by fingerprinting.

**Also needed (not in C3/C4/C8; requests to the core track):**
- conversion of one-row-per-animal CSVs at the check, not at upload, so a units
  file is paired whatever the order (as `generate_report.import_files` already
  behaves [R]);
- `redundant_files` blocking (Q10 b);
- the completeness rule for apical platforms (Q10 c);
- every `.bm2` read at the check (§8);
- workbook units read from the Key sheet (`bmdx_pipe.key_sheet_units` exists [R]);
- the workbook-only integration loss (§8) investigated.

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
  (`shell/nextStep.ts`), so the two never disagree.

## 11. Open questions for the maintainer

- **Q-M2-1 (Q10 a). Should choosing a file clear a conflict error?** Today it
  clears nothing, and for apical platforms it has no effect at all (finding 3).
  - **A.** No. A choice never clears an error; the person must remove or fix a
    file. Choosing is then only for warnings.
  - **B.** Yes, as a recorded decision. The other file stays in the list marked
    "set aside"; the check treats the conflict as settled; integration uses only
    the kept file. Needs C3 item 5 and changes in `validate_pool` and
    `integrate_pool`.
  - **C. (recommended)** Keeping one file sets the other aside, by moving it to
    the removed files (restorable, with the reason recorded). The error clears
    because the file is gone. The check and the dataset see exactly the files
    listed, there is no hidden decision state, and `precedence.json` retires.
    Cost: a set-aside file is no longer "in" the study, which is the point.
- **Q-M2-2 (Q10 b). Redundant files** (both are combined today, so the data counts
  twice) [V on a copy].
  - **A.** Leave them as information (today).
  - **B. (recommended)** A blocking conflict, settled as Q-M2-1. Exact copies are
    already refused at intake (`same_content`).
  - **C.** Drop the duplicate automatically. Rejected: silent.
- **Q-M2-3 (Q10 c). Is a `.bm2` still required for apical platforms?**
  - **A. (recommended)** No. The completeness rule (`workflow/phases.py:239-243`)
    and its message change: Process computes the apical benchmark doses, and
    NIEHS-10 builds without one.
  - **B.** Keep it as a warning.
  - **C.** Keep it as it is.

  Under A the coverage row says "Process computes its benchmark doses."
- **Q-M2-4. Must every file be confirmed before integration?** Proposed: yes.
  Integration refuses `classification_unconfirmed` (a C1/C3 guard), and the bulk
  confirm (§3 S2) keeps it quick except for flagged files.
- **Q-M2-5. A `.bm2` holding several test articles** (NIEHS-07 … 10's shared
  project).
  - **A. (recommended)** A blocking issue, with an act "Keep only this study's
    experiments" that runs `bmdx_pipe.subset_bm2` (it exists) and replaces the
    file. The test article token is chosen by the person from the experiment
    names.
  - **B.** A warning only.

  Until decided: the warning flag.
- **Q-M2-6. Classify one-row-per-animal files by content, not by name** (ADR-0017)?
  Recommended: yes, "the study's own measurements" when the file has one row per
  animal with `Animal ID`/`Sex`. Until then: the flag.
- **Q-M2-7. Units.**
  - (a) A one-row-per-animal CSV without a units file: allow it with the explicit
    acknowledgment and "[units pending]" (recommended; a person's own data may
    have none), or refuse it?
  - (b) Read a workbook's units from its Key sheet (recommended)?
- **Q-M2-8. The size limit per file.** Proposed 512 MB (the largest published
  `.bm2` is 251 MB [V]).
- **Q-M2-9. An exact copy under another name: refuse it** (recommended)?
- **Q-M2-10. A same-name replacement keeps the old file among the removed files**
  (recommended)?
- **Q-M2-11. Removed files after "Start over".** Proposed: deleted with the rest,
  and the dialog says so.

## 12. Acceptance criteria

Tested in a headed browser against the app on a **scratch store**, with
`SESSIONS_DIR`, `OUTPUT_DIR` and `BM2_CACHE_DIR` in the tester's scratch
directory. The test files are in `/workspace/ui-team/_scratch/design-m2/testdata/`:
- T1: NIEHS-10's inputs, 27 files;
- T2: the 2026 PFHxSAm package, 21 files;
- T3: NIEHS-10's CEBS workbooks and the shared `.bm2`;
- T4: conflicts;
- T5: a value mismatch;
- T6: wrong files.

Each study is created first in M1, for example `DTXSID9000001` … `DTXSID9000006`
(created as other sessions). "A copy of NIEHS-10" means `sessions/DTXSID50469320`
copied into the scratch store. A criterion marked [C3], [C4], [C8] or [Q10] is
tested against the mocks until that holds.

**Reaching the page**
1. `/app/studies/DTXSID50469320_published/files` shows "This is the published
   book's own content. It takes no data files." and no control.
2. On a new, empty study, the page shows "No files yet", the next step "Bring in
   the study's files", and Check, Remove and Start over disabled, each with its
   reason on hover.

**Bringing in: in the browser**
3. Choosing every file of T6 lists them before anything is sent. The `.pdf`, the
   `.docx` and `body_weight_truth_female.sidecar.json` are refused with plain
   reasons; `empty.csv` says "This file is empty." **Send to the server for
   checking** stays disabled until the refused rows are removed from the list.
4. Choosing T1's `body_weight_truth_female.units.json` alone is refused: "This
   units file has no table …".
5. Choosing two files of the same name (from two folders) is refused before
   sending.

**Bringing in: on the server**
6. Sending `hormones_male_table.bm2` (T6) gives "… is named .bm2 but is a text
   table …", and it is not added.
7. Sending `two_same_names.zip` (T6) refuses both entries with the "two files
   named body_weight_truth_male.csv (in a/ and b/)" message. Nothing is added.
8. Sending T6's `tissue_conc_truth_female.csv` without its units file marks it
   "Needs your answer". **Bring in** stays disabled until **Bring it in without
   units** is ticked. Afterwards its row shows "[units pending]".
9. Sending all of T1 shows 27 rows: 13 tables with their units files paired
   ("Units for …"), 2 clinical-observation tables, and 1 `.bm2`. **Bring in 27
   files** adds them. The table then has **15 rows**, each `.units.json` shown in
   its table's expanded row, never as a row of its own [C4].
10. **Discard** after the server's plan leaves the study unchanged (the files
    table is as before, and the phase is unchanged).
11. A plan left open for over an hour, then committed, says "These files were
    waiting too long … Nothing was brought in." [C8]
12. Bringing in T1's `body_weight_truth_female.csv` again, unchanged, is refused
    as an exact copy [Q-M2-9]. With one value edited, it is marked "Replaces …"
    with both sizes and dates. Without **Replace it** ticked it is not added. With
    it ticked, the new file is in and the old one is among the removed files
    [C8].
13. On a copy of NIEHS-10 (APPROVED), bringing in any file first shows what will
    be deleted. The list includes the file check, the combined dataset, the data
    review and the stored processing results, says the Summary will be marked out
    of date, and gives the cost. **Cancel** changes nothing [C8].

**Checking**
14. On the T1 study, **Check the files** shows a blocking wait with elapsed time,
    then: "Nothing blocks. 7 points are worth a look; 25 are expected for this
    kind of package." Every issue names files by their names; no id like
    `9a196bfd-…` or `scan-…` appears anywhere.
15. The "Expected" panel is collapsed. It holds the ten "… animals in the study's
    roster are not in …" items, each saying the data review accounts for them.
16. On a copy of NIEHS-10, the page says the analysis-method checks are shown in
    Method and report definition, with a link. No method message appears in the
    issue lists.
17. The coverage table of the T1 study shows 8 rows (gene expression and 7
    platforms), each "ok". The words "Requires .bm2" appear nowhere [Q10 c].
18. On a copy of NIEHS-10, checking again leaves the phase APPROVED and the
    combined dataset in place. The tooltip of **Check the files** says checking
    never deletes it.
19. The T5 study's check shows under "Must fix": "Body Weight: 1 of 243 values …
    animal 111, SD0 … workbook 215.9, table 251.9 …". **Combine** is not offered
    anywhere on the page.
20. The T3 study's check gives no "Must fix". The `.bm2` row carries the warning
    "This BMDExpress project holds experiments of 4 test articles (10-2 FTOH,
    2,3-Benzofluorene, 6-1 FTOH, PFHxSAm) …". The coverage rows of the workbook-only
    platforms warn "Only the study workbook …". The workbooks show "[units
    pending]".
21. The T2 study's six `.bm2` rows show "[contents not read …]" when their
    contents were not read, and never show empty doses as if they were data.

**Saying what each file is**
22. Every checked row shows "Detected, not confirmed" and, in its expanded row,
    why ("From the file name" or "From the experiment names inside the BMDExpress
    project").
23. In "What is this file?", a table offers three data types, each with its
    explanation; a workbook offers one; a `.bm2` offers two. The platform list
    holds only the platforms offered for the chosen data type, with no free-text
    entry. Choosing gene expression hides the platform.
24. Correcting `hematology_truth_male.csv` to Hormones, then checking again,
    keeps "Changed by you: Hormones". The correction survives a server restart
    [C3].
25. After a correction, the Check step says the check is out of date because a
    file's classification changed [C3].
26. **Use what the tool detected** fills the detected values. **Undo** after
    saving restores the previous statement.
27. On a copy of NIEHS-10, correcting a file first shows that the dataset must be
    combined and processed again. After saving, the page says the files changed
    since they were combined (integration out of date) [C3].
28. **Confirm the N files as shown…** lists exactly the files it will confirm, and
    leaves out the flagged and unrecognised ones, naming them. After confirming,
    those rows read "Confirmed by you".
29. In a T6 study, `Organ_Weights_M.csv` carries the "one row per animal … taken as
    gap-filled data" flag and "[sex pending]". It is left out of the bulk confirm.
30. With the files table open in two tabs, removing a file in one and then bulk
    confirming in the other says "The files changed while this list was open.
    Nothing was confirmed."

**Conflicts**
31. The T4 study's check shows two conflicts under "Must fix", one for Hormones
    (females: doses 1.4 vs 2) and one for Body Weight (a copy). Each shows the two
    files side by side, with the differing rows highlighted.
32. No file is preselected. **Keep this file** is disabled until one is chosen. The
    check's suggestion, when shown, says it does not know which is right.
33. Keeping `hormones_truth_female.csv` shows what will be set aside (the rerun
    file and its units file and tables) and that it can be restored. After it,
    the conflict is gone, the rerun file is among the removed files, and the next
    step is "Check the files". Checking again clears the dose error [Q10 C, C8].
34. Restoring the set-aside file brings the conflict back at the next check [C8].
35. The redundant body-weight copy blocks combining until settled [Q10 b].

**Removing, restoring, starting over**
36. On an unchecked study, **Remove…** removes the file at once with an **Undo**.
    **Undo** brings it back, its units file included [C8].
37. On a checked study, **Remove…** first lists what goes (the file, its units
    file, its table and sidecar, the check). **Cancel** changes nothing.
    **Remove** moves it to "Removed files", with when and why [C8].
38. **Restore…** is disabled, with the reason, while a file of the same name is
    in the study.
39. On a copy of NIEHS-10, **Start over…** lists:
    - what goes: the files, the converted originals, the combined dataset, the data
      review, the result sections, the Summary, the stored processing results;
    - what stays: the identity, the study design, the authors, the method pin,
      the deposit record, the Background, the history;
    - the line that the stated facts will apply again to the next files.

    **Start over for good** stays disabled until `DTXSID50469320` is typed exactly
    [C8].
40. After **Start over**, the page shows "No files yet", the phase is EMPTY, and
    the study is still in the studies list.
41. Changing the files in another tab while a removal or "Start over" dialog is
    open, then confirming, says the files changed after review. Nothing is done
    [C8].

**Everywhere**
42. Every refusal shows plain words and a "Details" toggle with the backend's own
    message. No file id and no internal key (`Body Weight|tox_study`,
    `issue_index`) is shown outside "Details".
43. While Process runs on the study (another tab), every M2 act is disabled with
    "Process is running on this study since …" [C5].
44. Reloading the page at any point shows the same state. The browser stores
    nothing; a reload during an upload loses the staged batch and nothing in the
    study.
45. The word "wizard" appears nowhere on M2's screens.
