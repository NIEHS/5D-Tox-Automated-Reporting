# Gate 0, PROCESS: workflow analysis

Workflow analyst, 2026-10-14. Scope: HANDOFF §3 step 9 (Process:
`workflow.steps.process_step` → `pipeline.process_integrated.run_process`, then
`workflow.steps.materialize_result_sections`), content preparation
(`workflow.steps.document_step`, ADR-0021) and reprocessing with its currency
(`workflow/reprocess.py`, `workflow/currency.py`, `pipeline/pool_state.py`).

**Legend.** *Verified*: I ran it on a scratch copy of the published PFHxSAm session
(`DTXSID50469320` copied to `/workspace/ui-team/_scratch/analyst-process/sessions/DTXSID50469320_apx`,
`SESSIONS_DIR`/`OUTPUT_DIR` pointed at the scratch directory, run under
`./run-server.sh --run`, LLM gateway live, Java live). *Read*: read from code, not
run. The driver scripts are in `/workspace/ui-team/_scratch/analyst-process/bin/`.
Nothing under the real `sessions/` or `output/` was written.

**`.bm2` cache caveat.** My first runs used the shared, full `/tmp/_bm2_cache` LMDB
(1 GB map), because `BM2_CACHE_DIR` was unset. To check them, I re-ran the two runs
that read `.bm2` files on a fresh copy (`DTXSID50469320_apx2`) with
`BM2_CACHE_DIR=/workspace/ui-team/_scratch/analyst-process/bm2_cache`:
- the first Process;
- the file change → validate → integrate → animal report → Process.

The outcomes were identical:
- the same unit misses and the same cache hashes;
- 301 animals, core 301;
- 16 experiments;
- the same phase, gate and section states.

Only the timings moved; both are given in §1. The other runs read no `.bm2`, apart
from Methods' read of the cache (`pipeline/session_store.py:128-140`, *read*),
which only affects the Methods prose, not any finding here. A side observation
(*read*): Methods takes the BMDExpress analysis settings from that machine-wide
cache, keyed by the `.bm2`'s absolute path. If the cache is full, or the session
directory was copied or moved, they are silently left out of the prompt.

HANDOFF §2 constraint, kept throughout: **Process blocks on purpose.** It is one
foreground operation the person waits for. A progress indicator inside that wait is
allowed. Nothing below proposes a background job.

---

## 0. The findings that matter most

1. **Every Process run un-approves the apical result sections and throws away a
   person's edits to them, with no history copy** (*verified*, on a warm run with no
   input changed). `materialize_result_sections` rewrites every `bm2_<slug>.json`
   with `approved: False` and `archive=False` (`workflow/steps.py:155,170`). The
   version manifest still says "v1 blessed". The unit tests pin this behaviour
   (`tests/unit/test_workflow_steps.py:301-302`: "the section is provisional again").
   That conflicts with HANDOFF §2 and ADR-0015, which say no machine silently
   overwrites approved content. The maintainer has to decide which one is right (Q1).
2. **Currency only fires on a change to the files.** `stale` and `regenerated` are
   set only by `invalidate_pool_artifacts` (`pipeline/pool_state.py:224-276`), which
   runs when files are added, replaced or removed. **Re-pinning the method profile**
   (*verified*), changing the study design or experiment metadata, or a tracking pin
   moving to a newer profile (*read*) changes the numbers and regenerates the
   Methods text, but leaves an approved Summary approved and not stale. The publish
   gate stays open. ADR-0027 line 97 says a re-pin "marks the derived content
   stale". The code does not.
3. **A "regenerated" LLM section was not regenerated** (*verified*). After a file
   change, the approved `summary.json` is marked `stale` with
   `regenerated: {reason: "data_changed"}`. Process, and then `materialize_summary`,
   keep its old text, because `materialize_summary` never overwrites an approved
   summary (`workflow/steps.py:76`). Re-accepting it re-blesses the **old** text
   (*read*, `accept_section_step` only flips flags). To get new text, the person must
   release the section first and then re-run Summary.
4. **Three of the five LLM-written parts have no section file and no approval.**
   Methods, the apical-BMD narrative and the genomics interpretations live only in
   caches (`_cache_methods_*`, `_cache_apical_narrative_*`,
   `_cache_interpretation_*`), and the renderer reads those caches directly
   (`rendering/latex_export.py:758,811,834-860`).
   `accept_section_step(…, "methods")` → `StepError 404 "No 'methods' section to approve"`
   (*verified*, the same for `bmd_summary`). They are rewritten silently whenever
   their hash moves:
   - Methods regenerated on the re-pin (*verified*);
   - the genomics narratives regenerated after a file change (*verified*), with
     different wording run to run (*verified*).

   They are never stale and never block publishing.
5. **The genomics narratives do NOT follow the data under a pin change**
   (*verified*). The method changed from 2021 to 2025, which changes the GO ranking
   statistics and so the gene-set tables. Process recomputed the genomics extraction,
   but the four `_cache_interpretation_*` files stayed byte-identical. The prose
   describes rankings the tables no longer show, and nothing flags it. This is by
   design in `narrative/genomics_llm.py:140-230` ("never silently regenerate over
   narrative the user may have … approved"), but there is no approval for it
   (finding 4).
6. **There is no lock.** Two Process runs on one session (two tabs or two people)
   both run to completion, both pay the LLM call, and the last writer wins
   (*verified*). A client that disconnects does not stop the run: it finishes and
   writes its caches (*verified*). Nothing on disk says a run is in flight.
7. **An LLM failure is a silent success** (*verified*). With the gateway unreachable,
   Process returns 200 or "ok":
   - Methods is `None`;
   - one organ × sex genomics narrative is missing;
   - the failures are logged only (not in the payload);
   - the publish gate stays open.

   A Java failure, by contrast, is a `StepError 500` whose message is a raw Java stack
   line (*verified*).
8. **Process runs, and pins things, without being asked.** The core checks only that
   `integrated.json` exists (`pipeline/process_integrated.py:1707-1711`). It ignores
   the phase. Before that check it pins the method profile and the document
   definition when the session has none (*verified*: a refused Process on a
   VALIDATED session wrote `method_profile.json` (`pinned_by: "default"`, tracking
   `ntp-5day-2025.1`) and `document_definition.json` (`eras/niehs-2026`)).
9. **Run-time parameters are not saved.** The dose unit, compound name, GO ranking
   statistics and GO cutoffs posted with a Process run apply to that run only
   (*read*). The next Process without them falls back silently: the dose unit to
   recorded or `mg/kg`, the name to `identity.json` or "Test Compound", the GO
   settings to the profile's. The renderer takes the GO cutoffs from the view or
   profile, never from the run (`rendering/latex_export.py:838-847`).
10. **The HTTP Process route does not materialize.** `POST /api/process-integrated`
    returns the payload (7.4 MB, mostly base64 chart images) and stops. The section
    files need a second call, `POST /api/pool/materialize-sections`. The command line
    does both (`tooling/generate_report.py:391-409`).

---

## 1. Measured timings (all *verified*)

| Run | What recomputed | Time |
|---|---|---|
| First Process in the copied session | `ntp`, `bmds` (Java ToxicR), `sections`, `bmd_summary`, `methods` (LLM; its hash includes the session id). `genomics`, `charts`, interpretations hit. | **56.9 s**; 58.2 s on the fresh copy with its own `.bm2` cache (identical hashes) |
| Warm Process, nothing changed (fresh Python process, like the command line) | nothing; content skip guard hit | **4.0–4.4 s** (+0.09 s materialize) |
| Warm Process over HTTP on a running server (`127.0.0.1:9502`) | nothing | **1.8 s**, response 7.4 MB |
| Warm `document_step` | nothing (same `run_data`, content skipped) | **4.2 s** |
| `methods` cache deleted | one Methods LLM call | **33.4 s** (32–33 s twice in the two-tab test; 29.8 s over HTTP) |
| `methods` + one `_cache_interpretation_kidney_female_*` + `.prepare_content.fingerprint` deleted | Methods LLM; enrichment + LLM for one organ × sex | **64.6 s** (content preparation 31.5 s) |
| Method profile re-pinned 2021 → 2025 (`generate_report.method_profile`) | every data unit (`ntp`, `bmds`, `genomics`, `sections`, `charts`, `bmd_summary`) + Methods LLM; genomics narratives **not** regenerated | **101.6 s** |
| File change: `invalidate_pool_artifacts` → validate + confirm → integrate → animal report → Process + materialize → summary | everything (the `bmds` hash missed too); the interpretation caches were deleted, so 4 genomics LLM narratives + apical-BMD LLM + Methods LLM | shared `.bm2` cache: 0.0 s + 0.4 s + **24.1 s** + 0.3 s + **169.6 s** (content preparation 71.1 s; one LLM JSON retry) + 0.0 s. Re-run with its own `.bm2` cache on a fresh copy: 0.0 + 0.4 + **23.7 s** + 0.3 + **142.9 s** (content preparation 45.8 s) + 0.0 s |
| Process refused, not integrated | – | 3.0 s (pins written anyway) |
| Java broken (`BMDX_PROJECT_ROOT=/nonexistent`, `bmds` cache deleted) | – | `StepError 500` after 3.9 s |
| LLM endpoint not approved (`ANTHROPIC_BASE_URL=https://example.invalid`) | – | "success" after 6.3 s, Methods empty, one narrative missing |
| Two Process runs at once (methods cache deleted) | both did the Methods LLM call | 33.4 s and 32.2 s, both ok |
| Client gives up after 3 s (HTTP) | run continued server-side | finished at 29.8 s; `GET …/state` answered in ~5 ms throughout |

A Process on a session that had never been processed was not run. The file-change
run is the closest: every unit recomputed, including `bmds`, whose hash also missed.
HANDOFF §3 quotes 3–5 minutes for a cold session.

---

## 2. Step 9: Process

### 2.1 What the person does

- **Decides that the data are ready to compute on.** Facts stated (design, experiment
  metadata, identity and abbreviation), pins set (method profile, document
  definition), data approved (the animal accounting).
- **Starts Process** and waits: from about 2 seconds warm to 2–5 minutes cold.
- **Optionally states run parameters** (`POST /api/process-integrated` body,
  `integrated_routes.py:182-191`):
  - `compound_name`: the short name the tables and narratives use;
  - `dose_unit`;
  - `bmd_stats`: the GO ranking statistics;
  - `go_pct`, `go_min_genes`, `go_max_genes`, `go_min_bmd`: the GO display
    cutoffs.

  The command line sends `compound_name` (short name or identity name), `dose_unit`
  and any stated overrides (`tooling/generate_report.py:714-723`).
- **Reads the outcome:**
  - what was computed and what was reused;
  - what was assumed (the dose unit source, design fallbacks, method deviations);
  - what failed;
  - which sections now exist, and their approval state.

### 2.2 What a person can get wrong, and what follows

| # | Mistake | Consequence | Evidence |
|---|---|---|---|
| P1 | **Processes before stating the design, the abbreviation or the dose unit.** | The fallbacks are baked into caches and LLM prose. Dose unit: `mg/kg` with source `fallback` in this very session (methods context `dose_unit_source: "fallback"`). Name: identity name, else "Test Compound". Design: the standard design, listed in `methods.context.design_fallback`. Correcting the identity name afterwards doesn't reach Methods: `_hash_methods` keys only the session id, fingerprints and design (`pipeline/cache_plumbing.py:419-457`). The genomics narratives keep the old name too (their fast path returns the stored narrative). | dose unit *verified*; the rest *read* |
| P2 | **Processes before pinning the method or document definition.** | The core pins them itself, silently: `pinned_by: "default"`, mode `track`, the newest profile (`ntp-5day-2025.1`) and `eras/niehs-2026`. It does this even when Process is then refused. For a 2021 study that is the wrong method, and every BMD and statistic is computed under it. | *verified* (`process_integrated.py:1580,1673`; `method_profile.py:630-641`) |
| P3 | **Processes a session that tracks the newest profile after a new profile was added.** | `ensure_pin` moves the study to the new profile at the start of Process (`method_profile.py:642-647`; the move is logged and archived). Numbers change without the person choosing it. No section goes stale, so the publish gate stays open (P6). | *read* |
| P4 | **Processes before approving the data** (phase INTEGRATED). | Allowed: the INTEGRATED phase's legal actions include `REPROCESS`, and the core ignores the phase. The Methods cache key ignores `animal_report.json`: the same hash `28a878755a1d3de4` with and without it. On PFHxSAm the Methods context came out identical apart from the order of endpoint lists. That order is itself non-deterministic, and it feeds the LLM prompt. | *verified* |
| P5 | **Re-processes after approving or editing apical result sections.** | Every `bm2_<slug>.json` is rewritten with `approved: False`. A person's edit is gone, and no history copy is kept. The version manifest still reads "blessed". Note: the renderer never read the edited file anyway; it renders the apical sections from `_cache_sections_*` (`latex_export.py:762-790`). | *verified* (`bm2_body-weight`: approved and edited → after a warm Process `approved: False`, edit gone, `history/` holds only `index.jsonl`) |
| P6 | **Changes a pin or a stated fact, then re-processes, believing the gate will catch stale prose.** | It doesn't. The approved Summary stays approved, not stale, and `can_publish: true`. Methods is silently rewritten. The genomics narratives stay as they were over changed gene-set tables. | *verified* (re-pin run) |
| P7 | **Re-processes after a file change and re-accepts the "regenerated" Summary.** | The Summary text was never regenerated (P-finding 3), so the person re-blesses text written from the old data. | stale-but-unchanged text *verified*; the re-accept effect *read* |
| P8 | **Leaves or reloads during the wait.** | The run keeps going and writes its caches. Over HTTP the materialize call (a second request) never happens, so the `bm2_*` files reflect the previous run. A reloaded page has no way to know a run is in flight. If the person presses Process again, two runs overlap (P9). | continuing run *verified*; missing materialize *read* (route) |
| P9 | **Two tabs, or two people, process one session.** | Both run; there's no refusal or lock. LLM calls are paid twice, and the last writer wins on every cache. Each tab shows its own payload, which can differ from what ends up on disk, because LLM text differs run to run (*verified* separately). | both ran *verified* |
| P10 | **A Java unit fails mid-run** (classpath, JDK, a bad `.bm2`). | `StepError 500 "Processing failed: RunApicalBmds failed (exit 1): Error: Unable to initialize main class RunApicalBmds\nCaused by: java.lang.NoClassDefFoundError: …"`. On disk: units that finished before the failure keep their new caches; the others keep their old ones; materialize and `session.duckdb` are skipped. When the inputs had changed, the renderer takes the newest cache per unit, so it can mix units from two runs (*read*: `_save_cache` replaces per unit, `latex_export` reads the newest per unit). In a long-lived server the sibling tasks of the failed `asyncio.gather` (genomics, Methods LLM) are not cancelled and may still write their caches after the error is reported (*read*, from asyncio semantics; not observed). | message *verified* |
| P11 | **The BMD divergence hard stop fires** (a `.bm2` BMD and the ToxicR recompute differ by more than 25%). | `StepError 500 "Processing failed: N apical BMD endpoint(s) diverge between the .bm2 and the ToxicR recompute beyond 25% — <sex> <endpoint> (<platform>): bm2=… vs ToxicR=… (Δ…%); …"` (`process_integrated.py:136-144`, wrapped at `:1856`). It's deterministic: a retry fails the same way, since the `bmds` cache is kept. The person can't fix it in the app; it goes to the data team. Afterwards `_cache_ntp_*` exists, so the session reads as "processed" (`engine.py:54-61`) and Methods unlocks. | *read* |
| P12 | **The LLM gateway is unreachable**, or a model call fails. | Process succeeds. Methods is `None` and no Methods cache is written. If an older Methods cache with another hash is still on disk, the renderer shows that older Methods (*read*). The affected genomics narrative is missing. Content is "not cached" so the next run retries. Warnings are logged only; the payload carries none, and the gate stays open. | *verified* |
| P13 | **Re-validates while INTEGRATED** (VALIDATE is legal) and validation now finds errors. | Phase VALIDATION_ERRORS, but `integrated.json` is still there, so the core would still process the old dataset. | *read* |
| P14 | **States a dose unit that disagrees with the data, or has files recording two units.** | A stated unit wins silently. Two recorded units fall back to `mg/kg` silently (`pipeline/study_design.py:96-105`). | *read* |
| P15 | **A session file is corrupt**, or a pinned profile file was edited. | `UnreadableSessionFile` → 422 naming the file (`background_server.py:87`). `MethodProfileError` ("method profile … changed since it was pinned … write a new profile and re-pin", `method_profile.py:668-673`) is raised before the `StepError` wrapping, so the route answers with a bare 500 and no `{error}` body. | *read* |

### 2.3 What the backend refuses or derives

**Phase and legal actions** (`workflow/phases.py`). There is no PROCESS action.
Process is the `REPROCESS` action, legal in:
- `INTEGRATED` → `{APPROVE, REPROCESS, RESET, VALIDATE}` (`phases.py:109-116`);
- `APPROVED` → `{REPROCESS, RESET}` (`phases.py:117-124`).

The phase is derived at `phases.py:156-188`. *Verified* on the scratch copy: APPROVED
before and after Process; INTEGRATED with `animal_report.json` set aside; UPLOADED
after a file change.

**The core does not consult the phase.** `process_step` and `document_step` refuse
only when `integrated.json` is missing:

| StepError | status | where |
|---|---|---|
| `"No integrated data found -- run integration first"` | 400 | `pipeline/process_integrated.py:1709-1711` (*verified*) |
| `"Processing failed: {e}"`, any exception in the data or content layers, including `BmdDivergenceError` | 500 | `process_integrated.py:1856` (*verified* for the Java case) |
| `"Content preparation failed: {e}"` (`document_step`) | 500 | `process_integrated.py:1882` (*read*) |
| `BmdDivergenceError` text (inside the 500 above) | 500 | `process_integrated.py:136-144`, tolerance `pipeline/processing_helpers.py:1381` (0.25) |
| `"No '{section_key}' section to approve"` (`accept_section_step`; for `methods` and `bmd_summary` after any Process) | 404 | `workflow/steps.py:680-682` (*verified*) |
| `"dtxsid and section_key are required"` | 400 | `workflow/steps.py:676,743` |
| `GuardViolation "Advancing stale content toward final/published is refused (currency BLOCK): re-bless it (recompute so its inputs match) before promoting."` | – | `workflow/currency.py:93-98` (pure; no step calls it during Process) |
| LLM egress refusal (reaches the person only as a missing section, never as an error): `"ANTHROPIC_BASE_URL='…' is not an approved LLM endpoint. Study data may only go to: litellm.toxpipe.niehs.nih.gov (https)."` | logged | `styling_export/llm_endpoints.py` (*verified* text) |

Errors raised **before** the `try` in `run_process` are not `StepError`s:
- `MethodProfileError`, `DefinitionPinError` (pin hash mismatch);
- `UnreadableSessionFile`.

**Side effects before any refusal** (*verified*, `process_integrated.py:1580,1673`):
- `method_profile.json`: written when absent; a tracking pin is moved;
- `document_definition.json` and `.yaml`: likewise;
- `_fingerprints.json` is rewritten on every run.

**What Process derives and writes** (*verified*, file diffs):
- `_cache_<unit>_<hash>.json` for `ntp`, `bmds`, `genomics`, `methods`,
  `sections`, `charts`, `bmd_summary`. One file per unit: `_save_cache` deletes the
  other hashes of the unit (`cache_plumbing.py:98-135`).
- `_cache_interpretation_<organ>_<sex>_*` and `_cache_apical_narrative_*`, written by
  the content kinds.
- `.prepare_content.fingerprint` and `.outputs.json`: the content skip guard. A
  degraded run is not cached (`process_integrated.py:1535-1545`).
- `references.json`, `session.duckdb`, `session_parquet/`, `.session_db.fingerprint`.
- `meta.json` (`updated_at`).
- After `materialize_result_sections`: `bm2_<slug>.json` × 7.

**The content skip guard** (`process_integrated.py:1427-1550`). Content preparation is
skipped when four things are unchanged:
- the data hashes (`ntp`, `bmds`, `genomics`, `methods`);
- the declarations (compound name, dose unit, primary statistic, GO cutoffs);
- the size and mtime of `identity.json`;
- the size and mtime of `genomics_narrative_overrides.json`.

*Verified*: `content_skipped` on warm runs.

**The genomics narrative store** (`narrative/genomics_llm.py:140-230`). If a narrative
exists for an organ × sex, under any hash, it is returned as is. Only `force=True`
(the regenerate endpoint) or a deleted cache produces new text. Both the
invalidation and re-integration delete all caches.

**What "processed" means to the rest of the system.** `_cache_ntp_*.json` exists
(`engine.py:54-61`; `GET /api/wizard/{id}/processed`, `wizard_routes.py:61-74`). It
unlocks Methods readiness (`section_catalog.py:57`, `"methods": ("processed",)`).
After a failed Process the NTP cache can exist, so the session reads as processed.

**Data policy.** The egress guard holds: no study data left for a non-approved
endpoint (*verified*: the refusal above).

### 2.4 Gaps the interface must cover

Each gap is tagged:
- **Prevent**: make the wrong act impossible;
- **Check**: check before running;
- **Explain**: put a refusal or a block into words;
- **Confirm/Undo**: confirm, or allow undoing, a destructive act.

1. **Prevent: gate Process on the derived phase.** Offer it only when `REPROCESS` is
   in `legal_actions`. Never call the core outside those phases (P13). Whether
   Process should wait for APPROVED is a maintainer question (Q3).
2. **Check: before running, show and require every fact Process would otherwise
   default.** These must never default silently:
   - the **method profile**: show the pin (name, mode, by whom). An unpinned session
     must be pinned by a person before Process. A *tracking* pin that would move must
     be shown as "Process will switch this study from X to Y" (P2, P3);
   - the **document definition** pin (P2);
   - the **dose unit**: stated, recorded or fallback, with conflicting recorded units
     named (P1, P14);
   - the **compound short name**, never "Test Compound" (P1);
   - the **study design** facts: any field that would use the standard design, from
     `methods.context.design_fallback` after the run, or from
     `pipeline.study_design.study_design_facts` before it (P1);
   - **method deviations** (`session_method(id).deviations`, e.g. "asks for
     `bmds_2_7_high_dose_drop` … `toxicr_model_average` is used") and **recorded
     mismatches** (`method_profile.recorded_mismatches`). Today these only reach the
     log; on this study they were printed on every run.
3. **Prevent: no run parameters on the Process screen**, or persist them as
   declarations. The dose unit and short name belong to the facts step; the GO
   ranking and cutoffs belong to the method profile or the view (P-finding 9). A value
   used once and forgotten is a silent default on the next run.
4. **Prevent: one Process per session at a time.** This needs a per-session run lock
   in the core or the route, which is missing. Refuse a second start with a message
   naming who or what is running, and since when (P9).
5. **Explain: the reload case.** A page that loads while a run is in flight must say
   so and wait for it, not offer Process again (P8). This needs a "run in flight"
   signal, which is missing (§5.1).
6. **Prevent: Process and materialize as one act.** The interface must not be able to
   do one without the other: one endpoint, or the shared kit calls both (P8,
   finding 10).
7. **Explain: failures in the person's terms**, never the raw Java text:
   - Java unit failed: which unit (apical BMD modelling, genomics extraction), what to
     tell the maintainer, and that the previous results are partly kept (P10);
   - BMD divergence: a deviation, sized as an error, listing each endpoint with both
     values. Not retryable; it goes to the data team. Show it as a blocking error,
     never softened (P11; HANDOFF §2 "Deviations are errors");
   - LLM failure: Process returns success, so the interface must find the degraded
     outputs itself. That needs `content_errors` and a missing-Methods flag in the
     result, which are missing (P12). Show them as "[… pending]" sections with the
     cause.
8. **Confirm/Undo: re-processing over approved apical sections.** As long as finding 1
   holds, the confirmation must list each approved `bm2_*` section that will drop to
   unapproved, and each one with a `user_edited` mark whose edit will be lost. Better:
   the core keeps the approval when nothing changed (Q1).
9. **Explain: after Process, show what changed**, from the run's provenance events:
   - units recomputed versus reused;
   - LLM text that was rewritten (Methods, genomics, the apical-BMD narrative), which
     no approval protects (findings 4 and 5);
   - sections whose approval was dropped;
   - `wording_review` flags.
10. **Explain: currency gaps.** Until the core stales sections on pin and fact
    changes (finding 2), the interface must not claim that the publish gate covers
    them (Q2).

### 2.5 What the screen reads and calls

| Need | Core | Route today |
|---|---|---|
| Phase, legal actions, artifacts (`hasQuerySubstrate`, `hasKnowledgeBase`) | `WorkflowEngine(id).state()` | `GET /api/workflow/{id}/state` (existing; *verified* ~5 ms during a run) |
| Is it processed? | `engine._is_processed` (the NTP cache) | `GET /api/wizard/{id}/processed` (existing; name to retire) |
| Method pin, mode, deviations, mismatches | `pipeline.method_profile.read_pin`, `session_method(id).deviations`, `recorded_mismatches` | **missing** (a gate0-data dependency: step 7) |
| Document definition pin, drift | `document_model.definition_pin.read_pin`, `drift` | **missing** (step 7) |
| Dose unit preview (stated, recorded or fallback) | `pipeline.study_design.resolve_dose_unit` over `ensure_fingerprints` | **missing** |
| What would recompute (a plan) | the `_hash_*` functions + cache presence | **missing** (§5.1) |
| Run Process | `process_step` | `POST /api/process-integrated/{id}` (existing; returns the 12-key payload, `{error}` on `StepError`; no materialize) |
| Materialize the apical sections | `materialize_result_sections` | `POST /api/pool/materialize-sections/{id}` (existing) |
| Progress during the run | provenance events | **missing** (§5.1) |
| The last run's record | `sessions/<id>/.provenance.jsonl` (flushed per request by the middleware, `background_server.py:195-225`) | **missing** (no reader) |
| After the run: sections, readiness, publish gate | `section_catalog`, `derive_section_readiness`, `publish_readiness` | `GET /api/workflow/{id}/sections`, `/section-readiness`, `/publish-readiness` (existing). The sections route carries `enabled`, `approved`, `blocked_by` but **not** `stale`, `regenerated` or `wording_review` (*verified*). |
| Degraded content (LLM failures) | `ctx.content_errors`, `methods_result is None` | **missing** from the payload |

---

## 3. Content preparation (`document_step`, ADR-0021)

### 3.1 What it is and what the person does

`document_step` → `run_document` (`process_integrated.py:1859-1882`) runs
`run_data` (every data unit, cache-checked) and then `prepare_content_if_changed`. It
returns the content subset of the payload (`_CONTENT_PAYLOAD_KEYS`, `:1781-1793`). It
does **not**:
- build `session.duckdb`;
- materialize the `bm2_*` files;
- write `summary.json`.

It has no HTTP route (ADR-0021 "Decided"; `http-api.md`).

*Verified*: warm, 4.2 s, the same cache hits as Process, `content_skipped`.

In the person's terms there is no distinct act here today:
- with the caches warm, it does exactly what Process does, minus the side effects;
- with nothing changed, it skips;
- it has **no "force"**: it cannot re-write an LLM narrative on demand.

The skip guard restores the previous outputs, and the genomics narrative store never
regenerates. Methods is generated in `run_data` (concern [1], `:1349-1353`), not in
content preparation, so `document_step` doesn't re-run it either. On-demand
regeneration lives in separate endpoints:
- `POST /api/session/{id}/regenerate-genomics-narrative` (one organ, `force=True`);
- `POST /api/generate-methods`;
- `POST /api/generate-summary`.

ADR-0021 R4 notes that these endpoints can drift from the eager pass (model, cache).
I didn't open their code beyond the route list.

### 3.2 What a person can get wrong

| Mistake | Consequence | Evidence |
|---|---|---|
| Expects "re-prepare the text" to produce new prose after editing a prompt or changing their mind | Nothing happens: content is skipped and narratives are restored from the store | *verified* (skip); *read* (store) |
| Uses a single-section regenerate endpoint on a section the person approved | The genomics regenerate is `force=True` and skips the narrative store. Its approval semantics are outside this module (the Review module) | *read* (route docstring only) |
| Expects content preparation to be cheap | It runs `run_data` first. After any data change it is a full Process | *read* |

### 3.3 Backend refusals and derivations

Same as Process (§2.3): the 400 for "not integrated", and `"Content preparation failed: {e}"` (500).

### 3.4 Gaps

- **Explain:** don't present "Prepare content" as a separate button until it does
  something Process doesn't. Today it would be a no-op button. What the person needs
  is "rewrite this narrative" (per section, with the approval rules), which is the
  Review module's act. See §5.3 and Q4.
- **Missing core:** a forced re-preparation of named content kinds that respects
  ownership (`workflow.ownership.may_machine_write`, which no production code calls
  yet: `grep` finds it only in a comment, `narrative/genomics_llm.py:215`).

### 3.5 Reads and calls

`document_step`: no route (**missing**, and not needed for Gate 0). The per-section
regenerate endpoints exist (`llm_routes.py`) and belong to Review.

---

## 4. Reprocess and currency

### 4.1 What "reprocess" is, concretely

There is no reprocess function. Three things go by the name:
1. **REPROCESS, the action**: running Process again (the only action for Process
   in the phase table).
2. **The data reprocess** (currency's sense): files are added, replaced or removed
   after progress → `invalidate_pool_artifacts` (`pipeline/pool_state.py:148-276`),
   called from the upload routes (`upload_routes.py:159,368,554`), from per-file
   removal (`pool_state.py:358`), and from `generate_report.import_files`. It deletes:
   - `validation_report.json`, `precedence.json`, `integrated.json`;
   - `_category_lookup.json`, `genomics.sidecar.json`, `animal_report.json`;
   - every cache except `_cache_bmds_*`;
   - the query substrate and both skip-guard fingerprints.

   Then it **stales the data-dependent LLM sections** (§4.2). The person must then
   validate, integrate, approve the data, and Process again.
3. **A re-pin or re-statement followed by Process**: the caches recompute because
   their hashes include the method signature and the design facts. No staleness is
   recorded (finding 2).

### 4.2 What happens to each kind of section (the answer to brief Q2)

| Section | Author | Where its content lives | Warm Process, nothing changed | Re-pin or changed facts, then Process | File change → invalidate → re-integrate → Process | Blocks publishing? |
|---|---|---|---|---|---|---|
| `bm2_<slug>` (apical results) | programmatic | `_cache_sections_*`, which the renderer reads; `bm2_<slug>.json` holds state | file rewritten; **approved → False, edits lost, no archive** (*verified*) | the same, plus new numbers (*verified*) | invalidation leaves it approved and not stale (*verified* `bm2_hematology`); then Process un-approves it (*verified*). `wording_review` set only if it was approved and a categorical word flipped (*read*; unit test `test_workflow_steps.py:279`) | never |
| `summary` | `content_origin` says LLM; `materialize_summary` is deterministic, no LLM (`steps.py:55-87`) | `summary.json` | untouched (*verified*) | untouched, **not stale**, gate open (*verified*) | approved: `stale: true`, `regenerated: data_changed`, FINAL withdrawn (PROTECTED stays), still `approved: true`, v2 archived (*verified*); **text not rewritten** (*verified*). Unapproved and generated: staled, then rewritten by `materialize_summary`, which drops the stale flag (*read*) | yes, until re-accepted |
| `background` | LLM, from the chemical identity | `background.json` | untouched | untouched | **not staled**, not data-dependent (`section_catalog.py` `data_dependent`; *verified*) | no |
| `methods` | LLM + data-built subsections | `_cache_methods_*` only | cache hit | **rewritten silently** (*verified*) | rewritten (*verified*) | never; cannot be approved (404, *verified*) |
| `bmd_summary` (apical BMD narrative) | descriptive programmatic + analytical LLM | `_cache_bmd_summary_*`, `_cache_apical_narrative_*` | cache hit | numbers recomputed; LLM paragraph regenerated when the summary hash moves (*read*) | regenerated (*verified*, deleted by invalidation) | never; cannot be approved (404, *verified*) |
| `genomics_<organ>_<sex>` | LLM | `_cache_interpretation_*`; a person's edits in `genomics_narrative_overrides.json` win | cache hit | **not regenerated even though the gene-set tables changed** (*verified*) | regenerated silently, different wording (*verified*) | never; no section file, "read-only" per `pool_routes.py:176-183` |
| Group narratives (`animal_condition`, `clinical_pathology`, `internal_dose`) | programmatic | `_cache_sections_*` `unified_narratives` | hit | recomputed | recomputed | no; display-only |
| `references.json` | assembled | file | skipped with content | rebuilt with content | rebuilt | no |

The publish gate, `WorkflowEngine.publish_readiness()` (`engine.py:186-206`) over
`reprocess.blocking_llm_sections` (`reprocess.py:97-115`), therefore blocks today on
exactly one section kind in practice: a stale `summary.json`, or a `methods.json`
or `bmd_summary.json` saved by the old approve route. *Verified*:
`{"can_publish": false, "blocking": [{"section_key": "summary", "reason": "data_changed"}]}`
from the moment of invalidation, through validate, integrate and Process.

A side effect on the phase: `has_stale_sections` (`store.py:149-159`) sends the
phase back to UPLOADED for any stale `bm2_*` or `genomics_*` file. Invalidation no
longer stales those, so this cannot trigger from current code. Older sessions with a
stale `bm2_*` file would be stuck in UPLOADED until each is re-accepted (*read*).

### 4.3 What a person must be shown before confirming a reprocess

A file change is the moment of commitment, because the upload routes invalidate
immediately. So the confirmation belongs **before the file change**, not before the
later Process.

**Before confirming a file change on a progressed session** (*read* from
`pool_state.py:148-276`):
- the data approval (`animal_report.json`) is withdrawn, so the person must account
  for every animal again;
- validation, conflict choices (`precedence.json`) and integration are discarded and
  must be redone. That takes about 25 s of Java (*verified* 24.1 s and 23.7 s);
- every computed result except the apical BMD fits is recomputed. Expect minutes,
  plus LLM calls (*verified* 143–170 s);
- **the conflict choices are lost** (`precedence.json` is deleted): the person must
  resolve the same conflicts again;
- the sections, each by name:
  - approved data-dependent LLM sections (here: Summary) will be marked "needs
    re-accepting" and will **block publishing**. Their text will **not** be
    rewritten: to get new text the person must reopen and regenerate;
  - approved apical result sections stay approved through the file change, then lose
    their approval at the next Process. Any edit to them is lost;
  - Methods, the apical-BMD narrative and the genomics interpretations will be
    rewritten by the model with no approval step. If the person has edited genomics
    narratives, their overrides survive (*read*);
  - Background is unaffected.

**Before confirming a re-pin or a changed fact followed by Process:**
- what the change does (the method name and its deviations);
- that the numbers will change;
- that Methods will be rewritten;
- that approved text (Summary) will **not** be flagged, and that the genomics
  interpretations will **not** be rewritten. Both may now be out of step with the
  data.

That last point is the honest statement of finding 2 until the core is fixed.

**Before a plain re-Process with nothing changed:** that it is a cache hit (about 2 s
on a server), and finding 1: approved apical sections lose their approval.

---

## 5. The three concrete questions

### 5.1 What progress information exists today, per unit, and what it would take

**What exists** (*verified*, the provenance events captured from the runs above).
`common.provenance.record()` emits each event as one JSON line on the `provenance`
logger (stdout). It also accumulates the events in a per-request context variable,
which the middleware flushes at the end of the request to `sessions/<id>/.provenance.jsonl`.

| Event | Emitted by | What it tells the wait screen |
|---|---|---|
| `step_start` / `step_done {ms}` / `step_error {ms, status}` | `common.provenance.step_provenance` on `process_step`, `document_step` | the run started, ended, failed |
| `cache_hit` / `cache_miss` / `cache_saved {unit, hash, bytes}` | `pipeline.cache_plumbing._load_cache` / `_save_cache` | per unit: reused (hit) or computing (miss … saved). Units: `ntp`, `bmds`, `genomics`, `methods`, `sections`, `charts`, `bmd_summary` |
| `content_skipped` / `content_regenerated {ms}` | `prepare_content_if_changed` | content preparation reused or redone, and its duration |
| `materialized {section_key, was_approved, wording_review}` | `materialize_result_sections` | which result sections were (re)written, and whether an approval was dropped |

The order of the units is fixed by the code:
1. Layer 1: `ntp`.
2. Layer 2, in parallel: `bmds` → `sections`; `genomics`; `methods`.
3. Layer 2.5: `charts`.
4. Layer 3: `bmd_summary`.
5. Content: `genomics-llm` per organ × sex in parallel → `genomics-body` and
   `references`; `apical-bmd`.
6. The query substrate.
7. Materialize.

A miss…saved pair brackets each data unit's computation, so "computing Methods (LLM)"
can be shown between `cache_miss methods` and `cache_saved methods` (*verified*:
about 30 s).

**What does not exist:**
- **Events inside content preparation.** There's no event per content kind or per
  organ × sex LLM call, only one `content_regenerated` at the end (71 s in the
  file-change run). The interpretation builder prints plain text to stdout ("Running
  pathway enrichment…", "Gathering per-gene literature…").
- No event for the query-substrate build, or for the method or definition pin being
  written or moved.
- No events reach **another request**. They are per request (a context variable), so
  a poll from the same page cannot see them.
- **No plan up front.** Nothing says which units *will* recompute before the run
  starts. The hashes are computed inside `run_data`, and the `sections` and
  `bmd_summary` keys need the NTP output.
- No "run in flight" marker on disk or in memory.

**What it would take, still one foreground operation:**
1. **Stream the run in the same request.** The Process endpoint returns a stream of
   newline-delimited events (the provenance events, with the content kinds added)
   ending with the result or the error. The client waits in the foreground on that
   one request. There's precedent: `POST /api/generate` (`llm_routes.py:241`) and
   `POST /api/prompts/{section}/compare` (`prompt_routes.py:339`) already stream SSE.
   Needs:
   - a small hook in `provenance.record` that also pushes to a per-run queue;
   - `record()` calls for each content kind (`content_registry.run_content_plan`)
     and each organ × sex;
   - a `record()` around the substrate build.
2. **A per-session in-memory "run in flight" record**, with its start time, its last
   events and its owner. A plain `GET` can read it, which covers reload (P8) and a
   second tab (P9). The same record is the lock (gap 4). The event loop stays
   responsive during Process: `GET …/state` answered in about 5 ms throughout a 30 s
   run (*verified*). So a poll is cheap, and does not make Process a background job:
   the person's page still waits.
3. **Optionally, a plan before the run**: a dry-run function that computes every unit
   hash and reports hit or miss. That lets the confirm dialog say "about 2 seconds,
   nothing to recompute" or "Methods and four genomics narratives will be rewritten
   by the model, a few minutes". Feasible from the existing `_hash_*` functions, but
   the NTP hash needs `integrated.json` (77 MB) loaded, and `sections` and
   `bmd_summary` need the NTP cache. Missing.

### 5.2 Reprocess per section kind

See the table in §4.2 and the confirmation contents in §4.3.

### 5.3 Recomputing the data versus re-preparing the text (HANDOFF §10 Q2), in a person's terms

**Recomputing the data** turns the study's measurements into numbers: the
statistics, the BMDs and the genomics tables and charts.
- **What it reads:** the dataset, the method profile and the stated design.
- **What it produces:** the same numbers every time from the same inputs.
- **When to do it:** whenever the files, the method or the stated facts change.
- **What it costs:** seconds warm. Minutes when the method or the files change (about
  100 s for a re-pin, 143–170 s after a file change, measured).

**Re-preparing the text** turns those numbers into sentences:
- **programmatic sentences**, written by rules, which are the same every time;
- **model-written prose**: Methods, the genomics interpretations and the analytical
  paragraph of the BMD summary. These differ in wording on every regeneration
  (*verified*: two kidney/female interpretations of the same data, different
  wording).

Rule-written text is safe to redo silently. Model-written text is a new draft that a
person must read again.

How today's code maps onto that:
- **Process does both**, eagerly (ADR-0021 "EAGER-but-separated"). A person can't
  recompute data without the text being re-prepared, nor the reverse:
  - `document_step` re-runs the data layers (from cache);
  - Methods, though prose, is generated inside the data layer.
- **Whether text is redone depends on caches, not on the person's choice.**
  - Rule-written text always follows the data.
  - Methods and the apical-BMD paragraph follow the data whenever their inputs
    change.
  - The genomics interpretations follow the data only when their cache is deleted
    (file change, re-integration) or a person forces one.
- **What the screen can say honestly today.** Before and after Process, list:
  - **numbers**: what was recomputed;
  - **rule-written text**: refreshed, with nothing to re-read except a
    `wording_review` flag;
  - **model-written text**: which pieces were rewritten (new wording, read it
    again), which were kept although the data changed, and which failed.

  There should be no separate "re-prepare text" button until the core offers a
  forced, ownership-respecting regeneration (§3.4).

---

## 6. Shared-kit needs

1. **StepError explainer entries** for this module:

   | Status | Message (prefix) | Person's terms |
   |---|---|---|
   | 400 | `No integrated data found -- run integration first` | "The data hasn't been combined yet. Finish Integrate first." Unreachable if gating works. |
   | 500 | `Processing failed: RunApicalBmds failed …` / `… ExportGenomics …` | "A calculation program failed (apical BMD modelling or genomics). Your earlier results are partly kept. Tell the maintainer." Raw text behind a "details" toggle. |
   | 500 | `Processing failed: N apical BMD endpoint(s) diverge …` | A blocking **error**, sized: a table of the endpoints with both values and Δ. "Not fixable here; send to the data team." Retrying won't help. |
   | 500 | `Processing failed: …` (other) | generic, with details |
   | 500 | `Content preparation failed: …` | generic |
   | 404 | `No '{key}' section to approve` | "This section isn't a file you can approve yet." Affects `methods` and `bmd_summary` after Process. |
   | 422 | unreadable session file (`UnreadableSessionFile`, names the file) | "A session file is damaged: <file>." |
   | 500, no body | `MethodProfileError` / `DefinitionPinError` (raised outside the `StepError` wrapping) | needs the route to map them, which is missing; until then "unexpected error" with the log |

   The two routes answer differently: `integrated_routes` returns `{error}` and the
   status; `pool_routes._step_error_response` returns the same shape. The kit should
   treat any non-2xx without `{error}` as unexpected.
2. **The wait pattern** (Process; also integrate, about 25 s):
   - a modal or blocking region with an elapsed-time counter;
   - a step list of the units, each shown as "reused" or "computing" from the stream
     (§5.1);
   - no cancel, since the core can't cancel (a client that disconnects does not stop
     the run, *verified*). If a cancel is ever wanted, it needs core support;
   - an "a run is already in progress since …" state for reload and second tabs.

   The same pattern serves any long synchronous step.
3. **The confirm pattern for reprocess and file changes:**
   - a modal listing the consequences, grouped by section kind (§4.3), computed from
     the section dicts on disk (approved, `user_edited`, data-dependent, origin);
   - destructive items named one by one;
   - two-step confirmation where an approval or an edit will be lost.

   Undo:
   - section history exists for archived saves only. The approval-dropping
     materialize writes no archive, so it **cannot be undone** today;
   - pins have `history/_method_profile/`, and a re-pin is undoable by pinning back
     (with a recompute).
4. **What the state hook must re-read after Process**, or after any step that
   invalidates:
   - `GET /workflow/{id}/state`: phase and artifacts (`hasQuerySubstrate` turns true);
   - `/sections` and `/section-readiness`: Methods unlocks on "processed", and the
     `bm2_*` approvals change;
   - `/publish-readiness`;
   - the method and definition pins, which Process may have written or moved
     (endpoint missing);
   - the last run's record: degraded outputs, fallbacks, deviations (missing).

   The `sections` route should also carry `stale`, `regenerated`, `wording_review` and
   `user_edited`, which are missing; today only `publish-readiness` exposes stale,
   and only for LLM sections.
5. **The "[… pending]" placeholder** for a Methods or genomics narrative that failed
   this run (P12), with the cause.

---

## 7. Proposed module cut

| Module | Covers | Depends on | Endpoints existing | Endpoints missing |
|---|---|---|---|---|
| **process** (screen + run) | step 9: the pre-flight check (facts, pins, dose unit, deviations, plan), the blocking run with progress, the outcome summary (recomputed / reused / rewritten / failed / approvals dropped) | shared kit (state hook, explainer, wait, confirm); gate0-data (step 6 facts and step 7 pins must have routes to send the person back to) | `GET …/state`, `POST /api/process-integrated/{id}`, `POST /api/pool/materialize-sections/{id}`, `GET …/sections`, `…/section-readiness`, `…/publish-readiness` | **one** `POST` that runs process + materialize and **streams** events (NDJSON/SSE) ending in a small result (counts, `content_errors`, `dose_unit_source`, `design_fallback`, deviations, materialized with `was_approved`; not the 7.4 MB payload); `GET …/process/run` (in flight? last run's record from `.provenance.jsonl`); `GET …/process/plan` (what will recompute, pins that will move); a per-session run lock in the core; `GET` for method pin, deviations and mismatches, and for the definition pin and drift (shared with gate0-data) |
| **reprocess / currency** | the consequences preview and confirmation before a file change on a progressed session and before a re-pin; the re-accept guidance for stale sections | process; the file-intake module (it owns the upload routes that invalidate); the review module (accept/release) | `GET …/publish-readiness`; the upload routes (invalidate) | `GET …/reprocess-impact?change=files\|pin\|facts` (pure, from section dicts + `reprocess.classify_section_reprocess` + `section_catalog.is_data_dependent`); core fixes per Q1/Q2 (keep approval when nothing changed; stale on pin/fact changes) |
| **content preparation** | no screen at Gate 0. Fold into process (eager) and review (per-section regenerate) | – | the per-section regenerate endpoints (`llm_routes`), owned by review | a forced, ownership-respecting `document_step(kinds=…)`, only if Q4 says so |

Results browsing (the payload's tables, charts, BMD summary) is not part of this cut.
The payload is a 7.4 MB blob today. The document and preview modules read the same
content from caches through `load_session_data`. A process screen needs counts and
flags, not the content.

---

## 8. Open questions for the maintainer

- **Q1. Should Process keep an approved apical result section approved** when its
  numbers and wording did not change, or keep it approved with only a
  `wording_review` flag when they did? Today every Process makes them provisional
  again, edits included, with no archive, and the tests pin that. Related: should a
  person be able to edit `bm2_*` text at all? The deliverable renders from the cache,
  not from that file.
- **Q2. Should a re-pin, a change of stated design or metadata, or a tracking pin
  moving to a new profile stale the approved LLM sections**, as ADR-0027 line 97
  says? Today only a file change does.
- **Q3. Must Process wait for the data approval (APPROVED)?** Today it is legal, and
  works, in INTEGRATED.
- **Q4. Should Methods, the apical-BMD narrative and the genomics interpretations
  become approvable sections** with the same ownership and currency rules as the
  Summary? Today they are cache-only, rewritten without a person's say (Methods,
  apical-BMD), or never rewritten (genomics) when the data move.
- **Q5. What should a stale "regenerated" Summary do at the next Process:** be
  rewritten as a new, visibly marked draft knocked below approved (as HANDOFF §4.4
  describes), or stay as it is until the person reopens it (today)?
- **Q6. Should the run parameters (dose unit, short name, GO ranking and cutoffs)
  exist at Process at all,** or only as saved declarations (facts, profile, view)?
- **Q7. Is a cancel button wanted inside the wait?** The core has no cancellation
  today, and a disconnect doesn't stop the run.

---

## 9. Wall

Nothing behind the wall was needed or opened. `workflow/phases.py` and some
docstrings name old front-end files (`web/js/pool_state.js`, a walled plan document,
walled memory notes). I didn't follow them. The legal-action table is "a faithful
transcription of the old screen's button table" (`phases.py:70-75`). The
interaction designer should know that the table's shape (no PROCESS action; Process
is "REPROCESS") comes from the old screen, not from the workflow.
