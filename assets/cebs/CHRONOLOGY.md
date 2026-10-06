# NIEHS 5-day biological potency reports: evolution of data packages and analysis methods

Built 2026-10-01 from the CEBS data pages of all 12 reports listed at https://cebs.niehs.nih.gov/cebs/paper/16195,
plus the PFHxSAm package originally supplied to this project (`../given-2026/`).
Per-package details are in `<report>/MANIFEST.md`. Dates come from inside the files (BMDExpress analysis
timestamps, Office/PDF metadata, zip entry times). The report publication pages (niehs.nih.gov) are firewalled,
so the publication dates below are approximate.

**Coverage:** all 12 packages complete (644 files): the 635 linked from the data pages, plus 9 RR-8 files (individual-animal
workbooks and NTP I04/I05/PA06/PA41/R07 tables) that only RR-8's CEBS *study* page links. Checked 2026-10-06: the NIEHS-02…10
study pages carry only byte-identical copies of data-page files, and NIEHS-12/13 have no study page.
Apart from the report publication dates, every statement below comes from the files themselves.

## Timeline

| date | event | evidence |
|---|---|---|
| 2014-05 | TPHP microarray CEL files scanned | zip entry times (RR-8) |
| 2017-12 | First BMDS 2.7 apical fit report (TPHP) | RR-8 appendix metadata |
| 2018-03-09 | GO annotation file for Affymetrix GPL1355 created | category-analysis notes |
| 2018-04-12 | **TPHP genomics** analysed in **BMDExpress 2.20.0148** | RR-8 project timestamps |
| 2018-05-01/02 | Aromatic-phosphate genomics analysed in **BMDExpress 2.20.0151** (EHDP, IDDP, IPP, TCP) | .bm2/JSON timestamps (NIEHS-02 .bm2, 04, 05, 06) |
| 2018-11/12 | RR-8 summary tables produced (Table 1–6 PDFs) | PDF metadata |
| 2020-11 → 2021-02 | PFAS study tables generated; TempO-Seq expression files built (BMDExpress 2.30.0485, 2020-11-18) | PDF metadata; expression-file headers |
| 2021-02-12 | **Shared PFAS project** analysed in **BMDExpress 2.30.0507** (4 chemicals × liver/kidney × sex) | project timestamps (NIEHS-07…10) |
| 2021-04 → 2021-08 | PFAS report tables and BMDS appendices produced (Parameter workbooks dated 2021-07-28) | docx/xlsx metadata |
| 2021-08-19/24 | Aromatic-phosphate study-table PDFs generated | PDF metadata |
| 2021-11-04 | **EHDP and BPDP genomics re-run** in BMDExpress 2.30.0507 (10,000 permutations, 19 animals); IDDP/IPP/TCP keep their 2018 analyses | NIEHS-02/03 JSON + exports |
| 2022 | Aromatic-phosphate (NIEHS-02…06) and PFAS (NIEHS-07…10) packages assembled; PFAS JSON export dated 2022-11-16 | zip entry times |
| 2023-03 | NIEHS-10 PDF on Bookshelf (copy in the supplied package is dated 2023-03-20) | PDF metadata |
| 2024-10-31 | S1500 annotation for BMDExpress 3 created | 2025/2026 experiment notes |
| 2025-04 → 2025-08 | **1,2-DCB and 1,4-DCB** (NIEHS-12/13) analysed in **BMDExpress 3.20.0119–0132** (curve-fit BMR 2 SD); eFDR null runs | project timestamps |
| 2025-11-21/22 | Pipeline evaluation: **EPA ETAP method** run on 20 gavage chemicals in BMDExpress 2.30.0516 | EPA_tBMD_pipeline.bm2 |
| 2025-12-11 | Pipeline evaluation: **DTT method** run on the same data in **BMDExpress 3.20.0141**, curve-fit BMR **1.581 SD** | DTT_tBMD_pipeline.bm2 |
| 2026-01-15 | DTT-method synthetic-null (eFDR) runs on kidney and liver | SyntheticKidney/Liver.bm2 |
| 2026-02 | Pipeline evaluation updated: the 1.25 fold filter after Williams removed ("consistent with what was applied to the DCB data"); NIEHS-12/13 tables finalised | Read Me.docx; PDF metadata |
| 2026-03-02 | **PFHxSAm re-analysed** with the February 2026 DTT method in BMDExpress 3.20.0156 → the package given to this project | `../given-2026/` |

## Package generations

| | G0: RR-8 | G1: NIEHS-02…06 | G2: NIEHS-07…10 | G3: NIEHS-12/13 |
|---|---|---|---|---|
| chemicals | triphenyl phosphate (2018 analysis) | aromatic phosphates | PFAS + 2,3-benzofluorene | dichlorobenzenes |
| design | male SD rats, gavage | male SD rats, gavage, 5–6 groups | M+F SD rats, gavage, 8–10 groups, liver + kidney | female SD rats + B6D2F1 mice, **inhalation** (ppm), 6–7 groups, 5 tissues |
| transcriptomics | Affymetrix Rat 230 2.0, CEL files, Partek batch correction | Affymetrix Rat 230 2.0 (31,099 probe sets), CEL files, Partek batch correction | **TempO-Seq S1500+** (2,654 probes), FASTQ in GEO | TempO-Seq S1500 v1.2, **raw (attenuation-adjusted) counts published** |
| apical BMD | modified BMDS 2.7.0, high-dose dropping (0–3) | **modified EPA BMDS 2.7.0** (python bmds 0.11), 16 rules, high-dose dropping | modified BMDS 2.7.0, high-dose dropping up to 5 doses (10 dose groups) | **BMDExpress 3** (ToxicR model averaging) |
| BMDExpress project | one project | one per chemical | **one shared 16-experiment project** for all four reports | per species: genomic + non-genomic (apical) projects, plus eFDR null projects |
| study tables | "Table 1–6" PDFs | NTP I04/I05/PA06/PA41/R07 PDFs | + PA43 hematology, PA48 tissue concentration | + I01/I02 removals, I04G weight gain; "-BMD" summary PDFs |
| report tables | Top 20 GO (PDF) | Top 10 genes/GO (docx) | Top 10 genes/GO per organ×sex (docx), summary docx | Top 10 per tissue + most-potent GO per tissue (PDF) |
| QC / provenance | batch-correction docs, sample list | animal↔CEL table, batch-annotated sample list, PCA | animal↔FASTQ table, TempO-Seq sample sheet, per-sample QC **with removal reasons**, 2D/3D PCA | QC report, removal-reason workbooks, **eFDR synthetic null**, probe manifests, **Materials and Methods PDF**, DTT vs EPA pipeline evaluation |
| file naming | `C11042_…` | generic names (`Model_Parameters.xlsx`) | study-number prefix (`C20022-01_…`) | DTT study numbers (`108020006_…`) |

## Genomic analysis method by era

| setting | 2018 (BMDExpress 2.20) | 2021 (BMDExpress 2.30) | 2025 (BMDExpress 3.20; NIEHS-12/13) | DTT method, Dec 2025 / Feb 2026 (pipeline evaluation; given PFHxSAm) |
|---|---|---|---|---|
| probe filter | none | none | **drop probes with any zero count ("No0")** | No0 |
| prefilter | Williams p<0.05, **100 permutations**, no MTC, fold ≥1.5 | Williams p<0.05, **10,000 permutations**, no MTC, fold ≥1.5, t-test NOTEL/LOTEL | Williams p<0.05 (10,000) → **curve-fit prefilter** (BMR 2 SD), no fold filter | Williams (no fold filter since Feb 2026) → curve-fit prefilter at **1.581 SD** |
| BMD models | Hill, Power, Linear, Poly2, Exp2–5 (8) | same 8 | **ToxicR Laplace model averaging** of Hill, Power, Exp3, Exp5 | same as 2025 |
| selection | lowest AIC | lowest AIC, BMDL/BMDU used in selection | model average | model average |
| BMR | factor 1.0 (type not recorded by 2.20; 1 SD by convention) | 1 SD | **25% relative deviation**, step-function threshold 0.5 | 25% RD |
| category filters | BMD p ≥0.1, BMDU/BMDL ≤40, GO BP plain + deduplicated, gene-level defined categories | same; GO deduplicated; gene level adds fold change ≥2 | **R² ≥0.6, BMD/BMDL ≤10, gene sets 40–500 genes**, drop step-function < first dose | same; GO BP BMD = 5th-percentile gene BMD, tBMD = lowest GO BP across liver+kidney (given PFHxSAm adds S1500 adversity signatures) |
| reports using it | RR-8, NIEHS-04, 05, 06 (and NIEHS-02's .bm2) | NIEHS-02, 03, 07–10 | NIEHS-12, 13 | no report yet; published as the 'Analysis Pipeline Evaluation' in NIEHS-12/13 |

## Apical BMD method by era

| | 2018–2021 (G0–G2) | 2025 (G3) | 2026 given PFHxSAm |
|---|---|---|---|
| engine | modified EPA BMDS 2.7.0 via python bmds 0.11 (Windows executables) | BMDExpress 3.20, ToxicR | BMDExpress 3.20.0156, ToxicR |
| models / selection | continuous models (Hill, Power, Polynomial, Exponential), 16 recommendation rules (BMD ≤ max dose added; 10× low-dose rules removed) | Laplace model averaging of Hill, Power, Exp3, Exp5 | same as 2025 |
| BMR | 1 SD | 1 SD | 1 SD, **except clinical chemistry at 25% RD** |
| endpoint screen | all endpoints modelled | only endpoints with a significant trend **and** ≥1 significant pairwise difference | Williams prefilter |
| high-dose dropping | yes in every BMDS package: endpoints refit with the top 1–5 doses removed (the depth grows with the number of dose groups) | no | no |

## Packaging defects found

- **NIEHS-02:** the `.bm2` (2018, 21 animals, 100 permutations) and the JSON (2021, 19 animals, 10,000 permutations) are different analyses; the exported result files match the JSON.
- **NIEHS-03:** the "JSON format" project file is actually a Java-serialised `.bm2`.
- **NIEHS-05:** `BMDs_code_package.docx` is a zip and `Model_Parameters.docx` is an Excel workbook.
- **NIEHS-07…10:** the GO annotation zips are labelled Affymetrix GPL1355 (left over from G1) and contain no S1500 probe IDs. The genomics project contains three other chemicals. NIEHS-08 also includes a stray Word lock file.
- **RR-8:** `C11042_Appendix.doc` is actually a .docx.
- **NIEHS-12:** the rat genomic project's top-level curve-fit prefilter list holds the **mouse** results; the rat BMD results point to their own embedded rat prefilters.
- **NIEHS-13:** the rat raw-count archive is named `…Rat_Study,zip` (comma, no extension).

## What this means for the report tool

1. **"The published method" is not one method.** Four distinct genomic configurations and two apical engines occur
   across 12 reports, and the switches happen within report families (NIEHS-02/03 vs 04–06). Validating against a
   published report means reproducing *that report's* generation. Validation needs a method profile per report
   (engine, version, prefilter, BMR, category filters), not one global setting.
2. **The package you were given is the current DTT method applied to a G2 study.** Its settings (No0, Williams with
   no fold filter, curve-fit 1.581 SD, model averaging at 25% RD, BMDExpress 3.20.0156) match the February 2026 DTT
   method in the NIEHS-12/13 pipeline evaluation exactly. That explains every PFHxSAm discrepancy found so far: PCA
   (No0 probe subset), genomic BMDs, and apical BMDs (BMDExpress instead of BMDS 2.7). Its one addition is a clinical
   chemistry apical BMR of 25% RD instead of 1 SD.
3. **The forward method is the DTT method, and it is still moving.** Published DCB reports use curve-fit 2 SD
   (3.20.0119); the evaluated method uses 1.581 SD (3.20.0141); the given package uses 3.20.0156. No published report
   yet uses the 1.581 version, so the pipeline evaluation (20 chemicals, EPA comparison, eFDR) is the closest published
   reference for it. NIEHS-10 remains the reference for the G2 method, validated with modified BMDS 2.7.
   The evaluation covers BPAF and triclosan, which this project already holds data for.
4. **Ingestion must verify by content and provenance, not by filename.** Several packages contain mislabelled
   types, non-matching bm2/JSON pairs, multi-chemical projects and cross-species objects. Analyses should be
   selected by their recorded settings, version and data source.
