# RR-8: NTP Research Report on In Vivo Repeat Dose Biological Potency Study of Triphenyl Phosphate (CAS No. 115-86-6) in Male Sprague Dawley Rats (Hsd: Sprague Dawley SD) (Gavage Studies)

Source: https://cebs.niehs.nih.gov/cebs/data/publication/RR-8 (DOI 10.22427/NTP-DATA-RR-8); GEO GSE121134
Downloaded 2026-10-01: 22 of 22 listed files

## Key facts

- Triphenyl phosphate (TPHP), study C11042, male Sprague Dawley rats, gavage, 0–881 mg/kg (6 groups, 20 animals). NTP Research Report 8, the first report in the series. GEO GSE121134.
- Package layout: one 'Benchmark Dose Analysis' section mixing apical and genomic files, plus 'Summary Tables' numbered Table 1–6 (not NTP I04/PA41 codes); Table 6 is a Top-20 GO BP table.
- Genomics: Affymetrix Rat 230 2.0 microarray (GPL1355, 31,099 probe sets), 20 CEL files, Partek batch correction. BMDExpress 2.20.0148 run 2018-04-12: Williams p<0.05 with 100 permutations, no MTC, fold ≥1.5 → 8 models lowest AIC, BMR factor 1 → GO BP (plain + deduplicated) and individual-gene categories (p≥0.1, BMDU/BMDL≤40). bm2 and JSON agree. Exports include individual PROBE-SET BMDs.
- Apical: modified BMDS v2.7.0, already with high-dose dropping (refits with 0–3 top doses removed); Model Parameters workbook (single sheet, 22 datasets × models), fit reports (2017-12 .doc appendix and 2018-07 docx). No BMDS code package or ReadMe yet.

## Package issues

- 'C11042_Appendix.doc' is actually a .docx.
- Folder/file naming typo 'Microarry_files'.


## Benchmark Dose Analysis

| item | file | size | contents |
|---|---|---|---|
| Appendix | `C11042_Appendix.doc` | 1.3 MB | ⚠ named .doc but is .docx. 42 tables, 11 images; BMD Results for Table 1: SD4 |
| Batch Correction Documentation | `C11042_BatchCorrectionDocumentation.zip` | 24.6 MB | 7 files: After batch correction.jpeg, AP RMA Normalized Data batch corrected - Hyb batch removed.txt, AP RMA Normalized Data with Covariates.txt, Bef … |
| BMD Apical Endpoint Model Fits | `C11042_BMDApicalEndpointModelFits.docx` | 2.3 MB | 66 tables, 16 images; Apical Endpoint Benchmark Dose Modeling Results; Toxicology Benchmark Dose Results |
| BMDExpress Expression Data | `C11042_BMDExpressExpressionData.txt` | 5.0 MB | Chip: Affymetrix Rat Genome 230 2.0 Array; Log Transformation: BASE2; BMDExpress2 Version: BMDExpress 2.20.0148 BETA — table 31101×21 |
| BMDExpress GO Biological Process BMD Results | `C11042_BMDExpressGOBiologicalProcessC11042_BMDResults.txt` | 8.4 MB | Gene Ontology Analyses; GO Category: BP; GO File Creation Date: 03/09/18 — table 6786×98 |
| BMDExpress GO Biological Process Deduplicated BMD Results | `C11042_BMDExpressGOBiologicalProcessDeduplicatedC11042_BMDResults.txt` | 6.3 MB | Gene Ontology Analyses; GO Category: BP; GO File Creation Date: 03/09/18 — table 3936×98 |
| BMDExpress Individual Gene BMD Results | `C11042_BMDExpressIndividualGeneC11042_BMDResults.txt` | 425 KB | Defined Category Analyses; Deduplicate Gene Sets: false; Data Source: TPHP mg_kg — table 1070×97 |
| BMDExpress Individual Probe Set BMD Results | `C11042_BMDExpressIndividualProbeSetC11042_BMDResults.txt` | 1.5 MB | Benchmark Dose Analyses; Data Source: TPHP mg_kg; Work Source: TPHP mg_kg_williams_0.05_NOMTC_foldfilter1.5 — table 1437×124 |
| BMDExpress Prefilter Results | `C11042_BMDExpressPrefilterResults.txt` | 195 KB | Williams Trend Test; Data Source: TPHP mg_kg; Work Source: null — table 1437×13 |
| BMDExpress Project File | `C11042_BMDExpressProjectFile.bm2` | 16.0 MB | BMDExpress project 'TPHP mg_kg.bm2': 1 experiments, 1 BMD results, 3 category analyses |
| BMDExpress Project File (JSON format) | `C11042_BMDExpressProjectFile(JSONformat).json` | 75.0 MB | BMDExpress project 'TPHP mg_kg.bm2': 1 experiments, 1 BMD results, 3 category analyses |
| BMDExpress Software | `C11042_BMDExpressSoftware.exe` | 63.5 MB | .exe |
| GO Biological Process BMD Analysis Results | `C11042_GOBiologicalProcessC11042_BMDAnalysisResults.zip` | 2.7 MB | 4 files: genes2gos.gz, genes2symbols.gz, probe2gene.gz, Readme.txt |
| Individual Gene BMD Analysis Results File | `C11042_IndividualGeneC11042_BMDAnalysisResultsFile.zip` | 260 KB | 3 files: Category_File_Rat_Individual_Gene_Category_File.txt, Probe File_Rat230_2_ProbeSetID_EntrezGeneID_Match.txt, readme.txt |
| Microarray Files | `C11042_Microarry_files.zip` | 47.1 MB | 20 files: 001-051914-MW_(Rat230_2).CEL, 002-051914-MW_(Rat230_2).CEL, 003-051914-MW_(Rat230_2).CEL, 004-051914-MW_(Rat230_2).CEL … |
| Model Parameters | `C11042_Model_Parameters.xlsx` | 285 KB | sheets: Sheet1 (474x35) |

## Summary Tables

| item | file | size | contents |
|---|---|---|---|
| Table 1 - Mean Body Weight Summary | `C11042_Table_1_-_Mean_Body_Weight_Summary.pdf` | 43 KB | 1 pp; Table 1. Mean Body Weight Summary  / Study Day  / (SD)  / 0 mg/kg  / N = 5  |
| Table 2 - Organ Weights Summary | `C11042_Table_2_-_Organ_Weights_Summary.pdf` | 47 KB | 1 pp; Table 2. Organ Weights Summary  / Endpoint 0 mg/kg  / N = 5  / 55 mg/kg  / N = 5  |
| Table 3 - Clinical Chemistry Summary | `C11042_Table_3_-_Clinical_Chemistry_Summary.pdf` | 47 KB | 1 pp; Table 3. Clinical Chemistry Summary  / Endpoint 0 mg/kg  / N = 5  / 55 mg/kg  / N = 5  |
| Table 4 - Hormone and Enzymes Summary | `C11042_Table_4_-_Hormone_and_Enzymes_Summary.pdf` | 107 KB | 1 pp; Table 4. Hormone and Enzymes Summary  / Endpoint 0 mg/kg  / N = 5  / 55 mg/kg  / N = 5  |
| Table 5 - BMD, NOEL and LOEL Summary for Apical Endpoints | `C11042_Table_5_-_BMD_NOEL_and_LOEL_Summary_for_Apical_Endpoints.pdf` | 21 KB | 1 pp; Table 5. BMD, NOEL, and LOEL Summary for Apical Endpoints, Sorted by LOEL or BMDL from  / Low to High  / Table Number Endpoint NOEL (mg/kg) LOEL (mg/k |
| Table 6 - Top 20 GO Biological Process Gene Sets | `C11042_Table6_Top_20_GO_Biological_Process_Gene_Sets.pdf` | 96 KB | 3 pp; Table 6. Top 20 GO Biological Process Gene Sets Ranked by Potency of Perturbation (Sorted by BMD Median)  / Category   / Name  / Input  / Genes/Platfo |
