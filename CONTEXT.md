# 5dToxReport — Context

The single-context domain document for this repository (see
`docs/agents/domain.md`). It explains **what the application is for** and **how
that purpose drives the architecture** — the *why* behind the structure, not a
module-by-module catalog (the README has the operational view; `docs/adr/` has
the decision records this document points to).

---

## Purpose

The U.S. National Toxicology Program (NTP) runs a short, high-information assay
called the **5-Day Genomic Dose Response study in Sprague-Dawley rats**: a test
chemical is dosed at several levels for five days, and the response is measured
two ways at once —

- **apical endpoints** — the classic toxicology readouts (body weight, organ
  weights, clinical chemistry, hematology, hormones, tissue concentration), and
- **transcriptomics** — genome-wide gene-expression dose-response, reduced to a
  **benchmark dose (BMD)** per gene.

For each study, a toxicologist must turn that data into a **NIEHS biological
potency report** — a long, highly conventional document (the gold-standard
layout reference is *NIEHS Report 10*) with NTP-style statistical tables,
prose narrative sections (background, methods, per-organ findings,
interpretation, summary), and a transcriptomic interpretation that connects the
gene-level signals to the apical findings.

Writing one by hand is slow and error-prone, and the conventions (table
formats, footnote schemes, BMD classification rules, naming conventions) are
strict. **This application automates that report.** It accepts the raw analysis
artifacts — BMDExpress output files (`.bm2`) for apical endpoints and a
gene-level BMD CSV for transcriptomics — and produces a structured,
review-and-approve report a human edits and signs off on, section by section.

The intended user is a **toxicologist/report author**, not a programmer: the
system generates a draft, the author reviews/edits/approves each section, and
the result is exported for publication.

---

## Domain glossary

Use these terms (and only these) when naming concepts in code, issues, tests,
and proposals. If a concept you need isn't here, that's a signal — either
you're inventing language the project doesn't use, or there's a real gap.

| Term | Meaning |
|------|---------|
| **Apical endpoint** | A whole-organism toxicology readout (body/organ weight, clinical chemistry, hematology, hormones, tissue concentration). Distinct from gene-level signals. |
| **BMD / BMDL** | Benchmark dose / its lower confidence bound — the dose producing a defined effect size. The report's central quantity, computed per apical endpoint and per gene. |
| **`.bm2`** | BMDExpress 3's Java-serialized project file. Carries apical dose-response results; parsed only through the Java layer. |
| **integrated.json** | The single, canonical dataset for one session, in BMDProject format. All report content reads from here (plus sidecar JSONs). See invariant 1. |
| **Sidecar** | A per-session JSON alongside integrated.json preserving per-animal metadata the pivot discards (Selection core-vs-biosampling, Observation Day, Terminal Flag, raw per-animal values). |
| **Document tree** | The `DocNode` tree — the single source of truth for report structure: heading hierarchy, section order, positional table/figure numbering, platform→section mapping. See invariant 2. |
| **Component catalog** | The registry of document-component *types* (`render_capabilities.py`) — each type's capabilities (orientable, breakable, editable…), allowed children, required bindings, and content kinds. |
| **Template** | A YAML file in `templates/` that *authors* a report: which components, in what order, with what bindings. Instantiated into a `DocNode` tree at load time. |
| **Platform** | A data domain within a study (e.g. "Body Weight", "Clinical Chemistry", "Tissue Concentration", "Gene Expression"). Maps to one or more report sections via the tree. |
| **Apical vs Genomics** | The two halves of the report. Apical = programmatic tables from integrated.json. Genomics = KB-grounded, LLM-written transcriptomic interpretation. |
| **Knowledge base (KB)** | `bmdx.duckdb` — a toxicogenomics database (genes, GO terms, pathways, papers, claims) that *grounds* the genomics narrative in literature rather than model training data. |
| **Pool** | The set of uploaded files for a session as they move through fingerprint → validate → integrate → process. The UI's phase is derived from what pool artifacts exist. |
| **Narrative** | Prose for a section. Some narratives are LLM-generated (background, methods, genomics interpretation), some are programmatic/deterministic. A narrative the user has edited is **user-owned** and never silently recomputed. |
| **Render surface** | An output projection of the document tree: the in-app **HTML preview** and the **Overleaf LaTeX bundle** today; **BITS/JATS** XML is a planned third (ADR-0004). |

---

## How purpose shapes the architecture

Each architectural choice traces back to a property of the problem.

### The report is conventional and structural → the structure is data, not code

Because the report's organization is fixed by NIEHS convention (and must stay
faithful to it while we *intentionally* diverge in places), structure is
modeled explicitly as a **document tree** rather than scattered through the
renderers. A **template** (YAML) authors the tree against a **component
catalog**; an **instantiator** (`document_template.py`) builds the `DocNode`
tree and validates the template at load time (unknown type, illegal
containment, missing required binding → loud failure). Anything structural —
heading levels, section order, table/figure numbers — is *derived from the tree*
(numbers are positional, assigned by a tree walk), never hand-coded into a
renderer. This is the **document-component model** (ADR-0003).

Consequence: composing or customizing a report is **editing files** (a YAML
template + the catalog), not writing renderer code — there is deliberately no
separate admin-authoring tool.

### The data has one true form → one source of truth, never bypassed

A study's data arrives in several raw formats (`.bm2`, CSV, txt, xlsx) with
known pitfalls (a pivot that drops per-animal metadata). To keep every report
section consistent, all content reads from **integrated.json** (plus sidecars
for the metadata the pivot loses). Reading a raw file directly is forbidden; if
data is missing, the fix belongs in the integration step, not a bypass. (See
ADR-0001: the BMDProject schema acts as a *load barrier* — bad data fails at the
boundary, not deep in a table builder.)

### Two audiences, one document → two render surfaces over one model

The author needs a fast in-browser **HTML preview**; the published artifact is
an **Overleaf-ready LaTeX bundle** (`report.tex` + class file + `figures/`). Both
are *projections of the same `DocNode` tree*. The two renderers
(`html_generator.py`, `latex_generator.py`) are thin **emit** layers over a
shared semantic **IR** (`render_common.py`): one tree walk (`walk_tree`, owned
by `document_tree`) and a markup-free *plan* per node type that decides *what*
to render; each renderer decides only *how* (its markup and escaping). Parity is
enforced structurally, not by convention — a node-type registry fails at import
if a type lacks an emitter on either surface, and a cross-surface
semantic-parity test asserts both surfaces *and* the IR agree on the same facts
(table/figure numbers, BMD endpoints). This is **ADR-0006**: drift between the
preview and the Overleaf hand-off is the failure it removes. Underneath,
assembly parity still holds — content is assembled into the data dict the same
way for both paths (`marshal_export_data` for the web/preview path,
`load_session_data` for the session-export path). A planned third surface,
**BITS/JATS** XML for PMC/Bookshelf submission, is a *projection only* — the
model already carries what it needs (ADR-0004), and the IR is the artifact it
projects from.

### The transcriptomic interpretation must be credible → it is KB-grounded

A genomics narrative that hallucinated pathway claims would be worse than
useless. So the interpretation step queries the **knowledge base**
(`bmdx.duckdb`) — pathway/GO enrichment, organ signatures, paper-derived claims —
and feeds that structured, literature-grounded context to the LLM. The KB schema
is a cross-project contract. Apical narratives, by contrast, are largely
deterministic; knowing **which sections are LLM vs programmatic** is essential
before changing any of them.

### The author is the authority → generated content is a draft, edits are owned

Every section follows **generate → review → edit → approve**. Once a user edits
a narrative, it becomes **user-owned**: it is never silently recomputed when
upstream inputs drift (e.g. a re-analysis changes a gene hash). Regeneration is
an explicit, opt-in action that clears the user's override. Approved content is
persisted and restored across reloads.

### `.bm2` is a Java format → a subprocess boundary, not a port

BMDExpress 3's serialization and its Williams/Dunnett statistics live in Java.
Rather than reimplement them, the app invokes pre-compiled Java helpers
headlessly via subprocess. This boundary has its own traps (serialization
ordering, transient vs persisted fields) documented for anyone who crosses it.

---

## Invariants (apply to all work)

These three rules hold regardless of what you're changing. They are the load-
bearing version of the sections above.

1. **integrated.json is the single source of truth.** All report content reads
   from integrated.json + sidecars. Never bypass to read raw `.bm2`/`.txt`/
   `.csv`/`.xlsx`. Missing data → fix the integration step.

2. **The document tree drives all structure.** Heading hierarchy, section order,
   table/figure numbering (positional, never user-provided), and platform→
   section mapping all come from the `DocNode` tree. Nothing structural is
   hardcoded in a renderer.

3. **UI phase is derived, never imperatively set.** `derivePoolPhase(artifacts)`
   examines which artifacts exist and returns the phase; code dispatches on its
   result. (Transient async phases are the only exception.)

---

## Decision records

Read the ADR that touches the area you're about to work in. If your change
contradicts one, surface it explicitly rather than silently overriding.

| ADR | Decision |
|-----|----------|
| [0001](docs/adr/0001-bmdproject-schema-as-load-barrier.md) | The BMDProject schema is a load barrier — validate at the data boundary. |
| [0002](docs/adr/0002-decompose-api-process-integrated.md) | Decompose the `api_process_integrated` god function into labeled layers. |
| [0003](docs/adr/0003-document-component-model.md) | Composable document-component model — catalog + data-driven template + instantiated tree + sub-addressable content. |
| [0004](docs/adr/0004-bits-jats-export-surface.md) | BITS/JATS as a third export surface for PMC/Bookshelf — a projection of the model, not a parallel one. |
| [0005](docs/adr/0005-overleaf-round-trip-content-sync.md) | Overleaf round-trip: committee edits in Overleaf reconcile back into the content model via stable per-node anchors, with the author in the middle. |
| [0006](docs/adr/0006-unify-html-latex-renderers.md) | Unify the HTML/LaTeX renderers behind one semantic IR (`render_common`) + a shared `walk_tree`; both surfaces are thin projections, with parity enforced by a node-type registry and a cross-surface parity test. |

> **Note (2026-05):** the report's output pivoted from Typst/PDF to
> **LaTeX/Overleaf** + the HTML preview; Typst/PDF is no longer a surface.
