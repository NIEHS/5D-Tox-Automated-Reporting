"""The Materials and Methods prompt states only what the study data record:
no instrument, kit, schedule, storage condition or analytical method the data
lack, and the gene-set statistic the study's method ranks by (the 2023 books:
median; the 2025 books: 5th percentile).  A fact the data lack is a
Placeholder the model must write verbatim."""

import re

from narrative.methods_models import MethodsContext
from narrative.methods_prompt import build_methods_prompt
from pipeline.method_profile import resolve


def _settings(**genomics) -> dict:
    values = dict(resolve("ntp-5day-2025").values)
    values.update({f"genomics.{k}": v for k, v in genomics.items()})
    return values


def _ctx(**kw) -> MethodsContext:
    ctx = MethodsContext(chemical_name="X", casrn="1-1-1", dtxsid="DTXSID0", dose_unit="mg/kg",
                         dose_groups=[0.0, 4.0, 37.0], sexes=["Male", "Female"], route="gavage",
                         has_body_weight=True, has_organ_weights=True, has_clin_chem=True,
                         has_hematology=True, has_tissue_conc=True, has_gene_expression=True,
                         ge_organs=["liver", "kidney"], clin_chem_endpoints=["Albumin"],
                         biosampling_doses=[4.0, 37.0], pk_timepoints=[2, 24],
                         method_profile="ntp-5day-2025", method_settings=_settings())
    for k, v in kw.items():
        setattr(ctx, k, v)
    return ctx


def _prompt(**kw) -> str:
    system, user = build_methods_prompt(_ctx(**kw))
    return system + "\n" + user


def test_no_procedure_the_data_lack():
    text = _prompt()
    for invented in ("AU680", "Advia", "retroorbital", "cardiac puncture", "RNeasy", "RIN",
                     "-80", "LC-MS", "twice daily", "cage-side", "flash-frozen",
                     "principal component"):
        assert invented not in text, invented
    for placeholder in ("the clinical observation schedule", "the blood collection method",
                        "the internal dose sample handling", "the transcriptomic sample collection",
                        "the sequencing quality checks"):
        assert f"[Placeholder: {placeholder}" in text, placeholder


def test_the_duration_is_the_studys():
    text = _prompt(duration_days=28)
    assert "28-day genomic dose-response studies" in text and "5-day" not in text


def test_internal_dose_states_what_the_data_record():
    text = _prompt()
    assert ("animals dedicated for internal dose assessment in the 4, 37 mg/kg groups; plasma "
            "concentrations were measured at 2 and 24 hours postdose") in text
    inhaled = _prompt(dose_unit="ppm", route="inhaled", pk_timepoints=[])
    assert "animals dedicated for internal concentration assessment in the 4, 37 ppm groups." in inhaled


def test_the_gene_set_statistic_is_the_methods():
    median = _prompt(method_settings=_settings(go_ranking=["median"],
                                               go_display={"pct": 5, "min_bmd": 3}))
    assert "at the median of the set's gene BMDs" in median
    assert "5th percentile" not in median
    assert "at least 3 genes passed all filters and at least 5% of the set" in median
    p5 = _prompt(method_settings=_settings(go_ranking=["fifth_pct", "median"]))
    assert "at the 5th percentile of the set's gene BMDs" in p5
    unknown = _prompt(method_settings=_settings(go_ranking=None, go_display=None))
    assert "[Placeholder: the gene-set potency statistic is not in the study data]" in unknown
    assert not re.search(r"at least \d+ genes", unknown)
