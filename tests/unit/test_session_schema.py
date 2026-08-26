"""
Unit tests for the canonical per-session DuckDB schema (ADR-0016 Phase A).

This is DDL-only (no writer yet), so the tests pin what a schema module can pin:
the DDL is valid DuckDB, it is idempotent, table_names() can't drift from the
actual tables, and the keystone `measurement` table has the (subject × endpoint ×
day) grain with the raw/parsed value split the sidecar reconstruction needs.
"""

import duckdb
import pytest

from pipeline.session_schema import (
    SCHEMA_VERSION,
    schema_statements,
    table_names,
)


def _fresh_db():
    con = duckdb.connect(":memory:")
    for stmt in schema_statements():
        con.execute(stmt)
    return con


def test_schema_version_is_positive_int():
    assert isinstance(SCHEMA_VERSION, int) and SCHEMA_VERSION >= 1


def test_ddl_loads_into_duckdb():
    con = _fresh_db()
    actual = {
        r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchall()
    }
    assert actual == set(table_names())


def test_table_names_cannot_drift_from_ddl():
    # table_names() is derived from the DDL, so it must equal what DuckDB built.
    con = _fresh_db()
    built = sorted(
        r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchall()
    )
    assert sorted(table_names()) == built


def test_ddl_is_idempotent():
    # CREATE TABLE IF NOT EXISTS → running the whole DDL twice is a no-op.
    con = _fresh_db()
    for stmt in schema_statements():
        con.execute(stmt)  # must not raise


def test_spine_and_extension_tables_present():
    names = set(table_names())
    spine = {"study", "experiment", "source_file", "subject",
             "dose_group", "measurement"}
    extensions = {"endpoint", "apical_result", "bmd_stat", "gene",
                  "gene_set", "gene_set_gene", "adversity_signature"}
    assert spine <= names, f"missing spine tables: {spine - names}"
    assert extensions <= names, f"missing extension tables: {extensions - names}"
    assert "schema_version" in names


def test_measurement_has_tidy_long_form_grain():
    # The keystone: one row per (subject × endpoint × day), value kept as BOTH a
    # verbatim string (nullable) and a parsed float (nullable).
    con = _fresh_db()
    cols = {r[1]: r[2] for r in con.execute("PRAGMA table_info(measurement)").fetchall()}
    for grain_col in ("subject_id", "endpoint", "day"):
        assert grain_col in cols
    assert cols["value_raw"] == "VARCHAR"
    assert cols["value_num"] == "DOUBLE"
    assert cols["terminal"] == "BOOLEAN"


def test_bmd_stat_has_ten_key_block():
    con = _fresh_db()
    cols = {r[1] for r in con.execute("PRAGMA table_info(bmd_stat)").fetchall()}
    ten_key = {"mean", "median", "minimum", "weighted_mean", "sd",
               "weighted_sd", "fifth_pct", "tenth_pct", "lower95", "upper95"}
    assert ten_key <= cols, f"missing stat keys: {ten_key - cols}"
    # polymorphic owner so one block table serves gene_set / adversity / apical
    assert {"owner_kind", "owner_id", "metric"} <= cols


def test_apical_result_keeps_string_and_parsed_bmd():
    # source bmd/bmdl are display STRINGS ("—" when none); we keep both.
    con = _fresh_db()
    cols = {r[1]: r[2] for r in con.execute("PRAGMA table_info(apical_result)").fetchall()}
    assert cols["bmd_str"] == "VARCHAR" and cols["bmdl_str"] == "VARCHAR"
    assert cols["bmd_num"] == "DOUBLE" and cols["bmdl_num"] == "DOUBLE"


def test_can_insert_and_query_measurement_roundtrip():
    # A smoke insert proves the column types accept the real value shapes,
    # including a NULL value_num for a non-numeric ("NA") cell.
    con = _fresh_db()
    con.execute(
        "INSERT INTO measurement VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ["DTXSID1", "DTXSID1|Body Weight|Male|101", "Body Weight",
         "Body Weight", "SD0", "285.1", 285.1, False],
    )
    con.execute(
        "INSERT INTO measurement VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ["DTXSID1", "DTXSID1|Body Weight|Male|102", "Body Weight",
         "Body Weight", "SD0", None, None, False],
    )
    rows = con.execute(
        "SELECT count(*), count(value_num) FROM measurement"
    ).fetchone()
    assert rows == (2, 1)  # 2 rows, 1 non-null parsed value
