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
    "session_store",
    "session_routes",
    "llm_routes",
    "background_server",
    "style_learning",
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
    for mod_name in _SESSIONS_DIR_MODULES:
        try:
            mod = sys.modules.get(mod_name)
            if mod and hasattr(mod, "SESSIONS_DIR"):
                monkeypatch.setattr(mod, "SESSIONS_DIR", sessions_path)
        except Exception:
            # Module not yet imported — that's fine, the test doesn't use it
            pass
    # Always patch session_store directly (it's the canonical source)
    import session_store
    monkeypatch.setattr(session_store, "SESSIONS_DIR", sessions_path)


# ---------------------------------------------------------------------------
# Helper: clear all in-memory shared state
# ---------------------------------------------------------------------------
# The server accumulates state in module-level dicts across requests.
# Tests must start with clean state to avoid cross-test contamination.

def _clear_server_state():
    """Reset all module-level mutable dicts to empty."""
    import pool_orchestrator
    pool_orchestrator._pool_fingerprints.clear()
    pool_orchestrator._integrated_pool.clear()
    pool_orchestrator._data_uploads.clear()

    import server_state
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
    from background_server import app
    return TestClient(app)


@pytest.fixture
def golden_50469320(tmp_path, monkeypatch):
    """
    Copy the DTXSID50469320 golden session into a fresh tmp_path.

    This session has 12 txt/csv data files across 6 platforms, sidecars,
    fingerprints, and a validation report.  It represents a session that
    has been through the upload + validate + confirm metadata flow.

    Returns the session directory path.
    """
    sessions_path = tmp_path / "sessions"
    dest = sessions_path / "DTXSID50469320"
    shutil.copytree(FIXTURES_DIR / "DTXSID50469320", dest)
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

    Patches at the import site (e.g., pool_orchestrator.integrate_pool)
    rather than globally, so each mock documents which external call
    the test depends on.

    Returns a namespace with all mocks for per-test configuration
    (e.g., mock_bmdx_pipe.integrate_pool.return_value = {...}).
    """
    patches = {
        # IntegrateProject.java — merges files into unified BMDProject
        "integrate_pool": patch(
            "pool_orchestrator.integrate_pool",
            return_value={"doseResponseExperiments": [], "_meta": {}},
        ),
        # RunPrefilter.java — Williams/Dunnett statistical tests
        "build_table_data": patch(
            "pool_orchestrator.build_table_data",
            return_value={"Male": [], "Female": []},
        ),
        # ExportGenomics.java — gene expression extraction
        "export_genomics": patch(
            "pool_orchestrator.export_genomics",
            return_value={},
        ),
        # ExportCategories.java — BMD category lookup
        "generate_results_narrative": patch(
            "pool_orchestrator.generate_results_narrative",
            return_value=[],
        ),
        # ExportBm2.java — .bm2 deserialization
        "build_table_data_from_bm2": patch(
            "upload_routes.build_table_data_from_bm2",
            return_value={},
        ),
        # pybmds — CPU-heavy BMD modeling
        "run_bmds_for_endpoints": patch(
            "pool_orchestrator.run_bmds_for_endpoints",
            return_value={},
        ),
        # LMDB cache — mock across all importing modules
        "bm2_cache_session": patch("session_routes.bm2_cache", MagicMock()),
        "bm2_cache_upload": patch("upload_routes.bm2_cache", MagicMock()),
        "bm2_cache_llm": patch("llm_routes.bm2_cache", MagicMock()),
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
