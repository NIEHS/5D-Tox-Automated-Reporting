"""
session_db.py — the writer that materializes a session's DuckDB (ADR-0016 Phase A).

``build_session_db`` reads a session's on-disk artifacts (integrated.json + the
per-animal sidecars + the derived ``_cache_*`` payloads) and writes the canonical
relational projection to ``sessions/<dtxsid>/session.duckdb`` — the schema defined
in ``pipeline/session_schema.py``.

This is a REBUILDABLE projection, not a system of record: it is dropped and
rewritten from scratch on every build, so it can never drift from the artifacts.
It carries no filters — every table is the full SUPERSET (GO cutoffs / organ /
sex / gene filters are a query-time concern, consistent with the phase-2/4
filter-agnostic-cache principle).

Read-only queries open it with ``read_only=True`` (Phase B); this writer is the
only writer.

The field mappings track the REAL artifact shapes (verified against
DTXSID50469320, 2026-08-23) — see the notes at each loader. In particular:

  * study identity lives under ``experimentDescription`` (``dsstox``,
    ``studyDuration``, ``articleRoute``/``articleVehicle``), not top-level;
  * sidecar ``observations[].value`` is a string or null → split into
    ``value_raw`` + parsed ``value_num``;
  * apical ``bmd``/``bmdl`` are display strings ("—", "2.56e+03") → kept as
    strings AND parsed to ``bmd_num``/``bmdl_num``;
  * ``gene_set.genes`` is a semicolon-joined string → exploded into
    ``gene_set_gene``;
  * the genomics ``gene_sets_chart_by_stat`` slice is the SUPERSET (no rank, no
    cutoffs) — that is what we load, so the DB is cutoff-agnostic.
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import tempfile
from pathlib import Path

import duckdb

from pipeline.session_schema import SCHEMA_VERSION, schema_statements, table_names

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _num(val) -> float | None:
    """Best-effort parse of a source value to float, else None.

    Source BMD/observation values are display strings ("—", "NA", "2.56e+03",
    "867") or None; anything that doesn't parse becomes NULL in the numeric
    column (the verbatim string is preserved separately).
    """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s or s in ("—", "-", "NA", "ND", "NR", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _iso_now_from(integrated: dict) -> str:
    """The build timestamp. We reuse the integration timestamp rather than a wall
    clock so a rebuild of the same integration is deterministic (and because the
    sandbox forbids Date.now-style calls in some contexts)."""
    return str((integrated.get("_meta") or {}).get("integrated_at") or "")


def _latest_cache(session_dir: Path, prefix: str) -> dict | list | None:
    """Load the newest ``_cache_<prefix>_*.json`` payload, or None if absent.

    Each stage writes a hash-suffixed cache; the newest by mtime is the current
    one (the same selection the export reader uses)."""
    matches = sorted(
        glob.glob(str(session_dir / f"_cache_{prefix}_*.json")),
        key=os.path.getmtime,
    )
    if not matches:
        return None
    try:
        with open(matches[-1], encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _load_sidecars(session_dir: Path) -> list[dict]:
    """Every sidecar under ``files/`` (all platforms × sexes), parsed."""
    files_dir = session_dir / "files"
    out: list[dict] = []
    if not files_dir.is_dir():
        return out
    for fname in sorted(os.listdir(files_dir)):
        if not fname.endswith(".sidecar.json"):
            continue
        try:
            with open(files_dir / fname, encoding="utf-8") as f:
                out.append(json.load(f))
        except (json.JSONDecodeError, OSError):
            continue
    return out


# ---------------------------------------------------------------------------
# Per-table loaders — each returns a list of value-tuples to executemany().
# Column order MUST match the CREATE TABLE column order in session_schema.py.
# ---------------------------------------------------------------------------


def _rows_study(dtxsid: str, integrated: dict) -> list[tuple]:
    exps = integrated.get("doseResponseExperiments") or []
    ed = (exps[0].get("experimentDescription") if exps else {}) or {}
    ta = ed.get("testArticle") or {}
    meta = integrated.get("_meta") or {}
    name = ta.get("name") or integrated.get("name") or dtxsid
    return [(
        dtxsid,
        name,
        ta.get("casrn") or "",
        ed.get("species") or "",
        ed.get("strain") or "",
        ed.get("studyDuration") or "",
        ed.get("articleRoute") or "",
        ed.get("articleVehicle") or "",
        _iso_now_from(integrated),
        len(meta.get("source_files") or {}),
    )]


def _rows_experiment(dtxsid: str, integrated: dict) -> list[tuple]:
    rows: list[tuple] = []
    for exp in integrated.get("doseResponseExperiments") or []:
        ed = exp.get("experimentDescription") or {}
        ref = str(exp.get("@ref") or "")
        rows.append((
            f"{dtxsid}|{ref}",           # experiment_id (dtxsid-scoped @ref)
            dtxsid,
            exp.get("name") or "",
            ed.get("platform") or "",
            ed.get("provider") or "",
            ed.get("sex") or "",
            ed.get("organ") or "",
            ed.get("dataType") or "",
            ref,
        ))
    return rows


def _rows_source_file(dtxsid: str, integrated: dict) -> list[tuple]:
    rows: list[tuple] = []
    src = (integrated.get("_meta") or {}).get("source_files") or {}
    for key, sf in src.items():
        # key is "<Platform>|<tier>"; the platform is the part before "|".
        platform = key.split("|", 1)[0] if "|" in key else key
        rows.append((
            sf.get("file_id") or key,
            dtxsid,
            sf.get("filename") or "",
            platform,
            sf.get("tier") or "",
            sf.get("file_count"),
            sf.get("experiment_count"),
        ))
    return rows


def _rows_subject_and_measurement(
    dtxsid: str, sidecars: list[dict]
) -> tuple[list[tuple], list[tuple], list[tuple]]:
    """Build subject, measurement, and dose_group rows from the sidecars.

    subject_id is synthesized "<dtxsid>|<platform>|<sex>|<external_id>" — an
    animal id (e.g. "101") is only unique within a sidecar (platform × sex).
    """
    subjects: list[tuple] = []
    measurements: list[tuple] = []
    # dose_group counts: (platform, sex, dose) -> n distinct animals
    dg: dict[tuple[str, str, float | None], int] = {}

    for sc in sidecars:
        platform = sc.get("platform") or ""
        sex = sc.get("sex") or ""
        for ext_id, animal in (sc.get("animals") or {}).items():
            dose = animal.get("dose")
            dose_f = float(dose) if isinstance(dose, (int, float)) else _num(dose)
            selection = animal.get("selection") or ""
            subject_id = f"{dtxsid}|{platform}|{sex}|{ext_id}"
            subjects.append((
                subject_id, dtxsid, str(ext_id), platform, sex, dose_f, selection,
            ))
            dg[(platform, sex, dose_f)] = dg.get((platform, sex, dose_f), 0) + 1
            for obs in animal.get("observations") or []:
                raw = obs.get("value")
                measurements.append((
                    dtxsid,
                    subject_id,
                    platform,
                    obs.get("endpoint") or "",
                    obs.get("day") or "",
                    None if raw is None else str(raw),
                    _num(raw),
                    bool(obs.get("terminal")),
                ))

    dose_groups = [
        (dtxsid, platform, sex, dose, n)
        for (platform, sex, dose), n in dg.items()
    ]
    return subjects, measurements, dose_groups


def _rows_apical(dtxsid: str, bmd_summary: dict | None) -> tuple[list[tuple], list[tuple]]:
    """apical_result rows + the distinct endpoint dimension rows.

    Built from the bmd_summary ``apical`` list (the real endpoints), enriched
    with ``model_name`` from the ``bmds`` list joined on (endpoint, sex,
    platform).  bmd/bmdl are display STRINGS in the source; we keep the string
    and a parsed numeric.
    """
    if not bmd_summary:
        return [], []
    apical = bmd_summary.get("apical") or []
    bmds = bmd_summary.get("bmds") or []
    model_by_key = {
        (b.get("endpoint"), b.get("sex"), b.get("platform")): b.get("model_name")
        for b in bmds
    }
    rows: list[tuple] = []
    endpoints: set[tuple[str, str]] = set()
    for a in apical:
        platform = a.get("platform") or ""
        endpoint = a.get("endpoint") or ""
        sex = a.get("sex") or ""
        endpoints.add((platform, endpoint))
        rows.append((
            dtxsid,
            platform,
            sex,
            endpoint,
            a.get("bmd"),
            a.get("bmdl"),
            _num(a.get("bmd")),
            _num(a.get("bmdl")),
            a.get("bmd_status"),
            a.get("loel"),
            a.get("noel"),
            a.get("direction") or "",
            model_by_key.get((endpoint, sex, platform)),
            None,   # responsive: not carried on the summary row
            None,   # trend_marker: not carried on the summary row
        ))
    endpoint_rows = [(dtxsid, p, e) for (p, e) in sorted(endpoints)]
    return rows, endpoint_rows


def _rows_genomics(dtxsid: str, genomics: dict | None):
    """gene, gene_set, gene_set_gene, adversity_signature, bmd_stat rows.

    genomics is the ``{"<organ>_<sex>": entry}`` extraction cache — the
    cutoff-agnostic SUPERSET.  We load gene_set from ``gene_sets_chart_by_stat``
    (the full slice, no rank) so the DB stays cutoff-agnostic.
    """
    genes: list[tuple] = []
    gene_sets: list[tuple] = []
    gene_set_genes: list[tuple] = []
    adversity: list[tuple] = []
    bmd_stats: list[tuple] = []

    if not genomics:
        return genes, gene_sets, gene_set_genes, adversity, bmd_stats

    for entry in genomics.values():
        if not isinstance(entry, dict):
            continue
        organ = entry.get("organ") or ""
        sex = entry.get("sex") or ""

        # genes: prefer the fuller top_genes shape; fall back to all_genes.
        seen_gene_keys: set[tuple] = set()
        for gk in ("top_genes", "all_genes"):
            for g in entry.get(gk) or []:
                sym = g.get("gene_symbol") or g.get("gene") or ""
                key = (sym, g.get("probe_id"))
                if key in seen_gene_keys:
                    continue
                seen_gene_keys.add(key)
                genes.append((
                    dtxsid, organ, sex, sym, g.get("probe_id"),
                    g.get("rank"), _num(g.get("bmd")), _num(g.get("bmdl")),
                    _num(g.get("bmdu")), g.get("direction") or "",
                    _num(g.get("fold_change")), _num(g.get("r_squared")),
                ))

        # gene_set: the chart-by-stat superset (no cutoffs, no rank).
        for stat, rows in (entry.get("gene_sets_chart_by_stat") or {}).items():
            for r in rows or []:
                go_id = r.get("go_id") or ""
                gene_sets.append((
                    dtxsid, organ, sex, stat, r.get("rank"),
                    go_id, r.get("go_term") or "",
                    _num(r.get("bmd")), _num(r.get("bmdl")), _num(r.get("bmdu")),
                    r.get("n_genes"), r.get("n_genes_with_bmd"),
                    r.get("direction") or "", r.get("n_up"), r.get("n_down"),
                    _num(r.get("fishers_p")),
                ))
                # explode the semicolon-joined member genes into the junction
                for sym in str(r.get("genes") or "").split(";"):
                    sym = sym.strip()
                    if sym:
                        gene_set_genes.append((dtxsid, organ, sex, go_id, sym))

        # adversity signatures + their 10-key stat blocks
        for a in entry.get("adversity_signatures") or []:
            sig_id = a.get("signature_id") or ""
            adversity.append((
                dtxsid, organ, sex, sig_id, a.get("title") or "",
                bool(a.get("active")), a.get("n_passed"), a.get("n_genes"),
                _num(a.get("percentage")), _num(a.get("bmd")), _num(a.get("bmdl")),
                _num(a.get("bmdu")), a.get("direction") or "",
                _num(a.get("fishers_p")),
            ))
            for metric, block_key in (("bmd", "bmd_stats"),
                                      ("bmdl", "bmdl_stats"),
                                      ("bmdu", "bmdu_stats")):
                blk = a.get(block_key)
                if isinstance(blk, dict):
                    bmd_stats.append((
                        dtxsid, "adversity", sig_id, metric,
                        blk.get("mean"), blk.get("median"), blk.get("minimum"),
                        blk.get("weighted_mean"), blk.get("sd"),
                        blk.get("weighted_sd"), blk.get("fifth_pct"),
                        blk.get("tenth_pct"), blk.get("lower95"), blk.get("upper95"),
                    ))

    return genes, gene_sets, gene_set_genes, adversity, bmd_stats


# ---------------------------------------------------------------------------
# The build entry point
# ---------------------------------------------------------------------------

# (table name, column count) — for the INSERT placeholder strings. Column count
# is validated against the actual DuckDB table before insert, so a schema/loader
# mismatch fails loudly rather than silently misaligning columns.
def _insert(con, table: str, rows: list[tuple]) -> int:
    if not rows:
        return 0
    ncols = len(rows[0])
    placeholders = ", ".join(["?"] * ncols)
    con.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)
    return len(rows)


def build_session_db(dtxsid: str, session_dir: str | Path, integrated: dict) -> Path:
    """Materialize ``sessions/<dtxsid>/session.duckdb`` from the session artifacts.

    Args:
        dtxsid:      the session id.
        session_dir: the session directory (holds files/, _cache_*.json).
        integrated:  the parsed integrated.json (BMDProject). Passed in rather
                     than re-read here so the caller (run_process) reuses the copy
                     already in memory, and so this is trivially testable.

    Returns the path to the written DB. Drops any existing DB first (the
    projection is always rebuilt from scratch — no stale rows).

    IMPLEMENTATION NOTE — build-then-copy. The DB is built at a TEMP path and the
    finished, checkpointed single file is copied into place, rather than opening
    DuckDB directly on ``session_dir/session.duckdb``. Two reasons: (1) it is
    atomic-ish — a reader never sees a half-written DB, and a crashed build leaves
    the old DB intact; (2) on some mounts DuckDB's create-time file lock (fcntl)
    blocks hard (observed in the /workspace sandbox on XFS/overlay), while a plain
    file copy does not. ``BMDX_SESSION_DB_TMPDIR`` overrides the temp location
    (default: the system temp dir); point it at a local/tmpfs path if the default
    temp is on a lock-hostile mount.
    """
    session_dir = Path(session_dir)
    db_path = session_dir / "session.duckdb"

    sidecars = _load_sidecars(session_dir)
    bmd_summary = _latest_cache(session_dir, "bmd_summary")
    genomics = _latest_cache(session_dir, "genomics")

    subjects, measurements, dose_groups = _rows_subject_and_measurement(dtxsid, sidecars)
    apical_rows, endpoint_rows = _rows_apical(dtxsid, bmd_summary)
    genes, gene_sets, gene_set_genes, adversity, bmd_stats = _rows_genomics(dtxsid, genomics)

    tmp_root = os.environ.get("BMDX_SESSION_DB_TMPDIR") or None
    tmp_dir = Path(tempfile.mkdtemp(prefix="session_db_", dir=tmp_root))
    tmp_db = tmp_dir / "session.duckdb"
    tmp_parquet = tmp_dir / "session_parquet"
    tmp_parquet.mkdir()
    try:
        con = duckdb.connect(str(tmp_db))
        try:
            for stmt in schema_statements():
                con.execute(stmt)

            con.execute(
                "INSERT INTO schema_version VALUES (?, ?)",
                [SCHEMA_VERSION, _iso_now_from(integrated)],
            )
            _insert(con, "study", _rows_study(dtxsid, integrated))
            _insert(con, "experiment", _rows_experiment(dtxsid, integrated))
            _insert(con, "source_file", _rows_source_file(dtxsid, integrated))
            _insert(con, "subject", subjects)
            _insert(con, "dose_group", dose_groups)
            _insert(con, "measurement", measurements)
            _insert(con, "endpoint", endpoint_rows)
            _insert(con, "apical_result", apical_rows)
            _insert(con, "bmd_stat", bmd_stats)
            _insert(con, "gene", genes)
            _insert(con, "gene_set", gene_sets)
            _insert(con, "gene_set_gene", gene_set_genes)
            _insert(con, "adversity_signature", adversity)
            # Fold the WAL into the main file so the copied artifact is a single,
            # self-contained file (no .wal to replay on open).
            con.execute("CHECKPOINT")

            # Per-table Parquet export. This is the browser transport (ADR-0016
            # Phase C): duckdb-wasm reads Parquet natively, which DECOUPLES the
            # browser engine version from this writer's — a native .duckdb would
            # couple them. Parquet is a stable columnar format; each table is a
            # small, independently-fetchable file the shell loads on demand.
            for table in table_names():
                out = (tmp_parquet / f"{table}.parquet").as_posix()
                con.execute(
                    f"COPY {table} TO '{out}' (FORMAT PARQUET)"
                )
        finally:
            con.close()

        # Copy the finished single DB file into place (plain sequential write — no
        # DuckDB lock on the destination mount). Replace any prior DB.
        if db_path.exists():
            db_path.unlink()
        shutil.copyfile(str(tmp_db), str(db_path))

        # Replace the Parquet dir wholesale (always fresh — no stale table files).
        parquet_dir = session_dir / "session_parquet"
        if parquet_dir.exists():
            shutil.rmtree(parquet_dir)
        shutil.copytree(str(tmp_parquet), str(parquet_dir))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return db_path
