"""
pipeline/bmds27/engine.py — apical BMDs by NTP's modified BMDS 2.7 package.

The method of the BMDS-era NIEHS reports (NIEHS-02 … NIEHS-10; method profile
ntp-5day-2021, `apical.bmd.engine: bmds_2_7_high_dose_drop`): for each
endpoint, NTP's BMDS 2.7 session with the package's default continuous models
(Linear, Polynomial 2…, Power, Hill, Exponential M2–M5; BMR 1 SD, constant
variance), its rule-based recommendation, and — when no model is recommended —
the highest dose dropped and the models re-run, until one is recommended or
three dose groups remain. All of that is NTP's code (ntp_bmds/, verbatim but
for the patches in PROVENANCE.md); this module only builds the dataset and
reads the result.

The dataset is per dose group: N (non-missing animals), mean and standard
deviation (n − 1) at full precision from the per-animal values — not rounded:
the direction of change (`is_increasing`) sets the model restrictions, and on a
tie it turns on the last bits of the means.
"""

from __future__ import annotations

import math
from collections import OrderedDict

from pipeline.bmds27.ntp_bmds import constants
from pipeline.bmds27.ntp_bmds.datasets import ContinuousDataset
from pipeline.bmds27.runner import Executor, session_class

ENGINE = "bmds_2_7_high_dose_drop"
SOURCE = "bmds27"


def dataset_from_animals(doses_per_animal: list, values: list) -> tuple[ContinuousDataset, list[str]]:
    """NTP's continuous dataset from per-animal values, and notes on groups
    left out (a group needs two animals for a standard deviation)."""
    groups: dict[float, list[float]] = OrderedDict()
    for d, y in zip(doses_per_animal, values):
        if y is None or (isinstance(y, float) and math.isnan(y)):
            continue
        groups.setdefault(float(d), []).append(float(y))
    doses, ns, means, sds, notes = [], [], [], [], []
    for d in sorted(groups):
        ys = groups[d]
        if len(ys) < 2:
            notes.append(f"dose {d:g} left out: {len(ys)} animal(s)")
            continue
        m = sum(ys) / len(ys)
        doses.append(d)
        ns.append(len(ys))
        means.append(m)
        sds.append(math.sqrt(sum((y - m) ** 2 for y in ys) / (len(ys) - 1)))
    return ContinuousDataset(doses=doses, ns=ns, means=means, stdevs=sds), notes


def run_dataset(dataset: ContinuousDataset, executor: Executor):
    """NTP's session on `dataset`: default models, execute, recommend, and drop
    the highest dose while nothing is recommended. Returns the final session;
    earlier rounds are in its `doses_dropped_sessions`."""
    session = session_class(executor)(constants.CONTINUOUS, dataset=dataset)
    session.add_default_models()
    session.execute_and_recommend(drop_doses=True)
    return session


def session_rows(session) -> list[dict]:
    """Every model of every round, as NTP's package tabulates them (the
    Parameter workbook's columns, dfile and output file included)."""
    od = session._df_ordered_dict(include_io=True)
    session._add_to_to_ordered_dict(od, 0)
    keys = list(od)
    return [dict(zip(keys, vals)) for vals in zip(*od.values())]


def _bmr(model) -> dict:
    values = getattr(model, "values", None) or {}
    kind = constants.BMR_INVERTED_CROSSALK[constants.CONTINUOUS].get(values.get("bmr_type"))
    return {"type": {"Std. Dev.": "sd", "Rel. Dev.": "rel_dev"}.get(kind, kind),
            "factor": values.get("bmr")}


def result_of(session) -> dict:
    """The endpoint's result in the shape the ToxicR path returns
    (tables.apical_bmds.run_bmds_for_endpoints), plus what NTP's run decided."""
    model = session.recommended_model
    base = {"source": SOURCE, "doses_dropped": session.doses_dropped,
            "bmr_config": "engine_default"}
    if model is None:
        failures = sorted({n for m in session.models
                           for n in (getattr(m, "logic_notes", {}) or {}).get(constants.BIN_FAILURE, [])})
        return {**base, "status": "NVM", "bmd": None, "bmdl": None, "bmdu": None,
                "model_name": None, "recommended_variable": None,
                "bmr": _bmr(session.models[0]) if session.models else None,
                "notes": "no model recommended" + (f" ({'; '.join(failures[:3])})" if failures else "")}
    out = model.output
    cautions = (model.logic_notes or {}).get(constants.BIN_NO_CHANGE, [])
    return {**base, "status": "viable", "bmd": out.get("BMD"), "bmdl": out.get("BMDL"),
            "bmdu": out.get("BMDU"), "model_name": model.name,
            "recommended_variable": model.recommended_variable, "bmr": _bmr(model),
            "cautions": list(cautions), "notes": "; ".join(cautions)}


def run_endpoints(endpoint_data: list[dict], *, executor: Executor) -> tuple[dict, dict]:
    """Model each endpoint (the `bmds_inputs` dicts the ToxicR path receives:
    key, sex, endpoint, per-animal `Y` + `doses_per_animal`).

    Returns (results, record): results {key: result_of(...)}, and the full
    record {key: {dataset, notes, runs}} — every model of every round, the
    audit trail the CEBS Parameter workbooks are for NTP's own runs."""
    results: dict[str, dict] = {}
    record: dict[str, dict] = {}
    for ep in endpoint_data:
        key = ep["key"]
        Y, doses = ep.get("Y"), ep.get("doses_per_animal")
        if not Y or not doses or len(Y) != len(doses):
            continue
        try:
            dataset, notes = dataset_from_animals(doses, Y)
        except ValueError as e:  # fewer than three usable dose groups
            results[key] = {"source": SOURCE, "status": "NVM", "bmd": None, "bmdl": None,
                            "bmdu": None, "model_name": None, "doses_dropped": 0,
                            "bmr_config": "engine_default", "bmr": None,
                            "notes": f"not modelled: {e}"}
            continue
        modelled = {"doses": list(dataset.doses), "ns": list(dataset.ns),
                    "means": list(dataset.means), "stdevs": list(dataset.stdevs)}
        session = run_dataset(dataset, executor)  # drops doses from `dataset` in place
        results[key] = result_of(session)
        if notes:
            results[key]["notes"] = "; ".join(filter(None, [results[key].get("notes"), *notes]))
        record[key] = {"sex": ep.get("sex"), "endpoint": ep.get("endpoint"),
                       "platform": ep.get("platform"), "notes": notes,
                       "dataset": modelled,
                       "runs": session_rows(session)}
    return results, record
