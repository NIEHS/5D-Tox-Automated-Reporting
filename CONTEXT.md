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

> **Module paths (2026-08-12, ADR-0013):** the code is organized into concern
> packages (`web_routes/`, `pipeline/`, `document_model/`, `rendering/`, `tables/`,
> `narrative/`, `genomics/`, `knowledge_base/`, `styling_export/`, `tooling/`).
> Bare module names below (e.g. `render_common.py`, `document_template.py`,
> `html_generator.py`) are package-qualified in code — see the package table in
> `CLAUDE.md` for which package each lives in. Imports are
> `from <package>.<module> import ...`; the app entrypoint is
> `python -m web_routes.background_server`.

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
| **Render surface** | An output projection of the document tree. Four emitters exist, all over the shared IR (`render_common`): the in-app **HTML preview** and the **Overleaf LaTeX bundle** (both live HTTP endpoints), plus a **Word/OOXML `.docx`** deliverable (ADR-0008) and **BITS/JATS** XML for PMC/Bookshelf submission (ADR-0004); the latter two are built emitters, invoked offline rather than wired to a route. |

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

### Many audiences, one document → N render surfaces over one model

Different audiences need the same report in different forms: the author needs a
fast in-browser **HTML preview**; the committee-review artifact is an
**Overleaf-ready LaTeX bundle** (`report.tex` + class file + `figures/`);
Word-driven reviewers need a **`.docx`** they can track-change; PMC/NCBI
Bookshelf needs **BITS/JATS** XML. Every one of these is a *projection of the
same `DocNode` tree*. The emitters (`html_generator.py`, `latex_generator.py`,
`docx_generator.py`, `jats_generator.py`) are thin **emit** layers over a shared
semantic **IR** (`render_common.py`): one tree walk (`walk_tree`, owned by
`document_tree`) and a markup-free *plan* per node type that decides *what* to
render; each emitter decides only *how* (its markup and escaping). This is the
**ADR-0006** thesis, generalized in its Amendment 1: the surfaces are not just
deduplicated, they are *provably describing the same study* because they read one
description — drift between them would be a **semantic inconsistency**, not a
code smell.

Parity is enforced structurally, not by convention. A node-type registry
(`RENDERABLE_NODE_TYPES`) fails at **import** if a registered type lacks an
emitter on the HTML, LaTeX, or Word surface (`assert_dispatch_covers`), and a
cross-surface semantic-parity test asserts the surfaces *and* the IR agree on the
same facts (table/figure numbers, BMD endpoints). Underneath, assembly parity
still holds — content is assembled into the data dict the same way for both the
web/preview path (`marshal_export_data`) and the session-export path
(`load_session_data`).

The four surfaces differ in **how far into the pipeline they sit**, not in what
they read:

- **HTML** (`html_generator.py`) and **LaTeX** (`latex_generator.py`) are **live
  HTTP endpoints** — `/api/preview-latex-html` and `/api/export-overleaf-bundle`
  (plus `/api/compile-pdf`, which compiles the LaTeX bundle locally with `tect`
  for an in-app truth-check, ADR-0007).
- **Word/OOXML** (`docx_generator.py`, **ADR-0008**) is a native third emitter
  and a one-way OUTPUT surface — Word is never a source of truth for structure.
  It shares the same IR and import-time parity coverage but is invoked offline
  (regeneration script + tests), not yet wired to an export route. Its one
  deliberate divergence is mechanical, not semantic: Word is an object model, so
  handlers *mutate* a python-docx `Document` rather than accumulate markup
  strings.
- **BITS/JATS** XML (`jats_generator.py`, **ADR-0004**) is the fourth projection,
  for PMC/Bookshelf submission — a *projection only*, the model already carries
  what it needs. As of 2026-08-10 it targets a **BITS `<book>`** (the reports are
  books on NCBI Bookshelf, not journal articles); the article-`<article>` path is
  kept alongside it. Validation is offline — a vendored NLM/PMC **StyleChecker**
  transform and a vendored **BITS DTD** gate, run in-process — because a BITS book
  goes through NCBI's manual Bookshelf QA rather than the article Previewer.

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
| [0007](docs/adr/0007-in-app-html-and-pdf-preview.md) | In-app preview: a live HTML view + an on-demand PDF view compiled locally from our own LaTeX (`tect`), side-by-side with a reference PDF — fewer Overleaf round trips, no new renderer. |
| [0008](docs/adr/0008-docx-render-surface.md) | Word/OOXML `.docx` as a third emitter over the shared IR — a one-way OUTPUT surface (Word is never a source of truth), with import-time parity coverage. |
| [0009](docs/adr/0009-complete-the-layout-style-vocabulary.md) | Complete the shared `layout_style` vocabulary so a Word/`.dotx` template can drive per-block typography on every surface. *(Proposed.)* |
| [0010](docs/adr/0010-semantic-type-vocabulary-system.md) | A descriptive semantic-type vocabulary reconciling the component catalog with Word named-styles/`basedOn`. *(Proposed; Phase 0 landed.)* |
| [0011](docs/adr/0011-lossless-canonical-dotx-layer.md) | A lossless canonical `.dotx` styling layer — a conservation law with hard-fail, so styling round-trips without silent loss. *(Proposed.)* |
| [0012](docs/adr/0012-semantic-figure-content-type.md) | A first-class semantic `figure` content type. *(Proposed; implemented alongside the vocabulary work.)* |

> **Note (2026-05):** the report's output pivoted from Typst/PDF to
> **LaTeX/Overleaf** + the HTML preview; Typst/PDF is no longer a surface. A
> vestigial `report.typ` remains on disk as a historical artifact but is dead —
> no live code compiles it.
>
> **Note (2026-08):** there are now **four** render surfaces (HTML, LaTeX, Word,
> BITS/JATS), all projections of the one `DocNode` tree via the `render_common`
> IR. The BITS surface targets a NCBI Bookshelf **`<book>`** (ADR-0004), and the
> newer ADRs (0007–0012) extend the model with a local-compile preview, the Word
> surface, and a semantic styling vocabulary.
