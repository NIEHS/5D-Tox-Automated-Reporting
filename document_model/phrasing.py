"""
document_model/phrasing.py — the wording a document definition declares for
the prose the report writes from its data (ADR-0029 §11).

Some of a report's prose is written by rules over its tables — the 2026
books' gene set and gene results (rendering.genomics_results), the eFDR
appendix (rendering.genomics_appendix).  The RULE is the code's: which gene
sets are named, which form a gene list takes, when a group is named.  The
WORDS are the definition's ``phrasing:`` block: each sentence a template
whose ``{fields}`` the rule fills, so an era (or a study) that words a
sentence differently says so in its YAML, and the code is unchanged.

    phrasing:
      gene_sets:
        one: "The most sensitive GO biological process … was {term} with a
              {measure} (BMD_L) of {pair} {unit}{table}."

The block is a closed schema (SCHEMA below): an unknown key, a template field
the rule does not supply, or a mis-shaped word list fails loudly at load.  A
key the definition leaves out is not an error at load; where the rule needs
it the report prints a visible placeholder naming it.  ``*x*`` in a template
prints x in italics and ``BMD_L`` its L as a subscript (genomics_results.units).

Definitions inherit and deep-merge the block (document_definition), so a study
re-words one sentence by stating only that key.
"""

from __future__ import annotations

import string
from dataclasses import dataclass


@dataclass(frozen=True)
class _T:
    """A sentence template and the fields its rule supplies."""
    fields: frozenset = frozenset()


@dataclass(frozen=True)
class _Words:
    """Words keyed by a data value (a statistic, a direction); ``keys`` the
    keys every definition must give, None for free keys."""
    keys: frozenset | None = None


@dataclass(frozen=True)
class _List:
    """A list of plain words or of templates (a table's headers), ``n`` long
    (or at least ``n`` with ``at_least``)."""
    n: int
    fields: frozenset = frozenset()
    at_least: bool = False


@dataclass(frozen=True)
class _Number:
    """A number a rule compares against (a percentage the wording names)."""


def _t(*fields: str) -> _T:
    return _T(frozenset(fields))


_PAIR = _List(2)           # [singular, plural]

SCHEMA: dict = {
    "words": {
        "numbers": _List(11, at_least=True),        # 0, 1, 2 … as words
        "statistic": _Words(),                      # a BMD statistic as the prose names it
        "score": _Words(),                          # the gene set potency score it stands for
        "direction": _Words(frozenset({"up", "down"})),
        "all_of": _Words(),                         # "both", "all three" (keys: the count)
        "species": _Words(),                        # "Rat" — a table cell's species
        "bmd": _PAIR,                               # [BMD, BMDs]
        "gene_set": _PAIR,
        "gene": _PAIR,
        "study": _PAIR,
    },
    "values": {
        "pair": _t("bmd", "bmdl"),
        "not_calculated": _t(),
        "same": _t("all", "measure", "pair", "unit"),
        "each": _t("measures", "pairs", "unit"),
    },
    "animals": {
        "in_group": _t("animals", "sentence"),
        "exposed": _t("animals", "exposed", "chemical"),
    },
    "term": _t("go_term", "go_id"),
    "gene": _t("symbol", "name"),
    "tables": {
        "cite": _t("number"),
        "tissue": _t("organ", "number"),
        "where": _t("tissues"),
        "span_none": _t(),
        "span_one": _t("first"),
        "span_two": _t("first", "last"),
        "span_many": _t("first", "last"),
    },
    "limit": {
        "below": _t("nouns", "measure", "lle", "unit", "exceptions"),
        "exceptions": _t("items"),
        "exception": _t("count", "organ", "noun", "animals"),
    },
    "gene_sets": {
        "none": _t("animals"),
        "one": _t("term", "measure", "pair", "unit", "table"),
        "several": _t("terms", "values", "table"),
        "full_list": _t("organ", "animals", "appendix"),
        "intro_examined": _t("tissues", "chemical", "score"),
        "intro_summary": _t("statistic", "table"),
        "intro_shown": _t("statistic", "where", "summary", "below", "span"),
        "summary_lead": _t("table"),
        "summary_both": _t("first", "second", "exposed", "chemical", "organ", "statistic",
                           "term1", "term2", "pair1", "pair2", "unit"),
        "summary_each": _t("animals", "organ", "statistic", "term", "pair", "unit"),
    },
    "genes": {
        "none": _t("organ", "animals"),
        "below_one": _t("organ", "animals", "exhibiting", "genes", "lle", "unit"),
        "below_many": _t("organ", "animals", "exhibiting", "genes", "lle", "unit"),
        "exhibiting_up": _t(),
        "exhibiting_down": _t(),
        "few": _t("count"),
        "few_lead": _t("count", "sentence"),
        "half": _t("count", "organ"),
        "half_up": _t("genes", "values"),
        "half_down": _t("genes", "values"),
        "all_one_way": _t("count", "organ", "direction"),
        "all_list": _t("genes", "values"),
        "one": _t("gene", "direction", "pair", "unit"),
        "most_up": _t("genes", "values"),
        "most_down": _t("genes", "values"),
        "intro": _t("where", "below", "span"),
    },
    "efdr": {
        # The percentages the results' wording names: the gene eFDR's stated
        # bound ("<1%") and the majority sentence's ("below 0.5%").
        "bound_pct": _Number(),
        "majority_below_pct": _Number(),
        "bound_below": _t("limit"),
        "bound_at_most": _t("max"),
        "gene_range": _t("bound", "min", "max", "table"),
        "gene_majority": _t("limit"),
        "go_none": _t(),
        "go_active": _t("found"),
        "go_active_item": _t("species", "tissue", "active", "experiments_with", "experiments"),
        "methods": _t("control", "whose", "generator", "generator_abbreviation", "generator_url",
                      "distribution", "resamples", "count", "groups", "appendix"),
        "methods_groups": _t("control_n", "control", "treated_n"),
        "methods_whose": _t("chemical", "species", "studies"),
        "methods_appendix": _t("appendix"),
        "table": {
            "caption": _t(),
            "headers": _List(6),
            "footnote": _t(),
        },
    },
    "gene_set_definitions": {
        "caption": _t("table"),
        "headers": _List(5, frozenset({"tag", "statistic", "unit"})),
        "go_source": _t("release"),
        "go_release": _t("release"),
        "fifth_pct": _t(),
    },
    "gene_identifiers": {
        "headers": _List(4),
        "footnote": _t(),
    },
}


class PhrasingError(ValueError):
    """A definition's ``phrasing:`` block that does not satisfy SCHEMA."""


def _fields_of(template: str, where: str) -> set[str]:
    try:
        parsed = list(string.Formatter().parse(template))
    except ValueError as e:
        raise PhrasingError(f"{where}: {e} in {template!r}") from None
    out = set()
    for _, name, spec, conv in parsed:
        if name is None:
            continue
        if not name or spec or conv:
            raise PhrasingError(f"{where}: a field is a bare {{name}}, got {template!r}")
        out.add(name)
    return out


def _check_template(v, allowed: frozenset, where: str) -> None:
    if not isinstance(v, str):
        raise PhrasingError(f"{where}: expected a sentence template, got {v!r}")
    extra = _fields_of(v, where) - allowed
    if extra:
        raise PhrasingError(f"{where}: field(s) {sorted(extra)} are not the rule's; "
                            f"it supplies {sorted(allowed) or 'none'}")


def validate(block, where: str = "phrasing", schema: dict = SCHEMA) -> None:
    """Check a ``phrasing:`` block (or a part of one) against SCHEMA."""
    if not isinstance(block, dict):
        raise PhrasingError(f"{where}: expected a mapping, got {type(block).__name__}")
    unknown = sorted(set(map(str, block)) - set(schema))
    if unknown:
        raise PhrasingError(f"{where}: unknown key(s) {unknown}")
    for key, v in block.items():
        spec, path = schema[str(key)], f"{where}.{key}"
        if isinstance(spec, dict):
            validate(v, path, spec)
        elif isinstance(spec, _T):
            _check_template(v, spec.fields, path)
        elif isinstance(spec, _Words):
            if not isinstance(v, dict) or not all(isinstance(w, str) for w in v.values()):
                raise PhrasingError(f"{path}: expected {{key: word}}, got {v!r}")
            missing = sorted((spec.keys or set()) - set(map(str, v)))
            if missing:
                raise PhrasingError(f"{path}: missing {missing}")
        elif isinstance(spec, _List):
            if not isinstance(v, list) or (len(v) < spec.n if spec.at_least else len(v) != spec.n):
                raise PhrasingError(f"{path}: expected {'at least ' if spec.at_least else ''}"
                                    f"{spec.n} entries, got {v!r}")
            for i, item in enumerate(v):
                _check_template(item, spec.fields, f"{path}[{i}]")
        elif isinstance(spec, _Number):
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise PhrasingError(f"{path}: expected a number, got {v!r}")


def missing(key: str) -> str:
    """The visible placeholder for wording a definition does not state."""
    return f"[Placeholder: the document definition states no wording for {key}]"


class Phrasing:
    """A definition's validated ``phrasing:`` block, for the rules to word
    their sentences with.  Empty when the definition declares none."""

    def __init__(self, block: dict | None):
        self.block = block or {}

    def __bool__(self) -> bool:
        return bool(self.block)

    def _get(self, key: str):
        node = self.block
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    def say(self, key: str, **fields) -> str:
        """The template at dotted ``key`` filled with ``fields``."""
        template = self._get(key)
        if template is None:
            return missing(key)
        return template.format_map(fields)

    def word(self, key: str, value, default: str | None = None) -> str:
        """``words.<key>``'s word for ``value``; ``default`` (else the
        placeholder) when the definition gives none."""
        words = self._get(f"words.{key}") or {}
        found = words.get(value, words.get(str(value)))
        if found is not None:
            return found
        return default if default is not None else missing(f"words.{key}.{value}")

    def number(self, n: int) -> str:
        """``n`` as a word ("eight"), or its digits past the declared words."""
        words = self._get("words.numbers") or []
        return words[n] if 0 <= n < len(words) else str(n)

    def noun(self, key: str, n: int) -> str:
        """``words.<key>``: singular for one, plural otherwise."""
        pair = self._get(f"words.{key}")
        if not pair:
            return missing(f"words.{key}")
        return pair[0] if n == 1 else pair[1]

    def items(self, key: str) -> list[str]:
        """A declared list (a table's header templates, unfilled)."""
        return list(self._get(key) or [])

    def has_word(self, key: str, value) -> bool:
        words = self._get(f"words.{key}") or {}
        return value in words or str(value) in words

    def value(self, key: str, default=None):
        found = self._get(key)
        return default if found is None else found


def phrasing_for(dtxsid: str | None) -> Phrasing:
    """The phrasing of the definition a session renders from (its own, else
    the definition of a new study); empty for no session."""
    if not dtxsid:
        return Phrasing(None)
    from common.dtxsid import is_valid_dtxsid
    if not is_valid_dtxsid(dtxsid):
        return Phrasing(None)
    from document_model.view_config import study_document_facts
    return Phrasing(study_document_facts(dtxsid)["phrasing"])
