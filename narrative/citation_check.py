"""
narrative/citation_check.py — the one place that decides whether a citation
the model wrote actually points at a source we gave it.

Why this exists: two report narratives are literature-grounded. The Background
prompt carries a numbered inventory of regulatory sources and papers and asks
for inline [N] citations; the genomics interpretation carries a [Pn] catalogue
of knowledge-graph papers and asks for [Pn] tokens. In both cases the model can
write a citation that does not exist in what it was given — a renumbered,
garbled or invented reference. Before 2026-09-21 the Background path accepted
any reference line the model wrote, and the genomics path silently deleted any
[Pn] token that missed the pool. Either way the author saw nothing.

This module provides the shared, pure primitives both paths (and any future
chat-style interpretation) use to turn that into a visible, structured record:

  * `sentence_containing(text, needle)` — the sentence a citation sits in, so a
    warning can show the author the claim that lost (or invented) its support.
  * `find_unresolved_tokens(...)` — every citation token in a paragraph list
    that is not in the caller's set of valid tokens, as issue dicts.

An "issue" is a plain dict so it can be persisted as JSON and shown in the UI:
    {"where": "<narrative or stratum>", "token": "[P9]" | "[12]",
     "issue": "unresolved_citation" | "unresolved_reference_line"
              | "reference_line_mismatch",
     "sentence": "<the sentence or reference line>"}

No I/O, no LLM, no first-party imports beyond the standard library — so it is
trivially testable and safe to import from anywhere.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# Sentence boundary: a terminator followed by whitespace. Good enough for
# scientific prose; a wrong split only shortens the context shown to the user.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def sentence_containing(text: str, needle: str) -> str:
    """Return the first sentence of `text` that contains `needle`, or the whole
    text (trimmed) when no sentence split contains it. Never raises."""
    if not text:
        return ""
    for sent in _SENTENCE_SPLIT.split(text):
        if needle in sent:
            return sent.strip()
    return text.strip()


def find_unresolved_tokens(
    paragraphs: Iterable[str],
    valid_tokens: set[str],
    bracket_re: re.Pattern,
    token_re: re.Pattern,
    where: str,
) -> list[dict]:
    """List every citation token in `paragraphs` that is NOT in `valid_tokens`.

    Args:
        paragraphs:   the prose to scan (non-str items are ignored).
        valid_tokens: the tokens the model was allowed to cite (e.g. {"P1","P2"}
                      for a genomics stratum, {"1","2",...} for Background).
        bracket_re:   matches one citation bracket (possibly carrying several
                      tokens, e.g. "[P1, P3]").
        token_re:     pulls the individual tokens out of a bracket match.
        where:        label for the issue's "where" field.

    Returns one issue dict per (token, sentence) occurrence, in document order,
    de-duplicated on (token, sentence). Empty when everything resolves.
    """
    issues: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for para in paragraphs:
        if not isinstance(para, str):
            continue
        for bracket in bracket_re.finditer(para):
            for tok in token_re.findall(bracket.group(0)):
                if tok in valid_tokens:
                    continue
                sentence = sentence_containing(para, bracket.group(0))
                key = (tok, sentence)
                if key in seen:
                    continue
                seen.add(key)
                issues.append({
                    "where": where,
                    "token": f"[{tok}]",
                    "issue": "unresolved_citation",
                    "sentence": sentence,
                })
    return issues


def summarize_issues(issues: list[dict], limit: int = 3) -> str:
    """One human-readable line for logs/UI: count + the first few tokens."""
    if not issues:
        return ""
    toks = []
    for it in issues:
        t = f"{it.get('where', '?')} {it.get('token', '?')}"
        if t not in toks:
            toks.append(t)
    shown = ", ".join(toks[:limit])
    more = f" (+{len(toks) - limit} more)" if len(toks) > limit else ""
    return f"{len(issues)} unresolved citation(s): {shown}{more}"
