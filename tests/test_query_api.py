"""HTTP surface of the semantic layer: the registry, /query and its siblings."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import main as api_main

PADDY = "CR17"

# What a dashboard asks for; the target is under 300 ms each.
LATENCY_BUDGET_MS = 300


@pytest.fixture(scope="module")
def query_db(db_path: Path, tmp_path_factory) -> Path:
    """A private copy, so the shared API connection does not lock the test database."""
    target = tmp_path_factory.mktemp("query") / "oiss.duckdb"
    shutil.copyfile(db_path, target)
    return target


@pytest.fixture(scope="module")
def client(query_db: Path) -> TestClient:
    api_main.app.dependency_overrides[api_main.database_path] = lambda: query_db
    try:
        yield TestClient(api_main.app)
    finally:
        api_main.app.dependency_overrides.clear()
        api_main.close_connections()


YIELD_SPEC = {
    "metric": "yield_rate",
    "dimensions": ["district", "agri_year"],
    "filters": [
        {"dimension": "crop", "op": "in", "values": [PADDY]},
        {"dimension": "season", "op": "eq", "values": ["Winter"]},
    ],
    "period": {"from": "2022-23", "to": "2024-25"},
    "order_by": {"field": "value", "direction": "desc"},
    "limit": 30,
    "include_records": False,
}


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------
def test_metrics_registry_lists_every_metric_with_its_rules(client: TestClient) -> None:
    body = client.get("/semantic/metrics").json()
    assert body["total"] == 11
    by_id = {item["metric_id"]: item for item in body["items"]}
    assert by_id["yield_rate"]["unit"] == "qtl/ha"
    assert "ratio of sums" in by_id["yield_rate"]["definition"]
    assert "block" not in by_id["avg_price"]["allowed_dimensions"]
    assert by_id["avg_price"]["requires_scope"] == ["data_origin"]
    assert by_id["price_yoy_pct"]["required_dimensions"] == ["agri_year"]


def test_dimensions_registry_says_where_each_one_is_available(client: TestClient) -> None:
    body = client.get("/semantic/dimensions").json()
    assert body["total"] == 12
    by_id = {item["dimension_id"]: item for item in body["items"]}
    assert by_id["district"]["is_coded"] is True
    assert by_id["season"]["is_coded"] is False
    assert "price" in by_id["price_type"]["available_on"]
    assert "price" not in by_id["season"]["available_on"]


def test_dimension_values_are_selectable_filter_values(client: TestClient) -> None:
    crops = client.get("/semantic/dimensions/crop/values").json()
    assert crops["total"] == 23
    assert {"value": "CR17", "label": "Paddy"} in crops["items"]

    districts = client.get("/semantic/dimensions/district/values").json()
    assert districts["total"] == 30


def test_unknown_dimension_values_request_is_rejected(client: TestClient) -> None:
    response = client.get("/semantic/dimensions/not_a_dimension/values")
    assert response.status_code == 422
    assert response.json()["code"] == "unknown_dimension"


# --------------------------------------------------------------------------
# /query
# --------------------------------------------------------------------------
def test_query_returns_rows_context_and_caveats(client: TestClient) -> None:
    body = client.post("/query", json=YIELD_SPEC).json()
    assert set(body) >= {"rows", "applied_context", "caveats"}

    row = body["rows"][0]
    assert {"district", "district_id", "agri_year", "value", "unit"} <= set(row)
    assert row["unit"] == "qtl/ha"

    context = body["applied_context"]
    assert context["metric"] == "yield_rate"
    assert context["dimensions"] == ["district", "agri_year"]
    assert context["period"] == {"from": "2022-23", "to": "2024-25"}
    assert context["row_count"] == len(body["rows"])
    assert context["underlying_row_count"] >= context["row_count"]
    assert context["source_datasets"]
    assert set(context["data_origin"]) == {"official", "synthetic"}


def test_grain_source_reaches_the_response_rows(client: TestClient) -> None:
    """The narrative has to be able to state the caveat per figure."""
    body = client.post("/query", json=YIELD_SPEC).json()
    assert all("grain_source" in row for row in body["rows"])
    assert set(body["applied_context"]["grain_source"]) <= {
        "published_district", "aggregated_from_blocks", "mixed",
    }


def test_include_records_attaches_the_supporting_rows(client: TestClient) -> None:
    body = client.post("/query", json={**YIELD_SPEC, "include_records": True}).json()
    assert body["records"]
    assert body["records"][0]["dataset_version_id"]


@pytest.mark.parametrize(
    "payload, code, field",
    [
        ({"metric": "nope"}, "unknown_metric", "metric"),
        (
            {"metric": "avg_price", "dimensions": ["block"],
             "filters": [{"dimension": "data_origin", "op": "eq", "values": ["official"]}]},
            "invalid_grain", "dimensions",
        ),
        ({"metric": "production", "dimensions": ["nope"]}, "unknown_dimension", "dimensions"),
        (
            {"metric": "production",
             "filters": [{"dimension": "crop", "op": "in", "values": ["CR99"]}]},
            "unknown_filter_value", "filters[0].values",
        ),
    ],
)
def test_invalid_specs_return_422_with_allowed_values(
    client: TestClient, payload: dict, code: str, field: str
) -> None:
    response = client.post("/query", json=payload)
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"detail", "code", "field", "allowed_values"}
    assert body["code"] == code
    assert body["field"] == field
    assert body["allowed_values"], "an LLM needs to know what it could have said"


def test_malformed_spec_is_rejected_before_it_reaches_sql(client: TestClient) -> None:
    response = client.post("/query", json={"metric": "production", "unexpected": 1})
    assert response.status_code == 422


def test_a_filter_value_is_never_interpolated_into_sql(client: TestClient) -> None:
    """A SQL fragment as a filter value is just an unknown value."""
    response = client.post(
        "/query",
        json={
            "metric": "production",
            "filters": [
                {"dimension": "crop", "op": "in", "values": ["CR17'; DROP TABLE x; --"]}
            ],
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "unknown_filter_value"


# --------------------------------------------------------------------------
# /query/records and /query/narrative-facts
# --------------------------------------------------------------------------
def test_records_endpoint_returns_traceable_facts(client: TestClient) -> None:
    body = client.post("/query/records", json=YIELD_SPEC).json()
    assert body["returned"] > 0
    assert body["total_matching"] >= body["returned"]
    assert body["source_datasets"]
    record = body["records"][0]
    assert record["source_file"]
    assert record["dataset_version_id"]


def test_narrative_facts_bundle_is_complete(client: TestClient) -> None:
    body = client.post("/query/narrative-facts", json=YIELD_SPEC).json()
    assert set(body) >= {
        "headline", "movement", "leaders", "laggards", "largest_changes",
        "anomalies", "applied_context", "caveats",
    }
    assert body["headline"]["value"] is not None
    assert body["leaders"] and body["laggards"]
    assert body["movement"]["percent_change"] is not None
    for change in body["largest_changes"]:
        assert {"from_period", "to_period", "percent_change"} <= set(change)


# --------------------------------------------------------------------------
# Determinism and latency
# --------------------------------------------------------------------------
def test_the_same_spec_returns_identical_bytes(client: TestClient) -> None:
    def payload() -> dict:
        body = client.post("/query", json=YIELD_SPEC).json()
        body["applied_context"].pop("generated_at")
        return body

    assert json.dumps(payload(), sort_keys=True) == json.dumps(payload(), sort_keys=True)


@pytest.mark.parametrize(
    "endpoint, payload",
    [
        ("/query", YIELD_SPEC),
        ("/query/records", YIELD_SPEC),
        ("/query/narrative-facts", YIELD_SPEC),
    ],
)
def test_dashboard_queries_stay_inside_the_latency_budget(
    client: TestClient, endpoint: str, payload: dict
) -> None:
    client.post(endpoint, json=payload)  # warm
    timings = []
    for _ in range(5):
        started = time.perf_counter()
        response = client.post(endpoint, json=payload)
        timings.append((time.perf_counter() - started) * 1000)
        assert response.status_code == 200
    median = sorted(timings)[len(timings) // 2]
    assert median < LATENCY_BUDGET_MS, f"{endpoint} median {median:.0f} ms"


def test_lineage_accepts_a_query_responses_source_datasets(client: TestClient) -> None:
    """One call from a chart to the files behind it."""
    context = client.post("/query", json=YIELD_SPEC).json()["applied_context"]
    version_ids = [source["dataset_version_id"] for source in context["source_datasets"]]
    assert version_ids

    body = client.get(
        "/lineage", params=[("dataset_version_id", v) for v in version_ids]
    ).json()
    assert body["total"] == len(version_ids)
    for item in body["items"]:
        assert item["edges"]
        assert {"extract", "transform", "load", "publish"} <= {
            edge["edge_type"] for edge in item["edges"]
        }

    # The block rollup behind 2022-23 must be visible as its own hop.
    rollup = [
        edge
        for item in body["items"]
        for edge in item["edges"]
        if edge["edge_type"] == "aggregate"
    ]
    assert rollup, "the block-to-district rollup must appear in lineage"


def test_lineage_rejects_an_unknown_version(client: TestClient) -> None:
    response = client.get("/lineage", params=[("dataset_version_id", "nope@000")])
    assert response.status_code == 404
    assert response.json()["code"] == "dataset_not_found"
