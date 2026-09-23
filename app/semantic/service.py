"""Execution: validate a spec, run it, and return rows with their context.

Every response says what it was asked, what it read and what to be careful of.
The narrative step and the assistant get their provenance from here rather than
reconstructing it, which is what stops them inventing it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import duckdb

from app.exports import provenance
from app.ingest.loaders import build_presence_index
from app.semantic import caveats as caveat_rules
from app.semantic import narrative as narrative_facts
from app.semantic.compiler import compile_query
from app.semantic.registry import (
    DIMENSIONS,
    DIMENSIONS_BY_ID,
    METRICS,
    RELATIONS,
    Dimension,
)
from app.semantic.spec import QuerySpec, validate_spec

# Values are rounded only here, at the edge, never mid-computation.
VALUE_DECIMALS = 4
RECORD_LIMIT = 500


def metric_catalogue() -> list[dict[str, object]]:
    return [
        {
            "metric_id": metric.id,
            "label": metric.label,
            "unit": metric.unit,
            "definition": metric.definition,
            "allowed_dimensions": sorted(metric.allowed_dimensions),
            "required_dimensions": sorted(metric.required_dimensions),
            "forbidden_dimensions": sorted(metric.forbidden_dimensions),
            "requires_scope": sorted(metric.requires_scope),
            "default_aggregation": metric.default_aggregation,
            "facts": list(metric.facts),
        }
        for metric in METRICS
        if metric.id != "predicted_yield"
    ]


def dimension_catalogue() -> list[dict[str, object]]:
    return [
        {
            "dimension_id": dimension.id,
            "label": dimension.label,
            "description": dimension.description,
            "value_type": dimension.value_type,
            "is_coded": dimension.is_coded,
            "available_on": sorted(
                key for key, relation in RELATIONS.items()
                if dimension.id in relation.dimensions
            ),
        }
        for dimension in DIMENSIONS
        if dimension.id != "run_id"
    ]


def _relations_with(dimension: Dimension, include_predictions: bool = True) -> list[str]:
    return [
        relation.name
        for key, relation in RELATIONS.items()
        if dimension.id in relation.dimensions
        and (include_predictions or key != "sandbox_prediction")
    ]


def dimension_values(
    con: duckdb.DuckDBPyConnection, dimension_id: str, include_predictions: bool = True
) -> list[dict[str, str]]:
    """Selectable values for a dimension, for filter UIs and for the LLM.

    ``include_predictions=False`` leaves out values that exist only in
    published sandbox estimates, which the assistant does not offer.
    """
    dimension = DIMENSIONS_BY_ID[dimension_id]
    relations = _relations_with(dimension, include_predictions)
    if not relations:
        return []
    unions = " UNION ".join(
        f"SELECT DISTINCT {dimension.key_column} AS key, "
        f"{dimension.label_column} AS label FROM {relation}"
        for relation in relations
    )
    rows = con.execute(
        f"SELECT key, any_value(label) AS label FROM ({unions}) "
        "WHERE key IS NOT NULL GROUP BY key ORDER BY key"
    ).df()
    return [{"value": row["key"], "label": row["label"]} for row in rows.to_dict("records")]


# Validating a spec needs every selectable value, which means a DISTINCT scan of
# every relation for every dimension. Those values only change when the database
# is rebuilt, so they are cached against the load run that produced it.
_VALUE_CACHE: dict[str, dict[str, set[str]]] = {}


def _database_fingerprint(con: duckdb.DuckDBPyConnection) -> str:
    """File plus load run: two databases built from the same sources share a
    run id, so the path keeps their caches apart."""
    run = con.execute(
        "SELECT run_id FROM analytics.load_run ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    path = con.execute(
        "SELECT path FROM duckdb_databases() WHERE path IS NOT NULL LIMIT 1"
    ).fetchone()
    return f"{path[0] if path else 'memory'}::{run[0] if run else 'unbuilt'}"


def known_values(con: duckdb.DuckDBPyConnection) -> dict[str, set[str]]:
    """Every value a filter may name, per dimension."""
    fingerprint = _database_fingerprint(con)
    cached = _VALUE_CACHE.get(fingerprint)
    if cached is not None:
        return cached
    values: dict[str, set[str]] = {}
    for dimension in DIMENSIONS:
        if dimension.id == "run_id":
            continue
        values[dimension.id] = {
            row["value"] for row in dimension_values(con, dimension.id)
        }
    _VALUE_CACHE[fingerprint] = values
    return values


_LABEL_CACHE: dict[str, dict[str, dict[str, str]]] = {}


def value_labels(con: duckdb.DuckDBPyConnection, dimension_id: str) -> dict[str, str]:
    """Master label for every value of a dimension, keyed by the stored value.

    A filter reads `crop: CR17` in the spec and `Potato` in the master. A file
    that states only the code is unreadable, and one that states only the name
    cannot be traced back, so both travel together.
    """
    fingerprint = _database_fingerprint(con)
    cached = _LABEL_CACHE.setdefault(fingerprint, {})
    if dimension_id not in cached:
        cached[dimension_id] = {
            str(row["value"]): str(row["label"])
            for row in dimension_values(con, dimension_id)
            if row["value"] is not None
        }
    return cached[dimension_id]


def display_value(con: duckdb.DuckDBPyConnection, dimension_id: str, value: str) -> str:
    """`Potato (CR17)`, or just the value when the master adds nothing."""
    dimension = DIMENSIONS_BY_ID.get(dimension_id)
    if dimension is None:
        return str(value)
    labels = value_labels(con, dimension_id)
    label = labels.get(str(value))
    if label and label != str(value):
        return f"{label} ({value})"
    for code, lbl in labels.items():
        if lbl.lower() == str(value).lower() and code != lbl:
            return f"{lbl} ({code})"
    return str(value)


def describe_filters(
    con: duckdb.DuckDBPyConnection, filters: list[dict[str, object]]
) -> list[dict[str, object]]:
    """Filters with their dimension label and their values spelled out."""
    described: list[dict[str, object]] = []
    for item in filters:
        dimension_id = str(item.get("dimension", ""))
        dimension = DIMENSIONS_BY_ID.get(dimension_id)
        raw_vals = item.get("values")
        if raw_vals is None and "value" in item:
            raw_vals = [item["value"]]
        values = [str(v) for v in (raw_vals or [])]
        described.append(
            {
                **item,
                "dimension_label": dimension.label if dimension else dimension_id,
                "values_display": [display_value(con, dimension_id, v) for v in values],
            }
        )
    return described


# How each relation's coverage is described to a reader. Relation names stay
# inside the semantic layer; only these descriptions leave it.
_COVERAGE_LABELS = {
    "crop_ayp_district": "district grain",
    "crop_ayp_block": "block grain",
    "crop_ayp_state": "state grain (filter grain_source = published_state)",
    "land_use": "district and block grain",
}
_COVERAGE_CACHE: dict[str, dict[str, dict[str, str]]] = {}


def coverage(con: duckdb.DuckDBPyConnection) -> dict[str, dict[str, str]]:
    """The agricultural years each metric covers, per grain or per data origin.

    Lets a caller tell "not in the data" from "asked the wrong way": official
    prices stop at 2018-19, district crop figures start at 2022-23, and a
    question outside those years has no answer to find.
    """
    fingerprint = _database_fingerprint(con)
    if fingerprint in _COVERAGE_CACHE:
        return _COVERAGE_CACHE[fingerprint]

    def span(first: object, last: object) -> str:
        return f"{first} to {last}" if first and last else "no rows"

    by_relation: dict[str, dict[str, str]] = {}
    for key, relation in RELATIONS.items():
        if key == "sandbox_prediction":
            continue
        where = f" WHERE {relation.base_predicate}" if relation.base_predicate else ""
        if key == "price":
            found = con.execute(
                f"SELECT data_origin, min(agri_year), max(agri_year) FROM {relation.name}"
                f"{where} GROUP BY data_origin ORDER BY data_origin"
            ).fetchall()
            by_relation[key] = {
                f"data_origin = {origin}": span(first, last) for origin, first, last in found
            }
        else:
            first, last = con.execute(
                f"SELECT min(agri_year), max(agri_year) FROM {relation.name}{where}"
            ).fetchone()
            by_relation[key] = {_COVERAGE_LABELS[key]: span(first, last)}

    result = {
        metric.id: {
            label: years
            for relation_key in metric.relations
            for label, years in by_relation[relation_key].items()
        }
        for metric in METRICS
        if metric.id != "predicted_yield"
    }
    _COVERAGE_CACHE[fingerprint] = result
    return result


def _round(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, float):
        return round(value, VALUE_DECIMALS)
    return value


def source_datasets(
    con: duckdb.DuckDBPyConnection, version_ids: tuple[str, ...]
) -> list[dict[str, object]]:
    if not version_ids:
        return []
    placeholders = ", ".join("?" for _ in version_ids)
    rows = con.execute(
        f"""
        SELECT dataset_version_id, dataset_name, source_file, layer
        FROM analytics.dataset_version
        WHERE dataset_version_id IN ({placeholders})
        ORDER BY dataset_name
        """,
        list(version_ids),
    ).df()
    return rows.to_dict("records")


def run_query(
    con: duckdb.DuckDBPyConnection,
    spec: QuerySpec,
    presence: Optional[frozenset] = None,
    row_limit: Optional[int] = None,
) -> dict[str, object]:
    """Validate, execute and describe one query.

    ``row_limit`` overrides the spec's own limit. The spec's limit is a display
    limit -- how many rows a panel draws -- and an export of that panel wants
    every row, subject to its own ceiling. When it is given, the response also
    says how many rows the selection actually holds and whether the file was
    cut short, because a truncated file that does not say so is the worst of
    the three outcomes.
    """
    presence = presence if presence is not None else build_presence_index()
    validate_spec(spec, known_values(con))
    compiled = compile_query(spec)

    matching_row_count: Optional[int] = None
    if row_limit is None:
        frame = con.execute(compiled.sql, list(compiled.params)).df()
    else:
        matching_row_count = int(
            con.execute(
                f"SELECT COUNT(*) FROM ({compiled.sql_unlimited}) AS counted",
                list(compiled.params_unlimited),
            ).fetchone()[0]
        )
        frame = con.execute(
            f"{compiled.sql_unlimited} LIMIT ?",
            [*compiled.params_unlimited, row_limit],
        ).df()
    records = frame.to_dict("records")

    rows: list[dict[str, object]] = []
    grain_counts: dict[str, int] = {}
    for record in records:
        row: dict[str, object] = {}
        for dimension in compiled.dimensions:
            row[dimension.id] = record[dimension.id]
            if dimension.is_coded:
                row[f"{dimension.id}_id"] = record[f"{dimension.id}_key"]
        row["value"] = _round(record["value"])
        row["unit"] = compiled.value_unit
        if compiled.has_grain_source:
            aggregated = int(record.get("_aggregated_rows") or 0)
            total = int(record.get("_row_count") or 0)
            # grain_source travels with the row, not only inside the view, so a
            # narrative or an export can state the caveat per figure.
            label = (
                "aggregated_from_blocks"
                if aggregated and aggregated == total
                else "mixed"
                if aggregated
                else "published_district"
            )
            row["grain_source"] = label
            grain_counts[label] = grain_counts.get(label, 0) + 1
        rows.append(row)

    stats = caveat_rules.collect_scope(con, compiled)
    found = caveat_rules.build_caveats(con, spec, compiled, stats, presence)

    context = {
        "metric": spec.metric,
        "metric_label": compiled.metric.label,
        "unit": compiled.value_unit,
        "dimensions": list(spec.dimensions),
        "filters": describe_filters(con, [f.model_dump() for f in spec.filters]),
        "period": spec.period.model_dump(by_alias=True) if spec.period else None,
        "relation": compiled.relation.name,
        "source_datasets": source_datasets(con, stats.dataset_version_ids),
        "data_origin": {
            k: v for k, v in {
                "official": stats.official_rows,
                "synthetic": stats.synthetic_rows,
                "model": stats.model_rows,
            }.items()
            if v > 0 or k in ("official", "synthetic")
        },
        "grain_source": grain_counts,
        "row_count": len(rows),
        "underlying_row_count": stats.row_count,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if matching_row_count is not None:
        context["matching_row_count"] = matching_row_count
        context["truncated"] = len(rows) < matching_row_count
    # The panel-level disclosure wording, derived from the context's own
    # origin and grain fields. It travels with the result so a screen and an
    # exported file of the same selection cannot word it differently.
    context["provenance_notes"] = provenance.notes_from_context(context)

    response: dict[str, object] = {
        "rows": rows,
        "applied_context": context,
        "caveats": [caveat.as_dict() for caveat in found],
    }
    if spec.include_records:
        response["records"] = run_records(con, spec, presence)["records"]
    return response


def run_records(
    con: duckdb.DuckDBPyConnection,
    spec: QuerySpec,
    presence: Optional[frozenset] = None,
    limit: int = RECORD_LIMIT,
) -> dict[str, object]:
    """The underlying fact rows behind a result, for drill-down.

    Returns what was actually read, with the dataset version and source file
    each row came from, so a figure on screen can be traced to a published page.
    """
    presence = presence if presence is not None else build_presence_index()
    validate_spec(spec, known_values(con))
    compiled = compile_query(spec)

    available = {
        row[0] for row in con.execute(f"DESCRIBE {compiled.relation.name}").fetchall()
    }
    wanted = [
        "agri_year", "season", "month", "district_id", "district_name", "block_id",
        "block_name", "crop_id", "crop_name", "product", "price_type", "measure",
        "land_use_category", "value", "price_rs_per_quintal", "unit",
        "value_canonical", "unit_canonical", "data_origin", "value_status",
        "grain_source", "dataset_version_id",
    ]
    columns = [column for column in wanted if column in available]
    order = [
        column
        for column in ("agri_year", "district_id", "crop_id", "season", "measure")
        if column in available
    ]
    sql = (
        f"WITH base AS ({compiled.base_sql}) "
        f"SELECT {', '.join(columns)} FROM base"
        + (f" ORDER BY {', '.join(order)}" if order else "")
        + " LIMIT ?"
    )
    frame = con.execute(sql, [*compiled.base_params, limit]).df()
    records = frame.astype(object).where(frame.notna(), None).to_dict("records")

    stats = caveat_rules.collect_scope(con, compiled)
    files = {
        row["dataset_version_id"]: row["source_file"]
        for row in source_datasets(con, stats.dataset_version_ids)
    }
    for record in records:
        record["source_file"] = files.get(record.get("dataset_version_id"))

    return {
        "records": records,
        "returned": len(records),
        "total_matching": stats.row_count,
        "truncated": stats.row_count > len(records),
        "source_datasets": source_datasets(con, stats.dataset_version_ids),
    }


def run_narrative_facts(
    con: duckdb.DuckDBPyConnection, spec: QuerySpec, presence: Optional[frozenset] = None
) -> dict[str, object]:
    """One precomputed bundle for a dashboard view: the GenAI step does no maths."""
    presence = presence if presence is not None else build_presence_index()
    validate_spec(spec, known_values(con))
    compiled = compile_query(spec)

    facts = narrative_facts.build(con, spec)
    stats = caveat_rules.collect_scope(con, compiled)
    found = caveat_rules.build_caveats(con, spec, compiled, stats, presence)

    return {
        "headline": facts.headline,
        "movement": facts.movement,
        "leaders": facts.leaders,
        "laggards": facts.laggards,
        "largest_changes": facts.largest_changes,
        "anomalies": facts.anomalies,
        "applied_context": {
            "metric": spec.metric,
            "metric_label": compiled.metric.label,
            "unit": compiled.value_unit,
            "dimensions": list(spec.dimensions),
            "filters": [f.model_dump() for f in spec.filters],
            "period": spec.period.model_dump(by_alias=True) if spec.period else None,
            "relation": compiled.relation.name,
            "source_datasets": source_datasets(con, stats.dataset_version_ids),
            "data_origin": {
                "official": stats.official_rows,
                "synthetic": stats.synthetic_rows,
            },
            "row_count": len(facts.leaders) + len(facts.laggards),
            "underlying_row_count": stats.row_count,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "caveats": [caveat.as_dict() for caveat in found],
    }
