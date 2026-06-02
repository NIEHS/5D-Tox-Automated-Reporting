"""
document_reconcile.py — attribute edited report.tex regions to nodes (ADR-0005).

The round-trip's hard 90%: given the GENERATED baseline report.tex and the
EDITED one that came back (from the Overleaf stand-in, or later the real
git-bridge), figure out *which anchored region a human changed* and record it as
a per-region override.  The generator's `%% rlm:begin/end <kind> <id>` sentinels
(latex_generator._anchor) make this a region-level comparison rather than a
fragile line-diff: we parse both versions into id->region maps and compare.

Attribution rules (mirroring ADR-0005's editability policy):
  - **Innermost wins.**  Genomics node regions nest their content-item regions.
    We compare each region's OWN text (direct children masked by an id
    placeholder), so editing an item's narrative attributes to the item, not its
    enclosing node.  An ancestor is attributed only when ITS own text changed;
    if both change, the ancestor override subsumes the descendant (the
    descendant attribution is dropped).
  - **Structure is app-owned (policy B).**  A region whose set/order of child
    sentinels changed, a sentinel that vanished, or a brand-new region in the
    edit is reported as a STRUCTURAL warning — never silently absorbed.
  - **Content edits win and are recorded** as overrides: latex_region = the
    edited region body; base_hash = region_hash of the BASELINE region (so the
    renderer later flags drift if the generated content moves out from under the
    edit).

This module is pure (operates on two strings); the git/stand-in wrapper that
fetches the two report.tex revisions lives in overleaf_sync.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
import re

from document_overrides import region_hash, set_override

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The sentinel lines latex_generator emits (kept in sync with _ANCHOR_PREFIX
# there).  Group 1 = kind (node|item), group 2 = anchor id.
_BEGIN_RE = re.compile(r"^%% rlm:begin (node|item) (.+)$")
_END_RE = re.compile(r"^%% rlm:end (node|item) (.+)$")

# Sentinel used to mask a direct child's span when computing a region's OWN
# text, so a child edit doesn't read as a parent edit.  NUL can't occur in the
# .tex, so it's an unambiguous placeholder.
def _child_token(child_id: str) -> str:
    return f"\x00{child_id}\x00"


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class Region:
    """One anchored region of report.tex (a node or a genomics content item)."""

    __slots__ = ("anchor_id", "kind", "body", "own_text", "child_ids")

    def __init__(self, anchor_id, kind, body, own_text, child_ids):
        self.anchor_id = anchor_id      # stable key (node.id or "<node>::<item>")
        self.kind = kind                # "node" | "item"
        self.body = body                # literal text between the sentinels
        self.own_text = own_text        # body with direct children masked
        self.child_ids = child_ids      # direct child ids, in document order


class ReconcileResult:
    """Outcome of comparing a baseline report.tex to an edited one."""

    __slots__ = ("edits", "structural", "parse_warnings")

    def __init__(self, edits, structural, parse_warnings):
        # edits: {anchor_id: {"baseline_body", "edited_body"}}
        self.edits = edits
        # structural / parse_warnings: lists of human-readable strings
        self.structural = structural
        self.parse_warnings = parse_warnings


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_regions(tex: str) -> "tuple[dict[str, Region], list[str]]":
    """
    Parse a report.tex into {anchor_id -> Region}, plus parse warnings.

    Stack-based over the sentinel lines (which are well nested by construction).
    Mismatched / unclosed / duplicate sentinels become warnings rather than
    exceptions — a human mangling a sentinel in Overleaf must degrade to a
    flagged region, not a crash.
    """
    lines = tex.split("\n")
    warnings: "list[str]" = []
    # Each open frame collects its body lines (with child spans replaced by a
    # placeholder token) and the literal body lines (for the stored override).
    stack: "list[dict]" = []
    regions: "dict[str, Region]" = {}

    for ln in lines:
        b = _BEGIN_RE.match(ln)
        e = _END_RE.match(ln)
        if b:
            kind, aid = b.group(1), b.group(2)
            # Register as a child of the current parent: a masked token in the
            # parent's own_text, and the literal child lines accumulate live.
            if stack:
                stack[-1]["own"].append(_child_token(aid))
                stack[-1]["children"].append(aid)
            stack.append({"id": aid, "kind": kind, "own": [], "literal": [],
                          "children": []})
        elif e:
            kind, aid = e.group(1), e.group(2)
            if not stack or stack[-1]["id"] != aid or stack[-1]["kind"] != kind:
                warnings.append(f"mismatched end sentinel: {kind} {aid}")
                continue
            frame = stack.pop()
            region = Region(
                anchor_id=frame["id"],
                kind=frame["kind"],
                body="\n".join(frame["literal"]),
                own_text="\n".join(frame["own"]),
                child_ids=list(frame["children"]),
            )
            if aid in regions:
                warnings.append(f"duplicate anchor id: {aid}")
            regions[aid] = region
            # The child's literal lines also belong to the parent's literal body.
            if stack:
                begin = f"%% rlm:begin {kind} {aid}"
                end = f"%% rlm:end {kind} {aid}"
                stack[-1]["literal"].append(begin)
                stack[-1]["literal"].extend(frame["literal"])
                stack[-1]["literal"].append(end)
        else:
            if stack:
                stack[-1]["own"].append(ln)
                stack[-1]["literal"].append(ln)

    for frame in stack:
        warnings.append(f"unclosed sentinel: {frame['kind']} {frame['id']}")

    return regions, warnings


# ---------------------------------------------------------------------------
# Reconciliation (pure)
# ---------------------------------------------------------------------------

def reconcile(baseline_tex: str, edited_tex: str) -> ReconcileResult:
    """
    Compare baseline vs edited report.tex and classify every change.

    Returns a ReconcileResult: content `edits` keyed by the innermost anchor
    whose own text changed (ancestor-subsumed descendants dropped), plus
    `structural` warnings (child set/order changed, sentinel removed/added) and
    `parse_warnings`.
    """
    base, base_warn = parse_regions(baseline_tex)
    head, head_warn = parse_regions(edited_tex)
    structural: "list[str]" = []
    edits: "dict[str, dict]" = {}

    # Anchors that appeared/vanished are structural — we can't map them.
    for aid in base.keys() - head.keys():
        structural.append(f"region no longer anchored in edit: {aid}")
    for aid in head.keys() - base.keys():
        structural.append(f"new region in edit, unmapped: {aid}")

    for aid in base.keys() & head.keys():
        b, h = base[aid], head[aid]
        if b.own_text == h.own_text:
            continue  # this region's own content is unchanged
        if b.child_ids != h.child_ids:
            # Children added / removed / reordered → structural, not content.
            structural.append(f"child structure changed under: {aid}")
            continue
        edits[aid] = {"baseline_body": b.body, "edited_body": h.body}

    # Drop any edit subsumed by an edited ancestor (the ancestor override, which
    # stores the whole region body, already carries the descendant's edit).
    parent = {}
    for aid, region in head.items():
        for cid in region.child_ids:
            parent[cid] = aid

    def _has_edited_ancestor(aid: str) -> bool:
        p = parent.get(aid)
        while p is not None:
            if p in edits:
                return True
            p = parent.get(p)
        return False

    edits = {aid: v for aid, v in edits.items() if not _has_edited_ancestor(aid)}

    return ReconcileResult(edits=edits, structural=structural,
                           parse_warnings=base_warn + head_warn)


# ---------------------------------------------------------------------------
# Public API — apply to the override store
# ---------------------------------------------------------------------------

def apply_reconcile(
    dtxsid: str,
    baseline_tex: str,
    edited_tex: str,
    *,
    source: str = "overleaf",
    sessions_dir=None,
) -> dict:
    """
    Reconcile two report.tex revisions and persist the resulting overrides.

    For each attributed content edit, writes an override (latex_region = the
    edited region body; base_hash = region_hash of the baseline region, matching
    what the renderer recomputes for stale detection).  Structural changes and
    parse problems are returned for the caller to surface — they are NOT written.

    Returns a summary dict: {written, structural, parse_warnings}.
    """
    result = reconcile(baseline_tex, edited_tex)
    written: "list[str]" = []
    for anchor_id, change in result.edits.items():
        kwargs = {} if sessions_dir is None else {"sessions_dir": sessions_dir}
        set_override(
            dtxsid,
            anchor_id,
            change["edited_body"],
            region_hash(change["baseline_body"]),
            source=source,
            **kwargs,
        )
        written.append(anchor_id)
    return {
        "written": sorted(written),
        "structural": result.structural,
        "parse_warnings": result.parse_warnings,
    }
