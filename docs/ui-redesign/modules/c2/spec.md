# C2 — Owned content is never overwritten by a machine (spec)

Core-guarantees module C2 (MODULES.md §2). Spec stage, 2026-10-14. Evidence: gate0-document §2 and §8,
gate0-process finding 1, §4.2 and P5, gate0-data §3.2; ADR-0015, ADR-0018, ADR-0020; MODULES §8 (Q1, Q4).

**Legend.** **[V]**: verified by running it on a scratch copy of `DTXSID50469320`
(`/workspace/ui-team/_scratch/spec-c2/`, scripts in `scripts/e1_writes.py`, `e2_discard.py`, `survey.py`).
**[R]**: read from the code. `file:line` refers to the `ui-redesign` worktree at `e9e763c`.

---

## 0. What C2 guarantees, in one paragraph

After C2, every write to a report section goes through **one guarded core write**. That write consults
`workflow.ownership.may_machine_write` and records a **version event**. A machine never replaces the text
of a section a person holds; it either keeps the person's text (LLM-written sections) or makes a
**recorded** refresh that archives the person's version and marks the section for re-review
(programmatic apical sections, whose printed numbers come from the data). Every version that ever existed
is in `history/<key>/`, and every change has a line in `history/<key>/index.jsonl` that says what caused it,
who or what did it, and why. That line is the record C11's report changelog is built from. Accept and
release become state-only acts. Restore and discard become `workflow.steps` steps that record their
event. "Protected" has one definition.

---

## 1. Decisions for the maintainer

| # | Question | Options | Recommendation |
|---|---|---|---|
| **S1** (confirms Q1) | Process changes an **approved apical section** (`bm2_*`): its numbers and/or wording differ | **A.** Any change to the section's content: archive the approved version, write the new one, mark it for re-review (`approved: false`, status `needs-re-bless`), list flipped words in `wording_review`. **B.** Numbers-only change (no categorical word flipped): keep the approval on the new version (event status `blessed`, reason `numbers_refreshed`); a word flip behaves as A. | **A.** It is the orchestrator's reading of Q1, and a person who approved a table approved its numbers. Cost: after a data change, every apical section a person approved needs re-accepting. D1 groups and diffs them. |
| **S2** (Q6a) | Restoring a past version | **A.** It comes back as a working draft: `approved: false`, PROTECTED (it is a person's text), event `restore/working`. The person accepts it again. **B.** It comes back as it was: approved again if the archived version was blessed (today's behaviour, now recorded). **C.** As B, but only when that version was blessed **and** the section is not stale; otherwise A. | **A.** It means no implicit approval, at the cost of one extra click. |
| **S3** (Q6b) | Is a reason required? | For each of release, discard, restore and replace: required or optional | **Required for all four.** The trail exists to say why, and the changelog is empty without it. |
| **S4** | A person asks for new machine text (regenerate the Background, "use run" for the Summary, regenerate a genomics narrative) over a section they hold | **R1.** Allowed only with `replace: true` and a reason. The held version is archived and the new text becomes the current draft (unapproved). **R2.** Refused until C7 provides a "draft beside the approved text". | **R1 now.** It is recorded and undoable (restore). C7 can add draft-beside for automatic currency rewrites later. |
| **S5** | The legacy routes that post section text (`/api/session/approve`, `/api/session/save-section`) and the legacy restore, discard and unapprove routes | **Retire** them on `ui-redesign` (answer 410 with the envelope); the new interface uses the `/api/v2` acts. **Fence** them: keep them, apply the guard. | **Retire.** Q1 rules out in-app text editing, and no served front-end on this branch calls them. **Consequence:** the old front-end on `main` uses them, so merging `ui-redesign` into `main` while that front-end still runs would break it. The maintainer decides when. |
| **S6** | `POST /api/session/{id}/genomics-narrative-override` (an in-app edit of a genomics narrative) | Retire (Q1). Existing overrides keep rendering until C9 imports them as versions. Or keep it, guarded and archived. | **Retire.** |
| **S7** | Restore or discard on a **programmatic** section (`bm2_*`) | Refuse restore (`restore_not_meaningful`): the deliverable prints the current data, so an old version can only be compared. Discard allowed (archived; next Process recreates a draft). Or allow both. | **Refuse restore, allow discard.** |
| **S8** | Archive every content change, or only changes to owned content? | Every content change, including unowned machine drafts. Or owned only. | **Every change.** Small cost (the full apical set is ~100 KB [V]); it lets the changelog show a diff for every generated change, as Q1 asks. |
| **S9** | Who did it | `by: person/system` and `via: <entry point>` now; `who` stays `null` until the interface has users (HANDOFF §10 Q8) | Confirm that C2 needs no login. |

Not C2's, but adjacent:
- **C7:** should accept refuse a stale LLM section whose text was not rewritten?
- **C6:** should an apical section waiting for re-review block publishing (today only stale LLM sections block)?

---

## 2. One definition of "protected" (ownership)

**Today [V]:**
- After a release, a section has `facts=['protected']`, `approved=false`.
- `may_machine_write` answers **False**, because it reads the facts (`workflow/ownership.py:134-154`).
- `protection_level` answers **OPEN**, because it reads only `approved`/`user_edited` (`ownership.py:161-179`, `is_user_owned` `:111-127`).
- `materialize_summary` reads only `approved` and `source` (`workflow/steps.py:76`). It **wrote over the released Summary**, dropped PROTECTED and archived nothing [V].
- `user_edited` is never written by any production code [R]: it is read by the predicate and returned by the approve route (`session_routes.py:943-962`), never persisted.

**After C2** (`workflow/ownership.py`):
- `is_owned(section) -> bool`, the one predicate. True when any of these holds:
  - `approved` is true;
  - the stored facts raise the guard to GUARDED or above (FINAL or PROTECTED; `guard.guard_level`);
  - `source == "ingested"` (reserved for C11);
  - legacy `user_edited` is true.
- `is_user_owned` remains as a deprecated alias of `is_owned`.
- `may_machine_write(section, *, force=False)` = `force or not is_owned(section)`. Only the guarded write (§4) passes `force`, and only on a person's `replace` with a reason.
- `protection_level(section)` = GUARDED when `is_owned(section)`, with the report-grain `published` floor kept. So after a release the mark and the machine guard agree: a machine won't overwrite it.
- The human axis stays separate: **maturity** = `labels.maturity_rung(section_facts(...))` (final / working / none).
- The read model serves both as `machine_may_write` (= `may_machine_write(section)`) and `maturity`. The kit's `<SectionStatus>` draws one mark from them (MODULES §4.5).
- Release keeps PROTECTED (ADR-0015 §5, unchanged). A released section is a person's text being reworked: no automatic write touches it, and only a person's replace, discard or restore changes it.

---

## 3. Versions, archives and version events

### 3.1 The model
- A **version** is one distinct content of a section. Every content change mints a new version number. State-only changes (accept, release, the currency stale flip) record an event against the **same** version.
- The **current** version is `<key>.json`. **Every superseded version** is archived as `history/<key>/v{version:04d}.json` before it is replaced or deleted.
  - Today the archive is named by `approved_at` (`pipeline/session_store.py:282-289`), and that name collides [V]: accept, then invalidate, then the approve route overwrote v3's archive with v4, and two different contents were both labelled v4 (E5).
  - Legacy timestamp-named archives are kept and read by the `version` field inside them.
- **Next version** = 1 + the highest of: the current file's `version`, every archived `version`, every manifest `version`.
  - Today it is 1 + the count of archive files (`session_store.py:294`), or the prior file's version for `archive=False`.
  - [V] After accept, discard and `materialize_summary`, the new unapproved draft was **v1**, and the manifest called v1 **blessed** (E8).
- **Deleting** a section always archives its current version first and records a `discard` (or `reset`) event. Today `session_store.delete_section` unlinks the file (`:412-422`). [V] After a discard, history exists but the routes answer 404 "No approved 'summary' section found" (E6).

### 3.2 The version-event record (one line of `history/<key>/index.jsonl`)

```json
{"version": 5, "cause": "reprocess", "status": "needs-re-bless", "ts": "2026-10-14T20:35:54.97+00:00",
 "by": "system", "via": "materialize_result_sections", "who": null,
 "reason": "data_changed", "from_version": 4, "archived": "v0004.json",
 "content_hash": "sha256:…", "source": "generated",
 "changes": {"content": true, "wording": ["Male|Terminal Body Wt..direction"]}}
```

| field | meaning | today |
|---|---|---|
| `version` | the version the event describes | exists |
| `cause` | closed list: `generate` (a machine wrote text), `reprocess` (the system reacted to new data), `edit` (a person accepted; kept from today's manifests, shown as "accepted"), `revise` (release), `restore`, `discard`, `reset` (pool reset), `ingest` (reserved for C11) | edit/revise/reprocess exist |
| `status` | the version's standing after the event: `draft` (machine text nobody approved), `blessed`, `working` (a person's text, not currently approved), `needs-re-bless`, `discarded` | blessed/working/needs-re-bless |
| `ts` | when | exists |
| `by` | `person` or `system`. **Required; no default:** a caller that omits it is a programming error (`ValueError`), not a silent "system". | new |
| `via` | the entry point: the step name, or `api/v2`, `cli`, `notebook` | new |
| `who` | the person's identity; `null` until there are users (S9) | new |
| `reason` | a person's free text, or a system code (`data_changed`, `numbers_refreshed`) | exists for revise |
| `from_version` | for `restore`: the version brought back; for `reprocess`/`generate`/`discard`: the version superseded | new |
| `archived` | the history file the superseded version went to | new |
| `content_hash` | `sha256` of the version's content (§4.2): two versions with the same hash have the same text | new |
| `source` | who wrote the text: `generated`, `model`, `ingested` (C11) | new on the event |
| `changes` | a short summary: `content: bool`; `wording`: flipped categorical slots (apical); C11 adds the regions changed | new |

### 3.3 How the changelog builds on it (C11)
- The **report changelog is derived**, never stored. It is every section's `index.jsonl` (and the pins' `history/_method_profile`, `_document_definition`) merged and ordered by `ts`.
- Each content-changing line (`content_hash` differs from the previous version's) links `from_version` → `version`, so the screen can show a diff from the two archives.
- State lines (accept, release) carry no diff.
- C11 appends `cause: ingest, by: person, via: word|overleaf` lines with `source: ingested`, which make the section owned (§2). So "a machine never overwrites an ingested version" follows from the same predicate.
- `.provenance.jsonl` (`common/provenance.py`) stays an operational log; it is not the changelog.

### 3.4 The store seam (`workflow/store.py`, `PoolStore`)
`save_section(…, archive=…)` and its transient `_version_event` marker (`session_store.py:231-360`) are
replaced by explicit operations. Each requires an event:

| method | does |
|---|---|
| `write_section_version(dtxsid, key, data, event) -> int` | archive the current version (if any) to `v{n}.json`, mint the next version, write the current file atomically (temp + rename), append the event |
| `record_section_event(dtxsid, key, data, event)` | rewrite the current file in place (same version) and append the event; for state-only acts |
| `delete_section(dtxsid, key, event)` | archive the current version, append the event (`status: discarded`), remove the file |
| `section_events(dtxsid, key) -> list[dict]` | the manifest (legacy lines without `by`/`via` read as `by: null`) |
| `section_versions(dtxsid, key) -> list[dict]` | `[{version, file, content_hash}]` from archives plus the current file |
| `read_section_version(dtxsid, key, n) -> dict \| None` | one version's content |

An archive or event that can't be written raises `StepError(500)` (`history_write_failed`) **before** the
current file is replaced. Today the event append is fail-soft (`session_store.py:322-330, 357-360`), which
would let a change happen with no changelog line.

---

## 4. The guarded write (`workflow/section_writes.py`, new)

### 4.1 The function

```python
def write_section_content(dtxsid, key, content: dict, *, store, by, via, source,
                          replace=False, reason="") -> WriteOutcome
```

`WriteOutcome` is one of:
- `written(version)`;
- `unchanged`;
- `kept_owned` (noop `section_owned`);
- `kept_other_draft` (noop `draft_from_elsewhere`);
- `refreshed_for_review(version, from_version, wording)`.

| prior section | content origin (`workflow.content_origin`) | who asks | result |
|---|---|---|---|
| absent | any | any | new version, `approved: false`, event `generate/draft` |
| same `content_hash` | any | any | **no write at all**: file byte-identical, approval, facts and version kept; `unchanged` |
| not owned, same `source` as the writer | any | any | archive, new version, event `generate/draft` |
| not owned, different `source` (e.g. a model run chosen by a person, and the deterministic Summary arrives) | any | system | **keep**; noop `draft_from_elsewhere` |
| not owned, different `source` | any | person | archive, new version, event `generate/draft` |
| **owned** | **LLM** | system | **keep**; noop `section_owned`. C7 adds "draft beside" here. |
| **owned** | **LLM** | person, no `replace` | refuse `section_owned` (409) |
| **owned** | **LLM** | person, `replace` + reason | archive the held version; new version `approved: false`, no facts, event `generate/draft`, `by: person`, reason |
| **owned** | **programmatic** (`bm2_*`) | system (materialize) | **S1-A:** archive the held version; new version `approved: false`, facts = `currency.demote_for_currency(prior)` (FINAL withdrawn, PROTECTED stands), `regenerated: {reason: "data_changed", from_version}`, `wording_review` = flips if any; event `reprocess/needs-re-bless`. **S1-B:** the same when a word flipped; with numbers only, approval and FINAL carried, event `reprocess/blessed`, reason `numbers_refreshed`. |

- A missing `reason` where one is required (S3) is `reason_required`.
- `replace` without a reason is refused.

### 4.2 Content hash
- `sha256` of canonical JSON (`sort_keys`, compact separators) of the section, without the state and provenance keys.
- State keys: `approved`, `approved_at`, `facts`, `stale`, `regenerated`, `wording_review`, `revised`, `version`, `saved_at`, `user_edited`.
- Provenance keys: `source`, `model_used`, `run_id`, `template_version`, `citation_report`, `notes`, `raw_data`, `original_*`.
- An exclusion list (rather than per-kind content fields) keeps new content fields counted as content by default.

### 4.3 The apical "needs re-review" state, and the phase
- The apical refresh does **not** set `stale`. `DiskPoolStore.has_stale_sections` (`workflow/store.py:149-159`) sends the phase back to UPLOADED for any stale `bm2_*` file [R]. Setting `stale` there would regress the phase.
- "Needs re-review" is the current version's manifest status `needs-re-bless`, with `approved: false`.
- LLM sections staled by invalidation keep today's shape (`approved: true`, `stale: true`, `needs-re-bless`). Making those two shapes one is C7's job; C2 records both the same way in the manifest.

---

## 5. Behaviour after C2, write path by write path

| # | Path | Today | After C2 |
|---|---|---|---|
| W1 | `workflow.steps.materialize_result_sections` (`steps.py:90-179`; callers `tooling/generate_report.py:407`, `POST /api/pool/materialize-sections` `pool_routes.py:285-296`) | Rewrites every `bm2_*` with `approved: False` (`:155`), `archive=False` (`:170`). [V] With nothing changed: approved+FINAL → `approved False, facts None`, still v1, manifest still `blessed`, no archive, content identical apart from flags (E1). [V] With the caption changed: the same, and the approved text is gone (E9). | Each section through §4.1. **Nothing changed: untouched** (approval kept). Changed and unowned: new draft version, archived. Changed and owned: S1. Returns `{ok, materialized, unchanged, needs_review:[{key, from_version, version, wording}]}`. Goes through `store`, not `pipeline.session_store.save_section` directly. |
| W2 | `workflow.steps.materialize_summary` (`steps.py:55-87`; `generate_report.py:417`; notebook) | Refuses when `approved` or `source != "generated"`; otherwise rewrites `archive=False`. [V] Wrote over a released (PROTECTED) Summary and dropped the fact (E2). | §4.1 with `by: system`, `source: generated`. Owned → noop `section_owned`. A chosen model run → noop `draft_from_elsewhere`. Identical → `unchanged`. Returns `{ok, written, paragraphs, noop?}`. |
| W3 | Background generation: `tooling/generate_report.background` (`:424-469`, writes `approved: False, archive=False` at `:461-468`, no guard); HTTP `/api/generate` returns text and the client saved it via save-section | No guard; [V in gate0-document] the approved text was lost | Core `write_section_content(…, by=person, via=cli\|api/v2, source="model")`. Owned → `section_owned` unless replace + reason. The CLI gains an explicit replace option that takes the reason; without it, it prints the refusal and saves nothing. The server-side "generate and save as draft" route is D2's, over the same call. |
| W4 | "Use run": `POST /api/prompts/summary/runs/{id}/{run}/use` (`prompt_routes.py:213-230`) | Unguarded `save_section(archive=True)`, `approved: False`, no event. [V] (same arguments, called directly): archived v1 and wrote v2 with no event, so `current_version_status` was `None` (E4). | §4.1, `by: person`, `source: model`. Owned → 409 `section_owned` unless `{replace: true, reason}`. Event `generate/draft` with `run_id` in `changes`. |
| W5 | `POST /api/session/save-section` (`session_routes.py:1037-1077`) | Writes posted content, `archive=False`, no guard; [V in gate0-document] lost an approved Background | **Retired** (S5): 410 `route_retired`. |
| W6 | `POST /api/session/approve` (`session_routes.py:767-964`): posts content, writes it `archive=True`, and also writes `identity.json`/`meta.json` | [V in gate0-document] empty `data` replaced the Summary with an empty approved v2 | **Retired** (S5). Replaced by the state-only accept (§6). Its legacy side effects (`identity.json`, copying uploads from `/tmp`) are not carried over: identity is C3's, uploads are M2's. |
| W7 | `accept_section_step` (`steps.py:656-717`) | State-only already; `archive=False`; event `edit/blessed` | Unchanged in effect. Adds `expect_version` (refuse `version_changed`), the noop `already_accepted` (approved, FINAL, not stale), key validation against the catalog, and the event's `by`/`via`. Through `store.record_section_event`. |
| W8 | `release_section_step` (`steps.py:720-767`); legacy `POST /api/session/unapprove` (`session_routes.py:1084-1134`) duplicates it | [V] A missing key answers `{"ok": True}` (E3); reason optional | Missing → 404 `no_section`. Reason required (S3) → `reason_required`. `expect_version`. Already released → noop `already_released`. The legacy route is retired (S5). |
| W9 | Restore: legacy `POST /api/session/{id}/restore` (`session_routes.py:1261-1335`) | Route logic; returns already approved with a fresh `approved_at` (`:1325`); no event; key unvalidated; 404 when the current file is absent [V] | New `restore_section_step` (§6.3). The legacy route is retired. |
| W10 | Discard: legacy `POST /api/session/discard-section` (`session_routes.py:1141-1161`) → `session_store.delete_section` | Deletes, archives nothing, history unreachable [V] (E6) | New `discard_section_step` (§6.4). The legacy route is retired. |
| W11 | Invalidation: `pipeline.pool_state.invalidate_pool_artifacts` (`pool_state.py:244-276`), `web_routes/pool_admin.invalidate_downstream` (`:189-227`) | Stales the data-dependent LLM sections and archives with event `reprocess/needs-re-bless` | **Behaviour unchanged.** Through `store.write_section_version` (version-numbered archive), the event gains `by: system, via: invalidate, reason: data_changed`. (It mints a new version for unchanged content; the identical `content_hash` tells the changelog. Making it state-only is optional cleanup, not C2.) |
| W12 | Pool reset `POST /api/pool/reset/{id}` (`session_routes.py:1581-1599`) | Unlinks every `bm2_*`, `genomics_*` and singleton except Background, with no archive | Each through `store.delete_section(…, event{cause: reset, by: person, reason: "pool reset"})`, so the last version of each section stays in `history/` (which reset already keeps). The dry-run listing is C8's. |
| W13 | Session reset `POST /api/session/reset/{id}` (`:1634-1678`) | Deletes everything, history included | **Not C2** (C8/M1: irreversible, type-to-confirm). |
| W14 | Genomics: `POST /api/session/{id}/regenerate-genomics-narrative` (`llm_routes.py:657-832`) | Clears the person's override for the organ (`:753-771`) with no backup, then force-regenerates | When an override exists for the organ: refuse `section_owned` unless `{replace: true, reason}`; archive `genomics_narrative_overrides.json` as a version under `history/genomics_narrative_overrides/` with event `generate`, `by: person`, reason; then clear. The interpretation caches it rewrites are machine output with no approval until C9. |
| W15 | `POST /api/session/{id}/genomics-narrative-override` (`session_routes.py:713-760`) | In-app edit; read-modify-write; no archive | **Retired** (S6). |
| W16 | Process caches: `_cache_methods_*`, `_cache_apical_narrative_*`, `_cache_interpretation_*` (`pipeline/process_integrated.py`; store rule `narrative/genomics_llm.py:180-231`); `POST /api/generate-genomics-narrative` with `force` (`llm_routes.py:625-654`) | Not sections: no approval exists, so nothing owned to protect | **No change in C2.** C9 turns them into sections written through §4.1 (§7). |
| W17 | Notebook: `_nb_cells_report.py:243-249` copies a reference `background.json` when absent | Raw copy, creation only | Becomes `write_section_content(…, by=person, via=notebook)` so the copy has its event. Creation only; low risk. |

The golden oracle's `run_process` writes no section file, so W1–W17 do not touch its payload [R] (§8.3).

---

## 6. The person's acts, as steps (`workflow/steps.py`)

All four take `expect_version`. A mismatch with the current version is `version_changed`: the person acts on
the version they read, not on one Process wrote in another tab. All four validate the key against the
section catalog (`workflow.section_catalog`), which the legacy restore route does not.

1. **`accept_section_step(dtxsid, key, store, *, expect_version, via)`**
   - Sets `approved`, `approved_at` and FINAL; clears `stale` and `wording_review` (unchanged).
   - Records `edit/blessed` on the same version.
   - Returns `{ok, section_key, approved, version, version_status}`.
2. **`release_section_step(dtxsid, key, store, *, reason, expect_version, via)`**
   - Applies the HUMAN_RELEASE demote (FINAL withdrawn, PROTECTED stands).
   - Records `revise/working` with the reason.
   - 404 when the section is absent.
3. **`restore_section_step(dtxsid, key, version, store, *, reason, expect_version, via)`**
   - Refused for programmatic sections (S7, `restore_not_meaningful`).
   - `no_such_version` when the version isn't in history; noop `already_current` when it is the current version.
   - Otherwise: archive the current version (if any); write the archived content as a new version.
     - **S2-A:** `approved: false`, facts `{PROTECTED}`, event `restore/working`, `from_version`.
     - **S2-B:** keep the archived approval, event `restore/blessed`.
   - `stale` = the current section's `stale` OR the restored version's: a data change after both still applies (C7 owns currency; restore never clears it).
   - Works when the current file is absent (after a discard).
4. **`discard_section_step(dtxsid, key, store, *, reason, expect_version, via)`**
   - Archives the current version, records `discard/discarded`, removes the file.
   - Allowed on owned sections, since nothing is lost: undo is restore.
   - The next machine write mints `max+1`, never an old number.

---

## 7. Q4 / C9: how these rules cover Methods, the apical-BMD narrative and the genomics interpretations

- The guarded write keys its rule on **`workflow.content_origin`**, not on a list of section keys, and on the one ownership predicate.
- `content_origin` already classifies `methods`, `bmd_summary` and `genomics` as LLM (`workflow/content_origin.py:42-48`), and the catalog already declares their files.
- So when C9 makes them section files, they inherit the LLM row of §4.1: absent → draft; own unowned draft → archived replacement; owned → kept (C7's draft-beside); a person's replace → archived and recorded.
- C9 must do three things:
  1. write them only through `write_section_content` (never a cache-only path);
  2. render them **from the section file**, not from `_cache_*` (today `rendering/latex_export.py:811-813, 859`). Otherwise an approved file and the printed text can differ, as they already do for apical sections (§9 R1);
  3. import any existing `genomics_narrative_overrides.json` text once, as versions with `cause: ingest, via: legacy_override, source: ingested`. Those versions are owned (§2). This is the ADR-0015 "content-store convergence".

---

## 8. Blast radius

### 8.1 Production callers that change

| caller | change |
|---|---|
| `workflow/ownership.py:111-179` | `is_owned`; `protection_level` keyed on it |
| `workflow/store.py:84-86` (protocol), `:174-176` (DiskPoolStore) | the §3.4 methods replace `save_section` |
| `pipeline/session_store.py:231-422` | version-numbered archives, next = max+1, required event with the new fields, `delete_section` archives first, readers tolerate legacy names and `edit` |
| `workflow/steps.py:55-87, 90-179, 656-767` | W1, W2, W7, W8; new restore and discard steps (steps.py stays under ~1000 lines) |
| `workflow/section_writes.py` (new) | §4 |
| `pipeline/pool_state.py:237-276`, `web_routes/pool_admin.py:189-227` | through the store; event fields (W11) |
| `web_routes/prompt_routes.py:213-230` | W4 |
| `web_routes/llm_routes.py:657-832` | W14 |
| `web_routes/session_routes.py:713-760, 767-964, 1037-1161, 1261-1335` | retired (S5, S6) |
| `web_routes/session_routes.py:1581-1599` | W12 |
| `tooling/generate_report.py:424-469` | W3, plus the CLI replace option |
| `notebooks/_nb_cells_report.py:243-249` | W17 (and the notebook is regenerated) |
| new `web_routes/v2_sections.py` (or the name the kit uses) | the v2 routes (contract.md); registration in `background_server.py` is the orchestrator's |
| the kit's error-code module (MODULES §4.2) | C2's codes; `StepError` gains `code` if the kit has not added it yet |

### 8.2 Tests that pin today's behaviour and must change

Baseline before C2: these 15 files pass, **254 passed** [V].

| test | why it changes |
|---|---|
| `tests/unit/test_workflow_steps.py:29-75` (`FakeStore`) | the protocol gains the §3.4 methods |
| `tests/unit/test_workflow_steps.py:251-256` | asserts `result == {"ok": True, "materialized": []}`; the result gains `unchanged`/`needs_review` |
| `tests/unit/test_workflow_steps.py:278-302` | still holds under S1-A and S1-B (a flip un-approves). The comment at `:301` ("inform-signal … provisional again") changes; add assertions on the archive and the `reprocess/needs-re-bless` event. No test pins today's "nothing changed → un-approved"; the new test pins the opposite (§10). |
| `tests/unit/test_workflow_authoring_steps.py:19-46` (`FakeSectionStore`) | protocol; `save_calls` tuples |
| `tests/unit/test_workflow_authoring_steps.py:80-82` | `save_calls == [("background", False)]` becomes `record_section_event` |
| `tests/unit/test_workflow_authoring_steps.py:123-135, 145-150` | release without a reason → `reason_required`; the result shape gains `version` |
| `tests/unit/test_workflow_authoring_steps.py:137-142` | a missing section now raises 404 `no_section` |
| `tests/unit/test_version_cause_snapshots.py:81-122` | the transient marker becomes a required event argument |
| `tests/unit/test_version_cause_snapshots.py:296-314` | the approve route is retired; rewrite on the v2 accept route |
| `tests/unit/test_version_cause_snapshots.py:348-360` | release without a reason → `reason_required` (S3) |
| `tests/unit/test_session_store.py:72-148` | `save_section` → `write_section_version` with an event; the counts still hold |
| `tests/unit/test_session_store.py:151-185` | `delete_section` archives the current version: history 1 → 2 at `:185` |
| `tests/integration/test_session_lifecycle.py:99-235` (approve and unapprove), `:238-305` (history via approve) | the routes are retired; reseed the section files and use the v2 routes |
| `tests/unit/test_review_fixes_2026_09_24.py:40-48` | approve route retired |
| `tests/unit/test_dtxsid_validation.py:93-105` | body-id traversal via the approve route; re-point it at a body-id route that remains |
| `tests/unit/test_prompt_routes.py:65` | asserts `.json() == {"ok": True}`; the response gains `version` |
| `tests/unit/test_session_files.py:75-95` | override route retired (S6) |

Exercised and expected to pass unchanged:
- `test_invalidate_pool_stale_by_origin.py:119-130`, `test_reprocess.py:83`, `test_workflow_engine.py:245` (all use `accept_section_step`);
- `test_version_cause_snapshots.py:131-213, 238-252` (cause names kept; archives counted by glob);
- `test_workflow_ownership.py` (add a released-section case for `protection_level`);
- `test_protection_marks.py`, `test_workflow_labels_guard.py`.

### 8.3 The golden oracle (`tests/integration/test_process_integrated_golden.py`)
**It does not move** [R].
- It compares `run_process`'s payload.
- `run_process` writes no section file: `materialize_result_sections` runs after it, only from `generate_report.process_async:407` and the materialize route.
- The genomics override read (`process_integrated.py:435`) is unchanged.
- No fixture under `tests/fixtures/` has `approved: true` or `facts` [R, grep], so `protection_map` stays `{}` and render goldens stay byte-identical.

The guard still runs after every step of the build (cross-cutting constraint).

### 8.4 Existing sessions on disk
- **Sandbox store** (`sessions/`, read-only survey [V]):
  - 118 section files: **0 approved, 0 with facts, 0 archives, 0 manifests**;
  - 103 `source: generated` (the `bm2_*` and `summary`); 15 Backgrounds with no `source`;
  - `history/` holds only the pins (`_method_profile`).
  - Workspaces `guest` and `NAME`: no section files [V].
  - Nothing here needs migrating.
- **The host store is not visible from the sandbox.** Run the survey (`/workspace/ui-team/_scratch/spec-c2/scripts/survey.py <sessions dir>`) there before deploying. It reports:
  - approved files;
  - files whose `approved` flag disagrees with the manifest status (the aftermath of E1/E9: manifest `blessed`, file unapproved);
  - duplicate archived versions (E5).
- **No migration writes.** Readers tolerate:
  - timestamp-named archives;
  - `edit` events and events without `by`/`via`;
  - Backgrounds without `source` (read as `model` for §4.1; new writes stamp it).
- The v2 history route sets `inconsistent: true` when the current version's last status is `blessed` but the file is unapproved, or when two archives claim one version. D1 shows it; nothing repairs it silently.

---

## 9. Risks

- **R1. An approved apical file is not what prints.**
  - The deliverable renders apical sections from `_cache_sections_*`, re-filtered per view (`rendering/latex_export.py:762-788`) [R]. Summary and Background render from their files (`:685, 743-747`).
  - C2 makes the approval honest relative to the file, which equals the cache at materialize time. A view-filter change can still print something different from the approved file.
  - D1 should preview the section from the cache. Whether apical sections render from their files is a C9/D3 question.
- **R2. Re-review noise (S1-A).** Every data change re-opens every approved apical section. D1 must group these and show the diff and `wording_review`.
- **R3. A released Summary is never refreshed automatically.** PROTECTED stands after release, so `materialize_summary` keeps it. New text needs a person's replace or discard. D1/D2 must say so.
- **R4. Concurrency.** There is no lock. `expect_version` protects a person's acts; C5's run lock covers Process; a manifest append and a content write from two processes can still interleave.
- **R5. Merge to `main`.** Retiring the legacy routes (S5, S6) breaks the old front-end that still exists there.
- **R6. The host store is unknown** (§8.4).
- **R7. Event writes are no longer fail-soft.** A full or read-only disk now refuses the act (`history_write_failed`) instead of changing text without a record. This is intended, and new.
- **R8. Silent defaults in code.** `by`, `via` and `source` are required arguments. A missing one is a programming error, never a default.

---

## 10. Order of the changes, and the tests that pin the new behaviour

Each step leaves `smart` and `guard` green.

1. **Ownership.** `is_owned`, `may_machine_write`, `protection_level`.
   - New test: a released section is GUARDED and not machine-writable.
2. **Version store.** Version-numbered archives, next = max+1, the event record (§3.2), the §3.4 store methods, the legacy readers.
   - New tests: E5 replayed (no collision); E8 replayed (a new draft after discard is `max+1`, status `draft`); the event write fails before the content changes.
3. **Guarded write** (§4), unit-tested with a fake `PoolStore`, one test per row of §4.1.
4. **W1, W2.**
   - New tests: E1 replayed (an approved apical section with nothing changed keeps approval, facts, version, bytes); E9 replayed (changed: archived, `needs-re-bless`, from_version); a released Summary is not overwritten (E2 replayed); a chosen model run is not overwritten.
5. **W7–W10 as steps.**
   - New tests: `expect_version`; required reasons; release of a missing key is 404 (E3); restore after discard (E6); restore of `bm2_*` refused; restore result per S2.
6. **Person-initiated writers** W3, W4, W14 (+ the CLI option); W11, W12 event fields.
7. **v2 routes**, thin, through the kit envelope; integration tests through the FastAPI client against a scratch `SESSIONS_DIR`.
8. **Retire the legacy routes** (S5, S6). Migrate the §8.2 tests.
9. Run `run-tests.sh smart`, then `guard`. The one known failure is `test_docx_generator.py::test_yaml_page_breaks_land_as_page_break_before`.

**Acceptance criteria** (each a test):
- No production code calls `pipeline.session_store` section writes except through the store's §3.4 methods (grep test).
- Every section write appends exactly one event with `by` and `via`.
- No content change happens without an archive of the superseded version.
- An owned LLM section's bytes never change through a system write.
- An owned apical section's bytes change only together with an archive and a `reprocess` event.
- `protection_level` and `may_machine_write` agree on every fact combination.

---

## 11. Evidence

**Verified** (scratch, `SESSIONS_DIR=/workspace/ui-team/_scratch/spec-c2/sessions`):
- **E1:** warm `materialize_result_sections` over an accepted `bm2_body-weight` (v1, blessed, FINAL+PROTECTED). After: `approved False`, `facts None`, still v1, manifest still `blessed`, no archive. Content identical apart from the flags.
- **E2:** release of the Summary gave `facts ['protected']`, `may_machine_write False`, `protection_level OPEN`. `materialize_summary` then returned `written: True` over it.
- **E3:** `release_section_step` on `bm2_no-such-thing` → `{'ok': True, …}`.
- **E4:** `save_section` called with the "use run" route's arguments (directly; the route itself not run) over the accepted Summary: v1 archived, v2 unapproved, no event, status `None`.
- **E5:** accept, then invalidate, then the approve route. v3's archive (named by `approved_at`) was overwritten by v4. The file and the archive both read v4, and the manifest has two v4 lines describing different texts.
- **E6:** after discard, restore and history both answered 404 "No approved 'summary' section found".
- **E8:** accept, discard, `materialize_summary`: the new draft is v1, and its manifest status is `blessed`.
- **E9:** a changed caption on an accepted `bm2_hormones`: un-approved, no archive, status `blessed`.
- **Survey:** §8.4.
- **Baseline:** 254 tests passed in the 15 files of §8.2.

**Read:** everything else, with `file:line`.
