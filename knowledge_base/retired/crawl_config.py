"""
Serialization + provenance layer for the literature-crawl configuration.

`GovernorConfig` (citegraph.py) is the source of truth for the crawl spec, but it
is pure Python with no JSON form. This module gives it one, so the config can be
edited in the UI and persisted per session — and it freezes today's Python defaults
as an immutable "original" that the human's edits are tracked against.

Editable surface (this cut): the nine governor scalars plus `topic_keywords` and
`organ_keywords`. `known_genes` is intentionally excluded — it is loaded at runtime
from `citegraph_output/gene_consensus.json`, not authored by a human.
"""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path

from knowledge_base.citegraph import GovernorConfig

# The keys this cut exposes for editing. `known_genes` and `organ_boost_keywords`
# are omitted: the former is runtime-derived, the latter is set per organ-crawl.
SCALAR_FIELDS = (
    "max_depth",
    "max_papers",
    "max_api_calls",
    "relevance_threshold",
    "saturation_window",
    "saturation_threshold",
    "max_refs_per_paper",
    "max_cites_per_paper",
    "rate_limit_delay",
)
LIST_FIELDS = ("topic_keywords",)
DICT_FIELDS = ("organ_keywords",)
EDITABLE_KEYS = SCALAR_FIELDS + LIST_FIELDS + DICT_FIELDS

_ORIGINAL_PATH = Path(__file__).with_name("crawl_config_original.json")


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def config_to_dict(cfg: GovernorConfig) -> dict:
    """Serialize the editable surface of a GovernorConfig to a plain dict."""
    out: dict = {}
    for f in fields(cfg):
        if f.name not in EDITABLE_KEYS:
            continue
        out[f.name] = getattr(cfg, f.name)
    # Deep-copy the containers so callers can't mutate the config's internals.
    out["topic_keywords"] = list(out["topic_keywords"])
    out["organ_keywords"] = {k: list(v) for k, v in out["organ_keywords"].items()}
    return out


def config_from_dict(d: dict) -> GovernorConfig:
    """Build a GovernorConfig from a dict, filling any missing keys from defaults.

    Only the editable keys are read from `d`; runtime-derived fields
    (`known_genes`) keep their default so the returned config is still runnable.
    """
    cfg = GovernorConfig()
    for key in SCALAR_FIELDS:
        if key in d:
            setattr(cfg, key, d[key])
    if "topic_keywords" in d:
        cfg.topic_keywords = list(d["topic_keywords"])
    if "organ_keywords" in d:
        cfg.organ_keywords = {k: list(v) for k, v in d["organ_keywords"].items()}
    return cfg


# ---------------------------------------------------------------------------
# Frozen original (the immutable baseline)
# ---------------------------------------------------------------------------
def _default_config_dict() -> dict:
    """The editable surface of the current Python defaults."""
    return config_to_dict(GovernorConfig())


def load_original() -> dict:
    """Load the committed frozen baseline, falling back to live defaults.

    The committed JSON is the authoritative immutable original; the fallback
    keeps the module usable before the file is frozen for the first time.
    """
    if _ORIGINAL_PATH.exists():
        try:
            return json.loads(_ORIGINAL_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return _default_config_dict()


ORIGINAL_CRAWL_CONFIG: dict = load_original()


def freeze_original() -> Path:
    """Write today's Python defaults to the committed original JSON. Run once."""
    _ORIGINAL_PATH.write_text(json.dumps(_default_config_dict(), indent=2) + "\n")
    return _ORIGINAL_PATH


# ---------------------------------------------------------------------------
# Validation (validate-before-write gate)
# ---------------------------------------------------------------------------
def validate_config(d: dict) -> None:
    """Raise ValueError if the config dict is malformed. No return on success."""
    if not isinstance(d, dict):
        raise ValueError("config must be a mapping")

    positive_ints = ("max_depth", "max_papers", "max_api_calls",
                     "saturation_window", "max_refs_per_paper", "max_cites_per_paper")
    for key in positive_ints:
        if key in d:
            v = d[key]
            if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
                raise ValueError(f"{key} must be a positive integer (got {v!r})")

    for key in ("relevance_threshold", "saturation_threshold"):
        if key in d:
            v = d[key]
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not (0.0 <= v <= 1.0):
                raise ValueError(f"{key} must be a number in [0, 1] (got {v!r})")

    if "rate_limit_delay" in d:
        v = d["rate_limit_delay"]
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0:
            raise ValueError(f"rate_limit_delay must be a non-negative number (got {v!r})")

    if "topic_keywords" in d:
        kw = d["topic_keywords"]
        if not isinstance(kw, list) or not all(isinstance(x, str) for x in kw):
            raise ValueError("topic_keywords must be a list of strings")
        if not [x for x in kw if x.strip()]:
            raise ValueError("topic_keywords must not be empty")

    if "organ_keywords" in d:
        ok = d["organ_keywords"]
        if not isinstance(ok, dict):
            raise ValueError("organ_keywords must be a mapping of organ -> [keywords]")
        for organ, terms in ok.items():
            if not isinstance(organ, str) or not organ.strip():
                raise ValueError(f"organ name must be a non-empty string (got {organ!r})")
            if not isinstance(terms, list) or not all(isinstance(x, str) for x in terms):
                raise ValueError(f"organ_keywords[{organ!r}] must be a list of strings")


# ---------------------------------------------------------------------------
# Diff against the original (the "what did the human do" record)
# ---------------------------------------------------------------------------
def diff_against_original(d: dict, original: dict | None = None) -> dict:
    """Report which editable fields differ from the frozen original.

    Shape:
      scalars           -> {"original": <o>, "current": <c>}
      topic_keywords    -> {"added": [...], "removed": [...]}
      organ_keywords    -> {"added": {organ: [...]}, "removed": {organ: [...]},
                            "changed": {organ: {"added": [...], "removed": [...]}}}
    Returns {} when the config is identical to the original.
    """
    base = original if original is not None else ORIGINAL_CRAWL_CONFIG
    diff: dict = {}

    for key in SCALAR_FIELDS:
        o, c = base.get(key), d.get(key)
        if key in d and o != c:
            diff[key] = {"original": o, "current": c}

    if "topic_keywords" in d:
        o = list(base.get("topic_keywords", []))
        c = list(d["topic_keywords"])
        added = [x for x in c if x not in o]
        removed = [x for x in o if x not in c]
        if added or removed:
            diff["topic_keywords"] = {"added": added, "removed": removed}

    if "organ_keywords" in d:
        o_map = base.get("organ_keywords", {}) or {}
        c_map = d["organ_keywords"] or {}
        added_organs = {k: list(v) for k, v in c_map.items() if k not in o_map}
        removed_organs = {k: list(v) for k, v in o_map.items() if k not in c_map}
        changed: dict = {}
        for organ in set(o_map) & set(c_map):
            o_terms, c_terms = list(o_map[organ]), list(c_map[organ])
            a = [x for x in c_terms if x not in o_terms]
            r = [x for x in o_terms if x not in c_terms]
            if a or r:
                changed[organ] = {"added": a, "removed": r}
        entry: dict = {}
        if added_organs:
            entry["added"] = added_organs
        if removed_organs:
            entry["removed"] = removed_organs
        if changed:
            entry["changed"] = changed
        if entry:
            diff["organ_keywords"] = entry

    return diff


if __name__ == "__main__":
    import sys
    if "--freeze" in sys.argv:
        path = freeze_original()
        print(f"froze original crawl config -> {path}")
    else:
        print(json.dumps(_default_config_dict(), indent=2))
