"""
vocabulary.py — the semantic-type vocabulary (design) system.

This is the "document design" layer of the descriptive-markup model (the 1980
Scribe/SGML/LaTeX/CSS tradition, later DITA specialization / TEI ODD): a
document is a tree of TYPED parts, each part is styled by its TYPE, and the type
system is a declared, extensible artifact — the "prior agreement" between
producer and consumer.

Where the pieces live:

  - STRUCTURE   — the DocNode tree (document_tree.py), instantiated from a
                  template (templates/*.yaml).  Answers "what parts, in what
                  order, nested how."
  - STYLE       — the abstract per-key vocabulary (layout_style.LAYOUT_KEY_SCHEMA),
                  translated to each surface identically (ADR-0006).  Answers
                  "what does a resolved style dict mean on docx/latex/html."
  - VOCABULARY  — THIS module.  A flat set of semantic TYPES, each carrying a
                  ``specializes`` parent (the one inheritance edge, mirroring
                  Word's ``basedOn`` / DITA's specialization / a CSS class), an
                  own STYLE delta (only the keys it overrides vs its parent), and
                  per-surface BINDINGS (the concrete style name / macro / class /
                  element each renderer uses).  Answers "what semantic parts
                  exist, how do they inherit, and what is each called per surface."

The vocabulary is MEDIUM-NEUTRAL and DOMAIN-SPECIFIC: ``base`` declares the
neutral roots (text, heading, block, …); a domain vocabulary (``ntp-report``)
``extends`` base and declares the concrete report roles (report_title,
section_heading_1, table_title, …).  A different domain (aircraft-engine-manual)
would be a different domain vocabulary over the same base and the same engine.

A vocabulary FILE (vocab/<name>.yaml):

    vocabulary: ntp-report
    extends: base                 # optional: inherit another vocabulary's types
    types:
      report_title:
        specializes: title        # the ONE parent-type edge (base's `title`)
        style: {font_size: "20pt", align: center, space_after: "6pt"}  # OWN delta
        bind:                     # optional per-surface override (else auto-derived)
          docx: "1-03_Report_Title"

Resolution:
  - ``resolve_type_style(vocab, type)`` walks ``specializes`` root→leaf and
    deep-merges the ``style`` deltas (child wins) into ONE flat layout_style
    dict — the same shape resolve_layout_style produces, so the three surface
    translators consume it unchanged.
  - ``resolve_bindings(vocab, type)`` returns the concrete per-surface names,
    auto-derived from the type name unless an explicit ``bind`` overrides.

This module is pure data: it imports nothing from the render pipeline (only the
generic deep_merge and, for validation, layout_style).  It is fully unit-testable
in isolation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from genomics.chart_style import deep_merge

# The per-key style schema + value validator live in layout_style; a type's
# ``style`` delta is an ordinary layout_style dict, so we validate it the same
# way and reject a bad VALUE loudly at load time.
import layout_style


# ---------------------------------------------------------------------------
# The surfaces a binding can name
# ---------------------------------------------------------------------------
# Each render surface addresses a type by its own concrete name: docx by Word
# style name (applied as w:pStyle + emitted as a <w:style>), latex by a control
# sequence, html by a CSS class, bits by a JATS/BITS element (ADR-0004).  The
# name is AUTO-DERIVED from the semantic type name unless the vocabulary supplies
# an explicit override (the derive-if-absent stub).
SURFACES = ("docx", "latex", "html", "bits")

# BITS/JATS element a type projects to, keyed by a coarse family the type name
# implies.  Deliberately tiny (a stub for ADR-0004); the default is <p>.  A type
# whose name ends in a known suffix maps to the matching element; everything else
# is body text.  An explicit ``bind.bits`` always wins over this.
_BITS_BY_SUFFIX = {
    "_title": "title",
    "_head": "title",
    "_heading": "title",
    "_caption": "caption",
    "_footnote": "fn",
    "_note": "fn",
}
_BITS_DEFAULT = "p"


# ---------------------------------------------------------------------------
# The type record
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TypeRecord:
    """One semantic type in a vocabulary.

    Fields:
        name        — the type's semantic name (snake_case), unique within the
                      resolved vocabulary; the styling/addressing key.
        specializes — the parent type name it inherits from (its ``basedOn``),
                      or None for a root.  Resolved within the same vocabulary
                      (after ``extends`` flattening), so a domain type may
                      specialize a base type.
        style       — this type's OWN style delta: a layout_style dict holding
                      only the keys it overrides vs its parent (NOT the resolved
                      absolute).  Empty for a pure grouping/root type.
        bind        — explicit per-surface name overrides ({surface: name}).
                      A surface absent here is auto-derived from ``name``.
    """
    name: str
    specializes: "str | None" = None
    style: dict = field(default_factory=dict)
    bind: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Vocabulary:
    """A resolved vocabulary: name → TypeRecord, with ``extends`` already
    flattened in (a child vocabulary's types override a parent vocabulary's of
    the same name).  ``resolve_*`` operate on this."""
    name: str
    types: dict  # str -> TypeRecord

    def get(self, type_name: str) -> "TypeRecord | None":
        return self.types.get(type_name)


# ---------------------------------------------------------------------------
# Binding auto-derivation
# ---------------------------------------------------------------------------

_KEBAB_RE = re.compile(r"[^a-z0-9]+")
_NONALNUM_RE = re.compile(r"[^a-z0-9]+")


def derive_binding(type_name: str, surface: str) -> str:
    """The default concrete name a surface uses for a semantic type, when the
    vocabulary supplies no explicit override.

      - html  → kebab-case CSS class  (report_title → "report-title")
      - latex → alnum-lowercase control-sequence stem (report_title → "reporttitle")
      - docx  → the type name unchanged (a customStyle id; a vocabulary GENERATED
                from a template overrides this with the real Word style name)
      - bits  → a coarse element by name suffix (…_title → title), else <p>
    """
    lower = type_name.lower()
    if surface == "html":
        return _KEBAB_RE.sub("-", lower).strip("-")
    if surface == "latex":
        return _NONALNUM_RE.sub("", lower)
    if surface == "docx":
        return type_name
    if surface == "bits":
        for suffix, element in _BITS_BY_SUFFIX.items():
            if lower.endswith(suffix):
                return element
        return _BITS_DEFAULT
    raise ValueError(f"unknown surface {surface!r} (known: {SURFACES})")


def resolve_bindings(vocab: Vocabulary, type_name: str) -> dict:
    """Concrete per-surface names for a type: auto-derived, then the vocabulary's
    explicit ``bind`` overrides merged on top (derive-if-absent, per surface).

    Returns {surface: name} for every surface in SURFACES."""
    rec = vocab.get(type_name)
    override = rec.bind if rec else {}
    return {
        surface: override.get(surface) or derive_binding(type_name, surface)
        for surface in SURFACES
    }


# ---------------------------------------------------------------------------
# Style resolution (the specialization chain walk)
# ---------------------------------------------------------------------------

def _specialization_chain(vocab: Vocabulary, type_name: str) -> list[TypeRecord]:
    """The chain of TypeRecords from ROOT down to ``type_name`` (root first,
    the type itself last), following ``specializes``.  Cycles are guarded by a
    visited set (defensive; a well-formed vocabulary is acyclic).  A
    ``specializes`` naming an unknown type stops the walk (validated at load)."""
    chain: list[TypeRecord] = []
    seen: set[str] = set()
    name: "str | None" = type_name
    while name is not None and name not in seen:
        seen.add(name)
        rec = vocab.get(name)
        if rec is None:
            break
        chain.append(rec)
        name = rec.specializes
    chain.reverse()  # root first, child overrides
    return chain


def resolve_type_style(vocab: Vocabulary, type_name: str) -> dict:
    """Resolve a type's effective style by walking ``specializes`` root→leaf and
    deep-merging each record's ``style`` delta (child wins).

    Returns a flat layout_style dict — the SAME shape resolve_layout_style
    produces, so html_generator._layout_to_css_props / latex_generator.
    _layout_to_latex / docx_generator._layout_to_docx consume it unchanged.
    An unknown type resolves to {} (no styling → the surface's built-in look)."""
    chain = _specialization_chain(vocab, type_name)
    return deep_merge(*[rec.style for rec in chain])


# ---------------------------------------------------------------------------
# Loading + validation
# ---------------------------------------------------------------------------

def _type_record_from_raw(name: str, raw: dict) -> TypeRecord:
    """Build a TypeRecord from one raw ``types`` entry, with shape validation."""
    if not isinstance(raw, dict):
        raise ValueError(f"type {name!r}: entry must be a mapping, got {type(raw).__name__}")
    specializes = raw.get("specializes")
    if specializes is not None and not isinstance(specializes, str):
        raise ValueError(f"type {name!r}: 'specializes' must be a string, got {specializes!r}")
    style = raw.get("style") or {}
    if not isinstance(style, dict):
        raise ValueError(f"type {name!r}: 'style' must be a mapping, got {type(style).__name__}")
    bind = raw.get("bind") or {}
    if not isinstance(bind, dict):
        raise ValueError(f"type {name!r}: 'bind' must be a mapping, got {type(bind).__name__}")
    for surface in bind:
        if surface not in SURFACES:
            raise ValueError(
                f"type {name!r}: bind.{surface!r} is not a known surface "
                f"(known: {list(SURFACES)})"
            )
    return TypeRecord(name=name, specializes=specializes, style=dict(style), bind=dict(bind))


def _merge_type_layers(parent_types: dict, child_types: dict) -> dict:
    """Flatten ``extends``: a child vocabulary's type overrides a parent's of the
    same name WHOLESALE (a redefined type replaces, it does not field-merge — the
    child owns the full record).  Types only in one side pass through."""
    out = dict(parent_types)
    out.update(child_types)
    return out


def build_vocabulary(name: str, raw_types: dict, parent: "Vocabulary | None" = None) -> Vocabulary:
    """Assemble a Vocabulary from raw ``types`` (name → raw entry), flattening an
    optional parent vocabulary (``extends``) underneath, then validating the
    resolved whole (specialization targets exist + no cycles + style values ok)."""
    records: dict = {n: _type_record_from_raw(n, r) for n, r in (raw_types or {}).items()}
    merged = _merge_type_layers(parent.types if parent else {}, records)
    vocab = Vocabulary(name=name, types=merged)
    _validate_vocabulary(vocab)
    return vocab


def _validate_vocabulary(vocab: Vocabulary) -> None:
    """Reject a malformed vocabulary loudly at load:
      - every ``specializes`` names a type present in the resolved vocabulary;
      - the specialization graph is acyclic;
      - every type's ``style`` delta carries valid layout_style VALUES (a bad
        value would corrupt a surface); unknown KEYS stay non-fatal (typo warning,
        surfaced via layout_style.unknown_layout_keys at render time)."""
    for name, rec in vocab.types.items():
        if rec.specializes is not None and rec.specializes not in vocab.types:
            raise ValueError(
                f"vocabulary {vocab.name!r}: type {name!r} specializes unknown "
                f"type {rec.specializes!r}"
            )
        errors = layout_style.validate_style(rec.style)
        if errors:
            raise ValueError(
                f"vocabulary {vocab.name!r}: type {name!r} has invalid style "
                f"value(s): {'; '.join(errors)}"
            )
    # Cycle check: every type must reach a root without revisiting itself.
    for name in vocab.types:
        seen: set[str] = set()
        cur: "str | None" = name
        while cur is not None:
            if cur in seen:
                raise ValueError(
                    f"vocabulary {vocab.name!r}: specialization cycle through {name!r}"
                )
            seen.add(cur)
            rec = vocab.types.get(cur)
            cur = rec.specializes if rec else None


def load_vocabulary(name: str, _loader=None, _seen=None) -> Vocabulary:
    """Load and resolve a vocabulary by name from the ``vocab/`` directory,
    following ``extends`` recursively.

    Args:
        name: the vocabulary file stem (vocab/<name>.yaml).
        _loader: internal — a callable(name) -> raw dict, injected by tests to
            avoid disk; defaults to reading vocab/<name>.yaml.
        _seen: internal — cycle guard for ``extends`` chains.

    Returns a fully-resolved Vocabulary (parents flattened, validated)."""
    loader = _loader or _read_vocab_file
    seen = _seen or set()
    if name in seen:
        raise ValueError(f"vocabulary 'extends' cycle through {name!r}")
    seen = seen | {name}

    raw = loader(name)
    if not isinstance(raw, dict):
        raise ValueError(f"vocabulary {name!r}: file must be a mapping, got {type(raw).__name__}")

    parent = None
    extends = raw.get("extends")
    if extends is not None:
        if not isinstance(extends, str):
            raise ValueError(f"vocabulary {name!r}: 'extends' must be a string, got {extends!r}")
        parent = load_vocabulary(extends, _loader=loader, _seen=seen)

    return build_vocabulary(raw.get("vocabulary") or name, raw.get("types") or {}, parent=parent)


def _read_vocab_file(name: str) -> dict:
    """Read vocab/<name>.yaml from the repo's vocab/ directory."""
    from pathlib import Path
    import yaml

    vocab_dir = Path(__file__).resolve().parent / "vocab"
    path = vocab_dir / f"{name}.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
