"""Semantic layer: correctness against published figures, and the rules.

Correctness here means agreeing with what DE&S printed, not agreeing with
itself. Each figure asserted below traces to a published report.
"""
from __future__ import annotations

import pytest

from app.semantic import service
from app.semantic.registry import METRICS_BY_ID, relation_for
from app.semantic.spec import QuerySpec, SpecError, validate_spec

PADDY, WHEAT = "CR17", "CR23"
BARGARH, BALANGIR, JAGATSINGHPUR = "OD04", "OD02", "OD12"


def spec(**kwargs) -> QuerySpec:
    return QuerySpec.model_validate(kwargs)


def run(con, **kwargs) -> dict:
    return service.run_query(con, spec(**kwargs))


# --------------------------------------------------------------------------
# Correctness against the published reports
# --------------------------------------------------------------------------
def test_paddy_production_2023_24_matches_the_published_state_total(con) -> None:
    result = run(
        con,
        metric="production",
        filters=[
            {"dimension": "crop", "op": "in", "values": [PADDY]},
            {"dimension": "product", "op": "eq", "values": ["paddy"]},
            {"dimension": "agri_year", "op": "eq", "values": ["2023-24"]},
        ],
    )
    lakh_mt = result["rows"][0]["value"] / 1e6
    assert round(lakh_mt, 2) == 174.83


def test_paddy_production_2023_24_unfiltered_defaults_to_paddy(con) -> None:
    """Without an explicit product filter, crop AYP metrics default to paddy, not paddy + rice."""
    result = run(
        con,
        metric="production",
        filters=[
            {"dimension": "crop", "op": "in", "values": [PADDY]},
            {"dimension": "agri_year", "op": "eq", "values": ["2023-24"]},
        ],
    )
    lakh_mt = result["rows"][0]["value"] / 1e6
    assert round(lakh_mt, 2) == 174.83


def test_paddy_production_2023_24_explicit_rice_is_reachable(con) -> None:
    """An explicit product=rice filter still reaches the rice terms."""
    result = run(
        con,
        metric="production",
        filters=[
            {"dimension": "crop", "op": "in", "values": [PADDY]},
            {"dimension": "product", "op": "eq", "values": ["rice"]},
            {"dimension": "agri_year", "op": "eq", "values": ["2023-24"]},
        ],
    )
    lakh_mt = result["rows"][0]["value"] / 1e6
    assert round(lakh_mt, 2) == 115.39


def test_long_run_state_series_covers_32_years(con) -> None:
    """Long-run state series queries analytics.v_state_crop_ayp for 1993-94..2024-25."""
    result = run(
        con,
        metric="production",
        dimensions=["agri_year"],
        filters=[
            {"dimension": "crop", "op": "in", "values": [PADDY]},
            {"dimension": "grain_source", "op": "eq", "values": ["published_state"]},
        ],
        period={"from": "1993-94", "to": "2024-25"},
        order_by={"field": "agri_year", "direction": "asc"},
        limit=50,
    )
    assert len(result["rows"]) == 32
    assert result["rows"][0]["agri_year"] == "1993-94"
    assert result["rows"][-1]["agri_year"] == "2024-25"
    assert result["applied_context"]["relation"] == "analytics.v_state_crop_ayp"
    # 2023-24 paddy state total in the series matches 174.83 lakh MT
    y2023 = [r for r in result["rows"] if r["agri_year"] == "2023-24"][0]
    assert round(y2023["value"] / 1e6, 2) == 174.83


def test_paddy_production_by_year_matches_every_published_total(con) -> None:
    result = run(
        con,
        metric="production",
        dimensions=["agri_year"],
        filters=[
            {"dimension": "crop", "op": "in", "values": [PADDY]},
            {"dimension": "product", "op": "eq", "values": ["paddy"]},
        ],
    )
    totals = {row["agri_year"]: round(row["value"] / 1e6, 2) for row in result["rows"]}
    assert totals == {"2022-23": 180.80, "2023-24": 174.83, "2024-25": 176.23}


def test_yield_rate_matches_the_published_district_table(con) -> None:
    """Bargarh, Winter paddy, 2024-25, straight off the district table."""
    published = con.execute(
        """
        SELECT value FROM analytics.v_district_crop_ayp
        WHERE district_id = ? AND crop_id = ? AND product = 'paddy'
          AND season = 'Winter' AND agri_year = '2024-25' AND measure = 'yield_rate'
        """,
        [BARGARH, PADDY],
    ).fetchone()[0]
    result = run(
        con,
        metric="yield_rate",
        dimensions=["district"],
        filters=[
            {"dimension": "crop", "op": "in", "values": [PADDY]},
            {"dimension": "product", "op": "eq", "values": ["paddy"]},
            {"dimension": "season", "op": "eq", "values": ["Winter"]},
            {"dimension": "agri_year", "op": "eq", "values": ["2024-25"]},
            {"dimension": "district", "op": "eq", "values": [BARGARH]},
        ],
    )
    assert round(result["rows"][0]["value"], 2) == round(published, 2)


def test_avg_price_matches_the_published_price_extract(con) -> None:
    published = con.execute(
        """
        SELECT price_rs_per_quintal FROM analytics.v_price
        WHERE district_id = ? AND crop_id = ? AND price_type = 'farm_harvest'
          AND agri_year = '2015-16' AND data_origin = 'official'
        """,
        [BALANGIR, PADDY],
    ).fetchone()[0]
    result = run(
        con,
        metric="avg_price",
        dimensions=["district"],
        filters=[
            {"dimension": "data_origin", "op": "eq", "values": ["official"]},
            {"dimension": "crop", "op": "in", "values": [PADDY]},
            {"dimension": "price_type", "op": "eq", "values": ["farm_harvest"]},
            {"dimension": "district", "op": "eq", "values": [BALANGIR]},
            {"dimension": "agri_year", "op": "eq", "values": ["2015-16"]},
        ],
    )
    assert result["rows"][0]["value"] == published
    assert result["rows"][0]["unit"] == "Rs/quintal"


def test_yield_rate_is_a_ratio_of_sums_not_a_mean_of_yields(con) -> None:
    """The two differ materially, and the metric must use the correct one."""
    ratio_of_sums, mean_of_yields = con.execute(
        """
        SELECT
            sum(value_canonical) FILTER (WHERE measure = 'production')
              / sum(value_canonical) FILTER (WHERE measure = 'area'),
            avg(value_canonical) FILTER (WHERE measure = 'yield_rate')
        FROM analytics.v_district_crop_ayp
        WHERE crop_id = ? AND product = 'paddy' AND agri_year = '2024-25'
          AND period_type = 'season'
        """,
        [PADDY],
    ).fetchone()
    assert abs(ratio_of_sums - mean_of_yields) > 1.0, "the case must discriminate"

    result = run(
        con,
        metric="yield_rate",
        filters=[
            {"dimension": "crop", "op": "in", "values": [PADDY]},
            {"dimension": "product", "op": "eq", "values": ["paddy"]},
            {"dimension": "agri_year", "op": "eq", "values": ["2024-25"]},
        ],
    )
    assert round(result["rows"][0]["value"], 3) == round(ratio_of_sums, 3)
    assert round(result["rows"][0]["value"], 3) != round(mean_of_yields, 3)


def test_the_total_season_row_is_never_double_counted(con) -> None:
    """The 2024-25 report prints seasons and a Total that repeats their sum."""
    result = run(
        con,
        metric="area",
        filters=[
            {"dimension": "crop", "op": "in", "values": [PADDY]},
            {"dimension": "product", "op": "eq", "values": ["paddy"]},
            {"dimension": "agri_year", "op": "eq", "values": ["2024-25"]},
        ],
    )
    published_total = con.execute(
        """
        SELECT sum(value_canonical) FROM analytics.v_district_crop_ayp
        WHERE crop_id = ? AND product = 'paddy' AND agri_year = '2024-25'
          AND measure = 'area' AND period_type = 'year'
        """,
        [PADDY],
    ).fetchone()[0]
    assert round(result["rows"][0]["value"]) == round(published_total)


# --------------------------------------------------------------------------
# Registry rules
# --------------------------------------------------------------------------
def test_avg_price_by_block_is_refused(con) -> None:
    with pytest.raises(SpecError) as raised:
        validate_spec(
            spec(
                metric="avg_price",
                dimensions=["block"],
                filters=[{"dimension": "data_origin", "op": "eq", "values": ["official"]}],
            ),
            service.known_values(con),
        )
    assert raised.value.code == "invalid_grain"
    assert raised.value.field == "dimensions"
    assert "block" not in raised.value.allowed_values


def test_yield_rate_by_block_is_allowed(con) -> None:
    """Block-grain paddy exists, so the same shape of question is answerable."""
    result = run(
        con,
        metric="yield_rate",
        dimensions=["block"],
        filters=[
            {"dimension": "crop", "op": "in", "values": [PADDY]},
            {"dimension": "agri_year", "op": "eq", "values": ["2023-24"]},
        ],
        limit=10,
    )
    assert result["rows"]
    assert result["applied_context"]["relation"] == "analytics.v_block_crop_ayp"


@pytest.mark.parametrize(
    "payload, code",
    [
        ({"metric": "no_such_metric"}, "unknown_metric"),
        ({"metric": "production", "dimensions": ["no_such_dimension"]}, "unknown_dimension"),
        (
            {"metric": "production", "filters": [{"dimension": "crop", "op": "in", "values": ["CR99"]}]},
            "unknown_filter_value",
        ),
        ({"metric": "price_yoy_pct", "dimensions": ["district"],
          "filters": [{"dimension": "data_origin", "op": "eq", "values": ["official"]}]},
         "missing_required_dimension"),
        ({"metric": "avg_price", "dimensions": ["district"]}, "unpinned_scope"),
        ({"metric": "fhp_wholesale_gap", "dimensions": ["price_type"],
          "filters": [{"dimension": "data_origin", "op": "eq", "values": ["official"]}]},
         "dimension_consumed_by_metric"),
    ],
)
def test_invalid_specs_name_the_field_and_the_allowed_values(
    con, payload: dict, code: str
) -> None:
    with pytest.raises(SpecError) as raised:
        validate_spec(spec(**payload), service.known_values(con))
    error = raised.value
    assert error.code == code
    assert error.field
    assert error.detail
    body = error.as_body()
    assert set(body) == {"detail", "code", "field", "allowed_values"}


def test_every_metric_declares_a_servable_relation() -> None:
    for metric in METRICS_BY_ID.values():
        assert metric.relations
        # Its own allowed dimensions must be servable by one of its relations.
        for dimension in metric.allowed_dimensions:
            relation_for(metric, {dimension})


# --------------------------------------------------------------------------
# Context and caveats
# --------------------------------------------------------------------------
def test_source_datasets_resolve_to_dataset_version_rows(con) -> None:
    result = run(
        con,
        metric="production",
        dimensions=["district"],
        filters=[{"dimension": "crop", "op": "in", "values": [PADDY]}],
    )
    sources = result["applied_context"]["source_datasets"]
    assert sources
    for source in sources:
        resolved = con.execute(
            "SELECT count(*) FROM analytics.dataset_version WHERE dataset_version_id = ?",
            [source["dataset_version_id"]],
        ).fetchone()[0]
        assert resolved == 1


def test_synthetic_price_query_flags_synthetic_and_projected(con) -> None:
    result = run(
        con,
        metric="avg_price",
        dimensions=["agri_year"],
        filters=[
            {"dimension": "data_origin", "op": "eq", "values": ["synthetic"]},
            {"dimension": "crop", "op": "in", "values": [PADDY]},
        ],
        period={"from": "2019-20", "to": "2024-25"},
    )
    codes = {caveat["code"] for caveat in result["caveats"]}
    assert {"SYNTHETIC_DATA", "PROJECTED_LEVELS"} <= codes
    assert result["applied_context"]["data_origin"]["synthetic"] > 0
    assert result["applied_context"]["data_origin"]["official"] == 0


def test_paddy_price_query_flags_msp(con) -> None:
    result = run(
        con,
        metric="avg_price",
        dimensions=["district"],
        filters=[
            {"dimension": "data_origin", "op": "eq", "values": ["official"]},
            {"dimension": "crop", "op": "in", "values": [PADDY]},
        ],
    )
    codes = {caveat["code"] for caveat in result["caveats"]}
    assert "MSP_SUBSTITUTED" in codes


def test_2022_23_paddy_flags_the_block_rollup(con) -> None:
    result = run(
        con,
        metric="yield_rate",
        dimensions=["district"],
        filters=[
            {"dimension": "crop", "op": "in", "values": [PADDY]},
            {"dimension": "product", "op": "eq", "values": ["paddy"]},
            {"dimension": "agri_year", "op": "eq", "values": ["2022-23"]},
        ],
    )
    codes = {caveat["code"] for caveat in result["caveats"]}
    assert "AGGREGATED_FROM_BLOCKS" in codes
    # grain_source must reach the rows, not just the view.
    assert all(row["grain_source"] == "aggregated_from_blocks" for row in result["rows"])
    assert result["applied_context"]["grain_source"]["aggregated_from_blocks"] == 30


def test_official_prices_beyond_2018_19_flag_a_period_gap(con) -> None:
    result = run(
        con,
        metric="avg_price",
        dimensions=["agri_year"],
        filters=[
            {"dimension": "data_origin", "op": "eq", "values": ["official"]},
            {"dimension": "crop", "op": "in", "values": [PADDY]},
        ],
        period={"from": "2013-14", "to": "2021-22"},
    )
    gaps = [c for c in result["caveats"] if c["code"] == "PERIOD_GAP"]
    assert gaps, "official prices stop at 2018-19"
    assert gaps[0]["affected_rows"] == 3  # 2019-20, 2020-21, 2021-22


def test_a_crop_never_priced_in_a_district_is_reported_as_absent(con) -> None:
    """Jagatsinghpur has no wheat price in any year; that is not a zero."""
    result = run(
        con,
        metric="avg_price",
        dimensions=["crop"],
        filters=[
            {"dimension": "data_origin", "op": "eq", "values": ["official"]},
            {"dimension": "district", "op": "eq", "values": [JAGATSINGHPUR]},
            {"dimension": "crop", "op": "in", "values": [WHEAT, PADDY]},
        ],
    )
    returned = {row["crop"] for row in result["rows"]}
    assert returned == {"Paddy"}
    codes = {caveat["code"] for caveat in result["caveats"]}
    assert "STRUCTURALLY_ABSENT" in codes


def test_official_crop_data_carries_no_synthetic_caveat(con) -> None:
    result = run(
        con,
        metric="area",
        dimensions=["district"],
        filters=[{"dimension": "crop", "op": "in", "values": [PADDY]}],
    )
    codes = {caveat["code"] for caveat in result["caveats"]}
    assert "SYNTHETIC_DATA" not in codes
    assert result["applied_context"]["data_origin"]["synthetic"] == 0


# --------------------------------------------------------------------------
# Drill-down and narrative facts
# --------------------------------------------------------------------------
def test_records_carry_their_source_file_and_version(con) -> None:
    result = service.run_records(
        con,
        spec(
            metric="production",
            dimensions=["district"],
            filters=[
                {"dimension": "crop", "op": "in", "values": [PADDY]},
                {"dimension": "agri_year", "op": "eq", "values": ["2022-23"]},
            ],
        ),
    )
    assert result["records"]
    for record in result["records"][:20]:
        assert record["dataset_version_id"]
        assert record["source_file"]
        assert record["data_origin"] in ("official", "synthetic")


def test_narrative_facts_supply_everything_a_narrative_would_assert(con) -> None:
    result = service.run_narrative_facts(
        con,
        spec(
            metric="yield_rate",
            dimensions=["district"],
            filters=[
                {"dimension": "crop", "op": "in", "values": [PADDY]},
                {"dimension": "product", "op": "eq", "values": ["paddy"]},
                {"dimension": "season", "op": "eq", "values": ["Winter"]},
            ],
            period={"from": "2022-23", "to": "2024-25"},
        ),
    )
    assert result["headline"]["value"] is not None
    assert result["headline"]["districts_covered"] == 30
    assert result["movement"]["from_period"] == "2023-24"
    assert result["movement"]["to_period"] == "2024-25"
    assert len(result["leaders"]) == 5
    assert len(result["laggards"]) == 5
    assert result["leaders"][0]["value"] >= result["laggards"][0]["value"]
    assert result["largest_changes"]
    assert result["applied_context"]["source_datasets"]
    assert {c["code"] for c in result["caveats"]} >= {"AGGREGATED_FROM_BLOCKS"}


def test_anomalies_are_reported_on_an_axis_that_can_support_them(con) -> None:
    """Three years cannot yield a 2-sigma outlier; 30 districts can."""
    result = service.run_narrative_facts(
        con,
        spec(
            metric="yield_rate",
            dimensions=["district"],
            filters=[
                {"dimension": "crop", "op": "in", "values": [PADDY]},
                {"dimension": "product", "op": "eq", "values": ["paddy"]},
                {"dimension": "season", "op": "eq", "values": ["Winter"]},
            ],
            period={"from": "2022-23", "to": "2024-25"},
        ),
    )
    anomalies = result["anomalies"]
    assert anomalies, "the cross-district axis should find outliers"
    assert all(a["axis"] == "cross_district" for a in anomalies)
    assert all(abs(a["standard_deviations"]) >= 2.0 for a in anomalies)


def test_headline_uses_ratio_of_sums_not_the_mean_of_district_yields(con) -> None:
    payload = dict(
        metric="yield_rate",
        dimensions=["district"],
        filters=[
            {"dimension": "crop", "op": "in", "values": [PADDY]},
            {"dimension": "product", "op": "eq", "values": ["paddy"]},
            {"dimension": "agri_year", "op": "eq", "values": ["2024-25"]},
        ],
    )
    facts = service.run_narrative_facts(con, spec(**payload))
    rows = service.run_query(con, spec(**payload))["rows"]
    mean_of_districts = sum(row["value"] for row in rows) / len(rows)
    assert abs(facts["headline"]["value"] - mean_of_districts) > 0.5


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------
def test_the_same_spec_returns_identical_rows_every_time(con) -> None:
    payload = dict(
        metric="yield_rate",
        dimensions=["district", "agri_year"],
        filters=[{"dimension": "crop", "op": "in", "values": [PADDY]}],
        order_by={"field": "value", "direction": "desc"},
        limit=50,
    )
    first = service.run_query(con, spec(**payload))
    second = service.run_query(con, spec(**payload))
    assert first["rows"] == second["rows"]
    assert first["caveats"] == second["caveats"]
    # Only the timestamp may differ between two runs of the same spec.
    assert {
        key: value for key, value in first["applied_context"].items()
        if key != "generated_at"
    } == {
        key: value for key, value in second["applied_context"].items()
        if key != "generated_at"
    }


def test_ties_are_broken_deterministically(con) -> None:
    """Equal values must not reorder between runs, or screenshots drift."""
    payload = dict(
        metric="area",
        dimensions=["district"],
        filters=[{"dimension": "crop", "op": "in", "values": [PADDY]}],
        order_by={"field": "value", "direction": "desc"},
        limit=30,
    )
    orders = [
        [row["district_id"] for row in service.run_query(con, spec(**payload))["rows"]]
        for _ in range(3)
    ]
    assert orders[0] == orders[1] == orders[2]
