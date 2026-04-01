"""
test_pipeline_flow.py — Visual step-through E2E test for the full upload →
validate → integrate → process pipeline.

Uses Playwright in headful mode so a human can watch each step in a real
browser.  At each checkpoint the Playwright Inspector opens and waits for
the tester to press "Resume".  A structured log is written to
tests/test.log for a second terminal running `tail -f`.

Golden fixture data: tests/fixtures/golden/DTXSID50469320/files/
This session has 6 .bm2 files + 12 txt/csv data files across Body Weight,
Clinical Chemistry, Hematology, Hormones, Organ Weights, and Gene Expression.

Run:    uv run pytest tests/e2e/test_pipeline_flow.py -s --headed
Tail:   tail -f tests/test.log
No-pause: STEP_NO_PAUSE=1 uv run pytest tests/e2e/test_pipeline_flow.py -s
"""

from pathlib import Path

import pytest

from tests.e2e.conftest import check


# ---------------------------------------------------------------------------
# Paths to golden fixture files — only the types the UI upload accepts
# ---------------------------------------------------------------------------
GOLDEN_FILES_DIR = (
    Path(__file__).resolve().parent.parent / "fixtures" / "golden"
    / "DTXSID50469320" / "files"
)

# .bm2 files (BMDExpress 3 project files — apical + genomics)
BM2_FILES = sorted(GOLDEN_FILES_DIR.glob("*.bm2"))

# Data files: .txt and .csv (dose-response tables, clinical observations)
# Exclude sidecar JSON files — those are metadata, not uploadable.
DATA_FILES = sorted(
    p for p in [*GOLDEN_FILES_DIR.glob("*.txt"), *GOLDEN_FILES_DIR.glob("*.csv")]
    if ".sidecar" not in p.name
)


@pytest.mark.e2e
def test_full_pipeline(page, step):
    """
    Walk through the complete upload → validate → integrate → process flow.

    Each step() call logs to tests/test.log and pauses execution so the
    tester can inspect the browser.  Assertions are logged as PASS/FAIL
    but do not abort the test — the full flow always runs so you can see
    where things break.
    """

    # ── Step 1: App loaded ────────────────────────────────────────────
    # On localhost the login gate is auto-skipped.  Verify the app
    # container is visible and Alpine.js has initialized.
    app_visible = page.locator("#app-container").is_visible()
    check(app_visible, "App container is visible (login gate skipped on localhost)")

    # Verify Alpine.js hydrated — at least one [x-data] element should exist
    x_data_count = page.locator("[x-data]").count()
    check(x_data_count > 0, f"Alpine.js hydrated ({x_data_count} x-data elements)")

    step("App loaded")

    # ── Step 2: Enter chemical identity (DTXSID) ─────────────────────
    # The DTXSID field triggers session restore — if the golden session
    # exists on disk, existing data will be loaded automatically.
    page.locator("#dtxsid").fill("DTXSID50469320")
    # Trigger blur to fire auto-resolve (the server looks up the chemical
    # and restores any existing session data).
    page.locator("#dtxsid").blur()

    # Wait for the resolve/restore to complete
    page.wait_for_timeout(3000)

    step("Chemical identity entered")

    # ── Step 3: Navigate to Data tab and upload files ────────────────
    # The session restore (step 2) may have already loaded files from
    # disk.  Navigate to the Data section and check — if files are
    # already in the pool we skip uploading, otherwise upload from
    # golden fixtures.

    # Wait for the Data link to become enabled in the sidebar
    data_link = page.locator("a.toc-node", has_text="Data")
    try:
        page.wait_for_function(
            "Alpine.store('app').ready.data === true",
            timeout=15_000,
        )
    except Exception:
        check(False, "Data section never became ready after chemical identity")
    data_link.click()
    page.wait_for_timeout(500)

    step("Data tab opened")

    # Check if files were restored from the session
    pool_summary = page.locator("#file-pool-summary")
    summary_text = pool_summary.text_content() or ""
    has_files = "file" in summary_text.lower()

    if not has_files:
        # No files from session restore — upload from golden fixtures
        file_input = page.locator("#unified-file-input")

        # Upload .bm2 files
        bm2_paths = [str(f) for f in BM2_FILES]
        check(len(bm2_paths) > 0, f"Found {len(bm2_paths)} .bm2 files")
        file_input.set_input_files(bm2_paths)
        page.wait_for_timeout(3000)

        # Upload data files (.txt, .csv)
        data_paths = [str(f) for f in DATA_FILES]
        check(len(data_paths) > 0, f"Found {len(data_paths)} data files")
        file_input.set_input_files(data_paths)
        page.wait_for_timeout(5000)

        summary_text = pool_summary.text_content() or ""

    check("file" in summary_text.lower(), f"File pool summary: '{summary_text}'")

    # Log the current pool phase for debugging
    pool_phase = page.evaluate("window.AppStore?.getState()?.pool?.phase || 'unknown'")
    check(True, f"Pool phase after file load: {pool_phase}")

    step("Files in pool")

    # ── Step 4: Validate ──────────────────────────────────────────────
    btn_validate = page.locator("#btn-validate")

    # Wait for the Validate button to become enabled.  The pool state
    # machine enables it in the UPLOADED phase.  If it doesn't enable
    # within 10s, log the pool phase for debugging and try to force
    # the transition.
    try:
        page.wait_for_function(
            "!document.getElementById('btn-validate')?.disabled",
            timeout=10_000,
        )
    except Exception:
        pool_phase = page.evaluate("window.AppStore?.getState()?.pool?.phase || 'unknown'")
        check(False, f"Validate button still disabled — pool phase is '{pool_phase}'")
        # Force the pool to UPLOADED so we can proceed with the test
        page.evaluate("AppStore.dispatch('pool.transition', 'UPLOADED')")
        page.wait_for_timeout(500)

    btn_validate.click()

    # Wait for validation to complete — the coverage matrix appears
    page.wait_for_selector("#coverage-matrix", state="visible", timeout=30_000)

    # Check validation summary
    summary_el = page.locator("#validation-summary")
    val_summary = summary_el.text_content()
    check(
        val_summary is not None and len(val_summary) > 0,
        f"Validation summary: '{val_summary}'",
    )

    step("Validation complete")

    # ── Step 5: Integrate ─────────────────────────────────────────────
    btn_integrate = page.locator("#btn-integrate")
    btn_integrate.wait_for(state="attached", timeout=10_000)

    # Wait for integrate button to become enabled
    try:
        page.wait_for_function(
            "document.getElementById('btn-integrate') && "
            "!document.getElementById('btn-integrate').disabled",
            timeout=10_000,
        )
    except Exception:
        check(False, "Integrate button did not become enabled after validation")

    btn_integrate.click()

    # Integration calls Java subprocess — can take 30-60 seconds.
    # Wait for the integrated preview or metadata review section.
    try:
        page.wait_for_selector(
            "#integrated-preview, #metadata-review-section",
            state="visible",
            timeout=120_000,
        )
        check(True, "Integration completed — preview or metadata section visible")
    except Exception:
        check(False, "Integration timed out after 120 seconds")

    step("Integration complete")

    # ── Step 6: Approve metadata ──────────────────────────────────────
    metadata_section = page.locator("#metadata-review-section")
    metadata_visible = metadata_section.is_visible()

    if metadata_visible:
        btn_approve_meta = page.locator("#btn-approve-metadata")
        btn_approve_meta.wait_for(state="visible", timeout=10_000)

        step("Metadata review — inspecting before approval")

        btn_approve_meta.click()
        check(True, "Metadata approved — processing pipeline started")
    else:
        check(False, "Metadata review section not visible after integration")

    step("Metadata confirmed — processing started")

    # ── Step 7: Wait for processing and verify section cards ──────────
    # Processing runs BMDS modeling — can take 10+ minutes on real data.
    try:
        page.wait_for_function(
            "document.querySelectorAll('.bm2-card').length > 0",
            timeout=600_000,  # 10 minutes for BMDS modeling
        )
        card_count = page.locator(".bm2-card").count()
        check(card_count > 0, f"Section cards visible: {card_count} cards")
    except Exception:
        card_count = page.locator(".bm2-card").count()
        check(False, f"Timed out waiting for section cards (found {card_count})")

    step("Section cards visible — pipeline complete")
