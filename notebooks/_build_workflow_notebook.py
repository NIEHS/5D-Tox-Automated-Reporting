"""
Author notebooks/workflow_walkthrough.ipynb programmatically.

The notebook is the headless report workflow one step per cell: the same step
functions `python -m tooling.generate_report` runs (which call the UI-agnostic
core, `workflow.steps`, ADR-0014), so the notebook, the command line and the
browser can never disagree about what a step does.  Each cell that changes the
session ends by re-printing the DERIVED workflow state (phase + legal actions):
the phase is a function of the files on disk, never stored.

It builds a published study (NIEHS-10 by default) into a scratch session from
the reference session's input files and the facts the published report states,
renders the deliverables and compares them with the published book.

Edit THIS builder, not the .ipynb, then regenerate:
    .venv/bin/python notebooks/_build_workflow_notebook.py
Run it headless (writes the outputs into the notebook):
    .venv/bin/python -m nbconvert --to notebook --execute --inplace \\
        --ExecutePreprocessor.timeout=3600 notebooks/workflow_walkthrough.ipynb
"""

from __future__ import annotations

from pathlib import Path

import nbformat as nbf
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

nb = new_notebook()
cells: list = []


def md(text: str) -> None:
    cells.append(new_markdown_cell(text.strip("\n")))


def code(src: str) -> None:
    cells.append(new_code_cell(src.strip("\n")))


# ---------------------------------------------------------------------------
md(r"""
# Report workflow — one step per cell

This notebook takes a study from its data files to a finished report, one step
per cell, without the browser. It runs the **same step functions** as
`python -m tooling.generate_report`. Those call the UI-agnostic workflow core
(`workflow.steps`, ADR-0014), which the web app's routes also call. A session
built here is an ordinary session: open it in the browser afterwards, or carry
on from the command line.

By default it rebuilds **NIEHS-10** (perfluorohexanesulfonamide) in a scratch
session, `DTXSID50469320_nb`. It copies the input files of the reference session
`DTXSID50469320`, takes the facts the published report states from
`tooling.build_published_reports`, and finishes by comparing the result with the
published Bookshelf book. Change `REPORT` in the parameters cell to build
another published study with one study (RR-8, NIEHS-02 … 10).

Every cell that changes the session ends by printing the **derived** workflow
state. The phase is never stored: it is worked out from the files on disk
(`EMPTY → UPLOADED → VALIDATED → INTEGRATED → APPROVED`, with a
`VALIDATION_ERRORS` branch).

**Running it.** In a browser: `.venv/bin/python -m jupyterlab` (the venv's
`jupyter` launcher scripts point at an old path). Headless:
`.venv/bin/python -m nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=3600 notebooks/workflow_walkthrough.ipynb`.
A cold run takes several minutes (integration, then Process). A re-run reuses
the session and its caches, and finishes in about a minute.

The manual for the whole headless workflow is
`docs/headless-report-generation.md`.
""")

# ---------------------------------------------------------------------------
md(r"""
## 1. Setup

Run from the repository root, then set the environment the Java and LLM layers
need, exactly as the command line does (`generate_report._bootstrap_env`):

- **JDK 21 first on `PATH`.** The Java helpers are built for Java 21, and the
  bridge calls a bare `java`.
- **`BMDX_PROJECT_ROOT`**, the BMDExpress-3 build the bridge loads.
- **`SSL_CERT_FILE`**, the NIH CA bundle for the LLM gateway, and a
  `REQUESTS_CA_BUNDLE` that also trusts the public roots, for the Background's
  sources.

Values already set in the environment win. The per-step provenance events are
quieted, as the command line does without `-v`.
""")

code(r"""
import os, sys, subprocess
from pathlib import Path

ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
os.chdir(ROOT)                      # the app is cwd-relative (templates, bmdx.duckdb)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tooling import generate_report as gr   # the command line's step functions
gr._bootstrap_env()                         # before the first bmdx_pipe import

import logging
from common import provenance               # quiet per-step provenance events, as the
provenance.logger.setLevel(logging.WARNING) # command line does without -v

java = subprocess.run(["java", "-version"], capture_output=True, text=True).stderr.splitlines()[0]
print("repository        :", ROOT)
print("java              :", java)
print("BMDX_PROJECT_ROOT :", os.environ.get("BMDX_PROJECT_ROOT", "(unset — integrate will fail)"))
print("SSL_CERT_FILE     :", os.environ.get("SSL_CERT_FILE", "(unset — LLM narratives will fail)"))
print("LLM gateway       :", os.environ.get("ANTHROPIC_BASE_URL", "(default)"))
""")

# ---------------------------------------------------------------------------
md(r"""
## 2. Parameters

The study and everything a person states about it. The data files don't carry
these facts. For a published study they come from the published report itself
(`tooling.build_published_reports.STUDIES`), the same values the batch build
passes on the command line:

| Notebook | Command line | Kept in the session as |
|---|---|---|
| `DESIGN` | `--design` | `study_design.json`; integration re-applies it |
| `EXPERIMENT_METADATA` | `--experiment-metadata` | `metadata_approved.json` |
| `FRONT_MATTER` | `--front-matter` | `front_matter.json` |
| `METHOD_PROFILE` | `--method-profile` | `method_profile.json` (the pin) |
| `DEPOSIT` | `--deposit` | `deposit.json`, listed by the Supplemental Data appendix |

`RESEED = True` wipes the scratch session and starts cold. Leave it `False` to
reuse what an earlier run built.
""")

code(r"""
from tooling.build_published_reports import BOOK_OWN_FILES, BOOKSHELF, GENOMIC_STATED, STUDIES

REPORT = "NIEHS-10"                 # a published study with one study (not NIEHS-12/13)
(SOURCE, NAME, CASRN, SHORT_NAME, _bm2, _token, DOSE_UNIT, DESIGN, DESIGNATION,
 METHOD_PROFILE, _convert) = STUDIES[REPORT]

DTXSID = f"{SOURCE}_nb"             # the scratch session this notebook builds
RESEED = False                      # True: wipe the scratch session and run cold

FRONT_MATTER = {"strain_designation": DESIGNATION}
EXPERIMENT_METADATA = None          # e.g. {"EDHP mg_kg": {"organ": "liver", "sex": "male"}}
DEPOSIT = BOOKSHELF / REPORT        # the deposit = the Bookshelf package less the book's own files
CORRECTIONS = {}                    # {filename: {"platform": …, "data_type": …}} overrides
PROCESS_OVERRIDES = {}              # e.g. {"go_pct": 5}; empty = the method profile's settings
BACKGROUND = False                  # True: write the Background (LLM + ATSDR/IRIS/PubChem)
SURFACES = ["docx", "html", "bits"] # also: jats, bookshelf, latex, pdf (pdf needs `tect`)
OUT = ROOT / "output" / DTXSID

for k, v in dict(REPORT=REPORT, DTXSID=DTXSID, NAME=NAME, CASRN=CASRN, DOSE_UNIT=DOSE_UNIT,
                 DESIGN=DESIGN, FRONT_MATTER=FRONT_MATTER, METHOD_PROFILE=METHOD_PROFILE,
                 DEPOSIT=DEPOSIT.relative_to(ROOT), OUT=OUT.relative_to(ROOT)).items():
    print(f"{k:15} {v}")
""")

# ---------------------------------------------------------------------------
md(r"""
## 3. Import

Importing means putting the study's files in `sessions/<DTXSID>/files/`. With no
files the phase is `EMPTY`; with files but nothing validated it is `UPLOADED`.

The input files are the reference session's: the `.bm2` and the
`.txt`/`.csv`/`.xlsx` files `tooling.cebs_to_pool` converted from the CEBS
package. Nothing derived is copied. Working that out again is what the rest of
the notebook does.
""")

code(r"""
import shutil
from workflow.engine import WorkflowEngine
from workflow.store import DiskPoolStore

store = DiskPoolStore()

def show_state():
    # The workflow state, derived again from the files on disk.
    s = WorkflowEngine(DTXSID, store).state()
    print(f"\nphase: {s.phase.value}   legal actions: {sorted(a.value for a in s.legal_actions)}")
    return s

session = store.session_dir(DTXSID)
if RESEED and session.exists():
    shutil.rmtree(session)
    print(f"RESEED: removed sessions/{DTXSID}/")

if store.has_files(DTXSID):
    print(f"sessions/{DTXSID}/files/ already holds the inputs — reusing them (RESEED = True to start cold)")
else:
    sources = sorted(p for p in store.session_dir(SOURCE).joinpath("files").iterdir() if p.is_file())
    gr.import_files(DTXSID, sources, store)
show_state();
""")

# ---------------------------------------------------------------------------
md(r"""
## 4. Validate

`validate_step` fingerprints every file (platform, data type, sexes, dose
groups), converts long-format CSVs, and checks the pool as a whole: platform
coverage, agreement between files on doses and sexes, and files no platform
claims. It writes `validation_report.json`. An error-severity issue stops the
workflow (`VALIDATION_ERRORS`). Otherwise the phase moves to `VALIDATED`.
""")

code(r"""
report = gr.validate(DTXSID, store)
show_state();
""")

# ---------------------------------------------------------------------------
md(r"""
## 5. Resolve conflicts

When two files cover the same platform, a person picks the one that counts.
Each choice is one `resolve_step` call, recorded in `precedence.json` for
integration to follow. This study has none.
""")

code(r"""
from workflow.steps import resolve_step

conflicts = [i for i in report.get("issues", []) if "conflict" in (i or {}).get("issue_type", "").lower()]
for index, issue in enumerate(conflicts):
    candidates = issue.get("file_ids") or issue.get("candidates") or []
    print(f"conflict {index}: {issue.get('message')}  candidates: {candidates}")
    # resolve_step(DTXSID, index, "<the file id that should win>", store)
print(f"{len(conflicts)} conflict(s)")
""")

# ---------------------------------------------------------------------------
md(r"""
## 6. Confirm the file classification

Each file's detected `(platform, data_type)`, as the browser's review panel
shows it. Confirming writes the classification back into the fingerprints, and
as `# Platform` / `# Data Type` headers into `.txt`/`.csv` files, which the Java
integration reads. Put an entry in `CORRECTIONS` (keyed by file name) only for a
file detected wrongly. Empty accepts the detection, as clicking through the
panel does.
""")

code(r"""
gr.confirm_metadata(DTXSID, CORRECTIONS or None, store)
""")

# ---------------------------------------------------------------------------
md(r"""
## 7. Integrate

`integrate_step` merges the pool into one BMDExpress project, `integrated.json`:
the **single source of truth** every later step reads. It calls the BMDExpress-3
Java library and takes a minute or two. The phase moves to `INTEGRATED`.

Integrating again wipes every Process cache, so this cell skips when the session
is already integrated, as the command line does without `--reintegrate`.
""")

code(r"""
identity = {"dtxsid": DTXSID, "name": NAME, "casrn": CASRN}
REINTEGRATE = RESEED

if store.artifact_exists(DTXSID, "integrated.json") and not REINTEGRATE:
    store.write_json(DTXSID, "identity.json", identity)
    print("already integrated — skipped (REINTEGRATE = True re-runs it and recomputes everything)")
else:
    gr.integrate(DTXSID, identity, store)
show_state();
""")

# ---------------------------------------------------------------------------
md(r"""
## 8. State what the data doesn't record

Facts a person states, kept in the session and re-applied at every integration:

- **Study design** (species, strain, route, vehicle, duration) from the
  controlled vocabulary. Without it the report states the logged standard
  design (Sprague Dawley rats, gavage in corn oil; inhalation for ppm).
- **Experiment metadata**, such as the tissue of an experiment the project
  names only "EDHP mg_kg".
- **Front matter**: authors, contributors, publication details, and the strain
  designation the title prints.
- **The data deposit**: the supplemental files deposited with the report.
""")

code(r"""
from pipeline.deposit import record_deposit

gr.apply_design(DTXSID, DESIGN, store)
if EXPERIMENT_METADATA:
    gr.apply_experiment_metadata(DTXSID, EXPERIMENT_METADATA)
gr.apply_front_matter(DTXSID, FRONT_MATTER, store)
if DEPOSIT:
    manifest = record_deposit(DTXSID, DEPOSIT, tuple(BOOK_OWN_FILES))
    print(f"  deposit: {len(manifest['files'])} file(s) from {DEPOSIT.relative_to(ROOT)}")
""")

# ---------------------------------------------------------------------------
md(r"""
## 9. Method profile

The analysis method is a versioned profile (`profiles/<name>.yaml`, ADR-0027):
statistics, BMD acceptance, BMR, GO ranking and the Methods text all come from
it. Pinning a profile fixes the study on it. A study with no pin follows the
newest profile. The cell prints what the profile asks for that this tool cannot
do as stated (a **deviation**), and anything the `.bm2` records differently.
""")

code(r"""
gr.method_profile(DTXSID, METHOD_PROFILE)
""")

# ---------------------------------------------------------------------------
md(r"""
## 10. Approve the data: the animal report

`generate_animal_report_step` writes `animal_report.json`: every animal with its
dose, sex and cohort (core or biosampling), checked across files and platforms.
The phase moves to `APPROVED`, the end of the data-preparation arc.
""")

code(r"""
gr.animal_report(DTXSID, store)
ar = store.read_json(DTXSID, "animal_report.json") or {}
print("  dose groups:", ar.get("dose_groups"))
show_state();
""")

# ---------------------------------------------------------------------------
md(r"""
## 11. Process

The heavy step. It runs NTP statistics (Jonckheere, then Williams/Dunnett or
Shirley/Dunn), BMD modeling, genomics extraction and charts, the result
sections, and the LLM-written narratives. Then it writes the apical result
sections as section files (`bm2_<slug>.json`). Each layer is cached by a hash
of its inputs, so an unchanged session finishes in seconds. **Expect several
minutes when cold.**

The GO ranking and cutoffs are the method profile's. `PROCESS_OVERRIDES`
overrides them for this run only, as `--go-pct` and the like do.
""")

code(r"""
params = {"compound_name": SHORT_NAME, "dose_unit": DOSE_UNIT, **PROCESS_OVERRIDES}
payload = await gr.process_async(DTXSID, params, store)
show_state();
""")

# ---------------------------------------------------------------------------
md(r"""
### 11b. Genomics charts

Process renders each organ × sex section's UMAP and cluster scatter charts as
PNGs (`payload["chart_images"]`, cached in `_cache_charts_*.json`).
""")

code(r"""
import base64
from IPython.display import Image, Markdown, display

for sec in payload.get("chart_images") or []:
    display(Markdown(f"**{sec.get('label') or sec.get('organ', '?') + ' / ' + sec.get('sex', '?')}**"))
    for kind in ("umap", "cluster"):
        if sec.get(f"{kind}_png"):
            display(Image(data=base64.b64decode(sec[f"{kind}_png"]), width=520))
if not payload.get("chart_images"):
    print("no genomics charts in this study")
""")

# ---------------------------------------------------------------------------
md(r"""
## 12. Background and Summary

The **Background** is about the chemical, not this data set. It is written by an
LLM over ATSDR, IRIS and PubChem, and refuses to write anything when ATSDR or
IRIS can't be reached. With `BACKGROUND = False`, the reference session's
Background is reused when it has one, as `build_published_reports` keeps it
across rebuilds.

The **Summary** is built from the session's results, with no LLM. It never
replaces a Summary a person approved or wrote.
""")

code(r"""
if BACKGROUND:
    gr.background(DTXSID, identity, "", store)
elif not store.session_dir(DTXSID).joinpath("background.json").exists():
    src = store.session_dir(SOURCE) / "background.json"
    if src.exists():
        shutil.copy2(src, store.session_dir(DTXSID) / "background.json")
        print(f"  Background copied from sessions/{SOURCE}/ (unapproved, as written there)")
    else:
        print("  no Background (set BACKGROUND = True to write one)")
gr.summary(DTXSID, store)
""")

# ---------------------------------------------------------------------------
md(r"""
## 13. Sections and the publish gate

The report's sections as files, each with its approval. You don't need to
approve anything for a first report: unapproved sections render as drafts.
Approval matters once a session is **reprocessed**. A reprocess marks the
LLM-written sections stale, and they block publishing until a person accepts
them again (`accept_section_step`). A blocked report renders only as a draft.
""")

code(r"""
from workflow.steps import accept_section_step, release_section_step

for key, sec in sorted(store.read_section_dicts(DTXSID).items()):
    flags = [f for f in ("approved", "stale") if sec.get(f)]
    print(f"  {key:32} {', '.join(flags) or 'draft'}")

readiness = WorkflowEngine(DTXSID, store).publish_readiness()
print("\ncan publish:", readiness["can_publish"], readiness["blocking"] or "")
# accept_section_step(DTXSID, "bm2_body-weight", store)    # approve one section
# release_section_step(DTXSID, "bm2_body-weight", store)   # and reopen it
""")

# ---------------------------------------------------------------------------
md(r"""
## 14. Render the deliverables

Each surface is a projection of the same data and document tree. The document
is the study's own definition when it has one (`templates/studies/<id>/`, over
its era, ADR-0029); for this scratch session it is the shared template. So
structural differences from the published book in the next cell are expected
where the published definition would differ. The files are written to `OUT` as
`<DTXSID><suffix>`.
""")

code(r"""
written = gr.render(DTXSID, SURFACES, OUT, None, False)
""")

# ---------------------------------------------------------------------------
md(r"""
## 15. Compare with the published report

The published book (`assets/cebs/_bookshelf/<REPORT>`) and ours, aligned
section by section and block by block (`rendering.bits_compare`). This is the
same comparison `python -m tooling.report_compare` writes for every published
report, and `/Compare/<dtxsid>` serves. The page is written next to the
deliverables; open it in a browser for the side-by-side and unified views. The
table below lists the sections that differ most.
""")

code(r"""
from IPython.display import Markdown, display
from rendering.bits_compare import compare, load_book, unified_diff
from rendering.bits_compare_page import render_page

if "bits" not in SURFACES:
    gr.render(DTXSID, ["bits"], OUT, None, False)
pub_book, pub_images = load_book(BOOKSHELF / REPORT)
our_book, our_images = load_book(OUT / f"{DTXSID}-bits.zip")
cmp = compare(pub_book, our_book, left_images=pub_images, right_images=our_images)

page = OUT / f"{DTXSID}-compare.html"
page.write_text(render_page(cmp, title=f"{REPORT} · {NAME} — published vs this notebook",
                            left_label=f"Published — {REPORT}", right_label=f"Generated — {DTXSID}"),
                encoding="utf-8")
(OUT / f"{DTXSID}-compare.diff").write_text(
    unified_diff(cmp, f"published/{REPORT}", f"generated/{DTXSID}"), encoding="utf-8")

print(f"{cmp.sim:.0%} of the words match;", ", ".join(f"{n} {s}" for s, n in sorted(cmp.counts().items())))
print("by kind:", "; ".join(f"{g} {v:.0%}" for g, (v, w) in cmp.by_kind().items() if w))
print("page:", page.relative_to(ROOT))

rows = [(sp, sim) for sp, (sim, st) in zip(cmp.sections, cmp.subtree()) if sp.changes]
rows.sort(key=lambda r: r[1])
display(Markdown("| section | words match | changed blocks | status |\n|---|---|---|---|\n" + "\n".join(
    f"| {' › '.join(sp.section.path)} | {sim:.0%} | {sp.changes} | {sp.status} |" for sp, sim in rows[:15])))
""")

# ---------------------------------------------------------------------------
md(r"""
## 16. Where things stand

The final derived state and the session's files. The session is an ordinary
one: it shows in the browser's session list and on `/Bookshelf`. Delete
`sessions/<DTXSID>/` and `output/<DTXSID>/` to remove it.
""")

code(r"""
show_state()
print()
for p in sorted(store.session_dir(DTXSID).glob("*.json")):
    print(f"  {p.name:42} {p.stat().st_size:>10,} bytes")
print("\ndeliverables:")
for p in sorted(OUT.iterdir()):
    print(f"  {p.relative_to(ROOT)}  ({p.stat().st_size / 1024:.0f} KB)")
""")

# ---------------------------------------------------------------------------
nb["cells"] = cells
nb["metadata"]["kernelspec"] = {
    "display_name": "Python 3 (rlm-bmdx .venv)",
    "language": "python",
    "name": "python3",
}
nb["metadata"]["language_info"] = {"name": "python"}
out = Path(__file__).parent / "workflow_walkthrough.ipynb"
with open(out, "w", encoding="utf-8") as fh:
    nbf.write(nb, fh)
print(f"wrote {out}  ({len(cells)} cells)")
