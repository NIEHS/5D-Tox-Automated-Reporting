"""
test_upload_routes.py — Integration tests for file upload endpoints.

Tests:
  - POST /api/upload-bm2 with a test file
  - POST /api/upload-csv with a test file
  - GET /api/preview/{file_id} returns file content
"""

import io

import pytest


@pytest.mark.integration
class TestUploadBm2:
    """POST /api/upload-bm2 — upload .bm2 files."""

    def test_upload_registers_file(self, sessions_dir, mock_bmdx_pipe):
        """Uploading a .bm2 file registers it in the uploads dict."""
        from fastapi.testclient import TestClient
        from background_server import app

        client = TestClient(app)

        # Create a minimal fake .bm2 file (just bytes — the real parsing
        # is mocked via mock_bmdx_pipe)
        fake_bm2 = io.BytesIO(b"\x00" * 100)

        resp = client.post(
            "/api/upload-bm2",
            files=[("files", ("test-file.bm2", fake_bm2, "application/octet-stream"))],
        )
        assert resp.status_code == 200

        data = resp.json()
        assert "files" in data
        assert len(data["files"]) == 1
        assert data["files"][0]["filename"] == "test-file.bm2"
        assert "id" in data["files"][0]


@pytest.mark.integration
class TestUploadCsv:
    """POST /api/upload-csv — upload CSV/TXT data files."""

    def test_upload_csv_registers_file(self, sessions_dir, mock_bmdx_pipe):
        """Uploading a .csv file registers it in the data uploads dict."""
        from fastapi.testclient import TestClient
        from background_server import app

        client = TestClient(app)

        # Minimal CSV content
        csv_content = b"Animal ID,Dose,Value\n1,0,100\n2,1,110\n"
        fake_csv = io.BytesIO(csv_content)

        resp = client.post(
            "/api/upload-csv",
            files=[("files", ("test-data.csv", fake_csv, "text/csv"))],
        )
        assert resp.status_code == 200

        data = resp.json()
        assert "files" in data
        assert len(data["files"]) == 1
        assert data["files"][0]["filename"] == "test-data.csv"

    def test_upload_txt_registers_file(self, sessions_dir, mock_bmdx_pipe):
        """Uploading a .txt file works the same as .csv."""
        from fastapi.testclient import TestClient
        from background_server import app

        client = TestClient(app)

        txt_content = b"Dose\t0\t1\nSD5\t100\t110\n"
        fake_txt = io.BytesIO(txt_content)

        resp = client.post(
            "/api/upload-csv",
            files=[("files", ("test-data.txt", fake_txt, "text/plain"))],
        )
        assert resp.status_code == 200
        assert resp.json()["files"][0]["filename"] == "test-data.txt"


@pytest.mark.integration
class TestPreview:
    """GET /api/preview/{file_id} — preview uploaded file content."""

    def test_preview_returns_content_for_data_upload(self, golden_50469320, mock_bmdx_pipe):
        """
        After session load re-registers files, preview should return content.
        """
        from fastapi.testclient import TestClient
        from background_server import app

        client = TestClient(app)

        # Load the session — this re-registers files in _data_uploads
        resp = client.get("/api/session/DTXSID50469320")
        data = resp.json()
        pending = data.get("pending_files", [])

        if not pending:
            pytest.skip("No pending files found in golden session")

        # Preview the first pending file
        file_id = pending[0]["id"]
        resp = client.get(f"/api/preview/{file_id}")
        assert resp.status_code == 200
