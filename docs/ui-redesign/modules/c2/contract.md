# C2 — contract: refusals, no-ops, routes

Built on the shared contracts of MODULES §4: the error envelope (§4.2) and the state read model (§4.1).
Codes go in the kit's closed code list; `say` is written there, next to the code. Placeholders in
`{braces}` are filled by the backend. "Decision" marks text that depends on spec §1.

## 1. Refusals C2 adds

Envelope: `{"error": {"code", "status", "message", "say", "fix", "details"}}`.

| code | status | message (verbatim) | say | fix | details |
|---|---|---|---|---|---|
| `section_owned` | 409 | `'{key}' is held by a person (approved, open for rework, or brought back from an edited file); a machine may not replace its text. To replace it, ask again with replace and a reason; the current text is kept in its history.` | This section is yours: a person approved it or is reworking it, so the app won't overwrite it. If you want the new text instead, choose Replace and say why; the current text is kept and can be brought back. | D2 (regenerate), D1 | `{key, version, approved, maturity}` |
| `reason_required` | 400 | `A reason is required to {act} '{key}'; it is kept in the section's history.` (`{act}`: release, discard, restore, replace) | Say why in a few words. The reason is kept with the section so the next reader knows what happened. | D1 | `{act}` |
| `no_section` | 404 | accept: `No '{key}' section to approve` (today's text, `steps.py:680-682`); release: `No '{key}' section to release`; discard: `No '{key}' section to discard` | This section has no text yet, so there is nothing to {act}. Result sections and the Summary appear after Process; the Background after it is generated. | P1 (results, Summary), D2 (Background) | `{act}` |
| `bad_section_key` | 400 | `'{key}' is not a section of this report` | That section isn't part of this report's structure. Reload the list of sections. | D1 | `{key}` |
| `version_changed` | 409 | `'{key}' changed since it was opened: expected version {expected}, current version {current}` | This section changed after you opened it (Process may have run again). Read the new version before you {act} it. | D1 | `{expected, current}` |
| `version_required` | 400 | `expect_version is required: the version of '{key}' the person read` | The screen didn't say which version you read. Reload the section. | D1 | – |
| `no_such_version` | 404 | `Version {version} of '{key}' not found` | That version isn't in this section's history. | D1 | `{version, versions: [...]}` |
| `restore_not_meaningful` (decision S7) | 409 | `'{key}' is rebuilt from the data on every Process; an older version can be compared, not restored` | Result sections are written from the data each time Process runs, so the report always prints the current numbers. You can compare an older version, but not bring it back. | D1 | `{key}` |
| `history_write_failed` | 500 | `Could not keep the previous version of '{key}' in its history: {error}. Nothing was changed.` | The app couldn't save a copy of the current text before changing it, so it changed nothing. Tell the person who maintains the app; the disk may be full or read-only. | null | `{error}` |
| `route_retired` (decision S5/S6) | 410 | `{route} is retired: section text is no longer posted to the app (ADR-0018; decision Q1). Use {replacement}.` | This action was removed: text is edited in Word or Overleaf, not in the app. | null | `{route, replacement}` |

## 2. No-ops ("success that did nothing", MODULES §4.2)

Answered with 200 and `"noop": {"code", "say"}`, never a bare `ok`.

| code | where | say |
|---|---|---|
| `already_accepted` | accept on a section approved, FINAL and not stale | This section was already approved; nothing changed. |
| `already_released` | release on a section already open for rework | This section is already open for rework; nothing changed. |
| `already_current` | restore of the current version (message kept: `Already the current version`) | That version is already the current one; nothing changed. |
| `unchanged` | a machine write whose text is identical | The new text is the same as the current text; nothing was written. |
| `section_owned` | an automatic write (materialize, Process) over a held section | Kept the text a person holds; the app's new version was not written over it. |
| `draft_from_elsewhere` | `materialize_summary` over a Summary chosen from a model run | Kept the Summary chosen from a model run; the automatic draft was not written over it. |

## 3. Routes added (`/api/v2`, thin drivers over `workflow.steps`)

`{id}` is validated by the existing `Dtxsid` dependency. `{key}` is validated against the section
catalog (`bad_section_key`). Every response that returns a section uses the read model's section
fields (MODULES §4.1).

**`POST /api/v2/studies/{id}/sections/{key}/accept`**
```json
// request
{"expect_version": 3}
// 200
{"section": {"key": "summary", "version": 3, "approved": true, "maturity": "final",
             "version_status": "blessed", "machine_may_write": false, "stale": false}}
```
Refusals: `bad_section_key`, `version_required`, `no_section`, `version_changed`, `history_write_failed`. No-op: `already_accepted`.

**`POST /api/v2/studies/{id}/sections/{key}/release`**
```json
{"reason": "tone of paragraph 2", "expect_version": 3}
// 200
{"section": {"key": "summary", "version": 3, "approved": false, "maturity": null,
             "version_status": "working", "machine_may_write": false}}
```
Refusals: the accept list plus `reason_required`. No-op: `already_released`.

**`POST /api/v2/studies/{id}/sections/{key}/restore`**
```json
{"version": 1, "reason": "v2 dropped the hepatic finding", "expect_version": 3}
// 200 (decision S2-A shown; under S2-B approved/maturity/version_status follow the restored version)
{"section": {"key": "summary", "version": 4, "restored_from": 1, "approved": false,
             "maturity": null, "version_status": "working", "machine_may_write": false},
 "archived": "v0003.json"}
```
Allowed when the current file is absent (after a discard); then `expect_version` is `null`.
Refusals: `bad_section_key`, `version_required`, `no_such_version`, `version_changed`, `reason_required` (decision S3), `restore_not_meaningful` (S7), `history_write_failed`. No-op: `already_current`.

**`POST /api/v2/studies/{id}/sections/{key}/discard`**
```json
{"reason": "regenerate from the new data", "expect_version": 3}
// 200
{"section": {"key": "summary", "version": null}, "discarded_version": 3, "archived": "v0003.json"}
```
Refusals: `bad_section_key`, `version_required`, `no_section`, `version_changed`, `reason_required`, `history_write_failed`.
Strength for `<ConfirmAct>`: **costly** (it is undone by restore).

**`GET /api/v2/studies/{id}/sections/{key}/history`** (side-effect-free)
```json
{"key": "summary",
 "current": {"version": 4, "approved": false, "version_status": "working", "content_hash": "sha256:…"},
 "versions": [{"version": 1, "content_hash": "sha256:…", "current": false},
              {"version": 4, "content_hash": "sha256:…", "current": true}],
 "events": [{"version": 1, "cause": "generate", "status": "draft", "ts": "…", "by": "system",
             "via": "materialize_summary", "who": null, "source": "generated", "content_hash": "sha256:…"}],
 "inconsistent": false}
```
`events` are the spec §3.2 records, oldest first. Legacy lines are passed through with `by: null`.
`current` is `null` after a discard. Refusal: `bad_section_key`. A section with no file and no history → `no_section` (404).

**`GET /api/v2/studies/{id}/sections/{key}/versions/{n}`**
→ `{"key", "version", "content": {…the section JSON as archived…}}`. Refusals: `bad_section_key`, `no_such_version`.

The report-wide changelog route (the merge of every section's events) is **C11's**, built on these records.

## 4. Routes changed

| route | change |
|---|---|
| `POST /api/pool/materialize-sections/{id}` | Behaviour per spec W1. Response `{"ok": true, "materialized": [...], "unchanged": [...], "needs_review": [{"key", "from_version", "version", "wording": [...]}]}`. Errors are wrapped in the envelope. C5 later folds this into the one Process endpoint. |
| `POST /api/prompts/summary/runs/{id}/{run}/use` | Optional body `{"replace": true, "reason": "…"}`. Over a held Summary without it → `section_owned` (409); `replace` without a reason → `reason_required`. 200 → `{"ok": true, "version": 5, "replaced_version": 4}`. |
| `POST /api/session/{id}/regenerate-genomics-narrative` | Body adds `{"replace", "reason"}`. When a person's override exists for the organ: `section_owned` (409, `details.organ`) without them. With them, the override file is archived under `history/genomics_narrative_overrides/` with its event before it is cleared. |
| `POST /api/pool/reset/{id}` | Response unchanged. Each deleted section is archived first with a `reset` event (spec W12). |

## 5. Routes retired (410 `route_retired`; decisions S5, S6)

| route | replacement |
|---|---|
| `POST /api/session/approve` | `POST /api/v2/studies/{id}/sections/{key}/accept` |
| `POST /api/session/save-section` | none (no in-app editing, Q1); generation saves server-side (D2, over the core write) |
| `POST /api/session/unapprove` | `…/release` |
| `POST /api/session/discard-section` | `…/discard` |
| `POST /api/session/{id}/restore` | `…/restore` |
| `POST /api/session/{id}/genomics-narrative-override` | none (Q1); existing overrides keep rendering until C9 imports them |
| `GET /api/session/{id}/history/{key}` | `GET …/sections/{key}/history`. Kept read-only until D1 ships, then retired. |

## 6. What C2 fills in the state read model (MODULES §4.1, `sections[]`)

| field | source after C2 |
|---|---|
| `machine_may_write` | `workflow.ownership.may_machine_write(section)` (the one definition) |
| `maturity` (add to the §4.1 example) | `labels.maturity_rung(section_facts(section))`: `"final"`, `"working_draft"`, `"first_draft"` or `null` |
| `version` | the current file's `version` |
| `version_status` | the last manifest status for the current version: `draft`, `blessed`, `working`, `needs-re-bless` (`discarded` only in history) |
| `source` | the section's `source` (`generated`, `model`, `ingested`; Background read as `model` when absent) |
| `wording_review`, `regenerated`, `stale` | unchanged, from the file |
