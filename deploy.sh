#!/usr/bin/env bash
# deploy.sh — build and deploy 5dToxReport (rlm-bmdx) to Google Cloud Run.
#
# What it does:
#   1. Copies BMDExpress 3 JARs into _bmdx_jars/ (temporary, gitignored).
#   2. Copies the bmdx.duckdb knowledge base into _data/.
#   3. Stages session data into _sessions/ (excludes LMDB cache).
#   4. Submits the build context to Cloud Build (one image).
#   5. Deploys TWO Cloud Run services from the same image:
#        rlm-bmdx-dan   — allowed user: dan_22bc6d42
#        rlm-bmdx-scott — allowed user: scott_2d774f16
#      Each service has its own session state (ephemeral per container,
#      persisted via sync.sh push/pull).
#   6. Cleans up temporary directories.
#
# Environment variables (all optional, sensible defaults):
#   GCP_PROJECT      — Google Cloud project ID (default: rlm-pipe)
#   GCP_REGION       — Cloud Run region (default: us-east1)
#   BMDX_PROJECT_DIR — path to BMDExpress-3 project (default: ~/Dev/Projects/BMDExpress-3)
#
# Single-user deploy (skip the dual deploy, just one service):
#   SERVICE_NAME=rlm-bmdx-dan ALLOWED_USERS=dan_22bc6d42 ./deploy.sh --single

set -euo pipefail

# -- Configuration ----------------------------------------------------------

PROJECT_ID="${GCP_PROJECT:-rlm-pipe}"
REGION="${GCP_REGION:-us-east1}"
REPO="rlm-bmdx-repo"
# Base image name — both services share the same built image
IMAGE_NAME="rlm-bmdx"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${IMAGE_NAME}:latest"
BMDX_PROJECT_DIR="${BMDX_PROJECT_DIR:-$HOME/Dev/Projects/BMDExpress-3}"

# Per-user service definitions.  Each entry is "service_name:allowed_user".
# Override with SERVICE_NAME + ALLOWED_USERS + --single for custom deploys.
DAN_SERVICE="rlm-bmdx-dan"
DAN_USER="dan_22bc6d42"
SCOTT_SERVICE="rlm-bmdx-scott"
SCOTT_USER="scott_2d774f16"

# -- Parse flags -----------------------------------------------------------

SINGLE_MODE=false
if [[ "${1:-}" == "--single" ]]; then
    SINGLE_MODE=true
fi

# -- Step 0: Ensure Artifact Registry repo exists --------------------------

echo "==> Ensuring Artifact Registry repo '${REPO}' exists..."
gcloud artifacts repositories describe "$REPO" \
  --location="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1 || \
gcloud artifacts repositories create "$REPO" \
  --repository-format=docker \
  --location="$REGION" \
  --project="$PROJECT_ID" \
  --description="5dToxReport Docker images"

# -- Step 1: Stage BMDExpress 3 JARs --------------------------------------

echo "==> Copying BMDExpress 3 JARs from ${BMDX_PROJECT_DIR}..."
rm -rf _bmdx_jars
mkdir -p _bmdx_jars/deps
cp "$BMDX_PROJECT_DIR/target/bmdx-core.jar" _bmdx_jars/
cp "$BMDX_PROJECT_DIR/target/deps/"*.jar _bmdx_jars/deps/

# -- Step 2: Stage DuckDB knowledge base -----------------------------------

echo "==> Copying bmdx.duckdb knowledge base..."
rm -rf _data
mkdir -p _data
cp bmdx.duckdb _data/bmdx.duckdb

# -- Step 3: Stage session data --------------------------------------------

echo "==> Staging session data..."
rm -rf _sessions
mkdir -p _sessions

if [ -d sessions ]; then
    rsync -a \
        --exclude='_bm2_cache' \
        --exclude='files' \
        sessions/ _sessions/
    session_count=$(find _sessions -maxdepth 1 -mindepth 1 -type d | wc -l)
    echo "    Staged ${session_count} session(s)"
else
    echo "    No sessions/ directory found — deploying with empty sessions"
fi

# -- Step 4: Cloud Build ---------------------------------------------------
# One image build, shared by both services.

echo "==> Submitting to Cloud Build..."
gcloud builds submit --tag "$IMAGE" --timeout=20m --project="$PROJECT_ID"

# -- Step 5: Deploy to Cloud Run ------------------------------------------
# Helper function — deploys a single Cloud Run service with a given
# allowed-user list.  Both services use the same image but get different
# ALLOWED_USERS env vars, giving each user their own session space.

deploy_service() {
    local service="$1"
    local allowed="$2"

    echo "==> Deploying ${service} (allowed: ${allowed})..."
    gcloud run deploy "$service" \
      --image "$IMAGE" \
      --region "$REGION" \
      --project "$PROJECT_ID" \
      --allow-unauthenticated \
      --port 8080 \
      --memory 2Gi \
      --cpu 2 \
      --set-env-vars "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-},ALLOWED_USERS=${allowed}" \
      --session-affinity

    echo "    $(gcloud run services describe "$service" \
      --region "$REGION" --project "$PROJECT_ID" \
      --format='value(status.url)')"
}

if $SINGLE_MODE; then
    # Single-service mode — use SERVICE_NAME and ALLOWED_USERS from env
    deploy_service "${SERVICE_NAME:-rlm-bmdx}" "${ALLOWED_USERS:-dan_22bc6d42,scott_2d774f16}"
else
    # Dual deploy — one service per user
    deploy_service "$DAN_SERVICE"   "$DAN_USER"
    deploy_service "$SCOTT_SERVICE" "$SCOTT_USER"
fi

# -- Step 6: Clean up -----------------------------------------------------

echo "==> Cleaning up temporary directories..."
rm -rf _bmdx_jars _data _sessions

echo "==> Done."
