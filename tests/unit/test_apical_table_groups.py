"""
An apical table's row groups (render_common.table_groups, apical_table_plan):
a study's sexes, Male then Female — or, in a report over several studies
(rendering.report_compose), each study's animals ("Rats", "Mice") in data order.
Studies given different dose levels share the union grid, a level a group was
not given showing NA, as the 2026 books print it.
"""

from document_model.document_node import DocNode
from rendering.render_common import apical_table_plan, table_groups


def _row(endpoint, doses, values):
    return {"endpoint": endpoint, "doses": doses, "values": values, "bmd": "ND", "bmdl": "ND"}


def _plan(table_data):
    node = DocNode(id="t", title="T", node_type="table", platform="Body Weight")
    data = {"apical_sections": [{"platform": "Body Weight", "dose_unit": "ppm",
                                 "caption": "Body Weights", "table_data": table_data}]}
    return apical_table_plan(node, data)


def test_sexes_come_male_then_female():
    td = {"Female": [_row("f", [0], ["1"])], "Male": [_row("m", [0], ["2"])]}
    assert [g for g, _ in table_groups(td)] == ["Male", "Female"]


def test_other_groups_follow_in_data_order_and_empty_ones_drop():
    td = {"Rats": [_row("r", [0], ["1"])], "Mice": [_row("m", [0], ["2"])], "Dogs": []}
    assert [g for g, _ in table_groups(td)] == ["Rats", "Mice"]


def test_one_grid_is_kept_as_is():
    plan = _plan({"Male": [_row("BW", [0.0, 10.0], ["1", "2"])]})
    assert plan.doses == [0.0, 10.0]
    assert plan.sex_blocks[0].rows[0].cells[:3] == ["BW", "1", "2"]


def test_groups_with_different_dose_levels_share_the_union():
    plan = _plan({"Rats": [_row("BW", [0, 1, 10, 800], ["a", "b", "c", "d"])],
                  "Mice": [_row("BW", [0, 10, 400], ["e", "f", "g"])]})
    assert plan.doses == [0, 1, 10, 400, 800]
    assert [b.sex_label for b in plan.sex_blocks] == ["Rats", "Mice"]
    rats, mice = (b.rows[0].cells for b in plan.sex_blocks)
    assert rats[1:6] == ["a", "b", "c", "NA", "d"]
    assert mice[1:6] == ["e", "NA", "f", "g", "NA"]
    assert plan.ncols == 1 + 5 + 2
