# CEBS NIEHS-10 published study data (PFHxSAm, study C20022-01)

Source: https://cebs.niehs.nih.gov/cebs/data/publication/NIEHS-10  (DOI 10.22427/NIEHS-DATA-NIEHS-10)
Downloaded 2026-10-01: all 55 files linked on the page (links.txt). Zips extracted under unzipped/.
GEO GSE183705 is linked from the page but was not downloaded.

## Apical (in vivo)
| files | what |
|---|---|
| C20022-01_Individual_Animal_*.xlsx (7) | per-animal BW, clin chem, clin obs, hematology, hormones, organ wt, tissue conc. BYTE-IDENTICAL to sessions/DTXSID50469320/files |
| C20022-01_I04/I05/PA06/PA41/PA43/PA48/R07_*.pdf (7) | NTP standard summary tables (4–10 pp each) |
| C20022-01_*_Summary.docx (5) | report-style mean±SEM summary tables (BW, organ wt, clin chem, heme, hormone), M+F |
| C20022-01_BMD_BMDL_LOEL_and_NOEL_Summary_...docx | apical BMD1SD/BMDL1SD/LOEL/NOEL table (values match the reference report) |
| C20022-01_Parameter_{Male,Female}_07282021.xlsx | every BMDS model fit per endpoint (BMD/BMDL/BMDU/AIC/p-values/logic bin/recommended) |
| C20022-01_Appendix_{Male,Female}_07282021.docx | per-endpoint BMDS v2.7.0 model-fit reports with plots |
| C20022-01_Benchmark_Dose_Model_Recommendation_Selection_Rules...docx | 16 model-selection rules |
| C20022-01_ReadME.docx | modifications made to EPA BMDS v2.7.0 |
| C20022-01_bmds.zip | python `bmds` 0.11.0 + Windows BMDS 2.31/2.40/2.60/2.70 executables (the apical BMD engine) |

## Transcriptomics (TempO-Seq S1500+ rat; liver + kidney, M+F)
| files | what |
|---|---|
| C20022-01_{Liver,Kidney}_PFHxSAm_{Male,Female}.txt (4) | normalized log2 expression, 2654 probes × 44–45 animals (BMDExpress 2.30.0485, 2020-11-18). = PCA inputs |
| C20022-01_{Liver,Kidney}_PCA.zip | copies of the 4 expression files + 2D and 3D PCA figure docx |
| C20022-01_EPA_PFAS_..._Traditional.bm2 / _JSON.zip | full BMDExpress 2.30.0507 project (2021-02-12). 16 experiments = 4 chemicals (PFHxSAm, 2,3-benzofluorene, 6:1 FTOH, 10:2 FTOH) × 2 tissues × 2 sexes. Williams p0.05 NOMTC fc1.5 → BMD (8 models, lowest AIC, BMR 1 SD) → GENE + GO_BP categories. PFHxSAm expression == the .txt files exactly |
| C20022-01_BMDExpress_Prefilter_Results_*.txt (4) | Williams prefilter exports |
| C20022-01_*_williams_..._GENE_...txt / _GO_BP_..._deduplicate.txt (8) | gene-level and GO BP category exports |
| C20022-01_{Liver,Kidney}_Top_10_*.docx (4) | report tables: top 10 genes / GO BP gene sets by BMD median |
| C20022-01_Animal_and_FASTQ_Metadata.zip | animal↔FASTQ table (= report Appendix B), TempO-Seq sample sheet (904 samples, 4 chemicals), per-sample QC with removal reasons |
| C20022-01_Functional_Classification_..._GPL1355.zip, C20022-01_Individual_Gene_..._GPL1355.zip | annotation files for Affymetrix GPL1355 (Rat 230 2.0) — NOT the S1500 platform used here (no S1500 probe IDs) |
| C20022-01_Software.zip | BMDExpress 2.2 Windows installer (the analysis itself used 2.30) |
