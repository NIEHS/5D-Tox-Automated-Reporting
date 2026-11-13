"""
session_schema.py — the canonical per-session DuckDB schema (ADR-0016 Phase A).

Defines the DDL for ``sessions/<dtxsid>/session.duckdb`` — the queryable,
relational projection of one session's study data. This module is DDL ONLY: the
writer that populates it (``build_session_db``) lands separately; the read-only
query layer (``session_query``) lands in Phase B. Keeping the schema in its own
module means the writer and any tests import ONE definition.

Design (per ADR-0016):

  * A GENERIC SPINE (``study / experiment / source_file / subject / dose_group /
    measurement``) that is domain-NEUTRAL — it reads sensibly for any dosed-cohort
    experiment, not just NTP tox. This is the seam that carries to non-tox journal
    articles.
  * TOX EXTENSIONS (``endpoint / apical_result / bmd_stat / gene / gene_set /
    gene_set_gene / adversity_signature``) layered on the spine. Pluggable.

``measurement`` is the keystone: one row per (subject × endpoint × day), the tidy
long form that exists in NO current artifact (it is reconstructed from the
per-animal sidecar ``observations[]``). Every ad-hoc per-animal question reduces
to this grain.

Conventions mirror the knowledge-base DB (``knowledge_base/build_db.py``): natural
``VARCHAR`` PKs where a natural key exists, singular snake_case columns,
``DOUBLE``/``INTEGER``/``BOOLEAN``, ``VARCHAR[]`` arrays, **no declared FK
constraints** (join discipline by convention — DuckDB enforcement is coarse and
the loads are idempotent ``INSERT OR IGNORE``). No surrogate autoincrement keys:
this DB is a rebuildable projection, not a system of record.

Field names track the REAL source artifacts, which diverge from the ADR's
paraphrase in several places (verified against source, 2026-08-23):

  * Study identity lives under ``experimentDescription`` in integrated.json, with
    names ``dsstox`` (not "dtxsid"), ``studyDuration``, ``articleRoute`` /
    ``articleVehicle`` — the writer maps those onto the neutral column names here.
  * ``measurement.value`` in the sidecar is a STRING and may be null ("NA"); we
    keep both ``value_raw`` (verbatim) and ``value_num`` (parsed float or NULL).
  * A TableRow carries NO numeric bmd/bmdl — only string forms; the BMD summary
    cache exposes ``bmd``/``bmdl`` as STRINGS too. ``apical_result`` therefore
    keeps the display strings AND a best-effort parsed numeric for querying.
  * ``gene_set.genes`` is a semicolon-joined string → exploded into the
    ``gene_set_gene`` junction.
  * The 10-key stat block (``mean median minimum weighted_mean sd weighted_sd
    fifth_pct tenth_pct lower95 upper95``) recurs in 3 places; ``lower95`` /
    ``upper95`` are frequently null in real data.
"""

from __future__ import annotations

# The schema version. Bump when the DDL below changes in a way that makes an
# existing session.duckdb unqueryable by the current query layer (added/renamed/
# removed columns or tables). The writer records this into the schema_version
# table so an old DB is detectable (→ rebuild on next process, same trigger as
# the cache wipe).
SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# DDL. One string of ``;``-separated CREATE statements — the writer executes it
# the same way build_db.py does:  for stmt in SCHEMA_SQL.split(";"): con.execute.
# CREATE TABLE IF NOT EXISTS so the string is safe to run against a fresh DB and
# harmless to re-run; the writer TRUNCATEs / rebuilds on re-integration.
# ---------------------------------------------------------------------------
SCHEMA_SQL = """
-- ======================================================================
-- Provenance
-- ======================================================================

-- One row. Records the schema version this DB was built under so a stale DB is
-- detectable and can be rebuilt.
CREATE TABLE IF NOT EXISTS schema_version (
    version       INTEGER,
    built_at      VARCHAR          -- ISO-8601 timestamp, passed in by the writer
);

-- ======================================================================
-- Generic spine (domain-neutral)
-- ======================================================================

-- One row per session. Study-level identity + provenance.
-- Source: integrated.json experimentDescription.testArticle{name,casrn,dsstox}
--         + studyDuration / species / strain / articleRoute / articleVehicle,
--         and _meta.{dtxsid, integrated_at}.
CREATE TABLE IF NOT EXISTS study (
    dtxsid            VARCHAR PRIMARY KEY,
    name              VARCHAR,       -- test article name
    casrn             VARCHAR,       -- may be '' in source
    species           VARCHAR,
    strain            VARCHAR,
    duration          VARCHAR,       -- <- experimentDescription.studyDuration
    route             VARCHAR,       -- <- articleRoute
    vehicle           VARCHAR,       -- <- articleVehicle
    integrated_at     VARCHAR,       -- <- _meta.integrated_at (ISO ts)
    source_file_count INTEGER
);

-- One row per dose-response experiment in the integrated pool.
-- Source: doseResponseExperiments[].experimentDescription + @ref.
-- (platform / provider / sex / organ / data_type are nested UNDER
--  experimentDescription, not top-level — see module docstring.)
CREATE TABLE IF NOT EXISTS experiment (
    experiment_id  VARCHAR PRIMARY KEY,   -- the @ref join key
    dtxsid         VARCHAR,
    name           VARCHAR,
    platform       VARCHAR,
    provider       VARCHAR,
    sex            VARCHAR,
    organ          VARCHAR,
    data_type      VARCHAR,               -- <- experimentDescription.dataType
    ref            VARCHAR                -- the raw @ref (kept even though == PK)
);

-- One row per source file that fed integration.
-- Source: integrated.json _meta.source_files (a dict keyed "<Platform>|<tier>").
CREATE TABLE IF NOT EXISTS source_file (
    file_id          VARCHAR PRIMARY KEY,
    dtxsid           VARCHAR,
    filename         VARCHAR,
    platform         VARCHAR,
    tier             VARCHAR,       -- 'bm2' / 'inferred' / ...
    file_count       INTEGER,
    experiment_count INTEGER
);

-- One row per animal. "subject" is the neutral term (animal in tox).
-- Source: the per-animal sidecar `animals{}` map (the id is the map KEY, not a
-- field). selection = Core Animals vs Biosampling Animals vs Unknown.
CREATE TABLE IF NOT EXISTS subject (
    subject_id   VARCHAR PRIMARY KEY,   -- synthesized: "<dtxsid>|<platform>|<sex>|<external_id>"
    dtxsid       VARCHAR,
    external_id  VARCHAR,               -- the study's animal id (sidecar map key, e.g. "101")
    platform     VARCHAR,               -- which sidecar the animal came from
    sex          VARCHAR,
    dose         DOUBLE,
    selection    VARCHAR
);

-- Design counts per (platform, sex, dose). Not per-animal — the dose-group grain.
-- Source: sidecar animal roster aggregated, or Treatment/dose_design.
CREATE TABLE IF NOT EXISTS dose_group (
    dtxsid    VARCHAR,
    platform  VARCHAR,
    sex       VARCHAR,
    dose      DOUBLE,
    n         INTEGER
);

-- THE tidy long form: one row per (subject × endpoint × day). Exists in no
-- current artifact — reconstructed from sidecar observations[].
-- value_raw keeps the verbatim string ("285.1", or NULL for a blank/"NA" cell);
-- value_num is the parsed float or NULL. terminal is the sidecar terminal flag.
CREATE TABLE IF NOT EXISTS measurement (
    dtxsid      VARCHAR,
    subject_id  VARCHAR,       -- FK-by-convention → subject.subject_id
    platform    VARCHAR,
    endpoint    VARCHAR,       -- raw observation endpoint (NOT the pivot day-tag)
    day         VARCHAR,       -- e.g. "SD0" / "SD5"
    value_raw   VARCHAR,       -- verbatim, NULL when the source cell was blank/"NA"
    value_num   DOUBLE,        -- parsed float, NULL when non-numeric
    terminal    BOOLEAN
);

-- ======================================================================
-- Tox extensions
-- ======================================================================

-- Distinct apical endpoints seen, per platform. A lookup/dimension table.
CREATE TABLE IF NOT EXISTS endpoint (
    dtxsid    VARCHAR,
    platform  VARCHAR,
    label     VARCHAR
);

-- One row per apical endpoint result (the dose-response table rows + BMD summary).
-- Source: _cache_bmd_summary(apical) rows + the NTP TableRow. NOTE: bmd/bmdl are
-- STRINGS in the source (display forms like "12.3" or "—"); we keep the string
-- AND a best-effort parsed numeric (NULL when not a number) for querying.
CREATE TABLE IF NOT EXISTS apical_result (
    dtxsid        VARCHAR,
    platform      VARCHAR,
    sex           VARCHAR,
    endpoint      VARCHAR,
    bmd_str       VARCHAR,       -- verbatim display string ("—" when none)
    bmdl_str      VARCHAR,
    bmd_num       DOUBLE,        -- parsed bmd_str, NULL when non-numeric
    bmdl_num      DOUBLE,
    bmd_status    VARCHAR,       -- viable / NVM / NR / UREP / failure / NULL
    loel          DOUBLE,        -- numeric in source (nullable)
    noel          DOUBLE,
    direction     VARCHAR,       -- "UP" / "DOWN" / ""
    model_name    VARCHAR,       -- from the bmds summary rows (nullable)
    responsive    BOOLEAN,
    trend_marker  VARCHAR
);

-- The recurring 10-key BMD stat block, normalized. Referenced polymorphically:
-- owner_kind ∈ {gene_set, adversity, apical}, owner_id identifies the row it
-- belongs to. metric ∈ {bmd, bmdl, bmdu} (which of the trio this block describes).
-- lower95 / upper95 are frequently NULL in real data.
CREATE TABLE IF NOT EXISTS bmd_stat (
    dtxsid         VARCHAR,
    owner_kind     VARCHAR,       -- gene_set | adversity | apical
    owner_id       VARCHAR,       -- identifies the owning row
    metric         VARCHAR,       -- bmd | bmdl | bmdu
    mean           DOUBLE,
    median         DOUBLE,
    minimum        DOUBLE,
    weighted_mean  DOUBLE,
    sd             DOUBLE,
    weighted_sd    DOUBLE,
    fifth_pct      DOUBLE,
    tenth_pct      DOUBLE,
    lower95        DOUBLE,
    upper95        DOUBLE
);

-- One row per gene (per organ × sex). Source: genomics top_genes / all_genes.
-- probe_id / rank / r_squared present on top_genes; all_genes is a thinner slice.
CREATE TABLE IF NOT EXISTS gene (
    dtxsid       VARCHAR,
    organ        VARCHAR,
    sex          VARCHAR,
    gene_symbol  VARCHAR,
    probe_id     VARCHAR,
    rank         INTEGER,       -- positional within the slice (nullable)
    bmd          DOUBLE,
    bmdl         DOUBLE,
    bmdu         DOUBLE,
    direction    VARCHAR,       -- lowercase in source ("up"/"down")
    fold_change  DOUBLE,
    r_squared    DOUBLE
);

-- One row per GO gene-set (per organ × sex × stat). THE SUPERSET — GO cutoffs and
-- organ/sex/gene filters are applied at QUERY time, not baked in (consistent with
-- the filter-agnostic-cache principle). Source: gene_sets_chart_by_stat rows.
CREATE TABLE IF NOT EXISTS gene_set (
    dtxsid            VARCHAR,
    organ             VARCHAR,
    sex               VARCHAR,
    stat              VARCHAR,       -- which BMD stat this slice is ranked by
    rank              INTEGER,       -- positional (nullable — chart slice has none)
    go_id             VARCHAR,
    go_term           VARCHAR,
    bmd               DOUBLE,
    bmdl              DOUBLE,
    bmdu              DOUBLE,
    n_genes           INTEGER,
    n_genes_with_bmd  INTEGER,
    direction         VARCHAR,
    n_up              INTEGER,
    n_down            INTEGER,
    fishers_p         DOUBLE
);

-- Junction: a gene_set's member genes, exploded from the semicolon-joined
-- gene_set.genes string. Keyed by (organ, sex, go_id) since a GO term recurs
-- across organ×sex slices with different membership.
CREATE TABLE IF NOT EXISTS gene_set_gene (
    dtxsid       VARCHAR,
    organ        VARCHAR,
    sex          VARCHAR,
    go_id        VARCHAR,
    gene_symbol  VARCHAR
);

-- One row per adversity signature (per organ × sex). Source: the extraction's
-- adversity_signatures + _category_lookup. Its bmd/bmdl/bmdu stat blocks land in
-- bmd_stat (owner_kind='adversity', owner_id=signature_id).
CREATE TABLE IF NOT EXISTS adversity_signature (
    dtxsid        VARCHAR,
    organ         VARCHAR,
    sex           VARCHAR,
    signature_id  VARCHAR,
    title         VARCHAR,
    active        BOOLEAN,
    n_passed      INTEGER,
    n_genes       INTEGER,
    percentage    DOUBLE,
    bmd           DOUBLE,
    bmdl          DOUBLE,
    bmdu          DOUBLE,
    direction     VARCHAR,
    fishers_p     DOUBLE
);
"""


def schema_statements() -> list[str]:
    """The DDL as a list of individual, non-empty CREATE statements.

    The canonical splitter — the writer and tests should call THIS rather than
    splitting SCHEMA_SQL themselves, because ``--`` line comments may contain a
    ``;`` (which a naive ``SCHEMA_SQL.split(';')`` would wrongly break on). We
    strip line comments first, then split on the statement terminator.
    """
    lines = [ln for ln in SCHEMA_SQL.splitlines()]
    stripped = "\n".join(
        ln.split("--", 1)[0] if "--" in ln else ln
        for ln in lines
    )
    return [s.strip() for s in stripped.split(";") if s.strip()]


def table_names() -> list[str]:
    """The table names the schema defines, in declaration order.

    Derived from the DDL (not a hand-maintained second list) so it can't drift.
    Used by the query layer's schema endpoint and by tests asserting coverage.
    """
    names: list[str] = []
    for stmt in schema_statements():
        upper = stmt.upper()
        marker = "CREATE TABLE IF NOT EXISTS "
        idx = upper.find(marker)
        if idx == -1:
            continue
        rest = stmt[idx + len(marker):].strip()
        # table name is the token before '(' or whitespace
        name = rest.split("(")[0].split()[0]
        names.append(name)
    return names
