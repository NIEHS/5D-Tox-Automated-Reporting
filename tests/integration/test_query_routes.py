"""
Integration tests for the read-only SQL query API (ADR-0016 Phase B).

Pins the query boundary the power-user tools sit on:
  * a SELECT/WITH returns {columns, rows, row_count, truncated};
  * non-SELECT / multi-statement / write bodies are rejected (400);
  * max_rows caps the result and sets truncated;
  * the schema endpoint lists the tables;
  * a missing session DB is a clean 400, not a 500.

Each test builds a tiny session.duckdb via pipeline.session_db into the patched
sessions dir (the writer + a synthetic session), so this exercises the real
files on disk end to end.
"""

import json
import os

import pytest


def _build_session_db(sessions_dir, dtxsid="DTXSID_Q"):
    """Write a minimal session.duckdb under the patched sessions dir."""
    from pipeline.session_db import build_session_db

    session = sessions_dir / dtxsid
    (session / "files").mkdir(parents=True)

    sidecar = {
        "source": "bw_male.csv", "platform": "Body Weight", "sex": "Male",
        "animals": {
            "101": {"dose": 0.0, "selection": "Core Animals", "observations": [
                {"day": "SD0", "endpoint": "Body Weight", "value": "285.1", "terminal": False},
            ]},
            "102": {"dose": 100.0, "selection": "Core Animals", "observations": [
                {"day": "SD0", "endpoint": "Body Weight", "value": "290.0", "terminal": False},
            ]},
        },
    }
    (session / "files" / "bw_male.sidecar.json").write_text(json.dumps(sidecar))
    (session / "_cache_bmd_summary_x.json").write_text(json.dumps({
        "apical": [
            {"endpoint": "Total Thyroxine", "sex": "Male", "platform": "Hormones",
             "bmd": "8.54", "bmdl": "3.59", "bmd_status": "viable",
             "loel": 37.0, "noel": 12.0, "direction": "DOWN"},
        ],
        "bmds": [],
    }))
    integrated = {
        "name": "PFHxSAm",
        "doseResponseExperiments": [{"@ref": "1", "name": "e1", "experimentDescription": {
            "testArticle": {"name": "PFHxSAm", "casrn": "", "dsstox": dtxsid},
            "studyDuration": "5d", "species": "rat", "strain": "Sprague-Dawley",
            "articleRoute": "gavage", "articleVehicle": "corn oil",
            "platform": "Body Weight", "provider": "Apical", "sex": "male",
            "organ": "Whole Body", "dataType": "tox_study"}}],
        "_meta": {"dtxsid": dtxsid, "integrated_at": "2026-08-24T00:00:00+00:00",
                  "source_files": {}},
    }

    shm = "/dev/shm"
    if os.path.isdir(shm):
        os.environ["BMDX_SESSION_DB_TMPDIR"] = shm
    build_session_db(dtxsid, session, integrated)
    return dtxsid


@pytest.mark.integration
class TestQueryRoutes:
    def _client(self):
        from fastapi.testclient import TestClient
        from web_routes.background_server import app
        return TestClient(app)

    def test_select_returns_rows(self, sessions_dir):
        dtxsid = _build_session_db(sessions_dir)
        client = self._client()
        resp = client.post(f"/api/query/{dtxsid}",
                            json={"sql": "SELECT endpoint, bmd_num FROM apical_result"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["columns"] == ["endpoint", "bmd_num"]
        assert body["row_count"] == 1
        assert body["rows"][0] == ["Total Thyroxine", 8.54]
        assert body["truncated"] is False

    def test_with_cte_allowed(self, sessions_dir):
        dtxsid = _build_session_db(sessions_dir)
        client = self._client()
        resp = client.post(f"/api/query/{dtxsid}", json={
            "sql": "WITH m AS (SELECT * FROM measurement) SELECT count(*) c FROM m"
        })
        assert resp.status_code == 200, resp.text
        assert resp.json()["rows"][0][0] == 2

    @pytest.mark.parametrize("bad_sql", [
        "DROP TABLE study",
        "DELETE FROM gene",
        "INSERT INTO gene VALUES (1)",
        "UPDATE study SET name = 'x'",
        "SELECT 1; DROP TABLE study",
        "",
    ])
    def test_non_select_rejected(self, sessions_dir, bad_sql):
        dtxsid = _build_session_db(sessions_dir)
        client = self._client()
        resp = client.post(f"/api/query/{dtxsid}", json={"sql": bad_sql})
        assert resp.status_code == 400, resp.text
        assert "error" in resp.json()

    def test_missing_sql_field_is_400(self, sessions_dir):
        dtxsid = _build_session_db(sessions_dir)
        client = self._client()
        resp = client.post(f"/api/query/{dtxsid}", json={})
        assert resp.status_code == 400
        assert "sql" in resp.json()["error"]

    def test_max_rows_caps_and_flags_truncated(self, sessions_dir):
        dtxsid = _build_session_db(sessions_dir)
        client = self._client()
        # 2 measurement rows exist; cap at 1 → truncated
        resp = client.post(f"/api/query/{dtxsid}",
                           json={"sql": "SELECT * FROM measurement", "max_rows": 1})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["row_count"] == 1
        assert body["truncated"] is True

    def test_schema_lists_tables(self, sessions_dir):
        dtxsid = _build_session_db(sessions_dir)
        client = self._client()
        resp = client.get(f"/api/query/{dtxsid}/schema")
        assert resp.status_code == 200, resp.text
        tables = {t["name"] for t in resp.json()["tables"]}
        assert {"measurement", "apical_result", "gene_set", "study"} <= tables
        # each table carries typed columns
        meas = next(t for t in resp.json()["tables"] if t["name"] == "measurement")
        colnames = {c["name"] for c in meas["columns"]}
        assert {"subject_id", "endpoint", "day", "value_raw", "value_num"} <= colnames

    def test_missing_db_is_clean_400(self, sessions_dir):
        client = self._client()
        resp = client.post("/api/query/DTXSID_NOPE", json={"sql": "SELECT 1"})
        assert resp.status_code == 400
        assert "no query database" in resp.json()["error"]

    def test_query_engine_error_is_400(self, sessions_dir):
        # a valid SELECT against a non-existent column is a user error → 400
        dtxsid = _build_session_db(sessions_dir)
        client = self._client()
        resp = client.post(f"/api/query/{dtxsid}",
                           json={"sql": "SELECT no_such_col FROM study"})
        assert resp.status_code == 400
        assert "error" in resp.json()

    def test_parquet_list(self, sessions_dir):
        dtxsid = _build_session_db(sessions_dir)
        client = self._client()
        resp = client.get(f"/api/query/{dtxsid}/parquet")
        assert resp.status_code == 200, resp.text
        tables = set(resp.json()["tables"])
        assert {"measurement", "apical_result", "study"} <= tables

    def test_parquet_streams_valid_file(self, sessions_dir):
        import duckdb
        dtxsid = _build_session_db(sessions_dir)
        client = self._client()
        resp = client.get(f"/api/query/{dtxsid}/parquet/measurement")
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"] == "application/octet-stream"
        # the bytes are a real Parquet file duckdb can read
        body = resp.content
        assert body[:4] == b"PAR1"  # Parquet magic
        # round-trip through duckdb from a temp file
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
            f.write(body)
            fp = f.name
        try:
            n = duckdb.connect(":memory:").execute(
                f"SELECT count(*) FROM read_parquet('{fp}')"
            ).fetchone()[0]
            assert n == 2
        finally:
            os.unlink(fp)

    def test_parquet_unknown_table_404(self, sessions_dir):
        dtxsid = _build_session_db(sessions_dir)
        client = self._client()
        # an unknown / traversal-y name is rejected by the allowlist
        for bad in ["bogus", "../secret", "study;drop"]:
            resp = client.get(f"/api/query/{dtxsid}/parquet/{bad}")
            assert resp.status_code == 404, f"{bad}: {resp.status_code}"

    def test_parquet_missing_session_404(self, sessions_dir):
        client = self._client()
        resp = client.get("/api/query/DTXSID_NOPE/parquet/measurement")
        assert resp.status_code == 404
