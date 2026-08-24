"""
Unit tests for the session DuckDB writer (ADR-0016 Phase A, build_session_db).

Builds a DB from a tiny SYNTHETIC session (a temp dir with one sidecar + a
bmd_summary cache + a genomics cache) and asserts the writer flattens the real
artifact shapes into the schema correctly: the measurement (subject × endpoint ×
day) grain with the raw/parsed value split, the string+parsed BMD on
apical_result, and the semicolon gene explosion into gene_set_gene.

The writer builds via a temp dir and copies the finished file into place; we
point that temp at a lock-safe location so the test runs unattended in the
sandbox (DuckDB's create-time file lock hangs on some mounts — see build_session_db).
"""

import json
import os
from pathlib import Path

import duckdb
import pytest

from pipeline.session_db import build_session_db
from pipeline.session_schema import SCHEMA_VERSION


@pytest.fixture(autouse=True)
def _lock_safe_tmpdir(monkeypatch, tmp_path):
    # Prefer tmpfs when present (sandbox), else a normal temp — both avoid the
    # session dir itself. On CI/host the default temp is fine; /dev/shm is the
    # sandbox's lock-safe mount.
    shm = "/dev/shm"
    monkeypatch.setenv(
        "BMDX_SESSION_DB_TMPDIR", shm if os.path.isdir(shm) else str(tmp_path)
    )


def _write_synthetic_session(root: Path) -> dict:
    """A minimal session dir + the integrated dict, exercising every table."""
    (root / "files").mkdir(parents=True)

    # one sidecar: 2 animals × 2 days of Body Weight, incl. a non-numeric value
    sidecar = {
        "source": "body_weight_male.csv",
        "platform": "Body Weight",
        "sex": "Male",
        "animals": {
            "101": {"dose": 0.0, "selection": "Core Animals", "observations": [
                {"day": "SD0", "endpoint": "Body Weight", "value": "285.1", "terminal": False},
                {"day": "SD5", "endpoint": "Body Weight", "value": "NA", "terminal": True},
            ]},
            "102": {"dose": 100.0, "selection": "Core Animals", "observations": [
                {"day": "SD0", "endpoint": "Body Weight", "value": "290.0", "terminal": False},
            ]},
        },
    }
    (root / "files" / "body_weight_male.sidecar.json").write_text(json.dumps(sidecar))

    bmd_summary = {
        "apical": [
            {"endpoint": "Total Thyroxine", "sex": "Male", "platform": "Hormones",
             "bmd": "8.54", "bmdl": "3.59", "bmd_status": "viable",
             "loel": 37.0, "noel": 12.0, "direction": "DOWN"},
            {"endpoint": "Cholesterol", "sex": "Male", "platform": "Clinical Chemistry",
             "bmd": "—", "bmdl": "—", "bmd_status": "NR",
             "loel": None, "noel": None, "direction": ""},
        ],
        "bmds": [
            {"endpoint": "Total Thyroxine", "sex": "Male", "platform": "Hormones",
             "bmd": "8.54", "bmdl": "3.59", "bmd_status": "viable",
             "model_name": "Hill", "loel": 37.0, "noel": 12.0, "direction": "DOWN"},
        ],
    }
    (root / "_cache_bmd_summary_deadbeef.json").write_text(json.dumps(bmd_summary))

    genomics = {
        "liver_male": {
            "organ": "liver", "sex": "male",
            "total_probes": 100, "total_responsive_genes": 10,
            "gene_sets_by_stat": {"median": []},
            "gene_sets_chart_by_stat": {"median": [
                {"go_id": "GO:0051301", "go_term": "cell division",
                 "bmd": 5.0, "bmdl": 3.0, "bmdu": 7.0, "n_genes": 3,
                 "n_genes_with_bmd": 2, "direction": "up", "n_up": 2, "n_down": 1,
                 "fishers_p": 0.01, "genes": "egr1;ddit4;myc"},
            ]},
            "top_genes": [
                {"rank": 1, "gene_symbol": "egr1", "probe_id": "p1",
                 "bmd": 4.2, "bmdl": 2.1, "bmdu": 6.0, "direction": "up",
                 "fold_change": 2.5, "r_squared": 0.9},
            ],
            "all_genes": [
                {"gene_symbol": "egr1", "bmd": 4.2, "bmdl": 2.1, "direction": "up",
                 "fold_change": 2.5},
            ],
            "adversity_signatures": [
                {"title": "Sig A", "signature_id": "SIGA", "active": True,
                 "n_passed": 5, "n_genes": 8, "percentage": 62.5,
                 "bmd": 5.0, "bmdl": 3.0, "bmdu": 7.0, "direction": "up",
                 "fishers_p": 0.02,
                 "bmd_stats": {"mean": 5.0, "median": 4.8, "minimum": 3.0,
                               "weighted_mean": 5.0, "sd": 1.0, "weighted_sd": 1.0,
                               "fifth_pct": 3.2, "tenth_pct": 3.5,
                               "lower95": None, "upper95": None},
                 "bmdl_stats": {"mean": 3.0}, "bmdu_stats": {"mean": 7.0}},
            ],
        }
    }
    (root / "_cache_genomics_cafe1234.json").write_text(json.dumps(genomics))

    integrated = {
        "name": "PFHxSAm",
        "doseResponseExperiments": [
            {"@ref": "1", "name": "exp1", "experimentDescription": {
                "testArticle": {"name": "PFHxSAm", "casrn": "1234-56-7", "dsstox": "DTXSID_T"},
                "studyDuration": "5d", "species": "rat", "strain": "Sprague-Dawley",
                "articleRoute": "gavage", "articleVehicle": "corn oil",
                "platform": "Body Weight", "provider": "Apical", "sex": "male",
                "organ": "Whole Body", "dataType": "tox_study"}},
        ],
        "_meta": {
            "dtxsid": "DTXSID_T",
            "integrated_at": "2026-08-23T00:00:00+00:00",
            "source_files": {
                "Body Weight|inferred": {"file_id": "scan-bw", "filename": "bw.bm2",
                                         "tier": "bm2", "file_count": 1,
                                         "experiment_count": 4},
            },
        },
    }
    return integrated


def _build(tmp_path: Path):
    session = tmp_path / "DTXSID_T"
    integrated = _write_synthetic_session(session)
    db = build_session_db("DTXSID_T", session, integrated)
    return db


def test_build_produces_db_file(tmp_path):
    db = _build(tmp_path)
    assert db.exists() and db.stat().st_size > 0
    # no stray WAL beside it (checkpointed + copied as a single file)
    assert not (db.parent / "session.duckdb.wal").exists()


def test_schema_version_recorded(tmp_path):
    db = _build(tmp_path)
    con = duckdb.connect(str(db), read_only=True)
    assert con.execute("SELECT version FROM schema_version").fetchone()[0] == SCHEMA_VERSION
    con.close()


def test_study_identity_mapped_from_experiment_description(tmp_path):
    db = _build(tmp_path)
    con = duckdb.connect(str(db), read_only=True)
    row = con.execute(
        "SELECT name, casrn, species, strain, duration, route, vehicle FROM study"
    ).fetchone()
    con.close()
    assert row == ("PFHxSAm", "1234-56-7", "rat", "Sprague-Dawley", "5d", "gavage", "corn oil")


def test_measurement_grain_and_value_split(tmp_path):
    db = _build(tmp_path)
    con = duckdb.connect(str(db), read_only=True)
    # 2+1 observations across the 2 animals
    assert con.execute("SELECT count(*) FROM measurement").fetchone()[0] == 3
    # the "NA" cell → value_raw kept, value_num NULL
    na = con.execute(
        "SELECT value_raw, value_num FROM measurement WHERE day='SD5'"
    ).fetchone()
    assert na == ("NA", None)
    # a numeric cell parses
    num = con.execute(
        "SELECT value_raw, value_num, terminal FROM measurement "
        "WHERE day='SD0' AND subject_id LIKE '%101'"
    ).fetchone()
    assert num == ("285.1", 285.1, False)


def test_subject_ids_scoped_and_dose_groups(tmp_path):
    db = _build(tmp_path)
    con = duckdb.connect(str(db), read_only=True)
    assert con.execute("SELECT count(*) FROM subject").fetchone()[0] == 2
    # dose_group: 2 doses (0.0, 100.0) each with 1 animal
    dg = con.execute("SELECT dose, n FROM dose_group ORDER BY dose").fetchall()
    con.close()
    assert dg == [(0.0, 1), (100.0, 1)]


def test_apical_result_keeps_string_and_parsed_bmd(tmp_path):
    db = _build(tmp_path)
    con = duckdb.connect(str(db), read_only=True)
    tt = con.execute(
        "SELECT bmd_str, bmd_num, bmd_status, model_name, direction "
        "FROM apical_result WHERE endpoint='Total Thyroxine'"
    ).fetchone()
    assert tt == ("8.54", 8.54, "viable", "Hill", "DOWN")
    # the non-numeric "—" → string kept, numeric NULL
    nr = con.execute(
        "SELECT bmd_str, bmd_num FROM apical_result WHERE endpoint='Cholesterol'"
    ).fetchone()
    con.close()
    assert nr == ("—", None)


def test_gene_set_superset_and_gene_explosion(tmp_path):
    db = _build(tmp_path)
    con = duckdb.connect(str(db), read_only=True)
    # one gene_set row, organ/sex lowercased from the entry
    gs = con.execute(
        "SELECT organ, sex, stat, go_id, n_genes FROM gene_set"
    ).fetchone()
    assert gs == ("liver", "male", "median", "GO:0051301", 3)
    # its 3 semicolon genes exploded into the junction
    members = [r[0] for r in con.execute(
        "SELECT gene_symbol FROM gene_set_gene WHERE go_id='GO:0051301' ORDER BY gene_symbol"
    ).fetchall()]
    con.close()
    assert members == ["ddit4", "egr1", "myc"]


def test_adversity_stat_block_normalized(tmp_path):
    db = _build(tmp_path)
    con = duckdb.connect(str(db), read_only=True)
    # 3 metrics (bmd/bmdl/bmdu) for the one signature → 3 bmd_stat rows
    n = con.execute(
        "SELECT count(*) FROM bmd_stat WHERE owner_kind='adversity' AND owner_id='SIGA'"
    ).fetchone()[0]
    assert n == 3
    bmd_block = con.execute(
        "SELECT mean, median, lower95 FROM bmd_stat "
        "WHERE owner_id='SIGA' AND metric='bmd'"
    ).fetchone()
    con.close()
    assert bmd_block == (5.0, 4.8, None)  # lower95 null preserved


def test_rebuild_is_idempotent(tmp_path):
    session = tmp_path / "DTXSID_T"
    integrated = _write_synthetic_session(session)
    db = build_session_db("DTXSID_T", session, integrated)
    first = db.stat().st_size

    # rebuild over the existing DB from the same inputs — must not raise (no WAL
    # replay conflict), and content is unchanged.
    build_session_db("DTXSID_T", session, integrated)
    con = duckdb.connect(str(db), read_only=True)
    assert con.execute("SELECT count(*) FROM measurement").fetchone()[0] == 3
    con.close()
    assert abs(db.stat().st_size - first) < 4096  # essentially unchanged
