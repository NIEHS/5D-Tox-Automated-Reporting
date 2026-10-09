"""
document_definition.py — a report's document definition as an era base plus
alterations (ADR-0029).

A *definition* is a template file (templates/<name>.yaml).  It is either a full
template (a ``document:`` list and its sibling blocks), or it ``extends``
another definition and states only how it differs:

    extends: eras/niehs-2023          # a name under templates/; chains allowed
    packaging: single-file            # chunked (default) | single-file
    book_meta: {...}                  # deep-merged over the base's
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

The levels (ADR-0029): ``niehs-5day-report`` is the definition of a new study;
``eras/<era>`` reproduce the published report generations; a published
study's ``studies/<DTXSID>/document`` extends its era.

Import graph: document_template and this module import each other lazily
(inside functions), so neither import-time order matters.
"""

from __future__ import annotations

import copy
from pathlib import Path

import yaml

from common.dtxsid import validate_dtxsid

PACKAGINGS = ("chunked", "single-file")
_DEFINITION_KEYS = frozenset({"extends", "packaging", "book_meta", "changes"})
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
    ``changes``, ``book_meta`` deep-merged and ``packaging`` overridden.  A full
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
    if raw.get("book_meta"):
        out["book_meta"] = _deep_merge(out.get("book_meta") or {}, raw["book_meta"])
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

def study_definition_name(dtxsid: str) -> str | None:
    """``studies/<DTXSID>/document`` when the study has its own definition."""
    name = f"studies/{validate_dtxsid(dtxsid)}/document"
    return name if (_templates_dir() / f"{name}.yaml").exists() else None


def packaging_of(raw) -> str:
    """A composed definition's packaging (chunked when it declares none)."""
    return (raw.get("packaging") if isinstance(raw, dict) else None) or "chunked"
