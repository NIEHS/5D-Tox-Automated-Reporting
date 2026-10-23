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
    # bmds_2_7_high_dose_drop runs only where Wine can run BMDS 2.7 (see
    # _MACHINE_DEPENDENT); False here is "not on every machine".
    "engine": {"toxicr_model_average": True, "bmds_2_7_high_dose_drop": False},
    # trend_or_pairwise is what NTP's BMDS 2.7 runs modelled (their recorded
    # datasets, NIEHS-07…10); it is applied by the bmds27 path only and no
    # profile names it yet (ADR-0030).
    "eligibility": {"trend_and_pairwise": True, "all_endpoints": False,
                    "trend_or_pairwise": False},
    "outlier_test": {"dixon_r10": True},
    "below_limit": {"half_limit": True},
    "above_highest_dose": {"nvm": True, "keep": True},
    "bmr_type": {"sd": True, "rel_dev": True},
    "model_selection": {"model_average": True, "lowest_aic": True},
    "bmd_stat": {s: True for s in ("mean", "median", "minimum", "weighted_mean",
                                   "fifth_pct", "tenth_pct", "lower95", "upper95")},
}

# Implementations that run only where the machine can run them: (kind, name)
# → a function returning None when available here, else the reason it is not.
# With probe=False it runs nothing: it answers UNCHECKED unless this process
# has already checked (a read without side effects — the state read model —
# must not start Wine).
UNCHECKED = "not checked on this machine yet"


def _bmds27_unavailable(probe: bool = True) -> str | None:
    from pipeline import bmds27
    if probe:
        return bmds27.unavailable_reason()
    known, why = bmds27.known_unavailable_reason()
    return why if known else UNCHECKED


_MACHINE_DEPENDENT = {("engine", "bmds_2_7_high_dose_drop"): _bmds27_unavailable}


def unavailable_reason(kind: str, name: str, *, probe: bool = True) -> str | None:
    """None when implementation `name` of `kind` runs here, else why not
    (UNCHECKED when probe=False and the machine has not been checked)."""
    check = _MACHINE_DEPENDENT.get((kind, name))
    if check is not None:
        return check(probe)
    return None if IMPLEMENTATIONS[kind].get(name, False) else "not implemented"


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
        # How the synthetic null data of the empirical FDR were made (the books'
        # Appendix D.2): the generator, its address, the distribution each
        # probe's control values were fitted to and the values drawn per probe.
        "efdr": {
            "generator": _text,
            "generator_abbreviation": _text,
            "generator_url": _text,
            "distribution": _text,
            "resamples_per_probe": _count,
        },
    },
}

# Sections added to the schema after profiles were written.  Profiles are
# immutable, so one that predates a section does not state it: the section is
# "to confirm" for it (the default), and a profile written since states it.
_ADDED_LATER = frozenset({"genomics.efdr"})

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
    missing = [] if partial else sorted(
        k for k in set(schema) - set(doc) if (f"{path}.{k}" if path else k) not in _ADDED_LATER)
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
            "efdr": {"generator": None, "generator_abbreviation": None, "generator_url": None,
                     "distribution": None, "resamples_per_probe": None},
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
    # Settings whose availability here was not checked (resolve(probe=False)):
    # their values are the profile's, not substituted.  Never set by a run.
    unchecked: list = field(default_factory=list)

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

    def efdr_generation(self) -> dict:
        """How the eFDR's synthetic null data were made: {generator,
        generator_abbreviation, generator_url, distribution,
        resamples_per_probe}, a value None where the profile does not say."""
        return self.section("genomics.efdr")

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
            request: dict | None = None, probe: bool = True) -> MethodSettings:
    """The settings of `profile_name` over the built-in defaults, then the
    study overlay and the request (both partial).  probe=False is for a read
    that only reports the method: it does not run the machine checks, and
    lists what it could not check in ``unchecked`` instead."""
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
    _substitute_unimplemented(settings, probe=probe)
    return settings


# Fields whose value names an implementation, and the registry kind.
_IMPL_FIELDS = {"apical.bmd.engine": "engine", "apical.bmd.eligibility": "eligibility"}


def _substitute_unimplemented(settings: MethodSettings, *, probe: bool = True) -> None:
    defaults: dict = {}
    _flatten(_builtin_defaults(), SCHEMA, "", defaults, keep_null=True)
    for p, kind in _IMPL_FIELDS.items():
        v = settings.values.get(p)
        why = unavailable_reason(kind, v, probe=probe) if v is not None else None
        if why == UNCHECKED:
            settings.unchecked.append(
                f"{p}: {settings.sources[p]} asks for {v!r}; whether this machine can "
                f"run it is checked when Process runs")
        elif why == "not implemented":
            settings.deviations.append(
                f"{p}: {settings.sources[p]} asks for {v!r}, which this tool does not "
                f"implement; {defaults[p]!r} is used")
            settings.values[p] = defaults[p]
            settings.sources[p] = f"default (not implemented: {v})"
        elif why:
            settings.deviations.append(
                f"{p}: {settings.sources[p]} asks for {v!r}, which cannot run here "
                f"({why}); {defaults[p]!r} is used")
            settings.values[p] = defaults[p]
            settings.sources[p] = f"default (unavailable here: {v})"


# ---------------------------------------------------------------------------
# The session pin
# ---------------------------------------------------------------------------

def pin_path(dtxsid: str) -> Path:
    from common.paths import SESSIONS_DIR

    return SESSIONS_DIR / dtxsid / PIN_FILE


def read_pin(dtxsid: str) -> dict | None:
    path = pin_path(dtxsid)
    return json.loads(path.read_text()) if path.is_file() else None


TRACK = "track"      # follow the newest profile of the series (the default)
FIXED = "fixed"      # stay on the named profile until re-pinned
NEWEST = "newest"    # the --method-profile value that selects TRACK


def pin_mode(pin: dict) -> str:
    """A pin's mode.  Pins written before modes existed: a user's choice is
    FIXED, an automatic default TRACKs."""
    return pin.get("mode") or (FIXED if pin.get("pinned_by") == "user" else TRACK)


def _write_pin(dtxsid: str, name: str, *, by: str, mode: str, series: str) -> dict:
    """Write the pin (the previous one, when it named another profile or hash,
    is kept under history/_method_profile/)."""
    path = profile_path(name)
    load_profile(name)                                   # validate before pinning
    pin = {"name": name, "hash": content_hash(path), "mode": mode, "series": series,
           "pinned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "pinned_by": by}
    target = pin_path(dtxsid)
    if target.is_file():
        old = json.loads(target.read_text())
        same_method = old.get("name") == name and old.get("hash") == pin["hash"]
        if same_method and pin_mode(old) == mode and (old.get("pinned_by") == by or by == "default"):
            return old
        if not same_method:
            hist = target.parent / "history" / "_method_profile"
            hist.mkdir(parents=True, exist_ok=True)
            stamp = (old.get("pinned_at") or "unknown").replace(":", "")
            (hist / f"{stamp}-{old.get('name')}.json").write_text(json.dumps(old, indent=2))
            logger.warning("Method profile for %s: %s → %s (%s)", dtxsid, old.get("name"), name,
                           "tracking the newest" if mode == TRACK else "re-pinned")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(pin, indent=2) + "\n")
    return pin


def pin_profile(dtxsid: str, name: str, *, by: str = "user") -> dict:
    """Pin the study to `name`.  `name` == "newest" makes the pin TRACK the
    newest profile of the series; any other name FIXES the study on that
    profile until it is re-pinned.  `by` is "user" or "default"."""
    if name == NEWEST:
        return track_newest(dtxsid, by=by)
    return _write_pin(dtxsid, name, by=by, mode=FIXED, series=load_profile(name)["series"])


def track_newest(dtxsid: str, *, series: str | None = None, by: str = "user") -> dict:
    """Pin the study to the newest profile of `series` (its current series, else
    the default) and keep it there as profiles are added."""
    pin = read_pin(dtxsid) or {}
    series = series or pin.get("series") or DEFAULT_SERIES
    return _write_pin(dtxsid, newest_profile(series), by=by, mode=TRACK, series=series)


def ensure_pin(dtxsid: str) -> dict:
    """The study's pin, made current: a study with none TRACKS the newest
    profile (the default — logged); a TRACK pin moves to a newer profile when
    one has been added (archived and logged; the caches recompute); a FIXED pin
    is left alone.  Called at integration and before every Process run."""
    pin = read_pin(dtxsid)
    if not pin:
        name = newest_profile()
        logger.warning("No method profile pinned for %s; it tracks the newest, %s "
                       "(fix one with generate_report --method-profile NAME)", dtxsid, name)
        return _write_pin(dtxsid, name, by="default", mode=TRACK, series=DEFAULT_SERIES)
    if pin_mode(pin) == TRACK:
        series = pin.get("series") or DEFAULT_SERIES
        newest = newest_profile(series)
        if newest != pin.get("name"):
            return _write_pin(dtxsid, newest, by=pin.get("pinned_by", "default"),
                              mode=TRACK, series=series)
    return pin


def chosen_by_person(pin: dict | None) -> bool:
    """Whether a person chose this pin (C1 D1): a pin written by default, or
    none at all, is not a choice."""
    return bool(pin) and pin.get("pinned_by") not in (None, "default")


def suggest_profile(dtxsid: str, *, count_mismatches=None) -> dict:
    """The profile to propose to the person choosing a study's method (ADR-0027
    §3; C1 D1 = B): ``{"name", "why"}``. A read with no side effects (no pin
    written, no machine check run). The proposal is the profile of the study's
    series whose expectations the dataset's recorded analyses (the .bm2
    settings) contradict least; on a tie, or with no dataset, the newest. The
    person confirms it; it is never applied for them.

    `count_mismatches(settings) -> int | None` counts the dataset's
    disagreements with resolved settings (None: no dataset, or one recording
    no analyses). The read model passes its memoized count; by default the
    dataset is read once here, without the in-memory cache."""
    pin = read_pin(dtxsid) or {}
    series = pin.get("series") or DEFAULT_SERIES
    newest = newest_profile(series)
    if count_mismatches is None:
        from common.session_files import read_json_file
        from pipeline.session_store import session_path
        integrated = read_json_file(session_path(dtxsid) / "integrated.json")

        def count_mismatches(settings):
            if not isinstance(integrated, dict) or not integrated.get("bMDResult"):
                return None
            return len(recorded_mismatches(integrated, settings))
    overlay = study_overlay(dtxsid)
    candidates = sorted((p for p in list_profiles() if p["series"] == series),
                        key=lambda p: p["effective"], reverse=True)       # newest first
    counts = {p["name"]: count_mismatches(resolve(
        p["name"], overlay=overlay, overlay_label=f"study:{dtxsid}", probe=False))
        for p in candidates}
    if any(c is None for c in counts.values()):
        return {"name": newest, "why": f"the newest profile of the {series} series (the "
                                       f"study has no recorded analyses to compare)"}
    best = min(counts.values())
    name = next(p["name"] for p in candidates if counts[p["name"]] == best)
    if name != newest:
        why = (f"it matches the analysis settings the study's .bm2 files record "
               f"({best} difference(s); the newest, {newest}, has {counts[newest]})")
    elif best == 0:
        why = (f"the newest profile of the {series} series; the analysis settings the "
               f"study's .bm2 files record agree with it")
    else:
        why = (f"the newest profile of the {series} series; no profile matches the "
               f"analysis settings the study's .bm2 files record better "
               f"({best} difference(s))")
    return {"name": name, "why": why}


def study_overlay(dtxsid: str) -> dict | None:
    """The `methods:` block of the study overlay (templates/studies/<dtxsid>/view.yaml)."""
    from document_model.view_config import load_study_view

    try:
        view = load_study_view(dtxsid) or {}
    except Exception:  # noqa: BLE001 — an unreadable overlay is reported by its own loader
        return None
    return view.get("methods") or None


def session_method(dtxsid: str | None, request: dict | None = None, *,
                   probe: bool = True) -> MethodSettings:
    """The resolved method of a study: its pinned profile (the newest when it
    has none — not written here), its study overlay, then `request`.  A pin
    whose profile file changed since pinning fails: profiles are immutable.
    probe=False: see resolve."""
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
    settings = resolve(name, overlay=overlay, overlay_label=f"study:{dtxsid}", request=request,
                       probe=probe)
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
