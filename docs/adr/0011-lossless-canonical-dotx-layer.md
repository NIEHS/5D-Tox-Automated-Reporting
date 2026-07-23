# 0011 — Lossless canonical `.dotx` layer with conservation-checked extraction

- **Status:** Proposed (2026-07-23).
- **Deciders:** Dan Svoboda
- **Related:** [ADR-0006](0006-unify-html-latex-renderers.md) (the shared
  `layout_style` vocabulary the three surfaces resolve identically — this ADR
  makes that vocabulary a *lossy projection* off a new lossless layer, not the
  thing responsible for reproducing a Word template); [ADR-0009](0009-complete-the-layout-style-vocabulary.md)
  (the bounded per-node styling vocabulary; its boundedness is deliberate and is
  exactly why it cannot be the lossless representation); the **vocabulary (design)
  system** work (`vocabulary.py`, `vocab/*.yaml`, `docx_style_extract
  --emit-vocabulary`) that produced the agnostic projection this ADR sits beneath;
  the **docx governance** and **docx styling bootstrap** project memories (the
  "author the look in Word, drive all surfaces" model and the reverse-engineered
  `.dotx` this layer must faithfully carry).

## Context

The application's purpose is document generation **from data**, using a Word
template (`.dotx`) as the styling source of truth. The template is either the one
we reverse-engineered (`assets/templates/NIEHS-report-style-*.dotx`) or a real
one handed to us later; either way we must turn it into *our* specification (a
YAML the pipeline consumes) and be able to turn that YAML back into the identical
template. The stated requirement: **`dotx → yaml → dotx` must not be lossy** —
the YAML must always be reconstructable to the `.dotx` we started from. (The
generated report document is NOT in this loop; this is about the template as a
representation, not a round-trip through a rendered report.)

Three empirical facts constrain the design (all verified against
`NIEHS-report-style-bordered.dotx`):

1. **Byte-for-byte round-trip is impossible through any parse-and-regenerate
   pipeline.** A no-op unzip→rezip already changes the bytes (ZIP compression is
   non-canonical: level, member order, timestamps, CRCs all vary by library —
   md5 `6512…` → `49c7…`, same 72,708 bytes). python-docx re-serializing a part
   changes it too (`styles.xml` 133,127 → 133,126 bytes with no logical edit:
   attribute order, namespace prefixes, whitespace are not preserved). Even Word
   does not re-save its own files byte-identically.

2. **"Readable structured YAML" and "byte-identical" are mutually exclusive.** A
   structured spec (types, `specializes`, `style: {...}`) has by construction
   discarded the serialization detail (attribute order, prefix decls, ZIP packing)
   needed to reproduce bytes. You can have a readable spec *or* byte-identity, not
   both in one artifact.

3. **A `.dotx` is almost entirely template-level, plus bookkeeping noise.** Of the
   package: `styles.xml` (384 styles), `numbering.xml` (10 abstractNum list
   *formats* + 10 num maps), `theme1.xml` (color/font scheme), `fontTable.xml`
   (font declarations) are all reusable *design* — not content. `settings.xml`
   (289 KB) is dominated by **10,886 rsids** (per-edit-session fingerprints, zero
   rendering meaning) plus compat flags. `document.xml` (3.5 KB, 5 demo
   paragraphs) is the only content-specific part. Byte-identity would force
   faithfully reproducing 10,886 rsids — i.e. preserving *garbage*.

The existing extraction (`docx_style_extract`, the `--emit-vocabulary` path)
reads by **allowlist** ("read the keys I know, ignore the rest"). That is
structurally incapable of a losslessness guarantee: "ignore the rest" silently
conflates *known noise* with *signal we failed to model*. A novel `.dotx` with an
unmodeled property is dropped silently, and extraction reports success.

The user's decisive requirement: **discard noise, and *only* noise, with
certainty** — with the caveat that a received `.dotx` may itself contain noise,
so we must be certain we discarded noise and *only* noise.

## Decision

### 1. Two layers, distinct jobs

- **Canonical lossless layer (NEW).** A complete, Word-specific capture of the
  rendering-relevant parts (styles + numbering + theme + fonts). It may hold
  Word-only properties (`outlineLvl`, `widowControl`, `w:link`, `snapToGrid`, …)
  that mean nothing to LaTeX/HTML, because its job is **losslessness**, not
  portability. This is the round-trip source of truth for the `.dotx`.
- **Agnostic vocabulary (EXISTS — ADR-0006/0009).** A bounded, `LAYOUT_KEY_SCHEMA`-
  limited *projection* off the canonical layer, driving the three render surfaces.
  It stays lossy **and that is fine**, because it is no longer responsible for
  reproducing the `.dotx`.

Losslessness lives in the canonical layer; medium-agnosticism lives in the
projection. Neither artifact is forced to be both — which is what dissolves the
"readable + byte-identical" contradiction.

### 2. The identity target is INFORMATION-lossless, not byte-identical

The reconstructed `.dotx` must contain all the same rendering-relevant
information and render identically in Word; its bytes may differ (different XML
serialization / ZIP packing) and its **noise is deliberately dropped**. Byte-
identity is explicitly a non-goal (it is unachievable AND would preserve garbage).

### 3. The conservation law (the certainty mechanism)

Extraction does not allowlist-and-ignore. It **accounts for every element and
attribute** in the rendering-relevant parts, partitioning each atom into exactly
one of three bins:

- **CAPTURED** — mapped into the canonical YAML (modeled signal).
- **NOISE** — matched against an **explicit, auditable noise allowlist** (rsids,
  named default compat flags, timestamps, the demo `document.xml` body, docProps
  dates, …).
- **UNKNOWN** — matched neither.

The invariant:

> `captured ∪ noise ∪ unknown = everything`, and the contract is **`unknown = ∅`**.

If `unknown = ∅`, we have *proven* only noise was dropped: every atom was either
captured or explicitly listed as noise. The guarantee reduces to one finite,
human-auditable artifact — **the noise allowlist** — so "did we drop only noise?"
becomes "is everything on the noise list actually noise?", a reviewable question.

### 4. Hard fail on `unknown ≠ ∅`

If any atom is unclassified, extraction **raises** — no partial YAML, no
"success with warnings." The default disposition of anything unrecognized is
**surface it, never drop it**. A novel `.dotx` cannot be used until a human
triages every unknown into the capture schema (it is signal) or the noise
allowlist (it is noise). This is the strict form the user chose, and it is what
converts "we think we dropped only noise" into certainty.

### 5. The three-part locator (what makes hard-fail actionable)

The unknown report is a triage aid, not a stack trace. Per unclassified atom:

1. **What** — qualified name (`w:snapToGrid`), value, and originating part
   (`styles.xml` / `numbering.xml` / `theme1.xml` / `fontTable.xml`).
2. **Where defined** (always available, from the `.dotx` alone) — the host
   element: e.g. style `1-03_Report_Title` (styleId `1-03ReportTitle`), or
   `abstractNum` id 3 level 0, or `theme1.xml` clrScheme.
3. **Where applied** (requires a document; OPTIONAL) — because a property applies
   not only via the style that carries it but via every style that inherits it
   through `basedOn`, the locator walks the `basedOn` graph **downward** to all
   descendant styles, then scans a **provided example `.docx`** for paragraphs/
   runs referencing any style in that set (`pStyle` / `rStyle` /
   `numPr`→`num`→`abstractNum`) and reports concrete hits (count, first N
   paragraph indices, text snippets).

The document is optional and maps onto fact #3 above: the `.dotx` body is 5 demo
paragraphs, so the `.dotx` alone gives only the definition site; a real example
`.docx` passed alongside gives real application sites. A useful disposition
signal falls out: an unknown on a style **no provided-document paragraph uses**
(directly or via inheritance) is dead-cruft → noise-allowlist candidate (the
"unused = harmless" logic generalized from the contamination detector); an
unknown that IS applied to real content is signal → extend the capture schema.

### 6. The losslessness proof (two independent checks)

- **Coverage gate:** `unknown = ∅` — nothing real was dropped (everything
  classified).
- **Normalized round-trip:** `strip_noise(source) ≡ strip_noise(rebuild(yaml))`.
  Strip the allowlisted noise from both the source `.dotx` and the yaml-
  reconstructed `.dotx`, then compare. Equality proves the YAML captured 100% of
  the non-noise. This is the achievable form of "byte-for-byte": byte-identity
  **modulo the noise we deliberately and explicitly removed**.

## Consequences

- A received `.dotx` is either fully understood (extraction succeeds, and we can
  prove it dropped only noise) or it **stops the line** with a precise, located
  triage report — never a silent partial capture.
- The noise allowlist becomes a first-class, reviewed artifact — the single point
  where "this is safe to discard" decisions are recorded and audited.
- We may **add to** a template from our own YAML (the user's "add to it" case):
  additive style definitions merge into the canonical layer, non-destructively,
  and re-emit alongside the carried-through original parts.
- The agnostic vocabulary is freed to stay bounded/lossy (ADR-0006's stance
  intact); it is a projection, not the round-trip artifact.
- Cost: the canonical layer is a genuinely new, Word-specific schema plus a
  conservation classifier and a `basedOn`-descent locator — larger than the
  vocabulary work. It is independent of the Phase 2 vocabulary-rendering work
  (that is the projection side and does not touch this layer).

## Non-goals

- **Byte-for-byte `.dotx` reproduction** — impossible through parse/regenerate
  (ZIP + XML both non-canonical) and undesirable (would preserve 10k rsids of
  edit-history garbage). Explicitly rejected in favor of information-losslessness
  modulo an explicit noise allowlist.
- **Round-tripping the generated REPORT document.** This ADR concerns the
  *template* as a representation (`dotx → yaml → dotx`); the data-driven report is
  a separate output whose bytes are produced by our generator, with no original to
  be identical to.
- **Preserving `settings.xml` bookkeeping** (rsids, per-session ids) or the demo
  `document.xml` body — these are the canonical members of the noise allowlist.
- **Making the agnostic vocabulary lossless** — it is a deliberately bounded
  projection (ADR-0006); losslessness is the canonical layer's job, not its.
