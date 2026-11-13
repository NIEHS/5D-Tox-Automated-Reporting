"""
pipeline/prompt_store.py — persistence for section prompt templates, the runs
they produced, and the workshop chat threads that changed them.

Where (all under SESSIONS_DIR, which is gitignored — a critique of an
unpublished study's output must never reach git):

  _prompts/<section>/v002.md …          an edited template version (immutable)
  _prompts/<section>/index.jsonl         append-only log: one line per saved
                                         version or "make current" act
  _prompts/<section>/threads/<id>.json   a workshop chat thread
  <DTXSID>/narrative_runs/<section>/<run_id>.json
                                         one generation: the exact prompt sent,
                                         the template version, the output
  <DTXSID>/narrative_comparisons/<section>/c001.json …
                                         a model comparison: which models ran
                                         how many times, their runs, and the
                                         arbiter's review; numbered per study,
                                         never rewritten once complete

Version 1 of every section is the shipped default (narrative/prompts/<section>.md);
it is never copied here. The current version is the `current` of the LAST index
line, so rolling back is a new line, never a deletion.

Writes are atomic (temp file + os.replace), as in pipeline/chat_store.py.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from pathlib import Path

import common.paths as paths
from common.clock import now_iso
from pipeline.chat_store import InvalidThreadId, validate_thread_id
from pipeline.session_store import session_dir

__all__ = [
    "InvalidThreadId", "validate_thread_id",
    "UnknownVersion", "section_dir", "versions", "current_version",
    "read_version_file", "save_version", "make_current",
    "save_run", "load_run", "list_runs",
    "new_comparison", "save_comparison", "load_comparison", "list_comparisons",
    "new_thread", "load_thread", "save_thread", "list_threads",
]

RUN_ID_RE = re.compile(r"^r\d{8}T\d{6}-[0-9a-f]{6}$")


class UnknownVersion(ValueError):
    """A template version number that was never saved."""


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _atomic_write_json(path: Path, payload: dict) -> None:
    _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------------------
# Template versions
# ---------------------------------------------------------------------------

def section_dir(section: str, *, create: bool = False) -> Path:
    """The section's prompt directory (created only for a write). `section`
    must already be validated against the registry (narrative.prompt_templates)."""
    d = paths.SESSIONS_DIR / "_prompts" / section
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def _index(section: str) -> list[dict]:
    p = section_dir(section) / "index.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def _append_index(section: str, entry: dict) -> None:
    p = section_dir(section, create=True) / "index.jsonl"
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def versions(section: str) -> list[dict]:
    """Every saved version, oldest first — version 1 (the shipped default)
    included: [{version, parent, at, rationale, thread_id}]."""
    out = [{"version": 1, "parent": None, "at": "", "thread_id": None,
            "rationale": "Shipped default."}]
    for e in _index(section):
        if e.get("kind") == "version":
            out.append({k: e.get(k) for k in ("version", "parent", "at", "rationale", "thread_id")})
    return out


def current_version(section: str) -> int:
    """The version in use: the `current` of the last index line, else 1."""
    entries = _index(section)
    return int(entries[-1]["current"]) if entries else 1


def read_version_file(section: str, version: int) -> str | None:
    """A saved version's text (None for version 1 — the caller reads the
    shipped default). Raises UnknownVersion for a version never saved."""
    if version == 1:
        return None
    p = section_dir(section) / f"v{int(version):03d}.md"
    if not p.exists():
        raise UnknownVersion(f"{section} has no version {version}")
    return p.read_text(encoding="utf-8")


def save_version(section: str, text: str, *, rationale: str = "",
                 thread_id: str | None = None, parent: int | None = None) -> int:
    """Write a new immutable version and make it current; return its number."""
    known = [v["version"] for v in versions(section)]
    n = max(known) + 1
    _atomic_write(section_dir(section, create=True) / f"v{n:03d}.md", text)
    _append_index(section, {
        "kind": "version", "version": n, "current": n,
        "parent": parent if parent is not None else current_version(section),
        "at": now_iso(), "rationale": (rationale or "").strip(),
        "thread_id": thread_id,
    })
    return n


def make_current(section: str, version: int, *, rationale: str = "") -> None:
    """Make an existing version current (a rollback is this) — a new index
    line; no file is deleted or rewritten."""
    if version not in {v["version"] for v in versions(section)}:
        raise UnknownVersion(f"{section} has no version {version}")
    _append_index(section, {
        "kind": "current", "current": int(version), "at": now_iso(),
        "rationale": (rationale or "").strip(),
    })


# ---------------------------------------------------------------------------
# Runs — one generation each, per session
# ---------------------------------------------------------------------------

def _runs_dir(dtxsid: str, section: str) -> Path:
    d = session_dir(dtxsid) / "narrative_runs" / section
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_run(dtxsid: str, section: str, record: dict) -> dict:
    """Persist a run record, stamped with a time-ordered `run_id` and `at`;
    return the stamped record."""
    run_id = f"r{time.strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(3)}"
    record = {**record, "run_id": run_id, "at": now_iso()}
    _atomic_write_json(_runs_dir(dtxsid, section) / f"{run_id}.json", record)
    return record


def load_run(dtxsid: str, section: str, run_id: str) -> dict | None:
    if not RUN_ID_RE.match(run_id or ""):
        return None
    p = _runs_dir(dtxsid, section) / f"{run_id}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except (OSError, ValueError):
        return None


def list_runs(dtxsid: str, section: str, limit: int = 50) -> list[dict]:
    """The session's runs for a section, newest first (full records)."""
    out = []
    for p in sorted(_runs_dir(dtxsid, section).glob("r*.json"), reverse=True)[:limit]:
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


# ---------------------------------------------------------------------------
# Model comparisons — per session, numbered c001, c002, …
# ---------------------------------------------------------------------------

COMPARISON_ID_RE = re.compile(r"^c\d{3,6}$")


def _comparisons_dir(dtxsid: str, section: str) -> Path:
    d = session_dir(dtxsid) / "narrative_comparisons" / section
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_comparison(dtxsid: str, section: str, record: dict) -> dict:
    """Start a comparison: the next number for this study; status "running"."""
    d = _comparisons_dir(dtxsid, section)
    taken = [int(p.stem[1:]) for p in d.glob("c*.json") if COMPARISON_ID_RE.match(p.stem)]
    n = max(taken, default=0) + 1
    record = {**record, "comparison_id": f"c{n:03d}", "number": n, "at": now_iso(),
              "status": "running"}
    _atomic_write_json(d / f"c{n:03d}.json", record)
    return record


def save_comparison(dtxsid: str, section: str, record: dict) -> None:
    """Update a comparison while it runs. A complete or failed one is final."""
    path = _comparisons_dir(dtxsid, section) / f"{record['comparison_id']}.json"
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stored = {}
    if stored.get("status") in ("complete", "failed"):
        raise ValueError(f"comparison {record['comparison_id']} is final")
    _atomic_write_json(path, record)


def load_comparison(dtxsid: str, section: str, comparison_id: str) -> dict | None:
    if not COMPARISON_ID_RE.match(comparison_id or ""):
        return None
    p = _comparisons_dir(dtxsid, section) / f"{comparison_id}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except (OSError, ValueError):
        return None


def list_comparisons(dtxsid: str, section: str) -> list[dict]:
    """Summaries of the study's comparisons, newest first."""
    out = []
    for p in _comparisons_dir(dtxsid, section).glob("c*.json"):
        try:
            c = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({k: c.get(k) for k in ("comparison_id", "number", "at", "status",
                                          "template_version", "generators", "repetitions",
                                          "arbiter_model")})
        out[-1]["recommended_model"] = ((c.get("review") or {}).get("recommendation") or {}).get("model")
    out.sort(key=lambda c: c["number"] or 0, reverse=True)
    return out


# ---------------------------------------------------------------------------
# Workshop threads — global per section; each turn names the session it saw
# ---------------------------------------------------------------------------

def _thread_path(section: str, thread_id: str, *, create: bool = False) -> Path:
    d = section_dir(section) / "threads"
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d / f"{validate_thread_id(thread_id)}.json"


def new_thread(section: str) -> dict:
    thread_id = f"t{int(time.time())}-{secrets.token_hex(3)}"
    thread = {"id": thread_id, "section": section, "title": "",
              "created_at": now_iso(), "updated_at": now_iso(), "messages": []}
    _atomic_write_json(_thread_path(section, thread_id, create=True), thread)
    return thread


def load_thread(section: str, thread_id: str) -> dict | None:
    p = _thread_path(section, thread_id)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except (OSError, ValueError):
        return None


def save_thread(section: str, thread: dict) -> None:
    thread["updated_at"] = now_iso()
    _atomic_write_json(_thread_path(section, thread["id"], create=True), thread)


def list_threads(section: str) -> list[dict]:
    """Thread summaries, newest first."""
    out = []
    for p in (section_dir(section) / "threads").glob("*.json"):
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"id": t.get("id", p.stem), "title": t.get("title", ""),
                    "updated_at": t.get("updated_at", ""),
                    "message_count": len(t.get("messages") or [])})
    out.sort(key=lambda t: t["updated_at"], reverse=True)
    return out
