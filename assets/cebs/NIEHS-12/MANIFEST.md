# NIEHS-12: NIEHS Report on the In Vivo Repeat Dose Biological Potency Study of 1,2-Dichlorobenzene (CASRN 95-50-1) in Sprague Dawley (Hsd:Sprague Dawley® SD®) Rats and B6D2F1/Crl Mice via Whole Body Respiratory Exposure

Source: https://cebs.niehs.nih.gov/cebs/data/publication/NIEHS-12 (DOI 10.22427/NIEHS-DATA-NIEHS-12)
Downloaded 2026-10-01: 141 of 141 listed files

## Key facts

- 1,2-Dichlorobenzene (1,2-DCB), studies 108020006 (rats) / 108020007 (mice): female Sprague Dawley rats (0–500 ppm, 7 groups) and B6D2F1/Crl mice (0–250 ppm, 6 groups), whole-body INHALATION; five tissues (heart, kidney, liver, lung, ovary). DTT study numbering; a 15-page Materials and Methods PDF is in the package.
- Genomics (BMDExpress 3.20.0119, 2025-04/05; documented in Materials_and_Methods.pdf): attenuation-adjusted read counts → RPM → log2; probes with a zero count in ANY sample removed ('No0': rat 1,864–2,072 probes kept); Williams p<0.05 (10,000 perm, no fold filter) → curve-fit prefilter (Hill/Power/Linear/Exp3/Exp5, BMR 2 SD) → ToxicR Laplace model averaging (Hill, Power, Exp3, Exp5), BMR 25% relative deviation, step-function threshold 0.5 → GO BP + gene categories (R²≥0.6, BMD/BMDL≤10, gene sets 40–500).
- Apical BMDs move into BMDExpress (non-genomic .bm2 per species, 3.20.0119/0129): endpoints pre-screened for a significant trend plus a significant pairwise effect, then ToxicR Laplace model averaging, BMR 1 SD, 'generic' platform, defined-category file of 5-day endpoints. No BMDS workbook.
- New artefacts: attenuation-adjusted raw read counts, TempO-Seq S1500 v1.2 rat and mouse manifests, per-tissue One-way ANOVA / Curve Fit / BMD exports, eFDR synthetic-null analyses (20 null data sets per tissue per species, as .bm2), transcriptomics QC reports, animal-removal workbooks, theoretical inhaled dose. Report tables are PDFs (Top 10 genes/GO per tissue, most potent GO per tissue).
- 'Analysis Pipeline Evaluation' (identical in NIEHS-12 and -13; updated February 2026): compares the proposed DTT tBMD method with the US EPA ETAP method across 20 five-day gavage studies (54 chemical×replicate×tissue data sets incl. BPAF, triclosan, PFOA, furan, BDCA, TBBPA). DTT method (BMDExpress 3.20.0141, Dec 2025): No0 → Williams p<0.05 (the 1.25 fold filter removed in the Feb 2026 update) → curve-fit prefilter at **1.581 SD** → ToxicR MA, BMR 25% RD → gene + GO BP; GO BP BMD = 5th-percentile gene BMD; tBMD = lowest GO BP across liver and kidney. EPA method (BMDExpress 2.30.0516): Williams + fold 1.5 → 8 models, BMR 1.349 SD, nested chi-square then lowest AIC → GO BP. Conclusion: the DTT method performs slightly better and replicates better.

## Package issues

- The rat genomic project's top-level curve-fit prefilter list holds the MOUSE results (mouse_2D_*); the rat BMD results reference their own embedded rat prefilters.
- Mouse genomic experiments are not named '_No0' even though the methods describe the same zero-count filter.


## Material and Methods

| item | file | size | contents |
|---|---|---|---|
| Materials and Methods | `Materials_and_Methods.pdf` | 354 KB | 15 pp; Materials and Methods for the  / In Vivo Repeat Dose Biological Potency Studies  / of 1,2‑Dichlorobenzene (CASRN 95-50-1) in  / Female Sprague Dawley  |

## Theoretical Inhaled Dose

| item | file | size | contents |
|---|---|---|---|
| Theoretical Inhaled Dose | `Theoretical_Inhaled_Dose.pdf` | 170 KB | 1 pp; 1,2-Dichlorobenzene  / Theoretical Inhaled Dose  / To provide information relevant for route-to-route extrapolation, to allow for comparison  / betwee |

## Apical Benchmark Dose Analysis - Rats

| item | file | size | contents |
|---|---|---|---|
| BMD, NOEL and LOEL Summary for Apical Endpoints | `108020006_BMD_NOEL_and_LOEL_Summary_for_Apical_Endpoints_Rats.pdf` | 404 KB | 1 pp; BMD, BMDL, LOEL, and NOEL Summary for Apical Endpoints, Sorted by BMD/LOEL from Low to High / DTTID: 108-020-006-000-7  / Study Number: 108020006  / S |
| BMDExpress Project File Rat Apical (bm2 format) | `108020006_2D_Rat_NonGenomic_Rats.bm2` | 47 KB | BMDExpress project '2D_RatNonGenomicBMD.bm2': 2 experiments, 2 BMD results, 2 category analyses |
| Clinical Chemistry Summary | `108020006_Clinical_Chemistry_Summary_Rats.pdf` | 91 KB | 1 pp; PA41-BMD: Clinical Chemistry Summary / DTTID: 108-020-006-000-7 TestCompound: 1,2-Dichlorobenzene Date: 19 Jun 2025 / Study Number: 108020006 CAS Numb |
| Mean Body Weight Summary | `108020006_Mean_Body_Weight_Summary_Rats.pdf` | 71 KB | 1 pp; I04-BMD: Mean Body Weight Summary / DTTID: 108-020-006-000-7 TestCompound: 1,2-Dichlorobenzene Date: 19 Jun 2025 / Study Number: 108020006 CAS Number: |
| Organ Weights Summary | `108020006_Organ_Weights_Summary_Rats.pdf` | 58 KB | 1 pp; PA06-BMD: Organ Weights Summary / DTTID: 108-020-006-000-7 TestCompound: 1,2-Dichlorobenzene Date: 19 Jun 2025 / Study Number: 108020006 CAS Number: 9 |

## Genomic Benchmark Dose Analysis - Rats

| item | file | size | contents |
|---|---|---|---|
| All Organ Principal Components Analysis Files | `108020006_All_Organ_Principal_Components_Analysis_Files_Rats.zip` | 932 KB | 5 files: PCA_108020006_(2DCB-RAT-OV).pdf, PCA_108020006_(2DCB-RAT-HE).pdf, PCA_108020006_(2DCB-RAT-KI).pdf, PCA_108020006_(2DCB-RAT-LI).pdf … |
| Animal and Fastaq Metadata | `108020006_Animal_and_Fastaq_Metadata_Rats.pdf` | 134 KB | 5 pp; DTTID: 108-020-006-000-7  / Study Number: 108020006  / Study Type: 5-Day Toxicity  / Species/Strain: Rat HSD:Sprague Dawley SD / Animal Numbers and FA |
| Attenuation-adjusted Raw Read Counts Rat Study | `Attenuation-adjusted_Raw_Read_Counts_Rat_Study.zip` | 2.8 MB | 2 files: Attenuation-adjusted Raw Read Counts Rat 1,2-DCB Study.xlsx, 1,2-DCB-Rat_FASTQ.xlsx |
| Benchmark Dose Analysis Rat Heart | `108020006_Benchmark_Dose_Analysis_Rat_Heart.txt` | 328 KB | Benchmark Dose Analyses; Data Source: rat_2D_HE_No0; Work Source: rat_2D_HE_No0_curvefitprefilter_nofoldfilter — table 117×197 |
| Benchmark Dose Analysis Rat Kidney | `108020006_Benchmark_Dose_Analysis_Kidney_Rats.txt` | 569 KB | Benchmark Dose Analyses; Data Source: rat_2D_KI_No0; Work Source: rat_2D_KI_No0_curvefitprefilter_nofoldfilter — table 203×197 |
| Benchmark Dose Analysis Rat Liver | `108020006_Benchmark_Dose_Analysis_Liver_Rats.txt` | 2.9 MB | Benchmark Dose Analyses; Data Source: rat_2D_LI_No0; Work Source: rat_2D_LI_No0_curvefitprefilter_nofoldfilter — table 1063×197 |
| Benchmark Dose Analysis Rat Lung | `108020006_Benchmark_Dose_Analysis_Lung_Rats.txt` | 413 KB | Benchmark Dose Analyses; Data Source: rat_2D_LU_No0; Work Source: rat_2D_LU_No0_curvefitprefilter_nofoldfilter — table 148×197 |
| Benchmark Dose Analysis Rat Ovary | `108020006_Benchmark_Dose_Analysis_Ovary_Rats.txt` | 221 KB | Benchmark Dose Analyses; Data Source: rat_2D_OV_No0; Work Source: rat_2D_OV_No0_curvefitprefilter_nofoldfilter — table 79×197 |
| BMDExpress Expression Data Heart | `108020006_BMDExpress_Expression_Data_Heart_Rats.txt` | 1.2 MB |  — table 1869×41 |
| BMDExpress Expression Data Kidney | `108020006_BMDExpress_Expression_Data_Kidney_Rats.txt` | 1.3 MB |  — table 2032×40 |
| BMDExpress Expression Data Liver | `108020006_BMDExpress_Expression_Data_Liver_Rats.txt` | 1.2 MB |  — table 1866×41 |
| BMDExpress Expression Data Lung | `108020006_BMDExpress_Expression_Data_Lung_Rats.txt` | 1.3 MB |  — table 2071×40 |
| BMDExpress Expression Data Ovary | `108020006_BMDExpress_Expression_Data_Ovary_Rats.txt` | 1.4 MB |  — table 2074×41 |
| BMDExpress GO Biological Process BMD Results Rat Heart | `108020006_BMDExpress_GO_Biological_Process_BMD_Results_Rat_Heart.txt` | 612 KB | Filter information:; Genes That Passed All Filters BETWEEN [3, 2147483647]; Percentage BETWEEN [5.0, Infinity] — table 273×115 |
| BMDExpress GO Biological Process BMD Results Rat Kidney | `108020006_BMDExpress_GO_Biological_Process_BMD_Results_Kidney_Rats.txt` | 1.6 MB | Filter information:; Genes That Passed All Filters BETWEEN [3, 2147483647]; Percentage BETWEEN [5.0, Infinity] — table 642×115 |
| BMDExpress GO Biological Process BMD Results Rat Liver | `108020006_BMDExpress_GO_Biological_Process_BMD_Results_Liver_Rats.txt` | 7.0 MB | Filter information:; Genes That Passed All Filters BETWEEN [-2147483648, 2147483647]; Percentage BETWEEN [-Infinity, Infinity] — table 951×115 |
| BMDExpress GO Biological Process BMD Results Rat Lung | `108020006_BMDExpress_GO_Biological_Process_BMD_Results_Lung_Rats.txt` | 622 KB | Filter information:; Genes That Passed All Filters BETWEEN [3, 2147483647]; Percentage BETWEEN [5.0, Infinity] — table 287×115 |
| BMDExpress GO Biological Process BMD Results Rat Ovary | `108020006_BMDExpress_GO_Biological_Process_BMD_Results_Ovary_Rats.txt` | 165 KB | Filter information:; Genes That Passed All Filters BETWEEN [3, 2147483647]; Percentage BETWEEN [5.0, Infinity] — table 100×115 |
| BMDExpress Individual Gene BMD Results Rat Heart | `108020006_BMDExpress_Individual_Gene_BMD_Results_Rat_Heart.txt` | 120 KB | Filter information:; Genes That Passed All Filters BETWEEN [1, 2147483647]; Gene Level Analyses — table 109×114 |
| BMDExpress Individual Gene BMD Results Rat Kidney | `108020006_BMDExpress_Individual_Gene_BMD_Results_Kidney_Rats.txt` | 184 KB | Filter information:; Genes That Passed All Filters BETWEEN [1, 2147483647]; Gene Level Analyses — table 171×114 |
| BMDExpress Individual Gene BMD Results Rat Liver | `108020006_BMDExpress_Individual_Gene_BMD_Results_Liver_Rats.txt` | 1.1 MB | Filter information:; Genes That Passed All Filters BETWEEN [1, 2147483647]; Gene Level Analyses — table 1047×114 |
| BMDExpress Individual Gene BMD Results Rat Lung | `108020006_BMDExpress_Individual_Gene_BMD_Results_Lung_Rats.txt` | 140 KB | Filter information:; Genes That Passed All Filters BETWEEN [1, 2147483647]; Gene Level Analyses — table 129×114 |
| BMDExpress Individual Gene BMD Results Rat Ovary | `108020006_BMDExpress_Individual_Gene_BMD_Results_Ovary_Rats.txt` | 68 KB | Filter information:; Genes That Passed All Filters BETWEEN [1, 2147483647]; Gene Level Analyses — table 61×114 |
| BMDExpress Project File Rat Genomic (bm2 format) | `108020006_2D_Genomic_Rats.bm2` | 16.8 MB | BMDExpress project 'DCB Analysis-2025-No0-1,2-DCB-Rat.bm2': 5 experiments, 5 BMD results, 10 category analyses |
| BMDExpress_Project_File_Rat_Genomic_(JSON_format) | `BMDExpress_Project_File_Rat_Genomic_(JSON_format).json` | 88.8 MB | BMDExpress project 'DCB Analysis-2025-No0-1,2-DCB-Rat.bm2': 5 experiments, 5 BMD results, 10 category analyses |
| Curve Fit Rat Heart | `108020006_Curve_Fit_Heart_Rats.txt` | 27 KB | Curve Fit Prefilter; Data Source: rat_2D_HE_No0_williams_0.05_NOMTC_nofoldfilter; Work Source: rat_2D_HE_No0 — table 117×23 |
| Curve Fit Rat Kidney | `108020006_Curve_Fit_Kidney_Rats.txt` | 45 KB | Curve Fit Prefilter; Data Source: rat_2D_KI_No0_williams_0.05_NOMTC_nofoldfilter; Work Source: rat_2D_KI_No0 — table 203×23 |
| Curve Fit Rat Liver | `108020006_Curve_Fit_Liver_Rats.txt` | 231 KB | Curve Fit Prefilter; Data Source: rat_2D_LI_No0_williams_0.05_NOMTC_nofoldfilter; Work Source: rat_2D_LI_No0 — table 1063×23 |
| Curve Fit Rat Lung | `108020006_Curve_Fit_Lung_Rats.txt` | 33 KB | Curve Fit Prefilter; Data Source: rat_2D_LU_No0_williams_0.05_NOMTC_nofoldfilter; Work Source: rat_2D_LU_No0 — table 148×23 |
| Curve Fit Rat Ovary | `108020006_Curve_Fit_Rat_Ovary.txt` | 18 KB | Curve Fit Prefilter; Data Source: rat_2D_OV_No0_williams_0.05_NOMTC_nofoldfilter; Work Source: rat_2D_OV_No0 — table 79×23 |
| Most Potent GO Biological Process In Each Tissue | `108020006_Most_Potent_GO_Biological_Process_In_Each_Tissue_Rats.pdf` | 179 KB | 1 pp; Liver GO:0006805 xenobiotic metabolic process 31/59 52.5 29.8 b 25.3  - 89.7 22 9 / Kidney 3/47 6.4 114.0 73.9 - NC 0 3 / Tissue  / GO:0070301 cellula |
| One-way ANOVA Rat Heart | `108020006_One-way_ANOVA_Heart_Rats.txt` | 43 KB | One-way ANOVA; Data Source: rat_2D_HE_No0; Work Source: null — table 176×24 |
| One-way ANOVA Rat Kidney | `108020006_One-way_ANOVA_Kidney_Rats.txt` | 65 KB | One-way ANOVA; Data Source: rat_2D_KI_No0; Work Source: null — table 269×24 |
| One-way ANOVA Rat Liver | `108020006_One-way_ANOVA_Liver_Rats.txt` | 314 KB | One-way ANOVA; Data Source: rat_2D_LI_No0; Work Source: null — table 1311×24 |
| One-way ANOVA Rat Lung | `108020006_One-way_ANOVA_Lung_Rats.txt` | 18 KB | One-way ANOVA; Data Source: rat_2D_LU_No0; Work Source: null — table 72×24 |
| One-way ANOVA Rat Ovary | `108020006_One-way_ANOVA_Ovary_Rats.txt` | 12 KB | One-way ANOVA; Data Source: rat_2D_OV_No0; Work Source: null — table 49×24 |
| Rat DCB eFDR Synthetic Null Analysis | `108020006_DCB_eFDR_Synthetic_Null_Analysis_Rats.zip` | 33.1 MB | 5 files: Rat Ovary DCB Synthetic Null Analysis.bm2, Rat Heart DCB Synthetic Null Analysis.bm2, Rat Kidney DCB Synthetic Null Analysis.bm2, Rat Liver  … |
| TempO-Seq S1500v1.2 Full Manifest Rattus Norvegicus | `TempO-Seq_S1500v1.2_Full_Manifest_Rattus_Norvegicus.csv` | 259 KB | PROBE_ID,GENE_SYMBOL,PROBE_NAME,PROBE_SEQUENCE,ALIGNED_ENSEMBL_TRANSCRIPTS,ATTENUATION_FACTOR |
| Top 10 Genes Ranked by Potency of Perturbation Heart | `108020006_Top_10_Genes_Ranked_by_Potency_of_Perturbation_Heart_Rats.pdf` | 417 KB | 2 pp; Top 10 Genes Ranked by Potency of Perturbation (Sorted by BMD Median) / Date: 25 May 2025 / Time: 6:28:54 PM / Female / Entrez Gene IDs BMDrd25 (BMDLr |
| Top 10 Genes Ranked by Potency of Perturbation Kidney | `108020006_Top_10_Genes_Ranked_by_Potency_of_Perturbation_Kidney_Rats.pdf` | 288 KB | 3 pp; Entrez Gene IDs BMDrd25 (BMDLrd25 - BMDUrd25) in ppm Maximum  Fold Change Direction of Expression ChangeGene Symbols / 4.3 UP / 1.5 UP / 1.5 DOWN / 1. |
| Top 10 Genes Ranked by Potency of Perturbation Liver | `108020006_Top_10_Genes_Ranked_by_Potency_of_Perturbation_Liver_Rats.pdf` | 460 KB | 2 pp; Female / Entrez Gene IDs Probe IDs BMDrd25 (BMDLrd25 - BMDUrd25) in ppm Maximum Fold Change Direction of Expression ChangeGene Symbols / Sult1c3 65185 |
| Top 10 Genes Ranked by Potency of Perturbation Lung | `108020006_Top_10_Genes_Ranked_by_Potency_of_Perturbation_Lung_Rats.pdf` | 214 KB | 2 pp; Female / Entrez Gene IDs BMDrd25 (BMDLrd25 - BMDUrd25) in ppm Maximum Fold Change Direction of Expression ChangeGene Symbols / Akr1b8 286921 118.9 (36 |
| Top 10 Genes Ranked by Potency of Perturbation Ovary | `108020006_Top_10_Genes_Ranked_by_Potency_of_Perturbation_Ovary_Rats.pdf` | 249 KB | 2 pp; Female / Entrez Gene IDs BMDrd25 (BMDLrd25 - BMDUrd25) in ppm Maximum Fold Change Direction of Expression ChangeGene Symbols / Ddit4 140942 102.9 (27. |
| Top 10 GO Biological Process Gene Sets Heart | `108020006_Top_10_GO_Biological_Process_Gene_Sets_Heart_Rats.pdf` | 82 KB | 2 pp; GO:0070301 cellular response to hydrogen peroxide 5/57  8.8 148.7 58.2 - 382.1 4 1 / GO:0044770 cell cycle phase transition 3/58  5.2 161.5 81.6 - 247 |
| Top 10 GO Biological Process Gene Sets Kidney | `108020006_Top_10_GO_Biological_Process_Gene_Sets_Kidney_Rats.pdf` | 133 KB | 2 pp; DTTID:108-020-006-000-7  / Study Number: 108020006  / Study Type: 5-Day /  Toxicity / GO:0048568 embryonic organ development 3/47  6.4 114.0 73.9 - NC |
| Top 10 GO Biological Process Gene Sets Liver | `108020006_Top_10_GO_Biological_Process_Gene_Sets_Liver_Rats.pdf` | 104 KB | 2 pp; GO:0006805 xenobiotic metabolic process 31/59 52.5 29.8 25.3 - 89.7 22  9 / GO:0098754 detoxification 30/58 51.7 33.8 18.2 - 99.6 21  9 / GO:1990748 c |
| Top 10 GO Biological Process Gene Sets Lung | `108020006_Top_10_GO_Biological_Process_Gene_Sets_Lung_Rats.pdf` | 84 KB | 2 pp; GO:0098754 detoxification 11/58 19.0 175.9 109.3 - 224.0 7 4 / GO:0098869 cellular oxidant detoxification 10/43 23.3 175.9 109.3 - 224.0 6 4 / GO:1990 |
| Top 10 GO Biological Process Gene Sets Ovary | `108020006_Top_10_GO_Biological_Process_Gene_Sets_Ovary_Rats.pdf` | 104 KB | 2 pp; GO:0001822 kidney development 4/57 7.0 156.7 50.8 - 280.4 4 0 / GO:0008406 gonad development 3/51 5.9 156.7 50.8 - 280.4 2 1 / GO:0008584 male gonad d |
| Transcriptomics Data QC Report | `108020006_Transcriptomics_Data_QC_Report_Rats.zip` | 3.9 MB | 2 files: per_sample_summary_Dichlorobenzene_ScottAuerbach_v1.xlsx, Sciome_HTT_Dichlorobenzene_ScottAuerbach_QCReport_v1.pdf |

## Study Tables - Rats

| item | file | size | contents |
|---|---|---|---|
| I01 - Animal Removal Summary | `108020006_I01_Animal_Removal_Summary_Rats.pdf` | 40 KB | 4 pp; Study Number: 108020006 / Test Type: 5-Day Toxicity / Route: Whole-Body Inhalation / Species/Strain: Rat/Harlan Sprague Dawley / I01: Animal Removal S |
| I02 - Animal Removals | `108020006_I02_Animal_Removals_Rats.pdf` | 215 KB | 6 pp; Study Number: 108020006 / Test Type: 5-Day Toxicity / Route: Whole-Body Inhalation / Species/Strain: Rat/Harlan Sprague Dawley / I02: Animal Removals: |
| I04 - Mean Body Weights and Survival | `108020006_I04_Mean_Body_Weights_and_Survival_Rats.pdf` | 80 KB | 4 pp; Study Number: 108020006 / Test Type: 5-Day Toxicity / Route: Whole-Body Inhalation / Species/Strain: Rat/Harlan Sprague Dawley / I04: Mean Body Weight |
| I04G - Mean Body Weight Gain | `108020006_I04G_Mean_Body_Weight_Gain_Rats.pdf` | 49 KB | 4 pp; Study Number: 108020006 / Test Type: 5-Day Toxicity / Route: Whole-Body Inhalation / Species/Strain: Rat/Harlan Sprague Dawley / I04G: Mean Body Weigh |
| I05 - Clinical Observations Summary | `108020006_I05_Clinical_Observations_Summary_Rats.pdf` | 62 KB | 4 pp; Study Number: 108020006 / Test Type: 5-Day Toxicity / Route: Whole-Body Inhalation / Species/Strain: Rat/Harlan Sprague Dawley / I05: Clinical Observa |
| PA06 - Organ Weights Summary | `108020006_PA06_Organ_Weights_Summary_Rats.pdf` | 62 KB | 4 pp; Study Number: 108020006 / Test Type: 5-Day Toxicity / Route: Whole-Body Inhalation / Species/Strain: Rat/Harlan Sprague Dawley / PA06: Organ Weights S |
| PA41 - Clinical Chemistry Summary | `108020006_PA41_Clinical_Chemistry_Summary_Rats.pdf` | 150 KB | 6 pp; Study Number: 108020006 / Test Type: 5-Day Toxicity / Route: Whole-Body Inhalation / Species/Strain: Rat/Harlan Sprague Dawley / PA41: Clinical Chemis |
| PA43 - Hematology Summary | `108020006_PA43_Hematology_Summary_Rats.pdf` | 67 KB | 6 pp; Study Number: 108020006 / Test Type: 5-Day Toxicity / Route: Whole-Body Inhalation / Species/Strain: Rat/Harlan Sprague Dawley / PA43: Hematology Summ |
| PA48 - Blood and Tissue Concentration | `108020006_PA48_Blood_and_Tissue_Concentration.pdf` | 35 KB | 3 pp; P A48: Blood and Tissue Concentration / Study Number: 108020006 T est Compound: 1,2-Dichlorobenzene Date: 10 Oct 2025 / T est Type: 5-Day T oxicity CA |

## Individual Animal Data - Rats

| item | file | size | contents |
|---|---|---|---|
| Individual Animal Body Weight Data | `108020006_Individual_Animal_Body_Weight_Data_Rats.xlsx` | 14 KB | sheets: Key to Column Labels (8x4), Data (367x7) |
| Individual Animal Clinical Chemistry Data | `108020006_Individual_Animal_Clinical_Chemistry_Data_Rats.xlsx` | 18 KB | sheets: Key to Column Labels (27x4), Data (41x22) |
| Individual Animal Clinical Observations Data | `108020006_Individual_Animal_Clinical_Observations_Data_Rats.xlsx` | 9 KB | sheets: Key to Column Labels (10x4), Data (162x9) |
| Individual Animal Hematology Data | `Individual_Animal_Hematology_Data.xlsx` | 18 KB | sheets: Key to Column Labels (25x4), Data (41x22) |
| Individual Animal Organ Weight Data | `108020006_Individual_Animal_Organ_Weight_Data_Rats.xlsx` | 7 KB | sheets: Key to Column Labels (12x4), Data (41x11) |
| Individual Animal Removal Reasons Data | `108020006_Individual_Animal_Removal_Reasons_Data_Rats.xlsx` | 6 KB | sheets: Key to Column Labels (8x4), Data (62x7) |

## Apical Benchmark Dose Analysis - Mice

| item | file | size | contents |
|---|---|---|---|
| BMD, NOEL and LOEL Summary for Apical Endpoints | `108020007_BMD,_NOEL_and_LOEL_Summary_for_Apical_Endpoints_Mice.pdf` | 108 KB | 1 pp; DTTID:108-020-007-000-8 / StudyNumber: 108020007 / StudyType: 5-Day Toxicity / Species/Strain: Mice B6D2F1/Crl / Alkaline Phosphatase  33.4 100  30 /  |
| BMDExpress Project File Mouse Apical (bm2 format) | `108020007_2D_Mouse_NonGenomic.bm2` | 134 KB | BMDExpress project '2D_MouseNonGenomicBMD.bm2': 6 experiments, 11 BMD results, 11 category analyses |
| Clinical Chemistry Summary | `108020007_Clinical_Chemistry_Summary_Mice.pdf` | 90 KB | 1 pp; PA41-BMD: Clinical Chemistry Summary / DTTID: 108-020-007-000-8 TestCompound: 1,2-Dichlorobenzene Date: 20 Jun 2025 / Study Number: 108020007 CAS Numb |
| Mean Body Weight Summary | `108020007_Mean_Body_Weight_Summary_Mice.pdf` | 59 KB | 1 pp; I04-BMD: Mean Body / Weight Summary / DTTID: 108-020-007-000-8 TestCompound: 1,2-Dichlorobenzene Date: 20 Jun 2025 / Study Number: 108020007 CAS Numbe |
| Organ Weights Summary | `108020007_Organ_Weights_Summary_Mice.pdf` | 58 KB | 1 pp; PA06-BMD: Organ Weights Summary / DTTID: 108-020-007-000-8 TestCompound: 1,2-Dichlorobenzene Date: 20 Jun 2025 / Study Number: 108020007 CAS Number: 9 |

## Genomic Benchmark Dose Analysis - Mice

| item | file | size | contents |
|---|---|---|---|
| All Organ Principal Components Analysis Files | `108020007_All_Organ_Principal_Components_Analysis_Files.zip` | 895 KB | 5 files: PCA_108020007_(2DCB-MOUSE-OV).pdf, PCA_108020007_(2DCB-MOUSE-HE).pdf, PCA_108020007_(2DCB-MOUSE-KI).pdf, PCA_108020007_(2DCB-MOUSE-LI).pdf … |
| Animal and Fastaq Metadata | `108020007_Animal_and_Fastaq_Metadata.pdf` | 153 KB | 5 pp; 1 Core Animals V / ehicle Control 0 Yes Heart 2DM1F1HE_S6_R1_001.fastq.gz / 1 Core Animals Vehicle Control 0 Yes Kidney 2DM1F1KI_S6_R1_001.fastq.gz /  |
| Attenuation adjusted Raw Read Counts Mice Study | `108020007_Attenuation_adjusted_Raw_Read_Counts_Mice_Study.zip` | 2.7 MB | 2 files: Attenuation-adjusted Raw Read Counts Mouse 1,2-DCB Study.xlsx, 1,2-DCB-Mouse_FASTQ.xlsx |
| Benchmark Dose Analysis Mouse Heart | `108020007_Benchmark_Dose_Analysis_Heart_Mice.txt` | 295 KB |  — table 176×191 |
| Benchmark Dose Analysis Mouse Kidney | `108020007_Benchmark_Dose_Analysis_Kidney_Mice.txt` | 829 KB | Benchmark Dose Analyses; Data Source: mouse_2D_KI; Work Source: mouse_2D_KI_curvefitprefilter_nofoldfilter_1 — table 318×191 |
| Benchmark Dose Analysis Mouse Liver | `108020007_Benchmark_Dose_Analysis_Liver_Mice.txt` | 2.2 MB | Benchmark Dose Analyses; Data Source: mouse_2D_LI; Work Source: mouse_2D_LI_curvefitprefilter_nofoldfilter — table 838×191 |
| Benchmark Dose Analysis Mouse Lung | `108020007_Benchmark_Dose_Analysis_Lung_Mice.txt` | 1.8 MB | Benchmark Dose Analyses; Data Source: mouse_2D_LU; Work Source: mouse_2D_LU_curvefitprefilter_nofoldfilter — table 705×191 |
| Benchmark Dose Analysis Mouse Ovary | `108020007_Benchmark_Dose_Analysis_Ovary_Mice.txt` | 189 KB | Benchmark Dose Analyses; Data Source: mouse_2D_OV; Work Source: mouse_2D_OV_curvefitprefilter_nofoldfilter — table 71×191 |
| BMDExpress Expression Data Heart | `108020007_BMDExpress_Expression_Data_Heart_Mice.txt` | 1.3 MB |  — table 2170×38 |
| BMDExpress Expression Data Kidney | `108020007_BMDExpress_Expression_Data_Kidney_Mice.txt` | 991 KB |  — table 2426×25 |
| BMDExpress Expression Data Liver | `108020007_BMDExpress_Expression_Data_Liver_Mice.txt` | 1.1 MB |  — table 2182×32 |
| BMDExpress Expression Data Lung | `108020007_BMDExpress_Expression_Data_Lung.txt` | 1.4 MB |  — table 2469×36 |
| BMDExpress Expression Data Ovary | `108020007_BMDExpress_Expression_Data_Ovary_Mice.txt` | 1.5 MB |  — table 2464×38 |
| BMDExpress GO Biological Process BMD Results Mouse Heart | `108020007_BMDExpress_GO_Biological_Process_BMD_Results_Heart_Mice.txt` | 109 KB | Filter information:; Percentage BETWEEN [5.0, Infinity]; Genes That Passed All Filters BETWEEN [3, 2147483647] — table 60×115 |
| BMDExpress GO Biological Process BMD Results Mouse Kidney | `108020007_BMDExpress_GO_Biological_Process_BMD_Results_Kidney_Mice.txt` | 682 KB | Filter information:; Genes That Passed All Filters BETWEEN [3, 2147483647]; Percentage BETWEEN [5.0, Infinity] — table 302×115 |
| BMDExpress GO Biological Process BMD Results Mouse Liver | `108020007_BMDExpress_GO_Biological_Process_BMD_Results_Liver_Mice.txt` | 5.1 MB | Filter information:; Genes That Passed All Filters BETWEEN [3, 2147483647]; Percentage BETWEEN [5.0, Infinity] — table 904×115 |
| BMDExpress GO Biological Process BMD Results Mouse Lung | `108020007_BMDExpress_GO_Biological_Process_BMD_Results_Lung_Mice.txt` | 4.1 MB | Filter information:; Genes That Passed All Filters BETWEEN [3, 2147483647]; Percentage BETWEEN [5.0, Infinity] — table 901×115 |
| BMDExpress GO Biological Process BMD Results Mouse Ovary | `108020007_BMDExpress_GO_Biological_Process_BMD_Results_Ovary_Mice.txt` | 27 KB | Filter information:; Genes That Passed All Filters BETWEEN [3, 2147483647]; Percentage BETWEEN [5.0, Infinity] — table 15×115 |
| BMDExpress Individual Gene BMD Results Mouse Heart | `108020007_BMDExpress_Individual_Gene_BMD_Results_Heart_Mice.txt` | 87 KB | Filter information:; Genes That Passed All Filters BETWEEN [1, 2147483647]; Gene Level Analyses — table 78×114 |
| BMDExpress Individual Gene BMD Results Mouse Kidney | `108020007_BMDExpress_Individual_Gene_BMD_Results_Kidney_Mice.txt` | 152 KB | Filter information:; Genes That Passed All Filters BETWEEN [1, 2147483647]; Gene Level Analyses — table 139×114 |
| BMDExpress Individual Gene BMD Results Mouse Liver | `108020007_BMDExpress_Individual_Gene_BMD_Results_Liver_Mice.txt` | 758 KB | Filter information:; Genes That Passed All Filters BETWEEN [1, 2147483647]; Gene Level Analyses — table 703×114 |
| BMDExpress Individual Gene BMD Results Mouse Lung | `108020007_BMDExpress_Individual_Gene_BMD_Results_Lung_Mice.txt` | 690 KB | Filter information:; Genes That Passed All Filters BETWEEN [1, 2147483647]; Gene Level Analyses — table 647×114 |
| BMDExpress Individual Gene BMD Results Mouse Ovary | `108020007_BMDExpress_Individual_Gene_BMD_Results_Ovary_Mice.txt` | 58 KB | Filter information:; Genes That Passed All Filters BETWEEN [1, 2147483647]; Gene Level Analyses — table 51×114 |
| BMDExpress Project File Mouse Genomic (bm2 format) | `108020007_2D_Genomic_Mice.bm2` | 14.2 MB | BMDExpress project 'DCB Analysis-2025-No0-1,2-DCB-Mouse.bm2': 5 experiments, 5 BMD results, 10 category analyses |
| BMDExpress Project File Mouse Genomic (JSON format) | `108020007_2D_Genomic_Mice.json` | 81.7 MB | BMDExpress project 'DCB Analysis-2025-No0-1,2-DCB-Mouse.bm2': 5 experiments, 5 BMD results, 10 category analyses |
| Curve Fit Mouse Heart | `108020007_Curve_Fit_Heart_Mice.txt` | 24 KB | Curve Fit Prefilter; Data Source: mouse_2D_HE_williams_0.05_NOMTC_nofoldfilter; Work Source: mouse_2D_HE — table 118×21 |
| Curve Fit Mouse Kidney | `108020007_Curve_Fit_Kidney_Mice.txt` | 63 KB | Curve Fit Prefilter; Data Source: mouse_2D_KI_williams_0.05_NOMTC_nofoldfilter; Work Source: mouse_2D_KI — table 318×21 |
| Curve Fit Mouse Liver | `108020007_Curve_Fit_Liver_Mice.txt` | 166 KB | Curve Fit Prefilter; Data Source: mouse_2D_LI_williams_0.05_NOMTC_nofoldfilter; Work Source: mouse_2D_LI — table 838×21 |
| Curve Fit Mouse Lung | `108020007_Curve_Fit_Lung_Mice.txt` | 138 KB | Curve Fit Prefilter; Data Source: mouse_2D_LU_williams_0.05_NOMTC_nofoldfilter; Work Source: mouse_2D_LU — table 705×21 |
| Curve Fit Mouse Ovary | `108020007_Curve_Fit_Ovary_Mice.txt` | 15 KB | Curve Fit Prefilter; Data Source: mouse_2D_OV_williams_0.05_NOMTC_nofoldfilter; Work Source: mouse_2D_OV — table 71×21 |
| Most Potent GO Biological Process In Each Tissue | `108020007_Most_Potent_GO_Biological_Process_In_Each_Tissue_Mice.pdf` | 153 KB | 1 pp; Liver GO:0046889: positive regulation of lipid biosynthetic process 15/45 33.3 1.5 b 0.5 - 5.5 6 9 / Heart GO:0006575: cellular modified amino acid me |
| Mouse DCB eFDR Synthetic Null Analysis | `108020007_DCB_eFDR_Synthetic_Null_Analysis_Mice.zip` | 35.0 MB | 5 files: Mouse Ovary DCB Synthetic Null Analysis.bm2, Mouse Heart DCB Synthetic Null Analysis.bm2, Mouse Kidney DCB Synthetic Null Analysis.bm2, Mous … |
| One-way ANOVA Mouse Heart | `108020007_One-way_ANOVA_Heart_Mice.txt` | 33 KB | One-way ANOVA; Data Source: mouse_2D_HE; Work Source: null — table 148×22 |
| One-way ANOVA Mouse Kidney | `108020007_One-way_ANOVA_Kidney_Mice.txt` | 49 KB | One-way ANOVA; Data Source: mouse_2D_KI; Work Source: null — table 220×22 |
| One-way ANOVA Mouse Liver | `108020007_One-way_ANOVA_Liver_Mice.txt` | 247 KB | One-way ANOVA; Data Source: mouse_2D_LI; Work Source: null — table 1126×22 |
| One-way ANOVA Mouse Lung | `108020007_One-way_ANOVA_Lung_Mice.txt` | 198 KB | One-way ANOVA; Data Source: mouse_2D_LU; Work Source: null — table 911×22 |
| One-way ANOVA Mouse Ovary | `108020007_One-way_ANOVA_Ovary_Mice.txt` | 20 KB | One-way ANOVA; Data Source: mouse_2D_OV; Work Source: null — table 88×22 |
| TempO-Seq S1500v1.2 Full Manifest Mus Musculus | `TempO-Seq_S1500v1.2_Full_Manifest_Mus_Musculus.csv` | 355 KB | PROBE_ID,GENE_SYMBOL,PROBE_NAME,PROBE_SEQUENCE,ALIGNED_ENSEMBL_TRANSCRIPTS,ATTENUATION_FACTOR |
| Top 10 Genes Ranked by Potency of Perturbation Heart | `108020007_Top_10_Genes_Ranked_by_Potency_of_Perturbation_Heart_Mice.pdf` | 238 KB | 2 pp; Female / Entrez Gene IDs Probe IDs BMDrd25 (BMDLrd25 - BMDUrd25) in ppm Maximum Fold Change Direction of Expression ChangeGene Symbols / Rsad2 58185 R |
| Top 10 Genes Ranked by Potency of Perturbation Kidney | `108020007_Top_10_Genes_Ranked_by_Potency_of_Perturbation_Kidney_Mice.pdf` | 319 KB | 2 pp; Female / Entrez Gene IDs Probe IDs BMDrd25 (BMDLrd25 - BMDUrd25) in ppm Maximum Fold Change Direction of Expression ChangeGene Symbols / Cdk2 12566 Cd |
| Top 10 Genes Ranked by Potency of Perturbation Liver | `108020007_Top_10_Genes_Ranked_by_Potency_of_Perturbation_Liver_Mice.pdf` | 629 KB | 2 pp; Entrez Gene IDs Probe IDs BMDrd25 (BMDLrd25 - BMDUrd25) in ppm  Maximum Fold Change Direction of Expression Change /  13170 Dbp_31391 0.7 (0.2 - 1.9)  |
| Top 10 Genes Ranked by Potency of Perturbation Lung | `108020007_Top_10_Genes_Ranked_by_Potency_of_Perturbation_Lung_Mice.pdf` | 105 KB | 2 pp; Date: 25 May 2025 / Time: 6:30:58 PM / DTTID: 108-020-007-000-8  / Study Number: 108020007  / Study Type: 5-Day Toxicity  / Species/Strain: Mice B6D2F |
| Top 10 Genes Ranked by Potency of Perturbation Ovary | `108020007_Top_10_Genes_Ranked_by_Potency_of_Perturbation_Ovary_Mice.pdf` | 275 KB | 2 pp; Female / Entrez Gene IDs Probe IDs BMDrd25 (BMDLrd25 - BMDUrd25) in ppm Maximum Fold Change Direction of Expression ChangeGene Symbols / Syn1  20964 S |
| Top 10 GO Biological Process Gene Sets Heart | `108020007_Top_10_GO_Biological_Process_Gene_Sets_Heart_Mice.pdf` | 89 KB | 2 pp; DTTID: 108-020-007-000-8  / Study Number: 108020007  / Study Type: 5-Day Toxicity / Species/Strain: Mice B6D2F1/Crl / DTXSID: DTXSID6020430 |
| Top 10 GO Biological Process Gene Sets Kidney | `108020007_Top_10_GO_Biological_Process_Gene_Sets_Kidney_Mice.pdf` | 104 KB | 2 pp; GO:0015850: organic hydroxy compound transport 6/58 10.3 2.3 0.6 - 219.7 4 2 / GO:0033559: unsaturated fatty acid metabolic process 7/40 17.5 2.6 1.2  |
| Top 10 GO Biological Process Gene Sets Liver | `108020007_Top_10_GO_Biological_Process_Gene_Sets_Liver_Mice.pdf` | 105 KB | 2 pp; GO:0046889: positive regulation of lipid biosynthetic process 15/45 33.3 1.5 0.5 - 5.5  6  9 / GO:0045834: positive regulation of lipid metabolic proc |
| Top 10 GO Biological Process Gene Sets Lung | `108020007_Top_10_GO_Biological_Process_Gene_Sets_Lung_Mice.pdf` | 133 KB | 2 pp; GO:0033559: unsaturated fatty acid metabolic process  8/40 20.0 2.1 0.7 - 4.8  8 0 / GO:0008203: cholesterol metabolic process  8/48 16.7 2.4 0.7 - 5. |
| Top 10 GO Biological Process Gene Sets Ovary | `108020007_Top_10_GO_Biological_Process_Gene_Sets_Ovary_Mice.pdf` | 104 KB | 2 pp; GO:0030097: hemopoiesis 1 / GO:0072594: establishment of protein localization to organelle 2 / GO:0048167: regulation of synaptic plasticity 3 / GO:00 |
| Transcriptomics Data QC Report | `108020007_Transcriptomics_Data_QC_Report_Mice.zip` | 3.9 MB | 2 files: per_sample_summary_Dichlorobenzene_ScottAuerbach_v1.xlsx, Sciome_HTT_Dichlorobenzene_ScottAuerbach_QCReport_v1.pdf |

## Study Tables - Mice

| item | file | size | contents |
|---|---|---|---|
| I01 - Animal Removal Summary | `108020007_I01_Animal_Removal_Summary_Mice.pdf` | 46 KB | 4 pp; Study Number: 108020007 / Test Type: 5-Day Toxicity / Route: Whole-Body Inhalation / Species/Strain: Mouse/B6D2F1/Crl / I01: Animal Removal Summary /  |
| I02 - Animal Removals | `108020007_I02_Animal_Removals_Mice.pdf` | 207 KB | 6 pp; Study Number: 108020007 / Test Type: 5-Day Toxicity / Route: Whole-Body Inhalation / Species/Strain: Mouse/B6D2F1/Crl / I02: Animal Removals: Chronolo |
| I04 - Mean Body Weights and Survival | `108020007_I04_Mean_Body_Weights_and_Survival_Mice.pdf` | 73 KB | 4 pp; Study Number: 108020007 / Test Type: 5-Day Toxicity / Route: Whole-Body Inhalation / Species/Strain: Mouse/B6D2F1/Crl / I04: Mean Body Weight Summary  |
| I04G - Mean Body Weight Gain | `108020007_I04G_Mean_Body_Weight_Gain_Mice.pdf` | 43 KB | 3 pp; Study Number: 108020007 / Test Type: 5-Day Toxicity / Route: Whole-Body Inhalation / Species/Strain: Mouse/B6D2F1/Crl / I04G: Mean Body Weight Gain /  |
| I05 - Clinical Observations Summary | `108020007_I05_Clinical_Observations_Summary_Mice.pdf` | 58 KB | 4 pp; Study Number: 108020007 / Test Type: 5-Day Toxicity / Route: Whole-Body Inhalation / Species/Strain: Mouse/B6D2F1/Crl / I05: Clinical Observations Sum |
| PA06 - Organ Weights Summary | `108020007_PA06_Organ_Weights_Summary_Mice.pdf` | 59 KB | 4 pp; Study Number: 108020007 / Test Type: 5-Day Toxicity / Route: Whole-Body Inhalation / Species/Strain: Mouse/B6D2F1/Crl / PA06: Organ Weights Summary /  |
| PA41 - Clinical Chemistry Summary | `108020007_PA41_Clinical_Chemistry_Summary_Mice.pdf` | 138 KB | 6 pp; Study Number: 108020007 / Test Type: 5-Day Toxicity / Route: Whole-Body Inhalation / Species/Strain: Mouse/B6D2F1/Crl / PA41: Clinical Chemistry Summa |
| PA48 - Blood and Tissue Concentration | `108020007_PA48_Blood_and_Tissue_Concentration.pdf` | 34 KB | 3 pp; P A48: Blood and Tissue Concentration / Study Number: 108020007 T est Compound: 1,2-Dichlorobenzene Date: 10 Oct 2025 / T est Type: 5-Day T oxicity CA |

## Individual Animal Data - Mice

| item | file | size | contents |
|---|---|---|---|
| Individual Animal Body Weight Data | `108020007_Individual_Animal_Body_Weight_Data_Mice.xlsx` | 13 KB | sheets: Key to Column Labels (8x4), Data (342x7) |
| Individual Animal Clinical Chemistry Data | `108020007_Individual_Animal_Clinical_Chemistry_Data_Mice.xlsx` | 16 KB | sheets: Key to Column Labels (27x4), Data (30x22) |
| Individual Animal Clinical Observations Data | `108020007_Individual_Animal_Clinical_Observations_Data_Mice.xlsx` | 8 KB | sheets: Key to Column Labels (10x4), Data (119x9) |
| Individual Animal Organ Weight Data | `108020007_Individual_Animal_Organ_Weight_Data_Mice.xlsx` | 6 KB | sheets: Key to Column Labels (14x4), Data (39x11) |
| Individual Animal Removal Reasons Data | `108020007_Individual_Animal_Removal_Reasons_Data_Mice.xlsx` | 6 KB | sheets: Key to Column Labels (8x4), Data (59x7) |

## Analysis Pipeline Evaluation

| item | file | size | contents |
|---|---|---|---|
| Analysis Pipeline Evaluation | `Analysis_Pipeline_Evaluation.zip` | 89.6 MB | 10 files: DTT_tBMD_pipeline_filtered.txt, EPA_tBMD_pipeline_filtered.txt, GO_replicates_EPA_DTT.xlsx, Read Me.docx … |
| DTT tBMD Pipeline bm2 | `DTT_tBMD_Pipeline_bm2.zip` | 73.0 MB | 1 files: DTT_tBMD_pipeline.bm2 |
| EPA tBMD Pipeline bm2 | `EPA_tBMD_Pipeline_bm2.zip` | 62.1 MB | 1 files: EPA_tBMD_pipeline.bm2 |
