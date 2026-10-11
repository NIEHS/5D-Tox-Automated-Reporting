# Section catalog — dependency map (phase 1 of 2)

**Status:** analysis, 2026-09-21. No code changes proposed here are implemented.
**Question answered:** *Are workflow sections created dynamically from the report
configuration?* — **No.** Rendering is tree-driven; the workflow's notion of a
"section" (what can be generated, approved, shown) is hand-maintained in seven
places that do not read the tree.

**Two phases.** This document is phase 1: where section identity comes from today,
every registry that duplicates it, and a proposed single catalog. Phase 2 (below)
traces every *downstream* dependency of the configured document, and requires a
document configuration that contains every section currently implemented, so the
traversal covers every path. The user will author that configuration.

---

## 1. The finding

The report configuration (`templates/niehs-5day-report.yaml`, instantiated by
`document_model/document_template.py` into the `DocNode` tree, optionally
overridden per session by `document_model/document_config.py`) drives **rendering**:
heading hierarchy, order, table/figure numbering, ToC, platform→section mapping,
section filtering. All four surfaces consume it (`rendering/report_data.py:455–497`,
`rendering/latex_export.py:893,1111`, `rendering/preview_surface.py:72`).

It does **not** drive the **workflow**. What can be generated, what unlocks what,
what the session payload carries, and what the Sections screen lists are each a
separate literal list. They agree today only because someone kept them in step by
hand, and this week's bugs were the places where they did not:

| symptom (2026-09-21) | root cause |
|---|---|
| Materials & Methods showed "0 paragraphs" and re-called the model on every visit | SPA counted only the flat `paragraphs` shape; Methods stores `sections[].paragraphs` |
| Summary never generated after Background was approved | SPA never called `/api/generate-summary` |
| Apical BMD Summary always "not generated" | SPA never fetched the derivation route |
| Internal Dose renders in the report but has no readiness, no payload field, no row | node exists in the template only |

The tree even carries a `ready_key` per content node — a leftover for the retired
Alpine store (`document_model/document_node.py:62,125`). Nothing reads it now, and
the SPA never requests `/api/document-tree` (`grep` over `wizard-ui/src`: none).

---

## 2. Section inventory today (from the template)

Content-bearing nodes in `templates/niehs-5day-report.yaml` (44 nodes; the 21
`methods` sub-nodes collapse to one section for workflow purposes):

| template node(s) | type | binding | workflow key today | produced by | stored as | readiness rule | SPA row |
|---|---|---|---|---|---|---|---|
| `foreword` `about` `peer-review` `publication` `acknowledgments` | front-matter | `data_key` | **none** (Configure step, front-matter metadata) | user config / freeform | `front_matter.json` | — | Configure |
| `abstract` | front-matter | `data_key: abstract` | **none** (derived at render from background + summary) | programmatic + LLM distillation | `background.json:abstract_background` | — | — |
| `background` | narrative | `data_key: background` | `background` | LLM (`narrative/background_writer`) | `background.json` | `()` | yes (auto-gen) |
| `methods` + 21 `mm-*` | heading-only + narratives | `data_key: methods`, `methods_key: <sub>` | `methods` | LLM (`narrative/methods_*`) | `methods.json` (`sections[]`) | `("processed",)` | yes (auto-gen) |
| `table-sample-counts` | sample-counts-table | `data_key: sample_counts` | **none** | programmatic (`tables/sample_counts_table`) | inside `methods.json:table1` | — | — |
| `animal-condition` + 2 tables | narrative+tables | `narrative_key: animal_condition`, `platform` | `bm2_body-weight`, `bm2_organ-weight` | programmatic (`narrative/unified_narrative`, `tables/*`) | `bm2_<slug>.json` (materialized from `_cache_sections_*`) | `()` | yes (per bm2 instance) |
| `clinical-path` + 3 tables | narrative+tables | `narrative_key: clinical_pathology`, `platform` | `bm2_clinical-chemistry`, `bm2_hematology`, `bm2_hormones` | programmatic | `bm2_<slug>.json` | `()` | yes |
| `internal-dose` + 1 table | narrative+tables | `narrative_key: internal_dose`, `platform: Tissue Concentration` | **`bm2_tissue-concentration` only** (table); narrative has **no key** | programmatic (`build_internal_dose_narrative`) | `_cache_sections_*:internal_dose` (no section file) | — | table row only |
| `bmd-summary` | bmd-summary | `data_key: bmd_summary` | `bmd_summary` | derived (`api_bmd_summary`) + LLM analytical paragraph (`narrative/apical_bmd_llm`) | `bmd_summary.json` (only once approved) + `_cache_apical_narrative_*` | `()` | yes (derived on demand, since dc11b95) |
| `gene-sets` `gene-bmd` | genomics-section | `data_key: genomics_sections`, `narrative_key` | `genomics_<organ>_<sex>` | LLM (`narrative/genomics_llm`) + KB | `_cache_interpretation_<organ>_<sex>_*.json` + `genomics_narrative_overrides.json` | `("knowledge_base",)` | yes (no controls) |
| `summary` | narrative | `data_key: summary` | `summary` | LLM (`llm_routes.api_generate_summary`) | `summary.json` | `("background","results")` | yes (auto-gen since dc11b95) |
| `references` | narrative | `data_key: references` | **none** | derived (`narrative/references_builder`) | `references.json` | — | — |

Observations:
- Three producer kinds exist and are never declared anywhere: **LLM**, **programmatic**, **derived**. The readiness engine encodes them implicitly through the rule tuples.
- "Section" means three different things: a *tree node* (44), a *workflow unit* (12 keys: background, methods, summary, bmd_summary, 7×bm2, N×genomics), and a *storage file*. No object holds the mapping.
- `internal_dose` is the clean proof: template ✓, processing ✓ (`report_data_overlays.py:360`), render ✓, workflow ✗.

---

## 3. The registries (every place section identity is hand-written)

| # | file:line | what it hardcodes | consumer |
|---|---|---|---|
| R1 | `workflow/section_readiness.py:57–70` `_UNLOCK_RULES` | section *types* and unlock groups; `_section_type_for_key:84–99` maps `bm2_*`/`genomics_*` prefixes | `derive_section_readiness` → `/api/workflow/{id}/section-readiness` |
| R2 | `web_routes/session_routes.py:739–741` `VALID_SECTION_TYPES` | the approvable types | `/api/session/approve` |
| R3 | `web_routes/session_routes.py:803–870` and `929–955` | per-type branches for approve / `_resolve_section_key` (file naming, required extras) | approve, unapprove |
| R4 | `web_routes/session_routes.py:594–618` | the fixed file list the session payload reads (`background.json`, `methods.json`, `bmd_summary.json`, `summary.json`, `bm2_*`, genomics caches) | `/api/session/{id}` → SPA |
| R5 | `web_routes/session_routes.py:1562` | files touched on reset (`methods.json`, `bmd_summary.json`, `summary.json`) | reset |
| R6 | `wizard-ui/src/steps/Sections.tsx:13–17` `FRONT_MATTER`; `:241–244` `approvalTarget`; `:322–326` prefix filters; `:372` bmd_summary special case; `maybeGenerate` branches | which rows exist, which auto-generate, how each approves | Sections screen |
| R7 | `wizard-ui/src/api.ts` `SessionLoad` interface (fixed field names) + one client function per generator (`generateBackground`, `generateMethods`, `generateSummary`, `getBmdSummary`) | payload shape and producers | all steps |

Also relevant but *not* section-identity registries (they are generic and can stay):
`workflow/ownership.py` (facts keyed by the section dict, not by type),
`workflow/labels.py`, `workflow/currency.py`, `pipeline/session_store.save_section`
(any key), `pipeline/cache_plumbing` (units, not sections).

The per-session document config (`document_model/document_config.py:174
build_session_tree`) is consumed only by rendering and the Configure step
(`web_routes/export_routes.py:129–138`). Readiness and the Sections screen never see
it: a section added or removed in the configurator changes the report but not the
workflow.

---

## 4. The dependency chain as it exists

```
raw files  ──validate/integrate──▶ integrated.json (+ sidecars)
     │
     ▼ Process (pipeline/process_integrated.run_process)
payload contract (12 keys, tests/fixtures/golden/process_integrated_payload.json):
  sections, unified_narratives, methods, apical_bmd_summary(+_bmds),
  apical_bmd_narrative, genomics_sections, gene_set_narrative, gene_narrative,
  chart_images, bmd_stats, bmd_stat_labels
     │ persisted as _cache_sections_* _cache_bmds_* _cache_bmd_summary_*
     │ _cache_genomics_* _cache_interpretation_<organ>_<sex>_* _cache_charts_*
     │ _cache_apical_narrative_* references.json  (+ .prepare_content.outputs.json)
     ▼ materialize (workflow/steps.materialize_result_sections)
bm2_<slug>.json   (one per apical platform; approved=False)
     │
     ▼ readiness (R1)   ◀── disk presence (which bm2_*/genomics_* files exist)
{key: enabled, approved, blocked_by}
     │
     ▼ session payload (R4)  ──▶  Sections screen (R6/R7)  ──▶ generate / approve (R2/R3)
     │                                                              │
     ▼                                                              ▼
render: tree (template ∪ session document config) + overlays          background.json
        (rendering/report_data_overlays: abstract, apical_sections,    methods.json
         unified_and_bmd [internal_dose], genomics, references)        summary.json
                                                                       bmd_summary.json
```

Everything to the right of "readiness" is keyed by literal names; everything below
"render" is keyed by the tree. The seam between them is the catalog that does not
exist.

---

## 5. Proposed: one section catalog, derived from the tree

Add a `document_model/section_catalog.py` that walks the (session) tree once and
yields the workflow view of it:

```python
@dataclass(frozen=True)
class SectionSpec:
    key: str                  # workflow key: "background", "methods", "bm2_<slug>", "genomics_<organ>_<sex>", "internal_dose", ...
    node_ids: tuple[str, ...] # tree nodes this section feeds (1..n)
    kind: Literal["llm", "programmatic", "derived", "authored"]
    producer: str             # dotted name of the generator / deriver (or "" for authored)
    store: str                # file pattern under the session dir ("methods.json", "bm2_{slug}.json", ...)
    approvable: bool
    unlock: tuple[str, ...]   # readiness groups: () | ("processed",) | ("knowledge_base",) | ("background","results")
    instance_of: str | None   # family key for instance sections ("bm2", "genomics"), else None
```

Where the fields come from:

- `key`, `node_ids`, `instance_of` — from the node's `data_key` / `narrative_key` /
  `platform` (instances expand from data presence exactly as `_section_type_for_key`
  does today, but via the template's `platform` bindings).
- `kind`, `producer`, `store`, `approvable`, `unlock` — **declared on the template
  node** under a new `workflow:` block (ADR-0003's "data-driven template" already
  puts bindings there; this is the same move for the workflow), with defaults per
  node type so existing templates keep working. The `ready_key` field is deleted.

Consumers, in order of payoff:

1. **R1** `derive_section_readiness` takes the catalog instead of `_UNLOCK_RULES`;
   instance discovery stays disk-driven but the family list comes from the catalog.
2. **R4** `/api/session/{id}` builds its payload by iterating the catalog's `store`
   patterns; adding a section to the template adds it to the payload.
3. **R6/R7** the Sections screen renders `GET /api/workflow/{id}/sections` (the
   catalog + readiness + content summary per key) and dispatches generate/approve by
   `kind`/`producer` — no `FRONT_MATTER`, no prefix special-casing.
4. **R2/R3** approve/unapprove validate the type against the catalog and derive the
   file name from `store`.
5. **R5** reset iterates the catalog.

Out of scope (already correct): rendering, numbering, the overlays' *content*
logic, ownership/labels/currency.

Acceptance for phase 1: `internal_dose` gains a workflow row, readiness and payload
field **by editing only the template**; the 12 existing keys are unchanged; the
golden and parity tests stay green.

---

## 6. Phase 2 — downstream dependencies of the *configured* document

The catalog fixes *identity*. What each section depends on at generation time
(which caches, which other sections, which external resources, which per-session
config values) is a second graph, and it can only be traversed against a document
that contains **every implemented section**, otherwise paths stay unexercised.

**Inputs the user provides:** a session document configuration (Configure step →
document YAML) enabling every node type and binding the current catalog supports —
all front-matter parts, abstract, background, the full Methods sub-tree incl.
`table-sample-counts`, all seven apical platforms across the three result sections,
`bmd-summary`, both genomics sections for every organ × sex the data has, `summary`,
`references`, plus any freeform pages/blocks and figures — on a session with genomics
data and `bmdx.duckdb` present.

**What phase 2 traces, per catalog entry:**

- *Data prerequisites* — which processing outputs (payload keys / cache files) it
  reads; what happens when each is absent (skip, placeholder, error).
- *Section prerequisites* — approval and content dependencies (e.g. Summary reads
  approved sections; abstract reads background + summary; references reads the
  genomics caches).
- *Configuration sensitivity* — which per-session config values change the output:
  document structure (node present/absent/reordered), report filters (organ/sex/
  assay/gene), views, layout style, front-matter metadata.
- *External resources* — LLM endpoint, knowledge base, Java bridge, kaleido.
- *Invalidation* — which fingerprint / currency rule re-runs it after a reprocess or
  a config change (`workflow/currency.py`, `pipeline/cache_plumbing.py` schema
  versions, `.prepare_content.outputs.json` fingerprint).

**Method:** for each entry, run the maximal document through Process → Sections →
Preview with instrumentation on cache reads (a one-off tracer around
`_load_cache` / `_read_json` / the overlays) and record the observed reads; then diff
against the expected graph. The output is a per-section dependency table plus a list
of missed invalidations.

---

## 7. Open questions

- Should instance families (`bm2`, `genomics`) be declared in the template as a
  *pattern* (one node with `platform` bindings expanding per data), or stay
  disk-discovered? (Proposal: pattern in template, expansion by data presence.)
- Does the per-session document config's structure editing become the source for
  the catalog (so removing a section also removes its workflow row), or should the
  workflow always use the full template and treat removal as render-only?
- `bmd_summary` is *derived* but also carries an LLM paragraph; is it one section
  with two producers or two sections?
