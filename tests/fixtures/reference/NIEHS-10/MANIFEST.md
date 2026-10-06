# NIEHS-10 reference fixture — PFHxSAm, study C20022-01

A subset of the published CEBS package for NIEHS Report 10 (NBK589955), the
5-day gavage study of perfluorohexanesulfonamide in male and female Sprague
Dawley rats.  Files keep their CEBS names, so CEBS tooling
(`tooling.cebs_to_pool`, `tooling.ntp_stats_conformance`) runs on this
directory as on a downloaded package.

Source: https://cebs.niehs.nih.gov/cebs/data/publication/NIEHS-10
(DOI 10.22427/NIEHS-DATA-NIEHS-10), downloaded 2026-10-01; the full package is
in `assets/cebs/NIEHS-10/` (untracked).

## What it is the reference for

The **raw data and the summary tables** NIEHS published from them: the
Individual Animal workbooks are the study's inputs, and the PA06/PA41/PA43/PA48
summaries are what NTP computed from those same animals (means, SEM, N,
significance markers, tissue concentrations).  `report_values.json` holds the
few values only the report text states (plasma half-lives).
The BMD/BMDL/LOEL/NOEL summary (`…LOEL_and_NOEL_Summary….docx`) is the
oracle for LOEL/NOEL (`tests/unit/test_reference_bmd_summary.py`).

It is **not** a reference for BMDs or genomics: the published apical BMDs came
from modified EPA BMDS 2.7 and the genomics from a BMDExpress 2.30 project
shared with three other chemicals (neither is in this fixture).  NIEHS-13
(`../NIEHS-13/`) is the reference for the BMDExpress 3.20 analysis.

Tests build a session from these files through the real ingest path
(`reference_session` fixture in `tests/conftest.py`: `cebs_to_pool` → pool
fingerprinting → sidecars).

| file | bytes | sha256 (first 16) |
|---|---:|---|
| `C20022-01_BMD_BMDL_LOEL_and_NOEL_Summary_for_Apical_Endpoints_Sorted_by_BMD_LOEL_from_Low_to_High.docx` | 15,813 | `ffd11b3152216be8` |
| `C20022-01_Individual_Animal_Body_Weight_Data.xlsx` | 12,751 | `a6b949e1c942d702` |
| `C20022-01_Individual_Animal_Clinical_Chemistry_Data.xlsx` | 14,176 | `e5e16e035858833d` |
| `C20022-01_Individual_Animal_Clinical_Observations_Data.xlsx` | 25,387 | `11ed5a211d2e9602` |
| `C20022-01_Individual_Animal_Hematology_Data.xlsx` | 14,791 | `2672964d3d7d93cf` |
| `C20022-01_Individual_Animal_Hormone_Data.xlsx` | 8,157 | `ec9fce4bc7569da8` |
| `C20022-01_Individual_Animal_Organ_Weight_Data.xlsx` | 10,360 | `e1bce1c28a6a5c51` |
| `C20022-01_Individual_Animal_Tissue_Concentration_Data.xlsx` | 5,711 | `51dbb9a9a860beb9` |
| `C20022-01_PA06_–_Organ_Weights_Summary.pdf` | 98,234 | `31b778cddb67c35f` |
| `C20022-01_PA41_–_Clinical_Chemistry_Summary.pdf` | 312,847 | `a2f1a420dec8884b` |
| `C20022-01_PA43_–_Hematology_Summary.pdf` | 345,880 | `df3f16d3cd9004d5` |
| `C20022-01_PA48_-_Summary_of_Tissue_Concentration.pdf` | 32,726 | `61e6161326ab6a6c` |
