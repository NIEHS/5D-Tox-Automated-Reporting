"""
content_item.py — an addressable content item WITHIN a document component
(ADR-0003 Part B).

A component (a `DocNode`) may own an ordered list of `ContentItem`s — a heading's
body decomposed into individually addressable text / table / chart / image
blocks. Each item has a stable id that is unique *within its component*, so its
full address is the composite ``"<component-id>::<item-id>"`` (the same key the
orientation overlay uses — see
`render_capabilities.content_item_landscape_requested`).

Two authoring modes converge on the SAME shape (ADR-0003 Part B, staged):
  * TEMPLATE-AUTHORED (static) — declared in the YAML template on a node; carries
    its own content inline (`text`) or a pointer to pipeline data (`data_key`).
  * RENDER-TIME-POPULATED (data-derived) — e.g. the genomics section's per-organ
    items, computed at marshal time from `data["genomics_sections"]`. These are
    NEVER written onto the process-global `DOCUMENT_TREE`; they are produced by a
    resolver at the emitter boundary (`render_common.resolve_content_items`).

This module is a LEAF: like `DocNode`, it imports nothing from the render
pipeline or the web layer, so it can be shared by the document model and the
renderers without a cycle.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ContentItem:
    """One addressable content block inside a component.

    Fields:
      id          — item id, unique WITHIN the component (NOT globally). The full
                    address is "<component-id>::<id>".
      kind        — a CONTENT_KINDS member: "text" | "table" | "chart" | "image".
      part        — optional emitter dispatch discriminator (e.g. "narrative",
                    "table", "descriptions", "chart"); defaults to `kind` when
                    unset.
      orientable  — may this item flip landscape on its own?
      breakable   — may a page break attach to this item on its own? (the break
                    stack that consumes this is ADR-0003 Part B stage 6–7, a
                    later pass; the flag is declared now, harmless until then.)
      orientation — authored default orientation ("portrait" | "landscape" | None).
      break_before / break_after — authored default page breaks (bool).
      text        — inline authored content (a str, or a dual-source
                    {"latex": ..., "html": ...} dict). MUTUALLY EXCLUSIVE with
                    data_key.
      data_key    — a key into the report `data` dict where this item's payload
                    (a table/chart) lives. MUTUALLY EXCLUSIVE with text.
      caption     — optional caption for a table/figure item.
    """

    id: str
    kind: str
    part: str | None = None
    orientable: bool = False
    breakable: bool = False
    orientation: str | None = None
    break_before: bool = False
    break_after: bool = False
    text: "str | dict | None" = None
    data_key: str | None = None
    caption: str | None = None

    @property
    def dispatch_part(self) -> str:
        """The discriminator a renderer switches on — `part` if set, else `kind`."""
        return self.part or self.kind
