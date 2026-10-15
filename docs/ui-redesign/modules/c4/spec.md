# C4 — Reads have no side effects; ids are stable: spec

Module C4 of the core-guarantees track (`MODULES.md` §2). Spec stage, 2026-10-15.
Evidence marks: **[V]** verified by running it against scratch copies (or the test
suite under a scratch-only pytest plugin; nothing in the repo changed); **[R]** read
from the code. Citations are `file:line` in `/workspace/rlm-bmdx-ui` unless a branch
is named. Scratch: `/workspace/ui-team/_scratch/spec-c4/` (drivers in `scripts/`,
outputs `audit_gets*.txt`, `survey.txt`, `probe/creations.jsonl`).

## 0. What C4 changes, in one paragraph

Today, reading a study can change it. Twenty-two GET routes create the session
folder for an id that does not exist. One GET re-fingerprints the files, rewrites
`_fingerprints.json`, converts CSVs and runs a Java export. Another registers every
file under fresh random ids that the next validation then uses. And the in-memory
registries, not the disk, decide what integration, Process and some reads see.

After C4:
- **A read locates; it never creates.** No folder, no file, no fingerprint, no id,
  no pin, no machine check.
- **A file's id is its name in `files/`**, the same in every validation, after
  every restart, in every report and record. Its content hash travels beside it.
- **The disk is the source of truth on a cold or a warm server.** What is held in
  memory is a cache, checked against the disk, or nothing.

## 1. Read paths: inventory and behaviour after C4

Method [V]: `scripts/audit_gets.py` calls every GET route of the app (Compare
excluded) through FastAPI's test client, with the in-memory registries cleared
before each call. It snapshots `SESSIONS_DIR` and `OUTPUT_DIR` before and after:
- (a) for an absent id, `DTXSID5046932O` (letter O), removing anything created
  before the next call;
- (b) for a copy of NIEHS-10;
- (c) for that copy with its pins removed.

A pytest plugin (`probe/c4_mkdir_probe.py`) recorded every production call site
that created a session folder during `tests/unit` + `tests/integration` [V].

### 1.1 GETs that create the session folder for an absent id [V]

| # | Route | Where the folder is made | After C4 |
|---|---|---|---|
| 1 | `GET /api/workflow/{id}/state` (`web_routes/pool_routes.py:81-91`) | `DiskPoolStore.session_dir` (`workflow/store.py:116-118`) → `pipeline/pool_globals.py:106-112` → `pipeline/session_store.py:75-86` (mkdir `:85`) | store reads locate (§3.1); body unchanged (EMPTY) |
| 2 | `GET /api/workflow/{id}/section-readiness` (`pool_routes.py:94-105`) | same; also `workflow/engine.py:179` (`_is_processed(store.session_dir(..))`) | same |
| 3 | `GET /api/workflow/{id}/sections` (`pool_routes.py:108-192`) | store; plus `pool_routes.py:184-185` (`session_store.session_dir`) | `session_path` |
| 4 | `GET /api/workflow/{id}/publish-readiness` (`pool_routes.py:195-205`) | store | store reads locate |
| 5 | `GET /api/integrated/{id}` (`web_routes/integrated_routes.py:49-68`) | `:58` `_session_dir` | `session_path` |
| 6 | `GET /api/integrated-summary/{id}`, `/api/integrated-tree/{id}` (`integrated_routes.py:71`, `:122`) | `load_integrated` → `pipeline/integrated_io.py:238` | `session_path` in the loader |
| 7 | `GET /api/experiment-metadata/{id}` (`web_routes/session_routes.py:1342-1400`) | `load_integrated`; `:1377` | `session_path` |
| 8 | `GET /api/export-bm2/{id}` (`web_routes/export_routes.py:712-783`) | `:733` | `session_path`; see §1.2 for its write |
| 9 | `GET /api/chat/{id}/threads`, `/threads/{tid}` (`web_routes/chat_routes.py:60`, `:75`) | `pipeline/chat_store.py:46-50` (`chat_dir` mkdirs) | create only on a write |
| 10 | `GET /api/prompts/{section}/runs/{id}` (`web_routes/prompt_routes.py:206-210`) | `pipeline/prompt_store.py:159-162` | create only on a write |
| 11 | `GET /api/prompts/{section}/comparisons/{id}` (`prompt_routes.py:342-346`) | `prompt_store.py:202-205` | create only on a write |
| 12 | `GET /api/wizard/{id}/files`, `/processed`, `/identity`, `/fingerprints` and `GET /api/document/{id}/front-matter` (`web_routes/wizard_routes.py:48-147`) | `DiskPoolStore().session_dir` (`:51-52`, `:71-72`, `:85`, `:100`, `:135`) | store reads locate |
| 13 | `GET /api/query/{id}/schema`, `/parquet`, `/parquet/{table}` (`web_routes/query_routes.py:83-125`) | `query/session_query.py:50-52`; `query_routes.py:107`, `:123` | `session_path` |
| 14 | `GET /api/preview/{id}/view`, `/download` (`web_routes/preview_routes.py:87-104`, `:130`) | `rendering/preview_surface.py:123-124` (`_preview_dir`), via `preview_file_path` `:225-233`; the gate's store | read path locates; `materialize_preview` keeps creating |
| 15 | `GET /api/crawl-config/{id}` (`web_routes/knowledge_graph_routes.py:56-70`) | store `read_json` (`:46-53`) | store reads locate |
| 16 | `GET /api/corpus/{id}/organs`, `/history` (`web_routes/corpus_routes.py:25-38`) | `knowledge_base/corpus_curation.py:57-70` (`_store().session_dir`) | `session_path` for reads |

The probe adds the same sites reached from the tests [V]:
- `session_store.py:85` via `pool_globals.py:112`, `query/session_query.py:52`,
  `query_routes.py:123` and `preview_surface.py:132` (`_identity`);
- the write paths (approve, save_section, pins, views, document config, prompt
  runs), which are not reads and stay as they are (§3.6).

### 1.2 GETs that write inside an existing study [V unless marked]

| Route | What it writes or does | After C4 |
|---|---|---|
| `GET /api/wizard/{id}/fingerprints` (`wizard_routes.py:128-147`) | On a cold server, `ensure_fingerprints` re-scans every file (`pipeline/pool_fingerprints.py:318-381`), rewrites `_fingerprints.json` [V], and mints `scan-<name>` ids in memory (`:378`). Of the validation report's 15 coverage-matrix ids, 12 are then absent [V]. Takes 2.2 s. Ran one Java `ExportBm2` for the genomic `.bm2` [V] (`bmdx_pipe/file_integrator.py:1449`). Can call the LLM metadata deduction (`file_integrator.py:1548`) [R; 0 calls here]. **Converts a long-format CSV** into a pivot and sidecar and moves the original to `_originals/` [V, session `_c4l`] | reads the record (§3.3); never scans |
| `GET /api/session/{id}` (`session_routes.py:224-…`) | Registers every file in `_bm2_uploads`/`_data_uploads` under new uuids (`:252-414`): 14 + 1 entries [V]. Puts 15 fingerprints into memory under those ids [V]. Fingerprints any file missing from the record (`:378-381`, `:413-416`), which writes the record (`pool_fingerprints.py:202`) [R]. Rewrites the chart cache when it lacks SVG (`:468-505`) [R; dormant: all 17 chart caches on disk have SVG, V]. Its `disk_read` events are flushed to `.provenance.jsonl` [V] | decision **D3** (§8): no registration, no fingerprinting, no cache rewrite |
| `GET /api/export-bm2/{id}` | Rewrites `integrated.bm2` when it is older than `integrated.json` (`export_routes.py:752-765`) [R] | **D5**: export to a temporary file and stream it |
| every `/api/…` GET carrying `DTXSID…` in its path | `provenance.flush` appends to `.provenance.jsonl` when the request recorded events (`common/provenance.py:102-131`, middleware `web_routes/background_server.py:194-223`). Only into an existing folder (`provenance.py:116-118`) [V] | **D4** |
| `GET /api/chat/…`, `/api/prompts/…/runs`, `/comparisons` | create `chat/`, `narrative_runs/<s>/`, `narrative_comparisons/<s>/` in an existing study [V] | create only on a write |
| `GET /Bookshelf/{id}`, `/report.docx`, `/report.pdf` | No file written [V: no change under sessions or output]. Resolves the method with `probe=True` (`rendering/latex_export.py:968-971`, `:1084`; `pipeline/method_profile.py:680`), which can run the BMDS 2.7 Wine check (`pipeline/bmds27/__init__.py:72-…`) [R; not exercised here] | pass `probe=False` on render paths; noted, low priority |

### 1.3 GETs whose answer depends on memory, not disk [V]

| Read | Problem | After C4 |
|---|---|---|
| `GET /api/integrated-summary`, `/integrated-tree`, `/experiment-metadata`, `/export-bm2` | They fill `_integrated_pool`. When `integrated.json` changed on disk (another process, the command line), the next read still answered 16 experiments while the disk held 3 [V] | the cache is checked against the file's `(mtime_ns, size)` on every load (§3.4) |
| `GET /api/methods-context/{id}` (`web_routes/llm_routes.py:420-470`, in-memory fingerprints at `:439-450`) | Cold: `species: null`, `sexes: []`, no endpoints. After a `GET /api/session` in the same process: `Rattus norvegicus`, both sexes, every endpoint [V] | reads the record |
| `POST /api/generate-methods` (`llm_routes.py:285-320`) | the same in-memory read [R] | reads the record |

### 1.4 Pins and machine checks

No GET wrote a pin, even with `method_profile.json` and `document_definition.*`
removed [V]. The read model resolves with `probe=False` [R]. Pins are written by
Process (`pipeline/process_integrated.py:1578-1580`, `:1672-1673`), integration
(until C1), and the command line. Those are acts, not reads.

### 1.5 Already clean [V]

- `GET /api/v2/studies/{id}/state`, `/api/v2/vocabularies`;
- the Bookshelf (apart from the probe above), supplemental, bmd-summary, citation
  warnings, document config, views, layout style, structure catalog, prompts and
  threads, `/api/admin/sessions/summary`, `/api/document-tree`;
- **C2's section-history reads** (branch `ui-c2-be`):
  `GET /api/v2/studies/{id}/sections/{key}/history`, `…/history/{version}`
  (`web_routes/v2_section_routes.py:96-114`) and `GET /api/session/{id}/history/{key}`.
  They use `ReadOnlyDiskPoolStore` and `session_store._history_dir`, which locates
  (`pipeline/session_store.py:252-253` on that branch). 404 for an absent study,
  200 for an existing one, nothing created [V, run on `ui-c2-be`].

No empty session folder exists on the real store today [V, survey of 32 sessions].

## 2. File ids today [V]

How ids are made:
- **Upload:** a fresh `uuid4` per file (`web_routes/upload_routes.py:108`, `:316`,
  `:491`).
- **Converted pivot** (a long-format CSV): another fresh `uuid4`, per sex
  (`pool_fingerprints.py:159`). The upload's response id names the CSV, which is
  never in the pool: the response id was not among the fingerprints [V].
- **Disk scan** (`ensure_fingerprints`, step 3): `scan-<name>` (`:378`).
- **Session load** (`GET /api/session`): fresh `uuid4`s into the upload registries.
  The next validation walks those registries first (`:347-369`) and takes their
  ids.

What changes ids, in sequences run in one process [V, `scripts/upload_churn.py`,
`id_churn.py`]:
- upload → `uuid`;
- validate 1 → `scan-…` (the registered CSV path was moved to `_originals/`, so the
  pivots fall through to the scan);
- validate 2 → `scan-…` (no change);
- `GET /api/session` → new uuids, and the in-memory dict holds 8 entries for 4
  names;
- validate 3 → the new uuids.

Two validations with nothing in between keep their ids [V]. The ids change because
of what happens between validations (a load, a restart, an upload), which is what
the person does.

Consequences:
- **Restart trap:** a cold `GET /api/wizard/{id}/fingerprints` leaves 12 of the 15
  coverage-matrix ids absent [V]. C1 now refuses integration then
  (`validation_out_of_date`); C4 removes the cause.
- **The record truncates on a cold upload:** one upload into a 15-file NIEHS-10
  copy on a cold server rewrote `_fingerprints.json` to **1** entry [V]. The
  fingerprint list then showed 1 row for 16 data files [V]. The cause:
  `fingerprint_and_store` saves the in-memory dict, which held only the new file
  (`pool_fingerprints.py:176-180`, `:185-207`).

On disk [V, `survey.txt`]:
- 17 sessions have a validation report: 14 mix `uuid` and `scan-` ids, 3 are all
  `scan-`;
- every coverage-matrix id resolves within its own report;
- every `_fingerprints.json` entry's `file_id` equals the report's id for that name;
- `integrated.json` `_meta.source_files[*].file_id` carries the same ids;
- no `precedence.json` exists.

## 3. Behaviour after C4

### 3.1 Locating vs creating

- `PoolStore` gains `session_path(dtxsid) -> Path` (locate, never create).
  `session_dir` keeps "create" and is used only to write.
- `DiskPoolStore`'s read methods use `session_path`: `has_files`,
  `artifact_exists`, `has_stale_sections`, `read_json`, `_iter_section_dicts`, and
  C2's history readers. **This one change fixes routes 1, 2, 4, 12 and 15, and
  C1's risk 6** (a refused act on a mistyped id left a folder), because C1's guard
  derives the state through the caller's store.
- `WorkflowEngine` uses `store.session_path` for `_is_processed`
  (`workflow/engine.py:179`).
- `ReadOnlyDiskPoolStore` moves from `workflow/read_model.py:55-70` to
  `workflow/store.py`, and `read_model` re-exports it. Its `session_dir` locates as
  now. It allows `get_fingerprints`, which becomes a disk read (§3.3). It still
  refuses `ensure_fingerprints`, `set_fingerprints`, `set_integrated`,
  `write_json` and `save_section`.
- Direct read sites switch to `session_store.session_path`:
  - `integrated_routes.py:58`;
  - `integrated_io.py:238` (the loader);
  - `session_routes.py:1377`;
  - `export_routes.py:733`;
  - `query/session_query.py:52`;
  - `query_routes.py:107`, `:123`;
  - `pool_routes.py:184-185`;
  - `preview_surface.py:124` (split: `preview_file_path` locates, `materialize_preview` creates) and `:132`;
  - `corpus_curation.py:61-70` for reads.
- `chat_store.chat_dir(create=False)` and `prompt_store._runs_dir` /
  `_comparisons_dir` create only from their write functions, with the same
  `create=` pattern `prompt_store.section_dir` already uses (`prompt_store.py:72-78`).
- **Answers for an absent study are unchanged:** EMPTY, `{"files": [], "count": 0}`,
  404 or 400 as today. Only the folder no longer appears.

### 3.2 The id scheme

- **`file_id` = the file's name in `files/`**, exactly as stored (basename).
  - One function mints it: `pipeline.pool_fingerprints.file_id_for(name) -> str`
    (the identity today), so a later change is made in one place.
  - Names are unique within `files/` by construction.
  - Every place that makes an id uses it: `fingerprint_and_store` (the `file_id`
    argument goes; the id comes from the stored name), the pivot loop (`:157-167`),
    the scan (`:378`), the three upload routes.
- **The record carries the content hash beside the id, not in it.**
  - Each `_fingerprints.json` entry is `asdict(FileFingerprint)` plus
    `content_sha256` and `size`. The hash takes 22 ms for the 8.2 MB genomic
    `.bm2` [V].
  - The record's reader already drops unknown keys: an entry with an extra key
    loads [V] (`pool_fingerprints.py:261-264`).
  - The hash is **not** in the validation report's fingerprints, which stay
    `asdict(FileFingerprint)`. So C1's basis does not change (§5.2).
- **Why not name + hash as the id** (the alternative, D1): the content of a file
  changes under the app's own hand.
  - Confirming a classification rewrites a txt/csv file's header
    (`workflow/steps.py:313-342`). Its id would change with no new file, the report
    and the choices made on it would stop matching, and the interface would be
    told the file is new.
  - Replacing a file under the same name already invalidates validation and
    choices (`pipeline/pool_state.py:166-178`), so a name id cannot carry a stale
    choice across a replacement.
  - "Has the content changed since the check" is a question the hash beside the
    id answers, without breaking references.
- Converting a long-format CSV gives pivot names derived from its stem. The pivot
  bytes are deterministic: two conversions gave identical bytes, equal to the
  session's pivot [V].

### 3.3 Fingerprints: the record is the truth

| | today | after C4 |
|---|---|---|
| `store.get_fingerprints(id)` | the in-memory dict (`store.py:124-126`), `{}` on a cold server | the record on disk, as `{name: FileFingerprint}` (the `load_cached_fingerprint` logic, generalised). 0.1–0.3 ms for 15 entries [V] |
| `ensure_fingerprints(id)` (not forced) | scans on a cold server | **= `get_fingerprints`** (kept as a deprecated alias). Callers: `wizard_routes.py:136`, `steps.py:559`, `process_integrated.py:1317`, `:1657`, `tooling/profile_process_run.py:66`, `tests/unit/test_endpoint_units.py:58` |
| `ensure_fingerprints(id, force=True)` | scan; walks the upload registries first (`:347-369`) | the scan, for **acts only** (validate, upload); walks `files/` only; may reuse a record entry whose `content_sha256` and size match (saves the Java export and the LLM deduction for a `.bm2`) |
| writing the record | from the in-memory dict, whole (`:185-207`); `confirm_metadata_step` from `get_fingerprints` (`steps.py:302-307`) | read-modify-write **by name**, written atomically (temp file + `os.replace`); never from memory alone. Fixes the cold-upload truncation (15 → 1) and data finding 4's `{}` |
| a data file in `files/` not in the record (copied in by the command line, `tooling/generate_report.py:179-197`; old fixtures) | scanned on any read | reported, not scanned: `fingerprinted: false` (contract §2.2). The next validation scans it |
| the in-memory dict `_pool_fingerprints` (`pool_globals.py:80`) | the source of truth for integration, confirm, methods context | **not read**. Kept, empty, for compatibility; nothing consults it; removed when no import remains |

Process, the animal report, `GET /api/methods-context` and `POST /api/generate-methods`
read the record (§1.3). The Methods cache key drops `file_id` already
(`pipeline/cache_plumbing.py:397-404`), so it is unchanged.

### 3.4 The integrated cache

`_load_integrated` (`integrated_io.py:212-282`) checks the cached entry against
`integrated.json`'s `(mtime_ns, size)`:
- a different file is re-read;
- an absent file clears the entry.

`save_integrated` records the stat after writing. Schema validation runs as now.
This is the pattern the read model already uses for the live mismatches
(`workflow/read_model.py:113-132`).

### 3.5 The upload registries

`_data_uploads` and `_bm2_uploads` (`pool_globals.py:91`, `:98`) and `_csv_uploads`
(`web_routes/server_state.py:47`):
- **are never consulted for a study's files and never filled by a read**;
- a study's file is addressed by (study id, file name);
- they remain for uploads without `?dtxsid=` (a temporary directory) and for the
  old flows keyed by an upload id: `/api/process-bm2`, `/api/preview/{file_id}`,
  the `bm2_id`/`csv_id` copy-in of `POST /api/session/approve`
  (`session_routes.py:895-931`), and `export_routes.py:59-69`.
- `remove_old_file_entries` (`pool_state.py:99-142`) deletes from the record by
  name.

What is the source of truth on a cold server:

| State | Truth | Memory |
|---|---|---|
| which files, and what each one is | `files/` and `_fingerprints.json` (by name) | none |
| the last file check | `validation_report.json` (names; legacy ids normalised on read, §4) | none |
| the merged dataset | `integrated.json` | memo, checked against the file |
| a study's existence | the folder exists and is not empty | none |
| an upload not yet in a study | memory only (lost on restart, as today) | the registries |

### 3.6 Writes are not C4's

Acts still create the folder:
- uploads with `?dtxsid=` (`upload_routes.py:97-98`, `:331`, `:439-440`);
- approve and save (`session_routes.py:822`, `session_store.py:270`);
- pins (`method_profile.py:627`, `definition_pin.py:134`);
- views and document config (`document_model/view_config.py:150`,
  `document_config.py:199`, `:319`);
- preview materialise; prompt runs.

Under C1 every guarded step on an absent id is refused (EMPTY allows only
ADD_FILES), so those writes are not reached. Whether an upload may create a study
is M1's (R6) and is listed as D6.

### 3.7 GET /api/session/{id} (D3, recommendation A)

- No registration in the upload registries, no fingerprinting, no record write, no
  chart-cache rewrite. The SVG migration renders in memory and does not persist.
- `pending_files[].id` and `bm2_sections[*].server_file_id` are the file names.
- `/api/preview/{file_id}` takes an optional `?dtxsid=`. With it, a file name is
  resolved in that study's `files/`. Without it, it uses the upload registries as
  today.

## 4. Old sessions on disk

**Normalise on read; never rewrite.** `pipeline.file_ids.normalize_report(report,
precedence=None)` returns a copy in which every id is replaced by its file name,
through the report's own `fingerprints` table:
- the keys of `fingerprints` and their `file_id`;
- every id in `coverage_matrix`;
- `issues[].files_involved` and `issues[].suggested_precedence`;
- `precedence[].chosen_file_id`.

An id the table does not know is left as it is, and C1's consistency check then
refuses.

It is applied wherever a report or precedence is read for its ids:
- `integrate_step` (with C1's check);
- `resolve_step`;
- M2's report read;
- `GET /api/wizard/{id}/fingerprints`;
- `value_validation` re-reads, if any.

The next validation writes a report in names, and the old one is gone naturally.

*Verified on a cold process* (`scripts/proto_ids.py integrate`, the NIEHS-10 copy):
the legacy report normalised in memory, plus the record keyed by name: 0 of 15
coverage ids missing. `integrate_pool` built **16 experiments**, source files
named. Under today's code the same cold path (after a re-scan) gives 4 (data
finding 2).

Other old artifacts:
- `_fingerprints.json` is already keyed by name. Its `file_id` fields are ignored
  on read (the id is the key). `content_sha256` is absent until the next scan;
  "changed since check" is then `null` (unknown), never false.
- `integrated.json` `_meta.source_files[*].file_id`: left as is (history). Its one
  reader, `pipeline/session_db.py:166` (the `source_file` table's key), gets names
  after the next integration and Process.
- The regression fixture `tests/fixtures/regression/given-pfhxsam-2026`: its record
  covers 12 of its 41 data files [V]. Reads report 29 files not fingerprinted
  until a validation.

## 5. Blast radius

### 5.1 Callers (production) [R]

- `workflow/store.py`: `session_path`; reads locate; `ReadOnlyDiskPoolStore`;
  `get_fingerprints` reads the record.
- `workflow/engine.py:179`.
- `workflow/read_model.py`: the store import; `members_state` and `study_state`
  use `session_path`.
- `workflow/steps.py:198`, `:270-307`, `:365-371`, `:559`: name ids; record writes
  by name; `normalize_report` in integrate and resolve.
- `pipeline/pool_fingerprints.py`: the whole file (`file_id_for`, record merge,
  scan, aliases).
- `pipeline/pool_state.py:99-142`, `:293-362`.
- `pipeline/integrated_io.py:212-282`, `:330-357`.
- `pipeline/process_integrated.py:1313-1325`, `:1652-1658`.
- `pipeline/chat_store.py:46-50`; `pipeline/prompt_store.py:159-205`.
- `pipeline/file_ids.py` (new, about 60 lines).
- `query/session_query.py:50-52`.
- `rendering/preview_surface.py:123-140`, `:225-233`.
- `knowledge_base/corpus_curation.py:57-70`.
- Routes:
  - `pool_routes.py:184-185`;
  - `integrated_routes.py:58`;
  - `session_routes.py:224-505` (D3) and `:1377`;
  - `export_routes.py:733-765` (D5);
  - `query_routes.py:107`, `:123`;
  - `wizard_routes.py:128-147`;
  - `llm_routes.py:298-320`, `:439-450`;
  - `upload_routes.py:78-560`: ids, and the record merge through
    `fingerprint_and_store`; plus `:695-…` (preview, D3).
- `tooling/generate_report.py:223-240` (confirm by name: simpler, same behaviour);
  `tooling/profile_process_run.py:66`.
- Notebook text `notebooks/_nb_cells_data.py:565-570` ("Disk-scanned files get the
  id `scan-<filename>`"), `:700-705`; regenerate. `docs/ui-redesign/http-api.md`.
- **bmdx-pipe: no change needed.** `FileFingerprint.file_id` is an opaque string;
  `validate_pool`, `lightweight_validate`, `integrate_pool` and
  `build_animal_report` key by what they are given (`file_integrator.py:439-480`,
  `:1704-1750`, `:2341-2460`; `pool_integrator.py:1032-1215`;
  `animal_report.py:527-551`) [R]. Recommended, optional (D7):
  - the docstrings saying "UUID from upload" (`file_integrator.py:449`, `:874`,
    `:1087`, `:1413`, `:1669`);
  - `roster_subset`'s message, `sorted(list(missing)[:5])` (`:2208`). It takes 5
    arbitrary members of a set, so two validations of the same files in two
    processes gave different text in 5 messages [V]. It should be
    `sorted(missing)[:5]`.

  A commit there is in the sibling repository, `/workspace/bmdx-pipe`.

### 5.2 C1 and C2

- **C1** (`ui-c1-be`, mid-build): `workflow/integration_basis.py` maps ids to names
  already. Its basis is identical for the legacy report, the same report normalised
  to names, and a fresh validation with name ids: `a2e2f1307c3b9bf5` all three
  [V, `scripts/basis_vs_names.py`, loading the branch's module by path]. So no
  recorded basis flips.
  - `_check_validation_matches` (`ui-c1-be` `workflow/steps.py:596-621`) keeps its
    names comparison.
  - Its `missing_ids` branch becomes reachable only for a legacy id that
    normalisation cannot resolve.
  - With C4, a legacy study on a cold server integrates without a forced
    re-validation; C1 alone would refuse it after any re-scan.
  - C4 lands after C1 merges, and `normalize_report` goes into C1's
    `integrate_step`.
- **C2** (`ui-c2-be`, built): its history reads are clean (§1.5). Its write gate is
  untouched. Its new `PoolStore` methods (`workflow/store.py` on that branch) gain
  nothing from C4 except the read ones moving to `session_path`.
- **C3** keys precedence by compound key and file name. With C4, `chosen_file_id`
  *is* the file name.

### 5.3 Tests that pin today's behaviour

| Test | What it pins | Change |
|---|---|---|
| `tests/integration/test_upload_routes.py:91-111` | preview via `pending_files[0].id` after `GET /api/session` registered it | D3-A: the id is a name; the test previews with `?dtxsid=` |
| `tests/integration/test_session_lifecycle.py:75-93` | `pending_files` discovered | kept; the ids are names |
| `tests/integration/test_wizard_routes.py:36-44` | absent study → `{"files": [], "count": 0}` | kept; add "no folder created" |
| `tests/integration/test_wizard_routes.py:105-124` | fingerprint row keys | two keys added (contract §2.2); the key-set assertion is updated |
| `tests/unit/test_endpoint_units.py:48-58` | `ensure_fingerprints` (not forced) after a forced scan | holds: reads the record the forced scan wrote [R] |
| `tests/conftest.py:111-114`, `:169-192` | clears the registries; forced scan | unchanged |
| `tests/unit/test_read_model.py:44`, `:69`, `:96-108` | fake store; read-only store refusals | the fake gains `session_path`; `get_fingerprints` allowed (disk read) |
| `tests/unit/test_workflow_engine.py:37`, `tests/unit/test_workflow_steps.py:44-70`, `:195-213` | fake stores; confirm keyed `"f1"` | fakes gain `session_path`; the confirm test is unchanged (fake store) |
| `tests/integration/test_pool_validate.py:55-97` | iterates fingerprints | values unchanged; keys are names |
| `tests/integration/test_pool_integrate.py:65-102`, `tests/unit/test_load_save_integrated.py:85-94` | `_integrated_pool` filled | still filled (memo) |
| `tests/integration/test_pool_file_removal.py:20-23`, `:54` | record keyed by name | consistent |
| `tests/unit/test_dtxsid_validation.py:109-114`, `tests/integration/test_query_routes.py` (missing db 400, parquet 404) | statuses for absent ids | unchanged; no folder |
| `tests/unit/test_provenance.py:41-100` | flush | unchanged unless D4-B |
| `tests/unit/test_session_db.py:124` | literal `"scan-bw"` in fixture data | unaffected |

New tests:
- **(a)** a parametrised test over `app.routes`: every GET (Compare excluded), on an
  absent id, creates nothing under `SESSIONS_DIR`. On a study copy, it changes no
  file except under D4's rule. This is the audit, made permanent.
- **(b)** ids stable across validate → restart (registries cleared) → validate.
- **(c)** cold upload keeps the record whole.
- **(d)** cold `GET …/fingerprints` writes nothing, converts nothing, takes no Java
  export.
- **(e)** `normalize_report` on a legacy report, then integrate gives 16
  experiments.
- **(f)** the integrated memo follows the disk.

### 5.4 The golden oracle

`test_process_integrated_golden.py` builds its session with an `integrated.json`
and an empty `files/`, with no record and no report (`test_process_integrated.py:149-159`).
- Process's fingerprint read gives `{}` today (empty scan) and `{}` after C4
  (absent record), so the Methods input is the same.
- The payload carries no file id (0 occurrences in
  `tests/fixtures/golden/process_integrated_payload.json` [V]).

Expected byte-identical [R]; `guard` must show it.

Baseline [V]: `tests/unit` + `tests/integration` run under the probe plugin, with
the only failure the known `test_docx_generator.py::test_yaml_page_breaks_land_as_page_break_before`.

## 6. Risks

1. **Name collisions** between an uploaded `x.txt` and the pivot converted from
   `x.csv`: the conversion overwrites silently, as today. Now the two would share
   an id. M2 or C3's checked upload should refuse it.
2. **File names in URLs** (spaces: `Body weight.bm2`, `Gene Expression-….bm2`):
   clients must encode them. The existing `DELETE /api/pool/{id}/files/{filename}`
   already does this.
3. **A record without hashes** (every session today) says "changed since check:
   unknown" until the next validation. It must never read as "unchanged".
4. **The old front-end** (behind the wall) may rely on `GET /api/session`
   registering uuids for preview and `process-bm2` (D3). I cannot check it.
5. **Studies whose record does not cover `files/`** (a command-line import before
   validation; `given-pfhxsam-2026`). Reads now show those files as not checked
   instead of scanning them. A Process test on such a fixture could see fewer
   fingerprints than today's scan gave. To be confirmed with `smart` when built.
6. **Concurrency:** the record's read-modify-write is atomic per write but not
   locked. Two uploads at once can still lose an entry. C5's per-session lock
   closes it.
7. **Determinism of the report text** (§5.1, D7): without the bmdx-pipe fix, two
   validations of the same files write different messages. The ids, coverage and
   basis are unaffected [V].

## 7. Order of the changes

Each step keeps the suite green, updating its tests in the same commit, and runs
`run-tests.sh smart`, then `guard`.

1. `workflow/store.py`: `session_path` in the protocol and `DiskPoolStore`; read
   methods locate; `ReadOnlyDiskPoolStore` moved and re-exported. Engine. Fake
   stores. New test (a), first for the store-backed routes.
2. The direct read sites of §3.1; chat and prompt stores create only on a write.
   Test (a) now covers every GET.
3. The integrated memo (§3.4). Test (f).
4. The record: name ids, `file_id_for`, hash and size, merge-by-name atomic writes,
   `get_fingerprints` from the record, the non-forced alias, registries not walked.
   Process, the animal report, methods-context and generate-methods read the
   record. Tests (b), (c), (d).
5. `pipeline/file_ids.normalize_report`, used by integrate (after C1 merges) and
   resolve. Test (e).
6. `GET /api/session` (D3), `/api/preview` `?dtxsid=`, `export-bm2` (D5),
   provenance (D4).
7. Notebook text and regeneration, `http-api.md`, the headless guide.
8. bmdx-pipe (D7), if accepted, in its own repository.
9. `run-tests.sh full`.

## 8. Decisions for the maintainer

- **D1. The file id.**
  - **A (recommended):** the file's name in `files/`, with the content hash beside
    it in the record.
  - **B:** name + content hash in the id itself. Confirming a classification
    rewrites a file's header, so B changes the id with no new file and breaks every
    reference to it (§3.2).
- **D2. Old sessions.**
  - **Normalise on read and never rewrite (recommended):** nothing in `sessions/`
    is touched; the next validation writes names.
  - The alternative is a one-off tool that rewrites old reports, which you would run
    on the real store.
- **D3. `GET /api/session/{id}`** (shaped by the old front-end).
  - **A (recommended):** free of side effects; file ids are names; `/api/preview`
    takes `?dtxsid=`.
  - **B:** keep its registration as an old-front-end-only route. It becomes
    harmless to the workflow, since nothing reads the registries for a study's
    files, but it still writes the record for an unfingerprinted file.
  - A may change the old front-end's preview after a restart; I cannot check that
    behind the wall.
- **D4. The request log** (`.provenance.jsonl`) on GETs.
  - **A (recommended):** keep it, as a diagnostic dotfile that no derivation reads.
    Dotfiles are not study state, so M1's `last_changed` ignores them (otherwise a
    read makes a study look changed).
  - **B:** flush only for non-GET requests (a read leaves no trace at all), losing
    the session-load profile.
- **D5. `GET /api/export-bm2`.** Export to a temporary file and stream it
  (recommended), instead of refreshing the study's `integrated.bm2` from a read.
- **D6. Writes to a study that does not exist.** Should uploads with `?dtxsid=`
  still create the study, or should creation belong only to M1's create? This is
  outside C4; M1's R6 and the C1 guard family carry it.
- **D7. bmdx-pipe.** Accept the two optional changes of §5.1: docstrings, and
  deterministic `roster_subset` messages.
