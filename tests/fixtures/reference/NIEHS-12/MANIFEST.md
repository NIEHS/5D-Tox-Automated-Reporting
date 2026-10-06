# NIEHS-12 reference fixture — 1,2-dichlorobenzene, rat 108020006 + mouse 108020007

A subset of the published CEBS package for NIEHS Report 12: the 5-day whole-
body inhalation studies of 1,2-dichlorobenzene in female Sprague Dawley rats
(0–500 ppm) and female B6D2F1/Crl mice (0–250 ppm).  Same (G3, 2025) method as
NIEHS-13.  Files keep their CEBS names.  Only the body weight files are
included: NIEHS-12 is the one report whose body weight table prints study days
between the first and the last — the days whose statistics are responsive.

Source: https://cebs.niehs.nih.gov/cebs/data/publication/NIEHS-12, downloaded
2026-10-01; the full package is in `assets/cebs/NIEHS-12/` (untracked), the
report itself in `assets/cebs/_bookshelf/NIEHS-12/` (Table 2).

| file | what |
|---|---|
| `108020006_Individual_Animal_Body_Weight_Data_Rats.xlsx` | rat body weights SD0–SD5, Core + Biosample animals |
| `108020007_Individual_Animal_Body_Weight_Data_Mice.xlsx` | mouse body weights, same |
| `108020006_Mean_Body_Weight_Summary_Rats.pdf` | rows SD0, SD4, SD5, gain — mean ± SEM [N], * / ** |
| `108020007_Mean_Body_Weight_Summary_Mice.pdf` | rows SD0, SD2, SD3, SD4, SD5, gain |

## What it is the reference for

- **Which study days the body weight table shows** (first, last, and every
  responsive day between) and each cell's mean ± SE and marker —
  `tests/unit/test_reference_body_weight_days.py`.
