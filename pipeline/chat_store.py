"""
pipeline/chat_store.py — persistence for session chat transcripts (ADR-0022).

Where: ``sessions/<DTXSID>/chat/<thread_id>.json``. One file per thread; each
holds the messages (user / assistant, with the assistant's tool trace,
references and unresolved-citation notes as metadata) and the thread's
SourceRegistry (the [Sn] tokens the model may cite, so numbering is stable
across turns and reloads).

Transcripts are EXPLORATORY artifacts: they are never report content (ADR-0018)
and no other part of the pipeline reads them. They are kept so the author can
revisit an interpretation session and so a future "send to narrative" feature
has something to start from.

Writes are atomic (temp file + os.replace) so an interrupted save never leaves
a half-written transcript.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from pathlib import Path

from common.clock import now_iso
from pipeline.session_store import session_dir

# Thread ids are generated here, but they also arrive from URLs, so they are
# validated with the same discipline as session ids (no separators, no dots).
THREAD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class InvalidThreadId(ValueError):
    """A thread id that is not one this module could have generated."""


def validate_thread_id(thread_id: str) -> str:
    if not isinstance(thread_id, str) or not THREAD_ID_RE.match(thread_id):
        raise InvalidThreadId(f"invalid thread id {thread_id!r}")
    return thread_id


def chat_dir(dtxsid: str) -> Path:
    """The session's chat directory (created on demand)."""
    d = session_dir(dtxsid) / "chat"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(dtxsid: str, thread_id: str) -> Path:
    return chat_dir(dtxsid) / f"{validate_thread_id(thread_id)}.json"


def _atomic_write_json(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    os.replace(tmp, path)


def new_thread(dtxsid: str, title: str = "") -> dict:
    """Create and persist an empty thread; return it."""
    thread_id = f"t{int(time.time())}-{secrets.token_hex(3)}"
    thread = {
        "id": thread_id,
        "title": (title or "").strip()[:120],
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "messages": [],
        "sources": [],
    }
    _atomic_write_json(_path(dtxsid, thread_id), thread)
    return thread


def list_threads(dtxsid: str) -> list[dict]:
    """Summaries of every thread, newest first."""
    out = []
    for p in chat_dir(dtxsid).glob("*.json"):
        try:
            t = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        out.append({
            "id": t.get("id", p.stem),
            "title": t.get("title", ""),
            "created_at": t.get("created_at", ""),
            "updated_at": t.get("updated_at", ""),
            "message_count": len(t.get("messages") or []),
        })
    out.sort(key=lambda t: t["updated_at"], reverse=True)
    return out


def load_thread(dtxsid: str, thread_id: str) -> dict | None:
    p = _path(dtxsid, thread_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def save_thread(dtxsid: str, thread: dict) -> None:
    thread["updated_at"] = now_iso()
    _atomic_write_json(_path(dtxsid, thread["id"]), thread)


def delete_thread(dtxsid: str, thread_id: str) -> bool:
    p = _path(dtxsid, thread_id)
    if not p.exists():
        return False
    p.unlink()
    return True


def append_turn(thread: dict, user_message: str, result: dict, sources: list[dict]) -> None:
    """Record one completed turn (user question + assistant answer with its
    grounding metadata) and the registry snapshot. Sets the title from the
    first question when the thread has none."""
    now = now_iso()
    thread.setdefault("messages", []).append({
        "role": "user", "content": user_message, "at": now,
    })
    thread["messages"].append({
        "role": "assistant",
        "content": result.get("answer", ""),
        "at": now,
        "references": result.get("references", []),
        "unresolved_citations": result.get("unresolved_citations", []),
        "tool_trace": result.get("tool_trace", []),
        "model_used": result.get("model_used", ""),
    })
    thread["sources"] = sources
    if not thread.get("title"):
        thread["title"] = user_message.strip().splitlines()[0][:80] if user_message.strip() else ""
