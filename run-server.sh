#!/usr/bin/env bash
# run-server.sh — launch the rlm-bmdx FastAPI server with the LLM credentials
# the Python process needs, resolved from ~/.claude/settings.json at runtime.
#
# Why this exists:
#   Claude Code injects ANTHROPIC_* into its OWN process from settings.json, but
#   a server you start in a plain shell inherits none of it — so the LLM layers
#   fail with "Could not resolve authentication method". This wrapper exports the
#   three values the *Python* SDK reads (the key, the proxy base URL, and the NIH
#   CA bundle) before exec'ing the server.
#
#   Note: the server's SDK reads SSL_CERT_FILE for the CA bundle, NOT the
#   NODE_EXTRA_CA_CERTS that settings.json sets (that var is Node-only). Without
#   it, TLS to the NIEHS proxy fails with a connection error even once auth
#   resolves. We source the same PEM path settings.json records.
#
# The secret is read from settings.json into an env var at runtime and never
# written to disk or echoed, so this script is safe to commit (like deploy.sh).
#
# Usage:
#   ./run-server.sh                 # port 9000, bound to 0.0.0.0 (see below)
#   ./run-server.sh --port 8080     # any background_server.py flags pass through
#   ./run-server.sh --host 127.0.0.1  # override the default bind (loopback only)
#
# Default bind is 0.0.0.0 (all interfaces), NOT background_server.py's own
# 127.0.0.1 default. This sandbox reaches the app through a host port-forward that
# lands on the container's external interface; a loopback-only listener never sees
# that traffic (the browser gets "no data" / 404). Binding to 0.0.0.0 is what makes
# the forward work. Pass an explicit --host to override for a one-off local run.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

PY="$REPO_DIR/.venv/bin/python"
SETTINGS="$HOME/.claude/settings.json"

if [[ ! -x "$PY" ]]; then
  echo "run-server.sh: no venv at $PY — create it first (uv venv)." >&2
  exit 1
fi

# Pull the three values out of settings.json's env block. Missing keys yield an
# empty string (not a crash), so a partially-configured settings.json degrades to
# whatever is already exported in the shell rather than failing here.
read -r SETTINGS_KEY SETTINGS_BASE_URL SETTINGS_CA < <(
  "$PY" - "$SETTINGS" <<'PY'
import json, sys
try:
    env = json.load(open(sys.argv[1])).get("env", {})
except Exception:
    env = {}
print(
    env.get("ANTHROPIC_API_KEY", ""),
    env.get("ANTHROPIC_BASE_URL", ""),
    env.get("NODE_EXTRA_CA_CERTS", ""),
)
PY
)

# Env already set in the shell wins over settings.json (lets you override for a
# one-off run without editing the file).
export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-$SETTINGS_KEY}"
export ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-$SETTINGS_BASE_URL}"
# The Python SDK honors SSL_CERT_FILE (httpx), not NODE_EXTRA_CA_CERTS.
export SSL_CERT_FILE="${SSL_CERT_FILE:-$SETTINGS_CA}"

if [[ -z "$ANTHROPIC_API_KEY" ]]; then
  echo "run-server.sh: no ANTHROPIC_API_KEY (checked \$ANTHROPIC_API_KEY and $SETTINGS) — LLM layers will fail." >&2
fi
if [[ -n "$SSL_CERT_FILE" && ! -f "$SSL_CERT_FILE" ]]; then
  echo "run-server.sh: SSL_CERT_FILE=$SSL_CERT_FILE does not exist — TLS to the proxy may fail." >&2
fi

# Default to binding all interfaces so the host port-forward reaches us (see the
# header note). Only inject --host when the caller didn't pass their own, so an
# explicit --host still wins and the server prints the address it actually binds.
host_given=false
for arg in "$@"; do
  if [[ "$arg" == "--host" ]]; then host_given=true; break; fi
done

if [[ "$host_given" == false ]]; then
  exec "$PY" -m web_routes.background_server --host 0.0.0.0 "$@"
fi
exec "$PY" -m web_routes.background_server "$@"
