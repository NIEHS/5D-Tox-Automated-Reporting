# Gate 0 — DOCUMENT: steps 10–13, the configurator, the hand-off, the Bookshelf

Workflow analysis for the new interface (HANDOFF §3 steps 10–13, §4.2–§4.5, §7, §8;
ADRs 0005, 0015, 0018, 0020, 0021, 0029). Written 2026-10-14 by the workflow analyst.

**Legend.** **[V]** = verified: I ran it on a scratch copy and saw the result.
**[R]** = read from code only. Code references are `file:line` in the `ui-redesign`
worktree.

**Data and method.** Scratch copies under
`/workspace/ui-team/_scratch/analyst-document/sessions/` (with `SESSIONS_DIR` and
`OUTPUT_DIR` pointed there):
- `DTXSID50469320_doc`: PFHxSAm under a new id, so it renders as a new study (2026 era);
- `DTXSID50469320`: the same data under its own id, so it renders from NIEHS-10's own
  2023 definition;
- `DTXSID50469320_stale`: for the reprocess/currency test;
- `DTXSID1020431` + `_rat` + `_mouse`: NIEHS-13, a report over two studies.

The scripts I ran are in `/workspace/ui-team/_scratch/analyst-document/scripts/`
(`e1_counts` … `e7_config`). None of these runs read `.bm2` files through the LMDB
bm2 cache:
- I ran no Process and no Java;
- the cache is read only by `pipeline/process_integrated.py` (`cached_bm2_jsons`) and
  the upload routes;
- rendering reads `integrated.json` and the `_cache_*.json` files.

I did not run Background generation (an LLM call plus ATSDR/IRIS lookups), the
Overleaf/GitHub transport (no token in the sandbox), or the default-template editor
(it rewrites git-tracked files).

The 14 test files of HANDOFF §4.7 that cover these steps all pass [V]: 231 tests,
including authoring steps, catalog, readiness, labels/guard, ownership, currency,
reprocess, engine, the state route, preview surface, definition pin, views, document
config and version-cause snapshots.

---

## 0. The numbers first

### 0.1 How many sections a report has [V]

The workflow has three ways to count sections, and they give different answers:
- **Catalog rows** (`catalog_for_session`): 16 for every session.
- **Readiness rows** (`derive_section_readiness`): the 14 non-family catalog keys plus
  every `bm2_*`/`genomics_*` file on disk.
- **Section files that can be accepted.** `accept_section_step` needs a file on disk.

| | PFHxSAm (NIEHS-10, one study) | NIEHS-13 (rat + mouse) |
|---|---|---|
| Readiness rows (`/api/workflow/{id}/sections`) | **21**: 7 front-matter (display only), 3 group narratives (display only), 4 singletons, 7 `bm2_*` | report session **14** (no `bm2_*`: they live in the members); rat **20**; mouse **18** |
| Section files on disk that can be accepted | **9**: background, summary, 7 `bm2_*` | **13** across 3 sessions: background (report); rat 6 `bm2_*` + summary; mouse 4 `bm2_*` + summary |
| LLM or derived prose with **no** section file, so it can't be accepted and never blocks publishing | methods, bmd_summary narrative, **4** genomics interpretations (liver/kidney × M/F) | methods ×2, bmd_summary ×2, **10** genomics interpretations (5 tissues × female × 2 species) |
| Content units a careful reviewer would look at | **≈15** (9 files + 6 cache-only), plus 7 front-matter rows | **≈27** (13 files + 14 cache-only), plus front matter |
| Render-tree nodes | 78 (2023 definition) / 110 (2026, under a new id) | 110 |
| Pages: docx → PDF (LibreOffice) / LaTeX PDF | 75 / 52 (2023 definition); 84 / 47 (2026) | 148 / 70 |

What follows from these counts:
- "20+ sections" (HANDOFF §10 Q4) is right for one study. A two-study report spreads its
  sections over **three sessions**, and nothing in the workflow aggregates them (§3).
- Of the **8 LLM-written** content units in PFHxSAm, only **2** (background, summary)
  can be accepted or can block publishing today:
  - `accept_section_step(…, "methods")` → `StepError(404): "No 'methods' section to approve"` (`workflow/steps.py:680`);
  - the same for `bmd_summary` and `genomics_liver_male` [V].

### 0.2 What rendering costs [V]

Each render takes the data from disk (no cache shared between requests). Timings come
from this sandbox; the machine is multi-core (user CPU time was about 11× wall time).

| Surface, via `render_preview` | PFHxSAm, 2023 definition | PFHxSAm, 2026 definition | NIEHS-13 (two studies) |
|---|---|---|---|
| html | 9.8 s (492 KB) | 12.7 s | 16.7 s |
| docx | 9.9 s (1.3 MB) | 11.9 s | 20.5 s |
| jats | 7.5 s | 10.7 s | 16.9 s |
| bits (zip) | 8.2 s | 9.6 s | 17.1 s |
| bookshelf (page) | 8.0 s | 10.2 s | 17.2 s |
| **Split:** data load + tree (`_preview_inputs`) | 7.3–10.2 s | – | 16.4–16.9 s |
| **Split:** emitting the surface only | docx 1.9 s; html/jats/bits/bookshelf < 0.1 s | – | docx 4.0 s; others ≤ 0.1 s |
| docx → PDF (`docx2pdf`, LibreOffice) | **+2.5 s** (75 pp) | +2.6 s (84 pp) | +3.4 s (148 pp) |
| LaTeX: bundle (includes the data load), then `tect` | 6.8 s + **3.3 s** (52 pp) | 9.0 + 3.1 s (47 pp) | 16.9 + 3.0 s (70 pp) |

**The conclusion for §10 Q5.** The cost is **loading the data** (7–17 s), not
typesetting. Once the data is loaded:
- a faithful Word preview adds about 2 s (docx) plus 2.5–3.4 s (PDF);
- a LaTeX PDF adds about 3 s;
- so the HTML content view saves only **≈5 s** over a faithful PDF.

Today every route loads the data again. So:
- each `/Bookshelf/<id>` page view costs 8–17 s;
- each right-rail download costs 10–20 s more;
- `materialize_preview` already shares one load between the deliverable and the HTML view (`rendering/preview_surface.py:187`).

The two targets also paginate very differently: the docx gives 75 pages and the LaTeX
PDF 52 for the same report. A "faithful" preview therefore depends on the target. One
generic PDF won't do.

### 0.3 What the gate lets through [V]

All of the following happened on PFHxSAm while `publish_readiness()` said
`{"can_publish": true, "blocking": []}`:
- **9 of 9** section files were unapproved;
- the strict LaTeX build raised `PendingContentError` with 5 markers:
  - `[Section pending: Authors]`, `[Section pending: Contributors]`;
  - 3 `[Placeholder: … not in the study data]` (animal source; dose rationale; test article source/lot);
- under the 2026 definition: 12 markers; NIEHS-13: 14.

---

## 1. Step 10: Background and Summary

### What the person does
- **Background.** Asks for it to be generated, from the chemical's identity (PubChem,
  CompTox, ATSDR, IRIS, …, plus one LLM call). Then reads it, checks the citations,
  and accepts it, or asks for it again with a different model.
- **Summary.** Two paths:
  - the default is **deterministic**: `materialize_summary` → `narrative.report_summary`, no LLM, `source: "generated"`;
  - an optional **LLM** version comes from the prompt workshop: `/api/generate-summary`, then "use run", which writes `source: "model"`.

  The person picks which text stands and accepts it.
- In passing, the person decides whether Methods, the apical-BMD narrative and the
  genomics interpretations are good enough. There is no approval act for these (§0.1).

### What they can get wrong, and what follows
| Mistake | Consequence |
|---|---|
| Regenerates the Background over one they had accepted | The approved text is replaced with no warning. `generate_report.background` writes `approved: False, archive=False` (`tooling/generate_report.py:461-468`) with no guard check. The HTTP path is "generate → client saves" (`/api/generate` returns text; `/api/session/save-section` writes it). **Verified:** save-section over an approved background left `approved=False`, `facts=None`, and `version` stayed 2, so **the approved v2 text was lost**. History holds only v1 (§2). |
| Generates the Background where ATSDR/IRIS can't be reached | The CLI refuses and saves nothing: `"WARNING: {ATSDR, IRIS} could not be reached — background not generated (run where these sources are reachable, e.g. the NIEHS network)"` (`tooling/generate_report.py:448`). **The HTTP route `/api/generate` has no such refusal** (`web_routes/llm_routes.py:169-240`): it streams whatever `generate_background` returns [R]. |
| Accepts a Background whose citations don't resolve | It is published with dead `[n]` references. `background.json` carries `citation_report` (`{inventory_size, cited, issues, unresolved_count}`) [V], and `/api/session/{id}/citation-warnings` lists them, but nothing blocks the accept. |
| Uses a model the study's data may not reach | The summary LLM path refuses through `narrative.model_policy` (`ModelNotAllowed`). The Background path has the egress guard in `styling_export/llm_endpoints.py` [R]. In this sandbox (dev, published data), not exercised. |
| Doesn't notice the Summary is the deterministic draft, not an LLM text, or the reverse | `content_origin` classifies `summary` as LLM (`workflow/content_origin.py`), so the reprocess logic stales and gates it either way. Its `source` field ("generated" or "model") is the only truth about who wrote it [R]. |
| Expects Summary to be "locked" until Background or a result is approved | `KIND_UNLOCK["summary"] = ("background","results")` (`workflow/section_catalog.py:57`), so readiness says `summary.enabled = false` [V]. But `summary.json` already exists (written by `materialize_summary`), **renders in every deliverable**, and **can be accepted** (accept_section_step doesn't consult readiness) [V]. Readiness gates nothing. |
| Edits Methods or a genomics interpretation | There is no in-app editing (ADR-0018). A genomics edit lives in `genomics_narrative_overrides.json`. `regenerate-genomics-narrative` **clears that override** before regenerating (`web_routes/llm_routes.py:677-683`) [R], with no backup. |

### What the backend refuses or derives
- `materialize_summary` **refuses to overwrite** an approved summary, or one not
  generated by itself: `if prior.get("approved") or prior.get("source") != "generated": return {"written": False}` (`workflow/steps.py:72-73`). **Verified:** over an approved summary it returned `{'ok': True, 'written': False, 'paragraphs': 0}` and left the file untouched.
- CLI Background refusals (`tooling/generate_report.py:448, 454, 459`), verbatim:
  - `"background generation returned no paragraphs — not saved"`;
  - `"background has no references (sources unreachable?) — not saved"`.
- `/api/generate`: `400 "Identity must include at least a name or CASRN"` (`web_routes/llm_routes.py:191`).
- `/api/generate-summary`: `422` on a template error, `500 "Summary generation failed: …"` (`llm_routes.py:536-542`).
- Background is **identity-only**: a data reprocess never stales it (`_IDENTITY_ONLY_KEYS`, `workflow/section_catalog.py`). **Verified:** after `invalidate_pool_artifacts`, the Background was not marked stale.

### Gaps the interface must cover
- **Prevent:** never offer "regenerate" on an accepted or user-owned section without
  an explicit release first, or a confirm that names what will be replaced. The
  backend doesn't enforce `may_machine_write` on any write path (§2), so the interface
  is today the only guard. Ask the backend to enforce it (§2 gaps).
- **Check before running:** that the identity has a name or CASRN; that ATSDR/IRIS can
  be reached (the HTTP path must refuse as the CLI does, or the screen must show
  which sources were unreachable, from `bg_data.unreachable_sources`); which model, and
  whether policy allows it.
- **Explain:** for the Summary, whether this is the deterministic draft or an LLM
  run (`source`, `run_id`, `template_version`, `model_used`), and the numbers the model
  wasn't given (`unmatched_numbers`, returned by `/api/generate-summary`). For the
  Background, the citation report and the sources that were unreachable.
- **Never default silently:** the model (the default is `claude-sonnet-4-6`,
  `narrative/background_writer.py:57`); the chemical identity used for lookups
  (resolved from CASRN or name, `generate_report.py:430-441`).
- **Undo:** generating writes `archive=False`, so the previous text isn't kept. The
  screen needs a generate path that archives (a "draft beside the approved text"),
  or it can't offer undo.

### What the screen reads and calls
| Need | Core | Route |
|---|---|---|
| Generate Background (stream progress) | `narrative.data_gatherer.gather_all` + `narrative.background_writer.generate_background` | `POST /api/generate` (SSE; **returns text, doesn't save**) |
| Save the Background as a draft, server-side, with the source-reachability refusal | `tooling.generate_report.background` logic | **missing** (only the CLI does generate+refuse+save) |
| Deterministic Summary | `workflow.steps.materialize_summary` | **missing** (CLI and notebook only) |
| LLM Summary run / use run | `narrative.summary_llm.generate_summary`; prompt store | `POST /api/generate-summary`; `POST /api/prompts/summary/runs/{id}/{run}/use` (archives the prior version; writes `approved: False`) |
| Citation problems | `narrative.citation_check` | `GET /api/session/{id}/citation-warnings` |
| Methods / genomics re-preparation | `workflow.steps.document_step` (ADR-0021) | **missing** as a route; `POST /api/generate-methods`, `POST /api/session/{id}/regenerate-genomics-narrative` exist |

---

## 2. Step 11: Reviewing sections (accept, release, facts, guards, maturity, history, restore)

### What the person does
For each section:
- reads it;
- decides "this is right" (**accept**), or "I need to reopen this" (**release**, with
  a reason);
- may look back through its versions and **restore** one.

A section that changed under them (stale, regenerated, or a wording flip) must be
re-read and re-accepted.

### What they can get wrong, and what follows
| Mistake | Consequence | |
|---|---|---|
| Accepts a section whose data changed underneath it (stale LLM text) **without the text having been rewritten** | After a pool change, an approved LLM section is marked `stale`, `regenerated: {reason: "data_changed"}`, FINAL dropped and PROTECTED kept (`pipeline/pool_state.py:249-273`). **Nothing rewrites it**: `materialize_summary` won't touch an approved summary. So re-accepting blesses **the old text against the new data**, and the gate opens. | **[V]**: summary stale → re-accepted → `can_publish: true` |
| Accepts a stale section **before re-validating, integrating and processing** | **Verified:** the session was in phase `UPLOADED` with `integrated.json` deleted, yet the summary re-accept made `can_publish: true`. The gate doesn't look at the phase. | [V] |
| Approves a programmatic apical section, then runs Process again | `materialize_result_sections` (run at the end of every Process and by `POST /api/pool/materialize-sections`) **silently un-approves it**: `approved: False` is hard-coded (`workflow/steps.py:155`) and it is saved `archive=False` (`:170`). Lost: `approved_at`, `facts`, and any edited narrative. The version manifest still reads `blessed` for that version, so the record contradicts the file. `wording_review` is set only when a categorical word flipped. | **[V]**: `bm2_body-weight` before: `approved=True facts=['final','protected']`; after: `approved=False facts=None`, `current_version_status = blessed`, no archive written |
| Approves through the route with empty or partial content | `/api/session/approve` **writes the posted `data` as the section** (`web_routes/session_routes.py:767-965`). An empty `data` replaced the Summary with an empty approved v2. Restore brought it back. | [V] |
| An auto-save, or a regenerate saved through `save-section`, overwrites an approved section | No guard (`session_routes.py:1037-1077`). It writes `approved: False`, drops the facts, keeps the version number and archives nothing, so **the approved text is unrecoverable**. | [V] |
| Releases a section without saying why | `release_section_step` accepts `reason=""` (`workflow/steps.py:721-751`) and the route takes it as optional. The trail gets `{"cause":"revise","status":"working"}` with no reason. | [V] |
| Releases a section that doesn't exist (wrong key) | Returns `{"ok": True, …}` (steps `:744-751`; the route returns `{"ok": true}` regardless, `session_routes.py:1103-1134`). A typo looks like success. | [V] |
| Discards a section | `/api/session/discard-section` deletes the file **and abandons its history**, with no confirm (`session_routes.py:1141-1161`, `session_store.delete_section`). | [V]: `bm2_hormones.json` gone |
| Restores an old version | It comes back **already approved**: the archived copy keeps `approved: True` and `facts`, and gets a fresh `approved_at` (`session_routes.py:1323-1329`). No version event is recorded, and the version number goes up. A restore is an implicit re-approval. | [V]: v1 restored as v3, `approved=True`, `facts=['final','protected']` |
| Reads "protected" wrongly after a release | Afterwards, `facts=['protected']` and `may_machine_write=False`, but `protection_level` (the visual mark) = **OPEN**, because it keys on `approved`/`user_edited`, not on the facts (`workflow/ownership.py:161-178`). The two "protected" meanings disagree. | [V] |
| Thinks the deliverable shows what's approved | `protection_map` runs in `latex_export._number_and_list` (`rendering/latex_export.py:1095`), but the session-loaded section dicts don't carry `approved`. After accepting the Summary, `data["protection"]` was `None`, so **no surface marks approved content**. | [V] |
| Looks for methods / genomics / BMD-summary text to approve | It can't: there is no section file, so accept returns 404 (§0.1). | [V] |

### What the backend refuses or derives
- **accept_section_step** (`workflow/steps.py:656-718`):
  - `StepError(400): "dtxsid and section_key are required"` (`:676`);
  - `StepError(404): "No '{section_key}' section to approve"` (`:680-682`).

  On success:
  - sets `approved=True` and `approved_at`;
  - pops `stale` and `wording_review`;
  - promotes the facts to FINAL (which auto-sets PROTECTED);
  - records `{cause:"edit", status:"blessed"}` against the **same** version (archive=False);
  - returns `{ok, section_key, approved, version}`.

  [V] The step does **not** validate the key's shape (`"../meta"` → 404 only because the file is absent); the route validates it through `resolve_section_key` (`_KEY_PART_RE`).
- **release_section_step** (`:721-751`): `StepError(400)` with no key. Otherwise:
  - `approved=False`;
  - the HUMAN_RELEASE demote (FINAL withdrawn, PROTECTED stands);
  - `revised: {reason}`;
  - the trail entry `{cause:"revise", status:"working", reason}`.

  [V] It is a no-op that still answers ok when the file is absent.
- **The fact ratchet** (`workflow/labels.py:107-153`): a demote with no reason raises
  `GuardViolation("Demoting 'final' is a reversal (lowers guard or maturity) and requires a recorded reason (human release or currency-forced); refused.")`.
  Currency: `GuardViolation("Advancing stale content toward final/published is refused (currency BLOCK): re-bless it (recompute so its inputs match) before promoting.")` (`workflow/currency.py:300-304`).
  **No step or route reaches either of these today** [R]. They are pure-layer guards.
- **The machine guard** `may_machine_write(section, force=False)` (`workflow/ownership.py:134`):
  false when the section is approved, user-edited, or holds FINAL/PROTECTED [V].
  **No production code calls it** [R]: grep finds it only in tests and in a comment in
  `narrative/genomics_llm.py:215`. The genomics path has its own "return the stored
  narrative" rule.
- **The version trail** (`pipeline/session_store.py:231-410`):
  - archives are written only on `archive=True` saves: the approve route, invalidate, restore, "use run";
  - the cause manifest `history/<key>/index.jsonl` records `edit/blessed`, `revise/working(+reason)`, `reprocess/needs-re-bless`;
  - `current_version_status()` reads it;
  - `GET /api/session/{id}/history/{key}` lists **archives only** (version, approved_at), not the causes or reasons [V];
  - route messages: `"No approved '{key}' section found"` (404, `session_routes.py:1202, 1294`); `"Version {n} not found"` (`:1232, :1320`); `"section_key and version are required"` (`:1285`); restoring the current version answers `"Already the current version"`.
- **The approve route's refusals** [V]:
  - `"section_type must be one of: background, bm2, bmd_summary, genomics, methods, summary"` (`session_routes.py:817`);
  - `"bm2 sections need bm2_slug (or data.filename)"` (`:887`);
  - `"genomics data must include organ and sex"` (`:920`).
- **Readiness** (`workflow/section_readiness.py:114-174`): `{enabled, blocked_by, approved}`.
  - It reads the approved flags only: no stale, regenerated, wording_review, source or version.
  - `/api/workflow/{id}/sections` merges it with the catalog's `kind`, `approvable`, `instance_of` and `region` [V].

### Gaps the interface must cover
- **Prevent:**
  - the interface must never post section content to approve: accept is a state change only (`accept_section_step`), and needs a route that takes `{section_key}` only;
  - no front-end auto-save may write a section file;
  - the interface must refuse to accept while the session is not processed, or while the section is stale **and its text was not regenerated** (show this as "the data changed; this text was written before it changed").
- **Check before running:** the section exists (accept), and the key is real (release),
  rather than trusting a 200.
- **Explain:** why a section is stale (`regenerated.reason`), what flipped
  (`wording_review` entries such as `"Male|Liver.direction_adj"`), its version status
  (`blessed` / `working` / `needs-re-bless`), and the reason for each past release.
- **Confirm or undo:**
  - **release:** requires a reason in the interface (the core accepts none); undo = accept again (verified symmetric: accept → release → accept restores `facts=['final','protected']`);
  - **restore:** confirm, and say it brings the version back *as approved*;
  - **discard:** confirm, and say history is abandoned (no undo);
  - **regenerate over owned content:** confirm.
- **Backend fixes the interface can't paper over.** For the orchestrator. Each is
  verified above.
  1. `materialize_result_sections` must keep an approved section's approval and
     facts (or archive it and mark it for re-review), not wipe it.
  2. `save-section` and every machine write must consult `may_machine_write`.
  3. Writes must archive before they overwrite owned content.
  4. Restore should be a `workflow.steps` step that records a version event.
  5. The version-cause manifest needs a route.
- **Never default silently:** the release reason; which version a restore brings back.

### What the screen reads and calls
| Need | Core | Route |
|---|---|---|
| The section list, with kind, approvable, enabled, blocked_by, approved | `catalog_for_session` + `WorkflowEngine.derive_section_readiness` | `GET /api/workflow/{id}/sections` (exists) |
| Per section: stale, regenerated, wording_review, source, model, version, version status | `store.read_section_dicts`, `session_store.current_version_status` | **missing** (only `GET /api/session/{id}`, which is 7.7 MB / 0.2 s for PFHxSAm and returns everything [V]) |
| One section's content | the section JSON | **missing** (slim, per key) |
| Accept (state only) | `workflow.steps.accept_section_step` | **missing** (`/api/session/approve` requires the client to post the content) |
| Release with a reason | `workflow.steps.release_section_step` | `POST /api/session/unapprove` (exists; reason optional; always 200) |
| History list / one version | `session_store` archives | `GET /api/session/{id}/history/{key}[?version=n]` (exists) |
| Cause trail (edit, revise, reprocess, with reasons) | `session_store.read_version_history` | **missing** |
| Restore | (route logic) | `POST /api/session/{id}/restore` (exists; should move to a core step) |
| Discard | `session_store.delete_section` | `POST /api/session/discard-section` (exists; destructive) |
| Section slice preview | `render_surface(…, section_filter=…)` handles only `apical` / `genomics` / `charts` | **missing** per node |

---

## 3. Step 12: The publish gate

### What the person does
They decide the report is ready to go out: they look at what is still blocking and
clear it, then download or hand off the deliverable.

### What they can get wrong, and what follows
| Mistake | Consequence | |
|---|---|---|
| Takes `can_publish: true` to mean "ready" | The gate checks **only stale LLM sections** (`workflow/reprocess.py:97-115`). It passes with **0 of 9 sections approved**, 5 pending placeholders, and the phase at `UPLOADED` with no `integrated.json`. | [V] |
| Publishes a two-study report | The report session's gate ignores its members: with the rat member's Summary stale, rat → `can_publish: false`, while the report → `can_publish: true` (phase `EMPTY`, no legal actions). | [V] |
| Changes the method profile, a document definition or the dose unit, and expects the approved text to be flagged | Only a **file-pool mutation** (`invalidate_pool_artifacts`) sets `stale`. A Process run after a pin or parameter change recomputes the caches but stales nothing. | [R] |
| Takes the phase `UPLOADED` as "the data changed, sections are stale" | `has_stale_sections` reads only `bm2_*`/`genomics_*` (`workflow/store.py:149-159`). `bm2_*` are never staled any more, and `genomics_*` files don't usually exist, so a stale Summary or Background doesn't move the phase. | [R] |
| Downloads a draft from the Bookshelf | `/Bookshelf/{id}/report.docx` and `report.pdf` are **not gated** ("not the gated final export", `web_routes/bookshelf_routes.py:217-259`). The Word link is labelled just "Word (.docx)". | [R] |

### What the backend refuses or derives
- `WorkflowEngine.publish_readiness()` → `{can_publish, blocking:[{section_key, reason}]}`
  (`workflow/engine.py:186-206`), where `reason` = `regenerated.reason`, else
  `"stale"` [V].
- It is enforced on:
  - `GET /api/preview/{id}/download`: `409 {"error": "Report is not publishable: re-accept the sections a data reprocess invalidated ({keys})", "blocking": […]}` (`web_routes/preview_routes.py:107-127, 138`);
  - `POST /api/export-overleaf-bundle`, only when the body names a dtxsid (`export_routes.py:119-125`);
  - the CLI: `"publish gate closed — re-accept the regenerated sections: {keys} (or pass --draft)"` (`tooling/generate_report.py:740-742`).
- It is **not** enforced on: `/Bookshelf/*` downloads, `/api/compile-pdf`, `/api/commit-local`, `/api/preview/{id}/view`, or `render_preview`.
- The Overleaf bundle **also** refuses pending markers (strict):
  `422 "Report has unresolved placeholder sections and cannot be exported as a deliverable."` with `pending: [...]` (`export_routes.py:156`).
  No other path checks pending markers.
- Nothing sets the report-grain `published` fact (`workflow/labels.py`). There is no "publish" act; the gate only gates downloads.

### Gaps the interface must cover
- **Explain:** show the gate as a checklist, not a boolean. The checklist items:
  - stale LLM sections, with their reasons (exists);
  - sections never accepted (derivable from readiness);
  - sections that can't be accepted at all: methods, bmd_summary, genomics (derivable from the catalog vs the files);
  - pending placeholders (`PendingContentError.markers`, only by rendering with `strict=True`);
  - phase not `APPROVED`, or the session not processed;
  - for a report over several studies, each member's gate.
- **Prevent:** label every download not taken through the gate as a draft.
- **Never default silently:** "draft" vs "final" on every download.
- **Backend:** a fuller readiness: one route that composes the items above and folds
  in the members of `studies.json`. Which items *block* is a maintainer question (§11).

### What the screen reads and calls
`GET /api/workflow/{id}/publish-readiness` (exists, partial). Missing:
- the pending-marker list (render with strict, or a dedicated scan);
- member aggregation;
- the unapproved list.

---

## 4. Step 13: Render, preview, downloads

### What the person does
Looks at the report as it will be delivered, in the target they will hand off (Word,
Overleaf/LaTeX, Bookshelf). Downloads it.

### What they can get wrong, and what follows
| Mistake | Consequence | |
|---|---|---|
| Treats the HTML view as the deliverable | HTML is a content proof. Pagination differs: 75 pp (docx→PDF) vs 52 pp (LaTeX) for the same report. | [V] |
| Downloads a materialized preview after changing a section | `/api/preview/{id}/download` serves whatever file was last materialized. `manifest.json` records only `{view, ts, deliverable, files}` (`preview_surface.py:212-221`), with no input hash, so a stale preview can't be detected. | [R] |
| Asks for the LaTeX preview | `materialize` with `surface: "latex"` → `501 "Preview surface 'latex' is provisioned but not implemented yet"`; `"pdf"` → `400 "Unknown surface: 'pdf'"`. | [V] |
| Renders a session with no identity | The title silently becomes "Test Article" / "000-00-0" (`rendering/preview_surface.py:127-140`); likewise `/api/sync-document` (`export_routes.py:324-325`). This breaks the "nothing invented" rule. | [R] |
| Hands off a document with "[… pending]" placeholders | Every surface prints them visibly. Only the Overleaf bundle refuses them. | [V] |
| Expects the Overleaf bundle to match the screen | `/api/export-overleaf-bundle` and `/api/compile-pdf` build from a **client-posted body** (`marshal_export_data(body)`, using `build_session_tree` or the global tree). They use **neither `load_session_data` nor the study's own definition**, unlike every other surface (`build_view_tree`). | [R] |

### What the backend refuses or derives
- `render_preview(id, surface, view, downloads, shelf)` (`rendering/preview_surface.py:252-273`). Surfaces: docx, html, jats, bits, bookshelf. latex raises NotImplementedError; anything unknown raises ValueError.
- `materialize_preview` writes `sessions/<id>/preview/<view>/` and archives the prior set under `history/<ts>/` (`:162-222`).
- Pending placeholders always render visibly. Strict mode (`PendingContentError`) applies only to the LaTeX bundle.
- `/api/preview/{id}/view|download`: `404 "No preview materialized yet — POST …/materialize first"` (`preview_routes.py:99, 143`) [V].
- `/api/compile-pdf`:
  - `503` when `tect` is missing;
  - `422 "LaTeX compilation failed."` with the log tail (`export_routes.py:229, 280`).
- Bookshelf PDF:
  - `503 "PDF conversion (docx2pdf) failed on the server. The DOCX preview and the facsimile page are unaffected."` (`bookshelf_routes.py:251`);
  - `500 "Could not render the DOCX preview."` / `"…PDF preview."` (`:227, :248`).

### Gaps the interface must cover
- **Explain:** which target a preview is faithful to; that HTML is a content view; the
  render time to expect (§0.2: 10–25 s, so show a wait indicator).
- **Prevent:**
  - a download of an out-of-date materialized preview: the manifest needs a fingerprint of its inputs (section versions + cache hashes + pins), or the interface must re-materialize before downloading;
  - draft downloads labelled as final.
- **Check before running:** identity present; pending markers listed.
- **Backend:**
  - a LaTeX/PDF surface built from the session (the code exists in `tooling/generate_report._render_latex`, `generate_report.py:500-532`);
  - a docx→PDF surface in `materialize_preview`;
  - one data load shared by every surface asked for.

### What the screen reads and calls
| Need | Route |
|---|---|
| Render on demand | **missing** as a generic `/api` route (only `/Bookshelf/{id}[/report.docx|pdf]`) |
| Materialize, view, download | `POST /api/preview/{id}/materialize`; `GET …/view`; `GET …/download` (gated) |
| LaTeX PDF from the session | **missing** (`/api/compile-pdf` is body-based) |
| Overleaf bundle from the session | **missing** (`/api/export-overleaf-bundle` is body-based) |
| Supplemental data folder | `GET /api/sessions/{id}/supplemental/[name]` (exists) |

---

## 5. The configurator (HANDOFF §7)

### What the person does
- States the front matter: authors, contributors, publication details, strain designation.
- Chooses or edits the document definition: structure, phrasing, appendices.
- Pins it: track, or fixed.
- Saves report views: filters by organ, sex, assay, gene; charts.
- Adjusts layout styles.
- Rarely (the maintainer): edits the shared default templates.

### What they can get wrong, and what follows
| Mistake | Consequence | |
|---|---|---|
| **Opens the structure editor on a published study and saves without changing anything** | `GET /api/document-config/{id}` opens on the **base grammar** (`is_default: true`, `default_document_yaml()`, `document_config.py:153`), not on the study's definition. Saving writes `sessions/<id>/document.yaml`, which **outranks the study's definition** (`view_config.build_view_tree`, `:226-247`; ADR-0029 resolution order). PFHxSAm's tree went from **78 to 67 nodes** while `definition_name()` still reported `studies/DTXSID50469320/document`, and the pin didn't change. | **[V]** |
| Saves a structure that validates but isn't a report | A single heading saves (200). The section catalog became **empty**, so every section dropped out of the workflow, readiness and the review list. | [V] |
| Saves a view with a misspelled organ or sex | Accepted (`{"organs":["livr"], "sex":["Mle"]}` → 200). The render silently lost 4 of 18 tables. | [V] |
| Saves a view with unknown chart names, or styles with unknown keys | Accepted (`charts: ["nonsense"]` → 200; `styles: {heading1: …}` → 200, ignored). | [V] |
| Wipes the front matter by saving a partial object | `POST /api/document/{id}/front-matter` replaces the file (`wizard_routes.py:124`). Saving `{}` erased `strain_designation`. **No history.** | [V] |
| Misspells a publication key (`DOI`) | Dropped silently by `clean_front_matter` (`rendering/front_matter.py:115-141`). | [V] |
| Edits the **default** template | `save_default_document_yaml` (`document_config.py:423-457`):<br>• rewrites the git-tracked `templates/niehs-5day-report.yaml`, dropping its comments (safe_dump);<br>• rebuilds the in-process tree live;<br>• **rewrites the golden test fixture** `tests/unit/fixtures/document_tree_golden.json`.<br>Every era extends the base grammar, so every TRACK session re-pins at its next Process, and every FIXED session reports drift. | [R], not run: it writes tracked files |
| Expects the TRACK pin to name what rendered | `ensure_pin` runs only before Process (`definition_pin.py:141-148`). A render between Process runs uses the current files whatever the pin says. | [R] |
| Thinks pinning FIXED freezes everything | Outside the pin: the content files a node names, and the renderers' code (ADR-0029 §12). | [R] |

### What the backend refuses or derives [V]
- Structure saves are validated as a full tree build before anything is written
  (`document_config.py:188-211`). Verbatim 422s:
  - `"invalid YAML: while parsing a flow mapping …"`;
  - `"template node 'x' uses type 'nonsense', which is not in the catalog"`;
  - `"duplicate node id 'x' in document tree — node ids must be unique (…)"`;
  - `"Request must include a non-empty 'yaml' string."`.
- `/api/document-structure/validate`: `{"ok": false, "error": "template node 'x' of type 'table' is missing required binding 'platform'", "node_id": "x"}`.
- Views: `"filter dimension 'organs' must be a list or an {area: ...} mapping, got str"`; `"the 'default' view cannot be deleted"`; `"view 'charts' must be a list of type strings, or null"` (`view_config.py:111-155`).
- Styles: enum/length/colour checks on the known blocks only (`document_config.py:245-297`).
- Pin:
  - `pin_definition` archives the old pin under `history/_document_definition/`;
  - `drift()` describes the files moving on;
  - a hand-edited snapshot fails with `DefinitionPinError("…no longer matches its pin (hash … → …); pinned definitions are immutable — re-pin instead")` (`definition_pin.py:89-92`).
- History: `document.yaml`, `styles.yaml` and views are archived before overwrite (`history/_document_yaml`, `_styles_yaml`, `_views/<name>`). `restore_document_version` / `restore_styles_version` exist in core. Front matter has **no history**.

### Gaps the interface must cover
- **Prevent:**
  - **Bug to fix:** the structure editor must open on the definition that actually renders (`build_view_tree`), not the base grammar.
  - A save that changes which definition renders must be confirmed, by name ("this report will stop using NIEHS-10's own definition").
  - A structure that removes approvable sections: warn with the list of sections that would leave the workflow (diff the catalogs before and after).
- **Check before running:** filter tokens and chart names against the controlled vocabularies (organs, sexes, assays, chart types); front-matter fields as a form with declared keys, never free YAML.
- **Explain:** which definition this report renders from (the study's own, its era, a pinned snapshot, a session override); pin mode and drift; what TRACK vs FIXED will do at the next Process.
- **Confirm or undo:** every save archives except the front matter, so the interface can offer undo for structure, styles and views. Front matter needs history (backend).
- **Restrict:** default-template editing belongs to the maintainer role. It writes tracked files and test fixtures.

### What the screen reads and calls
| Need | Route |
|---|---|
| Structure editor (raw YAML, or structured through catalog/parse/dump/validate) | `GET/POST /api/document-config/{id}` (exists; opens on the wrong default); `/api/document-structure/{catalog,parse,dump,validate}` |
| Which definition renders, and its pin and drift | **missing** (core: `document_definition.definition_name`, `definition_pin.read_pin`, `drift`, `pin_definition`) |
| Structure / styles history and restore | **missing** (core: `list_document_history`, `restore_document_version`, …) |
| Views | `GET/POST/DELETE /api/views/{id}[/{name}]` |
| Layout styles | `GET/POST /api/layout-style/{id}`; defaults at `/api/layout-style-default` |
| Front matter | `GET/POST /api/document/{id}/front-matter` (no history) |
| Default templates (maintainer) | `/api/document-config-default`, `/api/report-filters-default`, `/api/layout-style-default` |
| A study's own definition (`templates/studies/<id>/document.yaml`, ADR-0029) | **missing**: read only, today |
| Method profile pin (step 7, shown here for context) | **missing** (core: `pipeline.method_profile`) |

---

## 6. Hand-off and return (ADR-0005, ADR-0018)

### What the person does
- Hands the report to Word or Overleaf for human authoring.
- Later brings the changes back, so they reach the content model and so BITS.

### What they can get wrong, and what follows
| Mistake | Consequence | |
|---|---|---|
| Edits in **Word** and expects the edits to come back | There is no Word ingest: no reading of `w:ins`/`w:del` (ADR-0018 "Gap"). The docx does carry per-node TOC bookmarks (`docx_generator._toc_bookmark_name(node_id)`, `:474`), a possible attribution anchor. **Edits made in Word are lost to the app.** | [R] |
| Edits in Overleaf, then downloads Word or BITS | Reconciled overrides (`_document_overrides.json`) are applied by `html_generator` (`:1380-1403`) and `latex_generator` **only**. `docx_generator` and `jats_generator` never read `data["overrides"]`. **Committee edits don't reach Word or Bookshelf.** ADR-0005 says they must reach BITS. | [R] |
| Uses a workspace (`SESSIONS_DIR` set) | `roundtrip.overrides._DEFAULT_SESSIONS_DIR` is fixed to `<repo>/sessions` (`roundtrip/overrides.py:75`), and `latex_export` calls `load_overrides(dtxsid)` with that default (`:1007-1008`). A workspace reads, and the reconcile writes, the **maintainer's** overrides. | [R] |
| Commits locally from a session | `/api/commit-local/{id}` renders from a **posted body** (ADR-0005 Am.3 §B, by design), with the global tree and no publish gate (`export_routes.py:434-479`). The new interface's rule is "render from disk". These conflict. | [R] |
| Pushes when the committee's edits haven't been pulled | Refused with 409 (Am.3 §C; `export_routes.py:~520-525`). | [R] |
| Pulls before ever pushing | `409 "Nothing to pull yet — Commit Local and Push to GitHub first."`; with no binding, `400 "This report has no GitHub repo bound — link one first."` | [R] |

### Gaps
- **Explain:**
  - Word is a one-way hand-off today;
  - which edits came back from Overleaf ("edited in Overleaf" per node; overrides carry `edited_at`, `source_commit`);
  - that an Overleaf edit is not in the Word/BITS outputs.
- **Prevent:** hand-off while the gate is closed (no gate on commit-local).
- **Backend:**
  - apply overrides on docx and jats;
  - overrides must honour `SESSIONS_DIR`;
  - a session-based commit;
  - Word ingest (an ADR-0018 open question, so the maintainer's).

### Routes
- Existing:
  - `GET/POST /api/repo-binding/{id}`, `GET /api/repo-status/{id}` (derived git state, Am.3 §F);
  - `POST /api/commit-local/{id}`, `/api/push-to-github/{id}`, `/api/pull-from-github/{id}`, `/api/provision-report/{id}`;
  - `POST /api/export-overleaf-bundle`.
- **Missing:** Word return; a list of the overrides per node; a session-based bundle.

---

## 7. The Bookshelf (kept), where it meets these steps

- **The shelf** `/Bookshelf` lists every session with `integrated.json` + `_cache_sections_*`, so **once processed, it's on the shelf**, approved or not (`bookshelf_routes.py:81-85`).
  - Published or unpublished, and the publication order, come from `web_routes.compare_routes.published_report` (`bookshelf_routes.py:53, 162`). **That function lives in a walled file.** The kept Bookshelf depends on it. I did not open it. If the new interface needs "which published report is this", that lookup should move out of `compare_routes` (a question for the maintainer, §11).
- **The facsimile** `/Bookshelf/<id>` is `render_preview(surface="bookshelf")`, fresh per request, **8–17 s** (§0.2).
  - Its banner says "preview" (unpublished study), "a version of the report (already published) … to evaluate the pipeline" (a published study's generated report), or "as published" (a companion) (`rendering/bookshelf_preview.py:692-732`).
  - It **says nothing about approval state or the publish gate**.
- **The right rail** (`_download_links`, `bookshelf_routes.py:49-73`):
  - "PDF (preview)" and "Word (.docx)": ungated, rendered on demand; the Word link isn't marked as a preview;
  - "Compare with <report>" → `/Compare/<id>`: walled; I noted the link and did not follow it;
  - "Published content (<report>)" → the companion;
  - on a companion: "Generated report" and its Compare link.
- **Hook-up:**
  - the review screen links "see it as it will read on Bookshelf" to `/Bookshelf/<id>`;
  - the deliverables screen should use the same docx→PDF path as the rail's PDF;
  - the Compare link should be pointed at whatever the new design compares with (WALL.md allows this);
  - the facsimile and its downloads should carry a draft/approval notice derived from publish readiness.

---

## 8. HANDOFF §10 Q4: what a person must see, per section, to approve knowingly

From the section files and the derived state (each field exists on disk or in a core
function today, except where marked):

1. **The text as it will print.** That is the section's slice of the deliverable
   (per-node preview: missing), with its "[… pending]" markers highlighted.
2. **Who wrote it.** Several fields:
   - the catalog `kind` (llm / programmatic / derived / authored);
   - the real `source` (`generated` = deterministic, `model` = an LLM run, absent = a legacy or client save);
   - `model_used`; `run_id` / `template_version` (summary LLM);
   - for Background, the sources that couldn't be reached.
3. **Whether it is current.**
   - `stale` and `regenerated.reason`;
   - **whether the text was rewritten since the data changed.** Nothing records this today: a stale approved Summary keeps its old text (§2);
   - `wording_review` flips (finding and slot, old → new word).
4. **Evidence checks.**
   - Background: `citation_report.unresolved_count` and `issues`;
   - Summary LLM: `unmatched_numbers`;
   - genomics: `unresolved_citations`;
   - Methods: `design_fallback` (the standard design used for facts the data lacks; `generate_report.py:402-405`);
   - BMD summary rows: `bmr_config: "inferred"`.
5. **What changed since I last approved it.** A diff against the last *blessed*
   version: archives plus the `index.jsonl` cause trail (edit / revise / reprocess, with
   reasons). The archive exists only when the overwrite archived. accept, release,
   materialize and save-section don't, so the screen can't always show the diff
   (backend).
6. **Its guard.**
   - approved / FINAL / PROTECTED;
   - whether a machine may overwrite it (`may_machine_write`);
   - whether it blocks publishing (an LLM kind that is stale).
7. **Its dependencies.** `blocked_by` (readiness), and for the Summary, which approved
   sections it was built from.

For 20–30 units (§0.1), grouping is natural:
- front matter;
- the LLM narratives (gate-relevant);
- the apical result sections (programmatic: numbers refresh, the wording can flip);
- genomics.

Group by *what needs attention* (stale or regenerated → flipped wording → never
reviewed → accepted), not by document order. The kind and currency fields above are
enough to derive the groups.

---

## 9. Shared-kit needs (from this module)

1. **The refusal explainer.** It maps to plain words:
   - `StepError(status, message)`, and `{error}` JSON from the existing routes, which aren't uniform (`{"error": …}`; 409 with `blocking`; 422 with `pending`; 422 with `log`);
   - `GuardViolation`;
   - `DefinitionPinError`;
   - the validation 422s.

   The messages it must cover verbatim are quoted in §1–§6. Add the soft
   "success that did nothing" cases the core answers with 200 (release of a missing
   section; `materialize_summary` `written: false`). The interface must not report
   them as done.
2. **Confirm or undo**, one pattern with three strengths:
   - **reversible:** release (undo = accept, verified symmetric); view/style/structure saves (archived, so undo = restore);
   - **reversible but meaningful:** restore (brings a version back as approved); regenerate over owned content (needs an archive to be undoable);
   - **irreversible:** discard section (history abandoned); front-matter overwrite (no history); default-template edits (tracked files).

   Each needs a reason field where the trail records one (release: required by the
   interface).
3. **The "protected" mark.** It needs **one** definition. Today:
   - the visual mark (`protection_level`) keys on `approved`/`user_edited`;
   - the machine guard (`may_machine_write`) also on the FINAL/PROTECTED facts;
   - after a release they disagree [V].

   The hook should serve both, and the kit draws one mark: "a machine won't overwrite
   this", plus the human-facing maturity (final / working).
4. **The "[… pending]" placeholder.** The markers come from the renderers
   (`PendingContentError.markers`: `[Section pending: X]`, `[Placeholder: …]`,
   `[Table data pending: …]`, `[Narrative pending: …]`). The kit should show the list,
   and link each marker to the section or configurator field that would fill it:
   - Authors/Contributors → front matter;
   - animal source / dose rationale / test article lot → study design (step 6).
5. **The derived-state hook** must serve, without the front-end computing any of it:
   - `state()` (phase, legal actions);
   - the section list (catalog + readiness) **plus per-section currency** (stale, regenerated, wording_review, source, version, version status, guard);
   - publish readiness **as a checklist** (§3), aggregated over `studies.json` members;
   - which definition renders, plus pin and drift.
6. **The wait indicator** for renders (10–25 s) and Background generation (SSE progress). These are foreground waits, like Process.

---

## 10. Proposed module cut (steps 10–13, the configurator, the Bookshelf hook-up)

| Module | Covers | Depends on | Existing endpoints | Missing endpoints / core fixes |
|---|---|---|---|---|
| **D1 Review** | step 11 + the gate checklist of step 12: section list grouped by attention, review panel (§8), accept / release / restore / discard | shared hook; D3 for the per-section preview | `/api/workflow/{id}/sections`, `/section-readiness`, `/publish-readiness`; `/api/session/unapprove`; `/history`; `/restore`; `/discard-section` | state-only accept (`accept_section_step`); release with a required reason that answers 404 on a missing key; per-section slim read with currency; version-cause trail; restore as a core step; **core:** machine-write guard on every write, `materialize_result_sections` keeping approvals, archive before overwrite; readiness checklist + member aggregation |
| **D2 Narrative generation** | step 10: Background, Summary (deterministic / LLM), Methods and genomics re-preparation | D1 (where the result lands); model policy | `/api/generate` (SSE), `/api/generate-summary`, `/api/generate-methods`, `/regenerate-genomics-narrative`, `/api/prompts/*`, `/citation-warnings` | generate-and-save-as-draft server-side with the source refusal; `materialize_summary` route; `document_step` route; "draft beside approved" (no overwrite of owned text) |
| **D3 Preview & deliverables** | step 13: faithful preview per target, HTML content view, downloads (gated / draft) | D1 (gate); shared wait indicator | `/api/preview/{id}/materialize|view|download`; `/Bookshelf/{id}/report.docx|pdf` | session-based LaTeX bundle + PDF; docx→PDF surface; one data load for several surfaces; preview input fingerprint (staleness); render-on-demand `/api` route; pending-marker scan |
| **D4 Hand-off & return** | ADR-0005 Overleaf (bind, commit, push, pull, overrides), ADR-0018 Word | D3 | `/api/repo-binding`, `/repo-status`, `/commit-local`, `/push-to-github`, `/pull-from-github`, `/provision-report`, `/export-overleaf-bundle` | session-based commit; overrides on docx and jats; overrides honouring `SESSIONS_DIR`; override list per node; Word ingest (decision first) |
| **D5 Configurator** | §7: front matter, definition + pin, views, styles; maintainer-only default templates | shared vocab fields; affects D1 (catalog) and D3 (tree) | `/api/document-config/{id}`, `/api/document-structure/*`, `/api/views/*`, `/api/layout-style*`, `/api/document/{id}/front-matter`, `*-default` | open on the rendering definition (bug); "which definition renders" + pin/drift/re-pin routes; history/restore routes for structure/styles; front-matter history; vocab checks on filters and charts |
| **D6 Bookshelf hook-up** | links from the new interface to `/Bookshelf/<id>`, the companion, the Compare link's destination, a draft notice on the facsimile and its downloads | D3, D1 | `/Bookshelf`, `/Bookshelf/{id}`, `/report.docx|pdf`, `/api/sessions/{id}/supplemental/*` | the publish-state notice; repointing the Compare link; moving `published_report` out of `compare_routes` |

**Order.** D1 and D5 can start in parallel against mocks once the hook's contract is
fixed. D3 next (D1's per-section preview uses it). D2, D4 and D6 last. The core fixes
under D1 (machine-write guard, materialize keeping approvals) protect every other
module, so they should land first.

---

## 11. Open questions for the maintainer (only what the code can't settle)

1. **What does "ready to publish" require?** Today it is only "no stale LLM section". Should it also require:
   - every approvable section accepted;
   - no "[… pending]" placeholder;
   - phase `APPROVED`, processed;
   - every member of a report over several studies?

   Which of these block, and which only warn?
2. **Methods, the apical-BMD narrative and the genomics interpretations** are LLM text with no approval unit. Should they become approvable section files, as the apical results did (ADR-0018 "materialize"), so the review and the gate cover them?
3. **Approval on Process.** `materialize_result_sections` un-approves apical sections on every run. Is any part of that intended? For example, should a programmatic section keep its approval when only its numbers changed, and be flagged when a word flipped?
4. **Stale text that nothing rewrites.** After a data change, an approved Summary is marked stale but keeps its old text, and re-accepting clears the gate. Should the system produce a fresh draft beside it, to accept or reject, before re-acceptance is offered?
5. **Currency beyond the file pool.** Should a change of method profile, document definition, or Process parameter (dose unit, GO cutoffs) also stale approved text?
6. **Restore.** Should restoring a version bring it back approved (as now), or as a draft to accept?
7. **Release reason.** Should it be required? The core accepts none.
8. **Reports over several studies.** Are sections approved in the member sessions (where the files are) or in the report session? Is there one gate for the book?
9. **The structure editor's starting point.** ADR-0029 §10 keeps the base grammar as "the editor's default". But saving it overrides a study's own definition (verified). Should the configurator edit:
   - the study's definition (git-tracked `templates/studies/<id>/document.yaml`);
   - a session copy of the composed definition;
   - or only views?

   And who may edit the default templates (they rewrite the golden fixture)?
10. **Faithful preview.** Is LibreOffice (`docx2pdf`, here) acceptable as the Word preview in the new interface, or must it be OnlyOffice `x2t` (host)? Is 10–25 s per faithful preview acceptable, or should previews be materialized ahead?
11. **Bookshelf downloads.** Should the PDF/Word links on `/Bookshelf/<id>` be gated or labelled draft? Where should its "Compare" link point?
12. **Word return** (ADR-0018 open questions): its priority; read tracked changes only, or also write them; attribution by the existing per-node bookmarks or by heading.
13. **Overleaf commit source.** ADR-0005 Am.3 makes the commit render from the browser's posted body. The new interface renders from disk. May the commit move to `load_session_data` + the study's tree?
14. **"Published".** Nothing sets the report-grain `published` fact. Is publishing an act in the interface (with its louder guard, ADR-0015), or outside the app?
15. **`published_report` lives in the walled `compare_routes.py`** and the kept Bookshelf calls it. May it move to an unwalled module, so the new interface can know which published report a session reproduces?
