"""Generate bmdx.docx -- the full project paper as a Word document."""

from docx import Document
from docx.shared import Inches, Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn


def fmt(paragraph, size=11, bold=False, italic=False, font="Calibri", color=None,
        space_after=Pt(6), space_before=Pt(0), align=None):
    """Apply formatting to a paragraph."""
    pf = paragraph.paragraph_format
    pf.space_after = space_after
    pf.space_before = space_before
    if align:
        pf.alignment = align
    for run in paragraph.runs:
        run.font.size = Pt(size)
        run.font.name = font
        run.bold = bold
        run.italic = italic
        if color:
            run.font.color.rgb = RGBColor(*color)


def add_heading(doc, text, level=1):
    h = doc.add_heading(text, level=level)
    return h


def add_para(doc, text="", bold=False, italic=False, size=11):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    run.font.name = "Calibri"
    p.paragraph_format.space_after = Pt(6)
    return p


def add_bold_lead(doc, lead, rest):
    """Add paragraph with bold lead text followed by normal text."""
    p = doc.add_paragraph()
    r1 = p.add_run(lead)
    r1.bold = True
    r1.font.size = Pt(11)
    r1.font.name = "Calibri"
    r2 = p.add_run(rest)
    r2.font.size = Pt(11)
    r2.font.name = "Calibri"
    p.paragraph_format.space_after = Pt(6)
    return p


def add_bullet(doc, text, bold_prefix=""):
    p = doc.add_paragraph(style="List Bullet")
    if bold_prefix:
        r = p.add_run(bold_prefix)
        r.bold = True
        r.font.size = Pt(11)
        r.font.name = "Calibri"
    r = p.add_run(text)
    r.font.size = Pt(11)
    r.font.name = "Calibri"
    p.paragraph_format.space_after = Pt(2)
    return p


def add_numbered(doc, text, bold_prefix=""):
    p = doc.add_paragraph(style="List Number")
    if bold_prefix:
        r = p.add_run(bold_prefix)
        r.bold = True
        r.font.size = Pt(11)
        r.font.name = "Calibri"
    r = p.add_run(text)
    r.font.size = Pt(11)
    r.font.name = "Calibri"
    p.paragraph_format.space_after = Pt(4)
    return p


def add_table(doc, headers, rows, col_widths=None):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Light Shading Accent 1"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    # Header row
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = h
        for p in cell.paragraphs:
            for r in p.runs:
                r.bold = True
                r.font.size = Pt(10)
                r.font.name = "Calibri"

    # Data rows
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            cell = table.rows[ri + 1].cells[ci]
            cell.text = str(val)
            for p in cell.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(10)
                    r.font.name = "Calibri"

    if col_widths:
        for i, w in enumerate(col_widths):
            for row in table.rows:
                row.cells[i].width = Cm(w)

    doc.add_paragraph()  # spacing
    return table


def add_code_block(doc, code):
    p = doc.add_paragraph()
    run = p.add_run(code)
    run.font.name = "Consolas"
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(30, 30, 30)
    pf = p.paragraph_format
    pf.space_before = Pt(4)
    pf.space_after = Pt(4)
    # Light gray background via shading
    shading = p._element.get_or_add_pPr()
    shd = shading.makeelement(qn("w:shd"), {
        qn("w:val"): "clear",
        qn("w:color"): "auto",
        qn("w:fill"): "F0F0F0",
    })
    shading.append(shd)
    return p


def build():
    doc = Document()

    # -- Title --
    title = doc.add_heading("Citation-Graph-Driven Toxicogenomics Gene Discovery", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = subtitle.add_run(
        "Identify hallmark genes for organ-specific toxicity in rat, "
        "relevant to human health, by mining the scientific literature "
        "at scale and cross-referencing with Gene Ontology biological "
        "process annotations."
    )
    run.font.size = Pt(12)
    run.italic = True
    run.font.name = "Calibri"

    # ================================================================
    # MOTIVATION
    # ================================================================
    add_heading(doc, "Motivation", level=1)

    p = doc.add_paragraph()
    r = p.add_run("The architecture of this pipeline was inspired by ")
    r.font.size = Pt(11)
    r.font.name = "Calibri"
    r = p.add_run("Recursive Language Models")
    r.font.size = Pt(11)
    r.font.name = "Calibri"
    r.bold = True
    r = p.add_run(
        " (Zhang, Kraska & Khattab, 2026; arXiv:2512.24601). "
        "RLMs address the fundamental problem that LLMs degrade on long inputs: "
        "instead of feeding an entire corpus into context, the model holds data "
        "as variables in a REPL and writes code to decompose, filter, and "
        "recursively query itself on manageable pieces. On BrowseComp-Plus "
        "(6\u201311M token multi-hop QA), RLM achieved 91.3% accuracy where "
        "the base model scored 0%."
    )
    r.font.size = Pt(11)
    r.font.name = "Calibri"
    p.paragraph_format.space_after = Pt(6)

    p = add_para(doc,
        "This pattern \u2014 give the agent a handle to a large dataset, let it "
        "programmatically decompose and recursively query itself \u2014 maps "
        "directly onto literature analysis. Rather than stuffing thousands of "
        "papers into context, our pipeline:"
    )

    add_numbered(doc,
        "The citation graph crawler (citegraph.py) traverses the Semantic Scholar "
        "API graph structure, selecting papers via relevance scoring and governor "
        "heuristics \u2014 the equivalent of RLM\u2019s code-based chunking and filtering.",
        bold_prefix="Programmatic decomposition. "
    )
    add_numbered(doc,
        "A local LLM (Qwen 2.5 14B) processes each paper\u2019s abstract "
        "individually (extract.py), extracting structured claims, genes, and "
        "organs \u2014 the equivalent of RLM\u2019s llm_query() calls on individual chunks.",
        bold_prefix="Recursive per-chunk extraction. "
    )
    add_numbered(doc,
        "Results are accumulated across 2,315 papers through normalization, "
        "deduplication, and consensus classification \u2014 the equivalent of "
        "RLM\u2019s REPL variable accumulation and final synthesis.",
        bold_prefix="Programmatic accumulation. "
    )
    add_numbered(doc,
        "The accumulated gene set is enriched against external databases "
        "(GO, KEGG, Reactome) and unified into a queryable analytical "
        "database \u2014 extending beyond what any single-context LLM call "
        "could achieve.",
        bold_prefix="Cross-reference enrichment. "
    )

    add_para(doc,
        "The key insight from RLMs applied here: the bottleneck in literature "
        "analysis is not the LLM\u2019s reasoning ability but its context window. "
        "By decomposing the problem into graph traversal (code) and per-paper "
        "extraction (LLM), the pipeline scales to corpus sizes that would be "
        "impossible in a single prompt."
    )

    # ================================================================
    # PHASE 1
    # ================================================================
    add_heading(doc, "Phase 1: Citation Graph Construction", level=1)

    add_bold_lead(doc, "Approach. ",
        "Rather than manually curating papers, we built a citation graph "
        "outward from seed papers using the Semantic Scholar API, governed "
        "by relevance-scoring heuristics that control expansion."
    )

    add_bold_lead(doc, "Seed selection. ",
        "7 papers were selected by DOI as anchors spanning the field:"
    )
    add_bullet(doc,
        "Meier et al. 2024 \u2014 Progress in toxicogenomics to protect human "
        "health (Nature Reviews Genetics, comprehensive review, 193 references)"
    )
    add_bullet(doc, "TXG-MAP (2017) and TXG-MAPr (2021) \u2014 liver co-expression module frameworks")
    add_bullet(doc, "Open TG-GATEs (2014) \u2014 the foundational toxicogenomics database")
    add_bullet(doc, "TransTox (2024) \u2014 multi-organ transcriptomic translation (liver \u2194 kidney)")
    add_bullet(doc, "Reconciled rat-human metabolic networks (2017)")
    add_bullet(doc, "MSigDB Hallmark Gene Sets (2015)")

    add_para(doc,
        "An additional 5 seed papers were added via keyword search targeting "
        "underrepresented organs (kidney, heart)."
    )

    add_bold_lead(doc, "Graph expansion. ",
        "From each seed, we fetched its references and citing papers from "
        "Semantic Scholar, then expanded outward to depth 2. Each candidate "
        "paper was scored for relevance before inclusion."
    )

    add_bold_lead(doc, "Governor system. ",
        "Five stopping criteria controlled the crawl to prevent runaway expansion:"
    )
    add_numbered(doc,
        "Each paper was scored 0.0\u20131.0 against 25 topic keywords "
        "(toxicogenomics, gene expression, transcriptomics, organ names, "
        "biomarker, etc.). Title matches were weighted 3x over abstract matches. "
        "Papers below 0.3 were discarded. Of ~3,000 papers considered, "
        "2,208 were rejected by this filter.",
        bold_prefix="Relevance threshold (0.3). "
    )
    add_numbered(doc,
        "No paper more than 2 citation hops from a seed was included, "
        "preventing drift into tangential fields.",
        bold_prefix="Max depth (2). "
    )
    add_numbered(doc,
        "Hard budget cap. The crawl exhausted its queue at 798 papers before "
        "hitting this limit, indicating natural saturation of the "
        "relevance-filtered graph.",
        bold_prefix="Max papers (800). "
    )
    add_numbered(doc,
        "A sliding window tracked the novelty of incoming papers by measuring "
        "new bigram concepts. If the last 20 papers contributed fewer than 5% "
        "new concepts, the crawl would stop. This did not trigger \u2014 the "
        "relevance filter was strict enough to maintain novelty.",
        bold_prefix="Saturation detection. "
    )
    add_numbered(doc,
        "Hard cap on Semantic Scholar API requests. The crawl used 293.",
        bold_prefix="API budget (500 calls). "
    )

    add_bold_lead(doc, "Result. ",
        "798 papers, 999 citation edges, 326 reviews. Organ distribution: "
        "liver (60 papers at depth 0), kidney (40), heart (24), brain (20), "
        "lung (4), intestine (4), plus minor representation of adrenal, spleen, "
        "testis. The primary focus on liver and kidney reflects the seed "
        "selection; other organs were incidental catches via citation chains."
    )

    # ================================================================
    # PHASE 2
    # ================================================================
    add_heading(doc, "Phase 2: LLM-Based Claim and Gene Extraction", level=1)

    add_bold_lead(doc, "Approach. ",
        "Each paper\u2019s abstract was processed by a local LLM (Qwen 2.5 14B, "
        "Q4_K_M quantization) to extract structured information: gene names, "
        "organs studied, methods used, scientific claims, and a stance "
        "classification."
    )

    add_bold_lead(doc, "Infrastructure. ", "Two GPUs ran in parallel:")
    add_bullet(doc, "RTX 3080 Ti (12GB, local) \u2014 qwen2.5:14b via Ollama")
    add_bullet(doc, "RX 6900 XT (16GB, remote via SSH tunnel) \u2014 qwen2.5:14b via Ollama")

    add_para(doc,
        "Papers were distributed round-robin across endpoints. No cloud LLM "
        "tokens were consumed."
    )

    add_bold_lead(doc, "Extraction prompt. ",
        "The LLM was instructed to return a JSON object with fields for claims, "
        "genes (as standard symbols), organs, methods, species, a stance "
        "classification (supports_consensus / challenges_consensus / neutral / "
        "novel_finding), and a confidence score. A JSON parser with fallback "
        "heuristics handled formatting variations."
    )

    add_bold_lead(doc, "Result. ",
        "650 of 798 papers had abstracts available for extraction (148 lacked "
        "abstracts in Semantic Scholar). 172 papers yielded explicit gene names. "
        "This is expected \u2014 most papers discuss genes in full text, not "
        "abstracts."
    )

    # ================================================================
    # PHASE 3
    # ================================================================
    add_heading(doc, "Phase 3: Gene Name Normalization", level=1)

    add_bold_lead(doc, "Problem. ",
        "The same gene appears under different names across papers: P53 vs "
        "TP53, BCL-2 vs BCL2, TNF-alpha vs TNFA vs TNF, NRF2 vs NFE2L2, "
        "Caspase-3 vs CASP3, KIM-1 vs HAVCR1."
    )

    add_bold_lead(doc, "Approach. ",
        "A curated alias table of ~100 mappings was built covering:"
    )
    add_bullet(doc, "Common name \u2194 HGNC symbol (NRF2 \u2192 NFE2L2, KIM-1 \u2192 HAVCR1)")
    add_bullet(doc, "Punctuation/casing variants (BCL-2 \u2192 BCL2, TNF-alpha \u2192 TNF)")
    add_bullet(doc, "Protein names \u2192 gene symbols (Caspase-3 \u2192 CASP3)")
    add_bullet(doc, "Greek letter variants (PPARalpha \u2192 PPARA, IL-1beta \u2192 IL1B)")

    add_para(doc,
        "Organ names were similarly normalized (hippocampus/cerebellum/cortex "
        "\u2192 brain, hepatocytes \u2192 liver, etc.)."
    )

    add_bold_lead(doc, "Impact. ",
        "Normalization consolidated 461 raw gene names into 432 unique genes "
        "and significantly boosted consensus counts:"
    )
    add_bullet(doc, "TP53: 8 \u2192 14 papers (merged P53 + TP53)")
    add_bullet(doc, "BCL2: 4 \u2192 11 papers (merged BCL-2 + BCL2)")
    add_bullet(doc, "TNF: 4 \u2192 8 papers (merged TNF-alpha + TNFA + TNF)")
    add_bullet(doc, "HAVCR1: 0 \u2192 4 papers (merged KIM-1 + KIM1)")

    # ================================================================
    # PHASE 4
    # ================================================================
    add_heading(doc, "Phase 4: Consensus Classification", level=1)

    add_bold_lead(doc, "Heuristic. ",
        "Genes were classified by the number of independent papers "
        "mentioning them:"
    )

    add_bullet(doc,
        "35 genes. These are established hallmark genes with cross-study "
        "validation. The top tier: NFE2L2 (27 papers), TP53 (14), BAX (12), "
        "PPARA (12), BCL2 (11), TNF (8), NFKB1 (7), CASP3 (7), IL6 (7).",
        bold_prefix="Consensus (3+ papers): "
    )
    add_bullet(doc,
        "34 genes. Corroborated by at least one independent study. Includes "
        "CLU, CCNG1, EGR1, FGF21, KIM-1/HAVCR1, DRP1, GPX4.",
        bold_prefix="Moderate evidence (2 papers): "
    )
    add_bullet(doc,
        "363 genes. These include both well-known genes that happened to "
        "appear in only one abstract (undersampling artifact) and genuinely "
        "novel candidates from recent papers. Notably, several clusters of "
        "single-mention genes came from recent (2025\u20132026) single-cell "
        "sequencing and ML-based network studies, representing frontier "
        "candidates not yet validated by independent work.",
        bold_prefix="Single mention (1 paper): "
    )

    add_bold_lead(doc, "Organ-specific patterns. ",
        "The consensus genes partition into:"
    )
    add_bullet(doc, "Universal stress response: NFE2L2, BAX, TP53, BCL2 (appear across nearly all organs)")
    add_bullet(doc, "Liver-specific: PPARA, AHR, CAR, CYP1A1, CYP7A1, GCLC, HSP90AA1")
    add_bullet(doc, "Kidney-emerging: HAVCR1 (KIM-1), CLU, CD44, MDM2")
    add_bullet(doc, "Heart: MFN2, SIRT1, IL1B, AMPK, TTN, DRP1 (mitochondrial dynamics)")
    add_bullet(doc, "Cross-organ inflammation: TNF, NFKB1, IL6, IL1B")

    # ================================================================
    # PHASE 5
    # ================================================================
    add_heading(doc, "Phase 5: GO Term Cross-Reference", level=1)

    add_bold_lead(doc, "Approach. ",
        "2,840 Gene Ontology Biological Process terms (from BMDExpress "
        "reference UMAP data, with cluster assignments) were cross-referenced "
        "with gene annotations from two sources:"
    )
    add_numbered(doc,
        "12,363 GO terms, 564K annotations",
        bold_prefix="Rat GO annotations (EBI GOA, goa_rat.gaf) \u2014 "
    )
    add_numbered(doc,
        "11,207 GO terms, 834K annotations",
        bold_prefix="Human GO annotations (EBI GOA, goa_human.gaf) \u2014 "
    )

    add_para(doc,
        "An outer join was performed: every GO term appears in the output "
        "regardless of whether gene annotations exist. Each gene row is "
        "tagged with species provenance:"
    )
    add_bullet(doc, "rat \u2014 annotated only in rat GAF")
    add_bullet(doc, "human \u2014 annotated only in human GAF")
    add_bullet(doc, "rat | human \u2014 annotated in both (conserved ortholog with shared function)")

    add_para(doc,
        "For rat and rat | human rows, the original rat gene symbol is "
        "preserved in a separate column alongside the HGNC display symbol. "
        "Each gene was then cross-referenced against the toxicogenomics "
        "consensus analysis, adding evidence level, paper count, and "
        "implicated organs."
    )

    add_bold_lead(doc, "Result. ",
        "130,699 rows covering all 2,840 GO terms. 2,391 terms had gene "
        "annotations (449 had none in either species). 6,074 rows matched "
        "a toxicogenomics gene, spanning 1,318 distinct GO biological "
        "processes. Of these, 1,629 rows matched consensus-level genes, "
        "739 matched moderate-evidence genes, and 3,706 matched "
        "single-mention genes."
    )

    # ================================================================
    # PHASE 6
    # ================================================================
    add_heading(doc, "Phase 6: Organ-Specific Crawls", level=1)

    add_bold_lead(doc, "Problem. ",
        "The general crawl (Phase 1) was seeded with liver/kidney-focused "
        "papers, leaving heart, brain, and lung underrepresented."
    )

    add_bold_lead(doc, "Approach. ",
        "Three dedicated organ crawls were run, each with its own seed papers, "
        "search queries, and organ-boost keywords that gave +0.15 relevance "
        "to papers matching organ-specific vocabulary:"
    )
    add_bullet(doc,
        "6 DOI seeds (cardiotoxicity reviews, anthracycline signatures, "
        "TG-GATEs) + 5 keyword searches. Boost keywords: cardiac, "
        "cardiotoxic, doxorubicin, troponin, myocardial, etc.",
        bold_prefix="Heart (400 papers): "
    )
    add_bullet(doc,
        "5 DOI seeds (neurotoxicity transcriptomics, organophosphate ML "
        "study) + 5 keyword searches. Boost keywords: neurotoxic, "
        "hippocampal, dopaminergic, astrocyte, etc.",
        bold_prefix="Brain (400 papers): "
    )
    add_bullet(doc,
        "5 DOI seeds (nanomaterial meta-analysis, MWCNT inhalation) + 5 "
        "keyword searches. Boost keywords: pulmonary, inhalation, alveolar, "
        "nanoparticle, etc.",
        bold_prefix="Lung (400 papers): "
    )

    add_bold_lead(doc, "Result. ",
        "1,200 additional papers across the three organs, with 924 unique "
        "after deduplication against the general crawl."
    )

    # ================================================================
    # PHASE 7
    # ================================================================
    add_heading(doc, "Phase 7: Gene-Function Crawl", level=1)

    add_bold_lead(doc, "Problem. ",
        "The toxicogenomics crawls (Phases 1 and 6) only retained papers "
        "matching tox vocabulary. This missed gene-function papers \u2014 "
        "papers that explain WHY a gene matters for organ-specific biology "
        'but don\u2019t use tox terminology (e.g., "MFN2 regulates '
        'mitochondrial fusion in cardiomyocytes").'
    )

    add_bold_lead(doc, "Approach. ",
        "A second-pass crawl (genefunc_crawl.py) searched Semantic Scholar "
        "for each consensus/moderate gene\u2019s biological function in its "
        "associated organs. Key differences from the main crawl:"
    )
    add_bullet(doc,
        'were gene-centric: e.g., "NFE2L2 liver function mechanism", '
        '"MFN2 cardiomyocyte role biological"',
        bold_prefix="Search queries "
    )
    add_bullet(doc,
        "required gene name in title/abstract + organ keyword mention, "
        "with no toxicogenomics vocabulary requirement",
        bold_prefix="Relevance scoring "
    )
    add_bullet(doc,
        "from top search results to catch related function papers",
        bold_prefix="1-hop expansion "
    )

    add_para(doc, "Two passes were run:")
    add_bullet(doc,
        "Pass 1: covered 14 genes (NFE2L2, TP53, BAX, BCL2, etc.) before "
        "hitting 200 API call budget, yielding 246 papers"
    )
    add_bullet(doc,
        "Pass 2: covered 16 additional genes (KEAP1, GDF15, SQSTM1, SOD1, "
        "BTG2, etc.) with a 500 API call budget, yielding 400 papers"
    )

    add_bold_lead(doc, "Result. ",
        "646 gene-function papers across 30 genes, covering brain (124), "
        "liver (155), heart (104), kidney (105) \u2014 substantially expanding "
        "the evidence base for genes that were previously marginal."
    )

    # ================================================================
    # PHASE 8
    # ================================================================
    add_heading(doc, "Phase 8: Pathway Enrichment", level=1)

    add_bold_lead(doc, "Approach. ",
        "The 69 consensus + moderate genes were cross-referenced against "
        "two pathway databases (pathway_enrich.py):"
    )
    add_numbered(doc,
        "All human (hsa) and rat (rno) gene-pathway links were downloaded. "
        "Gene IDs were mapped to symbols via rest.kegg.jp/list/{species}. "
        "8,720 human and 10,032 rat genes matched, yielding pathway "
        "annotations for our genes.",
        bold_prefix="KEGG (REST API, bulk download): "
    )
    add_numbered(doc,
        "Each gene was queried against Homo sapiens pathways. 69/69 genes "
        "returned at least one pathway hit.",
        bold_prefix="Reactome (REST API, per-gene query): "
    )

    add_bold_lead(doc, "Result. ",
        "pathway_enrichment.tsv with 2,860 rows of gene-pathway associations, "
        "covering KEGG (human + rat, deduplicated by pathway name) and "
        "Reactome pathways for all 69 genes."
    )

    # ================================================================
    # PHASE 9
    # ================================================================
    add_heading(doc, "Phase 9: Hybrid Scoring", level=1)

    add_bold_lead(doc, "Approach. ",
        "To ensure future crawls automatically retain gene-function papers, "
        "a gene-aware relevance floor was added to citegraph.py:"
    )
    add_bullet(doc,
        "A known_genes set can be loaded from the consensus JSON "
        "(68 genes with symbols \u2265 3 chars)"
    )
    add_bullet(doc,
        "In score_relevance(): after normal keyword scoring, if a paper "
        "mentions any known gene (case-sensitive word-boundary regex) AND "
        "any organ keyword, the score is raised to at least 0.35"
    )
    add_bullet(doc,
        "This ensures gene-function papers pass the relevance threshold "
        "even without tox vocabulary"
    )

    # ================================================================
    # PHASE 10
    # ================================================================
    add_heading(doc, "Phase 10: Merged Consensus", level=1)

    add_bold_lead(doc, "Approach. ",
        "All 7 extraction files were merged (extract.py merge), "
        "deduplicating by paper ID:"
    )

    add_table(doc,
        ["Source", "Total", "Unique (after dedup)"],
        [
            ["citegraph_output/ (initial)", "50", "50"],
            ["citegraph_output_800/ (expanded)", "798", "750"],
            ["citegraph_output_brain/", "400", "271"],
            ["citegraph_output_genefunc/ (pass 1)", "246", "246"],
            ["citegraph_output_genefunc2/ (pass 2)", "400", "345"],
            ["citegraph_output_heart/", "400", "310"],
            ["citegraph_output_lung/", "400", "343"],
            ["Total", "2,694", "2,315"],
        ],
    )

    add_bold_lead(doc, "Result. ",
        "The merged consensus significantly expanded gene coverage:"
    )
    add_bullet(doc, " (3+ papers) \u2014 up from 35 in Phase 4", bold_prefix="161 consensus genes")
    add_bullet(doc, " (2 papers) \u2014 up from 34", bold_prefix="149 moderate evidence genes")
    add_bullet(doc, " \u2014 up from 432", bold_prefix="1,377 total unique genes")

    add_para(doc,
        "Top genes by paper count: NFE2L2 (81), TP53 (63), BCL2 (45), "
        "BAX (41), SIRT1 (39), IL6 (38), KEAP1 (37), TNF (36), HMOX1 (32), "
        "CASP3 (30)."
    )

    add_para(doc,
        "New consensus genes promoted from moderate/single: MFN2 (24 papers), "
        "GDF15 (20), SQSTM1 (12), BDNF (12), SOD1 (13), PPARGC1A (13), "
        "PIK3CA (12)."
    )

    # ================================================================
    # PHASE 11: ANALYTICAL DATABASE
    # ================================================================
    add_heading(doc, "Phase 11: Analytical Database", level=1)

    add_para(doc,
        "All crawl outputs, extractions, GO annotations, and pathway "
        "enrichment data are unified into a single DuckDB database "
        "(bmdx.duckdb) for fast analytical queries. The schema normalizes "
        "the scattered JSON/TSV files into 9 interlinked tables, enabling "
        "cross-domain queries that would otherwise require custom scripts "
        "to join disparate file formats."
    )

    # -- Schema diagram --
    add_heading(doc, "Entity-Relationship Diagram", level=2)

    add_para(doc,
        "The following diagram shows all 9 tables, their columns, and the "
        "relationships between them. Three core entity tables (go_terms, "
        "genes, papers) anchor the schema. Six junction/linking tables "
        "connect them: gene_go_terms bridges genes to GO terms, paper_genes/"
        "paper_organs/paper_claims attach extraction results to papers, "
        "citation_edges form the paper-to-paper citation graph, and pathways "
        "link genes to KEGG and Reactome pathway databases."
    )

    doc.add_picture("schema.png", width=Inches(6.5))
    last_paragraph = doc.paragraphs[-1]
    last_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # -- Schema narrative --
    add_heading(doc, "Schema Design", level=2)

    add_heading(doc, "Core Entity Tables", level=3)

    add_bold_lead(doc, "go_terms (2,840 rows). ",
        "Each row represents one Gene Ontology Biological Process term from "
        "the BMDExpress reference UMAP dataset. The go_id primary key "
        "(e.g., GO:0000018) uniquely identifies the term. The cluster_id "
        "column stores the HDBSCAN cluster assignment from dimensionality "
        "reduction (\u22121 = unclustered), while umap_1 and umap_2 store "
        "the 2D UMAP embedding coordinates. These coordinates allow spatial "
        "queries: finding all GO terms near a point in UMAP space, or "
        "identifying which biological processes cluster together."
    )

    add_bold_lead(doc, "genes (21,490 rows). ",
        "The union of all gene symbols encountered across the entire pipeline. "
        "The gene_symbol primary key is the uppercase HGNC symbol after "
        "normalization (Phase 3). The evidence column classifies each gene: "
        "'consensus' (161 genes, 3+ papers), 'moderate' (149, 2 papers), "
        "'single' (1,067, 1 paper), or NULL (~20k genes imported from GO "
        "annotations that were not mentioned in any crawled paper). "
        "mention_count records the number of papers mentioning the gene, "
        "and organs is an array of organ names associated with the gene "
        "from the extraction data. This table serves as the central gene "
        "registry that all other gene-referencing tables join against."
    )

    add_bold_lead(doc, "papers (2,319 rows). ",
        "Deduplicated papers from all 7 crawl directories. The paper_id "
        "primary key is the Semantic Scholar SHA-1 hash. Metadata includes "
        "title, year, abstract, venue, doi, citation_count, and "
        "reference_count. The relevance_score preserves the governor\u2019s "
        "relevance assessment (0.0\u20131.0). Boolean flags is_seed and "
        "is_review mark seed papers and review articles. The source column "
        "records which crawl directory the paper first appeared in "
        '("base", "800", "heart", "brain", "lung", "genefunc", "genefunc2"), '
        "enabling analysis of coverage by crawl strategy."
    )

    add_heading(doc, "Junction Tables", level=3)

    add_bold_lead(doc, "gene_go_terms (130,250 rows). ",
        "Links genes to GO terms, loaded from go_term_genes.tsv (the output "
        "of Phase 5). Each row records a gene_symbol, go_id, species "
        "provenance ('rat', 'human', or 'rat | human'), and the original "
        "rat_symbol for cross-species reference. This is the largest table "
        "and enables queries like: which GO biological processes involve a "
        "given gene? Which genes participate in a specific GO term cluster?"
    )

    add_bold_lead(doc, "paper_genes (2,769 rows). ",
        "Links papers to the genes they mention, derived from the LLM "
        "extraction data (Phase 2). Gene symbols are normalized (Phase 3) "
        "and deduplicated per paper. This table is the primary bridge between "
        "the literature evidence and the gene-centric analysis: it answers "
        '"which papers mention gene X?" and "which genes does paper Y discuss?"'
    )

    add_bold_lead(doc, "paper_organs (2,326 rows). ",
        "Links papers to the organs they study. Organ names are normalized "
        "(e.g., hepatocytes \u2192 liver, hippocampus \u2192 brain). Enables "
        "organ-specific filtering: find all papers studying heart toxicity, "
        "then join to paper_genes to find which genes are discussed in that "
        "context."
    )

    add_bold_lead(doc, "paper_claims (4,431 rows). ",
        "Scientific claims extracted from paper abstracts by the LLM. Each "
        "claim is a single finding or assertion (e.g., 'The TP53 R273C "
        "mutation is more prevalent in lower-grade, IDH-mutant astrocytomas'). "
        "Joining paper_claims with paper_genes yields gene-specific claims "
        "across the corpus."
    )

    add_bold_lead(doc, "citation_edges (2,224 rows). ",
        "The citation graph: source_id (citer) \u2192 target_id (cited). "
        "Edges are deduplicated across all 7 crawl directories. Enables "
        "network analysis: finding highly-cited papers, identifying citation "
        "clusters, or tracing how a finding propagated through the literature."
    )

    add_bold_lead(doc, "pathways (2,860 rows). ",
        "Gene-pathway associations from KEGG and Reactome (Phase 8). The "
        "pathway_db discriminator ('kegg' or 'reactome') distinguishes the "
        "source database. Each row links a gene_symbol to a pathway_id and "
        "pathway_name, with species annotation. Reactome pathway names are "
        "cleaned of HTML markup from the API response. This table enables "
        "pathway-level queries: which pathways are enriched among consensus "
        "genes? Which genes share a KEGG pathway?"
    )

    add_heading(doc, "Cross-Domain Query Examples", level=2)

    add_para(doc,
        "The normalized schema enables queries that span all data sources "
        "in a single SQL statement. Examples:"
    )

    add_bold_lead(doc, "Consensus genes in a UMAP cluster with their pathways. ",
        "Joins genes \u2192 gene_go_terms \u2192 go_terms (for spatial filtering) "
        "and genes \u2192 pathways (for functional annotation):"
    )
    add_code_block(doc,
        "SELECT g.gene_symbol, gt.go_term, p.pathway_id\n"
        "FROM genes g\n"
        "JOIN gene_go_terms ggt ON g.gene_symbol = ggt.gene_symbol\n"
        "JOIN go_terms gt ON ggt.go_id = gt.go_id\n"
        "JOIN pathways p ON g.gene_symbol = p.gene_symbol\n"
        "WHERE g.evidence = 'consensus'\n"
        "  AND gt.cluster_id = 5\n"
        "  AND p.pathway_db = 'kegg';"
    )

    add_bold_lead(doc, "Papers mentioning a gene, with their claims. ",
        "Joins papers \u2192 paper_genes (for gene filtering) and papers \u2192 "
        "paper_claims (for extracted findings):"
    )
    add_code_block(doc,
        "SELECT p.title, p.year, pc.claim\n"
        "FROM paper_genes pg\n"
        "JOIN papers p ON pg.paper_id = p.paper_id\n"
        "LEFT JOIN paper_claims pc ON pg.paper_id = pc.paper_id\n"
        "WHERE pg.gene_symbol = 'TP53';"
    )

    add_bold_lead(doc, "Consensus genes that appear in heart papers. ",
        "Joins genes \u2192 paper_genes \u2192 paper_organs to filter by organ context:"
    )
    add_code_block(doc,
        "SELECT DISTINCT g.gene_symbol, g.mention_count\n"
        "FROM genes g\n"
        "JOIN paper_genes pg ON g.gene_symbol = pg.gene_symbol\n"
        "JOIN paper_organs po ON pg.paper_id = po.paper_id\n"
        "WHERE g.evidence = 'consensus' AND po.organ = 'heart'\n"
        "ORDER BY g.mention_count DESC;"
    )

    add_heading(doc, "Data Sources", level=2)

    add_table(doc,
        ["Source File", "Tables Fed"],
        [
            ["referenceUmapData.ts (BMDExpress)", "go_terms"],
            ["go_term_genes.tsv", "gene_go_terms, genes (supplement)"],
            ["gene_consensus_merged.json", "genes"],
            ["gene_consensus_merged_extractions.json", "paper_genes, paper_organs, paper_claims"],
            ["citegraph_output*/papers.json (\u00d77)", "papers"],
            ["citegraph_output*/edges.json (\u00d77)", "citation_edges"],
            ["pathway_enrichment.tsv", "pathways"],
        ],
        col_widths=[8, 8],
    )

    add_heading(doc, "Table Summary", level=2)

    add_table(doc,
        ["Table", "Rows", "Description"],
        [
            ["go_terms", "2,840", "GO Biological Process terms with UMAP coordinates and HDBSCAN clusters"],
            ["genes", "21,490", "Union of all gene symbols: 161 consensus, 149 moderate, 1,067 single, ~20k GO"],
            ["papers", "2,319", "Deduplicated papers from all 7 crawl directories"],
            ["gene_go_terms", "130,250", "Gene-to-GO-term annotations (rat, human, or both)"],
            ["paper_genes", "2,769", "Which genes each paper mentions (normalized)"],
            ["paper_organs", "2,326", "Which organs each paper studies (normalized)"],
            ["paper_claims", "4,431", "Scientific claims extracted from abstracts"],
            ["citation_edges", "2,224", "Paper-cites-paper citation graph edges"],
            ["pathways", "2,860", "Gene-pathway associations (KEGG + Reactome)"],
        ],
        col_widths=[3.5, 2, 11],
    )

    # ================================================================
    # OUTPUTS
    # ================================================================
    add_heading(doc, "Outputs", level=1)

    add_table(doc,
        ["File", "Contents"],
        [
            ["bmdx.duckdb", "Analytical database (9 tables, 9.8 MB)"],
            ["citegraph_output_800/papers.json", "798 papers with metadata, relevance scores, organ tags"],
            ["citegraph_output_800/extractions.json", "798 LLM extractions (claims, genes, organs, methods)"],
            ["citegraph_output_brain/papers.json", "400 brain-focused papers"],
            ["citegraph_output_heart/papers.json", "400 heart-focused papers"],
            ["citegraph_output_lung/papers.json", "400 lung-focused papers"],
            ["citegraph_output_genefunc/papers.json", "246 gene-function papers (pass 1, 14 genes)"],
            ["citegraph_output_genefunc2/papers.json", "400 gene-function papers (pass 2, 16 genes)"],
            ["gene_consensus.json", "Original 432 genes (Phases 1\u20134 only)"],
            ["gene_consensus_merged.json", "1,377 genes from all 7 sources merged"],
            ["pathway_enrichment.tsv", "2,860 gene-pathway annotations (KEGG + Reactome)"],
            ["go_term_genes.tsv", "130,699 rows: GO terms \u00d7 genes \u00d7 species \u00d7 tox evidence"],
        ],
        col_widths=[7, 10],
    )

    # ================================================================
    # USAGE
    # ================================================================
    add_heading(doc, "Usage", level=1)

    add_code_block(doc,
        "uv sync                                          # install dependencies\n"
        "uv run python build_db.py                        # build bmdx.duckdb\n"
        "uv run python build_db.py --output foo.duckdb    # custom output path"
    )

    add_table(doc,
        ["Script", "Purpose"],
        [
            ["citegraph.py", "Citation graph crawler (Semantic Scholar API)"],
            ["extract.py", "LLM-based claim/gene extraction from abstracts"],
            ["go_gene_map.py", "GO term-gene cross-reference with rat/human GAF files"],
            ["genefunc_crawl.py", "Gene-function paper crawler"],
            ["pathway_enrich.py", "KEGG + Reactome pathway enrichment"],
            ["build_db.py", "Build the DuckDB analytical database"],
        ],
        col_widths=[4, 12],
    )

    add_para(doc, "Dependencies: Python \u2265 3.12, duckdb, networkx, requests.")

    # ================================================================
    # LIMITATIONS
    # ================================================================
    add_heading(doc, "Limitations", level=1)

    add_numbered(doc,
        "Gene names were extracted from abstracts, not full text. "
        "This undersamples genes discussed only in results/methods sections.",
        bold_prefix="Abstract-only extraction. "
    )
    add_numbered(doc,
        "The gene-function crawl covered 30 of 69 target genes before "
        "exhausting its API budget. The remaining 39 genes (mostly "
        "moderate-evidence with fewer papers) were not searched for function "
        "papers. Rate limiting by the Semantic Scholar API (no API key) was "
        "the primary bottleneck.",
        bold_prefix="Gene-function crawl coverage. "
    )
    add_numbered(doc,
        "The governor\u2019s relevance filter uses keyword matching, not "
        "semantic understanding. The hybrid scoring (Phase 9) partially "
        "addresses this for known genes but does not help with novel gene "
        "discovery.",
        bold_prefix="Keyword-based relevance scoring. "
    )
    add_numbered(doc,
        "The alias table covers ~100 common variants but is not exhaustive. "
        "Uncommon aliases or very recent gene name changes may be missed.",
        bold_prefix="Gene name normalization coverage. "
    )
    add_numbered(doc,
        "The KEGG/Reactome annotations reflect curated database knowledge, "
        "not our literature evidence. Combining pathway membership with "
        "paper-derived evidence would yield stronger functional groupings.",
        bold_prefix="Pathway enrichment is database-only. "
    )
    add_numbered(doc,
        "The gene lists have not been cross-validated against curated "
        "databases (CTD, TXG-MAPr modules) or full-text extraction. This "
        "would strengthen the consensus classification significantly.",
        bold_prefix="No full-text or database validation. "
    )

    # ================================================================
    # REFERENCES
    # ================================================================
    add_heading(doc, "References", level=1)

    p = doc.add_paragraph()
    r = p.add_run(
        "Zhang, A. L., Kraska, T., & Khattab, O. (2026). "
        "Recursive Language Models. "
    )
    r.font.size = Pt(11)
    r.font.name = "Calibri"
    r = p.add_run("arXiv:2512.24601")
    r.font.size = Pt(11)
    r.font.name = "Calibri"
    r.italic = True
    r = p.add_run(". https://arxiv.org/abs/2512.24601")
    r.font.size = Pt(11)
    r.font.name = "Calibri"
    p.paragraph_format.space_after = Pt(6)

    # -- Save --
    out = "bmdx.docx"
    doc.save(out)
    print(f"Saved {out}")


if __name__ == "__main__":
    build()
