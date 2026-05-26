# 0002 — Decompose `api_process_integrated` into per-Layer functions

- **Status:** Proposed (2026-05-25)
- **Deciders:** Dan Svoboda
- **Related:** [ADR-0001](0001-bmdproject-schema-as-load-barrier.md) (this
  endpoint loads `integrated.json` through that barrier); rlm-code
  from-scratch structure report (`docs/code-structure-report-2026-05-20.html`),
  which flags this function as the project's one genuine god function by
  call-graph fan-out.

## Context

`api_process_integrated(dtxsid, request)` in `process_integrated.py` is the
central pipeline endpoint: when the UI approves an integrated dataset, this
handler turns `integrated.json` into the full set of report artifacts —
NTP statistics, apical/genomic sections, BMDS modeling, charts, and every
LLM-generated narrative — and returns them as one JSON payload the frontend
renders directly.

As of this writing it is a **~775-line async route handler**
(`process_integrated.py:116–890`, file is 955 lines total). The call graph
gives it `in=0` (nothing internal calls it; it is reached only as an HTTP
route) and `out=28` (it orchestrates 28 distinct downstream symbols). The
entire body is a single `try/except` that accumulates local variables across
nine sequential phases and assembles them into a `result_payload` dict at the
end.

The function is not poorly written — the author has already **labeled its
phases as "Layers"** in comments, and the dependency structure between them is
explicit and correct. The problem is purely size and testability: 775 lines in
one scope means the only way to exercise any single phase is to run the whole
pipeline, the ~15 locals captured by the Layer-2 closures are invisible to a
reader scanning for a specific phase, and the file sits well over the project's
~1200-line soft cap when its sibling helpers are counted.

This function was itself **extracted from the older `pool_orchestrator.py`**
(commit `17db1b4`). This ADR proposes the next layer of that same
teasing-apart: from "one orchestrator file" to "a thin orchestrator calling
named, individually-testable phase functions."

### The contract that must not change

Two observable behaviors are load-bearing and must survive byte-for-byte:

1. **The HTTP payload shape.** `result_payload` has exactly twelve keys:
   `sections`, `unified_narratives`, `genomics_sections`, `gene_set_narrative`,
   `gene_narrative`, `chart_images`, `apical_bmd_summary`,
   `apical_bmd_summary_bmds`, `apical_bmd_narrative`, `bmd_stats`,
   `bmd_stat_labels`, `methods`. A comment at the assembly site states the
   shape is identical to the old monolithic response so the frontend needs no
   changes. The frontend depends on this; the decomposition may not alter it.

2. **The cache files written.** Each Layer writes a `_cache_<kind>_<hash>.json`
   sidecar (`ntp`, `sections`, `bmds`, `genomics`, `methods`, `charts`,
   `bmd_summary`, plus per-narrative and per-apical-hash files). These are how
   re-runs skip already-computed work. Their names, hashes, and contents must
   be unchanged so existing sessions keep hitting cache.

### Phase map (verified against the current file)

| Lines | Phase | Writes cache |
|---|---|---|
| 146–184 | Parse params + load integrated + migrate old monolithic caches | — |
| 185–230 | **Layer 1** — NTP stats (category lookup → filter gene expression → NTP) | `ntp` |
| 231–552 | **Layer 2** — four independent units via `asyncio.gather`: `_get_sections`, `_get_bmds`, `_get_genomics`, `_get_methods` (each a nested async closure) | `sections`, `bmds`, `genomics`, `methods` |
| 553–611 | **Layer 2.5** — Charts + Enrichr (depends on genomics output) | `charts` |
| 612–633 | **Layer 3** — BMD summary (depends on NTP + BMDS) | `bmd_summary` |
| 634–752 | **Layer 3.5a** — per-(organ, sex) LLM narratives: parallel `_one` fanout + user Lock/Unlock overrides | per-narrative |
| 753–794 | **Layer 3.5b** — deterministic body narratives | — |
| 795–858 | **Layer 3.5c** — apical BMD narratives (descriptive deterministic + LLM analytical) | per-hash |
| 859–883 | Assembly → `result_payload` → `JSONResponse` | — |
| 885–890 | `except` → 500 | — |

## Decision

Extract each Layer into a module-level function and reduce
`api_process_integrated` to a **~60-line orchestrator** that sequences them:
`parse → load → layer1 → gather(layer2 × 4) → layer2.5 → layer3 →
layer3.5a/b/c → assemble`. The orchestrator keeps the single outer `try/except`
and the cache-migration preamble. The endpoint signature, the route, the
payload shape, and the cache files are all unchanged.

> **No code is changed by this ADR.** Per the decision to record the design
> before touching the pipeline, this commit adds only this document. The
> extraction is a follow-up governed by the commit sequence below.

### State threading via a `ProcessContext` dataclass

The four Layer-2 units are nested `async` closures that capture roughly fifteen
outer locals (`loop`, `table_data`, the several `*_hash` values, `session_dir`,
`dose_unit`, `bmd_stats`, the GO cutoffs, `compound_name`, `fingerprints`, and
more). Lifting them to module level means that captured state has to be passed
explicitly — and a single forgotten capture is exactly the kind of silent
regression this refactor could introduce.

Rather than grow each extracted function's parameter list to a dozen-plus
arguments, introduce a small `ProcessContext` dataclass that accumulates state
as the pipeline advances. Layer 1 populates the NTP fields; Layer 2 reads those
and populates section/BMDS/genomics/methods fields; later layers read what they
need. This keeps signatures readable (`def layer_3_bmd_summary(ctx:
ProcessContext)`) and makes the data flow between layers an explicit, typed
object instead of implicit closure capture.

The context object is an internal implementation detail of
`process_integrated.py` — it is not the HTTP payload and not a persisted
schema, so it carries no compatibility obligations.

### Preserve, do not change, the dependency ordering

The existing Layer numbering encodes a real dependency DAG: Layer 2.5 needs
genomics from Layer 2; Layer 3 needs NTP from Layer 1 and BMDS from Layer 2;
the 3.5 narratives need their respective upstream sections. The orchestrator
must reproduce this exact ordering, including the `asyncio.gather` parallelism
across the four Layer-2 units. The refactor relocates code; it does not
re-sequence or re-parallelize it.

### Failure mode is unchanged

The single outer `try/except` that maps any failure to an HTTP 500 stays in the
orchestrator. Extracted layer functions raise normally and let the orchestrator
catch — they do not each grow their own try/except, because the endpoint's
contract is "any pipeline failure → one structured 500," and splitting that
across layers would change which errors surface how.

## Safety net and its one gap

The decomposition is value-preserving, so the regression net must compare
output values, not just shape:

- `tests/integration/test_process_integrated.py` — drives the endpoint with
  `TestClient` and a `mock_bmdx_pipe` (no Java subprocess). It is **structural
  smoke only**: asserts 200, key presence and rough shape, and 400 on no data.
  It does **not** value-compare the payload. ← the gap.
- `tests/e2e/test_full_pipeline.py`, `tests/e2e/test_pipeline_flow.py` —
  opt-in via `-m e2e`, skipped by default.
- Real fixture available for a snapshot: `sessions/DTXSID50469320/integrated.json`
  (~69 MB).

Closing the gap is the first step of the recommended sequence below: a
golden-snapshot test that captures the current full `result_payload` and
asserts it byte-identical after every extraction step. Without it, a dropped
closure capture would pass the existing smoke test and ship a wrong report.

## Commit sequence

This ADR records the design only. When implementation is approved, the
recommended sequence is:

1. **Golden-snapshot test first.** Capture the current `result_payload` against
   the synthetic session and assert byte-equality. This closes the
   value-comparison gap before any code moves, so every later step has a
   regression oracle.
2. **Extract one Layer per commit, leaf-first:** 3.5c → 3.5b → 3.5a → 3 →
   2.5 → the four Layer-2 units → Layer 1. Run the integration test plus the
   golden snapshot between each. Roughly eight small, individually-green
   commits.
3. **Introduce `ProcessContext`** at (or just before) the Layer-2 extraction,
   where implicit closure capture is densest and the dataclass earns its keep.
4. **Final orchestrator pass:** confirm `api_process_integrated` is the thin
   sequencer, the migrate-cache preamble and single `try/except` remain, and
   the file is back under the size cap.

Each step is independently landable and revertible.

## Consequences

### Positive

- **Each phase becomes independently testable.** A Layer can be exercised with
  a constructed `ProcessContext` instead of running the whole 69 MB pipeline.
- **The data flow between phases becomes explicit and typed** via
  `ProcessContext`, replacing ~15 implicitly-captured closure locals that a
  reader currently has to trace by hand.
- **The file drops back under the ~1200-line soft cap**, and the god-function
  flag clears from the rlm-code structure report.
- **The contract is provably preserved** if the golden snapshot lands first:
  byte-identical payload after every commit.

### Negative

- **High blast radius.** This is the central pipeline endpoint; a regression
  ships wrong customer-facing reports. This is precisely why the golden test
  precedes any extraction, and why this falls under the cross-cutting-refactor
  constraints (map blast radius, test the full flow). The earlier domain-model
  refactor — committed but never validated end-to-end — is the cautionary
  precedent.
- **`ProcessContext` is a new internal abstraction** that future pipeline
  changes must thread through. This is the intended trade (explicit state over
  implicit capture), but it is a new thing to maintain.
- **Eight commits of churn** on a hot file. Mitigated by keeping each commit a
  pure relocation that stays green.

## Alternatives considered

These were the four approaches weighed before settling on "plan first, then the
golden-test-first sequence":

- **(A) Golden test first, then leaf-first extraction** *(recommended sequence
  once implementation begins).* Safest; closes the value-comparison gap before
  any code moves. Chosen as the implementation plan.

- **(B) Refactor now, lean on existing tests.** Faster, but the structural
  smoke test cannot catch a value regression from a dropped closure capture —
  exactly the failure mode this refactor risks. Rejected as primary; the speed
  gain is not worth shipping a silently-wrong payload.

- **(C) First seam only — extract Layer 3.5c as proof-of-shape**, review the
  `ProcessContext` pattern on the smallest leaf, then decide. A reasonable
  reduced-commitment variant; folded into the recommended sequence as its first
  extraction rather than treated as a separate path.

- **(D) Plan only / ADR, no edits** *(this document).* Record the design for
  review before touching the central pipeline. Chosen for this commit; it does
  not preclude (A) as the subsequent implementation.

- **Big-bang rewrite** (extract all layers in one commit). Rejected: a single
  large diff on the central endpoint is the hardest thing to review and the
  hardest regression to localize. The whole point of leaf-first per-commit
  extraction is keeping each step a small, verifiable relocation.
