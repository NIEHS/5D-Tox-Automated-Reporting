# C4 — Reads have no side effects; ids are stable: contract

Against the shared error envelope (MODULES §4.2). Every claim is marked [V] verified or [R] read, as in spec.md.

## 1. Refusals C4 adds

**None.** C4 makes reads quiet and ids stable, and refuses nothing new:
- **An absent study** keeps today's answers on the old routes (EMPTY state, empty
  lists, 404s). The only difference is that no folder appears. The v2 read model
  answers `{"id", "exists": false}` as today.
- **An id that normalisation cannot resolve** (a legacy report naming a file that
  is gone) reaches C1's existing `validation_out_of_date` (409) at integration.
- **An unknown file name** in `POST /api/pool/resolve` or
  `POST /api/pool/confirm-metadata` stays C3's refusal to add.

## 2. Routes whose responses change

### 2.1 Behaviour only (the body is unchanged)

On an absent id, these routes no longer create the session folder [V today]:
- `GET /api/workflow/{id}/state`, `/section-readiness`, `/sections`, `/publish-readiness`;
- `GET /api/integrated/{id}`, `/api/integrated-summary/{id}`, `/api/integrated-tree/{id}`;
- `GET /api/experiment-metadata/{id}`, `GET /api/export-bm2/{id}`;
- `GET /api/chat/{id}/threads`, `/threads/{tid}`;
- `GET /api/prompts/{section}/runs/{id}`, `/comparisons/{id}`;
- `GET /api/wizard/{id}/files`, `/processed`, `/identity`, `GET /api/document/{id}/front-matter`;
- `GET /api/query/{id}/schema`, `/parquet`, `/parquet/{table}`;
- `GET /api/preview/{id}/view`, `/download`;
- `GET /api/crawl-config/{id}`, `GET /api/corpus/{id}/organs`, `/history`.

On an existing study, the chat and prompt-workshop GETs no longer create their
subfolders.

`GET /api/integrated-summary`, `/integrated-tree` and `/experiment-metadata`
answer from `integrated.json` as it is on disk now, even when another process
changed it [V today: they kept answering the old dataset].

`GET /api/methods-context/{id}` and `POST /api/generate-methods` read the study's
fingerprint record, so a cold server answers as a warm one [V today: the cold
answer had no species, sexes or endpoints].

### 2.2 `GET /api/wizard/{id}/fingerprints`

- Answers from `_fingerprints.json`. It never scans, converts, exports or writes:
  2.2 s cold today [V], milliseconds after.
- `file_id` is the file's name.
- Each row adds:
  - `fingerprinted: bool`: false for a data file in `files/` that the last check
    has not seen (its other fields are then null);
  - `changed_since_check: bool | null`: whether the file's content hash differs
    from the one recorded; null when no hash is recorded yet (a study fingerprinted
    before C4).
- Top level adds `unchecked: [names]`.

```json
{"fingerprints": [{"file_id": "body_weight_truth_female.txt", "filename": "body_weight_truth_female.txt",
                   "file_type": "txt", "platform": "Body Weight", "data_type": "tox_study",
                   "sexes": ["Female"], "fingerprinted": true, "changed_since_check": false}],
 "count": 15, "unchecked": []}
```

### 2.3 File ids are file names (every route that carries one)

| Route | Change |
|---|---|
| `POST /api/upload-bm2`, `/api/upload-csv`, `/api/upload-zip` (with `?dtxsid=`) | `files[].id` is the stored file's name. For a long-format CSV converted at upload, `id` is the first pivot's name and two keys are added: `ids` (every pivot's name) and `converted_from` (the original name). Today the returned id names nothing in the pool [V]. `validation_issues[].files_involved` hold names. Without `?dtxsid=`: unchanged (an upload id) |
| `POST /api/pool/validate/{id}` and `validation_report.json` | the keys of `fingerprints`, their `file_id`, every id in `coverage_matrix`, `issues[].files_involved` and `suggested_precedence` are file names. The same in every validation and after every restart |
| `POST /api/pool/integrate/{id}` | `_meta.source_files[*].file_id` is a file name. A legacy report (uuid or `scan-` ids) is accepted, normalised to names in memory, never rewritten |
| `POST /api/pool/resolve` | `chosen_file_id` is a file name (a legacy id is normalised through the report) |
| `POST /api/pool/confirm-metadata/{id}` | `metadata` is keyed by file name |
| `GET /api/session/{id}` (decision D3-A) | no registration; `pending_files[].id` and `bm2_sections[*].server_file_id` are file names. The route writes nothing (no fingerprinting, no chart-cache rewrite) |
| `GET /api/preview/{file_id}` (D3-A) | adds `?dtxsid=`: `file_id` is then a file name in that study. Without it, the upload registries as today |
| `GET /api/export-bm2/{id}` (D5) | same download; the study's `integrated.bm2` is no longer rewritten by the request |

### 2.4 Files on disk (format)

- **`_fingerprints.json`:** still keyed by file name. Each entry's `file_id` equals
  its key. Each entry adds `content_sha256` and `size`. The record is written by
  merging by name, atomically, and never shrinks on an upload [V today: a cold
  upload shrank it from 15 entries to 1].
- **`validation_report.json`, `precedence.json`:** ids are file names. Older
  files are read through normalisation and left as they are.
- **`.provenance.jsonl`:** per D4. Either still appended on GETs and ignored by
  every derivation (M1's `last_changed` included), or appended only for non-GET
  requests.

### 2.5 Unchanged

- `GET /api/v2/studies/{id}/state` and `/api/v2/vocabularies`, already free of side
  effects [V];
- C2's `GET /api/v2/studies/{id}/sections/{key}/history[/{version}]` and
  `GET /api/session/{id}/history/{key}` [V on `ui-c2-be`];
- the Bookshelf routes (they write nothing [V]; resolving the method there with
  `probe=False` is a noted follow-on).

## 3. Requests to other parties (through the orchestrator)

- **C1** (`ui-c1-be`): `integrate_step` reads the report through
  `pipeline.file_ids.normalize_report` before `_check_validation_matches`. The
  integration basis needs no change (identical hash for legacy, normalised and
  fresh name-id reports [V]).
- **M1:** `last_changed` ignores dotfiles (D4-A). R8's "empty folder counts as
  absent" holds after C4 too; no empty folder exists on disk today [V].
- **M2:** may rely on "file id = file name" everywhere, and on `fingerprinted` and
  `changed_since_check`.
- **The kit:** no new refusal code.
