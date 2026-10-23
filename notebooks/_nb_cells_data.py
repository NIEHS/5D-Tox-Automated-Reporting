"""
Cells of notebooks/workflow_walkthrough.ipynb, part 1: the introduction and
the data-preparation arc (setup → parameters → input files → import → validate
→ resolve → confirm → integrate → stated facts → method profile and document
definition → animal report).  Assembled by notebooks/_build_workflow_notebook.py; each step's
explanation must stay true to the code it describes.
"""

from __future__ import annotations

CELLS: list[tuple[str, str]] = []


def _md(text: str) -> None:
    CELLS.append(("md", text))


def _code(src: str) -> None:
    CELLS.append(("code", src))


# ---------------------------------------------------------------------------
_md(r"""
# Report workflow — one step per cell, explained

This notebook takes a study from its published data package to a finished
report, one step per cell, without the browser. Before every step there is a
long explanation in four parts:

- **Purpose**: what the step is for, and why the workflow needs it at that point.
- **How it's implemented**: the functions it calls, in order, as `module.function`,
  and what each one does.
- **Reads → writes**: the files in the session directory it consumes and produces.
- **If it goes wrong**: how it fails, and what that means.

The cells run the **same step functions** as `python -m tooling.generate_report`.
Those call the UI-agnostic workflow core (`workflow.steps`, ADR-0014), which
the web app's routes call too. A session built here is an ordinary session:
open it in the browser afterwards, or carry on from the command line.

By default it rebuilds **NIEHS-10** (perfluorohexanesulfonamide, Bookshelf
NBK589955) in a scratch session, `DTXSID50469320_nb` (in a workspace of your
own, below, the study's own id, `DTXSID50469320`). It converts the CEBS data
package in `assets/cebs/NIEHS-10/`, states the facts the published report
states (from `tooling.build_published_reports`), and finishes by comparing the
result with the published Bookshelf book. Change `REPORT` in the parameters
cell to build another published report about one study (RR-8, NIEHS-02 … 10).

**Running it.** In a browser: `.venv/bin/python -m jupyterlab` (the venv's
`jupyter` launcher scripts point at an old path). Headless:
`.venv/bin/python -m nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=3600 notebooks/workflow_walkthrough.ipynb`.
A cold run (`RESEED = True`) takes three to five minutes: the conversion a few
seconds, integration about 20 s, Process two to three and a half minutes (its
LLM calls and chart rendering dominate, and vary), rendering about 25 s. A
re-run reuses the session and its caches, and finishes in about a minute.

**A workspace of your own, with your own data.** To try it on your own study
without touching anyone else's sessions, outputs or Bookshelf, someone starts
a workspace for you: `tooling/workspace.sh <name>`. It keeps its sessions in
`workspaces/<name>/sessions/` (`SESSIONS_DIR`) and its deliverables in
`workspaces/<name>/output/` (`OUTPUT_DIR`). It starts the app on port 9300,
whose `/Bookshelf` lists that workspace's reports only, and JupyterLab on port
9400 (unless other ports are given) with this notebook copied into `workspaces/<name>/notebooks/`, so your
runs and their outputs stay in your copy.

Bring your data from your own machine: in JupyterLab, open the `uploads/`
folder beside the notebook and use the upload button (or drag the files onto
the file list). The notebook takes the kinds of file the browser's *Upload*
step does: BMDExpress projects (`.bm2`), `.csv`, `.txt` and `.xlsx` (the app
also unpacks a `.zip`); validation (step 5) says what each one is and which it
cannot use. Then set your study's id and what you
know about it in the parameters cell (step 2) and run the notebook. Steps 16
and 17's comparison with a published book apply only to a published study.
The app on port 9300 takes uploads too: its *Upload* step sends files from your
machine into the same workspace.

With `uploads/` empty, the notebook builds the published study (`REPORT`)
under its own id, as an example. The workspace's Bookshelf then shows it as the
published report's generated version, linked to the published content
(step 16).

The manual for the whole headless workflow is
`docs/headless-report-generation.md`.
""")

# ---------------------------------------------------------------------------
_md(r"""
## 0. How the pieces fit

Read this once. The step explanations below refer back to it.

### Layers

| Layer | Where | What it is |
|---|---|---|
| Front ends | `web_routes/*` (the browser), `tooling/generate_report.py` (the command line), this notebook | Parse input, call a step, show the result. No workflow logic. |
| Safeguards | `safeguards/*` (ADR-0031) | The idiot-proofing, between the browser or the command line and the core: an act refused outside its phase, Process refused until a person chose the method, a person's text never replaced by a machine, a reason to force or reopen, stated facts checked against the vocabularies, no Background without its sources, the publish gate; each refusal explained in plain words (`safeguards.refusals`). Entry point: `safeguards.guarded`, with the core steps' names. **This notebook calls the core directly, unguarded.** |
| Workflow core | `workflow/steps.py`, `workflow/engine.py`, `workflow/phases.py`, `workflow/store.py` | One function per step. Takes plain Python, returns plain Python, raises `workflow.errors.StepError` (with an HTTP-style status code the routes pass on). All session I/O goes through an injected `PoolStore` (`DiskPoolStore` here). |
| Pipeline | `pipeline/*`, `tables/*`, `genomics/*`, `narrative/*`, `rendering/*` | The work: fingerprint caching, processing layers, tables, narratives and the four render surfaces. HTTP-free. |
| Document | `document_model/*`, `templates/`, `profiles/` | The report's declarations: the document tree and its definitions (an era plus a study's alterations, ADR-0029), the wording of the prose written from data (`phrasing:`), the session's definition pin; the analysis method profiles (ADR-0027). Neither `pipeline` nor `document_model` imports the web layer. |
| Data model | `bmdx_pipe` (the sibling package `/workspace/bmdx-pipe`) | Fingerprinting, pool validation, integration, NTP statistics, BMD acceptance, the animal report. |
| Java | BMDExpress-3 (`$BMDX_PROJECT_ROOT/target/bmdx-core.jar` + `target/deps/*.jar`) and the helper classes in `bmdx_pipe/java/` | `ExportBm2` (`.bm2` → JSON), `IntegrateProject` (the merge), `ExportCategories`, `ExportGenomics`, `RunApicalBmds` (ToxicR model averaging), `SubsetBm2`, `JsonToBm2`. Called as subprocesses (`bmdx_pipe.java_bridge.build_classpath`). |

### The session directory is the state

Everything about a study lives in `sessions/<DTXSID>/`: the input files in
`files/`, and one JSON file per step's output (`validation_report.json`,
`integrated.json`, `animal_report.json`, `bm2_<slug>.json`, …). There is no
database of sessions and no in-memory state that matters. Restart the server,
or open the session in the browser, and everything is still there.

A session file that exists but can't be read (corrupt JSON, say) is an error
naming the file (`common.session_files.UnreadableSessionFile`, HTTP 422 in
the browser), never treated as absent: a report is not built without it.

### The phase is derived, never stored

`workflow.engine.WorkflowEngine.state()` gathers presence flags from the store
(`gather_artifacts`) and passes them to `workflow.phases.derive_phase`, which
applies these rules in order:

1. no files in `files/` → `EMPTY`
2. no `validation_report.json` → `UPLOADED`
3. the validation report has an error-severity issue → `VALIDATION_ERRORS`
4. no `integrated.json`, or one built from another validation
   (`workflow.integration_basis`: out of date) → `VALIDATED`
5. no `animal_report.json` → `INTEGRATED`
6. otherwise → `APPROVED`

A stale section does not move the phase: staleness is a section's matter
(its currency and the publish gate, §14).

The legal actions for each phase are the workflow's declared table of acts
(`workflow.phases.LEGAL_ACTIONS`: `ADD_FILES`, `REMOVE_FILE`, `RESET`,
`VALIDATE`, `RESOLVE`, `CONFIRM_CLASSIFICATION`, `INTEGRATE`,
`STATE_DATASET_FACTS`, `APPROVE`, `PROCESS`), with the act that moves each
phase forward (`NEXT_STEP`). Here they are shown, not enforced: the browser and
the command line refuse an act outside them (`safeguards.acts.require`).
Process, sections and rendering have no phase of their own; their state is
their files.

### Caches are keyed by their inputs

Process splits its work into units. Each unit writes
`_cache_<unit>_<hash>.json`, where the hash is a SHA-256 of everything that
unit's output depends on (the integrated data, the method profile's settings,
the sidecars' contents, and so on). Same inputs → same file → no recompute.
Change any input and the hash changes, so a stale cache is never read.
Integration deletes every cache, since it changes the data under all of them.

### Provenance

Each step is wrapped in `common.provenance.step_provenance`. It records
`step_start`, `step_done` (with milliseconds) or `step_error` events, and the
steps record their own events too (`materialized`, `content_skipped`, …). The
notebook quiets that logger to warnings, as the command line does without `-v`.

### Where an LLM is used, and where it may send data

Most of the workflow is deterministic. An LLM is called in four places only:

| Where | What it writes |
|---|---|
| Integrate | each experiment's metadata (organ, sex, species, route, …) inferred from names; a stated value always wins |
| Process: Methods | the Materials and Methods subsections a template doesn't build from data |
| Process: content | each organ × sex genomics interpretation, and the analytical paragraph of the apical BMD summary |
| Background | the Background section, over data gathered from ATSDR, IRIS, PubChem and others |

Every call goes through `styling_export.llm_helpers` →
`styling_export.llm_endpoints.AnthropicEndpoint` (default model
`claude-sonnet-4-6`). Prompts carry study data, so
`llm_endpoints.approved_base_url()` refuses to send one anywhere except the
walled NIEHS gateway: `ANTHROPIC_BASE_URL` must be
`https://litellm.toxpipe.niehs.nih.gov`. That host list is a code constant,
not a setting. Off the NIEHS network the LLM features fail; they never fall
back to a public endpoint.

Two other lookups would send the study's genes outside, so both are off
unless switched on: Enrichr cluster labels (`BMDX_ALLOW_ENRICHR=1`, step 12)
and NCBI gene names for the genomic sentences (`BMDX_ALLOW_NCBI_GENE=1`,
step 15; otherwise the committed cache `assets/gene_names.json`, and a
visible placeholder for a gene it lacks).

Most of the prose that is **not** LLM-written is written by rules over the
tables (the Abstract, the Summary, the 2026 books' gene set and gene results).
Where a definition declares the wording (`phrasing:`, ADR-0029 §11), the rule
only chooses the form and fills the fields; the rules still worded in code are
listed in `docs/writing-rules-inventory.md`.

### Three rules every step keeps

1. **`integrated.json` is the single source of truth.** After integration,
   nothing reads the raw input files again, only `integrated.json` and its
   sidecars.
2. **The document tree drives the structure.** Section order, headings and
   table numbers come from a `DocNode` tree, never from the code.
3. **The phase is derived** (above).

### The steps at a glance

| § | Step | Function | Java | LLM | Writes |
|---|---|---|---|---|---|
| 3 | Input files | `tooling.cebs_to_pool` | `SubsetBm2` | – | a temporary input directory |
| 4 | Import | `generate_report.import_files` | – | – | `files/` |
| 5 | Validate | `workflow.steps.validate_step` | `ExportBm2` | – | `_fingerprints.json`, `validation_report.json` |
| 6 | Resolve | `workflow.steps.resolve_step` | – | – | `precedence.json` |
| 7 | Confirm | `workflow.steps.confirm_metadata_step` | – | – | file headers, `_fingerprints.json` |
| 8 | Integrate | `workflow.steps.integrate_step` | `IntegrateProject`, `ExportCategories`, `ExportGenomics`, `JsonToBm2` | ✓ | `integrated.json`, `integrated.bm2`, `_category_lookup.json`, `genomics.sidecar.json`, `identity.json`, `method_profile.json` |
| 9 | State facts | `generate_report.apply_*`, `generate_report.record_abbreviation`, `pipeline.deposit.record_deposit`, `genomics.efdr.record_efdr` | `JsonToBm2`, `ExportCategories`, `ExportBm2` (eFDR) | – | `study_design.json`, `metadata_approved.json`, `front_matter.json`, `identity.json`, `deposit.json`, `efdr.json` |
| 10 | Method profile, document definition | `pipeline.method_profile.pin_profile`, `document_model.definition_pin` | – | – | `method_profile.json`, `document_definition.json` + `.yaml` |
| 11 | Animal report | `workflow.steps.generate_animal_report_step` | – | – | `animal_report.json` |
| 12 | Process | `workflow.steps.process_step` + `materialize_result_sections` | `RunApicalBmds`, `ExportGenomics` | ✓ | `_cache_*.json`, `references.json`, `bm2_<slug>.json`, `session.duckdb`; the definition pin kept current |
| 13 | Background, Summary | `generate_report.background`, `workflow.steps.materialize_summary` | – | ✓ (Background) | `background.json`, `summary.json` |
| 14 | Publish gate | `WorkflowEngine.publish_readiness` | – | – | – |
| 15 | Render | `rendering.preview_surface.render_preview` | – | – | `output/<DTXSID>/…` |
| 16 | Compare; the published book as a session | `rendering.bits_compare.compare`, `tooling.published_clone.build` | – | – | `output/<DTXSID>/…-compare.html`, `sessions/<SOURCE>_published/` |
""")

# ---------------------------------------------------------------------------
_md(r"""
## 1. Setup

**Purpose.** Run from the repository root, with the environment the Java and
LLM layers need, exactly as the command line sets it.

**How it's implemented.**

1. `os.chdir(ROOT)`: the repository (`BMDX_REPO` when a workspace sets it,
   else this notebook's parent directory). The app resolves several things relative to the working
   directory: `templates/`, `profiles/`, `sessions/` (via
   `common.paths.SESSIONS_DIR`) and the knowledge base `bmdx.duckdb`. The repo
   root goes on `sys.path` too, because the packages are imported by name
   from there (no `pip install`).
2. `tooling.generate_report._bootstrap_env()`, the same function
   `run-server.sh`'s defaults mirror. It must run **before the first
   `bmdx_pipe` import**, because `bmdx_pipe.java_bridge` reads
   `BMDX_PROJECT_ROOT` at import time. It sets, unless already set:
   - **JDK 21 first on `PATH`** and `JAVA_HOME` (from `BMDX_JDK_HOME`, default
     `/opt/liberica-jdk-21`). The helper classes are compiled for Java 21 and the
     bridge calls a bare `java`; an older JVM fails with
     `UnsupportedClassVersionError`.
   - **`BMDX_PROJECT_ROOT`**: the first of `/workspace/BMDExpress-3` or
     `~/Dev/Projects/BMDExpress-3` that has a `target/` directory.
   - **`SSL_CERT_FILE`**: the NIH CA bundle, which the LLM gateway's
     certificate is signed by. The Anthropic SDK's HTTP client reads
     `SSL_CERT_FILE`.
   - **`REQUESTS_CA_BUNDLE`**: a bundle with the NIH CA *and* the public roots
     (`_bundle_with_public_roots`: the system bundle if it already holds the
     NIH CA, else certifi + the NIH CA in a temp file). The Background's
     sources (PubChem, PubMed, …) are public sites and `requests` reads this
     variable; a bundle with only the NIH CA fails every one of them.
   - A warning when `ANTHROPIC_API_KEY` is not set.
3. `common.provenance.logger` is set to `WARNING`, as the command line does
   without `-v`.

**If it goes wrong.** The cell prints what it found. An unset
`BMDX_PROJECT_ROOT` makes integration fail. An unset `SSL_CERT_FILE` or a
missing gateway makes the LLM-written parts fail; everything else still runs.
""")

_code(r"""
import os, sys, subprocess
from pathlib import Path

ROOT = Path(os.environ.get("BMDX_REPO") or
            (Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()))
os.chdir(ROOT)                      # the app is cwd-relative (templates, profiles, bmdx.duckdb)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tooling import generate_report as gr   # the command line's step functions
gr._bootstrap_env()                         # before the first bmdx_pipe import

import logging
from common import provenance               # quiet per-step provenance events, as the
provenance.logger.setLevel(logging.WARNING) # command line does without -v

java = subprocess.run(["java", "-version"], capture_output=True, text=True).stderr.splitlines()[0]
import common.paths
print("repository        :", ROOT)
print("sessions          :", common.paths.SESSIONS_DIR)
print("outputs           :", common.paths.OUTPUT_DIR)
print("java              :", java)
print("BMDX_PROJECT_ROOT :", os.environ.get("BMDX_PROJECT_ROOT", "(unset — integrate will fail)"))
print("SSL_CERT_FILE     :", os.environ.get("SSL_CERT_FILE", "(unset — LLM narratives will fail)"))
print("LLM gateway       :", os.environ.get("ANTHROPIC_BASE_URL", "(unset — LLM calls are refused)"))
""")

# ---------------------------------------------------------------------------
_md(r"""
## 2. Parameters

**Purpose.** Name the study, and give everything a person states about it.
The data files don't record these facts; a study team would type them into the
browser. For a published study they come from the published report itself:
`tooling.build_published_reports.STUDIES` holds, per report, the values the
batch build (`python -m tooling.build_published_reports`) passes on the
command line.

| Notebook | Command line | Kept in the session as | Used by |
|---|---|---|---|
| `DESIGN` | `--design` | `study_design.json` | Every experiment's description; captions, Methods, the title. Re-applied at every integration. |
| `EXPERIMENT_METADATA` | `--experiment-metadata` | `metadata_approved.json` | An experiment's organ/sex when its name doesn't say (e.g. "EDHP mg_kg"). Re-applied at every integration. |
| `FRONT_MATTER` | `--front-matter` | `front_matter.json` | Authors, contributors, publication details, and the strain designation the title prints. |
| `METHOD_PROFILE` | `--method-profile` | `method_profile.json` (the pin) | Every statistical and BMD setting, and the Methods text. |
| `DEPOSIT` | `--deposit` | `deposit.json` | The Supplemental Data appendix. |
| `DOCUMENT_DEFINITION` | `--document-definition` | `document_definition.json` + `.yaml` (the pin) | Which definition the report renders from: `None`/`"track"` the current templates (recorded), `"fixed"` a snapshot taken now. |
| `DOSE_UNIT`, `SHORT_NAME` | `--dose-unit`, `--compound-name` | Process parameters; `SHORT_NAME` also as `identity.json`'s `abbreviation` | Table headers and narratives; the short name the sentences written from the tables use ("PFHxSAm", "1,4-DCB"). |

With your own data (`OWN_DATA`: files in `UPLOADS`), set these yourself:
`DTXSID` (the session id: your test article's DTXSID if it has one, so its
name and CASRN can be looked up), and whichever facts you know. Each one left
`None` is not invented: the name and CASRN are resolved from a real DTXSID;
the dose unit is read from the data; the design is the standard one and the
report says so; the method profile is the newest. There is no published book
to compare with, and no deposit unless you name one.

The rest steer the notebook itself:

- **`UPLOADS`**: the folder of your own data files (`BMDX_UPLOADS`, which
  `tooling/workspace.sh` sets to the workspace's `uploads/`). Files there
  make the notebook build your study (`OWN_DATA`).
- **`FROM_PACKAGE`** (default `True`; a published study only): convert the CEBS package in step 3. With
  `False`, step 3 instead copies the inputs the reference session `SOURCE`
  was built from (the same files, already converted once).
- **`RESEED`**: `True` deletes the scratch session first and runs everything
  cold. `False` reuses whatever an earlier run built. Changing `REPORT` or
  `FROM_PACKAGE` for an existing scratch session needs `RESEED = True`, since
  import keeps the files a session already has.
- **`CORRECTIONS`**: file classifications to override in step 7.
- **`PROCESS_OVERRIDES`**: Process settings for this run only (step 12).
- **`BACKGROUND`**: write the Background with the LLM (step 13).
- **`SURFACES`**, **`OUT`**: what to render (step 15) and where to
  (`OUTPUT_DIR/<DTXSID>`).
- **`DTXSID`**: the session this notebook builds. In the repository's own
  sessions it is a scratch session, `<SOURCE>_nb`, so the reference session
  `SOURCE` (the study as `build_published_reports` built it) is left alone. In
  a workspace of your own (`SESSIONS_DIR` elsewhere) it is the study's own id,
  `SOURCE`. **`REFERENCE`** is the reference session, in the repository's
  `sessions/` either way.

`EXPERIMENT_METADATA` is derived for the reports whose genomic project
names its experiments by chemical and dose only (RR-8, NIEHS-02 … 06): the
report says the liver of male rats was used, so every experiment in the
project gets `{"organ": "liver", "sex": "male"}`
(`build_published_reports.GENOMIC_STATED`).
""")

_code(r"""
import json
from tooling.build_published_reports import (BOOK_OWN_FILES, BOOKSHELF, CEBS, GENOMIC_STATED,
                                             STUDIES, _project_json)

# Your own data: the files in UPLOADS (a workspace's uploads/ folder, BMDX_UPLOADS,
# where JupyterLab's upload button puts what you send from your machine). With
# files there, the notebook builds your study; else the published study REPORT.
UPLOADS = Path(os.environ["BMDX_UPLOADS"]) if os.environ.get("BMDX_UPLOADS") else None
OWN_DATA = bool(UPLOADS and any(p.is_file() for p in UPLOADS.iterdir()))
WORKSPACE = common.paths.SESSIONS_DIR.resolve() != (ROOT / "sessions").resolve()

if OWN_DATA:
    REPORT = SOURCE = REFERENCE = None
    DTXSID = "DTXSID_MY_STUDY"      # your study's session id: its DTXSID if it has one
                                    # ("DTXSID" + up to 64 letters, digits, _ or -)
    NAME = CASRN = None             # the test article; None: resolved from a real DTXSID
    SHORT_NAME = None               # the short name the prose uses ("PFHxSAm"); None: the name
    DOSE_UNIT = None                # None: the unit the data records, else mg/kg
    DESIGN = None                   # {"strain": …, "articleRoute": …, …}; None: the standard
                                    # design (SD rats, gavage, corn oil, 5 days), logged as such
    METHOD_PROFILE = None           # None: the newest profile, tracked
    FRONT_MATTER = {}               # {"authors": […], "strain_designation": …}
    EXPERIMENT_METADATA = None
    DEPOSIT = None                  # a folder of the files deposited with the report, if any
else:
    REPORT = "NIEHS-10"             # a published report about one study (not NIEHS-12/13)
    (SOURCE, NAME, CASRN, SHORT_NAME, BM2, BM2_TOKEN, DOSE_UNIT, DESIGN, DESIGNATION,
     METHOD_PROFILE, CONVERT_ARGS) = STUDIES[REPORT]
    DTXSID = SOURCE if WORKSPACE else f"{SOURCE}_nb"   # the session this notebook builds
    REFERENCE = ROOT / "sessions" / SOURCE             # the reference session (step 3, 13)
    FRONT_MATTER = {"strain_designation": DESIGNATION}
    EXPERIMENT_METADATA = None      # {experiment name: {"organ": …, "sex": …}}
    if REPORT in GENOMIC_STATED and _project_json(REPORT):
        _names = [e["name"] for e in json.loads(_project_json(REPORT).read_text())
                  .get("doseResponseExperiments") or []]
        EXPERIMENT_METADATA = {n: GENOMIC_STATED[REPORT] for n in _names}
    DEPOSIT = BOOKSHELF / REPORT    # the deposit = the Bookshelf package less the book's own files

RESEED = False                      # True: wipe the session and run cold
FROM_PACKAGE = True                 # False: copy the reference session's inputs instead
DOCUMENT_DEFINITION = None          # "fixed": render from a snapshot of the definition as it is now
CORRECTIONS = {}                    # {filename: {"platform": …, "data_type": …}} overrides
PROCESS_OVERRIDES = {}              # e.g. {"go_pct": 5}; empty = the method profile's settings
BACKGROUND = False                  # True: write the Background (LLM + ATSDR/IRIS/PubChem)
SURFACES = ["docx", "html", "bits"] # also: jats, bookshelf, latex, pdf (pdf needs `tect`)
OUT = common.paths.OUTPUT_DIR / DTXSID

for k, v in dict(UPLOADS=UPLOADS, OWN_DATA=OWN_DATA, REPORT=REPORT, DTXSID=DTXSID, NAME=NAME, CASRN=CASRN, SHORT_NAME=SHORT_NAME,
                 DOSE_UNIT=DOSE_UNIT, DESIGN=DESIGN, FRONT_MATTER=FRONT_MATTER,
                 EXPERIMENT_METADATA=EXPERIMENT_METADATA, METHOD_PROFILE=METHOD_PROFILE,
                 DOCUMENT_DEFINITION=DOCUMENT_DEFINITION,
                 FROM_PACKAGE=FROM_PACKAGE, DEPOSIT=DEPOSIT,
                 OUT=OUT).items():
    print(f"{k:19} {v}")
if UPLOADS and not OWN_DATA:
    print(f"\n{UPLOADS} is empty: upload your data files there (JupyterLab's upload button)"
          f" and run this cell again. Until then the notebook builds {REPORT} as an example.")
""")

# ---------------------------------------------------------------------------
_md(r"""
## 3. Input files: your uploads, or the CEBS package

**With your own data** (`OWN_DATA`), the input files are simply the files in
`UPLOADS`, as you uploaded them; step 4 imports them, and validation (step 5)
says what each one is. The rest of this step is about a published study.

**Purpose.** Turn what NIEHS published into files the pool accepts. CEBS
publishes each study's apical data as NTP "Individual Animal" workbooks
(`C20022-01_Individual_Animal_Body_Weight_Data.xlsx` and so on), each with a
*Key to Column Labels* sheet and a *Data* sheet, plus the study's genomic
BMDExpress project (`.bm2`). The pool's accepted apical input is the
long-format NTP CSV: one row per animal and observation.

**How it's implemented** (`FROM_PACKAGE = True`, as
`build_published_reports.build` does it):

1. **`python -m tooling.cebs_to_pool --package assets/cebs/<REPORT> --out <tmp>/inputs`**
   runs as a subprocess. For each Individual Animal workbook it:
   - reads the *Data* sheet and writes it split by sex as
     `<platform>_truth_<sex>.csv` (`body_weight_truth_male.csv`,
     `clin_chem_truth_female.csv`, …). The file name is what later tells
     fingerprinting the platform and the data type (`tox_study`).
   - reads the units the *Key* sheet states for each column
     (`bmdx_pipe.key_sheet_units`) and writes them beside the CSV as
     `<stem>.units.json`, because the CSV headers carry none. They end up in
     the sidecars, and the tables print them.
   - for the 2025-format workbooks (no `Sex` column), fills the sex from the
     study title in the Key sheet, and says so.
   - for NIEHS-02 … 05, which publish a database-export layout instead, first
     converts it to the Key/Data columns (`tooling.cebs_db_export`).
   - with `--mg-per-kg-from <project .json>` (RR-8 and NIEHS-02 … 06, whose
     workbooks record doses in mmol/kg), converts each molar dose to the
     genomic project's mg/kg dose level. The project's nonzero levels must line
     up with a run of the molar levels at one ratio (the molecular weight,
     within 1%), or the workbook is refused.
   It prints one JSON line per workbook: status, files written, units found.
2. **The genomic project.** When several chemicals share one BMDExpress
   project (NIEHS-07 … 10 come from one EPA PFAS kidney/liver project),
   `bmdx_pipe.subset_bm2(project, out, token)` runs the Java `SubsetBm2` helper
   to keep only the experiments whose names contain the chemical's token
   (`_PFHxSAm_`), and writes `<DTXSID>_genomic.bm2`. Otherwise the project is
   copied as it is.

With `FROM_PACKAGE = False` the cell copies the inputs the reference session
`sessions/<SOURCE>/` was built from instead: the long-format CSVs and units
files validation moved to its `_originals/`, plus the files it kept as they
were (the `.bm2` and the clinical-observation CSVs). For NIEHS-10 the two are
byte-identical; the conversion is checked by `tests/unit/test_cebs_to_pool.py`.

**Reads → writes.** `assets/cebs/<REPORT>/` → a temporary directory.
Nothing in the session yet.

**If it goes wrong.** A workbook `cebs_to_pool` can't read (status `error`)
fails the conversion, and the cell raises with its message. A workbook that
holds another study than its name says is left out (status `rejected`), and the
rest are converted. A workbook with no apical platform is `skipped`.
""")

_code(r"""
import shutil, tempfile

if OWN_DATA:
    INPUT_FILES = sorted(p for p in UPLOADS.iterdir() if p.is_file() and not p.name.startswith("."))
elif FROM_PACKAGE:
    inputs = Path(tempfile.mkdtemp(prefix=f"nb_{REPORT}_")) / "inputs"
    project_json = _project_json(REPORT)
    dose_args = ["--mg-per-kg-from", str(project_json)] if project_json else []
    run = subprocess.run([sys.executable, "-m", "tooling.cebs_to_pool", "--package", str(CEBS / REPORT),
                          "--out", str(inputs), *dose_args, *CONVERT_ARGS],
                         capture_output=True, text=True)
    for line in run.stdout.splitlines():
        r = json.loads(line)
        print(f"  {r.get('status', ''):5} {r.get('file', '')[:70]:70} → "
              + (", ".join(r.get("written") or []) or r.get("reason", ""))
              + (f"  ({r['units']} units)" if r.get("units") else ""))
    if run.returncode:
        raise RuntimeError(run.stderr[-2000:])
    project = CEBS / REPORT / BM2
    if BM2_TOKEN:
        from bmdx_pipe import subset_bm2
        subset_bm2(str(project), str(inputs / f"{SOURCE}_genomic.bm2"), BM2_TOKEN)
        print(f"  subset {project.name} to the experiments named {BM2_TOKEN!r}")
    else:
        shutil.copy2(project, inputs / project.name)
    INPUT_FILES = sorted(inputs.iterdir())
else:
    src = REFERENCE
    originals = sorted((src / "_originals").glob("*")) if (src / "_originals").is_dir() else []
    converted = {p.name.split(".")[0] for p in originals}   # stems validation derived pivots from
    INPUT_FILES = originals + sorted(p for p in (src / "files").iterdir()
                                     if p.is_file() and p.name.split(".")[0] not in converted)

print(f"\n{len(INPUT_FILES)} input files:")
for p in INPUT_FILES:
    print(f"  {p.name:60} {p.stat().st_size:>12,} bytes")
""")

# ---------------------------------------------------------------------------
_md(r"""
## 4. Import

**Purpose.** Put the study's files in the session. Importing is the
browser's *Upload* step: once files are in `sessions/<DTXSID>/files/`, the
session exists and its phase is `UPLOADED`.

**How it's implemented.** `generate_report.import_files(dtxsid, paths, store)`:

1. creates `sessions/<DTXSID>/files/` and copies each file in with
   `shutil.copy2` (contents and timestamps).
2. If the pool had already progressed (`pipeline.pool_state.pool_has_progressed`:
   it has a validation report or later), calls
   `pipeline.pool_state.invalidate_pool_artifacts`, exactly as an upload
   through the API does. That deletes what the old pool produced (validation
   report, integration, caches) and marks approved sections stale, so nothing
   built from the old files survives.

There is no upload registry: validation scans the directory. Import is the
one part of the arc not lifted into `workflow.steps` yet (the manual's §10).

Before importing, this cell builds `show_state()`, used by every later cell:
it constructs a `WorkflowEngine` over a `DiskPoolStore` and prints the derived
phase and legal actions (§0). With `RESEED = True` it first deletes
`sessions/<DTXSID>/`. If the session already has files, they are reused.

**Reads → writes.** The input files → `files/`.
""")

_code(r"""
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
    gr.import_files(DTXSID, INPUT_FILES, store)
show_state();
""")

# ---------------------------------------------------------------------------
_md(r"""
## 5. Validate

**Purpose.** Find out what every file is, and whether the files agree with
each other, before anything is merged. Integration trusts the classification
validation produces, so mistakes have to surface here.

**How it's implemented.** `workflow.steps.validate_step(dtxsid, store)`:

1. **Fingerprint every file.** `store.ensure_fingerprints(dtxsid, force=True)`
   → `pipeline.pool_fingerprints.ensure_fingerprints` scans `files/` for
   `.xlsx`, `.txt`, `.csv` and `.bm2` (anything else, such as `.units.json`, is
   skipped) and calls `fingerprint_and_store` → `bmdx_pipe.file_integrator.fingerprint_file`
   on each. Disk-scanned files get the id `scan-<filename>`. The fingerprint is
   a `FileFingerprint` record:
   - `file_type` and `tier` (1 = xlsx, the study team's raw data; 2 = txt/csv,
     derived tables; 3 = bm2, a BMDExpress analysis);
   - `platform` and `data_type` (`tox_study`, `inferred`, `gene_expression`),
     from the file name by an ordered list of regular expressions
     (`detect_platform_and_type`), or for a `.bm2` from its experiment names;
   - `sexes`, `dose_groups`, `dose_unit`, `species`, `study_number`,
     `endpoint_names`, `animal_ids`, `n_animals_by_dose`, `selection_groups`
     (core / biosampling) and `animals_by_dose_selection`, read from the
     contents.
   For a `.bm2`, the Java `ExportBm2` helper converts the binary project to
   JSON first (`bmdx_pipe.bm2_cache`, cached by file).
2. **Convert long-format files.** A long-format CSV (one row per animal) is
   converted to BMDExpress's wide pivot format at this point, so every later
   comparison sees one format: `bmdx_pipe.tox_study_csv_to_pivot_txt` writes
   one `<stem>.txt` (endpoints × animals, a `Dose` row) and one
   `<stem>.sidecar.json` per sex. The sidecar keeps what the pivot discards:
   each animal's selection (core or biosampling), observation day, terminal
   flag and raw values, plus the units from `<stem>.units.json`. The original
   CSV and units file move to `_originals/`, and the pivot is fingerprinted in
   their place.
3. **Validate the pool.** `bmdx_pipe.validate_pool(dtxsid, fingerprints)`:
   - `classify_derived_by_anchor` (ADR-0017) first: a derived table whose
     animals provably lost data against the study workbook is relabelled
     `inferred`. Only provable loss changes a label.
   - builds the **coverage matrix**: per `platform|data_type`, the file in each
     tier (`xlsx`, `txt_csv`, `bm2`).
   - Level 0, **roster consistency**: the `tox_study` files of one sex must
     agree on the animals, and every other file must be a subset
     (`roster_subset`, info when it is).
   - Level 1, **unassigned files**: a file with neither platform nor data type
     is an error (`unassigned_file`) and blocks everything.
   - per platform: `missing_tier` (a tier absent), `dose_mismatch` (files in
     one platform and sex disagree on doses), `animal_count_mismatch`,
     `sex_mismatch`; across the pool, `redundant_files`.
4. **Check values against their source.**
   `pipeline.value_validation.check_value_provenance` compares a derived CSV
   with the study workbook it came from, value by value; a divergence is an
   error. When there is no workbook to compare with (as here: the package's
   workbooks were converted, not imported), it adds an
   `unverified_derived_data` warning per platform instead.
5. Writes `validation_report.json`: the fingerprints, the issues, the coverage
   matrix and `is_complete`.

`generate_report.validate` logs each issue and stops on an error.

**Reads → writes.** `files/` → `files/*.txt`, `files/*.sidecar.json`,
`_originals/`, `_fingerprints.json`, `validation_report.json`.

**Phase.** `VALIDATED`, or `VALIDATION_ERRORS` with any error-severity issue.

**If it goes wrong.** Errors stop the workflow until the files are fixed and
validation runs again. Warnings and infos are expected for a converted
package: no workbook or apical `.bm2` tier, and animals that are in the study
roster but not in a given platform (biosampling animals, early deaths).
""")

_code(r"""
import collections

report = gr.validate(DTXSID, store)

fps = report["fingerprints"]
print(f"\n{'file':40} tier  {'platform':22} {'data type':16} {'sexes':13} doses  animals")
for fp in sorted(fps.values(), key=lambda f: f["filename"]):
    n = sum((fp.get("n_animals_by_dose") or {}).values()) or ""
    print(f"{fp['filename'][:40]:40} {fp['tier']:>4}  {str(fp['platform'])[:22]:22} "
          f"{str(fp['data_type'])[:16]:16} {','.join(fp.get('sexes') or [])[:13]:13} "
          f"{len(fp.get('dose_groups') or []):>5}  {n}")

print("\ncoverage matrix (platform|data type: files per tier)")
for key, tiers in report["coverage_matrix"].items():
    print(f"  {key:34} xlsx {'✓' if tiers['xlsx'] else '–'}   txt/csv {len(tiers['txt_csv'] or [])}   "
          f"bm2 {'✓' if tiers['bm2'] else '–'}")

kinds = collections.Counter((i["severity"], i["issue_type"]) for i in report["issues"])
print("\nissues:", ", ".join(f"{n} {sev} {kind}" for (sev, kind), n in sorted(kinds.items())))
moved = sorted(p.name for p in (session / "_originals").glob("*")) if (session / "_originals").is_dir() else []
print(f"converted long-format inputs (now in _originals/): {len(moved)}")
show_state();
""")

# ---------------------------------------------------------------------------
_md(r"""
## 6. Resolve conflicts

**Purpose.** When two files cover the same platform in the same tier (two
body-weight tables, say), integration can't know which one counts. A person
decides, once per conflict.

**How it's implemented.** `workflow.steps.resolve_step(dtxsid, issue_index, chosen_file_id, store)`
appends `{issue_index, chosen_file_id, resolved_at}` to `precedence.json`. It
changes nothing else. Integration (step 8) reads the list: for a platform with
a decision, the chosen file wins; otherwise the tier preference applies.

**Reads → writes.** `precedence.json` (appended).

This study has no conflicts, so the cell only lists them. The commented line
shows the call.
""")

_code(r"""
from workflow.steps import resolve_step

conflicts = [i for i in report.get("issues", []) if "conflict" in (i or {}).get("issue_type", "").lower()
             or (i or {}).get("issue_type") == "redundant_files"]
for index, issue in enumerate(conflicts):
    print(f"conflict {index}: {issue.get('message')}  files: {issue.get('files_involved')}")
    # resolve_step(DTXSID, index, "<the file id that should win>", store)
print(f"{len(conflicts)} conflict(s)")
""")

# ---------------------------------------------------------------------------
_md(r"""
## 7. Confirm the file classification

**Purpose.** Fingerprinting guesses each file's platform and data type from its
name. A person confirms the guess, or corrects it, before integration builds on
it. This is the browser's file-review panel.

**How it's implemented.**

1. `generate_report.confirm_metadata(dtxsid, corrections, store)` maps
   `CORRECTIONS`, keyed by **file name**, to file ids (file ids are minted per
   scan, so names are the stable key), logs every file's current
   classification, and calls:
2. `workflow.steps.confirm_metadata_step(dtxsid, {file_id: {platform, data_type}}, store)`:
   - sets the corrected fields on each named fingerprint;
   - for each corrected `.txt`/`.csv` file, rewrites its header with
     `_write_metadata_headers`: any leading `#` lines are replaced by
     `# Provider: Apical`, `# Platform: <platform>` and
     `# Data Type: <data type>`. BMDExpress's `ExperimentDescriptionParser`
     (Java) reads those lines at integration, so the classification travels
     inside the file into the merged project.
   - re-saves every fingerprint to `_fingerprints.json`.

Empty `CORRECTIONS` accepts the detection, as clicking through the panel does.
The pivots written in step 5 already carry these headers.

**Reads → writes.** `_fingerprints.json`; the headers of corrected files.
""")

_code(r"""
gr.confirm_metadata(DTXSID, CORRECTIONS or None, store)
print()
print("".join(open(session / "files" / sorted(p.name for p in (session / "files").glob("*.txt"))[0]).readlines()[:4]))
""")

# ---------------------------------------------------------------------------
_md(r"""
## 8. Integrate

**Purpose.** Merge the pool into **one** BMDExpress project, `integrated.json`,
the single source of truth every later step reads. From here on nothing reads
the raw input files.

**How it's implemented.** `generate_report.integrate` →
`workflow.steps.integrate_step(dtxsid, identity, store)`:

1. Loads the fingerprints, the coverage matrix and `precedence.json`; refuses
   (`StepError` 400) if validation hasn't run.
2. Writes `identity.json` (`{dtxsid, name, casrn}`), which names the test
   article for metadata inference, Methods and the title.
3. Reads `metadata_approved.json`, the experiment metadata a person approved
   for an earlier integration, which must win over re-inference.
4. Calls `bmdx_pipe.pool_integrator.integrate_pool`, which:
   1. **Chooses one source per platform.** A precedence decision first; else
      the tier preference `.bm2` > `.txt`/`.csv` > `.xlsx` (a BMDExpress
      analysis carries BMD results; a table carries only data).
   2. Sets **clinical observations** aside: they are categorical findings, not
      numbers, so they bypass Java and become incidence tables at report time
      (`_meta.clinical_obs_files`).
   3. Converts any chosen `.xlsx` to a pivot (`xlsx_to_pivot_txt`, into
      `_pivots/`).
   4. Runs the Java merge: `java -cp <classpath> IntegrateProject --output … --bm2 … --txt …`.
      BMDExpress's own `ProjectUtilities` and `ExperimentFileUtil` load each
      project and table and combine them into one `BMDProject`. Jackson writes
      it as JSON (NaN → null).
   5. Adds `_meta`: the chosen file per platform (`source_files`), the study
      workbooks' animal rosters (`xlsx_rosters`), the clinical-observation files.
   6. Runs the Java `ExportCategories` for the category analyses' lookup table
      and writes it beside the project as `_category_lookup.json` (it can run
      to 10+ MB, so it's kept out of `integrated.json`).
   7. **Infers each experiment's metadata** (`bmdx_pipe.experiment_metadata.infer_experiment_metadata`):
      one LLM call over every experiment's name, source file and endpoint
      names, at temperature 0, validated against the controlled vocabularies.
      It fills `experimentDescription` (platform, provider, sex, organ,
      species, strain, route, vehicle, duration, test article). If the LLM is
      unavailable it logs and leaves the descriptions empty.
   8. Lays the approved metadata over the inferred (`_apply_approved_metadata`).
   9. Runs the Java `ExportGenomics` on the genomic `.bm2` and writes
      `genomics.sidecar.json`: per-gene BMDs and the GO category analyses,
      extracted once here so Process never reopens the raw upload. Then
      `reconcile_genomics_sidecar` corrects each section's organ and sex from
      the experiment metadata (the Java side parses them from the name).
   10. Writes `integrated.json`, and `integrated.bm2` through the Java
       `JsonToBm2` (the same project, openable in BMDExpress 3).
5. Back in `integrate_step`:
   - `reapply_study_design`: lays `study_design.json` (step 9) over every
     experiment and re-exports `integrated.bm2`, because inference just
     rewrote the descriptions.
   - `pipeline.sidecar_units.stamp_sidecar_units`: units onto the sidecars from
     any study workbook in the pool.
   - deletes every `_cache_*.json`, `session.duckdb` and `session_parquet/`:
     the data under them changed.
   - `_pin_and_check_method`: pins the newest method profile if the study has
     none (`pipeline.method_profile.ensure_pin`), and adds a `method_mismatch`
     warning to the validation report for every analysis setting the `.bm2`
     records differently from the profile.

Integrating again wipes every Process cache, so this cell skips when the
session is already integrated, as the command line does without
`--reintegrate`. It still rewrites `identity.json`.

**Reads → writes.** `files/`, `_fingerprints.json`, `validation_report.json`,
`precedence.json`, `metadata_approved.json`, `study_design.json` →
`integrated.json`, `integrated.bm2`, `_category_lookup.json`,
`genomics.sidecar.json`, `identity.json`, `method_profile.json`.

**Phase.** `INTEGRATED`.

**If it goes wrong.** A Java failure raises `StepError` 500 with the message.
The usual causes are the environment in step 1: no JDK 21, or no
`BMDX_PROJECT_ROOT`.
""")

_code(r"""
from pipeline.integrated_io import load_integrated

from types import SimpleNamespace

# The stated name and CASRN over identity.json; neither: resolved from the DTXSID
# (PubChem/CTX, best effort), as the command line does.
identity = gr._resolve_identity(DTXSID, SimpleNamespace(name=NAME, casrn=CASRN), store)
REINTEGRATE = RESEED

if store.artifact_exists(DTXSID, "integrated.json") and not REINTEGRATE:
    store.write_json(DTXSID, "identity.json", identity)
    print("already integrated — skipped (REINTEGRATE = True re-runs it and recomputes everything)")
else:
    gr.integrate(DTXSID, identity, store)

integrated = load_integrated(DTXSID)
print("\nsource chosen per platform:")
for key, src in integrated["_meta"]["source_files"].items():
    print(f"  {key:34} {src['tier']:8} {src['filename']}  ({src.get('file_count')} file(s))")
print(f"\n{len(integrated['doseResponseExperiments'])} experiments, "
      f"{len(integrated.get('bMDResult') or [])} BMD analyses, "
      f"{len(integrated.get('categoryAnalysisResults') or [])} category analyses")
for e in integrated["doseResponseExperiments"]:
    d = e.get("experimentDescription") or {}
    print(f"  {e['name'][:34]:34} {str(d.get('platform'))[:20]:20} {str(d.get('organ')):12} "
          f"{str(d.get('sex')):7} {len(e.get('probeResponses') or []):>6} endpoints/probes")
for name in ("integrated.json", "integrated.bm2", "_category_lookup.json", "genomics.sidecar.json"):
    p = session / name
    print(f"  {name:24} {p.stat().st_size if p.exists() else 0:>12,} bytes")
show_state();
""")

# ---------------------------------------------------------------------------
_md(r"""
## 9. State what the data doesn't record

**Purpose.** Some facts a report states are in none of the files: how the
chemical was given, what it was dissolved in, which strain was used, who wrote
the report. A person states them, and each is kept in the session so that
every later integration puts it back (integration re-infers the experiment
metadata from scratch each time).

**How it's implemented.**

- **Study design**, `generate_report.apply_design(dtxsid, DESIGN, store)` →
  `workflow.steps.record_study_design`: writes `study_design.json`
  (`{fields, recorded_at}`), and calls
  `workflow.steps.reapply_study_design`, which sets the fields on every
  experiment's `experimentDescription` (`apply_design_fields`), saves
  `integrated.json` and re-exports `integrated.bm2`. Without a stated design,
  the report uses the standard design (Sprague Dawley rats, gavage in corn oil,
  5 days; inhalation for a ppm study) and says so in the log
  (`pipeline.study_design`).
- **Experiment metadata**, `generate_report.apply_experiment_metadata(dtxsid, EXPERIMENT_METADATA)`:
  `pipeline.metadata_approval.approve_experiment_metadata(dtxsid, given, merge=True)`
  lays it over the descriptions and records it as the approval in
  `metadata_approved.json`, the same record the browser's approval writes.
  NIEHS-10's project names its experiments by organ and sex, so it states none.
- Both are written **as given** here. The app and the command line first
  check them (`safeguards.inputs`): the study must have a dataset, every
  experiment must be the dataset's, and every field and value the controlled
  vocabulary's (`pipeline.study_design.design_field_errors`,
  `bmdx_pipe.VOCABULARIES`); a refusal writes nothing.
- **Front matter**, `generate_report.apply_front_matter(dtxsid, FRONT_MATTER, store)`:
  merges the given keys over the saved `front_matter.json` and cleans it
  (`rendering.front_matter.clean_front_matter`), as the Configure screen saves
  it. NIEHS-10's title prints the strain as "Sprague Dawley (Hsd:Sprague Dawley® SD®)".
- **The data deposit**, `pipeline.deposit.record_deposit(dtxsid, DEPOSIT, BOOK_OWN_FILES)`:
  lists the files deposited with the report: the Bookshelf package less the
  book's own files (its XML, figures, `TOC.pdf`, licence). Each file gets a
  kind read from its name (apical, genomic, study tables, animal data, methods,
  internal dose, software) and a caption; a study's
  `templates/studies/<id>/deposit.yaml` can override both. Writes
  `deposit.json`, which the Supplemental Data appendix lists. The
  appendix gives the deposit's address: its DOI when `deposit.yaml` states
  one (every file's link then points there), else the session's local folder
  `sessions/<id>/supplemental/`, served at
  `http://127.0.0.1:9000/api/sessions/<id>/supplemental/` (`BMDX_LOCAL_URL`
  overrides the host) until the publishing package gives the real address
  (`pipeline.deposit.deposit_address`). A new study with no deposit of its own
  lists that folder's files.
- **The empirical FDR**, `genomics.efdr.record_efdr(dtxsid, zips)`, when the
  deposit holds synthetic-null analyses (`*_eFDR_Synthetic_Null_Analysis*.zip`,
  NIEHS-12/13 only; NIEHS-10 has none). For each `.bm2` in them the Java
  `ExportCategories` and `ExportBm2` helpers read the null experiments; per
  experiment, the gene eFDR is the genes passing the gene-level filters over
  the genes analysed (that universe recovered exactly from a one-gene
  category's Fisher tail), and the GO eFDR counts the processes passing the
  method profile's `go_display` criteria. Writes `efdr.json`, which Appendix D.2
  reads (step 15).
- **The short name**, `generate_report.record_abbreviation(dtxsid, SHORT_NAME, store)`:
  `identity.json`'s `abbreviation`, the name the sentences written from the
  tables use (step 15). Step 8 rewrote `identity.json`, so it is recorded
  here, after it, as the command line keeps it across integrations.

**Reads → writes.** → `study_design.json`, `metadata_approved.json`,
`front_matter.json`, `identity.json`, `deposit.json`, `efdr.json`;
`integrated.json` and `integrated.bm2` updated.
""")

_code(r"""
from pipeline.deposit import record_deposit

if DESIGN:
    gr.apply_design(DTXSID, DESIGN, store)
else:
    print("  no design stated: the report uses the standard design and says so")
if EXPERIMENT_METADATA:
    gr.apply_experiment_metadata(DTXSID, EXPERIMENT_METADATA)
if FRONT_MATTER:
    gr.apply_front_matter(DTXSID, FRONT_MATTER, store)
if SHORT_NAME:
    gr.record_abbreviation(DTXSID, SHORT_NAME, store)
if DEPOSIT:
    manifest = record_deposit(DTXSID, DEPOSIT, tuple(BOOK_OWN_FILES))
    kinds = collections.Counter(f.get("kind") for f in manifest["files"])
    print(f"  deposit: {len(manifest['files'])} file(s) from {DEPOSIT}: "
          + ", ".join(f"{n} {k}" for k, n in sorted(kinds.items(), key=lambda kv: str(kv[0]))))
    from genomics.efdr import ZIP_PATTERN, record_efdr
    nulls = sorted(DEPOSIT.glob(ZIP_PATTERN))
    if nulls:
        efdr = record_efdr(DTXSID, nulls)
        print(f"  eFDR: {len(efdr['tissues'])} species-tissue(s) from {len(nulls)} null analysis file(s)")
    else:
        print("  eFDR: no synthetic-null analyses in the deposit")
d = load_integrated(DTXSID)["doseResponseExperiments"][0]["experimentDescription"]
print("  first experiment now:", {k: d.get(k) for k in ("species", "strain", "articleRoute",
                                                         "administrationMeans", "articleVehicle", "studyDuration")})
""")

# ---------------------------------------------------------------------------
_md(r"""
## 10. Method profile and document definition

**Purpose.** Fix what the study is reported under: the analysis method, and
the document the report is written to. Both changed between report eras, so
both are versioned declarations rather than code, and a session pins each.

The method (which statistical tests, which BMD engine and acceptance rules,
which GO ranking and cutoffs, how the eFDR's null data were made, and the
Methods text that describes them) is a named **profile** (ADR-0027):
`profiles/ntp-5day-2021.yaml` for NIEHS 07 … 10; `ntp-5day-2025.yaml` and
`ntp-5day-2025.1.yaml` for NIEHS-12/13 (2025.1 is the same method with
`genomics.efdr` stated, and is the newest). Profiles are immutable: a revised
record is a new file, and a section added to the schema after a profile was
written resolves as "to confirm" for it.

**How it's implemented.** `generate_report.method_profile(dtxsid, METHOD_PROFILE)`:

1. `pipeline.method_profile.pin_profile(dtxsid, name, by="user")` writes the
   **pin**, `method_profile.json`: the profile's name, a hash of its content,
   the mode (`fixed` stays on this profile; `track` follows the newest of its
   series, the default for a study nobody pinned), who pinned it and when.
   Integration already pinned the newest one (`ensure_pin`); this replaces it.
2. `session_method(dtxsid)` → `resolve(...)` builds the settings in layers:
   the built-in defaults, then the profile, then the study's overlay (the
   `methods:` block of `templates/studies/<id>/view.yaml`), then a request's
   own settings (`PROCESS_OVERRIDES`). Each value remembers which layer set it.
   The schema is closed: an unknown key is an error.
3. `_substitute_unimplemented`: a value naming an implementation this tool
   lacks, or one that can't run on this machine, is replaced by the default and
   recorded as a **deviation**. NIEHS-10's profile asks for two:
   - `apical.bmd.engine: bmds_2_7_high_dose_drop`, NTP's modified BMDS 2.7. The
     package is vendored (`pipeline/bmds27`) but runs under Wine, and is used
     only once its certification passes on this machine; otherwise the ToxicR
     model average is used.
   - `apical.bmd.eligibility: all_endpoints` (model every endpoint) is not
     implemented; endpoints with a significant trend or pairwise test are
     modelled.
4. `recorded_mismatches(integrated, method)` compares what the `.bm2`'s
   analyses record (BMR, model selection, …) with the profile, and warns on
   each difference.

The settings' signature is part of every Process cache key, so re-pinning a
profile recomputes what depends on it.

**The document definition** (ADR-0029 §12),
`generate_report.document_definition(dtxsid, DOCUMENT_DEFINITION)`:

1. Which definition: the study's own (`templates/studies/<DTXSID>/document.yaml`,
   its era plus alterations), else the definition of a new study,
   `templates/eras/niehs-2026.yaml` (the 2026 books, ADR-0029 §10;
   `document_definition.current_definition_name`). The scratch session has no
   definition of its own, so it gets the 2026 one (step 15).
2. `document_model.definition_pin.ensure_pin` (or `pin_definition` with a
   mode) composes it (every `extends` resolved), hashes it and writes the pin,
   `document_definition.json` (name, hash, mode, who, when), with the composed
   definition beside it as `document_definition.yaml`.
   - **track** (the default): the report renders from the current templates;
     when the definition changes, the next pin records it and keeps the old
     pin and snapshot in `history/_document_definition/`.
   - **fixed**: the report renders from the snapshot, whatever the templates
     say later (`definition_name` gives `@pinned/<id>`, which the template
     loader reads from the session). `drift` says when the templates have
     moved on; an edited snapshot is refused; fixing again takes them up.

**Reads → writes.** `profiles/<name>.yaml`, `templates/…` →
`method_profile.json`, `document_definition.json`, `document_definition.yaml`.
""")

_code(r"""
from pipeline.method_profile import session_method

gr.method_profile(DTXSID, METHOD_PROFILE)
gr.document_definition(DTXSID, DOCUMENT_DEFINITION)
settings = session_method(DTXSID).to_json()["settings"]
print(f"\n{len(settings)} resolved settings (value — the layer that set it):")
for path, s in settings.items():
    print(f"  {path:48} {str(s['value'])[:46]:46} {s['source']}")
""")

# ---------------------------------------------------------------------------
_md(r"""
## 11. Approve the data: the animal report

**Purpose.** Account for every animal before any result is computed: which
dose and sex each one had, which cohort it was in (core or biosampling), and
which files and tiers it appears in. A count that differs between files has to
be explained (an early death, a biosampling animal, a sample removed in QC)
before the numbers can be trusted. Generating the report is the browser's
*Approve* button; it ends the data-preparation arc.

**How it's implemented.** `workflow.steps.generate_animal_report_step(dtxsid, store)`
→ `bmdx_pipe.animal_report.build_animal_report(session_dir, fingerprints)`. It
reads the animal ids out of every file (`_extract_animals_from_xlsx`,
`_extract_animals_from_txt_csv`, `_extract_animals_from_bm2`) and builds five
parts:

- **A. Study design**: dose × sex × cohort counts (`dose_design`, `dose_groups`,
  `core_count`, `biosampling_count`).
- **B. Animal roster**: every animal, with its presence per platform and tier.
- **C. Domain coverage**: animals per platform per tier.
- **D. Attrition**: who drops out between tiers, and the reason
  (`_classify_exclusions`: a dose group left out, a biosampling animal, QC).
- **E. Consistency**: an animal whose sex or dose differs between platforms.

`report_to_dict` turns it into `animal_report.json`.

Two things to know when reading it. Gene-expression samples are identified by
plate well (`Plate5-116`), not by animal number, so they are counted as
animals of their own: NIEHS-10's 301 = 122 study animals + 179 samples. And
the biosampling count reads 0, because the pivots it reads don't keep the
cohort column (the sidecars do, and the tables use them; gap G9 in the
manual).

**Reads → writes.** `files/`, `_fingerprints.json` → `animal_report.json`.

**Phase.** `APPROVED`.
""")

_code(r"""
gr.animal_report(DTXSID, store)
ar = store.read_json(DTXSID, "animal_report.json") or {}
print("  dose groups:", ar.get("dose_groups"))
print("  animals per dose and sex:")
for dose, by_sex in ar.get("dose_design", {}).items():
    print(f"    {dose:>8}  " + "  ".join(f"{s} {n}" for s, n in sorted(by_sex.items())))
print("  animals per platform and tier:")
for platform, tiers in ar.get("domain_coverage", {}).items():
    print(f"    {platform:22} " + "  ".join(f"{t} {n}" for t, n in tiers.items()))
print("  consistency issues:", len(ar.get("consistency_issues") or []))
show_state();
""")
