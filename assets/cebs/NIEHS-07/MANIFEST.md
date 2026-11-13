# NIEHS-07: NIEHS Report on the In Vivo Repeat Dose Biological Potency Study of 6:1 Fluorotelomer Alcohol (CASRN 375-82-6) in Sprague Dawley (Hsd:Sprague Dawley® SD®) Rats (Gavage Studies)

Source: https://cebs.niehs.nih.gov/cebs/data/publication/NIEHS-07 (DOI 10.22427/NIEHS-DATA-NIEHS-07); GEO GSE183705
Downloaded 2026-10-01: 55 of 55 listed files

## Key facts

- 6:1 Fluorotelomer alcohol (6:1 FTOH), study C20027-01, male and female Sprague Dawley rats, gavage, 0–1000 mg/kg (9–10 groups), liver + kidney. GEO GSE183705 (shared by the four PFAS reports).
- Genomics platform switches to TempO-Seq S1500+ rat (BioSpyder), 2,654 probes, normalised log2 counts (RPM + 1, log2). Expression files BMDExpress 2.30.0485 (2020-11-18).
- The BMDExpress project is ONE shared PFAS project (byte-identical across NIEHS-07, -08, -09 and -10): 16 experiments = 4 chemicals × liver/kidney × sex, BMDExpress 2.30.0507 run 2021-02-12. Williams p<0.05 (10,000 perm, no MTC) + fold 1.5 → 8-model lowest-AIC BMD, BMR 1 SD → GENE (p≥0.1, ratio≤40, fold change≥2) and GO BP (deduplicated) categories.
- Apical: modified BMDS v2.7.0, with high-dose dropping up to 5 doses (each endpoint refit with top doses removed; the recommended fit may come from a dropped-dose run). Adds hematology and tissue concentration (PA43, PA48). Per-sex Parameter workbooks and model-fit appendices dated 2021-07-28.
- QC: TempO-Seq sample sheet and per-sample QC with removal reasons (kidney 'overflow plate' effects, PCA outliers); animal↔FASTQ table; 2D and 3D PCA figures.

## Package issues

- The bundled GO annotation zips are labelled for Affymetrix GPL1355 (carried over from the microarray-era packages) and contain no S1500 probe IDs — not the annotation used for this TempO-Seq analysis.
- The shared project contains the other three chemicals; a consumer must filter to this study's experiments.


## Apical Benchmark Dose Analysis

| item | file | size | contents |
|---|---|---|---|
| BMD, NOEL and LOEL Summary for Apical Endpoints | `C20027-01_BMD_BMDL_LOEL_and_NOEL_Summary_for_Apical_Endpoints_Sorted_by_BMD_LOEL_from_Low_to_High.docx` | 16 KB | 1 tables, 0 images; BMD, BMDL, LOEL, and NOEL Summary for Apical Endpoints, Sorted by BMD/LOEL from Low to High |
| BMD Model Recommendation Selection Rules | `C20027-01_Benchmark_Dose_Model_Recommendation_Selection_Rules_for_Apical_Endpoints.docx` | 14 KB | 1 tables, 0 images; Benchmark Dose Model Recommendation/Selection Rules for Apical Endpoints |
| BMDs code package | `C20027-01_bmds.zip` | 26.0 MB | 228 files: __init__.py, __init__.cpython-36.pyc, anova.cpython-36.pyc, batch.cpython-36.pyc … |
| Clinical Chemistry Summary | `C20027-01_Clinical_Chemistry_Summary.docx` | 17 KB | 2 tables, 0 images; Male Clinical Chemistry Summary |
| Female BMD Apical Endpoints Model Fits | `C20027-01_Appendix_Female_07282021.docx` | 1.3 MB | 42 tables, 9 images; Female BMD Results for Table: Liver Weight Absolute |
| Female Model Parameters | `C20027-01_Parameter_Female_07282021.xlsx` | 791 KB | sheets: Organ Weights (225x53), Clinical Chemistry (309x55), Hematology (211x55), Hormone Data (141x55) |
| Hematology Summary | `C20027-01_Hematology_Data_Summary.docx` | 16 KB | 2 tables, 0 images; Male Hematology Data Summary |
| Hormone and Enzymes Summary | `C20027-01_Hormone_Summary.docx` | 15 KB | 2 tables, 0 images; Male Hormone Summary |
| Male BMD Apical Endpoints Model Fits | `C20027-01_Appendix_Male_07282021.docx` | 2.4 MB | 69 tables, 17 images; Male BMD Results for Table: Body Weight Gain |
| Male Model Parameters | `C20027-01_Parameter_Male_07282021.xlsx` | 1.0 MB | sheets: Body Weights (99x54), Organ Weights (155x53), Clinical Chemistry (491x55), Hematology (295x55), Hormone Data (225x55) |
| Mean Body Weight Summary | `C20027-01_Mean_Body_Weight_Summary.docx` | 15 KB | 2 tables, 0 images; Male Mean Body Weight Summary |
| Organ Weights Summary | `C20027-01_Organ_Weights_Summary.docx` | 16 KB | 2 tables, 0 images; Male Organ Weights Summary |
| Read Me | `C20027-01_ReadME.docx` | 14 KB | 0 tables, 0 images; We modified EPA BMDs v2.7.0 with the following updates: |

## Genomic Benchmark Dose Analysis

| item | file | size | contents |
|---|---|---|---|
| Animal and Fastaq Metadata | `C20027-01_Animal_and_FASTQ_Metadata.zip` | 250 KB | 3 files: C20022-01_Animal_Numbers_and_FASTQ_Data_File_Names.docx, per_sample_summary_with reason noted for sample removal.xlsx, TempO-QC-Metadata-T05 |
| BMDExpress Expression Data_Kidney_Female | `C20027-01_Kidney_6-1_FTOH_Female.txt` | 1.0 MB | Chip: BioSpyder S1500_Rat; Log Transformation: BASE2; BMDExpress2 Version: BMDExpress 2.30.0485 BETA — table 2656×46 |
| BMDExpress Expression Data_Kidney_Male | `C20027-01_Kidney_6-1_FTOH_Male.txt` | 1.0 MB | Chip: BioSpyder S1500_Rat; Log Transformation: BASE2; BMDExpress2 Version: BMDExpress 2.30.0485 BETA — table 2656×46 |
| BMDExpress Expression Data_Liver_Female | `C20027-01_Liver_6-1_FTOH_Female.txt` | 1.2 MB | Chip: BioSpyder S1500_Rat; Log Transformation: BASE2; BMDExpress2 Version: BMDExpress 2.30.0485 BETA — table 2656×55 |
| BMDExpress Expression Data_Liver_Male | `C20027-01_Liver_6-1_FTOH_Male.txt` | 1.1 MB | Chip: BioSpyder S1500_Rat; Log Transformation: BASE2; BMDExpress2 Version: BMDExpress 2.30.0485 BETA — table 2656×50 |
| BMDExpress GO Biological Process Deduplicated BMD Results_Kidney_Female | `C20027-01_Kidney_6-1_FTOH_Female_williams_0.05_NOMTC_foldfilter1.5_BMD_S1500_Plus_Rat_GO_BP_true_true_pval0.1_ratio40_conf0.5_deduplicate.txt` | 2.3 MB | Gene Ontology Analyses; GO Category: BP; GO File Creation Date: 07/15/20 — table 1962×102 |
| BMDExpress GO Biological Process Deduplicated BMD Results_Kidney_Male | `C20027-01_Kidney_6-1_FTOH_Male_williams_0.05_NOMTC_foldfilter1.5_BMD_S1500_Plus_Rat_GO_BP_true_true_pval0.1_ratio40_conf0.5_deduplicate.txt` | 3.3 MB | Gene Ontology Analyses; GO Category: BP; GO File Creation Date: 07/15/20 — table 2618×102 |
| BMDExpress GO Biological Process Deduplicated BMD Results_Liver_Female | `C20027-01_Liver_6-1_FTOH_Female_williams_0.05_NOMTC_foldfilter1.5_BMD_S1500_Plus_Rat_GO_BP_true_true_pval0.1_ratio40_conf0.5_deduplicate.txt` | 4.2 MB | Gene Ontology Analyses; GO Category: BP; GO File Creation Date: 07/15/20 — table 2790×102 |
| BMDExpress GO Biological Process Deduplicated BMD Results_Liver_Male | `C20027-01_Liver_6-1_FTOH_Male_williams_0.05_NOMTC_foldfilter1.5_BMD_S1500_Plus_Rat_GO_BP_true_true_pval0.1_ratio40_conf0.5_deduplicate.txt` | 5.2 MB | Gene Ontology Analyses; GO Category: BP; GO File Creation Date: 07/15/20 — table 3534×102 |
| BMDExpress Individual Gene BMD Results_Kidney_Female | `C20027-01_Kidney_6-1_FTOH_Female_williams_0.05_NOMTC_foldfilter1.5_BMD_S1500_Plus_Rat_GENE_true_true_pval0.1_ratio40_foldchange2_conf0.5.txt` | 77 KB | Gene Level Analyses; Gene Annotation File Creation Date: 07/15/20; Deduplicate Gene Sets: false — table 288×102 |
| BMDExpress Individual Gene BMD Results_Kidney_Male | `C20027-01_Kidney_6-1_FTOH_Male_williams_0.05_NOMTC_foldfilter1.5_BMD_S1500_Plus_Rat_GENE_true_true_pval0.1_ratio40_foldchange2_conf0.5.txt` | 95 KB | Gene Level Analyses; Gene Annotation File Creation Date: 07/15/20; Deduplicate Gene Sets: false — table 351×102 |
| BMDExpress Individual Gene BMD Results_Liver_Female | `C20027-01_Liver_6-1_FTOH_Female_williams_0.05_NOMTC_foldfilter1.5_BMD_S1500_Plus_Rat_GENE_true_true_pval0.1_ratio40_foldchange2_conf0.5.txt` | 145 KB | Gene Level Analyses; Gene Annotation File Creation Date: 07/15/20; Deduplicate Gene Sets: false — table 488×102 |
| BMDExpress Individual Gene BMD Results_Liver_Male | `C20027-01_Liver_6-1_FTOH_Male_williams_0.05_NOMTC_foldfilter1.5_BMD_S1500_Plus_Rat_GENE_true_true_pval0.1_ratio40_foldchange2_conf0.5.txt` | 191 KB | Gene Level Analyses; Gene Annotation File Creation Date: 07/15/20; Deduplicate Gene Sets: false — table 720×102 |
| BMDExpress Prefilter Results_ Kidney _Female | `C20027-01_BMDExpress_Prefilter_Results_Kidney_Female.txt` | 79 KB | Williams Trend Test; Data Source: Kidney_6-1 FTOH_Female; Work Source: null — table 275×27 |
| BMDExpress Prefilter Results_ Kidney _Male | `C20027-01_BMDExpress_Prefilter_Results_Kidney_Male.txt` | 92 KB | Williams Trend Test; Data Source: Kidney_6-1 FTOH_Male; Work Source: null — table 345×25 |
| BMDExpress Prefilter Results_ Liver _Female | `C20027-01_BMDExpress_Prefilter_Results_Liver_Female.txt` | 136 KB | Williams Trend Test; Data Source: Liver_6-1 FTOH_Female; Work Source: null — table 473×27 |
| BMDExpress Prefilter Results_ Liver _Male | `C20027-01_BMDExpress_Prefilter_Results_Liver_Male.txt` | 186 KB | Williams Trend Test; Data Source: Liver_6-1 FTOH_Male; Work Source: null — table 694×25 |
| BMDExpress Project File (bm2 format) | `C20027-01_EPA_PFAS_Kidney_Overflow_plate_removed_S1500_Plus_Analysis_Traditional.bm2` | 38.6 MB | BMDExpress project 'EPA PFAS Kidney Overflow plate removed-S1500+-Auerbach Analysis Traditional-for publication_to Jennifer.bm2': 16 experiments, 16 BMD results, 32 category analyses |
| BMDExpress Project File (JSON format) | `C20027-01_EPA_PFAS_Kidney_Overflow_plate_removed_S1500_Plus_Analysis_Traditional_JSON.zip` | 21.6 MB | 1 files: EPA PFAS Kidney Overflow plate removed-S1500+-Auerbach Analysis Traditional-for publication_to Jennifer.json |
| BMDExpress Software | `C20027-01_Software.zip` | 62.7 MB | 1 files: BMDExpress2_2_for_Windows_64bit.exe |
| GO Biological Process BMD Analysis Results | `C20027-01_Functional_Classification_Annotation_Files_for_GO_Biological_Process_Analysis_of_Array_Platform_GPL1355.zip` | 2.7 MB | 4 files: genes2gos.gz, genes2symbols.gz, probe2gene.gz, Readme.txt |
| Individual Gene BMD Analysis Results File | `C20027-01_Individual_Gene_Defined_Category_Files_for_Gene_Level_BMD_Analysis_of_Array_Platform_GPL1355.zip` | 260 KB | 3 files: Category_File_Rat_Individual_Gene_Category_File.txt, Probe File_Rat230_2_ProbeSetID_EntrezGeneID_Match.txt, readme.txt |
| Kidney Principal Components Analysis Files | `C20027-01_Kidney_PCA.zip` | 1.7 MB | 4 files: C20027-01_Kidney_Combined_Three-dimensional_Principle_Components_Analysis_(PCA).docx, C20027-01_Kidney_Two-dimensional_Principle_Components_ |
| Liver Principal Components Analysis Files | `C20027-01_Liver_PCA.zip` | 1.7 MB | 4 files: C20027-01_Liver_Combined_Three-dimensional_Principle_Components_Analysis_(PCA).docx, C20027-01_Liver_Two-dimensional_Principle_Components_An |
| Top 10 Genes Ranked by Potency of Perturbation_Kidney | `C20027-01_Kidney_Top_10_Genes_Ranked_by_Potency_of_Perturbation_Sorted_by_BMD_Median.docx` | 22 KB | 2 tables, 0 images; Male Kidney Top 10 Genes Ranked by Potency of Perturbation (Sorted by BMD Median) |
| Top 10 Genes Ranked by Potency of Perturbation_Liver | `C20027-01_Liver_Top_10_Genes_Ranked_by_Potency_of_Perturbation_Sorted_by_BMD_Median.docx` | 24 KB | 2 tables, 0 images; Male Liver Top 10 Genes Ranked by Potency of Perturbation (Sorted by BMD Median) |
| Top 10 GO Biological Process Gene Sets_Kidney | `C20027-01_Kidney_Top_10_GO_Biological_Process_Gene_Sets_Ranked_by_Potency_of_Perturbation_Sorted_by_BMD_Median.docx` | 20 KB | 2 tables, 0 images; Male Kidney Top 10 GO Biological Process Gene Sets Ranked by Potency of Perturbation (Sorted by BMD Median) |
| Top 10 GO Biological Process Gene Sets_Liver | `C20027-01_Liver_Top_10_GO_Biological_Process_Gene_Sets_Ranked_by_Potency_of_Perturbation_Sorted_by_BMD_Median.docx` | 20 KB | 2 tables, 0 images; Male Liver Top 10 GO Biological Process Gene Sets Ranked by Potency of Perturbation (Sorted by BMD Median) |

## Study Tables

| item | file | size | contents |
|---|---|---|---|
| I04 – Mean_Body_Weight_Summary | `C20027-01_I04_–_Mean_Body_Weight_Summary.pdf` | 136 KB | 10 pp; Study Number: C20027-01 / Test Type: TOX / Route: Oral Gavage / Species/Strain: Rat/Sprague Dawley / I04: Mean Body Weight Summary / Test Compound: 6: |
| I05 – Clinical_Observations_Summary | `C20027-01_I05_–_Clinical_Observations_Summary.pdf` | 200 KB | 8 pp; Study Number: C20027-01 / Test Type: TOX / Route: Oral Gavage / Species/Strain: Rat/Sprague Dawley / I05: Clinical Observations Summary / Test Compoun |
| PA06 – Organ_Weights_Summary | `C20027-01_PA06_–_Organ_Weights_Summary.pdf` | 107 KB | 6 pp; Study Number: C20027-01 / Test Type: TOX / Route: Oral Gavage / Species/Strain: Rat/Sprague Dawley / PA06: Organ Weights Summary / Test Compound: 6:1  |
| PA41 – Clinical_Chemistry_Summary | `C20027-01_PA41_–_Clinical_Chemistry_Summary.pdf` | 355 KB | 10 pp; Study Number: C20027-01 / Test Type: TOX / Route: Oral Gavage / Species/Strain: Rat/Sprague Dawley / PA41: Clinical Chemistry Summary / Test Compound: |
| PA43 - Hematology Summary | `C20027-01_-_PA43_–_Hematology_Summary.pdf` | 430 KB | 14 pp; Study Number: C20027-01 / Test Type: TOX / Route: Oral Gavage / Species/Strain: Rat/Sprague Dawley / PA43: Hematology Summary / Test Compound: 6:1 Flu |
| PA48 - Summary of Tissue Concentration | `C20027-01_-_PA48_-_Summary_of_Tissue_Concentration.pdf` | 32 KB | 4 pp; Study Number: C20027-01 / Test Type: TOX / Route: Oral Gavage / Species/Strain: Rat/Sprague Dawley / PA48: Summary of Tissue Concentration / Test Comp |
| R07 – Hormone_Summary | `C20027-01_R07_–_Hormone_Summary.pdf` | 78 KB | 8 pp; Study Number: C20027-01 / Test Type: TOX / Route: Oral Gavage / Species/Strain: Rat/Sprague Dawley / R07: Hormone Summary / Test Compound: 6:1 Fluorot |

## Individual Animal Data

| item | file | size | contents |
|---|---|---|---|
| Individual Animal Body Weight Data | `C20027-01_Individual_Animal_Body_Weight_Data.xlsx` | 13 KB | sheets: Key to Column Labels (9x4), Data (245x8) |
| Individual Animal Clinical Chemistry Data | `C20027-01_Individual_Animal_Clinical_Chemistry_Data.xlsx` | 16 KB | sheets: Key to Column Labels (26x4), Data (107x23) |
| Individual Animal Clinical Observations Data | `C20027-01_Individual_Animal_Clinical_Observations_Data.xlsx` | 28 KB | sheets: Key to Column Labels (11x4), Data (773x10) |
| Individual Animal Hematology Data | `C20027-01_Individual_Animal_Hematology_Data.xlsx` | 17 KB | sheets: Key to Column Labels (26x4), Data (107x23) |
| Individual Animal Hormone Data | `C20027-01_Individual_Animal_Hormone_Data.xlsx` | 9 KB | sheets: Key to Column Labels (10x4), Data (95x9) |
| Individual Animal Organ Weight Data | `C20027-01_Individual_Animal_Organ_Weight_Data.xlsx` | 10 KB | sheets: Key to Column Labels (12x4), Data (111x11) |
| Individual Animal Tissue Concentration Data | `C20027-01_Individual_Animal_Tissue_Concentration_Data.xlsx` | 6 KB | sheets: Key to Column Labels (14x4), Data (25x13) |
