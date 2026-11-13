"""
content_registry (ADR-0021 F) — the open content-KIND catalog for concern [2].

prepare_content used to be a hardcoded call sequence (3.5a→3.5b→3.5c→3.5d).
F makes it an OPEN registry: each content kind declares its name, prep method,
and `after` deps; a stable topological driver runs them. These tests pin:
  * the built-in kinds register and plan in today's exact order (byte-identity);
  * `after` deps are respected and the tiebreak is registration order;
  * a dependency cycle / unknown-dep raises loudly (no silently dropped step);
  * the driver awaits async prep methods and runs sync ones, in plan order;
  * a late registration inserts without editing prepare_content.
"""

import pytest

from pipeline.content_registry import (
    ContentKind,
    register_content_kind,
    unregister_content_kind,
    content_registry,
    build_content_plan,
    run_content_plan,
)


# Importing process_integrated registers the four built-ins at module import.
import pipeline.process_integrated  # noqa: F401


_BUILTINS = ["genomics-llm", "genomics-body", "apical-bmd", "references"]


def test_builtins_register_and_plan_in_todays_order():
    """The built-ins reproduce the exact pre-registry sequence 3.5a→3.5b→3.5c→3.5d
    — the property that keeps the payload byte-identical."""
    reg = content_registry()
    for name in _BUILTINS:
        assert name in reg
    plan = [k.name for k in build_content_plan()]
    assert plan == _BUILTINS


def test_after_deps_are_respected():
    """genomics-body and references must both run after genomics-llm; apical-bmd
    has no constraint. Any valid plan honors the edges regardless of the tiebreak."""
    plan = [k.name for k in build_content_plan()]
    assert plan.index("genomics-llm") < plan.index("genomics-body")
    assert plan.index("genomics-llm") < plan.index("references")


def _isolated_registry(kinds):
    """Build a plan over an explicit registry dict (does not touch the module one)."""
    return [k.name for k in build_content_plan({k.name: k for k in kinds})]


def test_plan_tiebreak_is_registration_order():
    """Among kinds with no dependency between them, the earliest-registered wins —
    the stable tiebreak that makes the plan deterministic."""
    a = ContentKind("a", prepare=lambda ctx: None)
    b = ContentKind("b", prepare=lambda ctx: None)
    c = ContentKind("c", prepare=lambda ctx: None)
    # dict preserves insertion order → a, b, c
    assert _isolated_registry([a, b, c]) == ["a", "b", "c"]


def test_after_dep_overrides_registration_order():
    first = ContentKind("first", prepare=lambda ctx: None, after=("second",))
    second = ContentKind("second", prepare=lambda ctx: None)
    # `first` is registered first but depends on `second`, so `second` runs first.
    assert _isolated_registry([first, second]) == ["second", "first"]


def test_unknown_dependency_raises():
    lonely = ContentKind("lonely", prepare=lambda ctx: None, after=("ghost",))
    with pytest.raises(ValueError, match="unknown kind 'ghost'"):
        build_content_plan({"lonely": lonely})


def test_dependency_cycle_raises():
    x = ContentKind("x", prepare=lambda ctx: None, after=("y",))
    y = ContentKind("y", prepare=lambda ctx: None, after=("x",))
    with pytest.raises(ValueError, match="cycle"):
        build_content_plan({"x": x, "y": y})


@pytest.mark.asyncio
async def test_driver_runs_sync_and_async_in_plan_order():
    """run_content_plan awaits async prep methods and calls sync ones, in the
    planned dependency order, mutating the shared ctx."""
    order: list[str] = []

    async def a_async(ctx):
        order.append("a")

    def b_sync(ctx):
        order.append("b")

    async def c_async(ctx):
        order.append("c")

    reg = {
        "a": ContentKind("a", prepare=a_async),
        "b": ContentKind("b", prepare=b_sync, after=("a",)),
        "c": ContentKind("c", prepare=c_async, after=("b",)),
    }
    await run_content_plan(object(), reg)
    assert order == ["a", "b", "c"]


def test_late_registration_inserts_without_editing_callers():
    """A new kind registers into the live module registry and appears in the plan
    — the whole point of an open registry. Cleaned up so other tests are unaffected."""
    try:
        register_content_kind(
            "extra-figure", lambda ctx: None, after=("apical-bmd",)
        )
        plan = [k.name for k in build_content_plan()]
        assert "extra-figure" in plan
        assert plan.index("apical-bmd") < plan.index("extra-figure")
    finally:
        unregister_content_kind("extra-figure")
    assert "extra-figure" not in content_registry()
