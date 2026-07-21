"""
Unit tests for layout_style.py — the three-layer per-content-type style merge.

Pins the styling contract both renderers bind to:
  - layer precedence defaults <- types[node_type] <- instances[node_id];
  - a per-node instance override wins over its type, which wins over defaults;
  - two nodes of the same type resolve independently;
  - inputs are never mutated;
  - value validation rejects a bad VALUE loudly (enum / length / color / number
    / bool), while an unknown KEY stays non-fatal (unknown_layout_keys).
"""

import layout_style as ls


# ---------------------------------------------------------------------------
# resolve_layout_style — the three-layer precedence
# ---------------------------------------------------------------------------

def test_resolve_with_no_config_is_empty():
    assert ls.resolve_layout_style(None, "narrative", "background") == {}
    assert ls.resolve_layout_style({}, "narrative", "background") == {}


def test_defaults_layer_applies_to_every_node():
    cfg = {"defaults": {"font_family": "serif"}}
    out = ls.resolve_layout_style(cfg, "narrative", "background")
    assert out == {"font_family": "serif"}


def test_type_layer_overrides_defaults_per_type():
    cfg = {
        "defaults": {"align": "left"},
        "types": {"narrative": {"align": "justify"}},
    }
    narrative = ls.resolve_layout_style(cfg, "narrative", "background")
    heading = ls.resolve_layout_style(cfg, "heading-only", "results")
    assert narrative["align"] == "justify"  # type layer won
    assert heading["align"] == "left"       # only defaults touched it


def test_instance_layer_is_highest_precedence():
    cfg = {
        "defaults": {"font_size": "11pt"},
        "types": {"narrative": {"font_size": "12pt"}},
        "instances": {"background": {"font_size": "10pt"}},
    }
    out = ls.resolve_layout_style(cfg, "narrative", "background")
    assert out["font_size"] == "10pt"


def test_layers_accumulate_distinct_keys():
    cfg = {
        "defaults": {"font_family": "serif"},
        "types": {"heading-only": {"weight": "bold"}},
        "instances": {"results": {"color": "#2c5282"}},
    }
    out = ls.resolve_layout_style(cfg, "heading-only", "results")
    assert out == {"font_family": "serif", "weight": "bold", "color": "#2c5282"}


def test_two_nodes_of_same_type_resolve_independently():
    cfg = {
        "types": {"narrative": {"align": "justify"}},
        "instances": {
            "background": {"first_line_indent": "1em"},
            "summary": {"first_line_indent": "2em"},
        },
    }
    background = ls.resolve_layout_style(cfg, "narrative", "background")
    summary = ls.resolve_layout_style(cfg, "narrative", "summary")
    other = ls.resolve_layout_style(cfg, "narrative", "references")
    assert background == {"align": "justify", "first_line_indent": "1em"}
    assert summary == {"align": "justify", "first_line_indent": "2em"}
    assert other == {"align": "justify"}  # no instance → type only


def test_resolve_does_not_mutate_cfg():
    cfg = {"instances": {"background": {"font_size": "9pt"}}}
    ls.resolve_layout_style(cfg, "narrative", "background")
    assert cfg["instances"]["background"] == {"font_size": "9pt"}


def test_resolve_returns_fresh_dict():
    layer = {"font_family": "serif"}
    cfg = {"defaults": layer}
    out = ls.resolve_layout_style(cfg, "narrative", "background")
    assert out == layer
    assert out is not layer  # fresh copy — mutating the result can't corrupt cfg


# ---------------------------------------------------------------------------
# validate_style — VALUE errors on known keys (loud at load time)
# ---------------------------------------------------------------------------

def test_valid_style_has_no_errors():
    style = {
        "font_family": "serif",
        "font_size": "11pt",
        "weight": "bold",
        "style": "italic",
        "color": "#2c5282",
        "align": "justify",
        "line_height": 1.4,
        "space_before": "6pt",
        "first_line_indent": "1.5em",
        "break_before": "page",
        "keep_together": True,
    }
    assert ls.validate_style(style) == []


def test_bad_enum_value_is_flagged():
    errors = ls.validate_style({"font_family": "comic-sans"})
    assert len(errors) == 1 and "font_family" in errors[0]


def test_font_string_key_accepts_any_nonempty_name():
    # The `font` key (literal family name) is an open string — any non-empty
    # value is valid (we can't validate a name against a render machine here).
    assert ls.validate_style({"font": "Times New Roman"}) == []
    assert ls.validate_style({"font": "Some Custom Font 2"}) == []


def test_font_string_key_rejects_empty_or_non_string():
    assert ls.validate_style({"font": "   "}) != []
    assert ls.validate_style({"font": 12}) != []
    assert ls.validate_style({"font": None}) != []


def test_font_key_is_in_schema_and_payload():
    assert ls.LAYOUT_KEY_SCHEMA["font"] == ("string",)
    payload = ls.style_schema_payload()
    assert payload["font"] == {"kind": "string"}


def test_bad_length_value_is_flagged():
    # A bare number with no unit, and a px unit (excluded), both fail.
    assert ls.validate_style({"font_size": 11}) != []
    assert ls.validate_style({"font_size": "11px"}) != []
    assert ls.validate_style({"font_size": "11pt"}) == []


def test_bad_color_value_is_flagged():
    assert ls.validate_style({"color": "blue"}) != []
    assert ls.validate_style({"color": "#12"}) != []
    assert ls.validate_style({"color": "#abc"}) == []
    assert ls.validate_style({"color": "#aabbcc"}) == []


def test_line_height_must_be_a_number_not_bool():
    assert ls.validate_style({"line_height": 1.5}) == []
    assert ls.validate_style({"line_height": "big"}) != []
    assert ls.validate_style({"line_height": True}) != []  # bool is not a number


def test_keep_together_must_be_bool():
    assert ls.validate_style({"keep_together": True}) == []
    assert ls.validate_style({"keep_together": "yes"}) != []


def test_unknown_key_is_not_a_value_error():
    # An unknown key is the domain of unknown_layout_keys, not validate_style.
    assert ls.validate_style({"fnot_family": "serif"}) == []


# ---------------------------------------------------------------------------
# unknown_layout_keys — non-fatal typo catcher
# ---------------------------------------------------------------------------

def test_unknown_layout_keys_flags_typos_only():
    style = {"font_family": "serif", "fnot_size": "11pt", "algin": "left"}
    bad = ls.unknown_layout_keys(style)
    assert set(bad) == {"fnot_size", "algin"}  # only the two typos, not font_family


def test_unknown_layout_keys_empty_for_clean_style():
    assert ls.unknown_layout_keys({"font_family": "serif", "align": "justify"}) == []


# ---------------------------------------------------------------------------
# style_schema_payload — the projection the browser form is generated from
# ---------------------------------------------------------------------------

def test_schema_payload_covers_every_schema_key():
    payload = ls.style_schema_payload()
    assert set(payload) == set(ls.LAYOUT_KEY_SCHEMA)


def test_schema_payload_reports_the_right_kind_per_key():
    payload = ls.style_schema_payload()
    assert payload["font_family"]["kind"] == "enum"
    assert payload["font_size"]["kind"] == "length"
    assert payload["line_height"]["kind"] == "number"
    assert payload["color"]["kind"] == "color"
    assert payload["keep_together"]["kind"] == "bool"


def test_schema_payload_enum_values_match_the_frozensets():
    payload = ls.style_schema_payload()
    # Values are sorted for stable output; compare as sets against the source.
    assert set(payload["font_family"]["values"]) == ls.FONT_FAMILIES
    assert set(payload["align"]["values"]) == ls.ALIGNMENTS
    assert set(payload["break_before"]["values"]) == ls.BREAKS
    assert payload["font_family"]["values"] == sorted(ls.FONT_FAMILIES)  # sorted


def test_schema_payload_length_keys_carry_the_unit_list():
    payload = ls.style_schema_payload()
    assert payload["font_size"]["units"] == list(ls.LENGTH_UNITS)
    # A non-length key has no units.
    assert "units" not in payload["line_height"]


def test_schema_payload_is_json_serializable():
    import json
    # Must round-trip cleanly — it ships as window.__LAYOUT_SCHEMA__ JSON.
    json.dumps(ls.style_schema_payload())


# ---------------------------------------------------------------------------
# Document-level vocabulary (page geometry + document defaults)
# ---------------------------------------------------------------------------

def test_document_style_valid_block_has_no_errors():
    doc = {
        "page_width": "8.5in", "page_height": "11in",
        "margin_left": "1in", "margin_top": "1in",
        "header_distance": "0.5in",
        "default_font": "Times New Roman", "default_font_size": "12pt",
        "header_font": "Arial",
    }
    assert ls.validate_document_style(doc) == []


def test_document_style_flags_bad_length_and_empty_font():
    assert ls.validate_document_style({"page_width": "8.5"}) != []      # no unit
    assert ls.validate_document_style({"default_font": "  "}) != []     # empty
    assert ls.validate_document_style({"margin_top": "2in"}) == []


def test_document_unknown_keys_are_reported():
    assert ls.unknown_document_keys({"page_width": "8.5in", "bogus": 1}) == ["bogus"]
    assert ls.unknown_document_keys({"page_width": "8.5in"}) == []


def test_document_keys_are_disjoint_from_node_keys():
    # The two vocabularies must not overlap — a node key in the document block
    # (or vice-versa) would be silently mis-validated.
    assert set(ls.DOCUMENT_KEY_SCHEMA) & set(ls.LAYOUT_KEY_SCHEMA) == set()
