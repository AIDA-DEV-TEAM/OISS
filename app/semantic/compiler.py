"""Compile a validated query spec into parameterised SQL.

Nothing a caller sends ever reaches the SQL text. Relation and column names come
from the registry, which the spec was validated against; every value the caller
supplied travels as a bound parameter. That is what makes it safe to hand this
layer to an LLM later.

The shape is always the same::

    WITH base AS (filtered rows)
       , agg  AS (grouped numerator and denominator)
       [, denom AS (the share denominator, computed at its own scope)]
    SELECT dimensions, value FROM ... ORDER BY ... LIMIT ?

Rounding never happens here -- only at the response edge -- so that shares and
year-on-year changes are computed from full-precision values.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.semantic.registry import (
    DIMENSIONS_BY_ID,
    METRICS_BY_ID,
    Dimension,
    Metric,
    Relation,
    relation_for,
)
from app.semantic.spec import Filter, QuerySpec

# Columns every base row carries so context and caveats can be derived from the
# same filtered set the numbers came from.
PROVENANCE_COLUMNS = ("data_origin", "dataset_version_id", "value_status")


@dataclass
class CompiledQuery:
    sql: str
    params: list[object]
    base_sql: str
    base_params: list[object]
    metric: Metric
    relation: Relation
    dimensions: list[Dimension]
    value_unit: str
    has_grain_source: bool = False
    has_basis: bool = False
    extra_columns: list[str] = field(default_factory=list)
    # The same query with no LIMIT, so a caller that needs the true size of a
    # result can count it without taking the SQL apart by hand.
    sql_unlimited: str = ""
    params_unlimited: list[object] = field(default_factory=list)


def _quote(identifier: str) -> str:
    """Registry-supplied identifiers only; never a caller-supplied string."""
    if not identifier.replace("_", "").replace(".", "").isalnum():
        raise ValueError(f"refusing to build SQL with identifier {identifier!r}")
    return identifier


def _filter_sql(filters: list[Filter]) -> tuple[list[str], list[object]]:
    clauses: list[str] = []
    params: list[object] = []
    for filter_ in filters:
        column = _quote(DIMENSIONS_BY_ID[filter_.dimension].key_column)
        if filter_.op in ("in", "eq"):
            placeholders = ", ".join("?" for _ in filter_.values)
            clauses.append(f"{column} IN ({placeholders})")
            params.extend(filter_.values)
        elif filter_.op == "not_in":
            placeholders = ", ".join("?" for _ in filter_.values)
            clauses.append(f"({column} IS NULL OR {column} NOT IN ({placeholders}))")
            params.extend(filter_.values)
        elif filter_.op == "between":
            clauses.append(f"{column} BETWEEN ? AND ?")
            params.extend(filter_.values[:2])
        elif filter_.op == "gte":
            clauses.append(f"{column} >= ?")
            params.append(filter_.values[0])
        elif filter_.op == "lte":
            clauses.append(f"{column} <= ?")
            params.append(filter_.values[0])
        else:  # pragma: no cover - the spec model constrains op
            raise ValueError(f"unsupported operator {filter_.op!r}")
    return clauses, params


def _period_sql(spec: QuerySpec) -> tuple[list[str], list[object]]:
    clauses: list[str] = []
    params: list[object] = []
    if spec.period is None:
        return clauses, params
    if spec.period.from_year:
        clauses.append("agri_year >= ?")
        params.append(spec.period.from_year)
    if spec.period.to_year:
        clauses.append("agri_year <= ?")
        params.append(spec.period.to_year)
    return clauses, params


# --------------------------------------------------------------------------
# The three always-on guards
#
# Every fact query carries these whether or not the caller asked for them,
# because each one prevents the same class of error: counting the same harvest,
# the same season or the same file twice. They are applied together in
# build_base so there is one place to read.
#
# 1. relation.base_predicate  -- declared per relation in the registry.
#    The crop reports publish per-season rows *and* a Total row that repeats
#    their sum, so querying both doubles every figure.
#
# 2. product                  -- applied when the relation carries it.
#    DE&S publishes paddy twice, once in paddy terms and once in rice (milled)
#    terms, restating the same area. `product` is a unit of account, not an
#    additive partition, so summing across it double-counts. Absent an explicit
#    product filter or grouping, only paddy and minor crops are counted; rice
#    stays reachable by asking for it.
#
# 3. active version           -- applied when the relation carries it.
#    An uploaded file is promoted into the fact tables under its own
#    dataset_version_id. Two versions of one dataset would sum together, so a
#    query reads only the version marked active for each dataset.
# --------------------------------------------------------------------------
ACTIVE_VERSION_PREDICATE = (
    "dataset_version_id IN ("
    "SELECT dataset_version_id FROM analytics.dataset_version WHERE is_active"
    ")"
)


def build_base(
    spec: QuerySpec, relation: Relation, drop_dimension: Optional[str] = None
) -> tuple[str, list[object]]:
    """The filtered row set. ``drop_dimension`` omits one filter, for share denominators."""
    kept = [f for f in spec.filters if f.dimension != drop_dimension]
    clauses, params = _filter_sql(kept)
    period_clauses, period_params = _period_sql(spec)
    clauses += period_clauses
    params += period_params

    # Guard 1: declared per relation.
    if relation.base_predicate:
        clauses.insert(0, relation.base_predicate)

    # Guard 2: unit of account.
    if "product" in relation.dimensions:
        has_product_filter = any(f.dimension == "product" for f in kept)
        has_product_dimension = "product" in spec.dimensions
        if not has_product_filter and not has_product_dimension:
            clauses.append("(product = 'paddy' OR product = 'minor')")

    # Guard 3: one version per dataset.
    if relation.carries_version:
        clauses.append(ACTIVE_VERSION_PREDICATE)

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return f"SELECT * FROM {_quote(relation.name)}{where}", params


# --------------------------------------------------------------------------
# Metric expressions
# --------------------------------------------------------------------------
def _measure_sum(measure: str) -> str:
    return f"sum(value_canonical) FILTER (WHERE measure = '{measure}')"


# Numerator/denominator pairs evaluated inside the grouped CTE. A metric whose
# denominator is None is a plain aggregate.
AGGREGATES: dict[str, tuple[str, Optional[str]]] = {
    "avg_price": ("avg(price_rs_per_quintal)", None),
    "price_yoy_pct": ("avg(price_rs_per_quintal)", None),
    "fhp_wholesale_gap": (
        "avg(price_rs_per_quintal) FILTER (WHERE price_type = 'wholesale') "
        "- avg(price_rs_per_quintal) FILTER (WHERE price_type = 'farm_harvest')",
        None,
    ),
    "fhp_wholesale_gap_pct": (
        "avg(price_rs_per_quintal) FILTER (WHERE price_type = 'wholesale') "
        "- avg(price_rs_per_quintal) FILTER (WHERE price_type = 'farm_harvest')",
        "avg(price_rs_per_quintal) FILTER (WHERE price_type = 'farm_harvest')",
    ),
    "area": (_measure_sum("area"), None),
    "production": (_measure_sum("production"), None),
    # Ratio of sums, never a mean of published yield rates.
    "yield_rate": (_measure_sum("production"), _measure_sum("area")),
    "yield_yoy_pct": (_measure_sum("production"), _measure_sum("area")),
    "production_share_pct": (_measure_sum("production"), None),
    "cropping_area_share_pct": (_measure_sum("area"), None),
    "land_use_share_pct": (_measure_sum("area"), None),
    "predicted_yield": ("avg(value)", None),
}

# Share metrics: the dimension whose filter is dropped when computing the
# denominator, and the dimensions the denominator is grouped by.
SHARES: dict[str, dict[str, object]] = {
    "production_share_pct": {
        "drop": "district",
        "partition": ("crop", "season", "agri_year", "product", "crop_group"),
        "denominator": _measure_sum("production"),
    },
    "cropping_area_share_pct": {
        "drop": "crop",
        "partition": ("district", "season", "agri_year"),
        "denominator": _measure_sum("area"),
    },
    "land_use_share_pct": {
        "drop": "land_use_category",
        "partition": ("district", "block", "agri_year"),
        "denominator": (
            "sum(value_canonical) FILTER (WHERE measure = 'area' AND "
            "land_use_category = 'Total area under survey')"
        ),
    },
}

YOY_METRICS = {"price_yoy_pct", "yield_yoy_pct"}


def compile_query(spec: QuerySpec) -> CompiledQuery:
    """Turn a validated spec into SQL plus bound parameters."""
    metric = METRICS_BY_ID[spec.metric]
    requested = set(spec.dimensions) | {f.dimension for f in spec.filters}
    grain_source_filters = {
        v for f in spec.filters if f.dimension == "grain_source" for v in f.values
    }
    relation = relation_for(metric, requested, grain_source_filter=grain_source_filters)
    dimensions = [DIMENSIONS_BY_ID[d] for d in spec.dimensions]

    base_sql, base_params = build_base(spec, relation)
    numerator, denominator = AGGREGATES[metric.id]

    select_parts: list[str] = []
    group_parts: list[str] = []
    for dimension in dimensions:
        select_parts.append(f"{_quote(dimension.key_column)} AS {_quote(dimension.id)}_key")
        group_parts.append(_quote(dimension.key_column))
        if dimension.is_coded:
            select_parts.append(f"any_value({_quote(dimension.label_column)}) AS {_quote(dimension.id)}")
        else:
            select_parts.append(f"{_quote(dimension.key_column)} AS {_quote(dimension.id)}")

    agg_selects = list(select_parts)
    agg_selects.append(f"({numerator}) AS _numerator")
    if denominator is not None:
        agg_selects.append(f"({denominator}) AS _denominator")

    # Context carried alongside every grouped row, so the response can report
    # provenance without a second pass over the facts.
    agg_selects.append("count(*) AS _row_count")
    if "grain_source" in relation.dimensions:
        agg_selects.append(
            "count(*) FILTER (WHERE grain_source <> 'published_district') "
            "AS _aggregated_rows"
        )
    agg_selects.append(
        "count(*) FILTER (WHERE data_origin = 'synthetic') AS _synthetic_rows"
    )

    params: list[object] = list(base_params)
    parts = [f"base AS ({base_sql})"]
    group_clause = ", ".join(group_parts) if group_parts else ""
    parts.append(
        "agg AS (SELECT "
        + ", ".join(agg_selects)
        + " FROM base"
        + (f" GROUP BY {group_clause}" if group_clause else "")
        + ")"
    )

    share = SHARES.get(metric.id)
    if share is not None:
        denom_sql, denom_params = build_base(spec, relation, drop_dimension=share["drop"])
        partition = [
            DIMENSIONS_BY_ID[d]
            for d in share["partition"]
            if d in spec.dimensions and d != share["drop"]
        ]
        denom_group = [_quote(d.key_column) for d in partition]
        denom_selects = [f"{_quote(d.key_column)} AS {_quote(d.id)}_key" for d in partition]
        denom_selects.append(f"({share['denominator']}) AS _denominator")
        parts.append(f"denom_base AS ({denom_sql})")
        parts.append(
            "denom AS (SELECT "
            + ", ".join(denom_selects)
            + " FROM denom_base"
            + (f" GROUP BY {', '.join(denom_group)}" if denom_group else "")
            + ")"
        )
        params += denom_params
        join = (
            " ON " + " AND ".join(f"agg.{_quote(d.id)}_key = denom.{_quote(d.id)}_key" for d in partition)
            if partition
            else " ON TRUE"
        )
        value_expr = "agg._numerator / nullif(denom._denominator, 0) * 100"
        source = f"agg LEFT JOIN denom{join}"
    elif denominator is not None:
        value_expr = (
            "_numerator / nullif(_denominator, 0)"
            if metric.id not in ("fhp_wholesale_gap_pct",)
            else "_numerator / nullif(_denominator, 0) * 100"
        )
        source = "agg"
    else:
        value_expr = "_numerator"
        source = "agg"

    final_selects = [f"agg.{_quote(d.id)}_key AS {_quote(d.id)}_key" for d in dimensions]
    final_selects += [f"agg.{_quote(d.id)} AS {_quote(d.id)}" for d in dimensions]
    final_selects.append("agg._row_count AS _row_count")
    final_selects.append("agg._synthetic_rows AS _synthetic_rows")
    has_grain = "grain_source" in relation.dimensions
    if has_grain:
        final_selects.append("agg._aggregated_rows AS _aggregated_rows")

    if metric.id in YOY_METRICS:
        # Year on year needs the previous year's value for the same series, so
        # the partition is every dimension except the year itself.
        partition_columns = [
            f"agg.{_quote(d.id)}_key" for d in dimensions if d.id != "agri_year"
        ]
        partition_clause = (
            f"PARTITION BY {', '.join(partition_columns)} " if partition_columns else ""
        )
        final_selects.append(
            f"({value_expr}) AS _current, "
            f"lag({value_expr}) OVER ({partition_clause}ORDER BY agg.agri_year_key) AS _previous"
        )
        parts.append(f"final AS (SELECT {', '.join(final_selects)} FROM {source})")
        value_select = "(_current - _previous) / nullif(_previous, 0) * 100 AS value"
        outer_source = "final"
        outer_where = " WHERE _previous IS NOT NULL"
    else:
        final_selects.append(f"({value_expr}) AS value")
        parts.append(f"final AS (SELECT {', '.join(final_selects)} FROM {source})")
        value_select = "value"
        outer_source = "final"
        outer_where = " WHERE value IS NOT NULL"

    # Deterministic ordering: the requested sort, then every dimension key, so
    # repeated runs and screenshots match exactly.
    order_terms: list[str] = []
    if spec.order_by is not None:
        direction = "DESC" if spec.order_by.direction == "desc" else "ASC"
        if spec.order_by.field == "value":
            order_terms.append(f"value {direction} NULLS LAST")
        else:
            order_terms.append(f"{_quote(spec.order_by.field)}_key {direction}")
    order_terms += [f"{_quote(d.id)}_key ASC" for d in dimensions]
    order_clause = f" ORDER BY {', '.join(order_terms)}" if order_terms else ""

    projected = (
        [f"{_quote(d.id)}_key" for d in dimensions]
        + [_quote(d.id) for d in dimensions]
        + ["_row_count", "_synthetic_rows"]
        + (["_aggregated_rows"] if has_grain else [])
        + [value_select]
    )
    sql_unlimited = (
        "WITH "
        + ", ".join(parts)
        + f" SELECT {', '.join(projected)} FROM {outer_source}{outer_where}"
        + order_clause
    )
    sql = sql_unlimited + " LIMIT ?"
    params_unlimited = list(params)
    params.append(spec.limit)

    return CompiledQuery(
        sql=sql,
        sql_unlimited=sql_unlimited,
        params_unlimited=params_unlimited,
        params=params,
        base_sql=base_sql,
        base_params=base_params,
        metric=metric,
        relation=relation,
        dimensions=dimensions,
        value_unit=metric.unit,
        has_grain_source=has_grain,
        has_basis=relation.name == "analytics.v_price",
    )
