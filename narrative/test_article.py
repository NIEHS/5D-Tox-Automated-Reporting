"""
narrative/test_article.py — how a generated text names the test article.

The abbreviation is a fact of the study (identity.json ``abbreviation``, given
with ``generate_report --compound-name``), never the model's to coin: a
prompt that gives only the name lets each text make up its own ("PFHSA",
"PFHxSA" for PFHxSAm), and the report's deterministic prose uses the recorded
one.  Every LLM prompt that names the test article states this rule.
"""

from __future__ import annotations


def abbreviation_of(identity: dict | None) -> str:
    """The recorded abbreviation; "" when the study records none."""
    return str((identity or {}).get("abbreviation") or "").strip()


def naming_rule(name: str, abbreviation: str = "") -> str:
    """The prompt's instruction for naming the test article."""
    name = (name or "").strip() or "the test article"
    if abbreviation and abbreviation != name:
        return (f'Name the test article "{name}" at its first mention, followed by its '
                f'abbreviation in parentheses — "{name} ({abbreviation})" — and '
                f'"{abbreviation}" after that. Use no other abbreviation or short form '
                f'for it.')
    return (f'Name the test article "{name}". The study records no abbreviation for '
            f'it: do not coin one; write its name each time.')
