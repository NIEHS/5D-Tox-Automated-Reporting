"""
workflow.ownership — the ONE guard predicate over content ownership (ADR-0015
§Consolidation, the narrow step-4b half).

Enforcement of "this content is user-owned / approved / don't let a machine
silently overwrite it" was smeared across the codebase: a per-section `approved`/
`approved_at`/`stale` boolean triple stamped on each section JSON, the ADR-0005
round-trip override presence, and an ad-hoc `force` flag inside the genomics LLM
path. This module gives all of them ONE lens: the on-disk booleans are mapped
into the step-4a Fact set (workflow.labels) at READ time, and the derived guard
(workflow.guard) answers the two questions callers actually ask:

  * may_machine_write(...) — may an LLM / regeneration overwrite this section?
    (axis 1, the hard machine guard — the escape-hatch `force` bypasses it.)
  * protection_map(...) — {node_id -> GuardLevel} for the renderer to draw the
    inform mark (axis 2), the real-data wiring behind step 5's data["protection"].

DELIBERATELY an ADAPTER, not a migration (decided 2026-08-16): the section JSONs
keep their `approved`/`stale` booleans unchanged; this module is the lens that
reads them AS facts. No write-format change, fully reversible, no session
migration. Converging the genomics ad-hoc override store onto roundtrip/overrides
is a separate follow-up (still Proposed in ADR-0015).

Purity: the fact adapter (`section_facts`) is pure over a section dict. The
disk-touching entry points take an explicit reader so the web path passes a
PoolStore-like accessor and tests pass a fake — no module globals.
"""

from __future__ import annotations

from workflow.guard import GuardLevel, blocks_machine_regen
from workflow.labels import Fact


# ---------------------------------------------------------------------------
# The adapter: on-disk section booleans -> the step-4a Fact set.
# ---------------------------------------------------------------------------

def section_facts(section: "dict | None") -> "frozenset[Fact]":
    """Map a section JSON's ownership booleans into the Fact set. Pure.

    The section dict is what save_section persisted (see session_routes approve):
      approved: bool      — the human blessed this content -> Fact.APPROVED
      approved_at: str    — timestamp (not a fact; presence tracked via approved)
      stale: bool         — pool mutated after approval (currency signal; handled
                            by is_section_stale, NOT folded into the fact set —
                            staleness is a currency concern, kind #6, not a label)

    Only `approved` maps to a content fact today. `final`/`protected`/`published`
    are not yet written by the approve path (that is the deferred facts-on-disk
    follow-up); when they are, add them here — this is the single translation
    point. A missing/empty section carries no facts.
    """
    if not isinstance(section, dict):
        return frozenset()
    facts: set[Fact] = set()
    if section.get("approved"):
        facts.add(Fact.APPROVED)
    return frozenset(facts)


def is_section_stale(section: "dict | None") -> bool:
    """Whether a section carries the on-disk `stale` flag (pool mutated after
    approval). This is the currency signal, kept separate from the fact set —
    workflow.currency owns what BLOCK does with it; here it only feeds the
    machine-write predicate (a stale section is NOT safe to silently regen, but
    an approved one having gone stale must still not be clobbered)."""
    return bool(isinstance(section, dict) and section.get("stale"))


def is_user_owned(section: "dict | None") -> bool:
    """Whether a human owns this section's content (edited and/or approved) — the
    CONTEXT.md 'user-owned narratives are never silently recomputed' rule.

    True when the section is approved OR carries the reconciler/edit marker. This
    is the provenance fact `blocks_machine_regen` needs; kept here (not in guard)
    because it reads storage shape. `user_edited`/`original_*` mirror what the
    approve path records for style-learning.
    """
    if not isinstance(section, dict):
        return False
    if section.get("approved"):
        return True
    # A section the user edited before approving still owns its text (the approve
    # path compares original_* vs current to detect edits; presence of an edited
    # flag or a divergent original marks ownership).
    return bool(section.get("user_edited"))


# ---------------------------------------------------------------------------
# The predicate callers ask: may a machine overwrite this section?
# ---------------------------------------------------------------------------

def may_machine_write(section: "dict | None", *, force: bool = False) -> bool:
    """May an LLM / regeneration write over this section's content?

    The single machine-guard predicate that replaces the scattered checks (the
    genomics `force`-flag reasoning, the 'return the store, full stop' comment,
    the per-surface override presence test). Composes workflow.guard axis 1:

      * `force=True` is the deliberate, user-triggered escape hatch (the
        Regenerate action) — it always permits the write (the human asked for it).
      * otherwise refuse when the content is user-owned (approved/edited) — the
        hard machine guard — regardless of staleness (a stale-but-owned section
        must still not be clobbered; the user re-blesses it, the machine doesn't).

    Returns True = safe to (re)generate; False = refuse.
    """
    if force:
        return True
    facts = section_facts(section)
    user_edited = is_user_owned(section)
    # blocks_machine_regen is True when we must NOT overwrite; invert for "may".
    return not blocks_machine_regen(facts, user_edited=user_edited)


# ---------------------------------------------------------------------------
# The render wiring: {node_id -> GuardLevel} for step 5's data["protection"].
# ---------------------------------------------------------------------------

def protection_level(section: "dict | None", *, report_published: bool = False) -> GuardLevel:
    """The visual protection level for one section — MACHINE-PROTECTED semantics.

    Decided 2026-08-16: the rendered mark shows what the SYSTEM won't silently
    overwrite (the editor's original driver — "show what is protected content"),
    NOT pure human-facing maturity. So the mark lights on OWNERSHIP (approved or
    user-edited), which the approve path already records — visible value today —
    rather than waiting for a `final`/`protected` fact the approve path doesn't
    write yet. The report-grain `published` floor still applies (louder mark).

    OPEN when the section is neither owned nor in a published report → no mark.
    """
    if is_user_owned(section):
        level = GuardLevel.GUARDED
    else:
        level = GuardLevel.OPEN
    if report_published and level < GuardLevel.PUBLISHED:
        level = GuardLevel.PUBLISHED
    return level


def protection_map(
    tree, data: dict, *, report_published: bool = False
) -> "dict[str, GuardLevel]":
    """Build the per-node protection level map the renderer surfaces (step 5).

    Walks the document tree; for each node that owns approvable content, reads the
    already-loaded section dict out of `data` (via the node's data_key /
    narrative_key — the SAME lookup the renderers use, so no node->section-key
    mapping is reinvented) and derives its MACHINE-PROTECTED level (see
    protection_level). Result is keyed by DocNode.id — exactly what
    render_common.resolve_protection expects under data["protection"].

    Only nodes at GUARDED+ are included; OPEN entries are omitted so an empty map
    (no owned content, unpublished report) stays byte-identical downstream.
    """
    result: dict[str, GuardLevel] = {}

    def _section_for(node) -> "dict | None":
        # Reuse the renderer's content-resolution keys. A node's owned content is
        # at data[data_key] (front-matter/section dicts) or, for narrative-group
        # nodes, data["unified_narratives"][narrative_key]. We only need the
        # ownership booleans, which live on the section dict either way.
        key = getattr(node, "data_key", None)
        if key and isinstance(data.get(key), dict):
            return data[key]
        nkey = getattr(node, "narrative_key", None)
        if nkey:
            unified = data.get("unified_narratives")
            if isinstance(unified, dict) and isinstance(unified.get(nkey), dict):
                return unified[nkey]
        return None

    def _visit(node) -> None:
        section = _section_for(node)
        level = protection_level(section, report_published=report_published)
        if level >= GuardLevel.GUARDED:
            result[node.id] = level
        for child in getattr(node, "children", None) or []:
            _visit(child)

    roots = tree if isinstance(tree, list) else [tree]
    for root in roots:
        if root is not None:
            _visit(root)
    return result
