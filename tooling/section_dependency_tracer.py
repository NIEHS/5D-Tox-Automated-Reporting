"""
section_dependency_tracer — observe, don't guess, what each report section reads.

Phase 2 of the section-catalog work (docs/plans/section-catalog-dependency-map.md
§6): the catalog fixed section *identity*; this traces section *dependencies* — for
each section, which processing outputs (cache units / payload keys / session files) it
reads, so the per-section dependency table and the missed-invalidation list rest on
OBSERVED reads, not on reading the code by eye.

Two read surfaces, instrumented separately then composed (the "two-layer" model — the
overlays read payload KEYS, never caches, so cache→section is a chain through
run_process):

  LAYER 1 (Process, cache→payload-key): wrap cache_plumbing._load_cache /
    session_db._latest_cache. Every read during run_process is a cache-unit read; the
    12-key payload assembled from ctx is the set those reads feed. Records
    {cache_unit: hit|miss} and the payload keys produced.

  LAYER 2 (Render, key/file→section): the preview path (rendering.latex_export.
    load_session_data + the report_data_overlays overlays) reads session files and
    _cache_* directly. Wrap the file readers and each _overlay_* fn; a thread-local
    "current section" set around each overlay attributes every read beneath it to that
    section. The node-walk in the generators is attributed by data_key/narrative_key.

Runs entirely against an ALREADY-PROCESSED session (the render path never re-Processes;
the caches are already on disk), so it needs no live Java/LLM. A best-effort Layer-1
run_process pass is attempted too; it is skipped (logged) if the pipeline degrades in
the sandbox — the render trace is the load-bearing half.

Usage:  .venv/bin/python -m tooling.section_dependency_tracer DTXSID50469320
Writes: docs/plans/section-dependency-trace.json  (machine-readable observations)
"""

from __future__ import annotations

import json
import sys
import threading
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

# ── observation state ─────────────────────────────────────────────────────────
_LOCK = threading.RLock()
_CURRENT_SECTION = threading.local()

# LAYER 1 (Process): cache unit -> True (read during run_process), and the 12-key
# payload the run produced. Process reads have no "section" — they feed the payload,
# which the render layer then attributes to sections.
_L1: dict[str, set] = {"cache_units": set(), "payload_keys": set()}

# LAYER 2 (Render): section_key -> what the node walk consumed for that section.
#   node_ids       — the tree nodes that rendered under this section key
#   bindings       — the data_key / narrative_key / platform each node declared
#   data_keys_read — top-level data[...] keys the node's handler actually read
_L2: dict[str, dict[str, set]] = defaultdict(
    lambda: {"node_ids": set(), "bindings": set(), "data_keys_read": set()}
)
# load_session_data file→data-key overlays (session_file -> data keys it populated)
_OVERLAY_READS: set = set()


def _current() -> str | None:
    return getattr(_CURRENT_SECTION, "key", None)


@contextmanager
def _section(key: str):
    prev = getattr(_CURRENT_SECTION, "key", None)
    _CURRENT_SECTION.key = key
    try:
        yield
    finally:
        _CURRENT_SECTION.key = prev


def _record_file(path: str) -> None:
    name = Path(path).name
    if not (name.endswith(".json") or name.endswith(".yaml")):
        return
    with _LOCK:
        _OVERLAY_READS.add(name)


def _node_workflow_key(node) -> str | None:
    """The workflow section key a rendered node belongs to — mirrors the catalog's
    node→section rule so render attribution and the catalog use one vocabulary."""
    nt = node.node_type
    if nt == "genomics-section":
        return "genomics"
    if node.platform and nt in ("table", "incidence-table"):
        return "bm2"
    if nt == "narrative+tables" and node.narrative_key:
        return node.narrative_key
    dk = node.data_key
    if dk in ("background", "methods", "summary", "bmd_summary"):
        return dk
    if dk == "genomics_sections":
        return "genomics"
    return None


# ── monkeypatch installers ─────────────────────────────────────────────────────
def _install_layer2():
    """Attribute render reads to sections via the node-walk dispatch + file readers."""
    import rendering.latex_export as lx
    import rendering.html_generator as hg

    # 2a. session-file reads inside load_session_data (file→data-key overlays)
    if hasattr(lx, "_load_json"):
        _orig_load_json = lx._load_json

        def _traced_load_json(path):
            _record_file(str(path))
            return _orig_load_json(path)

        lx._load_json = _traced_load_json

    # 2b. node walk: wrap every HTML dispatch handler so that while a node renders,
    #     its workflow section is current and the data[...] keys it reads are
    #     recorded. `data` is wrapped in a read-recording proxy for the duration.
    dispatch = hg._DISPATCH

    def _wrap_handler(node_type, orig_handler):
        def _traced(node, data):
            key = _node_workflow_key(node)
            if key is None:
                return orig_handler(node, data)
            with _LOCK:
                _L2[key]["node_ids"].add(node.id)
                for b in (node.data_key, node.narrative_key, node.platform):
                    if b:
                        _L2[key]["bindings"].add(b)
            proxy = _ReadRecordingDict(data, key)
            with _section(key):
                return orig_handler(node, proxy)

        return _traced

    for nt in list(dispatch.keys()):
        dispatch[nt] = _wrap_handler(nt, dispatch[nt])


class _ReadRecordingDict(dict):
    """A dict view that records top-level key reads against a section. Subclasses
    dict so isinstance/`**` and all handler access work unchanged; only .get and
    __getitem__ are observed (the two access forms the handlers use)."""

    def __init__(self, base: dict, section_key: str):
        super().__init__(base)
        self._section_key = section_key

    def _rec(self, key):
        with _LOCK:
            _L2[self._section_key]["data_keys_read"].add(key)

    def get(self, key, default=None):
        self._rec(key)
        return super().get(key, default)

    def __getitem__(self, key):
        self._rec(key)
        return super().__getitem__(key)


# ── run the trace ───────────────────────────────────────────────────────────
def trace_render(dtxsid: str) -> None:
    """Layer 2: drive the preview render path over the on-disk session."""
    from rendering.preview_surface import materialize_preview

    print(f"[render] materializing preview for {dtxsid} …", file=sys.stderr)
    try:
        manifest = materialize_preview(dtxsid, surface="html")
        print(f"[render] ok: {manifest.get('files')}", file=sys.stderr)
    except Exception as e:
        print(f"[render] FAILED: {e}", file=sys.stderr)


def trace_process(dtxsid: str) -> None:
    """Layer 1: READ-ONLY cache→payload-key probe.

    Records which cache units exist on disk for this session and maps them to the
    payload keys they feed (the static `_assemble_payload` contract). Deliberately
    does NOT run `run_process` — that PERSISTS caches as a side effect (it rebuilds
    `_cache_sections_*` etc.), and running it with placeholder params once corrupted
    a real session's captions/narratives with the "Test Compound" fallback. A trace
    must never mutate the thing it observes.
    """
    from common.paths import SESSIONS_DIR
    from pathlib import Path

    # cache unit → the payload keys it feeds (from _assemble_payload + run_data).
    unit_to_keys = {
        "ntp": [],  # feeds sections/bmd_summary downstream, no direct payload key
        "sections": ["sections", "unified_narratives"],
        "bmds": ["apical_bmd_summary_bmds"],
        "bmd_summary": ["apical_bmd_summary", "bmd_stats", "bmd_stat_labels"],
        "genomics": ["genomics_sections"],
        "charts": ["chart_images"],
        "methods": ["methods"],
    }
    d = Path(SESSIONS_DIR) / dtxsid
    found = 0
    for unit, keys in unit_to_keys.items():
        if list(d.glob(f"_cache_{unit}_*.json")):
            _L1["cache_units"].add(unit)
            _L1["payload_keys"].update(keys)
            found += 1
    print(f"[process] read-only probe: {found}/7 cache units present", file=sys.stderr)


def main() -> int:
    dtxsid = sys.argv[1] if len(sys.argv) > 1 else "DTXSID50469320"

    # Layer 1 is now a read-only cache probe (no pipeline run), so its _load_cache
    # wrap is unnecessary; only Layer 2 needs instrumentation installed.
    _install_layer2()

    trace_process(dtxsid)  # read-only cache→payload-key probe
    trace_render(dtxsid)   # the load-bearing render trace

    def _ser(d):
        return {k: sorted(v) for k, v in d.items()}

    out = {
        "dtxsid": dtxsid,
        "process_layer": _ser(_L1),
        "render_layer": {sec: _ser(obs) for sec, obs in sorted(_L2.items())},
        "load_session_overlay_reads": sorted(_OVERLAY_READS),
    }
    out_path = Path("docs/plans/section-dependency-trace.json")
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nwrote {out_path}")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
