"""
test_pure_functions.py — Unit tests for pool_orchestrator helper functions.

Tests pure functions that have no I/O or external dependencies:
  - _js_dose_key: float-to-string conversion matching JavaScript String(number)
  - _safe_float / _safe_float_from_bmdl: coerce values to float for sorting
  - serialize_table_rows: TableRow → JSON-friendly dicts
  - serialize_incidence_rows: IncidenceRow → JSON-friendly dicts
  - Hash functions: deterministic cache keys for NTP/sections/BMDS/genomics
"""

from dataclasses import dataclass, field
from math import inf

import pytest

# Import the functions under test directly from pool_orchestrator.
# These are module-private (prefixed _) but Python allows direct access.
from pool_orchestrator import (
    _js_dose_key,
    _safe_float,
    _safe_float_from_bmdl,
    serialize_table_rows,
    serialize_incidence_rows,
    _hash_ntp,
    _hash_sections,
    _hash_bmds,
    _hash_genomics,
)
from bmdx_pipe import TableRow, IncidenceRow


# ---------------------------------------------------------------------------
# _js_dose_key — replicates JavaScript's String(number) behavior
# ---------------------------------------------------------------------------

class TestJsDoseKey:
    """Verify _js_dose_key matches JavaScript String(number) output."""

    def test_integer_dose_drops_decimal(self):
        # JavaScript: String(1.0) → "1"
        assert _js_dose_key(1.0) == "1"

    def test_zero_drops_decimal(self):
        # JavaScript: String(0.0) → "0"
        assert _js_dose_key(0.0) == "0"

    def test_large_integer_dose(self):
        # JavaScript: String(1000.0) → "1000"
        assert _js_dose_key(1000.0) == "1000"

    def test_fractional_dose_preserved(self):
        # JavaScript: String(0.3) → "0.3"
        assert _js_dose_key(0.3) == "0.3"

    def test_small_fractional_dose(self):
        # JavaScript: String(0.01) → "0.01"
        assert _js_dose_key(0.01) == "0.01"

    def test_ten_is_integer(self):
        assert _js_dose_key(10.0) == "10"

    def test_non_round_float(self):
        assert _js_dose_key(3.5) == "3.5"


# ---------------------------------------------------------------------------
# _safe_float — coerce values to float for sorting
# ---------------------------------------------------------------------------

class TestSafeFloat:
    """Verify _safe_float handles NaN, None, and Java string serialization."""

    def test_none_returns_infinity(self):
        assert _safe_float(None) == inf

    def test_nan_string_returns_infinity(self):
        # Java serializes NaN as the string "NaN"
        assert _safe_float("NaN") == inf

    def test_numeric_string(self):
        assert _safe_float("12.3") == 12.3

    def test_numeric_value(self):
        assert _safe_float(0.5) == 0.5

    def test_zero(self):
        assert _safe_float(0.0) == 0.0

    def test_unparseable_string(self):
        assert _safe_float("NVM") == inf

    def test_float_nan_returns_infinity(self):
        assert _safe_float(float("nan")) == inf

    def test_custom_default(self):
        assert _safe_float(None, default=-1.0) == -1.0


# ---------------------------------------------------------------------------
# _safe_float_from_bmdl — extract numeric sort key from BMDL strings
# ---------------------------------------------------------------------------

class TestSafeFloatFromBmdl:
    """Verify BMDL string parsing for sort keys."""

    def test_numeric_bmdl(self):
        assert _safe_float_from_bmdl("12.3") == 12.3

    def test_nr_threshold_strips_less_than(self):
        # NR endpoints have BMDL formatted as "<0.1"
        assert _safe_float_from_bmdl("<0.1") == 0.1

    def test_nvm_returns_infinity(self):
        assert _safe_float_from_bmdl("NVM") == inf

    def test_urep_returns_infinity(self):
        assert _safe_float_from_bmdl("UREP") == inf

    def test_dash_returns_infinity(self):
        assert _safe_float_from_bmdl("—") == inf

    def test_nd_returns_infinity(self):
        assert _safe_float_from_bmdl("ND") == inf

    def test_empty_string_returns_infinity(self):
        assert _safe_float_from_bmdl("") == inf


# ---------------------------------------------------------------------------
# serialize_table_rows — TableRow objects → JSON
# ---------------------------------------------------------------------------

class TestSerializeTableRows:
    """Verify TableRow serialization produces correct JSON structure."""

    @pytest.fixture
    def sample_table_data(self):
        """Minimal table data: one male endpoint at two doses."""
        return {
            "Male": [
                TableRow(
                    label="Body Weight",
                    values_by_dose={0.0: "100.0 ± 5.0", 1.0: "110.0 ± 6.0**"},
                    n_by_dose={0.0: 10, 1.0: 10},
                    trend_marker="**",
                ),
            ],
        }

    def test_basic_structure(self, sample_table_data):
        result = serialize_table_rows(sample_table_data)
        assert "Male" in result
        assert len(result["Male"]) == 1

    def test_dose_keys_are_js_format(self, sample_table_data):
        result = serialize_table_rows(sample_table_data)
        row = result["Male"][0]
        # 0.0 → "0", 1.0 → "1" (not "0.0", "1.0")
        assert "0" in row["values"]
        assert "1" in row["values"]
        assert "0" in row["n"]
        assert "1" in row["n"]

    def test_expected_fields_present(self, sample_table_data):
        result = serialize_table_rows(sample_table_data)
        row = result["Male"][0]
        assert row["label"] == "Body Weight"
        assert row["trend_marker"] == "**"
        assert "doses" in row
        assert "values" in row
        assert "n" in row

    def test_doses_sorted(self, sample_table_data):
        result = serialize_table_rows(sample_table_data)
        row = result["Male"][0]
        assert row["doses"] == [0.0, 1.0]

    def test_missing_animals_included_when_present(self):
        """When missing_animals_by_dose is populated, it appears in output."""
        data = {
            "Female": [
                TableRow(
                    label="Liver",
                    values_by_dose={0.0: "5.0 ± 0.1", 10.0: "6.0 ± 0.2"},
                    n_by_dose={0.0: 8, 10.0: 7},
                    missing_animals_by_dose={10.0: 1},
                ),
            ],
        }
        result = serialize_table_rows(data)
        row = result["Female"][0]
        assert "missing_animals" in row
        assert row["missing_animals"]["10"] == 1

    def test_missing_animals_omitted_when_empty(self, sample_table_data):
        """No missing_animals key when the dict is empty/falsy."""
        result = serialize_table_rows(sample_table_data)
        row = result["Male"][0]
        assert "missing_animals" not in row


# ---------------------------------------------------------------------------
# serialize_incidence_rows — IncidenceRow objects → JSON
# ---------------------------------------------------------------------------

class TestSerializeIncidenceRows:
    """Verify IncidenceRow serialization produces correct JSON structure."""

    @pytest.fixture
    def sample_incidence_data(self):
        """Minimal incidence data: one finding at two doses."""
        return {
            "Male": [
                IncidenceRow(
                    label="Discharge — Eye",
                    incidence_by_dose={0.0: "0/10", 1.0: "3/10"},
                    total_n_by_dose={0.0: 10, 1.0: 10},
                ),
            ],
        }

    def test_basic_structure(self, sample_incidence_data):
        result = serialize_incidence_rows(sample_incidence_data)
        assert "Male" in result
        assert len(result["Male"]) == 1

    def test_values_are_n_over_n_strings(self, sample_incidence_data):
        result = serialize_incidence_rows(sample_incidence_data)
        row = result["Male"][0]
        assert row["values"]["0"] == "0/10"
        assert row["values"]["1"] == "3/10"

    def test_dose_keys_are_js_format(self, sample_incidence_data):
        result = serialize_incidence_rows(sample_incidence_data)
        row = result["Male"][0]
        # 0.0 → "0", 1.0 → "1"
        assert "0" in row["values"]
        assert "1" in row["values"]

    def test_total_n_per_dose(self, sample_incidence_data):
        result = serialize_incidence_rows(sample_incidence_data)
        row = result["Male"][0]
        assert row["n"]["0"] == 10
        assert row["n"]["1"] == 10


# ---------------------------------------------------------------------------
# Hash functions — determinism and sensitivity
# ---------------------------------------------------------------------------

class TestHashFunctions:
    """Verify hash functions are deterministic and sensitive to inputs."""

    def test_hash_ntp_deterministic(self):
        """Same inputs must produce the same hash."""
        integrated = {"doseResponseExperiments": [{"name": "exp_A"}]}
        h1 = _hash_ntp(integrated, "median")
        h2 = _hash_ntp(integrated, "median")
        assert h1 == h2

    def test_hash_ntp_sensitive_to_bmd_stat(self):
        """Different bmd_stat values produce different hashes."""
        integrated = {"doseResponseExperiments": [{"name": "exp_A"}]}
        h1 = _hash_ntp(integrated, "median")
        h2 = _hash_ntp(integrated, "mean")
        assert h1 != h2

    def test_hash_ntp_sensitive_to_experiments(self):
        """Adding an experiment changes the hash."""
        h1 = _hash_ntp(
            {"doseResponseExperiments": [{"name": "exp_A"}]}, "median"
        )
        h2 = _hash_ntp(
            {"doseResponseExperiments": [{"name": "exp_A"}, {"name": "exp_B"}]},
            "median",
        )
        assert h1 != h2

    def test_hash_ntp_is_16_chars(self):
        h = _hash_ntp({"doseResponseExperiments": []}, "median")
        assert len(h) == 16

    def test_hash_sections_deterministic(self):
        h1 = _hash_sections("abc123", "TestChem", "mg/kg")
        h2 = _hash_sections("abc123", "TestChem", "mg/kg")
        assert h1 == h2

    def test_hash_sections_sensitive_to_compound(self):
        h1 = _hash_sections("abc123", "ChemA", "mg/kg")
        h2 = _hash_sections("abc123", "ChemB", "mg/kg")
        assert h1 != h2

    def test_hash_bmds_order_independent(self):
        """Shuffled endpoint order should produce the same hash."""
        inputs_a = [
            {"key": "bw_male", "doses": [0, 1], "ns": [10, 10], "means": [100, 110], "stdevs": [5, 6]},
            {"key": "ow_male", "doses": [0, 1], "ns": [10, 10], "means": [5, 6], "stdevs": [0.5, 0.6]},
        ]
        inputs_b = list(reversed(inputs_a))
        assert _hash_bmds(inputs_a) == _hash_bmds(inputs_b)

    def test_hash_bmds_sensitive_to_data(self):
        """Different data values produce different hashes."""
        inputs_a = [{"key": "bw", "doses": [0, 1], "ns": [10, 10], "means": [100, 110], "stdevs": [5, 6]}]
        inputs_b = [{"key": "bw", "doses": [0, 1], "ns": [10, 10], "means": [100, 120], "stdevs": [5, 6]}]
        assert _hash_bmds(inputs_a) != _hash_bmds(inputs_b)

    def test_hash_genomics_deterministic(self):
        h1 = _hash_genomics(["median"], 5.0, 20, 500, 3, "gene.bm2")
        h2 = _hash_genomics(["median"], 5.0, 20, 500, 3, "gene.bm2")
        assert h1 == h2

    def test_hash_genomics_sensitive_to_file(self):
        h1 = _hash_genomics(["median"], 5.0, 20, 500, 3, "gene_a.bm2")
        h2 = _hash_genomics(["median"], 5.0, 20, 500, 3, "gene_b.bm2")
        assert h1 != h2
