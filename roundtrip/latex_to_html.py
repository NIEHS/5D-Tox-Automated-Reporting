"""
latex_to_html.py — conservative LaTeX → HTML for round-trip overrides (ADR-0005).

When a human edits a report region in Overleaf, the reconciler stores the edited
LaTeX (`latex_region`).  The on-screen preview can't emit raw LaTeX, so to show
the edit faithfully (divergence #2, Phase B) we translate that region to HTML
once, at reconcile time, and store it as `html_region`.

This translator is DELIBERATELY CONSERVATIVE.  It understands only the prose
vocabulary the generator itself emits into editable regions — bold/italic
run-ins, the escaped LaTeX specials, paragraph breaks — and returns ``None`` for
ANYTHING it does not recognize (tables, `\\includegraphics`, `\\ref`, `\\url`,
math, unknown macros, malformed braces).  ``None`` is not a failure: the preview
falls back to the Phase A "edited in Overleaf — may be stale" marker, which is
honest.  A best-effort partial translation would be worse — it could render
broken or misleading HTML that looks authoritative.

Supported, as the inverse of latex_generator._escape_latex + its run-in markup:
  \\textbf{...} -> <strong>...</strong>   \\emph{...} -> <em>...</em>
  \\noindent    -> (dropped)
  \\&  \\%  \\$  \\#  \\_  \\{  \\}        -> the literal character (HTML-escaped)
  \\textbackslash{}  \\textasciitilde{}  \\textasciicircum{}  -> \\  ~  ^
  blank line    -> paragraph break (<p>...</p> per paragraph)

Anything else -> None.
"""

from __future__ import annotations

import re

# Word-commands that take a single braced argument rendered as an inline tag.
_TAG_BY_CMD = {"textbf": "strong", "emph": "em"}

# Word-commands that take an (optional) empty-brace suffix and stand for one
# literal character.
_LITERAL_BY_CMD = {
    "textbackslash": "\\",
    "textasciitilde": "~",
    "textasciicircum": "^",
}

# Backslash-escaped single specials -> the literal character they denote.
_ESCAPED_SPECIAL = set("&%$#_{}")


def latex_to_html(tex: str) -> "str | None":
    """
    Translate an edited LaTeX region to HTML, or return None if any part of it
    falls outside the supported prose vocabulary (caller falls back to a marker).
    """
    if not tex or not tex.strip():
        return None
    paragraphs: list[str] = []
    for para in re.split(r"\n\s*\n", tex.strip()):
        inner = _convert_inline(para)
        if inner is None:
            return None
        inner = inner.strip()
        if inner:
            paragraphs.append(f"<p>{inner}</p>")
    return "\n".join(paragraphs) if paragraphs else None


def _convert_inline(s: str) -> "str | None":
    """Convert one paragraph's inline LaTeX to HTML, or None if unsupported."""
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            nxt = s[i + 1] if i + 1 < n else ""
            if nxt in _ESCAPED_SPECIAL:
                out.append(_esc_char(nxt))
                i += 2
                continue
            m = re.match(r"\\([a-zA-Z]+)", s[i:])
            if not m:
                return None  # a lone backslash or unknown escape
            cmd = m.group(1)
            i += 1 + len(cmd)
            if cmd in _LITERAL_BY_CMD:
                i = _skip_empty_braces(s, i)
                out.append(_esc_char(_LITERAL_BY_CMD[cmd]))
            elif cmd == "noindent":
                pass  # structural hint with no HTML equivalent — drop
            elif cmd in _TAG_BY_CMD:
                if i >= n or s[i] != "{":
                    return None  # expected a braced argument
                arg, i = _read_braced(s, i)
                if arg is None:
                    return None  # unbalanced braces
                inner = _convert_inline(arg)
                if inner is None:
                    return None
                tag = _TAG_BY_CMD[cmd]
                out.append(f"<{tag}>{inner}</{tag}>")
            else:
                return None  # unknown command -> degrade to marker
        elif c in "{}":
            i += 1  # bare grouping brace — drop, keep the contents
        elif c == "&":
            return None  # unescaped alignment char — not prose we can render
        elif c in "$#":
            return None  # math / macro-param — unsupported
        elif c == "%":
            return None  # comment — unsupported (escaped \% handled above)
        elif c in "<>":
            out.append(_esc_char(c))
            i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _esc_char(c: str) -> str:
    """HTML-escape a single literal character."""
    return {"&": "&amp;", "<": "&lt;", ">": "&gt;"}.get(c, c)


def _skip_empty_braces(s: str, i: int) -> int:
    """Advance past a `{}` suffix (e.g. after \\textbackslash) if present."""
    if i + 1 < len(s) and s[i] == "{" and s[i + 1] == "}":
        return i + 2
    return i


def _read_braced(s: str, i: int) -> "tuple[str | None, int]":
    """
    Read a balanced {...} group starting at s[i] == '{'.

    Escaped braces (\\{ \\}) are skipped so they don't affect nesting depth and
    survive into the returned argument for the recursive convert pass.  Returns
    (inner, index-after-closing-brace), or (None, i) when unbalanced.
    """
    depth, j = 0, i
    while j < len(s):
        c = s[j]
        if c == "\\" and j + 1 < len(s):
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
        j += 1
    return None, i
