"""
rendering/kept_render.py — a rendered report, kept until what it is rendered
from changes.

A report's Bookshelf page, its Word document and its PDF are rendered on
request (rendering.preview_surface.render_preview), so they always show the
report as it stands; for a report over two studies that takes most of a
minute each time.  ``kept`` keeps the result beside a fingerprint of
everything the render reads, and serves it again while the fingerprint is the
same:

  * every file of the report's session and of the studies it is composed of
    (path, size, modification time), the folders of past versions, kept
    previews and model run records aside — nothing renders from them;
  * the report definition each of those sessions renders from, by the hash of
    the composed definition;
  * the code and the declared content the render runs (the first-party
    packages, templates/, profiles/, vocab/), by path, size and time.

A change to any of them gives another fingerprint and the next request
renders again.  Nothing is kept of a render that fails or is refused.  The
copies live under OUTPUT_DIR/_kept_renders/<id>/ — never in the session, so a
read of a report still writes nothing into the study's own folder.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# Folders of a session no render reads.
_NOT_RENDERED_FROM = {"history", "preview", "narrative_runs", "_originals"}
# Files of a session no render reads: the record of a citation check is about
# the report, not part of it (rendering.citations_validate).
_NOT_RENDERED_FROM_FILES = {"citations_check.json"}
# What the render runs, beside the sessions.
_CODE_DIRS = ("common", "document_model", "genomics", "knowledge_base", "narrative", "pipeline",
              "rendering", "styling_export", "tables", "workflow", "templates", "profiles", "vocab")

_locks: dict[tuple[str, str], threading.Lock] = {}
_locks_guard = threading.Lock()
_code_stamp: str | None = None


def _repo() -> Path:
    return Path(__file__).resolve().parent.parent


def _stat_lines(root: Path, skip: set[str] = frozenset(),
                skip_files: set[str] = frozenset()) -> list[str]:
    lines = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in skip and d != "__pycache__")
        for name in sorted(filenames):
            if name in skip_files:
                continue
            path = Path(dirpath) / name
            try:
                st = path.stat()
            except OSError:
                continue
            lines.append(f"{path.relative_to(root)}\t{st.st_size}\t{st.st_mtime_ns}")
    return lines


def code_stamp() -> str:
    """The code and declared content this process renders with; read once."""
    global _code_stamp
    if _code_stamp is None:
        h = hashlib.sha256()
        for name in _CODE_DIRS:
            folder = _repo() / name
            if folder.is_dir():
                h.update(("\n".join([name, *_stat_lines(folder)]) + "\n").encode())
        _code_stamp = h.hexdigest()[:16]
    return _code_stamp


def _definition_stamp(dtxsid: str) -> str:
    try:
        from document_model.definition_pin import definition_hash
        from document_model.document_definition import definition_name
        from document_model.document_template import _load_raw
        name = definition_name(dtxsid)
        return f"{name}\t{definition_hash(_load_raw(name))}"
    except Exception as e:  # noqa: BLE001 — an unreadable definition is its own state
        return f"unreadable\t{type(e).__name__}: {e}"


def report_sessions(dtxsid: str) -> list[str]:
    """The report's session and the studies it is composed of."""
    from rendering.report_compose import member_sessions
    return [dtxsid, *(member for _, member in member_sessions(dtxsid) or [])]


def _content_lines(dtxsid: str) -> str:
    """The report's own content: every file of its sessions and the definition
    each renders from."""
    from common.dtxsid import is_valid_dtxsid
    from common.paths import SESSIONS_DIR

    out = []
    for sid in report_sessions(dtxsid):
        out.append(f"session\t{sid}")
        if not is_valid_dtxsid(sid):
            continue
        folder = SESSIONS_DIR / sid
        if folder.is_dir():
            out.extend(_stat_lines(folder, _NOT_RENDERED_FROM, _NOT_RENDERED_FROM_FILES))
        out.append(f"definition\t{_definition_stamp(sid)}")
    return "\n".join(out) + "\n"


def content_fingerprint(dtxsid: str) -> str:
    """One hash of the report's content as it stands (its sessions' files and
    their definitions), the code aside: what a check of the report was made
    on, so a later change of the content shows the check is out of date."""
    return hashlib.sha256(_content_lines(dtxsid).encode()).hexdigest()[:32]


def report_fingerprint(dtxsid: str) -> str:
    """One hash of everything a render of the report reads (module docstring)."""
    h = hashlib.sha256()
    h.update(f"code\t{code_stamp()}\n".encode())
    h.update(_content_lines(dtxsid).encode())
    return h.hexdigest()[:32]


def _root() -> Path:
    from common.paths import OUTPUT_DIR
    return OUTPUT_DIR / "_kept_renders"


def _folder(dtxsid: str) -> Path:
    from common.dtxsid import validate_dtxsid
    return _root() / validate_dtxsid(dtxsid)


def _lock(key: tuple[str, str]) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def kept(dtxsid: str, name: str, build, *, variant: str = ""):
    """``(content, was_kept)``: the kept copy ``name`` of the report when its
    fingerprint still holds, else ``build()`` — kept for the next request when
    it returns text or bytes (None, a failed conversion, is returned and not
    kept).  ``variant``: whatever else the content depends on (the links a
    page carries).  Two requests for the same copy render once."""
    folder = _folder(dtxsid)
    target, stamp_file = folder / name, folder / f"{name}.fingerprint"
    with _lock((dtxsid, name)):
        stamp = f"{report_fingerprint(dtxsid)}\t{variant}"
        try:
            if target.is_file() and stamp_file.read_text(encoding="utf-8") == stamp:
                data = target.read_bytes()
                return (data.decode("utf-8") if name.endswith(".html") else data), True
        except OSError:
            pass
        content = build()
        if content is None:
            return None, False
        # Kept under the fingerprint taken BEFORE the render (a render writes
        # nothing into a session): a change made while it ran leaves a copy
        # whose fingerprint no longer holds, and the next request renders again.
        try:
            folder.mkdir(parents=True, exist_ok=True)
            tmp = folder / f".{name}.tmp"
            tmp.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
            os.replace(tmp, target)
            stamp_file.write_text(stamp, encoding="utf-8")
        except OSError as e:
            logger.warning("Could not keep %s of %s: %s", name, dtxsid, e)
        return content, False
