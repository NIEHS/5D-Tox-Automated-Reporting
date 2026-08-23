# 0016 — A canonical per-session query substrate + rendering domains (materialized DuckDB)

- **Status:** **Proposed (2026-08-21)** — design for review; no code yet.
- **Deciders:** Dan Svoboda
- **Related:** ADR-0013 (package layout), ADR-0014 (UI-agnostic workflow engine),
  ADR-0003 (document-component model — the `data_key` binding seam this
  generalizes). Consumes the entity inventory in this repo's data sources;
  sibling doc `docs/data-integration-system.html` explains the current (pre-ADR)
  data flow.

---

## Context

Today a session's study data is **scattered across four kinds of on-disk
artifact**, each with a bespoke reader:

1. `integrated.json` — the merged apical BMDProject (~68 MB; per-animal response
   arrays dominate).
2. `*.sidecar.json` — per-animal metadata the integration pivot discards
   (selection, observation day, terminal flag, raw values).
3. the gene-expression `.bm2` — genomics is re-extracted from the **raw upload**
   at process time (`export_genomics`), never from `integrated.json`.
4. `_cache_*.json` — the derived report content (NTP stats, BMDS, genomics
   tables, summaries, narratives).

Three problems follow, and they are the same root cause seen from three angles:

- **No queryable substrate.** There is no place to ask "which endpoints in males
  had a BMD below 10 mg/kg across both organs?" without hand-walking JSON. The
  knowledge base (`bmdx.duckdb`, `ToxKBQuerier`) already proves the DuckDB
  pattern for *literature*; session *study data* has no equivalent.
- **`integrated.json` is mistaken for a ready-store.** It is an *input to
  compute*, not a self-contained queryable representation — the pivot lost the
  per-animal detail, so report code must also read sidecars and the raw `.bm2`.
- **The genomics data-source bypass.** `_extract_genomics` re-reads the raw
  `.bm2` from `files/`, violating the "read from integrated + sidecars, never raw
  files" invariant. It works, but it is fragile (depends on the upload still
  sitting under the recorded filename) and inconsistent with every other
  platform.

Critically, the inventory turned up that **no existing artifact holds a tidy
`(animal, endpoint, dose, day, value)` long-form row.** That tidy long form —
the natural unit of a relational query — exists only implicitly (sidecar
`observations[]`, or `ProbeResponse.responses` positionally aligned to
`Treatment`). Materializing it is the single highest-value thing this ADR adds.

**Forward intent.** This app is expected to generalize from a toxicology-report
tool into a general **data-processing + journal-article generation** platform. A
canonical, queryable, study-agnostic data model is the foundation that makes that
generalization tractable; the ad-hoc query page is the first power-user tool over
it.

**The deeper generalization: a document binds to queries, not to hardcoded
caches.** Today every renderer resolves a node's content the same way —
`data.get(node.data_key)` (`rendering/render_common.py:376`,
`latex_generator.py:1028`, `html_generator.py:894`, `docx_generator.py:1340`),
where `data` is a flat dict `marshal_export_data` populates from the `_cache_*`
JSON with **hardcoded keys** (`apical_sections`, `genomics_sections`,
`background`, …). A `DocNode` carries `data_key` (`document_node.py:35`) —
literally *"which key in the report data dict holds this node's content"* — and
`render_capabilities.COMPONENT_CATALOG` declares `requires=("data_key",)` per
component type. This is a clean indirection that is currently wired to a *fixed*
set of keys. If `data_key` could instead resolve against a **named, saved query**
over the query substrate, a power user could author a new report section by
writing a query — no pipeline change, no new cache. That is what makes the
platform extensible to arbitrary journal articles: **a "rendering domain" is a
named, versioned set of views over `session.duckdb` that a document's nodes bind
to.** Taken to its end, the same seam supports *"start from any data-processing
pipeline, generate a paper"* — because the document already declares the *shape*
each node needs, an arbitrary upstream pipeline can feed the paper by conforming
its output to that shape, rather than by us writing bespoke glue per pipeline (see
"Beyond the internal substrate" below). This ADR builds the substrate first (the
DB + read-only SQL), then names the binding seam it unlocks (rendering domains)
as the arc's north star — with an explicit staging so the two don't have to land
together.

---

## Decision

Introduce a **canonical per-session materialized DuckDB** —
`sessions/<dtxsid>/session.duckdb` — populated by the pipeline as a normal
build output, and a **read-only SQL query layer** over it. The existing JSON
caches remain (they are the render inputs); the DuckDB is the *analytical /
queryable* projection of the same data. First consumer: a power-user **SQL
console** page.

The substrate is also the foundation for a second, longer-horizon capability: a
**rendering domain** — a named, versioned set of saved queries/views over
`session.duckdb` that a document's nodes bind to, generalizing the current
hardcoded `data_key` → `data[data_key]` lookup. The SQL substrate ships first and
stands alone; rendering domains are staged on top of it (Phase E) once the schema
and query API have proven out. The two are decoupled on purpose: the query
console delivers immediate power-user value; the rendering-domain binding is the
architectural payoff that makes the platform extensible to non-tox articles.

Three properties are non-negotiable:

1. **Materialized, not virtual.** The DB is written to disk during
   integrate/process (like `integrated.json` and the caches), not assembled
   on-the-fly per query. This gives stable, fast, inspectable query targets and a
   real schema to document.
2. **Read-only at the query boundary.** The query API opens the DB read-only;
   user SQL can never mutate a session. (DuckDB `read_only=True`, as
   `ToxKBQuerier` already does.)
3. **Study-agnostic core + domain extensions.** The schema separates a generic
   spine (studies, subjects, groups, measurements, analyses) from
   tox-specific tables (bmd_results, gene_sets, adversity_signatures). The spine
   is what generalizes to journal articles in other domains; the extensions are
   pluggable.

### Why materialized DuckDB (vs. the alternatives considered)

- **vs. query view over existing JSON (on-demand load):** rejected as the
  end-state — it papers a query surface over the scattered sources without fixing
  the root problem, re-parses 68 MB per query, and can't express the tidy
  long-form that doesn't exist in any single JSON today. (It remains a viable
  *interim* if we want the query page before the writer lands — see Phasing.)
- **vs. Postgres/SQLite service:** DuckDB is already a dependency, is
  embedded/file-per-session (matches the session-as-folder model), is columnar
  (fast analytical scans over the wide observation tables), reads Parquet/JSON
  natively, and the `ToxKBQuerier` precedent means the team already knows it.
- **vs. keeping JSON authoritative and adding indices:** doesn't yield SQL, the
  interaction model the power-user toolkit is built around.

---

## The canonical schema

A **generic spine** (domain-neutral — this is what carries to non-tox journal
articles) plus **tox extensions**. Mirrors `bmdx.duckdb` conventions: natural
`VARCHAR` PKs, singular snake_case columns, `DOUBLE`/`INTEGER`/`BOOLEAN`,
junction tables for many-to-many, no declared FK constraints (join discipline by
convention), idempotent `INSERT OR IGNORE` loads.

### Generic spine

```
study(dtxsid PK, name, casrn, species, strain, duration, route, vehicle,
      integrated_at, source_platform_count)                 -- one row per session
    ← TestArticle + ExperimentDescription + Meta + identity.json

experiment(experiment_id PK, dtxsid, name, platform, provider, sex, organ,
           data_type, ref)                                  -- ref = the @ref join key
    ← DoseResponseExperiment + ExperimentDescription

source_file(file_id PK, dtxsid, filename, platform, data_type, tier,
            file_count, experiment_count)
    ← Meta.source_files + _fingerprints.json

subject(subject_id PK, dtxsid, external_id, sex, dose, selection)  -- "animal"
    ← sidecar animals{} + animal_report.animals[]
       (selection = Core vs Biosampling; external_id = the study's animal id)

dose_group(dtxsid, platform, sex, dose, n)                  -- design counts
    ← animal_report.dose_design + Treatment

measurement(dtxsid, subject_id, platform, endpoint, day, value_num,
            value_raw, terminal)                            -- THE tidy long form
    ← sidecar observations[]  (value_raw keeps non-numeric "NA";
       value_num is the parsed float or NULL)
       *** this table does not exist in any current artifact ***
```

`measurement` is the keystone: one row per (subject × endpoint × day), the
grain every ad-hoc question ultimately reduces to.

### Tox extensions

```
endpoint(dtxsid, platform, label, first_col_header)         -- distinct endpoints
apical_result(dtxsid, platform, sex, endpoint, bmd, bmdl, bmd_status,
              loel, noel, direction, model_name, responsive, trend_marker)
    ← _cache_bmd_summary(apical/bmds) + _cache_ntp TableRow

bmd_stat(owner_kind, owner_id, metric, mean, median, minimum, weighted_mean,
         sd, weighted_sd, fifth_pct, tenth_pct, lower95, upper95)
    ← the 10-key stat block reused across _category_lookup, genomics go_bp,
      adversity rows  (owner_kind ∈ {gene_set, adversity, endpoint})

gene(dtxsid, organ, sex, gene_symbol, probe_id, bmd, bmdl, bmdu, direction,
     fold_change, r_squared, fit_p_value)
    ← genomics all_genes / top_genes

gene_set(dtxsid, organ, sex, stat, go_id, go_term, go_level, bmd, bmdl, bmdu,
         n_genes, n_genes_with_bmd, direction, n_up, n_down, fishers_p)
    ← genomics gene_sets_chart_by_stat  (the SUPERSET — cutoffs applied at query
      time, not baked in; consistent with ADR filtering phase 4)

gene_set_gene(dtxsid, organ, sex, go_id, gene_symbol)       -- junction
    ← gene_set.genes semicolon-string, exploded

adversity_signature(dtxsid, organ, sex, signature_id, title, active, n_passed,
                    n_genes, percentage, bmd, bmdl, bmdu, direction, fishers_p)
    ← _extract_adversity_signatures
```

Notes:

- **`gene_set` stores the superset** (all GO terms, both directions) — the GO
  cutoffs and organ/sex/gene filters from the ADR filtering work are applied *in
  the query*, keeping the DB filter-agnostic (same principle as the phase-2/4
  caches). A default view (`gene_set_filtered`) can bake the template defaults.
- **`bmd_stat` normalizes the 10-key block** that currently recurs in three
  places, so a query can ask for any percentile of any BMD without knowing which
  JSON it came from.
- The spine is deliberately domain-neutral: `study/subject/group/measurement/
  analysis` reads sensibly for any dosed-cohort experiment, not just NTP tox —
  the generalization seam.

---

## The query layer

### Backend

- `pipeline/session_db.py` (new) — the writer: `build_session_db(dtxsid, store)`
  reads the existing computed artifacts (integrated.json, sidecars, the
  `_cache_*` payloads already in memory at process time) and materializes
  `session.duckdb`. Runs at the end of `run_process` (all inputs are already in
  hand there) and is invalidated/rebuilt on the same trigger that wipes the
  caches (re-integration).
- `query/session_query.py` (new) — a read-only querier mirroring `ToxKBQuerier`:
  opens `session.duckdb` with `read_only=True`, exposes `run_sql(dtxsid, sql)`
  with **hard guards** (see Safety) returning `{columns, rows, row_count,
  truncated}`; plus typed convenience methods later for the guided builder (v2).
- `web_routes/query_routes.py` (new) — `POST /api/query/{dtxsid}` (body:
  `{sql}`) → JSON result; `GET /api/query/{dtxsid}/schema` → table/column
  catalog for the console's schema sidebar.

### Frontend (power-user toolkit v1 — SQL console)

A new `/wizard`-adjacent page (or a `/tools/query` route): a SQL editor, a
"Run" button, a results grid with CSV/JSON export, and a schema browser
(tables + columns) fed by the schema endpoint. React, same Vite app as the
wizard. The guided query builder is explicitly **v2**, layered over the same
`/api/query` substrate once the schema proves out.

### Safety (read-only SQL from a browser)

The query boundary must be genuinely read-only and bounded:

1. Open DuckDB `read_only=True` — writes/DDL fail at the engine.
2. Reject non-`SELECT`/`WITH` statements and multi-statement bodies at the API
   (defense in depth; parse the leading token, forbid `;`-chains).
3. `LIMIT`-cap results (e.g. 10k rows) with a `truncated` flag; enforce a
   statement timeout.
4. The DB is per-session and contains only that session's study data — no
   cross-session or secret exposure. (The knowledge-base DB stays separate.)

---

## Rendering domains — a document binds to queries (the north star)

This is the capability the substrate exists to enable. It is **staged as Phase E**
(after the console) and described here so the earlier phases are built with it in
mind, not retrofitted for it.

### The seam that already exists

The render path has one uniform indirection: a `DocNode` names a `data_key`, and
every surface resolves `data.get(node.data_key)`. Today `data` is assembled by
`rendering/report_data.py::marshal_export_data` from the `_cache_*` JSON with a
**closed set of hardcoded keys** (`apical_sections`, `genomics_sections`,
`background`, `methods`, …). Adding a genuinely new kind of section today means:
touch the pipeline to compute it, add a cache, add a `marshal_export_data` branch
to populate its key, and add a `COMPONENT_CATALOG` entry. Four coordinated code
changes for one section.

### The generalization

A **rendering domain** replaces the hardcoded population of `data` with a
**resolver over named queries**:

```
rendering domain = {
  name: "pfhxsam-standard",
  queries: {
    "apical_sections":   <SQL or saved-view ref over session.duckdb>,
    "male_liver_genes":  "SELECT ... FROM gene WHERE organ='liver' AND sex='male' ...",
    ...
  },
  shape_adapters: { "apical_sections": "section_cards", ... }   -- query rows → the
                                                                   dict shape a node expects
}
```

A node's `data_key` then resolves in priority order:

1. a **domain query** named `data_key` (new) → run the view, adapt rows to the
   node's expected shape;
2. else the **legacy cache key** (unchanged) — so every existing report keeps
   working with an empty/absent domain.

The `shape_adapters` are the one non-trivial piece: nodes expect specific dict
shapes (section cards with `tables_json`, a chart payload with `png_b64`), and a
SQL result is `{columns, rows}`. A small, closed registry of adapters
(`rows → section_cards`, `rows → table_block`, `rows → kv_block`) bridges the two;
the `COMPONENT_CATALOG` already declares each type's `content_kinds`, which tells
the resolver which adapter a given node needs.

### What this collapses

Once a document binds to queries, three mechanisms that are separate today become
**special cases of one thing — a saved query**:

- **Filters** (ADR filtering work): `sex.apical = [male]` is just a `WHERE
  sex='male'` in the domain's `apical_sections` query. The subtractive-filter
  machinery becomes "author a narrower query."
- **Report versions** (`versions/<name>.yaml`): a version *is* a rendering domain
  — its structure (the tree) plus its query set. `resolve_version_filters` and
  `build_version_tree` converge into "load a rendering domain."
- **Method options** (BMD stat, GO cutoffs): a generative choice becomes a query
  parameter (`WHERE stat = :bmd_stat`) or a parameterized view, computed
  on-demand and memoized by the substrate rather than by a bespoke cache key.

This is why the substrate is worth building even though the JSON caches stay: the
caches remain the fast default render path, but the *extensibility* comes from
being able to define new content by query instead of by pipeline code.

### Why it is staged, not immediate

Rendering domains are deliberately **Phase E**, gated behind three things the
earlier phases establish:

1. the schema must be real and stable (Phase A) — you cannot author durable
   queries against a moving target;
2. the read-only query API and its safety guards must exist (Phase B) — the
   resolver runs domain queries through the same bounded path as the console;
3. the shape-adapter registry needs the `measurement`/`apical_result`/`gene`
   tables populated to prove the round-trip (query → adapt → render) reproduces a
   known section before it is trusted to define new ones.

Until Phase E lands, `data_key` resolves exactly as today (hardcoded caches);
nothing regresses. Phase E is additive: the resolver tries a domain query first
and falls through to the cache, so the default report is untouched.

### Beyond the internal substrate: arbitrary pipelines and the shape contract

The fullest form of the north star is *"start from any data-processing pipeline,
generate a paper."* The rendering-domain seam gets most of the way there for a
reason worth stating explicitly: **the document already declares the shape it
needs.** `data_key` + `COMPONENT_CATALOG.content_kinds` + the shape-adapter
registry together are a *shape contract* in all but name. So data can reach
`data[data_key]` from two directions:

1. **Query-sourced (internal)** — a domain query over `session.duckdb`. This is
   the path phases A–E build; the upstream pipeline is *our* pipeline, and its
   emissions land in the DB as tables.
2. **Emission-sourced (external)** — an upstream pipeline we do **not** own emits
   a dataset, ingested at a boundary. This is where "any pipeline → a paper"
   actually lives, and it is the case the user's caveat is about.

There are two ways to wire an external pipeline, and this ADR takes a position on
which to prefer:

- **Shape-driven ingest (favored).** The *document structure* defines the shape
  contract; the external pipeline's output must conform to it (validated at the
  ingest boundary, bridged by the same closed shape-adapter registry). The
  pipeline stays a black box — we own only the ingest boundary and the shape
  check, never the pipeline itself. This is the caveat made concrete: *external
  output data with a shape defined by the document structure may suffice.* The
  paper pulls a declared shape; conforming data — from anywhere — fills it.
- **Pipeline-driven emission (discouraged as a default).** The pipeline declares
  its *own* emitted shape and the document components are derived from it. This is
  the maximal "any pipeline → paper" vision, but it needs bespoke, per-pipeline
  glue. **One-off custom pipelines are explicitly not worth first-classing** — a
  plugin-per-pipeline's maintenance cost outweighs the payoff. Reserve this only
  for a *recurring, standardized* upstream whose emitted structure genuinely
  should drive the document, and even then prefer to re-express it as a shape
  contract the document adopts.

**Net stance: the extensibility interface is the shape contract, not a
pipeline-plugin API.** Any pipeline — internal or external — sits *upstream* of
that contract. Internal emissions become queryable extension tables addressable
by rendering domains uniformly; external emissions can either be loaded into
`session.duckdb` as extension tables (uniform, queryable, heavier) or passed
through as already-shaped `data[data_key]` payloads (lighter, bypasses the DB).
Both honor the same node-declared shapes, so neither is a special render path.

### Non-goals for rendering domains (in this ADR)

- **Not** replacing `marshal_export_data`'s front-matter assembly (foreword,
  abstract, references) — those are authored prose, not query results; they keep
  their current path.
- **Not** a query-authoring UI in Phase E — domains are authored as YAML
  (alongside `versions/<name>.yaml`) first; a visual binder is a later tool.
- **Not** cross-session domains — a domain is scoped to one session's DB, like
  everything else in this ADR.
- **Not** a pipeline-plugin / registry API, and **not** bespoke per-pipeline
  ingest adapters — deferred as not-worth-it for one-offs. The interface of record
  for plugging in an arbitrary pipeline is the **shape contract** the document
  declares, not code that knows about a specific pipeline.

---

## Resolving the two standing issues

- **`integrated.json` "ready-store" confusion** — the ADR makes the roles
  explicit: `integrated.json` = merge/compute input; `session.duckdb` = the
  queryable projection. The data-integration doc is updated to point at the DB as
  the query substrate.
- **Genomics data-source bypass** — materializing `gene`/`gene_set` into
  `session.duckdb` at process time means downstream *queries* no longer touch the
  raw `.bm2`. It does **not** by itself remove the extraction-time re-read of the
  `.bm2` (that is a separate, deliberate follow-up: persist a genomics sidecar so
  even extraction stops reaching into `files/`). The ADR records this as the
  end-state; the DB is the first step toward it.

---

## Phased implementation plan (each phase independently shippable + tested)

**Phase A — schema + writer (no UI).**
Define the DuckDB schema (`pipeline/session_schema.sql` or a Python DDL module).
Write `build_session_db` populating the spine + tox extensions from artifacts
already in hand at the end of `run_process`. Hook it in after the payload is
assembled; wipe/rebuild on re-integration (same trigger as the cache wipe).
Tests: build the DB for the reference session, assert row counts and a handful of
known-value spot checks (e.g. male Total Thyroxine BMD matches the report), and
that `measurement` has the expected `(subject × endpoint × day)` grain.

**Phase B — read-only query API.**
`session_query.py` + `POST /api/query/{dtxsid}` + `GET .../schema`, with the
safety guards. Tests mirror `test_wizard_routes.py`: a `SELECT` returns rows; a
non-SELECT / multi-statement / write is rejected; results respect the LIMIT cap;
the schema endpoint lists the tables.

**Phase C — SQL console page (power-user toolkit v1).**
The React SQL console + schema browser + result grid + export, over `/api/query`.
Verify end-to-end in a headed browser against the reference session (run a query,
export, confirm read-only rejection surfaces cleanly).

**Phase D (follow-up, not this arc) — genomics sidecar + guided builder.**
(1) Persist a genomics sidecar at integration so extraction stops re-reading the
raw `.bm2`; (2) the guided query builder (entity → filter → columns) over the
same substrate.

**Phase E (north star, separate arc) — rendering domains.**
Generalize `marshal_export_data` so `data_key` resolves against a rendering
domain's named queries before falling through to the legacy cache key. Ship the
closed shape-adapter registry (`rows → section_cards / table_block / kv_block`),
keyed off the node's `COMPONENT_CATALOG.content_kinds`. Author domains as YAML
beside `versions/<name>.yaml`. Prove the round-trip on one migrated section
(query → adapt → render reproduces the cache-driven output byte-for-byte) before
converting more. Filters/versions/method-options converge onto this path
incrementally; nothing is forced to migrate at once. This is a **separate arc**
from A–C and depends on the schema being stable (A) and the query API existing
(B).

---

## Consequences

**Positive**
- A single, documented, SQL-queryable representation of a session — the
  foundation for the power-user toolkit and the journal-article generalization.
- Materializes the tidy `(subject, endpoint, dose, day, value)` long form that
  exists nowhere today — enabling per-animal analytical questions the report
  can't currently answer.
- Normalizes the recurring 10-key BMD-stat block and the genomics superset into
  queryable tables, consistent with the filter-agnostic-cache principle.
- Read-only boundary makes the query page safe to expose to power users.
- Opens the path (Phase E) to defining report content **by query** rather than by
  pipeline code — the seam that lets filters, versions, and method-options
  converge into "a saved query" and makes the platform extensible to arbitrary
  journal articles without touching `marshal_export_data`.

**Costs / risks**
- A new build output per session (~a few MB; far smaller than `integrated.json`
  because `measurement` stores parsed values, not the 68 MB of nested arrays).
- The writer is new surface that must stay in sync with the artifacts it reads;
  the re-integration wipe trigger keeps it from going stale, and Phase-A spot
  checks pin it to the report values.
- Schema evolution: as the platform generalizes, the spine will need versioning
  (a `schema_version` table) so old session DBs are detectable/rebuildable.
- This does **not** replace the JSON caches (still the render inputs) — it is an
  additional projection, so there is transient duplication of data between the
  caches and the DB. Acceptable: they serve different consumers (render vs.
  query) and share one invalidation trigger.

**Explicitly out of scope for this ADR's *build* (A–C); named as the north star**
- Rendering domains (Phase E) — the `data_key`→query resolver and shape-adapter
  registry. Described in full above so A–C are built to enable it, but a separate
  arc; A–C ship and stand alone without it.
- Migrating filters / versions / method-options onto the domain path — happens
  incrementally *within* Phase E, section by section, never as a big-bang cutover.

**Explicitly out of scope entirely**
- Cross-session / cohort querying (a future "corpus" DB above the per-session DBs).
- Removing the genomics extraction-time `.bm2` re-read (Phase D).
- The guided (no-SQL) query builder (Phase D / v2).
- A visual query-authoring / domain-binding UI (post-Phase-E tool).
- Any change to the four render surfaces or the filtering system in phases A–C
  (Phase E adds a resolver *in front of* the existing render path, not a change
  to the surfaces themselves).
