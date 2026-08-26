"""
test_footnote_model.py — Tests for the typed footnote model.

Covers the model defined in table_builder_common.py: the record
constructors (legend_footnote / definition_footnote / lettered_footnote)
and finalize_footnotes(), which is the single lettering authority — it
assigns a/b/c... letters to `lettered` records and derives each row's
`markers` dict from its stable `marker_refs`.
"""

from __future__ import annotations

import pytest

from tables.table_builder_common import (
    legend_footnote,
    definition_footnote,
    lettered_footnote,
    finalize_footnotes,
    build_n_row,
    detect_core_animal_availability,
    build_sample_availability_footnotes,
    build_attrition_footnote,
    is_reportable_bmd,
)


class TestIsReportableBmd:
    """is_reportable_bmd — the `reportable` half of the row-emphasis rule."""

    def test_real_values_are_reportable(self):
        # A numeric BMD and the BMDExpress status codes all count as
        # "BMDExpress modeled it".
        for v in ("86.9", "0.15", "NVM", "UREP", "<0.05"):
            assert is_reportable_bmd(v) is True, v

    def test_sentinels_are_not_reportable(self):
        # The "nothing here" sentinels used across the apical builders.
        for v in ("—", "ND", "NA", "", "  ", None):
            assert is_reportable_bmd(v) is False, repr(v)


def _sidecar(animals: dict) -> dict:
    """Build a minimal sidecar dict.  `animals` maps id -> (dose, selection,
    [observation value, ...])."""
    return {
        "animals": {
            aid: {
                "dose": dose,
                "selection": selection,
                "observations": [{"value": v} for v in values],
            }
            for aid, (dose, selection, values) in animals.items()
        }
    }


class TestFootnoteConstructors:
    """The three record constructors produce the expected shapes."""

    def test_legend_footnote_shape(self):
        assert legend_footnote("hello") == {"kind": "legend", "text": "hello"}

    def test_definition_footnote_shape(self):
        assert definition_footnote("defn") == {"kind": "definition", "text": "defn"}

    def test_lettered_footnote_default_target_none(self):
        fn = lettered_footnote("text", "my_id")
        assert fn == {
            "kind": "lettered",
            "text": "text",
            "id": "my_id",
            "marker": {"target": "none"},
        }

    def test_lettered_footnote_explicit_targets(self):
        for target in ("header", "cells", "none"):
            fn = lettered_footnote("t", "i", target=target)
            assert fn["marker"]["target"] == target

    def test_lettered_footnote_rejects_bad_target(self):
        with pytest.raises(ValueError):
            lettered_footnote("t", "i", target="sidebar")


class TestFinalizeFootnotes:
    """finalize_footnotes assigns letters and derives row markers."""

    def test_lettered_get_sequential_letters(self):
        fns = [
            lettered_footnote("first", "f1"),
            lettered_footnote("second", "f2"),
            lettered_footnote("third", "f3"),
        ]
        finalize_footnotes(fns, {})
        assert [f["letter"] for f in fns] == ["a", "b", "c"]

    def test_legend_and_definition_skip_lettering(self):
        # legend / definition records carry no letter, and they do NOT
        # consume a letter slot — the lettered records still get a, b, c.
        fns = [
            legend_footnote("L"),
            definition_footnote("D"),
            lettered_footnote("first", "f1"),
            lettered_footnote("second", "f2"),
        ]
        finalize_footnotes(fns, {})
        assert "letter" not in fns[0]
        assert "letter" not in fns[1]
        assert fns[2]["letter"] == "a"
        assert fns[3]["letter"] == "b"

    def test_row_markers_derived_from_marker_refs(self):
        # A row carrying marker_refs ({dose_key: footnote_id}) gets a
        # `markers` dict ({dose_key: letter}) derived by id resolution.
        fns = [
            lettered_footnote("data format", "data_format"),
            lettered_footnote("attrition", "attr_333", target="cells"),
        ]
        rows = {
            "Male": [
                {"label": "n", "marker_refs": {"333": "attr_333"}},
                {"label": "Liver"},  # no marker_refs — untouched
            ],
        }
        finalize_footnotes(fns, rows)
        # attr_333 is the 2nd lettered footnote -> letter "b"
        assert rows["Male"][0]["markers"] == {"333": "b"}
        assert "markers" not in rows["Male"][1]

    def test_unknown_marker_ref_is_dropped(self):
        # A marker_ref pointing at an id with no matching footnote is
        # dropped rather than rendered as a dangling marker.
        fns = [lettered_footnote("real", "real_id", target="cells")]
        rows = {"Male": [{"label": "n", "marker_refs": {"0": "ghost_id"}}]}
        finalize_footnotes(fns, rows)
        assert rows["Male"][0]["markers"] == {}

    def test_idempotent_rerun(self):
        # finalize_footnotes always re-derives markers from the stable
        # marker_refs, so running it twice yields the same result — this
        # is what lets report_data.py merge in more footnotes and re-run.
        fns = [
            lettered_footnote("a-note", "n_a", target="cells"),
            lettered_footnote("b-note", "n_b", target="cells"),
        ]
        rows = {"Male": [{"label": "n", "marker_refs": {"0": "n_a", "37": "n_b"}}]}
        finalize_footnotes(fns, rows)
        first = dict(rows["Male"][0]["markers"])
        finalize_footnotes(fns, rows)
        assert rows["Male"][0]["markers"] == first == {"0": "a", "37": "b"}

    def test_rerun_after_append_reletters_whole_list(self):
        # Appending a footnote and re-running re-letters everything —
        # the appended record picks up the next letter, existing ones keep
        # theirs (same order), and any new marker_refs resolve.
        fns = [lettered_footnote("first", "f1", target="cells")]
        rows = {"Male": [{"label": "n", "marker_refs": {"0": "f1", "37": "f2"}}]}
        finalize_footnotes(fns, rows)
        assert rows["Male"][0]["markers"] == {"0": "a"}  # f2 not yet present
        fns.append(lettered_footnote("second", "f2", target="cells"))
        finalize_footnotes(fns, rows)
        assert fns[0]["letter"] == "a"
        assert fns[1]["letter"] == "b"
        assert rows["Male"][0]["markers"] == {"0": "a", "37": "b"}

    def test_none_serialized_rows_is_safe(self):
        # A footnote list with no cell markers can pass serialized_rows=None.
        fns = [lettered_footnote("note", "n1")]
        finalize_footnotes(fns, None)
        assert fns[0]["letter"] == "a"


class TestBuildNRowMarkerRefs:
    """build_n_row writes marker_refs (stable ids), not letters."""

    def test_n_row_carries_marker_refs_not_markers(self):
        row = build_n_row(
            {0.0: [1, 2, 3], 333.0: []},
            [0.0, 333.0],
            marker_refs={333.0: "attrition"},
        )
        assert row["marker_refs"] == {"333": "attrition"}
        assert "markers" not in row  # markers is derived later by finalize

    def test_n_row_without_marker_refs_omits_the_key(self):
        row = build_n_row({0.0: [1, 2]}, [0.0])
        assert "marker_refs" not in row


# ---------------------------------------------------------------------------
# Shared apical missing-animal pipeline — detection + the two footnote
# builders that clinical_pathology_table.py and organ_weight_table.py share.
# ---------------------------------------------------------------------------

class TestDetectCoreAnimalAvailability:
    """detect_core_animal_availability splits Core Animals by data presence."""

    def test_biosampling_animals_excluded(self):
        sc = {"Male": _sidecar({
            "a1": (0.0, "Core Animals", ["5.0"]),
            "b1": (0.0, "Biosampling Animals", ["9.0"]),
        })}
        core_n, total, missing = detect_core_animal_availability(sc)
        # Only the Core Animal counts; the Biosampling one is ignored.
        assert total["Male"] == {0.0: 1}
        assert core_n["Male"] == {0.0: 1}

    def test_all_na_animal_is_missing(self):
        sc = {"Male": _sidecar({
            "a1": (0.0, "Core Animals", ["5.0"]),
            "a2": (0.0, "Core Animals", ["NA"]),
            "a3": (0.0, "Core Animals", ["", "  "]),
        })}
        core_n, total, missing = detect_core_animal_availability(sc)
        assert total["Male"] == {0.0: 3}
        assert core_n["Male"] == {0.0: 1}            # only a1 has data
        assert sorted(missing["Male"][0.0]) == ["a2", "a3"]

    def test_unknown_selection_treated_as_core(self):
        # A sidecar with no Selection column reports "Unknown" — those
        # animals are implicitly Core Animals and must be counted.
        sc = {"Female": _sidecar({"a1": (1.0, "Unknown", ["3.3"])})}
        core_n, total, missing = detect_core_animal_availability(sc)
        assert total["Female"] == {1.0: 1}
        assert core_n["Female"] == {1.0: 1}


class TestBuildSampleAvailabilityFootnotes:
    """Sample-availability footnotes are deduped by count, whole-group skipped."""

    def test_deduped_by_count_across_doses_and_sexes(self):
        # Two doses with one missing sample each + one dose with two:
        # expect exactly two footnotes (count 1, count 2), and every
        # affected n-cell points at the right one.
        missing = {
            "Male": {0.0: ["a"], 1.0: ["b", "c"], 2.0: ["d"]},
            "Female": {0.0: ["e"]},
        }
        totals = {
            "Male": {0.0: 5, 1.0: 5, 2.0: 5},
            "Female": {0.0: 5},
        }
        records, refs = build_sample_availability_footnotes(
            missing, totals, [0.0, 1.0, 2.0],
        )
        # First appearance: Male 0.0 count1 -> first; Male 1.0 count2 -> second.
        assert [r["id"] for r in records] == [
            "sample_avail_count_1", "sample_avail_count_2",
        ]
        assert all(r["kind"] == "lettered" for r in records)
        assert all(r["marker"]["target"] == "cells" for r in records)
        # Every count-1 cell -> count_1 footnote; the count-2 cell -> count_2.
        assert refs["Male"] == {
            0.0: "sample_avail_count_1",
            1.0: "sample_avail_count_2",
            2.0: "sample_avail_count_1",
        }
        assert refs["Female"] == {0.0: "sample_avail_count_1"}

    def test_whole_group_dead_dose_is_skipped(self):
        # A dose where every Core Animal is missing data is whole-group
        # attrition, not sample-availability — it must not emit a footnote
        # here (build_attrition_footnote handles it).
        missing = {"Male": {333.0: ["a", "b", "c"]}}
        totals = {"Male": {333.0: 3}}
        records, refs = build_sample_availability_footnotes(
            missing, totals, [333.0],
        )
        assert records == []
        assert refs == {"Male": {}, "Female": {}}

    def test_no_missing_animals_yields_nothing(self):
        records, refs = build_sample_availability_footnotes(
            {"Male": {}, "Female": {}}, {"Male": {}, "Female": {}}, [0.0],
        )
        assert records == []


class TestBuildAttritionFootnote:
    """build_attrition_footnote emits one footnote for whole dead dose groups."""

    def test_dead_dose_groups_derive_text_and_marker(self):
        # Male 333 + Female 333 fully dead -> one footnote, doses derived,
        # marker on the first (Male, 333) cell.
        total = {"Male": {0.0: 5, 333.0: 5}, "Female": {0.0: 5, 333.0: 5}}
        core_n = {"Male": {0.0: 5, 333.0: 0}, "Female": {0.0: 5, 333.0: 0}}
        record, refs = build_attrition_footnote(
            total, core_n, [0.0, 333.0], "mg/kg",
        )
        assert record is not None
        assert record["id"] == "attrition"
        assert record["marker"]["target"] == "cells"
        assert "male and female" in record["text"]
        assert "333 mg/kg" in record["text"]
        assert refs == {"Male": {333.0: "attrition"}}

    def test_no_dead_groups_returns_none(self):
        total = {"Male": {0.0: 5}}
        core_n = {"Male": {0.0: 5}}
        record, refs = build_attrition_footnote(total, core_n, [0.0], "mg/kg")
        assert record is None
        assert refs == {}

    def test_single_sex_text(self):
        total = {"Male": {1000.0: 4}}
        core_n = {"Male": {1000.0: 0}}
        record, refs = build_attrition_footnote(
            total, core_n, [1000.0], "mg/kg",
        )
        # Only males dead -> text says "male", not "male and female".
        assert record["text"].startswith("All male 1,000 mg/kg")
