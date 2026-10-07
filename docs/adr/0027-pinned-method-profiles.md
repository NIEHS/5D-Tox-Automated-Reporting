# 0027 — Analysis methods are versioned profiles, pinned per study and checked against a published report

- **Status:** Accepted (2026-10-07). Steps 0–6 implemented — see "Implementation status" at the end and `docs/plans/adr-0027-implementation.md`.
- **Deciders:** Dan Svoboda
- **Related:**
  - [ADR-0003](0003-document-component-model.md): document structure is already declarative YAML. This ADR keeps the method out of it.
  - [ADR-0015](0015-label-and-guard-model.md): currency, i.e. changing a pinned profile makes derived content stale.
  - [ADR-0019](0019-metadata-vocabulary-policy.md): per-field provenance and authority. The same idea is applied here to *method settings*.
  - [ADR-0020](0020-one-evolving-report-not-a-version-tree.md): one evolving report with history. A profile change is an event in that history, not a branch.
  - [ADR-0021](0021-three-concerns-data-content-rendering.md): profiles parameterise concern [1], processing, and concern [2], the generated text.
  - [ADR-0024](0024-data-definitions-as-declarative-artifacts.md): the same "declarative artifact, not hardcoded Python" move, made for *what data is*. This ADR makes it for *how data is analysed*.
  - [ADR-0025](0025-bits-profile-as-structural-grammar.md): its "BITS profile" is a document grammar. To avoid the name clash, this ADR always says **method profile**.
- **Evidence:**
  - `assets/cebs/CHRONOLOGY.md` (12 published packages, four genomic eras, two apical engines).
  - `assets/cebs/NIEHS-13-comparison.md` (the number-by-number check of our pipeline against the newest report).

## Context

The goal of the tool is a report for *any* test article, validated against published NIEHS reports. Characterising all 12 published CEBS packages showed that "the published method" is not one method.

- **Genomics** changed in each era:
  - the probe filter;
  - the prefilter (Williams with fold 1.5; then a curve-fit prefilter at 2 SD; then 1.581 SD);
  - the model selection (lowest AIC, then model averaging);
  - the BMR (1 SD, then 25% relative deviation);
  - the statistic that ranks the GO tables.
- **Apical** BMDs moved from modified BMDS 2.7 with high-dose dropping to BMDExpress 3 model averaging. The rule for which endpoints get a BMD also changed.
- **The given PFHxSAm package** is the February 2026 DTT method applied to a 2021 study. Every discrepancy we chased for weeks came from this method mismatch, not from bugs.

The NIEHS-13 comparison then showed how the code absorbs these changes today:

1. **Method choices are scattered literals.** Examples:
   - `tables/apical_bmds._ASSAY_FAMILY_BMR` (clinical chemistry at 25% RD; NIEHS-13 uses 1 SD);
   - the significance thresholds in `bmdx_pipe.apical_stats`;
   - the GO cutoff and `bmd_stats` defaults in `pipeline/process_integrated._build_process_context`;
   - the gene-table granularity hidden inside the genomics extraction.

   Nothing records which era these values belong to.
2. **The report text can contradict the computation.** The footnotes say "Jonckheere and Williams or Dunnett" for weights and "Shirley or Dunn" for clinical pathology. That matches every published report from 2021 (NIEHS-10) and 2025 (NIEHS-13). The code computes Dunnett for everything. Footnotes and methods prose are literals (`tables/table_builder_common.py`, `narrative/methods_prompt.py`), so nothing ties them to what actually ran.
3. **Study-specific choices live in the shared template.** `templates/niehs-5day-report.yaml` carries NIEHS-10's organ list (liver/kidney), organ-weight sex (male) and per-sex "Select" assay lists. For NIEHS-13 they hide heart, lung, ovary and most endpoints, so the comparison had to monkeypatch them off.
4. **Upstream analyses already record their own settings and we ignore them.** Every `.bm2` analysis carries `analysisInfo` notes: BMR type and factor, models, model-averaging method, BMDExpress version, and the prefilter work source. The clinical-chemistry BMR mismatch was visible in the data and went unchecked.

Three different kinds of change are mixed together, and they change at different rates:

| kind | changes when | example |
|---|---|---|
| analysis **method** | NIEHS revises its analysis method, every few years | BMR per assay family, pairwise test family, GO ranking statistic |
| document **template** | the report series' format changes | sections, their order, appendix layout |
| **study** selection | per report | NIEHS-10's "Select" clinical chemistry endpoints, its organ list |

A fourth kind, **correctness**, is not a change in method at all. The sciome `DunnettsTest` p-value is non-monotone: 8 SD → p = 0.44, 12 SD → p = 0.99. A fix like that applies to every report and is never something to choose.

## Decision

### 1. Three layers, resolved in order, every value carrying its source

```
built-in defaults  →  method profile  →  study overlay
```

- The **method profile** is new (§2).
- The **document template** stays as it is (ADR-0003/0025). It does not change with the method, and it carries no study selections.
- The **study overlay** (`templates/studies/<dtxsid>/`, which already holds study-specific appendix content) receives the per-report selections now in the shared template. These are the `organs` / `sex` / `assays` / `genes` / `gene_sets` blocks. The shared template ships with none of them.

Each resolved value is a `(value, source)` pair, where source is `default`, `profile:<name>` or `study:<dtxsid>`. The source travels with the value into the processing context and into the generated text. This applies the "no silent defaults" rule to method settings.

### 2. A method profile is a declarative, versioned, immutable artifact

- **Format:** a YAML file per profile, e.g. `profiles/ntp-5day-2021.yaml`, `profiles/ntp-5day-2025.yaml`, `profiles/dtt-2026-02.yaml`.
  - Named by **series and effective date**, not by "current".
  - Validated at load, like templates. An unknown key or an unregistered implementation name fails loudly.
- **Immutable once a report references it.** A revised method is a new file. An old study keeps resolving to the method it was analysed under.
- **Contents are limited to settings that actually differ between published eras.** The chronology names them; this is a closed list that grows only when a published era introduces a new one:

| setting | ntp-5day-2021 (NIEHS-07–10) | ntp-5day-2025 (NIEHS-12/13) | dtt-2026-02 (given PFHxSAm) |
|---|---|---|---|
| apical BMD engine | modified BMDS 2.7, high-dose dropping | BMDExpress 3 / ToxicR model averaging | BMDExpress 3 / ToxicR model averaging |
| apical BMR | 1 SD | 1 SD, every family | 1 SD; clinical chemistry 25% RD |
| apical BMD eligibility | every endpoint modelled | significant trend **and** ≥1 significant pairwise | Williams prefilter |
| trend / pairwise tests | Jonckheere; Williams or Dunnett (weights); Shirley or Dunn (clinical pathology) | same | same (assumed; to confirm) |
| outlier handling | outliers examined and excluded, with a footnote | same | same (assumed; to confirm) |
| genomic probe filter | none | drop probes with any zero ("No0") | No0 |
| genomic prefilter | Williams p < 0.05, fold ≥ 1.5 | Williams, then curve-fit at 2 SD | Williams, then curve-fit at 1.581 SD |
| genomic BMR / models | 1 SD, 8 models, lowest AIC | 25% RD, model averaging | 25% RD, model averaging |
| GO filters | BMD p ≥ 0.1, BMDU/BMDL ≤ 40 | R² ≥ 0.6, BMD/BMDL ≤ 10, 40–500 genes, ≥ 3 genes, ≥ 5% | as 2025 |
| GO ranking statistic | to confirm | 5th percentile | 5th percentile |
| top-genes table | to confirm | per-gene: Entrez gene, median over probes, BMDExpress-filtered | as 2025 |
| number format | fixed decimals per endpoint | fixed decimals per endpoint | to confirm |

  The table is the starting content, not the schema. The "to confirm" cells are open questions, not defaults.
- **No code in profiles.** A setting that selects behaviour names a registered implementation, e.g. `pairwise: {weights: williams_or_dunnett, clinical_pathology: shirley_or_dunn}`. The registry maps names to Python. Adding a method means registering an implementation, then referencing it from a new profile.

### 3. A study pins one profile

- Integration writes a `method_profile.json` beside `identity.json`, holding the profile name and the content hash.
- Processing reads only the pinned profile, never "latest".
- Re-pinning is an explicit act, recorded in the report's history (ADR-0020). Through currency (ADR-0015) it marks the derived content stale, so the next Process run recomputes.
- **Choosing a default for a new study is a human decision.** The UI proposes the newest profile for the series. The integrated data's own recorded settings (§5) can suggest a better match.

### 4. Generated text comes from the resolved settings, not from literals

The text that describes how numbers were made is rendered from the resolved values. This covers the statistics and BMR footnote definitions, the "Statistical analysis performed by …" legends, the GO table's statistic in captions and headers, and the methods-section facts given to the LLM. A footnote can then only name a test that actually ran. When a value came from a study overlay or a default, its source is available to the text, e.g. to flag an assumption.

### 5. Recorded upstream settings are checked against the pinned profile

For analyses we pass through rather than compute (the genomic `.bm2` today, apical `.bm2` BMDs where present), the `.bm2`'s own `analysisInfo` is the authority for **what was done**, and the profile states **what should have been done**. Ingest compares the two. Any disagreement becomes a flagged discrepancy in the validation report, shown to the human. Ingest never silently trusts either side or overrides one with the other. This is ADR-0019's provenance-to-authority rule, applied to method settings.

### 6. Each profile has a published reference report and a conformance test

- A profile is only trusted once it reproduces a published report:
  - `ntp-5day-2025` ↔ NIEHS-13;
  - `ntp-5day-2021` ↔ NIEHS-10, with the apical BMDS 2.7 caveat recorded below;
  - `dtt-2026-02` ↔ the Analysis Pipeline Evaluation published with NIEHS-12/13. There is no report yet.
- The NIEHS-13 comparison becomes a test fixture. It ingests the reference package, processes under the profile, and compares the tables to the published values within stated tolerances.
- **Known, accepted deviations are listed in the profile's conformance record**, each with its reason, so they are visible rather than tolerated by accident.

### 7. Correctness fixes are not profile settings

A bug fix, such as the Dunnett p-value or the GO up/down direction counts, changes the code for every profile. No profile may select the buggy behaviour. When a fix changes the numbers of an already-generated report, ADR-0020's history makes the change visible.

## Alternatives considered

- **Hardcode the latest method; treat old reports as legacy.** Rejected: validation against NIEHS-10 (2021) is a stated requirement, and the method is still moving (2 SD → 1.581 SD within a year). Every revision would overwrite the last.
- **Global settings with feature flags.** Rejected: flags combine into states no published report used, and nothing ties a combination to a study or to a reference output.
- **Per-study configuration only.** Rejected: each study would re-enter the same dozen settings, and nothing groups them into a named, validated method.
- **A general rules engine with effective dates.** Rejected as too much. The varying surface is about a dozen named settings. A closed, validated schema with registered implementations is enough, and it can be reviewed.
- **Branching code by era (`if era == 2021`).** Rejected: this is the scattered-literal problem made explicit, with no artifact to review or pin.

## Consequences

- The method of every report becomes inspectable and reproducible: "this report used `ntp-5day-2025` @ hash, plus these study selections."
- Published reports become regression tests for their era. A change that breaks NIEHS-13 conformance fails a test instead of surfacing weeks later.
- The shared template loses its NIEHS-10-specific allowlists. The NIEHS-10 session needs a study overlay to keep its current output; that move is part of the migration.
- The statistics fixes the NIEHS-13 comparison found land as registered implementations referenced by profiles: Williams, Shirley, Dunn, a correct Dunnett, outlier handling and relative-weight statistics. The BMR fix is a profile value.
- **Cost:** a resolver every consumer must go through. Any literal left behind is a silent default, so the migration must be complete per setting, not partial.
- **NIEHS-10 apical BMDs (modified BMDS 2.7 with high-dose dropping)** are outside our engines. `ntp-5day-2021` records the engine honestly, and its conformance record lists apical BMDs as an accepted deviation until a BMDS 2.7 path exists (decided 2026-10-01: "use modified BMDS 2.7 to validate").

## Open questions

- Do profiles live in `rlm-bmdx` or `bmdx-pipe`? Genomic settings are applied upstream (BMDExpress) and verified here; apical statistics run in `bmdx-pipe`. Leaning: the files live in `rlm-bmdx`, and `bmdx-pipe` receives resolved values and never reads profiles.
- How much of a mouse-plus-rat study (NIEHS-12/13 have two species) is one profile with two studies, and how much needs multi-species support? That is a data-model question (one gene-expression `.bm2` per pool today), not a profile question, but it blocks a full NIEHS-13 conformance test.
- The "to confirm" cells for `dtt-2026-02`.

## Implementation order

Each step is a separate change, verified against the golden oracle.

0. Profile format and loader with validation. Write `ntp-5day-2025.yaml` from the NIEHS-13 evidence.
1. Resolver: move the scattered literals behind it, one setting at a time. Pinned to a profile matching today's behaviour, the golden output is unchanged.
2. Footnotes, legends and methods facts rendered from resolved values.
3. Move the NIEHS-10 allowlists to its study overlay; the shared template ships with none.
4. Pin a profile per session at integration (`method_profile.json`), with the currency hook.
5. `.bm2` `analysisInfo` vs profile check at ingest.
6. NIEHS-13 conformance fixture, then the statistics implementations (correct Dunnett, Williams, Shirley, Dunn, outliers, relative-weight statistics) registered and referenced by `ntp-5day-2025`.

## Implementation status (2026-10-07)

- **Profiles:** `profiles/ntp-5day-2025.yaml` (reference NIEHS-13, with NIEHS-12) and `profiles/ntp-5day-2021.yaml` (reference NIEHS-10). `dtt-2026-02` is not written: there is no reference report.
- **Loader and resolver:** `pipeline/method_profile.py`. The schema is closed, implementations are registered, every value carries its source, and pins are immutable. The study overlay is the `methods:` block of `templates/studies/<dtxsid>/view.yaml`. A Process request's explicit GO settings are the top layer, with source `request`.
- **bmdx-pipe receives values, never profiles:** `ntp_stats.StatsMethod` and `bmd_acceptance.Criteria`.
- **Consumers moved behind the resolver:**
  - apical statistics (test family per platform, trend-selection p, alphas, minimum group size);
  - BMD acceptance (the `.bm2` classification and the ToxicR fills);
  - the apical BMR when none is recorded. `_ASSAY_FAMILY_BMR` is removed; its clinical chemistry 25% RD was the DTT value, not 2025's 1 SD;
  - internal-dose rules and significant figures;
  - GO ranking and display cutoffs. The UI and CLI no longer hard-code `median` / 5 / 20 / 500 / 3.
- **§4 Text from settings:**
  - table statistics footnotes and marker legends;
  - the concentration table's BD, half-LOD and outlier footnotes;
  - the Materials and Methods statistics and apical BMD guidance. Outlier exclusion is described only when the profile performs it;
  - Appendix D-1.
- **§3 Pin:** `sessions/<id>/method_profile.json` is written at integration. `generate_report --method-profile` pins or re-pins. The resolved settings' signature keys the NTP, BMDS and methods caches, so a re-pin recomputes.
- **§5 Check:** `recorded_mismatches` compares each `.bm2` `analysisInfo` with the pinned profile. Each disagreement is a `method_mismatch` warning in the validation report.
- **§6 Conformance:** the reference tests run each published report under its own profile. NIEHS-02 predates both profiles and runs on the built-in defaults.
- **Not moved (one implementation, the same in both published eras):**
  - per-endpoint display precision (`tables/display_precision.py`);
  - the body weight intermediate-day rule.
- **Not done:** a profile picker in the UI (CLI only); automated apical outlier exclusion (`outliers: null` in both profiles).
