"""
narrative.section_template — the template representation for programmatic sections
(ADR-0014/0015 Phase 2; design in project_integrated_wizard_versioned_preview.md).

A programmatic section's prose is NOT frozen text — it is a TEMPLATE: an ordered
sequence of author WORDING (`Literal`) interleaved with live DATA references
(`Slot`). The template holds no data of its own, only references, so it can be
re-rendered against fresh data forever.

Why this shape (validated by tooling/spike_template_representation.py):

  * "refresh numbers, keep wording" stops being a merge problem. A data reprocess
    just re-renders the SAME template against a new binding; author wording (the
    Literals) is untouched by construction.
  * A wording EDIT replaces Literal text only — Slots stay live. So the seam
    between number and wording can never be destroyed, because the edit surface
    only ever exposes Literals.

Slots are TYPED, because "is a silent numeric refresh safe?" depends on the kind:

  * NUMERIC  — a magnitude (BMD, LOEL). A new value replaces the old and the
               surrounding wording still reads correctly. Silent refresh SAFE.
  * CATEGORICAL — a data-DERIVED WORD (direction=increased/decreased,
               trend=positive/negative). If a reprocess FLIPS it, the author's
               hand-written wording may now contradict the data (author wrote
               "a significant reduction"; data flips to increased). The slot value
               still refreshes, but the flip must be FLAGGED for wording review —
               even for a programmatic section. `categorical_flips()` detects this.

This module is pure and data-agnostic: it knows nothing about TableRow or NTP
conventions. Builders construct a Template + a `binding` dict (slot_key -> str)
projected from their data; rendering is the only thing that joins them.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class SlotKind(Enum):
    NUMERIC = "numeric"
    CATEGORICAL = "categorical"


@dataclass(frozen=True)
class Literal:
    """Author wording. The only segment an edit mutates."""
    text: str


@dataclass(frozen=True)
class Slot:
    """A live data reference, resolved against the binding at render time.
    `key` indexes the binding; `kind` governs refresh safety (see module docstring)."""
    key: str
    kind: SlotKind


Segment = Literal | Slot
Template = list[Segment]

# A binding is the data projection a builder computes for one render:
# {slot_key: already-formatted string}. The template never sees raw data.
Binding = dict[str, str]


def render(template: Template, binding: Binding) -> str:
    """Resolve every Slot against `binding`; concatenate with the Literals.

    A missing key renders as ``<key?>`` so a builder bug is visible in output
    rather than raising mid-report. Builders are expected to bind every slot.
    """
    parts: list[str] = []
    for seg in template:
        if isinstance(seg, Literal):
            parts.append(seg.text)
        else:
            parts.append(binding.get(seg.key, f"<{seg.key}?>"))
    return "".join(parts)


def edit_literal(template: Template, index: int, new_text: str) -> Template:
    """Return a NEW template with one Literal's text replaced. Slots untouched.

    This is the up-stream primitive behind "an edit is a personal template
    specific to that version" — it never mutates the input and can only target a
    Literal (targeting a Slot is a programming error the assert catches).
    """
    seg = template[index]
    if not isinstance(seg, Literal):
        raise TypeError(f"edit_literal targets a Literal; segment {index} is a Slot")
    new = list(template)
    new[index] = replace(seg, text=new_text)
    return new


def categorical_flips(
    template: Template, old: Binding, new: Binding
) -> list[tuple[str, str, str]]:
    """Categorical slots whose value CHANGED between two bindings.

    Returns (slot_key, old_value, new_value) per flipped CATEGORICAL slot; numeric
    deltas are ignored (they are silent-refresh-safe). A non-empty result is the
    Phase 3 signal that a programmatic section needs a wording-review flag even
    though its numbers refreshed cleanly. Each key reported once.
    """
    flips: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for seg in template:
        if not isinstance(seg, Slot) or seg.kind is not SlotKind.CATEGORICAL:
            continue
        if seg.key in seen:
            continue
        seen.add(seg.key)
        o, n = old.get(seg.key), new.get(seg.key)
        if o != n:
            flips.append((seg.key, o or "", n or ""))
    return flips
