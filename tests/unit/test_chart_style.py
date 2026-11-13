"""
Unit tests for chart_style.py (WP-1) — the three-layer chart-style merge.

Pins the contract every other work-package binds to (C2 resolved-style shape,
C1 instance key):
  - layer precedence built-in <- defaults <- types[type] <- instances[key];
  - an instance override of ONE nested leaf inherits its siblings (deep merge);
  - two instances of the same type resolve independently;
  - lists (the palette) replace wholesale, never element-merge;
  - inputs are never mutated.
"""

import genomics.chart_style as cs


# ---------------------------------------------------------------------------
# deep_merge
# ---------------------------------------------------------------------------

def test_deep_merge_later_scalar_wins():
    assert cs.deep_merge({"a": 1}, {"a": 2}) == {"a": 2}


def test_deep_merge_recurses_into_nested_dicts():
    out = cs.deep_merge(
        {"marker": {"size": 9, "opacity": 0.85}},
        {"marker": {"opacity": 0.5}},
    )
    # opacity overridden, size inherited
    assert out == {"marker": {"size": 9, "opacity": 0.5}}


def test_deep_merge_list_replaces_not_element_merges():
    out = cs.deep_merge({"palette": ["#a", "#b", "#c"]}, {"palette": ["#x"]})
    assert out == {"palette": ["#x"]}


def test_deep_merge_skips_non_dict_layers():
    assert cs.deep_merge({"a": 1}, None, "nope", {"b": 2}) == {"a": 1, "b": 2}


def test_deep_merge_does_not_mutate_inputs():
    base = {"marker": {"size": 9}}
    cs.deep_merge(base, {"marker": {"size": 3}})
    assert base == {"marker": {"size": 9}}, "input layer was mutated"


# ---------------------------------------------------------------------------
# instance_key (C1)
# ---------------------------------------------------------------------------

def test_instance_key_format_and_lowercasing():
    assert cs.instance_key("UMAP", "Liver", "Male") == "liver|male|umap"


def test_instance_key_tolerates_empty_segments():
    assert cs.instance_key("umap", "", "") == "||umap"


# ---------------------------------------------------------------------------
# resolve_chart_style — the four-layer precedence
# ---------------------------------------------------------------------------

BUILTIN = {
    "width": 900,
    "palette": ["#base1", "#base2"],
    "marker": {"size": 9, "opacity": 0.85},
    "legend": {"font_size": 9},
}


def test_resolve_with_no_config_returns_builtin():
    out = cs.resolve_chart_style(None, "umap", "liver", "male", BUILTIN)
    assert out == BUILTIN
    assert out is not BUILTIN  # fresh copy


def test_resolve_defaults_layer_applies_to_every_chart():
    cfg = {"defaults": {"paper_bgcolor": "#fff"}}
    out = cs.resolve_chart_style(cfg, "umap", "liver", "male", BUILTIN)
    assert out["paper_bgcolor"] == "#fff"
    assert out["width"] == 900  # inherited from builtin


def test_resolve_type_layer_overrides_defaults():
    cfg = {
        "defaults": {"width": 800},
        "types": {"cluster": {"width": 1000}},
    }
    umap = cs.resolve_chart_style(cfg, "umap", "liver", "male", BUILTIN)
    cluster = cs.resolve_chart_style(cfg, "cluster", "liver", "male", BUILTIN)
    assert umap["width"] == 800       # only the defaults layer touched umap
    assert cluster["width"] == 1000   # the type layer won for cluster


def test_resolve_instance_layer_is_highest_precedence():
    cfg = {
        "defaults": {"width": 800},
        "types": {"umap": {"width": 850}},
        "instances": {"liver|male|umap": {"width": 700}},
    }
    out = cs.resolve_chart_style(cfg, "umap", "liver", "male", BUILTIN)
    assert out["width"] == 700


def test_instance_overrides_single_nested_leaf_inherits_siblings():
    # The headline per-instance requirement: override marker.size for ONE
    # chart, inherit marker.opacity and everything else.
    cfg = {"instances": {"liver|male|umap": {"marker": {"size": 14}}}}
    out = cs.resolve_chart_style(cfg, "umap", "liver", "male", BUILTIN)
    assert out["marker"] == {"size": 14, "opacity": 0.85}
    assert out["legend"] == {"font_size": 9}  # untouched group intact


def test_two_instances_of_same_type_resolve_independently():
    cfg = {
        "instances": {
            "liver|male|umap": {"palette": ["#liver"]},
            "kidney|female|umap": {"palette": ["#kidney"]},
        }
    }
    liver = cs.resolve_chart_style(cfg, "umap", "liver", "male", BUILTIN)
    kidney = cs.resolve_chart_style(cfg, "umap", "kidney", "female", BUILTIN)
    other = cs.resolve_chart_style(cfg, "umap", "lung", "male", BUILTIN)
    assert liver["palette"] == ["#liver"]
    assert kidney["palette"] == ["#kidney"]
    assert other["palette"] == ["#base1", "#base2"]  # no instance → builtin


def test_resolve_does_not_mutate_builtin_or_cfg():
    cfg = {"instances": {"liver|male|umap": {"marker": {"size": 99}}}}
    cs.resolve_chart_style(cfg, "umap", "liver", "male", BUILTIN)
    assert BUILTIN["marker"] == {"size": 9, "opacity": 0.85}
    assert cfg["instances"]["liver|male|umap"] == {"marker": {"size": 99}}


# ---------------------------------------------------------------------------
# unknown_style_keys — typo catcher
# ---------------------------------------------------------------------------

def test_unknown_style_keys_flags_top_level_and_nested_typos():
    style = {
        "width": 900,
        "widht": 900,                       # typo
        "marker": {"size": 9, "opacty": 1}, # nested typo
    }
    bad = cs.unknown_style_keys(style)
    assert "widht" in bad
    assert "marker.opacty" in bad
    assert "width" not in bad
    assert "marker.size" not in bad
