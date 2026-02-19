"""
LLM-based extraction from paper abstracts using local Ollama instances.

Extracts:
- Key claims / findings
- Gene names mentioned
- Organ relevance
- Whether the paper supports/challenges consensus

Uses local Ollama instances in parallel across multiple GPUs.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from pathlib import Path
from threading import Lock
from typing import Optional

import requests


# ---------------------------------------------------------------------------
# Ollama client
# ---------------------------------------------------------------------------

@dataclass
class OllamaEndpoint:
    name: str
    url: str            # e.g. "http://localhost:11434"
    model: str          # e.g. "qwen2.5:14b"
    timeout: int = 120  # seconds
    weight: int = 1     # relative speed weight for work distribution

    def generate(self, prompt: str, system: str = "",
                 temperature: float = 0.1) -> str:
        """Send a prompt to Ollama and return the response text."""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": 2048,
            },
        }
        if system:
            payload["system"] = system

        try:
            r = requests.post(
                f"{self.url}/api/generate",
                json=payload,
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json().get("response", "")
        except requests.RequestException as e:
            print(f"  [{self.name} error: {e}]")
            return ""

    def is_available(self) -> bool:
        """Check if this endpoint is reachable."""
        try:
            r = requests.get(f"{self.url}/api/tags", timeout=5)
            return r.status_code == 200
        except requests.RequestException:
            return False


# ---------------------------------------------------------------------------
# Default endpoints
# ---------------------------------------------------------------------------

LOCAL_OLLAMA = OllamaEndpoint(
    name="local-3080ti",
    url="http://localhost:11434",
    model="qwen2.5:14b",
    weight=2,  # ~2x faster than the AMD
)

REMOTE_OLLAMA = OllamaEndpoint(
    name="remote-6900xt",
    url="http://localhost:11435",  # via SSH tunnel
    model="qwen2.5:14b",
    weight=1,
)


# ---------------------------------------------------------------------------
# Extraction data structures
# ---------------------------------------------------------------------------

@dataclass
class PaperExtraction:
    paper_id: str
    title: str
    year: Optional[int] = None
    claims: list[str] = field(default_factory=list)
    genes: list[str] = field(default_factory=list)
    organs: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    species: list[str] = field(default_factory=list)
    stance: str = ""          # "supports_consensus", "challenges", "neutral", "novel"
    confidence: float = 0.0   # how confident the LLM is in its extraction
    summary: str = ""
    raw_response: str = ""
    endpoint_used: str = ""


# ---------------------------------------------------------------------------
# Extraction prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a scientific literature analyst specializing in toxicogenomics.
You extract structured information from paper abstracts with precision.
Always respond in valid JSON. Never add commentary outside the JSON."""

EXTRACTION_PROMPT = """Analyze this scientific paper abstract and extract structured information.

Title: {title}
Year: {year}
Abstract: {abstract}

Respond with ONLY a JSON object (no markdown, no explanation) with these fields:
{{
  "claims": ["list of key scientific findings or conclusions, each as a concise statement"],
  "genes": ["list of gene names/symbols mentioned (e.g. CYP1A1, NRF2, TP53)"],
  "organs": ["list of organs/tissues studied (e.g. liver, kidney, heart)"],
  "methods": ["list of methods used (e.g. microarray, RNA-seq, qPCR, WGCNA)"],
  "species": ["list of species (e.g. rat, human, mouse)"],
  "stance": "one of: supports_consensus, challenges_consensus, neutral, novel_finding",
  "confidence": 0.0 to 1.0,
  "summary": "one-sentence summary of the paper's main contribution to toxicogenomics"
}}"""


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------

def parse_json_response(text: str) -> dict | None:
    """Try to extract JSON from LLM response, handling common issues."""
    text = text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
    return None


# ---------------------------------------------------------------------------
# Single-paper extraction (stateless, used by workers)
# ---------------------------------------------------------------------------

def extract_one(paper: dict, endpoint: OllamaEndpoint) -> PaperExtraction:
    """Extract structured info from one paper using a given endpoint."""
    pid = paper["paper_id"]
    title = paper.get("title", "")
    abstract = paper.get("abstract")
    year = paper.get("year")

    extraction = PaperExtraction(
        paper_id=pid,
        title=title,
        year=year,
    )

    if not abstract or len(abstract.strip()) < 50:
        return extraction

    prompt = EXTRACTION_PROMPT.format(
        title=title,
        year=year or "unknown",
        abstract=abstract,
    )

    response = endpoint.generate(prompt, system=SYSTEM_PROMPT)
    if not response:
        return extraction

    extraction.raw_response = response
    extraction.endpoint_used = endpoint.name

    data = parse_json_response(response)
    if data:
        extraction.claims = data.get("claims", [])
        extraction.genes = [g.upper() for g in data.get("genes", [])]
        extraction.organs = data.get("organs", [])
        extraction.methods = data.get("methods", [])
        extraction.species = data.get("species", [])
        extraction.stance = data.get("stance", "neutral")
        extraction.confidence = float(data.get("confidence", 0.0))
        extraction.summary = data.get("summary", "")

    return extraction


# ---------------------------------------------------------------------------
# Parallel extraction engine
# ---------------------------------------------------------------------------

class ParallelExtractionEngine:
    """
    Distributes paper extraction across multiple Ollama endpoints.
    Each endpoint gets its own thread; papers are assigned round-robin.
    """

    def __init__(self, endpoints: list[OllamaEndpoint] | None = None):
        if endpoints is None:
            endpoints = [LOCAL_OLLAMA, REMOTE_OLLAMA]

        # Only keep endpoints that are reachable
        self.endpoints = []
        for ep in endpoints:
            if ep.is_available():
                print(f"  [OK] {ep.name} ({ep.model} @ {ep.url})")
                self.endpoints.append(ep)
            else:
                print(f"  [DOWN] {ep.name} ({ep.url}) — skipping")

        if not self.endpoints:
            raise RuntimeError("No Ollama endpoints available")

        self.print_lock = Lock()
        self.stats = {
            "processed": 0,
            "failed": 0,
            "skipped_no_abstract": 0,
        }
        self.stats_lock = Lock()
        # Per-endpoint counters
        for ep in self.endpoints:
            self.stats[f"ep_{ep.name}"] = 0

    def _worker(self, paper: dict, endpoint: OllamaEndpoint,
                index: int, total: int) -> PaperExtraction:
        """Process one paper on one endpoint."""
        title = paper.get("title", "")
        relevance = paper.get("relevance_score", 0)

        extraction = extract_one(paper, endpoint)

        with self.print_lock:
            status = ""
            if extraction.genes:
                status += f" Genes: {', '.join(extraction.genes[:8])}"
            if extraction.organs:
                status += f" Organs: {', '.join(extraction.organs[:5])}"
            if not extraction.raw_response and (paper.get("abstract") or "").strip():
                status = " [FAILED]"
            elif not paper.get("abstract") or len((paper.get("abstract") or "").strip()) < 50:
                status = " [no abstract]"

            print(f"[{index}/{total}] [{endpoint.name}] [{relevance:.2f}] "
                  f"{title[:60]}...{status}")

        with self.stats_lock:
            if extraction.raw_response:
                self.stats["processed"] += 1
                self.stats[f"ep_{endpoint.name}"] += 1
            elif paper.get("abstract") and len((paper.get("abstract") or "").strip()) >= 50:
                self.stats["failed"] += 1
            else:
                self.stats["skipped_no_abstract"] += 1

        return extraction

    def process_papers(self, papers_file: str,
                       max_papers: int | None = None) -> list[PaperExtraction]:
        """Process papers in parallel across all available endpoints."""
        with open(papers_file) as f:
            papers = json.load(f)

        if max_papers:
            papers = papers[:max_papers]

        total = len(papers)
        n_endpoints = len(self.endpoints)

        # Weighted distribution: assign papers proportional to endpoint weight
        total_weight = sum(ep.weight for ep in self.endpoints)

        print(f"\nProcessing {total} papers across {n_endpoints} GPU(s)...")
        for ep in self.endpoints:
            share = round(total * ep.weight / total_weight)
            print(f"  {ep.name}: {ep.model} (weight={ep.weight}, ~{share} papers)")
        print()

        # Build weighted round-robin sequence: e.g. weight=2,1 -> [A,A,B,A,A,B,...]
        weighted_seq: list[OllamaEndpoint] = []
        for ep in self.endpoints:
            weighted_seq.extend([ep] * ep.weight)

        assignments: list[tuple[dict, OllamaEndpoint, int]] = []
        for i, paper in enumerate(papers):
            ep = weighted_seq[i % len(weighted_seq)]
            assignments.append((paper, ep, i + 1))

        # Process with one thread per endpoint
        # Each endpoint handles its papers sequentially (GPU can only do one at a time)
        # But endpoints run in parallel with each other
        endpoint_queues: dict[str, list[tuple[dict, int]]] = {
            ep.name: [] for ep in self.endpoints
        }
        for paper, ep, idx in assignments:
            endpoint_queues[ep.name].append((paper, idx))

        results: dict[str, PaperExtraction] = {}  # paper_id -> extraction

        def run_endpoint_queue(endpoint: OllamaEndpoint,
                               queue: list[tuple[dict, int]]):
            for paper, idx in queue:
                ext = self._worker(paper, endpoint, idx, total)
                results[paper["paper_id"]] = ext

        start_time = time.time()

        with ThreadPoolExecutor(max_workers=n_endpoints) as pool:
            futures = []
            for ep in self.endpoints:
                queue = endpoint_queues[ep.name]
                futures.append(pool.submit(run_endpoint_queue, ep, queue))

            # Wait for all to complete
            for f in futures:
                f.result()

        elapsed = time.time() - start_time

        # Rebuild list in original order
        extractions = []
        for paper in papers:
            pid = paper["paper_id"]
            if pid in results:
                extractions.append(results[pid])

        self._print_summary(extractions, elapsed)
        return extractions

    def _print_summary(self, extractions: list[PaperExtraction],
                       elapsed: float):
        """Print extraction summary."""
        all_genes: dict[str, int] = {}
        all_organs: dict[str, int] = {}
        all_methods: dict[str, int] = {}

        for ext in extractions:
            for g in ext.genes:
                all_genes[g] = all_genes.get(g, 0) + 1
            for o in ext.organs:
                o_lower = o.lower()
                all_organs[o_lower] = all_organs.get(o_lower, 0) + 1
            for m in ext.methods:
                m_lower = m.lower()
                all_methods[m_lower] = all_methods.get(m_lower, 0) + 1

        print(f"\n{'='*60}")
        print(f"EXTRACTION SUMMARY")
        print(f"{'='*60}")
        print(f"Time: {elapsed:.1f}s ({elapsed/60:.1f} min)")
        print(f"Papers/sec: {len(extractions)/elapsed:.2f}")
        print(f"Stats: {self.stats}")
        print(f"\nTop 30 genes (by frequency across papers):")
        for gene, count in sorted(all_genes.items(),
                                   key=lambda x: x[1], reverse=True)[:30]:
            print(f"  {gene}: {count} papers")
        print(f"\nOrgan coverage:")
        for organ, count in sorted(all_organs.items(),
                                    key=lambda x: x[1], reverse=True)[:20]:
            print(f"  {organ}: {count} papers")
        print(f"\nMethods used:")
        for method, count in sorted(all_methods.items(),
                                     key=lambda x: x[1], reverse=True)[:15]:
            print(f"  {method}: {count} papers")

    def save(self, extractions: list[PaperExtraction],
             path: str = "citegraph_output/extractions.json"):
        """Save all extractions to JSON."""
        out = [asdict(ext) for ext in extractions]
        with open(path, "w") as f:
            json.dump(out, f, indent=2, default=str)
        print(f"\nSaved {len(out)} extractions to {path}")


# ---------------------------------------------------------------------------
# Gene name normalization
# ---------------------------------------------------------------------------

# Canonical HGNC symbols for common aliases/variants found in literature.
# Maps variant -> canonical symbol.
GENE_ALIASES: dict[str, str] = {
    # p53 family
    "P53": "TP53",
    "TRP53": "TP53",
    "P53/TP53": "TP53",

    # BCL2 family
    "BCL-2": "BCL2",
    "BCL-XL": "BCL2L1",
    "BAK1": "BAK1",
    "BAK": "BAK1",

    # Caspases
    "CASPASE-3": "CASP3",
    "CASPASE3": "CASP3",
    "CASPASE-9": "CASP9",
    "CASPASE-8": "CASP8",
    "CASPASE-1": "CASP1",

    # TNF/NF-kB signaling
    "TNF-Α": "TNF",
    "TNFΑ": "TNF",
    "TNF-ALPHA": "TNF",
    "TNFA": "TNF",
    "NF-ΚB": "NFKB1",
    "NF-KB": "NFKB1",
    "NF-KAPPAB": "NFKB1",
    "NFKB": "NFKB1",
    "NF-ΚB P65": "RELA",
    "IL-6": "IL6",
    "IL-1Β": "IL1B",
    "IL-1B": "IL1B",
    "IL-10": "IL10",
    "IL-33": "IL33",
    "IL-1": "IL1B",

    # NRF2/KEAP1 pathway
    "NRF2": "NFE2L2",
    "NRF1": "NFE2L1",
    "KEAP-1": "KEAP1",

    # Nuclear receptors
    "PPARΑ": "PPARA",
    "PPAR-ALPHA": "PPARA",
    "PPAR-Α": "PPARA",
    "PPARα": "PPARA",
    "RXRΑ": "RXRA",
    "HIF-1Α": "HIF1A",
    "HIF-1A": "HIF1A",
    "PGC1Α": "PPARGC1A",
    "PGC-1Α": "PPARGC1A",
    "PGC1A": "PPARGC1A",
    "FOXO3A": "FOXO3",
    "ERΑ": "ESR1",

    # Xenobiotic metabolism
    "CYTOCHROME P450": "CYP",  # too generic, but normalize
    "CYP 1A1": "CYP1A1",
    "CYP 2E1": "CYP2E1",

    # Growth factors / signaling
    "TGF-Β": "TGFB1",
    "TGF-B": "TGFB1",
    "TGF-BETA": "TGFB1",
    "TGFB": "TGFB1",
    "TNF-Β": "LTA",
    "VEGF": "VEGFA",
    "VEGF-A": "VEGFA",
    "HGF": "HGF",
    "FGF-21": "FGF21",
    "GDF-15": "GDF15",

    # Apoptosis / cell cycle
    "P21": "CDKN1A",
    "P27": "CDKN1B",
    "P62": "SQSTM1",
    "BECLIN-1": "BECN1",

    # Kinases / signaling
    "ERK": "MAPK1",
    "ERK1/2": "MAPK1",
    "JNK": "MAPK8",
    "P-AKT": "AKT1",
    "AKT": "AKT1",
    "P-AMPK": "PRKAA1",
    "AMPK": "PRKAA1",
    "MTOR": "MTOR",
    "PI3K": "PIK3CA",

    # Oxidative stress
    "HMOX1": "HMOX1",
    "HMOX-1": "HMOX1",
    "HO-1": "HMOX1",
    "SOD": "SOD1",
    "SOD1": "SOD1",
    "SOD2": "SOD2",
    "GPX": "GPX1",
    "COX-2": "PTGS2",
    "COX2": "PTGS2",

    # Mitochondrial
    "DRP-1": "DNM1L",
    "DRP1": "DNM1L",
    "MFN-2": "MFN2",

    # Kidney biomarkers
    "KIM-1": "HAVCR1",
    "KIM1": "HAVCR1",
    "NGAL": "LCN2",

    # Misc
    "HSP90": "HSP90AA1",
    "HSP70": "HSPA1A",
    "SIRT-1": "SIRT1",
    "DJ-1/PARK7": "PARK7",
    "DJ-1": "PARK7",
}


def normalize_gene(name: str) -> str:
    """
    Normalize a gene name to its canonical HGNC symbol.

    Steps:
    1. Uppercase and strip whitespace
    2. Remove common prefixes (p-, h-, r- for protein/human/rat)
    3. Look up in alias table
    4. Strip trailing hyphens and normalize punctuation
    """
    name = name.strip().upper()

    # Skip obviously non-gene entries
    skip_patterns = [
        "NOT EXPLICITLY", "KEY GENES", "CORE GENES",
        "GENE EXPRESSION", "SIGNATURE", "PATHWAY",
        "TOTAL", "IMPLIED", "LISTED",
    ]
    for pattern in skip_patterns:
        if pattern in name:
            return ""

    # Direct alias lookup
    if name in GENE_ALIASES:
        return GENE_ALIASES[name]

    # Strip trailing punctuation that shouldn't be there
    name = name.rstrip(".,;:")

    # Check alias again after cleanup
    if name in GENE_ALIASES:
        return GENE_ALIASES[name]

    return name


def normalize_organ(name: str) -> str:
    """Normalize organ names to reduce duplicates."""
    name = name.strip().lower()

    organ_map = {
        "hepatocytes": "liver",
        "hepatocyte": "liver",
        "hepatic": "liver",
        "renal": "kidney",
        "kidneys": "kidney",
        "lungs": "lung",
        "hearts": "heart",
        "brains": "brain",
        "cerebellum": "brain",
        "hippocampus": "brain",
        "cortex": "brain",
        "frontal cortex": "brain",
        "striatum": "brain",
        "amygdala": "brain",
        "nervous system": "brain",
        "cardiovascular system": "heart",
        "pulmonary system": "lung",
        "gastrointestinal tract": "intestine",
        "gut": "intestine",
        "colon": "intestine",
        "colorectal tissue": "intestine",
        "rectum": "intestine",
        "esophagus": "stomach",
        "gallbladder": "liver",
        "bile duct": "liver",
        "breast tissue": "breast",
        "skeletal muscle": "muscle",
        "plasma": "blood",
        "peripheral blood mononuclear cells (pbmc)": "blood",
    }

    return organ_map.get(name, name)


# ---------------------------------------------------------------------------
# Gene consensus analysis
# ---------------------------------------------------------------------------

def analyze_gene_consensus(extractions_file: str = "citegraph_output/extractions.json"):
    """
    Analyze extracted genes to find:
    - Consensus hallmark genes (appear in many papers, across methods)
    - Organ-specific gene sets
    - Outlier/novel genes (few mentions but high confidence)
    """
    with open(extractions_file) as f:
        extractions = json.load(f)

    # Build gene-to-papers mapping
    gene_papers: dict[str, list[dict]] = {}
    gene_organs: dict[str, set] = {}

    for ext in extractions:
        genes = ext.get("genes", [])
        organs = ext.get("organs", [])
        normalized_organs = {normalize_organ(o) for o in organs}
        # Remove overly broad/noisy organ tags
        normalized_organs.discard("")

        for raw_gene in genes:
            gene = normalize_gene(raw_gene)
            if not gene:  # skip non-gene entries
                continue
            if gene not in gene_papers:
                gene_papers[gene] = []
                gene_organs[gene] = set()
            gene_papers[gene].append({
                "paper_id": ext["paper_id"],
                "title": ext["title"],
                "year": ext.get("year"),
                "confidence": ext.get("confidence", 0),
            })
            gene_organs[gene].update(normalized_organs)

    # Categorize genes
    consensus = {}      # >= 3 papers
    moderate = {}       # 2 papers
    single_mention = {} # 1 paper

    for gene, papers in gene_papers.items():
        entry = {
            "count": len(papers),
            "organs": sorted(gene_organs.get(gene, set())),
            "years": sorted(set(p["year"] for p in papers if p.get("year"))),
            "papers": papers,
        }
        if len(papers) >= 3:
            consensus[gene] = entry
        elif len(papers) == 2:
            moderate[gene] = entry
        else:
            single_mention[gene] = entry

    # Organ-specific gene sets
    organ_genes: dict[str, dict[str, int]] = {}
    for gene, organs in gene_organs.items():
        for organ in organs:
            if organ not in organ_genes:
                organ_genes[organ] = {}
            organ_genes[organ][gene] = len(gene_papers[gene])

    result = {
        "consensus_genes": dict(sorted(consensus.items(),
                                        key=lambda x: x[1]["count"],
                                        reverse=True)),
        "moderate_evidence": dict(sorted(moderate.items(),
                                          key=lambda x: x[1]["count"],
                                          reverse=True)),
        "single_mentions": len(single_mention),
        "organ_specific_genes": {
            organ: dict(sorted(genes.items(),
                               key=lambda x: x[1], reverse=True)[:20])
            for organ, genes in sorted(organ_genes.items())
        },
        "total_unique_genes": len(gene_papers),
    }

    # Print report
    print(f"\n{'='*60}")
    print(f"GENE CONSENSUS ANALYSIS")
    print(f"{'='*60}")
    print(f"Total unique genes: {result['total_unique_genes']}")
    print(f"Consensus (3+ papers): {len(consensus)}")
    print(f"Moderate (2 papers): {len(moderate)}")
    print(f"Single mention: {len(single_mention)}")

    print(f"\nConsensus hallmark genes:")
    for gene, info in list(result["consensus_genes"].items())[:30]:
        organs_str = ", ".join(info["organs"]) if info["organs"] else "unspecified"
        print(f"  {gene}: {info['count']} papers | organs: {organs_str}")

    print(f"\nOrgan-specific top genes:")
    for organ, genes in result["organ_specific_genes"].items():
        top = list(genes.items())[:10]
        if top:
            genes_str = ", ".join(f"{g}({c})" for g, c in top)
            print(f"  {organ}: {genes_str}")

    # Save
    outpath = "citegraph_output/gene_consensus.json"
    with open(outpath, "w") as f:
        json.dump(result, f, indent=2, default=list)
    print(f"\nSaved to {outpath}")

    return result


# ---------------------------------------------------------------------------
# Merge gene consensus across multiple extraction files
# ---------------------------------------------------------------------------

def merge_gene_consensus(
    extraction_files: list[str],
    output_path: str = "citegraph_output/gene_consensus_merged.json",
) -> dict:
    """
    Merge extractions from multiple crawl directories, deduplicate papers
    by paper_id, and re-run consensus analysis on the combined set.

    This is used after all crawls (main, organ-specific, gene-function) have
    been extracted, to produce a unified gene consensus.
    """
    # Collect all extractions, deduplicating by paper_id
    seen_ids: set[str] = set()
    merged: list[dict] = []

    for filepath in extraction_files:
        try:
            with open(filepath) as f:
                extractions = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"  [skip] {filepath}: {e}")
            continue

        added = 0
        for ext in extractions:
            pid = ext.get("paper_id", "")
            if pid and pid not in seen_ids:
                seen_ids.add(pid)
                merged.append(ext)
                added += 1
        print(f"  {filepath}: {len(extractions)} total, {added} new (deduped)")

    print(f"\nMerged: {len(merged)} unique papers from {len(extraction_files)} files")

    # Write merged extractions to a temp file for analyze_gene_consensus()
    merged_extractions_path = output_path.replace(".json", "_extractions.json")
    with open(merged_extractions_path, "w") as f:
        json.dump(merged, f, indent=2, default=str)

    # Re-run consensus analysis on the merged set
    # We call the same logic but with a custom output path
    # Build gene-to-papers mapping (same as analyze_gene_consensus)
    gene_papers: dict[str, list[dict]] = {}
    gene_organs: dict[str, set] = {}

    for ext in merged:
        genes = ext.get("genes", [])
        organs = ext.get("organs", [])
        normalized_organs = {normalize_organ(o) for o in organs}
        normalized_organs.discard("")

        for raw_gene in genes:
            gene = normalize_gene(raw_gene)
            if not gene:
                continue
            if gene not in gene_papers:
                gene_papers[gene] = []
                gene_organs[gene] = set()
            gene_papers[gene].append({
                "paper_id": ext["paper_id"],
                "title": ext["title"],
                "year": ext.get("year"),
                "confidence": ext.get("confidence", 0),
            })
            gene_organs[gene].update(normalized_organs)

    consensus = {}
    moderate = {}
    single_mention = {}

    for gene, papers in gene_papers.items():
        entry = {
            "count": len(papers),
            "organs": sorted(gene_organs.get(gene, set())),
            "years": sorted(set(p["year"] for p in papers if p.get("year"))),
            "papers": papers,
        }
        if len(papers) >= 3:
            consensus[gene] = entry
        elif len(papers) == 2:
            moderate[gene] = entry
        else:
            single_mention[gene] = entry

    organ_genes: dict[str, dict[str, int]] = {}
    for gene, organs in gene_organs.items():
        for organ in organs:
            if organ not in organ_genes:
                organ_genes[organ] = {}
            organ_genes[organ][gene] = len(gene_papers[gene])

    result = {
        "consensus_genes": dict(sorted(consensus.items(),
                                        key=lambda x: x[1]["count"],
                                        reverse=True)),
        "moderate_evidence": dict(sorted(moderate.items(),
                                          key=lambda x: x[1]["count"],
                                          reverse=True)),
        "single_mentions": len(single_mention),
        "organ_specific_genes": {
            organ: dict(sorted(genes.items(),
                               key=lambda x: x[1], reverse=True)[:20])
            for organ, genes in sorted(organ_genes.items())
        },
        "total_unique_genes": len(gene_papers),
        "source_files": extraction_files,
        "total_papers_merged": len(merged),
    }

    # Print report
    print(f"\n{'='*60}")
    print(f"MERGED GENE CONSENSUS")
    print(f"{'='*60}")
    print(f"Total unique genes: {result['total_unique_genes']}")
    print(f"Consensus (3+ papers): {len(consensus)}")
    print(f"Moderate (2 papers): {len(moderate)}")
    print(f"Single mention: {len(single_mention)}")

    print(f"\nConsensus hallmark genes:")
    for gene, info in list(result["consensus_genes"].items())[:30]:
        organs_str = ", ".join(info["organs"]) if info["organs"] else "unspecified"
        print(f"  {gene}: {info['count']} papers | organs: {organs_str}")

    # Save
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, default=list)
    print(f"\nSaved to {output_path}")

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "analyze":
        extractions_file = sys.argv[2] if len(sys.argv) > 2 else "citegraph_output/extractions.json"
        analyze_gene_consensus(extractions_file)
    elif len(sys.argv) > 1 and sys.argv[1] == "merge":
        # Usage: python extract.py merge [extraction_file1] [extraction_file2] ...
        # If no files specified, auto-discover all extractions.json in citegraph_output_* dirs
        if len(sys.argv) > 2:
            files = sys.argv[2:]
        else:
            from pathlib import Path
            files = sorted(str(p) for p in Path(".").glob("citegraph_output*/extractions.json"))
            print(f"Auto-discovered {len(files)} extraction files:")
            for f in files:
                print(f"  {f}")
        if not files:
            print("No extraction files found. Run extract.py on crawl outputs first.")
            sys.exit(1)
        merge_gene_consensus(files)
    else:
        # Usage: python extract.py [papers_dir] [max_papers]
        # papers_dir should contain papers.json; extractions.json will be saved there
        papers_dir = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].isdigit() else "citegraph_output_800"
        max_papers = None
        for arg in sys.argv[1:]:
            if arg.isdigit():
                max_papers = int(arg)
                break

        papers_file = f"{papers_dir}/papers.json"
        output_file = f"{papers_dir}/extractions.json"

        engine = ParallelExtractionEngine()
        extractions = engine.process_papers(papers_file, max_papers=max_papers)
        engine.save(extractions, output_file)
        print(f"\nRun 'python extract.py analyze {output_file}' for consensus analysis.")
