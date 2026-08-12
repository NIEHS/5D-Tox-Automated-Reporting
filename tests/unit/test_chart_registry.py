"""
Unit tests for chart_registry.py (WP-2) — the chart-type catalog.

Pins contract C3 and the code-vs-data boundary:
  - the default registry has the built-in code types (umap, cluster);
  - a YAML data-driven type round-trips its spec and is marked "data";
  - a YAML name colliding with a code type is rejected loudly;
  - malformed specs (missing trace/x/y, bad trace kind) are rejected;
  - late binding of a code builder works and flips is_code/kind.
"""

import importlib

import pytest

import genomics.chart_registry as cr


@pytest.fixture
def fresh_registry_module():
    """Reload the module so late-binding tests don't leak builder state across
    tests (register_builder mutates module-level built-ins)."""
    importlib.reload(cr)
    yield cr
    importlib.reload(cr)


# ---------------------------------------------------------------------------
# Default registry — the built-in code types
# ---------------------------------------------------------------------------

def test_default_registry_has_umap_and_cluster():
    reg = cr.default_registry()
    assert set(reg) == {"umap", "cluster"}
    assert reg["umap"].needs_umap_ref is True
    assert reg["cluster"].needs_umap_ref is False


def test_build_registry_without_config_equals_builtins():
    assert set(cr.build_registry()) == {"umap", "cluster"}
    assert set(cr.build_registry(None)) == {"umap", "cluster"}
    assert set(cr.build_registry({})) == {"umap", "cluster"}


# ---------------------------------------------------------------------------
# Data-driven types from YAML
# ---------------------------------------------------------------------------

BMD_BAR = {
    "trace": "bar",
    "x": "go_term",
    "y": "bmd",
    "color": "direction",
    "layout": {"width": 1000, "height": 500},
    "caption": "BMD per GO term — {organ_title} ({sex_title}).",
}


def test_data_driven_type_round_trips_spec():
    reg = cr.build_registry({"bmd-bar": BMD_BAR})
    assert set(reg) == {"umap", "cluster", "bmd-bar"}
    bar = reg["bmd-bar"]
    assert bar.builder is None
    assert bar.is_code is False
    assert bar.kind == "data"
    assert bar.spec["trace"] == "bar"
    assert bar.spec["x"] == "go_term"
    # layout/caption are lifted onto the convenience fields
    assert bar.style_defaults == {"width": 1000, "height": 500}
    assert "{organ_title}" in bar.caption_template


def test_builtin_types_are_code_kind_by_name_reservation():
    # is_code/kind key on NAME reservation, not on whether a builder has been
    # bound — so a built-in is "code" regardless of binding state.  This holds
    # whether or not genomics_viz (which binds the real builders at import time)
    # has been imported into the process, so it's order-independent.
    reg = cr.build_registry()
    assert reg["umap"].is_code is True
    assert reg["umap"].kind == "code"
    assert reg["cluster"].kind == "code"


def test_builtin_has_builder_false_before_binding(fresh_registry_module):
    # has_builder is the separate RUNTIME check: None until a builder is bound.
    # Use the reload fixture so the built-ins are in their pristine unbound state
    # (genomics_viz's import-time register_builder mutates the shared module-
    # level dict, so without the reload this depends on import order).
    reg = fresh_registry_module.build_registry()
    assert reg["umap"].has_builder is False
    assert reg["cluster"].has_builder is False


# ---------------------------------------------------------------------------
# Code-vs-data boundary enforcement
# ---------------------------------------------------------------------------

def test_yaml_name_colliding_with_code_type_raises():
    with pytest.raises(ValueError, match="collides with a built-in code chart type"):
        cr.build_registry({"umap": {"trace": "scatter", "x": "a", "y": "b"}})
    with pytest.raises(ValueError, match="collides"):
        cr.build_registry({"cluster": {"trace": "bar", "x": "a", "y": "b"}})


def test_missing_required_spec_keys_raise():
    for bad in (
        {"x": "a", "y": "b"},               # no trace
        {"trace": "bar", "y": "b"},         # no x
        {"trace": "bar", "x": "a"},         # no y
    ):
        with pytest.raises(ValueError, match="missing required key"):
            cr.build_registry({"new": bad})


def test_invalid_trace_kind_raises():
    with pytest.raises(ValueError, match="must be one of"):
        cr.build_registry({"new": {"trace": "pie", "x": "a", "y": "b"}})


def test_non_mapping_spec_raises():
    with pytest.raises(ValueError, match="must be a mapping"):
        cr.build_registry({"new": ["not", "a", "dict"]})


# ---------------------------------------------------------------------------
# Late binding of a code builder (WP-3 seam)
# ---------------------------------------------------------------------------

def test_register_builder_attaches_and_flips_kind(fresh_registry_module):
    m = fresh_registry_module

    def fake_umap_builder(*a, **k):
        return "FIG"

    m.register_builder("umap", fake_umap_builder,
                       style_defaults={"width": 900}, caption_template="cap")
    reg = m.build_registry()
    assert reg["umap"].builder is fake_umap_builder
    assert reg["umap"].is_code is True
    assert reg["umap"].kind == "code"
    assert reg["umap"].style_defaults == {"width": 900}
    assert reg["umap"].caption_template == "cap"


def test_register_builder_unknown_name_raises(fresh_registry_module):
    with pytest.raises(KeyError, match="not a built-in code chart type"):
        fresh_registry_module.register_builder("nope", lambda *a, **k: None)


# ---------------------------------------------------------------------------
# JS payload (contract C8)
# ---------------------------------------------------------------------------

def test_registry_payload_shape():
    reg = cr.build_registry({"bmd-bar": BMD_BAR})
    payload = cr.registry_payload(reg)
    by_name = {p["name"]: p for p in payload}
    assert by_name["umap"]["type"] == "code"
    assert "spec" not in by_name["umap"]          # code types ship no spec
    assert by_name["bmd-bar"]["type"] == "data"
    assert by_name["bmd-bar"]["spec"]["trace"] == "bar"
