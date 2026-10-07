"""
pipeline/method_profile.py — analysis method profiles (ADR-0027).

How a report's numbers are made — the NTP test per platform, its thresholds,
the BMD acceptance filter, the internal-dose rules, the GO ranking — is a
versioned, declarative METHOD PROFILE (`profiles/<name>.yaml`), not literals in
the code.  A study PINS one profile by name and content hash
(`sessions/<dtxsid>/method_profile.json`), and every consumer reads the
resolved settings through this module.

Resolution, each layer overriding the one before, every value carrying its
source:

    default            the built-in defaults below (the NTP procedure; what the
                       code did before profiles) — used where a profile says
                       null ("to confirm")
    profile:<name>     the pinned profile
    study:<dtxsid>     the study overlay's `methods:` block
                       (templates/studies/<dtxsid>/view.yaml)
    request            explicit values of one Process request (UI / CLI)

The schema is CLOSED: an unknown key, a missing key, or an implementation name
the registry does not know fails loudly at load.  A registered implementation
the tool does not have (the 2021 reports' BMDS 2.7 engine) resolves to the
default implementation and is listed in `deviations`, never silently.

bmdx-pipe never reads profiles; it receives the resolved values as arguments
(`stats_method()`, `acceptance_criteria()`).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"
PIN_FILE = "method_profile.json"
DEFAULT_SERIES = "ntp-5day"


class MethodProfileError(ValueError):
    """A profile file, pin or overlay that does not satisfy the schema."""


# ---------------------------------------------------------------------------
# Registry of implementation names: name → implemented by this tool?
# ---------------------------------------------------------------------------

IMPLEMENTATIONS: dict[str, dict[str, bool]] = {
    "trend_test": {"jonckheere": True},
    "pairwise": {"williams_or_dunnett": True, "shirley_or_dunn": True, "none": True},
    "engine": {"toxicr_model_average": True, "bmds_2_7_high_dose_drop": False},
    "eligibility": {"trend_and_pairwise": True, "all_endpoints": False},
    "outlier_test": {"dixon_r10": True},
    "below_limit": {"half_limit": True},
    "above_highest_dose": {"nvm": True, "keep": True},
    "bmr_type": {"sd": True, "rel_dev": True},
    "model_selection": {"model_average": True, "lowest_aic": True},
    "bmd_stat": {s: True for s in ("mean", "median", "minimum", "weighted_mean",
                                   "fifth_pct", "tenth_pct", "lower95", "upper95")},
}

# The bmdx-pipe test families the pairwise names select.
_FAMILY = {"williams_or_dunnett": "parametric", "shirley_or_dunn": "nonparametric"}


# ---------------------------------------------------------------------------
# Schema: leaf validators
# ---------------------------------------------------------------------------

def _fail(path: str, msg: str):
    raise MethodProfileError(f"{path}: {msg}")


def _text(path, v):
    if not isinstance(v, str) or not v.strip():
        _fail(path, f"expected text, got {v!r}")


def _prob(path, v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1:
        _fail(path, f"expected a number in [0, 1], got {v!r}")


def _positive(path, v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
        _fail(path, f"expected a positive number, got {v!r}")


def _count(path, v):
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        _fail(path, f"expected a whole number, got {v!r}")


def _impl(kind: str):
    def check(path, v):
        if v not in IMPLEMENTATIONS[kind]:
            _fail(path, f"unknown {kind} {v!r}; registered: {sorted(IMPLEMENTATIONS[kind])}")
    return check


def _bmr(path, v):
    if not isinstance(v, dict) or set(v) != {"type", "factor"}:
        _fail(path, f"expected {{type, factor}}, got {v!r}")
    _impl("bmr_type")(f"{path}.type", v["type"])
    _positive(f"{path}.factor", v["factor"])


def _outliers(path, v):
    if not isinstance(v, dict) or set(v) != {"test", "alpha"}:
        _fail(path, f"expected {{test, alpha}}, got {v!r}")
    _impl("outlier_test")(f"{path}.test", v["test"])
    _prob(f"{path}.alpha", v["alpha"])


def _stats_list(path, v):
    if not isinstance(v, list) or not v:
        _fail(path, f"expected a non-empty list, got {v!r}")
    for i, s in enumerate(v):
        _impl("bmd_stat")(f"{path}[{i}]", s)


def _go_display(path, v):
    keys = {"pct", "min_genes", "max_genes", "min_bmd"}
    if not isinstance(v, dict) or set(v) != keys:
        _fail(path, f"expected {sorted(keys)}, got {v!r}")
    if isinstance(v["pct"], bool) or not isinstance(v["pct"], (int, float)) or v["pct"] < 0:
        _fail(f"{path}.pct", f"expected a percentage, got {v['pct']!r}")
    for k in ("min_genes", "max_genes", "min_bmd"):
        _count(f"{path}.{k}", v[k])


class _Map:
    """A mapping with free keys (platform names) and one value validator."""
    def __init__(self, check):
        self.check = check


# The closed schema.  A dict is a section (exact keys); a _Map has free keys;
# a function validates a leaf.  Any section or leaf may be null ("to confirm").
SCHEMA: dict = {
    "name": _text,
    "series": _text,
    "effective": _text,
    "reference": _text,
    "description": _text,
    "apical": {
        "statistics": {
            "trend_test": _impl("trend_test"),
            "trend_select_p": _prob,
            "alpha": _prob,
            "alpha_strong": _prob,
            "min_group_n": _count,
            "pairwise": _Map(_impl("pairwise")),
            "outliers": _outliers,
        },
        "bmd": {
            "engine": _impl("engine"),
            "eligibility": _impl("eligibility"),
            "bmr_when_unrecorded": _Map(_bmr),
            "acceptance": {
                "r2_min": _prob,
                "bmd_bmdl_max": _positive,
                "bmd_above_highest_dose": _impl("above_highest_dose"),
                "not_reportable_fraction": _prob,
            },
        },
    },
    "internal_dose": {
        "pairwise": _impl("pairwise"),
        "below_limit": _impl("below_limit"),
        "bd_if_detected_share_at_most": _prob,
        "outliers": _outliers,
        "sig_figs": _count,
    },
    "genomics": {
        "go_ranking": _stats_list,
        "go_display": _go_display,
        "recorded": {
            "bmr": _bmr,
            "model_selection": _impl("model_selection"),
        },
    },
}

_IDENTITY_KEYS = ("name", "series", "effective", "reference", "description")


def validate(doc: dict, *, partial: bool = False, path: str = "") -> None:
    """Check `doc` against SCHEMA.  partial=True (a study overlay or a request)
    allows absent keys; a profile must state every key (null for "to confirm")."""
    _validate_section(doc, SCHEMA if not partial else
                      {k: v for k, v in SCHEMA.items() if k not in _IDENTITY_KEYS},
                      partial, path)


def _validate_section(doc, schema: dict, partial: bool, path: str) -> None:
    if not isinstance(doc, dict):
        _fail(path or "<profile>", f"expected a mapping, got {type(doc).__name__}")
    unknown = sorted(set(doc) - set(schema))
    if unknown:
        _fail(path or "<profile>", f"unknown key(s) {unknown}")
    missing = [] if partial else sorted(set(schema) - set(doc))
    if missing:
        _fail(path or "<profile>", f"missing key(s) {missing} (state null for 'to confirm')")
    for key, sub in schema.items():
        if key not in doc or doc[key] is None:
            continue
        p = f"{path}.{key}" if path else key
        if isinstance(sub, dict):
            _validate_section(doc[key], sub, partial, p)
        elif isinstance(sub, _Map):
            if not isinstance(doc[key], dict):
                _fail(p, "expected a mapping")
            for k, v in doc[key].items():
                sub.check(f"{p}.{k}", v)
        else:
            sub(p, doc[key])


# ---------------------------------------------------------------------------
# Built-in defaults — the NTP procedure; what the code did before profiles
# ---------------------------------------------------------------------------

def _builtin_defaults() -> dict:
    from bmdx_pipe import bmd_acceptance
    from bmdx_pipe.ntp_stats import DEFAULT_METHOD

    pairwise = {p: ("williams_or_dunnett" if f == "parametric" else "shirley_or_dunn")
                for p, f in DEFAULT_METHOD.families}
    return {
        "apical": {
            "statistics": {
                "trend_test": "jonckheere",
                "trend_select_p": DEFAULT_METHOD.trend_select_p,
                "alpha": DEFAULT_METHOD.alpha,
                "alpha_strong": DEFAULT_METHOD.alpha_strong,
                "min_group_n": DEFAULT_METHOD.min_group_n,
                "pairwise": pairwise,
                "outliers": None,
            },
            "bmd": {
                "engine": "toxicr_model_average",
                "eligibility": "trend_and_pairwise",
                "bmr_when_unrecorded": {"default": {"type": "sd", "factor": 1.0}},
                "acceptance": {
                    "r2_min": bmd_acceptance.R2_MIN,
                    "bmd_bmdl_max": bmd_acceptance.BMD_BMDL_MAX,
                    "bmd_above_highest_dose": "nvm",
                    "not_reportable_fraction": bmd_acceptance.NR_FRACTION,
                },
            },
        },
        "internal_dose": {
            "pairwise": "shirley_or_dunn",
            "below_limit": "half_limit",
            "bd_if_detected_share_at_most": 0.2,
            "outliers": {"test": "dixon_r10", "alpha": 0.01},
            "sig_figs": 3,
        },
        "genomics": {
            "go_ranking": ["median"],
            "go_display": {"pct": 5, "min_genes": 20, "max_genes": 500, "min_bmd": 3},
            "recorded": {"bmr": None, "model_selection": None},
        },
    }


# ---------------------------------------------------------------------------
# Profiles on disk
# ---------------------------------------------------------------------------

def profile_path(name: str) -> Path:
    if not name or "/" in name or name.startswith("."):
        raise MethodProfileError(f"bad profile name {name!r}")
    return PROFILES_DIR / f"{name}.yaml"


def content_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def load_profile(name: str) -> dict:
    """The validated profile `name` (profiles/<name>.yaml)."""
    path = profile_path(name)
    if not path.is_file():
        raise MethodProfileError(f"no method profile {name!r} in {PROFILES_DIR}")
    doc = yaml.safe_load(path.read_text())
    validate(doc, path="")
    if doc["name"] != name:
        raise MethodProfileError(f"{path.name}: name {doc['name']!r} does not match the file")
    return doc


def list_profiles() -> list[dict]:
    """Every profile: {name, series, effective, reference, hash}."""
    out = []
    for path in sorted(PROFILES_DIR.glob("*.yaml")):
        doc = load_profile(path.stem)
        out.append({k: doc[k] for k in ("name", "series", "effective", "reference")}
                   | {"hash": content_hash(path)})
    return out


def newest_profile(series: str = DEFAULT_SERIES) -> str:
    """The newest profile of `series` — the proposal for a new study (ADR §3)."""
    candidates = [p for p in list_profiles() if p["series"] == series]
    if not candidates:
        raise MethodProfileError(f"no method profile for series {series!r}")
    return max(candidates, key=lambda p: p["effective"])["name"]


# ---------------------------------------------------------------------------
# Resolved settings
# ---------------------------------------------------------------------------

@dataclass
class MethodSettings:
    """The resolved method: {dotted path: value} and {dotted path: source}."""
    profile: str
    profile_hash: str
    values: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)
    deviations: list = field(default_factory=list)

    def get(self, path: str):
        return self.values[path]

    def source(self, path: str) -> str:
        return self.sources[path]

    def section(self, prefix: str) -> dict:
        """{key: value} of the leaves directly under `prefix` (a _Map section)."""
        pre = prefix + "."
        return {p[len(pre):]: v for p, v in self.values.items()
                if p.startswith(pre) and "." not in p[len(pre):]}

    def signature(self) -> str:
        """A stable digest of every resolved value — for cache keys (a re-pin
        or an overlay change makes derived content stale)."""
        blob = json.dumps(self.values, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    def to_json(self) -> dict:
        return {"profile": self.profile, "hash": self.profile_hash,
                "settings": {p: {"value": self.values[p], "source": self.sources[p]}
                             for p in sorted(self.values)},
                "deviations": list(self.deviations)}

    # ── typed views for the consumers ─────────────────────────────────────

    def pairwise(self, platform: str | None) -> str | None:
        """The pairwise implementation name for an apical platform, or None."""
        return self.section("apical.statistics.pairwise").get((platform or "").strip())

    def stats_method(self):
        """bmdx_pipe.ntp_stats.StatsMethod for the apical tables."""
        from bmdx_pipe.ntp_stats import StatsMethod

        families = tuple(sorted((p, _FAMILY[impl]) for p, impl in
                                self.section("apical.statistics.pairwise").items()
                                if impl in _FAMILY))
        return StatsMethod(
            families=families,
            trend_select_p=self.get("apical.statistics.trend_select_p"),
            alpha=self.get("apical.statistics.alpha"),
            alpha_strong=self.get("apical.statistics.alpha_strong"),
            min_group_n=self.get("apical.statistics.min_group_n"),
        )

    def internal_dose_stats_method(self):
        """StatsMethod for the internal-dose table (its family + the thresholds)."""
        from bmdx_pipe.ntp_stats import StatsMethod

        return StatsMethod(
            families=(),
            trend_select_p=self.get("apical.statistics.trend_select_p"),
            alpha=self.get("apical.statistics.alpha"),
            alpha_strong=self.get("apical.statistics.alpha_strong"),
            min_group_n=self.get("apical.statistics.min_group_n"),
        )

    def acceptance_criteria(self):
        """bmdx_pipe.bmd_acceptance.Criteria for classifying apical BMDs."""
        from bmdx_pipe.bmd_acceptance import Criteria

        a = "apical.bmd.acceptance."
        return Criteria(
            r2_min=self.get(a + "r2_min"),
            bmd_bmdl_max=self.get(a + "bmd_bmdl_max"),
            max_dose=self.get(a + "bmd_above_highest_dose") == "nvm",
            nr_fraction=self.get(a + "not_reportable_fraction"),
        )

    def bmr_when_unrecorded(self, platform: str | None) -> dict:
        """{type, factor} for a platform whose analysis records no BMR."""
        table = self.section("apical.bmd.bmr_when_unrecorded")
        return table.get((platform or "").strip()) or table["default"]


# ---------------------------------------------------------------------------
# Method text (ADR-0027 §4): what the report says comes from what ran
# ---------------------------------------------------------------------------

_TREND_TEXT = {"jonckheere": "Jonckheere"}
_PAIRWISE_TEXT = {"williams_or_dunnett": "Williams or Dunnett", "shirley_or_dunn": "Shirley or Dunn"}
_PAIRWISE_PROCEDURES = {
    "williams_or_dunnett": ("parametric", "Williams and Dunnett", "Williams", "Dunnett"),
    "shirley_or_dunn": ("nonparametric", "Shirley and Dunn", "Shirley", "Dunn"),
}


def statistics_sentence(method: MethodSettings, pairwise_impl: str | None) -> str | None:
    """"Statistical analysis performed by the Jonckheere (trend) and Williams
    or Dunnett (pairwise) tests." for a pairwise implementation; None when it
    runs no statistics."""
    pairwise = _PAIRWISE_TEXT.get(pairwise_impl or "")
    if not pairwise:
        return None
    trend = _TREND_TEXT[method.get("apical.statistics.trend_test")]
    return f"Statistical analysis performed by the {trend} (trend) and {pairwise} (pairwise) tests."


def marker_legend(method: MethodSettings) -> str:
    """"*Statistically significant at p ≤ 0.05; **p ≤ 0.01." at the method's alphas."""
    a, a2 = method.get("apical.statistics.alpha"), method.get("apical.statistics.alpha_strong")
    return f"*Statistically significant at p \u2264 {a:g}; **p \u2264 {a2:g}."


def pairwise_procedures(pairwise_impl: str) -> tuple[str, str, str, str] | None:
    """(kind, "Williams and Dunnett", trend-sensitive test, the other) — for prose."""
    return _PAIRWISE_PROCEDURES.get(pairwise_impl)


def family_of(pairwise_impl: str | None) -> str | None:
    """bmdx-pipe family ("parametric" / "nonparametric") of a pairwise name."""
    return _FAMILY.get(pairwise_impl or "")


def _flatten(doc, schema, prefix: str, out: dict, keep_null: bool = False) -> None:
    """Leaves of `doc` (shaped by `schema`) as {dotted path: value}; a null
    section or leaf contributes nothing (the lower layer's value stands) unless
    keep_null (the defaults layer, where null means "no such rule")."""
    for key, sub in schema.items():
        if key in _IDENTITY_KEYS or not isinstance(doc, dict) or key not in doc:
            continue
        v = doc[key]
        p = f"{prefix}.{key}" if prefix else key
        if isinstance(sub, dict):
            if v is not None:
                _flatten(v, sub, p, out, keep_null)
        elif isinstance(sub, _Map):
            for k, mv in (v or {}).items():
                out[f"{p}.{k}"] = mv
        elif v is not None or keep_null:
            out[p] = v


def resolve(profile_name: str, *, overlay: dict | None = None, overlay_label: str = "",
            request: dict | None = None) -> MethodSettings:
    """The settings of `profile_name` over the built-in defaults, then the
    study overlay and the request (both partial)."""
    profile = load_profile(profile_name)
    settings = MethodSettings(profile=profile_name,
                              profile_hash=content_hash(profile_path(profile_name)))
    layers = [(_builtin_defaults(), "default"), (profile, f"profile:{profile_name}")]
    for extra, label in ((overlay, overlay_label or "study"), (request, "request")):
        if extra:
            validate(extra, partial=True, path=label)
            layers.append((extra, label))
    for doc, label in layers:
        flat: dict = {}
        _flatten(doc, SCHEMA, "", flat, keep_null=label == "default")
        for p, v in flat.items():
            settings.values[p] = v
            settings.sources[p] = label
    _substitute_unimplemented(settings)
    return settings


# Fields whose value names an implementation, and the registry kind.
_IMPL_FIELDS = {"apical.bmd.engine": "engine", "apical.bmd.eligibility": "eligibility"}


def _substitute_unimplemented(settings: MethodSettings) -> None:
    defaults: dict = {}
    _flatten(_builtin_defaults(), SCHEMA, "", defaults, keep_null=True)
    for p, kind in _IMPL_FIELDS.items():
        v = settings.values.get(p)
        if v is not None and not IMPLEMENTATIONS[kind].get(v, False):
            settings.deviations.append(
                f"{p}: {settings.sources[p]} asks for {v!r}, which this tool does not "
                f"implement; {defaults[p]!r} is used")
            settings.values[p] = defaults[p]
            settings.sources[p] = f"default (not implemented: {v})"


# ---------------------------------------------------------------------------
# The session pin
# ---------------------------------------------------------------------------

def pin_path(dtxsid: str) -> Path:
    from common.paths import SESSIONS_DIR

    return SESSIONS_DIR / dtxsid / PIN_FILE


def read_pin(dtxsid: str) -> dict | None:
    path = pin_path(dtxsid)
    return json.loads(path.read_text()) if path.is_file() else None


def pin_profile(dtxsid: str, name: str, *, by: str = "user") -> dict:
    """Pin `name` for the study (re-pinning is explicit; the previous pin is
    kept under history/_method_profile/).  `by` is "user" or "default"."""
    path = profile_path(name)
    load_profile(name)                                   # validate before pinning
    pin = {"name": name, "hash": content_hash(path),
           "pinned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "pinned_by": by}
    target = pin_path(dtxsid)
    if target.is_file():
        old = json.loads(target.read_text())
        if old.get("name") == name and old.get("hash") == pin["hash"]:
            return old
        hist = target.parent / "history" / "_method_profile"
        hist.mkdir(parents=True, exist_ok=True)
        stamp = (old.get("pinned_at") or "unknown").replace(":", "")
        (hist / f"{stamp}-{old.get('name')}.json").write_text(json.dumps(old, indent=2))
        logger.info("Method profile for %s re-pinned: %s → %s", dtxsid, old.get("name"), name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(pin, indent=2) + "\n")
    return pin


def ensure_pin(dtxsid: str) -> dict:
    """The study's pin, pinning the newest profile of the series when there is
    none (logged as a default — choosing a method is a human decision)."""
    pin = read_pin(dtxsid)
    if pin:
        return pin
    name = newest_profile()
    logger.warning("No method profile pinned for %s; pinned the newest, %s "
                   "(re-pin with generate_report --method-profile)", dtxsid, name)
    return pin_profile(dtxsid, name, by="default")


def study_overlay(dtxsid: str) -> dict | None:
    """The `methods:` block of the study overlay (templates/studies/<dtxsid>/view.yaml)."""
    from document_model.view_config import load_study_view

    try:
        view = load_study_view(dtxsid) or {}
    except Exception:  # noqa: BLE001 — an unreadable overlay is reported by its own loader
        return None
    return view.get("methods") or None


def session_method(dtxsid: str | None, request: dict | None = None) -> MethodSettings:
    """The resolved method of a study: its pinned profile (the newest when it
    has none — not written here), its study overlay, then `request`.  A pin
    whose profile file changed since pinning fails: profiles are immutable."""
    pin = read_pin(dtxsid) if dtxsid else None
    if pin:
        name = pin["name"]
        current = content_hash(profile_path(name))
        if pin.get("hash") != current:
            raise MethodProfileError(
                f"{dtxsid}: method profile {name!r} changed since it was pinned "
                f"(hash {pin.get('hash')} → {current}); profiles are immutable — "
                f"write a new profile and re-pin")
    else:
        name = newest_profile()
    overlay = study_overlay(dtxsid) if dtxsid else None
    settings = resolve(name, overlay=overlay, overlay_label=f"study:{dtxsid}", request=request)
    if not pin:
        settings.deviations.append(f"no profile pinned; the newest, {name}, is used")
    return settings


# ---------------------------------------------------------------------------
# Recorded settings vs the profile (ADR-0027 §5)
# ---------------------------------------------------------------------------

def _recorded_model_selection(notes: list[str]) -> str | None:
    if any(n.startswith("Model Averaging Method") for n in notes):
        return "model_average"
    if any(n.startswith("Best Model Selection") or "Lowest AIC" in n for n in notes):
        return "lowest_aic"
    return None


def recorded_mismatches(integrated: dict, method: MethodSettings) -> list[dict]:
    """Where an analysis we pass through (each .bm2 bMDResult's own
    analysisInfo) disagrees with the pinned profile: the genomic BMR and model
    selection (genomics.recorded.*) and the apical BMR.  Neither side wins —
    each disagreement is reported for a human."""
    from tables.apical_bmds import _BMR_REL, _BMR_SD, _parse_notes, _sex_platform_from_source

    bmr_type_of = {_BMR_SD: "sd", _BMR_REL: "rel_dev"}
    out: list[dict] = []
    for result in integrated.get("bMDResult") or []:
        if not isinstance(result, dict):
            continue
        notes = (result.get("analysisInfo") or {}).get("notes") or []
        cfg = _parse_notes(notes)
        name = result.get("name") or cfg["data_source"] or "?"
        recorded_bmr = ({"type": bmr_type_of[cfg["bmr_type"]], "factor": cfg["bmr_factor"]}
                        if cfg["bmr_type"] in bmr_type_of and cfg["bmr_factor"] is not None else None)
        apical = _sex_platform_from_source(cfg["data_source"]) is not None
        if apical:
            expected = {"bmr": method.bmr_when_unrecorded(cfg["data_source"].split("_", 1)[-1])}
            path = "apical.bmd.bmr_when_unrecorded"
        else:
            expected = {"bmr": method.get("genomics.recorded.bmr"),
                        "model_selection": method.get("genomics.recorded.model_selection")}
            path = "genomics.recorded"
        recorded = {"bmr": recorded_bmr, "model_selection": _recorded_model_selection(notes)}
        for key, want in expected.items():
            got = recorded.get(key)
            if want is None or got is None:
                continue
            if key == "bmr" and (got["type"], float(got["factor"])) == (want["type"], float(want["factor"])):
                continue
            if key != "bmr" and got == want:
                continue
            out.append({
                "analysis": name, "setting": f"{path}.{key}" if key != "bmr" or not apical else path,
                "recorded": got, "profile": want,
                "message": (f"{name}: the analysis records {key.replace('_', ' ')} {_show(got)}; "
                            f"method profile {method.profile} expects {_show(want)}"),
            })
    return out


def _show(v) -> str:
    if isinstance(v, dict) and "type" in v:
        return (f"{float(v['factor']) * 100:g}% relative deviation" if v["type"] == "rel_dev"
                else f"{float(v['factor']):g} SD")
    return str(v).replace("_", " ")
