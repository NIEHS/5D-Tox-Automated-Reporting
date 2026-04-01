# E2E Visual Step-Through Tests

Playwright-based end-to-end tests that run in a real browser. You watch the
test execute in Chromium while tailing a structured log in a second terminal.

## Prerequisites

```bash
uv add --dev playwright pytest-playwright pytest-asyncio
uv run playwright install chromium
```

## Running tests

**Terminal 1 — run the test:**

```bash
uv run pytest tests/e2e/test_pipeline_flow.py -s --headed
```

- `-s` disables stdout capture (required for Playwright Inspector to work)
- `--headed` is redundant here (the fixture forces headful mode) but makes
  intent clear

**Terminal 2 — tail the log:**

```bash
tail -f tests/test.log
```

Log format (tab-separated, one line per event):

```
2026-03-31T14:22:01    STEP       Upload .bm2 file       SCREENSHOT: tests/screenshots/upload_bm2.png
2026-03-31T14:22:05    STEP       Verify fingerprints     NO SCREENSHOT
2026-03-31T14:22:05    ASSERT     PASS                    File count badge shows "3 files"
2026-03-31T14:22:06    ASSERT     FAIL                    Expected platform "Body Weight", got "Unknown"
```

## Stepping through

At each `step()` call the Playwright Inspector window opens and execution
freezes. You can:

- **Resume** — click the green play button to advance to the next step
- **Step Over** — execute one Playwright action at a time
- **Inspect** — click elements in the browser to see their selectors

The browser stays interactive between steps — you can scroll, open DevTools,
inspect Alpine.js state (`$store.app` in the console), etc.

## Running without pausing

Set `STEP_NO_PAUSE=1` to skip all `page.pause()` calls. The test runs
straight through, still logging and taking screenshots:

```bash
STEP_NO_PAUSE=1 uv run pytest tests/e2e/test_pipeline_flow.py -s --headed
```

This is useful for unattended runs or CI where you just want the log and
screenshots.

## Screenshots

Captured automatically at each step to `tests/screenshots/`. Filenames
match the step label (spaces replaced with underscores):

```
tests/screenshots/
  App_loaded.png
  BM2_files_uploaded.png
  Data_files_uploaded.png
  Validation_complete.png
  Integration_complete.png
  ...
```

## Timeouts

- Default action timeout: **120 seconds** (processing steps are slow)
- BMDS modeling step: **10 minutes** (pybmds runs CPU-heavy dose-response
  modeling on every endpoint)
- Server startup: **15 seconds**

## Architecture

```
tests/e2e/
  conftest.py              Playwright fixtures (server, browser, page, step)
  test_pipeline_flow.py    Full pipeline walkthrough test
tests/
  test.log                 Structured log (tail -f target)
  screenshots/             Step screenshots
```

The `live_server` fixture starts `background_server.py` as a subprocess on
port 9000 — the full FastAPI app with all routes and the Alpine.js UI. This
is a true end-to-end test against the real server, not a TestClient mock.
