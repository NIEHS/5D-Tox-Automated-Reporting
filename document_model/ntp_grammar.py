"""
ntp_grammar.py — the NTP report grammar (vocab/ntp-bits-grammar.yaml): the NTP
Word template's structural styles and the BITS construct each becomes.

The published reports of every generation are written in this one vocabulary
(ADR-0029 §7); a document definition draws its parts from it, and its packaging
decides which element a heading becomes.  This module is pure data access
(yaml + pathlib only), so render_capabilities can derive its part vocabulary
from it at import.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

GRAMMAR_FILE = Path(__file__).resolve().parent.parent / "vocab" / "ntp-bits-grammar.yaml"
PACKAGINGS = ("chunked", "single-file")


@lru_cache(maxsize=1)
def grammar() -> dict:
    raw = yaml.safe_load(GRAMMAR_FILE.read_text(encoding="utf-8"))
    for style, by_packaging in raw["parts"].items():
        if set(by_packaging) != set(PACKAGINGS):
            raise ValueError(f"{GRAMMAR_FILE.name}: part style {style!r} must map "
                             f"each of {PACKAGINGS}")
    for kind, roles in raw["rosters"].items():
        missing = [s for s in roles.values() if s not in raw["paragraphs"]]
        if missing:
            raise ValueError(f"{GRAMMAR_FILE.name}: roster {kind!r} names styles "
                             f"with no content-type: {missing}")
    return raw


def part_constructs(packaging: str) -> frozenset[tuple[str, str | None]]:
    """The (element, book-part-type) parts a book of this packaging holds."""
    out = set()
    for by_packaging in grammar()["parts"].values():
        element, *bpt = by_packaging[packaging]
        out.add((element, bpt[0] if bpt else None))
    return frozenset(out)


def part_elements(packaging: str) -> frozenset[str]:
    return frozenset(element for element, _ in part_constructs(packaging))


def roster_content_types(book_part_type: str) -> dict[str, str] | None:
    """A roster part's paragraph content-types by role (person, affiliation,
    contributions); None when the part type is not a roster."""
    roles = grammar()["rosters"].get(book_part_type)
    if roles is None:
        return None
    return {role: grammar()["paragraphs"][style] for role, style in roles.items()}


def style_names() -> frozenset[str]:
    """Every template style the grammar names."""
    g = grammar()
    names = set(g["parts"]) | set(g["paragraphs"]) | set(g["blocks"])
    for roles in g["rosters"].values():
        names |= set(roles.values())
    return frozenset(names)
