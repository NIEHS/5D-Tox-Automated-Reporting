"""
layout_style.py — per-content-type font & flow specification (the styling
analog of chart_style.py).

A report's typography and page-flow are authored at the CONTENT-TYPE level: the
document config carries a ``styles`` block that maps each catalog node type
(render_capabilities.COMPONENT_CATALOG) to an ABSTRACT, surface-agnostic style
spec, which each renderer translates to its own directives — LaTeX
package/selector output (latex_generator) and CSS (html_generator).  Because
both surfaces resolve the SAME spec, they cannot drift (ADR-0006).

Three merge layers, in increasing precedence (identical shape to chart_style):

    1. styles.defaults        — applied to EVERY element.
    2. styles.types[T]        — applied to every node of content type T.
    3. styles.instances[id]   — applied to ONE node, keyed by its DocNode id.

Each layer is a partial dict overriding only the keys it names; the merge is the
generic ``chart_style.deep_merge`` (recurse dicts, replace scalars/lists/None
wholesale, never mutate).  An absent / empty ``styles`` block resolves to ``{}``
for every node, so the renderers emit exactly today's hardcoded look — the
all-absent path is a no-op.

This module is pure data: it imports nothing from the render pipeline and is
fully unit-testable in isolation.  The vocabulary is intentionally bounded (no
raw-LaTeX / raw-CSS escape hatch) so the two surfaces stay expressible from one
spec.
"""

from __future__ import annotations

import re

# Reuse the generic, well-tested deep-merge (recurse dicts, replace
# scalars/lists/None wholesale, deep-copy, never mutate inputs).  It is domain-
# neutral, so there is no reason to re-implement it here.
from genomics.chart_style import deep_merge


# ---------------------------------------------------------------------------
# The abstract vocabulary (canonical key schema)
# ---------------------------------------------------------------------------
# Flat (no nested groups): each key is one presentation dimension that can
# legitimately vary per content type on BOTH surfaces mid-document.  For each
# key we record the accepted values — an enum set for closed vocabularies, or a
# validator name for open scalars (length / number / color) — used by
# ``validate_style`` to reject a bad VALUE loudly at load time (a bad value
# would corrupt the .tex compile or the CSS), while an unknown KEY stays
# non-fatal (``unknown_layout_keys``), mirroring chart_style's discipline.

FONT_FAMILIES = frozenset({"serif", "sans", "mono"})
WEIGHTS = frozenset({"normal", "bold"})
STYLES = frozenset({"normal", "italic"})
ALIGNMENTS = frozenset({"left", "right", "center", "justify"})
BREAKS = frozenset({"auto", "page"})
# text_transform is deliberately scoped to {none, uppercase}: uppercase is the
# only value that maps to a FAITHFUL display-transform on all three surfaces
# (CSS text-transform:uppercase, LaTeX \MakeUppercase, docx w:caps/all_caps) AND
# is what the NTP `Title` (all-caps) needs.  `lowercase`/`capitalize` are NOT
# included because Word has no display-transform run property for them (only
# w:caps for all-caps) — emitting them would silently no-op on docx (a
# four-part-contract drift bug) or force irreversible actual-text mutation.
TEXT_TRANSFORMS = frozenset({"none", "uppercase"})

# Descriptive schema: key -> ("enum", frozenset) | ("length",) | ("number",)
# | ("color",) | ("bool",) | ("string",).  Used both as the author-facing doc
# and by validate_style / unknown_layout_keys.
#
# FONT PRECEDENCE (applied identically by all three translators —
# html_generator._layout_to_css_props, latex_generator._layout_to_latex,
# docx_generator._layout_to_docx): an explicit `font` (a literal family name like
# "Times New Roman") WINS and is used verbatim on every surface; otherwise
# `font_family` (serif/sans/mono) maps through each surface's abstract table.
# This lets a Word-authored / bootstrap-extracted config name the exact font
# while a hand-written serif/sans/mono config keeps working unchanged.
LAYOUT_KEY_SCHEMA: dict = {
    "font": ("string",),                      # literal family name, e.g. "Times New Roman"
    "font_family": ("enum", FONT_FAMILIES),   # serif | sans | mono (fallback when `font` unset)
    "font_size": ("length",),                 # e.g. "11pt", "1.2em"
    "weight": ("enum", WEIGHTS),              # normal | bold
    "style": ("enum", STYLES),                # normal | italic
    "text_transform": ("enum", TEXT_TRANSFORMS),  # none | uppercase (all-caps display)
    "letter_spacing": ("length",),            # inter-char tracking; ABSOLUTE units only (pt/mm/cm/in)
    "color": ("color",),                      # "#rgb" | "#rrggbb"
    "align": ("enum", ALIGNMENTS),            # left | right | center | justify
    "line_height": ("number",),              # unitless multiplier, e.g. 1.4
    "space_before": ("length",),              # vertical space above, e.g. "6pt"
    "space_after": ("length",),               # vertical space below
    "first_line_indent": ("length",),         # paragraph first-line indent
    "break_before": ("enum", BREAKS),         # auto | page
    "break_after": ("enum", BREAKS),          # auto | page
    "keep_together": ("bool",),               # avoid breaking inside
    "outline_level": ("number",),             # 0-based heading depth; a TOC/nav collects it
}

# A CSS/LaTeX length: a number (int or float, optionally signed) followed by a
# unit.  Deliberately restricted to print-safe absolute/relative units that map
# cleanly to BOTH surfaces (pt, mm, cm, in, em, ex).  px is excluded (meaningless
# in LaTeX); % is excluded (ambiguous target box).  The unit set is named so the
# regex and the schema payload (the form's unit dropdown) share ONE source.
LENGTH_UNITS = ("pt", "mm", "cm", "in", "em", "ex")
_LENGTH_RE = re.compile(r"^-?\d+(\.\d+)?(" + "|".join(LENGTH_UNITS) + r")$")
_COLOR_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


# ---------------------------------------------------------------------------
# The DOCUMENT-level vocabulary (page geometry + document defaults)
# ---------------------------------------------------------------------------
# Distinct from the per-node LAYOUT_KEY_SCHEMA above: these keys describe the
# WHOLE document (the page and its margins, the base body font, the running
# header), not a single node's block.  They live in an optional top-level
# ``document:`` section of the ``styles`` block.  A page dimension / margin is a
# print-length; the fonts are literal family names; the sizes are lengths.  This
# is where the reference's US-Letter trim, 1" margins, and header font become
# DATA the docx surface reads (replacing its hardcoded constants) — the same
# geometry LaTeX (geometry package) and HTML (@page) can honor where feasible.
DOCUMENT_KEY_SCHEMA: dict = {
    "page_width": ("length",),         # e.g. "8.5in"
    "page_height": ("length",),        # e.g. "11in"
    "margin_top": ("length",),
    "margin_bottom": ("length",),
    "margin_left": ("length",),
    "margin_right": ("length",),
    "header_distance": ("length",),    # header/footer distance from the page edge
    "default_font": ("string",),       # base body font family name
    "default_font_size": ("length",),  # base body size, e.g. "12pt"
    "header_font": ("string",),        # running-header font family name
    "header_font_size": ("length",),
}


# ---------------------------------------------------------------------------
# The TITLE-PAGE roles (a per-role styling sub-layer)
# ---------------------------------------------------------------------------
# The title-page node emits several semantically distinct lines (the report
# title, the report number/date, the publisher block, the ISSN) that each want a
# DIFFERENT style — unlike every other node, which resolves to ONE style.  So the
# title page gets a `title_page:` sub-layer in the styles config, keyed by ROLE
# (not node_type).  Each role's value is an ordinary per-node style dict
# (validated against LAYOUT_KEY_SCHEMA).  The role names map 1:1 onto the NTP
# template's `1-NN` title-page style family (see
# docx_style_extract._TITLE_PAGE_STYLE_TO_ROLE) so the extractor can populate
# them; the docx title-page handler (docx_generator._render_title_page) reads
# them to style each emitted block.  Snake_case, a closed set (an unknown role is
# rejected, like an unknown node_type).
TITLE_PAGE_ROLES = frozenset({
    "report_title", "report_type", "report_subtitle",
    "publication_date", "report_number", "doi", "issn", "nih_number",
    "publisher_name", "publisher_affiliation", "publisher_location",
    "publication_office", "publication_division",
    "publication_institute", "publication_department",
    "logo_graphic",
})


# ---------------------------------------------------------------------------
# Value validation
# ---------------------------------------------------------------------------

def _value_error(key: str, value, expected: str, schema: dict | None = None) -> str:
    """Return a validation error message, or '' if the value is acceptable.

    ``schema`` selects the vocabulary to look ``key`` up in — the per-node
    LAYOUT_KEY_SCHEMA by default, or DOCUMENT_KEY_SCHEMA for the document-level
    block.  Both share the same value-KIND checks below, so only the lookup
    table differs."""
    spec = (schema or LAYOUT_KEY_SCHEMA).get(key)
    if spec is None:
        return ""  # unknown key — not a VALUE error (caught by unknown_layout_keys)
    kind = spec[0]
    if kind == "enum":
        allowed = spec[1]
        if value not in allowed:
            return (
                f"{key}: {value!r} is not one of {sorted(allowed)}"
            )
    elif kind == "length":
        if not (isinstance(value, str) and _LENGTH_RE.match(value)):
            return (
                f"{key}: {value!r} is not a valid length "
                f"(a number with a unit: pt/mm/cm/in/em/ex)"
            )
    elif kind == "number":
        # bool is an int subclass — reject it explicitly (a leading is not a flag).
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"{key}: {value!r} is not a number"
    elif kind == "color":
        if not (isinstance(value, str) and _COLOR_RE.match(value)):
            return f"{key}: {value!r} is not a hex color (#rgb or #rrggbb)"
    elif kind == "bool":
        if not isinstance(value, bool):
            return f"{key}: {value!r} is not a boolean"
    elif kind == "string":
        # An open free-text scalar (a font family name).  Any non-empty string
        # is accepted — we can't validate a font NAME against the render
        # machine's installed set here, and doing so would couple this to a
        # specific box.  Emptiness is the only error.
        if not (isinstance(value, str) and value.strip()):
            return f"{key}: {value!r} is not a non-empty string"
    return ""


def validate_style(style: dict) -> list[str]:
    """
    Return a list of VALUE errors for a single resolved/authored style dict.

    Only KNOWN keys are value-checked; unknown keys are ignored here (they are
    the domain of ``unknown_layout_keys``, which is non-fatal).  An empty list
    means every named key carries an acceptable value.
    """
    errors: list[str] = []
    if not isinstance(style, dict):
        return [f"style must be a mapping, got {type(style).__name__}"]
    for key, value in style.items():
        msg = _value_error(key, value, "")
        if msg:
            errors.append(msg)
    return errors


def unknown_layout_keys(style: dict) -> list[str]:
    """
    Return keys in ``style`` not present in ``LAYOUT_KEY_SCHEMA`` — a typo-catcher
    for authored config.  Non-fatal: callers log these as warnings (mirroring
    chart_style.unknown_style_keys).  Flat vocabulary, so no recursion.
    """
    if not isinstance(style, dict):
        return []
    return [k for k in style if k not in LAYOUT_KEY_SCHEMA]


def validate_document_style(document: dict) -> list[str]:
    """
    Return a list of VALUE errors for the document-level ``document:`` block,
    checked against DOCUMENT_KEY_SCHEMA.  Same discipline as validate_style:
    known keys are value-checked, unknown keys are ignored here (typo-catching is
    unknown_document_keys' job).  Empty list ⇒ every named key is acceptable.
    """
    errors: list[str] = []
    if not isinstance(document, dict):
        return [f"document must be a mapping, got {type(document).__name__}"]
    for key, value in document.items():
        msg = _value_error(key, value, "", schema=DOCUMENT_KEY_SCHEMA)
        if msg:
            errors.append(msg)
    return errors


def unknown_document_keys(document: dict) -> list[str]:
    """Keys in the ``document:`` block absent from DOCUMENT_KEY_SCHEMA."""
    if not isinstance(document, dict):
        return []
    return [k for k in document if k not in DOCUMENT_KEY_SCHEMA]


# ---------------------------------------------------------------------------
# The resolver
# ---------------------------------------------------------------------------

def resolve_layout_style(
    layout_cfg: dict | None,
    node_type: str,
    node_id: str,
) -> dict:
    """
    Resolve the effective style for one node via the three-layer deep-merge
    (defaults ← types[node_type] ← instances[node_id]).

    Args:
        layout_cfg: the raw ``styles`` block (``{defaults, types, instances}``);
            any layer may be absent.  None / ``{}`` ⇒ ``{}`` (no styling → the
            renderer's built-in look).
        node_type:  the DocNode.node_type (the ``types`` key).
        node_id:    the DocNode.id (the ``instances`` key).

    Returns a fresh resolved-style dict.  Later layers win; a nested value would
    replace wholesale, but the vocabulary is flat so every key is a scalar.
    """
    cfg = layout_cfg or {}
    return deep_merge(
        cfg.get("defaults"),
        (cfg.get("types") or {}).get(node_type),
        (cfg.get("instances") or {}).get(node_id),
    )


# ---------------------------------------------------------------------------
# Schema projection for the browser form
# ---------------------------------------------------------------------------

def style_schema_payload() -> dict:
    """
    Project LAYOUT_KEY_SCHEMA into a JSON-serializable description the visual
    style builder (web/js/layout_builder.js) renders its controls from.

    Shape — one entry per key, in schema (author-facing) order:

        {
          "font_family": {"kind": "enum", "values": ["mono","sans","serif"]},
          "font_size":   {"kind": "length", "units": ["pt","mm","cm","in","em","ex"]},
          "line_height": {"kind": "number"},
          "color":       {"kind": "color"},
          "keep_together":{"kind": "bool"},
          ...
        }

    Deriving this from the single schema (rather than hand-listing keys in JS)
    means a new key added to LAYOUT_KEY_SCHEMA appears in the form automatically.
    Enum value lists are sorted for stable output (frozensets are unordered).
    """
    out: dict = {}
    for key, spec in LAYOUT_KEY_SCHEMA.items():
        kind = spec[0]
        entry: dict = {"kind": kind}
        if kind == "enum":
            entry["values"] = sorted(spec[1])
        elif kind == "length":
            entry["units"] = list(LENGTH_UNITS)
        out[key] = entry
    return out
