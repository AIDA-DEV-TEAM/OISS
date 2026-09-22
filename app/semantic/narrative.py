"""Precomputed fact bundle for one dashboard view.

Pure SQL. The GenAI step is handed this and writes prose from it; it never does
arithmetic, never sees a raw table and never chooses what is notable. Everything
a narrative would want to assert -- totals, movement, who leads, who lags, what
moved most, what looks anomalous -- is computed here so it can be checked.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import duckdb

from app.semantic.compiler import compile_query
from app.semantic.spec import QuerySpec

# A series is called out when it sits this far from its own mean, measured in
# standard deviations of that series.
ANOMALY_SIGMA = 2.0
# With n points the largest possible standard score is (n-1)/sqrt(n); it only
# reaches 2.0 at n = 6, so smaller groups are skipped rather than reported on.
MIN_POINTS_FOR_SIGMA = 6
TOP_N = 5


@dataclass
class NarrativeFacts:
    headline: dict[str, object]
    movement: Optional[dict[str, object]]
    leaders: list[dict[str, object]]
    laggards: list[dict[str, object]]
    largest_changes: list[dict[str, object]]
    anomalies: list[dict[str, object]]


def _rows(con: duckdb.DuckDBPyConnection, spec: QuerySpec) -> list[dict]:
    compiled = compile_query(spec)
    frame = con.execute(compiled.sql, list(compiled.params)).df()
    return frame.to_dict("records")


def _spec(base: QuerySpec, **overrides) -> QuerySpec:
    data = base.model_dump(by_alias=True)
    data.update(overrides)
    return QuerySpec.model_validate(data)


def build(
    con: duckdb.DuckDBPyConnection, spec: QuerySpec, limit: int = TOP_N
) -> NarrativeFacts:
    """Compute the bundle for ``spec``, which must group by district.

    The caller's own spec decides metric, crop, season and period; this adds the
    aggregations a narrative needs around it.
    """
    by_district = _spec(
        spec, dimensions=["district"], order_by={"field": "value", "direction": "desc"},
        limit=5_000,
    )
    district_rows = _rows(con, by_district)

    statewide = _spec(spec, dimensions=[], order_by=None, limit=1)
    total_rows = _rows(con, statewide)

    headline: dict[str, object] = {
        "metric": spec.metric,
        "value": total_rows[0]["value"] if total_rows else None,
        "districts_covered": len(district_rows),
    }

    by_year = _spec(
        spec, dimensions=["agri_year"],
        order_by={"field": "agri_year", "direction": "asc"}, limit=200,
    )
    year_rows = _rows(con, by_year)
    movement = None
    if len(year_rows) >= 2:
        previous, current = year_rows[-2], year_rows[-1]
        change = current["value"] - previous["value"]
        movement = {
            "from_period": previous["agri_year"],
            "to_period": current["agri_year"],
            "from_value": previous["value"],
            "to_value": current["value"],
            "absolute_change": change,
            "percent_change": (
                change / previous["value"] * 100 if previous["value"] else None
            ),
        }

    ranked = [row for row in district_rows if row.get("value") is not None]
    leaders = [
        {"district": row["district"], "value": row["value"], "rank": index + 1}
        for index, row in enumerate(ranked[:limit])
    ]
    laggards = [
        {
            "district": row["district"],
            "value": row["value"],
            "rank": len(ranked) - index,
        }
        for index, row in enumerate(reversed(ranked[-limit:]))
    ]

    # One district x year pass feeds both the change ranking and the anomaly
    # scan; they used to run the same query twice.
    by_district_year = _spec(
        spec, dimensions=["district", "agri_year"], order_by=None, limit=5_000
    )
    district_year_rows = _rows(con, by_district_year)
    largest_changes = _largest_changes(district_year_rows, limit)
    anomalies = _anomalies(district_year_rows)

    return NarrativeFacts(
        headline=headline,
        movement=movement,
        leaders=leaders,
        laggards=laggards,
        largest_changes=largest_changes,
        anomalies=anomalies,
    )


def _largest_changes(rows: list[dict], limit: int) -> list[dict[str, object]]:
    """Districts that moved most between the last two years in the period."""
    years = sorted({row["agri_year"] for row in rows})
    if len(years) < 2:
        return []
    previous_year, current_year = years[-2], years[-1]
    previous = {
        row["district"]: row["value"] for row in rows if row["agri_year"] == previous_year
    }
    current = {
        row["district"]: row["value"] for row in rows if row["agri_year"] == current_year
    }
    changes = []
    for district, value in current.items():
        before = previous.get(district)
        if before is None or value is None or before == 0:
            continue
        changes.append(
            {
                "district": district,
                "from_period": previous_year,
                "to_period": current_year,
                "from_value": before,
                "to_value": value,
                "absolute_change": value - before,
                "percent_change": (value - before) / before * 100,
            }
        )
    changes.sort(key=lambda c: (-abs(c["percent_change"]), c["district"]))
    return changes[:limit]


def _z_scores(points: list[dict], value_key: str = "value") -> list[tuple[dict, float]]:
    """Standard scores within one group, or nothing if the group cannot support them."""
    values = [point[value_key] for point in points]
    if len(values) < MIN_POINTS_FOR_SIGMA:
        return []
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    deviation = variance**0.5
    if deviation == 0:
        return []
    return [(point, (point[value_key] - mean) / deviation) for point in points]


def _anomalies(district_year_rows: list[dict]) -> list[dict[str, object]]:
    """Figures more than two standard deviations from their comparison group.

    Two axes, because the data supports different ones at different widths:

    * ``cross_district`` -- a district against every other district that year.
    * ``time_series`` -- a district against its own history.

    A short series cannot produce a 2-sigma outlier at all: with n points the
    largest possible standard score is (n-1)/sqrt(n), which only passes 2.0 once
    n reaches 6. The crop data has three years, so the time-series axis stays
    silent there rather than reporting nothing meaningful, and the
    cross-district axis (30 districts) does the work.
    """
    rows = [row for row in district_year_rows if row.get("value") is not None]

    anomalies: list[dict[str, object]] = []

    by_year: dict[str, list[dict]] = {}
    by_district: dict[str, list[dict]] = {}
    for row in rows:
        by_year.setdefault(row["agri_year"], []).append(row)
        by_district.setdefault(row["district"], []).append(row)

    for year, points in by_year.items():
        group_mean = sum(p["value"] for p in points) / len(points)
        for point, sigma in _z_scores(points):
            if abs(sigma) >= ANOMALY_SIGMA:
                anomalies.append(
                    {
                        "axis": "cross_district",
                        "district": point["district"],
                        "agri_year": year,
                        "value": point["value"],
                        "comparison": f"all districts in {year}",
                        "comparison_mean": group_mean,
                        "standard_deviations": sigma,
                    }
                )

    for district, points in by_district.items():
        group_mean = sum(p["value"] for p in points) / len(points)
        for point, sigma in _z_scores(points):
            if abs(sigma) >= ANOMALY_SIGMA:
                anomalies.append(
                    {
                        "axis": "time_series",
                        "district": district,
                        "agri_year": point["agri_year"],
                        "value": point["value"],
                        "comparison": f"{district} across {len(points)} years",
                        "comparison_mean": group_mean,
                        "standard_deviations": sigma,
                    }
                )

    anomalies.sort(
        key=lambda a: (
            -abs(a["standard_deviations"]), a["axis"], a["district"], a["agri_year"]
        )
    )
    return anomalies
