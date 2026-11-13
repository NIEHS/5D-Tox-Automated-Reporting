# Retired: the crawl as code (before named crawl queries)

These modules ran the May 2026 crawl with the query written into the code
(organ keyword lists, gene maps, seed DOIs, the gene-function and gene-tox
searches, the GO and pathway tables).  That crawl is now stated in full as
`crawl_queries/baseline.yaml` and runs through `knowledge_base.run_crawl`
(ADR-0034); its knowledge base is `knowledge_bases/baseline-2026-05/`.

They are kept for the record, not run: they import modules that no longer have
the functions they used (`citegraph.ORGAN_CRAWL_CONFIGS`, `extract.normalize_gene`).

| retired | now |
|---------|-----|
| `crawl_phase2.py` (the mechanism and organ-gap crawls) | the `crawls` of `baseline.yaml` |
| `extract_phase2_runner.py` | the `extract` stage of `run_crawl` |
| `genefunc_crawl.py` (gene-function and gene-tox crawls) | `follow_on` in the query; `knowledge_base.entity_crawl` |
| `go_gene_map.py` | the `annotate.go` section; `knowledge_base.annotate.go_table` |
| `pathway_enrich.py` | the `annotate.pathways` section; `knowledge_base.annotate.pathway_table` |
| `crawl_config.py`, `crawl_config_original.json` (per-session config editor) | named queries edited as text, directly or with `knowledge_base.query_agent` |
