r"""
cross_references.py — in-text cross-reference resolver (ADR-0004 amendment c).

In narrative text the author (LLM or human) writes a semantic reference token
that names a TARGET id, not a literal number:

    "...as shown in [[xref:bmd-summary]], the BMDLs were..."

At render time the resolver looks the target up in the document tree and emits
markup appropriate to the output surface:

    LaTeX  → "Table~\\ref{tab:bmd-summary}"     (resolves to the positional
                                                  number on the second pass)
    HTML   → '<a class="xref" href="#sec-bmd-summary">Table 8</a>'
    BITS   → '<xref ref-type="table" rid="bmd-summary">Table 8</xref>' (future)

Why this exists
---------------
Our table/figure numbering is POSITIONAL (auto-assigned by compute_table_numbers
walking the tree).  Any narrative that hardcodes "Table 3" therefore breaks
silently the moment the tree is reordered or a table is added.  Authoring
references as semantic tokens — and letting the renderer resolve the number —
removes that fragility.  It also gives us the BITS-aligned semantic model
NOW, so a future BITS export is additive (the same token maps to <xref rid>).

Token format
------------
`[[xref:<id>]]` — the brackets are NOT LaTeX-special and NOT HTML-special, so
the token passes through escape unchanged; the resolver runs AFTER escaping
and inserts markup that is therefore not re-escaped.  The id pattern accepts
word characters plus -, :, . — covering plain node ids (bmd-summary,
appendix-a) and composite content-item ids (gene-sets::liver-male-table).

A token whose id does NOT match any node is left as a visible broken-ref
marker (`[[xref:??id]]`) so the author notices, rather than silently dropping
the reference.

Scope today
-----------
TABLE references (table / incidence-table / bmd-summary node types) are
resolved end-to-end — `niehstable` already emits `\label{tab:<id>}`, so
`\ref{tab:<id>}` works in LaTeX, and `node.table_number` gives the HTML number.
Section / figure references are not yet wired (sections lack
`\label{sec:<id>}`; figures lack positional numbers — ADR-0004 amendment e);
they fall through to the broken-ref marker until those land.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

import re
from typing import Callable

from document_node import DocNode
from document_tree import find_node


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Token pattern.  Brackets are not LaTeX or HTML special, so the token survives
# both escapers; the id permits word chars plus -, :, . so we cover plain node
# ids (bmd-summary, appendix-a) and composite content-item ids
# (gene-sets::liver-male-table).  The `??` marker we emit for an unknown id
# contains `?`, which is NOT in this character class — so a broken-ref marker
# cannot re-match the pattern (no infinite loop, no double-substitution).
_XREF_RE = re.compile(r"\[\[xref:([\w\-:.]+)\]\]")

# Node types treated as tables for cross-reference purposes — they go through
# niehstable, which emits \label{tab:<id>}, and they receive a table_number
# from compute_table_numbers.
_TABLE_TYPES = frozenset({"table", "incidence-table", "bmd-summary"})


# ---------------------------------------------------------------------------
# Helper (private)
# ---------------------------------------------------------------------------

def _resolve(text: str, render: Callable[[DocNode | None, str], str]) -> str:
    """
    Replace every `[[xref:id]]` token in `text` with whatever the renderer's
    `render(target_node_or_None, target_id)` returns.

    Fast path: if the token sentinel isn't even a substring, return as-is so
    the vast majority of (untokenized) strings cost a single membership check.
    """
    if not text or "[[xref:" not in text:
        return text
    return _XREF_RE.sub(lambda m: render(find_node(m.group(1)), m.group(1)), text)


def _broken(target_id: str) -> str:
    """
    The visible broken-ref marker emitted for an unknown / unsupported target.
    `??` is not in the id pattern, so this marker cannot be re-matched.
    """
    return f"[[xref:??{target_id}]]"


# ---------------------------------------------------------------------------
# Public API — one resolver per render surface
# ---------------------------------------------------------------------------

def resolve_xrefs_latex(text: str) -> str:
    r"""
    Resolve `[[xref:id]]` tokens to LaTeX cross-reference markup.  Run AFTER
    `_escape_latex`'s character escaping, so the inserted `\ref{}` survives.
    """
    def render(node: DocNode | None, target_id: str) -> str:
        if node is None:
            return _broken(target_id)
        if node.node_type in _TABLE_TYPES:
            # niehstable emits \label{tab:<id>}; \ref{tab:<id>} resolves to the
            # positional number on the second LaTeX pass.  ~ is a non-breaking
            # space so "Table" and the number never split across a line.
            return f"Table~\\ref{{tab:{target_id}}}"
        # Sections / figures: targets exist but the LaTeX side lacks the
        # corresponding \label{...} hook yet (deferred — see module docstring).
        return _broken(target_id)
    return _resolve(text, render)


def resolve_xrefs_html(text: str) -> str:
    """
    Resolve `[[xref:id]]` tokens to HTML cross-reference markup.  Run AFTER
    `_esc`'s HTML escaping, so the inserted `<a>` survives.
    """
    def render(node: DocNode | None, target_id: str) -> str:
        if node is None:
            return _broken(target_id)
        if node.node_type in _TABLE_TYPES:
            num = node.table_number if node.table_number is not None else "?"
            return f'<a class="xref" href="#sec-{target_id}">Table {num}</a>'
        return _broken(target_id)
    return _resolve(text, render)
