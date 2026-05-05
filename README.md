# 5dToxReport

Automated report generation for NTP "5-Day Genomic Dose Response in Sprague-Dawley Rats" studies.

Accepts BMDExpress output files (`.bm2`) and gene-level benchmark dose CSVs, then produces a structured NIEHS Report 10-format document — NTP-style apical endpoint tables, LLM-generated narrative sections, and a toxicological genomics interpretation — exported as tagged PDF/UA-1 or Word (`.docx`).

---

## Contents

- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Report Workflow](#report-workflow)
- [Input Files](#input-files)
- [Knowledge Base Pipeline](#knowledge-base-pipeline)
- [Deployment](#deployment)
- [Dependencies](#dependencies)

---

## Architecture

The system has two major components.

### 1 — Report Generation Web Application

A browser-based application backed by a FastAPI server (`background_server.py`). Users work through sections in order — identify the chemical, generate text, upload dose-response data, review and approve each section, then export.

| Module | Purpose |
|--------|---------|
| `background_server.py` | FastAPI app, middleware, router mounting, static file serving |
| `pool_orchestrator.py` | File pool lifecycle: fingerprint → validate → integrate → process |
| `session_routes.py` | Session load/save, approve/unapprove, version history, BMD summary |
| `upload_routes.py` | Upload `.bm2`, CSV, ZIP; process genomics; preview files |
| `llm_routes.py` | LLM generation endpoints (background, methods, genomics narrative, summary) |
| `export_routes.py` | Export full report as tagged PDF/UA-1 or `.docx` |
| `document_tree.py` | `DocNode` tree — single source of truth for report structure and table numbering |
| `report_pdf.py` | PDF generation via Typst (`report.typ`) |
| `build_docx.py` | Word document assembly |
| `session_store.py` | On-disk session persistence with per-section version history |
| `server_state.py` | Shared mutable state (upload registries, pool fingerprints) |
| `style_learning.py` | Global writing style profile learned from user edits |
| `interpret.py` | Toxicological interpretation: KB queries, pathway/GO enrichment, LLM narratives |
| `web/` | Alpine.js frontend (HTML + CSS, no build step) |
| `java/` | Pre-compiled BMDExpress 3 helper classes (`.bm2` parsing, Williams/Dunnett tests) |

**Table builders** (consume `integrated.json` only):

| Module | Table |
|--------|-------|
| `body_weight_table.py` | Body weight |
| `organ_weight_table.py` | Organ weight |
| `clinical_pathology_table.py` | Clinical pathology |
| `tissue_concentration_table.py` | Tissue concentration |
| `apical_bmds.py` | Apical endpoint BMDs |

### 2 — Toxicogenomics Knowledge Base

A literature mining pipeline that builds `bmdx.duckdb`, a DuckDB analytical database used by the interpretation step. It crawls the Semantic Scholar API, extracts gene/claim data from abstracts via local LLM, normalizes gene names, cross-references Gene Ontology and pathway databases, and loads everything into a 9-table schema.

See [Knowledge Base Pipeline](#knowledge-base-pipeline) for details.

---

## Quick Start

```bash
# Install dependencies
uv sync

# Start the server (default port 9000)
uv run python background_server.py

# Or on a specific port / host
uv run python background_server.py --port 8080 --host 0.0.0.0
```

Open `http://localhost:9000` in a browser. The login gate displays the usage guide — read it before proceeding.

**Prerequisites:**
- Python 3.12+
- Java 21 JRE (for `.bm2` file processing via BMDExpress helper classes)
- `bmdx.duckdb` knowledge base (see [Knowledge Base Pipeline](#knowledge-base-pipeline) to build, or use the committed copy)
- `bmdx-core.jar` and its Maven dependencies staged in `bmdx/target/` (contact project maintainer)
- Anthropic API key in environment (`ANTHROPIC_API_KEY`) for Claude-backed generation, OR a local Ollama server for open-weight model runs

---

## Report Workflow

Every section follows the same cycle: **generate → review → edit (optional) → approve**.

Approved sections are saved to the server and restored automatically on page reload. Any section can be unapproved to regenerate or re-edit it.

**Step 1 — Identify the chemical**
Enter a DTXSID or chemical name. The server resolves it via CompTox to retrieve the chemical name, CAS number, and formula, which seed the report metadata.

**Step 2 — Generate narrative sections**
LLM-generated background and methods sections are streamed to the UI. The LLM receives structured context assembled from the knowledge base and experiment metadata.

**Step 3 — Upload dose-response data**
Upload one or more `.bm2` files (BMDExpress output) and/or a gene-level BMD CSV. The pool orchestrator fingerprints each file, validates cross-file consistency (dose groups, animal counts), and integrates the best file per platform into a unified `integrated.json`.

**Step 4 — Apical endpoint tables**
Table builders consume `integrated.json` and produce NTP-style formatted tables for body weight, organ weight, clinical pathology, tissue concentration, and apical BMDs.

**Step 5 — Genomics interpretation**
The gene-level BMD CSV is processed against the knowledge base: pathway and GO term enrichment (Fisher's exact test, BH FDR correction), BMD ordering by pathway, organ signatures. Results are sent to an LLM for a toxicological interpretation narrative.

**Step 6 — Export**
Export the approved report as a tagged PDF/UA-1 (via Typst) or Word document.

---

## Input Files

| File type | Extension | Contents |
|-----------|-----------|----------|
| BMDExpress output | `.bm2` | Apical endpoint dose-response results (Java serialized format) |
| Gene-level BMD CSV | `.csv` | Gene symbols with benchmark dose values from BMDExpress genomics analysis |
| ZIP archive | `.zip` | Bundle of the above; extracted and registered automatically |

`.bm2` files are parsed by Java helper classes (`ExportBm2.java`, `IntegrateProject.java`) invoked via subprocess. The Java layer handles the BMDExpress 3 serialization format and runs Williams/Dunnett statistical tests headlessly.

---

## Knowledge Base Pipeline

`bmdx.duckdb` is built by a multi-phase literature mining pipeline. A committed copy ships with the repo — rebuild only if you need to expand or update it.

### Schema

```
go_terms        — 2,840 GO Biological Process terms with UMAP coordinates and HDBSCAN clusters
genes           — ~21,490 gene symbols (161 consensus, 149 moderate, rest from GO annotations)
papers          — 2,319 deduplicated papers from all crawl directories
gene_go_terms   — 130,250 gene-to-GO-term annotations (rat, human, or both)
paper_genes     — which genes each paper mentions (normalized)
paper_organs    — which organs each paper studies (normalized)
paper_claims    — scientific claims extracted from abstracts
citation_edges  — paper-cites-paper edges
pathways        — 2,860 gene-pathway associations (KEGG + Reactome)
```

### Rebuild steps

```bash
# 1. Crawl papers (Semantic Scholar API)
uv run python citegraph.py --query "your search terms" --output citegraph_output_topic

# 2. Phase 2 targeted crawls (organ gaps, gene-function deep dives)
uv run python crawl_phase2.py

# 3. LLM extraction (requires local Ollama with qwen2.5:14b, or edit model arg)
uv run python extract.py citegraph_output_topic/papers.json

# 4. Merge consensus across all crawl directories
uv run python extract.py merge

# 5. Pathway enrichment (KEGG + Reactome)
uv run python pathway_enrich.py

# 6. Build DuckDB
uv run python build_db.py
```

See `README_pipeline.md` for detailed options including full-text extraction.

### Coverage

The current database was built from 2,315 deduplicated papers across 7 crawl directories (general tox, brain, heart, lung, gene-function passes 1 and 2). Top consensus genes by paper count: NFE2L2 (81), TP53 (63), BCL2 (45), BAX (41), SIRT1 (39), IL6 (38), KEAP1 (37), TNF (36).

---

## Deployment

The application ships with a `Dockerfile` targeting Google Cloud Run.

```bash
# Stage external JARs and data, then build and push
./deploy.sh
```

`deploy.sh` stages `bmdx-core.jar`, its Maven dependencies, and `bmdx.duckdb` into `_bmdx_jars/` and `_data/` before the Docker build, so those artifacts never enter version control.

Sessions are persisted to a GCS bucket mounted via GCS FUSE (`gs://rlm-bmdx-sessions/sessions/`) — the container mounts `/app/sessions` to this volume at runtime, so session data survives redeploys.

Single uvicorn worker is required because DuckDB is not safe to share across forked processes.

Access control is handled by the `ALLOWED_USERS` environment variable (comma-separated usernames). All `/api/` requests require `?user=<name>` matching the allowlist.

---

## Dependencies

**Python** (managed by `uv`):
`fastapi`, `uvicorn`, `duckdb`, `pybmds`, `anthropic`, `python-docx`, `typst`, `networkx`, `pandas`, `scipy`, `plotly`, `umap-learn`, `hdbscan`, `pronto`, `orjson`, `requests`

**System:**
- Java 21 JRE (BMDExpress 3 subprocess calls)
- Typst (bundled via `typst` Python package)

**External at runtime:**
- Anthropic API key, or local Ollama server
- `bmdx-core.jar` + Maven deps (BMDExpress 3 headless library — not open source; contact maintainer)

**Local dependency:**
- `bmdx-pipe` — editable install from `../bmdx-pipe`; provides `FileFingerprint`, `ValidationReport`, `build_table_data_from_bm2`, and related utilities
