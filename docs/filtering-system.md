# The rlm-bmdx filtering system

How report-level data filters work end to end — the predicate, the config shape,
where filters are applied, and how they enable multiple report **versions** over
one processed dataset.

This reflects the state after the four-phase filter refactor (commits
`e3b85aa` → `2505f0e`). File:line references are to the current tree.

---

## 1. What "filtering" means here

A filter narrows *which data appears in a report* without changing the data
itself. There are **eight dimensions**, grouped into three families:

| Family | Dimensions | Scope |
|--------|-----------|-------|
| Apical | `sex` (apical area), `assays` | The dose-response tables (Clinical Chemistry, Hematology, Hormones) + BMD summary + narratives |
| Organ-weight | `organs` (organ-weight area), `sex` (organ-weight area) | The Organ Weight table + its narrative |
| Genomics | `organs` (genomics area), `sex` (genomics area), `genes`, `gene_sets`, plus the GO **cutoffs** | The genomics gene-set / gene tables + charts |

Two conceptually different operations live under "filtering":

- **Subtractive filters** (all eight dimensions above): compute the full
  *superset*, then drop rows/sections at render time. Never part of a cache key.
- **Method options** (BMD stat; and, since phase 4, the GO cutoffs behave the
  same way): they select or re-derive a slice of an already-computed superset.
  The BMD stat is stored per-slice (`gene_sets_by_stat`); the GO cutoffs are a
  post-extraction subtractive filter.

The governing design rule, enforced across the codebase:

> **Filters are subtractive → applied at render, never cache-keyed. Method
> options are generative → per-slice. Document structure is render-only.**

---

## 2. The predicate — one function, three matching contracts

All filtering ultimately calls one predicate:
`document_model/filters.py::filter_allows` (line 78).

> **Where these live.** The filter predicates are report-level *data selection* —
> which sexes/assays/organs/genes appear — and are consumed across `pipeline/`,
> `narrative/`, `rendering/`, and the table builders. They live in
> `document_model/filters.py`, beside the filter *config* loaders
> (`document_template.py`), NOT under `tables/`. (They were historically
> extracted into `tables/table_builder_common.py` by proximity — the organ
> matcher started inside `body_weight_table.py` — which conflated data selection
> with table-cell construction; that module now just re-exports them for
> backward compatibility.)

```python
filter_allows(candidate: str, allowlist: list[str] | None, *,
              mode: str = "component", alt_id: str | None = None) -> bool
```

An **empty/None allowlist means "no filtering"** (returns `True`) in every mode —
this is the universal backward-compatible default.

The three modes are deliberately distinct and must **not** be collapsed:

- **`"component"`** (organ, assay, gene) — `_component_match` (line 37). The
  candidate is lower-cased and split on `[\s.\-/]+`; it passes if a listed token
  equals the whole candidate OR any one component. This lets a single
  author-friendly token cover inconsistent spellings: `"kidney"` matches
  `"Kidney-Left"` / `"R. Kidney"`; `"count"` matches `"Basophil count"` /
  `"Leukocyte Count"`.
- **`"exact"`** (sex) — `_exact_match` (line 65). Exact case-insensitive
  membership, NOT component-wise. Sex is a closed binary; a component split would
  wrongly let a partial token leak between `male`/`female`.
- **`"dual"`** (gene_set) — passes when `alt_id` (the GO accession, e.g.
  `GO:0051301`) equals a listed token OR `candidate` (the human-readable term)
  component-matches. So both `"GO:0051301"` and `"cell division"` work.

The five named predicates are thin wrappers preserving these contracts:

| Wrapper | Line | mode |
|---------|------|------|
| `organ_allowed(organ, allowlist)` | 111 | component |
| `sex_allowed(sex, allowlist)` | 125 | exact |
| `assay_allowed(label, allowlist)` | 137 | component |
| `gene_allowed(symbol, allowlist)` | 149 | component |
| `gene_set_allowed(go_id, go_term, allowlist)` | 160 | dual (`alt_id=go_id`) |

(All in `document_model/filters.py`.)

The allowlist is expected **pre-lower-cased** (the loaders guarantee this); only
the candidate is folded at match time.

---

## 3. The config shape

### 3.1 Where filters are declared

Filters live in the **template YAML** (`templates/niehs-5day-report.yaml`) as
siblings of the `document:` block, and — since phase 3 — optionally in a
**per-version file** (`sessions/<dtxsid>/versions/<name>.yaml`). The template
supplies the global default; a version overrides it.

Real template blocks:

```yaml
organs:                       # {area: [tokens]}
  genomics: [liver, kidney]
  organ-weight: [liver]

sex:                          # {area: [tokens]}
  organ-weight: [male]

assays:                       # {area: [tokens] | {sex: [tokens]}}
  clinical-chemistry:
    male: [cholesterol]
    female: ["aspartate aminotransferase", "sorbitol dehydrogenase"]
  hematology:
    male: ["neutrophil count"]
    female: ["manual hematocrit"]

# genes: [egr1, ddit4]        # flat list (genomics-only), commented out here
# gene_sets: ["GO:1902893", "cell division"]

charts: []                    # closed-vocab enable list (see §3.4)
```

### 3.2 The three legacy loader shapes

`document_model/document_template.py` has one `load_report_*` per block, and they
return **three incompatible shapes** — a historical wart the refactor tamed but
did not delete (existing compute call-sites still use them):

| Loader | Line | Return shape |
|--------|------|--------------|
| `load_report_organs` | 740 | `{area: [tokens]}` (areas: genomics, organ-weight) |
| `load_report_sex` | 756 | `{area: [tokens]}` (areas: apical, genomics, organ-weight) |
| `load_report_assays` | 796 | `{area: [tokens] \| {sex: [tokens]}}` — polymorphic per area |
| `load_report_genes` | 862 | `[tokens]` — flat |
| `load_report_gene_sets` | 874 | `[tokens]` — flat |
| `load_report_charts` | 888 | `[types] \| None` — closed-vocab, see §3.4 |

Valid areas are closed vocabularies (`REPORT_ORGAN_AREAS`,
`REPORT_SEX_AREAS`, `REPORT_ASSAY_AREAS`, lines 617/626/632), so a typo'd area
fails loudly at load.

### 3.3 The canonical shape

To let one caller consume all dimensions uniformly, phase 1 added a **canonical
form** and a normalizer (`document_template.py`):

```
{dimension: {area: {sex_key: [tokens]}}}
```

`sex_key` is `"*"` (both sexes / not sex-scoped) or `"male"`/`"female"`; flat
dimensions collapse to area `"*"`, non-per-sex areas to sex `"*"`.

- `_normalize_dimension(raw)` (line 956) maps any of the three legacy shapes to
  the canonical nesting.
- `normalize_filters(organs=…, sex=…, …)` (line 982) composes the loader outputs
  into `{dimension: {area: {sex: [tokens]}}}`, omitting empty dimensions.
- `load_report_filters(name)` (line 1008) returns
  `{"filters": <canonical>, "charts": <list|None>}` — the seam the render/version
  path consumes.
- `resolve_report_allowlist(filters, dimension, area=None, sex=None)` (line 1034)
  extracts one token list, falling back through the `"*"` wildcards. Returns
  `None` (⇒ no filtering) when the dimension/area is absent.

`charts` is **deliberately excluded** from the canonical structure and carried
alongside — see next.

### 3.4 `charts` — the closed-vocabulary exception

Every token allowlist treats empty/absent as "no filtering". `charts` is
different: it enables a closed set of chart *types* (`umap`, `cluster`, …).
`load_report_charts` (line 888) is **presence-sensitive**:

- key **absent** → `None` → render all types (default),
- key **present** (even `[]`) → render only those types (`[]` = render none).

The normalizer must never fold `charts` in, or that empty-semantics distinction
would break.

---

## 4. Where filters are applied

The load-bearing architectural decision (phase 2): **compute the full superset,
cache it filter-agnostically, apply filters after the cache read.** This is what
lets one processed dataset back many filtered versions with no reprocessing. The
genomics path already worked this way; phases 2 and 4 brought apical,
organ-weight, and the GO cutoffs into the same model.

### 4.1 The apply functions (`pipeline/processing_helpers.py`)

- **`apply_apical_filters(platform_tables, sex_allow, assay_filters)`** (line
  269) — filters the `{platform: {sex: [TableRow]}}` structure. Drops non-allowed
  sexes (exact) and, on the two assay platforms, non-allowed endpoint rows
  (component). Resolves the polymorphic assay shape (`{sex: [...]}` vs flat list)
  inside its sex loop. Used to build the BMD summaries and narratives from
  filtered TableRows.
- **`apply_section_filters(sections, *, sex_allow, assay_filters, organ_allowlist, ow_sex_allow, compound_name)`**
  (line 339) — filters *already-serialized* section cards (dicts with
  `label`/`tables_json`). Prunes sexes, drops assay/organ rows, and **rebuilds the
  Organ Weight caption** from the surviving rows (the caption reads "Liver Weights
  of *Male* Rats" vs the generic phrasing, derived from what renders — so it must
  be regenerated, not kept). **Always keeps the structural `n` / `is_n_row` row**
  regardless of the assay filter.
- **`apply_genomics_cutoffs(genomics_sections, *, go_pct, go_min_genes, go_max_genes, go_min_bmd)`**
  (line 883) — re-applies the four GO-category cutoffs to a cutoff-agnostic
  genomics superset: filters `gene_sets_chart_by_stat` rows by
  `n_genes`/`n_genes_with_bmd`/pct and re-slices the top-10 `gene_sets_by_stat`
  with fresh ranks.
- **`filter_genomics_sections(sections, *, organ, sex, genes, gene_sets)`**
  (`document_model/filters.py:174`) — the single genomics organ/sex/gene/gene-set
  choke point, shared by the compute path and both export surfaces.
- **`prune_card_sexes(card, sex_allow)`** (line 448) — sex-prunes a single card's
  `tables_json`; used for the sidecar-built cards (Tissue Concentration, Clinical
  Observations) that bypass `platform_tables`.

A crucial subtlety for the BMD summary: the summary's endpoint labels are
**display-relabeled** (`"Neutrophil Count"` → `"Neutrophils"`), so it must be
built from the *raw-label* filtered `platform_tables`, **not** by filtering the
relabeled summary rows. See `_build_bmd_summary` in `process_integrated.py`.

### 4.2 Compute path (`pipeline/process_integrated.py`, `run_process`)

1. **NTP stats** → `platform_tables` (full superset). No filtering.
2. **`_get_sections`**: builds the superset section cards (no filters passed to
   `_build_section_cards`), caches them (`_hash_sections`, now filter-agnostic —
   `cache_plumbing.py`), then calls `apply_section_filters` after the read to
   produce the returned payload. The default-filtered `unified_narratives` are
   re-persisted into the sections cache for the session-reload export path.
3. **BMDS** models *every* endpoint (the full superset), so its result cache
   serves any filter set.
4. **`_build_bmd_summary`**: builds the summary from the superset, then rebuilds
   it from an `apply_apical_filters`-narrowed copy of `platform_tables`.
5. **`_get_genomics`**: extracts the superset with **cutoffs OFF**
   (`_GO_CUTOFFS_OFF`, line 880), caches it (`_hash_genomics`, now cutoff- and
   filter-agnostic — keyed only on `bmd_stats` + `ge_filename`), then applies
   `apply_genomics_cutoffs` and `filter_genomics_sections` after the read.
6. **`_build_charts`**: chart cache key folds in the GO cutoffs directly (because
   `genomics_hash` is now cutoff-agnostic but charts render from the
   cutoff-filtered sets).

### 4.3 Render / export path (`rendering/latex_export.py::load_session_data`)

The Overleaf/session-reload export has no live payload — it reads the caches
(which are supersets) and must re-apply the version's filters, mirroring the
compute presentation step:

- `_resolve_apical_filters(dtxsid, version)` (line 259) → the apical/organ-weight
  allowlists as flat args; `apply_section_filters` projects the superset section
  cards.
- `_resolve_go_cutoffs(dtxsid, version)` (line 298) → the version's GO cutoffs
  (from its `methods` block, else pipeline defaults); `apply_genomics_cutoffs`
  then `filter_genomics_sections` project the genomics superset.

---

## 5. What is (and isn't) in a cache key

| Cache | Keyed on | NOT keyed on |
|-------|----------|--------------|
| NTP stats (`_hash_ntp`) | integrated identity, primary bmd_stat | filters |
| Sections (`_hash_sections`) | ntp hash, compound, dose_unit, sidecar hash, imputed_cells | **all filters** (phase 2) |
| BMD summary (`_hash_bmd_summary`) | ntp hash + bmds hash | filters |
| BMDS (`_hash_bmds`) | dose-response data + method version | bmd_stat, filters |
| Genomics (`_hash_genomics`) | bmd_stats, ge_filename | **GO cutoffs** (phase 4), organ/sex/gene filters |
| Charts | genomics_hash, chart style/types, **GO cutoffs** | organ/sex/gene filters |

The consequence: two report versions differing only in filters/cutoffs **share
every compute cache** and re-project at render — no BMDS re-run, no Java
re-extraction.

---

## 6. Versions — filters as a per-report projection

`document_model/version_config.py` stores a version at
`sessions/<dtxsid>/versions/<name>.yaml`:

```yaml
document:  [ ...node entries... ]   # optional — structure (falls back to global tree)
filters:                            # optional — canonical shape (§3.3)
  sex:    {apical: {"*": [male]}}
methods:                            # optional — GO cutoffs (+ future method opts)
  go_pct: 10
  go_min_bmd: 5
charts:  [umap, cluster]            # optional — closed-vocab enable list
```

- `DEFAULT_VERSION = "default"` (line 42) is **implicit** (no file required),
  **undeletable**, and falls back to the global template's structure + filters —
  so a session with no versions renders exactly as before.
- `resolve_version_filters(dtxsid, name)` (line 138): a version's own
  `filters`/`charts` win; otherwise the global template's
  (`load_report_filters(ACTIVE_TEMPLATE)`).
- `build_version_tree(dtxsid, name)` (line 161): the version's `document`
  structure, else the legacy `document.yaml`, else the global `DOCUMENT_TREE`.
- Version names are slug-validated (no `/`, `\`, `.`, `..`) so they cannot escape
  `versions/`.

CRUD is exposed at `GET/POST/DELETE /api/versions/{dtxsid}[/{name}]`
(`web_routes/export_routes.py`). The render path takes a `version` argument
(`load_session_data(..., version=…)`).

**Net effect:** process a DTXSID once; define N versions, each with its own
structure + filters + GO cutoffs; each renders from the shared superset caches
with zero reprocessing.

---

## 7. Adding a new filter dimension — checklist

1. Add a loader in `document_template.py` (or reuse `_load_per_area_block` /
   `_load_flat_block`) and register any new area in the relevant
   `REPORT_*_AREAS` closed vocabulary.
2. Wire it into `normalize_filters` / `load_report_filters` so it appears in the
   canonical shape.
3. Choose the predicate mode (`component` / `exact` / `dual`) — reuse
   `filter_allows`; do not hand-roll matching.
4. Apply it **after** the relevant cache read (an `apply_*` function), never in
   the cache key — unless it is a *generative* method option, in which case key
   the cache per-slice instead.
5. If it affects charts or a display-relabeled table, mind the two gotchas: the
   chart cache must fold in generative params, and summaries must filter on raw
   labels, not display labels.
6. Add unit tests mirroring `tests/unit/test_filter_unification.py`,
   `test_axis_filters.py`, `test_genomics_cutoffs.py`, and — for the superset
   invariant — a byte-identical check that the default projection is unchanged.

---

## 8. Known follow-ups (not yet done)

- **Per-version narrative regeneration at export.** The default version's
  Overleaf narratives are correct, but a non-default version's narrative *prose*
  is not yet regenerated at export (its tables are). The narratives are
  sex-generative and cheap to regenerate; the hook is `load_session_data`.
- **Wizard version picker.** The version backend (store + CRUD + render wiring)
  is complete and tested; the wizard UI does not yet expose a version selector.
