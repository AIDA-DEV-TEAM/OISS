"""The section 6 reconciliation checks, asserted against a freshly built database.

Each check is also asserted directly here rather than only through the build
summary, so a failure names the reconciliation that broke.
"""
from __future__ import annotations

import pytest

from app.ingest import checks


def test_build_succeeds_and_every_check_passes(summary: dict) -> None:
    failed = [check for check in summary["checks"] if not check["passed"]]
    assert failed == [], f"failing checks: {failed}"
    assert summary["status"] == "succeeded"


@pytest.mark.parametrize(
    "table, expected",
    sorted(checks.EXPECTED_RAW_ROWS.items()),
)
def test_raw_row_counts(con, table: str, expected: int) -> None:
    assert con.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == expected


def test_price_extract_grain(con) -> None:
    result = checks.check_price_grain(con)
    assert result.passed, result.message


def test_2024_25_district_sums_equal_state_row(con) -> None:
    result = checks.check_district_sums_match_state(con)
    assert result.passed, result.message


def test_2024_25_seasons_add_to_total(con) -> None:
    result = checks.check_season_additivity(con)
    assert result.passed, result.message


def test_land_use_identities(con) -> None:
    for result in checks.check_land_use_identities(con):
        assert result.passed, result.message


def test_state_series_coverage(con) -> None:
    result = checks.check_state_series_coverage(con)
    assert result.passed, result.message


def test_earas_2022_23_paddy_state_total(con) -> None:
    result = checks.check_paddy_2022_23(con)
    assert result.passed, result.message
    assert "40.64 lakh ha, 180.80 lakh MT" in result.observed


def test_earas_2023_24_paddy_and_rice(con) -> None:
    results = checks.check_paddy_2023_24(con)
    for result in results:
        assert result.passed, result.message
    assert "40.87 lakh ha, 174.83 lakh MT" in results[0].observed
    assert "115.39 lakh MT" in results[2].observed
    assert "174.83 lakh MT" in results[3].observed


def test_synthetic_prices_reconcile_to_their_annual_levels(con) -> None:
    for result in checks.check_synthetic_prices(con):
        assert result.passed, result.message


def test_no_unknown_districts_on_bundled_data(con) -> None:
    result = checks.check_no_unknown_districts(con)
    assert result.passed, result.message


def test_every_district_grain_source_covers_all_30_districts(con) -> None:
    result = checks.check_all_districts_present(con)
    assert result.passed, result.message


def test_every_fact_row_has_origin_and_resolvable_version(con) -> None:
    for result in checks.check_provenance(con):
        assert result.passed, result.message


def test_nothing_from_the_bundled_sources_is_quarantined(con) -> None:
    tables = con.execute(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'quarantine'
        """
    ).fetchall()
    assert tables, "expected a quarantine table per source"
    for (table,) in tables:
        count = con.execute(f"SELECT count(*) FROM quarantine.{table}").fetchone()[0]
        assert count == 0, f"quarantine.{table} holds {count} rows"


def test_state_totals_never_reach_district_facts(con) -> None:
    for table in ("fact_crop_ayp", "fact_land_use", "fact_price"):
        leaked = con.execute(
            f"SELECT count(*) FROM analytics.{table} WHERE district_id = 'OD00'"
        ).fetchone()[0]
        assert leaked == 0, f"{table} contains state-total rows"


def test_data_origin_is_never_null_and_covers_both_kinds(con) -> None:
    origins = con.execute(
        "SELECT DISTINCT data_origin FROM analytics.fact_price ORDER BY 1"
    ).fetchall()
    assert [row[0] for row in origins] == ["official", "synthetic"]


def test_dimensions_have_the_expected_grain(con) -> None:
    counts = {
        "dim_district": 30,
        "dim_crop": 23,
        # 314 coded blocks plus one urban pseudo-block per district
        "dim_block": 344,
    }
    for table, expected in counts.items():
        assert (
            con.execute(f"SELECT count(*) FROM analytics.{table}").fetchone()[0]
            == expected
        )


def test_block_codes_are_unique_and_cover_one_to_314(con) -> None:
    low, high, distinct = con.execute(
        """
        SELECT min(block_code), max(block_code), count(DISTINCT block_code)
        FROM analytics.dim_block WHERE block_code IS NOT NULL
        """
    ).fetchone()
    assert (low, high, distinct) == (1, 314, 314)


def test_unmatched_paddy_blocks_are_flagged_not_dropped(con) -> None:
    """The brief requires unmatched blocks to survive as a finding."""
    flagged = con.execute(
        "SELECT count(*) FROM analytics.validation_finding WHERE rule_code = 'UNKNOWN_BLOCK'"
    ).fetchone()[0]
    assert flagged > 0
    kept = con.execute(
        """
        SELECT count(*) FROM analytics.fact_crop_ayp
        WHERE block_id IS NULL AND block_name_as_published IS NOT NULL
        """
    ).fetchone()[0]
    assert kept == flagged * 3, "each unmatched block row must keep its three measures"


def test_district_view_covers_every_year_without_double_counting(con) -> None:
    """2022-23 paddy is block-only, so the view rolls it up to district grain."""
    coverage = con.execute(
        """
        SELECT agri_year, product, grain_source
        FROM analytics.v_district_crop_ayp
        WHERE product = 'paddy' GROUP BY ALL ORDER BY 1
        """
    ).fetchall()
    assert coverage == [
        ("2022-23", "paddy", "aggregated_from_blocks"),
        ("2023-24", "paddy", "published_district"),
        ("2024-25", "paddy", "published_district"),
    ]

    def state_total(year: str, measure: str, divisor: float) -> float:
        value = con.execute(
            """
            SELECT sum(value_canonical) FROM analytics.v_district_crop_ayp
            WHERE agri_year = ? AND product = 'paddy' AND measure = ?
            """,
            [year, measure],
        ).fetchone()[0]
        return round(value / divisor, 2)

    # Rolled-up blocks must reproduce the published state totals exactly.
    assert state_total("2022-23", "area", 1e5) == 40.64
    assert state_total("2022-23", "production", 1e6) == 180.80
    # The year published at both grains must not be counted twice.
    assert state_total("2023-24", "area", 1e5) == 40.87


def test_view_never_loses_data_origin(con) -> None:
    for view in ("v_district_crop_ayp", "v_price"):
        nulls = con.execute(
            f"SELECT count(*) FROM analytics.{view} WHERE data_origin IS NULL"
        ).fetchone()[0]
        assert nulls == 0, f"{view} has rows with no data_origin"


def test_2023_24_paddy_is_never_double_counted(con) -> None:
    """DE&S publishes 2023-24 paddy at block and district grain; only one counts.

    Pinned by both row count and state total so a future change to the rollup
    cannot silently double the figures.
    """
    rows, districts, sources = con.execute(
        """
        SELECT count(*), count(DISTINCT district_id), count(DISTINCT grain_source)
        FROM analytics.v_district_crop_ayp
        WHERE agri_year = '2023-24' AND product = 'paddy'
        """
    ).fetchone()
    # 30 districts x 3 seasons x 3 measures, published at district grain only.
    assert (rows, districts, sources) == (270, 30, 1)

    area, production = con.execute(
        """
        SELECT
            sum(value_canonical) FILTER (WHERE measure = 'area') / 1e5,
            sum(value_canonical) FILTER (WHERE measure = 'production') / 1e6
        FROM analytics.v_district_crop_ayp
        WHERE agri_year = '2023-24' AND product = 'paddy'
        """
    ).fetchone()
    assert round(area, 2) == 40.87
    assert round(production, 2) == 174.83


def test_the_rollup_is_recorded_in_lineage(con) -> None:
    """'Where did this number come from' must be answerable from lineage_edge."""
    edges = con.execute(
        """
        SELECT from_node, to_node, dataset_version_id
        FROM analytics.lineage_edge WHERE edge_type = 'aggregate'
        """
    ).fetchall()
    assert edges, "the block-to-district rollup has no lineage edge"
    for from_node, to_node, version_id in edges:
        assert from_node == "analytics.fact_crop_ayp[block]"
        assert to_node == "analytics.v_district_crop_ayp"
        resolves = con.execute(
            "SELECT count(*) FROM analytics.dataset_version WHERE dataset_version_id = ?",
            [version_id],
        ).fetchone()[0]
        assert resolves == 1


def test_onion_is_a_vegetable_not_a_tuber(con) -> None:
    groups = dict(
        con.execute(
            "SELECT display_name, crop_group FROM analytics.dim_crop "
            "WHERE display_name IN ('Onion', 'Potato')"
        ).fetchall()
    )
    assert groups == {"Onion": "vegetable", "Potato": "tuber"}


def test_missing_values_are_split_from_structurally_absent_series(con) -> None:
    """Nulls where the crop is simply not grown must not read as data-quality warnings."""
    counts = dict(
        con.execute(
            """
            SELECT rule_code, finding_count FROM analytics.finding_summary
            WHERE rule_code IN ('MISSING_VALUE', 'STRUCTURALLY_ABSENT')
            """
        ).fetchall()
    )
    assert set(counts) == {"MISSING_VALUE", "STRUCTURALLY_ABSENT"}
    # The split only earns its keep if most nulls really are absent series.
    assert counts["STRUCTURALLY_ABSENT"] > counts["MISSING_VALUE"]

    severities = dict(
        con.execute(
            "SELECT rule_code, severity FROM analytics.finding_summary "
            "WHERE rule_code IN ('MISSING_VALUE', 'STRUCTURALLY_ABSENT')"
        ).fetchall()
    )
    assert severities == {"MISSING_VALUE": "warning", "STRUCTURALLY_ABSENT": "info"}


def test_every_finding_summary_row_carries_a_usable_sample(con) -> None:
    rows = con.execute(
        "SELECT rule_code, sample_row_ref FROM analytics.finding_summary"
    ).fetchall()
    assert rows
    for rule_code, sample in rows:
        assert sample, f"{rule_code} has no sample row reference"
        # A bare 'row=12' cannot be looked up; the sample must name the series.
        assert "|" in sample, f"{rule_code} sample lacks row context: {sample}"
