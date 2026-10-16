**Module:** M1 Studies. Branches `ui-m1-be` (6b3553a) and `ui-m1-fe` (e93455b), plus integration commits b13e1b0 and 893bc2b, reviewed at 623f003 in `/workspace/ui-team/m1-review`.
**Reviewer:** ui-reviewer, 2026-10-15.

## Verdict: ready with fixes

The backend core (`workflow/studies.py`, the M1 steps in `workflow/steps.py`, `web_routes/studies_routes.py`) does what the contract says:
- create is atomic, through a staging folder and a rename;
- the delete token is stable across reads and refuses after a change;
- the typed-id check is exact;
- lookups tell "not found" apart from "unreachable";
- R6 sits before C1 everywhere it should.

The front end follows the spec closely and has a test for every acceptance criterion except AC2 (a timing check).

Two findings break the spec's own idiot-proofing promises: one damaged or half-built session crashes the list or the study page. Each is a few lines to fix and should be fixed before the done sign-off. The rest can follow.

---

## Findings, by severity

### 1. Major: a session with an unreadable format crashes the whole studies list and its page
- **Backend:** `workflow/studies.py:741` serves `format: null` when `format_summary` raises (a damaged `document_definition.json`, for example). `workflow/studies.py:895` serves `detail.format: null` too.
- **Front end:** the types declare these non-null (`ui/src/api/types.ts:515`, `:552`). The code dereferences them without a check: `ui/src/modules/m1/StudiesList.tsx:91` (`s.format.say`) and `ui/src/modules/m1/StudyPage.tsx:207-216` (`f.pin`, `f.title`).
- **Scenario (verified):**
  - The backend, on a scratch copy with `DTXSID_TEST/document_definition.json` replaced by `{bad`, returns 200 with `format: null` and a `damaged_session_file` note. That is correct.
  - The front end, given that shape in a vitest probe, does this:
    - `/studies` renders React Router's "Unexpected Application Error! Cannot read properties of null (reading 'say')";
    - `/studies/DTXSID_TEST` renders "…(reading 'pin')".
- **Why it matters:** spec §3 S1 says "A session the backend could not read fully still lists. Its row carries a warning icon with `notes[].say`". Instead, one damaged file takes down the app's entry page.
- **Fix:**
  - type `format` as `FormatSummary | null` (and `FormatDetail | null`);
  - render `<Pending label="format" cause={note.say}>` in `FormatCell`;
  - skip `FormatCard` (or show the note) when `d.detail.format` is null;
  - add a test with a null-format row in the list and on the page.

### 2. Major: a report whose member study folder is missing crashes the report's page
- **Backend:** `workflow/studies.py:897-898` serves a stub `{id, key, exists: false}` (no `stands`, no `relations`) in `detail.members` when a member folder is absent.
- **Front end:** `ui/src/api/types.ts:554` types `members` as `StudyRow[]`, and `ui/src/modules/m1/StudyPage.tsx:101` reads `m.stands.phase`.
- **Scenario (verified):**
  - The backend, with `DTXSID1020431_mouse` moved aside, serves the stub. Its `stands` correctly says "its studies are being prepared".
  - The front end, given that detail, shows "Unexpected Application Error! Cannot read properties of undefined (reading 'phase')".
  - This is reachable: a report rebuilt before its members, or a member removed through the old reset route (finding 5).
- **Fix (either):**
  - the backend serves a full row for a missing member (`stands.say` "This study is missing", `next: null`, `actions.open.allowed: false`);
  - or the type becomes `StudyRow | MissingMember` and `MembersTable` renders "Missing: this study's folder is not in the store" with no Open button.

  Add a test either way.

### 3. Major: Create is offered when PubChem gives no CASRN, but the backend refuses
- **Backend:** `workflow/steps.py:1006-1007` refuses `identity_incomplete` ("A name and a CASRN are needed.") when the CASRN is empty.
- **Front end:** the chemical card shows the CASRN as `<Pending>` (`ui/src/modules/m1/ChemicalCard.tsx`, CASRN item). Both ticks stay available, so **Create study** is enabled (`ui/src/modules/m1/NewStudy.tsx:226-227`) and sends `casrn: null` (`NewStudy.tsx:160`). The same happens in `IdentityLookup.tsx:39`.
- **Scenario (read, not run against PubChem):** for a compound PubChem knows that has no CAS-shaped synonym, the person confirms, clicks Create and gets a refusal with no way forward. Q-M1-3 rules out a stated identity, so no fix is possible either.
- **This breaks the brief's rule:** "nothing the backend would refuse offered as enabled".
- **Fix:**
  - `lookup_chemical` could refuse (or flag `can_confirm: false` with a `say`) when the CASRN is missing;
  - or the front end disables the confirm tick with words that say why and what to do.

  This is also a maintainer question (Q-M1-3).

### 4. Major (outside M1's files; breaks M1's guarantee): integration overwrites the confirmed identity
- **Where:** `workflow/steps.py:432-433`, inside `integrate_step`: `if identity: store.write_json(dtxsid, "identity.json", identity)`. The integrate route passes the request body's `identity` straight through (`web_routes/pool_routes.py:272-278`).
- **Scenario (read):** a study is created through M1, with `identity_source.kind = "lookup"` and a confirmation date. Any client that later sends `identity` with integrate replaces the file wholesale. The PubChem provenance and the short name are lost, and the name can change silently.
- **This contradicts** Q-M1-11 ("changing an identity that exists is not in M1", the signed spec) and the provenance line M1 shows.
- **Fix:** in `integrate_step`, refuse or ignore a body identity when `identity.json` already holds a name, or merge without replacing `name`, `casrn` or `identity_source`. This belongs to M3 or C3; flag it to them now.

### 5. Minor: the old full-session reset still deletes anything, with no guard
- **Where:** `web_routes/session_routes.py:1498`, `POST /api/session/reset/{dtxsid}`. It removes the whole session folder (`shutil.rmtree`) with:
  - no R6 check;
  - no member check;
  - no dry run or token.
- **Scenario (read):** a script or old bookmark posts to it for `DTXSID1020431_rat`. The member study is gone, and the report then reaches finding 2.
- The contract (§1) says the delete pair replaces this route, but the route is still served.
- **Fix:** retire it, or route it through `delete_study_step`'s guards. This is the maintainer's call.

### 6. Minor: "run in flight" is never served yet, so AC38 holds only against mocks
- **Where:** `workflow/studies.py:622`. `running_since()` always returns None, by design until C5.
- **Scenario:** while Process runs (one to four minutes), delete is offered, and `delete_study_step` renames the folder away from under the run.
- This was already known from the contract ("from C5's run lock"). The front-end test for AC38 passes only on a mocked `run.in_flight`.
- **Fix:** none in M1. Make C5 a precondition for calling AC38 met, and say so in the done sign-off.

### 7. Minor: plain words in the delete dialog carry internal codes, and the cost has a misleading label
- **Internal codes:** `ui/src/kit/ConfirmAct.tsx:95` and `:126` print each item's `what` code after its plain words: "(dataset)", "(statements)", "(study_definition)".
- **Cost label:** `ConfirmAct.tsx:138` labels `cost.say` "To redo it:". For M1 that text is often just "151 MB will be freed." (verified on DTXSID5032498).
- **Approvals lost:** `ConfirmAct.tsx:112-113` looks up the approvals by section key. The backend sends titles (`workflow/steps.py:1239`), so they fall back to monospace code style.
- **Fix (kit-level, the orchestrator's):**
  - drop the `(what)` suffix;
  - label the cost "Cost:" or let the backend word it;
  - render approval titles as text when no key matches.

### 8. Minor: concurrent deletes of the same study (unverified)
- **Where:** `workflow/steps.py:1354`, `folder.rename(doomed)`.
- **Scenario:** two requests that both passed the dry run race. The loser's rename raises FileNotFoundError, which probably reaches the person as a generic error envelope rather than `study_not_found`.
- **Verified:** sequential double deletes correctly return 404 `study_not_found`.
- **Fix:** catch FileNotFoundError and raise `study_not_found`.

### 9. Minor: file length
- `workflow/steps.py` is now 1361 lines. M1 added about 400 lines of study steps, past the ~1200-line house rule.
- **Fix:** move the study steps (create, identity, delete and its helpers) into `workflow/study_steps.py` and re-export them.

---

## What was checked and holds

**The wall**
- Nothing in M1's diff reads, imports or links `wizard-ui/`, `web_wizard/`, `web/`, `tests/e2e/` or the Compare files. The search excluded the Compare files.
- "wizard" appears in no user-facing M1 text. The only hit is a test that asserts its absence.

**Guard order (b13e1b0)**
- `require_data_session` comes before `require_legal` in:
  - `validate_step`, `resolve_step`, `confirm_metadata_step`, `integrate_step`, `generate_animal_report_step`;
  - `materialize_summary` and `materialize_result_sections`;
  - `run_process` and `run_document`, before `_require_processable`;
  - the three upload routes, before `_refuse_add_files`.
- Verified by running: validate on a companion gives 409 `read_only_session`; on a report, 409 `report_has_no_data`.

**893bc2b**
- The read model serves `legal_actions: []` for a companion or a report.
- `nextStepOf` reads only the served `stands.next`.

**Derived, never stored**
- `kind`, `stands`, `bookshelf`, `actions.delete` and `format` are derived on every read.
- Creation writes only `identity.json` and `meta.json`.
- On the full 32-session copy, the list's `stands` equal each session's `/state` `stands` for every row (AC3).

**No hard-coded facts**
- Era titles are declared in `document_definition.ERA_TITLES`.
- A missing publication date reads "[publication date pending]".
- A failed lookup never invents a name.

**Create**
- The atomic rename takes over an empty folder and refuses a non-empty one.
- `format_changed` (hash), `identity_changed` and the `dtxsid_matched` second tick are enforced in the backend.
- Matching now uses the uncapped synonym list, and the real Bisphenol A sample has `dtxsid_matched: true`.

**Delete**
- The dry run lists what goes and what stays.
- The token excludes `.provenance.jsonl`, and it was verified stable across GETs of the page, the state, the list and `/Bookshelf`.
- Lowercase typed id: 400 `confirm_mismatch`. The exact id with spaces around it deletes.
- Afterwards, `/api/v2/studies/{id}` and `/Bookshelf/{id}` both answer 404.

**Identity fill**
- Refused on a report or companion (409 `read_only_session`, verified), and when a name already exists.

**Contract conformance**
- Key-path shapes of the front end's mock fixtures equal the backend's real samples in `docs/ui-redesign/contracts/m1/` for:
  - the list, the details (`_nb`, `_published`, study, `_TEST`);
  - the creation checks, the chemical lookup, the delete preview, delete and created.
- The exceptions are the null and stub shapes of findings 1 and 2.

**Speed (AC2)**
- On a scratch copy of all 32 sessions, `GET /api/v2/studies` took 1.79 s cold and 0.09 s warm, under the 3 s criterion.
- The list showed 14 chemicals plus `DTXSID_TEST` unassigned, no `_prompts`, and no row with an error note (AC1).

## Tests (run)
- **Backend:** `tests/unit/test_studies.py`, `tests/unit/test_studies_steps.py`, `tests/integration/test_studies_routes.py`, `tests/unit/test_read_model.py` with `SESSIONS_DIR`, `OUTPUT_DIR` and `BM2_CACHE_DIR` in scratch: **131 passed**.
- **Front end:** `npm ci`, `npm run typecheck` and `npm run lint` are clean; `npx vitest run` gives **211 passed (14 files)**.
- **Coverage:** every acceptance criterion from AC1 to AC41 has a named test, except AC2, which I measured instead (above). AC38 is tested only against a mocked run lock (finding 6). No test covers the null-format or missing-member shapes (findings 1 and 2).

## Not checked
- No headed browser run; that is the adversarial tester's job.
- Port 9541 was never served: `run-server.sh` needs `.venv` inside the worktree, which the review worktree lacks. Live checks went through FastAPI's test client against scratch stores.
- The real PubChem lookup was not exercised: no network calls from the review. I did not reproduce a compound without a CASRN (finding 3 is from reading the code).
- Truly concurrent create or delete under load (finding 8 is from reading the code).
- The full test suite.
