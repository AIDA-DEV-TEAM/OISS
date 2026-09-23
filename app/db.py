"""DuckDB connection, layer creation and canonical schema DDL.

The four layers of the brief are schemas inside one database file:

* ``raw``        -- as published, every column VARCHAR, nothing repaired.
* ``quarantine`` -- rows an error-severity rule rejected, with the rule code.
* ``staging``    -- typed, with canonical district/crop/period/block ids attached.
* ``analytics``  -- the fact and dimension tables the rest of the PoC reads.

Governance tables live in ``analytics`` so that lineage, versions and findings
are queryable next to the facts they describe.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import duckdb

from app.config import DB_PATH, LAYERS

# The shape of the database this code expects. Any change to DDL in this file
# bumps it (DESIGN.md). `app.cli build` writes it into analytics.schema_meta, and
# the backend refuses to start against a database built for another version:
# CREATE TABLE IF NOT EXISTS silently keeps an old table, and DuckDB cannot
# change a CHECK constraint in place, so rebuilding is the supported upgrade.
#   v1 -- every database built before versioning.
#   v2 -- sandbox runs record the model configuration they ran against.
SCHEMA_VERSION = 2

SCHEMA_META_DDL = """
CREATE TABLE IF NOT EXISTS analytics.schema_meta (
    version INTEGER NOT NULL
);
"""


class SchemaMismatch(RuntimeError):
    """The database was built by a different version of this code."""

    def __init__(self, found: int, expected: int) -> None:
        super().__init__(
            f"DB schema v{found}, code expects v{expected}: "
            "stop the backend and run app.cli build."
        )
        self.found = found
        self.expected = expected

# Every fact carries these three; the schema makes data_origin NOT NULL so a row
# can never reach analytics without declaring whether it is official or synthetic.
FACT_PROVENANCE_DDL = """
    dataset_version_id VARCHAR NOT NULL,
    data_origin        VARCHAR NOT NULL CHECK (data_origin IN ('official', 'synthetic')),
    value_status       VARCHAR NOT NULL
"""

DIMENSION_DDL = """
CREATE TABLE IF NOT EXISTS analytics.dim_district (
    district_id      VARCHAR PRIMARY KEY,
    display_name     VARCHAR NOT NULL,
    lgd_name         VARCHAR,
    lgd_code         VARCHAR,
    census_2011_code VARCHAR,
    headquarters     VARCHAR
);

CREATE TABLE IF NOT EXISTS analytics.dim_block (
    block_id     VARCHAR PRIMARY KEY,
    district_id  VARCHAR NOT NULL REFERENCES analytics.dim_district(district_id),
    block_code   INTEGER,
    display_name VARCHAR NOT NULL,
    is_urban     BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics.dim_crop (
    crop_id      VARCHAR PRIMARY KEY,
    display_name VARCHAR NOT NULL,
    crop_group   VARCHAR NOT NULL CHECK (
        crop_group IN ('cereal', 'pulse', 'oilseed', 'fibre', 'tuber', 'vegetable', 'sugar')
    ),
    in_earas     BOOLEAN NOT NULL,
    in_price     BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics.dim_price_type (
    price_type   VARCHAR PRIMARY KEY,
    display_name VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics.dim_period (
    period_id   VARCHAR PRIMARY KEY,
    agri_year   VARCHAR NOT NULL,
    season      VARCHAR,
    month_start DATE,
    period_type VARCHAR NOT NULL CHECK (period_type IN ('year', 'season', 'month'))
);
"""

FACT_DDL = f"""
CREATE TABLE IF NOT EXISTS analytics.fact_price (
    period_id             VARCHAR NOT NULL REFERENCES analytics.dim_period(period_id),
    district_id           VARCHAR NOT NULL REFERENCES analytics.dim_district(district_id),
    crop_id               VARCHAR NOT NULL REFERENCES analytics.dim_crop(crop_id),
    price_type            VARCHAR NOT NULL CHECK (price_type IN ('farm_harvest', 'wholesale')),
    price_rs_per_quintal  DOUBLE,
    unit                  VARCHAR NOT NULL,
    annual_level_basis    VARCHAR,
    annual_level_rs_per_quintal DOUBLE,
    source_row_ref        VARCHAR,
{FACT_PROVENANCE_DDL}
);

CREATE TABLE IF NOT EXISTS analytics.fact_crop_ayp (
    period_id          VARCHAR NOT NULL REFERENCES analytics.dim_period(period_id),
    district_id        VARCHAR NOT NULL REFERENCES analytics.dim_district(district_id),
    block_id           VARCHAR REFERENCES analytics.dim_block(block_id),
    crop_id            VARCHAR NOT NULL REFERENCES analytics.dim_crop(crop_id),
    product            VARCHAR NOT NULL CHECK (product IN ('paddy', 'rice', 'minor')),
    measure            VARCHAR NOT NULL CHECK (measure IN ('area', 'yield_rate', 'production')),
    value              DOUBLE,
    unit               VARCHAR NOT NULL,
    value_canonical    DOUBLE,
    unit_canonical     VARCHAR NOT NULL,
    block_name_as_published VARCHAR,
    source_row_ref     VARCHAR,
{FACT_PROVENANCE_DDL}
);

CREATE TABLE IF NOT EXISTS analytics.fact_land_use (
    period_id         VARCHAR NOT NULL REFERENCES analytics.dim_period(period_id),
    district_id       VARCHAR NOT NULL REFERENCES analytics.dim_district(district_id),
    block_id          VARCHAR REFERENCES analytics.dim_block(block_id),
    land_use_category VARCHAR NOT NULL,
    measure           VARCHAR NOT NULL,
    value             DOUBLE,
    unit              VARCHAR NOT NULL,
    value_canonical   DOUBLE,
    unit_canonical    VARCHAR NOT NULL,
    block_name_as_published VARCHAR,
    source_row_ref    VARCHAR,
{FACT_PROVENANCE_DDL}
);

CREATE TABLE IF NOT EXISTS analytics.fact_state_series (
    period_id       VARCHAR NOT NULL REFERENCES analytics.dim_period(period_id),
    crop_id         VARCHAR NOT NULL REFERENCES analytics.dim_crop(crop_id),
    product         VARCHAR NOT NULL CHECK (product IN ('paddy', 'rice', 'minor')),
    season          VARCHAR NOT NULL,
    measure         VARCHAR NOT NULL CHECK (measure IN ('area', 'yield_rate', 'production')),
    value           DOUBLE,
    unit            VARCHAR NOT NULL,
    value_canonical DOUBLE,
    unit_canonical  VARCHAR NOT NULL,
    source_row_ref  VARCHAR,
{FACT_PROVENANCE_DDL}
);
"""

GOVERNANCE_DDL = """
CREATE TABLE IF NOT EXISTS analytics.dataset_version (
    dataset_version_id VARCHAR PRIMARY KEY,
    dataset_name       VARCHAR NOT NULL,
    source_file        VARCHAR NOT NULL,
    source_type        VARCHAR NOT NULL,
    sha256             VARCHAR NOT NULL,
    row_count          BIGINT NOT NULL,
    layer              VARCHAR NOT NULL,
    loaded_at          TIMESTAMP NOT NULL,
    generator_version  VARCHAR,
    -- Exactly one version per dataset_name feeds the facts a query sees.
    -- The batch build's versions are active; an upload is promoted into the
    -- fact tables but stays inactive until someone activates it, because
    -- summing across two versions of the same dataset double-counts it.
    is_active          BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS analytics.lineage_edge (
    from_node          VARCHAR NOT NULL,
    to_node            VARCHAR NOT NULL,
    edge_type          VARCHAR NOT NULL,
    dataset_version_id VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics.validation_finding (
    run_id             VARCHAR NOT NULL,
    dataset_version_id VARCHAR NOT NULL,
    rule_code          VARCHAR NOT NULL,
    severity           VARCHAR NOT NULL CHECK (severity IN ('error', 'warning', 'info')),
    row_ref            VARCHAR,
    column_name        VARCHAR,
    message            VARCHAR,
    observed_value     VARCHAR
);

CREATE TABLE IF NOT EXISTS analytics.load_run (
    run_id       VARCHAR PRIMARY KEY,
    started_at   TIMESTAMP NOT NULL,
    finished_at  TIMESTAMP,
    status       VARCHAR NOT NULL,
    summary_json VARCHAR
);

CREATE TABLE IF NOT EXISTS analytics.finding_summary (
    run_id         VARCHAR NOT NULL,
    rule_code      VARCHAR NOT NULL,
    severity       VARCHAR NOT NULL,
    finding_count  BIGINT NOT NULL,
    dataset_count  BIGINT NOT NULL,
    sample_row_ref VARCHAR,
    sample_message VARCHAR
);

CREATE TABLE IF NOT EXISTS analytics.export (
    export_id    VARCHAR PRIMARY KEY,
    export_type  VARCHAR NOT NULL,
    format       VARCHAR NOT NULL,
    status       VARCHAR NOT NULL,
    filename     VARCHAR NOT NULL,
    file_path    VARCHAR NOT NULL,
    size_bytes   BIGINT NOT NULL,
    created_at   TIMESTAMP NOT NULL,
    -- The applied context as written into the file. Stored verbatim so the
    -- Exports screen shows what the file says, not a second derivation of it.
    context_json VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics.reconciliation_check (
    run_id     VARCHAR NOT NULL,
    check_code VARCHAR NOT NULL,
    passed     BOOLEAN NOT NULL,
    expected   VARCHAR,
    observed   VARCHAR,
    message    VARCHAR
);
"""

SANDBOX_DDL = """
CREATE TABLE IF NOT EXISTS analytics.sandbox_run (
    run_id             VARCHAR PRIMARY KEY,
    dataset_id         VARCHAR NOT NULL,
    use_case           VARCHAR NOT NULL,
    -- JSON: what the model service stated about the model this run called,
    -- each field with the endpoint that stated it. NULL only for a run that
    -- failed before the service could be asked.
    model_config       VARCHAR,
    -- sha256 over everything model_config was read from (/openapi.json's
    -- /predict request schema, /health's model fields, the full /metadata).
    -- The replay key: results are never served for a different model.
    model_config_hash  VARCHAR,
    -- FALSE when the service was unreachable and the configuration shown is
    -- the replayed run's, not one fetched for this run.
    model_checked      BOOLEAN NOT NULL DEFAULT TRUE,
    -- JSON: combinations sent to /predict, and those left out with the reason.
    input_summary      VARCHAR,
    -- Typed reason a run failed: MODEL_SERVICE_UNAVAILABLE, STORAGE_FAILED, ...
    error_code         VARCHAR,
    -- completed_with_warnings: every estimate stored, but part of the model's
    -- evaluation could not be fetched; sandbox_result.warnings says which.
    status             VARCHAR NOT NULL CHECK (
        status IN ('queued', 'running', 'completed', 'completed_with_warnings', 'failed')
    ),
    progress           INTEGER NOT NULL DEFAULT 0,
    message            VARCHAR NOT NULL,
    served_from_cache  BOOLEAN NOT NULL DEFAULT FALSE,
    -- Set only when served_from_cache: the earlier live run, with the same
    -- parameters, whose stored results this run replays. A replay never
    -- carries numbers that did not come from the model service.
    replayed_from      VARCHAR,
    created_at         TIMESTAMP NOT NULL,
    completed_at       TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analytics.sandbox_result (
    run_id                 VARCHAR PRIMARY KEY REFERENCES analytics.sandbox_run(run_id),
    pooled_metrics         VARCHAR NOT NULL,
    per_crop_metrics       VARCHAR NOT NULL,
    actual_vs_predicted    VARCHAR NOT NULL,
    feature_importance     VARCHAR NOT NULL,
    explanation            VARCHAR NOT NULL,
    -- JSON list of what could not be produced, and why. Empty for a clean run.
    warnings               VARCHAR NOT NULL DEFAULT '[]',
    created_at             TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics.sandbox_prediction (
    prediction_id               VARCHAR PRIMARY KEY,
    run_id                      VARCHAR NOT NULL REFERENCES analytics.sandbox_run(run_id),
    district_id                 VARCHAR NOT NULL,
    district_name               VARCHAR NOT NULL,
    crop_id                     VARCHAR NOT NULL,
    crop_name                   VARCHAR NOT NULL,
    season                      VARCHAR NOT NULL,
    -- The year of the dataset row the estimate was made for.
    agri_year                   VARCHAR NOT NULL,
    area_ha                     DOUBLE NOT NULL,
    predicted_yield_qtl_per_ha  DOUBLE NOT NULL,
    estimated_production_qtls   DOUBLE NOT NULL,
    output_label                VARCHAR NOT NULL DEFAULT 'Analytical Estimates',
    data_origin                 VARCHAR NOT NULL DEFAULT 'model'
);

CREATE TABLE IF NOT EXISTS analytics.sandbox_version (
    version_id         VARCHAR PRIMARY KEY,
    run_id             VARCHAR NOT NULL REFERENCES analytics.sandbox_run(run_id),
    label              VARCHAR NOT NULL,
    parameters         VARCHAR NOT NULL,
    published          BOOLEAN NOT NULL DEFAULT FALSE,
    created_at         TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics.published_forecast (
    forecast_id        VARCHAR PRIMARY KEY,
    version_id         VARCHAR NOT NULL REFERENCES analytics.sandbox_version(version_id),
    crop_id            VARCHAR NOT NULL,
    crop_name          VARCHAR NOT NULL,
    district_id        VARCHAR NOT NULL,
    district_name      VARCHAR NOT NULL,
    season             VARCHAR NOT NULL,
    agri_year          VARCHAR NOT NULL,
    actual_yield       DOUBLE,
    forecast_yield     DOUBLE NOT NULL,
    unit               VARCHAR NOT NULL DEFAULT 'qtl/ha',
    output_label       VARCHAR NOT NULL DEFAULT 'Analytical Estimates',
    data_origin        VARCHAR NOT NULL DEFAULT 'model',
    -- The model the estimate came from; see sandbox_run.model_config_hash.
    model_config_hash  VARCHAR,
    created_at         TIMESTAMP NOT NULL
);
"""

LLM_DDL = """
CREATE TABLE IF NOT EXISTS analytics.llm_call (
    call_id            VARCHAR PRIMARY KEY,
    created_at         TIMESTAMP NOT NULL,
    purpose            VARCHAR NOT NULL,
    model              VARCHAR,
    input_key          VARCHAR NOT NULL,
    system_prompt      VARCHAR NOT NULL,
    messages_json      VARCHAR NOT NULL,
    response_text      VARCHAR,
    served_from_cache  BOOLEAN NOT NULL,
    -- ok, unavailable (no answer to be had) or error (an answer, but unusable)
    outcome            VARCHAR NOT NULL,
    error              VARCHAR,
    latency_ms         INTEGER NOT NULL
);
"""

# Convenience views for the dashboard / narrative / assistant layers. Each one
# carries data_origin through so the UI can badge synthetic figures.
VIEW_DDL = """
CREATE OR REPLACE VIEW analytics.v_sandbox_prediction AS
SELECT
    p.prediction_id,
    p.run_id,
    p.district_id,
    coalesce(d.display_name, p.district_name) AS district_name,
    p.crop_id,
    coalesce(c.display_name, p.crop_name) AS crop_name,
    c.crop_group,
    p.season,
    p.agri_year,
    p.area_ha,
    p.predicted_yield_qtl_per_ha AS value,
    'qtl/ha' AS unit,
    p.predicted_yield_qtl_per_ha AS value_canonical,
    'qtl/ha' AS unit_canonical,
    p.estimated_production_qtls,
    p.output_label,
    p.data_origin,
    'published_district' AS grain_source,
    r.dataset_id AS dataset_version_id
FROM analytics.sandbox_prediction p
LEFT JOIN analytics.dim_district d ON d.district_id = p.district_id
LEFT JOIN analytics.dim_crop c ON c.crop_id = p.crop_id
LEFT JOIN analytics.sandbox_run r ON r.run_id = p.run_id
-- Only runs a published version points at. A run is a draft until someone
-- publishes it, and GET /dashboard/forecasts is gated the same way; without
-- this every run's estimates reached /query and exports the moment it ended.
WHERE p.run_id IN (
    SELECT run_id FROM analytics.sandbox_version WHERE published
);

-- District-grain crop AYP. 2022-23 paddy is published only block-wise, so block
-- rows are rolled up for any district/crop/season the publisher did not give at
-- district grain. grain_source says which happened.
CREATE OR REPLACE VIEW analytics.v_district_crop_ayp AS
WITH published AS (
    SELECT period_id, district_id, crop_id, product, measure, value, unit,
           value_canonical, unit_canonical, data_origin, value_status,
           dataset_version_id
    FROM analytics.fact_crop_ayp
    WHERE block_id IS NULL AND block_name_as_published IS NULL
),
block_rows AS (
    SELECT f.*
    FROM analytics.fact_crop_ayp f
    WHERE (f.block_id IS NOT NULL OR f.block_name_as_published IS NOT NULL)
      AND NOT EXISTS (
          SELECT 1 FROM published q
          WHERE q.period_id = f.period_id AND q.district_id = f.district_id
            AND q.crop_id = f.crop_id AND q.product = f.product
      )
),
-- Grouping by origin and version keeps both provenance columns exact rather
-- than picking one arbitrarily.
rolled_totals AS (
    SELECT period_id, district_id, crop_id, product, measure,
           data_origin, dataset_version_id,
           sum(value_canonical) AS value_canonical,
           max(unit_canonical) AS unit_canonical
    FROM block_rows
    WHERE measure IN ('area', 'production')
    GROUP BY ALL
),
rolled AS (
    SELECT period_id, district_id, crop_id, product, measure,
           value_canonical AS value, unit_canonical AS unit,
           value_canonical, unit_canonical, data_origin,
           'aggregated_from_blocks' AS value_status, dataset_version_id
    FROM rolled_totals
    UNION ALL
    -- Yield is derived from the summed totals; averaging block yields would
    -- weight every block equally regardless of area.
    SELECT a.period_id, a.district_id, a.crop_id, a.product, 'yield_rate',
           p.value_canonical / nullif(a.value_canonical, 0), 'qtl/ha',
           p.value_canonical / nullif(a.value_canonical, 0), 'qtl/ha',
           a.data_origin, 'aggregated_from_blocks', a.dataset_version_id
    FROM rolled_totals a
    JOIN rolled_totals p
      ON a.period_id = p.period_id AND a.district_id = p.district_id
     AND a.crop_id = p.crop_id AND a.product = p.product
     AND a.data_origin = p.data_origin AND a.dataset_version_id = p.dataset_version_id
    WHERE a.measure = 'area' AND p.measure = 'production'
),
combined AS (
    SELECT *, 'published_district' AS grain_source FROM published
    UNION ALL
    SELECT *, 'aggregated_from_blocks' AS grain_source FROM rolled
)
SELECT
    f.period_id, p.agri_year, p.season, p.period_type,
    f.district_id, d.display_name AS district_name,
    f.crop_id, c.display_name AS crop_name, c.crop_group,
    f.product, f.measure, f.value, f.unit,
    f.value_canonical, f.unit_canonical,
    f.data_origin, f.value_status, f.grain_source, f.dataset_version_id
FROM combined f
JOIN analytics.dim_period p USING (period_id)
JOIN analytics.dim_district d USING (district_id)
JOIN analytics.dim_crop c USING (crop_id);

CREATE OR REPLACE VIEW analytics.v_price AS
SELECT
    f.period_id, p.agri_year, p.month_start, p.period_type,
    coalesce(strftime(p.month_start, '%Y-%m'), p.agri_year) AS month,
    f.district_id, d.display_name AS district_name,
    f.crop_id, c.display_name AS crop_name, c.crop_group,
    f.price_type, coalesce(pt.display_name, f.price_type) AS price_type_name,
    f.price_rs_per_quintal, f.unit,
    f.annual_level_basis, f.annual_level_rs_per_quintal,
    f.data_origin, f.value_status, f.dataset_version_id
FROM analytics.fact_price f
JOIN analytics.dim_period p USING (period_id)
JOIN analytics.dim_district d USING (district_id)
JOIN analytics.dim_crop c USING (crop_id)
LEFT JOIN analytics.dim_price_type pt USING (price_type);

-- Block-grain crop AYP, kept separate from the district view so the two can
-- never be summed together by accident.
CREATE OR REPLACE VIEW analytics.v_block_crop_ayp AS
SELECT
    f.period_id, p.agri_year, p.season, p.period_type,
    f.district_id, d.display_name AS district_name,
    f.block_id, coalesce(b.display_name, f.block_name_as_published) AS block_name,
    f.crop_id, c.display_name AS crop_name, c.crop_group,
    f.product, f.measure, f.value, f.unit,
    f.value_canonical, f.unit_canonical,
    f.data_origin, f.value_status, 'published_block' AS grain_source,
    f.dataset_version_id
FROM analytics.fact_crop_ayp f
JOIN analytics.dim_period p USING (period_id)
JOIN analytics.dim_district d USING (district_id)
JOIN analytics.dim_crop c USING (crop_id)
LEFT JOIN analytics.dim_block b ON b.block_id = f.block_id
WHERE f.block_id IS NOT NULL OR f.block_name_as_published IS NOT NULL;

CREATE OR REPLACE VIEW analytics.v_land_use AS
SELECT
    f.period_id, p.agri_year, p.period_type,
    f.district_id, d.display_name AS district_name,
    f.block_id, coalesce(b.display_name, f.block_name_as_published) AS block_name,
    f.land_use_category, f.measure, f.value, f.unit,
    f.value_canonical, f.unit_canonical,
    f.data_origin, f.value_status,
    CASE WHEN f.block_id IS NULL AND f.block_name_as_published IS NULL
         THEN 'published_district' ELSE 'published_block' END AS grain_source,
    f.dataset_version_id
FROM analytics.fact_land_use f
JOIN analytics.dim_period p USING (period_id)
JOIN analytics.dim_district d USING (district_id)
LEFT JOIN analytics.dim_block b ON b.block_id = f.block_id;

CREATE OR REPLACE VIEW analytics.v_validation_summary AS
SELECT
    v.dataset_version_id, dv.dataset_name, v.rule_code, v.severity,
    count(*) AS finding_count
FROM analytics.validation_finding v
LEFT JOIN analytics.dataset_version dv USING (dataset_version_id)
GROUP BY ALL;

CREATE OR REPLACE VIEW analytics.v_state_crop_ayp AS
SELECT
    f.period_id, p.agri_year, f.season, p.period_type,
    f.crop_id, c.display_name AS crop_name, c.crop_group,
    f.product, f.measure, f.value, f.unit,
    f.value_canonical, f.unit_canonical,
    f.data_origin, f.value_status, 'published_state' AS grain_source,
    f.dataset_version_id
FROM analytics.fact_state_series f
JOIN analytics.dim_period p USING (period_id)
JOIN analytics.dim_crop c USING (crop_id);
"""


def connect(path: Optional[Path] = None, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open the OISS database, creating its parent directory if needed."""
    target = Path(path) if path is not None else DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(target), read_only=read_only)


def create_layers(con: duckdb.DuckDBPyConnection) -> None:
    for layer in LAYERS:
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {layer}")


def create_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create every layer and every canonical table. Safe to call repeatedly."""
    create_layers(con)
    for ddl in (
        DIMENSION_DDL, FACT_DDL, GOVERNANCE_DDL, SANDBOX_DDL, LLM_DDL, SCHEMA_META_DDL, VIEW_DDL
    ):
        con.execute(ddl)


def write_schema_version(con: duckdb.DuckDBPyConnection) -> None:
    """Record the version this build produced. Called by `app.cli build` only."""
    con.execute("DELETE FROM analytics.schema_meta")
    con.execute("INSERT INTO analytics.schema_meta (version) VALUES (?)", [SCHEMA_VERSION])


def schema_version(con: duckdb.DuckDBPyConnection) -> int:
    """The version a database was built at; 1 for one built before versioning."""
    exists = con.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = 'analytics' AND table_name = 'schema_meta'"
    ).fetchone()[0]
    if not exists:
        return 1
    row = con.execute("SELECT max(version) FROM analytics.schema_meta").fetchone()
    return int(row[0]) if row and row[0] is not None else 1


def check_schema_version(con: duckdb.DuckDBPyConnection, expected: Optional[int] = None) -> int:
    """Raise :class:`SchemaMismatch` unless the database matches this code."""
    wanted = SCHEMA_VERSION if expected is None else expected
    found = schema_version(con)
    if found != wanted:
        raise SchemaMismatch(found, wanted)
    return found


def reset_database(path: Optional[Path] = None) -> Path:
    """Delete the database file so a build starts from scratch.

    A rebuild must be reproducible, and DuckDB keeps no history, so the cheapest
    honest reset is to remove the file.
    """
    target = Path(path) if path is not None else DB_PATH
    target.unlink(missing_ok=True)
    Path(f"{target}.wal").unlink(missing_ok=True)
    return target
