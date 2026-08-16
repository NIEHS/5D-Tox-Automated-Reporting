"""
workflow.store — the injectable state seam for the workflow engine (ADR-0014 Q2).

A `PoolStore` abstracts *where pool state lives* away from *what the step does*.
Step functions in `workflow/steps.py` take a store and become pure logic over an
interface: they never reach `pipeline.pool_globals` module dicts, never touch the
filesystem directly, and never know whether they're driven by the web UI, a TUI,
or a test.

Decision (ADR-0014 Q2, 2026-08-16): use an injectable store rather than
disk-reading-with-accessors. Disk remains the actual source of truth — the
in-memory `pool_globals` dicts are a per-process cache, exactly as
`integrated_io._load_integrated` already treats them. The store just makes that
seam explicit and swappable.

`DiskPoolStore` is the production implementation: a thin adapter over the existing
`pipeline` functions and `pool_globals` accessors, so it is behavior-identical to
the pre-unwrap handlers. Tests may inject a fake implementing `PoolStore` to run
steps with no disk or Java.

Scope: the store abstracts STATE (fingerprints, the integrated cache, session-
scoped file reads/writes, section persistence). It deliberately does NOT wrap the
pure compute functions `validate_pool` / `integrate_pool` / `build_animal_report`
— those are stateless transforms the steps call directly (and tests already mock
via conftest's `mock_bmdx_pipe`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class PoolStore(Protocol):
    """The state surface a workflow step needs. Implementations back this with
    disk + process cache (production) or in-memory fakes (tests)."""

    # --- session location ------------------------------------------------
    def session_dir(self, dtxsid: str) -> Path:
        """Return (creating if needed) the session directory for a DTXSID."""
        ...

    # --- fingerprints ----------------------------------------------------
    def ensure_fingerprints(self, dtxsid: str, force: bool = False) -> dict:
        """Populate (or force a fresh re-scan of) the session's fingerprints
        and return {file_id: FileFingerprint}."""

    def get_fingerprints(self, dtxsid: str) -> dict:
        """Return the cached fingerprints for a session ({} if none)."""

    def set_fingerprints(self, dtxsid: str, fps: dict) -> None:
        """Replace the cached fingerprints for a session."""

    # --- integrated project ---------------------------------------------
    def get_integrated(self, dtxsid: str) -> dict | None:
        """Return the integrated BMDProject (schema-validated, cache-or-disk),
        or None if the session has never been integrated."""

    def set_integrated(self, dtxsid: str, data: dict) -> None:
        """Cache an integrated BMDProject for the session in the process cache."""

    # --- session-scoped JSON documents ----------------------------------
    def read_json(self, dtxsid: str, name: str) -> dict | list | None:
        """Read sessions/{dtxsid}/{name} as JSON, or None if absent/unreadable."""

    def write_json(self, dtxsid: str, name: str, data) -> None:
        """Write `data` as pretty JSON to sessions/{dtxsid}/{name}."""

    # --- sections --------------------------------------------------------
    def save_section(self, dtxsid: str, key: str, data: dict, archive: bool = True) -> None:
        """Persist a report section (versioned, archived-before-overwrite).
        `data` is mutated in place with its `version` (see session_store)."""


class DiskPoolStore:
    """Production `PoolStore`: disk is canonical, `pool_globals` is the cache.

    A thin adapter — every method delegates to the same `pipeline` function the
    pre-unwrap handler called, so wrapping a handler in this store is
    behavior-preserving by construction.
    """

    def session_dir(self, dtxsid: str) -> Path:
        from pipeline.pool_globals import _session_dir
        return _session_dir(dtxsid)

    def ensure_fingerprints(self, dtxsid: str, force: bool = False) -> dict:
        from pipeline.pool_fingerprints import ensure_fingerprints
        return ensure_fingerprints(dtxsid, force=force)

    def get_fingerprints(self, dtxsid: str) -> dict:
        from pipeline.pool_globals import get_pool_fingerprints
        return get_pool_fingerprints().get(dtxsid, {})

    def set_fingerprints(self, dtxsid: str, fps: dict) -> None:
        from pipeline.pool_globals import get_pool_fingerprints
        get_pool_fingerprints()[dtxsid] = fps

    def get_integrated(self, dtxsid: str) -> dict | None:
        from pipeline.integrated_io import _load_integrated
        return _load_integrated(dtxsid)

    def set_integrated(self, dtxsid: str, data: dict) -> None:
        from pipeline.pool_globals import get_integrated_pool
        get_integrated_pool()[dtxsid] = data

    def read_json(self, dtxsid: str, name: str):
        path = self.session_dir(dtxsid) / name
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValueError):
            return None

    def write_json(self, dtxsid: str, name: str, data) -> None:
        path = self.session_dir(dtxsid) / name
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def save_section(self, dtxsid: str, key: str, data: dict, archive: bool = True) -> None:
        from pipeline.session_store import save_section
        save_section(dtxsid, key, data, archive=archive)
