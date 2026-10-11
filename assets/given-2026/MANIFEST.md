# PFHxSAm package as originally supplied to this project ("PFHxSAm.zip")

Recovered 2026-10-01 from a test-fixture copy after the live reference session was reset. 21 files.
Characterised with the same tooling as the CEBS packages (`_characterization.json`, `_facts.json`).

## What it is
A **re-analysis of the NIEHS-10 study (PFHxSAm, C20022-01) run on 2026-03-02 in BMDExpress 3.20.0156**
using the February 2026 DTT method (published as the NIEHS-12/13 "Analysis Pipeline Evaluation"), NOT the analysis behind the published report.

| file(s) | contents |
|---|---|
| `Gene Expression-Perflourohexane Sulfonamide.bm2` | 4 experiments `{Liver,Kidney}_PFHxSAm_{Male,Female}_No0`: zero-count probes removed (1,717–2,025 of 2,654). Williams p<0.05 (10,000 perm) → curve-fit prefilter (**BMR factor 1.581**, the February 2026 DTT method documented in the NIEHS-12/13 "Analysis Pipeline Evaluation"; the published DCB reports used 2) → ToxicR Laplace MA (Hill/Power/Exp3/Exp5), BMR 25% relative deviation, step 0.5 → GENE + GO BP (R²≥0.6, BMD/BMDL≤10) + S1500 Adversity Signatures category analysis |
| `{Liver,Kidney}_PFHxSAm_{Male,Female}_No0.txt` | the No0 expression matrices (values identical to the CEBS files for the probes kept) |
| `Body weight / Clinical Chemistry / Hematology / Hormones / Organ Weights.bm2` | apical BMDs in BMDExpress 3.20.0156: Williams prefilter → ToxicR Laplace MA (4 models), BMR 1 SD — **except Clinical Chemistry, which uses BMR 25% relative deviation** |
| `{male,female}_{body_weight,clin_chem,hematology,hormone_data,organ_weights}.txt` | apical BMDExpress input matrices |
| `Bookshelf_NBK589955 (2).pdf` | the published NIEHS-10 report (PDF dated 2023-03-20) |

## How it differs from the published NIEHS-10 package
- Genomics: No0 probe filter, curve-fit prefilter, model averaging, BMR 25% RD, R²/ratio-10 category filters
  vs. published full 2,654 probes, Williams + fold 1.5, 8 models lowest AIC, BMR 1 SD, p-value/ratio-40 filters.
- Apical: BMDExpress model averaging vs. published modified EPA BMDS 2.7.0 (lowest AIC + 16 rules, high-dose dropping).
- Not included: individual animal workbooks (supplied separately; byte-identical to CEBS), study-table PDFs,
  QC metadata, PCA inputs, BMDS parameter workbooks.
