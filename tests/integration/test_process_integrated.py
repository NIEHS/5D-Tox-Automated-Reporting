"""
test_process_integrated.py — Integration tests for the processing pipeline.

POST /api/process-integrated/{dtxsid} is the most complex endpoint:
  1. Loads integrated data
  2. Filters gene expression experiments
  3. Runs NTP stats (mocked — calls Java)
  4. Partitions by platform
  5. Builds section cards + unified narratives
  6. Runs BMDS (mocked — CPU-heavy)
  7. Extracts genomics (mocked — calls Java)
  8. Builds BMD summaries
  9. Returns combined JSON

This test validates the domain model refactor by asserting section cards
are keyed by the new platform names (not old monolithic domain strings).
"""

import json

import pytest

from bmdx_pipe import TableRow


def _make_integrated_data():
    """
    Build a realistic integrated BMDProject with experiments across
    two platforms, using the new domain model fields.
    """
    return {
        "doseResponseExperiments": [
            {
                "name": "BodyWeight_Male",
                "experimentDescription": {
                    "platform": "Body Weight",
                    "data_type": "tox_study",
                },
                "probeResponses": [
                    {"probe": {"id": "SD5"}, "responses": [100, 105, 110, 120]},
                ],
            },
            {
                "name": "BodyWeight_Female",
                "experimentDescription": {
                    "platform": "Body Weight",
                    "data_type": "tox_study",
                },
                "probeResponses": [
                    {"probe": {"id": "SD5"}, "responses": [90, 95, 100, 110]},
                ],
            },
            {
                "name": "ClinChem_Male",
                "experimentDescription": {
                    "platform": "Clinical Chemistry",
                    "data_type": "tox_study",
                },
                "probeResponses": [
                    {"probe": {"id": "ALT"}, "responses": [30, 35, 40, 50]},
                    {"probe": {"id": "AST"}, "responses": [20, 22, 25, 30]},
                ],
            },
        ],
        "_meta": {
            "source_files": {
                "Body Weight": {"filename": "body_weight_truth_male.txt"},
                "Clinical Chemistry": {"filename": "clin_chem_truth_male.txt"},
            },
        },
    }


def _make_table_data():
    """
    Build mock NTP stats output matching the integrated data above.

    build_table_data() returns {sex: [TableRow, ...]} — all platforms mixed.
    _partition_by_platform then splits them by matching probe IDs to experiments.

    Important: responsive=True is required because _build_section_cards filters
    to only responsive rows for non-Body-Weight platforms.  Body Weight bypasses
    the responsive filter (NIEHS always includes Table 2).
    """
    return {
        "Male": [
            TableRow(
                label="SD5",
                values_by_dose={0.0: "100.0 ± 5.0", 1.0: "105.0 ± 4.0", 10.0: "110.0 ± 6.0", 100.0: "120.0 ± 7.0"},
                n_by_dose={0.0: 10, 1.0: 10, 10.0: 10, 100.0: 10},
                trend_marker="**",
                responsive=True,
            ),
            TableRow(
                label="ALT",
                values_by_dose={0.0: "30.0 ± 2.0", 1.0: "35.0 ± 3.0", 10.0: "40.0 ± 4.0", 100.0: "50.0 ± 5.0**"},
                n_by_dose={0.0: 10, 1.0: 10, 10.0: 10, 100.0: 10},
                trend_marker="**",
                responsive=True,
            ),
            TableRow(
                label="AST",
                values_by_dose={0.0: "20.0 ± 1.0", 1.0: "22.0 ± 1.5", 10.0: "25.0 ± 2.0", 100.0: "30.0 ± 2.5"},
                n_by_dose={0.0: 10, 1.0: 10, 10.0: 10, 100.0: 10},
                trend_marker="**",
                responsive=True,
            ),
        ],
        "Female": [
            TableRow(
                label="SD5",
                values_by_dose={0.0: "90.0 ± 4.0", 1.0: "95.0 ± 3.5", 10.0: "100.0 ± 5.0", 100.0: "110.0 ± 6.0"},
                n_by_dose={0.0: 10, 1.0: 10, 10.0: 10, 100.0: 10},
                trend_marker="*",
                responsive=True,
            ),
        ],
    }


@pytest.mark.integration
class TestProcessIntegrated:
    """POST /api/process-integrated/{dtxsid} — section card generation."""

    def _setup_session(self, sessions_dir, dtxsid="DTXSID_TEST"):
        """Write integrated.json to a session dir and return the path."""
        session = sessions_dir / dtxsid
        session.mkdir(parents=True, exist_ok=True)
        (session / "files").mkdir(exist_ok=True)

        integrated = _make_integrated_data()
        (session / "integrated.json").write_text(
            json.dumps(integrated, indent=2),
        )
        return session

    def test_returns_sections(self, sessions_dir, mock_bmdx_pipe):
        """
        Process-integrated should return a JSON with 'sections' array.
        """
        from fastapi.testclient import TestClient
        from background_server import app

        dtxsid = "DTXSID_TEST"
        self._setup_session(sessions_dir, dtxsid)
        mock_bmdx_pipe.build_table_data.return_value = _make_table_data()

        client = TestClient(app)
        resp = client.post(
            f"/api/process-integrated/{dtxsid}",
            json={"compound_name": "TestChem", "dose_unit": "mg/kg"},
        )
        assert resp.status_code == 200, f"Failed: {resp.text}"

        data = resp.json()
        assert "sections" in data
        assert isinstance(data["sections"], list)

    def test_sections_have_platform_field(self, sessions_dir, mock_bmdx_pipe):
        """
        Each section card should have a 'platform' field matching the
        new domain model values (not old monolithic strings).
        """
        from fastapi.testclient import TestClient
        from background_server import app

        dtxsid = "DTXSID_TEST"
        self._setup_session(sessions_dir, dtxsid)
        mock_bmdx_pipe.build_table_data.return_value = _make_table_data()

        client = TestClient(app)
        resp = client.post(
            f"/api/process-integrated/{dtxsid}",
            json={"compound_name": "TestChem", "dose_unit": "mg/kg"},
        )
        data = resp.json()
        sections = data["sections"]

        platforms_found = set()
        for sec in sections:
            plat = sec.get("platform")
            if plat:
                platforms_found.add(plat)

        # We expect at least Body Weight and Clinical Chemistry from our test data
        assert "Body Weight" in platforms_found, (
            f"Body Weight not in sections. Found: {platforms_found}"
        )
        assert "Clinical Chemistry" in platforms_found, (
            f"Clinical Chemistry not in sections. Found: {platforms_found}"
        )

    def test_sections_have_tables_json(self, sessions_dir, mock_bmdx_pipe):
        """Each section should have tables_json with sex keys."""
        from fastapi.testclient import TestClient
        from background_server import app

        dtxsid = "DTXSID_TEST"
        self._setup_session(sessions_dir, dtxsid)
        mock_bmdx_pipe.build_table_data.return_value = _make_table_data()

        client = TestClient(app)
        resp = client.post(
            f"/api/process-integrated/{dtxsid}",
            json={"compound_name": "TestChem", "dose_unit": "mg/kg"},
        )
        data = resp.json()

        for sec in data["sections"]:
            tables_json = sec.get("tables_json")
            assert tables_json is not None, (
                f"Section '{sec.get('platform')}' missing tables_json"
            )
            # At minimum should have Male or Female
            assert any(k in tables_json for k in ("Male", "Female")), (
                f"Section '{sec.get('platform')}' has no Male/Female key"
            )

    def test_has_bmd_summary(self, sessions_dir, mock_bmdx_pipe):
        """Response should include apical_bmd_summary."""
        from fastapi.testclient import TestClient
        from background_server import app

        dtxsid = "DTXSID_TEST"
        self._setup_session(sessions_dir, dtxsid)
        mock_bmdx_pipe.build_table_data.return_value = _make_table_data()

        client = TestClient(app)
        resp = client.post(
            f"/api/process-integrated/{dtxsid}",
            json={"compound_name": "TestChem", "dose_unit": "mg/kg"},
        )
        data = resp.json()
        assert "apical_bmd_summary" in data

    def test_has_unified_narratives(self, sessions_dir, mock_bmdx_pipe):
        """Response should include unified_narratives dict."""
        from fastapi.testclient import TestClient
        from background_server import app

        dtxsid = "DTXSID_TEST"
        self._setup_session(sessions_dir, dtxsid)
        mock_bmdx_pipe.build_table_data.return_value = _make_table_data()

        client = TestClient(app)
        resp = client.post(
            f"/api/process-integrated/{dtxsid}",
            json={"compound_name": "TestChem", "dose_unit": "mg/kg"},
        )
        data = resp.json()
        assert "unified_narratives" in data
        assert isinstance(data["unified_narratives"], dict)

    def test_no_integrated_data_returns_400(self, sessions_dir):
        """Processing without integrated data should return 400."""
        from fastapi.testclient import TestClient
        from background_server import app

        client = TestClient(app)
        dtxsid = "DTXSID_NODATA"
        (sessions_dir / dtxsid / "files").mkdir(parents=True)

        resp = client.post(
            f"/api/process-integrated/{dtxsid}",
            json={"compound_name": "Test", "dose_unit": "mg/kg"},
        )
        assert resp.status_code == 400
