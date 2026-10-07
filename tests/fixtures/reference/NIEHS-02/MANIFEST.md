# NIEHS-02 reference fixture — 2-ethylhexyl diphenyl phosphate, study C10674

A subset of the published CEBS package for NIEHS Report 02 (5-day gavage study
of EHDP in male Sprague Dawley rats, 0–2.70 mMol/kg = 0–979 mg/kg).  Files keep
their CEBS names.  NIEHS-02 … 05 publish their Individual Animal data as the
CEBS DATABASE EXPORT (one row per animal per measurement, DEPOSITOR_STUDY_NUMBER /
ANMLNUM / SELECTION / …), not the NTP Key/Data workbook of NIEHS-06 onward;
tooling.cebs_db_export converts it.  Doses are in mMol/kg, as the data (and the
NTP summaries) record them.

Source: https://cebs.niehs.nih.gov/cebs/data/publication/NIEHS-02, downloaded
2026-10-01; full package in `assets/cebs/NIEHS-02/` (untracked), the report in
`assets/cebs/_bookshelf/NIEHS-02/`.

| file | what |
|---|---|
| `C10674_Individual_Animal_{Body_Weight,Clinical_Chemistry,Clinical_Observations,Hormone,Organ_Weight}_Data.xlsx` | database exports; a second cohort (8 animals, dosed a month later, SELECTION blank) besides the "Original Animals" |
| `C10674_I04_Mean_Body_Weight_Summary.pdf` | body weights — "Males: Original Animals" |
| `C10674_PA06_Organ_Weights_Summary.pdf`, `C10674_PA41_Clinical_Chemistry_Summary.pdf` | organ weights, clinical chemistry |

## What it is the reference for

- **The database-export conversion** — the Original Animals only, "Exclude"
  → NA: every published body weight cell (`test_reference_body_weight_days.py`)
  and the PA06/PA41 means, N, markers and printed cells
  (`test_reference_conformance.py`; 1 marker at p ≈ 0.013 is the known engine edge;
  Globulin and A/G Ratio are NTP-derived rows).
