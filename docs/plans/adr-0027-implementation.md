# ADR-0027 implementation plan — method profiles

Date: 2026-10-07.  ADR: `docs/adr/0027-pinned-method-profiles.md` (Proposed).

## Where we start

Already done in earlier work, outside a profile:

- **Step 3** (study selections out of the shared template): `templates/niehs-5day-report.yaml`
  selects nothing; NIEHS-10's organ/assay lists live in `templates/studies/DTXSID50469320/view.yaml`
  (rlm be8a831).
- **Step 6** (statistics implementations + conformance fixtures): Jonckheere, Williams,
  Dunnett, Shirley, Dunn, exact last step, relative-weight statistics, the NIEHS defined-category
  filter, Dixon outliers for concentrations — and reference fixtures for NIEHS-02/10/12/13 with
  ratchet tests.  But every method choice is a **code constant**, and the text describing the
  method is a **literal** beside it.

The method literals (the closed list this plan moves):

| setting | lives today |
|---|---|
| pairwise family per platform | `bmdx_pipe.ntp_stats.PLATFORM_FAMILY` |
| trend-test selection p, marker alphas, min group n | `ntp_stats.TREND_TEST_SELECT_P`, `ALPHA_STAR/DSTAR`, `MIN_GROUP_N` |
| apical BMR when a platform records none | `tables/apical_bmds._ASSAY_FAMILY_BMR` (clin chem 25% RD = the DTT value, not 2025's 1 SD) |
| BMD acceptance (R², BMD/BMDL, NR fraction) | `bmdx_pipe.bmd_acceptance` constants |
| internal dose: BD share, ½-LOD, Dixon α, test family, sig figs | `tables/blood_tissue_concentration_table.py`, `tables/display_precision.py` |
| GO ranking statistic + display cutoffs | UI/CLI request defaults (`["median"]`, 5/20/500/3) |
| number format | `tables/display_precision.py` (per-endpoint decimals) |
| method text | footnote literals in body_weight/organ_weight/clinical_pathology/table_builder_common/blood_tissue tables; `narrative/methods_prompt.py` stat_analysis + BMR phrase; Appendix D from module constants |

## Steps (each a separate commit, full suite + reference ratchets green)

### 0. Format, loader, validation
- `profiles/ntp-5day-2025.yaml` (reference NIEHS-13) and `profiles/ntp-5day-2021.yaml`
  (reference NIEHS-10) — only settings we implement and can test; unknown values are `null`
  ("to confirm"), never invented.  `dtt-2026-02` is not written (no reference report).
- `pipeline/method_profile.py`: closed schema (unknown key → error), registry of implementation
  names (`williams_or_dunnett`, `shirley_or_dunn`, `dixon_r10`, `half_lod`, `ntp_fixed_decimals`,
  `toxicr_model_average`, `trend_and_pairwise`, …; unknown name → error), content hash.
- Tests: both profiles load; a bad key / bad implementation name fails loudly.

### 1. Resolver, literals behind it
- `resolve(profile, overlay, request) → MethodSettings`: layers default → `profile:<name>` →
  `study:<dtxsid>` (overlay `method:` block in the study view file) → `request` (explicit
  UI/CLI values); every value is `(value, source)`.  `session_method(dtxsid)` reads the pin.
- bmdx-pipe takes resolved values as arguments (never reads profiles): `ntp_pairwise(...,
  trend_select_p, min_group_n)`, `sig_marker(p, alphas)`, `build_table_data(..., stats=)`,
  `bmd_acceptance.classify(..., criteria=)`.  Library defaults stay for other callers.
- rlm consumers switch: process (build_table_data, ToxicR classification), apical BMR
  fallback, concentration table, GO ranking/cutoffs default (request still overrides),
  CLI `--bmd-stats` default None ⇒ profile.  UI Process/Results stop hard-coding
  `bmd_stats: ["median"]` and the GO cutoffs; the server resolves them.
- Proof: golden/regression/reference tests unchanged (pinned profile = today's behaviour
  except the documented clin-chem inferred BMR, which no current session uses).

### 2. Text from resolved values
- Statistics legends ("Jonckheere … Williams or Dunnett / Shirley or Dunn") built from the
  family the table's platform resolved to; marker legend from the resolved alphas.
- Methods prompt stat_analysis + apical BMR phrase + acceptance sentence from resolved values.
- Appendix D-1 from the resolved acceptance criteria.
- Concentration footnotes (BD share, ½ LOD, test family) from resolved values.

### 4. Pin per session + currency
- `sessions/<id>/method_profile.json` `{name, hash, pinned_at, source}` written at integration
  when absent (newest profile of the series, source `default`, logged); `generate_report
  --method-profile NAME` pins/re-pins (source `user`).
- The profile hash folds into the NTP, sections, BMD-summary, BMDS, genomics and methods cache
  keys, so a re-pin recomputes.  Re-pin is logged.

### 5. Recorded `.bm2` settings vs the profile
- At integration: compare each `.bm2` analysis's recorded config (apical bMDResult BMR/
  model averaging; genomic BMR, model selection, prefilter where recorded) with the profile's
  expectations; each disagreement is a `method_mismatch` warning in the validation report and
  the CLI log.  Neither side overrides the other.

### Out of scope here (named, not done)
- Profile picker in the UI (CLI flag only).
- `dtt-2026-02` profile; NIEHS-10 apical BMDS 2.7 engine (accepted deviation in the 2021
  conformance record).
- Apical outlier exclusion (published tables exclude by staff judgement) — recorded in the
  profiles as `outliers: null` for apical.
- ADR status → Accepted once steps 0–5 land.
