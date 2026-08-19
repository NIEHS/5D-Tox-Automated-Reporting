"""
Author notebooks/workflow_walkthrough.ipynb programmatically.

One cell per pool-workflow step, driving the UI-agnostic workflow engine
(ADR-0014) in-process — the notebook is an alternative front-end to the same
core the web UI drives. Each mutation cell ends by re-printing the DERIVED
WorkflowEngine.state() (phase + legal actions), so cells are idempotent and the
phase machine is visible at every step.

Run this builder from the worktree root with the venv python:
    .venv/bin/python notebooks/_build_workflow_notebook.py
"""

from __future__ import annotations

from pathlib import Path

import nbformat as nbf
from nbformat.v4 import new_notebook, new_markdown_cell, new_code_cell

nb = new_notebook()
cells: list = []


def md(text: str) -> None:
    cells.append(new_markdown_cell(text.strip("\n")))


def code(src: str) -> None:
    cells.append(new_code_cell(src.strip("\n")))


# ---------------------------------------------------------------------------
md(r"""
# Pool workflow walkthrough — a notebook front-end

This notebook is an **alternative user interface** to the rlm-bmdx pool workflow.
Each cell is a single step in the data **import → prepare → process** pipeline.

It drives the same UI-agnostic core the browser drives (ADR-0014):

- **`workflow.steps`** — the pure step functions (`validate_step`,
  `integrate_step`, …), lifted out of the FastAPI handlers.
- **`workflow.store.DiskPoolStore`** — the injectable state seam (disk is
  canonical).
- **`workflow.engine.WorkflowEngine`** — re-derives `{phase, legal_actions}`
  from the artifacts on disk. **The phase is never stored** (CONTEXT.md
  invariant 3); it is a *function of what files exist*. That is why every
  mutation cell below ends by re-printing the derived state — you watch the
  phase advance as a consequence of the artifacts each step produces.

The workflow phases: `EMPTY → UPLOADED → VALIDATED → INTEGRATED → APPROVED`
(with a `VALIDATION_ERRORS` branch).
""")

# ---------------------------------------------------------------------------
md(r"""
## Cell 0 — Environment

The live pipeline needs three things in the sandbox environment (each fixes a
distinct, verified failure):

1. **JDK 21 first on `PATH`** — the Java helper classes are compiled to class
   version 65; the default `/usr/bin/java` is Java 17 and integrate dies with
   `UnsupportedClassVersionError`.
2. **`BMDX_PROJECT_ROOT`** — points the Java bridge at the in-sandbox
   BMDExpress-3 jar (the default is a dead host path).
3. **`SSL_CERT_FILE`** — the NIEHS LiteLLM proxy uses a self-signed NIH CA;
   without this bundle the LLM-narrative calls fail TLS verification. (Integrate
   degrades gracefully without it; the processing step needs it for full
   narratives.)

Set here so the notebook is self-contained.
""")

code(r"""
import os
from pathlib import Path

# (1) JDK 21 must be FIRST on PATH — JAVA_HOME alone is not enough, the bridge
#     invokes the bare name "java".
os.environ["JAVA_HOME"] = "/opt/liberica-jdk-21"
os.environ["PATH"] = "/opt/liberica-jdk-21/bin:" + os.environ.get("PATH", "")

# (2) In-sandbox BMDExpress-3 jar location.
os.environ["BMDX_PROJECT_ROOT"] = "/workspace/BMDExpress-3"

# (3) NIH CA bundle for the LiteLLM proxy (LLM narratives).
_ca = "/etc/ssl/certs/nih-ca-bundle.pem"
if Path(_ca).exists():
    os.environ["SSL_CERT_FILE"] = _ca
    os.environ["REQUESTS_CA_BUNDLE"] = _ca

# Run from the worktree root so first-party packages import (cwd-on-sys.path).
_root = Path.cwd()
if _root.name == "notebooks":
    _root = _root.parent
    os.chdir(_root)
print("cwd            :", Path.cwd())

import subprocess
print("java on PATH   :", subprocess.run(["java", "-version"], capture_output=True, text=True).stderr.splitlines()[0])
print("BMDX_PROJECT   :", os.environ["BMDX_PROJECT_ROOT"])
print("SSL_CERT_FILE  :", os.environ.get("SSL_CERT_FILE", "(unset — LLM narratives will degrade)"))
""")

# ---------------------------------------------------------------------------
md(r"""
## Cell 1 — Import: seed a fresh session from input files

"Import" = landing raw study files in `sessions/<DTXSID>/files/`. The workflow
engine derives `EMPTY` when there are no files and `UPLOADED` once files exist
but nothing has been validated.

We seed a throwaway session by copying **only the input files** (the `.bm2`,
`.txt`/`.csv`, and `.sidecar.json` files) from the reference session — never its
derived artifacts (`validation_report.json`, `integrated.json`, …). Deriving
those from scratch is the whole point.

**Re-running this notebook (warm vs cold):** this cell is *non-destructive* by
default. If the demo session already exists (from a previous run), it is **left
intact** — so `Run All` re-uses the cached `integrated.json` + `_cache_*` and the
integrate/process cells finish in seconds instead of ~10 minutes. To force a
clean end-to-end run from raw files, set `RESEED = True` below (or just delete
`sessions/DTXSID_NB_DEMO/`).
""")

code(r"""
import shutil
from workflow.engine import WorkflowEngine
from workflow.store import DiskPoolStore

DTXSID = "DTXSID_NB_DEMO"          # throwaway demo session
SOURCE = "DTXSID50469320"          # reference session to copy inputs from
RESEED = False                     # True = wipe + re-import (forces a full cold run)

store = DiskPoolStore()

def show_state(dtxsid=DTXSID):
    # Re-derive and print the workflow state from disk (phase is never stored).
    s = WorkflowEngine(dtxsid, store).state()
    print(f"  phase          = {s.phase.value}")
    print(f"  legal_actions  = {sorted(a.value for a in s.legal_actions)}")
    print(f"  artifacts      = {s.artifacts}")
    return s

src_files = Path("sessions") / SOURCE / "files"
session   = Path("sessions") / DTXSID
dst_files = session / "files"

if RESEED and session.exists():
    shutil.rmtree(session)                   # explicit cold start: drop derived artifacts too
    print(f"RESEED: wiped sessions/{DTXSID}/\n")

if dst_files.exists() and any(dst_files.iterdir()):
    # Warm start — session already imported. Leave derived artifacts in place so
    # downstream cells cache-hit instead of recomputing.
    n = sum(1 for _ in dst_files.iterdir())
    print(f"session already present — reusing {n} imported files (set RESEED=True for a clean run)\n")
else:
    # Cold start — import only the input files into a fresh session.
    dst_files.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in sorted(src_files.iterdir()):
        shutil.copy2(f, dst_files / f.name)
        n += 1
    print(f"imported {n} input files into sessions/{DTXSID}/files/\n")

print("Derived state after import:")
show_state()
""")

# ---------------------------------------------------------------------------
md(r"""
## Cell 2 — Validate

`validate_step` re-fingerprints every file in the pool and runs full
cross-validation (platform coverage, tier consistency, dose-group agreement),
writing `validation_report.json`.

The presence of that report (with no error-severity issues) advances the derived
phase `UPLOADED → VALIDATED`. If it contained errors, the phase would derive as
`VALIDATION_ERRORS` and `INTEGRATE` would not be a legal action.
""")

code(r"""
from workflow.steps import validate_step

report = validate_step(DTXSID, store)

errors = sum(1 for i in report.get("issues", []) if (i or {}).get("severity") == "error")
warns  = sum(1 for i in report.get("issues", []) if (i or {}).get("severity") == "warning")
print(f"validated {report.get('file_count')} files")
print(f"  is_complete = {report.get('is_complete')}")
print(f"  issues      = {len(report.get('issues', []))}  ({errors} error, {warns} warning)")
print(f"  platforms   = {sorted(report.get('coverage_matrix', {}).keys())}\n")

print("Derived state after validate:")
show_state()
""")

# ---------------------------------------------------------------------------
md(r"""
## Cell 3 — Resolve conflicts (precedence)

When validation finds the *same* platform covered by multiple files, the user
picks which file wins. Each decision is one `resolve_step` call, appended to
`precedence.json`.

This demo pool has no unresolved conflicts, so we show the mechanism without
forcing a decision. `resolve_step` does not change the derived phase — it only
records precedence that `integrate_step` will consult.
""")

code(r"""
from workflow.steps import resolve_step

report = store.read_json(DTXSID, "validation_report.json") or {}
conflicts = [i for i in report.get("issues", []) if "conflict" in (i or {}).get("kind", "").lower()]

if conflicts:
    print(f"{len(conflicts)} conflict(s) found — resolving each by choosing the first candidate:")
    for idx, issue in enumerate(conflicts):
        candidates = issue.get("file_ids") or issue.get("candidates") or []
        if candidates:
            resolve_step(DTXSID, idx, candidates[0], store)
            print(f"  issue {idx}: chose {candidates[0]}")
else:
    print("no precedence conflicts to resolve in this pool — nothing to do")

print("\nprecedence.json:", store.read_json(DTXSID, "precedence.json"))
""")

# ---------------------------------------------------------------------------
md(r"""
## Cell 4 — Confirm metadata

The user confirms/corrects each file's `(platform, data_type)` — corrections are
written back into the fingerprints and prepended as `# Provider/# Platform/
# Data Type` headers on `.txt`/`.csv` files (Java's `ExperimentDescriptionParser`
reads them at import time).

We pass an empty correction map here (the fingerprints already carry the right
metadata for this reference pool); the cell shows the step is a no-op when
there is nothing to correct.
""")

code(r"""
from workflow.steps import confirm_metadata_step

# {file_id: {"platform": ..., "data_type": ...}} — empty ⇒ accept as-is.
corrections = {}
result = confirm_metadata_step(DTXSID, corrections, store)
print("confirm-metadata:", result)
""")

# ---------------------------------------------------------------------------
md(r"""
## Cell 5 — Integrate (Java-backed)

`integrate_step` merges the whole pool into one unified `BMDProject`
(`integrated.json`) — this is the **single source of truth** every downstream
report reads. It shells out to the BMDExpress-3 Java library (needs JDK 21 +
`BMDX_PROJECT_ROOT` from Cell 0) and takes a minute or two.

The presence of `integrated.json` advances the derived phase
`VALIDATED → INTEGRATED`, which makes `APPROVE` and `REPROCESS` legal.

**Warm-run skip:** integrating *invalidates every `_cache_*` process result* (a
new integration means the inputs changed, so cached section/BMDS/genomics blobs
are stale). To keep `Run All` fast on an already-integrated session, this cell
**skips** when `integrated.json` already exists — leaving the process caches
intact so Cell 7 cache-hits in seconds. Set `RESEED = True` in Cell 1 (or the
per-cell `REINTEGRATE` below) to force a real re-integration.
""")

code(r"""
from workflow.steps import integrate_step

identity = {
    "name": "Perfluorohexanesulfonamide",
    "casrn": "41997-13-1",
    "dtxsid": DTXSID,
}

REINTEGRATE = RESEED  # force a fresh integrate (wipes process caches). Follows Cell 1's RESEED.

if store.artifact_exists(DTXSID, "integrated.json") and not REINTEGRATE:
    print("already integrated — skipping (preserves _cache_* so Cell 7 stays fast)")
    print("set REINTEGRATE=True (or RESEED=True in Cell 1) to force re-integration.\n")
else:
    print("running Java integration (this takes a minute or two)…\n")
    summary = integrate_step(DTXSID, identity, store)
    print(f"integrated OK")
    print(f"  experiment_count      = {summary.get('experiment_count')}")
    print(f"  bmd_result_count      = {summary.get('bmd_result_count')}")
    print(f"  category_analysis     = {summary.get('category_analysis_count')}")
    for exp in summary.get("experiments", [])[:8]:
        print(f"    - {exp['name']}  (probes: {exp['probe_count']})")
    print()

print("Derived state after integrate:")
show_state()
""")

# ---------------------------------------------------------------------------
md(r"""
## Cell 6 — Approve (generate the animal report)

Approval produces the per-animal traceability report
(`generate_animal_report_step` → `animal_report.json`): every animal mapped to
its dose, sex, and selection (core vs biosampling), cross-referenced across
tiers and platforms.

The presence of `animal_report.json` advances the derived phase
`INTEGRATED → APPROVED` — the terminal settled phase for the data-preparation
arc.
""")

code(r"""
from workflow.steps import generate_animal_report_step

animal_report = generate_animal_report_step(DTXSID, store)

print("animal report generated")
print(f"  total_animals     = {animal_report.get('total_animals')}")
print(f"  core / biosampling = {animal_report.get('core_count')} / {animal_report.get('biosampling_count')}")
print(f"  dose_groups       = {animal_report.get('dose_groups')}")
print(f"  domain_coverage   = {animal_report.get('domain_coverage')}")
print(f"  attrition         = {animal_report.get('attrition')}\n")

print("Derived state after approve:")
show_state()
""")

# ---------------------------------------------------------------------------
md(r"""
## Cell 7 — Process (the heavy compute)

The final step turns the integrated project into report content: NTP statistics
(Williams / Dunnett / Jonckheere), **BMDS dose-response modeling** (the ~8-minute
bottleneck), genomics extraction, section cards, and LLM-generated narratives.

Like the steps above, this is now a lifted, HTTP-free workflow step —
`process_step(dtxsid, params, store)` (ADR-0014). It drives the same compute the
FastAPI route drives (the route is now thin glue over the same core,
`run_process`), so the notebook needs no fake `Request` and no FastAPI at all.
`params` is the settings dict the web UI's Settings panel would post.
**Expect this to run for several minutes.**
""")

code(r"""
from workflow.steps import process_step

# Same settings the web UI's Settings panel posts.
params = {
    "compound_name": "PFHxSAm",
    "dose_unit": "mg/kg",
    "bmd_stats": ["median"],
    "go_pct": 5, "go_min_genes": 20, "go_max_genes": 500, "go_min_bmd": 3,
}

print("processing integrated data (NTP stats + BMDS modeling + genomics + narratives)…")
print("this is the ~8-minute step; be patient.\n")

payload = await process_step(DTXSID, params, store)

def _keys(v):
    # sections/genomics_sections are lists of card dicts; narratives are dicts.
    if isinstance(v, dict):
        return list(v.keys())
    if isinstance(v, list):
        return [c.get("key") or c.get("title") or c.get("platform") for c in v if isinstance(c, dict)]
    return v

print("processing complete. result payload:")
print(f"  apical sections      = {_keys(payload.get('sections'))}")
print(f"  genomics sections    = {_keys(payload.get('genomics_sections'))}")
print(f"  bmd_stats            = {payload.get('bmd_stats')}")
print(f"  has M&M methods      = {bool(payload.get('methods'))}")
print(f"  has apical BMD summ. = {bool(payload.get('apical_bmd_summary'))}")
print(f"  unified narratives   = {_keys(payload.get('unified_narratives'))}")
""")

# ---------------------------------------------------------------------------
md(r"""
## Cell 7b — Genomics charts (rendered inline)

`process_step` renders the UMAP and cluster scatter charts server-side
(Plotly → PNG via kaleido) and returns them under `payload["chart_images"]` —
one entry per organ × sex section, each carrying base64 `umap_png` / `cluster_png`
plus the Enrichr-derived `cluster_summary`. The cells above only printed text;
here we actually display the images inline.
""")

code(r"""
import base64
from IPython.display import display, Markdown, Image

# process_step returns rendered charts under "chart_images" (one dict per
# organ × sex). Fall back to the on-disk chart cache if an older payload
# shape doesn't carry them.
chart_sections = payload.get("chart_images")
if not chart_sections:
    import json, glob
    hits = glob.glob(str(Path("sessions") / DTXSID / "_cache_charts_*.json"))
    if hits:
        chart_sections = json.load(open(hits[0]))

if not chart_sections:
    print("No chart_images in payload and no chart cache on disk — re-run Cell 7.")
else:
    for sec in chart_sections:
        label = sec.get("label") or f"{sec.get('organ','?')} / {sec.get('sex','?')}"
        display(Markdown(f"### {label}"))
        for kind in ("umap", "cluster"):
            b64 = sec.get(f"{kind}_png")
            if not b64:
                continue
            caption = sec.get(f"{kind}_caption") or f"{kind} scatter"
            display(Markdown(f"**{kind.upper()}** — {caption}"))
            display(Image(data=base64.b64decode(b64)))
        # Enrichr cluster biology summary, if present
        for row in (sec.get("cluster_summary") or []):
            terms = ", ".join(row.get("terms", [])[:3])
            src = row.get("source", "")
            print(f"    cluster {row.get('cluster'):>7} [{src}] n={row.get('n_genes')}: {terms}")
""")

# ---------------------------------------------------------------------------
md(r"""
## Cell 8 — Final derived state

The session has walked the full phase machine. Everything below is re-derived
from the artifacts on disk — nothing about the phase was ever stored.
""")

code(r"""
print("Final derived state:")
s = show_state()
print()
print("Artifacts on disk:")
for p in sorted((Path("sessions") / DTXSID).glob("*.json")):
    print(f"  {p.name:34s} {p.stat().st_size:>10,} bytes")
""")

# ---------------------------------------------------------------------------
nb["cells"] = cells
nb["metadata"]["kernelspec"] = {
    "display_name": "Python 3 (rlm-bmdx .venv)",
    "language": "python",
    "name": "python3",
}
out = Path(__file__).parent / "workflow_walkthrough.ipynb"
with open(out, "w", encoding="utf-8") as fh:
    nbf.write(nb, fh)
print(f"wrote {out}  ({len(cells)} cells)")
