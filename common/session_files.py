"""
common/session_files.py — read one of a session's JSON documents
(sessions/<DTXSID>/<name>: identity.json, animal_report.json, ...).

Absent and unreadable are different facts and are reported differently:

  * absent  → ``None``. The session has not produced that artifact yet; the
    caller decides what that means (most treat it as "not available").
  * present but unreadable (truncated write, hand edit, bad encoding) →
    ``UnreadableSessionFile``. That is a broken session, not missing data, and
    must never be quietly turned into ``{}`` — a report built over it would
    lose its chemical identity or animal counts with nothing to say why.

SESSIONS_DIR is read from ``common.paths`` at call time, so an environment
override or a test's monkeypatch is honored, and the id goes through
``validate_dtxsid`` (the same gate as every other session path). Reading never
creates the session directory.
"""

import json
from pathlib import Path

from common import paths
from common.dtxsid import validate_dtxsid


class UnreadableSessionFile(ValueError):
    """A session JSON document exists but cannot be read or parsed. The FastAPI
    app maps it to a 422 naming the file (web_routes/background_server)."""

    def __init__(self, path: Path, cause: Exception):
        self.path = path
        self.cause = cause
        super().__init__(f"{path.parent.name}/{path.name} is unreadable: {cause}")


def session_file(dtxsid: str, name: str) -> Path:
    """Path of sessions/<dtxsid>/<name>, with the id validated."""
    return paths.SESSIONS_DIR / validate_dtxsid(dtxsid) / name


def read_json_file(path: Path):
    """``path`` parsed as JSON, ``None`` when it does not exist; raises
    UnreadableSessionFile when it exists but cannot be read or parsed."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:  # JSONDecodeError and UnicodeDecodeError are ValueErrors
        raise UnreadableSessionFile(path, exc) from exc


def read_session_json(dtxsid: str, name: str):
    """sessions/<dtxsid>/<name> parsed as JSON; see read_json_file."""
    return read_json_file(session_file(dtxsid, name))
