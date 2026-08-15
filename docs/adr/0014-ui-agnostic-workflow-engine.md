# 0014 — Extract a UI-agnostic workflow engine from the browser

- **Status:** Proposed (2026-08-13).
- **Deciders:** Dan Svoboda
- **Related:** [ADR-0002](0002-decompose-api-process-integrated.md) (decompose the
  process-integrated god function — the pipeline *steps* this engine sequences);
  [ADR-0013](0013-package-layout.md) (the concern-package layout this adds a
  `workflow/` package to); [ADR-0006](0006-unify-html-latex-renderers.md) and
  [ADR-0008](0008-docx-render-surface.md) (the render side, which is *already*
  UI-agnostic — the precedent this generalizes to the authoring side);
  [ADR-0005](0005-overleaf-round-trip-content-sync.md) (the round-trip problem the
  Word approval-governance hook is a lossier instance of). Invariant 3 in
  `CONTEXT.md` ("UI phase is derived, never imperatively set") is the rule this
  ADR *relocates into Python* without weakening.

## Context

The report-authoring workflow — **upload → validate → resolve → confirm-metadata
→ integrate → process → approve** — is sequenced entirely in the browser. The
phase machine (`derivePoolPhase`, `POOL_PHASES`, `computeSectionCompleteness`,
`isNodeComplete`) lives in `web/js/pool_state.js`. The Python side
(`web_routes/pool_routes.py`, `pipeline/`) is a set of **stateless per-step HTTP
handlers** with the step logic written inline in the FastAPI route bodies. **No
Python module knows the phase sequence or which action is legal when.** That
knowledge exists only in JavaScript.

Two independent forces make this a problem now, not a stylistic preference:

1. **Succession.** The current operator (who authored this system and is also its
   primary user) will retire on a 1–3 year horizon. The successor is a
   toxicologist, not a programmer, and will drive the app through the **browser
   UI** — which must therefore remain the durable, hand-off interface and stay
   maintainable by someone who will not touch the phase machine's internals.
2. **A second front-end already exists in embryo.** A Word-driven TUI
   (`feat/word-tui-workflow`: `word_tui.py` + `bmdx_word_plugin.py`, over a
   domain-agnostic `word-remote` library) was prototyped as a keyboard-first
   operator interface. It currently automates only the **last mile** (regenerate
   `.docx` → open in Word → export PDF), because that is the only part of the
   system that is *already* callable without a browser: the render seam
   (`generate_docx(data, tree)`, `load_session_data`, `build_session_tree`) is a
   set of plain functions over the DocNode tree. It hooks in cleanly precisely
   because the **output** half of the architecture is decoupled. The **authoring**
   half is not, so the TUI cannot drive it.

The moment there is more than one front-end (two UIs, or one UI plus the Word
round-trip path), "functional equivalence, kept in step with every workflow
change" is either maintained by discipline — a permanent tax, paid twice, that a
non-programmer successor cannot be expected to pay — or made **structural** by
giving both surfaces one workflow core to drive.

### What the phase machine actually is

`derivePoolPhase(artifacts) -> phase` is a pure function of six presence flags. It
does not touch the DOM. `computeSectionCompleteness` / `isNodeComplete` are pure
functions of a coverage matrix and the document tree. `POOL_PHASES` is the one
genuinely UI-bound structure — and even it fuses two separable things: **workflow
logic** ("which actions are legal in this phase") welded to **DOM rendering**
("button `btn-validate`, text `Validate`, badge class `badge-approved`"). The
pipeline steps themselves already exist as Python — they are just wrapped inside
`async def` route handlers rather than exposed as callables.

So the material to build a core is present; it is on the wrong side of the browser
boundary, and in one place (`POOL_PHASES`) the domain logic is tangled with
presentation.

## Decision

**Introduce a `workflow/` package containing one `WorkflowEngine` that owns phase
derivation, action legality, step execution, and the approval-state model. Both
the web app and any future front-end (TUI, Word round-trip, batch) become thin
drivers that translate engine state into their medium and user input back into
engine calls. No front-end contains workflow *logic* — only presentation and
input.** This generalizes the render-side decoupling (ADR-0006/0008) to the
authoring side.

### The boundary

| Concern | Today | After |
|---|---|---|
| "What phase is this session in?" | `derivePoolPhase` (JS) | **core** |
| "Which actions are legal now?" | `enabled:` flags in `POOL_PHASES` (JS) | **core** |
| Run validate / integrate / process / approve | inline in FastAPI handlers | **core** |
| Per-platform / per-node completeness | `computeSectionCompleteness` (JS) | **core** |
| "An approved section is not silently clobbered" | scattered / implicit | **core** |
| Button ids, text, badge CSS, spinners | `POOL_PHASES` DOM half (JS) | **each UI** |
| Menu layout, keybindings, HTTP shape | routes + JS | **each UI** |

Everything in the top group is pure domain logic; the core claims it. Everything
in the bottom group is medium-specific; each UI keeps it.

### The engine API

A single driver-facing type. Every mutating method **guards on legality first**
(rejects an action that is not legal in the current phase), executes the step, and
returns a `StepResult`.

```python
class WorkflowEngine:
    def __init__(self, dtxsid: str): ...

    def state(self) -> WorkflowState          # re-derives phase every call
    def validate(self) -> StepResult
    def resolve(self, issue_index: int, chosen_file_id: str) -> StepResult
    def confirm_metadata(self, metadata: dict) -> StepResult
    def integrate(self) -> StepResult
    def process(self) -> StepResult
    def approve(self) -> StepResult
    def reprocess(self) -> StepResult
    def reset(self) -> StepResult
```

The engine **never stores a phase**. `state()` re-derives it from the artifacts on
disk on every call. This preserves Invariant 3 (phase is derived, not set) exactly
— it moves the single derivation point from JavaScript into Python, where both
UIs inherit it instead of each re-implementing it.

### The two medium-agnostic types

`WorkflowState` is everything a UI needs to render itself, with no medium baked in:

```python
@dataclass(frozen=True)
class WorkflowState:
    phase: Phase                          # settled phases only (see below)
    legal_actions: frozenset[Action]
    platforms: tuple[str, ...]
    completeness: dict[str, SectionCompleteness]
    issues: tuple[ValidationIssue, ...]
```

`Action` is the decoupling linchpin. Instead of mapping a phase to concrete
widgets, the core maps a phase to a set of **abstract actions**:

```python
class Action(Enum):
    VALIDATE = auto(); RESOLVE = auto(); CONFIRM_METADATA = auto()
    INTEGRATE = auto(); APPROVE = auto(); REPROCESS = auto(); RESET = auto()

LEGAL_ACTIONS: dict[Phase, frozenset[Action]] = {
    Phase.UPLOADED:          frozenset({Action.VALIDATE}),
    Phase.VALIDATED:         frozenset({Action.INTEGRATE, Action.RESET}),
    Phase.VALIDATION_ERRORS: frozenset({Action.VALIDATE, Action.RESET}),
    Phase.INTEGRATED:        frozenset({Action.VALIDATE, Action.APPROVE,
                                        Action.REPROCESS, Action.RESET}),
    Phase.APPROVED:          frozenset({Action.REPROCESS, Action.RESET}),
    Phase.EMPTY:             frozenset(),
}
```

This table is `POOL_PHASES` with the DOM stripped out. The web UI maps
`Action.VALIDATE ∈ legal_actions` → `btn-validate.disabled = false`; the TUI maps
the same membership → an enabled menu command. **Adding or reordering a workflow
step is a one-line edit to this Python table, and every front-end picks it up.**
That is the "stay in step" guarantee expressed as code rather than as a
maintenance promise.

### Settled phases only — transient phases leave the core

`VALIDATING`, `INTEGRATING`, and `APPROVING` **do not exist in the engine.** They
mean "an async call is in flight" — a presentation concern each UI owns while it
awaits a synchronous engine call (the web app shows a spinner; the TUI prints
`validating…`). The core models only *settled* phases. This shrinks the phase enum
from nine to six and **removes the imperative-set exception entirely** — the one
place Invariant 3 had to carve out an exception ("transient phases ARE set
imperatively") becomes a UI-local detail, not a domain rule.

### Package placement

```
workflow/
  engine.py        WorkflowEngine — the driver-facing API
  phases.py        Phase, Action, LEGAL_ACTIONS, derive_phase()
  steps.py         validate/integrate/process/approve as pure callables
  completeness.py  computeSectionCompleteness + isNodeComplete, ported
  artifacts.py     inspect a session dir → the flags derive_phase() needs
  approval.py      approval-state model + the (a)/(b) governance hooks
```

`workflow/` depends on `pipeline/` (the steps) and `document_model/` (the tree,
for completeness). It depends on **no** `web_routes/`. The dependency arrow points
away from the UI — that is the invariant that makes the decoupling real and that a
future import-graph check can enforce (`workflow/` importing `web_routes/` is a
defect).

### Approval-state governance is a natural tenant of the core

Because "approved" state now lives in Python, the two approval guarantees the
maintainer wants become engine methods rather than cross-cutting checks
replicated per surface. **Scope is exactly these two — no per-role permissions, no
who-changed-what-when audit log:**

- **(a)** `engine.regenerate_section(node_id, override=False)` refuses when the
  section is approved unless `override=True`. Every caller — an LLM route, the
  TUI, a batch job — hits the same gate, so an LLM cannot silently clobber
  approved content from *any* surface.
- **(b)** `engine.reconcile_word_edits(docx_bytes) -> list[FlaggedEdit]` diffs a
  returned document against the sent tree and returns the edits that touch
  approved sections, to be recorded and flagged (not silently accepted).

(b) is the expensive one — it is ADR-0005's Overleaf round-trip problem in a
lossier surface (`.docx` protection is a deterrent, not a hard gate), so it ships
as a stubbed extension point, **not** built in this ADR. It is named here only to
record that the engine is its correct and only home — which is itself an argument
for building the engine first.

## What actually moves (the change is narrower than it appears)

1. **The steps already exist.** `api_pool_validate`'s body (`ensure_fingerprints`
   → `validate_pool` → persist report) *is* `engine.validate()`. The work is
   unwrapping logic from `async def handler` into a plain function — roughly five
   handlers.
2. **Port two pure JS functions to Python:** `derivePoolPhase` (~20 lines) and
   `computeSectionCompleteness` / `isNodeComplete` (~80 lines). Mechanical.
3. **Build `LEGAL_ACTIONS`** by reading the `enabled:` flags out of `POOL_PHASES`.
4. **Routes get thin:** parse → `engine.method()` → serialize. `/api/pool/…`
   handlers collapse to a few lines each.
5. **JavaScript stops deriving phase.** `pool_state.js` deletes `derivePoolPhase`
   and the completeness functions and instead consumes `legal_actions` from the
   server response; it *keeps* `POOL_PHASES` as a pure `action → DOM` lookup and
   `renderPoolControls`. The file gets smaller, not rewritten.

This is **not** a pipeline rewrite (ADR-0002's decomposition stands; the steps
stay put). It extracts a *sequencing layer* that currently exists only in the
browser and points the browser at it.

### Behavior parity is the load-bearing risk → characterization test first

The JS phase logic has accreted real edge cases that must survive the port
byte-for-byte: the `hasStale` regression back to `UPLOADED` when the pool is
mutated after approval; `animal_report` presence standing in for "integration
succeeded"; platform-name aliasing (`Clinical` → `Clinical Observations`). The
port is therefore gated on a **table-driven characterization test**: enumerate
every `(artifacts) → phase` and `(coverage_matrix) → completeness` case against
current JS behavior *before* porting, then make the Python pass the identical
table. That test doubles as the safety net that lets the successor change the
workflow without fear.

**Built 2026-08-13 (ahead of the port):**
- `tests/fixtures/characterization/workflow_phase_cases.json` — the locked
  contract: 34 cases with inputs + hand-authored expected outputs, each with a
  `why`. Its `_README` documents how to *evolve* the contract (add coverage vs.
  change a requirement vs. the forbidden edit-expected-to-pass).
- `tests/tools/gen_phase_oracle.mjs` — runs the cases through the **real
  `pool_state.js`** in a `node:vm` sandbox and asserts the JS agrees with the
  hand-authored expectations, then emits the oracle. This makes the browser code
  itself validate the contract (it did, 34/34 on first run).
- `tests/unit/test_workflow_phase_characterization.py` — an always-on
  oracle-sync guard (the JS-drift tripwire) plus the port comparison, which
  *skips* until `workflow.phases` exists and auto-arms the day it does.

A characterization test pins **behavior at sampled input points**, not design: it
constrains outputs, not the port's internals (dict or dataclass both pass), and
adding coverage is append-a-case-and-regenerate. The one thing it deliberately
makes sticky is editing an *expected* value to make a red port green — the
oracle-sync guard makes that tamper-evident (the oracle is generated, so a faked
value shows as a hand-edit to a generated file).

**Source-of-truth inverts at cutover.** While the JS still exists, the oracle is
generated *from it* — correct for the port window. Once step 5 deletes
`derivePoolPhase`/the completeness fns from `pool_state.js`, the Node generator
can no longer regenerate anything, and **Python becomes the source of truth**.
That is the correct end state, but it means the Node generator must be *replaced*
at cutover by a `gen_phase_oracle.py` that regenerates the same oracle from the
Python port — otherwise a legitimate future requirement change (a new phase, a new
platform rule) can only be applied by hand-editing the frozen oracle. Tracked as a
follow-up.

**One gap this unit-level contract does *not* cover:** the ADR's one intended
behavior change — feeding `hasIntegrated` and `hasAnimalReport` *separately*
(integrated.json vs. animal_report.json) instead of the JS caller's current
conflation to `!!animal_report` — happens in the **caller wiring**, not the pure
function. The function contract is preserved; the *system* behavior shifts. That
change needs its own route/integration-level test; these cases won't catch it.

## Consequences

### Positive
- One place defines the workflow; two (or more) front-ends inherit it. "Functional
  equivalence, kept in step" becomes structural, not a maintenance promise.
- The browser UI — the interface the successor inherits — gets *smaller* and loses
  its most subtle logic to a tested Python core.
- Invariant 3 is strengthened, not bent: a single Python derivation point, and the
  transient-phase exception disappears.
- The approval guarantees (a)/(b) get a correct, single home, enforced uniformly
  across every surface instead of re-checked per UI.
- The TUI reduces to a thin driver (`word_tui.py` already is one), so the
  maintainer's personal keyboard-first workflow costs almost nothing once the core
  exists — and never diverges from the browser.

### Negative / accepted
- **A new package that depends on `pipeline/` and `document_model/`** adds to the
  cross-package coupling ADR-0013 already flagged. Accepted: the arrow points
  *from* `workflow/` *to* those layers and never back to `web_routes/`, so it is
  layering, not a cycle. Worth a guard test.
- **Temporary duplication during migration.** Until the JS is cut over, phase
  logic exists in both languages. Bounded by doing the characterization test
  first and cutting over per-step; not a standing shim.
- **The Word branch must be reconciled onto the packaged layout** before its TUI
  can drive the engine (it forked pre-ADR-0013, with flat imports and a
  `word-remote` dependency absent from the sandbox). Mechanical, but real, and
  tracked separately.

### Neutral
- `POOL_PHASES` survives, demoted to a pure presentation lookup. The web UI keeps
  its atomic renderer; only the *source* of "what's legal" moves.

## Open questions (resolve before implementation)

1. **Synchronous engine vs. shared job/progress abstraction.** `process()` is the
   10-plus-minute BMDS bottleneck. A synchronous `engine.process()` blocks its
   caller, leaving each UI to background it (the web app already runs it in an
   executor). Alternatively the engine exposes a job/progress handle both UIs
   share — more work, but the natural home for the "progress in the spinner" and
   "cancel/abort" items already on the backlog. *Leaning synchronous now; revisit
   when the per-section cache split lands, since that work reshapes `process()`
   anyway.*
2. **Disk-reading engine vs. injected session store.** Reading the session from
   disk is simplest and matches today. Injecting a store makes the core testable
   without a filesystem and admits a future non-session caller, at the cost of
   abstraction that may never pay off. *Leaning disk-reading now; extract the seam
   only if a second backend appears.*

## Follow-ups (not blocking the decision)
- Reconcile `feat/word-tui-workflow` onto the packaged layout and re-point its
  plugin at the engine.
- Build the (b) Word-edit reconciliation once the round-trip (ADR-0005) matures.
- Add an import-graph guard asserting `workflow/` never imports `web_routes/`.
- **At cutover (migration step 5), replace `tests/tools/gen_phase_oracle.mjs`
  with a `gen_phase_oracle.py` that regenerates the characterization oracle from
  the Python port.** Once `pool_state.js` no longer contains the phase logic, the
  Node generator has nothing to read; Python is the source of truth, so oracle
  regeneration (needed for legitimate future requirement changes) must run off the
  port. Until then, keep the Node generator — it is correct for the port window.
- Add a route/integration-level test for the `hasIntegrated`/`hasAnimalReport`
  de-conflation (the one intended behavior change), which the unit-level
  characterization contract deliberately does not cover.
