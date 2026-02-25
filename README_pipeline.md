# BMDX Pipeline — Step by Step

## Step 1 — Crawl papers (citegraph.py)

The citation graph crawler queries the Semantic Scholar API starting from seed search terms (e.g. "benzo[a]pyrene toxicogenomics NRF2"). It expands outward by following citations and references, governed by a relevance-scoring system that prevents drift. The governor tracks saturation (diminishing new-paper rate) and stops expansion when the topic is sufficiently covered.

**Output**: `citegraph_output_<topic>/papers.json` + `edges.json` per crawl directory.

```
uv run python citegraph.py --query "your search terms" --output citegraph_output_topic
```

## Step 2 — Phase 2 crawls (crawl_phase2.py, genefunc_crawl.py)

After the initial broad crawl, Phase 2 runs targeted gap-filling crawls in three tiers:

- **Tier 1** — Mechanism-specific crawls (nrf2dose, inflammasome, celldeath, circadian, senescence) with narrow search terms
- **Tier 2** — Organ gap crawls (intestine, testis, vascular) for under-represented tissues
- **Tier 3** — Gene-tox deep dives (genefunc_crawl.py) targeting specific genes flagged during interpretation (GDF15, NLRP3, SQSTM1, STAT3, SIRT1, HIF1A, HAVCR1, PPARA)

These crawls use gene-aware hybrid scoring — they load `gene_consensus.json` from the Phase 1 extraction to boost papers mentioning consensus genes.

```
uv run python crawl_phase2.py
```

## Step 3 — Extract (extract.py)

The LLM extraction engine sends each paper's abstract (or full text, with the `--fulltext` flag) to a local Ollama model (qwen2.5:14b). It extracts structured JSON: genes, organs, claims, methods, species, stance, confidence, and summary.

The engine runs in parallel across multiple Ollama endpoints (multiple GPUs), with automatic retry and load balancing.

**Output**: `citegraph_output_<topic>/extractions.json` per crawl directory.

```
uv run python extract.py citegraph_output_topic/papers.json
```

For batch extraction across all Phase 2 directories, there's `extract_phase2_runner.py`.

### Full text extraction (optional, feat/fulltext-extraction branch)

With `--fulltext`, the pipeline fetches full paper text before extraction, trying sources in priority order: PMC (Europe PMC XML API), arXiv (ar5iv HTML mirror), S2 openAccessPdf, Unpaywall, and DOI proxy (institutional access). Full texts are cached in `.fulltext_cache/`. Papers without full text fall back to abstract extraction.

```
uv run python extract.py citegraph_output_topic/papers.json --fulltext --email your@email.com
```

Before using `--fulltext` on old crawl data, backfill S2 metadata to populate pmid/pmcid/open_access_pdf fields:

```
uv run python fulltext.py backfill citegraph_output_topic/papers.json
```

## Step 4 — Merge consensus (extract.py merge)

The `merge` subcommand scans all `citegraph_output*/extractions.json` files, deduplicates papers by S2 paper ID, and builds a gene consensus: for each gene, it counts how many papers mention it, aggregates the claims and organs, and classifies consensus level (strong / moderate / weak).

**Output**: `gene_consensus_merged.json` + `gene_consensus_merged_extractions.json` in the working directory.

```
uv run python extract.py merge
```

## Step 5 — Build the knowledge base (build_db.py)

This assembles everything into a DuckDB database (`bmdx.duckdb`). It loads:

- **Papers + citation edges** from all `citegraph_output*/papers.json` and `edges.json`
- **Gene consensus + extractions** from the merged JSON files
- **GO terms** from `referenceUmapData.ts` (parsed from the TypeScript source)
- **Gene-GO associations** from `go_term_genes.tsv`
- **Pathway enrichment** from `pathway_enrichment.tsv`

Schema includes tables: `go_terms`, `genes`, `papers`, `gene_go_terms`, `paper_genes`, `paper_organs`, `paper_claims`, `citation_edges`, `pathways`.

```
uv run python build_db.py
```

## Step 6 — Run interpretation (interpret.py)

This is the main analytical step. You provide a **dose-response CSV** (BMDExpress output with gene symbols and BMD values) and it:

1. **Loads the CSV** — parses gene names and BMD (benchmark dose) values
2. **Queries the KB** — for each gene, retrieves pathways, GO terms, paper claims, and organ associations from bmdx.duckdb
3. **Runs enrichment analysis** — Fisher's exact test for pathway and GO term over-representation among the dose-response genes vs. the full KB background, with Benjamini-Hochberg FDR correction
4. **Computes BMD ordering** — calculates median/min BMD per enriched pathway to show which pathways activate at which doses (adaptive-to-adverse transition)
5. **Computes organ signatures** — enrichment of target organs relative to KB background
6. **Formats context** — assembles all structured analysis into a text block
7. **Generates narratives** — sends the context to multiple LLM models (e.g. qwen2.5:14b, gemma2:9b, claude-sonnet-4-6) with multiple runs each, requesting a toxicological interpretation narrative
8. **Runs concordance analysis** — compares narratives across models to identify consistent findings vs. model-specific hallucinations
9. **Exports results** — Markdown report + Word document (.docx)

```
uv run python interpret.py dose_response_data.csv \
  --models qwen2.5:14b gemma2:9b claude-sonnet-4-6 \
  --runs 3 \
  --output interpretation_report
```
