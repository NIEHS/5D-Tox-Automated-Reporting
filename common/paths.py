"""
common/paths.py — where session data lives on disk.

`SESSIONS_DIR` is the root directory under which every study session
(`sessions/<DTXSID>/`) is stored. It defaults to `<repo>/sessions/` but can be
overridden with the SESSIONS_DIR environment variable — used when a GCS bucket
is mounted locally via gcsfuse, or when Cloud Run's GCS FUSE volume sits at a
non-default path.

This constant used to be defined in pipeline/session_store.py, which meant
document_model/ (a lower layer) had to import pipeline/ just to read it.
It lives here, in the dependency-free `common` package, so any layer can use
it; session_store re-exports it for backward compatibility.

NOTE for tests: modules bind this name at import time (`from common.paths
import SESSIONS_DIR`), so tests/conftest.py monkeypatches it on EVERY module
that imports it by name (see `_SESSIONS_DIR_MODULES` there).
"""

import os
from pathlib import Path

# Repository root — this file is <repo>/common/paths.py.
REPO_ROOT = Path(__file__).resolve().parent.parent

# Root directory for all session data (see module docstring for the override).
SESSIONS_DIR = Path(os.environ.get("SESSIONS_DIR", REPO_ROOT / "sessions"))
