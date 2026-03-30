"""
test_partition.py — Unit tests for platform partitioning and gene expression filtering.

These functions are central to the domain model refactor: they use the
experimentDescription.platform field to partition NTP stats output into
per-platform section cards.
"""

import pytest

from pool_orchestrator import _filter_gene_expression, _partition_by_platform
from bmdx_pipe import TableRow


# ---------------------------------------------------------------------------
# _filter_gene_expression — remove GE experiments from integrated data
# ---------------------------------------------------------------------------

class TestFilterGeneExpression:
    """Verify gene expression experiments are filtered before NTP stats."""

    def test_no_ge_returns_unchanged(self):
        """Without gene expression source files, input is returned as-is."""
        integrated = {
            "doseResponseExperiments": [
                {"name": "BodyWeight_Male"},
                {"name": "ClinChem_Female"},
            ],
            "_meta": {"source_files": {}},
        }
        result = _filter_gene_expression(integrated)
        assert len(result["doseResponseExperiments"]) == 2

    def test_ge_experiments_removed(self):
        """
        With gene expression source, experiments that don't match any
        clinical platform prefix are filtered out.
        """
        integrated = {
            "doseResponseExperiments": [
                {"name": "BodyWeight_Male"},
                {"name": "Liver_PFHxSAm_Male_No0"},  # GE experiment
            ],
            "_meta": {
                "source_files": {
                    "gene_expression": {"filename": "gene.bm2"},
                },
            },
        }
        result = _filter_gene_expression(integrated)
        remaining = [e["name"] for e in result["doseResponseExperiments"]]
        assert "BodyWeight_Male" in remaining
        assert "Liver_PFHxSAm_Male_No0" not in remaining

    def test_original_not_mutated(self):
        """Filtering should not mutate the original dict."""
        integrated = {
            "doseResponseExperiments": [
                {"name": "BodyWeight_Male"},
                {"name": "Liver_PFHxSAm_Male_No0"},
            ],
            "_meta": {
                "source_files": {
                    "gene_expression": {"filename": "gene.bm2"},
                },
            },
        }
        _filter_gene_expression(integrated)
        # Original should still have both experiments
        assert len(integrated["doseResponseExperiments"]) == 2

    def test_empty_experiments_list(self):
        """Empty experiments list should not crash."""
        integrated = {
            "doseResponseExperiments": [],
            "_meta": {"source_files": {"gene_expression": {"filename": "g.bm2"}}},
        }
        result = _filter_gene_expression(integrated)
        assert result["doseResponseExperiments"] == []


# ---------------------------------------------------------------------------
# _partition_by_platform — split TableRows into per-platform buckets
# ---------------------------------------------------------------------------

class TestPartitionByPlatform:
    """Verify TableRows are correctly grouped by platform using experimentDescription."""

    def _make_experiment(self, name, platform, probe_ids):
        """Helper to build a minimal experiment dict with probeResponses."""
        return {
            "name": name,
            "experimentDescription": {"platform": platform},
            "probeResponses": [
                {"probe": {"id": pid}} for pid in probe_ids
            ],
        }

    def _make_table_row(self, label):
        """Helper to build a minimal TableRow."""
        return TableRow(
            label=label,
            values_by_dose={0.0: "100", 1.0: "110"},
            n_by_dose={0.0: 10, 1.0: 10},
        )

    def test_single_platform(self):
        """All experiments in one platform → one partition."""
        integrated = {
            "doseResponseExperiments": [
                self._make_experiment("BW_Male", "Body Weight", ["SD0", "SD5"]),
            ],
        }
        table_data = {
            "Male": [self._make_table_row("SD0"), self._make_table_row("SD5")],
        }
        result = _partition_by_platform(integrated, {}, table_data)
        assert "Body Weight" in result
        assert "Male" in result["Body Weight"]
        assert len(result["Body Weight"]["Male"]) == 2

    def test_two_platforms(self):
        """Experiments from different platforms → separate partitions."""
        integrated = {
            "doseResponseExperiments": [
                self._make_experiment("BW_Male", "Body Weight", ["SD5"]),
                self._make_experiment("CC_Male", "Clinical Chemistry", ["ALT"]),
            ],
        }
        table_data = {
            "Male": [self._make_table_row("SD5"), self._make_table_row("ALT")],
        }
        result = _partition_by_platform(integrated, {}, table_data)
        assert "Body Weight" in result
        assert "Clinical Chemistry" in result

    def test_uses_platform_field_not_domain(self):
        """
        The new domain model uses experimentDescription.platform.
        If both platform and domain are present, platform takes precedence.
        """
        integrated = {
            "doseResponseExperiments": [{
                "name": "BW_Male",
                "experimentDescription": {
                    "platform": "Body Weight",
                    "domain": "body_weight_tox_study",  # old format
                },
                "probeResponses": [{"probe": {"id": "SD5"}}],
            }],
        }
        table_data = {
            "Male": [self._make_table_row("SD5")],
        }
        result = _partition_by_platform(integrated, {}, table_data)
        # Should use "Body Weight" from platform, not "body_weight_tox_study"
        assert "Body Weight" in result

    def test_empty_table_data(self):
        """Empty table_data should produce empty partitions."""
        integrated = {
            "doseResponseExperiments": [
                self._make_experiment("BW_Male", "Body Weight", ["SD5"]),
            ],
        }
        result = _partition_by_platform(integrated, {}, {"Male": [], "Female": []})
        # May produce empty dicts or omit the platform entirely — either is fine
        for platform_data in result.values():
            for sex_rows in platform_data.values():
                assert len(sex_rows) == 0
