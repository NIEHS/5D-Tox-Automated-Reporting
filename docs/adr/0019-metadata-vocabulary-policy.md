# 0019 — Metadata is the classifier of data: a vocabulary + provenance policy

- **Status:** Proposed (2026-09-14) — governing model for the DATA side of the
  application architecture. Generalizes [ADR-0017](0017-content-provenance-data-classification.md)
  (content-anchored `dataType`) from one field to the whole metadata vocabulary, and
  supplies the policy the deferred provenance→authority question was waiting on.
- **Deciders:** Dan Svoboda
- **Related:** [ADR-0017](0017-content-provenance-data-classification.md) (the first
  content-anchored field — `dataType` — this promotes to a general rule),
  [ADR-0001](0001-bmdproject-schema-as-load-barrier.md) (the schema is a *structural*
  load barrier with **no domain invariants** — this ADR says where those invariants
  live instead), [ADR-0003](0003-document-component-model.md) (the description+data
  composition model this ADR is deliberately *not* about — see "Composition is not
  architecture"), [ADR-0013](0013-package-layout.md) (concern packages),
  `project_bmdx_pipe_seam` (classification belongs below the data/presentation seam).

## Context — the "aha"

While profiling the Process step we kept trying to locate the LLM in the
architecture — first as a data-pipeline stage, then as a kind of prose. Every
placement was wrong, and the reason exposed a deeper conflation:

**"description (YAML) + data → document" is a render-time COMPOSITION formula, not
the application architecture.** Its three nouns are render-time *roles*, not
architectural layers. Reasoning from the formula as if it were the architecture
produces a false trichotomy (everything must be description, data, or document) that
has no slot for anything upstream of render — including the LLM, and including the
question this ADR answers: *how does the system know what a piece of data IS?*

Behind the composition boundary sit two fundamental concerns:

- **DATA** — structured numeric data, **classified by metadata**. (Imported files
  today; possibly query results in future.)
- **DOCUMENT** — a deterministic reduction of that data, organized by structure.

This ADR is about the DATA concern, and specifically about the classifier itself:
**the metadata.** Data without metadata is an undifferentiated grid of numbers; it
is metadata (platform, dataType, sex, organ, …) that says which numbers are a
hematology reading vs a gene BMD, which processing method applies, and which report
section they feed. The metadata vocabulary is therefore load-bearing — yet today it
is ad hoc: fields are stringly-typed `Optional[str]` on the schema
(`pipeline/bmd_project_schema.py`), `dataType` is *always None in practice*, values
are obtained by a grab-bag of filename regex, LLM inference, and content reads with
no stated authority, and [ADR-0001](0001-bmdproject-schema-as-load-barrier.md)
deliberately keeps *all* domain meaning out of the schema. There is no policy for
what the vocabulary is, where each field's value legitimately comes from, or which
source wins when two disagree.

## Decision

**Adopt a metadata vocabulary policy: the set of classifying fields, their allowed
values, and — for each field — its PROVENANCE and the AUTHORITY that provenance
confers. Metadata is read FROM the data wherever the data carries it; inference is a
declared fallback, never the default.**

Four parts:

### 1. The vocabulary is explicit and owned

Enumerate the classifying metadata fields and, where closed, their value sets.
Today's fields (from `experimentDescription` + the file/source model): `platform`,
`provider`, `dataType`, `sex`, `organ`, `species`, `strain`, `domain`, plus file
identity (`testArticle`/compound identity). Each field declares whether its value set
is **closed** (e.g. `sex ∈ {male, female}`) or **open and growing** (e.g. `platform`,
`provider` — new ones are added as bmdx-pipe learns them; see
[ADR-0017](0017-content-provenance-data-classification.md) and the schema comments).
Open sets are still *governed* — a new value is a deliberate vocabulary addition, not
a free string.

### 2. Every field has a PROVENANCE, and provenance sets AUTHORITY

For each (field × file-source) pair, the value is one of:

- **STATIC (derived fact)** — determined by the data's own content/origin; rendered
  read-only. *The data self-identifies.*
- **DETECTED-BUT-FALLIBLE** — inferred by a heuristic or model and possibly wrong;
  must stay editable and should show that it was inferred.
- **USER-AUTHORITATIVE** — genuinely a human choice with no in-data source.

Authority is a function of **where the value comes from**, not which tier/extension
the file has. The current known mapping:

| source | how metadata is obtained | authority |
|---|---|---|
| xlsx study file | self-identifies from its Key + Data sheet content | **STATIC** (real fact) |
| txt / csv | header line + ADR-0017 content-anchor (roster vs xlsx) | **DERIVED** where content proves it; else ambiguous → editable |
| bm2 | filename fallback + LLM inference over experiment names | **DETECTED-BUT-FALLIBLE** → editable / show confidence |

This is the small **provenance→authority table** each wizard control (and each
consumer) consults, replacing ad-hoc per-field UI decisions. Do **not** blanket-freeze
controls by tier: `bm2 ⟹ inferred` is a *modeling assumption* about what bm2 files
are, not a value read from the file, so its control is not safe to freeze on
structural grounds. `xlsx ⟹ tox_study` is a genuine self-identified fact and is.

### 3. Read from the data; infer only as declared fallback

Prefer metadata **contained within the data**. [ADR-0017](0017-content-provenance-data-classification.md)
is the first instance of this rule for one field (`dataType`, anchored to the xlsx's
own content); this ADR generalizes the stance to the whole vocabulary. Filename
heuristics and LLM inference are **fallbacks that AUGMENT** the in-data reading — they
apply only where the data does not carry the field — and their output is always
DETECTED-BUT-FALLIBLE, never STATIC.

### 4. Dual representation is resolved by a declared authority order, per field

Some fields are represented **both** ways — explicit in the data *and* inferable. That
duality is currently unhandled and is the crux this policy must settle: for each such
field, declare the **authority order** (which source wins) and what a *disagreement*
between sources means (silently prefer the authority? surface a conflict for the
human? treat as a data error, as ADR-0017 does for an unexpected value mismatch?).
The default order follows §2: STATIC in-data reading > DERIVED-by-content >
DETECTED-but-fallible inference > USER default. A conflict between a STATIC source and
an inference is a signal the inference is wrong, not a reason to overwrite the fact.

## The LLM's place (why it is not in this policy as a layer)

The LLM appears in exactly one spot on the data side: a **helper** that makes an
intelligent guess at descriptive metadata not explicitly supplied (sex, organ, …
from `fingerprint_bm2`). It is **not** a stage of the data pipeline and **not** a
structural axis — it is one possible *provenance* for a field, and by §2 that
provenance is always DETECTED-BUT-FALLIBLE. Its footprint is expected to **shrink as
this vocabulary is developed**: the more metadata the data carries and the policy
reads directly, the less there is to guess. Framing the LLM as architectural was the
original error; here it is correctly demoted to one fallback provenance among several.

## Consequences

- **The classifier of data becomes principled, not ad hoc.** "What is this file /
  experiment?" has one answer path: read the vocabulary from the data by provenance,
  fall back to declared inference, resolve duals by declared authority.
- **[ADR-0001](0001-bmdproject-schema-as-load-barrier.md) is respected and
  completed.** The schema stays structure-only (no domain invariants); this ADR is
  where the domain meaning of metadata lives — a policy layer *beside* the schema,
  not inside it. The "(platform, sex) is unique" style rules ADR-0001 explicitly
  refuses to encode have a home here.
- **The Confirm-Metadata UI derives control state from the provenance→authority
  table**, not per-field guesses: STATIC → read-only fact; DETECTED-BUT-FALLIBLE →
  editable + inferred badge; USER → plain input. Settles the deferred
  `project_metadata_authority_by_provenance` question.
- **Coverage checks move to the right granularity.** Asking tier-completeness per
  `Platform|dataType` key emits structurally-impossible noise when tier↔dataType is
  fixed; with the vocabulary explicit, coverage is asked at the level the policy says
  is meaningful (platform), not the accidental compound key.
- **This is the DATA-side prerequisite for the workflow abstraction.** A generic
  "data type → processing method" registry (`project_data_workflow_abstraction`)
  needs a governed type vocabulary to dispatch on. Ad-hoc `Optional[str]` metadata
  cannot key a registry; this policy is what makes types-and-methods-yet-to-come
  addressable.
- **Lands below the bmdx-pipe seam.** Classification is data-model/computation logic
  (`project_bmdx_pipe_seam`), reinforcing ADR-0017's placement — not presentation,
  not a point patch in the wizard.

## Composition is not architecture (scope guard)

This ADR is deliberately about the **production** side (how the system knows what its
data is), not the **composition** side ([ADR-0003](0003-document-component-model.md)'s
description + data → document). The composition formula consumes classified data as
an input; it does not classify. Keeping the two layers distinct is what dissolved the
"where does the LLM go" confusion, and it bounds this ADR: nothing here changes the
render IR or the four surfaces.

## Open questions

- **Vocabulary source of record.** Where does the enumerated vocabulary + value sets
  live — a YAML policy file (like the document template), a Python registry, or the
  schema's neighbor module? (It must be editable as policy, per the "metadata
  vocabulary developed as policy" intent, and consulted by both bmdx-pipe
  classification and the wizard.)
- **Per-field authority order for the known duals.** Enumerate which fields are
  represented both ways in real pools and fix each one's authority order + conflict
  behavior (prefer / surface / error).
- **Confidence surface for inferred values.** How is DETECTED-BUT-FALLIBLE shown —
  a badge, a confidence score, a "verify this" prompt? (Ties to
  [ADR-0018](0018-app-is-not-an-editor.md)'s provisional-vs-final stance: an inferred
  value is provisional until a human or a STATIC source confirms it.)
- **Migration.** `dataType` is `Optional[str]` and unpopulated today; landing the
  vocabulary means deciding whether to backfill existing sessions or apply the policy
  going forward only.
