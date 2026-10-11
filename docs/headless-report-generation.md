# Generating reports without the web UI

This manual covers two ways to take a study's data files to a finished report
without opening the browser:

- **Route A: Python.** Run the pipeline in-process. One command,
  `python -m tooling.generate_report`, wraps every step. You can also call the
  step functions yourself from a script or notebook.
- **Route B: HTTP API.** Drive a running server with `curl`. The script
  `tooling/generate_report_api.sh` makes the same calls the browser makes, in
  the same order.

Both routes run the same code as the web UI. Every step function lives in
`workflow/steps.py` (ADR-0014). The web routes are thin wrappers around those
functions, and the Python route calls them directly. Both routes read and write
the same session folder, `sessions/<DTXSID>/`. So a session built one way can be
continued the other way, or opened in the browser.

---

## Contents

1. [The pipeline at a glance](#1-the-pipeline-at-a-glance)
2. [Prerequisites](#2-prerequisites)
3. [Input files](#3-input-files)
4. [Route A — Python](#4-route-a--python)
5. [Route B — HTTP API with curl](#5-route-b--http-api-with-curl)
6. [Outputs](#6-outputs)
7. [Approval and the publish gate](#7-approval-and-the-publish-gate)
8. [Re-running, caching and resetting](#8-re-running-caching-and-resetting)
9. [Troubleshooting](#9-troubleshooting)
10. [Known gaps](#10-known-gaps)
- [Appendix A. Render surfaces](#appendix-a-render-surfaces)
- [Appendix B. What in the report comes from the data](#appendix-b-what-in-the-report-comes-from-the-data)
- [Appendix C. The YAML files and what they can do](#appendix-c-the-yaml-files-and-what-they-can-do)

---

## 1. The pipeline at a glance

| # | Step | What it does | Python (`workflow.steps`) | HTTP |
|---|------|--------------|---------------------------|------|
| 1 | **Import** | Puts input files into `sessions/<id>/files/` | copy files in (see 4.2) | `POST /api/upload-bm2`, `POST /api/upload-csv` |
| 2 | **Validate** | Fingerprints every file and cross-checks doses, animals, sexes and coverage. Writes `validation_report.json` | `validate_step` | `POST /api/pool/validate/{id}` |
| 2b | Resolve *(optional)* | Picks which file wins when two files cover the same platform | `resolve_step` | `POST /api/pool/resolve` |
| 3 | **Confirm metadata** | Accepts or overrides each file's detected `(platform, data_type)` | `confirm_metadata_step` | `POST /api/pool/confirm-metadata/{id}` |
| 4 | **Integrate** | Uses Java (BMDExpress 3) to merge the pool into `integrated.json`, the single source of truth | `integrate_step` | `POST /api/pool/integrate/{id}` |
| 5 | **Approve data** | Builds the per-animal traceability report, `animal_report.json` | `generate_animal_report_step` | `POST /api/generate-animal-report/{id}` |
| 6 | **Process** | Runs NTP statistics, BMDS modelling, genomics, charts, LLM narratives and Materials & Methods. Takes minutes on a first run | `process_step` (async) | `POST /api/process-integrated/{id}` |
| 7 | **Materialize sections** | Writes the apical result sections as `bm2_*.json` drafts | `materialize_result_sections` | `POST /api/pool/materialize-sections/{id}` |
| 8 | Background *(optional)* | LLM Background section, built from ATSDR, IRIS and PubChem lookups | see 4.2 | `POST /api/generate` (SSE) + `POST /api/session/save-section` |
| 8b | Summary | Built from the session's results (`narrative.report_summary`, deterministic); never replaces an approved or hand-written summary | `workflow.steps.materialize_summary` (run by `generate_report` after Process/Background) | `POST /api/generate-summary` (LLM variant) + `POST /api/session/save-section` |
| 9 | **Render** | Builds the docx, HTML, BITS/JATS XML, Bookshelf HTML, LaTeX bundle and PDF | `rendering.preview_surface.render_preview` | `POST /api/preview/{id}/materialize` + `GET …/download` |

You never set the workflow phase yourself. It is worked out from which files
exist on disk (`EMPTY → UPLOADED → VALIDATED → INTEGRATED → APPROVED`, with a
`VALIDATION_ERRORS` branch). To check it at any point:

```bash
curl -s localhost:9000/api/workflow/$ID/state | jq '{phase, legal_actions}'
```

```python
from workflow.engine import WorkflowEngine
WorkflowEngine("DTXSID50469320").state().to_dict()
```

---

## 2. Prerequisites

Both routes need the same environment, because both run the same pipeline
(Route B runs it inside the server process).

| Need | Why | How |
|------|-----|-----|
| Repo + venv | All the code | `uv sync`. Run everything **from the repo root**: the knowledge base `bmdx.duckdb` and the templates are found relative to the current directory |
| **JDK 21** first on `PATH` | Integration and statistics call compiled Java helpers (class version 65). On JDK 17 they fail with `UnsupportedClassVersionError` | `/opt/liberica-jdk-21/bin` in the sandbox |
| `BMDX_PROJECT_ROOT` | Tells the Java bridge where to find the BMDExpress-3 jars (`$BMDX_PROJECT_ROOT/target/*.jar`) | `/workspace/BMDExpress-3` in the sandbox |
| `ANTHROPIC_API_KEY` (+ `ANTHROPIC_BASE_URL`) | LLM narratives, Methods, Background, Summary | Toxpipe LiteLLM gateway |
| `SSL_CERT_FILE` | The toxpipe gateway uses the NIH CA chain. The Python SDK reads `SSL_CERT_FILE`, not `NODE_EXTRA_CA_CERTS` | `/usr/local/share/ca-certificates/extra/nih-ca-bundle.crt` |
| `BMDX_ALLOW_ENRICHR=1` *(optional, published data only)* | Labels the genomics cluster chart with Enrichr terms. Enrichr is a **public** service, so this sends each cluster's gene list off the NIEHS network. Off by default: clusters are labelled with the study's own GO terms. Never set it for an unpublished study | Unset |
| `tect` *(optional)* | Builds the local LaTeX PDF (`pdf` surface in Route A) | Baked into the sandbox. Never use plain `tectonic` |
| LibreOffice `docx2pdf` *(optional)* | PDF over HTTP (`GET /Bookshelf/{id}/report.pdf`) | Baked into the sandbox |

You don't need to export most of this by hand:

- **Route A:** `tooling/generate_report.py` fills in the JDK, `BMDX_PROJECT_ROOT`
  and `SSL_CERT_FILE` defaults itself. Values you set in your shell take
  precedence.
- **Route B:** start the server with `./run-server.sh`, which sets the same env
  and also reads the API key from `~/.claude/settings.json`.

> **Data policy.** Which data may go to which LLM depends on whether the study
> has been published (see the dev/test/prod split). Unpublished study data must
> only reach the walled **toxpipe** gateway, never a public model endpoint. The
> app's egress guard enforces toxpipe-only. Don't work around it by pointing
> `ANTHROPIC_BASE_URL` somewhere else.

---

## 3. Input files

These are the same files you would drop on the Upload step:

| File | Example | Notes |
|------|---------|-------|
| BMDExpress project | `PFHxSAm_Gene_Expression.bm2` | Genomic and/or apical BMD results |
| BMDExpress text exports | `Liver_PFHxSAm_Male_GENE_BMD_Results.txt`, `…_GO_Biological_Process_BMD_Results.txt`, `…_Expression_Data.txt` | Gene-expression tier |
| NTP long-format ("truth") tables | `body_weight_truth_male.csv`, `organ_weights_truth_male.csv`, `clin_chem_truth_female.csv` | One row per animal. Converted on import to a wide BMDExpress pivot `.txt` plus a per-animal `.sidecar.json`. The original moves to `_originals/` |
| Wide pivots + sidecars | `body_weight_truth_female.txt` + `body_weight_truth_female.sidecar.json` | Already-converted form. Import both |
| NTP study workbooks | `*.xlsx` | Raw study-team data, used to cross-check derived values |

Classification (platform and `tox_study` vs `inferred` vs `gene_expression`)
is detected from the file's name and contents. Check it at the
confirm-metadata step and override it if it's wrong (4.1 `--metadata`,
5.3 step 3).

**Published CEBS packages.** `tooling/cebs_to_pool.py` converts a CEBS NIEHS
data package (the Individual Animal workbooks plus expression files) into
these pool inputs:

```bash
python -m tooling.cebs_to_pool --package assets/cebs/NIEHS-13 \
    --prefix 108020004 --out /tmp/niehs13_inputs \
    --bundle assets/cebs/_bookshelf/NIEHS-13
```

`--bundle` also converts the workbooks of the report's Bookshelf bundle.
NIEHS-12 and -13 publish their blood and tissue concentrations only there, as
the lab's results workbook. The sheet for the package's species is the one
converted.

`--mg-per-kg-from PROJECT.json` handles RR-8 and NIEHS-02 … 06, which record
apical doses in mmol/kg. It converts each dose to the genomic project's mg/kg
level, provided the levels share one ratio (the molecular weight). The
converter exits non-zero if any workbook fails.

**Every downloaded study at once.** `tooling/build_published_reports.py` builds
a report for each published package (RR-8, NIEHS-02 … 10, 12, 13) into
`sessions/<DTXSID>` and `output/<DTXSID>`, so each one is on the Bookshelf. It
uses the design, strain designation, genomic tissue/sex and method profile the
published report states. NIEHS-12 and 13 report a rat study and a mouse study:
each study is built in its own session (`<DTXSID>_rat`, `<DTXSID>_mouse`), and
the report session lists them (`--studies`, below). Each build starts from a fresh session: the old one
moves to `output/_session_backups/` and a Background written on the host is
kept. `tooling/report_qc.py` then checks the rendered deliverables, including
against the published tables and the published book's structure, and writes
`output/QC/qc-report.md`. `tooling/bits_structure.py` prints the structure
diff alone (`-` published only, `+` ours only), and `tooling/bookshelf_preview.py`
renders a published bundle through our Bookshelf facsimile for a side-by-side
read:

```bash
python -m tooling.build_published_reports --jobs 3      # or name reports: RR-8 NIEHS-10
python -m tooling.report_qc                             # every report on the shelf
python -m tooling.bits_structure DTXSID50469320         # outline vs the published NIEHS-10
python -m tooling.bookshelf_preview assets/cebs/_bookshelf/NIEHS-10 -o output/NIEHS-10-published.html
```

---

## 4. Route A — Python

### 4.1 One command: `tooling.generate_report`

```bash
cd /workspace/rlm-bmdx
python -m tooling.generate_report DTXSID50469320 \
    --files /data/pfhxsam/*.bm2 /data/pfhxsam/*.txt /data/pfhxsam/*.csv \
    --name "Perfluorohexanesulfonamide" --casrn 41997-13-1 \
    --compound-name PFHxSAm --dose-unit mg/kg \
    --surfaces docx,html,jats,latex,pdf
```

This imports the files, then runs validate → confirm metadata → integrate →
animal report → process → materialize sections → render. It prints each step
and how long it took. The deliverables are written to `output/<DTXSID>/`
(change this with `--out`):

```
output/DTXSID50469320/
  DTXSID50469320.docx            Word deliverable
  DTXSID50469320.html            HTML preview
  DTXSID50469320.xml             BITS <book> XML (Bookshelf submission)
  DTXSID50469320-overleaf.zip    Overleaf bundle (report.tex + niehs.cls + figures/)
  DTXSID50469320.pdf             that bundle compiled locally with tect
```

A first ("cold") run takes several minutes; BMDS dose-response modelling
dominates. Every processing layer is cached by its inputs, so a second run on
the same session finishes in seconds.

**Options**

| Option | Meaning |
|--------|---------|
| `DTXSID` (positional) | Session id. The folder is `sessions/<DTXSID>/`. Any `DTXSID…` id of letters, digits, `_` or `-` is accepted |
| `--files F …` | Import these files first. Leave it out to use the files already in the session. Adding files to a session that has already progressed invalidates its downstream artifacts, just like an upload |
| `--name`, `--casrn` | Test-article identity. If you don't give them, `identity.json` is used. If that has no name, the script tries the PubChem/CTX resolver (needs network) |
| `--compound-name` | Short name used in captions and narratives (default: the identity name) |
| `--dose-unit` | The study's dose unit, used on every surface: table headers, Methods, Abstract, Summary, the report's Appendix B roster and the LLM narratives. **State it explicitly.** If you leave it out, the unit the data records is used, else `mg/kg`, and the log says which (`dose unit: ppm (stated)`). A concentration in air (`ppm`, `ppb`, `mg/m3`) makes it an inhalation study: "exposed to … by inhalation", "exposure concentrations", "chamber control", title "(Inhalation Studies)", and no vehicle or dose formulations |
| `--metadata FILE.json` | Classification overrides, keyed by **filename**: `{"organ_weights_truth_male.txt": {"platform": "Organ Weight", "data_type": "tox_study"}}` |
| `--design FILE.json` | Study-design facts the data does not record, set on every experiment's metadata (as the UI metadata step does) and kept in `sessions/<id>/study_design.json`, so every later integration (`--reintegrate`) puts them back: `{"strain": "Sprague-Dawley", "administrationMeans": "gavage", "articleVehicle": "corn oil"}`. Fields: `species`, `strain`, `articleRoute`, `administrationMeans`, `articleVehicle`, `studyDuration`, controlled vocabulary only. A fact the metadata does not record takes the standard design as a **fallback**: Sprague Dawley rats for five days (`studyDuration`, e.g. `"28d"`, overrides it), by gavage in corn oil for an oral (mg/kg) unit, by inhalation for an air concentration (ppm), no route fallback for other units. These facts also set the apical table captions: "…of Male Rats Administered X for Five Days", or "Exposed to X" for inhalation. The log prints `NOTE: not recorded in the data, standard design used: …`; record the real values with `--design` whenever they differ. Recorded values that disagree across experiments get no fallback. Facts the data never holds (animal source, quarantine, test-article lot and purity, dose rationale) appear as a `[Placeholder: …]` in Materials and Methods, which `--strict` refuses to ship |
| `--experiment-metadata FILE.json` | Experiment metadata the data doesn't record, as `{experiment name: {field: value}}` (vocabulary-checked), e.g. `{"EDHP mg_kg": {"organ": "liver", "sex": "male"}}` for a genomic experiment named by chemical and unit. The fields are laid over the named experiments and kept as the metadata approval (`metadata_approved.json`), the same record the browser's approval writes, so every later integration re-applies them |
| `--studies KEY=SESSION…` | A report over several studies (ADR-0029 §9), e.g. `rat=DTXSID1020431_rat mouse=DTXSID1020431_mouse`: each member is a study session built on its own first. Recorded as the session's `studies.json`; the report renders from them (implies `--render-only`). Combined tables group rows by study ("Rats" / "Mice") on the union of the studies' dose levels (NA where a study did not test a level); sections the definition repeats per study (`repeat: study_species`) render from that study's data |
| `--deposit DIR` | The study's data deposit: the supplemental files deposited with the report. Recorded as the session's `deposit.json` (each file's size, kind and species, read from its name); the Supplemental Data appendix lists them, one section per kind (and, in the 2026 books, per species). `--deposit-exclude GLOB…` leaves out files in `DIR` that are not deposited (`build_published_reports` passes the Bookshelf package less the book's own XML, figures, `TOC.pdf`, `license.txt`, `SOURCE.txt`) |
| `--front-matter FILE.json` | Front matter, as the Configure screen saves it to `front_matter.json`: `authors`, `contributors`, `publication` (`report_number`, `doi`, `report_date`) and `strain_designation`, the supplier designation the title prints after the strain, e.g. `{"strain_designation": "(Hsd:Sprague Dawley® SD®)"}`. Keys the file gives replace the saved ones |
| `--method-profile NAME` | The analysis method profile (`profiles/<name>.yaml`, ADR-0027): test family per platform, thresholds, BMD acceptance, internal-dose rules, GO ranking. `NAME` fixes the study on that profile; `newest` makes it track the newest profile as profiles are added, which is also the default for a study with no pin. A change of profile archives the old pin and recomputes. The log prints the profile, anything it asks for that the tool does not implement (`NOTE`), and every setting a `.bm2` analysis records differently (`WARNING`, also a `method_mismatch` in the validation report) |
| `--bmd-stats`, `--go-pct`, `--go-min-genes`, `--go-max-genes`, `--go-min-bmd` | GO gene-set table settings for this run, overriding the method profile's (ntp-5day-2025: `fifth_pct,median`, 5, 20, 500, 3). Omit them to use the profile |
| `--reintegrate` | Run integration again even though `integrated.json` exists. This wipes the process caches, so processing starts from scratch. Without the flag, integration is skipped when `integrated.json` is already there |
| `--background` | Also generate and save the Background section (LLM over ATSDR, IRIS and PubChem; needs network). `--model` picks the model |
| `--stop-after validate\|integrate\|process` | Stop after that step and render nothing |
| `--render-only` | Skip the pipeline and render the session as it is now on disk |
| `--surfaces` | Comma-separated list from `docx, html, jats, bookshelf, bits, latex, pdf` (default `docx,html`) |
| `--view NAME` | Render a saved report view (its filters and chart selection). Default: the default view |
| `--strict` | `latex`/`pdf` only: refuse to build while any `[… pending]` placeholder remains. This is the check the Overleaf export route applies |
| `--draft` | Render even when the publish gate is closed (see §7) |
| `-v` | Show pipeline logging, including per-cache `provenance` events |

The script exits non-zero and prints the reason when a step fails. Examples:
validation reports errors, a step raises `StepError`, or the publish gate is
closed.

**Common recipes**

```bash
# Check the inputs only (validation report and detected classification)
python -m tooling.generate_report DTXSID50469320 --files in/* --stop-after validate

# Session already processed (e.g. in the browser): just produce the deliverables
python -m tooling.generate_report DTXSID50469320 --render-only --surfaces docx,pdf,jats

# Correct a misclassified file, then rebuild everything from scratch
python -m tooling.generate_report DTXSID50469320 --metadata fixes.json --reintegrate
```

### 4.2 Step by step: calling the workflow core yourself

If you want different wrapping (a batch over many studies, a custom stopping
point, extra checks), call the steps directly. This is exactly what
`generate_report.py` does, without its argument handling. Set up the env first,
as in §2, or copy `_bootstrap_env()`. `bmdx_pipe` reads `BMDX_PROJECT_ROOT` at
import time, so it must be set before the first import.

```python
import asyncio, shutil
from pathlib import Path

from workflow.store import DiskPoolStore
from workflow.engine import WorkflowEngine
from workflow.steps import (
    validate_step, confirm_metadata_step, integrate_step,
    generate_animal_report_step, process_step, materialize_result_sections,
)
from rendering.preview_surface import render_preview

ID = "DTXSID50469320"
store = DiskPoolStore()

# 1. Import: copy inputs into files/. Validation's disk scan fingerprints them
#    (and converts long-format CSVs), so no upload call is needed.
files = store.session_dir(ID) / "files"
files.mkdir(parents=True, exist_ok=True)
for p in Path("/data/pfhxsam").iterdir():
    shutil.copy2(p, files / p.name)

# 2. Validate: stop on error-severity issues
report = validate_step(ID, store)
assert not [i for i in report["issues"] if i.get("severity") == "error"]

# 3. Confirm metadata: {} accepts what was detected.
#    Keys are file ids from store.get_fingerprints(ID).
confirm_metadata_step(ID, {}, store)

# 4. Integrate (Java)
integrate_step(ID, {"name": "Perfluorohexanesulfonamide", "casrn": "41997-13-1", "dtxsid": ID}, store)

# 5. Approve data: build the animal report
generate_animal_report_step(ID, store)

# 6. Process (async; minutes when cold).  The GO ranking and cutoffs come from
#    the study's method profile; add bmd_stats / go_* keys only to override it.
payload = asyncio.run(process_step(ID, {
    "compound_name": "PFHxSAm", "dose_unit": "mg/kg",
}, store))

# 7. Materialize the apical result sections as section files
materialize_result_sections(ID, store)

print(WorkflowEngine(ID, store).state().to_dict()["phase"])   # → APPROVED

# 9. Render: docx → bytes; html / jats / bookshelf → str
Path(f"{ID}.docx").write_bytes(render_preview(ID, surface="docx"))
Path(f"{ID}.xml").write_text(render_preview(ID, surface="jats"))
```

The optional Background section (step 8) uses the same functions as
`POST /api/generate`:

```python
from narrative.chem_resolver import ChemicalIdentity
from narrative.data_gatherer import gather_all
from narrative.background_writer import generate_background

identity = store.read_json(ID, "identity.json")
result = generate_background(gather_all(ChemicalIdentity.from_dict(identity)))
store.save_section(ID, "background", {
    "paragraphs": result["paragraphs"], "references": result.get("references", []),
    "citation_report": result.get("citation_report"),
    "abstract_background": result.get("abstract_background", ""), "approved": False,
}, archive=False)
```

For the LaTeX bundle and PDF, `rendering.latex_export` provides
`load_session_data` + `build_overleaf_bundle`. There is also a standalone CLI:
`python -m rendering.latex_export --session --dtxsid ID --out bundle.zip`. Note
that the CLI does not apply a saved view's document tree;
`generate_report --surfaces latex` does.

**Interactive alternative.** `notebooks/workflow_walkthrough.ipynb` runs steps
2–7 one cell per step and prints the derived phase after each one.

---

## 5. Route B — HTTP API with curl

### 5.1 Start the server

```bash
./run-server.sh                 # 0.0.0.0:9000; sets the JDK, BMDX_PROJECT_ROOT, LLM env
./run-server.sh --port 9100     # another port
```

If the server was started with `ALLOWED_USERS=alice,bob`, every `/api/…`
request needs `?user=alice`. For the script, set `RLM_USER=alice`. Without
`ALLOWED_USERS` the server is open.

### 5.2 One command: `tooling/generate_report_api.sh`

```bash
BASE=http://localhost:9000 tooling/generate_report_api.sh \
    -i DTXSID50469320 -n "Perfluorohexanesulfonamide" -c 41997-13-1 -u mg/kg -k PFHxSAm \
    -s docx,jats,pdf -o output/DTXSID50469320 \
    /data/pfhxsam/*
```

| Flag | Meaning |
|------|---------|
| `-i` | Session id (required) |
| `-n`, `-c` | Test-article name and CASRN (sent to integrate) |
| `-u` | Dose unit. Leave it out and the server uses the unit the data records, else `mg/kg`; the script prints a note |
| `-k` | Short compound name for captions (default: `-n`) |
| `-b` | Also generate the Background section |
| `-s` | Deliverables from `docx, html, jats, bookshelf, pdf` (default `docx,html`) |
| `-o` | Output directory (default `output/<id>`) |
| `FILE …` | Files to upload. Leave them out to use the files already in the session |

The script also saves `validation_report.json` and `process_payload.json` in
the output directory for inspection. It needs `curl` and `jq`.

### 5.3 The calls, one by one

All examples assume `B=http://localhost:9000` and `ID=DTXSID50469320`. The
`post` helper below just adds the JSON header:

```bash
post() { curl -sS -X POST -H 'Content-Type: application/json' --data "${2:-{\}}" "$B$1"; }
```

**1. Upload.** Send multipart field `files` (repeat it for several files).
`.bm2` files go to `upload-bm2`; everything else goes to `upload-csv`.
`?dtxsid=` saves the files into the session and fingerprints them.

```bash
curl -sS -F files=@PFHxSAm_Gene_Expression.bm2 "$B/api/upload-bm2?dtxsid=$ID"
curl -sS -F files=@body_weight_truth_male.csv -F files=@organ_weights_truth_male.csv \
     "$B/api/upload-csv?dtxsid=$ID"
curl -sS "$B/api/wizard/$ID/files" | jq      # what is in the pool now
```

`POST /api/upload-zip` (field `file`) accepts a single archive instead. To
remove a file: `DELETE /api/pool/{id}/files/{filename}` (moved to `_removed/`,
recoverable).

**2. Validate.**

```bash
post /api/pool/validate/$ID | jq '{file_count, is_complete,
    errors: [.issues[] | select(.severity=="error")]}'
```

If there are any `error` issues, the phase becomes `VALIDATION_ERRORS` and
integration is not allowed. Fix the files and validate again.

*Conflicts (optional).* When two files cover the same platform, integration
picks a winner by tier (`bm2 > txt/csv > xlsx`). To choose yourself, record a
decision before integrating:

```bash
post /api/pool/resolve '{"dtxsid":"'$ID'","issue_index":3,"chosen_file_id":"<file_id>"}'
```

**3. Confirm metadata.** Review the detected classification, then confirm.
`{}` accepts everything as detected (the same as clicking through the UI panel
unchanged):

```bash
curl -sS "$B/api/wizard/$ID/fingerprints" | jq -r '.fingerprints[] | [.file_id,.filename,.platform,.data_type] | @tsv'
post /api/pool/confirm-metadata/$ID '{"metadata": {}}'
# override one file:
post /api/pool/confirm-metadata/$ID '{"metadata": {"<file_id>": {"platform": "Organ Weight", "data_type": "tox_study"}}}'
```

**4. Integrate.** Merges the pool with Java. Send the identity; it is saved as
`identity.json`.

```bash
post /api/pool/integrate/$ID '{"identity": {"name": "Perfluorohexanesulfonamide", "casrn": "41997-13-1", "dtxsid": "'$ID'"}}' \
  | jq '{experiment_count, bmd_result_count}'
```

To fill in an identity from just the DTXSID (best-effort; needs network):
`post /api/resolve '{"identifier": "'$ID'"}'`.

**5. Approve the data (animal report).**

```bash
post /api/generate-animal-report/$ID | jq '{total_animals, core_count, biosampling_count}'
```

**6. Process.** The long step. The request blocks until processing finishes
(minutes when cold, seconds when cached). curl has no default timeout. If a
proxy sits in front of the server, check its idle timeout.

```bash
post /api/process-integrated/$ID '{"compound_name": "PFHxSAm", "dose_unit": "mg/kg"}' \
  > process_payload.json
```

The server takes the GO ranking and cutoffs from the study's method profile.
Send `bmd_stats`, `go_pct`, `go_min_genes`, `go_max_genes` or `go_min_bmd`
only to override it for this run. Leave out `dose_unit` and the server uses
the unit the data records, else `mg/kg`.

The response is large: it includes base64 chart PNGs, which is why it goes
straight to a file. Every result in it is also cached in the session, so you
don't need to keep it.

**7. Materialize result sections.**

```bash
post /api/pool/materialize-sections/$ID | jq .materialized
```

**8. Background (optional).** `POST /api/generate` streams Server-Sent Events
(`progress …`, then `complete` or `error`). The section must then be saved
explicitly:

```bash
curl -sSN -X POST -H 'Content-Type: application/json' \
  --data '{"identity": {"name": "Perfluorohexanesulfonamide", "casrn": "41997-13-1", "dtxsid": "'$ID'"}}' \
  "$B/api/generate" \
| awk '/^event: /{ev=$2} /^data: /{if (ev=="complete") {sub(/^data: /,""); print}}' > bg.json

post /api/session/save-section "$(jq -c --arg d $ID \
  '{dtxsid: $d, section_type: "background",
    data: {paragraphs, references, citation_report, abstract_background}}' bg.json)"
```

**Summary (optional).** The Summary is an LLM synthesis of what the session
already holds: the Background, the apical result narratives, an approved BMD
summary (`bmd_summary.json`) and any genomics section files. Run it after
steps 7–8. If none of those has content, the route returns
`400 No approved sections found to summarize`, so check for `.error` before
saving. Like the Background, it is returned by one call and saved by a second:

```bash
post /api/generate-summary '{"dtxsid": "'$ID'", "identity": {"name": "Perfluorohexanesulfonamide"}}' > summary.json
post /api/session/save-section "$(jq -c --arg d $ID \
  '{dtxsid: $d, section_type: "summary", data: {paragraphs, model_used}}' summary.json)"
```

Route A writes the Summary itself (`workflow.steps.materialize_summary`):
built deterministically from the BMD summary, the genomics results and the
Background's abstract sentence, saved as an unapproved draft. The route above
is the separate LLM variant. From Route A, start the server and make these two calls.

**Front matter (optional).** Authors, contributors and publication details
feed the About This Report and Publication Details sections. The strain
designation goes into the title after the strain:

```bash
post /api/document/$ID/front-matter '{"front_matter": {
  "authors": [{"name": "A. Author", "affiliation": "NIEHS", "role": "Study Scientist"}],
  "contributors": [], "publication": {"report_number": "NIEHS 14", "report_date": "2026-10"},
  "strain_designation": "(Hsd:Sprague Dawley® SD®)"}}'
```

**9. Render and download.** `materialize` renders the requested surface plus
the HTML view into `sessions/<id>/preview/default/`. It moves the previous set
into `history/` first. That means materializing one surface removes the
previous one from `preview/default/`, so **download each surface right after
materializing it**:

```bash
for s in docx jats; do
  post /api/preview/$ID/materialize '{"surface": "'$s'"}' >/dev/null
  curl -sSf -OJ "$B/api/preview/$ID/download?surface=$s"     # → <ID>_preview.docx, …
done
curl -sS "$B/api/preview/$ID/view" > preview.html             # the HTML view (inline)
curl -sSf -o report.pdf "$B/Bookshelf/$ID/report.pdf"          # docx → PDF (LibreOffice)
```

| Surface | Endpoint | Gated? |
|---------|----------|--------|
| `docx` | `materialize` + `download?surface=docx` | yes (409) |
| `html` | `materialize` + `download?surface=html`, or `GET …/view` | `download`: yes; `view`: no |
| `jats` (BITS XML) | `materialize` + `download?surface=jats` | yes |
| `bookshelf` (Bookshelf look-alike HTML) | `materialize` + `download?surface=bookshelf`, or `GET /Bookshelf/{id}` | `download`: yes; `/Bookshelf`: no |
| `pdf` | `GET /Bookshelf/{id}/report.pdf` (docx converted on the server) | no — preview |
| `latex` | **Not available per session over HTTP.** Use Route A (`--surfaces latex,pdf`) | — |

Add `"view": "<name>"` to the materialize body (and `&view=<name>` to download)
to render a saved view.

**Status and inspection endpoints**

| Call | Returns |
|------|---------|
| `GET /api/workflow/{id}/state` | Derived phase, legal actions, artifact flags |
| `GET /api/workflow/{id}/sections` | Every report section with its kind, readiness and approval state |
| `GET /api/workflow/{id}/publish-readiness` | `{can_publish, blocking: [...]}` |
| `GET /api/session/{id}` | All saved section content |
| `GET /api/integrated-summary/{id}` | Integrated-dataset summary |
| `GET /api/session/{id}/citation-warnings` | Unresolved citations in Background and genomics narratives |

---

## 6. Outputs

What a finished session contains under `sessions/<DTXSID>/`:

| Artifact | Written by |
|----------|------------|
| `files/`, `_originals/`, `_fingerprints.json` | Import / validate |
| `validation_report.json`, `precedence.json` | Validate / resolve |
| `identity.json`, `integrated.json`, `integrated.bm2`, `genomics.sidecar.json` | Integrate |
| `animal_report.json` | Approve data |
| `_cache_{ntp,bmds,genomics,sections,methods,bmd_summary,charts,interpretation_*}_<hash>.json`, `references.json`, `session.duckdb`, `session_parquet/` | Process |
| `bm2_<slug>.json` | Materialize sections |
| `background.json`, `summary.json`, `bmd_summary.json`, `front_matter.json` | Background, Summary, approving the BMD summary, front matter |
| `study_design.json`, `method_profile.json`, `metadata_approved.json` | `--design`, the method pin, approving experiment metadata. Integration re-applies the design and the approval |
| `preview/<view>/preview.{docx,html,xml}`, `manifest.json`, `history/` | HTTP materialize |

Route A writes deliverables only to `--out`. It does not touch
`sessions/<id>/preview/`.

---

## 7. Approval and the publish gate

**You don't need to approve anything to produce a first report.** The
deliverable renders whatever content the session has. Generated sections render
as unapproved drafts. Anything not yet produced appears as a visible
`[… pending]` placeholder. `--strict` refuses to build a LaTeX bundle that
still has placeholders.

Approval matters once a session has been **reprocessed**. When the data
changes, the LLM-written sections are marked `stale`. Those sections then block
publishing until a person accepts them again. A blocked report gets HTTP 409
from the download route, and Route A refuses to render without `--draft`.

To accept a section again:

```python
from workflow.steps import accept_section_step
accept_section_step(ID, "bm2_body-weight", store)   # section key = file stem
```

```bash
# the approve route re-saves the section's current content with the approval stamp
data=$(curl -sS "$B/api/session/$ID" | jq '.background')
post /api/session/approve "$(jq -nc --arg d $ID --argjson x "$data" \
  '{dtxsid: $d, section_type: "background", data: $x}')"
```

Apical result sections take `section_type: "bm2"` plus the slug from the file
name (`bm2_body-weight.json` → `body-weight`):

```bash
data=$(curl -sS "$B/api/session/$ID" | jq '.bm2_sections["body-weight"]')
post /api/session/approve "$(jq -nc --arg d $ID --argjson x "$data" \
  '{dtxsid: $d, section_type: "bm2", bm2_slug: "body-weight", data: $x}')"
```

Reopen a section with `release_section_step` or `POST /api/session/unapprove`.

---

## 8. Re-running, caching and resetting

- **Re-running is cheap.** Each processing layer is cached by a hash of its
  inputs. A repeat `process` on an unchanged session takes seconds.
  Content preparation is skipped entirely when nothing it depends on changed.
- **Re-integration wipes every process cache**, BMDS included, so the next
  process recomputes from scratch. Route A skips integration when
  `integrated.json` exists unless you pass `--reintegrate`. Route B always
  integrates. Integration puts back what people stated: the approved
  experiment metadata (`metadata_approved.json`) and the `--design` facts
  (`study_design.json`). It also re-pins the method profile when the study
  tracks the newest one.
- **Adding or replacing a file** after validation invalidates the downstream
  artifacts (validation report, `integrated.json`, animal report, caches),
  except the BMDS cache, whose hash is based on the data itself. Approved
  section text is kept but marked `stale`.
- **Changing the method profile** (`--method-profile`, or a newer profile for
  a study that tracks the newest) changes the NTP, BMDS, sections and Methods
  cache keys, so the next process recomputes them.
- **Reset the pool** but keep identity and sections: `POST /api/pool/reset/{id}`.
  **Delete the whole session:** `POST /api/session/reset/{id}`. Both are
  destructive, so check the session id first.

---

## 9. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `UnsupportedClassVersionError` during integrate | JDK 17 is first on `PATH`. Put JDK 21 first (`run-server.sh` and `generate_report` do this when `/opt/liberica-jdk-21` exists; otherwise set `BMDX_JDK_HOME`) |
| Integrate fails with a missing class or an empty classpath | `BMDX_PROJECT_ROOT` is unset or wrong. There must be a readable `*.jar` in `$BMDX_PROJECT_ROOT/target/` |
| LLM calls fail with `Could not resolve authentication method` | `ANTHROPIC_API_KEY` is not exported to the Python process. Use `run-server.sh`, or export the key |
| LLM calls fail with `Connection error` / certificate verify failed | `SSL_CERT_FILE` doesn't point at the NIH CA bundle, or `ANTHROPIC_BASE_URL` is exported as an empty string |
| `step failed (400): No integrated data found` | Process ran before integrate |
| `validation found errors` | Read the `[error]` lines: dose mismatch, sex mismatch or unassigned file. Fix the inputs, or override the classification with `--metadata` |
| HTTP 409 on download | Publish gate (§7): accept the listed sections again |
| HTTP 404 `No preview materialized yet` | Call `POST …/materialize` for that surface first. Materializing another surface since then moved it into `history/` |
| Summary: `400 No approved sections found to summarize` | The session has no Background, apical narrative, approved BMD summary or genomics section file to summarize. Add one first |
| Background fails or comes back empty | Some external sources (ATSDR, PubChem, IRIS) can't be reached from the sandbox firewall. Run it on the host, or skip `--background` |
| A curl request hangs and then fails with "no route" | That's the firewall, not a transient error. Don't retry in a loop |

---

## 10. Known gaps

These hold as of 2026-10-05. Appendix B.4 lists every place the report still
lacks data, with what would close it.

- **About This Report** (authors, contributors) is human-set front matter
  (`front_matter.json`, §5.3); nothing in the data supplies it.
- **Background** needs ATSDR and IRIS. Where either is unreachable (the sandbox
  firewall), `--background` saves nothing and says so, rather than writing a
  Background that reports the unreachable sources as data gaps.
- **The report's Appendix C.2 (empirical FDR)** needs the study's synthetic-null analysis,
  which is not ingested; its figure stays pending.
- **Materials & Methods** in the deliverable comes from Process
  (`_cache_methods_*`). The browser's separate *Generate M&M* button saves
  `methods.json`, which the renderer does not read. Headless runs get M&M from
  Process automatically.
- **LaTeX over HTTP.** `POST /api/export-overleaf-bundle` and
  `POST /api/compile-pdf` take a full report body assembled by the legacy UI,
  not a session id. There is no "LaTeX for session X" endpoint, and the
  preview's `latex` surface returns 501. Use Route A for LaTeX.
- **Experiment metadata review** (`GET`/`POST /api/experiment-metadata/{id}`:
  species, sex and organ per experiment, written back into `integrated.json`)
  is not a step in either script. Call it after integrate if you need to
  correct experiment descriptions.

---

## Appendix A. Render surfaces

> The report has appendices of its own (A–F). This manual's appendices are
> referred to as A, B and C, or by section (A.1, B.2, C.3); the report's
> are always written "the report's Appendix …".

A **render surface** is one output format of the report. Every surface is a
projection of the same two inputs, and none of them is a source of truth.
This appendix explains the idea, lists the surfaces, explains BITS and JATS,
and says how each surface is checked. It holds as of 2026-10-07.

### A.1 The idea: one description, many projections

```
session (integrated.json + sidecars + section files + front matter)
        │  assemble the render data            rendering/report_data.py,
        ▼                                      rendering/latex_export.load_session_data
render data  +  document tree (template / view; Appendix C below)
        │  EXTRACT: what to show, in what order rendering/render_common.py
        ▼
markup-free plans (tables, captions, rows, narrative sources, numbering)
        │  EMIT: one emitter per surface
        ├─▶ HTML      html_generator.py
        ├─▶ LaTeX     latex_generator.py   → Overleaf bundle → PDF (tect)
        ├─▶ Word      docx_generator.py    → PDF (LibreOffice)
        └─▶ BITS XML  jats_generator.py    → Bookshelf facsimile
```

- **One description.** The data assembly and the document tree are shared,
  so every surface reports the same study: the same sections in the same
  order, the same tables with the same numbers, rows, footnotes and captions,
  and the same text.
- **Extract, then emit** (ADR-0006). The decision about what a node shows
  is made once, in `render_common`, as a plan with no markup in it. Each
  emitter only turns plans into its own format and applies its own escaping.
  A bug in what a table contains is therefore fixed once, for every surface.
- **Shared, surface-independent decisions:**
  - table and figure numbers, counted by position in the tree;
  - captions, built from the design facts;
  - "not evaluated" statements and `[… pending]` placeholders;
  - the per-node page breaks and layout styles (`styles`; see C.2 below);
  - cross-references.
- **Cross-references.** Narrative text names a target, not a number
  (`[[xref:bmd-summary]]`), so reordering the tree can't leave a stale
  "Table 3" behind. An unknown target shows as `[[xref:??id]]`, and only table
  references are wired so far. Each surface resolves the token to its own form:
  - LaTeX: `Table~\ref{tab:bmd-summary}`;
  - HTML: a link reading "Table 8";
  - BITS: `<xref ref-type="table" rid="bmd-summary">Table 8</xref>`.
- **Outputs are one-way.** A surface is never read back. Edits made in Word or
  Overleaf stay there; the app is not an editor (ADR-0018). The only way in
  for authored text is a freeform node (C.2 below), which can import a
  `.docx` block.

### A.2 The surfaces

| Surface (`--surfaces`) | Output | Built by | Role |
|---|---|---|---|
| `html` | One self-contained `.html` | `html_generator.generate_html` | The on-screen view: the browser's preview frame and a quick check |
| `docx` | `.docx` | `docx_generator.generate_docx` | The default deliverable, for Word-based review. Styles come from the NIEHS-10 reference (`assets/templates/niehs-10-base.docx`) |
| `latex` | `-overleaf.zip`: `main.tex`, `report.tex`, `niehs.cls`, `figures/`, a README | `latex_generator.generate_latex` + `latex_export.build_overleaf_bundle` | For Overleaf: drop the zip into a new project and compile |
| `pdf` | `.pdf` | The `latex` bundle compiled locally with `tect` | A typeset PDF |
| `jats` | `.xml`: a BITS 2.0 `<book>` | `jats_generator.generate_bits` | **The submission format** for NCBI Bookshelf (A.3) |
| `bookshelf` | `.bookshelf.html` | `bookshelf_preview.render_book_xml` over the BITS book | A lookalike of the Bookshelf reader, built from the exact XML we would submit |
| `bits` | `-bits.zip`: `TOC.nxml`, one file per part, the figure files | `bits_bundle.bundle_zip` over the BITS book | The book chunked as Bookshelf holds it (NIEHS-07 onward): the submission package's XML |

**Surface details:**

- **Word** is an object model rather than markup. Its handlers modify a
  document instead of returning strings, and it walks the tree itself. What
  each section contains still comes from the shared plans (ADR-0008).
  - Its page breaks follow `styles`.
  - Its other typography comes from the Word base styles, not the per-node
    layout styles.
  - Pages are numbered in roman in the front matter, then in arabic from the
    body.
- **PDF** is produced two ways, which typeset differently. For a Bookshelf
  submission, the PDF is the one rendition we supply alongside the XML.
  - the `pdf` surface compiles the LaTeX bundle;
  - `GET /Bookshelf/{id}/report.pdf` converts the Word file with LibreOffice
    (`docx2pdf`).
- **The JATS article** (`jats_generator.generate_jats`) emits a PMC journal
  `<article>` instead of a book. It covers the prose only and exists for
  PMC's article tools. Reports publish as books, so it is not a deliverable.
- **Typst**, an earlier PDF route, was abandoned in the 2026-05 move to LaTeX.
  `report.typ` is a leftover.

**Where each surface is reached:**

| Surface | Command line (Route A) | Server (Route B) |
|---|---|---|
| `html` | `--surfaces html` | `POST /api/preview/{id}/materialize`, always written alongside the chosen surface; `GET …/view` |
| `docx` | `--surfaces docx` | Materialize with `surface: docx` (the default), then `GET …/download`; `GET /Bookshelf/{id}/report.docx` |
| `latex` | `--surfaces latex` | Not per session (§10). `POST /api/export-overleaf-bundle` takes a full report body from the legacy UI |
| `pdf` | `--surfaces pdf` (`--strict` refuses placeholders) | `GET /Bookshelf/{id}/report.pdf` (from Word) |
| `jats` | `--surfaces jats` | Materialize with `surface: jats` |
| `bookshelf` | `--surfaces bookshelf` | `GET /Bookshelf/{id}` (the shelf of sessions: `GET /Bookshelf`) |

**Materialized previews.** A materialized preview is written to
`sessions/<id>/preview/<view>/`, and the previous set is archived under
`history/`. A restyle re-renders the same content without creating a new
content version. The command line writes only to `--out`.

### A.3 BITS and JATS

- **JATS**, the Journal Article Tag Suite, is the NISO standard XML vocabulary
  for journal articles (Z39.96). PubMed Central archives articles in it.
- **BITS**, the Book Interchange Tag Suite, is JATS extended for books. It
  adds:
  - book metadata;
  - book parts (chapters);
  - front and back matter;
  - appendix groups.

  NCBI's Bookshelf ingests books as BITS. NIEHS's 5-day reports are published
  there as books: NIEHS-10 is NBK589955. **A BITS `<book>` is therefore the
  report's ultimate deliverable**, and the other surfaces exist for review and
  editing along the way.

**How our report maps onto a BITS book.** The structure is the published
book's (ADR-0028), and the template declares it: each top-level node names its
BITS `element` and `book_part_type`, so the YAML reads like the book's part list.
The table below is the shared template's (the 2023 books, chunked). A
published study's own definition (ADR-0029, B.1) may be packaged
`single-file` instead, as RR-8 and NIEHS-02 … 06 are: one whole-book
`<book-part>`, titled with the book title, whose front matter adds an `<ack>`,
whose body is top-level `<sec>` chapters, and whose back holds the
`<ref-list>` and the `<app>`s. The `bits` surface then writes it as one
`TOC.nxml`.

| Our document | BITS 2.0 |
|---|---|
| The report | `<book dtd-version="2.0">` |
| The series (template `book_meta:`) | `<collection-meta>`: the Bookshelf collection; the book series with its ISSN |
| Title page, front matter (report number, DOI, date, authors), abstract | `<book-meta>`: `book-id` (DOI), `book-title-group` (the title page's title + the report number as `subtitle`), `contrib-group` + `aff`, `pub-date`, `publisher`, `permissions`, `abstract` with one `<sec>` per declared part |
| Foreword; Authors, Contributors, Peer Review, Publication Details, Acknowledgments | `<front-matter>`: `<foreword>`; `<front-matter-part book-part-type="authors" / "contributors" / "peer-review" / "section" / "acknowledgments">` |
| Background, Materials and Methods, Results, Summary | `<book-body>`: one `<book-part book-part-type="section">` each; its `<body>` holds the content directly |
| References | the last `<book-part>`: `<back><ref-list>` of `<ref><label>n</label><mixed-citation>` |
| Sections | `<sec>`; inside an appendix it carries its computed `<label>` (C.1, C.2.1) |
| Tables, with their footnotes | `<table-wrap>`: `<label>`, `<caption><title>`, `<table>`, `<table-wrap-foot>`, `<fn>`; always a block in its section |
| Figures | `<fig>`: `<label>`, `<caption><p>`, `<graphic>` |
| Appendices A–F | `<book-back>`: `<book-app book-part-type="appendix">` with `<label>Appendix A</label>`; authored HTML becomes `<sec>`, `<p>`, `<table-wrap>` and `<list>` |
| `[[xref:id]]` | `<xref ref-type="table" rid="id">` |

Print-only nodes (the table of contents, the list of tables) have no BITS
element: Bookshelf builds its own contents. The `bits` surface cuts the book
into the chunked bundle the published books use: `TOC.nxml` (collection-meta,
book-meta with the abstract, and a `<toc>`), plus one `<book-part-wrapper>` per
part.

**The submission package** (NCBI's specification NBK554845) holds:

- the BITS XML;
- at least one PDF, which we supply (A.2);
- the images.

NCBI renders the HTML book page from the XML on its own servers after
acceptance. We never hold their production stylesheet. The
`bookshelf` surface is our lookalike of that page:

- It reproduces the reader content: a contents landing page laid out like the
  real one for NIEHS Report 10 (title, subtitle, series, authors with an
  affiliations toggle, publication line, copyright, the abstract with inline
  part headings, the contents with sections nested, About the Series, and
  Cite this Page in the rail), one page per part with
  Previous/Next, tables and figures as thumbnail cards that open in a
  lightbox, and cross-references that work across pages.
- A single-file book (RR-8, NIEHS-02 … 06) is one page, as Bookshelf serves
  it: the landing holds the title block, the abstract and every part under
  its own heading, with no contents list. The reference is the real NIEHS-02
  page, `tests/fixtures/reference/NIEHS-02/bookshelf-pages/toc-reader.html`.
- It renders what the book says: labels and headings come from the BITS.
  It also renders a chunked bundle directory, including a published book
  from `assets/cebs/_bookshelf/<REPORT>`, so ours and the published report
  of a study read side by side.
- It deliberately leaves out NCBI's site chrome, and a banner marks every page
  as a preview.

### A.4 How surfaces are checked

| Check | What it guards | Where |
|---|---|---|
| Dispatch parity | HTML, LaTeX and Word handle every renderable node type. Checked at import and by test | `render_common.assert_dispatch_covers`, `tests/unit/test_renderer_dispatch_parity.py` |
| Semantic parity | Surfaces agree on table and figure numbers, cross-references and BMD summary endpoints | `tests/unit/test_render_semantic_parity.py` |
| DTD validity | The BITS book and the JATS article validate against the vendored BITS 2.0 and JATS 1.3 DTDs (`assets/bits-dtd`, `assets/jats-dtd`) | `tests/unit/test_jats_stylecheck.py` |
| PMC StyleChecker | Zero errors from NLM's StyleChecker (style `book` and `article`), run offline from the vendored v5.48 transforms (`assets/stylechecker`) | `rendering/jats_stylecheck.py`, the same test |
| BITS grammar | The template and the reference report's structure instantiate as a valid BITS profile; part declarations and flow-before-sub-sections are enforced | `tests/unit/test_bits_profile.py`, `tests/unit/test_bits_part_declaration.py` |
| Published structure | The NIEHS-10 book's outline equals the published book's, apart from a listed set of content gaps; the chunked bundle round-trips | `tests/unit/test_bits_published_structure.py`, `tests/unit/test_bits_book.py`; `report_qc` `structure` for every study |
| Report definitions | Each of the 12 published reports, built from its document definition, has its published book's section structure (apart from listed content and data gaps), validates against the DTD and carries its published series ISSN | `tests/unit/test_report_definitions.py` |
| No placeholders | `--strict` refuses a LaTeX or PDF build while any `[… pending]` remains | `tooling/generate_report.py` |

**Previewing a book online.** NCBI's online tools are the PMC Article Previewer
and the online StyleChecker. The sandbox firewall blocks them, so use them from
the host.

**BITS sits outside the dispatch-parity guard by design.** A node type it
doesn't yet project emits a visible `<!-- TODO -->` in the XML, never nothing.

### A.5 Limits

- **Charts in BITS.** Genomics chart images aren't packaged into the book yet:
  a tree `figure` projects to `<fig>`, but data-driven chart images don't. The
  shipped template draws no charts, so this doesn't affect current reports.
- **Citations.** References are `<mixed-citation>` text, not structured
  `<element-citation>` records.
- **Cross-references** to sections and figures fall through to the
  broken-reference marker. Only table references resolve.
- **LaTeX over HTTP.** There is no per-session LaTeX route, and the preview's
  `latex` surface returns 501. Use the command line.
- **Word typography.** Word applies page breaks from `styles` but not the
  per-node fonts and spacing.
- **Checking Word output.** Converting a `.docx` in the sandbox uses
  LibreOffice. The project's fidelity reference for Word is OnlyOffice, which
  runs on the host.

---

## Appendix B. What in the report comes from the data

This appendix sets out everything in a report that is driven by the data:
the rules (B.1), how each fact is worked out from the files (B.2), where each
part of the report comes from (B.3), and where it still falls short (B.4). It
holds as of 2026-10-07.

### B.1 The rules

- **The integrated dataset is the source of truth.** Every number and study
  fact in the report is read from `integrated.json` (the BMDExpress project
  that Integrate builds) and its sidecars, the per-animal files that keep what
  the pivot drops: cohort (Core or Biosample), observation day, terminal flag
  and units. Nothing reads the raw `.bm2`, `.txt` or `.xlsx` uploads directly.
- **The document tree sets the structure.** Headings, their order and the
  table and figure numbers come from the study's document definition, or from
  a saved view's own structure. A new study's definition is the shared
  template (`templates/niehs-5day-report.yaml`). A published study has its
  own (`templates/studies/<id>/document.yaml`, ADR-0029): its era's base
  (`templates/eras/`) plus that report's alterations. A study's overlay
  (`templates/studies/<id>/view.yaml`) selects what is shown. Numbers are
  given by position, never typed in.
- **The method profile sets how the data is analysed.** The statistical
  tests, thresholds, BMD acceptance criteria, internal-dose rules, GO ranking
  and number formats come from the study's pinned profile (`profiles/*.yaml`,
  ADR-0027). The footnotes, Methods text and the report's Appendix D that describe the
  method are generated from those same settings, so the text can't claim a
  test that didn't run.
- **A fact the data doesn't hold is never invented.** It takes one of three
  forms:
  - a **logged fallback** (the standard design, the dose unit, an inferred
    BMR), printed as a `NOTE` and, for the BMR, footnoted in the report;
  - a visible **placeholder** (`[Placeholder: …]`, `[… pending]`) that
    `--strict` refuses to ship;
  - "not evaluated", for a data domain the study didn't collect.
- **People supply what no file records.** That covers `--design`, front
  matter, experiment-metadata approval and section approval. Each is kept in
  the session and re-applied when integration runs again.

### B.2 How the data is read

Each fact below is worked out from the files at the step named. Where a rule
is a method setting, the setting's name in the profile is given, with its
`ntp-5day-2025` value.

**YAML labels.** An item set by a YAML file carries a label naming the file:

| Label | File | What it sets |
|---|---|---|
| `template.yaml` | `templates/niehs-5day-report.yaml`, the report type | Sections, their order and headings, the Methods subsections, which data each section shows, the appendix text files it names, page breaks (`styles`), and charts (`charts`, `chart_style`, `chart_types`) |
| `deposit.yaml` | `templates/studies/<id>/deposit.yaml` (optional) | The study's own wording for deposited files (`captions:`) a file's kind where its name breaks the depositors' convention (`kinds:`), and the deposit's DOI (`doi:`), which opens the Supplemental Data appendix ("The following supplemental files are available at https://doi.org/…") |
| `document.yaml` | A published study's definition, `templates/studies/<id>/document.yaml`, extending an era (`templates/eras/<era>.yaml`) that extends the template (ADR-0029) | What that report's structure does differently: `changes` (set / remove / insert / move nodes), `packaging` (chunked or single-file), `object_position`, `book_meta` (series, ISSN, publisher), `tissue_order` (the genomic tissues named first, the rest alphabetically). A title or caption may name the study's chemical (`${chemical_name}`) and its animals and treatment (`${subject} ${treatment}`: "Female Rats and Mice Exposed to … for Five Days"; a per-study copy names its own study); a genomics section's `caption_suffix` ends each of its tables' captions so, naming the animals that table has rows for. A section may `repeat:` per deposit species, per study of a report over several (`${species}`) or per genomic tissue (`${organ}`); a `first_copy` node in it stays in the first copy only, showing the whole report's data (a table the studies share, under the first study's heading) |
| `view.yaml` | A study overlay, `templates/studies/<id>/view.yaml`, or a saved view, `sessions/<id>/views/<name>.yaml` | Selections (`filters`: organs, sex, assays, genes, gene sets); a saved view can also carry its own structure; an overlay's `methods:` block overrides profile settings for that study |
| `profile.yaml` | The pinned method profile, `profiles/<name>.yaml` | Statistical tests and thresholds, BMD engine, eligibility, BMR fallback and acceptance, internal-dose rules, GO ranking and display, the settings expected in a `.bm2` |

An item without a label is computed from the data or fixed in code. Stated
facts (`study_design.json`, `front_matter.json`) are JSON, not YAML. B.4 lists
the code-fixed settings that belong in a YAML file.

**Files (Validate, Integrate)**

- **What a file is.** Each file gets a platform (Body Weight, Organ Weight,
  Clinical Chemistry, Hematology, Hormones, tissue concentration, clinical
  observations) and a data type (`tox_study`, `inferred` or
  `gene_expression`). Confirm metadata (`--metadata`) can override either.
  They are detected differently:
  - a `.bm2` from its content and chip (ADR-0017);
  - a text or CSV file's platform from NTP naming patterns in its file name,
    e.g. `organ_weights_truth_male.txt`.
- **Cross-checks.** Validation compares the files with each other: dose
  groups, sexes, animals and coverage per platform. When two files cover the
  same data, it asks which one wins. A truth CSV derived from a study workbook
  is checked value by value against that workbook.
- **Long tables become a pivot plus a sidecar.** A one-row-per-animal table
  becomes the BMDExpress pivot (`.txt`) that Integrate needs, plus a
  `.sidecar.json`. The sidecar keeps what the pivot drops: each animal's
  cohort, observation day, terminal flag and raw value.
- **Units.** Units come from the study workbook's "Key to Column Labels"
  sheet, or from the `.units.json` that `cebs_to_pool` writes. Where both give
  one, the workbook wins. A unit stated nowhere is left unrecorded and
  flagged, never assumed. Studies differ: NIEHS-07 to -09 report plasma in
  ng/mL, NIEHS-10 in µg/mL.

**The study (Integrate, then every step)**

- **Identity.** Name, CASRN and DTXSID come from `identity.json`. The short
  name in captions comes from `--compound-name`.
- **Doses and sexes** are read from the files: every file's dose groups and
  sexes, and the animal report's dose groups.
- **Cohorts.** Each animal's Selection says which cohort it belongs to:
  - "Core Animals" are the cohort that every table, statistic and group size
    is built from.
  - "Biosampling Animals" (NIEHS-10) and "Biosample Animals" (NIEHS-07, -12,
    -13) are the internal-dose cohort. Both spellings count.
  - A study whose files mark no cohort (NIEHS-02 to -06, RR-8) treats every
    animal as Core.
  - A database export that marks "Original Animals" uses those, as published.
- **Group sizes** for Methods and the N rows:
  - Distinct Core animals are counted per sex and dose across all sidecars.
  - The group size is the most common count over the treated groups. The
    control size is the most common count over the control groups.
  - Doses with biosampling animals are listed separately ("Additional animals
    in the … groups").
- **Design facts.** Species, strain, route, vehicle and duration come from
  each experiment's `experimentDescription`, and every experiment that records
  one must agree. Integration fills these from the stated design
  (`study_design.json`) or approved metadata, else infers them. A fact still
  missing falls back to the standard design, and the fallback is logged.
  Values that disagree get no fallback. The standard design is:
  - Sprague Dawley rats for five days;
  - by gavage in corn oil for an oral unit (mg/kg);
  - by inhalation for an air concentration (ppm, ppb, mg/m³).
- **Dose unit.** The stated unit wins, else the one unit the data records,
  else mg/kg (logged). An air-concentration unit changes the wording
  throughout:
  - "exposed to" and "by inhalation";
  - "exposure concentrations";
  - "chamber control";
  - "postexposure";
  - "(Inhalation Studies)";
  - no vehicle or dose formulations.
- **Wording from the design.** Captions are built from these facts, e.g.
  "Summary of Body Weights of Male Rats Administered Triclosan for Five Days".
  So are the title's animals and study type, and the Methods animals sentence.
  Durations up to ten print in words.

**Apical endpoints (Process)**

- **Derived endpoints:**
  - Relative organ weight = organ weight ÷ terminal body weight × 1000
    (mg/g), per animal.
  - Body weight gain = last-day weight − first-day weight, per animal.
  - Both get full statistics, LOEL and NOEL, and BMDs.
- **Statistics** [`profile.yaml`] follow the profile's `apical.statistics`:
  - A Jonckheere trend test runs on every endpoint.
  - When its p ≤ `trend_select_p` (0.01), the trend-sensitive pairwise test
    runs: Williams for weights, Shirley for clinical pathology.
  - Otherwise Dunnett runs for weights and Dunn for clinical pathology
    (`pairwise` per platform).
  - Groups smaller than `min_group_n` (2) are left out.
  - Markers are `*` at p ≤ `alpha` (0.05) and `**` at p ≤ `alpha_strong`
    (0.01).
  - The footnote naming the tests is built from the family that ran.
- **LOEL** [`profile.yaml`] is the lowest dose with a significant pairwise difference from
  control, at `alpha`.
- **NOEL** is the highest tested dose below the LOEL. It is "ND" when there is
  no LOEL or no dose below it, never the control or the top dose.
- **Direction** (up or down) is shown only when the trend test is significant.
- **Which rows appear.** Every measured endpoint the selections [`view.yaml`] keep appears in the tables,
  whether or not it is significant. N rows count Core animals. The row rules
  per table are:
  - **Body weights:** the first and last day, plus any day between that is
    significant in both the trend and a pairwise test, as NIEHS-12 prints
    them;
  - **Organ weights:** each organ has an absolute row (g) and a relative row
    (mg/g), with terminal body weight as context.
- **Attrition.** An animal whose terminal flag falls before the scheduled
  sacrifice is attrition. Attrition footnotes give the day from the data.
  Mortality counts Core deaths only, so scheduled biosample sacrifices aren't
  counted as deaths.
- **Clinical observations.** Incidence counts Core animals. The onset of signs
  is the first day they were recorded. Without clinical-observation data the
  narrative says nothing about overt toxicity.
- **Decimals.** Every mean ± SE in a row prints at one precision, chosen by
  the endpoint. The precision NIEHS's published summary tables use comes
  first; an endpoint they don't list uses the precision its values are
  recorded with (at least one decimal).

**Apical BMDs (Process)**

- **Where a BMD comes from.** [`profile.yaml`]
  - The `.bm2`'s BMDExpress results are used where they exist.
  - An endpoint the `.bm2` didn't model is fitted with ToxicR Laplace model
    averaging (`apical.bmd.engine`) and marked as filled.
  - Where both exist they must agree, or processing stops.
- **Eligibility.** [`profile.yaml`] A BMD is reported only for an endpoint with a significant
  trend and a significant pairwise test (`eligibility: trend_and_pairwise`).
- **BMR.** [`profile.yaml`] The BMR is the one the `.bm2` analysis records. Where it records
  none, `bmr_when_unrecorded` (1 SD) is used and footnoted as inferred.
- **Acceptance** [`profile.yaml`] (`acceptance`) applies to every BMD, whatever its source.
  The report's Appendix D-1 prints these values:
  - R² < 0.6, BMD/BMDL > 10, or a BMD above the highest dose → "NVM" (no
    viable model);
  - a BMD below ⅓ of the lowest nonzero dose → "<LNZD/3".
- **Precision.** BMDs print at one precision report-wide: 3 decimals for the
  NIEHS-10 method (gene expression without gene-level analysis), else 1.

**Internal dose (Process)**

The rules come from the profile's `internal_dose` settings [`profile.yaml`], except for the plasma concentration table and the toxicokinetics:

- Tables are built by study day, from biosample animals.
- A group with ≤ 20 % of values detected prints "BD"
  (`bd_if_detected_share_at_most`). Otherwise values below the limit count as
  half the limit (`below_limit: half_limit`).
- Outliers are removed by the Dixon r10 test at α = 0.01 (`outliers`).
- Pairwise markers use Shirley or Dunn, and only when the control has a mean.
- Values print to 3 significant figures (`sig_figs`). Normalized rows divide
  each animal's concentration by its group's nominal dose or exposure
  concentration.
- **Plasma concentration table** (studies with timepoints after dosing,
  e.g. NIEHS-10):
  - rows are the sampling times ("2 h postdose");
  - columns are the dose groups that have biosample animals;
  - values are the mean ± SE of the biosample animals, with values below the
    limit of quantification counted as half the limit;
  - it has no statistics or BMDs.
- **Toxicokinetics** (`tables/toxicokinetics.py`) uses the group-mean
  concentrations at two time points:
  - elimination rate k = ln(C₁/C₂) / Δt and half-life t½ = ln 2 / k,
    computed only with exactly two time points and a falling concentration;
  - dose proportionality: the high-to-low concentration ratio against the
    dose ratio;
  - a bioaccumulation flag when t½ > 24 h.

  These numbers reproduce NIEHS-10's to the decimal, and the Abstract's
  internal-dose paragraph reports them.

**Transcriptomics (Integrate, Process)**

- **Experiments.** [`view.yaml`] Organ and sex come from each experiment's metadata:
  approved metadata, else inferred. A view's `organs` and `sex` selections
  choose which organ × sex sections show.
- **Assay.** The assay (TempO-Seq, Affymetrix, Illumina) is read from the
  chip.
- **Sample counts.** The sample-counts table counts each experiment's samples
  per organ, sex and dose.
- **GO tables** [`profile.yaml`]:
  - They come from the `.bm2`'s GO category analyses.
  - They are ranked by `genomics.go_ranking` (5th percentile, then median).
  - They are cut by `go_display`: top 5 %, 20 to 500 genes, BMD ≥ 3.
  - Up and down counts come from the genes' directions.
- **Gene tables.** The top genes come from BMDExpress's gene-level (GENE)
  analysis, sorted by BMD. Fold change is the mean over each gene's probes.
- **Methods.** The transcriptomic Methods prompt takes the analysis settings
  the `.bm2` records: version, prefilter, models, BMR and GO filters.
- **Mismatch check.** [`profile.yaml`] At integration these recorded settings are compared with
  `genomics.recorded` (BMR 25 % relative deviation, model averaging). A
  disagreement is a `method_mismatch` warning; neither side wins.
- **The report's Appendix C.1 PCA** is drawn per tissue and sex from the integrated
  expression matrix: one dot per animal, coloured by dose. Columns are
  mean-centred without scaling and decomposed by SVD, with scikit-learn's
  sign convention. This reproduces NIEHS-10's figures exactly when given the
  full matrix.
- **Organ order.** Genomics sections come one per organ, both sexes stacked:
  liver, then kidney, then the rest alphabetically.
- **Genomics prose** has two layers:
  - an intro and one findings paragraph per organ, built without a model from
    the ranked tables, using the reliability rules below;
  - the LLM interpretation per organ and sex, grounded in the knowledge base
    (`bmdx.duckdb`).
- **Charts.** [`template.yaml`] [`view.yaml`] The UMAP and cluster charts are off: the template's `charts: []`
  matches the NIEHS report, which has no main-body genomics figures. Turned
  on, clusters are labelled with the study's own GO terms, or with Enrichr
  terms only if `BMDX_ALLOW_ENRICHR=1`. New chart types can be declared in the
  template (`chart_types`) over the GO table columns, without code.
- **References.** The genomics prose may cite only the `[Pn]` papers it was
  given, and the Background only its numbered sources. `citation_check` drops
  any citation that points at nothing given. The reference list is built from
  the papers actually cited.

**What appears, and where (render)**

- **Sections follow the data.** [`template.yaml`] The template lists every possible section, in order, with its heading and the data it shows.
  Each one renders with what the session has:
  - a platform the study didn't measure reads "not evaluated";
  - content not yet produced is a visible `[… pending]`;
  - a genomics section appears for each organ the expression data has.
- **Numbering and captions.** [`template.yaml`] Tables and figures are numbered by their
  position in the template's tree, and appendix tables per appendix ("Table B-1").
  Captions are built from the design facts and the sexes in the data.
- **Views narrow the report without recomputing.** [`view.yaml`] A study overlay
  (`templates/studies/<id>/view.yaml`) or a saved view selects what is shown,
  and changes neither the data nor the statistics. NIEHS-10's overlay, for
  instance, keeps the liver-only, male-only organ weight table and the
  hand-picked "Select" endpoints. The shared template selects nothing, so a
  study is reported in full unless its overlay says otherwise. The axes are:
  - `organs` (per area: genomics, organ weight);
  - `sex` (apical, genomics);
  - `assays` (clinical chemistry, hematology, hormones; per sex if needed);
  - `genes`;
  - `gene_sets`;
  - `charts`.
- **Page breaks and appendix text.** [`template.yaml`] The template's `styles` block sets
  where pages break, matching NIEHS-10. The report's Appendix C, D and E prose comes from
  the files the template names (`templates/freeform/appendix-{c,d,e}.*`).
  Its Appendix A and F come from the study's own files
  (`templates/studies/<id>/appendix-{a,f}.*`), so no other study inherits
  them.

**The animal report and the report's Appendix B (Approve data)**

- **The animal report** (`animal_report.json`) traces every animal ID across
  every file. It has five parts:
  - the study design, as dose × sex × cohort counts;
  - the roster, with each animal's presence per platform;
  - platform coverage;
  - attrition, giving who dropped out and why;
  - sex and dose consistency checks.
- **The report's Appendix B** lists each animal with its number, sex, dose and tissue, and
  the FASTQ name of its expression sample.

**The workflow itself**

- **Phase.** The phase (`EMPTY → UPLOADED → VALIDATED → INTEGRATED →
  APPROVED`) is derived from which artifacts exist, never set.
- **Caches.** Every cache is keyed by a hash of its inputs: the data, the view
  and the method signature. A change recomputes only what depends on it.
- **Stale sections.** [`template.yaml`] When the data changes under an approved section, the
  section is kept but marked `stale`, and it blocks publishing until accepted
  again (§7). The list of sections that need approval is itself derived from
  the document tree.

**Prose built from the data (Process)**

- **No model involved.** These are assembled from the numbers above, so they
  can't disagree with the tables:
  - the Abstract (except its Background sentence);
  - the Summary;
  - the Animal Condition, Clinical Pathology and Internal Dose narratives;
  - Methods' Study Design, Dose Selection and Chemistry;
  - the genomics intros and per-organ findings.
- **"Most sensitive" lists** in the Abstract and Summary take reliable BMDs
  only:
  - the BMD must be viable and not NVM;
  - it must be at or above the lower limit of extrapolation (⅓ of the lowest
    nonzero dose);
  - it must not be anomalous: a BMD below NOEL/10, or LOEL/10 without a NOEL,
    is left out.
- **LLM-written prose** [`template.yaml`] [`profile.yaml`] is given only the session's numbers, and only through
  the NIEHS gateway. Genomics narratives may cite only the papers the
  knowledge base supplies. That prose covers:
  - the apical BMD paragraph;
  - the genomics narratives;
  - the remaining Methods subsections. The template places them and gives
    their headings; which subsections exist, and when each applies, is fixed
    in code (`SUBSECTION_SKELETON`). The Statistical Analysis and apical BMD
    prompts are built from the profile;
  - the Background.

### B.3 Where each part of the report comes from

Every row's place and heading come from `template.yaml`. The YAML column
names the files that also shape its content (see the labels in B.2).

**Kinds of source:**

- **Data:** computed from the integrated dataset.
- **Profile:** the method profile.
- **Stated:** given by a person.
- **LLM:** written by a model from the data, through the NIEHS gateway only.
- **Fixed:** NIEHS boilerplate.

| Report part | Source | How it's derived | When the data doesn't say | YAML |
|---|---|---|---|---|
| Title: chemical, CASRN | Data / stated | `identity.json` (`--name`, `--casrn`, or the resolver) | — | — |
| Title: strain, species, route ("Gavage Studies") | Data / stated | The experiments' metadata (`study_design_facts`) | The standard design, logged | — |
| Title: supplier designation "(Hsd:…)" | Stated | `front_matter.json` `strain_designation` | Left out | — |
| Report number, date, DOI | Stated | `front_matter.json` `publication` | "to be assigned" placeholders | — |
| Foreword, Peer Review, Acknowledgments | Fixed | Boilerplate in code (`rendering/report_data.py`) | — | — |
| About This Report | Stated | `front_matter.json` authors and contributors | Pending | — |
| Abstract: Methods, Results, Summary | Data | Built from the BMD summary, the genomics results and the design facts, without a model | Paragraphs drop out for absent data | — |
| Abstract: Background, Background section | LLM | ATSDR, IRIS and PubChem lookups (`--background`) | Nothing is saved when a source is unreachable | — |
| Methods: Study Design, Dose Selection, Chemistry | Data | Group sizes (Core cohort), doses, dose unit, design facts, identity | `[Placeholder: …]` for the source, age, quarantine, randomization, dose rationale, lot and purity | — |
| Methods: Statistical Analysis, apical BMD | LLM from profile | The prompt is built from the profile's test families, alphas, BMR and acceptance criteria | — | `profile.yaml` |
| Methods: transcriptomic BMD | LLM | The prompt carries the `.bm2`'s recorded settings (BMDExpress version, prefilter, models, BMR, GO filters) | "not recorded" | — |
| Methods: clinical exams, organ and clin-path endpoints | LLM | The prompt lists the endpoints in the data | — | — |
| Methods: other subsections | LLM | Fixed guides: sample collection, RNA, sequencing, QC, normalization, internal dose, data accessibility | — (see gap G14) | `template.yaml` (placement, headings) |
| Sample counts table | Data | Animal report and expression samples per organ, sex and dose | Omitted without expression data | — |
| Results: body, organ weight, clinical pathology tables | Data + profile | Mean ± SE per group; markers from the profile's tests; decimals per endpoint; caption from sexes, species, route and duration; units from the study workbook | A domain that isn't collected reads "not evaluated" | `profile.yaml`, `view.yaml` |
| Results: Animal Condition, Clinical Pathology narratives | Data | Built from the tables, mortality by cohort, and clinical-sign incidence and onset, without a model | — | `view.yaml` |
| Results: Internal Dose table and narrative | Data + profile | The BD share, ½-LOD, Dixon outlier test, test family and significant figures come from the profile; units come from the lab workbook | Omitted without concentration data | `profile.yaml` |
| Apical BMD summary | Data + profile | `.bm2` results reconciled with ToxicR; profile acceptance filter (NVM); LOEL/NOEL from the statistics | The BMR is inferred from the profile and footnoted; NOEL is "ND" | `profile.yaml`, `view.yaml` |
| Apical BMD analytical paragraph | LLM | The summary rows | — | — |
| Gene set and gene BMD tables | Data + profile | BMDExpress gene-level and GO analyses from the `.bm2`; ranking statistic and cutoffs from the profile; fold change is the mean over probes | — | `profile.yaml`, `view.yaml` |
| Gene set and gene narratives | Data, then LLM + knowledge base | Intro and per-organ findings built from the ranked tables; then the per-organ, per-sex interpretation grounded in `bmdx.duckdb` | Findings drop out without dose groups | `view.yaml` |
| References | Knowledge base, Background sources | The papers the narratives actually cite; `citation_check` drops citations to anything not given | — | — |
| Genomics charts | Data | UMAP and cluster charts from the GO tables; off in the shipped template (`charts: []`) | — | `template.yaml`, `view.yaml` |
| Summary | Data | Built from the same inputs as the Abstract, without a model | — | — |
| Appendix A (internal dose method), F (supplemental files) | Stated | Study overlay HTML/TeX (PFHxSAm only) | Pending | — (study files) |
| Appendix B animal roster | Data | Animal report joined to the FASTQ sample names | — | — |
| Appendix C.1 PCA | Data | Integrated expression matrix | — | — |
| Appendix C.2 eFDR | — | Not ingested | Pending figure | — |
| Appendix D acceptance table, configuration table | Profile, data | Profile criteria; the `.bm2` analyses' recorded configuration | — | `profile.yaml` |
| Appendix D, C and E prose | Fixed | Shared freeform files | — | `template.yaml` (names the files) |

**Precedence when sources disagree:**

| Fact | Precedence (strongest first) |
|---|---|
| Dose unit | `--dose-unit` (stated) > the one unit the data records > `mg/kg` (logged) |
| Design facts | Experiment metadata, including the `--design` facts re-applied at each integration > the standard design (logged). Recorded values that disagree get no fallback |
| Experiment organ and sex | Approved metadata (`metadata_approved.json`) > inference from names and the LLM |
| Method setting | Request (CLI or UI) > study overlay `methods:` > pinned profile > built-in default. Each value carries its source |
| Apical BMR | Recorded in the `.bm2` > the profile's `bmr_when_unrecorded` (footnoted as inferred) |
| `.bm2` setting vs profile | Neither wins. A disagreement is a `method_mismatch` warning |

### B.4 Gap analysis

**Status values:**

- **Input:** no file the pipeline receives carries the fact, so a person or a new data source must supply it.
- **Wiring:** the data exists but doesn't reach the report.
- **Text:** fixed wording that should come from the profile or the data.
- **Structure:** a section NIEHS publishes that the template lacks.

**Input gaps**

| # | Gap | Today | To close it |
|---|---|---|---|
| G1 | Strain, route, vehicle and duration aren't in the BMDExpress project or the STQ weight extracts | The standard design (logged), or `--design`. BPAF and Triclosan were stated as the standard design on 2026-10-07 | Ingest the study's protocol record (CEBS study metadata or the source-of-truth `.xlsx` Key sheet) |
| G2 | Animal source, age, quarantine, randomization, dose rationale, test-article lot and purity, formulation analyses | `[Placeholder]` in Methods; `--strict` blocks | A study-facts input, or text authored in Word (ADR-0018) |
| G3 | Supplier strain designation | Front matter only; the title leaves it out if unset | The same protocol record as G1 |
| G4 | eFDR (synthetic-null analysis) | The report's Appendix C.2 is pending; Methods says it isn't included | Ingest the synthetic-null BMDExpress results |
| G5 | Theoretical inhaled dose (inhalation studies) | Rows normalized by inhaled dose aren't built | A file recording the inhaled-dose calculation |
| G6 | Authors, report number, DOI, Background sources | Front matter and `--background` on the host | Human input; host network |

**Wiring gaps**

| # | Gap | Today | To close it |
|---|---|---|---|
| G7 | Experiment metadata (organ, sex, species) | Inferred from experiment names (LLM) unless approved; the source-of-truth `.xlsx` is primary only for classification | Read the workbook's Key and Data sheets first (ADR-0017/0019) |
| G8 | Multi-species studies (NIEHS-13: rats and mice) | One gene-expression `.bm2` per pool, and genomics keyed by organ and sex, so species collide. Our NIEHS-13 session holds the rat data only | Key genomics by species and keep every expression project |
| G9 | Animal report counts NIEHS-13's biosample animals as Core | The animal report's Core count is too high; the tables use the right cohort | Use the cohort rule the tables use |
| G10 | The UI's Process step sends `mg/kg` when no unit is set, and a few render helpers (the report's Appendix B dose header, the genomics table labels) fall back to `mg/kg` when no unit is passed | Hides the recorded unit and the logged fallback | Send nothing and let the server resolve it; pass the resolved unit everywhere |
| G11 | A text or CSV file's platform is read from its file name | A file not named to NTP conventions is unassigned or misclassified until overridden | Classify by content (endpoint names), as `.bm2` files are |
| G12 | Apical outlier exclusion (NIEHS staff judgement) | Not represented; the profile says `outliers: null` | A per-study exclusion list in the overlay |
| G13 | NIEHS-10's apical engine (BMDS 2.7) and `all_endpoints` | Listed as profile deviations; the substitute runs | Implement, or accept as recorded |

**Text gaps**

| # | Gap | Today | To close it |
|---|---|---|---|
| G14 | Methods guides for internal dose ("LC-MS/MS"), sample collection, RNA, sequencing, QC and instruments are fixed text | The LLM writes plausible, older-era protocol text | Move the guides into the profile, or build them from data |
| G15 | The transcriptomic BMD guide fixes "5th percentile", "≥3 genes, ≥5 %" and "median over probes" | Can disagree with the profile's GO ranking | Generate from the profile, as the statistics guide is |
| G16 | The report's Appendix D prose (ToxicR, Laplace model averaging) and Appendix C prose | Fixed text | Generate from the profile and the recorded configuration |
| G17 | The report's Appendix E describes liver, kidney and heart whatever was weighed | Can describe organs the study didn't weigh, and miss ones it did | Select descriptions by the organs in the data |
| G18 | The "most sensitive" filters use a fixed lower limit of extrapolation (⅓ of the lowest nonzero dose) and anomaly ratio (10) | Fixed in code, not the profile | Read them from the profile, as the acceptance criteria are |
| G19 | BMD precision (1 or 3 decimals) is inferred from whether the `.bm2` has gene-level analyses | A data heuristic standing in for a method setting | A profile setting |
| G20 | The transcriptomics Methods guides name TempO-Seq and the S1500+ platform | Wrong for an Affymetrix or Illumina study, although the assay is detected from the chip | Build the guides from the detected assay |
| G21 | The set of Methods subsections, and when each applies, is fixed in code (`narrative/methods_models.SUBSECTION_SKELETON`) | A template node can place or retitle a subsection but not add one the LLM writes | Derive the list from the template's `methods_key` nodes |
| G22 | Peer Review says the design and methods are identical to those reviewed | Not checked | Compare the pinned profile with the reviewed one |
| G23 | The title doesn't name the sex of a one-sex study (NIEHS: "Male Sprague Dawley … Rats"), and Peer Review names the study by its short title, without the CASRN, designation and study type | Both are built from the design facts but drop these parts | Build both from the cover title, with the sexes in the data |

**Structure gaps**

| # | Gap | Today | To close it |
|---|---|---|---|
| G24 | NIEHS-13's "most potent GO per tissue" table, the report's Appendix E gene-set definitions and NIEHS-13's appendix order | Missing; the order differs | Template changes, checked against the reference fixtures |
| G25 | Genomics organs are ordered liver, kidney, then alphabetical | NIEHS-10's order, fixed in code; another study's published order may differ | Order by the template or the study overlay |

---

## Appendix C. The YAML files and what they can do

Appendix B says which parts of a report each YAML file sets. This appendix
covers the files themselves: where they live, what each key can do, how they
combine, and how they are checked. It holds as of 2026-10-07.

### C.1 The files

| File | Scope | Edited with | Takes effect |
|---|---|---|---|
| `templates/niehs-5day-report.yaml`: the **report template** | Every report | A text editor, or the default-template routes (`POST /api/document-config-default`, `/api/report-filters-default`, `/api/layout-style-default`) | Saving through a route rebuilds the tree at once. A hand edit to `document:` needs a server restart; the other blocks are read at each render |
| `templates/studies/<id>/view.yaml`: the **study overlay** | One study, version-controlled | A text editor | The next render; its `methods:` block, the next Process |
| `sessions/<id>/views/<name>.yaml`: a **saved view** | One session | The Configure screen, `POST /api/views/{id}/{name}` | The next render, with no reprocessing |
| `sessions/<id>/document.yaml`: the session's **structure** | One session | The Configure structure editor, `POST /api/document-config/{id}` | The next render |
| `sessions/<id>/styles.yaml`: the session's **layout styles** | One session | `POST /api/layout-style/{id}` | The next render |
| `profiles/<name>.yaml`: a **method profile** | Every study pinned to it | A new file; profiles are never edited | The next Process of a study pinned to it, or tracking the newest |
| `vocab/<name>.yaml`: a **style vocabulary** | Word output that opts in | `docx_style_extract --emit-vocabulary` (generated layer) and by hand (curated layer) | The next docx render |

**History.**

- Every save through a route archives the previous file under
  `sessions/<id>/history/`, so a structure, style or view edit can be undone.
- The template and the profiles are in git.
- A route save of the template rewrites only its `document:` block. That
  drops the file's comments, so review the diff before committing.

### C.2 The report template

**Top-level keys:**

| Key | What it sets |
|---|---|
| `document` | The structure: three region containers (`front`, `body`, `back`), each with `children` node entries |
| `organs`, `sex`, `assays`, `genes`, `gene_sets` | Shared selections. The shipped template sets none, so every study is reported in full; a study's choices go in its overlay (C.3) |
| `charts` | The genomics chart types to draw. The shipped `[]` draws none, as the NIEHS report has none |
| `chart_style` | Chart styling, merged in four layers: built-in, then `defaults`, then `types.<type>`, then `instances."<organ>\|<sex>\|<type>"`. Keys follow `genomics/chart_style.STYLE_KEY_SCHEMA`: size, colours, palette, marker, legend, margins and axes |
| `chart_types` | New chart types declared without code (below) |
| `styles` | Typography and page flow for every surface, merged in three layers: `defaults`, then `types.<content-type>`, then `instances.<node-id>` |

**Regions.** A region (`front`, `body`, `back`) maps directly to BITS
`<front-matter>`, `<book-body>` and `<book-back>`. It also switches page
numbering from roman to arabic. Every node inherits its container's region.

**Node entries.** Each entry needs `id` and `title`, plus `type` or an
explicit `role` + `binding` pair that names a preset. Other keys:

| Key | Meaning |
|---|---|
| `type` | The component (list below) |
| `title` | The heading, or the table or figure title. `""` gives an untitled block |
| `data_key` | The key in the render data the node shows (`methods`, `bmd_summary`, `genomics_sections`, `appendix_animals_matrix`, …) |
| `platform` | For apical tables: the platform whose section the table shows (`Body Weight`, `Clinical Chemistry`, …) |
| `narrative_key` | The narrative a `narrative+tables` or genomics node shows above its tables |
| `methods_key` | For a Methods subsection: which subsection's prose it shows (`study_design`, `stat_analysis`, …). It must be a key the Methods writer produces |
| `ready_key` | The navigation flag that enables the section in the browser |
| `requires_platform` | A data gate: one platform, or a list of which any one is enough. Without it, the node renders its `not_collected_text` |
| `not_collected_text` | What a gated node says instead (default: "<title> was not evaluated in this study.") |
| `orientation` | `landscape` or `portrait` for a table or figure. A per-session override in the UI wins |
| `caption` | A caption paragraph for a table or figure. It overrides the caption built from the data |
| `subtype` | The cover or title-page layout (`niehs-5d-tox`), or a figure's kind (`chart`, `logo`) |
| `content`, `content_file`, `representation` | Authored content, for freeform nodes (below) |
| `session_content`, `missing_content_text` | Per-study authored content, looked up in `sessions/<id>/authored/` then `templates/studies/<id>/`. Without it, `missing_content_text` is shown, or a pending placeholder if that is unset |
| `content_items` | Ordered blocks inside one component (text, table, chart), each addressable as `<node-id>::<item-id>` |
| `children` | Nested nodes |

**Computed, never written:**

- the heading level;
- table and figure numbers, counted by position (per appendix inside an
  appendix: "B-1");
- appendix letters, counted in order;
- the region.

**Node types** (`document_model/render_capabilities.COMPONENT_CATALOG`; the
second column is what each needs):

| Type | Needs | What it is |
|---|---|---|
| `cover`, `title-page` | — | Fixed pages laid out from the identity, design and front matter |
| `toc`, `tables-list`, `figures-list` | — | Generated lists |
| `heading-only` | — | A heading whose children carry the content; may nest |
| `page-break` | — | A forced page break |
| `front-matter` | `data_key` | Front-matter prose (foreword, abstract, …) |
| `narrative` | `data_key` | A prose section |
| `narrative+tables` | — | A narrative (`narrative_key`) with child `table` nodes |
| `table`, `incidence-table` | `platform` | An apical table built from the data |
| `sample-counts-table`, `data-table` | `data_key` | A table built from a prepared matrix |
| `bmd-summary` | `data_key` | The apical BMD summary |
| `genomics-section` | `data_key`, `narrative_key` | One gene set or gene section per organ |
| `figure` | — | A figure (`subtype: chart` for a data figure) |
| `appendix` | — | An appendix; holds sections, tables, figures and authored content |
| `freeform-page`, `freeform-block`, `authored-table` | — | Authored content: a page of its own, an inline block, or a table with supplied markup |
| `supplementary-material` | — | A supplied data file (`content_file`) |

**Authored content** goes in freeform nodes:

- Give exactly one source:
  - inline `content` with a `representation` (`latex` or `html`);
  - `content_file` (a path under `templates/`) with a `representation`
    (`latex`, `html` or `docx`; a `.docx` is converted at load);
  - or `content: {latex: …, html: …}` with no representation, when the two
    surfaces need different markup.
- A single-surface node shows a short pending note on the other surface.
- The report's Appendix C, D and E use this mechanism. Their text is in
  `templates/freeform/`.

**Data-driven chart types** (`chart_types`):

- Required keys:
  - `trace`: `scatter`, `bar` or `line`;
  - `x` and `y`: GO table columns.
- Optional keys:
  - `color`: one trace per distinct value;
  - `size`;
  - `sort: {by, dir}`;
  - `limit`;
  - `axes`: titles and types per axis;
  - `layout`;
  - `caption`.
- Available columns are `bmd`, `bmdl`, `direction`, `fishers_p`, `go_id`,
  `go_term`, `n_down`, `n_genes`, `n_genes_with_bmd`, `n_up` and `rank`.
- Titles may use `${dose_unit}`, and captions `{organ_title}` and
  `{sex_title}`.
- The built-in `umap` and `cluster` types can't be redeclared.
- A declared type is drawn only when it is listed in `charts`.

**Layout styles** (`styles`) keys:

| Key | Values |
|---|---|
| `font_family` | `serif`, `sans`, `mono` |
| `font_size` | A length, e.g. `11pt` (pt, mm, cm, in, em, ex) |
| `line_height` | A number, e.g. `1.4` |
| `weight` | `normal`, `bold` |
| `style` | `normal`, `italic` |
| `color` | `#rgb` or `#rrggbb` |
| `align` | `left`, `right`, `center`, `justify` |
| `space_before`, `space_after`, `first_line_indent` | A length |
| `break_before`, `break_after` | `auto`, `page` |
| `keep_together` | `true`, `false` |

- **Breaks on every surface.** Word gets `pageBreakBefore`, LaTeX
  `\clearpage`, and HTML `break-before: page`.
- **The shipped breaks** reproduce NIEHS-10's pagination: front-matter pages,
  Results, Summary, References, three tables and every appendix.
- **Precedence:** the template, then the session's `styles.yaml`, then the
  request.

### C.3 Study overlays and saved views

A study overlay (`templates/studies/<id>/view.yaml`) and a saved view
(`sessions/<id>/views/<name>.yaml`) share one format:

```yaml
document: [ …node entries… ]   # saved views only: this view's own structure
filters:
  organs:    {genomics: [liver, kidney], organ-weight: [liver]}
  sex:       {organ-weight: [male]}
  assays:
    clinical-chemistry: {male: [cholesterol], female: ["aspartate aminotransferase"]}
    hematology: ["neutrophil count"]          # a flat list = both sexes
  genes:     [egr1, ddit4]
  gene_sets: ["GO:1902893", "cell division"]
charts: [umap, cluster]        # or [] for none; leave out to use the template's
methods:                       # study overlay only: method overrides (C.4)
  apical: {statistics: {alpha: 0.05}}
```

**Selection axes**, all optional:

| Axis | Areas | Matching |
|---|---|---|
| `organs` | `genomics` (sections, charts, narratives, gene tables), `organ-weight` (the table and its narrative) | By component: `kidney` matches "Kidney-Left" and "R. Kidney" |
| `sex` | `apical` (every apical table's columns, the BMD summary, the narratives), `genomics` (whole sections), `organ-weight` (the organ weight table only) | Exact: `male`, `female` |
| `assays` | `clinical-chemistry`, `hematology`, `hormones` | By component on the endpoint label: `count` keeps every "… count" row. Use several words to narrow it ("total thyroxine") |
| `genes` | — | Gene symbols |
| `gene_sets` | — | A GO accession or a word of the term: `division` keeps "cell division" |

**How values work:**

- Any area's value may be a flat list (both sexes) or `{male: […], female: […]}`.
- A missing axis or area, or an empty list, means no selection.
- An unknown area is a load error.

**Which file applies:**

- **Filters and charts:** the session's saved view wins, then the study overlay,
  then the template. A layer counts when it states `filters` or `charts`.
- **Structure:** a saved view's `document:`, then the session's
  `document.yaml` (only when the session has no views), then the template.
- **Methods:** the overlay's `methods:` block applies when processing.

Selections are a projection at render time. The statistics and BMDs are
computed over everything, so switching or adding a view never reprocesses.
NIEHS-10's overlay is the worked example: the liver-only, male-only organ
weight table and the hand-picked "Select" endpoints of its published Tables
4–6.

### C.4 Method profiles

A profile (`profiles/<name>.yaml`) states the whole analysis method.

**Identity keys:**

| Key | Meaning |
|---|---|
| `name` | The profile's name |
| `series` | Its series: `ntp-5day` |
| `effective` | The year it takes effect: `"2025"` |
| `reference` | The published report whose data its tests reproduce |
| `description` | A short description |

**Method keys:**

| Key | Values (registered implementations) |
|---|---|
| `apical.statistics.trend_test` | `jonckheere` |
| `apical.statistics.trend_select_p`, `alpha`, `alpha_strong` | Probabilities |
| `apical.statistics.min_group_n` | A whole number |
| `apical.statistics.pairwise.<platform>` | `williams_or_dunnett`, `shirley_or_dunn`, `none` |
| `apical.statistics.outliers` | `{test: dixon_r10, alpha}` or null |
| `apical.bmd.engine` | `toxicr_model_average`; `bmds_2_7_high_dose_drop` is registered but not implemented |
| `apical.bmd.eligibility` | `trend_and_pairwise`; `all_endpoints` is registered but not implemented |
| `apical.bmd.bmr_when_unrecorded.<platform or default>` | `{type: sd \| rel_dev, factor}` |
| `apical.bmd.acceptance` | `r2_min`, `bmd_bmdl_max`, `bmd_above_highest_dose` (`nvm`, `keep`), `not_reportable_fraction` |
| `internal_dose.pairwise` | As for apical pairwise |
| `internal_dose.below_limit` | `half_limit` |
| `internal_dose.bd_if_detected_share_at_most` | A probability |
| `internal_dose.outliers` | As for apical outliers |
| `internal_dose.sig_figs` | A whole number |
| `genomics.go_ranking` | A list from `fifth_pct`, `tenth_pct`, `median`, `mean`, `minimum`, `weighted_mean`, `lower95`, `upper95` |
| `genomics.go_display` | `{pct, min_genes, max_genes, min_bmd}` |
| `genomics.recorded.bmr` | What a genomic `.bm2` should record: `{type, factor}` |
| `genomics.recorded.model_selection` | `model_average`, `lowest_aic` |

**Rules:**

- **The schema is closed.**
  - An unknown key, a missing key or an unregistered value fails at load.
  - A profile must state every key. `null` means "to confirm" and resolves to
    the built-in default, reported as such.
  - A registered value the tool doesn't implement runs the default and is
    listed as a deviation (e.g. `ntp-5day-2021`'s BMDS 2.7 engine).
- **Profiles are immutable.** A study pins a profile by name and content hash
  (`sessions/<id>/method_profile.json`), and an edited profile fails the pin
  check. A revised method is a new file.
  - A study that tracks its series moves to the newest file automatically.
  - `--method-profile NAME` fixes a study on one profile.
- **Layers.** The built-in default, then the profile, then the study overlay's
  `methods:` block, then the request (CLI or UI). A study overlay or request
  may state any subset of keys. Every resolved value carries its source.
- **Text follows the profile.** Footnotes, the Methods statistics and BMD
  text, and the report's Appendix D-1 are generated from the resolved values.

The shipped profiles are `ntp-5day-2025` (NIEHS-12/13, the reference
NIEHS-13) and `ntp-5day-2021` (NIEHS-07 to -10, the reference NIEHS-10).

### C.5 Style vocabularies

`vocab/<name>.yaml` maps the report's semantic roles (report title, section
heading, table title, …) to Word paragraph styles. It has two layers:

- `ntp-report-generated.yaml` is extracted from a reference `.docx` and never
  hand-edited;
- `ntp-report.yaml` extends it with stable role names.

A render uses a vocabulary only when the render data names one
(`vocabulary`); otherwise Word output uses its built-in styling.

### C.6 What YAML can't change yet

These are fixed in code; Appendix B.4 tracks each one:

- the boilerplate text: Foreword, Peer Review, Acknowledgments;
- the set of Methods subsections and their LLM instructions;
- table captions and the wording of the prose built from the data;
- endpoint decimals;
- the "most sensitive" lower limit and anomaly ratio;
- BMD precision;
- the genomics organ order.
