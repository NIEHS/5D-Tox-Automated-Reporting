# 5dToxReport Cloud Deployment Guide

## Overview

5dToxReport runs on Google Cloud Run as a containerized FastAPI application.
The deployment produces **two independent Cloud Run services** from a single
Docker image — one per user — so each user gets their own session state
without sharing a container.

| Service           | URL (auto-assigned)                                    | Username         |
|-------------------|--------------------------------------------------------|------------------|
| `rlm-bmdx-dan`   | `https://rlm-bmdx-dan-<id>.us-east1.run.app`          | `dan_22bc6d42`   |
| `rlm-bmdx-scott` | `https://rlm-bmdx-scott-<id>.us-east1.run.app`        | `scott_2d774f16` |

Each service has:
- 2 GiB RAM, 2 vCPUs
- Session affinity (routes returning users to the same container)
- Public access (no Google IAM login required)
- A user gate that rejects API requests without a valid `?user=` parameter

---

## Prerequisites

1. **Google Cloud SDK** (`gcloud`) — installed at `~/google-cloud-sdk/`.
   Make sure it's on your PATH or the scripts will find it automatically.

2. **GCP project** — defaults to `rlm-pipe`. The project must have:
   - Cloud Build API enabled
   - Cloud Run API enabled
   - Artifact Registry API enabled

3. **Authenticated gcloud session**:
   ```bash
   gcloud auth login
   gcloud config set project rlm-pipe
   ```

4. **ANTHROPIC_API_KEY** — required for LLM narrative generation.
   Export it before deploying:
   ```bash
   export ANTHROPIC_API_KEY=sk-ant-api03-...
   ```

5. **BMDExpress-3 project** — must be built locally with the bmdx-core
   JAR and Maven dependencies in place:
   ```
   ~/Dev/Projects/BMDExpress-3/
       target/bmdx-core.jar
       target/deps/*.jar       (47 JARs, ~71 MB total)
   ```
   Override the location with `BMDX_PROJECT_DIR` if it lives elsewhere.

---

## Deployment files

| File              | Purpose                                                    |
|-------------------|------------------------------------------------------------|
| `Dockerfile`      | Full image build: Python 3.12 + Java 21 + app + data      |
| `Dockerfile.sync` | Fast session-only layer on top of the existing image       |
| `deploy.sh`       | Build image + deploy both services to Cloud Run            |
| `sync.sh`         | Pull/push session data between local machine and cloud     |
| `.gcloudignore`   | Filters the Cloud Build upload (keeps it under ~90 MB)     |

---

## Full deploy

Builds the Docker image from scratch (Python deps, Java JRE, app code,
BMDExpress JARs, DuckDB knowledge base, session data) and deploys both
services.  Takes ~3 minutes.

```bash
export ANTHROPIC_API_KEY=sk-ant-api03-...
./deploy.sh
```

### What deploy.sh does, step by step

1. **Ensures the Artifact Registry repo exists** (`rlm-bmdx-repo` in
   `us-east1`).  Creates it on first run.

2. **Stages BMDExpress 3 JARs** — copies `bmdx-core.jar` and all 47
   dependency JARs from `~/Dev/Projects/BMDExpress-3/target/` into
   a temporary `_bmdx_jars/` directory.  The Dockerfile copies these
   into `/app/bmdx/target/` where `java_bridge.py` finds them via
   `BMDX_PROJECT_ROOT=/app/bmdx`.

3. **Stages the DuckDB knowledge base** — copies `bmdx.duckdb` into
   `_data/`.  Contains gene-gene co-mention data, organ mappings, and
   GO ground truth used by the interpret module.

4. **Stages session data** — copies `sessions/` into `_sessions/`,
   excluding:
   - `_bm2_cache/` — LMDB cache that uses memory-mapped files; not
     portable, rebuilds on demand when the server processes .bm2 files
   - `files/` — uploaded .bm2 files (large, can be re-uploaded)

   This bakes approved report sections and version history into the
   image so they survive container restarts.

5. **Submits to Cloud Build** — uploads the filtered working directory
   (~90 MB compressed) and builds the Docker image.  The image is
   pushed to Artifact Registry.

6. **Deploys two Cloud Run services** from the same image, each with
   a different `ALLOWED_USERS` environment variable:
   - `rlm-bmdx-dan` with `ALLOWED_USERS=dan_22bc6d42`
   - `rlm-bmdx-scott` with `ALLOWED_USERS=scott_2d774f16`

7. **Cleans up** temporary staging directories (`_bmdx_jars/`, `_data/`,
   `_sessions/`).

### Single-service deploy

To deploy just one service (e.g., only dan's):

```bash
SERVICE_NAME=rlm-bmdx-dan ALLOWED_USERS=dan_22bc6d42 ./deploy.sh --single
```

---

## Session persistence

Cloud Run containers are ephemeral.  When a container shuts down (due to
inactivity, scaling, or redeployment), any sessions created at runtime
are lost.  The persistence model works around this:

### How it works

1. **At deploy time**, `deploy.sh` bakes the local `sessions/` directory
   into the Docker image.  Every new container starts with this snapshot.

2. **At runtime**, the app reads and writes `sessions/` normally.  New
   approved sections, version history, and style profiles are written to
   the container's filesystem.

3. **Before the next deploy**, use `sync.sh pull` to download runtime
   sessions from the cloud back to your local machine.  Then the next
   `deploy.sh` bakes them into the new image.

### The sync workflow

```
Local machine                     Cloud Run
─────────────                     ─────────
sessions/  ──── deploy.sh ────>   /app/sessions/   (baked into image)
                                       |
                                  user approves sections at runtime
                                       |
sessions/  <── sync.sh pull ────  /app/sessions/   (runtime state)
     |
     └── deploy.sh or sync.sh push ──> new image with updated sessions
```

### Important: pull before deploy

If sessions were created on the cloud since the last deploy, you must
pull them before deploying again.  Otherwise the new image overwrites
the cloud sessions with your (stale) local copy:

```bash
# 1. Pull latest sessions from both services
./sync.sh dan pull
./sync.sh scott pull

# 2. Now deploy — bakes the pulled sessions into the new image
./deploy.sh
```

---

## Syncing sessions

`sync.sh` provides fast bidirectional sync between the local machine and
a specific Cloud Run service.

### Pull sessions from cloud

Downloads all session data (approved sections, version history, style
profile) as a `.tar.gz` from the running service and extracts it into
the local `sessions/` directory.

```bash
./sync.sh dan pull        # pull from dan's instance
./sync.sh scott pull      # pull from scott's instance
```

The pull endpoint is `GET /api/admin/sessions/export`, which streams a
tarball of `sessions/` excluding the LMDB cache.  The `?user=` parameter
is included automatically so the user gate allows the request.

### Push sessions to cloud (fast)

Stages local `sessions/` into the image and redeploys.  Uses
`Dockerfile.sync` which extends the existing image with just one new
layer — no Python reinstall, no Java JRE download, no JAR copy.

Takes ~30-60 seconds vs ~3 minutes for a full deploy.

```bash
./sync.sh dan push        # fast push to dan's instance
./sync.sh scott push      # fast push to scott's instance
```

### Push with full rebuild

If code has changed (Python files, frontend JS/CSS, Java classes), use
`--full` to trigger a complete rebuild via `deploy.sh`:

```bash
./sync.sh dan push --full
```

---

## User gate

The server uses a lightweight access control mechanism: every `/api/`
request must include a `?user=<username>` query parameter that matches
one of the values in the `ALLOWED_USERS` environment variable.

### How it works

- **Backend**: A FastAPI middleware intercepts all `/api/` requests.
  If `ALLOWED_USERS` is set and the `?user=` parameter is missing or
  doesn't match, the server returns HTTP 403.  Static assets (HTML, CSS,
  JS) are served without the check.

- **Frontend**: The browser's `fetch()` function is wrapped to
  automatically append `?user=<name>` to every `/api/` request.  The
  username is stored in `localStorage` after the first login.  One
  non-fetch API call (`oboe()` for streaming JSON preview) has the
  parameter added manually.

- **Login prompt**: On first visit, the app probes the server to check
  if authentication is required.  If the server returns 403, a login
  overlay appears asking for a username.  The entered name is validated
  by making a probe request — if the server accepts it, the name is
  stored and the app is revealed.

### Open mode (local development)

If `ALLOWED_USERS` is not set or empty, the gate is disabled.  All API
requests are accepted regardless of the `?user=` parameter.  The login
prompt never appears.  This is the default for local development:

```bash
# No ALLOWED_USERS — open mode
uv run python background_server.py
```

### Restricted mode (cloud deployment)

`deploy.sh` sets `ALLOWED_USERS` for each service.  Each service only
accepts its own user:

- `rlm-bmdx-dan` accepts `dan_22bc6d42`
- `rlm-bmdx-scott` accepts `scott_2d774f16`

The usernames include a random suffix (GUID fragment) to make them
unguessable.  This is not real authentication — there are no passwords
or tokens — but it's enough to prevent casual access.

---

## Docker image contents

The image is ~500 MB and contains:

```
/app/
    *.py                    Python backend (FastAPI server + all modules)
    web/                    Static frontend (HTML, CSS, JS)
    java/                   Pre-compiled Java helper .class files
    bmdx/
        target/
            bmdx-core.jar   BMDExpress 3 headless library
            deps/           47 Maven dependency JARs (~71 MB)
    bmdx.duckdb             Gene knowledge base (~13 MB)
    sessions/               Baked-in session data (approved sections, history)
```

System packages:
- Python 3.12 (Debian Trixie slim)
- OpenJDK 21 JRE (for BMDExpress subprocess calls)
- curl, ca-certificates

Python dependencies (44 packages installed via `uv`):
- `fastapi`, `uvicorn` — web framework and ASGI server
- `anthropic` — Claude API for LLM narrative generation
- `duckdb` — analytical queries on the gene knowledge base
- `pandas`, `scipy`, `networkx` — data processing and statistics
- `python-docx` — DOCX report export
- `typst` — PDF report generation
- `lmdb`, `orjson` — high-performance .bm2 caching
- `javaobj-py3` — Java serialization format parsing
- Full list in `pyproject.toml`

---

## Environment variables

| Variable            | Required | Default                              | Description                                         |
|---------------------|----------|--------------------------------------|-----------------------------------------------------|
| `ANTHROPIC_API_KEY` | Yes      | (none)                               | Claude API key for LLM features                     |
| `ALLOWED_USERS`     | No       | (empty = open mode)                  | Comma-separated list of allowed usernames            |
| `BMDX_PROJECT_ROOT` | No       | `/app/bmdx` (set in Dockerfile)      | Path to BMDExpress JARs inside the container         |
| `GCP_PROJECT`       | No       | `rlm-pipe`                           | Google Cloud project ID (deploy scripts only)        |
| `GCP_REGION`        | No       | `us-east1`                           | Cloud Run region (deploy scripts only)               |
| `BMDX_PROJECT_DIR`  | No       | `~/Dev/Projects/BMDExpress-3`        | Local BMDExpress-3 path (deploy scripts only)        |
| `SERVICE_NAME`      | No       | `rlm-bmdx`                           | Cloud Run service name (--single mode only)           |

---

## Admin API endpoints

Two endpoints are available for operational use.  Both are gated by the
`?user=` parameter like all other API endpoints.

### GET /api/admin/sessions/export

Returns a `.tar.gz` archive of all session data (excluding the LMDB
cache).  Used by `sync.sh pull`.

```bash
curl -o sessions.tar.gz \
  "https://rlm-bmdx-dan-<id>.us-east1.run.app/api/admin/sessions/export?user=dan_22bc6d42"
```

### GET /api/admin/sessions/summary

Returns a JSON summary of all sessions — DTXSID, section count, and
section keys for each.  Useful for verifying that a sync moved the
expected data.

```bash
curl -s "https://rlm-bmdx-dan-<id>.us-east1.run.app/api/admin/sessions/summary?user=dan_22bc6d42" | python -m json.tool
```

Example response:
```json
{
    "sessions": [
        {
            "dtxsid": "DTXSID6020430",
            "sections": 5,
            "section_keys": ["background", "methods", "bmd-summary", "genomics-liver_m", "summary"]
        }
    ],
    "count": 1
}
```

---

## Common workflows

### First-time setup

```bash
# Authenticate with Google Cloud
gcloud auth login
gcloud config set project rlm-pipe

# Set the API key
export ANTHROPIC_API_KEY=sk-ant-api03-...

# Deploy both services
./deploy.sh
```

### Code change (Python, JS, or CSS)

```bash
# Pull any cloud sessions first
./sync.sh dan pull
./sync.sh scott pull

# Full rebuild and deploy
export ANTHROPIC_API_KEY=sk-ant-api03-...
./deploy.sh
```

### Session-only update (no code changes)

```bash
# Push local sessions to a specific service
./sync.sh dan push
./sync.sh scott push
```

### Download cloud sessions for local dev

```bash
./sync.sh dan pull
# Now sessions/ has the cloud data — start the local server
uv run python background_server.py
```

### Check what's deployed

```bash
# List running services
gcloud run services list --region us-east1 --project rlm-pipe

# Get a specific service URL
gcloud run services describe rlm-bmdx-dan \
  --region us-east1 --project rlm-pipe \
  --format='value(status.url)'

# Check sessions on a running service
curl -s "https://<url>/api/admin/sessions/summary?user=dan_22bc6d42"
```

### Tear down

```bash
# Delete both services
gcloud run services delete rlm-bmdx-dan --region us-east1 --project rlm-pipe
gcloud run services delete rlm-bmdx-scott --region us-east1 --project rlm-pipe

# Delete the Artifact Registry repo (and all images)
gcloud artifacts repositories delete rlm-bmdx-repo \
  --location us-east1 --project rlm-pipe
```

---

## Troubleshooting

### "gcloud: command not found"

The deploy scripts expect `gcloud` on PATH.  Add it:
```bash
export PATH="$HOME/google-cloud-sdk/bin:$PATH"
```
Or add this to your shell profile (`~/.bashrc` or `~/.zshrc`).

### Build fails with "Package openjdk-17-jre-headless has no installation candidate"

The Dockerfile uses `python:3.12-slim` which is based on Debian Trixie.
Trixie only ships OpenJDK 21.  The Dockerfile already uses
`openjdk-21-jre-headless` — if you see this error, you may have a stale
Dockerfile.

### Cloud Run returns 403 on all API calls

The `ALLOWED_USERS` environment variable is set but the frontend isn't
sending the `?user=` parameter.  This can happen if:
- The browser has cached an old version of `state.js` (clear cache or
  hard refresh with Ctrl+Shift+R)
- The username stored in localStorage doesn't match `ALLOWED_USERS`
  (open DevTools > Application > Local Storage > clear `5dtox-user`)

### Sessions lost after deploy

You forgot to pull before deploying.  The new image overwrites the
container's `sessions/` with whatever was in the local `sessions/` at
build time.  Always run `sync.sh pull` before `deploy.sh`.

### LMDB cache errors after deploy

The LMDB cache (`sessions/_bm2_cache/`) is not included in the image
because it uses memory-mapped files that aren't portable across machines.
It rebuilds automatically when the server processes .bm2 files.  The
first .bm2 process after a deploy will be slightly slower (triggers a
Java subprocess export).  Subsequent processes use the rebuilt cache.

### Cloud Build upload is too large

The `.gcloudignore` file filters the upload to ~90 MB.  If it's much
larger, check for unexpected files:
```bash
# See what would be uploaded
gcloud meta list-files-for-upload
```
Common culprits: `.venv/`, large output files, untracked data files.
