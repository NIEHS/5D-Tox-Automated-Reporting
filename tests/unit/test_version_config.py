"""
Unit tests for report VERSIONS (document_model/version_config.py) — the per-DTXSID
structure+filter projections of one processed dataset (phase 3).

Pins: the store round-trips; 'default' is implicit and undeletable; version names
can't traverse out of versions/; filter resolution falls back to the global
template for 'default'; and the export path (latex_export) applies a version's
apical filters to the phase-2 superset section cache.
"""

import pytest

from document_model import version_config as vc


@pytest.mark.integration
class TestVersionStore:
    def test_default_is_implicit_and_listed(self, sessions_dir):
        assert vc.list_versions("DTXSID_V") == ["default"]

    def test_save_load_list_delete_roundtrip(self, sessions_dir):
        vc.save_version("DTXSID_V", "male-only",
                        {"filters": {"sex": {"apical": {"*": ["male"]}}}})
        assert set(vc.list_versions("DTXSID_V")) == {"default", "male-only"}
        assert vc.load_version("DTXSID_V", "male-only") == {
            "filters": {"sex": {"apical": {"*": ["male"]}}}
        }
        assert vc.delete_version("DTXSID_V", "male-only") is True
        assert vc.list_versions("DTXSID_V") == ["default"]

    def test_default_cannot_be_deleted(self, sessions_dir):
        with pytest.raises(ValueError):
            vc.delete_version("DTXSID_V", "default")

    def test_version_name_traversal_rejected(self, sessions_dir):
        with pytest.raises(ValueError):
            vc.version_path("DTXSID_V", "../evil")
        with pytest.raises(ValueError):
            vc.save_version("DTXSID_V", "a/b", {})

    def test_absent_version_loads_empty(self, sessions_dir):
        assert vc.load_version("DTXSID_V", "nope") == {}

    def test_resolve_default_falls_back_to_global_template(self, sessions_dir):
        # 'default' with no file resolves to the global template's filters.
        resolved = vc.resolve_version_filters("DTXSID_V", "default")
        assert "filters" in resolved
        # the active template ships organs/sex/assays blocks
        assert set(resolved["filters"]) & {"organs", "sex", "assays"}

    def test_resolve_version_own_filters_win(self, sessions_dir):
        vc.save_version("DTXSID_V", "custom",
                        {"filters": {"sex": {"apical": {"*": ["male"]}}}})
        resolved = vc.resolve_version_filters("DTXSID_V", "custom")
        assert resolved["filters"] == {"sex": {"apical": {"*": ["male"]}}}

    def test_save_normalizes_legacy_filter_shape(self, sessions_dir):
        # The friendlier per-area shape (sex: {apical: [male]}) is accepted on
        # save and CANONICALIZED to {apical: {"*": [male]}} — so the render-time
        # consumer (resolve_report_allowlist) never sees a list where it expects
        # a mapping (the bug: it would crash calling .get on a list).
        vc.save_version("DTXSID_V", "legacy",
                        {"filters": {"sex": {"apical": ["male"]},
                                     "genes": ["egr1", "ddit4"]}})
        stored = vc.load_version("DTXSID_V", "legacy")["filters"]
        assert stored == {
            "sex": {"apical": {"*": ["male"]}},
            "genes": {"*": {"*": ["egr1", "ddit4"]}},
        }
        # and it resolves cleanly at render time (no crash)
        from document_model.document_template import resolve_report_allowlist
        resolved = vc.resolve_version_filters("DTXSID_V", "legacy")["filters"]
        assert resolve_report_allowlist(resolved, "sex", "apical") == ["male"]
        assert resolve_report_allowlist(resolved, "genes") == ["egr1", "ddit4"]

    def test_save_rejects_unknown_filter_dimension(self, sessions_dir):
        with pytest.raises(ValueError):
            vc.save_version("DTXSID_V", "bad", {"filters": {"bogus": ["x"]}})

    def test_save_rejects_malformed_filter_tokens(self, sessions_dir):
        # a non-list token leaf is a structural error, caught at save
        with pytest.raises(ValueError):
            vc.save_version("DTXSID_V", "bad", {"filters": {"genes": "egr1"}})

    def test_save_rejects_bad_charts_block(self, sessions_dir):
        with pytest.raises(ValueError):
            vc.save_version("DTXSID_V", "bad", {"charts": "umap"})

    def test_save_preserves_charts_empty_vs_absent(self, sessions_dir):
        # [] (render none) must survive save distinct from absent (render all)
        vc.save_version("DTXSID_V", "no-charts", {"charts": []})
        assert vc.load_version("DTXSID_V", "no-charts")["charts"] == []


@pytest.mark.integration
class TestVersionRenderIntegration:
    def _seed_superset_sections_cache(self, session_dir):
        # A minimal filter-agnostic sections cache (the phase-2 superset shape):
        # both sexes, all clinical-chemistry endpoints.
        import json
        from pipeline.cache_plumbing import _hash_sections
        # The export reader picks the newest _cache_sections_*.json regardless of
        # hash, so any hash works for this unit test.
        h = _hash_sections("nt", "PFHxSAm", "mg/kg", sidecar_hash="s")
        superset = {
            "sections": [{
                "platform": "Clinical Chemistry",
                "title": "Clinical Chemistry",
                "tables_json": {
                    "Male": [
                        {"label": "n", "is_n_row": True},
                        {"label": "Cholesterol"},
                        {"label": "Albumin"},
                    ],
                    "Female": [
                        {"label": "n", "is_n_row": True},
                        {"label": "Cholesterol"},
                        {"label": "Albumin"},
                    ],
                },
            }],
        }
        (session_dir / f"_cache_sections_{h}.json").write_text(json.dumps(superset))

    def test_version_filters_project_superset_at_export(self, sessions_dir):
        from rendering.latex_export import load_session_data
        session = sessions_dir / "DTXSID_V"
        session.mkdir(parents=True, exist_ok=True)
        self._seed_superset_sections_cache(session)

        # A version keeping only MALE, no assay filter → all male CC endpoints.
        vc.save_version("DTXSID_V", "male-full",
                        {"filters": {"sex": {"apical": {"*": ["male"]}}}})
        d = load_session_data("DTXSID_V", chemical_name="PFHxSAm", version="male-full")
        cc = next(s for s in d["apical_sections"]
                  if (s.get("platform") or s.get("title")) == "Clinical Chemistry")
        td = cc.get("table_data") or cc.get("tables_json")
        assert set(td) == {"Male"}  # female dropped
        labels = [r["label"] for r in td["Male"] if not r.get("is_n_row")]
        assert labels == ["Cholesterol", "Albumin"]  # no assay filter → both kept

    def test_version_assay_filter_projects_superset(self, sessions_dir):
        from rendering.latex_export import load_session_data
        session = sessions_dir / "DTXSID_V"
        session.mkdir(parents=True, exist_ok=True)
        self._seed_superset_sections_cache(session)

        vc.save_version("DTXSID_V", "chol-only", {"filters": {
            "assays": {"clinical-chemistry": {"*": ["cholesterol"]}},
        }})
        d = load_session_data("DTXSID_V", chemical_name="PFHxSAm", version="chol-only")
        cc = next(s for s in d["apical_sections"]
                  if (s.get("platform") or s.get("title")) == "Clinical Chemistry")
        td = cc.get("table_data") or cc.get("tables_json")
        for sex in td:
            labels = [r["label"] for r in td[sex] if not r.get("is_n_row")]
            assert labels == ["Cholesterol"]  # albumin dropped, n-row kept


@pytest.mark.integration
class TestVersionGenomicsChartResolvers:
    """The genomics/chart export resolvers must honor the VERSION's overrides,
    not the global template (the bug: latex_export read ACTIVE_TEMPLATE
    unconditionally, silently dropping a version's genomics/chart filters)."""

    def test_genomics_filters_use_version_override(self, sessions_dir):
        from rendering.latex_export import _resolve_genomics_filters
        vc.save_version("DTXSID_V", "liver-male", {"filters": {
            "organs": {"genomics": {"*": ["liver"]}},
            "sex": {"genomics": {"*": ["male"]}},
            "genes": ["egr1"],
            "gene_sets": ["GO:0051301"],
        }})
        got = _resolve_genomics_filters("DTXSID_V", "liver-male")
        # tokens are lower-cased on save (predicate expects a pre-lowered
        # allowlist), so "GO:0051301" is stored/resolved as "go:0051301"
        assert got == {
            "organ": ["liver"], "sex": ["male"],
            "genes": ["egr1"], "gene_sets": ["go:0051301"],
        }

    def test_charts_use_version_override(self, sessions_dir):
        from rendering.latex_export import _resolve_charts
        # explicit empty list (render none) must be honored, not overridden by
        # the template's default (render all)
        vc.save_version("DTXSID_V", "no-charts", {"charts": []})
        assert _resolve_charts("DTXSID_V", "no-charts") == []
        vc.save_version("DTXSID_V", "umap-only", {"charts": ["umap"]})
        assert _resolve_charts("DTXSID_V", "umap-only") == ["umap"]

    def test_default_falls_back_to_template(self, sessions_dir):
        # default (no override) resolves to whatever the global template ships —
        # the key property is it does NOT raise and returns the template values.
        from rendering.latex_export import _resolve_genomics_filters, _resolve_charts
        from document_model.document_tree import ACTIVE_TEMPLATE
        from document_model.document_template import (
            load_report_organs, load_report_charts,
        )
        got = _resolve_genomics_filters("DTXSID_V", "default")
        assert got["organ"] == (load_report_organs(ACTIVE_TEMPLATE).get("genomics"))
        assert _resolve_charts("DTXSID_V", "default") == load_report_charts(ACTIVE_TEMPLATE)
