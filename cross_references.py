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

from document_model.document_node import DocNode
from document_model.document_tree import NUMBERED_TABLE_TYPES, find_node


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
# from compute_table_numbers.  The producer side (document_tree.
# NUMBERED_TABLE_TYPES) is the source of truth; we mirror it and assert equality
# so a type can never be numbered-but-unreferenceable (or vice versa) again.
_TABLE_TYPES = NUMBERED_TABLE_TYPES
assert _TABLE_TYPES == frozenset(
    {"sample-counts-table", "table", "incidence-table", "bmd-summary"}
)


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
# LaTeX label keys
# ---------------------------------------------------------------------------

# Characters that are special inside a LaTeX `\label{...}` / `\ref{...}` key.
# A node id carrying any of these would break the .tex when spliced raw into
# `\begin{niehstable}{<id>}` (which expands to `\label{tab:<id>}`).  We map each
# to a hyphen so the key stays a plain, ref-able token.
_LATEX_LABEL_UNSAFE = re.compile(r"[\\&%#$_{}~^]+")


def latex_label_key(node_id: str) -> str:
    r"""
    Sanitize a DocNode id for use as a LaTeX label/ref key.

    `niehstable` splices its first argument into `\label{tab:<id>}` and this
    module emits the matching `\ref{tab:<id>}`; both sides MUST agree, so both
    call this one function on the same id.  LaTeX-special characters
    (`\ & % # $ _ { } ~ ^`) are collapsed to hyphens — a key like
    `tab:foo_bar` would otherwise expand `_` to subscript math and break the
    label.  Current ids are plain `[a-z0-9-]` slugs, so this is the identity
    on every id in the tree today; it guards against a future template id with
    a special character (arch #2's index enforces id uniqueness, not charset).
    """
    return _LATEX_LABEL_UNSAFE.sub("-", node_id)


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
            # space so "Table" and the number never split across a line.  The id
            # goes through latex_label_key so this ref matches the sanitized key
            # the niehstable label site emits (latex_generator).
            return f"Table~\\ref{{tab:{latex_label_key(target_id)}}}"
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
