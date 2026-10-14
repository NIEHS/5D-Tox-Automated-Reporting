# M1 Studies: API contract

Every new route is under `/api/v2/`, is a thin driver (parse → core → serialize),
answers errors in the §4.2 envelope (`MODULES.md`) and has no side effect on a
`GET` (C4). The `{id}` in a path is checked with `common.dtxsid.validate_dtxsid`
(`common/dtxsid.py:30`, the permissive session-id pattern
`^DTXSID[A-Za-z0-9_-]{1,64}$`), because suffixed sessions are opened too.
**Creation** requires the strict pattern `^DTXSID\d+$` (`narrative/chem_resolver.py:52`).

Shared contracts used as they are: `GET /api/v2/studies/{id}/state` (§4.1), the
error envelope (§4.2), the confirm/dry-run object (§4.3). The extensions M1 asks for
(spec §10, R1–R4) are marked **[request]**.

Evidence:
- **[V]**: verified by running the core functions on a scratch copy of the 32
  session folders of 2026-10-14, or the resolver against PubChem from the sandbox;
- **[R]**: read from the code.

---

## 1. Existing routes this replaces or draws on

| Existing | Where | Its use for M1 |
|---|---|---|
| `GET /api/admin/sessions/summary` | `web_routes/background_server.py:498-541` | Replaced for M1 by `GET /api/v2/studies`. It has no phase and no identity, and it counts `integrated.json` and similar files as "sections" [V, analysis] |
| `POST /api/resolve` | `web_routes/background_server.py:426-454` | Replaced for M1 by `GET /api/v2/chemicals/{dtxsid}`. Today it answers 200 with empty fields when nothing is found [V] |
| `GET /api/wizard/{id}/identity` | `web_routes/wizard_routes.py:77-89` | Superseded by the `identity` in §4.1 and in the study row |
| `POST /api/session/reset/{id}` | `web_routes/session_routes.py:1634-1678` | Replaced by the delete pair (§2.8–2.9); its logic (rmtree and clearing the in-memory upload registries) moves into the core step. It answers 200 "No session to reset" for an absent id |
| Bookshelf predicates `has_generated_report`, `clone_record`, `companion_of`, `_members` | `web_routes/bookshelf_routes.py:81-122` | Their logic feeds `kind`, `relations` and `bookshelf`; to move to core (R7) |
| `report_of`, `published_date` | `narrative/prompt_workshop.py:69-101` | Feed `published` (R7) |
| `study_definition_name`, `current_definition_name`, `definition_name`, `DEFAULT_DEFINITION` | `document_model/document_definition.py:210-229` | Feed `format` |
| `read_pin`, `pin_definition`, `drift` | `document_model/definition_pin.py:77-151` | Feed `format.pin` (through §4.1 `pins.definition`) |
| `resolve_chemical`, `_pubchem_get` | `narrative/chem_resolver.py:403-463`, `:129-144` | The lookup. **CHANGED** below: `_pubchem_get` returns None for both "not found" and "unreachable" [R], so the cause is lost |

---

## 2. Endpoints

### 2.1 `GET /api/v2/studies`: the list, grouped by chemical (NEW)

**Core:** NEW `workflow.studies.list_studies()`. For each non-empty, non-`_`, non-`.`
folder of `SESSIONS_DIR`:
- `WorkflowEngine(id).state()` (`workflow/engine.py`);
- `workflow.studies.session_kind(id)`, `relations(id)` and `stands(state, kind)` (§3);
- the moved Bookshelf predicate;
- `document_definition.describe_format(id)` (NEW, §2.4);
- `last_changed`.

Then group by `chemical_dtxsid`. One unreadable session yields a row with `notes`,
never a failed list.

It costs 1–224 ms per session [V]; about 1 s for 32.

**Request:** none.

**Response 200:**
```json
{
  "chemicals": [
    {"dtxsid": "DTXSID…", "name": "…|null", "casrn": "…|null",
     "primary": "<session id>|null",
     "can_create": false,
     "sessions": [ StudyRow, … ]}
  ],
  "unassigned": [ StudyRow, … ],
  "generated_at": "2026-10-14T13:05:00Z"
}
```
- `primary` is the chemical's study (kind `study`) or report (kind `report`).
- `can_create` is true when the chemical has no primary session.
- `sessions` is ordered: the primary first, then `member`s, then `companion`, then
  `other`.
- Chemicals are ordered by their newest `last_changed`, most recent first.
- `unassigned` holds sessions whose id carries no `DTXSID\d+` prefix.

**StudyRow:**
```json
{
  "id": "DTXSID50469320",
  "kind": "study | report | member | companion | other",
  "chemical_dtxsid": "DTXSID50469320 | null",
  "chemical_dtxsid_from": "id | id_prefix",
  "identity": {"name": "…|null", "casrn": "…|null", "short_name": "…|null",
               "source": {"kind": "lookup | stated | unknown", "service": "PubChem|null", "confirmed_at": "…|null"}},
  "stands": {"phase": "APPROVED | … | null", "say": "…",
             "next": {"say": "…", "fix": "M2|M3|M6|P1|D1|D3|null"} },
  "processed": true,
  "last_changed": "2026-10-12T11:41:25Z",
  "format": FormatSummary,
  "published": {"report": "NIEHS-10", "date": "2023-03", "nbk": "NBK589955"} ,
  "bookshelf": {"on_shelf": true, "url": "/Bookshelf/DTXSID50469320", "say": "On the Bookshelf (draft)"},
  "relations": {"parent": null, "members": [], "companion": "DTXSID50469320_published", "twin": null,
                "others": ["DTXSID50469320_nb"]},
  "actions": {"open": {"allowed": true},
              "delete": {"allowed": true, "code": null, "say": null}},
  "notes": []
}
```
- `published` is null for an unpublished study.
- `stands.next` is null when there is no next step (published content).
- `identity.source.kind == "unknown"` for sessions made before M1 (no provenance on
  file).
- `processed` is the read model's `processed`.
- `last_changed` is the newest modification time among the session's top-level
  files, `files/` and `history/` ("the last change on disk").
- `notes[]` is `{level: "warn|error", code, say}`.

**FormatSummary** (in the row; the detail in §2.2 adds `brings`):
```json
{"definition": "studies/DTXSID50469320/document", "source": "study | default | session | pinned",
 "era": "eras/niehs-2023", "title": "NIEHS Report, as published in March 2023 (NIEHS-07 … 10)",
 "title_short": "NIEHS Report, March 2023", "changes": 0,
 "say": "This chemical has a published report, NIEHS-10 (March 2023). The study is written in that book's format: the NIEHS Report as published in March 2023, unaltered."}
```
`source` comes from the same derivation as §4.1 `pins.definition.source`:
- `session`: the session's own `document.yaml` (`document_model/document_config.py:46`);
- `pinned`: a FIXED snapshot;
- `study`: `templates/studies/<id>/document.yaml`;
- `default`: `eras/niehs-2026`.

`title` comes from the era's declared title (Q-M1-6; **CHANGED** era YAMLs or a table
beside `DEFAULT_DEFINITION`). `changes` counts the study definition's `changes`.

**Errors:** 500 `list_failed` only if `SESSIONS_DIR` itself can't be read.

### 2.2 `GET /api/v2/studies/{id}`: one session (NEW)

**Core:** NEW `workflow.studies.study_summary(id)`. The same row as §2.1, plus
`detail`:
```json
{ "…StudyRow fields…": "…",
  "detail": {
    "banner": {"level": "info|warning", "say": "…", "links": [{"say": "…", "href": "/app/studies/…|/Bookshelf/…"}]} ,
    "format": {"…FormatSummary…": "…",
               "brings": [{"what": "document_definition|report_view|deposit|authored_content",
                           "path": "templates/studies/DTXSID50469320/view.yaml", "say": "…"}],
               "pin": {"mode": "track|fixed|null", "pinned_at": "…|null", "pinned_by": "user|default|null"},
               "chosen_by": "id"},
    "members": [ StudyRow ]
  }
}
```
- `banner` is null for a plain study.
- `pin.mode` is null when not pinned (NIEHS-10's study has no `document_definition.json` [V]).
- `members` is only present for kind `report`.

**Errors:**
- 400 `invalid_study_id`;
- 404 `study_not_found`: the folder is absent or empty. **No folder is created.**

### 2.3 `GET /api/v2/studies/{id}/state` (shared, §4.1)

As fixed at Gate 0. **[request]** R1 and R2 add these fields, built by the same
functions as the row:
- `kind`;
- `chemical_dtxsid`;
- `relations`;
- `stands`.

### 2.4 `GET /api/v2/studies/{dtxsid}/creation-check` (NEW)

**Core:** NEW `workflow.studies.creation_check(dtxsid)`, using
`document_model.document_definition.describe_format(dtxsid)` (NEW; wraps
`current_definition_name`, `load_definition`, the era title, the files under
`templates/studies/<id>/`, and the definition hash from `definition_pin.definition_hash`).
It is side-effect-free and needs no network.

**Response 200:**
```json
{"dtxsid": "DTXSID7020182", "exists": false, "existing": null,
 "related_sessions": [ {"id": "…", "kind": "…", "say": "…"} ],
 "format": {"…FormatSummary + brings…": "…", "hash": "cdbd602e773aee83"},
 "published": null}
```
- `existing` is `{id, kind}` when the session exists.
- `related_sessions` are other sessions with this chemical's DTXSID.

**Errors:**
- 400 `invalid_study_id`: fails the permissive pattern;
- 400 `study_id_has_suffix`: passes the permissive pattern but not `^DTXSID\d+$`.

### 2.5 `GET /api/v2/chemicals/{dtxsid}` and `…/structure.png`: the lookup (NEW, with a CHANGED core)

**Core:** NEW `workflow.studies.lookup_chemical(dtxsid)` over `narrative.chem_resolver.resolve_chemical`
(`narrative/chem_resolver.py:403`), with these changes:
- **CHANGED** `_pubchem_get` (`:129-144`) and its CTX counterpart report *not
  found* apart from *unreachable* (today both are None);
- results are cached in-process for 10 minutes, so step 2 and the create check agree;
- `dtxsid_matched` = the requested DTXSID is in PubChem's synonyms for the compound,
  or CTX returned it.

`structure.png`: NEW `narrative.chem_resolver.structure_png(cid)`. It fetches
`https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/PNG?image_size=300x300`
(reachable from the sandbox [V]).

**Response 200 (`GET /api/v2/chemicals/{dtxsid}`):**
```json
{"dtxsid": "DTXSID50469320",
 "identity": {"name": "…", "casrn": "…", "pubchem_cid": 0, "molecular_formula": "…",
              "molecular_weight": 0.0, "iupac_name": "…", "inchikey": "…"},
 "dtxsid_matched": true,
 "service": "PubChem",
 "say_source": "Looked up in PubChem just now. The CompTox (CTX) lookup is not set up on this server.",
 "structure_url": "/api/v2/chemicals/DTXSID50469320/structure.png",
 "looked_up_at": "2026-10-14T13:02:11Z"}
```
`structure.png` answers `image/png`, or 404 `structure_unavailable` in the envelope.

**Errors:**
- 400 `study_id_has_suffix` / `invalid_study_id`;
- 404 `identity_not_found`;
- 503 `identity_lookup_unreachable`.

### 2.6 `POST /api/v2/studies`: create with a confirmed identity (NEW)

**Core:** NEW `workflow.steps.create_study_step(dtxsid, identity, format_seen)`:
1. strict id check;
2. `format_seen.hash` must equal the current definition hash (else
   `format_changed`);
3. for `source.kind == "lookup"`, the identity must equal the cached lookup's name
   and CASRN (else `identity_changed`);
4. create the folder **atomically** (`mkdir(exist_ok=False)`; an existing *empty*
   folder counts as absent until C4 lands; else `study_exists`);
5. write `identity.json` and `meta.json`.

It writes nothing else: no `files/`, no pins (Q-M1-10). The phase after is EMPTY.

**Request:**
```json
{"dtxsid": "DTXSID7020182",
 "identity": {"name": "Bisphenol A", "casrn": "80-05-7", "pubchem_cid": 6623,
              "source": {"kind": "lookup", "service": "PubChem", "looked_up_at": "2026-10-14T13:02:11Z"}},
 "confirmed": true,
 "dtxsid_checked_by_person": false,
 "format_seen": {"definition": "eras/niehs-2026", "hash": "cdbd602e773aee83"}}
```

**Files written:**
- `sessions/<id>/identity.json` (**CHANGED shape, additive**: `pubchem_cid` and
  `identity_source` added beside `dtxsid`, `name`, `casrn`; the readers of
  `identity.json` to be checked by the backend engineer):
  ```json
  {"dtxsid": "DTXSID7020182", "name": "Bisphenol A", "casrn": "80-05-7", "pubchem_cid": 6623,
   "identity_source": {"kind": "lookup", "service": "PubChem", "confirmed_at": "2026-10-14T13:02:40Z"}}
  ```
- `sessions/<id>/meta.json`: `{"dtxsid", "created_at", "updated_at"}` (the existing
  shape [V]).

**Response 201:** the new session's StudyRow.

**Errors:**
- 400: `invalid_study_id`, `study_id_has_suffix`, `identity_unconfirmed`,
  `identity_incomplete`, `invalid_casrn`;
- 409: `study_exists` (`details.existing_id`), `format_changed`, `identity_changed`.

### 2.7 `PUT /api/v2/studies/{id}/identity`: fill a missing identity (NEW)

**Core:** NEW `workflow.steps.record_identity_step(id, identity)`. The same body as
§2.6's `identity` plus `confirmed`. It refuses when `identity.json` already has a name
(`identity_exists`), and for kinds `companion` and `report` (`read_only_session`).

**Response 200:** the StudyRow.

**Errors:**
- 400: `identity_unconfirmed`, `invalid_casrn`;
- 404: `study_not_found`;
- 409: `identity_exists`, `read_only_session`, `identity_changed`.

### 2.8 `GET /api/v2/studies/{id}/delete-preview`: the dry run (NEW; C8)

**Core:** NEW `workflow.steps.delete_study_dry_run(id)`. It lists what is under
`sessions/<id>/` by plain category, and the approved sections from the section files.
It also lists what is *kept* because it lies outside the session:
- `output/<id>/`;
- `templates/studies/<id>/`;
- the companion and other sessions of the chemical.

`preview_token` = a hash of the listing and of the newest modification time in the
folder. Side-effect-free.

**Response 200:**
```json
{"confirm": { "act": "delete_study", "strength": "irreversible",
              "deletes": [{"what": "files", "say": "…"}], "keeps": [{"what": "…", "say": "…"}],
              "approvals_lost": ["…"], "cost": {"say": "…"} , "reason_required": false },
 "type_to_confirm": "DTXSID5032498",
 "preview_token": "sha256:…"}
```
- `confirm` is the §4.3 object.
- `cost` is null when there is nothing to say.
- `preview_token` is beside it until R4 puts it in §4.3.

**Errors:**
- 404: `study_not_found`;
- 409: `read_only_session` (companion), `member_of_report` (`details.parent`),
  `run_in_flight` (`details.started_at`; from C5's run lock, until then from
  `state.run`).

### 2.9 `POST /api/v2/studies/{id}/delete`: delete (NEW)

`POST`, not `DELETE`: the request carries a body, which some proxies drop on `DELETE`.

**Core:** NEW `workflow.steps.delete_study_step(id, confirm_id, preview_token)`. It
re-runs the dry run and compares the token, refuses on any guard of §2.8, then
removes `sessions/<id>/` and clears the in-memory upload registries, fingerprints
and integrated pool for the id. That is the logic of `session_routes.py:1651-1676`,
moved to core (Q-M1-4 decides rmtree vs a bin).

**Request:** `{"confirm_id": "DTXSID5032498", "preview_token": "sha256:…"}`

**Response 200:** `{"deleted": "DTXSID5032498", "kept": [{"what": "…", "say": "…"}], "say": "DTXSID5032498 was deleted."}`

**Errors:**
- 400: `confirm_mismatch`;
- 404: `study_not_found`;
- 409: `changed_since_preview`, `read_only_session`, `member_of_report`,
  `run_in_flight`.

---

## 3. Derivation rules the backend owns (proposed; one function each)

**`session_kind(id)`**, first match wins:
1. `published_clone.json` is present → `companion`;
2. `studies.json` is present → `report`;
3. listed as a value in another session's `studies.json` → `member`;
4. the id matches `^DTXSID\d+$` → `study`;
5. otherwise → `other`.

**`chemical_dtxsid`:** the `^DTXSID\d+` prefix of the id, or null.
- `chemical_dtxsid_from` is `id` when the whole id is that prefix, and `id_prefix`
  otherwise.
- The member files' `identity.json` names the session id (`"dtxsid": "DTXSID1020431_rat"`),
  and the report's has no `dtxsid` [V]. Neither is used for this.

**`stands(state, kind)`**:

| kind / state | `phase` | `say` | `next` |
|---|---|---|---|
| companion | null | "The published book's content (read-only)" | null |
| report, a member not processed | null | "A report over N studies; its studies are being prepared" | "Finish the member studies", fix `M1` |
| report, all members processed | null | "A report over N studies" | "Review the report's sections", fix `D1` |
| EMPTY | EMPTY | "No files yet" | "Bring in the study's files", `M2` |
| UPLOADED | UPLOADED | "Files brought in, not yet validated" | "Validate the files", `M2` |
| VALIDATION_ERRORS | VALIDATION_ERRORS | "The files have problems to fix" | "Fix the problems the validation found", `M2` |
| VALIDATED | VALIDATED | "Files validated, not yet integrated" | "Integrate the data", `M3` |
| INTEGRATED or APPROVED, not processed | as derived | "Data integrated" / "Data reviewed" | "Process the data", `P1` (the data review informs and gates nothing, Q3) |
| processed, publish readiness not served or not ready | as derived | as above | "Review the report's sections", `D1` |
| processed, `readiness.publish.ready` (C6 served) | as derived | as above | "Publish the report", `D3` |

Until C6 lands, "Publish" is never the next step: today's `publish_readiness()` said
`can_publish: true` for every one of the 32 sessions, companions and empty ones
included [V].

**`bookshelf`**:
- `on_shelf` = `has_generated_report(id)` (`bookshelf_routes.py:112`).
- For a member, `on_shelf` is false and `say` is "Part of DTXSID1020431's book";
  `url` is the parent's.
- For a companion, `url` is `/Bookshelf/<id>` and `say` is "The published content,
  on the Bookshelf".
- Otherwise, when not on the shelf: "Not yet: the study has no report (it has not
  been processed)".

**`actions.delete`**: not allowed for `companion` (`read_only_session`), for
`member` (`member_of_report`), or while a run is in flight (`run_in_flight`).

---

## 4. Mock fixtures

From the real sessions of 2026-10-14 [V]. Identities, phases, published reports and
dates, last-change times, Bookshelf status and definitions are as the probe read
them. The era titles and `say` texts are the proposals above. Where a fixture value
is constructed, it says so.

### 4.1 `GET /api/v2/studies` (abridged to five chemicals and the unassigned group)

```json
{
  "generated_at": "2026-10-14T13:05:00Z",
  "chemicals": [
    {
      "dtxsid": "DTXSID50469320", "name": "Perfluorohexanesulfonamide", "casrn": "41997-13-1",
      "primary": "DTXSID50469320", "can_create": false,
      "sessions": [
        {
          "id": "DTXSID50469320", "kind": "study",
          "chemical_dtxsid": "DTXSID50469320", "chemical_dtxsid_from": "id",
          "identity": {"name": "Perfluorohexanesulfonamide", "casrn": "41997-13-1", "short_name": null,
                       "source": {"kind": "unknown", "service": null, "confirmed_at": null}},
          "stands": {"phase": "APPROVED", "say": "Data reviewed",
                     "next": {"say": "Review the report's sections", "fix": "D1"}},
          "processed": true,
          "last_changed": "2026-10-13T14:47:39Z",
          "format": {"definition": "studies/DTXSID50469320/document", "source": "study",
                     "era": "eras/niehs-2023",
                     "title": "NIEHS Report, as published in March 2023 (NIEHS-07 … 10)",
                     "title_short": "NIEHS Report, March 2023", "changes": 0,
                     "say": "This chemical has a published report, NIEHS-10 (March 2023). The study is written in that book's format: the NIEHS Report as published in March 2023, unaltered."},
          "published": {"report": "NIEHS-10", "date": "2023-03", "nbk": "NBK589955"},
          "bookshelf": {"on_shelf": true, "url": "/Bookshelf/DTXSID50469320", "say": "On the Bookshelf (draft)"},
          "relations": {"parent": null, "members": [], "companion": "DTXSID50469320_published",
                        "twin": null, "others": ["DTXSID50469320_nb"]},
          "actions": {"open": {"allowed": true}, "delete": {"allowed": true, "code": null, "say": null}},
          "notes": []
        },
        {
          "id": "DTXSID50469320_published", "kind": "companion",
          "chemical_dtxsid": "DTXSID50469320", "chemical_dtxsid_from": "id_prefix",
          "identity": {"name": "Perfluorohexanesulfonamide", "casrn": "41997-13-1", "short_name": null,
                       "source": {"kind": "unknown", "service": null, "confirmed_at": null}},
          "stands": {"phase": null, "say": "The published book's content (read-only)", "next": null},
          "processed": false,
          "last_changed": "2026-10-13T14:47:39Z",
          "format": {"definition": "session:document.yaml", "source": "session", "era": null,
                     "title": "The published book's own structure", "title_short": "As published",
                     "changes": 0,
                     "say": "This session holds NIEHS-10's own content and structure, built from the published book."},
          "published": {"report": "NIEHS-10", "date": "2023-03", "nbk": "NBK589955"},
          "bookshelf": {"on_shelf": true, "url": "/Bookshelf/DTXSID50469320_published",
                        "say": "The published content, on the Bookshelf"},
          "relations": {"parent": null, "members": [], "companion": null, "twin": "DTXSID50469320", "others": []},
          "actions": {"open": {"allowed": true},
                      "delete": {"allowed": false, "code": "read_only_session",
                                 "say": "This is the published book's own content, made by a tool. It can't be changed or deleted here."}},
          "notes": []
        },
        {
          "id": "DTXSID50469320_nb", "kind": "other",
          "chemical_dtxsid": "DTXSID50469320", "chemical_dtxsid_from": "id_prefix",
          "identity": {"name": "Perfluorohexanesulfonamide", "casrn": "41997-13-1", "short_name": null,
                       "source": {"kind": "unknown", "service": null, "confirmed_at": null}},
          "stands": {"phase": "APPROVED", "say": "Data reviewed",
                     "next": {"say": "Review the report's sections", "fix": "D1"}},
          "processed": true,
          "last_changed": "2026-10-13T13:46:23Z",
          "format": {"definition": "eras/niehs-2026", "source": "default", "era": "eras/niehs-2026",
                     "title": "NIEHS Report, as published in 2026 (NIEHS-12, 13): the format for new studies",
                     "title_short": "NIEHS Report, 2026", "changes": 0,
                     "say": "This session's id is not a chemical's DTXSID, so it uses the format for new studies. A study under DTXSID50469320 would use NIEHS-10's format."},
          "published": null,
          "bookshelf": {"on_shelf": true, "url": "/Bookshelf/DTXSID50469320_nb", "say": "On the Bookshelf (draft)"},
          "relations": {"parent": null, "members": [], "companion": null, "twin": null, "others": ["DTXSID50469320"]},
          "actions": {"open": {"allowed": true}, "delete": {"allowed": true, "code": null, "say": null}},
          "notes": [{"level": "warn", "code": "not_a_chemical_id",
                     "say": "Made by a tool; its id is not a chemical's DTXSID."}]
        }
      ]
    },
    {
      "dtxsid": "DTXSID1020431", "name": "1,4-Dichlorobenzene", "casrn": "106-46-7",
      "primary": "DTXSID1020431", "can_create": false,
      "sessions": [
        {
          "id": "DTXSID1020431", "kind": "report",
          "chemical_dtxsid": "DTXSID1020431", "chemical_dtxsid_from": "id",
          "identity": {"name": "1,4-Dichlorobenzene", "casrn": "106-46-7", "short_name": "1,4-DCB",
                       "source": {"kind": "unknown", "service": null, "confirmed_at": null}},
          "stands": {"phase": null, "say": "A report over 2 studies",
                     "next": {"say": "Review the report's sections", "fix": "D1"}},
          "processed": false,
          "last_changed": "2026-10-13T11:33:57Z",
          "format": {"definition": "studies/DTXSID1020431/document", "source": "study",
                     "era": "eras/niehs-2026",
                     "title": "NIEHS Report, as published in 2026 (NIEHS-12, 13): the format for new studies",
                     "title_short": "NIEHS Report, 2026", "changes": 1,
                     "say": "This chemical has a published report, NIEHS-13 (April 2026). The report is written in that book's format: the NIEHS Report as published in 2026, with 1 change."},
          "published": {"report": "NIEHS-13", "date": "2026-04", "nbk": "NBK621744"},
          "bookshelf": {"on_shelf": true, "url": "/Bookshelf/DTXSID1020431", "say": "On the Bookshelf (draft)"},
          "relations": {"parent": null,
                        "members": [{"key": "rat", "id": "DTXSID1020431_rat"}, {"key": "mouse", "id": "DTXSID1020431_mouse"}],
                        "companion": "DTXSID1020431_published", "twin": null, "others": []},
          "actions": {"open": {"allowed": true}, "delete": {"allowed": true, "code": null, "say": null}},
          "notes": []
        },
        {
          "id": "DTXSID1020431_rat", "kind": "member",
          "chemical_dtxsid": "DTXSID1020431", "chemical_dtxsid_from": "id_prefix",
          "identity": {"name": "1,4-Dichlorobenzene", "casrn": "106-46-7", "short_name": null,
                       "source": {"kind": "unknown", "service": null, "confirmed_at": null}},
          "stands": {"phase": "APPROVED", "say": "Data reviewed",
                     "next": {"say": "Review the report's sections", "fix": "D1"}},
          "processed": true,
          "last_changed": "2026-10-12T11:42:28Z",
          "format": {"definition": "studies/DTXSID1020431/document", "source": "study", "era": "eras/niehs-2026",
                     "title": "NIEHS Report, as published in 2026 (NIEHS-12, 13): the format for new studies",
                     "title_short": "NIEHS Report, 2026", "changes": 1,
                     "say": "Written as part of the report DTXSID1020431, in its format."},
          "published": {"report": "NIEHS-13", "date": "2026-04", "nbk": "NBK621744"},
          "bookshelf": {"on_shelf": false, "url": "/Bookshelf/DTXSID1020431", "say": "Part of DTXSID1020431's book"},
          "relations": {"parent": "DTXSID1020431", "members": [], "companion": null, "twin": null,
                        "others": ["DTXSID1020431_mouse"]},
          "actions": {"open": {"allowed": true},
                      "delete": {"allowed": false, "code": "member_of_report",
                                 "say": "This is the rat study of the report DTXSID1020431. Deleting it would break that report."}},
          "notes": []
        }
      ]
    },
    {
      "dtxsid": "DTXSID5032498", "name": "Triclosan", "casrn": "3380-34-5",
      "primary": "DTXSID5032498", "can_create": false,
      "sessions": [
        {
          "id": "DTXSID5032498", "kind": "study",
          "chemical_dtxsid": "DTXSID5032498", "chemical_dtxsid_from": "id",
          "identity": {"name": "Triclosan", "casrn": "3380-34-5", "short_name": null,
                       "source": {"kind": "unknown", "service": null, "confirmed_at": null}},
          "stands": {"phase": "APPROVED", "say": "Data reviewed",
                     "next": {"say": "Review the report's sections", "fix": "D1"}},
          "processed": true,
          "last_changed": "2026-10-09T12:43:23Z",
          "format": {"definition": "eras/niehs-2026", "source": "default", "era": "eras/niehs-2026",
                     "title": "NIEHS Report, as published in 2026 (NIEHS-12, 13): the format for new studies",
                     "title_short": "NIEHS Report, 2026", "changes": 0,
                     "say": "No published report is on file for this chemical, so the study uses the format for new studies: the NIEHS Report as published in 2026."},
          "published": null,
          "bookshelf": {"on_shelf": true, "url": "/Bookshelf/DTXSID5032498", "say": "On the Bookshelf (draft)"},
          "relations": {"parent": null, "members": [], "companion": null, "twin": null, "others": []},
          "actions": {"open": {"allowed": true}, "delete": {"allowed": true, "code": null, "say": null}},
          "notes": []
        }
      ]
    },
    {
      "dtxsid": "DTXSID1021952", "name": "Triphenyl Phosphate", "casrn": "115-86-6",
      "primary": "DTXSID1021952", "can_create": false,
      "sessions": [
        {
          "id": "DTXSID1021952", "kind": "study",
          "chemical_dtxsid": "DTXSID1021952", "chemical_dtxsid_from": "id",
          "identity": {"name": "Triphenyl Phosphate", "casrn": "115-86-6", "short_name": null,
                       "source": {"kind": "unknown", "service": null, "confirmed_at": null}},
          "stands": {"phase": "APPROVED", "say": "Data reviewed",
                     "next": {"say": "Review the report's sections", "fix": "D1"}},
          "processed": true,
          "last_changed": "2026-10-12T11:22:31Z",
          "format": {"definition": "studies/DTXSID1021952/document", "source": "study", "era": "eras/ntp-rr-2018",
                     "title": "NTP Research Report, as published in December 2018 (RR-8)",
                     "title_short": "NTP Research Report, 2018", "changes": 0,
                     "say": "This chemical has a published report, RR-8 (December 2018). The study is written in that book's format: the NTP Research Report as published in 2018, unaltered."},
          "published": {"report": "RR-8", "date": "2018-12", "nbk": "NBK535511"},
          "bookshelf": {"on_shelf": true, "url": "/Bookshelf/DTXSID1021952", "say": "On the Bookshelf (draft)"},
          "relations": {"parent": null, "members": [], "companion": "DTXSID1021952_published", "twin": null, "others": []},
          "actions": {"open": {"allowed": true}, "delete": {"allowed": true, "code": null, "say": null}},
          "notes": []
        }
      ]
    },
    {
      "dtxsid": "DTXSID7020182", "name": "Bisphenol A", "casrn": "80-05-7",
      "primary": "DTXSID7020182", "can_create": false,
      "sessions": [
        {
          "id": "DTXSID7020182", "kind": "study",
          "chemical_dtxsid": "DTXSID7020182", "chemical_dtxsid_from": "id",
          "identity": {"name": "Bisphenol A", "casrn": "80-05-7", "short_name": null,
                       "source": {"kind": "lookup", "service": "PubChem", "confirmed_at": "2026-10-14T13:02:40Z"}},
          "stands": {"phase": "EMPTY", "say": "No files yet",
                     "next": {"say": "Bring in the study's files", "fix": "M2"}},
          "processed": false,
          "last_changed": "2026-10-14T13:02:40Z",
          "format": {"definition": "eras/niehs-2026", "source": "default", "era": "eras/niehs-2026",
                     "title": "NIEHS Report, as published in 2026 (NIEHS-12, 13): the format for new studies",
                     "title_short": "NIEHS Report, 2026", "changes": 0,
                     "say": "No published report is on file for this chemical, so the study uses the format for new studies: the NIEHS Report as published in 2026."},
          "published": null,
          "bookshelf": {"on_shelf": false, "url": null, "say": "Not yet: the study has no report (it has not been processed)"},
          "relations": {"parent": null, "members": [], "companion": null, "twin": null, "others": []},
          "actions": {"open": {"allowed": true}, "delete": {"allowed": true, "code": null, "say": null}},
          "notes": []
        }
      ]
    }
  ],
  "unassigned": [
    {
      "id": "DTXSID_TEST", "kind": "other",
      "chemical_dtxsid": null, "chemical_dtxsid_from": null,
      "identity": {"name": null, "casrn": null, "short_name": null,
                   "source": {"kind": "unknown", "service": null, "confirmed_at": null}},
      "stands": {"phase": "EMPTY", "say": "No files yet",
                 "next": {"say": "Bring in the study's files", "fix": "M2"}},
      "processed": false,
      "last_changed": "2026-10-11T14:12:56Z",
      "format": {"definition": "eras/niehs-2026", "source": "default", "era": "eras/niehs-2026",
                 "title": "NIEHS Report, as published in 2026 (NIEHS-12, 13): the format for new studies",
                 "title_short": "NIEHS Report, 2026", "changes": 0,
                 "say": "This session's id is not a chemical's DTXSID, so it uses the format for new studies."},
      "published": null,
      "bookshelf": {"on_shelf": false, "url": null, "say": "Not yet: the session has no report"},
      "relations": {"parent": null, "members": [], "companion": null, "twin": null, "others": []},
      "actions": {"open": {"allowed": true}, "delete": {"allowed": true, "code": null, "say": null}},
      "notes": [{"level": "warn", "code": "not_a_chemical_id", "say": "Made by a tool or a test; its id names no chemical."}]
    }
  ]
}
```
Notes on this fixture:
- **Bisphenol A (DTXSID7020182) is constructed.** It is the session S2's create
  fixture (§4.5) produces. It is not in the store.
- The NBK numbers come from the study definitions' headers (`templates/studies/*/document.yaml`)
  and from NIEHS-10's `breakdown/report.json`.
- The rest are real.
- The full 32-session list can be produced with the probe script in
  `/workspace/ui-team/_scratch/design-m1/probe.py`.

### 4.2 `GET /api/v2/studies/DTXSID50469320_nb` (the detail)

```json
{
  "id": "DTXSID50469320_nb", "kind": "other", "chemical_dtxsid": "DTXSID50469320",
  "…": "the StudyRow of §4.1",
  "detail": {
    "banner": {"level": "warning",
               "say": "This session's id, DTXSID50469320_nb, is not a chemical's DTXSID: it was made by a tool. Its report uses the 2026 format; a study under DTXSID50469320 would use NIEHS-10's format.",
               "links": [{"say": "The study DTXSID50469320", "href": "/app/studies/DTXSID50469320"}]},
    "format": {"definition": "eras/niehs-2026", "source": "default", "era": "eras/niehs-2026",
               "title": "NIEHS Report, as published in 2026 (NIEHS-12, 13): the format for new studies",
               "title_short": "NIEHS Report, 2026", "changes": 0, "say": "…",
               "brings": [],
               "pin": {"mode": "track", "pinned_at": "2026-10-13T13:45:31+00:00", "pinned_by": "default"},
               "chosen_by": "id"}
  }
}
```
The pin is real (`sessions/DTXSID50469320_nb/document_definition.json`).

### 4.3 `GET /api/v2/studies/DTXSID50469320/creation-check` (exists)

```json
{"dtxsid": "DTXSID50469320", "exists": true,
 "existing": {"id": "DTXSID50469320", "kind": "study"},
 "related_sessions": [
   {"id": "DTXSID50469320_published", "kind": "companion", "say": "The published book's content"},
   {"id": "DTXSID50469320_nb", "kind": "other", "say": "Other session, made by a tool"}],
 "format": {"definition": "studies/DTXSID50469320/document", "source": "study", "era": "eras/niehs-2023",
            "title": "NIEHS Report, as published in March 2023 (NIEHS-07 … 10)",
            "title_short": "NIEHS Report, March 2023", "changes": 0,
            "say": "This chemical has a published report, NIEHS-10 (March 2023). A study under this id is written in that book's format: the NIEHS Report as published in March 2023, unaltered.",
            "brings": [
              {"what": "document_definition", "path": "templates/studies/DTXSID50469320/document.yaml",
               "say": "the book's structure and wording"},
              {"what": "report_view", "path": "templates/studies/DTXSID50469320/view.yaml",
               "say": "the book's choice of organs and endpoints for its tables (for example liver only for organ weights; liver and kidney for the gene sets)"},
              {"what": "deposit", "path": "templates/studies/DTXSID50469320/deposit.yaml",
               "say": "the book's captions for its deposited files and its data DOI, 10.22427/NIEHS-DATA-NIEHS-10"},
              {"what": "authored_content", "path": "templates/studies/DTXSID50469320/appendix-a.html",
               "say": "Appendix A's text as published"}],
            "hash": "[the composed definition's hash]"},
 "published": {"report": "NIEHS-10", "date": "2023-03", "nbk": "NBK589955"}}
```
The same id in a store **without** that session (a workspace) gives `"exists": false,
"existing": null, "related_sessions": []` and the same `format`: acceptance
criterion 20. The `hash` is not computed here.

### 4.4 `GET /api/v2/studies/DTXSID7020182/creation-check` (new, default format)

```json
{"dtxsid": "DTXSID7020182", "exists": false, "existing": null, "related_sessions": [],
 "format": {"definition": "eras/niehs-2026", "source": "default", "era": "eras/niehs-2026",
            "title": "NIEHS Report, as published in 2026 (NIEHS-12, 13): the format for new studies",
            "title_short": "NIEHS Report, 2026", "changes": 0,
            "say": "No published report is on file for this chemical, so the study uses the format for new studies: the NIEHS Report as published in 2026.",
            "brings": [], "hash": "cdbd602e773aee83"},
 "published": null}
```
The hash is the one `DTXSID50469320_nb`'s pin records for `eras/niehs-2026` [V].

### 4.5 `GET /api/v2/chemicals/…` (from real resolver output [V])

Found:
```json
{"dtxsid": "DTXSID50469320",
 "identity": {"name": "Perfluorohexanesulfonamide", "casrn": "41997-13-1", "pubchem_cid": 11603678,
              "molecular_formula": "C6H2F13NO2S", "molecular_weight": 399.13,
              "iupac_name": "1,1,2,2,3,3,4,4,5,5,6,6,6-tridecafluorohexane-1-sulfonamide",
              "inchikey": "WDZLGCSJJWEQJO-UHFFFAOYSA-N"},
 "dtxsid_matched": true, "service": "PubChem",
 "say_source": "Looked up in PubChem just now. The CompTox (CTX) lookup is not set up on this server.",
 "structure_url": "/api/v2/chemicals/DTXSID50469320/structure.png",
 "looked_up_at": "2026-10-14T13:01:52Z"}
```
```json
{"dtxsid": "DTXSID7020182",
 "identity": {"name": "Bisphenol A", "casrn": "80-05-7", "pubchem_cid": 6623,
              "molecular_formula": "C15H16O2", "molecular_weight": 228.29,
              "iupac_name": "4-[2-(4-hydroxyphenyl)propan-2-yl]phenol",
              "inchikey": "IISBACLAFKSPIT-UHFFFAOYSA-N"},
 "dtxsid_matched": false, "service": "PubChem",
 "say_source": "Looked up in PubChem just now. The CompTox (CTX) lookup is not set up on this server.",
 "structure_url": "/api/v2/chemicals/DTXSID7020182/structure.png",
 "looked_up_at": "2026-10-14T13:02:11Z"}
```
For Bisphenol A, PubChem's first 20 synonyms (the resolver caps them at 20) do not
include `DTXSID7020182` [V], so `dtxsid_matched` would be **false**. The resolver
found the compound by the DTXSID, so the full synonym list surely has it.
**[backend]** compute the match on the uncapped list, or the confirm step will
over-warn. This fixture keeps `false` so the front-end's second-tick path is built
and tested.

Not found (from `DTXSID5046932O`'s real empty result, with a well-formed id):
```json
{"error": {"code": "identity_not_found", "status": 404,
           "message": "PubChem lookup failed for name 'DTXSID0000000001'",
           "say": "PubChem has no chemical with the DTXSID DTXSID0000000001. A single mistyped digit gives another chemical or none. Check the id on the CompTox dashboard.",
           "fix": null, "details": {"service": "PubChem"}}}
```
Unreachable (constructed; the resolver can't tell this case apart today):
```json
{"error": {"code": "identity_lookup_unreachable", "status": 503,
           "message": "PubChem request failed: ConnectTimeout",
           "say": "The chemical lookup service (PubChem) could not be reached. Nothing was created. Try again in a minute.",
           "fix": null, "details": {"service": "PubChem"}}}
```

### 4.6 `POST /api/v2/studies`

Request (Bisphenol A, after its lookup): as in §2.6.

Response 201: the Bisphenol A StudyRow of §4.1.

Refusal (exists):
```json
{"error": {"code": "study_exists", "status": 409,
           "message": "session DTXSID50469320 already exists",
           "say": "A study of this chemical already exists (DTXSID50469320). Open it instead.",
           "fix": "M1", "details": {"existing_id": "DTXSID50469320"}}}
```
Refusal (suffix):
```json
{"error": {"code": "study_id_has_suffix", "status": 400,
           "message": "study id 'DTXSID50469320_v2' must match ^DTXSID\\d+$",
           "say": "A study's id is the DTXSID alone. Ids with a suffix are made by the system.",
           "fix": null, "details": {}}}
```

### 4.7 `GET /api/v2/studies/DTXSID50469320/delete-preview`

The counts are real [V]: 27 files, 24 originals, 0 of 9 sections approved, 7 files in
`output/DTXSID50469320/`, 121 MB. The token is constructed.
```json
{"confirm": {
   "act": "delete_study", "strength": "irreversible",
   "deletes": [
     {"what": "files", "say": "The study's 27 data files, and the 24 originals they were converted from"},
     {"what": "dataset", "say": "The integrated dataset and everything computed from it (statistics, BMDs, genomics, the query database)"},
     {"what": "sections", "say": "9 report sections (7 apical results, Background, Summary); none is approved"},
     {"what": "statements", "say": "What people stated: study design, front matter, deposit list"},
     {"what": "identity", "say": "The chemical's identity as recorded for this study"},
     {"what": "pins", "say": "The method profile pin (ntp-5day-2021, fixed)"},
     {"what": "history", "say": "The history of every section and pin (1 entry)"}],
   "keeps": [
     {"what": "output", "say": "The deliverables already written to output/DTXSID50469320/ (7 files)"},
     {"what": "study_definition", "say": "NIEHS-10's study definition under templates/studies/DTXSID50469320/ (not part of the study)"},
     {"what": "companion", "say": "The published book's content, DTXSID50469320_published"},
     {"what": "others", "say": "The other session of this chemical, DTXSID50469320_nb"}],
   "approvals_lost": [],
   "cost": {"say": "This study reproduces NIEHS-10. It can be rebuilt only from the command line (tooling.build_published_reports), not from this interface. 121 MB will be freed."},
   "reason_required": false},
 "type_to_confirm": "DTXSID50469320",
 "preview_token": "sha256:5f1c…"}
```

Refusal (member):
```json
{"error": {"code": "member_of_report", "status": 409,
           "message": "DTXSID1020431_rat is listed in DTXSID1020431/studies.json",
           "say": "This is the rat study of the report DTXSID1020431. Deleting it would break that report.",
           "fix": "M1", "details": {"parent": "DTXSID1020431", "key": "rat"}}}
```

### 4.8 `POST /api/v2/studies/DTXSID5032498/delete`

Request: `{"confirm_id": "DTXSID5032498", "preview_token": "sha256:9a03…"}`

Response 200:
```json
{"deleted": "DTXSID5032498",
 "kept": [{"what": "output", "say": "The deliverables in output/DTXSID5032498/"}],
 "say": "DTXSID5032498 was deleted."}
```
Refusal (changed):
```json
{"error": {"code": "changed_since_preview", "status": 409,
           "message": "preview token sha256:9a03… does not match sha256:b71e…",
           "say": "The study changed after you reviewed what would be deleted. Nothing was deleted; review the list again.",
           "fix": null, "details": {}}}
```
