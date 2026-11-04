# 0034: Named crawl queries make named knowledge bases

- **Status:** Accepted (2026-11-04).
- **Deciders:** Dan Svoboda
- **Supersedes:** the crawl as code (`knowledge_base/crawl_phase2.py`,
  `genefunc_crawl.py`, `extract_phase2_runner.py`, `go_gene_map.py`,
  `pathway_enrich.py`, now in `knowledge_base/retired/`), the per-session crawl
  config editor (`crawl_config.py`, `/api/crawl-config/{dtxsid}`), and the one
  database at the repository root (`bmdx.duckdb`).
- **Related:**
  - `crawl_queries/baseline.yaml` (the May 2026 query, stated in full);
  - `knowledge_base/crawl_queries.py` (the store and the shape check);
  - `knowledge_base/query_agent.py` (proposed edits);
  - `knowledge_base/run_crawl.py` (the stages), `citegraph.py`, `entity_crawl.py`,
    `extract.py`, `annotate.py`, `build_db.py`;
  - `knowledge_base/registry.py` (the knowledge bases, `kb_for`);
  - `document_model/document_definition.py` (`knowledge_base:`),
    `document_model/knowledge_base_assignment.py`;
  - `pipeline/kb_currency.py` (a change stales the genomics sections);
  - `safeguards/knowledge.py`, `safeguards/guarded.py`, `safeguards/refusals.py`;
  - `web_routes/knowledge_graph_routes.py`;
  - `tests/unit/test_knowledge_bases.py`.

## Context

The genomics interpretation is grounded in a literature knowledge base: papers,
the claims extracted from them, the genes and organs they name, GO terms and
pathways. There was one, `bmdx.duckdb`, built in May 2026 and never rebuilt. Its
recipe was spread over Python constants: organ keyword lists, seed DOIs, gene
alias maps, a "toxicogenomics analyst" prompt, consensus thresholds, the
gene-function and gene-tox search templates, and paths to crawl directories on
another machine. A config editor exposed a few crawler limits per session; it
launched nothing.

The maintainer asked for a crawl customizer that is agnostic: the person sees
the query and tailors it, directly or with an agent's help; names the query and
names the crawl; and the crawl yields a knowledge base that any report can be
assigned (in its YAML), or that is the default.

## Decision

1. **A query is named text.** `crawl_queries/<name>.yaml`, under git. The text
   holds the whole recipe, one section per stage: `crawls` (seeds, searches,
   limits), `relevance` and `tags` (how a paper is judged and tagged), `extract`
   (the model's instructions and the fields, each with its normalisation rules),
   `consensus` (which field is counted, by which), `follow_on` (crawls seeded
   from entities), `annotate` (GO and pathway sources). A stage whose section is
   absent is skipped. Nothing in the code knows the topic.
2. **The check is loose.** Before saving, the text must parse and each section
   must have the shape its stage reads. The content is never judged. Saving over
   a name archives the old text (`crawl_queries/.history/<name>/`).
3. **The agent proposes; the person saves.** `query_agent.propose(text,
   request)` returns a revised text, an explanation and a diff; it saves nothing
   and runs nothing. It knows the format and the text it is given, nothing of
   any session. It calls the model through the approved gateway.
4. **A named crawl makes a named knowledge base.** `python -m
   knowledge_base.run_crawl <query> --as <name>` (or the route) writes
   `knowledge_bases/<name>/`: `kb.duckdb`, the crawl's outputs (untracked),
   and `manifest.json`. The manifest holds the query's name, text and hash, each
   stage's status, the database's SHA-256 and its **capabilities**, which are read
   off the tables it holds.
5. **No partial result.** A stage that cannot run (a source unreachable, no
   model) leaves the knowledge base unfinished; an unfinished one is never read,
   and can be resumed. A finished one never changes, and its name is never
   reused.
6. **Two layers in the database.** Any query yields `papers`, `citation_edges`,
   `paper_claims` and `paper_entities(paper_id, field, value)`. A query that
   counts genes by organs also yields the toxicogenomics tables `ToxKBQuerier`
   reads: `genes`, `paper_genes`, `paper_organs`, `go_terms`, `gene_go_terms`
   and `pathways`.
7. **A report reads one, resolved in one place.** `registry.kb_for(dtxsid)`
   returns the knowledge base named by the report's document definition
   (`knowledge_base:`, inherited through `extends` like the rest of the
   definition; a study a report composes reads its report's), else the one named
   in `knowledge_bases/DEFAULT`. Every reader resolves through it: the
   interpretation, its references, the chat tools, the workflow's
   `hasKnowledgeBase`, curation, the upload route and the tooling. No code names
   a database path.
8. **Refused, not degraded.** A report's knowledge base must hold papers, claims,
   genes, GO and pathways. `safeguards.knowledge` refuses to assign, or to make
   the default, one that is unknown, unfinished or lacks these, and refuses an
   assignment a fixed definition would hide. The core steps assign what they are
   given, so the notebook can.
9. **A change is never silent.** The interpretation cache is a narrative store
   that is never rewritten unasked. So at Process, `kb_currency.reconcile`
   compares the report's knowledge base with the one the session last processed
   with (`knowledge_base.json`). On a change it discards the store and marks the
   catalog's knowledge-base sections (genomics) stale with the reason
   `knowledge_base_changed`. They are written again, and the publish gate waits
   for a person to accept them.
10. **Today's database is the first named one.** `bmdx.duckdb` is registered as
    `knowledge_bases/baseline-2026-05/` (`replaces: bmdx.duckdb`), from
    `baseline.yaml`, and is the default. A session processed before named
    knowledge bases read it.

## Consequences

- **Nothing changes for the existing reports.** The query-driven build, run on
  the May 2026 crawl outputs under `baseline.yaml`, gives back every table of
  `bmdx.duckdb` row for row. A test checks this when the outputs are present.
- **A query leaves.** Its searches go to Semantic Scholar, a public service. A
  save whose searches newly name genes from an unpublished study's results
  (sessions with no published book) is held until the person confirms. Whether
  to refuse instead is the maintainer's call.
- **A real crawl here needs the network.**
  - Semantic Scholar answers, but without `S2_API_KEY` it rate-limits.
  - `rest.kegg.jp`, `reactome.org` and the GO annotation hosts are blocked, so
    a query that annotates from them leaves its knowledge base unfinished.
  - The `table:` alternative lets a query take a table already built.
- **The old crawl modules are retired, not deleted.** They import functions
  that no longer exist.
- **Per-session organ curation reads the session's knowledge base.**
  `corpus_curation` takes its vocabulary from that knowledge base's query.
