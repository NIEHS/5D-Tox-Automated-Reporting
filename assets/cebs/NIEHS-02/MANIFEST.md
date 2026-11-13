# NIEHS-02: NIEHS Report on In Vivo Repeat Dose Biological Potency Study of 2-Ethylhexyl Diphenyl Phosphate (CAS No. 1241-94-7) in Male Sprague Dawley Rats (Hsd: Sprague Dawley SD) (Gavage Studies)

Source: https://cebs.niehs.nih.gov/cebs/data/publication/NIEHS-02 (DOI 10.22427/NIEHS-DATA-NIEHS-02)
Downloaded 2026-10-01: 33 of 33 listed files

## Key facts

- 2-Ethylhexyl diphenyl phosphate (EHDP), study C10674, male Sprague Dawley rats, gavage, 0–978.5 mg/kg (6 groups).
- Genomics: Affymetrix Rat Genome 230 2.0 microarray (GPL1355), 31,099 probe sets, raw CEL files, RMA normalisation with Partek hybridisation-batch removal (before/after PCA images + Partek settings screenshot).
- Published analysis (exported results text + JSON): BMDExpress 2.30.0507 run 2021-11-04 on 19 animals — Williams trend p<0.05 (10,000 permutations, no MTC), fold filter 1.5 → BMD with 8 models (Hill, Power, Linear, Poly2, Exp2–5), lowest AIC, BMR 1 SD → GO BP (deduplicated) and individual-gene defined-category analysis (p≥0.1, BMDU/BMDL≤40).
- Apical: modified EPA BMDS v2.7.0 (python bmds 0.11 code package, 16 model-selection rules, Model_Parameters workbook = every model fit, model-fit report docx). Body weight, organ weight, clinical chemistry, hormones.
- Extras: Gene description CSV, GO BP description TSV, PCA files, animal/CEL-file metadata, sample list with processing batches.

## Package issues

- The .bm2 and the JSON are DIFFERENT analyses: the .bm2 is BMDExpress 2.20.0151 from 2018-05-01 with 21 animals and only 100 Williams permutations (no fold-change NOTEL test); the JSON and all exported result files are the 2021 re-run on 19 animals. A consumer ingesting the .bm2 gets a superseded analysis.


## Apical Benchmark Dose Analysis

| item | file | size | contents |
|---|---|---|---|
| BMD Apical Endpoints Model Fits | `BMD_Apical_Endpoints_Model_Fits.docx` | 1.3 MB | 36 tables, 9 images; BMD Results for Table: Body Weight SD4 |
| BMD Model Recommendation Selection Rules | `BMD_Model_Recommendation_Selection_Rules.docx` | 14 KB | 1 tables, 0 images; Benchmark Dose Model Recommendation/Selection Rules for Apical Endpoints |
| BMDs code package | `BMDs_code_package.zip` | 26.0 MB | 228 files: __init__.py, __init__.cpython-36.pyc, anova.cpython-36.pyc, batch.cpython-36.pyc … |
| Model Parameters | `Model_Parameters.xlsx` | 234 KB | sheets: Body Weights (45x57), Organ Weights (111x55), Clinical Chemistry (100x57), Hormone Data (12x57) |
| Read Me | `Read_Me.docx` | 14 KB | 0 tables, 0 images; We modified EPA BMDs v2.7.0 with the following updates: |

## Genomic Benchmark Dose Analysis

| item | file | size | contents |
|---|---|---|---|
| Animal and Microarray Metadata | `Animal_and_Microarray_Metadata.zip` | 115 KB | 2 files: EHDP_Animal_Numbers_and_CEL_File_Names.docx, G822872F Sample List with Batches Noted - 11012017_corrected.xlsx |
| Array platform gene and GO term annotation file | `Array_platform_gene_and_GO_term_annotation_file.zip` | 2.7 MB | 4 files: genes2gos.gz, genes2symbols.gz, probe2gene.gz, Readme.txt |
| Batch Correction Documentation | `Batch_Correction_Documentation.zip` | 21.4 MB | 7 files: After batch correction.jpeg, AP RMA Normalized Data batch corrected - Hyb batch removed.txt, AP RMA Normalized Data with Covariates.txt, Bef … |
| BMDExpress Expression Data | `BMDExpress_Expression_Data.txt` | 4.8 MB | Chip: Affymetrix Rat Genome 230 2.0 Array; Log Transformation: BASE2; BMDExpress2 Version: BMDExpress 2.30.0507 BETA — table 31101×20 |
| BMDExpress GO Biological Process Deduplicated BMD Results | `BMDExpressGOBiologicalProcessDeduplicatedBMDResults.txt` | 4.7 MB | Gene Ontology Analyses; GO Category: BP; GO File Creation Date: 04/15/21 — table 3475×102 |
| BMDExpress Individual Gene BMD Results | `BMDExpress_Individual_Gene_BMD_Results.txt` | 166 KB | Defined Category Analyses; Deduplicate Gene Sets: false; Data Source: EDHP mg_kg — table 734×102 |
| BMDExpress Individual Probe Set BMD Results | `BMDExpress_Individual_Probe_Set_BMD_Results.txt` | 1.0 MB | Benchmark Dose Analyses; Data Source: EDHP mg_kg; Work Source: EDHP mg_kg_williams_0.05_NOMTC_foldfilter1.5 — table 944×126 |
| BMDExpress Prefilter Results | `BMDExpress_Prefilter_Results.txt` | 183 KB | Williams Trend Test; Data Source: EDHP mg_kg; Work Source: null — table 944×19 |
| BMDExpress Project File (bm2 format) | `BMDExpress_Project_File_(bm2_format).bm2` | 12.3 MB | BMDExpress project 'EDHP mg_kg.bm2': 1 experiments, 1 BMD results, 3 category analyses |
| BMDExpress Project File (JSON format) | `BMDExpress_Project_File_(JSON_format).json` | 38.7 MB | BMDExpress project 'EDHP mg_kg.bm2': 1 experiments, 1 BMD results, 2 category analyses |
| BMDExpress Software | `BMDExpress_Software.zip` | 62.7 MB | 1 files: BMDExpress2_2_for_Windows_64bit.exe |
| Gene Description | `Gene_Description.csv` | 24.1 MB | Human Gene Symbol,Rat Gene Symbol,Human Entrez Gene ID,Rat Entrez Gene ID,Human Entrez Gene Summary,Rat Entrez Gene Summary,Human Uniprot ID |
| GO Biological Process Description | `GO_Biological_Process_Description.tsv` | 9.6 MB |  — table 44532×4 |
| Individual Gene BMD Analysis Results File | `Individual_Gene_BMD_Analysis_Results_File.zip` | 260 KB | 3 files: Category_File_Rat_Individual_Gene_Category_File.txt, Probe File_Rat230_2_ProbeSetID_EntrezGeneID_Match.txt, readme.txt |
| Principal Components Analysis Files | `Principal_Components_Analysis_Files.zip` | 2.1 MB | 5 files: EDHP mg_kg.txt, EDHP.png, EDHP_PCA_1_2.tif, EDHP_PCA_1_3.tif … |
| Raw Data CEL Files | `Raw_data_CEL_files.zip` | 45.6 MB | 19 files: 025-052014-MW_(Rat230_2).CEL, 026-052014-MW_(Rat230_2).CEL, 027-052014-MW_(Rat230_2).CEL, 028-052014-MW_(Rat230_2).CEL … |
| Top 10 Genes Ranked by Potency of Perturbation | `Top_10_Genes_Ranked_by_Potency_of_Perturbation.docx` | 74 KB | 1 tables, 0 images; Top 10 Genes Ranked by Potency of Perturbation, Sorted by Benchmark Dose Mediana |
| Top 10 GO Biological Process Gene Sets | `Top_10_GO_Biological_Process_Gene_Sets.docx` | 72 KB | 1 tables, 0 images; Top 10 Gene Ontology Biological Process Gene Sets Ranked by Potency of Perturbation, Sorted by Benchmark Dose Mediana |

## Study Tables

| item | file | size | contents |
|---|---|---|---|
| I04 – Mean Body Weight Summary | `C10674_I04_Mean_Body_Weight_Summary.pdf` | 51 KB | 4 pp; Study Number: C10674 / Test Type: TOX / Route: Oral Gavage / Species/Strain: Rat/Harlan Sprague Dawley / I04: Mean Body Weight Summary / Test Compound |
| I05 – Clinical Observations Summary | `C10674_I05_Clinical_Observations_Summary.pdf` | 32 KB | 3 pp; Study Number: C10674 / Test Type: TOX / Route: Oral Gavage / Species/Strain: Rat/Harlan Sprague Dawley / I05: Clinical Observations Summary / Test Com |
| PA06 – Organ Weights Summary | `C10674_PA06_Organ_Weights_Summary.pdf` | 44 KB | 4 pp; Study Number: C10674 / Test Type: TOX / Route: Oral Gavage / Species/Strain: Rat/Harlan Sprague Dawley / PA06: Organ Weights Summary / Test Compound:  |
| PA41 – Clinical Chemistry Summary | `C10674_PA41_Clinical_Chemistry_Summary.pdf` | 130 KB | 6 pp; Study Number: C10674 / Test Type: TOX / Route: Oral Gavage / Species/Strain: Rat/Harlan Sprague Dawley / PA41: Clinical Chemistry Summary / Test Compo |
| R07 – Hormone Summary | `C10674_R07_Hormone_Summary.pdf` | 35 KB | 4 pp; Study Number: C10674 / Test Type: TOX / Route: Oral Gavage / Species/Strain: Rat/Harlan Sprague Dawley / R07: Hormone Summary / Test Compound: 2-Ethyl |

## Individual Animal Data

| item | file | size | contents |
|---|---|---|---|
| Individual Animal Body Weight Data | `C10674_Individual_Animal_Body_Weight_Data.xlsx` | 10 KB | sheets: Body Weights (75x27) |
| Individual Animal Clinical Chemistry Data | `C10674_Individual_Animal_Clinical_Chemistry_Data.xlsx` | 31 KB | sheets: NTP Clinical Chemistry (373x25) |
| Individual Animal Clinical Observations Data | `C10674_Individual_Animal_Clinical_Observations_Data.xlsx` | 9 KB | sheets: Clinical Observations (68x28) |
| Individual Animal Hormone Data | `C10674_Individual_Animal_Hormone_Data.xlsx` | 7 KB | sheets: Hormone (47x23) |
| Individual Animal Organ Weight Data | `C10674_Individual_Animal_Organ_Weight_Data.xlsx` | 10 KB | sheets: Organ Weights (91x24) |
