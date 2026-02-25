# Concordance Analysis

*Analyzed by claude-sonnet-4-6*

# Concordance Analysis: Toxicogenomics Interpretation Narratives

## Preliminary Notes on Analytical Framework

This analysis compares 12 narratives from 4 models (claude-haiku-4-5, qwen2.5:14b, qwen2.5:7b, claude-opus-4-6), each run 3 times. I evaluate concordance both within and across model families, noting where inter-run consistency within a model reinforces or undermines cross-model agreement. Citations to specific model outputs use the format [Model, Run #].

---

## 1. Biological Response Narrative — Concordance

### Agreement

All 12 narratives independently identify the same core dose-response architecture: an early adaptive antioxidant phase dominated by NRF2/KEAP1 signaling, followed by inflammatory escalation, and ultimately cell death pathways at the highest doses. This three-tier structure (adaptive → transitional → adverse) is the single most robustly reproduced finding in the entire dataset.

**Specific points of universal agreement:**

- **NRF2/KEAP1 pathway activation** is identified as the earliest and most prominent adaptive response in all 12 narratives without exception. All models cite NFE2L2, KEAP1, HMOX1, NQO1, and GCLC as early-responding genes.
- **AHR/CYP1A1 signaling** as the molecular initiating event (or earliest detectable response) is identified by all three claude-haiku-4-5 runs and all three claude-opus-4-6 runs, and implicitly referenced in qwen2.5 models through xenobiotic metabolism framing.
- **Inflammatory pathway activation** (IL1B, TNF, NFKB1, NLRP3) at higher doses is universally identified.
- **Apoptotic pathway engagement** (BAX, CASP3, TP53, CDKN1A) at intermediate-to-high doses is identified by all models.
- **TGFB1-mediated fibrotic signaling** at high doses is noted by all claude models and qwen2.5:14b runs.

### Divergence

**Dose-range specificity:** The claude models (both haiku and opus) provide explicit BMD-anchored phase descriptions (e.g., "Phase I: BMD 0.2–0.55"), while qwen2.5 models use qualitative dose labels ("low," "moderate," "high") without anchoring to specific BMD values. This is a structural difference that limits direct comparison of dose thresholds between model families. The qwen2.5 models appear to be working from the same dataset but either did not access or did not utilize the quantitative BMD information.

**Phase granularity:** Claude-haiku-4-5 (Run 1) identifies 8 distinct phases including a dedicated "Senescence-Associated Secretory Phenotype (SASP)" phase and a "Hypoxic Stress and Angiogenic Response" phase. Claude-opus-4-6 models identify 5–7 phases. Qwen2.5 models identify 3 phases (low/moderate/high). This is a significant structural divergence: the claude models are substantially more granular in their dose-response parsing.

**Circadian disruption:** All three claude-haiku-4-5 runs and all three claude-opus-4-6 runs identify circadian clock gene downregulation as a distinct phase (BMD ~2.0–2.25). This finding is entirely absent from all six qwen2.5 narratives (both 14b and 7b), representing a consistent blind spot in the smaller models.

**Ferroptosis:** Claude-opus-4-6 (all three runs) specifically identifies ferroptosis pathway activation as an early distinct phase (BMD ~0.6). Claude-haiku-4-5 does not explicitly call out ferroptosis as a named phase. Qwen2.5 models do not mention ferroptosis at all. This is a model-family-specific finding.

**Autophagy/mitophagy:** Claude-haiku-4-5 (Run 1) and all claude-opus-4-6 runs identify autophagy and mitophagy as distinct phases (BMD 3.5–4.5). Qwen2.5:14b (Run 3) mentions SIRT1-mediated autophagy briefly. Qwen2.5:7b models do not address autophagy systematically.

**Innate immune pattern recognition at high doses:** Claude-opus-4-6 (all runs) and claude-haiku-4-5 (Run 2) identify TLR, NOD-like receptor, and RIG-I-like receptor pathway activation at the highest doses. This is absent from qwen2.5 narratives.

### Concordance Rating: **Moderate-Strong**

The core three-tier structure (adaptive → inflammatory → apoptotic) achieves strong agreement. Specific phase granularity, dose anchoring, and identification of secondary pathways (ferroptosis, circadian disruption, innate immune activation) show moderate-to-weak agreement, primarily driven by the structural gap between claude and qwen2.5 model families.

---

## 2. Organ-Level Prediction — Concordance

### Agreement

**Liver** is identified as a primary target organ by all 12 narratives. This is the single organ prediction with universal agreement. The mechanistic rationale is also consistent: hepatic xenobiotic metabolism via CYP enzymes, NRF2-mediated antioxidant response, NLRP3 inflammasome activation in Kupffer cells, and progression to fibrosis via TGFB1.

**Kidney** is identified as a primary target by all 12 narratives, making it the second organ with universal agreement. The mechanistic basis (oxidative stress in tubular epithelium, apoptosis, inflammatory infiltration) is consistent across models.

**Brain/CNS** is identified by all three claude-haiku-4-5 runs, all three claude-opus-4-6 runs, qwen2.5:14b (all three runs), and qwen2.5:7b (Runs 2 and 3). This represents near-universal agreement (11/12 narratives).

**Heart** is identified by qwen2.5:14b (Runs 1 and 2), qwen2.5:7b (Runs 1, 2, and 3), and qwen2.5:14b (Run 3). It is not identified as a primary target by any claude model. This represents a model-family divergence.

### Divergence

**Testis/male reproductive system:** All three claude-opus-4-6 runs and claude-haiku-4-5 (Run 1) identify testis as a high-confidence primary target. This organ is entirely absent from all qwen2.5 narratives. This is the most striking organ-prediction divergence in the dataset.

**Heart:** Identified by 5/6 qwen2.5 narratives but 0/6 claude narratives. The qwen2.5 models cite SIRT1, TP53, and NLRP3 as cardiac markers; the claude models do not prioritize cardiac tissue despite these same genes being present in their analyses.

**Lung:** Identified by qwen2.5:7b (Run 1) as a primary target. Not identified by any other model. This is a unique, low-confidence prediction.

**Gastrointestinal tract:** Claude-haiku-4-5 (Run 2) mentions GI tract involvement. Not systematically addressed by other models.

**Enrichment specificity:** Claude models provide quantitative enrichment values (e.g., "30.36× enriched, 28 genes" for liver; "41.99× enriched" for kidney; "390.13× enriched" for microglia). Qwen2.5 models provide qualitative organ predictions without enrichment statistics. This difference in evidential grounding is substantial.

**Organ ranking:** Claude-opus-4-6 consistently ranks liver > kidney > testis > brain > cardiovascular. Claude-haiku-4-5 ranks liver > kidney > brain. Qwen2.5:14b ranks liver > kidney > heart > brain. Qwen2.5:7b ranks liver > lung > kidney > heart > brain. The top two (liver, kidney) are universally agreed upon; rankings below that diverge.

### Concordance Rating: **Strong for liver and kidney; Moderate for brain; Weak for heart, testis, and lung**

---

## 3. Mechanism of Action — Concordance

### Agreement

All models agree on the following mechanistic sequence:

1. **ROS generation** as the primary upstream driver of toxicity
2. **KEAP1-NRF2 pathway** as the primary adaptive sensor-effector mechanism
3. **NF-κB pathway** as the bridge between oxidative stress and inflammation
4. **NLRP3 inflammasome** as the amplifier of inflammatory cell death
5. **TP53/BAX/CASP3 axis** as the apoptotic execution mechanism

The concept of a **molecular initiating event (MIE)** is explicitly invoked by qwen2.5:14b (all runs), qwen2.5:7b (all runs), and claude-haiku-4-5 (Run 1). Claude-opus-4-6 uses equivalent language ("earliest transcriptional responses," "primary initiating event") without formally labeling it MIE.

### Divergence

**AHR as MIE:** Claude-haiku-4-5 (Run 1) and all claude-opus-4-6 runs explicitly identify AHR activation as the molecular initiating event, preceding and driving ROS generation through CYP1A1/CYP1B1 bioactivation. Qwen2.5 models identify ROS generation itself as the MIE, without specifying the upstream receptor event. This is a meaningful mechanistic divergence: the claude models propose a receptor-mediated mechanism (AHR ligand binding → CYP induction → reactive metabolite formation → ROS), while qwen2.5 models propose a direct oxidative stress mechanism (ROS → NRF2 activation).

**Ferroptosis mechanism:** Claude-opus-4-6 (all runs) specifically identifies lipid peroxidation and ferroptosis as a mechanistically distinct early cell death pathway, separate from apoptosis and necroptosis. This mechanistic specificity is absent from all other models.

**SQSTM1/p62 feedback loop:** Claude-opus-4-6 (Runs 1 and 2) specifically identifies the SQSTM1-KEAP1 positive feedback loop (SQSTM1 sequesters KEAP1, further stabilizing NRF2) as a mechanistic amplifier. This molecular detail is not mentioned by any other model.

**Pyroptosis vs. apoptosis distinction:** Claude-haiku-4-5 (Runs 1 and 3) and claude-opus-4-6 (all runs) distinguish between apoptosis (CASP3-mediated), pyroptosis (NLRP3/gasdermin D-mediated), and necroptosis as distinct cell death modalities. Qwen2.5 models treat apoptosis as the primary cell death mechanism without distinguishing pyroptosis or necroptosis.

**SIRT1 mechanism:** Qwen2.5:14b (Run 3) and qwen2.5:7b (all runs) emphasize SIRT1-mediated autophagy as a protective mechanism. Claude-haiku-4-5 (Run 1) mentions SIRT1 in the context of metabolic sensing. Claude-opus-4-6 mentions SIRT1 in organ signatures but does not develop it as a central mechanistic element. The mechanistic role of SIRT1 is thus more prominent in qwen2.5 narratives.

### Concordance Rating: **Moderate**

Core pathway sequence (ROS → NRF2 → NF-κB → NLRP3 → apoptosis) achieves strong agreement. The identity of the MIE, the role of ferroptosis, and the distinction between cell death modalities show meaningful divergence.

---

## 4. Protective vs. Adverse Responses — Concordance

### Agreement

All models agree that:
- Low-dose responses are predominantly **adaptive/protective**, centered on NRF2 activation
- High-dose responses are predominantly **adverse**, involving inflammation and cell death
- A **transition point** exists between these regimes

All models identify the NRF2 pathway as the primary protective mechanism and NLRP3/apoptosis as the primary adverse mechanisms.

### Divergence

**Transition dose estimate:** This is the most significant divergence in this section. Claude models provide BMD-anchored estimates:
- Claude-haiku-4-5 (Run 3): Transition at BMD 2.5–5.5
- Claude-haiku-4-5 (Run 2): Transition at BMD 2.0–2.25 (circadian disruption as marker)
- Claude-opus-4-6 (Runs 1, 2, 3): Transition estimated at BMD 3–5

Qwen2.5 models provide qualitative estimates:
- Qwen2.5:14b (Run 1): Transition at "intermediate dose level (5 mg/kg)"
- Qwen2.5:14b (Run 2): Transition at "moderate dose level"
- Qwen2.5:7b (Run 2): Transition at "medium dose (1 mg/kg)"

The qwen2.5:7b (Run 2) estimate of 1 mg/kg is notably lower than all other estimates, suggesting this model may be applying a more conservative threshold or interpreting the dose scale differently.

**BCL2 classification:** Claude-haiku-4-5 (Run 1) and claude-opus-4-6 (Runs 1, 2) note that BCL2 upregulation alongside BAX represents a contested survival signal — cells are simultaneously activating pro- and anti-apoptotic programs. Qwen2.5 models classify BCL2 straightforwardly as an anti-apoptotic/protective gene without noting this tension.

**KEAP1 upregulation paradox:** Claude-haiku-4-5 (Run 1) specifically flags the "paradoxical upregulation" of KEAP1 alongside NFE2L2 as evidence of active pathway cycling. Claude-opus-4-6 (Run 2) addresses this as "mixed directionality" consistent with canonical NRF2 activation. Qwen2.5 models do not address this apparent paradox.

**Circadian disruption as transition marker:** Claude-haiku-4-5 (Run 2) and claude-opus-4-6 (Runs 2 and 3) specifically use circadian clock gene downregulation at BMD 2.0–2.25 as a marker of the adaptive-to-adverse transition. This specific marker is absent from all qwen2.5 narratives.

### Concordance Rating: **Moderate**

Qualitative agreement on the existence of an adaptive-to-adverse transition is strong. Quantitative agreement on the transition dose and the mechanistic markers of that transition is moderate-to-weak.

---

## 5. Literature Support — Concordance

### Agreement

The following papers are cited consistently across multiple models:

| Paper | Models Citing |
|---|---|
| "The KEAP1-NRF2 System: a Thiol-Based Sensor-Effector Apparatus for Maintaining Redox Homeostasis" (2018, cited 1544×) | All claude models (6/6 runs); qwen2.5:14b (2/3 runs); qwen2.5:7b (2/3 runs) |
| "An Overview of Nrf2 Signaling Pathway and Its Role in Inflammation" (2020, cited 1094×) | Claude-haiku-4-5 (Runs 1, 3); claude-opus-4-6 (Run 3); qwen2.5:14b (Run 1); qwen2.5:7b (Run 2) |
| "NLRP3 Inflammasome Activation in Liver Disorders" (2025) | Claude-haiku-4-5 (Runs 1, 3); claude-opus-4-6 (Runs 1, 2, 3) |
| "Rutin Protects from Destruction by Interrupting the Pathways" (2021) | Claude-haiku-4-5 (Runs 1, 2); claude-opus-4-6 (Runs 1, 2, 3) |
| "ROS Generation in Microglia: Understanding Oxidative Stress and Inflammation in Neurodegenerative Disease" (2020) | Claude-opus-4-6 (Run 1); qwen2.5:14b (Run 1); qwen2.5:7b (Runs 1, 2) |

The KEAP1-NRF2 2018 paper is the single most consistently cited reference, appearing in 10 of 12 narratives.

### Divergence

**Selective citation by claude models:** Claude-haiku-4-5 and claude-opus-4-6 cite several papers not referenced by qwen2.5 models:
- "Microglial NLRP3-gasdermin D activation is essential for peripheral inflammation-induced BBB disruption" (2025) — cited only by claude models
- "Potential Therapeutic Effects of New Ruthenium (III) Complex" (2021) — cited only by claude models
- "Toxicogenomic module associations with pathogenesis" (2017) — cited only by claude-opus-4-6
- "Lead Exposure Triggers Ferroptotic Hepatocellular Death" (2026) — cited only by claude-opus-4-6 (Run 1)

**Qwen2.5-specific citations:**
- "Nucleocytoplasmic Shuttling of the NAD+-dependent Histone Deacetylase SIRT1" (2007) — cited by qwen2.5:14b (Run 3) and qwen2.5:7b (Runs 2, 3), not by claude models
- "Signaling pathways and targeted therapy for myocardial infarction" (2022) — cited by qwen2.5:14b (Run 2) and qwen2.5:7b (Run 3), not by claude models

**Contradictory literature use:** No outright contradictory interpretations of the same paper were identified. However, qwen2.5 models cite the myocardial infarction paper to support cardiac toxicity predictions, while claude models do not use this paper and do not predict cardiac toxicity as a primary concern. This represents divergent literature deployment in service of divergent organ predictions.

**Citation accuracy concern:** Claude-opus-4-6 (Run 1) cites "Lead Exposure Triggers Ferroptotic Hepatocellular Death" with a 2026 publication date. This future date warrants scrutiny — it may represent a hallucinated or incorrectly dated reference, which is a reliability concern specific to this model run.

### Concordance Rating: **Moderate-Strong**

Core literature (KEAP1-NRF2 papers, NRF2 overview, NLRP3 liver paper, Rutin paper) is consistently cited. Model-specific literature selections reflect and reinforce model-specific mechanistic and organ-level divergences.

---

## 6. Confidence Assessment — Concordance

### Agreement

All models express **high confidence** in:
- NRF2/KEAP1 pathway activation as the primary adaptive response
- The general dose-response progression from adaptive to adverse
- Liver and kidney as primary target organs

All models express **lower confidence** in:
- Precise dose thresholds for the adaptive-to-adverse transition
- Specific organ rankings beyond liver and kidney
- Novel mechanistic findings not well-represented in existing literature

### Divergence

**Structural approach to confidence:** Claude models embed confidence assessments within their narrative (e.g., "High Confidence Target," "Highest Confidence," "Very High"), while qwen2.5 models provide explicit confidence sections with categorical ratings (High/Moderate/Low). This structural difference makes direct comparison difficult.

**CASP3 confidence:** Qwen2.5:7b (Runs 1 and 3) explicitly rates CASP3-mediated apoptosis as a "novel finding" with "limited literature support" or "low confidence." Claude models treat CASP3 activation as a well-established, high-confidence finding. This is a meaningful divergence in confidence calibration for the same gene.

**NLRP3 confidence:** Qwen2.5:14b (Run 3) rates NLRP3 inflammasome activation as "moderate confidence." Claude models treat NLRP3 as a high-confidence finding with strong literature support. This divergence may reflect the qwen2.5:14b model having less access to the 2025 NLRP3 liver paper that claude models cite extensively.

**Testis prediction confidence:** Claude-opus-4-6 (all runs) rates testis as a "High Confidence" target. Qwen2.5 models do not mention testis at all, implying either low confidence or non-consideration. The absence of a confidence rating for an organ not mentioned is itself informative.

**Intra-model consistency:** Claude-opus-4-6 shows the highest intra-model consistency across its three runs, with nearly identical confidence assessments. Qwen2.5:7b shows the most intra-run variability, with Run 1 expressing lower confidence in CASP3 and NLRP3 than Runs 2 and 3.

### Concordance Rating: **Moderate**

High-level confidence categories (NRF2 = high confidence; transition dose = moderate confidence) are broadly agreed upon. Gene-specific confidence ratings for CASP3 and NLRP3 diverge meaningfully between model families.

---

## High-Confidence Findings

*Claims supported by all 4 model families (claude-haiku-4-5, qwen2.5:14b, qwen2.5:7b, claude-opus-4-6):*

1. **NRF2/KEAP1 pathway activation is the primary early adaptive response.** All 12 narratives identify NFE2L2, KEAP1, HMOX1, NQO1, and GCLC as early-responding genes representing the organism's first-line defense against oxidative stress.

2. **The dose-response follows an adaptive-to-adverse progression.** Low doses trigger cytoprotective responses; high doses trigger inflammatory and apoptotic responses. This three-tier structure is universally reproduced.

3. **Liver is the primary target organ.** All 12 narratives identify the liver as the most affected organ, with consistent mechanistic rationale (xenobiotic metabolism, NRF2 activation, NLRP3 inflammasome, fibrosis).

4. **Kidney is a co-primary target organ.** All 12 narratives identify the kidney, with consistent mechanistic rationale (tubular oxidative stress, apoptosis, inflammation).

5. **NLRP3 inflammasome activation drives high-dose inflammatory toxicity.** All models identify NLRP3, IL1B, and TNF as high-dose adverse response markers.

6. **TP53/BAX/CASP3 apoptotic axis is engaged at intermediate-to-high doses.** All models identify this axis as the primary cell death mechanism.

7. **ROS generation is the central upstream driver of toxicity.** All models, regardless of whether they specify AHR as the MIE, agree that ROS is the proximate cause of the downstream cascade.

8. **TGFB1-mediated fibrotic signaling emerges at high doses.** All claude models and qwen2.5:14b identify this as a high-dose adverse response; qwen2.5:7b implies it through "fibrosis" language without always naming TGFB1 explicitly.

---

## Divergent Findings

### Divergence 1: Identity of the Molecular Initiating Event

**Nature of disagreement:** Claude models (haiku and opus, all 6 runs) identify AHR ligand binding and CYP1A1/CYP1B1 induction as the molecular initiating event, with ROS generation as a downstream consequence of bioactivation. Qwen2.5 models (all 6 runs) identify ROS generation itself as the MIE, without specifying an upstream receptor event.

**Significance:** This is a substantive mechanistic disagreement. If the claude models are correct, the compound is an AHR ligand (consistent with PAHs, dioxins, or similar planar aromatics), and the primary toxicological concern is bioactivation to reactive metabolites. If the qwen2.5 models are correct, the compound may be a direct oxidant or pro-oxidant without receptor-mediated specificity. These hypotheses have different implications for structure-activity relationships and risk assessment.

**Assessment:** The claude models' interpretation is better supported by the dataset, as AHR, CYP1A1, and CYP1B1 are explicitly identified as the earliest-responding genes (BMD 0.2–0.35) in the pathway enrichment data. The qwen2.5 models appear to have either not accessed or not weighted this early-response information.

### Divergence 2: Testis as a Target Organ

**Nature of disagreement:** All three claude-opus-4-6 runs and claude-haiku-4-5 (Run 1) identify testis/male reproductive system as a high-confidence primary target organ with detailed mechanistic rationale (AHR enrichment in testicular tissue, spermatocyte apoptosis via TP53, oxidative stress in cauda epididymis). All six qwen2.5 narratives do not mention testis.

**Significance:** If the claude models are correct, this represents a reproductive toxicity concern that is entirely missed by the qwen2.5 models. The claude models cite specific organ enrichment statistics (19–21 genes annotated to testis) that appear to be drawn from the dataset's organ signature analysis. The qwen2.5 models' omission may reflect either failure to access this data layer or a different prioritization algorithm.

**Assessment:** The testis prediction by claude models appears data-driven (based on organ enrichment statistics) rather than speculative. The qwen2.5 models' silence on this organ is a potential gap rather than a contradictory finding.

### Divergence 3: Heart as a Target Organ

**Nature of disagreement:** Five of six qwen2.5 narratives identify heart as a primary target organ, citing SIRT1, TP53, NLRP3, and IL1B as cardiac markers. Zero of six claude narratives identify heart as a primary target.

**Significance:** This is a direct contradiction in organ prioritization. The qwen2.5 models cite the myocardial infarction signaling paper (2022) to support cardiac involvement. The claude models, despite analyzing the same genes, do not prioritize cardiac tissue.

**Assessment:** The qwen2.5 models' cardiac prediction appears to be driven by the general expression of SIRT1, TP53, and NLRP3 — genes that are expressed in many tissues — rather than by organ-specific enrichment data. The claude models' organ predictions are anchored to quantitative enrichment statistics, which may explain why they do not prioritize heart (if cardiac enrichment is lower than liver, kidney, brain, or testis). The qwen2.5 cardiac prediction should be treated as lower confidence without enrichment data support.

### Divergence 4: Ferroptosis as a Distinct Mechanistic Phase

**Nature of disagreement:** All three claude-opus-4-6 runs identify ferroptosis pathway activation (path:hsa04216, median BMD 0.6) as a distinct early mechanistic phase. Claude-haiku-4-5 does not name ferroptosis as a distinct phase. Qwen2.5 models do not mention ferroptosis.

**Significance:** Ferroptosis is mechanistically distinct from apoptosis and necroptosis, involving iron-dependent lipid peroxidation. If ferroptosis is genuinely activated at low doses (BMD 0.6), this has implications for the types of cellular damage occurring early in the dose-response and for potential therapeutic interventions (ferroptosis inhibitors vs. apoptosis inhibitors).

**Assessment:** Claude-opus-4-6's consistent identification of ferroptosis across all three runs, anchored to a specific pathway (path:hsa04216) and BMD value (0.6), suggests this is a data-driven finding rather than a hallucination. The absence of this finding in other models represents a genuine gap.

### Divergence 5: Circadian Disruption as a Transition Marker

**Nature of disagreement:** All six claude narratives identify circadian clock gene downregulation at BMD 2.0–2.25 as a significant finding and use it as a marker of the adaptive-to-adverse transition. All six qwen2.5 narratives do not mention circadian disruption.

**Significance:** Circadian disruption has functional consequences for xenobiotic metabolism (CYP enzymes are circadian-regulated), antioxidant defense, and inflammatory responses. Its identification as a transition marker provides a mechanistic explanation for why adaptive responses fail at this dose range.

**Assessment:** This is another case where claude models appear to be accessing pathway-level data (circadian pathway enrichment with downregulation direction) that qwen2.5 models are not utilizing.

### Divergence 6: CASP3 Confidence Rating

**Nature of disagreement:** Qwen2.5:7b (Runs 1 and 3) explicitly rates CASP3-mediated apoptosis as a "novel finding" with "limited literature support" or "low confidence." All claude models treat CASP3 as a well-established, high-confidence apoptotic marker.

**Significance:** CASP3 (caspase-3) is one of the most extensively characterized executioner caspases in the apoptosis literature. The qwen2.5:7b model's low-confidence rating for CASP3 appears to reflect a calibration error rather than a genuine uncertainty about the literature. This is a reliability concern specific to qwen2.5:7b.

---

## Model-Specific Observations

### Claude-haiku-4-5 (unique contributions)

- **KEAP1 upregulation paradox** [Run 1]: Specifically flags the "paradoxical upregulation" of KEAP1 alongside NFE2L2 as evidence of active Keap1-Nrf2 cycling, a mechanistic nuance not addressed by other models.
- **SASP as a distinct phase** [Runs 1, 2, 3]: All three runs identify Senescence-Associated Secretory Phenotype as a terminal phase at the highest doses, representing a transition from acute to chronic toxicity. While claude-opus-4-6 also mentions SASP, haiku develops it as a named phase more consistently.
- **GDF15 as mitochondrial stress marker** [Run 1]: Identifies GDF15 (growth differentiation factor 15) upregulation as a marker of mitochondrial stress and metabolic dysfunction, a specific mechanistic annotation not made by other models.
- **Gastrointestinal tract involvement** [Run 2]: Briefly mentions GI tract as a potential target organ, a prediction not made by any other model.

### Qwen2.5:14b (unique contributions)

- **Explicit confidence section structure**: All three runs provide a dedicated, structured confidence assessment section with categorical ratings (High/Moderate/Low) and explicit identification of "novel findings." This structured approach to uncertainty quantification is more systematic than the narrative-embedded confidence assessments of claude models.
- **UPR (unfolded protein response) mention** [Run 2]: Briefly mentions UPR activation as an adaptive response at low doses, a mechanism not explicitly named by other models (though ER stress pathways are mentioned by claude-opus-4-6).
- **Transition point framing** [all runs]: Consistently frames the adaptive-to-adverse transition as a "transition point" with explicit discussion of what drives the shift, providing a cleaner conceptual framework than the phase-based descriptions of claude models.

### Qwen2.5:7b (unique contributions)

- **Lung as target organ** [Run 1]: Uniquely identifies lung as a primary target organ, citing NFKB1, IL1B, and SOD1. No other model makes this prediction. While unsupported by enrichment statistics, it is not implausible given the inflammatory gene signature.
- **Most conservative transition dose** [Run 2]: Estimates the adaptive-to-adverse transition at 1 mg/kg, substantially lower than all other models. If correct, this would have significant implications for risk assessment.
- **CASP3 as novel finding** [Runs 1, 3]: While likely a calibration error (see Divergence 6), this rating does highlight that qwen2.5:7b is applying a more conservative standard for what constitutes "established" vs. "novel" findings.

### Claude-opus-4-6 (unique contributions)

- **Ferroptosis as a distinct early phase** [all 3 runs]: The most consistent unique contribution of this model. All three runs independently identify ferroptosis pathway activation at BMD ~0.6 as a mechanistically distinct early response, with specific pathway identifiers (path:hsa04216/rno04216).
- **SQSTM1/p62-KEAP1 positive feedback loop** [Runs 1, 2]: Specifically identifies the molecular mechanism by which SQSTM1 sequesters KEAP1 to amplify NRF2 signaling, a level of mechanistic detail not provided by any other model.
- **Innate immune pattern recognition at high doses** [all 3 runs]: Consistently identifies TLR, NOD-like receptor, RIG-I-like receptor, and cytosolic DNA-sensing pathway activation at the highest doses as a DAMP-driven response. This represents a coherent mechanistic explanation for why infectious disease pathways are enriched in a non-infectious toxicology context.
- **HAVCR1/KIM-1 as renal biomarker** [Runs 1, 2]: Specifically identifies KIM-1 (kidney injury molecule-1) as a responsive gene within the renal signature, providing a clinically translatable biomarker prediction.
- **Future-dated citation concern** [Run 1]: Cites "Lead Exposure Triggers Ferroptotic Hepatocellular Death" with a 2026 date, which warrants verification as a potential hallucination.

---

## Overall Concordance Summary

### Aggregate Assessment

The 12 narratives show **moderate-to-strong overall concordance** on the core toxicological story but **moderate-to-weak concordance** on mechanistic specifics, organ rankings beyond the top two, and dose-threshold quantification.

### Strongest Consensus Sections

**Section 3 (Mechanism of Action)** and **Section 2 (Organ-Level Prediction — liver and kidney)** show the strongest consensus. The core mechanistic sequence (ROS → NRF2 → NF-κB → NLRP3 → apoptosis) and the identification of liver and kidney as primary targets are robust findings supported by all model families.

**Section 5 (Literature Support)** shows strong consensus on the core reference set (KEAP1-NRF2 2018 paper, NRF2 overview 2020, NLRP3 liver 2025, Rutin 2021), providing a shared evidential foundation.

### Weakest Consensus Sections

**Section 1 (Biological Response Narrative)** shows the greatest structural divergence, primarily because claude models provide BMD-anchored, multi-phase descriptions while qwen2.5 models provide qualitative three-tier descriptions. The content within each tier is broadly consistent, but the granularity gap is substantial.

**Section 2 (Organ-Level Prediction — beyond liver/kidney)** shows weak consensus for testis, heart, and lung predictions, with model-family-specific divergences that likely reflect differential access to organ enrichment statistics.

**Section 6 (Confidence Assessment)** shows moderate divergence, particularly for CASP3 and NLRP3 confidence ratings, and for the structural approach to uncertainty quantification.

### Key Structural Finding

The most important meta-level observation is that **the two claude model families (haiku and opus) show substantially higher intra-family consistency and greater mechanistic specificity than the two qwen2.5 model families**. The claude models consistently access and utilize quantitative pathway enrichment data (BMD values, enrichment fold-changes, gene counts per pathway), while qwen2.5 models appear to work primarily from qualitative gene-level information. This structural difference in data utilization — rather than fundamental disagreement about biology — accounts for most of the cross-model divergences observed.

Within model families, **claude-opus-4-6 shows the highest intra-run consistency** (three runs produce nearly identical narratives), while **qwen2.5:7b shows the most intra-run variability** (confidence ratings and organ predictions shift between runs). This suggests claude-opus-4-6 is the most deterministic of the four models for this task, and qwen2.5:7b is the least.

### Priority Areas for Further Investigation

1. **Testis as a target organ**: The claude models' consistent, data-anchored prediction of reproductive toxicity warrants experimental validation, as it is entirely absent from qwen2.5 analyses.
2. **Ferroptosis at low doses**: Claude-opus-4-6's consistent identification of ferroptosis pathway activation at BMD ~0.6 is a specific, testable prediction not reproduced by other models.
3. **AHR as MIE vs. direct ROS generation**: The mechanistic divergence on the identity of the MIE has direct implications for compound characterization and should be resolved through receptor binding assays or AHR knockout experiments.
4. **Transition dose quantification**: The range of transition dose estimates (BMD 1–5 across models) is wide enough to have practical risk assessment implications and warrants more precise characterization.
