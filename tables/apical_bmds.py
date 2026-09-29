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
    are INFERRED per assay family and flagged `bmr_config="inferred"` for data-team
    verification (an inferred fill is render-gated until per-endpoint approval).

Model averaging (Laplace, the BMDExpress default) is used because the .bm2's own
results are model-averaged (`bestStatResult.@type == "modelaveraging"`) — like-for-like.
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
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


# Assay-family BMR fallback for a platform with NO recorded .bm2 config. In practice
# every BMD-modeled apical platform in a real .bm2 carries a config (Clinical Chemistry
# → REL/0.25; Organ/Body Weight, Hematology, Hormones → SD/1.0), so this only fires for
# a genuinely config-less platform (an unmodeled incidence/PK platform), whose result is
# then flagged `inferred` for data-team verification.
_ASSAY_FAMILY_BMR: dict[str, tuple[int, float]] = {
    "clinical chemistry": (_BMR_REL, 0.25),
    "hormones": (_BMR_SD, 1.0),
    "hematology": (_BMR_SD, 1.0),
    "organ weight": (_BMR_SD, 1.0),
    "body weight": (_BMR_SD, 1.0),
    "clinical observations": (_BMR_SD, 1.0),
    "tissue concentration": (_BMR_REL, 0.25),
}


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


def _config_for(sex: str, platform: str, configs: dict) -> dict:
    """Resolve the fit config for one endpoint: recorded (from .bm2) if present, else
    INFERRED from the assay family (flagged for data-team verification)."""
    recorded = configs.get((sex, _canon_platform(platform)))
    if recorded is not None:
        return recorded
    # No recorded config → infer per assay family.
    fam = _ASSAY_FAMILY_BMR.get(platform.strip().lower())
    bmr_type, bmr_factor = fam if fam else (_BMR_SD, 1.0)
    return {
        "models": _DEFAULT_MODELS,
        "bmr_type": bmr_type,
        "bmr_factor": bmr_factor,
        "is_ncv": False,
        "bmr_config": "inferred",  # render-gated until per-endpoint approval
    }


# ---------------------------------------------------------------------------
# Batch endpoint modeling (ToxicR via the Java helper)
# ---------------------------------------------------------------------------

def run_bmds_for_endpoints(
    endpoint_data: list[dict],
    configs: dict[tuple[str, str], dict] | None = None,
) -> dict[str, dict]:
    """Fit apical BMDs for a batch of endpoints via the ToxicR Java engine.

    `endpoint_data` is the list of enriched `_bmds_input` dicts (each carries per-animal
    `Y` + `doses_per_animal`, plus `sex`, `endpoint`, and the summary stats). `configs`
    is the {(sex, platform_token): config} map from `parse_bmd_configs`; when a platform
    has no recorded config the fit config is inferred per assay family and flagged.

    Returns {key: {bmd, bmdl, bmdu, model_name, status, notes, bmr_config}} — the same
    shape the former pybmds path returned, plus `bmr_config` (bm2_config | inferred) for
    the render gate. Endpoints lacking per-animal data are skipped (nothing to model).
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
        cfg = _config_for(sex, platform, configs)
        cfg_by_key[ep["key"]] = cfg["bmr_config"]
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
    results = run_apical_bmds_java(payload)

    # Stamp the config provenance onto each result so the reconcile/render gate can
    # tell an inferred-BMR fill (needs approval) from a recorded-config one.
    for key, res in results.items():
        res["bmr_config"] = cfg_by_key.get(key, "inferred")
        if res.get("status") == "viable":
            logger.info(
                "ToxicR %s: BMD=%s BMDL=%s (%s, %s)",
                key, res.get("bmd"), res.get("bmdl"),
                res.get("model_name"), res["bmr_config"],
            )
        else:
            logger.info("ToxicR %s: %s — %s", key, res.get("status"), res.get("notes"))
    return results
