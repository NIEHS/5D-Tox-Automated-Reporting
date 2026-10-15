"""
document_definition.py — a report's document definition as an era base plus
alterations (ADR-0029).

A *definition* is a template file (templates/<name>.yaml).  It is either a full
template (a ``document:`` list and its sibling blocks), or it ``extends``
another definition and states only how it differs:

    extends: eras/niehs-2023          # a name under templates/; chains allowed
    packaging: single-file            # chunked (default) | single-file
    object_position: {back: float}    # tables/figures float or anchor, per region
    book_meta: {...}                  # deep-merged over the base's
    phrasing: {...}                   # the generated prose's wording, deep-merged
                                      # likewise (document_model.phrasing)
    changes:                          # applied in order
      - set: appendix-d               # replace fields on a node (null removes one)
        title: New title
      - remove: appendix-a            # drop a node with its subtree
      - insert: [ {node entry}, ... ] # add nodes after | before a node, or
        after: appendix-c             # into a node / region (at: first | last)
      - move: mm-a                    # reorder a node: after | before | into
        before: mm-b

Composition happens on the raw YAML entries, before instantiation, so the
template validator checks the composed document exactly as it checks an
authored one.  An unknown id, a cycle or an unknown key fails loudly.

The levels (ADR-0029): ``niehs-5day-report`` is the shared base grammar;
``eras/<era>`` reproduce the published report generations; a published
study's ``studies/<DTXSID>/document`` extends its era.  A new study — one with
no definition of its own — is written to the latest generation's
(DEFAULT_DEFINITION, the 2026 books).

Import graph: document_template and this module import each other lazily
(inside functions), so neither import-time order matters.
"""

from __future__ import annotations

import copy
from pathlib import Path

import yaml

from common.dtxsid import validate_dtxsid

PACKAGINGS = ("chunked", "single-file")
_DEFINITION_KEYS = frozenset({"extends", "packaging", "object_position", "book_meta",
                              "phrasing", "tissue_order", "abstract_genes", "changes"})
_OPS = ("set", "remove", "insert", "move")
_PLACES = ("after", "before", "into")


def _templates_dir() -> Path:
    # document_template's, read at call time so a test that points the
    # templates root elsewhere points both modules there.
    from document_model import document_template
    return document_template.TEMPLATES_DIR


def _read(name: str):
    path = _templates_dir() / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"no template named {name!r} at {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def is_extension(raw) -> bool:
    """True when a template's raw mapping is a definition that extends another."""
    return isinstance(raw, dict) and "extends" in raw


def load_definition(name: str, _seen: tuple[str, ...] = ()) -> dict | list:
    """The raw template mapping for `name` with every ``extends`` resolved: the
    base's mapping (all its sibling blocks), its ``document`` altered by
    ``changes``, ``book_meta`` and ``phrasing`` deep-merged and ``packaging`` /
    ``tissue_order`` overridden.  A full
    template comes back as read."""
    if name in _seen:
        raise ValueError(f"definition {name!r}: extends cycle {' -> '.join((*_seen, name))}")
    raw = _read(name)
    if not is_extension(raw):
        return raw
    unknown = set(raw) - _DEFINITION_KEYS
    if unknown:
        raise ValueError(f"definition {name!r}: unknown key(s) {sorted(unknown)} "
                         f"(an extending definition states only {sorted(_DEFINITION_KEYS)})")
    base = load_definition(str(raw["extends"]), (*_seen, name))
    if not (isinstance(base, dict) and isinstance(base.get("document"), list)):
        raise ValueError(f"definition {name!r}: base {raw['extends']!r} has no document list")
    out = copy.deepcopy(base)
    if "packaging" in raw:
        if raw["packaging"] not in PACKAGINGS:
            raise ValueError(f"definition {name!r}: packaging must be one of {PACKAGINGS}")
        out["packaging"] = raw["packaging"]
    if "tissue_order" in raw:
        out["tissue_order"] = raw["tissue_order"]
    if "abstract_genes" in raw:
        out["abstract_genes"] = raw["abstract_genes"]
    if raw.get("object_position"):
        out["object_position"] = {**(out.get("object_position") or {}), **raw["object_position"]}
    if raw.get("book_meta"):
        out["book_meta"] = _deep_merge(out.get("book_meta") or {}, raw["book_meta"])
    if raw.get("phrasing"):
        out["phrasing"] = _deep_merge(out.get("phrasing") or {}, raw["phrasing"])
    for i, change in enumerate(raw.get("changes") or []):
        try:
            apply_change(out["document"], change)
        except (KeyError, ValueError) as e:
            raise ValueError(f"definition {name!r}: change {i + 1}: {e}") from None
    return out


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


# ---------------------------------------------------------------------------
# Changes
# ---------------------------------------------------------------------------

def _children_lists(document: list):
    """Every (container, list) pair in the document: the top list, each region
    container's children and each node's children."""
    stack = [(None, document)]
    while stack:
        owner, lst = stack.pop()
        yield owner, lst
        for entry in lst:
            if isinstance(entry, dict) and isinstance(entry.get("children"), list):
                stack.append((entry, entry["children"]))


def _locate(document: list, node_id: str) -> tuple[list, int]:
    """(the list holding node `node_id`, its index)."""
    for _owner, lst in _children_lists(document):
        for i, entry in enumerate(lst):
            if isinstance(entry, dict) and entry.get("id") == node_id:
                return lst, i
    raise KeyError(f"no node {node_id!r}")


def _container(document: list, target: str) -> list:
    """The children list of node `target`, or of the region container named so."""
    for entry in document:
        if isinstance(entry, dict) and entry.get("region") == target and "id" not in entry:
            return entry.setdefault("children", [])
    lst, i = _locate(document, target)
    return lst[i].setdefault("children", [])


def _place(document: list, entries: list, change: dict) -> None:
    places = [p for p in _PLACES if p in change]
    if len(places) != 1:
        raise ValueError(f"name exactly one of {_PLACES}, got {places or 'none'}")
    where = places[0]
    if where == "into":
        lst = _container(document, change["into"])
        at = change.get("at", "last")
        if at not in ("first", "last"):
            raise ValueError(f"at must be first or last, got {at!r}")
        lst[0 if at == "first" else len(lst):0 if at == "first" else len(lst)] = entries
    else:
        lst, i = _locate(document, change[where])
        j = i + 1 if where == "after" else i
        lst[j:j] = entries


def apply_change(document: list, change: dict) -> None:
    """Apply one change (see the module docstring) to a raw document in place."""
    if not isinstance(change, dict):
        raise ValueError(f"a change must be a mapping, got {type(change).__name__}")
    ops = [op for op in _OPS if op in change]
    if len(ops) != 1:
        raise ValueError(f"a change names exactly one of {_OPS}, got {ops or 'none'}")
    op = ops[0]
    if op == "set":
        fields = {k: v for k, v in change.items() if k != "set"}
        if not fields or {"id", "children"} & set(fields):
            raise ValueError("set changes a node's fields (not its id or children)")
        lst, i = _locate(document, change["set"])
        for k, v in fields.items():
            if v is None:
                lst[i].pop(k, None)
            else:
                lst[i][k] = copy.deepcopy(v)
    elif op == "remove":
        lst, i = _locate(document, change["remove"])
        del lst[i]
    elif op == "insert":
        entries = change["insert"]
        if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
            raise ValueError("insert takes a list of node entries")
        _place(document, copy.deepcopy(entries), change)
    elif op == "move":
        lst, i = _locate(document, change["move"])
        entry = lst.pop(i)
        _place(document, [entry], change)


# ---------------------------------------------------------------------------
# A study's definition
# ---------------------------------------------------------------------------

# The definition of a study with none of its own: the latest published
# generation (NIEHS-12, 13, April 2026).
DEFAULT_DEFINITION = "eras/niehs-2026"


def study_definition_name(dtxsid: str) -> str | None:
    """``studies/<DTXSID>/document`` when the study has its own definition."""
    name = f"studies/{validate_dtxsid(dtxsid)}/document"
    return name if (_templates_dir() / f"{name}.yaml").exists() else None


def current_definition_name(dtxsid: str) -> str:
    """The definition the files give a study: its own, else DEFAULT_DEFINITION."""
    return study_definition_name(dtxsid) or DEFAULT_DEFINITION


def definition_name(dtxsid: str) -> str:
    """The definition a study renders from: its pinned snapshot when the
    session FIXES its definition (document_model.definition_pin), else the
    current one."""
    from document_model.definition_pin import pinned_name
    return pinned_name(dtxsid) or current_definition_name(dtxsid)


def packaging_of(raw) -> str:
    """A composed definition's packaging (chunked when it declares none)."""
    return (raw.get("packaging") if isinstance(raw, dict) else None) or "chunked"


# ---------------------------------------------------------------------------
# The formats' names (Q-M1-6, signed 2026-10-15)
# ---------------------------------------------------------------------------

# What each era is called where a person chooses or reads a study's format.
# ``title`` is the full name, ``short`` fits a table cell, ``phrase`` is the
# name inside a sentence ("… is written in <phrase>").  Declared here, beside
# DEFAULT_DEFINITION, so no screen or route names a format itself.  An era
# with no entry is named by its file (``era_title``), never guessed.
ERA_TITLES: dict[str, dict[str, str]] = {
    "eras/ntp-rr-2018": {
        "title": "NTP Research Report, as published in December 2018 (RR-8)",
        "short": "NTP Research Report, 2018",
        "phrase": "the NTP Research Report as published in 2018",
    },
    "eras/niehs-2022": {
        "title": "NIEHS Report, as published in October 2022 (NIEHS-02 … 06), one file",
        "short": "NIEHS Report, October 2022",
        "phrase": "the NIEHS Report as published in October 2022",
    },
    "eras/niehs-2023": {
        "title": "NIEHS Report, as published in March 2023 (NIEHS-07 … 10)",
        "short": "NIEHS Report, March 2023",
        "phrase": "the NIEHS Report as published in March 2023",
    },
    "eras/niehs-2026": {
        "title": "NIEHS Report, as published in 2026 (NIEHS-12, 13): the format for new studies",
        "short": "NIEHS Report, 2026",
        "phrase": "the NIEHS Report as published in 2026",
    },
}

# What a definition may alter besides its structure (_DEFINITION_KEYS), in the
# words a person reads ("… with its own series details").
ALTERATION_WORDS: dict[str, str] = {
    "packaging": "packaging",
    "object_position": "placement of tables and figures",
    "book_meta": "series details",
    "phrasing": "wording",
    "tissue_order": "order of tissues",
    "abstract_genes": "naming of genes in the abstract",
}


def era_title(era: str | None) -> dict[str, str]:
    """{title, short, phrase} of an era; an undeclared one is named by its file."""
    if era in ERA_TITLES:
        return dict(ERA_TITLES[era])
    name = era or "an undeclared format"
    return {"title": name, "short": name, "phrase": name}


def definition_outline(name: str) -> dict:
    """Where a definition stands among the declared formats, read from the
    files without composing them: ``{era, changes, alters}``.

    ``era`` is the first ``eras/…`` definition on its ``extends`` chain (the
    name itself when it is one; None when the chain reaches no era).
    ``changes`` counts the structural changes the definitions between it and
    its era state; ``alters`` lists the other keys they set (book_meta, …),
    in ALTERATION_WORDS order.  Cheap: one small YAML read per link."""
    changes, alters = 0, []
    seen: list[str] = []
    current: str | None = name
    while current and not current.startswith("eras/"):
        if current in seen:
            raise ValueError(f"definition {name!r}: extends cycle {' -> '.join((*seen, current))}")
        seen.append(current)
        raw = _read(current)
        if not is_extension(raw):
            return {"era": None, "changes": changes, "alters": alters}
        changes += len(raw.get("changes") or [])
        alters += [k for k in ALTERATION_WORDS if k in raw and k not in alters]
        current = str(raw["extends"])
    return {"era": current, "changes": changes,
            "alters": [k for k in ALTERATION_WORDS if k in alters]}
