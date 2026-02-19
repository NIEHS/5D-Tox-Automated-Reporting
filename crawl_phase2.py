"""
Phase 2 crawl: interpretation-driven literature expansion.

Uses gap analysis from the 5-model × 3-run interpretation pipeline to
design targeted crawls filling mechanism, organ, and gene-specific holes
in the knowledge base.

Tier 1 — Mechanism-specific crawls (NRF2 dose-response, inflammasome,
         cell death pathways, circadian-tox, senescence)
Tier 2 — Organ gap crawls (intestine, testis, vascular)
Tier 3 — Gene-tox deep dives (delegates to genefunc_crawl.run_genetox_crawl)

Usage:
    python crawl_phase2.py all              # all tiers (16 crawls)
    python crawl_phase2.py tier1            # 5 mechanism crawls
    python crawl_phase2.py tier2            # 3 organ gap crawls
    python crawl_phase2.py tier3            # 8 gene-tox crawls
    python crawl_phase2.py nrf2dose         # single crawl by name
    python crawl_phase2.py inflammasome
    python crawl_phase2.py celldeath
    python crawl_phase2.py circadian
    python crawl_phase2.py senescence
    python crawl_phase2.py intestine
    python crawl_phase2.py testis
    python crawl_phase2.py vascular
    python crawl_phase2.py genetox          # just Tier 3
"""

import sys
import time

from citegraph import CitationGraphCrawler, GovernorConfig, load_known_genes
from genefunc_crawl import run_genetox_crawl


# ---------------------------------------------------------------------------
# Tier 1 — Mechanism-specific crawl configs
# ---------------------------------------------------------------------------

MECHANISM_CRAWL_CONFIGS = {
    "nrf2dose": {
        "max_papers": 400,
        "max_api_calls": 800,
        "searches": [
            ("NRF2 dose response oxidative stress threshold", 10),
            ("KEAP1 NRF2 activation dose dependent", 10),
            ("NRF2 antioxidant response saturation toxicity", 10),
            ("oxidative stress adaptive adverse dose transition", 10),
            ("NRF2 biphasic hormesis oxidative stress", 10),
        ],
        "topic_keywords": [
            "nrf2", "nfe2l2", "keap1",
            "oxidative stress", "antioxidant",
            "dose-response", "dose-dependent", "dose response",
            "threshold", "biphasic", "hormesis",
            "adaptive", "adverse", "transition",
            "saturation", "antioxidant response element", "are",
            "electrophile", "sulforaphane",
            "cytoprotective", "maladaptive",
            "reactive oxygen species", "ros",
            "gene expression", "transcriptomics",
            "toxicity", "toxic",
        ],
        "boost_keywords": [
            "nrf2", "keap1", "nfe2l2",
            "hormesis", "biphasic", "threshold",
            "adaptive-to-adverse", "transition dose",
        ],
    },
    "inflammasome": {
        "max_papers": 300,
        "max_api_calls": 600,
        "searches": [
            ("NLRP3 inflammasome activation dose response", 10),
            ("NF-kB activation threshold toxicology dose", 10),
            ("inflammation onset dose chemical toxicity", 10),
            ("TNF IL6 dose dependent toxicogenomics", 10),
        ],
        "topic_keywords": [
            "nlrp3", "inflammasome",
            "nfkb", "nf-kb", "nf-kappa",
            "il-1beta", "il1b", "interleukin",
            "caspase-1", "casp1",
            "pyroptosis", "gasdermin",
            "dose-response", "dose-dependent", "dose response",
            "threshold", "activation",
            "inflammation", "inflammatory", "proinflammatory",
            "innate immune", "innate immunity",
            "damage-associated", "damp",
            "sterile inflammation",
            "toxicity", "toxic", "toxicology",
            "gene expression", "transcriptomics",
        ],
        "boost_keywords": [
            "nlrp3", "inflammasome",
            "pyroptosis", "gasdermin",
            "nfkb", "nf-kb",
            "dose-response", "threshold",
        ],
    },
    "celldeath": {
        "max_papers": 400,
        "max_api_calls": 800,
        "searches": [
            ("ferroptosis dose response oxidative stress", 10),
            ("ferroptosis apoptosis necroptosis decision", 10),
            ("autophagy apoptosis switch dose dependent", 10),
            ("necroptosis toxicology dose response", 10),
            ("cell death mode determination dose", 10),
            ("GPX4 ferroptosis threshold", 10),
        ],
        "topic_keywords": [
            "ferroptosis", "necroptosis",
            "autophagy", "mitophagy",
            "pyroptosis",
            "gpx4", "glutathione peroxidase",
            "ripk1", "ripk3", "mlkl",
            "beclin", "sqstm1", "p62",
            "cell death", "programmed cell death",
            "regulated cell death",
            "dose-dependent", "dose-response", "dose response",
            "threshold", "decision",
            "lipid peroxidation", "iron",
            "erastin", "rsl3",
            "toxicity", "toxic", "toxicology",
            "gene expression", "transcriptomics",
        ],
        "boost_keywords": [
            "ferroptosis", "necroptosis",
            "gpx4", "ripk3", "mlkl",
            "cell death mode", "regulated cell death",
            "lipid peroxidation",
        ],
    },
    "circadian": {
        "max_papers": 200,
        "max_api_calls": 400,
        "searches": [
            ("AHR circadian clock ARNT BMAL1", 10),
            ("circadian rhythm disruption toxicity xenobiotic", 10),
            ("chronotoxicology circadian gene expression", 10),
            ("circadian clock oxidative stress DNA repair", 10),
        ],
        "topic_keywords": [
            "circadian", "circadian rhythm", "circadian clock",
            "bmal1", "arntl", "clock",
            "per1", "per2", "cry1", "cry2",
            "chronotoxicology", "chronopharmacology",
            "diurnal", "zeitgeber",
            "ahr", "arnt", "aryl hydrocarbon",
            "xenobiotic", "dioxin",
            "circadian disruption",
            "gene expression", "transcriptomics",
            "toxicity", "toxic", "toxicology",
        ],
        "boost_keywords": [
            "circadian", "bmal1", "chronotoxicology",
            "ahr", "arnt", "clock gene",
            "diurnal", "chronopharmacology",
        ],
    },
    "senescence": {
        "max_papers": 200,
        "max_api_calls": 400,
        "searches": [
            ("cellular senescence toxicology SASP", 10),
            ("senescence associated secretory phenotype toxicant", 10),
            ("p21 senescence dose response toxicity", 10),
            ("senescence oxidative stress chemical exposure", 10),
        ],
        "topic_keywords": [
            "senescence", "cellular senescence",
            "sasp", "secretory phenotype",
            "cdkn1a", "p21", "cdkn2a", "p16",
            "senolytic", "senostatic",
            "growth arrest", "irreversible",
            "oxidative stress",
            "dose-response", "dose-dependent", "dose response",
            "gene expression", "transcriptomics",
            "toxicity", "toxic", "toxicology",
            "chemical exposure",
        ],
        "boost_keywords": [
            "senescence", "sasp",
            "cdkn1a", "p21", "p16",
            "secretory phenotype",
            "senolytic", "senostatic",
        ],
    },
}


# ---------------------------------------------------------------------------
# Tier 2 — Organ gap crawl configs
# ---------------------------------------------------------------------------

ORGAN_GAP_CONFIGS = {
    "intestine": {
        "max_papers": 400,
        "max_api_calls": 800,
        "searches": [
            ("intestinal toxicogenomics gene expression barrier", 10),
            ("gut liver axis toxicology chemical exposure", 10),
            ("intestinal epithelial NRF2 oxidative stress", 10),
            ("enterocyte toxicity gene expression dose response", 10),
            ("gut permeability toxicant gene expression", 10),
        ],
        # Uses default topic_keywords (tox vocabulary)
        "topic_keywords": None,
        "boost_keywords": [
            "intestine", "intestinal", "enterocyte",
            "gut", "colon", "colonic",
            "ileum", "jejunum", "duodenum",
            "gut-liver", "gut liver axis",
            "barrier", "permeability",
            "tight junction", "villus", "crypt",
            "microbiome", "dysbiosis",
        ],
    },
    "testis": {
        "max_papers": 300,
        "max_api_calls": 600,
        "searches": [
            ("testicular toxicogenomics gene expression spermatogenesis", 10),
            ("reproductive toxicology transcriptomics rat testis", 10),
            ("male fertility toxicant gene expression", 10),
            ("sertoli cell Leydig cell toxicity transcriptomic", 10),
            ("endocrine disruptor testicular gene expression", 10),
        ],
        "topic_keywords": None,
        "boost_keywords": [
            "testis", "testicular",
            "spermatogenesis", "spermatocyte", "spermatid",
            "sertoli", "leydig",
            "reproductive", "fertility", "infertility",
            "endocrine disruptor", "testosterone",
            "seminiferous",
        ],
    },
    "vascular": {
        "max_papers": 300,
        "max_api_calls": 600,
        "searches": [
            ("endothelial toxicity gene expression vascular", 10),
            ("vascular toxicogenomics transcriptomic", 10),
            ("VEGF oxidative stress endothelial dose response", 10),
            ("atherosclerosis toxicant gene expression", 10),
            ("endothelial dysfunction chemical exposure transcriptomics", 10),
        ],
        "topic_keywords": None,
        "boost_keywords": [
            "endothelial", "endothelium",
            "vascular", "vasculature",
            "atherosclerosis",
            "vegf", "vegfa", "angiogenesis",
            "shear stress",
            "thrombosis", "coagulation",
        ],
    },
}


# ---------------------------------------------------------------------------
# Crawl runner
# ---------------------------------------------------------------------------

def run_mechanism_crawl(
    name: str,
    config_dict: dict,
    max_depth: int = 2,
    api_key: str | None = None,
) -> tuple:
    """
    Run a single mechanism or organ-gap crawl.

    Builds a GovernorConfig with custom topic_keywords (if provided) and
    organ_boost_keywords, loads known_genes for gene-aware scoring floor,
    creates CitationGraphCrawler, seeds via search, expands, and saves.

    Returns (crawler, report).
    """
    max_papers = config_dict["max_papers"]
    max_api_calls = config_dict["max_api_calls"]
    searches = config_dict["searches"]
    topic_keywords = config_dict.get("topic_keywords")
    boost_keywords = config_dict.get("boost_keywords", [])

    # Load known genes for hybrid scoring
    try:
        known_genes = load_known_genes()
    except FileNotFoundError:
        print("  [warning: gene_consensus.json not found, skipping gene-aware scoring]")
        known_genes = set()

    # Build GovernorConfig
    kwargs = dict(
        max_depth=max_depth,
        max_papers=max_papers,
        max_api_calls=max_api_calls,
        rate_limit_delay=1.5,
        organ_boost_keywords=boost_keywords,
        known_genes=known_genes,
    )
    if topic_keywords is not None:
        kwargs["topic_keywords"] = topic_keywords

    config = GovernorConfig(**kwargs)
    crawler = CitationGraphCrawler(config=config, api_key=api_key)

    print(f"\n{'='*60}")
    print(f"PHASE 2 CRAWL: {name.upper()}")
    print(f"Max papers: {max_papers}, Max API calls: {max_api_calls}")
    print(f"Searches: {len(searches)}, Boost keywords: {len(boost_keywords)}")
    if topic_keywords is not None:
        print(f"Custom topic keywords: {len(topic_keywords)}")
    else:
        print(f"Topic keywords: default (tox vocabulary)")
    print(f"{'='*60}\n")

    # Add search-derived seeds
    for query, limit in searches:
        crawler.add_seed_by_search(query, max_results=limit)

    # Expand
    report = crawler.expand()

    # Save to crawl-specific directory
    output_dir = f"citegraph_output_{name}"
    crawler.save(output_dir)

    return crawler, report


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_all_phase2(
    tiers: list[int] | None = None,
    api_key: str | None = None,
):
    """
    Run all Phase 2 crawls (or a subset of tiers).

    tiers: list of tier numbers to run (1, 2, 3). None = all.
    """
    if tiers is None:
        tiers = [1, 2, 3]

    results: dict[str, dict] = {}
    t_start = time.time()

    # Tier 1: mechanism crawls
    if 1 in tiers:
        print(f"\n{'#'*60}")
        print(f"# TIER 1: MECHANISM-SPECIFIC CRAWLS ({len(MECHANISM_CRAWL_CONFIGS)} crawls)")
        print(f"{'#'*60}")
        for name, config_dict in MECHANISM_CRAWL_CONFIGS.items():
            t0 = time.time()
            crawler, report = run_mechanism_crawl(name, config_dict, api_key=api_key)
            elapsed = time.time() - t0
            results[name] = {
                "tier": 1,
                "papers": len(crawler.papers),
                "api_calls": crawler.client.call_count,
                "time_s": elapsed,
            }
            print(f"\n  [{name}] {len(crawler.papers)} papers, "
                  f"{crawler.client.call_count} API calls, {elapsed:.0f}s")

    # Tier 2: organ gap crawls
    if 2 in tiers:
        print(f"\n{'#'*60}")
        print(f"# TIER 2: ORGAN GAP CRAWLS ({len(ORGAN_GAP_CONFIGS)} crawls)")
        print(f"{'#'*60}")
        for name, config_dict in ORGAN_GAP_CONFIGS.items():
            t0 = time.time()
            crawler, report = run_mechanism_crawl(name, config_dict, api_key=api_key)
            elapsed = time.time() - t0
            results[name] = {
                "tier": 2,
                "papers": len(crawler.papers),
                "api_calls": crawler.client.call_count,
                "time_s": elapsed,
            }
            print(f"\n  [{name}] {len(crawler.papers)} papers, "
                  f"{crawler.client.call_count} API calls, {elapsed:.0f}s")

    # Tier 3: gene-tox crawls
    if 3 in tiers:
        print(f"\n{'#'*60}")
        print(f"# TIER 3: GENE-TOX DEEP DIVES (8 genes)")
        print(f"{'#'*60}")
        t0 = time.time()
        crawler = run_genetox_crawl(api_key=api_key)
        elapsed = time.time() - t0
        results["genetox"] = {
            "tier": 3,
            "papers": len(crawler.papers),
            "api_calls": crawler.client.call_count,
            "time_s": elapsed,
        }
        print(f"\n  [genetox] {len(crawler.papers)} papers, "
              f"{crawler.client.call_count} API calls, {elapsed:.0f}s")

    # Summary
    total_elapsed = time.time() - t_start
    total_papers = sum(r["papers"] for r in results.values())
    total_api = sum(r["api_calls"] for r in results.values())

    print(f"\n{'='*60}")
    print(f"PHASE 2 CRAWL COMPLETE")
    print(f"{'='*60}")
    print(f"Total time:    {total_elapsed:.0f}s ({total_elapsed/3600:.1f}h)")
    print(f"Total papers:  {total_papers}")
    print(f"Total API calls: {total_api}")
    print(f"\nPer-crawl summary:")
    for name, r in results.items():
        print(f"  [{r['tier']}] {name:20s}  {r['papers']:4d} papers  "
              f"{r['api_calls']:4d} calls  {r['time_s']:.0f}s")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

ALL_CRAWL_NAMES = set(MECHANISM_CRAWL_CONFIGS) | set(ORGAN_GAP_CONFIGS) | {"genetox"}

def main():
    if len(sys.argv) < 2:
        print("Usage: python crawl_phase2.py <target>")
        print()
        print("Targets:")
        print("  all        — all 16 crawls (Tier 1 + 2 + 3)")
        print("  tier1      — 5 mechanism crawls")
        print("  tier2      — 3 organ gap crawls")
        print("  tier3      — 8 gene-tox crawls")
        print("  genetox    — alias for tier3")
        print()
        print("Single crawls:")
        for name in MECHANISM_CRAWL_CONFIGS:
            print(f"  {name}")
        for name in ORGAN_GAP_CONFIGS:
            print(f"  {name}")
        sys.exit(1)

    target = sys.argv[1].lower()

    if target == "all":
        run_all_phase2()
    elif target == "tier1":
        run_all_phase2(tiers=[1])
    elif target == "tier2":
        run_all_phase2(tiers=[2])
    elif target == "tier3" or target == "genetox":
        run_all_phase2(tiers=[3])
    elif target in MECHANISM_CRAWL_CONFIGS:
        run_mechanism_crawl(target, MECHANISM_CRAWL_CONFIGS[target])
    elif target in ORGAN_GAP_CONFIGS:
        run_mechanism_crawl(target, ORGAN_GAP_CONFIGS[target])
    else:
        print(f"Unknown target: {target}")
        print(f"Available: all, tier1, tier2, tier3, genetox, "
              f"{', '.join(sorted(ALL_CRAWL_NAMES - {'genetox'}))}")
        sys.exit(1)


if __name__ == "__main__":
    main()
