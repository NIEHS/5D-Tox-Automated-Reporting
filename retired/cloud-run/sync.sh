#!/usr/bin/env bash
# sync.sh — fast state sync between local dev and Cloud Run for 5dToxReport.
#
# This script provides two operations:
#
#   sync.sh dan push       — fast session-only deploy for dan's service
#   sync.sh scott push     — fast session-only deploy for scott's service
#   sync.sh dan push --full — full rebuild via deploy.sh
#   sync.sh dan pull        — download sessions from dan's cloud instance
#   sync.sh scott pull      — download sessions from scott's cloud instance
#
# The first argument selects the user/service.  Valid values: dan, scott.
#
# Environment variables (all optional, sensible defaults):
#   GCP_PROJECT  — Google Cloud project ID (default: rlm-pipe)
#   GCP_REGION   — Cloud Run region (default: us-east1)
#   CLOUD_URL    — base URL override (auto-detected if unset)

set -euo pipefail

# -- Configuration ----------------------------------------------------------

PROJECT_ID="${GCP_PROJECT:-rlm-pipe}"
REGION="${GCP_REGION:-us-east1}"
REPO="rlm-bmdx-repo"
IMAGE_NAME="rlm-bmdx"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${IMAGE_NAME}:latest"

# Resolve the gcloud binary.  The user's install lives under ~/google-cloud-sdk
# which may not be on $PATH in non-interactive shells.
GCLOUD="${GCLOUD:-${HOME}/google-cloud-sdk/bin/gcloud}"
if ! command -v "$GCLOUD" &>/dev/null; then
    GCLOUD="gcloud"
fi

# ---------------------------------------------------------------------------
# Helper: stage_sessions
#
# Copies sessions/ into the _sessions/ staging directory, excluding the
# LMDB cache (_bm2_cache/) which uses mmap and rebuilds on demand, and
# uploaded .bm2 files (large, can be re-uploaded).
# ---------------------------------------------------------------------------
stage_sessions() {
    echo "==> Staging sessions/ into _sessions/..."
    rm -rf _sessions
    mkdir -p _sessions

    if [ -d sessions ]; then
        rsync -a \
            --exclude='_bm2_cache' \
            --exclude='files' \
            sessions/ _sessions/
        local count
        count=$(find _sessions -maxdepth 1 -mindepth 1 -type d | wc -l)
        echo "    Staged ${count} session(s)"
    else
        echo "    No sessions/ directory — deploying with empty sessions"
    fi
}


# ---------------------------------------------------------------------------
# Subcommand: push
#
# Stages local sessions/ and deploys to Cloud Run.
# With --full, delegates to deploy.sh for a complete rebuild.
# Without --full, uses Dockerfile.sync for a fast session-only update.
# ---------------------------------------------------------------------------
do_push() {
    local full=false
    if [[ "${1:-}" == "--full" ]]; then
        full=true
    fi

    if $full; then
        echo "==> Full rebuild via deploy.sh"
        exec bash deploy.sh
    fi

    echo "==> Fast session-only push (Dockerfile.sync)"

    # Stage the sessions/ into _sessions/
    stage_sessions

    # Submit to Cloud Build using the minimal Dockerfile.sync.
    # This pulls the existing deployed image, adds one COPY layer for
    # _sessions/ → sessions/, and pushes.  Much faster than a full rebuild.
    echo "==> Submitting to Cloud Build (Dockerfile.sync)..."
    "$GCLOUD" builds submit \
        --config=/dev/stdin \
        --timeout=5m \
        --project="$PROJECT_ID" \
        <<CLOUDBUILD_EOF
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-f', 'Dockerfile.sync', '-t', '$IMAGE', '.']
images:
  - '$IMAGE'
CLOUDBUILD_EOF

    # Deploy the new image to Cloud Run.
    # Same flags as deploy.sh to keep the service config consistent.
    echo "==> Deploying to Cloud Run..."
    "$GCLOUD" run deploy "$SERVICE" \
        --image "$IMAGE" \
        --region "$REGION" \
        --project "$PROJECT_ID" \
        --allow-unauthenticated \
        --port 8080 \
        --memory 2Gi \
        --cpu 2 \
        --session-affinity

    # Clean up the staging directory
    echo "==> Cleaning up _sessions/..."
    rm -rf _sessions

    echo "==> Done. Service URL:"
    "$GCLOUD" run services describe "$SERVICE" \
        --region "$REGION" \
        --project "$PROJECT_ID" \
        --format='value(status.url)'
}


# ---------------------------------------------------------------------------
# Subcommand: pull
#
# Downloads sessions from the running Cloud Run instance as a .tar.gz,
# then extracts into the local sessions/ directory.
# ---------------------------------------------------------------------------
do_pull() {
    # Resolve the Cloud Run service URL if not explicitly set.
    local cloud_url="${CLOUD_URL:-}"
    if [ -z "$cloud_url" ]; then
        echo "==> Detecting Cloud Run service URL..."
        cloud_url=$("$GCLOUD" run services describe "$SERVICE" \
            --region "$REGION" \
            --project "$PROJECT_ID" \
            --format='value(status.url)')
        echo "    URL: $cloud_url"
    fi

    # The export endpoint is gated by ?user= — pass the allowed user for
    # this service so the middleware lets the request through.
    local export_url="${cloud_url}/api/admin/sessions/export?user=${ALLOWED_USER}"
    local tarball="_sessions_pull.tar.gz"

    echo "==> Downloading sessions from cloud..."
    echo "    GET ${export_url}"

    if ! curl -fL --progress-bar -o "$tarball" "$export_url"; then
        echo "ERROR: Failed to download. Check that the service is running at ${cloud_url}"
        rm -f "$tarball"
        exit 1
    fi

    echo ""
    echo "==> Extracting into sessions/..."
    # Extract — the tarball contains sessions/{dtxsid}/... paths, so we
    # extract into the project root.  Existing local sessions are preserved;
    # conflicting files are overwritten with the cloud version.
    tar xzf "$tarball"
    rm -f "$tarball"

    # Show a quick summary
    echo ""
    echo "--- Summary ---"
    if [ -d sessions ]; then
        local session_count
        session_count=$(find sessions -maxdepth 1 -mindepth 1 -type d \
            ! -name '_*' | wc -l)
        echo "  Sessions: ${session_count}"
        # List each session with its section count
        for d in sessions/DTXSID*/; do
            [ -d "$d" ] || continue
            local name sections
            name=$(basename "$d")
            sections=$(find "$d" -maxdepth 1 -name "*.json" ! -name "meta.json" | wc -l)
            echo "    ${name}: ${sections} section(s)"
        done
    else
        echo "  No sessions found"
    fi
}


# ---------------------------------------------------------------------------
# Main — resolve user, then dispatch to subcommand
# ---------------------------------------------------------------------------

# First argument selects the user/service.  Maps short names to the
# Cloud Run service name and allowed username.
user_arg="${1:-}"
shift || true

case "$user_arg" in
    dan)
        SERVICE="rlm-bmdx-dan"
        ALLOWED_USER="dan_22bc6d42"
        ;;
    scott)
        SERVICE="rlm-bmdx-scott"
        ALLOWED_USER="scott_2d774f16"
        ;;
    *)
        echo "sync.sh — local ↔ cloud session sync for 5dToxReport"
        echo ""
        echo "Usage:"
        echo "  sync.sh <user> <command>"
        echo ""
        echo "Users:"
        echo "  dan       rlm-bmdx-dan   (dan_22bc6d42)"
        echo "  scott     rlm-bmdx-scott (scott_2d774f16)"
        echo ""
        echo "Commands:"
        echo "  push          Fast session-only deploy (~30-60s)"
        echo "  push --full   Full rebuild via deploy.sh (~3 min)"
        echo "  pull          Download sessions from cloud"
        echo ""
        echo "Examples:"
        echo "  sync.sh dan push        # push sessions to dan's instance"
        echo "  sync.sh scott pull      # pull sessions from scott's instance"
        exit 1
        ;;
esac

cmd="${1:-}"
shift || true

case "$cmd" in
    push)
        do_push "$@"
        ;;
    pull)
        do_pull "$@"
        ;;
    *)
        echo "Unknown command: ${cmd:-<none>}"
        echo "Valid commands: push, pull"
        exit 1
        ;;
esac
