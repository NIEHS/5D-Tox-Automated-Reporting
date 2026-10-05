# NIEHS-13 (1,4-dichlorobenzene, female rat): our pipeline vs the published tables

Run 2026-10-02. Session `sessions/DTXSID1020431` was built from the CEBS package only:

- Five Individual Animal workbooks went through `tooling/cebs_to_pool.py`. Sex was filled from the Key title.
- The genomic project `108020004_4D_Genomic_Rats.bm2` was ingested as-is. Organs were matched by sample ID to the expression files.
- The flow was validate → integrate → metadata → approve → process (`dose_unit=ppm`, `bmd_stats=[fifth_pct, median]`, default GO cutoffs).
- The template's NIEHS-10-specific allowlists (organs, sex, assays) were switched off for the run.
- The non-genomic apical `.bm2` was *not* ingested. It is one experiment holding the 9 pre-selected endpoints, mixed across platforms.

Published references: the `*-BMD` summary PDFs, PA06/PA41/PA43, `…BMD,_NOEL_and_LOEL_Summary…`, the Top 10 GO/genes PDFs, the Most Potent GO PDF, the BMDExpress GO export `.txt`, and the non-genomic `.bm2`.

> **Update 2026-10-05: statistics resolved.** `bmdx_pipe.ntp_stats` now runs the published procedure: Jonckheere selects Williams or Dunnett (weights) and Shirley or Dunn (clinical pathology). Relative organ weights are tested and modelled as endpoints of their own.
>
> - Every NIEHS-13 PA06/PA41/PA43 marker cell whose data row matches agrees: 371/371. Across NIEHS-07..13, 3636/3649 agree; see `NTP-STATS-CONFORMANCE.md`.
> - The BMD summary now lists all **9 of 9** published endpoints, with the published LOEL/NOEL.
> - The relative-weight ToxicR BMDs reproduce the published values: Liver 191.38/127.62, Kidney-L 219.18/89.38.
> - Kidney-R relative is published NVM; ToxicR fits it at 339.5/77.0.
>
> The rows below marked *(resolved)* are kept as the 2026-10-02 record.

## Results at a glance

| area | match | difference | cause |
|---|---|---|---|
| Group means ± SEM, N | every value where N agrees | heart 150 ppm (published N=4, excludes animal 403 = 2.42 g); AST control (N=9); CK control and 150 ppm (N=9/4) | published removes outliers; we have no outlier step |
| Number format | – | we use sig-fig rounding (`0.619 ± 0.012`, `10.21 ± 0.64`, `4.0` with SE dropped); published uses fixed decimals per endpoint (`0.62 ± 0.01`, `4.0 ± 0.0`) | formatting rule |
| Derived rows | – | published has Body Weight Gain (BW table) and A/G ratio (PA41); we have neither | not derived |
| Relative organ weights *(resolved)* | means ± SEM match | we run **no statistics and no BMD** on relative weights (no markers, BMD "ND"); published has markers and BMDs (Liver 191.4/127.6, Kidney-L 219.2/89.4, Kidney-R NVM) | builder computes relatives for display only |
| Trend markers (Jonckheere) *(Creatinine resolved by the tie-corrected Jonckheere, now `*`; AST remains, outlier step)* | every control-column marker on absolute values except two | Creatinine (pub * / ours none); AST (pub * on N=9 after outlier removal / ours none on N=10) | test or data difference (Creatinine); outlier step (AST) |
| Pairwise markers *(resolved)* | Cholesterol, Triglycerides, Urea N, Reticulocytes, Kidney-R abs | Liver abs 800 (pub ** / ours none), Kidney-L abs 400/800 (pub * / none), SDH (pub 800* / ours 400*), ALT 800 (pub * / none), Alk phos 800 (pub none / ours **), Bile acids 800 (pub none / ours *) | **Java Dunnett bug** + wrong test family (below) |
| Apical BMDs (ToxicR MA, 1 SD) | Liver abs 245/163, Kidney-L abs 259/94.3 (pub 93.3), Reticulocytes 437/307, SDH NVM | Cholesterol 449/291 vs **259.4/126.2**; Triglycerides 464/289 vs **489.4/332.3** | clinical chemistry BMR is 25% RD; G3 uses 1 SD. Refitting at 1 SD reproduces **259.438/126.155 and 489.433/332.328 exactly** |
| BMD summary rows *(resolved: 9 of 9, LOEL/NOEL exact)* | 5 of 9 endpoints | missing: 3 relative weights + Kidney-L abs (no pairwise significance in ours); every BMD renders "—" | relative-weight gap; Dunnett bug; inferred BMR config is render-gated when no apical `.bm2` config exists |
| Top 10 GO (5th pct), heart/kidney/liver/lung | **40/40 GO IDs in rank order; 40/40 BMD, BMDL and BMDU to 0.1 ppm; 40/40 gene counts (x/y)** | up/down counts agree in 15/40 rows (e.g. xenobiotic metabolism 18/2 vs ours 13/2) | we count direction by probe-name symbol lookup; published uses BMDExpress "Genes with Adverse Direction Up/Down" |
| NaN BMDU | – | published prints "NC" (non-convergent) | rendering |
| Most potent GO per tissue / tPOD | all 5 tissues (liver xenobiotic metabolic process 87.6 = tPOD) | | |
| Top 10 genes | BMDs of single-probe genes match exactly | 7–9/10 overlap per tissue | (1) published applies the BMDExpress gene filters (BMD/BMDL ≤ 10 etc.: drops SCD 4.6/0.43, ACAT2, RACGAP1, CYP1B1); (2) published is **gene-level**: probes map to Entrez genes, multi-probe genes take the median (Cyp2b1 69.9 = median(91.3, 48.4); Ugt2b1 105.4), and one probe can map to two genes (Ccnb2/Ccnb2-ps2, Cyp2c6/Loc100911718); (3) rat-case symbols + Entrez IDs; (4) newer annotation names (RGD1566401 → Meg3) |
| Ovary Top 10 GO | – | not in the package: `…Top_10_GO…Lung_Ovary_Rats.pdf` is actually the ovary Top 10 **genes** table | packaging defect |

## The Dunnett bug (affects every report, NIEHS-10 included)

`bmdx_pipe.apical_stats` takes pairwise p-values from sciome-commons-math `DunnettsTest` (math-1.04.0139, via `RunPrefilter.java`). That p-value is **not monotone in effect size**. Very large effects come back non-significant:

| effect (SD units), n=10 vs 5 | Java Dunnett p | scipy `stats.dunnett` p |
|---|---|---|
| 2 | 0.0066 | 0.0014 |
| 4 | 0.0 | 0.00002 |
| 5 | 0.11 | <1e-6 |
| 8 | 0.44 | <1e-6 |
| 12 | 0.99 | <1e-6 |

Liver absolute 800 ppm (11.50 vs 7.40 g, a 55% increase): Java p = 0.30, scipy p < 1e-6. For moderate effects the Java p-value is also about 4× too large. Away from both extremes the two implementations agree to 4 decimals.

## Test family (the methods footnote vs what we compute) *(resolved 2026-10-05)*

The published legends say **Jonckheere + Williams or Dunnett** for weights, and **Jonckheere + Shirley or Dunn** for clinical pathology. We always use Dunnett and label it "williams" when the trend is significant. The footnotes we print already match the published legends; the computation does not. Fixing the Dunnett bug alone will not reproduce the Kidney-L 400/800 `*` markers (scipy Dunnett p = 0.15/0.056), the SDH placement, or the Alk phos/bile acid non-significance. Those need Williams (weights) and Shirley/Dunn (clinical pathology), with the NTP rule for choosing between them.
