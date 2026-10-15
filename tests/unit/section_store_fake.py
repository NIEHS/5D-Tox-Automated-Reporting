"""
An in-memory PoolStore for the section steps and the write gate (C2): no disk,
no globals. It keeps the semantics of pipeline.session_store that the gate
relies on — archive-before-overwrite under unique names, a monotonic version
counter, the transient version-event marker popped and appended — so a step
tested here behaves as it does on disk (the integration tests check that).

Not a test module (no ``test_`` prefix): imported by the C2 unit tests.
"""

from __future__ import annotations

import copy
from pathlib import Path

from pipeline.session_store import _VERSION_EVENT_KEY


class FakeSectionStore:
    def __init__(self, sections: dict | None = None):
        self.sections: dict[str, dict] = {k: copy.deepcopy(v) for k, v in (sections or {}).items()}
        self.archives: dict[str, list[tuple[str, dict]]] = {}
        self.events: dict[str, list[dict]] = {}
        self.writes: list[tuple[str, bool]] = []      # (key, archive) per save_section
        self.deleted: list[str] = []
        self._clock = 0

    # --- what the phase guard reads (C1): an INTEGRATED study, so Process
    # is legal — files, a clean validation report and integrated.json.
    _DOCS = {"validation_report.json": {"issues": [], "coverage_matrix": {}}}
    _PRESENT = {"integrated.json"}

    def has_files(self, dtxsid):
        return True

    def has_stale_sections(self, dtxsid):
        return False

    # --- the parts of PoolStore the section code uses -------------------
    def session_dir(self, dtxsid):
        return Path("/nonexistent-fake") / dtxsid

    def read_json(self, dtxsid, name):
        if name in self._DOCS:
            return copy.deepcopy(self._DOCS[name])
        key = name[:-5] if name.endswith(".json") else name
        data = self.sections.get(key)
        return copy.deepcopy(data) if data is not None else None

    def artifact_exists(self, dtxsid, name):
        if name in self._PRESENT:
            return True
        key = name[:-5] if name.endswith(".json") else name
        return key in self.sections

    def _next_version(self, key):
        seen = [0]
        cur = self.sections.get(key)
        if cur and isinstance(cur.get("version"), int):
            seen.append(cur["version"])
        seen += [d.get("version", 0) for _n, d in self.archives.get(key, [])]
        seen += [e.get("version", 0) for e in self.events.get(key, [])]
        return max(seen) + 1

    def _archive(self, key, content):
        self._clock += 1
        name = f"v{content.get('version', 0):04d}-t{self._clock:06d}.json"
        self.archives.setdefault(key, []).append((name, copy.deepcopy(content)))
        return name

    def save_section(self, dtxsid, key, data, archive=True):
        event = data.pop(_VERSION_EVENT_KEY, None)
        prior = self.sections.get(key)
        archived = None
        if archive:
            if prior is not None:
                archived = self._archive(key, prior)
            data["version"] = self._next_version(key)
        else:
            data.setdefault("version", prior.get("version", 1) if prior else self._next_version(key))
        self.sections[key] = copy.deepcopy(data)
        self.writes.append((key, archive))
        if event:
            if archived:
                event.setdefault("archived", archived)
                event.setdefault("prior_version", prior.get("version"))
            self.record_version_event(dtxsid, key, data["version"], event)

    def archive_section(self, dtxsid, key):
        prior = self.sections.get(key)
        return self._archive(key, prior) if prior is not None else None

    def delete_section(self, dtxsid, key):
        self.sections.pop(key, None)
        self.deleted.append(key)

    def read_version_history(self, dtxsid, key):
        return [dict(e) for e in self.events.get(key, [])]

    def record_version_event(self, dtxsid, key, version, event):
        self._clock += 1
        line = {"version": version, "ts": f"t{self._clock:06d}", **dict(event)}
        self.events.setdefault(key, []).append(line)

    def list_archived(self, dtxsid, key):
        return sorted(self.archives.get(key, []), key=lambda t: (t[1].get("version", 0), t[0]))

    def read_archived(self, dtxsid, key, version):
        match = None
        for _name, data in self.list_archived(dtxsid, key):
            if data.get("version") == version:
                match = copy.deepcopy(data)
        return match

    def read_section_dicts(self, dtxsid):
        return copy.deepcopy(self.sections)

    # --- helpers for assertions -----------------------------------------
    def last_event(self, key):
        return self.events.get(key, [])[-1]

    def retrievable(self, key, version) -> bool:
        """I3: the version's text can be read back."""
        cur = self.sections.get(key)
        if cur is not None and cur.get("version") == version:
            return True
        return any(d.get("version") == version for _n, d in self.archives.get(key, []))
