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
# Only export the base URL / CA bundle when there is a VALUE. An exported empty
# string is not "unset" to the Anthropic SDK: ANTHROPIC_BASE_URL="" makes every
# request target a blank URL and fail with a bare "Connection error", and an
# empty SSL_CERT_FILE can disable default certificate loading. (Bit us on
# 2026-09-21 on a machine with no proxy configured.)
_base_url="${ANTHROPIC_BASE_URL:-$SETTINGS_BASE_URL}"
if [[ -n "$_base_url" ]]; then export ANTHROPIC_BASE_URL="$_base_url"; else unset ANTHROPIC_BASE_URL; fi
# CA bundle resolution, in priority order:
#   1. $SSL_CERT_FILE already in the shell (explicit override)
#   2. settings.json's env.NODE_EXTRA_CA_CERTS ($SETTINGS_CA)
#   3. $NODE_EXTRA_CA_CERTS from the ambient shell — THIS sandbox sets the NIEHS
#      bundle here (Claude Code / Node reads it), NOT in settings.json's env block,
#      so relying on (2) alone left SSL_CERT_FILE empty and every Python LLM call
#      failed cert verification against the LiteLLM proxy (self-signed chain).
#   4. the known sandbox path as a last resort.
# The Python SDK (httpx) honors SSL_CERT_FILE, NOT NODE_EXTRA_CA_CERTS — so we must
# copy whichever of these resolves INTO SSL_CERT_FILE. Only export a non-empty,
# existing path (an empty SSL_CERT_FILE can disable default cert loading entirely).
_ca="${SSL_CERT_FILE:-${SETTINGS_CA:-${NODE_EXTRA_CA_CERTS:-/usr/local/share/ca-certificates/extra/nih-ca-bundle.crt}}}"
if [[ -n "$_ca" && -f "$_ca" ]]; then export SSL_CERT_FILE="$_ca"; else unset SSL_CERT_FILE; fi

if [[ -z "$ANTHROPIC_API_KEY" ]]; then
  echo "run-server.sh: no ANTHROPIC_API_KEY (checked \$ANTHROPIC_API_KEY and $SETTINGS) — LLM layers will fail." >&2
fi
if [[ -n "${SSL_CERT_FILE:-}" && ! -f "${SSL_CERT_FILE:-}" ]]; then
  echo "run-server.sh: SSL_CERT_FILE=${SSL_CERT_FILE:-} does not exist — TLS to the proxy may fail." >&2
fi

# --- Java pipeline env (integration + BMDS) --------------------------------
# The Java layer (IntegrateProject, RunPrefilter, …) is compiled for JDK 21;
# running it under the sandbox's default JDK 17 fails with
# UnsupportedClassVersionError (class file 65.0 vs 61.0). And bmdx_pipe.java_bridge
# resolves the classpath under $BMDX_PROJECT_ROOT (its default is a nonexistent
# ~/Dev path). pool_integrator invokes a BARE `java`, so JDK 21 must lead $PATH,
# not just $JAVA_HOME. Shell-set values win (one-off override); we supply the
# sandbox defaults and warn if a path is absent.
_jdk21="${BMDX_JDK_HOME:-/opt/liberica-jdk-21}"
if [[ -x "$_jdk21/bin/java" ]]; then
  export JAVA_HOME="$_jdk21"
  export PATH="$_jdk21/bin:$PATH"
else
  echo "run-server.sh: JDK 21 not found at $_jdk21/bin/java — Java integration will fail (UnsupportedClassVersionError)." >&2
fi
# Default the BMDExpress root only to a path that EXISTS: the sandbox checkout
# first, then bmdx-pipe's own default (~/Dev/Projects/BMDExpress-3, where a
# by-hand target/ layout lives on the author's laptop — see the README in that
# target/). Exporting a nonexistent path would override java_bridge's default
# and break integration on machines that are not the sandbox.
if [[ -z "${BMDX_PROJECT_ROOT:-}" ]]; then
  for _cand in /workspace/BMDExpress-3 "$HOME/Dev/Projects/BMDExpress-3"; do
    if [[ -d "$_cand/target" ]]; then export BMDX_PROJECT_ROOT="$_cand"; break; fi
  done
fi
# java_bridge.build_classpath globs target/*.jar, so ANY real jar there works —
# it does NOT require the `bmdx-core.jar` name specifically (which is a symlink to
# a host /ddn path that's dangling in the sandbox; the sibling
# bmdexpress3-*.jar is the real artifact the glob picks up). So check for a
# NON-DANGLING jar in target/, not that one symlink, to avoid a false alarm.
if ! compgen -G "$BMDX_PROJECT_ROOT/target/*.jar" >/dev/null 2>&1 || \
   ! find "$BMDX_PROJECT_ROOT/target" -maxdepth 1 -name '*.jar' -type f 2>/dev/null | grep -q .; then
  echo "run-server.sh: no readable *.jar under $BMDX_PROJECT_ROOT/target — Java classpath will be broken." >&2
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
