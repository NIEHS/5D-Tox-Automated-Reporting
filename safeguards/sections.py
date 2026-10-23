"""
safeguards.sections — C2: content a person owns is never overwritten by a
machine, and a person's act that replaces or reopens it says why.

A section a person owns (they approved it, it holds the PROTECTED fact, a
person's text came back from outside the application: workflow.ownership.
is_owned) is protected by ``ownership_policy``, the write policy the section
write gate (workflow.section_writes.write_section) asks once a write would
change its text:

  * a machine's write over it is HELD (recorded, not applied) — or, for an
    apical result section whose printed content has already changed, written
    with its approval knocked down for re-review (``on_owned=REVIEW``, C2 D2/A1);
  * a person's write over content that is locked (approved, edited by a person,
    ingested) is refused (``section_owned``) unless forced;
  * a forced write needs a reason (``reason_required``), kept in the history.

The section acts' own preconditions are here too: reopening, restoring or
discarding needs a reason; an approved section is released before it is
discarded. The history itself (archive before every write, one event per
act) is the core's and holds for every caller.
"""

from __future__ import annotations

from workflow.ownership import is_owned
from workflow.section_writes import (
    REVIEW, SectionRefusal, WriteRequest, hold, is_locked, knock_down,
)


def owned(key: str, act: str) -> SectionRefusal:
    return SectionRefusal(
        "section_owned",
        f"'{key}' is approved or protected; {act} would replace its text. "
        "Release it first, with a reason.", 409, key=key, act=act)


def reason_required(key: str, verb: str) -> SectionRefusal:
    return SectionRefusal("reason_required", f"A reason is required to {verb} '{key}'", 400,
                          key=key, act=verb)


def require_reason(reason, key: str, verb: str) -> str:
    """The reason, stripped; a refusal when it is empty (C2 D3)."""
    text = reason.strip() if isinstance(reason, str) else ""
    if not text:
        raise reason_required(key, verb)
    return text


def ownership_policy(req: WriteRequest) -> dict | None:
    """The C2 write policy (rules 4–6 of workflow.section_writes): None lets
    the write through; a held or knocked-down outcome stops it; a refusal is
    raised."""
    if req.prior is None or not is_owned(req.prior):
        return None
    if req.force:
        req.reason = require_reason(req.reason, req.key, req.act)      # rule 6
        return None
    if req.actor == "system":
        return knock_down(req) if req.on_owned == REVIEW else hold(req)  # rule 4
    # Rule 5. A released section (only PROTECTED stands: C2 D1) is replaced by
    # a person's explicit act — that is what releasing it was for; Process
    # still never replaces it.
    if is_locked(req.prior):
        raise owned(req.key, req.act)
    return None
