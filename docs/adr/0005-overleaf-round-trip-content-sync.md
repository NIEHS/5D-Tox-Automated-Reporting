# 0005 — Overleaf round-trip: human-in-the-loop content sync

- **Status:** **Partially implemented (verified 2026-08-17)** — the round-trip
  core is built and tracked: an 8-module `roundtrip/` package (anchors, region
  parse/`reconcile`, `overrides` store, git-clone reconcile) with
  `test_document_reconcile.py` + `test_document_overrides.py`, and app-wired
  endpoints `/api/repo-binding` (GET/POST), `/api/repo-status`,
  `/api/provision-report`, `/api/report-for-project`, `/api/export-overleaf-bundle`.
  (Terminology landed as the doc's own reframe: `repo-binding`, not
  `overleaf-binding`.) Still design-only per the body: the git-bridge as the LIVE
  remote (a GitHub remote is the decided mechanism), and structured app-side
  editing as a later complement. Was Proposed 2026-06-01; the amendment at the end
  is still marked Proposed (2026-06-11) but its decisions are the ones that shipped.
- **Deciders:** Dan Svoboda
- **Related:** [ADR-0001](0001-bmdproject-schema-as-load-barrier.md) (the
  integrated dataset every component reads through);
  [ADR-0003](0003-document-component-model.md) (the document-component model and
  its **sub-addressable content items with stable IDs** — the anchor grain this
  layer round-trips against); [ADR-0004](0004-bits-jats-export-surface.md) (the
  BITS/Bookshelf projection that must consume *reconciled* content so committee
  edits reach the published product); the **LaTeX/Overleaf pivot** project memory
  (Overleaf is the chosen sign-off surface); the **genomics user-owned narrative
  store** (commit `551be0a`) — the provenance pattern this ADR generalizes from
  one section to the whole report.

## Context

The application already does the hard upstream work: it ingests a study's data,
runs the analysis, builds every table and figure, drafts the narrative, and
assembles a complete, publication-formatted report from the canonical `DocNode`
tree (ADR-0003). Today that report leaves the system as a **one-way `.tex`
export**: we can *push* a bundle toward Overleaf, but we have no way to *absorb*
what a human does to it afterward.

That one-way boundary is the wrong shape for how the report actually gets
finalized:

1. **A committee finalizes the report in Overleaf.** Overleaf is their familiar
   environment and the sign-off surface; we are not going to build a WYSIWYG
   editor to replace it.
2. **After sign-off, we are not done.** The signed-off content must be projected
   to **BITS/JATS** for NCBI Bookshelf (ADR-0004) — which produces the published
   web product and the hosted PDF. NCBI owns that *rendering*; we own the
   *content*. So committee edits must live in **our content model**, not only in
   an Overleaf project, or they never reach publication.
3. **The application must stay the system of record** for data and generated
   content, iterating with Overleaf edits, **with the author in the middle** — so
   that regenerating a section from fresh data does not silently destroy a
   human's wording.

### The precedent we are generalizing

We already solved this exact problem once, narrowly. The **genomics user-owned
narrative store** (`551be0a`) made an LLM-generated narrative, once a human owns
it, **never silently recomputed** on data drift: the override is authoritative,
regeneration is explicit (a per-organ *Regenerate* button + `force` flag), and
the stored override surfaces instead of fresh machine text. This ADR is that
pattern **promoted from one section to every node in the report**, with Overleaf
as the editing surface and `git` as the transport.

### What makes this tractable (and what does not)

Syncing a *generated* artifact with a *hand-edited* one is the classic
round-trip problem, and LaTeX — a Turing-complete macro language — is the
worst-case input for it. It is tractable **only because we own the generator**:
we can emit the `.tex` as a *parseable interchange format* with stable per-node
anchors, and reconcile edits inside those anchored regions. Outside them (new
macros, restructuring, preamble edits) faithful reverse-mapping is the
WYSIWYG-LaTeX swamp, and we will not attempt it — we detect and surface such
edits rather than guess. The design therefore stands or falls on **disciplined
anchoring + a constrained editability contract**, not on a clever parser.

## Decision

**Add a bidirectional Overleaf sync layer that promotes the `.tex` from a
one-way export to a round-trip interchange format, with per-node edit
provenance.** The `DocNode` tree remains the single source of truth for
*structure and data* (invariant #2); committee edits become *per-node content
overrides* on that tree. Four parts:

### 1. Transport — Overleaf git-bridge

Treat the Overleaf project as a **git remote** (Personal Access Token auth). The
app **pushes** the generated bundle and **pulls** the committee's edits as
commits. `git` is not only the transport — its diff is the change-detection
substrate (part 3). Each push records a **generated-baseline commit**; each pull
is the **human-edited commit** to diff against that baseline.

git-bridge is available on **Overleaf Cloud premium** plans and **Server Pro
4.0+** (where it must be explicitly enabled). Tier availability is the
feasibility gate — see Open Questions. If unavailable, the layer degrades to a
**manual import/export** round-trip (documented as the degraded path, not the
optimal one).

### 2. Anchored projection — stable per-node sentinels

`latex_generator` wraps each **editable region** in sentinel **comments** keyed
to the ADR-0003 sub-addressable content-item IDs (e.g. `liver-male-narrative`):

```latex
%% rlm:begin liver-male-narrative
… generated prose …
%% rlm:end liver-male-narrative
```

Because they are LaTeX comments, the sentinels are **invisible in the compiled
PDF** (the rendered output is byte-identical), they survive ordinary editing, and
they provide a **region ↔ node map**. The preamble, `niehs.cls`, and structural
scaffolding lie *outside* any editable region.

### 3. Reconciliation — git-diff × sentinel map

On **pull**, diff the human-edited commit against the last generated-baseline
commit. For each changed hunk, locate the **enclosing sentinel region** → the
owning node. Extract that region's current text; if it differs from what we
generated, record a **user override** for that node. Attribution granularity is
the content-item (the ID grain). The engine is a bounded *diff-and-attribute*
pass, not a LaTeX parser.

### 4. Provenance / merge — generalize the genomics store

Track, per node / content-item:

```
{ generated, user_override?, edited_at, source_commit }
```

- **Override wins and is never silently recomputed** (the genomics rule).
- The UI badges the node **"edited in Overleaf."**
- **Explicit regenerate** clears the override (the genomics escape hatch).
- If fresh data *would* change a region currently under an override, the system
  **flags "underlying data changed — review,"** it does not clobber.
- **Both** the LaTeX and BITS projections render from the *reconciled* content
  (generated ∪ overrides), so a committee edit propagates to the Overleaf PDF
  **and** to the Bookshelf publication from one source.

### The three policy calls this layer pins

These define the editability contract that keeps reconciliation bounded:

- **(A) Editability scope.** v1: **prose / narrative regions are
  Overleaf-editable and round-tripped; data-derived regions (tables, computed
  numbers) are app-owned.** An edit *inside* a data region is a *data correction*,
  not a prose edit — it is detected and **surfaced as a warning, not absorbed**.
  (A sentinel comment can tell editors "edit this in the application.")
- **(B) Structural edits.** v1: **structure is app-owned.** Adding, removing, or
  reordering sections, and preamble/`cls` changes, are **not** round-tripped;
  structural drift (missing / extra / reordered sentinels) is **detected and
  surfaced as an unreconciled-structure warning** for a human, never auto-applied.
  Structure changes happen in the app (the DocNode template).
- **(C) Conflict policy.** **Override-wins + review-flag** whenever regeneration
  would change an overridden region.

## Migration shape (when implementation is approved)

Design only; no code changes here. A plausible sequence, each step independently
landable:

1. **Anchored projection.** Emit sentinels around content-item regions in
   `latex_generator`; assert the compiled PDF is byte-identical (comments are
   invisible). Landable now, independent of transport.
2. **Override / provenance store.** Generalize the genomics per-`(organ, sex)`
   store to a per-node content store keyed by content-item ID; the read path
   prefers an override over generated text.
3. **Transport.** A git-bridge client (push baseline, pull commit), PAT config,
   and baseline-commit bookkeeping.
4. **Reconciliation engine.** git-diff × sentinel map → attribute hunks → write
   overrides; plus the structural-drift detector.
5. **UI.** "Edited in Overleaf" badges; per-node regenerate (extend the genomics
   *Regenerate* control); the "data changed under an override — review" flag.
6. **Round-trip oracle.** A fixture report: push → simulate an edit in one prose
   region → pull → assert exactly that node gains an override and others do not;
   assert a simulated table edit and a structural change surface as **warnings**,
   not silent absorption (ADR-0002 golden-discipline spirit).

## Consequences

### Positive

- **One source of truth from raw data to the Bookshelf page**, with committee
  edits captured, attributed, and carried through to **both** the PDF and BITS.
- **Reuses `git`** (transport *and* change detection) and the **genomics
  provenance pattern** — minimal net-new machinery for a large capability.
- **`.tex` becomes interchange, consistent with invariant #2:** edits become
  per-node overrides; structure stays tree-owned.
- **No custom editor to build** — the committee stays in Overleaf, their trusted
  surface.
- **Closes the "regeneration silently clobbers human work" risk** for the whole
  report, not just genomics narratives.

### Negative / risks

- **The round-trip ceiling is real and must be honest.** Reliable only inside
  anchored prose regions; free-form edits (new macros, restructuring, anything
  outside the sentinels) degrade to *unreconciled-diff-for-a-human*. We surface,
  we do not guess.
- **Depends on ADR-0003 IDs being stable and complete.** An unanchored region
  cannot round-trip; coverage of editable content by content-item IDs is a
  prerequisite.
- **Sentinel discipline.** An editor who deletes or relocates a sentinel comment
  breaks attribution for that region — mitigated by detecting missing/!moved
  sentinels and warning, but it is a sharp edge.
- **Tier dependency.** git-bridge requires Overleaf premium / Server Pro 4.0+;
  the optimal loop is unavailable on free Cloud / Community Edition.
- **Two-writer hazard.** If the app regenerates *and* a human edits between sync
  points, correct attribution depends on faithful **baseline bookkeeping** (the
  last-pushed commit). Mis-tracking the baseline mis-attributes edits.
- **Data edits are intentionally not absorbed.** A committee member who "fixes" a
  number directly in an Overleaf table will see it flagged/reverted on the next
  sync — this needs clear UX messaging so it is not surprising, and a v2 path
  (capture it as a *data-correction proposal*) is worth considering.

## Alternatives considered

- **Build a WYSIWYG / in-app editor instead of using Overleaf** *(rejected).*
  Reinvents an editor, discards the surface the committee already trusts, and
  removes Overleaf as the sign-off venue.

- **Keep one-way export; edits live in Overleaf forever** *(rejected).* The app
  stops being the system of record, edits never reach BITS/Bookshelf, and
  regeneration either clobbers or permanently diverges from the human copy.

- **Round-trip arbitrary LaTeX with a full parser** *(rejected).* LaTeX is
  Turing-complete; faithfully reverse-mapping free-form edits is the
  WYSIWYG-LaTeX swamp. The sentinel-anchored prose-region approach captures the
  tractable 90% and is honest about the rest.

- **Edit a structured form (JSON/markdown) in the app, treat Overleaf as
  read-only** *(rejected for v1).* The committee wants to edit *in Overleaf*
  directly. App-side structured editing remains a possible complement later, not
  the primary loop.

- **Manual import/export (zip up / zip down) as the sync** *(fallback only).*
  The degraded path if git-bridge is unavailable on the client's tier; recorded
  so the workflow fails gracefully rather than breaking.

## Open questions

- **Overleaf tier / git-bridge availability** — the feasibility gate. Confirm
  Cloud premium vs Server Pro 4.0+ (git-bridge enabled) vs an unsupported tier.
- **Sentinel format robust to editor reflow** — comment syntax that survives
  reformatting and is hard to clobber accidentally.
- **Project lifecycle** — one Overleaf project per report recreated each push, or
  a persistent project updated in place? This drives the commit-baseline
  bookkeeping in part 3.
- **v2: capture data/table edits as data-correction proposals** rather than
  discarding them — closing the loop on policy (A) without re-keying.

---

## Amendment 1 (2026-06-03): topology, turn-taking, and the library boundary

Implementation + a series of design conversations settled three things the
original draft left open or got slightly wrong. This amendment supersedes the
matching parts above.

### A. Transport topology — git-bridge is the live surface; GitHub is an archive

The original draft treated GitHub as a possible hub. The decided topology
instead makes the app talk to Overleaf **directly** via git-bridge, with GitHub
as a passive backup — two remotes on one local clone:

```
                         git-bridge (live, master-only)
   App ── local clone ──⇄  Overleaf            (the editing surface)
              │
              └── push mirror ──▶  GitHub repo  (archive, full history, multi-branch)
```

- **git-bridge** exposes each Overleaf project as a **single-branch (`master`)**
  git remote at `https://git.overleaf.com/<project-id>` — the same id as the web
  URL `…/project/<id>`, so the git URL is *derivable* from the project URL we
  already store in the binding. Pushing to it updates the Overleaf editor
  directly (no human sync step). **Overleaf cannot show multiple branches**, so
  any branch/version structure lives on the GitHub side, not in Overleaf.
- **GitHub** is repurposed from "hub" to **passive, write-only archive**: the app
  mirrors the clone there after every operation. It is *out of the round-trip
  loop* (never read back; Overleaf is the only source of committee edits), so it
  adds no manual sync hop. It gives durable backup, full attributed provenance
  (richer than git-bridge's coarse per-sync history), and a real multi-branch
  home for per-turn tags.

### B. The three roles — and why Overleaf is a buffer, not a cache

- **System of record:** the app's content model (integrated data + per-node
  overrides).
- **Durable archive:** the GitHub mirror.
- **Live exchange buffer:** the Overleaf project (via git-bridge). It is
  *mostly* a disposable, reconstructible projection — **except** it transiently
  holds the **only** copy of committee edits (born in Overleaf, not yet pulled).
  So it is a write-buffer that is authoritative *in transit*, not a cache.
  **Operational consequence (load-bearing rule): always pull + reconcile before
  overwriting Overleaf** (placeholder swap, new version, anything) or the one
  copy of un-pulled edits is lost.

### C. Turn-taking by placeholder swap — the committee never touches the app

Hard constraints on Overleaf Cloud: **no API or git-bridge signal for presence
or locking**, and **no way to set the editor read-only programmatically**. And
the committee works *only* in Overleaf — they never use the app. Therefore the
original click-to-acquire lock does not fit (they can't participate), and a
code-only mutex over their typing is impossible.

Decided model: a per-report **turn flag** (`APP` / `COMMITTEE`) whose transition
is a **document swap on `master`**:

- **→ APP** (take a turn): pull + reconcile committee edits → push a
  **placeholder/banner** document ("the automated system is preparing this
  report; nothing to edit"). The real report is now staged only in the app's
  local clone, so **there is effectively nothing to edit in Overleaf** — stray
  keystrokes hit a throwaway placeholder. The app does its work locally.
- **→ COMMITTEE** (hand off): push the finished editable document → the committee
  reviews/edits in Overleaf.

Enforcement, honestly stated:
- **App side is fully enforced in code:** the app refuses to push while the flag
  is `COMMITTEE`.
- **Committee side is the strongest *automated* approximation, not a hard lock:**
  during the app's turn the report content isn't in Overleaf at all (placeholder
  only), and **reconcile-before-overwrite** makes any out-of-turn edit
  non-destructive (captured as an override, or surfaced as a conflict). A true
  hard lock requires the **manual Editor→Viewer share toggle** in Overleaf — the
  only thing that makes the editor reject keystrokes — offered as "hard mode."

This supersedes the per-user checkout lock (`edit_lock`), which assumed app-side
editors; that module becomes the turn-flag store.

### D. The behaviors are a domain-agnostic library — `roundtrip`

The round-trip is **independent of LaTeX, Overleaf, and reports**: it is
"sync a machine-generated document that humans edit in a git-backed editor."
The mechanics are extracted into an **in-repo package, `roundtrip/`**, with a
hard rule: **nothing in it imports app code** (no `latex_*`, `report_data`,
`document_tree`, no knowledge of `sessions/`, `report.tex`, or DocNode).

| `roundtrip/` (generic) | App (rlm-bmdx) supplies |
|---|---|
| `anchors` — sentinel convention (`wrap`, `BEGIN_RE`/`END_RE`), comment-syntax-parameterizable | the generator that emits anchored text (`latex_generator`, calling `anchors.wrap`) |
| `reconcile` — parse regions, diff baseline↔edited, innermost-wins attribution + structural drift | how overrides are *applied* at render time (the renderer prefers an override) |
| `overrides` — per-region store + `region_hash` stale detection | binding config (which remotes), placeholder/banner content |
| `transport` — clone + live remote (+ archive remote), push/pull/mirror, local stand-in | session/cache layout, the bundle composition |
| `lock` — turn flag | |

The one coupling made explicit: **`roundtrip.anchors` owns the sentinel format**,
imported by the app's generator, so writer and reader can't drift.

**Timing decision: extract the boundary now, package later.** Move the modules
behind the `roundtrip/` package now (no app imports, no behavior change) — that
gets the design benefit and forces an honest interface. Lift it to a standalone
installable repo *only* once the turn-taking/placeholder/archive design is built
and stable **and** a second consumer (or open-sourcing) appears — extracting a
versioned package mid-design would just churn its API. The in-repo default
storage location (`<repo>/sessions`) is the one remaining soft seam; it is an
injectable default (`sessions_dir=`), not an app import.

### Implementation status (2026-06-03)

**Built and committed (against the local stand-in and the real GitHub remote):**
anchored projection (`%% rlm:` sentinels, PDF byte-identical); override store +
renderer overlay; reconciler (diff × sentinel → overrides); local git stand-in
+ real-remote `push_document`; report↔project binding; the Report-tab Overleaf
hand-off UI (no in-app preview; "Open in Overleaf" + link-a-project) with the
checkout lock; the `main.tex`/`report.tex` Option-B split.

**Designed here, not yet built:** git-bridge as the live remote (vs the GitHub
remote currently bound); the **GitHub archive** second remote + per-turn tags;
the **turn-taking placeholder-swap** protocol (the `edit_lock` → turn-flag
reframe); the app-wired **Send / Fetch** endpoints (push, and pull+reconcile)
with the lock check and reconcile-before-overwrite; auto-derivation of the
git-bridge URL from the project URL.

**This amendment's structural step (now):** extract the built modules into the
`roundtrip/` package (no behavior change).

---

## Amendment 1a (2026-06-03): provisioning + the operator runbook

Concrete settlement of Amendment 1 for the git-bridge transport.

### Identity & provisioning (one human paste, ever)
- **GitHub working/archive repo:** name derived from the test-article id by
  convention (e.g. `…-<DTXSID>`) — fully automatic; the Overleaf project *title*
  is set to the same string.
- **Overleaf project id is opaque and NOT derivable** — Overleaf has no
  title-based URL and no Cloud API to resolve title→id. So provisioning is:
  app creates the convention-named GitHub repo + pushes the initial bundle →
  **human imports that repo into Overleaf once** (New Project → Import from
  GitHub) → **human pastes the resulting `overleaf.com/project/<id>` back into
  the app once.** From that id the app derives BOTH the web URL ("Open in
  Overleaf") and the git-bridge endpoint `git.overleaf.com/<id>` — so the two
  can never drift (the failure mode that bit us when project_url and git_remote
  were set independently).

### Two remotes, two roles (on one local clone)
- **Overleaf via git-bridge** — the live waypoint. **Single-branch (`master`).**
  Holds exactly one flat state at a time: the banner (app's turn) or the
  editable report (committee's turn).
- **GitHub** — the app user's working repo (branches, multiple commits) AND the
  full-history archive. The committee never touches it.

### Turn-taking runbook (the operator sequence)
1. **Take turn:** pull + reconcile any committee edits (mandatory — drain
   before clobber), then push the **"🔒 Locked by Administrator"** banner to the
   Overleaf project. The real report is now staged only on GitHub/local, so
   there is nothing real to edit in Overleaf.
2. **Work:** commit/branch freely on GitHub; regenerate; etc. Overleaf shows the
   banner throughout. Overleaf and GitHub intentionally diverge here.
3. **Hand off:** push the finished editable document to BOTH the Overleaf
   project (git-bridge, replacing the banner) AND GitHub (archive). They
   converge.
4. **Committee edits** in Overleaf (`master` only).
5. **Next cycle:** back to step 1 — pull their edits from Overleaf, reconcile,
   then banner.

### Mutual exclusion — what's enforced vs cooperative
- **Committee-editing-during-app's-turn: enforced** by the banner (nothing real
  to edit).
- **App-taking-turn-during-committee-editing: NOT code-enforceable** — Overleaf
  exposes no presence/locking signal. Guards: (a) out-of-band turn convention,
  (b) reconcile-before-banner makes a mistimed take-turn *non-destructive*
  (worst case: a surprised editor, not lost work), (c) the manual Editor→Viewer
  share toggle as the only hard lock.

### Credentials
git-bridge auth = an Overleaf git token (account-scoped on Cloud), supplied to
the server as `OVERLEAF_GIT_TOKEN`, never in code. GitHub archive auth = the
existing git credential helper.

---

## Amendment 2 (2026-06-09): GitHub-in-the-middle is the live transport

**This amendment reverses the central topology call of Amendment 1A.** Am.1A
made git-bridge the live surface and GitHub a passive, write-only archive *out
of the loop*. The implemented and decided design is the opposite: **GitHub is
the hub the app reads and writes, and Overleaf reaches the content only through
its own GitHub integration.** git-bridge is demoted to an optional fallback the
binding *can* hold but does not.

### The decided topology

```
   App ── local clone ──⇄  GitHub repo  ──⇄  Overleaf
            (push/pull,        (the hub:        (GitHub sync:
             via git creds)     branches +       human-driven
                                full history)    pull/push in
                                                 the Overleaf menu)
```

The app's only network peer is the **GitHub repo**
(`github.com/<owner>/<DTXSID>-5D-Tox`, originated/adopted by
`github_provision.ensure_repo`). Overleaf is linked to that same repo via
Overleaf's built-in **GitHub sync**; the committee's edits travel
Overleaf → GitHub → app, and generated updates travel app → GitHub → Overleaf.

### Why we reversed Am.1A

- **Tier independence — the feasibility gate, settled the cheap way.** git-bridge
  is premium-Cloud / Server-Pro-4.0+-gated (Open Question #1). The
  GitHub-import + GitHub-sync path needs **no special Overleaf tier** and no
  `OVERLEAF_GIT_TOKEN` provisioning dance — it works on the account we already
  have. Am.1A's "if unavailable, degrade to manual import/export" is, in
  practice, the path that is *always* available, so we made it the primary one.
- **One remote, not two.** Am.1A needed a *separate* archive remote to get
  branches, full attributed history, and per-turn tags, because git-bridge is
  single-branch and coarse-grained. With GitHub as the hub, those properties are
  **native to the one remote we already talk to** — the "hub" and the "archive"
  collapse into a single repo. Less to provision, nothing to keep mirrored in
  lockstep.
- **One credential.** Auth is the existing **git credential helper** for GitHub
  (already present for every other repo op). `OVERLEAF_GIT_TOKEN` moves to the
  dormant git-bridge fallback only.

### The cost we re-accept: a human sync hop on the Overleaf side

git-bridge's one real advantage was that an app push **updated the Overleaf
editor directly, with no human step**. Overleaf's GitHub sync is **menu-driven**
(a person clicks *Menu → GitHub → pull* to ingest app updates, and *→ push* to
send committee edits back to GitHub). So every turn boundary now includes a
human clicking sync in Overleaf. We accept this: the committee is already
in-Overleaf and human-in-the-loop by design (Am.1 §C), the turns are coarse
(not keystroke-live), and tier-independence is worth one click per handoff.

### How this changes the Amendment 1A constraints

- **"GitHub is out of the round-trip loop, never read back" (Am.1 §A/§B) — void.**
  GitHub is now squarely *in* the loop and is read back on every Fetch: it is the
  channel committee edits arrive through. It is no longer a write-only mirror.
- **Single-writer-into-Overleaf — still required, contended object moves.** The
  turn-taking placeholder swap (Am.1 §C) is unchanged in spirit, but the single
  flat state now lives on the **GitHub branch Overleaf's sync tracks** (one
  branch), not on a git.overleaf `master`. The app's other branches simply
  aren't the tracked branch, so Am.1A's "Overleaf cannot show multiple branches"
  worry is satisfied *for free* — Overleaf follows one branch and ignores the
  rest.
- **Reconcile-before-overwrite — still load-bearing, danger window grows by one
  hop.** The only copy of un-pulled committee edits now sits in the **Overleaf
  project until a human clicks GitHub-push**; the app's Fetch only sees edits
  that have already reached GitHub. So "always pull + reconcile before
  overwriting" (Am.1 §B) now also depends on the committee having synced their
  edits up. The `remote_head` vs `baseline_commit` staleness guard
  (`transport.py`) enforces the app side: Send refuses if GitHub's tip has moved
  past the recorded baseline — i.e. if edits arrived we haven't reconciled.

### What this did *not* touch — the library boundary paid off

Because the round-trip mechanics were extracted into the transport-agnostic
`roundtrip/` package (Am.1 §D), swapping the live remote from git-bridge to
GitHub changed **only the binding's `git_remote` URL and the provisioning
module** — exactly as `transport.py`'s header promised ("only the remote URL
changes; nothing else here moves"). The anchored projection, the reconciler, the
override store, and the turn flag are all unchanged: they operate on a git remote
without caring whether it is git.overleaf or github.com.

### Code state confirming this amendment

- The live binding (`sessions/<dtxsid>/_overleaf_binding.json`) carries
  `git_remote: https://github.com/daniel-sciome/DTXSID50469320-5D-Tox` — a GitHub
  URL, not `git.overleaf.com`.
- `transport.py` documents the remote as "**the GitHub repo Overleaf syncs
  with**, or a git-bridge URL."
- `github_provision.py` exists solely to originate/adopt that hub repo and
  returns the URL stored as `git_remote`.

### Credentials (superseding the Am.1A note)

Primary transport auth = the **GitHub credential helper** (already configured).
`OVERLEAF_GIT_TOKEN` is required **only** if the dormant git-bridge fallback is
ever activated for a given report.

## Amendment 3 (2026-06-11): the app speaks git, not Overleaf — single source, deferred push

**This amendment makes two corrections that Amendment 2 implied but did not
finish.** Am.2 moved the live transport to GitHub but left the *outbound* path
carrying two regressions from the older design: (a) the push rendered from a
**different data source** than the in-app view, so "what you see" was not "what
you push"; and (b) the operational vocabulary still said *Overleaf* even though
the app, post-Am.2, has **no Overleaf peer at all** — its only network peer is a
git remote. This amendment settles both, plus the turn model (commit and push
are now separate) and the single-user simplification.

### A. The app's entire surface is a git repo — Overleaf is invisible to it

After Am.2 the app makes **only `git` subprocess calls** (`clone`/`add`/`commit`/
`push`/`fetch`/`pull`) against `binding.git_remote`. There is no Overleaf API,
no `overleaf.com` request, nothing the app can *do* to Overleaf. Overleaf is a
**downstream consumer the human wires up once** (Overleaf's own GitHub-sync),
and the rendering + editing surface for the committee — entirely outside the
app's reach.

Therefore the app's operational vocabulary must be **repo-centric**, not
Overleaf-centric. Overleaf survives only in *human-facing prose* ("the repo your
Overleaf project syncs from"), never in a button label, route name, variable,
or filename. Concretely:

| Old (Overleaf-framed) | New (repo-framed) |
|---|---|
| "Send to Overleaf" button / `/api/send-to-overleaf` | **"Commit Local"** + **"Push to GitHub"** (split — see §C) |
| "Fetch from Overleaf" / `/api/fetch-from-overleaf` | **"Pull from GitHub"** / `/api/pull-from-github` |
| "Open in Overleaf" button + `openInOverleaf()` + checkout lock | **removed** (see §D) |
| "Export to Overleaf (.zip)" | **"Export Bundle (.zip)"** (kept — offline/first-time escape hatch) |
| `/api/overleaf-binding`, `_overleaf_binding.json`, `binding.project_url` | `/api/repo-binding`, `_repo_binding.json`, **`project_url` dropped** (only `git_remote` remains) |

The binding-file rename carries a **back-compat read**: load `_repo_binding.json`
if present, else fall back to the legacy `_overleaf_binding.json`, and write the
new name going forward. Existing sessions keep working without a migration step.
The `roundtrip/` package keeps its name (it is the round-trip *mechanism*, which
is real and unchanged) but its docstrings drop "the send to Overleaf" glosses.

### B. One source of truth for the outbound render: the in-app working copy

The bug this amendment exists to kill: the **HTML working copy** (what the user
sees in the app) and the **pushed LaTeX** were rendered from two different
inputs, so they silently diverged.

- HTML working copy + "Export Bundle" rendered from the **browser's in-memory
  store**, posted in the request body → `marshal_export_data(body)`.
- The push rendered from **on-disk session caches**, re-read fresh →
  `sync_document()` → `load_session_data(dtxsid)`.

When the store and the disk caches drift, the push is wrong while the view looks
right. This is **not section-specific** — it was first observed in the genomics
gene-set tables (the on-disk genomics cache had empty `gene_sets`; the store had
them) and in Materials & Methods, but it is structural: *any* section can drift.
It is one seam producing N symptoms.

**Decision: the push renders from the same working copy the view renders from.**
The repo-push route accepts the posted body and runs
`marshal_export_data(body) → generate_latex → write bundle → git commit` —
byte-identical to the Export-Bundle path, just followed by a commit. **`load_session_data`
is retired from the push path entirely.** With one input, "what you see is what
you commit" holds *by construction*, not by the two renderers happening to agree.

This makes the outbound push **browser-originated by design**. That is
acceptable and intended: scripted/headless pushing existed only for testing, and
real usage is always the single human at the browser. `load_session_data` remains
available for any offline CLI/testing render, but it is no longer on the live
path.

### C. Commit and push are separate turns (deferred push)

`push_document()` already performed *mirror → add → commit → push* in sequence;
this amendment **splits that seam** and surfaces both halves:

- **"Commit Local"** = mirror the working copy into the local clone → `add` →
  `commit`. **No network.** Local commits accumulate on the clone.
- **"Push to GitHub"** = `push` the accumulated local commits to `git_remote`.

The **local repo is the existing clone** (`.overleaf-clone/<dtxsid>` — to be
renamed `.repo-clone/<dtxsid>` under §A's hygiene pass), which is already a real
git working tree bound to the remote. `documents/<dtxsid>/` is **not** made a
repo: it is already tracked by the main rlm-bmdx project repo and a nested repo
there would collide.

**`baseline_commit` semantics are unchanged and pin to the last *pushed* sha**
(what Overleaf imported). Commit Local **must not** touch `baseline_commit`; only
Push to GitHub advances it. The **reconcile-before-overwrite staleness guard
(Am.2) moves to the Push button** — Push refuses with 409 if `remote_head` has
advanced past `baseline_commit` (committee edits arrived un-reconciled), directing
the user to Pull from GitHub first. Commit Local needs no guard; it is purely
local.

### D. Single-user: the checkout lock is removed

The app is **single-user**; all multi-author editing happens in **Overleaf**,
which has its own concurrency model. The single-writer **checkout lock** (Am.1
§C, acquired by the now-deleted "Open in Overleaf") guarded against two *app*
users clobbering each other — a contention that no longer exists. It is removed
along with `openInOverleaf()` and the lock banner. (`roundtrip/lock.py` may be
retired or left dormant; no live path calls it.)

### E. Provision is init-only

`/api/provision-report` today also runs `sync_document` + push. Under this
amendment it **only creates/adopts the repo and sets `git_remote`** — repo
origination, nothing else. The first content reaches the repo through the normal
**Commit Local → Push to GitHub** turn, identical to every later turn. There is
no special first-push path.

### F. UI status is derived, never set (ADR-0005 × the UI-state invariant)

The button-enable states fall directly out of the clone's git status, so the
phase is *derived* (consistent with the project's "phase is derived, never
imperatively set" rule):

| Derived state | Computed from | Action offered |
|---|---|---|
| Working copy has uncommitted changes | rendered body ≠ clone `HEAD` tree | **Commit Local** |
| Local commits not yet pushed | `git rev-list --count @{u}..HEAD` > 0 | **Push to GitHub** |
| In sync with origin | ahead = 0 and behind = 0 | — |
| Origin moved past baseline | `remote_head` ≠ `baseline_commit` | **Pull from GitHub** (then reconcile) |

### What this does *not* touch

The **round-trip itself survives unchanged** — it was always repo-based. The
human still edits in Overleaf; Overleaf still pushes to GitHub; the app still
pulls from GitHub and reconciles committee edits against `baseline_commit` via
the anchored projection + override store (Am.1 §B–C, Am.2). This amendment
renames the *outbound* operations to match what the app actually talks to and
collapses the outbound render to a single source; it leaves the *inbound*
reconcile mechanics, the anchor grain, and the override store exactly where Am.2
left them.

### Status of this amendment

**Proposed (2026-06-11)** — decisions locked (single-user → no lock; keep Export
Bundle; do the `_repo_binding.json` rename with back-compat). Implementation
pending: split `push_document`, repoint the push route at `marshal_export_data(body)`,
the vocabulary/rename sweep across `web/`, `export_routes.py`, `roundtrip/`, and
`*_binding.json`, removal of the lock + "Open in Overleaf", and the
provision-is-init-only trim.
