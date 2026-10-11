# 0023 — Figure provenance: data-figures are constructed, authored-figures are supplied

- **Status:** Proposed (2026-09-23) — a design principle pinned before the mechanism
  is built. Amends [ADR-0012](0012-semantic-figure-content-type.md): the figure
  `subtype` is reframed as a **provenance declaration**, and the reserved
  `diagram`/`photograph` subtypes gain a defined source channel. No code yet;
  captures the rule so the wiring (and a future AI-artwork capability) can't
  reintroduce the hole.
- **Deciders:** Dan Svoboda
- **Related:** [ADR-0012](0012-semantic-figure-content-type.md) (the `figure` node +
  subtype axis this constrains), [ADR-0017](0017-content-provenance-data-classification.md)
  (content provenance as the classifying principle — this applies the same idea to
  figures), [ADR-0021](0021-three-concerns-data-content-rendering.md) (data vs.
  content-preparation vs. rendering — a data-figure is a concern-[1] product, an
  authored-figure is concern-[2] authored content), [ADR-0018](0018-app-is-not-an-editor.md)
  (authoring is external + reconciled on ingest — governs where an authored figure's
  bytes may come from), [ADR-0005](0005-overleaf-round-trip-content-sync.md) /
  [ADR-0008](0008-docx-render-surface.md) (the round-trip channels a docx-extraction
  source would ride later); the freeform `content_file` channel
  (`document_model/document_template.py`, `styling_export/freeform_content.py`) this
  reuses for authored figures.

## Context

ADR-0012 made `figure` a first-class node with a `subtype` axis (`chart`, `logo`,
reserved `photograph`/`diagram`/…). It left one thing implicit: **where a figure's
image comes from.** Today only `chart` (data-derived, via the genomics chart
pipeline) and `logo` (a supplied branding asset) are wired, and neither is
author-placeable — a standalone `figure` node in a session `document.yaml` renders a
visible `[Figure pending: …]` placeholder because no overlay populates a top-level
figure artifact (the `data["genomics_charts"]` key a naive author would reach for is
dead — `rendering/report_data_overlays.py`, "no node type ever consumed it").

Closing that gap forces the sourcing question — and the sourcing question is really a
**provenance** question. Two figure populations exist, and they must be sourced
differently, because one is a scientific claim and the other is not:

1. **Anything derived from the alphanumeric study data** — a dose-response plot, a
   BMD chart, a UMAP over the expression matrix. This is a rendering *of the data*.
   It is a scientific artifact with the same status as a table cell: it must be
   reproducible from `integrated.json`, re-derivable on reprocess, and never
   author-substituted.
2. **Explanatory artwork not derived from study data** — a workflow diagram, a
   mechanism sketch, a line drawing, a conceptual illustration. There is *nothing in
   the data to construct it from*; it is authored content, legitimately supplied.

The failure mode to prevent: an externally created PNG of the study data brought in
as an image. It looks like a figure but asserts a data claim the app cannot verify,
regenerate, or keep current — a laundering of un-provenanced data through the image
channel. This is the exact hole ADR-0017 closed for tabular data (classify by
content/provenance, not by filename); this ADR closes it for figures.

## Decision

### 1. `subtype` is a provenance declaration, not a rendering hint

Split the figure subtypes along the provenance boundary as the **primary**
distinction a reviewer sees:

- **data-figure** (`chart`, and any future data-derived plot kind) — **MUST be
  constructed from study data** via the chart pipeline (`chart_style` /
  `chart_registry`, concern [1]/[2]). It is deterministic, regenerable, and subject to
  the same currency rules as other data-derived content (re-renders on reprocess;
  the Phase-3b wording-flip logic has no bearing, but the "data changed → refresh"
  discipline does).
- **authored-figure** (`diagram`, `photograph`, `logo`, future `illustration`) —
  **supplied**, because it depicts something with no construction rule in the data.
  Its bytes are authored content, sourced through an authored channel (below).

The `kind` (chart / diagram / logo / …) remains a secondary attribute; the
load-bearing question — *"is this allowed to be supplied as a file?"* — is answerable
from the provenance class alone.

### 2. The guarantee is enforced by CHANNEL, not by inspection

You cannot look at a PNG and prove it is not a mislabeled plot of the study numbers.
So the boundary is not inspected — it is **structural**: the two provenance classes
have disjoint, non-crossing source paths.

- A **data-figure has no upload/supply path.** Its only source is construction from
  data. The file pool, a `content_file` reference, and any future docx-extracted image
  are all *rejected* for a data-figure subtype. Bringing in an external chart PNG is
  therefore not "discouraged" — it is **unrepresentable**.
- An **authored-figure has no construct-from-data path.** It is only ever a supplied
  asset.

"Verboten" is thus a checkable invariant: a data-figure that could be uploaded is the
bug; the type system must make it impossible, the way ADR-0018's channels keep
authoring external.

### 3. Authored-figure source: reuse the freeform `content_file` channel now

An authored-figure references its asset the way `freeform-block`/`freeform-page`
already reference authored bodies — a `content_file` resolved at render time from a
known location (`templates/`-relative today; a session assets dir is the natural
extension). This adds **no new registry and no filename-matching convention** — it
reuses the one existing "authored content lives on the node, resolved from a file"
pattern, and composes with the configurator that already edits `document.yaml`.

### 4. Data-figure source: bind by reference to a constructed chart

A data-figure names an existing generated chart (e.g. by organ / sex / chart-type);
an overlay lifts that chart's PNG onto the node's artifact key at render time. It
reuses the pipeline that already produces the bytes (`attach_genomics_charts` and the
`_cache_charts_*` output) — nothing new is stored, and the chart stays a pure product
of the data.

### 5. Future: an AI artwork capability stays on the authored side of the line

A hypothetical AI illustration tool (user directs it to produce a workflow diagram or
explanatory sketch) is an **authored-figure producer** — its output is supplied
content, not constructed-from-data. It is permitted ONLY for non-data illustration.
The moment it is asked to depict study numbers ("draw the liver BMD response"), it
must refuse and route to the data-figure pipeline — otherwise it reintroduces exactly
the verboten case wearing an AI hat. The provenance rule binds the AI's output the
same as any other authored figure: no data claim may enter through the authored
channel.

## Consequences

- The data-vs-document seam (ADR-0017/0021) now covers figures, not just tables and
  prose: a chart is data (constructed, regenerable, current), a diagram is document
  (authored, supplied).
- The "no external data-chart PNG" guarantee is structural and checkable, not a
  review-time judgement call.
- Authored figures become buildable with existing infrastructure (the freeform
  channel), closing the `[Figure pending]` gap for the legitimate case without new
  concepts.
- A later docx-extraction source (author drops a diagram into the Word deliverable;
  the app extracts + reconciles it on ingest — the ADR-0018 round-trip path, and the
  same media channel as the unbuilt Word tracked-changes reading) can supersede the
  `content_file` source for authored figures **without changing the node model** — it
  is a new source for the same provenance class, not a new figure type.
- Cost: naming/relabeling the subtype axis around provenance touches ADR-0012's
  vocabulary; the two source channels are new render-path wiring (bounded — the
  `[Figure pending]` placeholder already fails safe).

## Non-goals

- **Building the wiring now.** This pins the principle; the `content_file` authored
  source, the data-figure reference-binding, and any subtype rename are separate
  implementation increments.
- **The docx-extraction source.** Deferred to the broader Word round-trip work
  (tracked-changes reading, `w:ins`/`w:del`); named here only so the node model is
  chosen to accommodate it later.
- **The AI artwork tool.** Named as a future capability and constrained in advance;
  not designed or scheduled here.
- **Turning main-body figures on for the NIEHS 5-day report.** As ADR-0012, the
  reference has no main-body figures; this governs the *capability*, not the shipped
  report.
