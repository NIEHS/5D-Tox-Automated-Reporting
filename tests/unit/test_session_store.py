"""
test_session_store.py — Unit tests for session persistence functions.

Tests pure functions and disk I/O in session_store.py:
  - bm2_slug: .bm2 filename → URL-safe slug
  - safe_filename: chemical name → filesystem-safe string
  - save_section + load round-trip: JSON persistence with version history
  - delete_section: file removal
"""

import json

import pytest

from session_store import bm2_slug, safe_filename, save_section, delete_section


# ---------------------------------------------------------------------------
# bm2_slug — .bm2 filename to URL-safe slug
# ---------------------------------------------------------------------------

class TestBm2Slug:
    """Verify bm2_slug strips prefix, lowercases, and hyphenates."""

    def test_organ_weights(self):
        assert bm2_slug("P3MP-Organ and Body Weights.bm2") == "organ-and-body-weights"

    def test_clinical_pathology(self):
        assert bm2_slug("P3MP-Clinical Pathology.bm2") == "clinical-pathology"

    def test_simple_name(self):
        assert bm2_slug("XYZ-Hematology.bm2") == "hematology"

    def test_no_prefix_hyphen(self):
        # If there's no hyphen, the whole stem (minus .bm2) is slugified
        assert bm2_slug("Hematology.bm2") == "hematology"

    def test_special_characters_become_hyphens(self):
        assert bm2_slug("FOO-Gene Expression (Liver).bm2") == "gene-expression-liver"


# ---------------------------------------------------------------------------
# safe_filename — chemical name → filesystem-safe string
# ---------------------------------------------------------------------------

class TestSafeFilename:
    """Verify safe_filename sanitizes chemical names for file paths."""

    def test_comma_replaced(self):
        assert safe_filename("1,2-Dichlorobenzene") == "1_2-Dichlorobenzene"

    def test_alphanumeric_preserved(self):
        assert safe_filename("TestCompound123") == "TestCompound123"

    def test_spaces_preserved(self):
        # Spaces are explicitly allowed in the implementation
        assert safe_filename("Test Compound") == "Test Compound"

    def test_hyphens_preserved(self):
        assert safe_filename("2-Chloro-4-nitro") == "2-Chloro-4-nitro"

    def test_parentheses_replaced(self):
        assert safe_filename("Benzo(a)pyrene") == "Benzo_a_pyrene"


# ---------------------------------------------------------------------------
# save_section + load round-trip
# ---------------------------------------------------------------------------

class TestSaveSectionRoundTrip:
    """Verify save_section writes JSON, archives history, and increments version."""

    def test_first_save_creates_file(self, sessions_dir):
        """First save creates the section file with version 1."""
        dtxsid = "DTXSID_TEST"
        save_section(dtxsid, "background", {"paragraphs": ["Hello"]})

        path = sessions_dir / dtxsid / "background.json"
        assert path.exists()

        data = json.loads(path.read_text())
        assert data["version"] == 1
        assert data["paragraphs"] == ["Hello"]

    def test_second_save_archives_first(self, sessions_dir):
        """Second save moves the first version to history/."""
        dtxsid = "DTXSID_TEST"
        save_section(dtxsid, "background", {
            "paragraphs": ["v1"],
            "approved_at": "2026-01-01T00:00:00+00:00",
        })
        save_section(dtxsid, "background", {
            "paragraphs": ["v2"],
            "approved_at": "2026-01-02T00:00:00+00:00",
        })

        # Current file should be v2
        current = json.loads(
            (sessions_dir / dtxsid / "background.json").read_text()
        )
        assert current["version"] == 2
        assert current["paragraphs"] == ["v2"]

        # History should contain v1
        history_dir = sessions_dir / dtxsid / "history" / "background"
        assert history_dir.exists()
        history_files = list(history_dir.glob("*.json"))
        assert len(history_files) == 1

        archived = json.loads(history_files[0].read_text())
        assert archived["paragraphs"] == ["v1"]

    def test_meta_json_updated(self, sessions_dir):
        """save_section creates/updates meta.json with timestamps."""
        dtxsid = "DTXSID_TEST"
        save_section(dtxsid, "background", {"text": "test"})

        meta = json.loads(
            (sessions_dir / dtxsid / "meta.json").read_text()
        )
        assert "created_at" in meta
        assert "updated_at" in meta
        assert meta["dtxsid"] == dtxsid

    def test_three_saves_produce_two_history_entries(self, sessions_dir):
        """Three saves: current is v3, history has v1 and v2."""
        dtxsid = "DTXSID_TEST"
        for i in range(1, 4):
            save_section(dtxsid, "methods", {
                "text": f"v{i}",
                "approved_at": f"2026-01-0{i}T00:00:00+00:00",
            })

        current = json.loads(
            (sessions_dir / dtxsid / "methods.json").read_text()
        )
        assert current["version"] == 3

        history_files = list(
            (sessions_dir / dtxsid / "history" / "methods").glob("*.json")
        )
        assert len(history_files) == 2


# ---------------------------------------------------------------------------
# delete_section
# ---------------------------------------------------------------------------

class TestDeleteSection:
    """Verify delete_section removes the section file."""

    def test_delete_existing_section(self, sessions_dir):
        dtxsid = "DTXSID_TEST"
        save_section(dtxsid, "background", {"text": "to delete"})
        path = sessions_dir / dtxsid / "background.json"
        assert path.exists()

        delete_section(dtxsid, "background")
        assert not path.exists()

    def test_delete_nonexistent_is_noop(self, sessions_dir):
        """Deleting a section that doesn't exist should not raise."""
        # Create the session dir so the path is valid
        (sessions_dir / "DTXSID_TEST").mkdir(parents=True)
        delete_section("DTXSID_TEST", "nonexistent")  # Should not raise

    def test_delete_preserves_history(self, sessions_dir):
        """Deleting the current version should NOT delete history."""
        dtxsid = "DTXSID_TEST"
        save_section(dtxsid, "bg", {
            "text": "v1",
            "approved_at": "2026-01-01T00:00:00+00:00",
        })
        save_section(dtxsid, "bg", {
            "text": "v2",
            "approved_at": "2026-01-02T00:00:00+00:00",
        })

        delete_section(dtxsid, "bg")

        # Current file gone, but history preserved
        assert not (sessions_dir / dtxsid / "bg.json").exists()
        history_files = list(
            (sessions_dir / dtxsid / "history" / "bg").glob("*.json")
        )
        assert len(history_files) == 1
