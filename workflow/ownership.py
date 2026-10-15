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

# The on-disk key holding the serialized ASSERTED content facts (final /
# protected / …). APPROVED is NOT stored here — it is derived from the `approved`
# bool (data-readiness, widely read elsewhere), so the two representations never
# disagree. See store_content_facts.
_FACTS_KEY = "facts"

# The facts that may be serialized to `_FACTS_KEY` — the narrative maturity/lock
# facts a human asserts. APPROVED is derived (excluded); PUBLISHED is report-grain
# (not a node fact). Unknown strings on disk are ignored on read (forward-compat).
_STORABLE_FACTS = frozenset({Fact.FINAL, Fact.PROTECTED, Fact.WORKING_DRAFT, Fact.FIRST_DRAFT})


def section_facts(section: "dict | None") -> "frozenset[Fact]":
    """Map a section JSON into its Fact set. Pure.

    Two on-disk representations, unioned:
      approved: bool      — the human blessed this content -> Fact.APPROVED
                            (data-readiness; the source of truth for the lock).
      facts: list[str]    — the ASSERTED content facts (final / protected / …)
                            written by store_content_facts. Deserialized here;
                            unknown / non-storable strings are ignored so an older
                            or newer on-disk shape never raises.
      approved_at: str    — timestamp (not a fact).
      stale: bool         — currency signal, handled by is_section_stale (kind #6,
                            NOT a label) — never folded into the fact set.

    A missing/empty section carries no facts. Back-compat: a section with only the
    `approved` bool (no `facts` list) yields exactly {APPROVED}, identical to the
    pre-facts-on-disk behavior.
    """
    if not isinstance(section, dict):
        return frozenset()
    facts: set[Fact] = set()
    if section.get("approved"):
        facts.add(Fact.APPROVED)
    stored = section.get(_FACTS_KEY)
    if isinstance(stored, list):
        by_value = {f.value: f for f in _STORABLE_FACTS}
        for raw in stored:
            fact = by_value.get(raw)
            if fact is not None:
                facts.add(fact)
    return frozenset(facts)


def store_content_facts(section: dict, facts: "frozenset[Fact] | set[Fact]") -> None:
    """Serialize the ASSERTED content facts of `facts` onto the section dict,
    IN PLACE, under `_FACTS_KEY`. Pure over the dict (no I/O — the caller saves).

    Only _STORABLE_FACTS are written (APPROVED stays the `approved` bool; PUBLISHED
    is report-grain). Deterministic order (by value) so re-saving an unchanged fact
    set is byte-stable. An empty result removes the key entirely, so a section with
    no maturity facts is byte-identical to a pre-facts-on-disk section.
    """
    storable = sorted(
        (f.value for f in facts if f in _STORABLE_FACTS)
    )
    if storable:
        section[_FACTS_KEY] = storable
    else:
        section.pop(_FACTS_KEY, None)


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


# The `source` a section carries when a person's text came back from outside
# the application (Word, Overleaf; C11). Reserved: nothing writes it yet.
INGESTED_SOURCE = "ingested"


def is_owned(section: "dict | None", *, report_published: bool = False) -> bool:
    """THE ownership predicate (C2 §2): a machine may not replace this section's
    text. One definition, so "protected" means one thing everywhere — the
    machine guard (may_machine_write), the render mark (protection_level) and
    the read model's `machine_may_write` all ask this.

    Owned when any of these holds:
      * a person approved it (`approved`);
      * a person edited it (`user_edited`), or its text came back from outside
        the application (`source == "ingested"`, C11);
      * it holds a content-guarding fact (FINAL or PROTECTED). A released
        section keeps PROTECTED (ADR-0015 §5; C2 D1), so it stays owned: only
        a person's explicit act (regenerate, use run, restore) replaces it;
      * the report is published (the ADR-0015 floor; no act sets it yet).
    """
    if report_published:
        return True
    if not isinstance(section, dict):
        return False
    if is_user_owned(section) or section.get("source") == INGESTED_SOURCE:
        return True
    return blocks_machine_regen(section_facts(section), user_edited=False)


# The keys of a section file that are its STATE, not its content (C2 §2):
# accepting, releasing, staling or numbering a section changes these and never
# what it says. The write gate compares content with them removed
# (content_hash), which is how "nothing changed" is decided.
STATE_KEYS: frozenset[str] = frozenset({
    "approved", "approved_at", "facts", "stale", "regenerated", "wording_review",
    "review", "revised", "version", "saved_at",
})


def section_content(section: "dict | None") -> dict:
    """The section's content: the dict without its STATE_KEYS."""
    if not isinstance(section, dict):
        return {}
    return {k: v for k, v in section.items() if k not in STATE_KEYS}


def content_hash(section: "dict | None") -> str:
    """``sha256:<hex>`` of the section's content (STATE_KEYS removed), as
    canonical JSON (sorted keys, no whitespace). Equal hashes = same text."""
    import hashlib
    import json

    canonical = json.dumps(section_content(section), sort_keys=True,
                           separators=(",", ":"), ensure_ascii=False, default=str)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# The predicate callers ask: may a machine overwrite this section?
# ---------------------------------------------------------------------------

def may_machine_write(section: "dict | None", *, force: bool = False) -> bool:
    """May an LLM / regeneration write over this section's content?

    The single machine-guard predicate that replaces the scattered checks (the
    genomics `force`-flag reasoning, the 'return the store, full stop' comment,
    the per-surface override presence test):

      * `force=True` is the deliberate, user-triggered escape hatch (the
        Regenerate action) — it always permits the write (the human asked for it).
      * otherwise refuse when the content is owned (is_owned: approved, edited,
        ingested, FINAL or PROTECTED) — regardless of staleness (a stale-but-owned
        section must still not be clobbered; the user re-blesses it, the machine
        doesn't).

    Returns True = safe to (re)generate; False = refuse.
    """
    return force or not is_owned(section)


# ---------------------------------------------------------------------------
# The render wiring: {node_id -> GuardLevel} for step 5's data["protection"].
# ---------------------------------------------------------------------------

def protection_level(section: "dict | None", *, report_published: bool = False) -> GuardLevel:
    """The visual protection level for one section — MACHINE-PROTECTED semantics.

    Decided 2026-08-16: the rendered mark shows what the SYSTEM won't silently
    overwrite (the editor's original driver — "show what is protected content"),
    NOT pure human-facing maturity. So it lights exactly when is_owned does
    (C2: `protection_level >= GUARDED` ⇔ `not may_machine_write`, invariant I7;
    a released section holding PROTECTED is marked). The report-grain
    `published` floor still applies (louder mark).

    OPEN when the section is neither owned nor in a published report → no mark.
    """
    if report_published:
        return GuardLevel.PUBLISHED
    return GuardLevel.GUARDED if is_owned(section) else GuardLevel.OPEN


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
