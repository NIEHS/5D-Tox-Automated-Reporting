"""
render_common.py — format-agnostic EXTRACT step shared by the HTML and LaTeX
renderers (ADR-0006).

The two renderers (html_generator.py, latex_generator.py) walk the same
canonical DocNode tree and, for most node types, make the *same decision* about
WHAT to render — they differ only in the markup they EMIT.  Historically that
shared decision logic was copy-pasted into both files, which let them drift
(the reason tests/unit/test_renderer_dispatch_parity.py exists).  ADR-0006
splits each handler into:

  * EXTRACT (here) — a pure function that inspects the node + report data and
    returns a small, markup-free description of what should be rendered;
  * EMIT (in each renderer) — turns that description into HTML or LaTeX,
    applying its own escaping and wrapping.

This module is the extract half.  It deliberately produces NO markup and knows
nothing about HTML or LaTeX — everything here is "which content, in which
order," never "what tags."  Step 2 of ADR-0006 migrates the three provably
identical handlers (front-matter, labeled-sections, narrative) onto it; later
steps move the table handlers.

A note on what stays in the emitters: the "rendered body came out empty, so
show a [Section pending] placeholder" decision is intentionally NOT made here.
Emptiness is format-dependent — e.g. a single empty-string paragraph renders as
"<p></p>" in HTML (non-empty) but "" in LaTeX (empty, → pending).  Preserving
that pre-existing per-format behavior means the pending fallback stays in each
emitter; this module only chooses the content SOURCE.
"""

from __future__ import annotations

# DocNode is the node SHAPE (document_node.py), imported directly rather than
# via document_tree to keep this leaf module free of the tree/template import
# chain — the renderers already depend on both, but nothing here needs the
# instantiated DOCUMENT_TREE, only the node type for hints.
from dataclasses import dataclass, field

from document_node import DocNode


# ---------------------------------------------------------------------------
# Type definitions — markup-free descriptions handed to the emitters
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FrontMatterPlan:
    """
    What a front-matter / narrative node should render, decided once and
    consumed by either renderer.

    Fields:
        level:         heading level (passed straight to the renderer's
                       _heading); 0 means "no heading."
        title:         heading text (raw, unescaped — the emitter escapes it).
        kind:          which body source won the precedence:
                         "labeled"    → render labeled_parts as a structured
                                        abstract (run-in bold labels);
                         "paragraphs" → render paragraphs as a flat prose list;
                         "none"       → no content source; the emitter's
                                        empty-body check will show "pending."
        labeled_parts: [(label, text)] for kind == "labeled"; label may be ""
                       (text is already stripped and guaranteed non-empty).
        paragraphs:    list of raw paragraph strings for kind == "paragraphs".
    """
    level: int
    title: str
    kind: str
    labeled_parts: list[tuple[str, str]] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Extractors — pure, markup-free
# ---------------------------------------------------------------------------

def labeled_section_parts(sections) -> list[tuple[str, str]]:
    """
    Normalise a structured-abstract "sections" list into [(label, text)],
    dropping anything that carries no text.

    This is the iterate-and-filter logic that both renderers' old
    _render_labeled_sections shared verbatim: skip non-dict entries, strip the
    text and skip it when empty (so a Methods abstract with no MethodsContext
    contributes nothing), strip the label (which may legitimately be empty for
    an unlabeled paragraph).  Only the per-part MARKUP differed between
    renderers, and that stays in each emitter.

    Args:
        sections: the raw list from content["sections"] (may be None, or
            contain junk — both are tolerated).

    Returns:
        A list of (label, text) tuples.  Both strings are stripped; text is
        guaranteed truthy; label may be "".  Empty list when nothing qualifies.
    """
    parts: list[tuple[str, str]] = []
    for sec in sections or []:
        if not isinstance(sec, dict):
            continue
        text = (sec.get("text") or "").strip()
        if not text:
            continue
        label = (sec.get("label") or "").strip()
        parts.append((label, text))
    return parts


def front_matter_plan(node: DocNode, data: dict) -> FrontMatterPlan:
    """
    Decide which body a front-matter / narrative node renders, format-agnostically.

    Reproduces the precedence both renderers' _render_front_matter shared:

      1. The content lives at data[node.data_key] and must be a dict.
      2. If it carries labeled sections with any non-empty text, that wins
         (the structured-abstract path: Background / Methods / Results / Summary).
      3. Otherwise fall back to the flat "paragraphs" list.
      4. If neither yields content, kind is "none" and the emitter shows a
         pending placeholder.

    Note step 2's "any non-empty text" gate matches the old behavior exactly:
    the previous code rendered labeled sections, and only if that produced an
    EMPTY string fell through to paragraphs.  Labeled-section emptiness depends
    solely on whether any section has text — a format-agnostic condition — so
    resolving it here (via labeled_section_parts) is faithful to both renderers.

    Args:
        node: the DocNode being rendered (uses .data_key, .level, .title).
        data: the full report data dict.

    Returns:
        A FrontMatterPlan describing the chosen content source.
    """
    content = data.get(node.data_key) if node.data_key else None
    if isinstance(content, dict):
        parts = labeled_section_parts(content.get("sections"))
        if parts:
            return FrontMatterPlan(node.level, node.title, "labeled", labeled_parts=parts)
        paragraphs = content.get("paragraphs", []) or []
        if paragraphs:
            return FrontMatterPlan(node.level, node.title, "paragraphs", paragraphs=paragraphs)
    return FrontMatterPlan(node.level, node.title, "none")


# ---------------------------------------------------------------------------
# Dispatch registry — the canonical set of renderable node types (ADR-0006 #3)
# ---------------------------------------------------------------------------
# Before ADR-0006 #3, each renderer kept its own _DISPATCH table and the two
# were forced to agree only by tests/unit/test_renderer_dispatch_parity.py —
# a guard bolted onto a problem the structure didn't prevent.  This registry IS
# that structure: one canonical list both renderers validate their dispatch
# against at IMPORT time, so a node type added to one renderer but not the other
# (the silent-fall-through-to-"[Section pending]" bug) becomes a loud failure on
# import, not a surprise on Overleaf.

# Every node_type the report tree can contain and that a renderer is expected to
# emit.  Adding a node type to the document tree means adding it here AND giving
# both renderers an emitter for it (or declaring a structural omission below).
RENDERABLE_NODE_TYPES: frozenset[str] = frozenset({
    "cover",
    "title-page",
    "front-matter",
    "narrative",
    "heading-only",
    "appendix",
    "tables-list",
    "toc",
    "narrative+tables",
    "table",
    "incidence-table",
    "bmd-summary",
    "genomics-section",
})

# Node types a renderer may legitimately NOT implement, with the structural
# reason.  The LaTeX renderer builds the title page with \maketitle (ADR-0003
# decision #6), so its cover / title-page tree nodes intentionally emit nothing;
# this is the single documented divergence between the two surfaces.
LATEX_OMITS: frozenset[str] = frozenset({"cover", "title-page"})


class RenderDispatchError(RuntimeError):
    """
    Raised at import time when a renderer's dispatch table does not match the
    canonical RENDERABLE_NODE_TYPES registry — either it's missing an emitter
    for a registered type, or it registers a type the registry doesn't know
    about (which means the registry is stale).  Either way the two output
    surfaces would silently disagree, so we fail loudly instead.
    """


def assert_dispatch_covers(
    dispatch, *, renderer: str, allow_omit: frozenset[str] = frozenset()
) -> None:
    """
    Verify a renderer's dispatch table exactly matches the registry.

    Called by each renderer immediately after it defines its `_DISPATCH`, so a
    coverage gap is an import-time RenderDispatchError rather than a silent
    "[Section pending]" placeholder discovered later on one surface only.

    Args:
        dispatch:   the renderer's node_type → handler mapping (any object whose
                    iteration yields the registered node_type keys — a dict).
        renderer:   human-readable renderer name for the error message
                    (e.g. "HTML", "LaTeX").
        allow_omit: node types this renderer is permitted to skip because it
                    handles them structurally elsewhere (LaTeX passes
                    LATEX_OMITS for cover/title-page).

    Raises:
        RenderDispatchError: if any registered type (minus allow_omit) has no
            emitter, or if the table registers a type outside the registry.
    """
    keys = set(dispatch)
    missing = RENDERABLE_NODE_TYPES - keys - allow_omit
    if missing:
        raise RenderDispatchError(
            f"{renderer} renderer is missing emitters for registered node "
            f"types: {sorted(missing)}. Add a handler, or — if this renderer "
            f"handles them structurally — pass them in allow_omit."
        )
    unknown = keys - RENDERABLE_NODE_TYPES
    if unknown:
        raise RenderDispatchError(
            f"{renderer} renderer registers node types absent from the "
            f"canonical RENDERABLE_NODE_TYPES registry: {sorted(unknown)}. "
            f"Add them to render_common.RENDERABLE_NODE_TYPES so the other "
            f"renderer is required to handle them too."
        )
