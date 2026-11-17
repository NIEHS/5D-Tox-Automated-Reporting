"""
apical_bmds.py — BMDS benchmark-dose modeling for apical endpoints via ToxicR.

Fits apical continuous BMD models using the SAME native engine BMDExpress itself
uses — ToxicR (libDRBMD.so) driven through the Java helper `RunApicalBmds` (see
bmdx_pipe.run_apical_bmds_java) — so the numbers are BMDExpress-identical rather than
an EPA-BMDS (pybmds) approximation. This replaces the former pybmds recompute.

Two uses (see pipeline.process_integrated._build_bmd_summary):
  - FILL: model endpoints the .bm2 left blank (BMDExpress didn't model them), so the
    report is complete (e.g. thyroid T3/T4 the NIEHS reference reports).
  - VALIDATE: re-model endpoints the .bm2 DID compute, as an independent cross-check;
    an overlap divergence beyond tolerance is a hard-stop (data-team notify).

Fit CONFIG is per-endpoint, matched to the .bm2:
  - Each `bMDResult.analysisInfo.notes` records the models / BMR type / BMR factor /
    constant-variance the .bm2 was run with. `parse_bmd_configs(integrated)` extracts a
    {(sex, platform): config} map; only clin_chem / hematology / organ_weight carry one.
  - Config-less platforms (body weight, hormones, clinical observations, tissue conc)
    are INFERRED per assay family and flagged `bmr_config="inferred"`; the report's
    BMD summary footnotes every value fit at an inferred BMR.

Model averaging (Laplace, the BMDExpress default) is used because the .bm2's own
results are model-averaged (`bestStatResult.@type == "modelaveraging"`) — like-for-like.
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
import json
import logging

from bmdx_pipe import run_apical_bmds_java

logger = logging.getLogger(__name__)

# --- ToxicR model IDs (com.toxicR.ToxicRConstants) ---
_HILL, _POWER, _EXP3, _EXP5 = 6, 8, 3, 5
# The BMDExpress default continuous model set ("hill, power, exponential 3,
# exponential 5" per analysisInfo notes).
_DEFAULT_MODELS = [_HILL, _POWER, _EXP3, _EXP5]

# BMR type at the BMDSToxicRUtils.calculateToxicRMA boundary: 1=Standard Deviation,
# 2=Relative Deviation (remapped to ToxicR SD/REL internally by the helper).
_BMR_SD, _BMR_REL = 1, 2


# ---------------------------------------------------------------------------
# analysisInfo → fit config
# ---------------------------------------------------------------------------

def _parse_notes(notes: list[str]) -> dict:
    """Pull the fit settings out of a bMDResult.analysisInfo.notes list."""
    def find(prefix: str) -> str | None:
        for n in notes or []:
            if n.startswith(prefix):
                return n.split(":", 1)[1].strip() if ":" in n else ""
        return None

    data_source = (find("Data Source") or "").strip()
    bmr_type_str = (find("BMR Type") or "").lower()
    bmr_factor_str = find("BMR Factor")
    const_var_str = find("Constant Variance")

    bmr_type = _BMR_SD if "standard" in bmr_type_str else (
        _BMR_REL if "relative" in bmr_type_str else None)
    try:
        bmr_factor = float(bmr_factor_str) if bmr_factor_str is not None else None
    except (TypeError, ValueError):
        bmr_factor = None
    # "Constant Variance: 1" → constant variance → isNCV=false.
    is_ncv = (const_var_str or "").strip() not in ("1", "true", "True")

    return {
        "data_source": data_source,
        "models": _DEFAULT_MODELS,
        "bmr_type": bmr_type,
        "bmr_factor": bmr_factor,
        "is_ncv": is_ncv,
    }


# Canonical platform key ← BOTH the analysisInfo Data-Source token (what the .bm2
# records: "organ_weights", "hormone_data", …) AND the platform_tables platform name
# (what an endpoint carries: "Organ Weight", "Hormones", …). The two spell the same
# platform differently, so a recorded config and its endpoints must normalize to ONE
# key to match — otherwise Organ Weight / Hormones miss their recorded SD/1.0 config
# and wrongly fall to inferred BMR (which diverges from the .bm2 by 20-45 %).
_CANONICAL_PLATFORM: dict[str, str] = {
    # .bm2 Data-Source tokens (the part after the sex prefix)
    "clin_chem": "clin_chem",
    "hematology": "hematology",
    "organ_weights": "organ_weight",
    "body_weight": "body_weight",
    "hormone_data": "hormones",
    # platform display names (lowercased, spaces → underscores)
    "clinical_chemistry": "clin_chem",
    "organ_weight": "organ_weight",
    "hormones": "hormones",
    "clinical_observations": "clinical_observations",
    "tissue_concentration": "tissue_concentration",
}


def _canon_platform(token: str) -> str:
    """Normalize a .bm2 data-source token OR a platform name to a canonical platform
    key, so a recorded config and its endpoints resolve to the SAME key."""
    t = (token or "").strip().lower().replace(" ", "_")
    return _CANONICAL_PLATFORM.get(t, t)


def _sex_platform_from_source(data_source: str) -> tuple[str, str] | None:
    """Map a Data Source string ('female_clin_chem', 'male_hormone_data', …) to
    (sex, canonical-platform). Genomics sources (Kidney/Liver…) return None — they are
    gene-level, not apical endpoints."""
    s = data_source.lower()
    if s.startswith("female"):
        sex = "Female"
    elif s.startswith("male"):
        sex = "Male"
    else:
        return None  # e.g. "Kidney_PFHxSAm_Female_No0" — genomics, not apical
    rest = s.split("_", 1)[1] if "_" in s else ""
    return (sex, _canon_platform(rest))


# The BMR for a platform with NO recorded .bm2 config comes from the study's method
# profile (apical.bmd.bmr_when_unrecorded, ADR-0027) — 1 SD for every family in
# ntp-5day-2025.  A fit at such a BMR is flagged `inferred` and footnoted.
_PROFILE_BMR_TYPE = {"sd": _BMR_SD, "rel_dev": _BMR_REL}


def parse_bmd_configs(integrated: dict) -> dict[tuple[str, str], dict]:
    """Build a {(sex, canonical_platform): config} map from integrated.json's bMDResults.

    Every apical platform BMDExpress modeled carries a recorded config keyed by the
    canonical platform (clin_chem, hematology, organ_weight, body_weight, hormones).
    Genomics results (Kidney/Liver) are skipped. A platform with no bMDResult is handled
    at endpoint time by _config_for (assay-family inference).
    """
    out: dict[tuple[str, str], dict] = {}
    for b in integrated.get("bMDResult") or []:
        notes = (b.get("analysisInfo") or {}).get("notes") or []
        cfg = _parse_notes(notes)
        sp = _sex_platform_from_source(cfg["data_source"])
        if sp is None or cfg["bmr_type"] is None or cfg["bmr_factor"] is None:
            continue
        cfg["bmr_config"] = "bm2_config"
        out[sp] = cfg
    return out


def bmr_record(cfg: dict) -> dict:
    """The BMR a fit config used, as {"type": "SD"|"RD", "factor": float}."""
    return {"type": "SD" if cfg.get("bmr_type") == _BMR_SD else "RD",
            "factor": cfg.get("bmr_factor")}


def inferred_bmr(platform: str, method) -> dict:
    """The BMR an endpoint of `platform` is fit at when the .bm2 records none
    (the method profile's), as bmr_record() describes it."""
    return bmr_record(_config_for("", platform, {}, method))


def _config_for(sex: str, platform: str, configs: dict, method) -> dict:
    """Resolve the fit config for one endpoint: recorded (from .bm2) if present, else
    INFERRED from the method profile (`method`, pipeline.method_profile.MethodSettings),
    flagged for data-team verification."""
    recorded = configs.get((sex, _canon_platform(platform)))
    if recorded is not None:
        return recorded
    bmr = method.bmr_when_unrecorded(platform)
    bmr_type, bmr_factor = _PROFILE_BMR_TYPE[bmr["type"]], float(bmr["factor"])
    return {
        "models": _DEFAULT_MODELS,
        "bmr_type": bmr_type,
        "bmr_factor": bmr_factor,
        "is_ncv": False,
        "bmr_config": "inferred",  # footnoted in the BMD summary
    }


# ---------------------------------------------------------------------------
# Batch endpoint modeling (ToxicR via the Java helper)
# ---------------------------------------------------------------------------

def run_bmds_for_endpoints(
    endpoint_data: list[dict],
    configs: dict[tuple[str, str], dict] | None = None,
    *,
    method,
) -> dict[str, dict]:
    """Fit apical BMDs for a batch of endpoints via the ToxicR Java engine.

    `endpoint_data` is the list of enriched `_bmds_input` dicts (each carries per-animal
    `Y` + `doses_per_animal`, plus `sex`, `endpoint`, and the summary stats). `configs`
    is the {(sex, platform_token): config} map from `parse_bmd_configs`; when a platform
    has no recorded config the fit config is inferred from `method` (the study's
    resolved method profile) and flagged; `method` also supplies the acceptance
    criteria each fit is classified by.

    Returns {key: {bmd, bmdl, bmdu, model_name, status, notes, bmr_config, bmr}} — the
    shape the former pybmds path returned, plus `bmr_config` (bm2_config | inferred: was
    the BMR recorded in the .bm2 or an assay-family default?) and `bmr` (the BMR used). Endpoints lacking per-animal data are skipped (nothing to model).
    """
    configs = configs or {}
    if not endpoint_data:
        return {}

    payload = []
    cfg_by_key: dict[str, str] = {}
    for ep in endpoint_data:
        Y = ep.get("Y")
        doses = ep.get("doses_per_animal")
        if not Y or not doses or len(Y) != len(doses):
            continue  # no per-animal data for this endpoint — cannot ToxicR-fit
        sex = ep.get("sex", "")
        platform = ep.get("platform", "")
        cfg = _config_for(sex, platform, configs, method)
        cfg_by_key[ep["key"]] = cfg
        payload.append({
            "key": ep["key"],
            "doses": doses,
            "Y": Y,
            "models": cfg["models"],
            "bmr_type": cfg["bmr_type"],
            "bmr_factor": cfg["bmr_factor"],
            "is_ncv": cfg["is_ncv"],
        })

    if not payload:
        return {}

    logger.info("ToxicR modeling %d apical endpoints", len(payload))
    results = run_apical_bmds_java(payload, criteria=method.acceptance_criteria())

    # Stamp the config provenance onto each result so the report can say when a
    # filled BMD used an inferred (assay-family default) BMR.
    for key, res in results.items():
        cfg = cfg_by_key.get(key) or {}
        res["bmr_config"] = cfg.get("bmr_config", "inferred")
        if cfg:
            res["bmr"] = bmr_record(cfg)
        if res.get("status") == "viable":
            logger.info(
                "ToxicR %s: BMD=%s BMDL=%s (%s, %s)",
                key, res.get("bmd"), res.get("bmdl"),
                res.get("model_name"), res["bmr_config"],
            )
        else:
            logger.info("ToxicR %s: %s — %s", key, res.get("status"), res.get("notes"))
    return results


# ---------------------------------------------------------------------------
# The record of the apical BMD method (2026-11-17)
# ---------------------------------------------------------------------------
# What the Methods, the table legends and the BMD summary legend say about the
# apical BMDs is read from ONE record of what was computed: per sex and assay,
# the settings the study's BMDExpress project records (its BMDs are printed
# as that analysis gave them; our fit fills only what it did not model), or,
# where the project records no analysis, the settings this tool fits with.
# Nothing in the report states a benchmark response, a variance assumption or
# a model set that is not in this record.

_MODEL_NAMES = {_HILL: "Hill", _POWER: "Power", _EXP3: "Exponential 3", _EXP5: "Exponential 5"}


def bmr_phrase(bmr: dict | None) -> str | None:
    """{"type": "SD"|"RD", "factor": f} → "1 standard deviation" / "25% relative
    deviation"; None for no record (nothing is assumed)."""
    if not isinstance(bmr, dict) or bmr.get("factor") is None:
        return None
    f = float(bmr["factor"])
    if bmr.get("type") == "RD":
        return f"{f * 100:g}% relative deviation"
    return f"{f:g} standard deviation" + ("" if f == 1 else "s")


def bmr_tag(bmr: dict | None) -> str:
    """The subscript a BMD column carries for its BMR: "1Std", "2Std", "rd25"
    (as the genomics tables write it); "" for no record."""
    if not isinstance(bmr, dict) or bmr.get("factor") is None:
        return ""
    f = float(bmr["factor"])
    return f"rd{round(f * 100):g}" if bmr.get("type") == "RD" else f"{f:g}Std"


def _recorded_analysis(notes: list[str]) -> dict:
    """What a bMDResult's analysisInfo notes say of the analysis, as written:
    the software, how a model was chosen, the models, the variance note."""
    def find(prefix: str) -> str | None:
        for n in notes or []:
            if n.startswith(prefix):
                return n.split(":", 1)[1].strip() if ":" in n else ""
        return None

    variance = find("Constant Variance")
    models = find("Models fit") or find("Models Used") or ""
    return {
        "software": find("BMDExpress3 Version") or find("BMDExpress2 Version")
                    or find("BMDExpress Version"),
        "selection": find("Model Averaging Method") or find("Best Model Selection"),
        "models": [m.split(":")[0].strip() for m in models.split(",") if m.strip()],
        # True / False as the note says; None when the project has no such note.
        "constant_variance": (None if variance is None
                              else variance.strip() in ("1", "true", "True")),
    }


TOXICR_ENGINE = "toxicr_model_average"
# The order the report presents the assays in (its tables', and the published
# Methods' "body weights, organ weights, and clinical pathology").
_PLATFORM_ORDER = ("Body Weight", "Organ Weight", "Clinical Chemistry", "Hematology", "Hormones")


def in_report_order(platform_sexes: dict[str, list[str]]) -> dict[str, list[str]]:
    rank = {p: i for i, p in enumerate(_PLATFORM_ORDER)}
    return {p: platform_sexes[p]
            for p in sorted(platform_sexes, key=lambda p: (rank.get(p, len(rank)), p))}


def apical_bmd_method(integrated: dict | None, method,
                      platform_sexes: dict[str, list[str]],
                      engine_bmr: dict | None = None) -> dict:
    """The record of how this study's apical BMDs are computed.

    ``platform_sexes``: {platform display name: [sexes]} the study has data for.
    Returns {"engine", "settings": [...]}; each setting is one group of
    (platform, sex) sharing the same fit settings:
      source              "recorded" (the BMDExpress project's analysis; its BMDs
                          are printed, and our fit fills what it left without a
                          BMD, under the same BMR and variance), "inferred" (no
                          analysis recorded: this tool's fit, at the method
                          profile's BMR) or "engine" (an engine that is the
                          source of every BMD and runs with its own settings:
                          BMDS 2.7, at ``engine_bmr``)
      platforms           {platform: [sexes]}
      bmr                 {"type": "SD"|"RD", "factor"}
      constant_variance   the variance our fit used (not for "engine")
      models              the models our fit averages (not for "engine")
      analysis            (recorded only) the project's own notes: software,
                          selection, models, constant_variance (None: no note)
    """
    engine = method.get("apical.bmd.engine")
    platform_sexes = in_report_order(platform_sexes)
    if engine != TOXICR_ENGINE:
        platforms = {p: [str(s).title() for s in sexes]
                     for p, sexes in platform_sexes.items()}
        return {"engine": engine,
                "settings": [{"source": "engine", "bmr": engine_bmr,
                              "platforms": platforms}] if platforms else []}
    integrated = integrated or {}
    configs = parse_bmd_configs(integrated)
    notes_of = {}
    for b in integrated.get("bMDResult") or []:
        notes = (b.get("analysisInfo") or {}).get("notes") or []
        sp = _sex_platform_from_source(_parse_notes(notes)["data_source"])
        if sp is not None:
            notes_of.setdefault(sp, notes)

    groups: dict[str, dict] = {}
    for platform, sexes in platform_sexes.items():
        for sex in sexes or [""]:   # a study without a sex dimension: one group
            key = (str(sex).title(), _canon_platform(platform))
            cfg = _config_for(key[0], platform, configs, method)
            recorded = cfg.get("bmr_config") == "bm2_config"
            setting = {
                "source": "recorded" if recorded else "inferred",
                "bmr": bmr_record(cfg),
                "constant_variance": not cfg["is_ncv"],
                "models": [_MODEL_NAMES.get(m, str(m)) for m in cfg["models"]],
            }
            if recorded:
                setting["analysis"] = _recorded_analysis(notes_of.get(key) or [])
            sig = json.dumps(setting, sort_keys=True)
            group = groups.setdefault(sig, {**setting, "platforms": {}})
            group["platforms"].setdefault(platform, []).extend([key[0]] if key[0] else [])
    # Recorded analyses first; each kind in the order its first assay appears.
    settings = sorted(groups.values(), key=lambda g: g["source"] != "recorded")
    return {"engine": engine, "settings": settings}


def platform_bmrs(record: dict | None, platform: str,
                  sexes: list[str] | None = None) -> list[dict]:
    """The distinct BMRs ``record`` gives for ``platform`` (for ``sexes`` when
    given), in the record's order; [] when the record does not cover it."""
    out: list[dict] = []
    want = {str(s).title() for s in sexes} if sexes else None
    for setting in (record or {}).get("settings") or []:
        have = setting.get("platforms", {}).get(platform)
        if not have or (want is not None and not want & set(have)):
            continue
        if setting["bmr"] not in out:
            out.append(setting["bmr"])
    return out


_BMR_MEANS = {"SD": "{n} standard deviation{s} from the mean",
              "RD": "a {pct}% relative deviation from the control mean"}
_NUMBER_WORD = {1: "one", 2: "two", 3: "three"}


def _bmr_meaning(bmr: dict) -> str:
    f = float(bmr["factor"])
    if bmr.get("type") == "RD":
        return _BMR_MEANS["RD"].format(pct=f"{f * 100:g}")
    n = _NUMBER_WORD.get(int(f), f"{f:g}") if f == int(f) else f"{f:g}"
    return _BMR_MEANS["SD"].format(n=n, s="" if f == 1 else "s")


def subscript_tag(tag: str) -> str:
    """"1Std" → "₁Std" (the published legends' form); other tags as written."""
    digits = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
    return tag.translate(digits) if tag.endswith("Std") else tag


def bmd_terms(bmrs: list[dict] | None) -> str:
    """The legend's definition of the BMD and BMDL columns for the BMR(s) the
    table's BMDs were fit at.  One BMR: the published wording ("BMD₁Std =
    benchmark dose corresponding to a benchmark response set to one standard
    deviation from the mean; BMDL₁Std = …").  Several: each named.  None
    recorded: the terms alone — a BMR is never assumed."""
    bmrs = [b for b in bmrs or [] if isinstance(b, dict) and b.get("factor") is not None]
    if len(bmrs) == 1:
        tag, means = subscript_tag(bmr_tag(bmrs[0])), _bmr_meaning(bmrs[0])
        return (f"BMD{tag} = benchmark dose corresponding to a benchmark response "
                f"set to {means}; "
                f"BMDL{tag} = benchmark dose lower confidence limit corresponding "
                f"to a benchmark response set to {means}")
    base = "BMD = benchmark dose; BMDL = benchmark dose lower confidence limit"
    if not bmrs:
        return base
    return base + "; benchmark responses were set to " + " or ".join(
        _bmr_meaning(b) for b in bmrs) + ", by endpoint"
