# NIEHS-13 reference fixture — 1,4-dichlorobenzene, rat study 108020004

A subset of the published CEBS package for NIEHS Report 13: the 5-day
whole-body inhalation study of 1,4-dichlorobenzene in female Sprague Dawley
rats (0–800 ppm).  NIEHS-13 is the 2025 (G3) method — BMDExpress 3.20, ToxicR
Laplace model averaging, BMR 1 SD for apical endpoints, the NIEHS defined-
category filter — the analysis this project's pipeline targets.  Files keep
their CEBS names, so CEBS tooling runs on this directory as on a downloaded
package.  Only the rat study is included (the mouse study is 108020005).

Source: https://cebs.niehs.nih.gov/cebs/data/publication/NIEHS-13, downloaded
2026-10-01; the full package is in `assets/cebs/NIEHS-13/` (untracked).
Session-level comparison of the whole report: `assets/cebs/NIEHS-13-comparison.md`.

## What it is the reference for

- **Raw data → summary tables**: the Individual Animal workbooks and the
  PA06/PA41/PA43 summaries NTP computed from them (means, SEM, N, markers,
  printed precision) — `tests/unit/test_reference_conformance.py`.
- **Apical BMDs**: the non-genomic BMDExpress project and the published
  "BMD, BMDL, LOEL, and NOEL Summary" — `tests/unit/test_reference_bmd_summary.py`.
  `108020004_4D_NonGenomic_Rats.bm2.json` is the `.bm2` deserialized by
  bmdx-pipe's ExportBm2 (`assets/cebs/bm2json.sh`; needs Java, so tests read
  the JSON).  The project also carries NIEHS-12's (108020006/7) analyses.

**Not covered yet: genomics.**  The GO and gene tables come from the
genomic project's category analyses (`108020004_4D_Genomic_Rats.bm2`, 9.8 MB;
55 MB as JSON; Java to read) — too large / not offline for this fixture.  The
session comparison reproduces the Top-10 GO tables (40/40 GO IDs, BMD, BMDL,
BMDU); a test for it needs a decision on how to carry that project.

| file | bytes | sha256 (first 16) |
|---|---:|---|
| `108020004_4D_NonGenomic_Rats.bm2` | 137,432 | `7e04d1e6c3260c6b` |
| `108020004_4D_NonGenomic_Rats.bm2.json` | 545,177 | `18cdecc04083957a` |
| `108020004_BMD,_NOEL_and_LOEL_Summary_for_Apical_Endpoints_Rats.pdf` | 176,770 | `85a2aa1c54f13ae5` |
| `108020004_Individual_Animal_Body_Weight_Data_Rats.xlsx` | 14,609 | `5bd627a31e7ca934` |
| `108020004_Individual_Animal_Clinical_Chemistry_Data_Rats.xlsx` | 15,386 | `68dd25995cbecfc1` |
| `108020004_Individual_Animal_Clinical_Observations_Data_Rats.xlsx` | 12,221 | `96c9349b2e50a79d` |
| `108020004_Individual_Animal_Hematology_Data_Rats.xlsx` | 18,680 | `7237e28baa2d78fd` |
| `108020004_Individual_Animal_Organ_Weight_Data_Rats.xlsx` | 6,909 | `33518352fea28adb` |
| `108020004_Individual_Animal_Removal_Reasons_Data_Rats.xlsx` | 6,552 | `a7467517f8464edd` |
| `108020004_PA06_Organ_Weights_Summary_Rats.pdf` | 64,203 | `191948f4942d5ef1` |
| `108020004_PA41_Clinical_Chemistry_Summary_Rats.pdf` | 153,927 | `0216f061153116e9` |
| `108020004_PA43_Hematology_Summary_Rats.pdf` | 76,774 | `d7d2e9b8a4e08db0` |
