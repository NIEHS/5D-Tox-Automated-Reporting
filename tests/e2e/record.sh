#!/usr/bin/env bash
# record.sh — Launch Playwright codegen against the live server.
#
# Opens a browser + inspector side-by-side.  Every click, fill, and
# navigation you perform is translated into Python test code in the
# inspector panel.  When you're done, copy the generated code and
# paste it into a test file.
#
# Usage:
#   ./tests/e2e/record.sh              # start server + codegen
#   ./tests/e2e/record.sh --no-server  # codegen only (server already running)
#
# The generated code uses Playwright's sync API and standard selectors,
# so it drops straight into a test function that uses our page fixture.

set -euo pipefail
cd "$(dirname "$0")/../.."

PORT=9000
START_SERVER=true

if [[ "${1:-}" == "--no-server" ]]; then
    START_SERVER=false
fi

# Start the server if needed
SERVER_PID=""
if $START_SERVER; then
    # Kill any stale process on the port
    fuser -k "$PORT/tcp" 2>/dev/null || true
    sleep 1

    echo "Starting server on port $PORT..."
    BROWSER=echo uv run python background_server.py --port "$PORT" --host 127.0.0.1 &
    SERVER_PID=$!

    # Wait for server to be ready
    for i in $(seq 1 30); do
        if curl -sf "http://127.0.0.1:$PORT/" >/dev/null 2>&1; then
            echo "Server ready."
            break
        fi
        sleep 0.5
    done
fi

echo ""
echo "Recording — interact with the browser."
echo "The inspector panel on the right shows generated Python code."
echo "When done, copy the code and close the browser."
echo ""

# Launch codegen — generates Python (pytest-playwright compatible) by default
uv run playwright codegen \
    --target python \
    --viewport-size "1400,900" \
    "http://127.0.0.1:$PORT/"

# Cleanup
if [[ -n "$SERVER_PID" ]]; then
    echo "Stopping server (pid=$SERVER_PID)..."
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
fi

echo "Done. Paste the recorded code into a test function in tests/e2e/."
