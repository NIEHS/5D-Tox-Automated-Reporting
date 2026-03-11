#!/usr/bin/env bash
# deploy.sh — build and deploy 5dToxReport (rlm-bmdx) to Google Cloud Run.
#
# What it does:
#   1. Copies BMDExpress 3 JARs into _bmdx_jars/ (temporary, gitignored).
#   2. Copies the bmdx.duckdb knowledge base into _data/.
#   3. Clears per-user GCS session buckets (fresh start each deploy).
#   4. Submits the build context to Cloud Build (one image).
#   5. Deploys TWO Cloud Run services from the same image, each with its
#      own GCS FUSE volume mount for isolated session storage:
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
DAN_BUCKET="rlm-bmdx-sessions-dan"
SCOTT_SERVICE="rlm-bmdx-scott"
SCOTT_USER="scott_2d774f16"
SCOTT_BUCKET="rlm-bmdx-sessions-scott"

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

# -- Step 3: Session buckets (preserved across deploys) ---------------------
# GCS session buckets persist across deploys so users don't lose work.
# To manually clear a bucket:
#   gcloud storage rm "gs://rlm-bmdx-sessions-dan/**" --recursive --project=rlm-pipe
#   gcloud storage rm "gs://rlm-bmdx-sessions-scott/**" --recursive --project=rlm-pipe

echo "==> Session buckets preserved (not clearing)"

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
    local bucket="$3"

    echo "==> Deploying ${service} (allowed: ${allowed}, bucket: ${bucket})..."
    gcloud run deploy "$service" \
      --image "$IMAGE" \
      --region "$REGION" \
      --project "$PROJECT_ID" \
      --allow-unauthenticated \
      --port 8080 \
      --memory 2Gi \
      --cpu 2 \
      --set-env-vars "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-},ALLOWED_USERS=${allowed}" \
      --session-affinity \
      --execution-environment gen2 \
      --add-volume name=sessions-vol,type=cloud-storage,bucket="${bucket}" \
      --add-volume-mount volume=sessions-vol,mount-path=/app/sessions

    echo "    $(gcloud run services describe "$service" \
      --region "$REGION" --project "$PROJECT_ID" \
      --format='value(status.url)')"
}

if $SINGLE_MODE; then
    # Single-service mode — use env vars (bucket defaults to dan's)
    deploy_service "${SERVICE_NAME:-rlm-bmdx}" "${ALLOWED_USERS:-dan_22bc6d42,scott_2d774f16}" "${SESSION_BUCKET:-$DAN_BUCKET}"
else
    # Dual deploy — each user gets their own service and session bucket
    deploy_service "$DAN_SERVICE"   "$DAN_USER"   "$DAN_BUCKET"
    deploy_service "$SCOTT_SERVICE" "$SCOTT_USER" "$SCOTT_BUCKET"
fi

# -- Step 6: Clean up -----------------------------------------------------

echo "==> Cleaning up temporary directories..."
rm -rf _bmdx_jars _data

echo "==> Done."
