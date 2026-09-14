"""
content_registry.py — the content-KIND catalog for concern [2] (ADR-0021 F).

Content preparation reduces processed data ([1]) into document CONTENT: genomics
prose, the apical BMD narrative, the reference list, and — in the future —
figure/chart kinds "yet to be defined" (ADR-0021 §[2]). This module makes that
set an OPEN registry rather than a hardcoded call sequence: each content kind
declares its NAME, its prep METHOD, and the kinds it must run AFTER, and the
driver runs them in a stable dependency order. A new kind registers without
editing a switch — the prep-side twin of the node-type→render dispatch
(``render_capabilities.COMPONENT_CATALOG``) and the chart-type registry
(``genomics.chart_registry``), which this deliberately mirrors.

Late binding (like ``chart_registry`` / ``genomics_viz``): this module imports
NOTHING from ``pipeline.process_integrated``. The built-in kinds are registered
FROM there at its import time (it owns the ``_build_*`` methods + the
``ProcessContext``), so the dependency points one way (process_integrated →
here) and there is no cycle.

A prep method is any callable ``(ctx) -> None | Awaitable[None]`` that mutates
the shared ``ProcessContext`` (or performs a persisted side effect). Sync and
async methods are both supported: the driver awaits the return value when it is
awaitable, so a kind's record stays about WHAT it is (name + deps), not HOW it
runs.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Awaitable, Callable


# ---------------------------------------------------------------------------
# The content-kind record
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ContentKind:
    """One entry in the content-kind catalog.

    Fields:
        name:    the kind id ("genomics-llm", "apical-bmd", ...) — unique key.
        prepare: the prep method, ``(ctx) -> None | Awaitable[None]``. It reads
                 processed data + declarations off ``ctx`` and writes the content
                 back onto ``ctx`` (or persists a side effect, e.g. references).
                 Sync or async; the driver awaits an awaitable return.
        after:   names of kinds that MUST have run before this one — the
                 declarative dependency edges (e.g. genomics body narratives read
                 the LLM narratives that "genomics-llm" produced). Empty = no
                 ordering constraint. The driver topologically sorts on these.
    """
    name: str
    prepare: Callable[..., None | Awaitable[None]]
    after: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# The registry (insertion-ordered; registration order is the stable tiebreak)
# ---------------------------------------------------------------------------

_CONTENT_KINDS: dict[str, ContentKind] = {}


def register_content_kind(
    name: str,
    prepare: Callable[..., None | Awaitable[None]],
    *,
    after: tuple[str, ...] | list[str] = (),
) -> None:
    """Register a content kind (idempotent-replace by name).

    Called at import time by ``pipeline.process_integrated`` for the built-ins,
    and available to any extension that adds a new content kind. Registration
    ORDER is preserved (Python dicts are insertion-ordered) and used as the
    stable tiebreak among kinds with no dependency between them — so registering
    the built-ins in today's execution order reproduces that order exactly.

    Re-registering an existing name replaces it in place (keeps its original
    ordering slot) — an extension may override a built-in method without
    reshuffling the plan.
    """
    kind = ContentKind(name=name, prepare=prepare, after=tuple(after))
    _CONTENT_KINDS[name] = kind


def unregister_content_kind(name: str) -> None:
    """Remove a kind (no-op if absent). For tests / dynamic reconfiguration."""
    _CONTENT_KINDS.pop(name, None)


def content_registry() -> dict[str, ContentKind]:
    """A shallow copy of the live registry (built-ins + any late registrations),
    in registration order. Callers get a stable snapshot they can plan over."""
    return dict(_CONTENT_KINDS)


# ---------------------------------------------------------------------------
# Planning (stable topological order) + driving
# ---------------------------------------------------------------------------

def build_content_plan(
    registry: dict[str, ContentKind] | None = None,
) -> list[ContentKind]:
    """Return the content kinds in a STABLE dependency order.

    A kind runs only after every name in its ``after`` has run; among kinds that
    are simultaneously ready, the earliest-REGISTERED goes first. That stable
    tiebreak makes the plan deterministic — with the built-ins registered in
    today's execution order and their real deps, this reproduces the exact
    pre-registry sequence (so the payload stays byte-identical).

    Raises ValueError on a dependency cycle or a reference to an unregistered
    kind — a loud failure rather than a silently dropped step.
    """
    reg = content_registry() if registry is None else dict(registry)

    # Validate every `after` names a known kind (catch typos loudly).
    for kind in reg.values():
        for dep in kind.after:
            if dep not in reg:
                raise ValueError(
                    f"content kind {kind.name!r} depends on unknown kind {dep!r} "
                    f"(known: {sorted(reg)})"
                )

    done: set[str] = set()
    plan: list[ContentKind] = []
    # Kahn's algorithm with a registration-ordered scan: each pass appends every
    # currently-ready kind in registration order. Deterministic and stable.
    while len(plan) < len(reg):
        progressed = False
        for name, kind in reg.items():          # registration order
            if name in done:
                continue
            if all(dep in done for dep in kind.after):
                plan.append(kind)
                done.add(name)
                progressed = True
        if not progressed:
            unplaced = [n for n in reg if n not in done]
            raise ValueError(
                f"content-kind dependency cycle among {sorted(unplaced)}"
            )
    return plan


async def run_content_plan(
    ctx,
    registry: dict[str, ContentKind] | None = None,
) -> None:
    """Run every registered content kind against ``ctx`` in dependency order.

    Each kind's ``prepare(ctx)`` is called in turn; an awaitable return is
    awaited (so sync and async prep methods interleave transparently). Kinds run
    SEQUENTIALLY in the planned order — preserving today's behavior exactly.
    (Running mutually-independent kinds concurrently is a future optimization the
    dependency graph now makes safe to express, but is intentionally not done
    here to keep this byte-identical.)
    """
    for kind in build_content_plan(registry):
        result = kind.prepare(ctx)
        if inspect.isawaitable(result):
            await result
