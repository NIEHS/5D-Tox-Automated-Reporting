"""
narrative/model_policy.py — which models may receive a study's data.

A published study (narrative.prompt_workshop.report_of names its published
report) may go to any model the gateway serves. An unpublished study may only
go to a model matching `unpublished_allowed` in narrative/model_policy.yaml.
Every model call that carries study data checks here first and raises
ModelNotAllowed rather than send it.
"""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

import yaml

POLICY_PATH = Path(__file__).with_name("model_policy.yaml")


class ModelNotAllowed(ValueError):
    """A model the policy does not allow for this study's data."""


def patterns() -> list[str]:
    doc = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8")) or {}
    return [str(p) for p in doc.get("unpublished_allowed") or []]


def is_published(dtxsid: str) -> bool:
    from narrative.prompt_workshop import report_of
    return report_of(dtxsid)[0] is not None


def allowed(dtxsid: str, model: str, *, published: bool | None = None) -> bool:
    if published is None:
        published = is_published(dtxsid)
    return published or any(fnmatch(model, p) for p in patterns())


def check(dtxsid: str, models: list[str]) -> None:
    """Raise ModelNotAllowed naming every model this study may not use."""
    published = is_published(dtxsid)
    refused = [m for m in models if not allowed(dtxsid, m, published=published)]
    if refused:
        raise ModelNotAllowed(
            f"{dtxsid} is unpublished; its data may only go to models matching "
            f"{patterns()} (narrative/model_policy.yaml). Not allowed: {', '.join(refused)}")
