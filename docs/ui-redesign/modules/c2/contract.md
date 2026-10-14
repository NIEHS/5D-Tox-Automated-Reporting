# C2 — Owned content is never overwritten by a machine: contract (revision 2)

Every new or changed route answers refusals in the MODULES §4.2 envelope:

```json
{"error": {"code": "…", "status": 409, "message": "…verbatim…", "say": "…", "fix": "D1", "details": {}}}
```

A success that did nothing carries `"noop": {"code": "…", "say": "…"}`. `code` and `say` live in the backend's closed error list (the kit's module), next to the `StepError` that raises them. `message` texts are verbatim. `{…}` are filled in from the request.

## Refusals C2 adds

| code | status | message (verbatim) | say (plain words) | fix | raised by |
|---|---|---|---|---|---|
| `section_owned` | 409 | `"'{key}' is approved or protected; {act} would replace its text. Release it first, with a reason."` | "This section has been approved, or you chose to keep it, so it can't be replaced automatically. To replace it, reopen it and say why." | D1 | the gate (§3 rule 5): save-section, use run, CLI background, discard of an approved section, regenerate without force |
| `section_key_invalid` | 400 | `"'{key}' is not a section of this report"` | "There is no section by that name in this report." | D1 | every section step (rule 1); replaces today's unvalidated restore key |
| `section_not_found` | 404 | `"No '{key}' section to {act}"` (accept keeps today's `"No '{key}' section to approve"`) | "This section hasn't been written yet, so there is nothing to {act}." | D2 (generate it) | accept, release (today ok), discard, approve-route fence |
| `reason_required` | 400 | `"A reason is required to {act} '{key}'"` | "Please say why. The reason is kept with the section's history." | D1 | release, restore, discard, any forced write (◆ D3) |
| `version_not_found` | 404 | `"Version {n} of '{key}' not found"` | "That version of the section doesn't exist." | D1 | restore, history read |
| `version_content_missing` | 409 | `"Version {n} of '{key}' is recorded but its text was not kept"` | "This version is listed in the history, but its text was lost before history was kept reliably. It can't be restored." | – | restore of a manifest version with no archive (old sessions) |
| `approve_content_retired` | 409 | `"Approving no longer saves text; accept '{key}' as it is, or change it outside the application and bring the new version in"` | "Approving can't change the text. Accept the section as it is, or edit it in Word or Overleaf and bring that version back." | D4 | `POST /api/session/approve` when the posted content differs from the file (◆ D5) |
| `approve_via_accept` | 400 | `"save-section cannot approve a section; use accept"` | "Saving doesn't approve. Use Accept." | D1 | `POST /api/session/save-section` with `approved: true` |

**No-ops** (200, with `noop`):

| code | say | from |
|---|---|---|
| `already_accepted` | "This section is already accepted and nothing has changed since." | accept |
| `not_approved` | "This section isn't approved, so there is nothing to reopen." | release |
| `already_current` | "That version is already the current one." | restore (today: `"Already the current version"`) |

**Not refusals, but reported** in step results and in the trail: a `held` write (a machine had new text for an owned section and didn't apply it) and a `needs_review` (an approved apical section's printed content changed; ◆ D2). They are carried in `materialize-sections` responses and later in C5's Process stream (`{"event":"step", …}` / result summary).

## Routes added (new `web_routes` module; registration by the orchestrator)

All take `{id}` through the `Dtxsid` parameter and `{key}` validated by the catalog.

| Route | Body | 200 response | Refusals |
|---|---|---|---|
| `POST /api/v2/studies/{id}/sections/{key}/accept` | `{}` | `{section_key, approved: true, version, version_status: "blessed", noop?}` | `section_key_invalid`, `section_not_found` |
| `POST /api/v2/studies/{id}/sections/{key}/release` | `{reason}` | `{section_key, approved: false, version, version_status: "working", noop?}` | `section_key_invalid`, `section_not_found`, `reason_required` |
| `POST /api/v2/studies/{id}/sections/{key}/restore` | `{version, reason}` | `{section_key, version, from_version, approved, version_status}` (`approved` per ◆ D3) | `section_key_invalid`, `version_not_found`, `version_content_missing`, `reason_required`, `noop already_current` |
| `POST /api/v2/studies/{id}/sections/{key}/discard` (only if ◆ D4 keeps it) | `{reason}` | `{section_key, archived, version}` | `section_key_invalid`, `section_not_found`, `section_owned`, `reason_required` |
| `GET /api/v2/studies/{id}/sections/{key}/history` | – | `{section_key, current_version, current_status, versions: [{version, archived, status, approved_at}], events: [ …§5 lines… ]}`; works when the current file is absent | `section_key_invalid`, `section_not_found` (no file and no history) |
| `GET /api/v2/studies/{id}/sections/{key}/history/{version}` | – | the version's section JSON | `section_key_invalid`, `version_not_found`, `version_content_missing` |

Each is a thin driver: parse → `accept_section_step` / `release_section_step` / `restore_section_step` / `discard_section_step` / `section_writes.section_history` → serialize. Every mutating route is followed by the kit's state re-read (MODULES §4.1).

## Routes changed

| Route | Change |
|---|---|
| `POST /api/session/approve` | fenced (◆ D5): state-only accept when the posted content equals the file; otherwise `approve_content_retired` / `section_not_found`; no longer writes `identity.json`/`meta.json` |
| `POST /api/session/save-section` | through the gate: `section_owned`, `approve_via_accept`; archives what it replaces; records an event |
| `POST /api/session/unapprove` | calls `release_section_step`: `section_not_found`, `reason_required`, `noop not_approved`; envelope |
| `POST /api/session/discard-section` | calls `discard_section_step` (archives first; `section_owned`, `reason_required`) |
| `POST /api/session/{id}/restore` | calls `restore_section_step` (key validated; works after a discard; approval per ◆ D3) |
| `GET /api/session/{id}/history/{key}` | unchanged shape; reads through `section_history`, so it works after a discard and lists unique archives |
| `POST /api/prompts/{section}/runs/{id}/{run}/use` | through the gate (`section_owned` ◆ D6); response `{ok, version}` |
| `POST /api/pool/materialize-sections/{id}` | response gains `unchanged`, `needs_review`, `held` (`materialized` = files written) |
| `POST /api/session/{id}/regenerate-genomics-narrative` | archives the override and records an event before clearing it; takes `reason` (◆ D3) |
| `POST /api/generate-genomics-narrative` | `force: true` without `reason` → `reason_required` |
| `POST /api/session/{id}/genomics-narrative-override` | archives the prior override before writing (still retired from the new interface by Q1) |
| `POST /api/pool/reset/{id}` | archives each section and records `discard` events before deleting |

## Routes retired

None removed outright (◆ D5: the old front-end may still call them). From the **new interface**, never call:
- `POST /api/session/approve` (use `…/accept`);
- `POST /api/session/save-section` (D2's server-side generate replaces it);
- `POST /api/session/discard-section` (◆ D4);
- `POST /api/session/{id}/genomics-narrative-override` (no in-app editing, Q1).

When the old interface is retired, these four can be deleted.
