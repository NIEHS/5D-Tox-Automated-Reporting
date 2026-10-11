"""
chart_registry.py — the chart-type catalog (WP-2 of the configurable-charts
feature).

Mirrors the design of ``render_capabilities.COMPONENT_CATALOG``: an unordered,
frozen-dataclass registry keyed by type-name that is the SINGLE coupling point
between "what chart types exist" and the render pipeline.  It imports nothing
from the renderers, so the dependency points one way (renderer → here).

Two kinds of chart type
-----------------------
  - **Code-registered (custom)** — e.g. ``umap`` and ``cluster``.  Their figures
    need bespoke Python (UMAP joins a precomputed reference embedding; cluster
    does jitter / background bands / custom y-ticks), so they are built by a
    registered ``builder`` function.  A document template may NOT declare or
    override a code type (loud ``ValueError``) — that keeps the two shipped
    charts golden-stable.

  - **Data-driven** — declared entirely in the document config's ``chart_types``
    block (``trace`` + column bindings, see chart_style / the generic builder).
    No Python.  ``builder is None``; the single generic builder consumes
    ``spec``.

The boundary is therefore crisp and enforced: ``name in _BUILTIN_CHART_TYPES``
⇒ code (builder filled by WP-3 via :func:`register_builder`); everything else ⇒
data-driven, sourced from YAML.

Owns contract **C3** (the ``ChartType`` shape).  The umap/cluster ``builder``
callables and their ``style_defaults`` are attached at import time by
genomics_viz (WP-3) through :func:`register_builder` / :func:`set_style_defaults`
— late binding avoids a circular import (genomics_viz imports this module).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Callable


# ---------------------------------------------------------------------------
# The chart-type record (contract C3)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChartType:
    """
    One entry in the chart-type catalog.

    Fields:
        name:            the type id ("umap", "cluster", "bmd-bar") — the
                         ``key`` carried on each attached chart payload and the
                         ``<organ>|<sex>|<type>`` instance-key suffix.
        builder:         the Python figure builder for a CODE type (returns a
                         plotly ``go.Figure``; signature is contract C4).  None
                         for a data-driven type (the generic builder handles it
                         from ``spec``).
        spec:            the data-driven declaration (trace kind + column
                         bindings + axes/layout/caption) for a data type; empty
                         for a code type.
        needs_umap_ref:  True when the builder needs the precomputed UMAP
                         reference embedding passed in (umap only).
        style_defaults:  this type's layer-0 built-in style (the values that,
                         with no YAML config, reproduce today's render exactly).
                         Read by chart_style.resolve_chart_style as the base
                         layer.
        caption_template: default caption format string
                         ({organ_title}/{sex_title}/${dose_unit} substitution).
    """
    name: str
    builder: Callable | None = None
    spec: dict = field(default_factory=dict)
    needs_umap_ref: bool = False
    style_defaults: dict = field(default_factory=dict)
    caption_template: str = ""

    @property
    def is_code(self) -> bool:
        """A code-registered (custom-builder) type, vs a data-driven one.

        Keyed on NAME RESERVATION (``_CODE_TYPE_NAMES``), not the momentary
        ``builder`` state: umap/cluster are code types even in the window before
        WP-3's import-time :func:`register_builder` binds their callables.  This
        guarantees a built-in never gets misrouted to the generic data-driven
        builder if binding is missing — it would raise "no builder" loudly
        instead of silently mis-rendering.
        """
        return self.name in _CODE_TYPE_NAMES

    @property
    def kind(self) -> str:
        """\"code\" or \"data\" — the JS registry payload's ``type`` field (C8)."""
        return "code" if self.is_code else "data"

    @property
    def resolved_builder(self) -> Callable | None:
        """
        The live builder for this type.

        For a code type (``is_code``), the builder is looked up from the
        module-level ``_BUILTIN_CHART_TYPES`` *at access time* rather than trusting
        ``self.builder``.  This matters because a ChartType can be constructed
        (e.g. by ``build_registry`` inside ``load_chart_types``) in the import
        window *before* genomics_viz has run its ``register_builder`` calls — such
        an instance captures ``builder=None`` permanently and would otherwise be
        silently misrouted to the generic data-driven builder, producing a blank
        chart.  Resolving against the live registry makes binding independent of
        import order.  Data-driven types return their own (always-None) builder.
        """
        if self.is_code:
            live = _BUILTIN_CHART_TYPES.get(self.name)
            if live is not None and live.builder is not None:
                return live.builder
        return self.builder

    @property
    def has_builder(self) -> bool:
        """Whether a Python figure builder is actually bound (runtime check)."""
        return self.resolved_builder is not None


# ---------------------------------------------------------------------------
# The built-in (code-registered) chart types
# ---------------------------------------------------------------------------
# umap and cluster are declared here with builder=None as PLACEHOLDERS; their
# real builder callables and style_defaults are attached at import time by
# genomics_viz (WP-3) via register_builder()/set_style_defaults().  They are
# "code" types regardless: membership in this dict — not the momentary
# builder-None state during import — is what marks a name as code-reserved
# (see _CODE_TYPE_NAMES).  This late binding breaks the genomics_viz ↔
# chart_registry import cycle.
_BUILTIN_CHART_TYPES: dict[str, ChartType] = {
    "umap": ChartType(name="umap", needs_umap_ref=True),
    "cluster": ChartType(name="cluster"),
}

# The set of names reserved for code types.  Fixed at module load from the
# built-in keys; a YAML chart_types block may not use any of these.
_CODE_TYPE_NAMES: frozenset[str] = frozenset(_BUILTIN_CHART_TYPES)


def register_builder(
    name: str,
    builder: Callable,
    *,
    style_defaults: dict | None = None,
    caption_template: str | None = None,
) -> None:
    """
    Attach the real builder (and optionally style defaults / caption) to a
    built-in code type.  Called by genomics_viz at import time (WP-3).

    Raises KeyError if ``name`` is not a declared built-in code type — a code
    builder must correspond to a reserved name, so a typo fails loudly rather
    than silently creating an unreserved type.
    """
    if name not in _BUILTIN_CHART_TYPES:
        raise KeyError(
            f"register_builder: {name!r} is not a built-in code chart type "
            f"(known: {sorted(_BUILTIN_CHART_TYPES)})"
        )
    current = _BUILTIN_CHART_TYPES[name]
    updates: dict = {"builder": builder}
    if style_defaults is not None:
        updates["style_defaults"] = style_defaults
    if caption_template is not None:
        updates["caption_template"] = caption_template
    _BUILTIN_CHART_TYPES[name] = replace(current, **updates)


def set_style_defaults(name: str, style_defaults: dict) -> None:
    """Set/replace a built-in type's layer-0 style defaults (WP-3 helper)."""
    if name not in _BUILTIN_CHART_TYPES:
        raise KeyError(f"set_style_defaults: unknown built-in type {name!r}")
    _BUILTIN_CHART_TYPES[name] = replace(
        _BUILTIN_CHART_TYPES[name], style_defaults=style_defaults
    )


# ---------------------------------------------------------------------------
# Building the effective registry (built-ins + YAML data types)
# ---------------------------------------------------------------------------

# Allowed trace kinds for a data-driven type's ``spec.trace``.
_VALID_TRACES: frozenset[str] = frozenset({"scatter", "bar", "line"})
# Spec keys a data-driven type MUST supply.
_REQUIRED_SPEC_KEYS: tuple[str, ...] = ("trace", "x", "y")


def validate_data_spec(name: str, spec: dict) -> None:
    """
    Reject a malformed data-driven chart-type spec loudly (mirrors the
    document_template validator discipline).

    Checks: name does not collide with a code type; spec is a mapping; required
    keys (trace/x/y) present and non-empty; trace ∈ {scatter,bar,line}.
    """
    if name in _CODE_TYPE_NAMES:
        raise ValueError(
            f"chart_types: {name!r} collides with a built-in code chart type; "
            f"code types may not be declared or overridden in the template"
        )
    if not isinstance(spec, dict):
        raise ValueError(
            f"chart_types[{name!r}] must be a mapping, got {type(spec).__name__}"
        )
    for k in _REQUIRED_SPEC_KEYS:
        if not spec.get(k):
            raise ValueError(
                f"chart_types[{name!r}] is missing required key {k!r}"
            )
    trace = spec["trace"]
    if trace not in _VALID_TRACES:
        raise ValueError(
            f"chart_types[{name!r}]: trace {trace!r} must be one of "
            f"{sorted(_VALID_TRACES)}"
        )


def build_registry(chart_types_cfg: dict | None = None) -> dict[str, ChartType]:
    """
    Return the effective chart-type registry: the built-in code types merged
    with the data-driven types declared in the document config's
    ``chart_types`` block.

    ``chart_types_cfg`` maps type-name → data spec.  Each is validated
    (:func:`validate_data_spec`) — a name colliding with a code type, or a
    malformed spec, raises.  Absent/empty config ⇒ just the built-ins (today's
    behaviour).

    The returned dict is a fresh copy; the module-level built-ins are not
    mutated by callers.
    """
    registry: dict[str, ChartType] = dict(_BUILTIN_CHART_TYPES)
    for name, spec in (chart_types_cfg or {}).items():
        validate_data_spec(name, spec)
        registry[name] = ChartType(
            name=name,
            builder=None,                       # data-driven → generic builder
            spec=dict(spec),
            style_defaults=dict(spec.get("layout") or {}),
            caption_template=str(spec.get("caption") or ""),
        )
    return registry


def default_registry() -> dict[str, ChartType]:
    """The built-in code types only (no YAML) — the no-config default."""
    return dict(_BUILTIN_CHART_TYPES)


def registry_payload(registry: dict[str, ChartType]) -> list[dict]:
    """
    The serializable form injected to the browser as ``window.__CHART_REGISTRY__``
    (contract C8): one entry per type with its name, kind, and (for data types)
    spec.  Code types carry no spec (their builder is server-side only).
    """
    out: list[dict] = []
    for ct in registry.values():
        entry = {"name": ct.name, "type": ct.kind}
        if ct.kind == "data":
            entry["spec"] = ct.spec
        out.append(entry)
    return out
