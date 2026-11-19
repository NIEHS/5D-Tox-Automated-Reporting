"""tables/row_sources.py — the dataset endpoints a row of a results table is
built from.

A results table names its rows as the published reports do, which is seldom
the name the dataset holds the endpoint under: "Heart Relative (mg/g)" is the
endpoint "Heart" divided by "Terminal Body Weight"; the body weight row "4" is
the endpoint "SD4"; "A/G Ratio" has no endpoint of its own.  ``row_sources``
gives, for a row's label, the endpoints of the dataset it is built from and,
where it is computed, how.

Each rule is the builder's own naming read back: the organ weight labels
(tables.organ_weight_table.row_label), the study day of a body weight endpoint
(tables.body_weight_table._study_day_label), the matrix of a concentration
endpoint (tables.blood_tissue_concentration_table) and the derived clinical
chemistry endpoints (bmdx_pipe.apical_report.DERIVED_INPUTS).  It parses no
free text: a label none of these makes gives None, and the caller says the
link is not known.
"""

from __future__ import annotations

from collections.abc import Iterable


def _named(name: str, endpoints: list[str]) -> str | None:
    """The dataset's endpoint of this name (as the derivations find one:
    case and outer spaces aside)."""
    want = name.strip().lower()
    return next((e for e in endpoints if e.strip().lower() == want), None)


def _organ_weight(label: str, endpoints: list[str]) -> dict | None:
    from tables.organ_weight_table import ABSOLUTE, RELATIVE, TERMINAL_BODY_WEIGHT, row_label

    def is_row(name: str) -> bool:
        # row_label(name, unit) for any unit: the name, then the unit in brackets.
        return label.startswith(row_label(name, "")[:-1])

    body = _named(TERMINAL_BODY_WEIGHT, endpoints)
    if body and is_row(TERMINAL_BODY_WEIGHT):
        return {"endpoints": [body], "how": None}
    for organ in endpoints:
        if is_row(f"{organ} {ABSOLUTE}"):
            return {"endpoints": [organ], "how": None}
        if body and is_row(f"{organ} {RELATIVE}"):
            return {"endpoints": [organ, body],
                    "how": "the organ's weight divided by the terminal body weight, per animal"}
    return None


def _body_weight(label: str, endpoints: list[str]) -> dict | None:
    from tables.body_weight_table import _study_day_label

    for endpoint in endpoints:
        day = _study_day_label(endpoint)
        if day != endpoint and day == label:
            return {"endpoints": [endpoint], "how": f"the body weight on study day {day}"}
    return None


def _clinical_chemistry(label: str, endpoints: list[str]) -> dict | None:
    from bmdx_pipe.apical_report import DERIVED_INPUTS

    if label not in DERIVED_INPUTS:
        return None
    inputs, how = DERIVED_INPUTS[label]
    found: list[str] = []
    for name in inputs:
        endpoint = _named(name, endpoints)
        if endpoint is None and name in DERIVED_INPUTS:
            # An input that is itself derived (Globulin, when it was not measured).
            inner = _clinical_chemistry(name, endpoints)
            if inner is None:
                return None
            found += [e for e in inner["endpoints"] if e not in found]
            how = f"{how}; {name.lower()} is {inner['how']}"
        elif endpoint is None:
            return None
        elif endpoint not in found:
            found.append(endpoint)
    return {"endpoints": found, "how": how}


def _tissue_concentration(label: str, endpoints: list[str]) -> dict | None:
    from tables.blood_tissue_concentration_table import (
        _CONC, _limit_endpoint, concentration_label, normalized_label,
    )

    for endpoint in endpoints:
        m = _CONC.match(endpoint)
        limit = _limit_endpoint(endpoint, endpoints) if m else None
        if not limit:
            continue
        matrix = m.group("matrix").title()
        with_limit = f"with each sample's limit ({limit})"
        if label.startswith(concentration_label(matrix, "")[:-1]):
            return {"endpoints": [endpoint, limit], "how": with_limit}
        if label.startswith(normalized_label(matrix, "", "").split("[")[0]):
            return {"endpoints": [endpoint, limit],
                    "how": f"divided by the exposure concentration, {with_limit}"}
    return None


_RULES = {
    "Organ Weight": _organ_weight,
    "Body Weight": _body_weight,
    "Clinical Chemistry": _clinical_chemistry,
    "Tissue Concentration": _tissue_concentration,
}


def row_sources(platform: str | None, label: str, endpoints: Iterable[str]) -> dict | None:
    """``{"endpoints": [names], "how": words | None}``: the endpoints of the
    dataset (``endpoints``: those of the table's experiment) that the row
    ``label`` of a ``platform`` table is built from.  ``how`` is None when the
    row shows one endpoint as it is recorded.  None when no rule of the
    builders names an endpoint for the label."""
    names = list(endpoints)
    if label in names:
        return {"endpoints": [label], "how": None}
    rule = _RULES.get(platform or "")
    return rule(label, names) if rule else None
