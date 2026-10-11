"""
SPIKE (Phase 2 de-risk, 2026-09-01) — programmatic section as an editable template.

NOT production code. A throwaway proof for ONE question:

    Can a programmatic section be represented as (author wording + live data
    slots) such that
      (1) rendering interleaves wording with numbers pulled from TableRow,
      (2) a WORDING edit produces a NEW personal template with the slots STILL
          LIVE (not frozen prose), and
      (3) a data REPROCESS re-renders that personal template against new numbers
          — wording preserved, numbers refreshed — with NO merge,
    and crucially: WHERE does "silently refresh the numbers" stop being safe?

Grounded in the real sentence from
narrative/unified_narrative.py:_build_body_weight_paragraphs, which today bakes
data straight into f-strings:

    f"Terminal body weight was significantly {increased/decreased} in {sex} rats"
    f" at >={loel} {unit} with a {trend} trend (Table 2). The BMD and BMDL were"
    f" {bmd} and {bmdl} {unit}, respectively."

The numbers (bmd, bmdl, loel) and the data-DERIVED words (direction, trend) are
slots; everything else is author wording. Run:  uv run tooling/spike_template_representation.py
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


# ---------------------------------------------------------------------------
# The template model — the thing the spike is testing.
# ---------------------------------------------------------------------------

class SlotKind(Enum):
    """Why the distinction matters for 'is a silent refresh safe?':

    NUMERIC      — a magnitude (bmd, loel). A new value just replaces the old;
                   the author's surrounding wording still reads correctly.
                   Silent refresh is SAFE.
    CATEGORICAL  — a data-DERIVED word (direction=increased/decreased,
                   trend=positive/negative). If reprocess FLIPS it, the author's
                   wording may now contradict the data ("this concerning
                   increase" under a decreased value). Silent refresh of the slot
                   is fine, but a flip must be FLAGGED for wording review.
    """
    NUMERIC = "numeric"
    CATEGORICAL = "categorical"


@dataclass(frozen=True)
class Literal:
    """Author wording. The ONLY thing an edit changes."""
    text: str


@dataclass(frozen=True)
class Slot:
    """A live reference resolved against the data binding at render time.
    Survives edits untouched — this is what keeps number and wording separable."""
    key: str
    kind: SlotKind


# A template is just an ordered list of segments. Data-agnostic: it holds NO
# numbers, only references to them. This is what makes it re-renderable forever.
Segment = Literal | Slot
Template = list[Segment]


def render(template: Template, binding: dict[str, str]) -> str:
    """Resolve every slot against the binding; concatenate. Pure projection."""
    out: list[str] = []
    for seg in template:
        if isinstance(seg, Literal):
            out.append(seg.text)
        else:
            out.append(binding.get(seg.key, f"<{seg.key}?>"))
    return "".join(out)


# ---------------------------------------------------------------------------
# Binding: TableRow -> {slot_key: rendered value}. Mirrors what
# unified_narrative derives inline today; here it is a separate, explicit step
# so the template never sees a TableRow — only its projection.
# ---------------------------------------------------------------------------

@dataclass
class FakeRow:
    """Stand-in for bmdx_pipe.TableRow — only the fields the sentence uses."""
    direction: str      # "increase" | "decrease"
    loel: float
    bmd_str: str
    bmdl_str: str
    responsive: bool = True


def bind(row: FakeRow, sex: str, unit: str) -> dict[str, str]:
    return {
        "direction": "increased" if row.direction == "increase" else "decreased",
        "trend": "positive" if row.direction == "increase" else "negative",
        "sex": sex.lower(),
        "loel": f"{row.loel:g}",
        "unit": unit,
        "bmd": row.bmd_str,
        "bmdl": row.bmdl_str,
    }


# ---------------------------------------------------------------------------
# The default (base) template for the body-weight sentence.
# ---------------------------------------------------------------------------

def base_body_weight_template() -> Template:
    return [
        Literal("Terminal body weight was significantly "),
        Slot("direction", SlotKind.CATEGORICAL),
        Literal(" in "),
        Slot("sex", SlotKind.CATEGORICAL),
        Literal(" rats at ≥"),
        Slot("loel", SlotKind.NUMERIC),
        Literal(" "),
        Slot("unit", SlotKind.NUMERIC),
        Literal(" with a "),
        Slot("trend", SlotKind.CATEGORICAL),
        Literal(" trend (Table 2). The BMD and BMDL were "),
        Slot("bmd", SlotKind.NUMERIC),
        Literal(" and "),
        Slot("bmdl", SlotKind.NUMERIC),
        Literal(" "),
        Slot("unit", SlotKind.NUMERIC),
        Literal(", respectively."),
    ]


# ---------------------------------------------------------------------------
# The two acts from the design.
# ---------------------------------------------------------------------------

def edit_wording(template: Template, index: int, new_text: str) -> Template:
    """A wording edit = replace ONE literal's text, slots untouched. Produces a
    NEW personal template (input never mutated) — 'a personal template specific
    to that version of the section.' The edit surface only ever exposes literals;
    slots are never editable text, so the seam can't be destroyed."""
    seg = template[index]
    assert isinstance(seg, Literal), "edit targets a Literal, never a Slot"
    new = list(template)
    new[index] = replace(seg, text=new_text)
    return new


def reprocess_diff(
    template: Template, old: dict[str, str], new: dict[str, str]
) -> list[str]:
    """What changed between two bindings, classified by slot kind. NUMERIC changes
    are silent-safe; a CATEGORICAL flip is the boundary that needs a wording-review
    flag. Returns human-readable flags (empty = safe silent refresh)."""
    flags: list[str] = []
    seen: set[str] = set()
    for seg in template:
        if not isinstance(seg, Slot) or seg.key in seen:
            continue
        seen.add(seg.key)
        o, n = old.get(seg.key), new.get(seg.key)
        if o != n and seg.kind is SlotKind.CATEGORICAL:
            flags.append(f"CATEGORICAL slot {seg.key!r} flipped {o!r} -> {n!r} "
                         f"(author wording may now contradict the data)")
    return flags


# ---------------------------------------------------------------------------
# The demonstration / self-check.
# ---------------------------------------------------------------------------

def main() -> None:
    unit = "mg/kg/day"
    row_v1 = FakeRow(direction="decrease", loel=50, bmd_str="41.2", bmdl_str="22.8")

    tpl = base_body_weight_template()
    b1 = bind(row_v1, sex="Male", unit=unit)

    print("=" * 78)
    print("A. Default template, rendered against data v1")
    default_render = render(tpl, b1)
    print("  ", default_render)

    print("=" * 78)
    print("B. Writer edits WORDING (not numbers). New personal template; slots live.")
    # Change only the opening literal's phrasing.
    personal = edit_wording(tpl, 0, "A significant reduction in terminal body weight was seen (")
    # And close the parenthetical by editing the trailing literal wording.
    personal = edit_wording(personal, len(personal) - 1, ").")
    edited_render = render(personal, b1)
    print("  ", edited_render)
    assert "41.2" in edited_render and "22.8" in edited_render, "numbers survived the edit"
    assert "A significant reduction" in edited_render, "author wording applied"
    # The slots are STILL slots — prove it by re-rendering against different data.

    print("=" * 78)
    print("C. Data REPROCESS (v2: bmd/bmdl/loel change, direction SAME).")
    print("   Personal template re-renders: wording kept, numbers refreshed, no merge.")
    row_v2 = FakeRow(direction="decrease", loel=25, bmd_str="18.7", bmdl_str="9.4")
    b2 = bind(row_v2, sex="Male", unit=unit)
    reprocessed = render(personal, b2)
    print("  ", reprocessed)
    assert "A significant reduction" in reprocessed, "author wording preserved across reprocess"
    assert "18.7" in reprocessed and "9.4" in reprocessed and "25" in reprocessed, "numbers refreshed"
    assert "41.2" not in reprocessed, "stale numbers gone"
    flags_c = reprocess_diff(personal, b1, b2)
    print("   flags:", flags_c or "none — silent refresh SAFE (only NUMERIC changed)")
    assert not flags_c, "numeric-only reprocess needs no flag"

    print("=" * 78)
    print("D. THE BOUNDARY — reprocess v3 FLIPS direction decrease -> increase.")
    print("   Numbers still refresh, but a data-derived WORD flipped under the wording.")
    row_v3 = FakeRow(direction="increase", loel=25, bmd_str="18.7", bmdl_str="9.4")
    b3 = bind(row_v3, sex="Male", unit=unit)
    flipped = render(personal, b3)
    print("  ", flipped)
    flags_d = reprocess_diff(personal, b1, b3)
    for f in flags_d:
        print("   FLAG:", f)
    assert flags_d, "a categorical flip MUST be flagged"
    # Note the author literal 'A significant reduction' now contradicts trend=positive.
    print("   ^ author literal 'reduction' now contradicts a positive trend — "
          "this is why even a PROGRAMMATIC section can need a wording-review flag.")

    print("=" * 78)
    print("RESULT: template/edit/reprocess mechanism holds. The seam between")
    print("number and wording is never lost because editing only ever touches")
    print("Literals; Slots stay live. The one real risk is a CATEGORICAL slot")
    print("flip, which is detectable (Scenario D) — so 'numbers auto-update' is")
    print("safe, but 'data-derived category flipped' should raise a wording flag")
    print("even for programmatic sections.")


if __name__ == "__main__":
    main()
