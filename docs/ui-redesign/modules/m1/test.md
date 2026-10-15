M1 Studies: adversarial test, 2026-10-15. Tester: ui-adversarial-tester.
Build: worktree `/workspace/ui-team/m1-test` (branch `ui-m1-test` = `ui-redesign` @ 623f003), `ui/` built with `npm ci && npm run build`, served by `./run-server.sh --port 9531 --host 127.0.0.1` with `SESSIONS_DIR`, `OUTPUT_DIR`, `BM2_CACHE_DIR` in `/workspace/ui-team/_scratch/m1-test/`. Real backend, no mocks. Headed Chromium (Playwright 1.50, `browse`). Scripts: `tests/ui/m1/t_*.py`. Screenshots: `/workspace/ui-team/_scratch/m1-test/shots/`.

Store: the 13-session demo copy. For criteria 1, 6 and 33, stand-ins were added: `DTXSID50469320_nb` (a copy of the Triclosan session, renamed), `DTXSID_TEST` (empty `meta.json`), `_prompts/`, and `DTXSID8031865` (no identity). PubChem was reachable from the sandbox.

## Acceptance criteria

| # | Result | Evidence |
|---|---|---|
| 1 | pass (demo store) | One top-level row per chemical, plus "Sessions not tied to a chemical" holding `DTXSID_TEST`; `_prompts` appears nowhere. Not run on the 14-chemical store of 2026-10-14. `s1_list_initial.png`, `s1_list_expanded.png` |
| 2 | pass | First row in 0.46 s |
| 3 | pass | The "where it stands" text of all 15 sessions is the same in the list and on the page (`s3_<id>.png`) |
| 4 | pass | The 1,4-Dichlorobenzene row reads "Report over 2 studies", "NIEHS-13 · 2026 Apr", "A report over 2 studies". Expanded: rat, mouse, published content, each with its own stands and next step |
| 5 | pass | Published-content and report rows show no phase and no "No files yet" |
| 6 | pass (stand-in) | `_nb` is listed as "Other session". Its page banner: "…uses the format NIEHS Report, 2026; a study under DTXSID50469320 would use NIEHS-10's format." `s3_DTXSID50469320_nb.png` |
| 7 | pass | "On the Bookshelf (draft)" → `/Bookshelf/DTXSID50469320`, `target=_blank`. The rat cell reads "Part of DTXSID1020431's book" |
| 8 | pass | "41997-13-1" leaves only Perfluorohexanesulfonamide. "DTXSID1020431_rat" leaves the DCB group expanded, rat visible. Clearing brings back 9/9 rows. `s1_search_*.png` |
| 9 | pass | 0 delete controls in the list |
| 10 | pass | Empty store: "No studies yet" with **New study**. `s1_empty_store.png` |
| 11 | pass | Each "Next:" link goes to `/app/studies/<id>/<module>`: files, dataset, review |
| 12 | pass | `dtxsid7020182` typed shows `DTXSID7020182`, upper-cased as typed |
| 13 | pass | "Character 14 is the letter O…"; Next disabled |
| 14 | pass | Suffix message; Next disabled |
| 15 | pass | "A DTXSID starts with 'DTXSID'…"; Next disabled |
| 16 | pass | Pasting the CompTox address offers "Use DTXSID7020182?". The field keeps the URL until the click; the click fills it. `s2_paste_offer.png` |
| 17 | pass | "A study of this chemical already exists: DTXSID50469320, Perfluorohexanesulfonamide." **Open it** opens the page; Next disabled; store unchanged. `s2_exists.png` |
| 18 | pass | Spinner "Looking up…" seen. Then Bisphenol A, 80-05-7, C15H16O2, structure image loaded, CID link to pubchem 6623, source line naming PubChem. `s2_lookup_wait.png`, `s2_step2_bpa.png` |
| 19 | pass | Info-style alert, 2026 format, "no published report is on file" |
| 20 | pass | Store without `DTXSID50469320`: warning-style notice naming NIEHS-10 and March 2023, listing organs/endpoints, deposit captions and DOI, Appendix A. The checkbox label names the format. `s2_pfhxsam_step2.png` |
| 21 | pass | **Create study** disabled until the tick |
| 22 | pass | `DTXSID0000000001`: "PubChem has no chemical…" with **Back to the id**. No name, no "Test Article", no Create button. `s2_not_found.png` |
| 23 | pass | Lookup refused (proxy to a closed port): message after 0.8 s. Lookup hanging (proxy that never answers): message after 15.9 s ("could not be reached. Nothing was created. Try again in a minute."), with **Try again**. Store unchanged. `s2_unreachable_refused.png`, `s2_unreachable_slow.png` |
| 24 | pass | Back keeps the id; reload returns to an empty step 1; store unchanged |
| 25 | pass | Success page shows id, name, CASRN, format and "Bring in the study's files". The list row says "No files yet". The page says "Confirmed by a person from a PubChem lookup on 15 Oct 2026". `s2_created_bpa.png`, `s3_new_bpa.png` |
| 26 | pass | Second tab: "The study was not created / A study of this chemical already exists (DTXSID0020232). Open it instead." with **Open it**; one folder. `s2_second_tab_create.png` |
| 27 | pass | Identity, "Data reviewed" + next button, "NIEHS Report, as published in March 2023" (the study's own definition), pin state, link to pins, Bookshelf link, related `_published` and `_nb`. `s3_pfhxsam.png` |
| 28 | pass | Read-only banner, links to the Bookshelf and to the generated study; no next-step button; delete disabled with the reason. `s3_published.png` |
| 29 | pass | Names report DTXSID1020431 and the mouse sibling, with links; delete disabled with "…would break that report." `s3_rat.png` |
| 30 | pass | Members table lists rat and mouse, each with its own stands and Open. `s3_report.png` |
| 31 | pass | "[short name pending]" popover: "Fill it in: Study facts" → `/app/studies/<id>/facts`. `s3_short_name_popover.png` |
| 32 | pass | Absent id: "There is no study DTXSID7020182…" with **Create a study of this chemical** (prefills S2). `foo`: "'foo' is not a study id." No folder created. `s5_absent.png`, `s5_foo.png` |
| 33 | pass | `DTXSID_TEST`: "[name pending]" and "can't be looked up from here: this session's id names no chemical". `DTXSID8031865`: **Look up the chemical** → modal; Save disabled until ticked; saved PFOA / 335-67-1, button gone. Not offered when an identity exists. `s3_lookup_modal.png`, `s3_lookup_done.png` |
| 34 | partial fail | Lists what goes, approvals lost by name (6 on DTXSID6024701), what stays (output/, templates/studies/, companion, members, others). On Triclosan: no "What stays" list at all, and a section named "unknown" (F5). `s4_dialog*.png` |
| 35 | pass | Disabled for `''`, `dtxsid5032498`, `DTXSID503249`, `DTXSID50324988`, `DTXSID5032498_`. Enabled for the exact id, with spaces or a tab around it |
| 36 | pass | Cancel and Escape close the dialog; nothing deleted |
| 37 | pass | Returns to the list with the toast "DTXSID5032498 was deleted."; gone from the list and from `/Bookshelf`. `s4_after_delete.png` |
| 38 | **fail** | During a real Process, the page shows no "Process is running" and Delete is enabled; the delete succeeded (F1) |
| 39 | pass | A file added after the preview: "The study changed while this was open…" with the reloaded list and the typed id cleared; nothing deleted. A touch that only changed the time is refused too. `s4_changed_since_preview.png` |
| 40 | pass (on reload) | The other tab, reloaded: "There is no study DTXSID5032498. It may have been deleted." See F8 for the wording. `s5_deleted_other_tab.png` |
| 41 | pass | Every refusal seen shows plain words and "Show the technical details". "wizard" appears on no M1 screen |

## Findings, by severity

### F1. Blocker: a study can be deleted while Process runs on it, and Process then rebuilds part of the folder
Steps:
1. `POST /api/process-integrated/DTXSID4028880` (scratch copy, caches removed so it runs about 60 s).
2. Within 4 s, open `/app/studies/DTXSID4028880`. **Delete this study…**, type the id, **Delete for good**.

Expected: Delete disabled with "Process is running on this study since …" (spec §3 S3, criterion 38); the preview and the delete refused with `run_in_flight`.

Actual:
- No run text, Delete enabled. `delete-preview` answered 200 throughout the run, and `actions.delete.allowed` stayed true.
- The delete succeeded. Process went on and finished with 200 after 64 s, writing `_cache_*`, `session.duckdb`, `session_parquet/`, `references.json` and `.prepare_content.*` into a new `sessions/DTXSID4028880/`.
- The study is back in the list as a "Study", "No files yet", "[name pending]", "[CASRN pending]", deletable. Its creation check says it exists, so it can't be recreated cleanly.
- Cause: `workflow/studies.py:626` `running_since()` always returns None (waits on C5).

Screenshots: `s3_midrun.png`, `s4_midrun_dialog.png`, `s4_midrun_after.png`.

### F2. Blocker (outside M1's routes, reachable on the same server): the legacy reset route deletes what M1 refuses to delete
Steps: `curl -X POST http://127.0.0.1:9531/api/session/reset/DTXSID1020431_rat`, then the same for `/api/session/reset/DTXSID50469320_published`.

Expected: refused, as by `POST /api/v2/studies/{id}/delete` (`member_of_report`, `read_only_session`).

Actual: `{"ok":true}` 200, and both folders are gone. No preview, no typed id, no guard. Any other client of the old API, or a stale page, can still do it. Screenshot: none (API only).

### F3. Major: double-clicking "Delete for good" gives one server error (500) among the requests
Steps: open the delete dialog of DTXSID5032498, type the id, double-click **Delete for good**.

Expected: one delete; the second request refused cleanly or never sent.

Actual:
- Server log shows the delete POST three times: 409, 500, 200. The 500 was `FileNotFoundError …/DTXSID5032498/narrative_runs/summary/r…json`: the dry run walking a folder another request was removing.
- The end state was right (deleted, toast shown), and in this run the 500 did not reach the screen.
- Under other timing the person may see an unexpected-error refusal for a delete that did happen.

Screenshot: `s4_after_delete.png`.

### F4. Major: simultaneous "Save this identity" gives a server error (500) and two successes
Steps:
1. A session whose `identity.json` has no name (`DTXSID2020006`).
2. Three `PUT /api/v2/studies/DTXSID2020006/identity` at once, with the looked-up identity.
   - It also happened once from the browser when double-clicking **Save this identity** on `DTXSID8031865` (log lines 733–734: 500 then 200).

Expected: one 200, the others `identity_exists` 409.

Actual: one 500 (`FileNotFoundError: .identity.json.tmp -> identity.json`), two 200s. The file ends correct.
- The screen's second click either shows an "unexpected" refusal or succeeds twice.
- The check-then-write is not atomic, so with a different identity in each tab the later write would win, despite the `identity_exists` rule.

Screenshot: `s3_lookup_done.png`.

### F5. Minor: the delete dialog lists a section named "unknown"
Steps: open the delete dialog of DTXSID5032498.

Actual: "5 report sections (Background, Body Weight, Organ Weight, unknown, Summary)", from `bm2_unknown.json` in that session. The person can't tell what "unknown" is. The same session's dialog has no "What stays" list: correct (nothing outside the folder), but the spec's dialog promises the section. A line "Nothing outside the study is affected" would be clearer.

Screenshot: `s4_dialog.png`.

### F6. Minor: deleting a report over several studies turns its members into "Other session, made by a tool"
Steps: delete-preview, then delete `DTXSID1020431` (the report).

Expected (signed Q-M1-5): the parent goes; the members "show as other sessions", as the dialog says.

Actual:
- The members list as kind `other` and become deletable.
- Their banner says "This session's id, DTXSID1020431_rat, is not a chemical's DTXSID: it was made by a tool…", which is false: they are hand-built studies.
- The chemical now shows "No study of this chemical yet", and the creation check offers a new study in the 2026 format, not NIEHS-13's.

Consistent with the decision, but the wording misleads. API check only, after the delete.

### F7. Minor: in step 1, a pasted CompTox address shows both the error and the offer
Steps: paste `https://comptox.epa.gov/dashboard/chemical/details/DTXSID7020182`.

Actual: the field holds the upper-cased URL in red with "A DTXSID starts with 'DTXSID'…", and below it "Use DTXSID7020182?". This meets criterion 16, but the red error beside the offer is confusing.

Also, an id of 80 digits passes the screen's check (green tick), then the backend refuses it with "That is not a valid study id…" and a link "Go to Studies to fix this", which leads nowhere useful.

Screenshots: `s2_paste_offer.png`, `s2_bad_very_long.png`.

### F8. Minor: a tab with a deleted study shows the generic not-found text
Spec S5: "This study was deleted." Actual: "There is no study DTXSID5032498. It may have been deleted." (seen after a reload; no focus-triggered re-read was tested).

Screenshot: `s5_deleted_other_tab.png`.

### F9. Minor: the browser's Back after "Created" lands on the new study's page
Steps: create a study, then press the browser's Back.

Actual: `/app/studies/<new id>`, not the New study form. Harmless, but surprising.

Screenshot: `s2_back_after_create.png`.

### F10. Minor (note): deep links into a module of a published-content session open its pages
`/app/studies/DTXSID50469320_published/files` renders a page that says it is read-only. The page itself is a placeholder; whether it offers data acts is for M2 and the shell to test.

Screenshot: `s5_DTXSID50469320_published_files.png`.

### Checked and held (no finding)
- **Typing:**
  - lower case, letters O/I/l, spaces, `-`, `.`, `DTXCID`, Arabic and full-width digits, a trailing space, an empty id: all refused before anything runs, with a message;
  - pasting with whitespace or newlines: trimmed;
  - pasting two ids: no offer.
- **Create (POST):**
  - an unconfirmed identity, or one of kind `stated`: `identity_unconfirmed`;
  - a wrong or invented name: `identity_changed`, which also guards against a skipped lookup;
  - a wrong or missing `format_seen`: `format_changed`;
  - a lower-case id: `invalid_study_id`;
  - malformed JSON: 422 in the envelope;
  - double-click on **Create study**: two POSTs, 201 then 409, one study, success page shown.
- **An existing empty folder** counts as absent, as the contract says (R8).
- **Delete (POST) refusals:** an empty token gives `changed_since_preview`, a lower-case typed id gives `confirm_mismatch`; members and companions are refused by POST too.
- **Identity (PUT):** on a companion, `read_only_session`; on an existing identity, `identity_exists`; on an absent id, `study_not_found` with no folder created.
- **No GET wrote anything:** list, page, state, creation-check, chemicals lookup, structure.png, delete-preview, deep links to absent, invalid or odd ids (`DTXSIDfoo`, `..`, `DTXSID%2e%2e`, `…%20`, upper-cased suffix). The folder count was unchanged throughout.
- **List search:** upper/lower case, a name, a CASRN and a suffixed id all match; "zzzz" gives "Nothing matches"; spaces only give the full list.

## What I could not check, and why
- **Criteria 1 and 5 on the full store of 2026-10-14** (14 chemicals): the scratch store was the 13-session demo copy; `_nb` and `DTXSID_TEST` were stand-ins.
- **The `dtxsid_matched: false` path** (the second tick, "I checked the DTXSID on the CompTox dashboard"): every real DTXSID tried was matched by PubChem. It needs a mock.
- **`structure_unavailable`** with PubChem up: not reproduced. With PubChem down, the lookup fails first.
- **The Process-running state as designed** (criterion 38): C5 is not served, so this could only fail (F1).
- **The browser's own Back button during step 2**, and a focus-triggered re-read of a deleted study in another tab: only reload was tested.
- The orchestrator's demo server on 9200 was left untouched.
