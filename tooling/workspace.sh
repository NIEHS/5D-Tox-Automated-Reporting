#!/usr/bin/env bash
# tooling/workspace.sh — a separate workspace for someone trying the tool on
# their own data: its own sessions (so its own Bookshelf), its own outputs, its
# own copy of the walkthrough notebook, its own app server and JupyterLab.
#
#   workspaces/<name>/sessions/             SESSIONS_DIR: the workspace's sessions
#   workspaces/<name>/output/               OUTPUT_DIR: its deliverables
#   workspaces/<name>/notebooks/            its copy of notebooks/workflow_walkthrough.ipynb
#   workspaces/<name>/notebooks/uploads/    BMDX_UPLOADS: the data files they upload
#
# The app (port 9300 by default) serves only the workspace's sessions: its
# /Bookshelf lists the workspace's reports, and its Upload step takes files
# from the person's machine.  JupyterLab (port 9400) opens on the notebook
# copy; its upload button puts files from their machine in uploads/, which the
# notebook builds a report from.  Both run with run-server.sh's environment
# (LLM gateway, CA bundle, JDK 21).  The repository's own sessions/ and output/
# are not touched.  The ports must be ones the sandbox forwards (SANDBOX_PORT).
#
# Usage:
#   tooling/workspace.sh NAME [--server-port 9300] [--jupyter-port 9400]
#   tooling/workspace.sh NAME stop
#   tooling/workspace.sh NAME env [--server-port P]   # the exports: eval "$(… env)"
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="${1:-}"
[[ "$NAME" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "usage: $0 NAME [--server-port P] [--jupyter-port P] | NAME stop | NAME env" >&2; exit 2; }
shift
WS="$REPO/workspaces/$NAME"

if [[ "${1:-}" == "stop" ]]; then
  for svc in server jupyter; do
    if [[ -f "$WS/$svc.pid" ]] && kill "$(cat "$WS/$svc.pid")" 2>/dev/null; then
      echo "stopped $svc ($(cat "$WS/$svc.pid"))"
    fi
    rm -f "$WS/$svc.pid"
  done
  exit 0
fi

SERVER_PORT=9300
JUPYTER_PORT=9400
MODE=start
while [[ $# -gt 0 ]]; do
  case "$1" in
    --server-port) SERVER_PORT="$2"; shift 2 ;;
    --jupyter-port) JUPYTER_PORT="$2"; shift 2 ;;
    env) MODE=env; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

# BMDX_LOCAL_URL: the address the Supplemental Data appendix gives for files
# not yet deposited elsewhere (pipeline.deposit) — this workspace's app.
exports() {
  printf 'export SESSIONS_DIR=%q OUTPUT_DIR=%q BMDX_REPO=%q BMDX_UPLOADS=%q BMDX_LOCAL_URL=%q\n' \
    "$WS/sessions" "$WS/output" "$REPO" "$WS/notebooks/uploads" "http://127.0.0.1:$SERVER_PORT"
}
if [[ "$MODE" == env ]]; then exports; exit 0; fi

for port in "$SERVER_PORT" "$JUPYTER_PORT"; do
  if [[ -n "${SANDBOX_PORT:-}" && " $SANDBOX_PORT " != *" $port "* ]]; then
    echo "port $port is not forwarded to the host (SANDBOX_PORT: $SANDBOX_PORT)" >&2; exit 1
  fi
  if curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$port/"; then
    echo "port $port is already in use" >&2; exit 1
  fi
done

mkdir -p "$WS/sessions" "$WS/output" "$WS/notebooks/uploads"
if [[ ! -f "$WS/notebooks/workflow_walkthrough.ipynb" ]]; then
  cp "$REPO/notebooks/workflow_walkthrough.ipynb" "$WS/notebooks/"
fi
eval "$(exports)"

(setsid nohup "$REPO/run-server.sh" --port "$SERVER_PORT" > "$WS/server.log" 2>&1 & echo $! > "$WS/server.pid")

TOKEN="$("$REPO/.venv/bin/python" -c 'import secrets; print(secrets.token_hex(16))')"
(setsid nohup "$REPO/run-server.sh" --run "$REPO/.venv/bin/python" -m jupyterlab --no-browser \
   --ip 0.0.0.0 --port "$JUPYTER_PORT" --ServerApp.root_dir="$WS/notebooks" \
   --ServerApp.token="$TOKEN" --ServerApp.trust_xheaders=True \
   > "$WS/jupyter.log" 2>&1 & echo $! > "$WS/jupyter.pid")
echo "http://localhost:$JUPYTER_PORT/lab/tree/workflow_walkthrough.ipynb?token=$TOKEN" > "$WS/jupyter-url.txt"

for port in "$SERVER_PORT" "$JUPYTER_PORT"; do
  for _ in $(seq 1 60); do
    curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$port/" && break
    sleep 2
  done
done

cat <<MSG
workspace $NAME: $WS
  app        http://localhost:$SERVER_PORT/            (Bookshelf: /Bookshelf)
  notebook   $(cat "$WS/jupyter-url.txt")
  uploads    $WS/notebooks/uploads/   (JupyterLab's upload button, in that folder)
  logs       $WS/server.log, $WS/jupyter.log
  stop       tooling/workspace.sh $NAME stop
MSG
