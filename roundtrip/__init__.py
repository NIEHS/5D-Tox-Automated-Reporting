"""
roundtrip — domain-agnostic round-trip sync for a machine-generated document
that humans edit in a git-backed editor (ADR-0005).

Nothing in this package imports app code (no latex_*, report_data, document_tree;
no knowledge of report.tex, the DocNode tree, or a specific sessions/ layout
beyond an injectable default).  rlm-bmdx is its first consumer; the boundary is
drawn now, a standalone package can be lifted out later.

Layers:
  - anchors    — the sentinel convention (writer + reader share it here)
  - overrides  — per-region human-edit store + region_hash stale detection
  - reconcile  — parse anchored regions, diff baseline↔edited, attribute edits
  - lock       — single-writer turn flag
  - transport  — working clone + remote(s): push / pull / mirror / stand-in
"""

from .anchors import PREFIX, BEGIN_RE, END_RE, begin_line, end_line, wrap
from .overrides import (
    region_hash,
    load_overrides,
    save_overrides,
    set_override,
    clear_override,
    get_override,
)
from .reconcile import Region, ReconcileResult, parse_regions, reconcile, apply_reconcile
from .lock import get_lock, acquire_lock, release_lock
from .transport import (
    init_standin,
    push_document,
    pull_document,
    read_clone_report,
    report_at,
    remote_head,
    reconcile_from_clone,
    simulate_overleaf_edit,
    get_binding,
    set_binding,
)

__all__ = [
    "PREFIX", "BEGIN_RE", "END_RE", "begin_line", "end_line", "wrap",
    "region_hash", "load_overrides", "save_overrides", "set_override",
    "clear_override", "get_override",
    "Region", "ReconcileResult", "parse_regions", "reconcile", "apply_reconcile",
    "get_lock", "acquire_lock", "release_lock",
    "init_standin", "push_document", "pull_document", "read_clone_report",
    "report_at", "remote_head", "reconcile_from_clone", "simulate_overleaf_edit",
    "get_binding", "set_binding",
]
