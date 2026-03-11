# Dockerfile — Cloud Run service for 5dToxReport (rlm-bmdx).
#
# Single-stage build: Python 3.12 + Java 21 JRE in one image.
# The app is a FastAPI server (uvicorn) that also serves static JS/CSS
# from the web/ directory.  Java is required at runtime because
# BMDExpress 3 helper classes (ExportBm2, ExportGenomics, RunPrefilter,
# IntegrateProject) are invoked via subprocess to parse .bm2 dose-response
# files and run Williams/Dunnett statistical tests.
#
# The deploy script (deploy.sh) stages external dependencies into
# _bmdx_jars/ before building, so the Dockerfile expects:
#   _bmdx_jars/bmdx-core.jar   — headless BMDExpress 3 library
#   _bmdx_jars/deps/            — Maven-resolved dependency JARs

FROM python:3.12-slim
WORKDIR /app

# ---------------------------------------------------------------------------
# System dependencies: Java 21 JRE for BMDExpress 3 subprocess calls.
# Also install curl for health checks and ca-certificates for HTTPS.
# ---------------------------------------------------------------------------
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        openjdk-21-jre-headless \
        ca-certificates \
        curl \
        fonts-liberation && \
    rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Install uv (fast Python package installer) from its official image.
# ---------------------------------------------------------------------------
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# ---------------------------------------------------------------------------
# Python dependencies — cached layer, only re-runs when lockfile changes.
# ---------------------------------------------------------------------------
COPY pyproject.toml uv.lock ./
RUN uv pip install --system .

# ---------------------------------------------------------------------------
# Backend source — all Python modules at the project root.
# Copies every .py file rather than listing individually, so newly-added
# modules are automatically included.  Also copies the Typst report template
# (report.typ) used by report_pdf.py for PDF/UA-1 export.
# ---------------------------------------------------------------------------
COPY *.py ./
COPY report.typ cover-bg.jpg ./

# ---------------------------------------------------------------------------
# Frontend assets — static HTML/CSS/JS served by FastAPI StaticFiles.
# ---------------------------------------------------------------------------
COPY web/ ./web/

# ---------------------------------------------------------------------------
# Pre-compiled Java helper classes (ExportBm2, ExportGenomics, etc.).
# These are invoked by java_bridge.py via subprocess.
# ---------------------------------------------------------------------------
COPY java/ ./java/

# ---------------------------------------------------------------------------
# BMDExpress 3 JARs — staged by deploy.sh into _bmdx_jars/.
# At runtime, BMDX_PROJECT_ROOT points here so java_bridge.py finds
# bmdx-core.jar and target/deps/*.jar.
# ---------------------------------------------------------------------------
COPY _bmdx_jars/bmdx-core.jar ./bmdx/target/bmdx-core.jar
COPY _bmdx_jars/deps/ ./bmdx/target/deps/

# ---------------------------------------------------------------------------
# DuckDB knowledge base — staged by deploy.sh into _data/.
# Contains gene-gene co-mention data, organ mappings, GO ground truth.
# ---------------------------------------------------------------------------
COPY _data/bmdx.duckdb ./bmdx.duckdb

# ---------------------------------------------------------------------------
# Sessions directory — created empty here; at runtime it is overlaid by a
# GCS FUSE volume mount (gs://rlm-bmdx-sessions/sessions/) so session data
# persists independently of the container image.  The mkdir ensures the
# mount point exists even if the volume isn't attached (local dev).
# ---------------------------------------------------------------------------
RUN mkdir -p /app/sessions

# ---------------------------------------------------------------------------
# Environment: tell java_bridge.py where the BMDExpress JARs live.
# Cloud Run injects $PORT (defaults to 8080).
# ---------------------------------------------------------------------------
ENV BMDX_PROJECT_ROOT=/app/bmdx
EXPOSE 8080

# ---------------------------------------------------------------------------
# Start uvicorn — single worker because DuckDB isn't safe to share across
# forked processes.  Cloud Run routes to one container at a time by default.
# ---------------------------------------------------------------------------
CMD ["python", "-m", "uvicorn", "background_server:app", \
     "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
