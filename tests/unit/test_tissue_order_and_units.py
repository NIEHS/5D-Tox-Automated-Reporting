"""Two derived facts the hard-coding audit fixed:

- the tissues come in the report's tissue order (a definition's tissue_order:
  the 2023 books liver first, the 2026 books alphabetical) everywhere they are
  listed — the tables, the references, the Summary, the PCA figure — not a
  fixed liver-then-kidney;
- the body weight and organ weight units are the ones the Key sheets record,
  a Placeholder when they record none.
"""

import json

from document_model.document_tree import order_tissues, tissue_key
from narrative.references_builder import collect_reference_strata
from tables.body_weight_table import data_format_footnote
from tables.organ_weight_table import weight_units


def test_tissue_key_names_first_then_alphabetical():
    tissues = ["Ovary", "liver", "Heart", "kidney", "Lung"]
    assert sorted(tissues, key=tissue_key([])) == ["Heart", "kidney", "liver", "Lung", "Ovary"]
    assert sorted(tissues, key=tissue_key(["liver", "kidney"])) == \
        ["liver", "kidney", "Heart", "Lung", "Ovary"]
    assert [e["organ"] for e in order_tissues([{"organ": "Liver"}, {"organ": "Heart"}], [])] == \
        ["Heart", "Liver"]


def test_references_follow_the_report_tissue_order(tmp_path):
    from genomics.genomics_narratives import interpretation_cache_prefix
    for organ in ("liver", "heart"):
        (tmp_path / f"{interpretation_cache_prefix(organ, 'female')}x.json").write_text(
            json.dumps({"reference_pool": [{"paper_id": organ}]}))
    cache = {"liver_female": {}, "heart_female": {}}
    assert [s["organ"] for s in collect_reference_strata(tmp_path, cache, [])] == ["heart", "liver"]
    assert [s["organ"] for s in collect_reference_strata(tmp_path, cache, ["liver"])] == \
        ["liver", "heart"]


def test_weight_units_come_from_the_key_sheets():
    recorded = [{"units": {"Liver": "grams", "Terminal Body Weight": "grams"}}]
    assert weight_units(recorded) == {"absolute": "g", "body": "g", "relative": "mg/g",
                                      "relative_organ": "mg"}
    assert data_format_footnote([{"units": {"Body Weight": "grams"}}]).endswith(
        "body weight data are presented in grams.")
    assert data_format_footnote([{"units": {"Body Weight": "g"}}]).endswith("presented in grams.")


def test_an_unrecorded_weight_unit_is_a_placeholder():
    units = weight_units([{"units": {}}])
    assert units["absolute"] == "[Placeholder: organ weight unit not recorded in the data]"
    assert units["relative"].startswith("[Placeholder:")
    assert "[Placeholder: body weight unit not recorded in the data]" in data_format_footnote([{}])
