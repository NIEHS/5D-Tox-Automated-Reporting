# Published-study reports: build and QC, 2026-10-08

A report was generated for every downloaded published NIEHS package and put on
the Bookshelf. The QC then compared the rendered reports with the published ones.

- **Build:** `python -m tooling.build_published_reports --jobs 3`
- **QC:** `python -m tooling.report_qc` (writes `output/QC/qc-report.md`)

## On the shelf (14)

| report | DTXSID | chemical | era |
|---|---|---|---|
| RR-8 | DTXSID1021952 | Triphenyl Phosphate | G0, Affymetrix, BMDExpress 2.20 |
| NIEHS-02 | DTXSID1025300 | 2-Ethylhexyl Diphenyl Phosphate | G1, Affymetrix, BMDExpress 2.20 |
| NIEHS-03 | DTXSID6024701 | tert-Butylphenyl Diphenyl Phosphate | G1, Affymetrix, BMDExpress 2.30 |
| NIEHS-04 | DTXSID3025465 | Isodecyl Diphenyl Phosphate | G1, Affymetrix, BMDExpress 2.20 |
| NIEHS-05 | DTXSID4028880 | Isopropylated Phenyl Phosphate | G1, Affymetrix, BMDExpress 2.20 |
| NIEHS-06 | DTXSID4021391 | Tricresyl Phosphate | G1, Affymetrix, BMDExpress 2.20 |
| NIEHS-07 | DTXSID00190950 | 6:1 Fluorotelomer Alcohol | G2, TempO-Seq, BMDExpress 2.30 |
| NIEHS-08 | DTXSID2029905 | 1,1,2,2-Tetrahydroperfluoro-1-dodecanol | G2 |
| NIEHS-09 | DTXSID1022477 | 2,3-Benzofluorene | G2 |
| NIEHS-10 | DTXSID50469320 | Perfluorohexanesulfonamide | G2 |
| NIEHS-12 | DTXSID6020430 | 1,2-Dichlorobenzene (rat + mouse, 2026-10-11) | G3, TempO-Seq, BMDExpress 3.20 |
| NIEHS-13 | DTXSID1020431 | 1,4-Dichlorobenzene | G3 |
| — | DTXSID7037717 | Bisphenol AF | unpublished |
| — | DTXSID5032498 | Triclosan | unpublished |

## What the QC found, and what was fixed

- **Apical doses in the wrong unit (G0/G1).**
  - RR-8 and NIEHS-02 … 06 record apical doses in mmol/kg, and the reports labelled them mg/kg (LOEL 0.169 where NIEHS-02 publishes 61).
  - `cebs_to_pool --mg-per-kg-from` now converts them to the genomic project's mg/kg levels. A shared ratio is required, and it comes out at the molecular weight.
  - A level the project lacks is computed at that ratio. NIEHS-05 has no top-dose arrays.
- **Methods named the wrong platform and software.**
  - Every report said "BMDExpress 3, ToxicR model averaging, Curve Fit Prefilter, zero-count probes excluded". For BMDExpress 2.x projects the text now names the recorded version, the Williams fold filter and the best-model selection by lowest AIC, as published.
  - Zero-count exclusion is stated only when the data has no zero responses.
  - Microarray studies were described as TempO-Seq sequencing. Their Methods now describe hybridization and scanning, with the normalization as a placeholder.
- **Top-genes fold change printed 0.0 (BMDExpress 2.x).**
  - These projects record no fold change in their stat results.
  - It now comes from the Williams prefilter the analysis ran on (NIEHS-10 liver: Egr1 −4.218 → 4.2, as published).
- **Affymetrix probe sets printed as gene symbols** ("1368025_at", no Entrez ID, so no literature and empty References). The chip annotation now names the gene (Ddit4, 140942).
- **GO active genes in lower case** ("zfp36"). They now print in display case (Zfp36), as published.
- **G1 genomic experiment had no organ or sex** ("Unknown null", "Top 10 EDHP mg Genes"). The package records neither, and the reports state male rat liver. They are now stated with `generate_report --experiment-metadata`, recorded through the same approval path the browser uses.
- **Shared PFAS project.** NIEHS-07 … 10 share one 16-experiment project. `bmdx_pipe.subset_bm2` keeps only this chemical's experiments.
- **A test leak guard deleted live sessions.** It removed session dirs created during a test, which destroyed report builds running alongside the tests. It now only fails.

## Matches with the published report (after the fixes)

| report | BMD summary endpoints in both | **apical BMDs that agree (within 2%)** | LOEL/NOEL differences | GO top-10 matched | top genes matched |
|---|---|---|---|---|---|
| NIEHS-13 | 13 | **13** | 0 | 50/50 (0 BMD differences) | 50/50 (0 BMD or fold-change differences) |
| NIEHS-12 | 16 | **15** | 0 | 50/50 | 50/50 |
| NIEHS-10 | 10 | **4** | 0 | 36/40 | 40/40 |
| NIEHS-09 | 16 | **3** | 2 | 31/39 | 40/40 |
| NIEHS-08 | 18 | **3** | 4 | 34/40 | 40/40 |
| NIEHS-07 | 26 | **3** | 2 | 32/40 | 40/40 |
| NIEHS-06 | 8 | **1** | 0 | 2–7/10 | 0–4/10 |
| NIEHS-05 | 7 | **2** | 0 | 2–7/10 | 0–4/10 |
| NIEHS-04 | 7 | **1** | 0 | 2–7/10 | 0–4/10 |
| NIEHS-03 | 4 | **0** | 0 | 2–7/10 | 0–4/10 |
| NIEHS-02 | 6 | **2** | 0 | 2–7/10 | 0–4/10 |
| RR-8 | 8 | **1** | 0 | 2–7/10 | 0–4/10 |

*Corrected 2026-10-11.* This table first gave a single "BMD summary rows matched"
column. It counted the endpoints present in both tables, not equal values, so
"NIEHS-10: 10/10" read as a match when only 4 of those 10 BMDs agree. The QC also
filed BMD differences for RR-8 … NIEHS-10 as information rather than errors.

**Apical BMDs of RR-8 and NIEHS-02 … 10 do not reproduce the published ones: 20 of
110 agree.** Those reports used NTP's modified EPA BMDS 2.7 with high-dose dropping
(the `ntp-5day-2021` method profile); this tool does not implement that engine, so
the method profile substitutes BMDExpress 3 / ToxicR model averaging (ADR-0027). The
gaps are large — NIEHS-09 female TSH published 1.078, ours 147.4; RR-8 LDL
cholesterol published 213, ours 638 — and several endpoints the books flag NVM or
UREP get a BMD from us, or the reverse. The QC now reports this as two errors per
report: `method` (the profile asks for an engine this tool lacks) and `bmd_summary`
(every BMD more than 2% from the published). Implementing the BMDS 2.7 engine is
planned; each of these packages carries NTP's BMDS code and a fit-by-fit parameter
workbook to validate it against.

## Book structure against the published Bookshelf books (2026-10-09)

The structure YAML now matches the published BITS book one-to-one (ADR-0028), and the BITS emitter and Bookshelf facsimile follow it. All 14 reports were re-rendered. `report_qc` has a `structure` check, and `python -m tooling.bits_structure` prints the same diff.

- **Every book and every file of its chunked bundle** (the new `bits` surface, `<DTXSID>-bits.zip`) is DTD-valid and StyleChecker-clean.
- **NIEHS-07 … 10 have the published parts exactly.** That covers:
  - the full title;
  - the Foreword;
  - Authors / Contributors / Peer Review / Publication Details / Acknowledgments as typed front-matter parts;
  - five body parts with no repeated heading, and References last with numbered refs;
  - Table 1 inside "Sequencing Quality Checks";
  - appendices labelled "Appendix A" … with section labels C.1, C.2;
  - the abstract's four parts.

  The remaining 76–78 differing lines are content we do not produce:
  - no front matter supplied (report number → subtitle, author roster → contrib-group);
  - Appendix C (one PCA figure instead of four; no eFDR methods/results);
  - Appendix D (our acceptance/configuration tables instead of the model-selection rules and flowcharts);
  - Appendix F (55 supplied files as `<media>`; ours has F.1 text only);
  - NIEHS-07 … 09 have no Appendix A text.
- **NIEHS-12 and -13 (G3) differ in body structure, not only content (≈300 lines).** They have:
  - rat and mouse subsections;
  - exposure-system and vapor-monitoring sections;
  - per-organ genomics sections;
  - theoretical inhaled dose;
  - five appendices of chemistry and internal concentration.

  This is G3 conformance gap 8 ("structure") and needs a 2026 report-type template. *(Done the same day: see the next section.)*
- **RR-8 and NIEHS-02 … 06 are not compared.** They are older single-part books (one `book-part` with sections inside), a layout ours does not follow. *(Done the same day: see the next section.)*
- **Abstract Methods shows as pending in every report.** The abstract-overlay call that builds it never produces text. This is a content fix.

## Each report from its own document definition (2026-10-09, ADR-0029)

Each published report now renders from its own definition,
`templates/studies/<DTXSID>/document.yaml`. That file extends its generation's
base in `templates/eras/` and states only how the report differs:

| Era | Reports | Packaging |
|---|---|---|
| `ntp-rr-2018` | RR-8 | single-file, NTP Research Report series |
| `niehs-2022` | NIEHS-02 … 06 | single-file |
| `niehs-2023` | NIEHS-07 … 10 | chunked |
| `niehs-2026` | NIEHS-12, 13 | chunked |

All 12 were re-rendered (docx, html, jats, bits, pdf). Every BITS book is
DTD-valid and StyleChecker-clean.

**Section structure against the published books:**
- **RR-8 and NIEHS-02 … 10:** identical. What still differs is content and
  objects:
  - the title (sex and strain form; RR-8's NTP wording);
  - the report number and authors;
  - the 2022 Appendix B and RR-8 B/C/E tables;
  - the F file lists (`<media>`);
  - the 2023 per-tissue PCA and eFDR objects.
  Unlike the earlier comparison, NIEHS-07 … 09 now have A.1 and Appendix D
  follows the published structure. The BMDS flowcharts are pending: our
  pipeline does not run BMDS 2.7.
- **NIEHS-12 and 13:** 65 section lines differ. All of them are:
  - per-species or per-tissue sections (Rats/Mice; Heart … Ovary), which the
    data must supply (G3 gap 5: one species is modelled);
  - Appendix B's method sections, which are the study's own content.

**Supplemental Data (2026-10-10).** The F/G file lists now come from each
study's data deposit (`pipeline/deposit.py`). After a re-render, every
published file entry (33, 55, 143 or 144 per book; 672 in all) is in our book,
in the same section. NIEHS-12/13's per-species G.3 Rats / G.4 Mice come from
the deposit. Their remaining differences fall from 65 section lines to 45:
the Methods/Results species and tissue sections, and Appendix B. Captions
default to the file name. Where the 2023 books edited a caption by hand,
it's study content (NIEHS-10's 13 are in `templates/studies/DTXSID50469320/deposit.yaml`).

**Rats and mice (2026-10-11, ADR-0029 §9).** NIEHS-12 and 13 are now built
over both of their studies. Each study is its own session (`<DTXSID>_rat`,
`<DTXSID>_mouse`), and the report session lists them in `studies.json`.
- The combined tables group rows by study, with NA for a dose a study did not
  test.
- The per-study and per-tissue sections are repeats in `eras/niehs-2026`. The
  tissues follow the definition's `tissue_order`: alphabetical in 2026,
  Liver then Kidney in 2023.
- Genomic tables are numbered where their section stands, so the internal
  concentration tables follow them.

What remains different from the published books:
- **Content and data gaps:**
  - the title's "Female" and "Whole-body";
  - Table 12 (most potent GO per tissue) and Table 18 (theoretical inhaled
    dose), which we don't produce, so the internal concentration tables are
    17/18 rather than 19/20;
  - Appendix A–B content, the D PCA figures, and the E tables.
- **Placement:** the published books put the combined Tables 2–5 inside the
  Rats sub-section, where the tables are first cited. Ours put them at the
  head of the section.
- **Abstract length:** each study's abstract states its individual genes per
  tissue, which the 2026 books leave out. Together the abstract exceeds
  Bookshelf's 9,900-character limit (StyleChecker error).

The BMD summary matches the published table for NIEHS-13: 13/13 rows across
rats and mice, with no BMD or LOEL/NOEL differences. NIEHS-12 matches 16/22
rows: A/G ratio, terminal body weight and the study-day body weights are
missing, and one BMD differs (mouse relative right kidney weight).

`tests/unit/test_report_definitions.py` checks the outlines (file entries
included), the DTD and each book's series ISSN. The ISSN is per book: NIEHS-02 … 04, 07, 08 and RR-8 carry
2473-4756.

## Still open (ranked)

1. **G0/G1 genomic reporting rules are not implemented.**
   - The 2018 reports work at the gene level: probes are filtered on fit, the gene BMD is the median of its probes' BMDs, and a BMD below ⅓ of the lowest dose prints as "<20.3 (NR)".
   - We print the per-probe best fit, which gives degenerate BMDs of 0.000 for the top probes, so GO and top-genes overlap is low.
   - Fixing this needs an `ntp-5day-2018` method profile and gene-level aggregation from the per-probe results.
2. **Derived apical endpoints are missing.** A/G ratio, Globulin and Terminal Body Weight are in most published BMD summaries and not in ours. NIEHS-12 also lacks Body Weight on study day 4.
3. **A few LOEL/NOEL differences in G2:**
   - NIEHS-07 male creatinine;
   - NIEHS-08 female alkaline phosphatase and monocytes;
   - NIEHS-09 male total T4.

   This is probably the trend/pairwise test choice for those endpoints.
4. ~~**Methods headings for microarray studies**~~ Fixed 2026-10-09: the 2022 and 2018 era definitions give the microarray Methods ("RNA Isolation and cDNA Synthesis", "Analysis of GeneChip Data Quality").
5. **Presentation differences:**
   - published G2 prints BMDs to 3 decimals and we print 1 (`report_bmd_decimals` keys on gene-level analyses, which the CEBS NIEHS-10 project has);
   - published G1 prints doses as integers.
6. **Background: done for the 12 published studies (2026-10-09).** EPA IRIS (`cfpub.epa.gov`) became reachable. The CompTox hazard API (`api-ccte.epa.gov`) is still blocked, and the Background is written without it.
   - Each Background is 7 paragraphs, 1,000–1,600 words, with 2–5 references.
   - NIEHS-10's old Background (2026-09-24) said "CASRN: not available" and was replaced. A copy is in `output/_session_backups/background-pre-2026-10-09/`.
   - BPAF and Triclosan got theirs on 2026-10-09 too. The app's LLM calls only go to the NIEHS toxpipe gateway (the egress guard), and the Background prompt carries only public chemical data. The CDC/ATSDR hosts were intermittent: Triclosan needed a second run.
   - **About This Report** authors are pending in all reports.
7. **The genomics narrative coins its own abbreviation** ("EHDPP") instead of the stated short name (EHDP).
8. **A pre-existing test failure:** `tests/unit/test_docx_generator.py::test_yaml_page_breaks_land_as_page_break_before` fails at HEAD too.
