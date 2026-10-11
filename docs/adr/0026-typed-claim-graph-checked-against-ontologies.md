# 0026 — The literature claims become a typed graph, and narratives are checked against it

- **Status:** Proposed (2026-09-25). Nothing implemented.
- **Deciders:** Dan Svoboda
- **Related:** [ADR-0022](0022-session-interpretation-chat.md) (the "RLM" pattern:
  the model may only cite from a code-built catalogue — this ADR extends the same
  guarantee from *citations* to *relations*),
  [ADR-0017](0017-content-provenance-data-classification.md) (provenance as the
  classifying principle — a claim edge is provenance made queryable),
  [ADR-0021](0021-three-concerns-data-content-rendering.md) (this is a *data* concern;
  no rendering surface changes), the knowledge-base constraint profile (the
  `bmdx.duckdb` schema is a cross-project contract with rlm-pipe — every change
  here is additive), and the planned gene → apical-endpoint integration (memory:
  `project_gene_apical_integration`), which is the first consumer that cannot be
  built on the current data.

## Context

### What `bmdx.duckdb` is, layer by layer

A colleague asked whether the literature graph with its annotations is "an actual
knowledge graph". The honest answer is that it is three different things stacked in
one file, and only the bottom layer qualifies:

| layer | tables | what an edge means | is it a knowledge graph? |
|---|---|---|---|
| imported ontology fragments | `pathways`, `gene_go_terms`, `go_terms` | gene *participates-in* pathway; gene *annotated-with* GO term | yes — copied from KEGG, Reactome and GO, which are knowledge graphs by construction |
| literature graph | `papers`, `citation_edges`, `paper_genes`, `paper_organs` | paper *cites* paper; paper *mentions* gene / organ | no — these are bibliometric relations, not domain relations. A mention edge says a gene appears in a paper; it does not say what the paper claims about the gene |
| annotations | `paper_claims`, `genes.evidence`, `genes.organs` | one free-text sentence per row; rolled-up counts and tags | no — a sentence like "Cyp1a1 induction in liver preceded hepatocellular hypertrophy" *contains* a triple but is stored as a string. Nothing can traverse it |

The distinguishing test: a knowledge graph answers *"what does gene X do to organ Y,
according to whom, and does any source disagree?"* by walking edges. Ours answers
*"which papers mention X and Y together?"* and hands the model the text. The first
is graph reasoning; the second is retrieval. The colleague is objecting to the gap
between those two questions, and the objection stands.

Two further defects in the existing layers matter here:

- **The GO hierarchy was discarded at build time.** `go_terms` stores each term as a
  flat row with a `cluster_id` and two UMAP coordinates. GO itself is a directed
  acyclic graph of `is_a` / `part_of` edges. Without it, enrichment cannot report at a
  chosen depth, annotations cannot be propagated to ancestors, and the narrative
  cannot say "these terms fall under xenobiotic metabolic process" except by the
  model's recall — exactly the kind of statement a reviewer will check.
- **`paper_organs` is uncurated.** ~400 distinct strings, most of them cell types,
  specimens or vague categories (see memory `expertise_knowledge_base`). A hand-built
  38-organ map exists in another project and was never applied here. Any graph whose
  object nodes are these strings inherits the mess.

### What the narrative pipeline does with it today

The genomics interpretation (`narrative/interpret_analysis.py`) runs enrichment,
BMD ordering, organ-signature prediction and per-gene literature lookup, then
`format_context_text` flattens everything into a ~200-line text block, and the model
writes prose. ADR-0022 guarantees that every `[Sn]` the model cites is a real row in
the catalogue. It guarantees nothing about the *relations* the prose asserts: the
model can cite a real paper for a relation that paper does not contain, and no code
downstream would notice. There is no step after generation that checks the prose
against anything.

### The trigger: the GO Consortium's own agent workflow

In September 2026 the Gene Ontology Consortium began accepting pull requests against
`go-edit.obo` authored by a Claude Code agent, with the repository's `CLAUDE.md`
prescribing the workflow (reported second-hand; the pattern is confirmed by the
public `geneontology/go-ontology` repo, the individual PR details are not
independently verified here). The transferable part is not the curation mechanics —
we consume GO, we will never edit it — but the **division of labour**:

> the model proposes; code that is not the model verifies against the ontology;
> only verified output is accepted.

Our pipeline has the first half only. This ADR adds the second half, and adds the
data structure (typed claim edges) without which the second half has nothing to
check against.

### The consumer that forces the issue

The planned gene → apical-endpoint work requires connections like *Gpt* ↑ →
serum ALT ↑, or *Cyp7a1* → cholesterol, each **individually** backed by a rat- or
human-context paper, with no mouse-knockout intermediary (the MP-ontology route was
rejected for exactly that reason). "Individually backed" means one edge, one
predicate, one paper id, one confidence — a triple with provenance. That cannot be
represented as a claim string, and it cannot be counted, contradicted or audited as
one.

## Decision

### 1. Add a typed claim table; the string claims become its source, not its replacement

`bmdx.duckdb` gains one table (additive — the existing nine are untouched, per the
cross-project schema contract):

```sql
CREATE TABLE claim_triples (
    triple_id    VARCHAR PRIMARY KEY,   -- deterministic hash of (paper_id, s, p, o, qualifiers)
    paper_id     VARCHAR,               -- FK papers.paper_id : the provenance
    subject      VARCHAR,               -- CURIE, e.g. NCBIGene:24296 or a rat symbol pending resolution
    predicate    VARCHAR,               -- one of the controlled vocabulary below
    object       VARCHAR,               -- CURIE: GO:, UBERON:, CL:, CHEBI:, or a local endpoint id
    qualifiers   JSON,                  -- {species, sex, dose, direction, tissue, timepoint} where stated
    evidence     VARCHAR,               -- the claim sentence (or fulltext span) the triple was read from
    confidence   DOUBLE,                -- extractor's self-reported confidence, 0–1
    resolved     BOOLEAN                -- every CURIE resolved by code (see §3); unresolved rows are kept but never served
);
```

`paper_claims` stays. It is the raw material the triples are read from and the
human-readable evidence a reviewer sees. The rolled-up `genes.evidence` /
`genes.organs` columns stay for the existing table builders but are no longer the
basis of any narrative statement once §5 lands.

### 2. A controlled predicate vocabulary, small, with Relation Ontology ids where RO has them

The whole point of typing is that the set of predicates is closed and each has a
definition. Initial set (one file, `knowledge_base/claim_vocabulary.py`; extending it
is a deliberate change, not a side effect of extraction):

| predicate | RO id (if any) | typical subject → object |
|---|---|---|
| `expressed_in` | RO:0002206 | gene → UBERON / CL |
| `upregulated_by` / `downregulated_by` | — (local) | gene → CHEBI (the chemical) |
| `participates_in` | RO:0000056 | gene → GO process / pathway |
| `positively_regulates` / `negatively_regulates` | RO:0002213 / RO:0002212 | gene → GO process |
| `causally_upstream_of` | RO:0002411 | gene or process → process / lesion |
| `associated_with_endpoint` | — (local) | gene or process → apical endpoint |
| `induces` | — (local) | CHEBI → lesion / endpoint |
| `part_of` | BFO:0000050 | UBERON / CL → UBERON (imported, not extracted) |

Roughly a dozen. Anything the extractor cannot fit into this set is *not* a triple
and stays a string claim. That is the intended behaviour: a graph with a hundred
ad-hoc predicates is a string table with extra steps.

### 3. The triple pass: the model reads, code resolves

A second extraction pass runs over `paper_claims` (and over the full-text spans in
`fulltext.py` output where present), one paper at a time, in the same
`knowledge_base/extract.py` style as the existing claim extraction:

1. **Model step.** Input: the paper's title, abstract and claim sentences. Output:
   zero or more candidate triples as *labels* — `{"subject": "Cyp1a1", "predicate":
   "expressed_in", "object": "liver", "qualifiers": {...}, "evidence": "<sentence>",
   "confidence": 0.8}`. The model is never asked for an ontology identifier.
2. **Resolution step (code, deterministic).** Each label is resolved to a CURIE by
   lookup in the locally loaded ontologies (§4) — exact label, then exact synonym,
   then nothing. Gene symbols resolve through the existing rat-symbol handling in
   `gene_go_terms.rat_symbol`. A triple with any unresolved node is stored with
   `resolved = FALSE` and reported in a rejects file for vocabulary review; it is
   never served to the narrative.
3. **Load.** Resolved triples are written to `claim_triples` with a deterministic
   `triple_id`, so re-running the pass is idempotent.

**Why the split.** Language models read well and recall identifiers badly. Asking the
model for `UBERON:0002107` invites a plausible wrong id that no later step can catch.
Asking it for "liver" and having code map that to the id means every identifier in
the graph was produced by a lookup that can be re-run and inspected. This is the same
principle as ADR-0022's catalogue: the model's freedom is bounded by a structure that
code owns.

**Why a pass over existing claims and not a fresh crawl.** The claims already exist
for 2,315 papers and were expensive to produce. The triple pass is a re-reading of
them, so it costs one model call per paper, and it does not require rlm-pipe to be
re-run. If the crawl is later refreshed, the pass re-runs over the new claims.

### 4. Ontologies are loaded as graphs at runtime, from local files, through `oaklib`

`go-basic.json`, `uberon-basic.obo` and `cl-basic.obo` (and ChEBI's subset as needed)
are vendored under `knowledge_base/ontologies/` and opened with the Ontology Access
Kit (`oaklib`, added as a dependency via `uv add`). One thin module,
`knowledge_base/ontology_graph.py`, exposes what the rest of the code needs: label →
id lookup with synonyms, `ancestors(id, predicates=[is_a, part_of])`, and
`is_subsumed_by(a, b)`.

Consequences for existing code:

- `rank_go_sets_by_bmd` and the GO enrichment report their terms with ancestor
  context, and a GO-slim roll-up becomes possible. The UMAP `cluster_id` stays for the
  existing scatter plot only; it is no longer used to *group* terms in any narrative
  statement, because a UMAP neighbourhood is not a semantic relation.
- `paper_organs` strings are mapped once through Uberon (label / synonym) and the
  mapping is committed as a table; the 38-organ hand map becomes a fallback list of
  synonyms fed to the same resolver rather than a separate truth.

The MCP servers that wrap GO for a Claude Code session (`oak-mcp`, the OLS server)
are development conveniences for designing the vocabulary; they are **not** the
runtime path. Narrative generation runs inside the server process and calls the
model through the NIEHS proxy; it must not depend on an interactive session's tool
set.

### 5. A post-generation checker: every relation in the prose must be entailed

After the model produces a genomics narrative (and, later, the gene → apical
narrative), a checker runs before the section is cached:

1. The generator is asked to emit, alongside the prose, the list of relations it
   asserted, as labels in the same shape as §3 step 1 (subject, predicate, object,
   which `[Sn]` supports it). This is the cheapest reliable way to know what the
   prose claims; a second model pass extracting relations from the prose is the
   fallback if the co-emission proves unreliable.
2. Each asserted relation is resolved by code (§3 step 2) and then tested for
   **entailment** against the union of: this session's enrichment result (gene ∈
   enriched term, term ∈ ancestor closure), `claim_triples` (an edge exists with
   that predicate, optionally up to subsumption — `expressed_in liver` is entailed
   by `expressed_in hepatocyte` + `hepatocyte part_of liver`), and the imported
   pathway / GO annotations.
3. A relation with no support is a **finding**: it is listed on the section's review
   surface with the sentence it came from, and the section is marked as needing
   review. Whether unsupported sentences are cut automatically or merely flagged is a
   per-section policy; the default is flag, because a false negative from the
   resolver should not silently delete a correct sentence.

This is the GO-repository pattern moved from "CI before merge" to "check before
cache". It is cheap: subsumption over `go-basic` is a set lookup, milliseconds, so no
reasoner (ELK, HermiT) is involved and the check can run on every generation.

### 6. Where the graph is exposed

- `format_context_text` gains a `=== LITERATURE CLAIMS ===` block: the resolved
  triples touching the session's responsive genes, each with its `[Sn]` provenance
  and qualifiers, ranked by confidence and paper relevance. The model is told these
  are the only gene-level relations it may assert beyond the enrichment result.
- The session chat (ADR-0022) gains one tool, `claims_for(gene | term | organ)`,
  returning triples with provenance, so a toxicologist can ask "what is known about
  Cyp7a1 and cholesterol in rat liver" and get edges, not paragraphs.
- The gene → apical-endpoint section consumes `associated_with_endpoint` and
  `causally_upstream_of` edges directly; that section is not attempted until those
  edges exist.

## Why triples, stated once

- **Mention is not relation.** `paper_genes` says a paper contains a gene symbol.
  Every narrative claim the report makes is a *relation* — gene to process, gene to
  organ, process to endpoint — and a relation needs a predicate.
- **Multi-hop grounding.** Gene → GO process → ancestor process → organ → endpoint
  is a path. Paths can only be walked over edges. The gene → apical goal is a path
  problem.
- **Contradiction and confidence.** With edges, support and opposition per assertion
  can be counted across papers. With strings, only mentions can be counted, which is
  why the current evidence tiers are mention-based.
- **Auditability.** A reviewer checks a triple against its `paper_id` and
  `evidence` sentence in seconds. A paragraph synthesised from twenty claim strings
  cannot be traced sentence by sentence.
- **Checkability.** §5 is impossible over strings. The checker needs something to
  entail *from*.

## Consequences

**Positive**

- The knowledge base becomes a knowledge graph in the strict sense at the claims
  layer, and the imported GO layer regains the hierarchy it was built with.
- Narrative correctness is enforced by code, not by prompting, for relations as
  well as citations. This closes the largest remaining credibility gap in the
  genomics section.
- The gene → apical integration has a data model, and its "each connection
  individually backed" rule is a schema constraint (`paper_id` NOT NULL on the edge),
  not a review discipline.
- The organ vocabulary problem is solved by Uberon rather than by a private map.

**Negative / costs**

- One model call per paper for the triple pass (~2,300 calls), plus ontology files
  of tens of megabytes vendored into the repo or fetched at setup.
- Entity resolution will have a precision ceiling. Rat symbols, human symbols and
  protein names collide; endpoint names (ALT, SGPT, alanine aminotransferase) are
  not in any single ontology. Unresolved triples are the honest cost of not letting
  the model invent ids, and the rejects file will need periodic review.
- The checker will produce false negatives (correct sentences the resolver could not
  ground). The default-to-flag policy in §5 exists because of this; it means some
  reviewer attention is spent on non-errors.
- A schema addition to `bmdx.duckdb` must be coordinated with rlm-pipe's `build-db`
  step so the two projects do not diverge on the table definition.

**Open questions**

- Which ontology, if any, holds the apical endpoints. OBA (Ontology of Biological
  Attributes) covers some clinical-chemistry measurands; organ weights and
  histopathology lesions may need a local vocabulary aligned to the report's endpoint
  names. Until decided, `associated_with_endpoint` objects use a local `endpoint:`
  prefix, and the checker treats them as opaque ids.
- Whether to extract from abstracts + claims only, or also from full text where we
  have it. Full text gives more triples and more noise; start with claims, measure
  the reject rate, then decide.

## Alternatives considered

- **Keep string claims and improve retrieval (status quo plus).** Cheaper, and it is
  what the pipeline does now. Rejected because it cannot support the checker or the
  per-connection provenance the gene → apical work needs; more retrieval does not turn
  a sentence into an edge.
- **A real triple store (RDF + SPARQL, e.g. Oxigraph or rdflib).** The principled
  home for OWL-typed data. Rejected for now: one DuckDB table plus `oaklib` ancestor
  lookups covers every query this ADR needs, and the rest of the pipeline already
  speaks DuckDB. Revisit if cross-ontology reasoning grows beyond subsumption.
- **Run a reasoner (ROBOT + ELK) as the GO repository does.** Rejected: we do not
  author axioms, so there is nothing for a reasoner to find inconsistent. Subsumption
  closure over pre-reasoned `-basic` releases is sufficient and is milliseconds, not
  ten minutes.
- **Route through mouse phenotype (MP) annotations.** Already rejected in the
  gene → apical plan: a cross-species knockout inference chain is not evidence for a
  rat exposure study.
- **Apply the existing 38-organ hand map instead of Uberon.** Rejected: it is a
  private list with no `part_of` structure, so it cannot support subsumption
  (hepatocyte → liver) and it is not shareable with other projects.

## Implementation phases

Each phase is independently shippable and leaves the pipeline working.

| phase | scope | acceptance |
|---|---|---|
| 0 | `oaklib` dependency; vendored `go-basic.json`; `ontology_graph.py` with label lookup, ancestors, subsumption | unit test: `is_subsumed_by(GO:0006805 xenobiotic metabolic process ← GO:0071466 cellular response to xenobiotic stimulus)` and a synonym lookup both pass; the existing genomics tests are unchanged |
| 1 | predicate vocabulary file; `claim_triples` DDL added to `build_db.py`; Uberon + CL loaded; `paper_organs` → Uberon mapping table | mapping covers ≥ 90 % of `paper_organs` rows by count; every unmapped string is listed |
| 2 | the triple pass over `paper_claims`; rejects file | run over the full corpus; report resolved / unresolved counts; spot-check 50 triples against their evidence sentence |
| 3 | `=== LITERATURE CLAIMS ===` block in `format_context_text`; `claims_for` chat tool | the genomics narrative for the reference session regenerates with the block present; a chat question about a known gene returns edges with `[Sn]` |
| 4 | the post-generation checker with co-emitted assertions; findings on the review surface | a deliberately wrong relation injected into a test narrative is flagged; the reference session's real narrative flags ≤ 2 findings, each inspected |
| 5 | endpoint vocabulary decision; gene → apical section consumes `associated_with_endpoint` edges | superseded or extended by the gene → apical ADR when that is written |

Phase 0 is the one to do first regardless of the rest: it costs an afternoon, it
fixes the discarded-hierarchy defect, and every later phase depends on it.
