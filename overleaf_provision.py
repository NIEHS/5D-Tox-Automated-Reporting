"""
overleaf_provision.py — Overleaf-specific addressing helpers (ADR-0005 Am.1a).

This is the APP-side Overleaf adapter; it deliberately does NOT live in the
domain-agnostic `roundtrip` package.  Its whole job is to make a report's
identity drift-proof: a report is pinned to ONE opaque Overleaf project id, and
both URLs the app uses are *derived* from it —

    web   ("Open in Overleaf")  →  https://www.overleaf.com/project/<id>
    git   (git-bridge push/pull) →  https://git.overleaf.com/<id>

— so the "Open" target and the "Send" target can never point at different
projects (the inconsistency that bit us when they were stored independently).

The opaque id is the one thing a human must supply once (Overleaf has no
title-based URL and no Cloud API to resolve a title→id); everything else is
derived.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Where per-session bindings live (sessions/<dtxsid>/_overleaf_binding.json) —
# scanned by the reverse soft-link below.  Resolved relative to this module.
_DEFAULT_SESSIONS_DIR = Path(__file__).resolve().parent / "sessions"
_BINDING_FILENAME = "_overleaf_binding.json"

# An Overleaf project id is a 24-char hex string (a Mongo ObjectId).  We accept
# either a bare id or any overleaf URL that contains `/project/<id>`.
_ID_RE = re.compile(r"[0-9a-f]{24}", re.IGNORECASE)
_PROJECT_URL_RE = re.compile(r"/project/([0-9a-f]{24})", re.IGNORECASE)

_WEB_BASE = "https://www.overleaf.com/project/"
_GIT_BASE = "https://git.overleaf.com/"


def extract_project_id(ref: str) -> str:
    """
    Pull the opaque project id out of a project URL or a bare id.

    Accepts e.g. "https://www.overleaf.com/project/6a19…bb97",
    "git.overleaf.com/6a19…bb97", or just "6a19…bb97".  Raises ValueError if no
    24-hex id is present, so a bad paste fails loudly at bind time rather than
    silently producing a dead remote.
    """
    if not ref:
        raise ValueError("empty Overleaf project reference")
    m = _PROJECT_URL_RE.search(ref) or _ID_RE.fullmatch(ref.strip()) or _ID_RE.search(ref)
    if not m:
        raise ValueError(f"no Overleaf project id found in {ref!r}")
    return m.group(1) if m.re is _PROJECT_URL_RE else m.group(0)


def web_url(ref: str) -> str:
    """Canonical 'Open in Overleaf' web URL for a project ref."""
    return _WEB_BASE + extract_project_id(ref)


def git_bridge_url(ref: str) -> str:
    """git-bridge push/pull endpoint for a project ref (single-branch master)."""
    return _GIT_BASE + extract_project_id(ref)


def dtxsid_for_project(ref: str, *, sessions_dir: "Path | None" = None) -> "str | None":
    """
    Reverse soft-link: which report (dtxsid) is bound to this Overleaf project?

    Derived, not stored — scans the per-session bindings for one whose
    project_url resolves to the same opaque id, so there's no separate index to
    drift out of sync.  Returns the dtxsid, or None if no report is bound to it.
    Useful for attributing an incoming Overleaf project back to its report.
    """
    try:
        target = extract_project_id(ref)
    except ValueError:
        return None
    base = Path(sessions_dir) if sessions_dir is not None else _DEFAULT_SESSIONS_DIR
    if not base.exists():
        return None
    for binding_file in base.glob(f"*/{_BINDING_FILENAME}"):
        try:
            url = (json.loads(binding_file.read_text()) or {}).get("project_url")
            if url and extract_project_id(url) == target:
                return binding_file.parent.name
        except (ValueError, json.JSONDecodeError, OSError):
            continue
    return None
