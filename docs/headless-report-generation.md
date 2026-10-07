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
- [Appendix A. What in the report comes from the data](#appendix-a-what-in-the-report-comes-from-the-data)

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
| `--dose-unit` | The study's dose unit, used on every surface: table headers, Methods, Abstract, Summary, the Appendix B roster and the LLM narratives. **State it explicitly.** If you leave it out, the unit the data records is used, else `mg/kg`, and the log says which (`dose unit: ppm (stated)`). A concentration in air (`ppm`, `ppb`, `mg/m3`) makes it an inhalation study: "exposed to … by inhalation", "exposure concentrations", "chamber control", title "(Inhalation Studies)", and no vehicle or dose formulations |
| `--metadata FILE.json` | Classification overrides, keyed by **filename**: `{"organ_weights_truth_male.txt": {"platform": "Organ Weight", "data_type": "tox_study"}}` |
| `--design FILE.json` | Study-design facts the data does not record, set on every experiment's metadata (as the UI metadata step does) and kept in `sessions/<id>/study_design.json`, so every later integration (`--reintegrate`) puts them back: `{"strain": "Sprague-Dawley", "administrationMeans": "gavage", "articleVehicle": "corn oil"}`. Fields: `species`, `strain`, `articleRoute`, `administrationMeans`, `articleVehicle`, `studyDuration`, controlled vocabulary only. A fact the metadata does not record takes the standard design as a **fallback**: Sprague Dawley rats for five days (`studyDuration`, e.g. `"28d"`, overrides it), by gavage in corn oil for an oral (mg/kg) unit, by inhalation for an air concentration (ppm), no route fallback for other units. These facts also set the apical table captions: "…of Male Rats Administered X for Five Days", or "Exposed to X" for inhalation. The log prints `NOTE: not recorded in the data, standard design used: …`; record the real values with `--design` whenever they differ. Recorded values that disagree across experiments get no fallback. Facts the data never holds (animal source, quarantine, test-article lot and purity, dose rationale) appear as a `[Placeholder: …]` in Materials and Methods, which `--strict` refuses to ship |
| `--front-matter FILE.json` | Front matter, as the Configure screen saves it to `front_matter.json`: `authors`, `contributors`, `publication` (`report_number`, `doi`, `report_date`) and `strain_designation`, the supplier designation the title prints after the strain, e.g. `{"strain_designation": "(Hsd:Sprague Dawley® SD®)"}`. Keys the file gives replace the saved ones |
| `--method-profile NAME` | The analysis method profile (`profiles/<name>.yaml`, ADR-0027): test family per platform, thresholds, BMD acceptance, internal-dose rules, GO ranking. `NAME` fixes the study on that profile; `newest` makes it track the newest profile as profiles are added, which is also the default for a study with no pin. A change of profile archives the old pin and recomputes. The log prints the profile, anything it asks for that the tool does not implement (`NOTE`), and every setting a `.bm2` analysis records differently (`WARNING`, also a `method_mismatch` in the validation report) |
| `--bmd-stats`, `--go-pct`, `--go-min-genes`, `--go-max-genes`, `--go-min-bmd` | GO gene-set table settings for this run, overriding the method profile's (ntp-5day-2025: `fifth_pct,median`, 5, 20, 500, 3). Omit them to use the profile |
| `--reintegrate` | Run integration again even though `integrated.json` exists. This wipes the process caches, so processing starts from scratch. Without the flag, integration is skipped when `integrated.json` is already there |
| `--background` | Also generate and save the Background section (LLM over ATSDR, IRIS and PubChem; needs network). `--model` picks the model |
| `--stop-after validate\|integrate\|process` | Stop after that step and render nothing |
| `--render-only` | Skip the pipeline and render the session as it is now on disk |
| `--surfaces` | Comma-separated list from `docx, html, jats, bookshelf, latex, pdf` (default `docx,html`) |
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

These hold as of 2026-10-05. Appendix A.4 lists every place the report still
lacks data, with what would close it.

- **About This Report** (authors, contributors) is human-set front matter
  (`front_matter.json`, §5.3); nothing in the data supplies it.
- **Background** needs ATSDR and IRIS. Where either is unreachable (the sandbox
  firewall), `--background` saves nothing and says so, rather than writing a
  Background that reports the unreachable sources as data gaps.
- **Appendix C.2 (empirical FDR)** needs the study's synthetic-null analysis,
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

## Appendix A. What in the report comes from the data

This appendix sets out everything in a report that is driven by the data:
the rules (A.1), how each fact is worked out from the files (A.2), where each
part of the report comes from (A.3), and where it still falls short (A.4). It
holds as of 2026-10-07.

### A.1 The rules

- **The integrated dataset is the source of truth.** Every number and study
  fact in the report is read from `integrated.json` (the BMDExpress project
  that Integrate builds) and its sidecars, the per-animal files that keep what
  the pivot drops: cohort (Core or Biosample), observation day, terminal flag
  and units. Nothing reads the raw `.bm2`, `.txt` or `.xlsx` uploads directly.
- **The document tree sets the structure.** Headings, their order and the
  table and figure numbers come from the template
  (`templates/niehs-5day-report.yaml`) and a study's overlay
  (`templates/studies/<id>/view.yaml`). Numbers are given by position, never
  typed in.
- **The method profile sets how the data is analysed.** The statistical
  tests, thresholds, BMD acceptance criteria, internal-dose rules, GO ranking
  and number formats come from the study's pinned profile (`profiles/*.yaml`,
  ADR-0027). The footnotes, Methods text and Appendix D that describe the
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

### A.2 How the data is read

Each fact below is worked out from the files at the step named. Where a rule
is a method setting, the setting's name in the profile is given, with its
`ntp-5day-2025` value.

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
- **Statistics** follow the profile's `apical.statistics`:
  - A Jonckheere trend test runs on every endpoint.
  - When its p ≤ `trend_select_p` (0.01), the trend-sensitive pairwise test
    runs: Williams for weights, Shirley for clinical pathology.
  - Otherwise Dunnett runs for weights and Dunn for clinical pathology
    (`pairwise` per platform).
  - Groups smaller than `min_group_n` (2) are left out.
  - Markers are `*` at p ≤ `alpha` (0.05) and `**` at p ≤ `alpha_strong`
    (0.01).
  - The footnote naming the tests is built from the family that ran.
- **LOEL** is the lowest dose with a significant pairwise difference from
  control.
- **NOEL** is the highest tested dose below the LOEL. It is "ND" when there is
  no LOEL or no dose below it, never the control or the top dose.
- **Direction** (up or down) is shown only when the trend test is significant.
- **Which rows appear.** Every measured endpoint appears in the tables,
  whether or not it is significant. N rows count Core animals.
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

- **Where a BMD comes from.**
  - The `.bm2`'s BMDExpress results are used where they exist.
  - An endpoint the `.bm2` didn't model is fitted with ToxicR Laplace model
    averaging (`apical.bmd.engine`) and marked as filled.
  - Where both exist they must agree, or processing stops.
- **Eligibility.** A BMD is reported only for an endpoint with a significant
  trend and a significant pairwise test (`eligibility: trend_and_pairwise`).
- **BMR.** The BMR is the one the `.bm2` analysis records. Where it records
  none, `bmr_when_unrecorded` (1 SD) is used and footnoted as inferred.
- **Acceptance** (`acceptance`) applies to every BMD, whatever its source.
  Appendix D-1 prints these values:
  - R² < 0.6, BMD/BMDL > 10, or a BMD above the highest dose → "NVM" (no
    viable model);
  - a BMD below ⅓ of the lowest nonzero dose → "<LNZD/3".
- **Precision.** BMDs print at one precision report-wide: 3 decimals for the
  NIEHS-10 method (gene expression without gene-level analysis), else 1.

**Internal dose (Process)**

The rules come from the profile's `internal_dose` settings:

- Tables are built by study day, from biosample animals.
- A group with ≤ 20 % of values detected prints "BD"
  (`bd_if_detected_share_at_most`). Otherwise values below the limit count as
  half the limit (`below_limit: half_limit`).
- Outliers are removed by the Dixon r10 test at α = 0.01 (`outliers`).
- Pairwise markers use Shirley or Dunn, and only when the control has a mean.
- Values print to 3 significant figures (`sig_figs`). Normalized rows divide
  each animal's concentration by its group's nominal dose or exposure
  concentration.
- **Plasma half-lives** use the two-point formula t½ = ln 2 · Δt / ln(C₁/C₂).
  They are computed only with exactly two time points and a falling
  concentration.

**Transcriptomics (Integrate, Process)**

- **Experiments.** Organ and sex come from each experiment's metadata:
  approved metadata, else inferred.
- **Assay.** The assay (TempO-Seq, Affymetrix, Illumina) is read from the
  chip.
- **Sample counts.** The sample-counts table counts each experiment's samples
  per organ, sex and dose.
- **GO tables:**
  - They come from the `.bm2`'s GO category analyses.
  - They are ranked by `genomics.go_ranking` (5th percentile, then median).
  - They are cut by `go_display`: top 5 %, 20 to 500 genes, BMD ≥ 3.
  - Up and down counts come from the genes' directions.
- **Gene tables.** The top genes come from BMDExpress's gene-level (GENE)
  analysis, sorted by BMD. Fold change is the mean over each gene's probes.
- **Methods.** The transcriptomic Methods prompt takes the analysis settings
  the `.bm2` records: version, prefilter, models, BMR and GO filters.
- **Mismatch check.** At integration these recorded settings are compared with
  `genomics.recorded` (BMR 25 % relative deviation, model averaging). A
  disagreement is a `method_mismatch` warning; neither side wins.
- **Appendix C.1 PCA** is computed from the integrated expression matrix.

**Prose built from the data (Process)**

- **No model involved.** These are assembled from the numbers above, so they
  can't disagree with the tables:
  - the Abstract (except its Background sentence);
  - the Summary;
  - the Animal Condition, Clinical Pathology and Internal Dose narratives;
  - Methods' Study Design, Dose Selection and Chemistry.
- **"Most sensitive" lists** in the Abstract and Summary take reliable BMDs
  only:
  - the BMD must be viable and not NVM;
  - it must be at or above the lower limit of extrapolation (⅓ of the lowest
    nonzero dose);
  - it must not be anomalous: a BMD below NOEL/10, or LOEL/10 without a NOEL,
    is left out.
- **LLM-written prose** is given only the session's numbers, and only through
  the NIEHS gateway. Genomics narratives may cite only the papers the
  knowledge base supplies. That prose covers:
  - the apical BMD paragraph;
  - the genomics narratives;
  - the remaining Methods subsections;
  - the Background.

### A.3 Where each part of the report comes from

**Kinds of source:**

- **Data:** computed from the integrated dataset.
- **Profile:** the method profile.
- **Stated:** given by a person.
- **LLM:** written by a model from the data, through the NIEHS gateway only.
- **Fixed:** NIEHS boilerplate.

| Report part | Source | How it's derived | When the data doesn't say |
|---|---|---|---|
| Title: chemical, CASRN | Data / stated | `identity.json` (`--name`, `--casrn`, or the resolver) | — |
| Title: strain, species, route ("Gavage Studies") | Data / stated | The experiments' metadata (`study_design_facts`) | The standard design, logged |
| Title: supplier designation "(Hsd:…)" | Stated | `front_matter.json` `strain_designation` | Left out |
| Report number, date, DOI | Stated | `front_matter.json` `publication` | "to be assigned" placeholders |
| Foreword, Peer Review, Acknowledgments | Fixed | Template | — |
| About This Report | Stated | `front_matter.json` authors and contributors | Pending |
| Abstract: Methods, Results, Summary | Data | Built from the BMD summary, the genomics results and the design facts, without a model | Paragraphs drop out for absent data |
| Abstract: Background, Background section | LLM | ATSDR, IRIS and PubChem lookups (`--background`) | Nothing is saved when a source is unreachable |
| Methods: Study Design, Dose Selection, Chemistry | Data | Group sizes (Core cohort), doses, dose unit, design facts, identity | `[Placeholder: …]` for the source, age, quarantine, randomization, dose rationale, lot and purity |
| Methods: Statistical Analysis, apical BMD | LLM from profile | The prompt is built from the profile's test families, alphas, BMR and acceptance criteria | — |
| Methods: transcriptomic BMD | LLM | The prompt carries the `.bm2`'s recorded settings (BMDExpress version, prefilter, models, BMR, GO filters) | "not recorded" |
| Methods: clinical exams, organ and clin-path endpoints | LLM | The prompt lists the endpoints in the data | — |
| Methods: other subsections | LLM | Fixed guides: sample collection, RNA, sequencing, QC, normalization, internal dose, data accessibility | — (see gap G14) |
| Sample counts table | Data | Animal report and expression samples per organ, sex and dose | Omitted without expression data |
| Results: body, organ weight, clinical pathology tables | Data + profile | Mean ± SE per group; markers from the profile's tests; decimals per endpoint; caption from sexes, species, route and duration; units from the study workbook | A domain that isn't collected reads "not evaluated" |
| Results: Animal Condition, Clinical Pathology narratives | Data | Built from the tables, mortality by cohort, and clinical-sign incidence and onset, without a model | — |
| Results: Internal Dose table and narrative | Data + profile | The BD share, ½-LOD, Dixon outlier test, test family and significant figures come from the profile; units come from the lab workbook | Omitted without concentration data |
| Apical BMD summary | Data + profile | `.bm2` results reconciled with ToxicR; profile acceptance filter (NVM); LOEL/NOEL from the statistics | The BMR is inferred from the profile and footnoted; NOEL is "ND" |
| Apical BMD analytical paragraph | LLM | The summary rows | — |
| Gene set and gene BMD tables | Data + profile | BMDExpress gene-level and GO analyses from the `.bm2`; ranking statistic and cutoffs from the profile; fold change is the mean over probes | — |
| Gene set and gene narratives, References | LLM + knowledge base | Grounded in `bmdx.duckdb`; may cite only the papers it is given | — |
| Summary | Data | Built from the same inputs as the Abstract, without a model | — |
| Appendix A (internal dose method), F (supplemental files) | Stated | Study overlay HTML/TeX (PFHxSAm only) | Pending |
| Appendix B animal roster | Data | Animal report joined to the FASTQ sample names | — |
| Appendix C.1 PCA | Data | Integrated expression matrix | — |
| Appendix C.2 eFDR | — | Not ingested | Pending figure |
| Appendix D acceptance table, configuration table | Profile, data | Profile criteria; the `.bm2` analyses' recorded configuration | — |
| Appendix D, C and E prose | Fixed | Shared freeform files | — |

**Precedence when sources disagree:**

| Fact | Precedence (strongest first) |
|---|---|
| Dose unit | `--dose-unit` (stated) > the one unit the data records > `mg/kg` (logged) |
| Design facts | Experiment metadata, including the `--design` facts re-applied at each integration > the standard design (logged). Recorded values that disagree get no fallback |
| Experiment organ and sex | Approved metadata (`metadata_approved.json`) > inference from names and the LLM |
| Method setting | Request (CLI or UI) > study overlay `methods:` > pinned profile > built-in default. Each value carries its source |
| Apical BMR | Recorded in the `.bm2` > the profile's `bmr_when_unrecorded` (footnoted as inferred) |
| `.bm2` setting vs profile | Neither wins. A disagreement is a `method_mismatch` warning |

### A.4 Gap analysis

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
| G4 | eFDR (synthetic-null analysis) | Appendix C.2 is pending; Methods says it isn't included | Ingest the synthetic-null BMDExpress results |
| G5 | Theoretical inhaled dose (inhalation studies) | Rows normalized by inhaled dose aren't built | A file recording the inhaled-dose calculation |
| G6 | Authors, report number, DOI, Background sources | Front matter and `--background` on the host | Human input; host network |

**Wiring gaps**

| # | Gap | Today | To close it |
|---|---|---|---|
| G7 | Experiment metadata (organ, sex, species) | Inferred from experiment names (LLM) unless approved; the source-of-truth `.xlsx` is primary only for classification | Read the workbook's Key and Data sheets first (ADR-0017/0019) |
| G8 | Multi-species studies (NIEHS-13: rats and mice) | One gene-expression `.bm2` per pool, and genomics keyed by organ and sex, so species collide. Our NIEHS-13 session holds the rat data only | Key genomics by species and keep every expression project |
| G9 | Animal report counts NIEHS-13's biosample animals as Core | The animal report's Core count is too high; the tables use the right cohort | Use the cohort rule the tables use |
| G10 | The UI's Process step sends `mg/kg` when no unit is set | Hides the recorded-unit and logged fallback | Send nothing and let the server resolve it |
| G11 | A text or CSV file's platform is read from its file name | A file not named to NTP conventions is unassigned or misclassified until overridden | Classify by content (endpoint names), as `.bm2` files are |
| G12 | Apical outlier exclusion (NIEHS staff judgement) | Not represented; the profile says `outliers: null` | A per-study exclusion list in the overlay |
| G13 | NIEHS-10's apical engine (BMDS 2.7) and `all_endpoints` | Listed as profile deviations; the substitute runs | Implement, or accept as recorded |

**Text gaps**

| # | Gap | Today | To close it |
|---|---|---|---|
| G14 | Methods guides for internal dose ("LC-MS/MS"), sample collection, RNA, sequencing, QC and instruments are fixed text | The LLM writes plausible, older-era protocol text | Move the guides into the profile, or build them from data |
| G15 | The transcriptomic BMD guide fixes "5th percentile", "≥3 genes, ≥5 %" and "median over probes" | Can disagree with the profile's GO ranking | Generate from the profile, as the statistics guide is |
| G16 | Appendix D prose (ToxicR, Laplace model averaging) and Appendix C prose | Fixed text | Generate from the profile and the recorded configuration |
| G17 | Appendix E describes liver, kidney and heart whatever was weighed | Can describe organs the study didn't weigh, and miss ones it did | Select descriptions by the organs in the data |
| G18 | The "most sensitive" filters use a fixed lower limit of extrapolation (⅓ of the lowest nonzero dose) and anomaly ratio (10) | Fixed in code, not the profile | Read them from the profile, as the acceptance criteria are |
| G19 | BMD precision (1 or 3 decimals) is inferred from whether the `.bm2` has gene-level analyses | A data heuristic standing in for a method setting | A profile setting |
| G20 | The transcriptomics Methods guides name TempO-Seq and the S1500+ platform | Wrong for an Affymetrix or Illumina study, although the assay is detected from the chip | Build the guides from the detected assay |
| G21 | Peer Review says the design and methods are identical to those reviewed | Not checked | Compare the pinned profile with the reviewed one |
| G22 | The title doesn't name the sex of a one-sex study (NIEHS: "Male Sprague Dawley … Rats"), and Peer Review names the study by its short title, without the CASRN, designation and study type | Both are built from the design facts but drop these parts | Build both from the cover title, with the sexes in the data |

**Structure gaps**

| # | Gap | Today | To close it |
|---|---|---|---|
| G23 | NIEHS-13's "most potent GO per tissue" table, the Appendix E gene-set definitions and NIEHS-13's appendix order | Missing; the order differs | Template changes, checked against the reference fixtures |
