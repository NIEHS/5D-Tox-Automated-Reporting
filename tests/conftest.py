"""
conftest.py — Root test configuration for rlm-bmdx.

Provides fixtures for:
  - State isolation (patched SESSIONS_DIR, cleared in-memory dicts)
  - FastAPI TestClient with fresh state per test
  - Golden session data (copied into tmp_path)
  - Mock bmdx_pipe (blocks all Java subprocess calls)
  - Mock HTTP (prevents real network requests)
  - Mock Anthropic (prevents real LLM calls)

Every test gets isolated state — no cross-test contamination from
module-level dicts or disk state.
"""

import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so imports resolve.
# The project doesn't use a proper package structure — all .py files
# are at the repo root, so we add that directory to sys.path.
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Path to golden fixture data (real session data snapshotted for tests)
# ---------------------------------------------------------------------------
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "golden"
# The supplied PFHxSAm package (2026 re-analysis) — a regression fixture, not a reference.
GIVEN_PFHXSAM_DIR = Path(__file__).parent / "fixtures" / "regression" / "given-pfhxsam-2026"
# Published CEBS packages (subsets, original file names) + their published tables.
REFERENCE_DIR = Path(__file__).parent / "fixtures" / "reference"


# ---------------------------------------------------------------------------
# Helper: patch SESSIONS_DIR everywhere it's imported
# ---------------------------------------------------------------------------
# session_store.SESSIONS_DIR is a module-level Path computed at import time.
# It's imported by name in several modules, so we must patch the attribute
# in session_store AND in every module that did `from session_store import
# SESSIONS_DIR`.  Patching only session_store leaves the other modules
# pointing at the original Path object.

# All modules that import SESSIONS_DIR by name (found via grep).
_SESSIONS_DIR_MODULES = [
    # The leaf that DEFINES it (common/paths.py) — patched so any late
    # `from common.paths import SESSIONS_DIR` inside a function sees the
    # test directory too.
    "common.paths",
    "pipeline.session_store",
    # The LLM narrative generators bind SESSIONS_DIR at import for their
    # per-session cache files (moved out of web_routes.llm_routes 2026-09-18).
    "narrative.apical_bmd_llm",
    "narrative.genomics_llm",
    "web_routes.session_routes",
    "web_routes.llm_routes",
    "web_routes.background_server",
    "document_model.document_config",
    "document_model.view_config",
]

# pool_orchestrator imports session_dir (the function), which reads
# session_store.SESSIONS_DIR internally — patching session_store is enough.
# upload_routes imports session_dir too — same story.


def _patch_sessions_dir(monkeypatch, sessions_path: Path):
    """
    Redirect SESSIONS_DIR to sessions_path in every module that imports it.

    Also creates the directory so tests don't need to mkdir themselves.
    """
    sessions_path.mkdir(parents=True, exist_ok=True)
    # The leaf is imported first, so it is patched even when nothing has
    # imported it yet (a module that reads common.paths.SESSIONS_DIR at call
    # time — web_routes.bookshelf_routes — would otherwise see the real dir).
    import common.paths  # noqa: F401
    for mod_name in _SESSIONS_DIR_MODULES:
        try:
            mod = sys.modules.get(mod_name)
            if mod and hasattr(mod, "SESSIONS_DIR"):
                monkeypatch.setattr(mod, "SESSIONS_DIR", sessions_path)
        except Exception:
            # Module not yet imported — that's fine, the test doesn't use it
            pass
    # Always patch session_store directly (it's the canonical source)
    import pipeline.session_store as session_store
    monkeypatch.setattr(session_store, "SESSIONS_DIR", sessions_path)


# ---------------------------------------------------------------------------
# Helper: clear all in-memory shared state
# ---------------------------------------------------------------------------
# The server accumulates state in module-level dicts across requests.
# Tests must start with clean state to avoid cross-test contamination.

def _clear_server_state():
    """Reset all module-level mutable dicts to empty."""
    import pipeline.pool_orchestrator as pool_orchestrator
    pool_orchestrator._pool_fingerprints.clear()
    pool_orchestrator._integrated_pool.clear()
    pool_orchestrator._data_uploads.clear()

    import web_routes.server_state as server_state
    server_state._bm2_uploads.clear()
    server_state._csv_uploads.clear()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sessions_dir(tmp_path, monkeypatch):
    """
    Provide a fresh, empty sessions directory for the test.

    Patches SESSIONS_DIR in all modules and clears in-memory state.
    Returns the path to the sessions directory.
    """
    sessions_path = tmp_path / "sessions"
    _patch_sessions_dir(monkeypatch, sessions_path)
    _clear_server_state()
    return sessions_path


@pytest.fixture
def client(sessions_dir):
    """
    FastAPI TestClient with isolated state.

    Uses the sessions_dir fixture to ensure SESSIONS_DIR is patched and
    all in-memory state is cleared before each test.
    """
    from fastapi.testclient import TestClient
    from web_routes.background_server import app
    return TestClient(app)


@pytest.fixture
def reference_session(tmp_path, monkeypatch):
    """
    Factory: build a session from a published CEBS package in
    tests/fixtures/reference/<report>/ through the real ingest path.

    Each Individual Animal workbook goes through tooling.cebs_to_pool (truth
    CSV per sex + its .units.json companion) into sessions/<dtxsid>/files/,
    then pool fingerprinting converts the CSVs to pivots + sidecars exactly as
    an upload does.  `with_workbooks=True` also places the workbooks in the
    pool (the source-of-truth xlsx a customer may supply alongside the CSVs).

        session = reference_session("NIEHS-10", "DTXSID50469320")
        sidecars = find_sidecar_paths(str(session), "Tissue Concentration")

    `study` limits it to one study's workbooks by their study-number prefix
    (a report with a rat and a mouse study: "108020006").

    Returns the session directory.
    """
    from pipeline.pool_fingerprints import ensure_fingerprints
    from tooling.cebs_to_pool import convert_workbook, package_species

    sessions_path = tmp_path / "sessions"
    _patch_sessions_dir(monkeypatch, sessions_path)
    _clear_server_state()

    def build(report: str, dtxsid: str, *, with_workbooks: bool = False,
              units: bool = True, study: str = "") -> Path:
        files = sessions_path / dtxsid / "files"
        files.mkdir(parents=True, exist_ok=True)
        workbooks = sorted((REFERENCE_DIR / report).glob(f"{study}*Individual_Animal_*.xlsx"))
        for xlsx in workbooks:
            # The species of a multi-species lab workbook: its study's siblings say.
            prefix = xlsx.name.split("_", 1)[0]
            species = package_species([w.name for w in workbooks if w.name.startswith(prefix)])
            summary = convert_workbook(str(xlsx), str(files), species)
            assert summary["status"] in ("ok", "skipped"), summary
            if with_workbooks:
                shutil.copy2(xlsx, files / xlsx.name)
        if not units:
            for companion in files.glob("*.units.json"):
                companion.unlink()
        ensure_fingerprints(dtxsid, force=True)
        return sessions_path / dtxsid

    return build


@pytest.fixture
def given_pfhxsam(tmp_path, monkeypatch):
    """
    Copy the given-PFHxSAm regression session (as DTXSID50469320) into a
    fresh tmp_path.

    This session has 12 txt/csv data files across 6 platforms, sidecars,
    fingerprints, and a validation report.  It represents a session that
    has been through the upload + validate + confirm metadata flow.  It is a
    REGRESSION fixture for the workflow plumbing — its inputs are a 2026
    re-analysis, not the analysis behind any published report (see its
    README.md); conformance to a published report uses tests/fixtures/reference/.

    Returns the session directory path.
    """
    sessions_path = tmp_path / "sessions"
    dest = sessions_path / "DTXSID50469320"
    shutil.copytree(GIVEN_PFHXSAM_DIR, dest)
    _patch_sessions_dir(monkeypatch, sessions_path)
    _clear_server_state()
    return dest


@pytest.fixture
def golden_70191136(tmp_path, monkeypatch):
    """
    Copy the DTXSID70191136 golden session into a fresh tmp_path.

    This session has 2 .bm2 files with an approved background section
    and two approved apical sections (clinical pathology, organ weights).
    It represents a session that has been through the full approval flow.

    Returns the session directory path.
    """
    sessions_path = tmp_path / "sessions"
    dest = sessions_path / "DTXSID70191136"
    shutil.copytree(FIXTURES_DIR / "DTXSID70191136", dest)
    _patch_sessions_dir(monkeypatch, sessions_path)
    _clear_server_state()
    return dest


@pytest.fixture
def mock_bmdx_pipe():
    """
    Block all bmdx_pipe functions that invoke Java subprocesses.

    Patches at the import site (the module where each function is looked
    up after the pool_orchestrator monolith split) rather than globally,
    so each mock documents which external call the test depends on.

    Returns a namespace with all mocks for per-test configuration
    (e.g., mock_bmdx_pipe.integrate_pool.return_value = {...}).
    """
    patches = {
        # IntegrateProject.java — merges files into unified BMDProject.
        # Patched at workflow.steps (ADR-0014 step 2 moved the call site there
        # from web_routes.pool_routes when the handler was unwrapped).
        "integrate_pool": patch(
            "workflow.steps.integrate_pool",
            return_value={"doseResponseExperiments": [], "_meta": {}},
        ),
        # RunPrefilter.java — Williams/Dunnett statistical tests
        "build_table_data": patch(
            "pipeline.process_integrated.build_table_data",
            return_value={"Male": [], "Female": []},
        ),
        # ExportGenomics.java — gene expression extraction
        "export_genomics": patch(
            "pipeline.processing_helpers.export_genomics",
            return_value={},
        ),
        # Per-platform narrative entry (app-side templated builder)
        "generate_results_narrative": patch(
            "pipeline.processing_helpers.generate_platform_narrative",
            return_value=[],
        ),
        # ExportBm2.java — .bm2 deserialization
        "build_table_data_from_bm2": patch(
            "web_routes.upload_routes.build_table_data_from_bm2",
            return_value={},
        ),
        # pybmds — CPU-heavy BMD modeling
        "run_bmds_for_endpoints": patch(
            "pipeline.process_integrated.run_bmds_for_endpoints",
            return_value={},
        ),
        # LMDB cache — mock across all importing modules.  get_json must
        # return a JSON-serializable value (the real cache returns a plain
        # dict on hit, None on miss); a bare MagicMock leaks into the
        # preview route's orjson.dumps and fails to serialize.
        "bm2_cache_session": patch(
            "web_routes.session_routes.bm2_cache", MagicMock(get_json=lambda *a, **k: {}),
        ),
        "bm2_cache_upload": patch(
            "web_routes.upload_routes.bm2_cache", MagicMock(get_json=lambda *a, **k: {}),
        ),
        "bm2_cache_llm": patch(
            "web_routes.llm_routes.bm2_cache", MagicMock(get_json=lambda *a, **k: {}),
        ),
    }

    started = {}
    for name, p in patches.items():
        started[name] = p.start()

    # Expose as a simple namespace object so tests can do:
    #   mock_bmdx_pipe.integrate_pool.return_value = my_fixture
    class MockNamespace:
        pass

    ns = MockNamespace()
    for name, mock_obj in started.items():
        setattr(ns, name, mock_obj)

    yield ns

    for p in patches.values():
        p.stop()


_REAL_SESSIONS = Path(__file__).resolve().parent.parent / "sessions"


def _real_session_dirs() -> set[str]:
    try:
        return {p.name for p in _REAL_SESSIONS.iterdir() if p.is_dir()}
    except OSError:
        return set()


@pytest.fixture(autouse=True)
def no_real_session_dirs_created():
    """
    Fail a test that creates a directory in the REAL sessions/ (instead of its
    tmp sessions_dir).  Leaked test sessions (DTXSID_VC, DTXSID_TEST_NO_SESSION,
    …) listed on the Bookshelf as if they were reports.

    It never deletes: a report build running alongside the tests creates real
    session dirs too, and removing those destroyed the builds.  A leak is
    removed by hand once the failure names it.
    """
    before = _real_session_dirs()
    yield
    leaked = _real_session_dirs() - before
    if leaked:
        pytest.fail(f"session dir(s) appeared in the real sessions/ during this test: "
                    f"{sorted(leaked)} — a test should use the sessions_dir fixture "
                    "(or a report build was running alongside the tests)")


@pytest.fixture(autouse=True)
def mock_http(monkeypatch):
    """
    Prevent any real HTTP requests from tests.

    Autouse — applies to every test automatically.  Tests that need
    HTTP responses should patch specific callsites with unittest.mock.
    """
    import requests

    def _blocked(*args, **kwargs):
        raise RuntimeError(
            f"Test attempted real HTTP request: {args!r}. "
            "Mock the specific HTTP call instead."
        )

    monkeypatch.setattr(requests.Session, "send", _blocked)


@pytest.fixture
def mock_anthropic(monkeypatch):
    """
    Block all Anthropic/Claude API calls.

    Returns canned JSON so tests don't need a real API key.
    """
    monkeypatch.setattr(
        "llm_helpers.AnthropicEndpoint.generate",
        lambda *a, **kw: '{"result": "mocked"}',
    )


# ---------------------------------------------------------------------------
# Real-session gate
# ---------------------------------------------------------------------------
# A handful of renderer/export tests read the PROCESSED DTXSID50469320 session
# (sections, narratives, caches) from the live sessions/ directory — which is a
# gitignored GCS mount that exists only on the author's machines. The raw
# input pool is checked in under tests/fixtures/golden/, but the processed
# outputs are not (they need Java + ~8 min of BMDS), so on a fresh clone or in
# CI those tests can only fail for lack of data. This fixture turns that into an
# explicit skip: request it from any test that asserts on real-session content.
REAL_SESSION_DTXSID = "DTXSID50469320"


def processed_session_present(dtxsid: str = REAL_SESSION_DTXSID) -> bool:
    """True when the processed session (integrated.json) exists under the
    CURRENT session_store.SESSIONS_DIR (env override / monkeypatch honored)."""
    from pipeline import session_store  # local: conftest keeps app imports lazy
    return (session_store.SESSIONS_DIR / dtxsid / "integrated.json").exists()


@pytest.fixture
def real_session_50469320():
    """Skip the requesting test unless the processed golden session is present."""
    from pipeline import session_store  # local: conftest keeps app imports lazy
    if not processed_session_present():
        pytest.skip(
            f"processed session {REAL_SESSION_DTXSID} not present under "
            f"{session_store.SESSIONS_DIR} (GCS mount / author machine only)"
        )
