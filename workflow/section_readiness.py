"""
workflow.section_readiness — DERIVED report-section readiness (Phase 1).

The document-structure authoring workflow (Background → Materials & Methods →
apical/genomics results → Apical BMD Summary → Summary) has *completion
dependencies* between sections. Today those are ad-hoc imperative flags in the JS
front-end (`Alpine.store('app').ready.methods = true`, `ready.summary = true`,
and `btn.disabled` toggles) set from a dozen call sites in `web/js/*.js`. That is
exactly the imperative pattern CONTEXT.md invariant 3 forbids ("UI phase is
DERIVED, never imperatively set") and the suspected reason approve/lock/unlock
felt unreliable.

This module replaces those flags with a single DERIVED function: given which
sections are approved (read from disk via the store) plus a declared dependency
table, it returns per-section readiness. Nothing is stored — readiness is
recomputed from the approved-set every call, same discipline as
`workflow.engine.derive_phase`.

Dependency rules — extracted from the JS as a faithful UNION of every place that
sets `ready.methods` / `ready.summary`:

  * `showMethodsSection()` is called from background approve (background.js:302),
    session restore when background is approved OR ≥1 apical result section
    exists (chemical.js:471 — `backgroundApproved || apicalSections`), and after
    process-integrated (pipeline.js:597).
  * `showSummarySection()` is called from background approve (background.js:305),
    genomics generation (genomics.js:209 — a result exists), session restore when
    background is approved (chemical.js:598), and after process-integrated
    (pipeline.js:598).

Collapsed to their derived (approval-driven) form, both Methods and Summary
unlock on the SAME condition: `background approved OR ≥1 result section approved`.
The result group is the apical (`bm2_*`) and genomics (`genomics_*`) instance
families. See `_UNLOCK_RULES` — the rules live as DATA, not as conditionals
scattered across handlers.

Ambiguity resolved (flagged for review): the task prose says Methods "unlocks
only after a result section is approved", but the live JS ALSO unlocks it on
background approval (and treats the pipeline-processed path as unlocking both).
This module preserves the JS UNION behavior (background OR result) because the
characterization gate must reproduce the *existing* rules; the "results only"
reading would be a behavior change, not a port.
"""

from __future__ import annotations

# The singleton report sections that always appear in the readiness map, even
# before anything is on disk (a UI wants to show them as present-but-locked).
# Instance families (bm2_*, genomics_*) only appear once they exist on disk.
_SINGLETON_KEYS: tuple[str, ...] = ("background", "methods", "bmd_summary", "summary")


# Declared dependency table (DATA, not code). Maps a section TYPE to the unlock
# groups it requires. A section is enabled iff it declares no groups OR at least
# one group is satisfied (OR semantics — mirrors the JS `||`). An empty tuple
# means "no approval dependency" (available as soon as its data exists).
_UNLOCK_RULES: dict[str, tuple[str, ...]] = {
    "background": (),      # front matter — always available
    "bm2": (),             # apical result — gated by data, not by another approval
    "genomics": ("knowledge_base",),  # genomics interpretation is grounded in the
                                       # knowledge graph (bmdx.duckdb → graph-grounded
                                       # references); gated on the KB being present
    "bmd_summary": (),     # auto-derived apical BMD summary — always available
    "methods": ("background", "results"),   # background approved OR ≥1 result approved
    "summary": ("background", "results"),   # background approved OR ≥1 result approved
}

# Unlock groups that are satisfied by an EXTERNAL resource (not the approved-set).
# Passed into derive_section_readiness as flags rather than read from section
# approvals. Today only the knowledge base (bmdx.duckdb).
_RESOURCE_GROUPS: frozenset[str] = frozenset({"knowledge_base"})


def _section_type_for_key(section_key: str) -> str:
    """Collapse an on-disk section_key to its dependency-rule TYPE.

    Bare singletons map to themselves; the prefixed instance families
    (`bm2_<slug>`, `genomics_<organ>_<sex>`) map to `bm2` / `genomics`.
    Mirrors the canonical vocabulary in session_routes._resolve_section_key.
    """
    if section_key in _UNLOCK_RULES:
        return section_key
    if section_key.startswith("bm2_"):
        return "bm2"
    if section_key.startswith("genomics_"):
        return "genomics"
    return section_key  # unknown → no rule → treated as always-enabled


def _group_satisfied(
    group: str,
    approved_keys: set[str],
    resources: dict[str, bool],
) -> bool:
    """Whether an unlock group is satisfied.

    Approval groups are satisfied by the approved-set; RESOURCE groups (e.g.
    knowledge_base) are satisfied by an external presence flag in `resources`.
    """
    if group == "background":
        return "background" in approved_keys
    if group == "results":
        return any(
            k.startswith("bm2_") or k.startswith("genomics_")
            for k in approved_keys
        )
    if group in _RESOURCE_GROUPS:
        return bool(resources.get(group))
    return False


def derive_section_readiness(
    section_states: dict[str, bool],
    resources: dict[str, bool] | None = None,
) -> dict[str, dict]:
    """Derive per-section readiness from the approved-state of every section.

    `section_states` maps on-disk section_key → its `approved` boolean (what
    `PoolStore.read_section_states` returns). `resources` carries external
    unlock signals that are NOT part of the approved-set — currently just
    `{"knowledge_base": bool}` (whether bmdx.duckdb is present), which gates the
    genomics-interpretation sections that ground their references in the graph.

    Readiness is a pure function of these two inputs + the declared
    `_UNLOCK_RULES`.

    Returns `{section_key: {"enabled": bool, "blocked_by": [group, ...],
    "approved": bool}}` for every singleton section plus every instance section
    present on disk. `blocked_by` lists the unlock groups (any one of which would
    enable the section); it is empty when the section is enabled.
    """
    resources = resources or {}
    approved_keys = {k for k, approved in section_states.items() if approved}

    # Universe of keys to report on: the fixed singletons + any instance
    # sections that exist on disk (approved or not).
    keys = set(_SINGLETON_KEYS) | set(section_states.keys())

    readiness: dict[str, dict] = {}
    for key in sorted(keys):
        groups = _UNLOCK_RULES.get(_section_type_for_key(key), ())
        if not groups:
            enabled = True
            blocked_by: list[str] = []
        else:
            enabled = any(
                _group_satisfied(g, approved_keys, resources) for g in groups
            )
            # OR semantics: when blocked, ANY of the groups would unblock it.
            blocked_by = [] if enabled else list(groups)
        readiness[key] = {
            "enabled": enabled,
            "blocked_by": blocked_by,
            "approved": key in approved_keys,
        }
    return readiness
