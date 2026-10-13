# Report-writing rules: inventory (2026-10-13)

What decides the report's words and table content, beyond the data itself, and
where each rule lives today. Agreed direction (2026-10-13):

- Every report-writing rule is either declared in the document definition or
  is a named, registered rule implementation that the definition selects.
  A rule that changed gets a new name; the old name stays registered, so an
  old report keeps rendering as it did.
- Analysis rules (how the numbers are made) stay in the method profile
  (ADR-0027).
- Definitions are pinned per session like method profiles
  (`document_model.definition_pin`).

Status key:

- **decl**: declared in the definition YAML.
- **profile**: in the method profile.
- **code**: a literal or branch in Python.

Basis key:

- **book**: grounded in the published books.
- **inferred**: chosen by us without a published statement.

## A. Already declared

| Rule | Where | Status |
|---|---|---|
| Structure, ordering, numbering, repeats per study/tissue, route gates | definition | decl |
| 2026 genomic results, eFDR and definitions wording | `phrasing:` (ADR-0029 §11) | decl |
| Abstract names genes (2023) or gene sets only (2026) | `abstract_genes` | decl |
| Tissue order | `tissue_order` | decl |
| Dose words ("Exposure Concentration …") | node titles | decl |
| BMD summary caption (2026) | node `caption` | decl |
| What the generated prose cites | `cited_as` | decl |
| Statistical tests, alphas, BMD acceptance, BMR, GO ranking and display cut-offs, internal-dose rules, eFDR null data generation | method profile | profile |

## B. Rules in code

### B1. Reliability. One rule, many copies, and two inferred thresholds

| Rule | Where | Status | Basis |
|---|---|---|---|
| Lower limit of extrapolation = lowest non-zero dose ÷ 3. Gene sets, genes and BMDs below it are not "reliably calculated". | 7 copies: `narrative/abstract_genomics.py:189`, `narrative/abstract_summary.py:127`, `narrative/report_summary.py:110`, `genomics/gene_bodies.py:203`, `:418`, `rendering/report_data_overlays.py:434`, `rendering/genomics_results.py:177`. The apical equivalent is the profile's `not_reportable_fraction`. | code ×7 | book (`<LNZD/3`) |
| A reliable BMD is numeric and viable, not `—`/NVM/ND/NA | `narrative/narrative_helpers._is_reliable_bmd` | code | book |
| **Anomalous BMD (UREP)**: BMD < NOEL ÷ 10 (or LOEL ÷ 10). It is replaced by UREP in the BMD summary table and dropped from the Abstract's effects. | `narrative_helpers.ANOMALY_RATIO_THRESHOLD = 10` (used by `pipeline/processing_helpers` and `abstract_*`) | code | **inferred** (the docstring says "somewhere around 10×") |
| **"In the same range"**: two points of departure within 2× of each other | `narrative/report_summary._SAME_RANGE_FACTOR` | code | **inferred** (one NIEHS-10 example) |
| Top-N picks: up to N, ascending BMD, at or above the limit, NaN dropped | `narrative_helpers._picks_above_lle` | code | book |

### B2. Apical tables (`tables/`)

| Rule | Where | Status | Basis |
|---|---|---|---|
| A row is shown when the endpoint is responsive (trend and pairwise) | builders; thresholds from the profile | code + profile | book |
| BMD cell sentinels: ND (not responsive or failed), NA (n row, baseline), `—` (not modeled) | `table_builder_common.bmd_display_from_stats`, `_NON_REPORTABLE_BMD` | code | book |
| Bold row: responsive, or has a reportable BMD | `clinical_pathology_table:244`, `organ_weight_table:510` | code | book |
| An organ is shown when its absolute or relative weight responds. The terminal body weight row is always shown, with BMD ND. | `organ_weight_table` | code | book |
| Body weight: first and last day, plus responsive intermediate days only | `body_weight_table:750` | code | book (NIEHS-12 vs 13) |
| Body weight gain row when the data has the derived endpoint; caption "… and Body Weight Gain" | `body_weight_table:709` | code | book (2025 books). **Not gated by era; check the 2023 reports.** |
| **BMD definition footnote** says "one standard deviation" | `table_builder_common.BMD_DEFINITION` | code | book for 1 SD. **Wrong whenever the profile or recorded BMR is not 1 SD** (e.g. DTT clinical chemistry 25% RD). It should come from the profile or recorded BMR. |
| Footnote scheme: significance explanation, marker key (profile), BMD definition, (a) data format, (b) statistics (profile), attrition (one per whole lost group, day from data), "sample not received" (one per distinct count), lettering order | `table_builder_common` | code + profile | book |
| Decimals per endpoint (the published convention table); fallback = recorded precision | `tables/display_precision.PUBLISHED_DECIMALS` (a data table written in Python) | code | book |
| Adaptive decimals by magnitude; raw floats to 2 dp | `table_builder_common.adaptive_decimals`, `DISPLAY_DECIMALS` | code | book / inferred |
| Caption templates: "Summary of Select {Platform} Data for {subject} {treatment}", organ weight, plasma, blood/tissue | `CAPTION_TEMPLATE` in each builder | code | book |
| Below LOQ → LOQ ÷ 2 (G2 plasma table) | `tissue_concentration_table:262` | code | book. The profile has `internal_dose.below_limit`, but this table doesn't read it. |
| BMD summary rows: reliable BMDs ascending, then the rest by LOEL; sex order Male, Female | `pipeline/processing_helpers:1693` | code | book |

### B3. Genomic tables

| Rule | Where | Status | Basis |
|---|---|---|---|
| Caption "Top N <Organ> … Ranked by Potency of Perturbation, Sorted by <stat>"; the percentile form is "5th Percentile Benchmark Dose" | `rendering/render_common.genomics_table_caption` | code | book |
| Statistic names in headers ("5th Percentile", "Median") | `render_common._STAT_PHRASE` | code | book |
| Genes ranked by the median over their probes; top 10 | `render_common`, genomics converter | code | book |
| Most potent gene set per tissue: lowest BMD per group and tissue, most potent first | `rendering/genomics_summary` | code | book (2026) |

### B4. Genomic prose. The rule that already evolved

| Era | Where | Status |
|---|---|---|
| 2026 (NIEHS-12, 13) | `rendering/genomics_results` (rules) + `phrasing:` (words) | code + decl |
| NIEHS-10 skeleton (2023 and earlier) | `genomics/gene_bodies` (rules and words, its own limit copies) | code |

The definition already chooses between them through its data bindings
(`intro_key` / `gene_set_results` against `gene_set_narrative`). This is the
pattern to generalise: two named implementations, selected by the
definition. The 2018 genomic "not reportable" rules (G0/G1, open) would be a
third.

### B5. Programmatic prose (`narrative/`)

| Section | Where | What is in code |
|---|---|---|
| Abstract: Methods | `abstract_methods` | the whole template |
| Abstract: Results (apical) | `abstract_apical` | which effects are named (reliable, not anomalous); direction words; wording |
| Abstract: Results (genomics) | `abstract_genomics` | top picks, the limit; wording |
| Abstract: Results (PK) | `abstract_pk` | two-point half-life; wording |
| Abstract: Summary | `abstract_summary` | lowest reliable apical, gene set and gene; wording |
| Summary section | `report_summary` | the NIEHS-10 five-part shape, UREP list, ×2 same range; wording. (The Summary prompt is also a versioned template; two mechanisms coexist.) |
| Results narratives (animal condition, body/organ weight, clinical pathology) | `unified_narrative` | `string.Template` sentences; selection by LOEL and lowest significant dose; `_DIRECTION_WORDS` |
| Methods: Study Design, Dose Selection, Chemistry | `methods_design` | the templates and their placeholder rules |
| Methods subsection skeleton (headings, gates) | `methods_models.SUBSECTION_SKELETON` | **structure in code**, parallel to the document tree |

### B6. Study-design wording (`pipeline/study_design`)

| Rule | Status | Basis |
|---|---|---|
| "Administered X for Five Days" against "Exposed to X …", by route | code | book |
| "vehicle control" against "chamber control" | code | book |
| Species plural and capitalisation; "Rats and Mice" for compositions | code | book |
| The sanctioned fallback design (SD rats, gavage, corn oil; ppm → inhalation) | code | the user's decision (2026-10-05) |

### B7. LLM prompts

| Section | Where | Versioned? |
|---|---|---|
| Summary | `sessions/_prompts` (Jinja, prompt workshop) | yes |
| Materials and Methods guides | `narrative/methods_prompt` | no |
| Background | `narrative/background_writer` | no |
| Tissue interpretation, apical BMD narrative | `narrative/interpret*`, `genomics_llm`, `apical_bmd_llm` | no |

### B8. Formats

| Rule | Where |
|---|---|
| Limit printed to 3 decimals | `genomics_results._lle_text` |
| eFDR two decimals, half-up | `genomics_appendix._pct` |
| Doses: trailing zeros dropped, thousands separated | `narrative_helpers._format_dose_value`, `table_builder_common.format_dose_label` |
| Serial comma ("a, b, and c") | `_join` / `_join_oxford` (three copies) |

## C. Findings

1. **One rule, seven copies.** The lower limit of extrapolation is
   computed seven times. It is an acceptance rule, like the apical
   `not_reportable_fraction`. It belongs in the profile once and should be
   read everywhere from there.
2. **Two thresholds are inferred, not published:** UREP's 10× and the
   Summary's 2× "same range". Under the rules-or-declarations model each
   needs a stated basis, or should be marked as our convention.
3. **A latent wrong footnote.** The BMD definition footnote always says
   1 SD, even when the BMR is not 1 SD.
4. **Era variation not gated:** the body weight gain row (check 2023), and
   the G2 plasma table's LOQ ÷ 2, which ignores the profile's `below_limit`.
5. **Structure in code:** the Methods subsection skeleton.
6. **Most prose wording outside the 2026 genomic text is still in Python:**
   the abstract, Summary, results narratives, Methods templates, captions,
   footnotes and study-design phrases.

## D. Proposed order of moves

1. **Profile, as `ntp-5day-2025.2`:** the lower limit's fraction (one reader
   replaces the seven copies). Also decide the basis of UREP 10× and the
   same-range 2×.
2. **Fix the BMD definition footnote** from the BMR in effect (the profile
   or the record).
3. **Wording into `phrasing:`** section by section, each with a
   text-identity check against every published report:
   - table captions and footnotes;
   - study-design phrases;
   - results narratives;
   - abstract;
   - Summary;
   - Methods templates.
4. **Named rule implementations** where the books changed a rule:
   - genomic prose (`ntp-2023` = `gene_bodies`, `ntp-2026` =
     `genomics_results`);
   - body weight gain;
   - 2018 genomic not-reportable rules.
   The definition names each rule, e.g. `rules: {genomic_prose: ntp-2026}`.
5. **The Methods subsection skeleton** moves into the tree.
