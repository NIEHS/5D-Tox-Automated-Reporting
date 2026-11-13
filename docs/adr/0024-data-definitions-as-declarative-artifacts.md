# 0024 — Data definitions are first-class declarative artifacts (format first, UI last)

- **Status:** Proposed (2026-09-23) — a foundational direction, pinned before code.
  Establishes that a *data definition* (what a dataset type IS) becomes a declarative,
  user-authorable artifact rather than hardcoded Python. Sequenced format → pipeline
  consumption → UI. No code yet.
- **Deciders:** Dan Svoboda
- **Related:** [ADR-0017](0017-content-provenance-data-classification.md) (content-anchored
  classification — today's classifier is the hardcoded `_PLATFORM_PATTERNS` this
  generalizes), [ADR-0019](0019-metadata-vocabulary-policy.md) (the metadata vocabulary
  a definition declares its classifying fields against — this is where those fields get
  a *per-dataset* home), [ADR-0001](0001-bmdproject-schema-as-load-barrier.md) (the
  BMDProject load barrier a definition must validate against), [ADR-0016](0016-canonical-query-substrate.md)
  (defined datasets land in the query substrate so downstream consumers bind by query),
  [ADR-0003](0003-document-component-model.md) (document structure is already declarative
  YAML — this extends the same principle to the data side), [ADR-0023](0023-figure-provenance-boundary.md)
  (the annotated data-figure tool is a downstream consumer that NEEDS defined primary
  data); the **data workflow abstraction** and **generic doc-gen** project memories (this
  IS the concrete first step of that direction).

## Context

This decision surfaced from a dependency chain, walked backwards:

> to add an **annotated chart** of new data (ADR-0023, a data-figure) → the chart must
> be **constructed from data in `integrated.json`** (no image upload) → so the new data
> must first flow through the pipeline → but the pipeline only handles **known**
> platforms → so "previously unknown data" first requires a way to **define** what that
> data IS.

Data definitions today are **hardcoded**. `bmdx_pipe/file_integrator.py` carries
`_PLATFORM_PATTERNS`, `_BM2_PLATFORM_MAP`, `_KNOWN_PLATFORMS` as literal tables; the
per-platform table builders, the BMDProject schema, and the NTP stats paths are all
Python. Adding a new kind of data is therefore a **developer act**, not a
configuration. ADR-0019 already recorded the symptom from the metadata side: the
classifying vocabulary is "load-bearing yet today has no single definition."

Everything else in the architecture has moved to declarative: document structure is
YAML (ADR-0003), the metadata vocabulary is heading to a declared policy (ADR-0019),
charts are declared (`chart_types`/`chart_style`). The hardcoded platform table is the
odd one out — and the thing blocking arbitrary new data.

**The decision on the table is NOT "add a chart tool" or even "add a definition UI."**
It is: *does a data definition become a first-class configurable artifact at all, or
stay a developer act?* The UI is downstream of that; posed first, it would be a GUI over
a format that does not exist.

## Decision

### 1. A data definition becomes a declarative artifact, not code

Introduce a **data-definition** artifact: a declarative description of a dataset type —
its fields, types, units, identity keys (what makes a row unique), validation rules, and
the metadata (ADR-0019 vocabulary) that classifies it. The integrator reads definitions
from this artifact instead of consulting hardcoded `_PLATFORM_PATTERNS` /
`_KNOWN_PLATFORMS`. The known platforms (Body Weight, Clinical Chemistry, …) become
*shipped definitions*, not literal tables — the same move ADR-0003 made for document
structure (built-in template = a shipped config, not hardcoded nodes).

This keeps **Architectural Invariant #1** intact: defined-but-novel data flows into the
one `integrated.json` (+ sidecars, + the ADR-0016 query substrate), NOT a parallel
store. A separate source of truth for "new" data would be the bypass the invariant
forbids; this is the opposite — one pipeline gaining a general channel.

### 2. Sequence: format → pipeline consumption → UI (UI last, maybe never-needed)

Three separable things, deliberately ordered; do NOT collapse them:

1. **The definition FORMAT** — the declarative schema for a dataset type. The real
   prerequisite; nothing downstream exists without it. Design this first.
2. **Pipeline CONSUMPTION** — `file_integrator` (now cleanly below the seam, post
   ADR-0017/seam-recut) reads definitions from config; an unrecognized-but-*defined*
   dataset is carried through as a generic, metadata-typed dataset rather than
   rejected or force-fit to a known platform. This is the "generic carry-through" the
   annotated-chart tool (ADR-0023) depends on.
3. **A UI to author definitions** — last, and optional. Once definitions are
   declarative config, a user authors them by editing the artifact (like `document.yaml`
   via the configurator) long before any GUI exists. Plain-file authoring bridges the
   gap, exactly as it did for the document configurator.

**Rationale for UI-last:** a definition-authoring GUI over a not-yet-existing format is
backwards; and a half-defined format exposed to users ossifies (users author against
it, freezing it before it is right). Format-first de-risks; the format can still evolve
while only YAML authors touch it.

### 3. The UI, when built, is an admin function behind the existing obscurity gate

The definition-authoring UI is an **administrative** surface (defining data types is a
setup/governance act, not per-report work). It rides the pattern already in the
codebase — an `/api/admin/*` route prefix already exists (`background_server.py`), and
the app already uses **security-through-obscurity** as its access model (the `?user=`
`ALLOWED_USERS` gate, explicitly documented there as "not real auth… good enough to
keep random visitors out"). A secret/unlisted admin route under that same gate is the
consistent choice: **good enough for now, and plausibly forever** for this app's threat
model (a small research tool, not a public multi-tenant service). If a real threat model
ever arrives, hardening the gate is a localized change — not a reason to over-build auth
now.

### 4. Downstream consumers (named, not built here)

- **Generic dataset carry-through** (§2.2) — the integrator change; first consumer of
  the format.
- **Annotated data-figure tool** (ADR-0023) — binds a chart to a defined dataset (ideally
  by query against the ADR-0016 substrate) and adds the annotation layer. The original
  motivating feature; now correctly a *third-order* consumer down the chain.
- **The broader data-workflow abstraction** — this is the concrete first step of
  splitting the pipeline from being THE hardwired BMD-Express workflow (project memory).

## Consequences

- Adding a new kind of data becomes configuration, not a code change — the data-side
  peer of the already-declarative document side.
- Single source of truth holds: novel data lives in `integrated.json` + the query
  substrate, provenance-classified by the ADR-0019 vocabulary, not a side channel.
- The chart tool (ADR-0023) becomes buildable — its blocking prerequisite is this
  format + carry-through.
- This is a **large, foundational** direction, not a feature: it touches the
  integrator, the classifier (ADR-0017), the metadata vocabulary (ADR-0019), and the
  substrate (ADR-0016). It should be built in staged, independently-committable
  increments under the golden/characterization nets, like the seam re-cut.
- Cost/risk: the definition format is a new contract that, once authored against,
  resists change — hence format-first with only YAML authoring until it has settled.

## Non-goals

- **Designing the definition format here.** This ADR decides *that* definitions become
  declarative + the sequencing; the concrete schema is the next step.
- **Building the pipeline carry-through or the chart tool now.** Named as downstream
  consumers; separately scoped.
- **A real authentication/authorization system.** The admin surface uses the existing
  obscurity gate; real auth is out of scope unless the threat model changes.
- **Replacing the known-platform behavior.** Shipped definitions reproduce today's known
  platforms; this generalizes the mechanism without changing existing report output.
