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
| `--design FILE.json` | Study-design facts the data does not record, set on every experiment's metadata (as the UI metadata step does): `{"strain": "Sprague-Dawley", "administrationMeans": "gavage", "articleVehicle": "corn oil"}`. Fields: `species`, `strain`, `articleRoute`, `administrationMeans`, `articleVehicle`, `studyDuration`, controlled vocabulary only. A fact the metadata does not record takes the standard design as a **fallback**: Sprague Dawley rats for five days (`studyDuration`, e.g. `"28d"`, overrides it), by gavage in corn oil for an oral (mg/kg) unit, by inhalation for an air concentration (ppm), no route fallback for other units. These facts also set the apical table captions: "…of Male Rats Administered X for Five Days", or "Exposed to X" for inhalation. The log prints `NOTE: not recorded in the data, standard design used: …`; record the real values with `--design` whenever they differ. Recorded values that disagree across experiments get no fallback. Facts the data never holds (animal source, quarantine, test-article lot and purity, dose rationale) appear as a `[Placeholder: …]` in Materials and Methods, which `--strict` refuses to ship |
| `--method-profile NAME` | The analysis method profile (`profiles/<name>.yaml`, ADR-0027) to pin for the study: test family per platform, thresholds, BMD acceptance, internal-dose rules, GO ranking. A study with no pin gets the newest profile at integration (`pinned by default`, logged); re-pinning archives the old pin and recomputes. The log prints the profile, anything it asks for that the tool does not implement (`NOTE`), and every setting a `.bm2` analysis records differently (`WARNING`, also a `method_mismatch` in the validation report) |
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

# 6. Process (async; minutes when cold)
payload = asyncio.run(process_step(ID, {
    "compound_name": "PFHxSAm", "dose_unit": "mg/kg", "bmd_stats": ["median"],
    "go_pct": 5, "go_min_genes": 20, "go_max_genes": 500, "go_min_bmd": 3,
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
| `-u` | Dose unit (defaults to `mg/kg`, with a printed note) |
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
post /api/process-integrated/$ID '{"compound_name": "PFHxSAm", "dose_unit": "mg/kg",
  "bmd_stats": ["median"], "go_pct": 5, "go_min_genes": 20, "go_max_genes": 500,
  "go_min_bmd": 3}' > process_payload.json
```

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
feed the About This Report and Publication Details sections:

```bash
post /api/document/$ID/front-matter '{"front_matter": {
  "authors": [{"name": "A. Author", "affiliation": "NIEHS", "role": "Study Scientist"}],
  "contributors": [], "publication": {"report_number": "NIEHS 14", "report_date": "2026-10"}}}'
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
- **Re-integration wipes the process caches**, except the BMDS cache, whose
  hash is based on the data itself. The next process then recomputes. Route A
  skips integration when `integrated.json` exists unless you pass
  `--reintegrate`. Route B always integrates.
- **Adding or replacing a file** after validation invalidates the downstream
  artifacts (validation report, `integrated.json`, animal report, caches).
  Approved section text is kept but marked `stale`.
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

These hold as of 2026-10-05:

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
