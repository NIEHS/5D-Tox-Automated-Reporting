"""
conftest.py — Playwright fixtures for visual step-through E2E testing.

Uses pytest-playwright's built-in sync fixtures (browser, page, context)
and extends them with:
  - live_server: starts background_server.py on port 9000, kills it after tests
  - step:        helper that logs to tests/test.log, takes screenshots, and
                 pauses execution so the tester can inspect state in the browser

Run with:   uv run pytest tests/e2e/ -s --headed --slowmo 500
Tail logs:  tail -f tests/test.log
Skip pause: STEP_NO_PAUSE=1 uv run pytest tests/e2e/ -s --headed --slowmo 500
"""

import datetime
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TESTS_DIR = PROJECT_ROOT / "tests"
LOG_FILE = TESTS_DIR / "test.log"
SCREENSHOTS_DIR = TESTS_DIR / "screenshots"


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
def _ts():
    """ISO-8601 timestamp truncated to seconds."""
    return datetime.datetime.now().isoformat(timespec="seconds")


def _log(line: str):
    """Append a tab-separated log line to tests/test.log."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def log_step(label: str, screenshot_path: str | None = None):
    """Write a STEP entry to the structured log."""
    ss = f"SCREENSHOT: {screenshot_path}" if screenshot_path else "NO SCREENSHOT"
    _log(f"{_ts()}\tSTEP\t{label}\t{ss}")


def log_assert(passed: bool, message: str):
    """Write an ASSERT PASS/FAIL entry to the structured log."""
    status = "PASS" if passed else "FAIL"
    _log(f"{_ts()}\tASSERT\t{status}\t{message}")


# ---------------------------------------------------------------------------
# step() — the core visual-debugging helper
# ---------------------------------------------------------------------------
# Monotonic counter so screenshot filenames sort in creation order.
# Modified timestamps aren't fine-grained enough when steps run sub-second.
_step_counter = 0


def _step_impl(page, label: str, screenshot: bool = True):
    global _step_counter
    _step_counter += 1
    """
    Pause execution at a named checkpoint so the tester can inspect the
    browser.  Each call:

      1. Writes a timestamped STEP line to tests/test.log (tail -f friendly).
      2. Optionally captures a screenshot to tests/screenshots/{label}.png.
      3. Calls page.pause() which opens Playwright Inspector — press
         "Resume" (or Step Over) to continue.  Set STEP_NO_PAUSE=1 to
         skip the pause (useful for CI or unattended runs).
    """
    # Sanitize label for use as a filename (replace spaces/slashes)
    safe_label = label.replace(" ", "_").replace("/", "_").replace("\\", "_")

    ss_path = None
    if screenshot:
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        ss_path = str(SCREENSHOTS_DIR / f"{_step_counter:02d}_{safe_label}.png")
        page.screenshot(path=ss_path)

    log_step(label, ss_path)

    # Pause for interactive inspection unless STEP_NO_PAUSE is set
    if not os.environ.get("STEP_NO_PAUSE"):
        page.pause()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def live_server():
    """
    Start background_server.py on port 9000 before tests, kill it after.

    The server is started as a subprocess so it runs the full FastAPI app
    with all routes, static files, and Alpine.js UI — exactly as the user
    sees it.  We wait up to 15 seconds for the server to become ready
    (responding to HTTP requests) before yielding.
    """
    # Clear the log file at the start of each session so it's fresh
    LOG_FILE.unlink(missing_ok=True)

    port = 9000

    # Kill any stale process already listening on the port (e.g., a
    # leftover from a previous manual run or crashed test).  Without
    # this the health-check below passes immediately against the old
    # server and the test runs against stale state.
    stale = subprocess.run(
        ["fuser", f"{port}/tcp"],
        capture_output=True, text=True,
    )
    if stale.stdout.strip():
        for pid_str in stale.stdout.split():
            pid_str = pid_str.strip()
            if pid_str.isdigit():
                _log(f"{_ts()}\tSESSION\tKilling stale process {pid_str} on port {port}")
                try:
                    os.kill(int(pid_str), signal.SIGTERM)
                except ProcessLookupError:
                    pass
        time.sleep(1)

    _log(f"{_ts()}\tSESSION\tStarting live server on port {port}")

    proc = subprocess.Popen(
        [sys.executable, str(PROJECT_ROOT / "background_server.py"),
         "--port", str(port), "--host", "127.0.0.1"],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        # BROWSER=echo prevents webbrowser.open() from launching a real
        # browser window — we use Playwright's own Chromium instance instead.
        env={**os.environ, "BROWSER": "echo"},
    )

    # Wait for the server to be ready (accept HTTP connections)
    import urllib.request
    import urllib.error

    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/")
            break
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.3)
    else:
        proc.kill()
        stdout = proc.stdout.read().decode() if proc.stdout else ""
        raise RuntimeError(
            f"Server did not start within 15s. Output:\n{stdout}"
        )

    _log(f"{_ts()}\tSESSION\tServer ready on port {port}")
    yield f"http://127.0.0.1:{port}"

    # Teardown: kill the server process tree
    _log(f"{_ts()}\tSESSION\tStopping server (pid={proc.pid})")
    try:
        os.kill(proc.pid, signal.SIGTERM)
        proc.wait(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        proc.kill()


# -- pytest-playwright configuration hooks ----------------------------------
# These override pytest-playwright's built-in fixtures to set headful mode,
# slow_mo, viewport, and timeouts.  We don't define our own browser/page
# fixtures — we let pytest-playwright handle that.

@pytest.fixture(scope="session")
def browser_type_launch_args():
    """Always launch headful with slow_mo regardless of CLI flags."""
    return {
        "headless": False,
        "slow_mo": 500,
    }


@pytest.fixture(scope="session")
def browser_context_args(live_server):
    """
    Configure every browser context with the live server base URL,
    a large viewport, and a generous default timeout.
    """
    return {
        "base_url": live_server,
        "viewport": {"width": 1400, "height": 900},
    }


@pytest.fixture
def page(context):
    """
    Fresh page per test with extended timeout and navigated to the app.

    Overrides pytest-playwright's page fixture to:
      - Set 120s default timeout (processing steps are slow)
      - Navigate to the app root
      - Wait for Alpine.js to hydrate
    """
    pg = context.new_page()
    pg.set_default_timeout(120_000)

    # Navigate to the app — base_url is set in browser_context_args
    pg.goto("/")

    # Wait for Alpine.js to initialize — the app container becomes visible
    # and Alpine hydrates x-data attributes on all components
    pg.wait_for_selector("[x-data]", state="attached", timeout=10_000)

    yield pg


@pytest.fixture
def step(page):
    """
    Provide the step() helper bound to the current page.

    Usage in tests:
        step("Upload .bm2 file")
        step("Verify fingerprint table", screenshot=False)
    """
    def _step(label: str, screenshot: bool = True):
        _step_impl(page, label, screenshot=screenshot)

    return _step


@pytest.fixture(autouse=True)
def mock_http():
    """
    Override the root conftest's autouse mock_http fixture.

    The root conftest blocks all requests.Session.send() calls to prevent
    accidental real HTTP in unit/integration tests.  E2E tests run against
    a live server subprocess — Playwright uses its own HTTP transport, not
    Python requests — so the mock is unnecessary and could interfere with
    any test-process HTTP calls (e.g., health checks).  This no-op
    override disables the block for the e2e directory.
    """
    yield


def check(condition: bool, message: str):
    """
    Log an assertion result without stopping the test on failure.

    Writes PASS or FAIL to tests/test.log.  The test continues either way
    so the tester can inspect the full flow, but a failure is recorded for
    post-run analysis.  Returns the condition so callers can branch if needed.
    """
    log_assert(condition, message)
    return condition
