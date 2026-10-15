# C2 — Owned content is never overwritten by a machine: spec (revision 2)

Core-guarantees module C2 (MODULES.md §2). Spec stage: no code. Written 2026-10-14.

**Legend.** *verified* = I ran it on a scratch copy (`/workspace/ui-team/_scratch/spec-c2/sessions/DTXSID50469320`, with `SESSIONS_DIR`, `OUTPUT_DIR` and `BM2_CACHE_DIR` pointed at the scratch; scripts in `…/spec-c2/scripts/e1_writes.py`, `e2_discard.py`, `e3_key.py`, `e4_key.py`, `survey.py`). *read* = taken from the code only. Line numbers are for the `ui-redesign` worktree at e9e763c.

**Decisions this spec needs are marked ◆ and listed together in §9.**

---

## 0. What C2 guarantees, in one paragraph

A section a person owns (they approved it, or it holds the PROTECTED fact, or a person's text came back from outside the app) is never replaced by a machine. Every write to a section file, whether a person's or a machine's, goes through one core gate. The gate refuses a machine write over owned content. It saves the old content to history, under a name that cannot collide, before anything replaces it. It also adds one line to the section's version trail saying who did what, why, and to which version. Accepting a section changes its state and never its text. Restore and discard become `workflow.steps` steps. A Process run that changes nothing leaves every section file untouched. "Protected" means one thing everywhere.

## 1. Today, verified

| # | Finding | How shown |
|---|---|---|
| T1 | A warm `materialize_result_sections` over an approved apical section with **identical content** sets `approved: False`, drops `facts`, keeps v1, writes no archive. The manifest still says v1 `blessed`. | *verified* E1: `bm2_body-weight` before `True ['final','protected'] v1 blessed`; after `False None v1 blessed`; "content identical apart from flags: True"; history holds only `index.jsonl` |
| T2 | The same happens when the content **did** change: the approval is lost, with no archive and no event. | *verified* E9 (changed caption in `_cache_sections_*`): `approved False facts None v1 status blessed archives []` |
| T3 | After a release, `facts=['protected']`, `may_machine_write=False`, but `protection_level=OPEN`. | *verified* E2 |
| T4 | `materialize_summary` **overwrites a released Summary** that still holds PROTECTED, because it checks only `approved` and `source`. | *verified* E2: `{'ok': True, 'written': True, 'paragraphs': 5}` |
| T5 | Releasing a key that does not exist answers ok. | *verified* E3: `{'ok': True, 'section_key': 'bm2_no-such-thing', 'approved': False}` |
| T6 | "Use run" over an approved Summary: the approval vanishes. The old text is archived, but no event is recorded, and the current version's status reads `None`. | *verified* E4 (same `save_section` call as `prompt_routes.py:222-229`) |
| T7 | **Archive names collide and history is lost.** An archive is named after the section's `approved_at` (`session_store.py:282-289`). Invalidation keeps `approved_at`, so the next approve archives v4 under v3's file name and **v3's archive is overwritten**. | *verified* E5: archives `v1, v2, v3` became `v1, v2, v4` |
| T8 | **Version numbers restart after a discard**, and the manifest then lies. Discard deletes the file and keeps `history/`. The next save stamps v1 (`len(glob)+1`, or `setdefault 1` with `archive=False`), and the old manifest's `v1 blessed` line now describes an unapproved draft. | *verified* E8: new draft `approved False v1`, `current_version_status = blessed` |
| T9 | After a discard, restore and history both answer 404, though the archives are still on disk. Nothing can bring the text back. | *verified* E6: `"No approved 'summary' section found"` |
| T10 | Restore takes `section_key` unvalidated and builds paths from it (`session_routes.py:1288-1290`). `../DTXSID_VICTIM/summary` read another session's file. | *verified* E3 (it answered "Already the current version" from the other session's file). No cross-session write was achieved (E4). |
| T11 | No production code calls `may_machine_write`. | *read* (only tests, and a comment at `narrative/genomics_llm.py:212-219`) |
| T12 | Real data on disk: 118 section files across `sessions/`. **0 approved, 0 with `facts`, 0 archives, 0 section manifests.** `workspaces/guest` and `workspaces/NAME` have none. 15 `background.json` files carry no `source`. | *verified* `survey.py`, read-only over the real store |
| T13 | Baseline: the 15 test files that pin this behaviour pass (254 tests); `run-tests.sh guard` passes (10). | *verified* |

## 2. One definition of "owned" (and so of "protected")

Today two predicates disagree after a release (T3): `protection_level` keys on `approved`/`user_edited` (`ownership.py:161-179`), and `may_machine_write` also on the FINAL/PROTECTED facts (`:134-154`).

**After C2** there is one predicate in `workflow/ownership.py`:

```
is_owned(section, *, report_published=False) =
      section.approved
   or section.user_edited                      # person's text (old in-app edit; C11 ingest)
   or section.source == "ingested"             # reserved for C11
   or guard_level(section_facts(section)) >= GUARDED   # FINAL or PROTECTED
   or report_published                         # ADR-0015 published floor, once Q5's act exists
```

- `may_machine_write(section, *, force=False)` = `force or not is_owned(section)`. Unchanged signature.
- `protection_level(section, report_published)` = `PUBLISHED` if published; else `GUARDED` if `is_owned`; else `OPEN`.

  So `protection_level >= GUARDED ⇔ not may_machine_write` (invariant I7). The render wiring `protection_map` is unchanged; it simply calls the fixed `protection_level`.
- **The state read model** (MODULES §4.1, `sections[].machine_may_write`) serves `may_machine_write(section)`. The kit's `<SectionStatus>` draws one mark from it.
- **The content/state split.** `ownership.STATE_KEYS` lists the keys that are state, not content: `approved, approved_at, facts, stale, regenerated, wording_review, review, revised, version, saved_at`. The gate compares content as the section dict minus `STATE_KEYS`, through a canonical JSON hash (`content_hash`). This is how "nothing changed" is decided (§3, I5).

◆ **D1. A released section stays protected** (ADR-0015 §5: release withdraws FINAL, PROTECTED stands). So after a release, Process still may not overwrite it. A machine replaces it only by a person's explicit act (regenerate, use run, restore). *Recommended*, as the ADR says. The alternative is for release to drop PROTECTED too, so the next Process rewrites a released section freely. That would make "release" mean "let the machine have it", which is not what a person reopening a section usually wants.

## 3. The gate: `workflow.section_writes`

A new core module (about 250 lines). Everything that writes a section file calls it. Nothing else calls `session_store.save_section` / `delete_section` directly, except the gate itself and the invalidation demote (§4.14, which the gate wraps).

```
write_section(dtxsid, key, content, store, *, act, actor, author,
              force=False, reason=None, extra_event=None) -> WriteOutcome
WriteOutcome = {key, outcome: "written"|"unchanged"|"held"|"needs_review"|"refused",
                version, prior_version, archived, event}
```

Rules, in order:
1. **Key.** It must be a section of this session's catalog (`section_catalog.catalog_for_session` and its families). Otherwise `StepError 400 section_key_invalid`. This closes T10 for every path.
2. **Read the prior** file. Absent → write it as v(next), and record an event.
3. **Unchanged.** If `content_hash(prior) == content_hash(new)`: no write, no event, outcome `unchanged` (I5).
4. **Owned, and the actor is the system** (Process, CLI defaults): no overwrite. The outcome is `held` (or `needs_review` for apical sections, §4.1). The bulk caller carries on; a held event is recorded (§5).
5. **Owned, and the actor is a person, without force:** `StepError 409 section_owned`.
6. **Owned, with force** (a person's explicit act): a reason is required (`reason_required`, ◆ D3). Archive, then write.
7. **Otherwise:** archive the prior if its content differs, write, and record the event.

**The primitive changes** in `pipeline/session_store.py`:
- **Archive names are unique.** `history/<key>/v{version:04d}-{ts}.json`, where `{version}` is the archived content's own version. Today the name is `approved_at` (T7). Readers already read `version` from the content, so old timestamp-named archives still read.
- **The version counter is monotonic.** next = `max(current.version, max(archived versions), max(manifest versions)) + 1`. Today it is `len(glob)+1` (`:294-295`), which restarts after a discard and breaks after a collision (T8).
- `save_section(..., archive=False)` keeps its meaning for state-only saves (accept, release, demote).
- **An archive helper**, `archive_current(dtxsid, key)`, for discard and pool reset.
- `delete_section` stays as a primitive and is called only by `discard_section_step` (after archiving) and the resets.

**The store seam.** `PoolStore` gains the following, so steps stay testable with a fake:
- `archive_section(dtxsid, key) -> name|None`;
- `delete_section(dtxsid, key)`;
- `read_version_history(dtxsid, key) -> list`;
- `read_archived(dtxsid, key, version) -> dict|None`.

`DiskPoolStore` delegates to `session_store`, as it does today.

## 4. Behaviour after C2, write path by write path

| # | Path (today's code) | Today | After C2 |
|---|---|---|---|
| 4.1 | `workflow.steps.materialize_result_sections` (`steps.py:90-179`; callers `tooling/generate_report.py:407`, `POST /api/pool/materialize-sections` `pool_routes.py:285-296`, the notebook through `process_async`) | rewrites every `bm2_<slug>.json` with `approved: False` (`:155`), `archive=False` (`:170`); approval, facts and edits lost; `wording_review` only on a flip (T1, T2) | through the gate, `actor=system, act=materialize, author=generated`. **Unchanged content → nothing written** (approval stands; T1 fixed). **Changed content over an unowned section** → archived, written, event `generate/draft`. **Changed content over an owned section** → ◆ **D2** (below). Returns `{ok, materialized, unchanged, needs_review:[{key, why, prior_version, version, flips}], held}`; `materialized` keeps its meaning: "files written" |
| 4.2 | `workflow.steps.materialize_summary` (`steps.py:54-87`; caller `generate_report.py:417`, the notebook) | refuses over `approved` or `source != generated`; **overwrites a released, PROTECTED Summary** (T4); `archive=False` | through the gate (`actor=system, act=summary`). It keeps its own extra rule: it replaces only its own earlier output (`source == generated`). Owned → `held`, plus a `hold` event when the new text differs (so the changelog shows "Process wrote a new Summary; not applied because you approved this one"). The held text itself is **not** kept; C7's "fresh draft beside" stores it. Returns `{ok, written, paragraphs, held?: {why}}` |
| 4.3 | `workflow.steps.accept_section_step` (`steps.py:655-717`); no route calls it today | state-only; records `edit/blessed` on the same version | stays state-only (`archive=False`). Adds: key validated (rule 1). Accepting a section that is already approved, carries no `stale`/`review`, and has status `blessed` → `noop: already_accepted`, no event. Clears the new `review` marker as it clears `wording_review`. Event `edit/blessed`, `actor=person, act=accept` |
| 4.4 | `workflow.steps.release_section_step` (`steps.py:720-751`); twin route `POST /api/session/unapprove` (`session_routes.py:1084-1134`) duplicates the logic instead of calling the step | a missing key answers ok (T5); the reason is optional | missing → `StepError 404 section_not_found`. Not approved → `noop: not_approved`, no event. Reason per ◆ **D3**. The route calls the step |
| 4.5 | `POST /api/session/approve` (`session_routes.py:767-964`) | **writes the posted `data` as the section**, archive=True, plus `identity.json`/`meta.json` (`:824-840`); empty data replaced an approved Summary (document analysis §2) | ◆ **D5** (fence, recommended): the file exists and the posted content hashes equal to it → `accept_section_step` (state-only). Content differs → `409 approve_content_retired`. No file → `404 section_not_found`. The identity write is dropped (C3 owns identity). The new interface uses `POST /api/v2/…/accept` only |
| 4.6 | `POST /api/session/save-section` (`session_routes.py:1037-1077`) | writes any content, `archive=False`; takes `approved` from the body (`:1073`), a back-door approval; destroys an approved Background (document analysis §2) | through the gate as `actor=person, act=save, author=<data.source or "client">`: owned → `409 section_owned`; changed → archive + event `generate/draft`. `approved: true` in the body → `400 approve_via_accept`. Kept only until D2 saves generated Background server-side (◆ D5) |
| 4.7 | `POST /api/session/discard-section` → `session_store.delete_section` (`session_routes.py:1141-1161`, `session_store.py:412-422`) | deletes the file; history is abandoned in practice (T8, T9) | `discard_section_step(dtxsid, key, store, *, reason)`: owned and approved → `409 section_owned` (release first). Otherwise archive the current file, delete it, and record event `discard/discarded`. The version counter stays monotonic, and restore still reaches the archives (T9 fixed). ◆ **D4**: keep it, or retire it from the new interface |
| 4.8 | `POST /api/session/{id}/restore` (`session_routes.py:1261-1335`) | the key is unvalidated (T10); comes back **approved** with a fresh `approved_at` (`:1325`); no event; 404 after a discard | `restore_section_step(dtxsid, key, version, store, *, reason)`: key validated; finds the version in the archives or the current file; works when the current file is absent (after a discard); archives the current file; writes the restored content as v(next); event `restore` with `from_version`. The approval it comes back with: ◆ **D3 / Q6**. Restoring never clears currency: if the current file is `stale` or under `review`, the restored one keeps those markers |
| 4.9 | `POST /api/prompts/{section}/runs/{id}/{run}/use` (`prompt_routes.py:213-230`) | `save_section` archive=True, `approved: False`, no event; an approved Summary loses its approval (T6) | through the gate, `actor=person, act=use_run, author=model` (+`run_id`, `model`). Owned → ◆ **D6** (`409 section_owned`, recommended: release first, with its reason). Response stays `{"ok": true}`, with `version` added |
| 4.10 | `tooling.generate_report.background` (`generate_report.py:461-468`); the notebook calls it | `store.save_section(..., archive=False)`, no guard | through the gate, `actor=person` (the operator asked), `act=background`, `author=model`. Owned → the CLI prints the `section_owned` message and saves nothing. `--force` with `--reason` is the escape hatch |
| 4.11 | `POST /api/generate`, `/api/generate-methods`, `/api/generate-summary` (`llm_routes.py:169-249, 256+, 507+`) | return text and write no section file (*read*) | unchanged. D2 adds a server-side "generate and save as draft" that calls the gate |
| 4.12 | genomics: `POST /api/session/{id}/regenerate-genomics-narrative` (`llm_routes.py:657-832`) clears the person's override with no backup (`:753-771`); `POST /api/generate-genomics-narrative` takes `force` from the request body (`:648`); `POST /api/session/{id}/genomics-narrative-override` (`session_routes.py:713-760`) replaces the override in place | no archive; no record | Until C9 there is no genomics section file. C2 still: (a) **archives** `genomics_narrative_overrides.json` to `history/genomics_<organ>_<sex>/` and records an event (`act=regenerate`, `actor=person`, reason ◆ D3) before regenerate clears it; (b) `force` from the generate route's body is honoured only with a `reason`, else `400 reason_required`; (c) archives before each override write. Converging the override store onto section files is C9's job (§7) |
| 4.13 | `run_process` / `document_step` writing `_cache_methods_*`, `_cache_apical_narrative_*`, `_cache_interpretation_*` (*read*: no section file is written) | Methods and the apical-BMD narrative rewritten silently when their hash moves (Process analysis, finding 4) | **Out of C2's reach until C9**: there is nothing approvable to protect. C2 states it as a known gap, and §7 says how C9 inherits the rules |
| 4.14 | `pipeline.pool_state.invalidate_pool_artifacts` (`pool_state.py:224-276`); `web_routes/pool_admin.py:151-227` (CLI) | archives and records `reprocess/needs-re-bless` for data-dependent LLM sections (correct), but archives collide (T7) | A state change, not a content write: it keeps its logic and uses the fixed primitive (unique archive names, monotonic versions). The event gains `actor=system, act=invalidate`. It does not touch `bm2_*` (unchanged, Phase 3a) |
| 4.15 | `POST /api/pool/reset/{id}` (`session_routes.py:1496-1627`, section deletes `:1581-1599`) | deletes `bm2_*`, `genomics_*`, `methods`, `bmd_summary`, `summary`; keeps `history/` | before each delete: `archive_current`, then event `discard/discarded`, `act=pool_reset`, `actor=person`, so a reset is restorable. The dry-run and confirm are C8's |
| 4.16 | `POST /api/session/reset/{id}` (`:1634-1678`) | deletes the whole directory | out of C2 (irreversible, C8's type-to-confirm) |
| 4.17 | `roundtrip.reconcile.apply_reconcile` → `set_override` (`roundtrip/reconcile.py:232`) | a person's Overleaf edit enters the override store | out of C2 (C11). Such text is person-owned (`source: "ingested"` in `is_owned`, §2) |

◆ **D2. An approved apical section whose content changed on Process.** The deliverable renders apical content from `_cache_sections_*`, not from `bm2_<slug>.json` (`rendering/latex_export.py:762-788`, *read*; the Process analysis's P5). So once the numbers change, the printed section has already changed; keeping the old text in the file would not keep it in the report. Two honest options:
- **A1 (recommended): knock it down, with a record.**
  - The new content becomes v(next), and the approved version is archived.
  - `approved: False`; facts demoted by currency (FINAL withdrawn, PROTECTED stands).
  - A `review: {why: "numbers_changed"|"wording_changed", since_version, flips}` marker.
  - Event `reprocess/needs-re-bless`, `act=materialize`, `actor=system`.

  The person sees "approved in v3; the data changed what it prints; read and re-accept". Re-accepting clears `review`. That is the Q1 reading: "marked for re-review, never silently un-approved with no record".
- **A2: keep `approved: True` and add the marker**, as the LLM `stale` path does today. "Approved" would then describe text that is no longer what prints; the publish gate (C6) must read `review` to block.

Either way, `stale` is **not** used on `bm2_*`. `has_stale_sections` (`store.py:149-159`) would send the phase back to UPLOADED (`phases.py:167-169`, *read*). `wording_review` stays as it is today: `review.flips` holds the same list, and both are cleared by accept.

## 5. The version event: the record the changelog is built on

One line per event, appended to `history/<key>/index.jsonl` (append-only, as now). Old lines (`version, cause, status, ts, reason?`) still read. New lines carry `"v": 2`.

| Field | Type | Meaning |
|---|---|---|
| `v` | int | line format (absent = 1) |
| `section` | str | the section key (the directory says it too; carried so the report changelog can merge lines without paths) |
| `version` | int | the version this event is about (the new one for a write; the current one for a state change or a hold) |
| `ts` | ISO 8601 | `common.clock.now_iso()` |
| `cause` | closed list | `edit` (= accept; old name kept), `revise` (= release), `reprocess`, `generate`, `restore`, `discard`, `hold`; reserved: `ingest` (C11), `propose` (C7) |
| `status` | closed list | the version's status after the event: `draft`, `blessed`, `working`, `needs-re-bless`, `discarded`; reserved: `proposed` |
| `act` | str | the entry point: `accept, release, restore, discard, materialize, summary, background, save, use_run, regenerate, invalidate, pool_reset` (+ `ingest` later) |
| `actor` | `"person"` \| `"system"` | who caused it. A person act is one a person asked for (a route call from the interface, a CLI flag); Process and invalidation are `system` |
| `user` | str \| null | null until the interface has users (HANDOFF §10 Q8); the field is reserved so C11 needs no format change |
| `author` | str | who wrote the content of `version`: `generated` (deterministic), `model`, `person`, `ingested`, `client` (old save-section) |
| `prior_version` | int \| null | the version that was current before |
| `from_version` | int \| null | restore only |
| `changed` | bool | did the content change (false for accept, release, hold) |
| `content_hash` | str | `sha256:` of the canonical content (STATE_KEYS removed) of `version` |
| `archived` | str \| null | the archive file written by this event (the prior content) |
| `reason` | str | release / restore / discard / forced writes (◆ D3); the currency reason (`data_changed`) for invalidation |
| `review` | object \| null | `{why, flips}` for `needs-re-bless` from materialize (D2) |
| `applied` | bool | false for `hold` (the machine had new content and did not write it) |
| `run_id`, `model`, `template_version` | optional | for `author: model` |

**Invariants the event log must satisfy** (the acceptance criteria, §8):
- **I3:** every `version` a line names has retrievable content (the current file, or an archive whose `version` field matches). Today this is violated (T7, and T1's unarchived overwrite).
- **I4:** every change of approval appends exactly one line.
- **I8:** `content_hash` lets the changelog say "text changed" or "state only" without loading archives.

**How it serves the changelog (C11).** The report changelog is **derived, never stored**: the union of every section's `index.jsonl` (and the pins' `history/`), ordered by `ts`. Per line, the changelog says:
- *what*: section, version;
- *how*: `cause` / `act`;
- *by whom*: `actor` / `user`;
- *written by*: `author`;
- *why*: `reason` / `review`;
- *whether the text changed*: `changed`, with a diff from the archives for `prior_version` → `version`.

C11 adds `cause: ingest` lines (`author: ingested`, `actor: person`) and, if ingests are reviewed before they stand, `status: proposed`. C7 adds `cause: propose` for the fresh draft beside stale text. Neither needs a format change. A read helper, `workflow.section_writes.section_history(dtxsid, key)`, returns `{current_version, current_status, versions:[{version, archived, status, approved_at}], events:[…]}`. It serves the new history route (contract).

## 6. Existing sessions on disk

- **The real store** (T12, *verified*): no approved sections, no facts, no section archives, no section manifests. Nothing needs migrating. The "approved file whose manifest says blessed" case exists only in tests and in scratch copies.
- **Old timestamp-named archives** (none in the real store; possible in test fixtures) still read: readers take `version` from the content. A version lost to an old collision stays lost. `section_history` reports a manifest version with no content as `archived: null` (contract: `version_content_missing`).
- **The 15 `background.json` files with no `source`** are unowned (not approved, no facts), so a machine may replace them. The gate archives them first, so nothing is lost.
- **Sessions where a version number restarted after a discard** (T8): the monotonic counter starts above every number already seen, so new events never land on an old version's line.

## 7. Methods, the apical-BMD narrative and the genomics interpretations (C9, Q4)

C2's rules are written against the catalog and the gate, not against kinds, so C9 adds no rule. When C9 makes these sections:
1. each becomes a catalog section with a file (`methods`, `bmd_summary`, `genomics_<organ>_<sex>`; the keys already exist in `singleton_section_stems` and the families);
2. its writer (content preparation in `run_process` / `document_step`, the genomics regenerate route) calls `write_section` with `actor=system, act=prepare_content` (or `actor=person, act=regenerate`, `force`, `reason`), and gets unchanged / held / needs_review exactly as §3 and §4.2 say;
3. the renderer reads the section file, not the cache (`latex_export.py:811-813, 834-860`), so "held" really keeps the approved text in the deliverable. That is the difference from apical sections (D2);
4. the genomics override store (`genomics_narrative_overrides.json`) migrates onto the section file as a person-authored version (`author: person`, owned). The archives C2 writes under `history/genomics_<organ>_<sex>/` (§4.12) become that section's history;
5. `narrative/genomics_llm.py:133-231`'s "return the store, full stop" rule is replaced by `may_machine_write` (ADR-0015's deferred convergence).

Until C9, Process rewrites Methods and the apical-BMD narrative silently. C2 does not hide that: D1's spec must say these parts are not yet approvable.

## 8. Acceptance criteria (each a test)

- **I1:** for each machine path in §4 (4.1, 4.2, 4.10, 4.12, and the gate itself), an owned section (approved; released with PROTECTED; `user_edited`) is not overwritten. A unit test per path, with the fake store.
- **I2:** every content-changing overwrite archives the prior first; two overwrites within the same second keep both archives (T7 regression).
- **I3:** every manifest version has retrievable content (a property test over a sequence of accept / release / invalidate / approve / restore / discard).
- **I4:** one event per approval change; no event for an unchanged materialize.
- **I5:** a warm `materialize_result_sections` with nothing changed leaves every `bm2_*.json` byte-identical (mtime too) and an approved section approved (T1 regression).
- **I6:** a refused person act raises `StepError` with a contract code; a held system write appears in the step's result and as a `hold` line.
- **I7:** `protection_level(s) >= GUARDED ⇔ not may_machine_write(s)` for every combination of `approved` / `user_edited` / `facts` / `stale` (T3 regression).
- Restore after a discard works (T9); restore with `../x` → 400 (T10); version numbers never repeat after a discard (T8).
- Integration, through the FastAPI test client against a scratch `SESSIONS_DIR`: each route in the contract, with each refusal's code and envelope.

## 9. Decisions for the maintainer

| # | Question | Options | Recommended |
|---|---|---|---|
| D1 | Does a released section stay protected from machines? | (a) yes, PROTECTED stands (ADR-0015); (b) release drops PROTECTED | (a) |
| D2 | An approved apical section whose numbers or wording changed on Process | A1 knock down with a record (`approved: False`, FINAL withdrawn, `review` marker, archive, `needs-re-bless`); A2 keep `approved: True` + marker | A1 (what is approved should be what prints) |
| D3 = Q6 | Restore: approved or draft? Reasons required? | Restore: (a) back as a draft (owned: PROTECTED, not approved, accept is a separate act); (b) back with the approval it had (today); (c) approved only if blessed and its inputs unchanged (needs C7's input fingerprint; later). Reasons: required for release, restore, discard and forced machine writes; or optional (today) | restore (a); reasons required (non-empty) for all four |
| D4 | Discard | (a) keep, as an archived, restorable step; (b) retire from the new interface (Q1 removes editing; regenerate and restore cover it) | (b) for the interface, with (a)'s step behind the old route and pool reset |
| D5 | The old front-end's write routes (`/api/session/approve` with content, `save-section`) while the old interface still runs on 9000 | fence them (§4.5, §4.6; the old interface's "edit then approve" is refused with an explanation); or leave them until the new interface replaces it (C2's guarantee then holds only for the new routes) | fence |
| D6 | "Use run" (or a regenerate) over an approved Summary | (a) refuse: release first, with its reason; (b) allow with a reason and confirm, archiving the approved text | (a); C7's draft-beside will make it one act later |

## 10. Blast radius

**Code that changes:**
- `pipeline/session_store.py` (`save_section` archive name and counter, `:274-306`; `_record_version_event` fields, `:333-360`; `archive_current`);
- `workflow/ownership.py` (`is_owned`, `STATE_KEYS`, `content_hash`; `protection_level` `:161-179`);
- new `workflow/section_writes.py`;
- `workflow/store.py` (Protocol + `DiskPoolStore`: four methods);
- `workflow/steps.py` (`materialize_*` `:54-179`; accept/release `:655-767`; new `restore_section_step` and `discard_section_step`; the file goes from 767 to about 950 lines);
- `pipeline/pool_state.py:269-272` and `web_routes/pool_admin.py:214-220` (event fields; nothing else);
- `web_routes/session_routes.py` (approve, save-section, unapprove, discard, restore, override, pool reset);
- `web_routes/prompt_routes.py:213-230`;
- `web_routes/llm_routes.py:625-654, 753-771`;
- `tooling/generate_report.py:424-469` (+ `--force/--reason`);
- a new `web_routes/` v2 module for the section routes (its registration in `background_server.py` is the orchestrator's);
- the notebook's text on Process and sections (`notebooks/_nb_cells_report.py:120-140, 225-275`): the orchestrator decides.

**Tests that pin today's behaviour and must change:**
- `tests/unit/test_workflow_steps.py:278-302` (`assert bw["approved"] is False` at `:302`): under D2/A1 still False, but now also `review`, an archive and a `needs-re-bless` line; under A2, True. Add the I5 test beside `:322-342`.
- `tests/unit/test_workflow_authoring_steps.py:137-142` (`release` of an absent section → ok): becomes 404. `:123-135`, `:145-150` and `:166-175` call `release` without a reason: they need one if D3 requires it.
- `tests/unit/test_version_cause_snapshots.py:348-365` (`release` without a reason records the reopen) changes under D3. `:296-314` (`TestLiveApproveRoute`, which posts content to a new file) changes under D5. `:103-108`: the docstring's "unapprove / restore are unmarked" becomes false (the assertion on the primitive still holds).
- `tests/integration/test_session_lifecycle.py`: these use the approve route to *create* sections, so under D5 they must seed a file and accept it instead:
  - `:99-123`, `:125-158`, `:160-175`, `:177-193`;
  - `:238-273` and `:275-305` (history through two content-posting approves).
- `tests/unit/test_review_fixes_2026_09_24.py:40-48` (approve route posting content) changes under D5.
- `tests/unit/test_prompt_routes.py:65` (`== {"ok": True}` exactly) changes if the response gains `version`.
- **Unchanged** (*read*):
  - `test_workflow_ownership.py:106-147, 168-205` (same results for those inputs);
  - `test_session_store.py:72-185` (archives still end in `.json`; counts are unchanged);
  - `test_dtxsid_validation.py:95-107` (id validation still runs first);
  - `test_session_files.py:75-90`;
  - `test_reprocess.py`, `test_workflow_engine.py:245`, `test_invalidate_pool_stale_by_origin.py:119-130`, `test_protection_marks.py`.

**The golden oracle** (`tests/integration/test_process_integrated_golden.py`) **does not move**. It drives `POST /api/process-integrated` → `run_process` and compares the returned payload (`:194-230`). `run_process` writes no section file, and the HTTP route does not materialize (*read*). `guard` passes today (*verified*). After C2, run `guard` to confirm.

## 11. Risks

- **The old front-end** (walled; I can't see what it calls) may depend on `approve`-with-content and `save-section` with `approved: true`. D5's fence refuses those with an explanation rather than silently. The orchestrator should ask the maintainer whether the old interface on 9000 is still in use.
- **Determinism.** I5 assumes apical section content is byte-stable across warm runs. *Verified* for a warm run (E1); not checked across a cold recompute. If floats or ordering wobble, every Process would knock down approved apical sections (D2). The engineer must test a cold-vs-warm hash.
- **No run lock** (C5): the gate reads, then writes; two concurrent Process runs can still interleave. C2 does not add a lock.
- **Render bytes.** The I7 fix lights the protection mark on released sections; no real session has facts (T12), so no deliverable on disk changes. The render surfaces don't receive `approved` at all today (document analysis §2, "no surface marks approved content"). Not C2's job; D3/C10.
- **The publish gate** does not yet read `review` (D2/A1) or `hold`; that is C6. Until then, a knocked-down apical section blocks nothing.
- **History growth**: one archive per content change, 2–30 KB per apical section (*verified* file sizes); negligible.

## 12. The order of the changes

1. The primitive: unique archive names, monotonic counter, v2 event lines, `archive_current`. Tests for T7, T8, I2 and I3.
2. Ownership: `is_owned`, `STATE_KEYS`, `content_hash`; `protection_level` on `is_owned`. Test for I7.
3. `workflow/section_writes.py`: the gate, `section_history`; fake `PoolStore` methods. Unit tests per rule.
4. `materialize_result_sections` and `materialize_summary` through the gate (D2). Tests for I1, I5 and T4; `guard`.
5. The steps: accept noop and key check; release 404 and reason (D3); `restore_section_step`, `discard_section_step`. Unit tests.
6. Routes: fence the old routes onto the steps (D5, D6); add the v2 section routes. Integration tests.
7. CLI `background` through the gate; genomics archive-before-clear.
8. Run `smart`, then `guard`; update the HANDOFF §4.3 text and `http-api.md` (orchestrator).

---

## Signed (2026-10-15, the maintainer)

The recommendations of §9 were accepted:
- **D1 (a).** A released section stays protected: PROTECTED stands (ADR-0015).
- **D2 A1.** An approved apical section whose content changed on Process is knocked
  down with a record: archived, `approved: false`, FINAL withdrawn, a `review`
  marker, `needs-re-bless`.
- **D3.** Restore brings a version back as a draft (owned, not approved; accept is a
  separate act). A non-empty reason is required for release, restore, discard and
  every forced machine write.
- **D4 (b).** Discard is not offered by the new interface; the step exists behind the
  old route and pool reset.
- **D5.** The old write routes are fenced (§4.5, §4.6), not retired.
- **D6 (a).** "Use run" (or a regenerate) over an approved Summary is refused: release
  it first, with a reason.

Draft 1 (`spec-draft1.md`, `contract-draft1.md`) is background only.
