"""
Unit tests for the Phase-1 filter-unification surface:

  1. tables.table_builder_common.filter_allows — the single predicate behind the
     five named matchers, with its three modes (exact / component / dual). The
     named wrappers' behavior is pinned by test_axis_filters.py / test_organ_filter.py;
     here we pin the unified entry point and that each mode matches its wrapper.
  2. document_template.normalize_filters / resolve_report_allowlist — the canonical
     {dimension: {area: {sex_key: [tokens]}}} representation that folds the three
     legacy loader shapes (flat, per-area, per-area-per-sex) into one.
  3. The organ-weight NARRATIVE now honors the organ-weight sex allowlist (bug fix:
     it previously looped a fixed Male/Female and could name a sex the table dropped).
"""

import pytest

from document_model.filters import (
    filter_allows,
    sex_allowed,
    organ_allowed,
    gene_set_allowed,
)
from document_model.document_template import (
    normalize_filters,
    resolve_report_allowlist,
    _normalize_dimension,
)


# ---------------------------------------------------------------------------
# 1. filter_allows — the three modes
# ---------------------------------------------------------------------------

class TestFilterAllows:
    def test_empty_allowlist_is_no_filter_in_every_mode(self):
        for mode in ("exact", "component", "dual"):
            assert filter_allows("anything", None, mode=mode) is True
            assert filter_allows("anything", [], mode=mode) is True

    def test_exact_mode_matches_sex_allowed(self):
        # exact, case-insensitive, NOT component-wise
        assert filter_allows("Male", ["male"], mode="exact") is True
        assert filter_allows("Female", ["male"], mode="exact") is False
        # parity with the named wrapper
        for cand, allow in [("Male", ["male"]), ("Female", ["male"]), ("male", None)]:
            assert filter_allows(cand, allow, mode="exact") == sex_allowed(cand, allow)

    def test_component_mode_matches_organ_allowed(self):
        assert filter_allows("Kidney-Left", ["kidney"], mode="component") is True
        assert filter_allows("Liver", ["kidney"], mode="component") is False
        for cand, allow in [("Kidney-Left", ["kidney"]), ("R. Kidney", ["kidney"]),
                            ("Liver", ["kidney"])]:
            assert filter_allows(cand, allow, mode="component") == organ_allowed(cand, allow)

    def test_dual_mode_matches_gene_set_allowed(self):
        # go_id (alt_id) exact OR go_term component
        assert filter_allows("cell division", ["go:0051301"],
                             mode="dual", alt_id="GO:0051301") is True
        assert filter_allows("cell division", ["division"],
                             mode="dual", alt_id="GO:9999999") is True
        assert filter_allows("apoptosis", ["division"],
                             mode="dual", alt_id="GO:9999999") is False
        # parity with the named wrapper (note wrapper arg order: go_id, go_term)
        assert filter_allows("cell division", ["division"], mode="dual",
                             alt_id="GO:1") == gene_set_allowed("GO:1", "cell division",
                                                                ["division"])


# ---------------------------------------------------------------------------
# 2. Canonical normalization
# ---------------------------------------------------------------------------

class TestNormalizeFilters:
    def test_flat_shape(self):
        assert _normalize_dimension(["egr1", "ddit4"]) == {"*": {"*": ["egr1", "ddit4"]}}

    def test_per_area_shape(self):
        assert _normalize_dimension({"genomics": ["kidney"], "organ-weight": ["liver"]}) == {
            "genomics": {"*": ["kidney"]},
            "organ-weight": {"*": ["liver"]},
        }

    def test_per_area_per_sex_shape(self):
        assert _normalize_dimension(
            {"hematology": {"male": ["neutrophil count"], "female": ["manual hematocrit"]}}
        ) == {"hematology": {"male": ["neutrophil count"], "female": ["manual hematocrit"]}}

    def test_empty_inputs_omitted(self):
        assert _normalize_dimension(None) == {}
        assert _normalize_dimension([]) == {}
        assert normalize_filters(organs={}, sex=None, assays={}, genes=[], gene_sets=[]) == {}

    def test_compose_and_resolve(self):
        f = normalize_filters(
            organs={"organ-weight": ["liver"]},
            sex={"apical": ["male"]},
            assays={"hematology": {"male": ["neutrophil count"]}},
            genes=["egr1"],
            gene_sets=[],
        )
        # dimension → area → sex resolution with "*" fallback
        assert resolve_report_allowlist(f, "sex", "apical") == ["male"]
        assert resolve_report_allowlist(f, "assays", "hematology", "male") == ["neutrophil count"]
        # per-sex area, other sex absent → None (that sex unfiltered)
        assert resolve_report_allowlist(f, "assays", "hematology", "female") is None
        # flat dimension resolves via "*" area regardless of requested area
        assert resolve_report_allowlist(f, "genes", "genomics") == ["egr1"]
        # absent dimension/area → None (no filtering)
        assert resolve_report_allowlist(f, "organs", "genomics") is None
        assert resolve_report_allowlist(f, "gene_sets") is None


# ---------------------------------------------------------------------------
# 3. Organ-weight narrative honors the organ-weight sex allowlist (bug fix)
# ---------------------------------------------------------------------------

class TestOrganWeightNarrativeSex:
    def _tables(self):
        from bmdx_pipe import TableRow

        def row(label):
            r = TableRow(label=label)
            # minimal fields the narrative reads
            r.responsive = False
            r.bmd_str = "ND"
            return r

        return {
            "Organ Weight": {
                "Male": [row("Absolute Liver Weight")],
                "Female": [row("Absolute Liver Weight")],
            }
        }

    def test_sex_allowlist_drops_female_paragraph(self):
        from narrative.unified_narrative import _build_organ_weight_paragraphs

        both = _build_organ_weight_paragraphs(self._tables(), "PFHxSAm", "mg/kg")
        assert any("male rats" in p.lower() for p in both)
        assert any("female rats" in p.lower() for p in both)

        male_only = _build_organ_weight_paragraphs(
            self._tables(), "PFHxSAm", "mg/kg", sex_allowlist=["male"]
        )
        joined = " ".join(male_only).lower()
        assert "male rats" in joined
        assert "female rats" not in joined

    def test_no_sex_allowlist_keeps_both(self):
        from narrative.unified_narrative import _build_organ_weight_paragraphs

        out = _build_organ_weight_paragraphs(
            self._tables(), "PFHxSAm", "mg/kg", sex_allowlist=None
        )
        joined = " ".join(out).lower()
        assert "male rats" in joined and "female rats" in joined
