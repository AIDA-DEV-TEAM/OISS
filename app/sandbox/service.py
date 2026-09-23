"""Sandbox service managing runs, results, model versions, and published forecasts.

The model is pre-trained and served by a separate service. A run chooses what
the model is run over -- a dataset -- and nothing about the model itself: its
configuration is whatever the service states (see :mod:`app.sandbox.model_config`).
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

import duckdb
import pandas as pd

from app.sandbox import model_config
from app.sandbox.client import (
    ModelServiceClient,
    ModelServiceError,
    ModelServiceUnavailableError,
    model_to_crop_id,
    model_to_district_id,
    validate_input,
)
from app.semantic import service as semantic
from app.semantic.spec import QuerySpec

logger = logging.getLogger(__name__)

# The one use case: the service exposes one model with one target (GET /health),
# so there is nothing to choose, and the wizard shows it read-only.
USE_CASE = {
    "id": "minor_crop_yield",
    "label": "Minor-crop yield estimation",
    "description": (
        "Yield in quintals per hectare for a district, season, minor crop and sown "
        "area, from the model service's POST /predict."
    ),
}

NOT_STATED = "not stated by the model service"


class SandboxError(RuntimeError):
    """A sandbox request that cannot be served, with a client-safe reason."""

    def __init__(self, code: str, detail: str, status_code: int = 400) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code


class RunFailed(RuntimeError):
    """A run that cannot produce honest results; its message is shown as-is."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


_PROGRESS = (
    "UPDATE analytics.sandbox_run SET status = 'running', progress = ?, message = ? "
    "WHERE run_id = ?"
)


# --------------------------------------------------------------------------
# Model configuration and the use case, as the service states them
# --------------------------------------------------------------------------
def get_model_config(client: Optional[ModelServiceClient] = None) -> dict[str, Any]:
    """The service's current model configuration, or why it could not be read."""
    cli = client or ModelServiceClient()
    try:
        config, config_hash, _ = model_config.fetch(cli)
    except ModelServiceError as error:
        unavailable = isinstance(error, ModelServiceUnavailableError)
        return {
            "checked": False,
            "message": (
                "Current model could not be checked: service unavailable. " if unavailable
                else "Current model could not be checked: "
            ) + _reason(error),
            "config": None,
            "config_hash": None,
            "use_case": {**USE_CASE, "fixed_reason": _fixed_reason(None)},
        }
    finally:
        cli.close()
    return {
        "checked": True,
        "message": None,
        "config": config,
        "config_hash": config_hash,
        "use_case": {**USE_CASE, "fixed_reason": _fixed_reason(config)},
    }


def _fixed_reason(config: Optional[dict[str, Any]]) -> str:
    if config is None:
        return (
            "This system integrates one model service, which serves one model. The "
            "service could not be reached to confirm its model and target."
        )
    name = config["model_name"]["value"] or NOT_STATED
    target = config["target"]["value"] or NOT_STATED
    return (
        f"The model service exposes one model ({name}) with one target ({target}), "
        "both stated by GET /health, so there is nothing to choose."
    )


# --------------------------------------------------------------------------
# Datasets: what each can supply, checked against the model's own request
# --------------------------------------------------------------------------
# The model's POST /predict fields, as the columns of this system's data that
# supply them. The service names its fields; this is the one translation.
FIELD_COLUMNS = {
    "district": "district_id",
    "season": "season",
    "minor_crop": "crop_id",
    "area_ha": "area",
}

# Which of those columns each fact table carries, as SQL over its rows joined
# to dim_period, so a dataset is judged by what its rows actually hold.
# Land use has areas, but of land categories, not a crop's sown area.
_FACT_COLUMNS = {
    "fact_crop_ayp": {
        "district_id": "TRUE", "crop_id": "TRUE", "season": "count(p.season) > 0",
        "area": "count(*) FILTER (WHERE f.measure = 'area') > 0",
    },
    "fact_price": {
        "district_id": "TRUE", "crop_id": "TRUE", "season": "count(p.season) > 0",
        "area": "FALSE",
    },
    "fact_land_use": {
        "district_id": "TRUE", "crop_id": "FALSE", "season": "count(p.season) > 0",
        "area": "FALSE",
    },
    "fact_state_series": {
        "district_id": "FALSE", "crop_id": "TRUE", "season": "count(f.season) > 0",
        "area": "count(*) FILTER (WHERE f.measure = 'area') > 0",
    },
}

# Checked in this order; a combination is counted under the first it fails.
_DOMAIN_REASONS = {
    "UNKNOWN_DISTRICT": "district not in the model's districts (GET /metadata)",
    "UNKNOWN_CROP": "crop not in the model's minor_crops (GET /metadata)",
    "UNKNOWN_SEASON": "season not in the model's seasons (GET /metadata)",
    "AREA_OUT_OF_RANGE": "area outside the model's area_ha_range (GET /metadata)",
}


def _dataset_columns(con: duckdb.DuckDBPyConnection) -> dict[str, dict[str, Any]]:
    """Every active dataset with fact rows: its row count, years and columns."""
    found: dict[str, dict[str, Any]] = {}
    for table, columns in _FACT_COLUMNS.items():
        rows = con.execute(
            f"""
            SELECT f.dataset_version_id, count(*), min(p.agri_year), max(p.agri_year),
                   {columns['district_id']}, {columns['crop_id']},
                   {columns['season']}, {columns['area']}
            FROM analytics.{table} f
            JOIN analytics.dim_period p USING (period_id)
            JOIN analytics.dataset_version v USING (dataset_version_id)
            WHERE v.is_active
            GROUP BY f.dataset_version_id
            """
        ).fetchall()
        for dataset_id, count, first, last, *present in rows:
            found[dataset_id] = {
                "table": table,
                "row_count": int(count),
                "years": first if first == last else f"{first} to {last}",
                "columns": dict(zip(("district_id", "crop_id", "season", "area"), present)),
            }
    return found


def _required_fields(config: dict[str, Any]) -> list[str]:
    return [feature["name"] for feature in config["features"]["value"]]


def _missing_fields(columns: Mapping[str, bool], required: list[str]) -> list[dict[str, str]]:
    """The model's fields a dataset cannot supply, each with why."""
    missing = []
    for field in required:
        column = FIELD_COLUMNS.get(field)
        if column is None:
            missing.append({"field": field, "reason": "no column in this system maps to it"})
        elif not columns.get(column):
            missing.append({"field": field, "reason": f"the dataset has no {column} values"})
    return missing


def _candidate_rows(con: duckdb.DuckDBPyConnection, dataset_id: str) -> list[tuple]:
    """A dataset's sown district x crop x season combinations with their area.

    Block-grain datasets are summed to district grain, which is the grain the
    model takes. Rice is left out: it is the milled output of the same paddy
    land, and a dataset stating both would otherwise count the area twice.
    """
    return con.execute(
        """
        WITH area AS (
            SELECT f.district_id, f.crop_id, p.season, p.agri_year, f.value_canonical,
                   (f.block_id IS NULL AND f.block_name_as_published IS NULL) AS district_grain
            FROM analytics.fact_crop_ayp f
            JOIN analytics.dim_period p USING (period_id)
            WHERE f.dataset_version_id = ? AND f.measure = 'area'
              AND f.product IN ('paddy', 'minor') AND p.season IS NOT NULL
        ),
        grain AS (SELECT bool_or(district_grain) AS any_district FROM area)
        SELECT a.district_id, d.display_name, a.crop_id, c.display_name,
               a.season, a.agri_year, sum(a.value_canonical) AS area_ha
        FROM area a
        CROSS JOIN grain g
        JOIN analytics.dim_district d USING (district_id)
        JOIN analytics.dim_crop c USING (crop_id)
        -- A dataset with district rows is read at that grain; one without is
        -- summed from its blocks. Never both, which would double-count.
        WHERE a.district_grain = g.any_district
        GROUP BY ALL
        HAVING sum(a.value_canonical) > 0
        ORDER BY a.district_id, a.crop_id, a.season, a.agri_year
        """,
        [dataset_id],
    ).fetchall()


def _domain_check(
    rows: list[tuple], metadata: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Split combinations into those within the model's input domains and the rest.

    Out-of-domain combinations are counted by reason and never sent to /predict.
    """
    inputs: list[dict[str, Any]] = []
    out: dict[str, int] = {}
    for district_id, district_name, crop_id, crop_name, season, agri_year, area_ha in rows:
        try:
            model_district, model_crop, model_season, area = validate_input(
                district_id, crop_id, season, float(area_ha), metadata
            )
        except ModelServiceError as error:
            reason = _DOMAIN_REASONS.get(error.code, error.detail)
            out[reason] = out.get(reason, 0) + 1
            continue
        inputs.append({
            "district_id": district_id, "district_name": district_name,
            "crop_id": crop_id, "crop_name": crop_name, "season": season,
            "agri_year": agri_year, "area_ha": area,
            "model": (model_district, model_season, model_crop, area),
        })
    summary = {
        "agri_years": sorted({row[5] for row in rows}),
        "combinations": len(rows),
        "sent": len(inputs),
        "out_of_domain": [
            {"reason": reason, "count": count}
            for reason, count in sorted(out.items(), key=lambda item: -item[1])
        ],
        "rule": (
            "Each combination is counted once, under the first check it fails: "
            "district, crop, season, then area."
        ),
    }
    return inputs, summary


def list_datasets(
    con: duckdb.DuckDBPyConnection, client: Optional[ModelServiceClient] = None
) -> dict[str, Any]:
    """Every dataset, marked compatible or not with the model's request.

    Compatibility is read from the service itself: the fields its POST /predict
    requires, and the input domains in its /metadata. With the service down,
    neither is known, and the listing says so rather than guessing.
    """
    cli = client or ModelServiceClient()
    try:
        config, _, metadata = model_config.fetch(cli)
        message = None
    except ModelServiceError as error:
        config = metadata = None
        message = (
            "Compatibility could not be checked: the model service could not be read. "
            + _reason(error)
        )
    finally:
        cli.close()

    labels = dict(con.execute(
        "SELECT dataset_version_id, dataset_name FROM analytics.dataset_version"
    ).fetchall())
    items = []
    for dataset_id, info in sorted(_dataset_columns(con).items(), key=lambda kv: labels[kv[0]]):
        item: dict[str, Any] = {
            "dataset_id": dataset_id,
            "label": labels[dataset_id],
            "years": info["years"],
            "row_count": info["row_count"],
            "compatible": None,
            "missing_fields": [],
            "input_summary": None,
        }
        if config is not None:
            missing = _missing_fields(info["columns"], _required_fields(config))
            item["missing_fields"] = missing
            if not missing and info["table"] == "fact_crop_ayp":
                _, summary = _domain_check(_candidate_rows(con, dataset_id), metadata)
                item["input_summary"] = summary
                item["compatible"] = summary["sent"] > 0
            else:
                item["compatible"] = False
        items.append(item)
    return {
        "items": items, "total": len(items), "page": 1, "size": len(items),
        "model_checked": config is not None, "message": message,
    }


def _dataset_exists(con: duckdb.DuckDBPyConnection, dataset_id: str) -> bool:
    return con.execute(
        "SELECT count(*) FROM analytics.dataset_version WHERE dataset_version_id = ?",
        [dataset_id],
    ).fetchone()[0] > 0


def _run_inputs(
    con: duckdb.DuckDBPyConnection,
    dataset_id: str,
    config: dict[str, Any],
    metadata: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """What the run sends to /predict, or why the dataset cannot be run."""
    info = _dataset_columns(con).get(dataset_id)
    if info is None:
        raise RunFailed("DATASET_INCOMPATIBLE", f"dataset {dataset_id} has no active fact rows")
    missing = _missing_fields(info["columns"], _required_fields(config))
    if missing or info["table"] != "fact_crop_ayp":
        named = "; ".join(f"{m['field']}: {m['reason']}" for m in missing)
        raise RunFailed(
            "DATASET_INCOMPATIBLE",
            f"dataset {dataset_id} cannot supply the model's request fields ({named})",
        )
    inputs, summary = _domain_check(_candidate_rows(con, dataset_id), metadata)
    if not inputs:
        raise RunFailed(
            "NO_INPUTS_IN_DOMAIN",
            f"none of the dataset's {summary['combinations']} district, crop and season "
            "combinations fall within the model's input domains",
        )
    return inputs, summary


# --------------------------------------------------------------------------
# A run
# --------------------------------------------------------------------------
def create_run(
    con: duckdb.DuckDBPyConnection,
    payload: Mapping[str, Any],
    client: Optional[ModelServiceClient] = None,
) -> dict[str, Any]:
    """Run the model over a dataset's in-domain combinations, or fail honestly.

    The estimates are the run; the evaluation describes the model. So:

    * every /predict answers -> the estimates are stored first. If the
      held-out comparison or the feature importance then fails, the run still
      completes, as ``completed_with_warnings``, and says what is missing.
    * the service cannot be reached -> an earlier live run is replayed from
      DuckDB (matched on the model configuration when it could be read), or
      the run fails with nothing stored.
    * the service answers with an error, the dataset cannot be run, or storing
      fails -> the run fails with a typed ``error_code`` and a specific message.

    The request blocks until the run ends; there is no background job.
    """
    dataset_id = str(payload.get("dataset_id") or "")
    use_case = str(payload.get("use_case") or USE_CASE["id"])
    if use_case != USE_CASE["id"]:
        raise SandboxError("UNKNOWN_USE_CASE", f"Unknown use case {use_case!r}")
    if not _dataset_exists(con, dataset_id):
        raise SandboxError("DATASET_NOT_FOUND", f"Dataset {dataset_id!r} not found", 404)

    cli = client or ModelServiceClient()
    run_id = f"run-minor-yield-{uuid.uuid4().hex[:8]}"
    con.execute(
        """
        INSERT INTO analytics.sandbox_run (
            run_id, dataset_id, use_case, status, progress, message,
            served_from_cache, created_at
        ) VALUES (?, ?, ?, 'queued', 0, 'Run queued.', FALSE, ?)
        """,
        [run_id, dataset_id, use_case, datetime.now(timezone.utc)],
    )

    try:
        outcome = _execute(con, run_id, dataset_id, use_case, cli)
    finally:
        cli.close()
    if outcome is not None:
        _complete(con, run_id, *outcome)
    return {"run_id": run_id}


def _execute(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    dataset_id: str,
    use_case: str,
    cli: ModelServiceClient,
) -> Optional[tuple[int, dict[str, Any], dict[str, Any], list[str]]]:
    """Read the model's configuration, estimate, store the estimates, evaluate.

    Returns what is left to store, or None when the run has already ended:
    failed, or replayed from an earlier run.
    """
    try:
        config, config_hash, metadata = model_config.fetch(cli)
    except ModelServiceUnavailableError as error:
        # The current model cannot be read, so the replay cannot be matched
        # on it; it is matched on dataset and use case, and says so.
        _replay_or_fail(con, run_id, dataset_id, use_case, None, cli.base_url, _reason(error))
        return None
    except ModelServiceError as error:
        _fail(con, run_id, error.code, f"Run failed. {_reason(error)}")
        return None
    con.execute(
        "UPDATE analytics.sandbox_run SET model_config = ?, model_config_hash = ? "
        "WHERE run_id = ?",
        [json.dumps(config), config_hash, run_id],
    )

    try:
        inputs, summary = _run_inputs(con, dataset_id, config, metadata)
        con.execute(
            "UPDATE analytics.sandbox_run SET input_summary = ? WHERE run_id = ?",
            [json.dumps(summary), run_id],
        )
        predictions = _estimate(con, run_id, cli, inputs)
    except ModelServiceUnavailableError as error:
        # Nothing is written before every estimate is in, so losing the
        # service part-way through is the same as never reaching it.
        _replay_or_fail(
            con, run_id, dataset_id, use_case, config_hash, cli.base_url, _reason(error)
        )
        return None
    except (ModelServiceError, RunFailed) as error:
        _fail(con, run_id, error.code, f"Run failed. {_reason(error)}")
        return None

    # Stored before the evaluation is asked for, so an evaluation that fails,
    # or fails to store, never costs the estimates.
    try:
        _store_predictions(con, run_id, predictions)
    except duckdb.Error:
        logger.exception("storing the estimates of run %s failed", run_id)
        _fail(
            con, run_id, "STORAGE_FAILED",
            f"Run failed. The model service returned {len(predictions)} estimates, but "
            "storing them failed, so none was kept.",
        )
        return None

    evaluation, warnings = _evaluation(con, run_id, cli)
    return len(predictions), summary, evaluation, warnings


def _complete(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    estimates: int,
    summary: dict[str, Any],
    evaluation: dict[str, Any],
    warnings: list[str],
) -> None:
    """Store the evaluation and end the run, saying what it holds."""
    try:
        _store_evaluation(con, run_id, evaluation, warnings)
    except duckdb.Error:
        logger.exception("storing the evaluation of run %s failed", run_id)
        _fail(
            con, run_id, "STORAGE_FAILED",
            f"Run failed. The {estimates} estimates were stored, but storing the model's "
            "evaluation failed, so the run's results are incomplete and are not shown.",
        )
        return

    left_out = summary["combinations"] - summary["sent"]
    note = (
        f" {left_out} of the dataset's {summary['combinations']} combinations were outside "
        "the model's input domains and were not sent."
        if left_out else ""
    )
    message = f"{estimates} estimates from the model service.{note}"
    if warnings:
        _finish(
            con, run_id, "completed_with_warnings",
            f"Run complete with warnings: {message} {' '.join(warnings)}",
        )
    else:
        _finish(con, run_id, "completed", f"Run complete: {message}")


def _reason(error: Exception) -> str:
    """What went wrong, in the words the error carries."""
    detail = getattr(error, "detail", None) or str(error)
    return detail if detail.endswith(".") else f"{detail}."


def _estimate(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    cli: ModelServiceClient,
    inputs: list[dict[str, Any]],
) -> list[tuple]:
    """Every estimate the run needs. All must succeed, or none is kept."""
    con.execute(
        _PROGRESS, [46, f"Requesting {len(inputs)} estimates from the model service.", run_id]
    )
    return [_predict(cli, row) for row in inputs]


def _evaluation(
    con: duckdb.DuckDBPyConnection, run_id: str, cli: ModelServiceClient
) -> tuple[dict[str, Any], list[str]]:
    """The service's evaluation of its model. A part that fails is left empty
    and explained.

    Nothing here stands in for a missing figure: no held-out records means no
    metrics, shown as a dash, and a reason in the run's warnings. The
    explanation stays a string, empty when the service gave none.
    """
    warnings: list[str] = []
    evaluation: dict[str, Any] = {
        "pooled": None, "per_crop": [], "actual_vs_predicted": [],
        "feature_importance": [], "explanation": "",
    }

    con.execute(_PROGRESS, [78, "Evaluating held-out comparisons.", run_id])
    try:
        comparisons, total = _held_out(cli)
        pooled, per_crop, actual_vs_predicted = _evaluate(con, comparisons)
        evaluation.update(pooled=pooled, per_crop=per_crop, actual_vs_predicted=actual_vs_predicted)
        if total > len(comparisons):
            warnings.append(
                f"The model evaluation covers {len(comparisons)} of the service's "
                f"{total} held-out records."
            )
    except (ModelServiceError, RunFailed) as error:
        warnings.append(f"Model evaluation is unavailable: {_reason(error)}")

    con.execute(_PROGRESS, [94, "Ranking feature importance.", run_id])
    try:
        importance, explanation = _feature_importance(cli)
        evaluation.update(feature_importance=importance, explanation=explanation)
    except ModelServiceError as error:
        warnings.append(f"Feature importance is unavailable: {_reason(error)}")

    return evaluation, warnings


def _predict(cli: ModelServiceClient, row: dict[str, Any]) -> tuple:
    """One estimate from the service. A missing figure fails the run."""
    response = cli.predict(*row["model"])
    estimate = response.get("analytical_estimates") or response
    predicted = estimate.get("predicted_yield_qtl_per_ha")
    if predicted is None:
        raise ModelServiceError(
            "MALFORMED_RESPONSE",
            "the model service returned no predicted yield for "
            f"{row['district_name']} / {row['crop_name']} / {row['season']}",
        )
    predicted = float(predicted)
    production = estimate.get("estimated_production_qtls")
    # Production is area times yield by definition; derived only if the
    # service leaves it out, never assumed.
    production = float(production) if production is not None else row["area_ha"] * predicted
    return (
        row["district_id"], row["district_name"], row["crop_id"], row["crop_name"],
        row["season"], row["agri_year"], row["area_ha"], predicted, production,
    )


def _held_out(cli: ModelServiceClient) -> tuple[list[dict[str, Any]], int]:
    """The service's held-out test records, translated to master IDs, and how
    many it says it holds, so a partial set can be reported as partial."""
    response = cli.get_actual_vs_predicted()
    records = []
    for item in response.get("comparisons") or []:
        actual = item.get("Actual_Yield_qtl_per_ha")
        predicted = item.get("Predicted_Yield_qtl_per_ha")
        if actual is None or predicted is None:
            raise ModelServiceError(
                "MALFORMED_RESPONSE", "a held-out record is missing its actual or predicted yield"
            )
        records.append({
            "district_id": model_to_district_id(str(item.get("District", ""))),
            "crop_id": model_to_crop_id(str(item.get("Minor_Crop", ""))),
            "actual": float(actual),
            "predicted": float(predicted),
        })
    if not records:
        raise RunFailed(
            "NO_HELD_OUT_RECORDS",
            "the model service returned no held-out records to evaluate against",
        )
    total = response.get("total_samples")
    return records, int(total) if isinstance(total, (int, float)) else len(records)


def _feature_importance(cli: ModelServiceClient) -> tuple[list[dict[str, Any]], str]:
    """Ranked weights and prose, exactly as the service reports them."""
    response = cli.get_feature_importance()
    importance = [
        {
            "feature": str(item["Feature"]),
            "label": str(item["Feature"]).replace("_", " "),
            "weight": float(item["Importance"]),
        }
        for item in (response.get("top_features") or [])[:5]
        # A feature the service gives no weight is not given one here.
        if item.get("Feature") and item.get("Importance") is not None
    ]
    return importance, str(response.get("plain_language_explanation") or "")


_METRIC_SQL = """
    count(*) AS n,
    sqrt(avg(power(actual - predicted, 2))) AS rmse,
    avg(abs(actual - predicted)) AS mae,
    CASE WHEN count(*) > 1 AND var_pop(actual) > 0
         THEN 1 - avg(power(actual - predicted, 2)) / var_pop(actual) END AS r2
"""


def _metrics(n: int, rmse: float, mae: float, r2: Optional[float]) -> dict[str, Any]:
    return {
        "n": int(n),
        "rmse": round(rmse, 4),
        "mae": round(mae, 4),
        "r2": round(r2, 4) if r2 is not None else None,
    }


def _evaluate(
    con: duckdb.DuckDBPyConnection, comparisons: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Pooled and per-crop metrics, computed in SQL from the held-out records.

    R² is 1 - MSE / var_pop(actual). It is NULL for a crop with fewer than two
    records or no variance in its actuals, because there is nothing to explain.
    """
    view = f"held_out_{uuid.uuid4().hex[:8]}"
    con.register(view, pd.DataFrame(comparisons))
    try:
        pooled = con.execute(f"SELECT {_METRIC_SQL} FROM {view}").fetchone()
        per_crop = con.execute(
            f"""
            SELECT h.crop_id, coalesce(c.display_name, h.crop_id) AS crop_name, {_METRIC_SQL}
            FROM {view} h LEFT JOIN analytics.dim_crop c USING (crop_id)
            GROUP BY ALL ORDER BY n DESC, h.crop_id
            """
        ).fetchall()
        pairs = con.execute(
            f"""
            SELECT coalesce(d.display_name, h.district_id), coalesce(c.display_name, h.crop_id),
                   h.actual, h.predicted, h.actual - h.predicted
            FROM {view} h
            LEFT JOIN analytics.dim_district d USING (district_id)
            LEFT JOIN analytics.dim_crop c USING (crop_id)
            ORDER BY 2, 1
            """
        ).fetchall()
    finally:
        con.unregister(view)

    return (
        _metrics(*pooled),
        [
            {"crop_id": crop_id, "crop_name": name, **_metrics(*rest)}
            for crop_id, name, *rest in per_crop
        ],
        [
            {"district_name": d, "crop_name": c, "actual": a,
             "predicted": round(p, 4), "residual": round(r, 4)}
            for d, c, a, p, r in pairs
        ],
    )


def _store_predictions(
    con: duckdb.DuckDBPyConnection, run_id: str, predictions: list[tuple]
) -> None:
    """All the run's estimates, in one transaction: all are kept, or none."""
    con.execute("BEGIN TRANSACTION")
    try:
        for d_id, d_name, c_id, c_name, season, year, area_ha, y_rate, p_qtls in predictions:
            con.execute(
                """
                INSERT INTO analytics.sandbox_prediction (
                    prediction_id, run_id, district_id, district_name, crop_id, crop_name,
                    season, agri_year, area_ha, predicted_yield_qtl_per_ha,
                    estimated_production_qtls, output_label, data_origin
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Analytical Estimates', 'model')
                """,
                # Season and year are part of the key: a district sows one
                # crop in several seasons, and a key without them collides.
                [f"pred-{run_id}-{d_id}-{c_id}-{season}-{year}", run_id, d_id, d_name,
                 c_id, c_name, season, year, area_ha, y_rate, p_qtls],
            )
        con.execute("COMMIT")
    except duckdb.Error:
        con.execute("ROLLBACK")
        raise


def _store_evaluation(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    evaluation: dict[str, Any],
    warnings: list[str],
) -> None:
    con.execute(
        """
        INSERT INTO analytics.sandbox_result (
            run_id, pooled_metrics, per_crop_metrics, actual_vs_predicted,
            feature_importance, explanation, warnings, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            run_id,
            json.dumps(evaluation["pooled"]),
            json.dumps(evaluation["per_crop"]),
            json.dumps(evaluation["actual_vs_predicted"]),
            json.dumps(evaluation["feature_importance"]),
            evaluation["explanation"],
            json.dumps(warnings),
            datetime.now(timezone.utc),
        ],
    )


def _replay_or_fail(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    dataset_id: str,
    use_case: str,
    config_hash: Optional[str],
    base_url: str,
    reason: str,
) -> None:
    """Replay an earlier live run of the same model over the same dataset, or fail.

    "Served from cache" means exactly this and nothing else: results the model
    service really returned, stored by an earlier run, copied under this run.
    Only live runs are replay sources, so a replay is never a copy of a copy.

    With the current configuration known, only a run of the same model (same
    configuration hash) is replayed, so a retrained or changed model is never
    answered with an old model's results. With it unknown -- the service
    could not be read at all -- the match is on dataset and use case, and the
    run says the current model could not be checked.
    """
    checked = config_hash is not None
    source = con.execute(
        f"""
        SELECT run_id, status, created_at FROM analytics.sandbox_run
        WHERE status IN ('completed', 'completed_with_warnings') AND NOT served_from_cache
          AND dataset_id = ? AND use_case = ?
          {"AND model_config_hash = ?" if checked else ""}
        ORDER BY completed_at DESC
        LIMIT 1
        """,
        [dataset_id, use_case, *([config_hash] if checked else [])],
    ).fetchone()
    unavailable = f"The model service at {base_url} is unavailable: {reason}"
    if source is None:
        wanted = "this dataset and this model configuration" if checked else "this dataset"
        _fail(
            con, run_id, "MODEL_SERVICE_UNAVAILABLE",
            f"{unavailable} No earlier run of {wanted} exists to replay, "
            "so no estimates were produced.",
        )
        return

    source_id, source_status, source_at = source
    con.execute(
        """
        INSERT INTO analytics.sandbox_prediction (
            prediction_id, run_id, district_id, district_name, crop_id, crop_name,
            season, agri_year, area_ha, predicted_yield_qtl_per_ha,
            estimated_production_qtls, output_label, data_origin
        )
        SELECT 'pred-' || ? || '-' || district_id || '-' || crop_id || '-' || season
               || '-' || agri_year, ?,
               district_id, district_name, crop_id, crop_name, season, agri_year, area_ha,
               predicted_yield_qtl_per_ha, estimated_production_qtls, output_label, data_origin
        FROM analytics.sandbox_prediction WHERE run_id = ?
        """,
        [run_id, run_id, source_id],
    )
    con.execute(
        """
        INSERT INTO analytics.sandbox_result (
            run_id, pooled_metrics, per_crop_metrics, actual_vs_predicted,
            feature_importance, explanation, warnings, created_at
        )
        SELECT ?, pooled_metrics, per_crop_metrics, actual_vs_predicted,
               feature_importance, explanation, warnings, ?
        FROM analytics.sandbox_result WHERE run_id = ?
        """,
        [run_id, datetime.now(timezone.utc), source_id],
    )
    # The replayed results belong to the source's model, so the run records
    # that model's configuration, not one it could not read.
    con.execute(
        """
        UPDATE analytics.sandbox_run AS r
        SET served_from_cache = TRUE, replayed_from = s.run_id, model_checked = ?,
            model_config = s.model_config, model_config_hash = s.model_config_hash,
            input_summary = s.input_summary
        FROM analytics.sandbox_run AS s
        WHERE r.run_id = ? AND s.run_id = ?
        """,
        [checked, run_id, source_id],
    )
    ran = source_at.strftime("%Y-%m-%d %H:%M UTC")
    if checked:
        note = (
            f"Replayed the stored results of run {source_id} ({ran}), which ran the "
            "same model configuration over the same dataset."
        )
    else:
        note = (
            f"Replayed the stored results of run {source_id} ({ran}) over the same dataset. "
            "Current model could not be checked: service unavailable."
        )
    # A replay carries its source's warnings, and so its status.
    _finish(con, run_id, source_status, f"{unavailable} {note}")


def _finish(con: duckdb.DuckDBPyConnection, run_id: str, status: str, message: str) -> None:
    con.execute(
        """
        UPDATE analytics.sandbox_run
        SET status = ?, progress = 100, message = ?, completed_at = ?
        WHERE run_id = ?
        """,
        [status, message, datetime.now(timezone.utc), run_id],
    )


def _fail(con: duckdb.DuckDBPyConnection, run_id: str, code: str, message: str) -> None:
    con.execute(
        "UPDATE analytics.sandbox_run SET error_code = ? WHERE run_id = ?", [code, run_id]
    )
    _finish(con, run_id, "failed", message)


def get_run_status(con: duckdb.DuckDBPyConnection, run_id: str) -> dict[str, Any]:
    row = con.execute(
        "SELECT run_id, status, progress, message, error_code "
        "FROM analytics.sandbox_run WHERE run_id = ?",
        [run_id],
    ).fetchone()
    if not row:
        raise SandboxError("RUN_NOT_FOUND", f"Sandbox run {run_id!r} not found", 404)
    return {
        "run_id": row[0],
        "status": row[1],
        "progress": row[2],
        "message": row[3],
        "error_code": row[4],
    }


def get_run_results(con: duckdb.DuckDBPyConnection, run_id: str) -> dict[str, Any]:
    run_row = con.execute(
        """
        SELECT r.status, r.served_from_cache, r.replayed_from, r.model_config,
               r.model_config_hash, r.model_checked, r.input_summary, s.created_at
        FROM analytics.sandbox_run r
        LEFT JOIN analytics.sandbox_run s ON s.run_id = r.replayed_from
        WHERE r.run_id = ?
        """,
        [run_id],
    ).fetchone()
    if not run_row:
        raise SandboxError("RUN_NOT_FOUND", f"Sandbox run {run_id!r} not found", 404)

    res_row = con.execute(
        """
        SELECT pooled_metrics, per_crop_metrics, actual_vs_predicted,
               feature_importance, explanation, warnings
        FROM analytics.sandbox_result
        WHERE run_id = ?
        """,
        [run_id],
    ).fetchone()
    if not res_row:
        raise SandboxError("RESULTS_NOT_FOUND", f"Results for run {run_id!r} not found", 404)

    # Each estimate beside the yield DE&S published for the same district,
    # crop, season and year, from our own database. This comparison needs
    # nothing from the model service, so it survives its evaluation failing.
    pred_rows = con.execute(
        """
        WITH actual AS (
            SELECT district_id, crop_id, season, agri_year,
                   max(value_canonical) AS yield_rate
            FROM analytics.v_district_crop_ayp
            WHERE measure = 'yield_rate'
              AND product IN ('paddy', 'minor') AND value_canonical IS NOT NULL
            GROUP BY ALL
        )
        SELECT p.district_id, p.district_name, p.crop_id, p.crop_name, p.season,
               p.agri_year, p.area_ha, p.predicted_yield_qtl_per_ha,
               p.estimated_production_qtls, p.output_label, a.yield_rate
        FROM analytics.sandbox_prediction p
        LEFT JOIN actual a USING (district_id, crop_id, season, agri_year)
        WHERE p.run_id = ?
        ORDER BY p.district_name, p.crop_name, p.season
        """,
        [run_id],
    ).fetchall()

    predictions = [
        {
            "district_id": r[0],
            "district_name": r[1],
            "crop_id": r[2],
            "crop_name": r[3],
            "season": r[4],
            "agri_year": r[5],
            "area_ha": float(r[6]),
            "predicted_yield_qtl_per_ha": float(r[7]),
            "estimated_production_qtls": float(r[8]),
            "output_label": r[9],
            "actual_yield_qtl_per_ha": float(r[10]) if r[10] is not None else None,
        }
        for r in pred_rows
    ]
    config = json.loads(run_row[3]) if run_row[3] else None
    years = sorted({p["agri_year"] for p in predictions})

    return {
        "run_id": run_id,
        "status": run_row[0],
        "warnings": json.loads(res_row[5]),
        "pooled": json.loads(res_row[0]),
        "per_crop": json.loads(res_row[1]),
        "actual_vs_predicted": json.loads(res_row[2]),
        "feature_importance": json.loads(res_row[3]),
        "explanation": res_row[4],
        "predictions": predictions,
        "data_origin": {"model": len(predictions)},
        "served_from_cache": bool(run_row[1]),
        "replayed_from": run_row[2],
        "replayed_run_at": run_row[7].isoformat() if run_row[7] else None,
        "model_configuration": config,
        "model_config_hash": run_row[4],
        "model_checked": bool(run_row[5]),
        "input_summary": json.loads(run_row[6]) if run_row[6] else None,
        "agri_years": years,
        "comparison_label": model_config.comparison_label(config, " / ".join(years)),
    }


def _stated_value(config: Optional[dict[str, Any]], key: str) -> str:
    value = ((config or {}).get(key) or {}).get("value")
    return str(value) if value not in (None, "") else NOT_STATED


def _config_parameters(config: Optional[dict[str, Any]], config_hash: Optional[str]) -> dict[str, str]:
    """The model configuration as a version's flat parameters."""
    features = ((config or {}).get("features") or {}).get("value") or []
    return {
        "model_name": _stated_value(config, "model_name"),
        "target": _stated_value(config, "target"),
        "features": ", ".join(f["name"] for f in features) or NOT_STATED,
        "model_version": _stated_value(config, "model_version"),
        "training_period": _stated_value(config, "training_period"),
        "model_config_hash": config_hash or "not recorded",
        "model_config_sources": "GET /health, GET /openapi.json, GET /metadata",
    }


def save_version(con: duckdb.DuckDBPyConnection, run_id: str, label: str) -> dict[str, Any]:
    run = con.execute(
        "SELECT use_case, dataset_id, model_config, model_config_hash "
        "FROM analytics.sandbox_run WHERE run_id = ?",
        [run_id],
    ).fetchone()
    if not run:
        raise SandboxError("RUN_NOT_FOUND", f"Run {run_id!r} not found", 404)

    version_id = f"ver-minor-yield-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)
    config = json.loads(run[2]) if run[2] else None
    params = {
        "use_case": run[0],
        "dataset": run[1],
        **_config_parameters(config, run[3]),
    }

    con.execute(
        """
        INSERT INTO analytics.sandbox_version (
            version_id, run_id, label, parameters, published, created_at
        ) VALUES (?, ?, ?, ?, FALSE, ?)
        """,
        [version_id, run_id, label, json.dumps(params), now],
    )

    return {
        "version_id": version_id,
        "run_id": run_id,
        "label": label,
        "created_at": now.isoformat(),
        "published": False,
        "parameters": params,
    }


def publish_version(con: duckdb.DuckDBPyConnection, version_id: str) -> dict[str, Any]:
    ver = con.execute(
        """
        SELECT v.run_id, r.model_config_hash
        FROM analytics.sandbox_version v JOIN analytics.sandbox_run r USING (run_id)
        WHERE v.version_id = ?
        """,
        [version_id],
    ).fetchone()
    if not ver:
        raise SandboxError("VERSION_NOT_FOUND", f"Version {version_id!r} not found", 404)

    run_id, config_hash = ver
    now = datetime.now(timezone.utc)

    # Mark published
    con.execute(
        "UPDATE analytics.sandbox_version SET published = TRUE WHERE version_id = ?",
        [version_id],
    )

    # Fetch predictions for this run
    preds = con.execute(
        """
        SELECT district_id, district_name, crop_id, crop_name, season, agri_year,
               predicted_yield_qtl_per_ha
        FROM analytics.sandbox_prediction
        WHERE run_id = ?
        """,
        [run_id],
    ).fetchall()

    # Clear previous forecasts for this version if any
    con.execute("DELETE FROM analytics.published_forecast WHERE version_id = ?", [version_id])

    # Insert into published_forecast, joining the actual yield where available
    for r in preds:
        d_id, d_name, c_id, c_name, season, agri_year, pred_y = r

        # The actual for the estimate's own year and season. Without the season
        # this picked whichever season's yield came first.
        actual_row = con.execute(
            """
            SELECT value_canonical
            FROM analytics.v_district_crop_ayp
            WHERE agri_year = ? AND district_id = ? AND crop_id = ? AND season = ?
              AND measure = 'yield_rate' AND product IN ('paddy', 'minor')
            LIMIT 1
            """,
            [agri_year, d_id, c_id, season],
        ).fetchone()

        actual_val = float(actual_row[0]) if actual_row and actual_row[0] is not None else None
        forecast_id = f"fc-{version_id}-{d_id}-{c_id}-{season}-{agri_year}"

        con.execute(
            """
            INSERT INTO analytics.published_forecast (
                forecast_id, version_id, crop_id, crop_name, district_id, district_name,
                season, agri_year, actual_yield, forecast_yield, unit, output_label,
                data_origin, model_config_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'qtl/ha', 'Analytical Estimates',
                      'model', ?, ?)
            """,
            [forecast_id, version_id, c_id, c_name, d_id, d_name, season, agri_year,
             actual_val, float(pred_y), config_hash, now],
        )

    # Insert lineage edges
    con.execute(
        """
        INSERT INTO analytics.lineage_edge (from_node, to_node, edge_type, dataset_version_id)
        VALUES
            (?, ?, 'trained_version', ?),
            (?, 'published_forecast', 'published_forecast', ?),
            ('published_forecast', 'dashboard', 'dashboard_panel', ?)
        """,
        [run_id, version_id, version_id, version_id, version_id, version_id],
    )

    return {"version_id": version_id, "published": True}


def get_dashboard_forecasts(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    # Get latest published version's forecasts, or all published forecasts if only one version
    rows = con.execute(
        """
        SELECT f.crop_id, f.crop_name, f.district_id, f.district_name, f.season,
               f.agri_year, f.actual_yield, f.forecast_yield, f.unit, f.version_id,
               f.output_label, f.model_config_hash
        FROM analytics.published_forecast f
        JOIN analytics.sandbox_version v ON v.version_id = f.version_id
        WHERE v.published = TRUE
        ORDER BY f.district_name, f.crop_name
        """
    ).fetchall()

    return [
        {
            "crop_id": r[0],
            "crop_name": r[1],
            "district_id": r[2],
            "district_name": r[3],
            "season": r[4],
            "agri_year": r[5],
            "actual_yield": float(r[6]) if r[6] is not None else None,
            "forecast_yield": float(r[7]),
            "unit": r[8],
            "version_id": r[9],
            "output_label": r[10],
            "model_config_hash": r[11],
            "data_origin": {"model": 1},
        }
        for r in rows
    ]


def model_configurations(con: duckdb.DuckDBPyConnection, spec: QuerySpec) -> list[dict[str, Any]]:
    """The model configuration behind each run whose estimates a query returns.

    Asked of the same query, grouped by run, so an export states the models
    behind exactly the rows it carries.
    """
    by_run = semantic.run_query(con, spec.model_copy(update={
        "dimensions": ["run_id"], "order_by": None, "limit": 5_000, "include_records": False,
    }))
    run_ids = sorted({str(row["run_id"]) for row in by_run["rows"] if row.get("run_id")})
    if not run_ids:
        return []
    placeholders = ", ".join("?" for _ in run_ids)
    rows = con.execute(
        f"""
        SELECT model_config_hash, any_value(model_config), list(run_id ORDER BY run_id)
        FROM analytics.sandbox_run
        WHERE run_id IN ({placeholders})
        GROUP BY model_config_hash
        ORDER BY model_config_hash
        """,
        run_ids,
    ).fetchall()
    return [
        {
            **_config_parameters(json.loads(config) if config else None, config_hash),
            "run_ids": ", ".join(runs),
        }
        for config_hash, config, runs in rows
    ]
