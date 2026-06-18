"""
_io.py — atomic file writes for the round-trip state files (ADR-0005).

The binding, lock, and override stores are all small JSON files that the readers
(`get_binding`, `get_lock`, `load_overrides`) treat a parse failure on as
"absent" — `{}` / `None` / no-overrides.  A plain `path.write_text(...)` is not
atomic: a crash or interrupt mid-write leaves the target truncated, the reader
silently swallows it, and the next write records state derived from a phantom
empty file (e.g. a wrong `baseline_commit`, or every human edit lost).  Routing
every persisted write through `atomic_write_text` makes the target transition
in one `os.replace` step — either the old content or the new, never a partial.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: "Path | str", text: str, *, encoding: str = "utf-8") -> Path:
    """
    Write `text` to `path` atomically: serialize into a temp file in the SAME
    directory (so `os.replace` is a same-filesystem rename, which is atomic),
    fsync it, then replace the target in one step.  On any failure the temp file
    is removed and the target is left untouched.  Returns the path written.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path
