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

- **Body Weight Gain**: the Mean Body Weight Summary's gain row —
  `tests/unit/test_reference_body_weight_gain.py`.
- **Genomics**: the Top 10 GO Biological Process gene sets and Top 10 genes for
  all five tissues, and the most potent GO set per tissue —
  `tests/unit/test_reference_genomics.py` runs the report's own table code on
  `108020004_4D_Genomic_Rats.slim.json.gz`, the part of the genomic project
  those tables read (`tooling/slim_genomics_extract.py`: the ExportGenomics GO
  categories and gene fits, BMDExpress's GO_BP/GENE category analyses, the BMR
  notes; values copied, inputs' checksums inside).  The full project
  (`108020004_4D_Genomic_Rats.bm2`, 9.8 MB, sha256 `f5a180b98a603d84…`; 55 MB as
  JSON; Java to read) is not in the fixture.  Two ovary files are swapped in
  the CEBS package ("…Top_10_Genes_…_Ovary" holds the ovary GO table,
  "…Top_10_GO_…_Lung_Ovary" the ovary genes table); the test identifies each
  table by its content.

| file | bytes | sha256 (first 16) |
|---|---:|---|
| `108020004_4D_Genomic_Rats.slim.json.gz` | 471,657 | `ea61e95c674ab496` |
| `108020004_4D_NonGenomic_Rats.bm2` | 137,432 | `7e04d1e6c3260c6b` |
| `108020004_4D_NonGenomic_Rats.bm2.json` | 545,177 | `18cdecc04083957a` |
| `108020004_BMD,_NOEL_and_LOEL_Summary_for_Apical_Endpoints_Rats.pdf` | 176,770 | `85a2aa1c54f13ae5` |
| `108020004_Individual_Animal_Body_Weight_Data_Rats.xlsx` | 14,609 | `5bd627a31e7ca934` |
| `108020004_Individual_Animal_Clinical_Chemistry_Data_Rats.xlsx` | 15,386 | `68dd25995cbecfc1` |
| `108020004_Individual_Animal_Clinical_Observations_Data_Rats.xlsx` | 12,221 | `96c9349b2e50a79d` |
| `108020004_Individual_Animal_Hematology_Data_Rats.xlsx` | 18,680 | `7237e28baa2d78fd` |
| `108020004_Individual_Animal_Organ_Weight_Data_Rats.xlsx` | 6,909 | `33518352fea28adb` |
| `108020004_Individual_Animal_Removal_Reasons_Data_Rats.xlsx` | 6,552 | `a7467517f8464edd` |
| `108020004_Mean_Body_Weight_Summary_Rats.pdf` | 87,337 | `4bbff660009191f1` |
| `108020004_Most_Potent_GO_Biological_Process_In_Each_Tissue_Rats.pdf` | 50,061 | `32b8516b356b62d8` |
| `108020004_PA06_Organ_Weights_Summary_Rats.pdf` | 64,203 | `191948f4942d5ef1` |
| `108020004_PA41_Clinical_Chemistry_Summary_Rats.pdf` | 153,927 | `0216f061153116e9` |
| `108020004_PA43_Hematology_Summary_Rats.pdf` | 76,774 | `d7d2e9b8a4e08db0` |
| `108020004_Top_10_GO_Biological_Process_Gene_Sets_Heart_Rats.pdf` | 149,380 | `615d40bab09ad760` |
| `108020004_Top_10_GO_Biological_Process_Gene_Sets_Kidney_Rats.pdf` | 152,389 | `94d9faf6c4858596` |
| `108020004_Top_10_GO_Biological_Process_Gene_Sets_Liver_Rats.pdf` | 135,957 | `e31d0e96df9f6280` |
| `108020004_Top_10_GO_Biological_Process_Gene_Sets_Lung_Ovary_Rats.pdf` | 263,908 | `90c1f92700091f0b` |
| `108020004_Top_10_GO_Biological_Process_Gene_Sets_Lung_Rats.pdf` | 150,702 | `e9e4f223584f6ef9` |
| `108020004_Top_10_Genes_Ranked_by_Potency_of_Perturbation_Heart_Rats.pdf` | 264,639 | `8bdfa4d651889d68` |
| `108020004_Top_10_Genes_Ranked_by_Potency_of_Perturbation_Kidney_Rats.pdf` | 294,268 | `28e0a103e714053e` |
| `108020004_Top_10_Genes_Ranked_by_Potency_of_Perturbation_Liver_Rats.pdf` | 255,424 | `0da64dbaf09a5ab7` |
| `108020004_Top_10_Genes_Ranked_by_Potency_of_Perturbation_Lung_Rats.pdf` | 203,098 | `40bd7c145efc3d3a` |
| `108020004_Top_10_Genes_Ranked_by_Potency_of_Perturbation_Ovary_Rats.pdf` | 148,280 | `69b1adda6f5a733f` |

## Internal concentration (added 2026-10-07)

| file | what |
|---|---|
| `108020004_Individual_Animal_Blood_and_Tissue_Concentration_Data.xlsx` | the analytical lab's blood/lung/liver results, rat and mouse sheets (Bookshelf bundle only; not in the CEBS package) |
| `bookshelf_Table_19.json`, `bookshelf_Table_20.json` | the published rat and mouse concentration tables (`tooling.bookshelf_breakdown`) |

Reference for `tests/unit/test_reference_internal_concentration.py`
(`tooling.cebs_lab_concentration` → `tables.blood_tissue_concentration_table`).
Every published cell reproduces, including the three Dixon–Massey outlier
exclusions of the mouse table.  The bundle's `108020005_…` workbook holds the
same data and is not copied.
