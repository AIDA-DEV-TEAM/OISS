"""Reconciliation checks that must hold against the published DE&S reports.

These are known-true facts about the sources, so a mismatch is a load failure,
not a warning. Each check is independently callable and returns a
:class:`CheckResult`; :func:`run_all` runs the set the brief specifies.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import duckdb

from app.ingest.loaders import LAND_USE_NINE

LAKH = 100_000.0
QUINTALS_PER_LAKH_MT = 1_000_000.0  # 1 lakh MT = 10 lakh quintals = 1e6 qtl


@dataclass(frozen=True)
class CheckResult:
    check_code: str
    passed: bool
    expected: str
    observed: str
    message: str

    def as_dict(self) -> dict[str, object]:
        return {
            "check_code": self.check_code,
            "passed": self.passed,
            "expected": self.expected,
            "observed": self.observed,
            "message": self.message,
        }


def _result(code: str, expected: object, observed: object, ok: bool, note: str = "") -> CheckResult:
    return CheckResult(
        check_code=code,
        passed=bool(ok),
        expected=str(expected),
        observed=str(observed),
        message=note or ("ok" if ok else f"expected {expected}, observed {observed}"),
    )


def _scalar(con: duckdb.DuckDBPyConnection, sql: str, params: Optional[Sequence] = None):
    return con.execute(sql, list(params or [])).fetchone()[0]


# --------------------------------------------------------------------------
# Row-count checks
# --------------------------------------------------------------------------
EXPECTED_RAW_ROWS = {
    "raw.price_statistics_2020": 6_300,
    "raw.earas_2024_25_district_crop_ayp": 5_456,
    "raw.earas_2024_25_district_land_use": 682,
    "raw.earas_state_series": 5_632,
    "raw.synthetic_monthly_prices": 90_564,
}


def check_row_counts(con: duckdb.DuckDBPyConnection) -> list[CheckResult]:
    results = []
    for table, expected in EXPECTED_RAW_ROWS.items():
        observed = _scalar(con, f"SELECT count(*) FROM {table}")
        results.append(
            _result(f"ROWCOUNT_{table.split('.')[-1].upper()}", expected, observed, observed == expected)
        )
    return results


def check_price_grain(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """35 tables x 30 districts x 6 years."""
    tables, districts, years = con.execute(
        """
        SELECT count(DISTINCT table_no), count(DISTINCT district_as_published),
               count(DISTINCT year)
        FROM raw.price_statistics_2020
        """
    ).fetchone()
    resolved = _scalar(
        con, "SELECT count(DISTINCT district_id) FROM analytics.fact_price WHERE data_origin = 'official'"
    )
    ok = tables == 35 and years == 6 and resolved == 30
    return _result(
        "PRICE_GRAIN",
        "35 tables x 30 districts x 6 years",
        f"{tables} tables x {resolved} districts ({districts} published spellings) x {years} years",
        ok,
    )


# --------------------------------------------------------------------------
# 2024-25 district report
# --------------------------------------------------------------------------
def check_district_sums_match_state(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """District rows must add up to the printed STATE row for every crop/season."""
    frame = con.execute(
        """
        WITH d AS (
            SELECT crop_table, product, season, measure, sum(CAST(value AS DOUBLE)) AS district_sum
            FROM raw.earas_2024_25_district_crop_ayp
            WHERE is_state_total = '0' AND value IS NOT NULL
            GROUP BY ALL
        ), s AS (
            SELECT crop_table, product, season, measure, CAST(value AS DOUBLE) AS state_value
            FROM raw.earas_2024_25_district_crop_ayp
            WHERE is_state_total = '1' AND value IS NOT NULL
        )
        SELECT d.*, s.state_value
        FROM d JOIN s USING (crop_table, product, season, measure)
        WHERE measure IN ('area', 'production')
        """
    ).df()
    deviation = (frame.district_sum - frame.state_value).abs()
    tolerance = (frame.state_value.abs() * 0.005).clip(lower=0.05)
    bad = int((deviation > tolerance).sum())
    return _result(
        "AYP_2024_25_DISTRICT_SUMS_EQUAL_STATE",
        "0 mismatched crop/season/measure groups",
        f"{bad} of {len(frame)} mismatched",
        bad == 0,
    )


def check_season_additivity(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """Autumn + Winter + Summer must equal the printed Total."""
    frame = con.execute(
        """
        WITH v AS (
            SELECT crop_table, product, district_as_published, measure, season,
                   CAST(value AS DOUBLE) AS value
            FROM raw.earas_2024_25_district_crop_ayp
            WHERE measure IN ('area', 'production') AND value IS NOT NULL
        )
        SELECT crop_table, product, district_as_published, measure,
               sum(CASE WHEN season <> 'Total' THEN value ELSE 0 END) AS season_sum,
               sum(CASE WHEN season = 'Total' THEN value ELSE 0 END) AS total_value,
               count(*) FILTER (WHERE season = 'Total') AS has_total
        FROM v GROUP BY ALL
        """
    ).df()
    frame = frame[frame.has_total > 0]
    deviation = (frame.season_sum - frame.total_value).abs()
    tolerance = (frame.total_value.abs() * 0.02).clip(lower=0.05)
    bad = int((deviation > tolerance).sum())
    return _result(
        "AYP_2024_25_SEASON_ADDITIVITY",
        "0 rows where Autumn + Winter + Summer <> Total",
        f"{bad} of {len(frame)} rows differ",
        bad == 0,
    )


def check_land_use_identities(con: duckdb.DuckDBPyConnection) -> list[CheckResult]:
    """The nine categories sum to the surveyed area; surveyed + not = geographical."""
    frame = con.execute(
        """
        SELECT district_as_published, land_use_category, CAST(value AS DOUBLE) AS value
        FROM raw.earas_2024_25_district_land_use
        WHERE measure = 'area' AND value IS NOT NULL
        """
    ).df()
    wide = frame.pivot_table(
        index="district_as_published", columns="land_use_category", values="value", aggfunc="sum"
    )
    surveyed_gap = (wide[list(LAND_USE_NINE)].sum(axis=1) - wide["Total area under survey"]).abs().max()
    geo_gap = (
        wide["Total area under survey"]
        + wide["Area not included under survey"]
        - wide["Geographical area"]
    ).abs().max()
    return [
        _result(
            "LAND_USE_NINE_SUM_TO_SURVEYED",
            "max gap <= 0.05 ('000 ha)",
            f"{surveyed_gap:.4f}",
            surveyed_gap <= 0.05,
        ),
        _result(
            "LAND_USE_SURVEYED_PLUS_NOT_EQUALS_GEOGRAPHICAL",
            "max gap <= 0.05 ('000 ha)",
            f"{geo_gap:.4f}",
            geo_gap <= 0.05,
        ),
    ]


# --------------------------------------------------------------------------
# State series
# --------------------------------------------------------------------------
def check_state_series_coverage(con: duckdb.DuckDBPyConnection) -> CheckResult:
    rows, crops, first, last = con.execute(
        """
        SELECT count(*), count(DISTINCT crop_id), min(agri_year), max(agri_year)
        FROM analytics.fact_state_series f
        JOIN analytics.dim_period p USING (period_id)
        """
    ).fetchone()
    ok = rows == 5_632 and crops == 14 and first == "1993-94" and last == "2024-25"
    return _result(
        "STATE_SERIES_COVERAGE",
        "5632 rows, 14 crops, 1993-94..2024-25",
        f"{rows} rows, {crops} crops, {first}..{last}",
        ok,
    )


# --------------------------------------------------------------------------
# EARAS paddy state totals
# --------------------------------------------------------------------------
def _paddy_totals(con: duckdb.DuckDBPyConnection, dataset: str, product: str = "paddy"):
    """State-level area (lakh ha) and production (lakh MT) from a staging table."""
    area, production = con.execute(
        f"""
        SELECT
            sum(CASE WHEN measure = 'area' THEN value_canonical END),
            sum(CASE WHEN measure = 'production' THEN value_canonical END)
        FROM staging.{dataset}
        WHERE product = ? AND NOT is_state_total
        """,
        [product],
    ).fetchone()
    return (area or 0) / LAKH, (production or 0) / QUINTALS_PER_LAKH_MT


def check_paddy_2022_23(con: duckdb.DuckDBPyConnection) -> CheckResult:
    area, production = _paddy_totals(con, "earas_2022_23_block_paddy")
    ok = abs(area - 40.64) <= 0.01 and abs(production - 180.80) <= 0.01
    return _result(
        "EARAS_2022_23_PADDY_STATE_TOTAL",
        "40.64 lakh ha, 180.80 lakh MT",
        f"{area:.2f} lakh ha, {production:.2f} lakh MT",
        ok,
    )


def check_paddy_2023_24(con: duckdb.DuckDBPyConnection) -> list[CheckResult]:
    block_area, block_production = _paddy_totals(con, "earas_2023_24_block_paddy")
    dist_area, dist_production = _paddy_totals(con, "earas_2023_24_district_paddy")
    _, rice_production = _paddy_totals(con, "earas_2023_24_district_paddy", product="rice")
    from app.semantic import service as semantic_service
    from app.semantic.spec import QuerySpec
    unfiltered = semantic_service.run_query(
        con,
        QuerySpec(
            metric="production",
            filters=[
                {"dimension": "crop", "op": "in", "values": ["CR17"]},
                {"dimension": "agri_year", "op": "eq", "values": ["2023-24"]},
            ],
            limit=10,
        ),
    )
    unfiltered_val = (unfiltered["rows"][0]["value"] if unfiltered["rows"] else 0) / QUINTALS_PER_LAKH_MT
    return [
        _result(
            "EARAS_2023_24_PADDY_BLOCK_FILE",
            "40.87 lakh ha, 174.83 lakh MT",
            f"{block_area:.2f} lakh ha, {block_production:.2f} lakh MT",
            abs(block_area - 40.87) <= 0.01 and abs(block_production - 174.83) <= 0.01,
        ),
        _result(
            "EARAS_2023_24_PADDY_DISTRICT_FILE_AGREES",
            "40.87 lakh ha, 174.83 lakh MT",
            f"{dist_area:.2f} lakh ha, {dist_production:.2f} lakh MT",
            abs(dist_area - block_area) <= 0.01
            and abs(dist_production - block_production) <= 0.01,
        ),
        _result(
            "EARAS_2023_24_RICE_STATE_TOTAL",
            "115.39 lakh MT",
            f"{rice_production:.2f} lakh MT",
            abs(rice_production - 115.39) <= 0.01,
        ),
        _result(
            "EARAS_2023_24_UNFILTERED_PADDY_DEFAULTS_TO_PADDY",
            "174.83 lakh MT",
            f"{unfiltered_val:.2f} lakh MT",
            abs(unfiltered_val - 174.83) <= 0.01,
        ),
    ]


# --------------------------------------------------------------------------
# Synthetic prices
# --------------------------------------------------------------------------
def check_synthetic_prices(con: duckdb.DuckDBPyConnection) -> list[CheckResult]:
    rows = _scalar(
        con, "SELECT count(*) FROM analytics.fact_price WHERE data_origin = 'synthetic'"
    )
    worst = _scalar(
        con,
        """
        WITH s AS (
            SELECT district_id, crop_id, price_type, p.agri_year,
                   avg(f.price_rs_per_quintal) AS monthly_mean,
                   max(f.annual_level_rs_per_quintal) AS annual_level
            FROM analytics.fact_price f
            JOIN analytics.dim_period p USING (period_id)
            WHERE f.data_origin = 'synthetic'
            GROUP BY ALL
        )
        SELECT max(abs(monthly_mean - annual_level)) FROM s
        """,
    )
    return [
        _result("SYNTHETIC_PRICE_ROWCOUNT", 90_564, rows, rows == 90_564),
        _result(
            "SYNTHETIC_PRICE_MONTHLY_MEAN_EQUALS_ANNUAL",
            "max gap <= Rs 0.01",
            f"{worst:.4f}",
            worst is not None and worst <= 0.01,
        ),
    ]


# --------------------------------------------------------------------------
# Master-data and provenance guarantees
# --------------------------------------------------------------------------
def check_no_unknown_districts(con: duckdb.DuckDBPyConnection) -> CheckResult:
    count = _scalar(
        con,
        "SELECT count(*) FROM analytics.validation_finding WHERE rule_code = 'UNKNOWN_DISTRICT'",
    )
    return _result("ZERO_UNKNOWN_DISTRICTS", 0, count, count == 0)


def check_all_districts_present(con: duckdb.DuckDBPyConnection) -> CheckResult:
    """Every district-grain source must resolve all 30 districts."""
    gaps = con.execute(
        """
        SELECT dataset_version_id, count(DISTINCT district_id) AS n
        FROM analytics.fact_crop_ayp
        GROUP BY ALL HAVING n <> 30
        """
    ).fetchall()
    return _result(
        "ALL_30_DISTRICTS_IN_EVERY_SOURCE",
        "every district-grain dataset covers 30 districts",
        f"{len(gaps)} datasets short: {gaps}" if gaps else "30 districts everywhere",
        not gaps,
    )


def check_provenance(con: duckdb.DuckDBPyConnection) -> list[CheckResult]:
    """Every fact row must declare an origin and resolve to a dataset version."""
    results = []
    for table in ("fact_price", "fact_crop_ayp", "fact_land_use", "fact_state_series"):
        null_origin = _scalar(
            con, f"SELECT count(*) FROM analytics.{table} WHERE data_origin IS NULL"
        )
        orphans = _scalar(
            con,
            f"""
            SELECT count(*) FROM analytics.{table} f
            LEFT JOIN analytics.dataset_version v USING (dataset_version_id)
            WHERE v.dataset_version_id IS NULL
            """,
        )
        results.append(
            _result(
                f"PROVENANCE_{table.upper()}",
                "0 null data_origin, 0 unresolved dataset_version_id",
                f"{null_origin} null origins, {orphans} unresolved versions",
                null_origin == 0 and orphans == 0,
            )
        )
    return results


def run_all(con: duckdb.DuckDBPyConnection, results=None) -> list[CheckResult]:
    """Run every reconciliation check in the order the brief lists them."""
    out: list[CheckResult] = []
    out += check_row_counts(con)
    out.append(check_price_grain(con))
    out.append(check_district_sums_match_state(con))
    out.append(check_season_additivity(con))
    out += check_land_use_identities(con)
    out.append(check_state_series_coverage(con))
    out.append(check_paddy_2022_23(con))
    out += check_paddy_2023_24(con)
    out += check_synthetic_prices(con)
    out.append(check_no_unknown_districts(con))
    out.append(check_all_districts_present(con))
    out += check_provenance(con)
    return out
