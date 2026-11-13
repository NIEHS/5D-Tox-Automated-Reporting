# NTP apical statistics vs the published significance markers

Run 2026-10-05 with `python -m tooling.ntp_stats_conformance assets/cebs/NIEHS-{07,08,09,10,12,13} --show-diffs`.

## What is compared

- **Implementation under test:** `bmdx_pipe.ntp_stats`, used by `apical_report.build_table_data`. It follows the procedure the published reports state in their Materials and Methods:
  - The Jonckheere trend test selects the pairwise test. When J p ≤ 0.01, the trend-sensitive test is used:
    - weights: Williams, otherwise Dunnett;
    - clinical pathology: Shirley, otherwise Dunn.
  - The control column's marker is the trend test. A dose column's marker is its pairwise test.
- **Published side:** the PA06 (organ weights), PA41 (clinical chemistry) and PA43 (hematology) summary tables of each package.
- **Data side:** each package's Individual Animal workbooks.
- **Row matching:** each published row is matched to a data endpoint by value. Every dose group must have the same N, and the same mean at the published precision. A row the NTP staff edited (outlier excluded) therefore stays **unmatched** and is not compared on different data.
- **NIEHS-02..05** publish the CEBS database export (one row per animal per measurement), not the Key/Data workbook; `tooling.cebs_db_export` converts it (2026-10-07). Their tables count the "Original Animals" (NIEHS-02/03; a second, month-later cohort is left out) or the whole study (NIEHS-04/05, unlabelled). NIEHS-06 has Key/Data workbooks with no Selection column.

## Result: 3636 / 3649 marker cells agree (99.6%)

| package | cells agree | unmatched rows (outlier edits) |
|---|---|---|
| NIEHS-07 | 788 / 790 | 3 |
| NIEHS-08 | 785 / 792 | 2 |
| NIEHS-09 | 799 / 800 | 2 |
| NIEHS-10 | 638 / 640 | 2 |
| NIEHS-12 | 255 / 256 | 13 |
| NIEHS-13 | 371 / 371 | 7 |
| NIEHS-02 | 101 / 102 | 2 |
| NIEHS-03 | 102 / 102 | 2 |
| NIEHS-04 | 102 / 102 | 2 |
| NIEHS-05 | 85 / 85 | 2 |
| NIEHS-06 | 100 / 102 | 2 |

NIEHS-02..06 (run 2026-10-07, `… assets/cebs/NIEHS-0{2,3,4,5,6}`): 490 / 493 marker cells and 492 / 493 printed cells agree. Their unmatched rows are Globulin and A/G Ratio, which NTP derives. Their 3 disagreements are also at 0.01: NIEHS-02 Brain Relative 2.7 (Williams p = 0.0133, published `**`), NIEHS-06 Liver Absolute 2.7 (p = 0.0124, `**`), NIEHS-06 Albumin 0.675 (p = 0.0097, published `*`). The printed-cell difference is NIEHS-03 Sorbitol dehydrogenase 2.7, 22.1 ± 13.8 vs published 22.0.

Relative organ weights (organ / terminal body weight × 1000, per animal) are included in PA06 and agree like the absolute weights.

## Choices the published markers decided

- **Jonckheere variance:** the tie-corrected normal approximation (Hollander–Wolfe). It agreed with the published markers best. The no-tie and continuity-corrected variants were each worse by 2 cells, and a Monte-Carlo exact p did not fix the borderline cells.
- **Williams / Shirley critical values:** simulated for the exact design. There are 200k null draws, with the seed derived from the design. The simulation reproduces Williams' tables (k = 1..6, df = ∞). A step with one treatment group left is exact instead (normal for Shirley, t for Williams; bmdx-pipe 2026-10-07): the simulation put NIEHS-13 Table 19's 1 ppm blood at p = 0.0500 + noise, the exact p is 0.0495 (published `*`). The totals above did not change.
- **Two-sided reporting:** the step-down p-value is one-sided in the Jonckheere direction, doubled.
- **Groups of one animal are left out of every test:** NIEHS-07 male has 1000 mg/kg with N = 1. The cell is shown without a marker, and lower doses keep their Williams/Shirley markers. With the group included, the step-down stops at it and loses 28 cells (760/790).

## The 13 remaining disagreements are all at a threshold

| package | endpoint | ours | published |
|---|---|---|---|
| NIEHS-07 M | Reticulocytes 111 | Shirley p = 0.0099 (`**`) | `*` |
| NIEHS-07 M | Creatinine 111 | Shirley p = 0.049 (`*`) | none |
| NIEHS-08 F | Alk Phos 18/55/160 | Shirley p = 0.038–0.048 | none |
| NIEHS-08 F | Monocytes 55 | Shirley p = 0.0486 | none |
| NIEHS-08 F | Large Unstained Cells | J = 0.0104, so Dunn (published used the trend test: control `**`, 160/475 `*`) | — |
| NIEHS-09 F | Globulin control | J = 0.0501 | `*` |
| NIEHS-10 M | Cholesterol control / 111 | J = 0.0105 / Dunn p = 0.0486 | `**` / `**` |
| NIEHS-12 F | L. Kidney Relative 100 | Williams p = 0.0099 (`**`) | `*` |

Each is within about 0.001 of 0.01 or 0.05. Possible sources:

- the simulation noise of the critical values;
- NTP's exact-versus-asymptotic choices;
- NTP's rounding of the input values.

None points to a different procedure.

## Not reproduced: outlier removal

NTP staff examine values flagged by the Dixon and Massey test, and remove some by judgement. The removed values are visible only as published Ns smaller than the data's. We do not remove outliers. Rows where NTP did are listed as unmatched above. In our reports those endpoints are computed on all animals.

## Internal concentration tables (G3, 2026-10-07)

NIEHS-12 Tables 18/19 and NIEHS-13 Tables 19/20 (blood, liver and lung by study day) come from the lab's results workbook in each Bookshelf bundle (`tooling.cebs_lab_concentration` → `tables.blood_tissue_concentration_table`). Nonparametric family (Jonckheere, Shirley or Dunn), tested only when the control has a mean. 359 / 364 compared cells agree, markers and BD included (`tests/unit/test_reference_internal_concentration.py`). The 5 differences are NIEHS-12 Table 19 SEs printed at 2 significant figures ("0.80"). Every exclusion reproduces with Dixon's r10 outlier test at α = 0.01 (the reports' "outlier test of Dixon and Massey"), values below the LOD at ½ LOD. Not built: the rows normalized by the theoretical inhaled dose, which no data file records.
