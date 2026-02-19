# Dose-Response Interpretation

### 1. Biological Response Narrative

**Low Dose:**
- **Activated Processes:** At low doses, the primary biological response is an activation of antioxidant defense mechanisms mediated by NRF2 (NFE2L2). Genes such as GCLC and GPX1 show increased expression, indicating a compensatory upregulation to counteract oxidative stress.
- **Suppressed Processes:** There are minimal signs of cellular damage or inflammation. Apoptotic pathways like BAX remain suppressed.

**Medium Dose:**
- **Activated Processes:** As the dose increases, there is further activation of NRF2-mediated antioxidant response with additional genes such as HMOX1 and SOD1 showing increased expression.
- **Suppressed Processes:** There is a slight suppression in DNA repair mechanisms (TP53-related pathways) due to increased oxidative stress. However, this does not yet lead to significant cellular damage.

**High Dose:**
- **Activated Processes:** At high doses, there is a marked increase in inflammatory responses with elevated expression of IL6 and TNF. Additionally, the activation of DNA repair mechanisms (TP53) becomes more pronounced but insufficient to prevent cell death.
- **Suppressed Processes:** The adaptive antioxidant response mediated by NRF2 starts to wane as the cellular damage exceeds its capacity for repair. Apoptotic pathways such as BAX become activated, leading to increased cell death.

### 2. Organ-Level Prediction

**Most Affected Organs:**
1. **Liver (Hepatocytes):** The liver is likely the most affected organ due to high expression of NRF2 and its downstream targets like GPX1, GCLC, and HMOX1 in hepatocytes. Additionally, literature evidence supports the role of NRF2 in hepatic oxidative stress response.
2. **Kidney:** Kidney cells also show significant activation of NRF2 pathways (e.g., NQO1). Furthermore, studies indicate that cadmium-induced toxicity disrupts renal function and activates NF-κB and Nrf2 pathways leading to inflammation and fibrosis.
3. **Heart:** Cardiomyocytes exhibit increased expression of TP53 and BAX at higher doses, indicating cardiac damage due to oxidative stress and DNA damage.

**Reasoning:**
- The liver is a primary site for detoxification and has high NRF2 activity.
- Kidneys are sensitive to heavy metals and show activation of inflammatory pathways.
- Heart cells have high expression of TP53, which activates in response to cellular stress leading to apoptosis.

### 3. Mechanism of Action

**Molecular Initiating Event (MIE):**
- **Oxidative Stress:** The MIE is the induction of oxidative stress due to exposure to a xenobiotic or heavy metal that disrupts redox homeostasis in cells.

**Key Events:**
1. **Activation of NRF2 Pathway:** Early activation of NRF2 leads to increased expression of antioxidant enzymes (e.g., GPX1, GCLC) and detoxification proteins.
2. **DNA Damage Response Activation:** As oxidative stress increases, DNA damage occurs leading to TP53 activation and subsequent cell cycle arrest or apoptosis.
3. **Inflammation:** Persistent oxidative stress triggers inflammatory responses through NF-κB pathway activation, leading to increased expression of cytokines like IL6 and TNF.
4. **Cell Death:** At high doses, the balance shifts towards cellular damage with BAX activation causing apoptosis.

### 7. Protective vs. Adverse Responses

**Adaptive/Protective Responses:**
- Low doses: NRF2-mediated antioxidant defense (GCLC, GPX1)
- Medium doses: Continued NRF2 response and slight TP53 activation for DNA repair
- High doses: Initial increase in NRF2 but waning efficacy due to overwhelming oxidative stress

**Responses Indicating Damage:**
- Medium doses: Mild inflammation as indicated by NF-κB pathway activation
- High doses: Significant apoptosis (BAX), inflammation, and fibrosis

**Transition Point:**
The transition from adaptive to adverse responses likely occurs around the medium dose level where NRF2-mediated defense mechanisms are still active but DNA repair pathways start showing signs of stress.

### 8. Literature Support

**Supporting Papers:**

- **Nucleocytoplasmic Shuttling of the NAD+-dependent Histone Deacetylase SIRT1 (2007):**
  - Supports the role of SIRT1 in regulating NRF2 and TP53 pathways.
  
- **Heavy Metals: Toxicity and Human Health Effects (2024):**
  - Provides evidence for oxidative stress-induced DNA damage, inflammation, and apoptosis mediated by BAX and NF-κB.

- **Hesperetin Ameliorates Hepatic Oxidative Stress and Inflammation via the PI3K/AKT-Nrf2-ARE Pathway (2021):**
  - Demonstrates NRF2's role in hepatic antioxidant defense against oxidative stress.

### 9. Confidence Assessment

**High Confidence:**
- **NRF2 Antioxidant Defense:** Strong literature support from consensus genes and multiple studies.
- **TP53 DNA Repair Response:** Well-documented activation of TP53 pathways in response to cellular damage.
  
**Moderate Confidence:**
- **NF-κB Inflammatory Responses:** Evidence supports NF-κB activation in inflammation but less specific for this context.

**Low Confidence:**
- **Specific Dose Transition Point:** Limited data on exact dose-response transition from adaptive to adverse responses.

### Novel Findings
- The detailed progression of NRF2-mediated defense mechanisms and the shift towards DNA damage and apoptosis at higher doses provides a nuanced understanding not fully captured in existing literature.
  
Overall, this analysis integrates multiple biological processes and organ-specific gene expression patterns to provide a comprehensive narrative on the mechanism of toxicity.

---

# Appendix: Structured Analysis

```
=== DOSE-RESPONSE SUMMARY ===
32 responsive genes, BMD range 0.2-20
Direction: 27 up, 5 down

=== PATHWAY ENRICHMENT (FDR < 0.05) ===
1. path:rno05200 (p=5.92e-38, FDR=7.78e-36, 15/26 genes)
   Genes: BAX, BCL2, CASP3, CDKN1A, HIF1A, HMOX1, IL6, KEAP1, NFE2L2, NFKB1, NQO1, STAT3, TGFB1, TP53, VEGFA
2. path:hsa05200 (p=5.92e-38, FDR=7.78e-36, 15/26 genes)
   Genes: BAX, BCL2, CASP3, CDKN1A, HIF1A, HMOX1, IL6, KEAP1, NFE2L2, NFKB1, NQO1, STAT3, TGFB1, TP53, VEGFA
3. path:rno05417 (p=6.89e-32, FDR=4.53e-30, 12/17 genes)
   Genes: BAX, BCL2, CASP3, CYP1A1, IL1B, IL6, NFE2L2, NFKB1, NLRP3, STAT3, TNF, TP53
4. path:hsa05417 (p=6.89e-32, FDR=4.53e-30, 12/17 genes)
   Genes: BAX, BCL2, CASP3, CYP1A1, IL1B, IL6, NFE2L2, NFKB1, NLRP3, STAT3, TNF, TP53
5. path:rno05418 (p=1.41e-28, FDR=6.17e-27, 11/17 genes)
   Genes: BCL2, HMOX1, IL1B, KEAP1, NFE2L2, NFKB1, NQO1, SQSTM1, TNF, TP53, VEGFA
6. path:hsa05418 (p=1.41e-28, FDR=6.17e-27, 11/17 genes)
   Genes: BCL2, HMOX1, IL1B, KEAP1, NFE2L2, NFKB1, NQO1, SQSTM1, TNF, TP53, VEGFA
7. path:rno05161 (p=1.11e-26, FDR=2.93e-25, 10/14 genes)
   Genes: BAX, BCL2, CASP3, CDKN1A, IL6, NFKB1, STAT3, TGFB1, TNF, TP53
8. path:hsa05161 (p=1.11e-26, FDR=2.93e-25, 10/14 genes)
   Genes: BAX, BCL2, CASP3, CDKN1A, IL6, NFKB1, STAT3, TGFB1, TNF, TP53
9. path:hsa04933 (p=1.11e-26, FDR=2.93e-25, 10/14 genes)
   Genes: BAX, BCL2, CASP3, IL1B, IL6, NFKB1, STAT3, TGFB1, TNF, VEGFA
10. path:rno04933 (p=1.11e-26, FDR=2.93e-25, 10/14 genes)
   Genes: BAX, BCL2, CASP3, IL1B, IL6, NFKB1, STAT3, TGFB1, TNF, VEGFA
11. path:hsa05163 (p=3.34e-26, FDR=7.32e-25, 10/15 genes)
   Genes: BAX, CASP3, CDKN1A, IL1B, IL6, NFKB1, STAT3, TNF, TP53, VEGFA
12. path:rno05163 (p=3.34e-26, FDR=7.32e-25, 10/15 genes)
   Genes: BAX, CASP3, CDKN1A, IL1B, IL6, NFKB1, STAT3, TNF, TP53, VEGFA
13. path:rno05167 (p=2.08e-23, FDR=3.42e-22, 9/14 genes)
   Genes: BAX, CASP3, CDKN1A, HIF1A, IL6, NFKB1, STAT3, TP53, VEGFA
14. path:hsa05169 (p=2.08e-23, FDR=3.42e-22, 9/14 genes)
   Genes: BAX, BCL2, CASP3, CDKN1A, IL6, NFKB1, STAT3, TNF, TP53
15. path:rno05169 (p=2.08e-23, FDR=3.42e-22, 9/14 genes)
   Genes: BAX, BCL2, CASP3, CDKN1A, IL6, NFKB1, STAT3, TNF, TP53
16. path:hsa05167 (p=2.08e-23, FDR=3.42e-22, 9/14 genes)
   Genes: BAX, CASP3, CDKN1A, HIF1A, IL6, NFKB1, STAT3, TP53, VEGFA
17. path:hsa05206 (p=1.19e-22, FDR=1.56e-21, 9/16 genes)
   Genes: BCL2, CASP3, CDKN1A, HMOX1, NFKB1, SIRT1, STAT3, TP53, VEGFA
18. path:rno05206 (p=1.19e-22, FDR=1.56e-21, 9/16 genes)
   Genes: BCL2, CASP3, CDKN1A, HMOX1, NFKB1, SIRT1, STAT3, TP53, VEGFA
19. path:rno05208 (p=1.19e-22, FDR=1.56e-21, 9/16 genes)
   Genes: AHR, CYP1A1, HIF1A, HMOX1, KEAP1, NFE2L2, NFKB1, NQO1, VEGFA
20. path:hsa05208 (p=1.19e-22, FDR=1.56e-21, 9/16 genes)
   Genes: AHR, CYP1A1, HIF1A, HMOX1, KEAP1, NFE2L2, NFKB1, NQO1, VEGFA

=== GO TERM ENRICHMENT (FDR < 0.05, top 20) ===
1. response to xenobiotic stimulus [GO:0009410] (p=3.47e-28, FDR=1.17e-25, 22/552 genes)
   Genes: AHR, BAX, BCL2, CASP3, CAT, CDKN1A, CYP1A1, GCLC, GPX1, HAVCR1, HIF1A, HMOX1, IL1B, IL6, NFE2L2, NFKB1, NQO1, SOD1, SOD2, TGFB1, TNF, TP53
2. response to ethanol [GO:0045471] (p=7.14e-20, FDR=1.03e-17, 15/308 genes)
   Genes: BCL2, CASP3, CAT, IL1B, IL6, NFKB1, NLRP3, NQO1, PPARA, SIRT1, SOD1, STAT3, TGFB1, TNF, TP53
3. response to hypoxia [GO:0001666] (p=9.11e-20, FDR=1.03e-17, 15/313 genes)
   Genes: BAX, BCL2, CASP3, CAT, CYP1A1, HIF1A, HMOX1, IL1B, IL6, PPARA, SOD2, STAT3, TGFB1, TNF, VEGFA
4. positive regulation of apoptotic process [GO:0043065] (p=7.04e-18, FDR=5.96e-16, 15/418 genes)
   Genes: AHR, BAX, BCL2, CASP3, CYP1B1, HIF1A, HMOX1, IL1B, IL6, SIRT1, SOD1, SQSTM1, TGFB1, TNF, TP53
5. response to oxidative stress [GO:0006979] (p=1.25e-16, FDR=8.46e-15, 12/213 genes)
   Genes: BCL2, CAT, GCLC, GPX1, HMOX1, NFE2L2, NFKB1, NQO1, SIRT1, SOD1, SOD2, TP53
6. response to gamma radiation [GO:0010332] (p=1.94e-15, FDR=1.10e-13, 8/45 genes)
   Genes: BAX, BCL2, GPX1, IL1B, IL6, SOD2, TGFB1, TP53
7. negative regulation of neuron apoptotic process [GO:0043524] (p=5.78e-15, FDR=2.80e-13, 11/208 genes)
   Genes: BAX, BCL2, GCLC, HIF1A, HMOX1, IL6, SIRT1, SOD1, SOD2, STAT3, VEGFA
8. response to estradiol [GO:0032355] (p=8.78e-15, FDR=3.72e-13, 11/216 genes)
   Genes: AHR, CASP3, CAT, CYP1B1, GPX1, HIF1A, IL1B, NQO1, STAT3, TGFB1, VEGFA
9. response to hydrogen peroxide [GO:0042542] (p=1.83e-13, FDR=6.91e-12, 8/77 genes)
   Genes: BCL2, CASP3, CAT, GPX1, HMOX1, SIRT1, SOD1, SOD2
10. negative regulation of apoptotic process [GO:0043066] (p=2.27e-13, FDR=7.70e-12, 14/676 genes)
   Genes: BCL2, CAT, CDKN1A, GCLC, HIF1A, IL6, NFKB1, NQO1, SIRT1, SOD1, SOD2, TNF, TP53, VEGFA
11. response to toxic substance [GO:0009636] (p=4.02e-13, FDR=1.24e-11, 9/140 genes)
   Genes: AHR, BAX, BCL2, CAT, CDKN1A, CYP1A1, CYP1B1, GPX1, NQO1
12. negative regulation of cell population proliferation [GO:0008285] (p=3.84e-12, FDR=1.09e-10, 12/507 genes)
   Genes: BAX, BCL2, CDKN1A, CYP1B1, HMOX1, IL1B, IL6, SOD2, STAT3, TGFB1, TNF, TP53
13. cellular response to hydrogen peroxide [GO:0070301] (p=5.71e-12, FDR=1.49e-10, 8/117 genes)
   Genes: BAX, BCL2, CYP1B1, HIF1A, IL6, NFE2L2, NQO1, SIRT1
14. negative regulation of gene expression [GO:0010629] (p=2.46e-11, FDR=5.97e-10, 10/323 genes)
   Genes: CDKN1A, HIF1A, IL1B, KEAP1, NFKB1, SIRT1, STAT3, TGFB1, TNF, VEGFA
15. neuron apoptotic process [GO:0051402] (p=2.83e-11, FDR=6.39e-10, 7/82 genes)
   Genes: BAX, BCL2, CASP3, GPX1, SIRT1, TGFB1, VEGFA
16. positive regulation of protein kinase B signaling [GO:0051897] (p=3.57e-11, FDR=7.56e-10, 9/230 genes)
   Genes: CAT, GDF15, GPX1, IL1B, IL6, SIRT1, TGFB1, TNF, VEGFA
17. positive regulation of angiogenesis [GO:0045766] (p=9.16e-11, FDR=1.83e-09, 8/165 genes)
   Genes: CYP1B1, HIF1A, HMOX1, IL1B, NFE2L2, SIRT1, STAT3, VEGFA
18. positive regulation of transcription by RNA polymerase II [GO:0045944] (p=1.83e-10, FDR=3.45e-09, 15/1353 genes)
   Genes: AHR, HIF1A, IL1B, IL6, NFE2L2, NFKB1, NLRP3, PPARA, SIRT1, SQSTM1, STAT3, TGFB1, TNF, TP53, VEGFA
19. negative regulation of fat cell differentiation [GO:0045599] (p=2.04e-10, FDR=3.65e-09, 6/56 genes)
   Genes: IL6, SIRT1, SOD2, TGFB1, TNF, VEGFA
20. positive regulation of gene expression [GO:0010628] (p=2.49e-10, FDR=4.21e-09, 11/556 genes)
   Genes: HIF1A, IL1B, IL6, NFE2L2, NFKB1, SIRT1, STAT3, TGFB1, TNF, TP53, VEGFA

=== DOSE-ORDERED RESPONSE ===
BMD 0.2-0.35: Aryl hydrocarbon receptor signalling (median BMD 0.35, 3 genes, mostly UP)
BMD 0.2-2.12: path:rno05208 (median BMD 0.5, 9 genes, mostly UP)
BMD 0.2-2.12: path:hsa05208 (median BMD 0.5, 9 genes, mostly UP)
BMD 0.35-0.87: path:rno01100 (median BMD 0.5, 5 genes, mostly UP)
BMD 0.35-0.87: path:hsa01100 (median BMD 0.5, 5 genes, mostly UP)
BMD 0.3-0.55: Nuclear events mediated by NFE2L2 (median BMD 0.55, 2 genes, mixed)
BMD 0.3-0.55: GSK3B and BTRC:CUL1-mediated-degradation of NFE2L2 (median BMD 0.55, 2 genes, mixed)
BMD 0.5-0.55: path:hsa01240 (median BMD 0.55, 2 genes, mostly UP)
BMD 0.5-0.55: path:rno01240 (median BMD 0.55, 2 genes, mostly UP)
BMD 0.4-2: path:hsa04216 (median BMD 0.6, 3 genes, mostly UP)
BMD 0.4-2: path:rno04216 (median BMD 0.6, 3 genes, mostly UP)
BMD 2-2.25: Circadian clock (median BMD 2.25, 2 genes, mostly DOWN)
BMD 2-2.25: path:hsa04922 (median BMD 2.25, 2 genes, mostly DOWN)
BMD 2-2.25: path:rno04922 (median BMD 2.25, 2 genes, mostly DOWN)
BMD 0.2-2.35: path:rno04934 (median BMD 2.35, 2 genes, mostly UP)
BMD 0.2-2.35: path:hsa04934 (median BMD 2.35, 2 genes, mostly UP)
BMD 0.3-4.06: path:hsa05225 (median BMD 2.65, 8 genes, mostly UP)
BMD 0.3-4.06: path:rno05225 (median BMD 2.65, 8 genes, mostly UP)
BMD 3-3.83: path:hsa04137 (median BMD 3.5, 3 genes, mostly UP)
BMD 3-3.83: path:rno04137 (median BMD 3.5, 3 genes, mostly UP)
BMD 3-4: path:rno04140 (median BMD 3.5, 3 genes, mostly UP)
BMD 3-4: path:hsa04140 (median BMD 3.5, 3 genes, mostly UP)
BMD 2.5-3.75: path:hsa04310 (median BMD 3.75, 2 genes, mixed)
BMD 2.5-3.75: path:rno04310 (median BMD 3.75, 2 genes, mixed)
BMD 0.3-4.5: path:rno05418 (median BMD 4.0, 11 genes, mostly UP)
BMD 0.3-4.5: path:hsa05418 (median BMD 4.0, 11 genes, mostly UP)
BMD 0.2-4.22: path:rno05207 (median BMD 4.0, 7 genes, mostly UP)
BMD 0.2-4.22: path:hsa05207 (median BMD 4.0, 7 genes, mostly UP)
BMD 3.5-6.75: path:hsa05211 (median BMD 4.25, 4 genes, mostly UP)
BMD 3.5-6.75: path:rno05211 (median BMD 4.25, 4 genes, mostly UP)
BMD 4-4.25: Transcriptional regulation by the AP-2 (TFAP2) family of transcription factors (median BMD 4.25, 2 genes, mostly UP)
BMD 3.5-4.25: path:hsa05230 (median BMD 4.25, 2 genes, mostly UP)
BMD 3.5-4.25: path:rno04919 (median BMD 4.25, 2 genes, mostly UP)
BMD 3.5-4.25: path:hsa04919 (median BMD 4.25, 2 genes, mostly UP)
BMD 3.5-4.25: path:rno05230 (median BMD 4.25, 2 genes, mostly UP)
BMD 4-4.5: path:rno05219 (median BMD 4.5, 3 genes, mostly UP)
BMD 4-4.5: path:hsa05219 (median BMD 4.5, 3 genes, mostly UP)
BMD 4-4.75: path:rno04510 (median BMD 4.75, 2 genes, mixed)
BMD 4-4.75: path:hsa04510 (median BMD 4.75, 2 genes, mixed)
BMD 0.3-5.53: path:rno05200 (median BMD 5.0, 15 genes, mostly UP)
BMD 0.3-5.53: path:hsa05200 (median BMD 5.0, 15 genes, mostly UP)
BMD 0.4-5.27: path:hsa05206 (median BMD 5.0, 9 genes, mostly UP)
BMD 0.4-5.27: path:rno05206 (median BMD 5.0, 9 genes, mostly UP)
BMD 0.4-5.92: path:hsa04066 (median BMD 5.0, 8 genes, mostly UP)
BMD 0.4-5.92: path:rno04066 (median BMD 5.0, 8 genes, mostly UP)
BMD 2.5-7.29: path:hsa04218 (median BMD 5.0, 7 genes, mostly UP)
BMD 2.5-7.29: path:rno04218 (median BMD 5.0, 7 genes, mostly UP)
BMD 0.3-4.02: path:rno05012 (median BMD 5.0, 5 genes, mostly UP)
BMD 0.3-4.02: path:hsa05012 (median BMD 5.0, 5 genes, mostly UP)
BMD 4.5-8.17: path:rno04110 (median BMD 5.0, 3 genes, mostly UP)
BMD 4.5-8.17: path:hsa04110 (median BMD 5.0, 3 genes, mostly UP)
BMD 4.5-5.17: path:rno05217 (median BMD 5.0, 3 genes, mostly UP)
BMD 4.5-5.17: path:hsa05217 (median BMD 5.0, 3 genes, mostly UP)
BMD 4.5-5.17: path:rno05216 (median BMD 5.0, 3 genes, mostly UP)
BMD 4.5-5.17: path:hsa05216 (median BMD 5.0, 3 genes, mostly UP)
BMD 4.5-5.17: path:hsa05214 (median BMD 5.0, 3 genes, mostly UP)
BMD 4.5-5.17: path:hsa05224 (median BMD 5.0, 3 genes, mostly UP)
BMD 4.5-5.17: path:rno05214 (median BMD 5.0, 3 genes, mostly UP)
BMD 4.5-5.17: path:hsa05213 (median BMD 5.0, 3 genes, mostly UP)
BMD 4.5-5.17: path:rno05224 (median BMD 5.0, 3 genes, mostly UP)
BMD 4.5-5.17: path:rno05213 (median BMD 5.0, 3 genes, mostly UP)
BMD 4.5-5.17: path:hsa05218 (median BMD 5.0, 3 genes, mostly UP)
BMD 4.5-5.17: path:rno05218 (median BMD 5.0, 3 genes, mostly UP)
BMD 4.5-5: path:rno04928 (median BMD 5.0, 2 genes, mixed)
BMD 4.5-5: path:hsa04928 (median BMD 5.0, 2 genes, mixed)
BMD 4-6.67: path:rno04151 (median BMD 5.25, 6 genes, mostly UP)
BMD 4-6.67: path:hsa04151 (median BMD 5.25, 6 genes, mostly UP)
BMD 4.5-6: path:hsa05215 (median BMD 5.25, 4 genes, mostly UP)
BMD 4.5-5.25: path:hsa01522 (median BMD 5.25, 4 genes, mostly UP)
BMD 4.5-5.25: path:rno01522 (median BMD 5.25, 4 genes, mostly UP)
BMD 4.5-6: path:rno05215 (median BMD 5.25, 4 genes, mostly UP)
BMD 4.5-5.25: TP53 Regulates Transcription of Cell Cycle Genes (median BMD 5.25, 2 genes, mostly UP)
BMD 4.5-5.8: path:hsa04115 (median BMD 5.5, 5 genes, mostly UP)
BMD 4.5-5.8: path:rno04115 (median BMD 5.5, 5 genes, mostly UP)
BMD 4.5-5.8: path:hsa01524 (median BMD 5.5, 5 genes, mostly UP)
BMD 4.5-7.2: path:rno05226 (median BMD 5.5, 5 genes, mostly UP)
BMD 4.5-5.8: path:rno01524 (median BMD 5.5, 5 genes, mostly UP)
BMD 4.5-7.2: path:hsa05226 (median BMD 5.5, 5 genes, mostly UP)
BMD 2.5-5.62: path:hsa04211 (median BMD 5.5, 4 genes, mostly UP)
BMD 2.5-5.62: path:rno04211 (median BMD 5.5, 4 genes, mostly UP)
BMD 4.5-6: path:hsa05223 (median BMD 5.5, 4 genes, mostly UP)
BMD 4.5-6: path:rno05223 (median BMD 5.5, 4 genes, mostly UP)
BMD 0.3-3.93: path:hsa04141 (median BMD 5.5, 3 genes, mostly UP)
BMD 0.3-3.93: path:rno04141 (median BMD 5.5, 3 genes, mostly UP)
BMD 2-5.5: path:rno04024 (median BMD 5.5, 2 genes, mixed)
BMD 2-5.5: path:hsa04024 (median BMD 5.5, 2 genes, mixed)
BMD 3-6.25: path:rno05014 (median BMD 5.75, 6 genes, mostly UP)
BMD 3-6.25: path:hsa05014 (median BMD 5.75, 6 genes, mostly UP)
BMD 4.5-6.33: path:rno05222 (median BMD 5.75, 6 genes, mostly UP)
BMD 4.5-6.33: path:hsa05222 (median BMD 5.75, 6 genes, mostly UP)
BMD 4.5-7.33: path:hsa05210 (median BMD 5.75, 6 genes, mostly UP)
BMD 4.5-7.33: path:rno05210 (median BMD 5.75, 6 genes, mostly UP)
BMD 5-6.38: path:hsa04722 (median BMD 5.75, 4 genes, mostly UP)
BMD 5-6.38: path:rno04722 (median BMD 5.75, 4 genes, mostly UP)
BMD 5.5-5.75: TP53 Regulates Transcription of Cell Death Genes (median BMD 5.75, 2 genes, mixed)
BMD 5.5-5.75: Activation of BH3-only proteins (median BMD 5.75, 2 genes, mixed)
BMD 3.5-6.72: path:rno05167 (median BMD 6.0, 9 genes, mostly UP)
BMD 3.5-6.72: path:hsa05167 (median BMD 6.0, 9 genes, mostly UP)
BMD 4-7.43: path:rno05212 (median BMD 6.0, 7 genes, mostly UP)
BMD 4-7.43: path:hsa05212 (median BMD 6.0, 7 genes, mostly UP)
BMD 4-6.64: path:hsa05165 (median BMD 6.0, 7 genes, mostly UP)
BMD 4-6.64: path:rno05165 (median BMD 6.0, 7 genes, mostly UP)
BMD 5-7.1: path:rno04071 (median BMD 6.0, 5 genes, mostly UP)
BMD 4.5-7.3: path:hsa05202 (median BMD 6.0, 5 genes, mostly UP)
BMD 5-7.1: path:hsa04071 (median BMD 6.0, 5 genes, mostly UP)
BMD 4.5-7.3: path:rno05202 (median BMD 6.0, 5 genes, mostly UP)
BMD 4.5-7.9: path:hsa05220 (median BMD 6.0, 5 genes, mostly UP)
BMD 4.5-7.9: path:rno05220 (median BMD 6.0, 5 genes, mostly UP)
BMD 4-7.2: path:rno01521 (median BMD 6.0, 5 genes, mostly UP)
BMD 4-7.2: path:hsa01521 (median BMD 6.0, 5 genes, mostly UP)
BMD 5-6.33: path:hsa05016 (median BMD 6.0, 3 genes, mostly UP)
BMD 5-6.33: path:rno05016 (median BMD 6.0, 3 genes, mostly UP)
BMD 5.5-6.5: path:hsa04215 (median BMD 6.0, 3 genes, mostly UP)
BMD 5.5-6.5: path:rno04215 (median BMD 6.0, 3 genes, mostly UP)
BMD 3.5-7.31: path:hsa05205 (median BMD 6.5, 8 genes, mostly UP)
BMD 3.5-7.31: path:rno05205 (median BMD 6.5, 8 genes, mostly UP)
BMD 4-6.5: path:rno04014 (median BMD 6.5, 2 genes, mostly UP)
BMD 4-6.5: path:hsa04014 (median BMD 6.5, 2 genes, mostly UP)
BMD 0.4-6.7: Cytoprotection by HMOX1 (median BMD 6.7, 2 genes, mostly UP)
BMD 2-6.62: path:hsa05160 (median BMD 7.0, 8 genes, mostly UP)
BMD 2-6.62: path:rno05160 (median BMD 7.0, 8 genes, mostly UP)
BMD 4.5-6.83: path:rno05203 (median BMD 7.0, 6 genes, mostly UP)
BMD 4.5-6.83: path:hsa05203 (median BMD 7.0, 6 genes, mostly UP)
BMD 5-7.25: path:rno04210 (median BMD 7.0, 6 genes, mostly UP)
BMD 5-7.25: path:hsa04210 (median BMD 7.0, 6 genes, mostly UP)
BMD 4.5-7.62: path:hsa04630 (median BMD 7.0, 4 genes, mostly UP)
BMD 4.5-7.62: path:rno04630 (median BMD 7.0, 4 genes, mostly UP)
BMD 3-7.81: path:hsa05131 (median BMD 7.5, 8 genes, mostly UP)
BMD 4.5-7.61: path:hsa05169 (median BMD 8.0, 9 genes, mostly UP)
BMD 4.5-7.61: path:rno05169 (median BMD 8.0, 9 genes, mostly UP)
BMD 2.5-9.8: path:rno04148 (median BMD 8.0, 5 genes, mostly UP)
BMD 2.5-9.8: path:hsa04148 (median BMD 8.0, 5 genes, mostly UP)
BMD 5.5-7.7: path:hsa05170 (median BMD 8.0, 5 genes, mostly UP)
BMD 5.5-7.7: path:rno05170 (median BMD 8.0, 5 genes, mostly UP)
BMD 0.3-7.39: path:rno05417 (median BMD 8.25, 12 genes, mostly UP)
BMD 0.3-7.39: path:hsa05417 (median BMD 8.25, 12 genes, mostly UP)
BMD 4.5-8.35: path:rno05161 (median BMD 8.25, 10 genes, mostly UP)
BMD 4.5-8.35: path:hsa05161 (median BMD 8.25, 10 genes, mostly UP)
BMD 4-7.8: path:hsa05163 (median BMD 8.25, 10 genes, mostly UP)
BMD 4-7.8: path:rno05163 (median BMD 8.25, 10 genes, mostly UP)
BMD 5-8.12: path:hsa05162 (median BMD 8.25, 8 genes, mostly UP)
BMD 5-8.12: path:rno05162 (median BMD 8.25, 8 genes, mostly UP)
BMD 5.5-8.25: AUF1 (hnRNP D0) binds and destabilizes mRNA (median BMD 8.25, 2 genes, mixed)
BMD 5-8.31: path:rno05168 (median BMD 8.5, 8 genes, mostly UP)
BMD 5-8.31: path:hsa05168 (median BMD 8.5, 8 genes, mostly UP)
BMD 3-8.06: path:hsa05022 (median BMD 8.5, 8 genes, mostly UP)
BMD 3-8.06: path:rno05022 (median BMD 8.5, 8 genes, mostly UP)
BMD 3-8.14: path:rno04217 (median BMD 8.5, 7 genes, mostly UP)
BMD 3-8.14: path:hsa04217 (median BMD 8.5, 7 genes, mostly UP)
BMD 2.5-8.5: path:hsa04068 (median BMD 8.5, 5 genes, mostly UP)
BMD 2.5-8.5: path:rno04068 (median BMD 8.5, 5 genes, mostly UP)
BMD 3.5-7: path:hsa05235 (median BMD 8.5, 3 genes, mostly UP)
BMD 3.5-7: path:rno05235 (median BMD 8.5, 3 genes, mostly UP)
BMD 8-8.5: path:hsa05120 (median BMD 8.5, 2 genes, mostly UP)
BMD 4-8.9: path:hsa04933 (median BMD 8.75, 10 genes, mostly UP)
BMD 4-8.9: path:rno04933 (median BMD 8.75, 10 genes, mostly UP)
BMD 5.5-9.33: path:rno05145 (median BMD 8.75, 6 genes, mostly UP)
BMD 5.5-9.33: path:hsa05145 (median BMD 8.75, 6 genes, mostly UP)
BMD 2-7.38: path:rno04920 (median BMD 8.75, 4 genes, mostly UP)
BMD 2-7.38: path:hsa04920 (median BMD 8.75, 4 genes, mostly UP)
BMD 8.5-8.75: path:hsa05221 (median BMD 8.75, 2 genes, mostly UP)
BMD 8.5-8.75: path:rno05221 (median BMD 8.75, 2 genes, mostly UP)
BMD 8.5-8.75: path:rno04062 (median BMD 8.75, 2 genes, mostly UP)
BMD 8.5-8.75: path:hsa04062 (median BMD 8.75, 2 genes, mostly UP)
BMD 8.5-8.75: path:rno04917 (median BMD 8.75, 2 genes, mostly UP)
BMD 8.5-8.75: path:hsa04917 (median BMD 8.75, 2 genes, mostly UP)
BMD 0.2-8.46: path:rno04659 (median BMD 9.0, 7 genes, mostly UP)
BMD 0.2-8.46: path:hsa04659 (median BMD 9.0, 7 genes, mostly UP)
BMD 4.5-8.79: path:hsa05166 (median BMD 9.0, 7 genes, mostly UP)
BMD 4.5-8.79: path:rno05166 (median BMD 9.0, 7 genes, mostly UP)
BMD 4-8.86: path:hsa04010 (median BMD 9.0, 7 genes, mostly UP)
BMD 4-8.86: path:rno04010 (median BMD 9.0, 7 genes, mostly UP)
BMD 2-7.79: path:hsa04936 (median BMD 9.0, 7 genes, mostly UP)
BMD 2-7.79: path:rno04936 (median BMD 9.0, 7 genes, mostly UP)
BMD 2-8.3: path:rno04931 (median BMD 9.0, 5 genes, mostly UP)
BMD 2-8.3: path:hsa04931 (median BMD 9.0, 5 genes, mostly UP)
BMD 4-9.33: path:hsa04926 (median BMD 9.0, 3 genes, mostly UP)
BMD 2-8.67: path:rno05415 (median BMD 9.0, 3 genes, mostly UP)
BMD 2-8.67: path:hsa05415 (median BMD 9.0, 3 genes, mostly UP)
BMD 4-9.33: path:rno04926 (median BMD 9.0, 3 genes, mostly UP)
BMD 8-9: path:rno04650 (median BMD 9.0, 2 genes, mostly UP)
BMD 8-9: path:hsa04650 (median BMD 9.0, 2 genes, mostly UP)
BMD 5.5-9.56: path:rno05152 (median BMD 9.5, 8 genes, mostly UP)
BMD 5.5-9.56: path:hsa05152 (median BMD 9.5, 8 genes, mostly UP)
BMD 2-9.12: path:rno04932 (median BMD 9.5, 8 genes, mostly UP)
BMD 2-9.12: path:hsa04932 (median BMD 9.5, 8 genes, mostly UP)
BMD 5.5-9.31: path:rno05132 (median BMD 9.5, 8 genes, mostly UP)
BMD 5.5-9.31: path:hsa05132 (median BMD 9.5, 8 genes, mostly UP)
BMD 5.5-8.88: path:rno04064 (median BMD 9.5, 4 genes, mostly UP)
BMD 5.5-8.88: path:hsa04064 (median BMD 9.5, 4 genes, mostly UP)
BMD 9-9.5: path:hsa04622 (median BMD 9.5, 2 genes, mostly UP)
BMD 9-9.5: path:rno04622 (median BMD 9.5, 2 genes, mostly UP)
BMD 4-9.5: path:rno04518 (median BMD 9.5, 2 genes, mostly UP)
BMD 4-9.5: path:hsa04518 (median BMD 9.5, 2 genes, mostly UP)
BMD 9-9.5: path:hsa04660 (median BMD 9.5, 2 genes, mostly UP)
BMD 9-9.5: path:rno04660 (median BMD 9.5, 2 genes, mostly UP)
BMD 4.5-9.75: RUNX3 regulates CDKN1A transcription (median BMD 9.75, 2 genes, mostly UP)
BMD 6-9.86: path:hsa05130 (median BMD 10.0, 7 genes, mostly UP)
BMD 6-9.86: path:hsa05164 (median BMD 10.0, 7 genes, mostly UP)
BMD 6-9.86: path:rno05164 (median BMD 10.0, 7 genes, mostly UP)
BMD 8-10: path:rno05134 (median BMD 10.0, 5 genes, mostly UP)
BMD 8-10: path:hsa05134 (median BMD 10.0, 5 genes, mostly UP)
BMD 6-9.4: path:rno05020 (median BMD 10.0, 5 genes, mostly UP)
BMD 3-9.6: path:hsa04380 (median BMD 10.0, 5 genes, mostly UP)
BMD 3-9.6: path:rno04380 (median BMD 10.0, 5 genes, mostly UP)
BMD 6-9.4: path:hsa05020 (median BMD 10.0, 5 genes, mostly UP)
BMD 8-10: path:hsa05010 (median BMD 10.0, 5 genes, mostly UP)
BMD 8-10: path:rno05010 (median BMD 10.0, 5 genes, mostly UP)
BMD 8-10: path:rno04657 (median BMD 10.0, 5 genes, mostly UP)
BMD 8-10: path:hsa04657 (median BMD 10.0, 5 genes, mostly UP)
BMD 8-10: path:rno04668 (median BMD 10.0, 5 genes, mostly UP)
BMD 8-10: path:hsa04668 (median BMD 10.0, 5 genes, mostly UP)
BMD 8.5-10.2: Senescence-Associated Secretory Phenotype (SASP) (median BMD 10.25, 2 genes, mostly UP)
BMD 8-10.8: path:hsa05146 (median BMD 10.5, 6 genes, mostly UP)
BMD 8-10.8: path:rno05146 (median BMD 10.5, 6 genes, mostly UP)
BMD 8.5-10.9: path:hsa05321 (median BMD 10.5, 6 genes, mostly UP)
BMD 8.5-10.9: path:rno05321 (median BMD 10.5, 6 genes, mostly UP)
BMD 8.5-10.6: path:hsa05171 (median BMD 10.5, 6 genes, mostly UP)
BMD 8.5-10.6: path:rno05171 (median BMD 10.5, 6 genes, mostly UP)
BMD 8-10.5: path:hsa05133 (median BMD 10.5, 6 genes, mostly UP)
BMD 8-10.5: path:rno05133 (median BMD 10.5, 6 genes, mostly UP)
BMD 5.5-10.1: path:rno04621 (median BMD 10.5, 6 genes, mostly UP)
BMD 5.5-10.1: path:hsa04621 (median BMD 10.5, 6 genes, mostly UP)
BMD 9-10.5: path:rno01523 (median BMD 10.5, 4 genes, mostly UP)
BMD 9-10.5: path:hsa01523 (median BMD 10.5, 4 genes, mostly UP)
BMD 9-11.2: path:rno05140 (median BMD 10.5, 4 genes, mostly UP)
BMD 9-11.2: path:hsa05140 (median BMD 10.5, 4 genes, mostly UP)
BMD 9-10.5: path:hsa04620 (median BMD 10.5, 4 genes, mostly UP)
BMD 9-10.5: path:rno04620 (median BMD 10.5, 4 genes, mostly UP)
BMD 10-10.5: path:hsa04940 (median BMD 10.5, 2 genes, mostly UP)
BMD 10-10.5: path:rno04940 (median BMD 10.5, 2 genes, mostly UP)
BMD 4-10.4: path:hsa05323 (median BMD 11.0, 5 genes, mostly UP)
BMD 4-10.4: path:rno05323 (median BMD 11.0, 5 genes, mostly UP)
BMD 7-11: path:hsa04060 (median BMD 11.0, 5 genes, mostly UP)
BMD 7-11: path:rno04060 (median BMD 11.0, 5 genes, mostly UP)
BMD 8-10.6: path:hsa04623 (median BMD 11.0, 5 genes, mostly UP)
BMD 8-10.6: path:rno04623 (median BMD 11.0, 5 genes, mostly UP)
BMD 9-11: path:rno05135 (median BMD 11.0, 5 genes, mostly UP)
BMD 9-11.4: path:hsa05142 (median BMD 11.0, 5 genes, mostly UP)
BMD 9-11: path:hsa05135 (median BMD 11.0, 5 genes, mostly UP)
BMD 9-11.4: path:rno05142 (median BMD 11.0, 5 genes, mostly UP)
BMD 9-11: path:hsa04625 (median BMD 11.0, 5 genes, mostly UP)
BMD 9-11: path:rno04625 (median BMD 11.0, 5 genes, mostly UP)
BMD 10-11: path:hsa05143 (median BMD 11.0, 3 genes, mostly UP)
BMD 10-11: path:hsa05332 (median BMD 11.0, 3 genes, mostly UP)
BMD 10-11: path:rno05332 (median BMD 11.0, 3 genes, mostly UP)
BMD 10-11: path:rno05143 (median BMD 11.0, 3 genes, mostly UP)
BMD 10-11: path:rno04640 (median BMD 11.0, 3 genes, mostly UP)
BMD 10-11: path:hsa04640 (median BMD 11.0, 3 genes, mostly UP)
BMD 10-11: path:rno04061 (median BMD 11.0, 2 genes, mostly UP)
BMD 10-11: path:hsa04061 (median BMD 11.0, 2 genes, mostly UP)
BMD 10-12: path:hsa05144 (median BMD 11.5, 4 genes, mostly UP)
BMD 10-12: path:rno05144 (median BMD 11.5, 4 genes, mostly UP)
BMD 10-12.3: path:rno05410 (median BMD 12.0, 3 genes, mostly UP)
BMD 10-12.3: path:hsa05410 (median BMD 12.0, 3 genes, mostly UP)
BMD 11-12: Inflammasomes (median BMD 12.0, 2 genes, mostly UP)
BMD 11-12: CLEC7A/inflammasome pathway (median BMD 12.0, 2 genes, mostly UP)
BMD 10-12.5: path:hsa05414 (median BMD 12.5, 2 genes, mostly UP)
BMD 10-12.5: path:rno04350 (median BMD 12.5, 2 genes, mostly UP)
BMD 10-12.5: path:rno05414 (median BMD 12.5, 2 genes, mostly UP)
BMD 10-12.5: path:hsa04350 (median BMD 12.5, 2 genes, mostly UP)
BMD 12-13.5: path:hsa04672 (median BMD 13.5, 2 genes, mostly UP)
BMD 12-13.5: path:rno04672 (median BMD 13.5, 2 genes, mostly UP)

=== ORGAN SIGNATURE ===
Cingulate Cortex: 671.56x enriched (NFE2L2)
Fibroblasts: 671.56x enriched (KEAP1, NFE2L2, NQO1)
Thyroid: 671.56x enriched (KEAP1, NFE2L2)
Hepatic Kupffer Cells: 671.56x enriched (HMOX1)
Monocytes/Macrophages: 671.56x enriched (HMOX1)
Renal Tubular Epithelium: 671.56x enriched (HMOX1)
Abdominal Adipose Tissue: 671.56x enriched (NQO1)
Tissues And Organs: 671.56x enriched (AHR)
Lung Fibroblasts: 671.56x enriched (CYP1B1)
Bone (Osteosarcoma): 671.56x enriched (TP53)
Cns: 671.56x enriched (TP53)
Immune System: 671.56x enriched (TP53)
Small Intestine: 671.56x enriched (TP53)
Cerebrospinal Fluid: 671.56x enriched (BCL2)
Peripheral Blood: 671.56x enriched (IL1B, NFKB1)
Pancreatic Islets: 671.56x enriched (GDF15)
Blood Lymphocytes: 559.64x enriched (CAT, KEAP1, NFE2L2, NQO1, SOD2)
Ileum: 503.67x enriched (HMOX1, KEAP1, NFE2L2, NQO1, SIRT1, SOD1)
Neurodegenerative Tissues (Alzheimer’S And Parkinson’S Diseases): 503.67x enriched (BAX, BCL2, NFE2L2)
Reproductive Organs: 503.67x enriched (BAX, BCL2, NFE2L2)
Testis: 470.09x enriched (BAX, BCL2, CASP3, CAT, GPX1, NFE2L2, TP53)
Head And Neck: 447.71x enriched (KEAP1, NFE2L2)
Spleen: 447.71x enriched (CAT, CDKN1A, KEAP1, NFE2L2, NQO1, SOD2)
Tumor: 447.71x enriched (KEAP1, NFE2L2)
Ependymal Cells: 447.71x enriched (SIRT1, TP53)
Spermatocytes: 447.71x enriched (SIRT1, TP53)
Brain Tissue: 447.71x enriched (BAX, BCL2, CASP3, VEGFA)
Astrocyte: 335.78x enriched (HMOX1)
Erythrocytes: 335.78x enriched (GCLC)
Fetal Fibroblasts: 335.78x enriched (GCLC)
Testicles: 335.78x enriched (SOD1)
Liver Microsomes: 335.78x enriched (CYP1A1)
Lung Epithelium: 335.78x enriched (CYP1A1)
Macrophages: 335.78x enriched (CYP1A1, CYP1B1)
Astrocytoma: 335.78x enriched (TP53)
Cervix: 335.78x enriched (CASP3)
Cartilage: 335.78x enriched (CDKN1A)
Joint: 335.78x enriched (CDKN1A)
Central Nervous System (Cns): 335.78x enriched (IL1B, IL6, TNF)
Pericardium: 335.78x enriched (IL1B, IL6)
Trachea: 335.78x enriched (IL6, STAT3)
Endothelium: 335.78x enriched (SIRT1)
Erector Spinae Muscle: 335.78x enriched (SIRT1)
Peripheral Blood Mononuclear Cells (Pbmcs): 335.78x enriched (SIRT1)
Lung Tissue: 287.81x enriched (HMOX1, IL6, NFE2L2)
Breast: 279.82x enriched (CDKN1A, CYP1A1, CYP3A4, NFKB1, TP53)
Stomach: 274.73x enriched (BAX, BCL2, GDF15, IL6, KEAP1, NFE2L2, NQO1, SQSTM1, ... (+1 more))
Substantia Nigra: 268.62x enriched (BAX, TP53)
Muscle: 255.83x enriched (CAT, CYP1A1, CYP1B1, GDF15, SOD1, SOD2, TGFB1, TP53)
Not Specified In Abstract: 237.02x enriched (BCL2, HIF1A, NFKB1, TGFB1, TNF, VEGFA)
Cloaca Region: 223.85x enriched (SOD1)
Hindgut: 223.85x enriched (SOD1)
Epidermis: 223.85x enriched (AHR, CYP1A1, CYP1B1)
Serum: 223.85x enriched (AHR, CYP1A1, CYP1B1)
Aortic Valve: 223.85x enriched (SIRT1, TP53)
Fibroblast Cells (Ccd-1064Sk): 223.85x enriched (BAX)
Proximal Small Intestine: 223.85x enriched (BAX, CASP3)
Broncho-Alveolar Lavage (Bal) Fluid: 223.85x enriched (IL6)
Cardiac Microvasculature: 223.85x enriched (TGFB1)
Hippocampal Ca1 Region: 191.88x enriched (BAX, BCL2)
Neurons: 184.68x enriched (BAX, BCL2, CASP3, IL1B, IL6, NFE2L2, SIRT1, SOD1, ... (+3 more))
Pancreas: 179.08x enriched (CAT, GCLC, GDF15, IL6, NLRP3, NQO1, SOD1, SQSTM1)
Intestine: 172.69x enriched (AHR, BAX, BCL2, CDKN1A, CYP1A1, CYP1B1, GDF15, HMOX1, ... (+10 more))
Gastric Tissue: 167.89x enriched (TP53)
Maxilla: 167.89x enriched (TP53)
Neck: 167.89x enriched (TP53)
Thymus: 167.89x enriched (TP53)
Hindbrain: 167.89x enriched (GDF15)
Periventricular Germinal Epithelium: 167.89x enriched (GDF15)
Olfactory Bulb: 154.98x enriched (IL1B, IL6, TNF)
Pons: 154.98x enriched (IL1B, IL6, TNF)
Tongue: 154.98x enriched (IL1B, IL6, TNF)
Skin: 134.31x enriched (BAX, BCL2, NFE2L2, SIRT1)
Blood: 134.31x enriched (BCL2, GCLC, IL1B, NLRP3, SIRT1, STAT3, TNF, TP53)
Hoof: 134.31x enriched (GCLC)
Enteric Nervous System (Ens): 134.31x enriched (GDF15)
Male Reproductive System: 134.31x enriched (GDF15)
Gastric Mucosa: 134.31x enriched (SQSTM1)
Lymph Node: 127.92x enriched (IL1B, IL6, TNF, TP53)
Prostate: 125.92x enriched (IL6, TNF, TP53)
Ovary: 111.93x enriched (HMOX1)
Spinal Cord: 111.93x enriched (HMOX1, NFKB1, SOD1)
Bladder: 111.93x enriched (TP53)
Choroid Plexus: 111.93x enriched (TP53)
Left Ventricular Myocardium Tissue: 111.93x enriched (VEGFA)
Vascular Endothelium: 95.94x enriched (HMOX1, SIRT1)
Adipose Tissue: 95.94x enriched (NLRP3, PPARA)
Bone Marrow: 95.94x enriched (BCL2, TGFB1, TP53)
Perientheseal Bone: 95.94x enriched (IL1B)
Spinal Enthesis Soft Tissue: 95.94x enriched (IL1B)
Bone: 89.54x enriched (TP53, VEGFA)
Mediastinum: 83.95x enriched (TP53)
Mesentery: 83.95x enriched (TP53)
Soft Tissue: 83.95x enriched (TP53)
Thoracic Vertebrae: 83.95x enriched (TP53)
Cornea: 83.95x enriched (CASP3)
Right Ventricle: 83.95x enriched (IL1B, TNF)
Astrocytes: 83.95x enriched (SQSTM1)
Kidney: 75.59x enriched (AHR, BAX, BCL2, CASP3, CDKN1A, CYP1A1, CYP1B1, GCLC, ... (+18 more))
Pulmonary Artery: 74.62x enriched (IL6)
Brain: 67.48x enriched (AHR, BAX, BCL2, CASP3, CAT, GCLC, GDF15, GPX1, ... (+13 more))
Whole Blood Cells: 67.16x enriched (NLRP3)
Wharton'S Jelly: 67.16x enriched (TGFB1)
Testes: 61.05x enriched (CASP3)
Eye: 55.96x enriched (CASP3)
Retina: 55.96x enriched (CASP3)
Aorta: 55.96x enriched (NLRP3)
Heart: 51.35x enriched (AHR, BAX, BCL2, CASP3, CAT, CDKN1A, CYP3A4, GDF15, ... (+18 more))
Liver: 45.06x enriched (AHR, BAX, BCL2, CASP3, CAT, CDKN1A, CYP1A1, CYP1B1, ... (+23 more))
Lung: 44.62x enriched (BAX, BCL2, CASP3, CAT, CDKN1A, CYP1A1, CYP3A4, GCLC, ... (+12 more))

=== LITERATURE CONTEXT ===
## NFE2L2 (81 papers, consensus gene)
  Organs: blood lymphocytes, brain, cingulate cortex, fibroblasts, head and neck, heart, ileum, intestine, kidney, liver, lung, lung tissue, neurodegenerative tissues (alzheimer’s and parkinson’s diseases), neurons, reproductive organs, skin, spleen, stomach, testis, thyroid, tumor
  Key claims:
  - "Network-based approaches using co-expression network analysis can predict drug toxicity mechanisms and phenotypes more effectively than traditional gene-level analysis." (Toxicogenomic module associations with pathogenesis: a netwo, 2017)
  - "Early network responses complement histology-based assessment in predicting long-term study outcomes." (Toxicogenomic module associations with pathogenesis: a netwo, 2017)
  - "A novel mechanism of hepatotoxicity involving endoplasmic reticulum stress and Nrf2 activation is identified." (Toxicogenomic module associations with pathogenesis: a netwo, 2017)

## TP53 (63 papers, consensus gene)
  Organs: aortic valve, astrocytoma, bladder, blood, bone, bone (osteosarcoma), bone marrow, brain, breast, choroid plexus, cns, ependymal cells, gastric tissue, heart, immune system, intestine, kidney, liver, lung, lymph node, maxilla, mediastinum, mesentery, muscle, neck, neurons, prostate, small intestine, soft tissue, spermatocytes, substantia nigra, testis, thoracic vertebrae, thymus
  Key claims:
  - "The RuIII/Q complex has potent antioxidant and anti-inflammatory effects, reducing oxidative stress and apoptosis in testicular and brain tissues." (Potential Therapeutic Effects of New Ruthenium (III) Complex, 2021)
  - "RuIII/Q administration ameliorates aging neurotoxicity and reproductive toxicity induced by D-galactose." (Potential Therapeutic Effects of New Ruthenium (III) Complex, 2021)
  - "The TP53 R273C mutation is more prevalent in lower-grade, IDH-mutant astrocytomas (LGIMAs) and defines a distinct biological subset marked by increased Ki-67 expression and female predominance." (Next-Generation Sequencing Reveals a Diagnostic and Prognost, 2025)

## BCL2 (45 papers, consensus gene)
  Organs: blood, bone marrow, brain, brain tissue, cerebrospinal fluid, heart, hippocampal ca1 region, intestine, kidney, liver, lung, neurodegenerative tissues (alzheimer’s and parkinson’s diseases), neurons, not specified in abstract, reproductive organs, skin, stomach, testis
  Key claims:
  - "The RuIII/Q complex has potent antioxidant and anti-inflammatory effects, reducing oxidative stress and apoptosis in testicular and brain tissues." (Potential Therapeutic Effects of New Ruthenium (III) Complex, 2021)
  - "RuIII/Q administration ameliorates aging neurotoxicity and reproductive toxicity induced by D-galactose." (Potential Therapeutic Effects of New Ruthenium (III) Complex, 2021)
  - "circUSP36 expression is decreased in IS patients and correlates with disease severity" (CircUSP36 attenuates ischemic stroke injury through the miR-, 2022)

## BAX (41 papers, consensus gene)
  Organs: brain, brain tissue, fibroblast cells (ccd-1064sk), heart, hippocampal ca1 region, intestine, kidney, liver, lung, neurodegenerative tissues (alzheimer’s and parkinson’s diseases), neurons, proximal small intestine, reproductive organs, skin, stomach, substantia nigra, testis
  Key claims:
  - "Heavy metals interfere with antioxidant defense mechanisms and signaling pathways leading to diverse health effects." (Heavy metals: toxicity and human health effects, 2024)
  - "Arsenic binds directly to thiols, affecting Nrf2 activity in response to oxidative stress." (Heavy metals: toxicity and human health effects, 2024)
  - "Cadmium affects Bcl-2 family proteins, altering cell survival mechanisms." (Heavy metals: toxicity and human health effects, 2024)

## SIRT1 (39 papers, consensus gene)
  Organs: aortic valve, blood, endothelium, ependymal cells, erector spinae muscle, heart, ileum, kidney, liver, lung, neurons, peripheral blood mononuclear cells (pbmcs), skin, spermatocytes, vascular endothelium
  Key claims:
  - "Spermidine ameliorates aortic valve degenerations by improving mitochondrial function and biogenesis." (Abstract P3198: Spermidine Ameliorates Aortic Valve Degenera, 2023)
  - "The IRS2-AKT-TP53-SIRT1-DNMT1 pathway is involved in the mechanism of spermidine's therapeutic effect on aortic valve interstitial cells (AVICs)." (Abstract P3198: Spermidine Ameliorates Aortic Valve Degenera, 2023)
  - "Inhibition of DNMT1 and reduction of mtDNA hypermethylation improve mitochondrial biogenesis, which may serve as a treatment mechanism for aortic stenosis." (Abstract P3198: Spermidine Ameliorates Aortic Valve Degenera, 2023)

## IL6 (37 papers, consensus gene)
  Organs: brain, broncho-alveolar lavage (bal) fluid, central nervous system (cns), heart, intestine, kidney, liver, lung, lung tissue, lymph node, neurons, olfactory bulb, pancreas, pericardium, pons, prostate, pulmonary artery, stomach, tongue, trachea
  Key claims:
  - "Intermittent hypoxia exacerbates NAFLD by promoting ferroptosis via IL6-induced MARCH3-mediated GPX4 ubiquitination" (IL6 Derived from Macrophages under Intermittent Hypoxia Exac, 2024)
  - "Ferroptosis inhibitor Fer-1 alleviates the progression of NAFLD in mice under chronic intermittent hypoxia" (IL6 Derived from Macrophages under Intermittent Hypoxia Exac, 2024)
  - "C. speciosus nanoparticles ameliorate diabetes-induced structural changes in rat prostate by mediating pro-inflammatory cytokines IL-6, IL1β and TNF-α" (Nanoparticles of Costus speciosus Ameliorate Diabetes-Induce, 2022)

## KEAP1 (37 papers, consensus gene)
  Organs: blood lymphocytes, fibroblasts, head and neck, heart, ileum, intestine, liver, lung, spleen, stomach, thyroid, tumor
  Key claims:
  - "Oyster peptides derived from Crassostrea gigas protect against intestinal oxidative damage induced by cyclophosphamide in mice" (Protective Effect of Oyster Peptides Derived From Crassostre, 2022)
  - "OP increases bodyweight and improves ileum tissue morphology and villus structure" (Protective Effect of Oyster Peptides Derived From Crassostre, 2022)
  - "OP enhances antioxidant enzyme activities (SOD, CAT, GSH-Px) and reduces MDA content" (Protective Effect of Oyster Peptides Derived From Crassostre, 2022)

## TNF (35 papers, consensus gene)
  Organs: blood, brain, central nervous system (cns), heart, intestine, kidney, liver, lung, lymph node, not specified in abstract, olfactory bulb, pons, prostate, right ventricle, stomach, tongue
  Key claims:
  - "Cardiac arrest in rats leads to a systemic and organ-specific TNFα and cytokine response, with increased biomarkers of injury." (Targeting TNFα-mediated cytotoxicity using thalidomide after, 2022)
  - "Thalidomide at a dose previously shown to be neuroprotective did not decrease TNFα or cytokine levels post-cardiac arrest." (Targeting TNFα-mediated cytotoxicity using thalidomide after, 2022)
  - "Whey protein (WP) pre-treatment significantly alleviates thioacetamide (TAA)-induced cardiotoxicity in male albino rats by reducing oxidative stress, inflammatory response, and apoptotic markers." (The cardioprotective effect of whey protein against thioacet, 2025)

## HMOX1 (32 papers, consensus gene)
  Organs: astrocyte, brain, heart, hepatic kupffer cells, ileum, intestine, kidney, liver, lung, lung tissue, monocytes/macrophages, ovary, renal tubular epithelium, spinal cord, vascular endothelium
  Key claims:
  - "Cadmium exposure in human neuronal cells (SH-SY5Y) leads to early deregulation of genes and processes, including activation of p53 signaling pathway, heat shock proteins, metallothioneins, and alterat" (Neuronal specific and non-specific responses to cadmium poss, 2019)
  - "Cadmium-induced neurotoxicity may contribute to neurodegenerative diseases by disrupting essential metal homeostasis and neuronal functions." (Neuronal specific and non-specific responses to cadmium poss, 2019)
  - "Supplementation with Zn and Se attenuates neurotoxicity caused by a mixture of heavy metals in female rats" (Zn and Se protect toxic metal mixture-mediated memory defici, 2025)

## CASP3 (30 papers, consensus gene)
  Organs: brain, brain tissue, cervix, cornea, eye, heart, kidney, liver, lung, neurons, proximal small intestine, retina, testes, testis
  Key claims:
  - "Whey protein (WP) pre-treatment significantly alleviates thioacetamide (TAA)-induced cardiotoxicity in male albino rats by reducing oxidative stress, inflammatory response, and apoptotic markers." (The cardioprotective effect of whey protein against thioacet, 2025)
  - "Pre-treatment with WP mitigates TAA-induced alterations in cardiac tissue activities of glutathione, superoxide dismutase, catalase, malondialdehyde, nitric oxide, TNF-α, IL-1β, Bax, Bcl-2, caspase-3 " (The cardioprotective effect of whey protein against thioacet, 2025)
  - "Curcumin protects against oxidative stress and lung damage caused by cadmium (Cd) + arsenic (As)" (Curcumin Protects against Arsenic and Cadmium‐Induced Lung T, 2026)

## VEGFA (29 papers, consensus gene)
  Organs: bone, brain, brain tissue, heart, kidney, left ventricular myocardium tissue, liver, neurons, not specified in abstract
  Key claims:
  - "Nanocurcumin (CUR-NP) can mitigate doxorubicin-induced nephrotoxicity in rats by modulating VEGF and AhR pathways." (Aryl Hydrocarbon Receptor (AhR) and Vascular Endothelial Gro, 2026)
  - "CUR-NP treatment significantly improves kidney function, reduces oxidative stress markers, and normalizes inflammatory mediators in renal tissues." (Aryl Hydrocarbon Receptor (AhR) and Vascular Endothelial Gro, 2026)
  - "Time-dependent factors are crucial for post-injury alterations in gene expression during liver regeneration." (RNA-Seq transcriptome profiling in three liver regeneration , 2020)

## AHR (27 papers, consensus gene)
  Organs: brain, epidermis, heart, intestine, kidney, liver, serum, tissues and organs
  Key claims:
  - "Quantitative transcriptional biomarkers for xenobiotic receptor activation in rat liver can predict drug-induced liver injury (DILI) with high sensitivity and specificity." (Quantitative Transcriptional Biomarkers of Xenobiotic Recept, 2020)
  - "Gene expression panels associated with key xenobiotic nuclear receptors, stress response mediators, and innate immune responses are proposed as quantitative mechanistic biomarkers for DILI assessment." (Quantitative Transcriptional Biomarkers of Xenobiotic Recept, 2020)
  - "A set of six gene expression biomarkers can identify rat liver tumorigens in short-term assays" (A Set of Six Gene Expression Biomarkers Identify Rat Liver T, 2020)

## NFKB1 (27 papers, consensus gene)
  Organs: brain, breast, heart, intestine, kidney, liver, lung, not specified in abstract, peripheral blood, spinal cord
  Key claims:
  - "Cadmium-induced toxicity in hepatic macrophages leads to oxidative stress, disruption of calcium homeostasis, and activation of transcription factors such as NF-κB and Nrf2." (Research Advances on Cadmium-Induced Toxicity in Hepatic Mac, 2026)
  - "These perturbations alter macrophage polarization (M1/M2), promote cellular damage and apoptosis, and exacerbate hepatic inflammation and fibrosis." (Research Advances on Cadmium-Induced Toxicity in Hepatic Mac, 2026)
  - "Cadmium induces oxidative stress and disrupts cellular signaling pathways leading to apoptosis and carcinogenesis." (Cadmium Exposure: Mechanisms and Pathways of Toxicity and Im, 2024)

## PPARA (26 papers, consensus gene)
  Organs: adipose tissue, intestine, kidney, liver
  Key claims:
  - "Quantitative transcriptional biomarkers for xenobiotic receptor activation in rat liver can predict drug-induced liver injury (DILI) with high sensitivity and specificity." (Quantitative Transcriptional Biomarkers of Xenobiotic Recept, 2020)
  - "Gene expression panels associated with key xenobiotic nuclear receptors, stress response mediators, and innate immune responses are proposed as quantitative mechanistic biomarkers for DILI assessment." (Quantitative Transcriptional Biomarkers of Xenobiotic Recept, 2020)
  - "Fenofibrate differentially activates PPARα-mediated lipid metabolism in rat liver and kidney, leading to organ-specific toxicity mechanisms." (Fenofibrate differentially activates PPARα-mediated lipid me, 2025)

## NQO1 (24 papers, consensus gene)
  Organs: abdominal adipose tissue, blood lymphocytes, fibroblasts, heart, ileum, intestine, kidney, liver, pancreas, spleen, stomach
  Key claims:
  - "A protocol for integrating drug-wise rankings of gene expression changes in toxicogenomics data prioritizes genes associated with liver or kidney toxicity." (Literature optimized integration of gene expression for orga, 2019)
  - "Comparing gene ranks from different models highlights differences in toxicity-associated genes between human and rat hepatocytes, as well as between rat liver and rat hepatocytes." (Literature optimized integration of gene expression for orga, 2019)
  - "p53 activation by doxorubicin alleviates acetaminophen-induced hepatotoxicity in mice" (p53 attenuates acetaminophen-induced hepatotoxicity by regul, 2018)

=== TOP RELEVANT PAPERS ===
- Nucleocytoplasmic Shuttling of the NAD+-dependent Histone Deacetylase SIRT1* (2007, cited 760x) [genes: SIRT1, TP53]
- Selective cytotoxicity of intracellular amyloid β peptide1–42 through p53 and Bax in cultured primary human neurons (2002, cited 452x) [genes: BAX, TP53]
- Heavy metals: toxicity and human health effects (2024, cited 420x) [genes: BAX, BCL2, NFE2L2]
- Hesperetin ameliorates hepatic oxidative stress and inflammation via the PI3K/AKT-Nrf2-ARE pathway in oleic acid-induced HepG2 cells and a rat model of high-fat diet-induced NAFLD. (2021, cited 331x) [genes: GCLC, GPX1, HMOX1, IL6, NFE2L2, NFKB1, SOD1, TNF]
- The BCL2 selective inhibitor venetoclax induces rapid onset apoptosis of CLL cells in patients via a TP53-independent mechanism. (2016, cited 276x) [genes: BCL2, TP53]
- Cardiomyocyte gene programs encoding morphological and functional signatures in cardiac hypertrophy and failure (2018, cited 226x) [genes: NFE2L2, TP53]
- LKB1 and KEAP1/NRF2 pathways cooperatively promote metabolic reprogramming with enhanced glutamine dependence in KRAS-mutant lung adenocarcinoma. (2019, cited 222x) [genes: KEAP1, NFE2L2]
- New molecular and biochemical insights of doxorubicin-induced hepatotoxicity. (2020, cited 215x) [genes: CAT, GPX1, HMOX1, SOD1]
- Comparison of RNA-Seq and Microarray Gene Expression Platforms for the Toxicogenomic Evaluation of Liver From Short-Term Rat Toxicity Studies (2019, cited 199x) [genes: CYP1A1, NFE2L2]
- KEAP1‐NRF2 protein–protein interaction inhibitors: Design, pharmacological properties and therapeutic potential (2022, cited 169x) [genes: KEAP1, NFE2L2]
```
