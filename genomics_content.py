"""
genomics_content.py — the ordered, sub-addressable content items inside a
genomics-section component (ADR-0003 Phase 4, Part B).

The genomics-section used to be a monolith: one handler emitting narrative +
table + descriptions per (organ, sex).  Part B of ADR-0003 makes each of those
an addressable content item with a stable id, so an item can be independently
oriented (and, in Phase 5, so a chart can be inserted as one more item without
touching the section's structure).

This module owns the ORDER and IDENTITY (item_id, kind, orientable) of those
content items.  It is shared by both renderers so the LaTeX and HTML paths
cannot drift on which items exist or what they are called — the same role the
dispatch-parity guard plays for node types.  It renders nothing; each renderer
emits the item's payload in its own markup (keyed off the returned `part`).
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entry_base_id(entry: dict) -> str:
    """
    Stable per-(organ, sex) id prefix, e.g. "liver-male".  Lower-cased and
    hyphenated so it is a safe overlay-key and DOM-id component (display text
    is capitalised separately by the renderers).
    """
    organ = (entry.get("organ") or "").strip().lower().replace(" ", "-")
    sex = (entry.get("sex") or "").strip().lower().replace(" ", "-")
    return f"{organ}-{sex}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def genomics_content_plan(entry: dict, role: str) -> list[dict]:
    """
    The ordered content items for one (organ, sex) genomics entry.

    Returns a list of dicts {item_id, kind, part, orientable}, where `part`
    tells the renderer which payload to emit.  Order matches the original
    monolith exactly: narrative (only if present) -> table (always) ->
    descriptions (only if present).  The table is the one orientable item (it
    is wide and may flip landscape); prose is not.  Phase 5 inserts chart items
    into this list (orientable charts), with no change to the renderers' loop.

    item_ids are scoped to the (organ, sex) block, so the full overlay key for
    a content item is "<component-id>::<item_id>" (see
    render_capabilities.content_item_landscape_requested).
    """
    base = _entry_base_id(entry)
    plan: list[dict] = []

    if entry.get("narrative"):
        plan.append(
            {"item_id": f"{base}-narrative", "kind": "text",
             "part": "narrative", "orientable": False}
        )

    # The table is always planned: even with no rows the renderer emits a
    # visible "pending" placeholder, matching the pre-decomposition behaviour.
    plan.append(
        {"item_id": f"{base}-table", "kind": "table",
         "part": "table", "orientable": True}
    )

    # Charts (Phase 5): one orientable content item per attached chart image
    # (UMAP / cluster scatter).  entry["charts"] is populated by
    # genomics_charts.attach_genomics_charts on BOTH paths — the session-export
    # path (latex_export) and the web/preview path (report_data) — so chart
    # items appear identically on either surface.  When a session has no chart
    # cache, entry["charts"] is absent and no chart items are planned.  Each
    # carries its `chart_key` so the renderer can fetch the right image from
    # entry["charts"].
    for chart in entry.get("charts") or []:
        key = chart.get("key", "chart")
        plan.append(
            {"item_id": f"{base}-{key}", "kind": "chart", "part": "chart",
             "chart_key": key, "orientable": True}
        )

    descriptions = (
        entry.get("go_descriptions") if role == "gene_set"
        else entry.get("gene_descriptions")
    )
    if descriptions:
        plan.append(
            {"item_id": f"{base}-descriptions", "kind": "text",
             "part": "descriptions", "orientable": False}
        )

    return plan
