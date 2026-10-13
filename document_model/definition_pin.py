"""
document_model/definition_pin.py — a session's document definition, pinned
(ADR-0029 §12), as its analysis method is (ADR-0027).

A definition (an era, or a study's own extending one) changes as the tool
learns the books: an era file gains a section, a phrasing is corrected.  A
report that is finished must not change with it.  So a session PINS the
definition it renders from, by the content hash of the composed definition
(every ``extends`` resolved):

    sessions/<id>/document_definition.json   {name, hash, mode, pinned_at, pinned_by}
    sessions/<id>/document_definition.yaml   the composed definition, as pinned

Two modes, the method profile's:

  TRACK   (the default) the session renders from the current files; the pin
          records which definition it rendered from, and a change of hash
          re-pins with the previous pin and snapshot kept under
          ``history/_document_definition/`` — the record of what changed.
  FIXED   the session renders from its snapshot, whatever the files say
          since; ``drift`` reports that they differ.  Fix a finished
          report; re-pin to take up a revised definition.

A FIXED session's definition name is ``@pinned/<id>`` (definition_name), which
document_template._load_raw reads from the snapshot, so every loader — the
tree, the series facts, the phrasing — reads the pinned definition.  A
snapshot whose content no longer matches its pin's hash fails loudly:
pinned definitions are immutable.  What the snapshot does not hold — content
files a node names, the renderers' code — is outside the pin; rules that
change in code are kept by name (docs/writing-rules-inventory.md).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone

import yaml

logger = logging.getLogger(__name__)

PIN_FILE = "document_definition.json"
SNAPSHOT_FILE = "document_definition.yaml"
HISTORY = "_document_definition"
PINNED = "@pinned/"
TRACK = "track"
FIXED = "fixed"
MODES = (TRACK, FIXED)


class DefinitionPinError(ValueError):
    """A pin or snapshot that does not hold what it says."""


def _session(dtxsid: str):
    from common.dtxsid import validate_dtxsid
    from common.paths import SESSIONS_DIR
    return SESSIONS_DIR / validate_dtxsid(dtxsid)


def definition_hash(raw) -> str:
    """The content hash of a composed definition."""
    blob = json.dumps(raw, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _current(dtxsid: str) -> tuple[str, object]:
    """(the definition the files give this study, its composed mapping)."""
    from document_model.document_definition import current_definition_name
    from document_model.document_template import _load_raw
    name = current_definition_name(dtxsid)
    return name, _load_raw(name)


def read_pin(dtxsid: str) -> dict | None:
    path = _session(dtxsid) / PIN_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def load_snapshot(dtxsid: str):
    """A pinned session's composed definition, checked against its pin."""
    pin = read_pin(dtxsid)
    path = _session(dtxsid) / SNAPSHOT_FILE
    if not pin or not path.is_file():
        raise DefinitionPinError(f"{dtxsid}: no pinned document definition")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if definition_hash(raw) != pin.get("hash"):
        raise DefinitionPinError(
            f"{dtxsid}: {SNAPSHOT_FILE} no longer matches its pin (hash {pin.get('hash')} → "
            f"{definition_hash(raw)}); pinned definitions are immutable — re-pin instead")
    return raw


def pinned_name(dtxsid: str) -> str | None:
    """``@pinned/<id>`` for a FIXED session, else None."""
    from common.dtxsid import is_valid_dtxsid
    if not is_valid_dtxsid(dtxsid):
        return None
    pin = read_pin(dtxsid)
    return f"{PINNED}{dtxsid}" if pin and pin.get("mode") == FIXED else None


def _archive(session, pin: dict) -> None:
    hist = session / "history" / HISTORY
    hist.mkdir(parents=True, exist_ok=True)
    stamp = (pin.get("pinned_at") or "unknown").replace(":", "")
    stem = f"{stamp}-{pin.get('hash')}"
    (hist / f"{stem}.json").write_text(json.dumps(pin, indent=2) + "\n", encoding="utf-8")
    snapshot = session / SNAPSHOT_FILE
    if snapshot.is_file():
        (hist / f"{stem}.yaml").write_text(snapshot.read_text(encoding="utf-8"),
                                           encoding="utf-8")


def pin_definition(dtxsid: str, mode: str = FIXED, *, by: str = "user") -> dict:
    """Pin the study to the definition its files give it now, in ``mode``
    (the previous pin, when it differs, is kept in the history)."""
    if mode not in MODES:
        raise DefinitionPinError(f"mode must be one of {MODES}, got {mode!r}")
    session = _session(dtxsid)
    name, raw = _current(dtxsid)
    pin = {"name": name, "hash": definition_hash(raw), "mode": mode,
           "pinned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "pinned_by": by}
    old = read_pin(dtxsid)
    if old:
        if (old.get("name"), old.get("hash"), old.get("mode")) == (name, pin["hash"], mode):
            return old
        _archive(session, old)
        logger.warning("Document definition of %s: %s %s (%s) → %s %s (%s)", dtxsid,
                       old.get("name"), old.get("hash"), old.get("mode"), name, pin["hash"], mode)
    session.mkdir(parents=True, exist_ok=True)
    (session / SNAPSHOT_FILE).write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    (session / PIN_FILE).write_text(json.dumps(pin, indent=2) + "\n", encoding="utf-8")
    return pin


def ensure_pin(dtxsid: str) -> dict:
    """The study's pin, made current: a study with none TRACKS (the default);
    a TRACK pin whose definition changed is re-pinned (the change recorded in
    the history); a FIXED pin is left alone.  Called before every Process run."""
    pin = read_pin(dtxsid)
    if pin and pin.get("mode") == FIXED:
        return pin
    return pin_definition(dtxsid, TRACK, by=(pin or {}).get("pinned_by", "default"))


def drift(dtxsid: str) -> str | None:
    """For a FIXED session: how the files' definition now differs from the
    pinned one (None when it does not, or the session is not FIXED)."""
    pin = read_pin(dtxsid)
    if not pin or pin.get("mode") != FIXED:
        return None
    name, raw = _current(dtxsid)
    now = definition_hash(raw)
    if (name, now) == (pin.get("name"), pin.get("hash")):
        return None
    return (f"{dtxsid} renders from its pinned definition {pin.get('name')} {pin.get('hash')}; "
            f"the files now give {name} {now} (re-pin to take it up)")
