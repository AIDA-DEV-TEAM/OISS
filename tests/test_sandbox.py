"""Tests for the Task 7 Data Science Sandbox and Crop-Yield Forecasting adapter.

The model service is a separate process on port 8000 and is never running in
CI, so every test that needs estimates talks to a stand-in that behaves like
it. No test relies on the service being down to produce numbers: the adapter
used to invent them when it was, and the tests passed because of it.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import duckdb
import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import main as api_main
from app.masters.crop_master import CROP_MASTER
from app.masters.districts import district_master
from app.sandbox import client as sandbox_client
from app.sandbox import model_config
from app.sandbox import service as sandbox_service
from app.sandbox.client import (
    ModelServiceClient,
    ModelServiceError,
    ModelServiceFailedError,
    ModelServiceUnavailableError,
    crop_id_to_model,
    district_id_to_model,
    model_to_crop_id,
    model_to_district_id,
    validate_input,
)

FIXTURES = Path(__file__).parent / "fixtures"
# The service's own responses, captured live from it: never reconstructed.
METADATA = json.loads((FIXTURES / "model_service_metadata.json").read_text("utf-8"))
HEALTH = json.loads((FIXTURES / "model_service_health.json").read_text("utf-8"))
OPENAPI = json.loads((FIXTURES / "model_service_openapi.json").read_text("utf-8"))

# Held-out records as the service reports them: its own spellings, two or more
# per crop so a per-crop R² exists.
HELD_OUT = [
    {"District": "BARGARH", "Minor_Crop": "GREENGRAM",
     "Actual_Yield_qtl_per_ha": 5.4, "Predicted_Yield_qtl_per_ha": 5.1},
    {"District": "BALANGIR", "Minor_Crop": "GREENGRAM",
     "Actual_Yield_qtl_per_ha": 4.8, "Predicted_Yield_qtl_per_ha": 5.0},
    {"District": "KALAHANDI", "Minor_Crop": "GREENGRAM",
     "Actual_Yield_qtl_per_ha": 5.9, "Predicted_Yield_qtl_per_ha": 5.6},
    {"District": "CUTTACK", "Minor_Crop": "BLACKGRAM",
     "Actual_Yield_qtl_per_ha": 6.3, "Predicted_Yield_qtl_per_ha": 6.1},
    {"District": "ANUGUL", "Minor_Crop": "BLACKGRAM",
     "Actual_Yield_qtl_per_ha": 6.7, "Predicted_Yield_qtl_per_ha": 6.5},
    {"District": "KHURDA", "Minor_Crop": "HORSEGRAM",
     "Actual_Yield_qtl_per_ha": 5.7, "Predicted_Yield_qtl_per_ha": 5.5},
]

AYP_2024_25 = "earas_2024_25_district_crop_ayp"
# Never run live in this module, so there is never anything to replay for it.
MINOR_2023_24 = "earas_2023_24_district_minor_crops"


class FakeModelService:
    """Answers like the model service does, deterministically."""

    base_url = "http://model-service.test"

    def __init__(self, metadata: dict[str, Any] = METADATA) -> None:
        self.predict_calls = 0
        self.metadata = metadata

    def get_openapi(self) -> dict[str, Any]:
        return OPENAPI

    def get_health(self) -> dict[str, Any]:
        return HEALTH

    def get_metadata(self) -> dict[str, Any]:
        return self.metadata

    def predict(self, district: str, season: str, minor_crop: str, area_ha: float) -> dict:
        self.predict_calls += 1
        predicted = round(2.0 + len(minor_crop) * 0.4 + (len(district) % 5) * 0.1, 3)
        return {
            "predicted_yield_qtl_per_ha": predicted,
            "estimated_production_qtls": round(predicted * area_ha, 2),
            "output_label": "Analytical Estimates",
        }

    def get_actual_vs_predicted(self, limit: int = 50) -> dict[str, Any]:
        return {"comparisons": HELD_OUT[:limit]}

    def get_feature_importance(self) -> dict[str, Any]:
        return {
            "top_features": [
                {"Feature": "Minor_Crop", "Importance": 0.52},
                {"Feature": "District", "Importance": 0.24},
                {"Feature": "Area_ha", "Importance": 0.15},
            ],
            "plain_language_explanation": "Crop identity carries most of the signal.",
        }

    def close(self) -> None:
        """The real client releases its connection pool here; nothing to release."""


class UnreachableModelService:
    """What the adapter sees when nothing is listening on port 8000."""

    base_url = "http://model-service.test"

    def _down(self, *_args: Any, **_kwargs: Any) -> Any:
        raise ModelServiceUnavailableError("connection refused")

    get_openapi = get_health = get_metadata = predict = _down
    get_actual_vs_predicted = get_feature_importance = _down

    def close(self) -> None:
        """Nothing was opened."""


@pytest.fixture(scope="module")
def test_db(db_path: Path, tmp_path_factory) -> Path:
    """A private copy of the database to isolate state and lineage writes."""
    target = tmp_path_factory.mktemp("sandbox") / "oiss.duckdb"
    shutil.copyfile(db_path, target)
    return target


@pytest.fixture
def client(test_db: Path) -> TestClient:
    api_main.app.dependency_overrides[api_main.database_path] = lambda: test_db
    try:
        yield TestClient(api_main.app)
    finally:
        api_main.app.dependency_overrides.clear()


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> FakeModelService:
    fake = FakeModelService()
    monkeypatch.setattr(sandbox_service, "ModelServiceClient", lambda: fake)
    return fake


@pytest.fixture
def service_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sandbox_service, "ModelServiceClient", UnreachableModelService)


def _dataset_id(test_db: Path, name: str) -> str:
    """The active version of a dataset: runs name a version, not a dataset name."""
    con = duckdb.connect(str(test_db))
    try:
        return con.execute(
            "SELECT dataset_version_id FROM analytics.dataset_version "
            "WHERE dataset_name = ? AND is_active",
            [name],
        ).fetchone()[0]
    finally:
        con.close()


def _run(client: TestClient, test_db: Path, dataset: str = AYP_2024_25) -> dict[str, Any]:
    response = client.post(
        "/sandbox/runs",
        json={"dataset_id": _dataset_id(test_db, dataset), "use_case": "minor_crop_yield"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _prediction_count(test_db: Path, run_id: str) -> int:
    con = duckdb.connect(str(test_db))
    try:
        return con.execute(
            "SELECT count(*) FROM analytics.sandbox_prediction WHERE run_id = ?", [run_id]
        ).fetchone()[0]
    finally:
        con.close()


# --------------------------------------------------------------------------
# 1. Every spelling the service reports resolves through the masters
# --------------------------------------------------------------------------
def test_every_metadata_district_resolves_through_the_district_master():
    districts = METADATA["districts"]
    assert len(districts) == 30
    ids = {model_to_district_id(spelling) for spelling in districts}
    # All 30 master districts, each reached by exactly one service spelling.
    assert ids == set(district_master()["district_id"])
    for spelling in districts:
        assert district_id_to_model(model_to_district_id(spelling), METADATA) == spelling

    # The spellings prompt 7 names, which no display name matches.
    assert model_to_district_id("ANUGUL") == "OD01"
    assert model_to_district_id("KHURDA") == "OD19"


def test_every_metadata_crop_resolves_through_the_crop_master():
    crops = METADATA["minor_crops"]
    assert len(crops) == 13
    ids = {model_to_crop_id(spelling) for spelling in crops}
    assert len(ids) == 13 and ids <= set(CROP_MASTER["crop_id"])
    for spelling in crops:
        assert crop_id_to_model(model_to_crop_id(spelling), METADATA) == spelling

    names = dict(zip(CROP_MASTER["crop_id"], CROP_MASTER["display_name"]))
    spellings = ("BLACKGRAM", "GREENGRAM", "HORSEGRAM", "NIGER")
    assert {names[model_to_crop_id(s)] for s in spellings} == {"Biri", "Mung", "Kulthi", "Nizer"}


def test_a_spelling_the_masters_do_not_know_is_refused_not_guessed():
    with pytest.raises(ModelServiceError) as exc:
        model_to_district_id("ATLANTIS")
    assert exc.value.code == "UNKNOWN_DISTRICT"
    with pytest.raises(ModelServiceError) as exc:
        model_to_crop_id("QUINOA")
    assert exc.value.code == "UNKNOWN_CROP"
    # A crop in the master but not in the model's own list has no spelling.
    with pytest.raises(ModelServiceError):
        crop_id_to_model("CR17", METADATA)


# --------------------------------------------------------------------------
# 2. Input validation
# --------------------------------------------------------------------------
def test_input_validation_rules():
    d, c, s, a = validate_input("OD01", "CR13", "Summer", 12480.0, METADATA)
    assert (d, c, s, a) == ("ANUGUL", "GREENGRAM", "Summer", 12480.0)

    cases = [
        (("INVALID_DIST", "CR13", "Summer", 100.0), "UNKNOWN_DISTRICT"),
        (("OD01", "INVALID_CROP", "Summer", 100.0), "UNKNOWN_CROP"),
        (("OD01", "CR13", "Monsoon", 100.0), "UNKNOWN_SEASON"),
        (("OD01", "CR13", "Summer", 0.1), "AREA_OUT_OF_RANGE"),
        (("OD01", "CR13", "Summer", 100000.0), "AREA_OUT_OF_RANGE"),
    ]
    for args, code in cases:
        with pytest.raises(ModelServiceError) as exc:
            validate_input(*args, METADATA)
        assert exc.value.code == code
        assert exc.value.status_code == 400


# --------------------------------------------------------------------------
# 3. Wizard presets and metadata endpoints
# --------------------------------------------------------------------------
def test_model_configuration_is_what_the_service_states_each_field_sourced(
    client: TestClient, service: FakeModelService
):
    body = client.get("/sandbox/model-config").json()
    assert body["checked"] is True
    config = body["config"]
    assert config["model_name"] == {
        "value": "Tuned Gradient Boosting Regressor", "source": "GET /health"
    }
    assert config["target"] == {"value": "Yield_rate_qtl_per_ha", "source": "GET /health"}
    # The features are the fields POST /predict requires, from its own schema.
    assert [f["name"] for f in config["features"]["value"]] == [
        "district", "season", "minor_crop", "area_ha"
    ]
    assert config["features"]["source"].startswith("GET /openapi.json")
    # The /metadata lists are input domains, sourced to /metadata.
    domains = config["input_domains"]
    assert domains["source"] == "GET /metadata"
    assert domains["value"]["area_ha_range"] == METADATA["area_ha_range"]
    # Neither is stated by the service, and neither is filled in.
    assert config["model_version"] == {"value": None, "source": None}
    assert config["training_period"] == {"value": None, "source": None}
    # One model with one target: the use case is fixed, and says why.
    assert body["use_case"]["id"] == "minor_crop_yield"
    assert "one model (Tuned Gradient Boosting Regressor)" in body["use_case"]["fixed_reason"]


def test_the_configuration_hash_covers_everything_it_was_read_from():
    schema = OPENAPI["components"]["schemas"]["CropYieldPredictionRequest"]
    base = model_config.config_hash(schema, HEALTH, METADATA)
    # The service's momentary state is not the model.
    assert model_config.config_hash(schema, {**HEALTH, "status": "degraded"}, METADATA) == base
    # Any change to the model's name, request schema or metadata is a new model.
    assert model_config.config_hash(schema, {**HEALTH, "model_name": "Other"}, METADATA) != base
    assert model_config.config_hash({**schema, "required": ["district"]}, HEALTH, METADATA) != base
    assert model_config.config_hash(schema, HEALTH, {**METADATA, "seasons": ["Winter"]}) != base


def test_comparison_wording_is_forecast_only_when_training_visibly_ended_before():
    def config(period: Any) -> dict[str, Any]:
        return {"training_period": {"value": period, "source": "GET /metadata" if period else None}}

    estimate = "Model estimate vs published 2024-25 actual"
    assert model_config.comparison_label(None, "2024-25") == estimate
    assert model_config.comparison_label(config(None), "2024-25") == estimate
    assert model_config.comparison_label(config("2015-16 to 2024-25"), "2024-25") == estimate
    assert model_config.comparison_label(config("recent years"), "2024-25") == estimate
    assert (
        model_config.comparison_label(config("2015-16 to 2023-24"), "2024-25")
        == "Model forecast vs published 2024-25 actual"
    )


def test_dataset_compatibility_against_the_real_service_fixtures(
    client: TestClient, service: FakeModelService, test_db: Path
):
    listing = client.get("/sandbox/datasets").json()
    assert listing["model_checked"] is True and listing["message"] is None
    by_name = {d["label"]: d for d in listing["items"]}

    # Row counts are the database's own, not typed in.
    con = duckdb.connect(str(test_db))
    try:
        for name, table in [(AYP_2024_25, "fact_crop_ayp"),
                            ("price_statistics_2020", "fact_price"),
                            ("earas_state_series", "fact_state_series")]:
            counted = con.execute(
                f"SELECT count(*) FROM analytics.{table} WHERE dataset_version_id = ?",
                [by_name[name]["dataset_id"]],
            ).fetchone()[0]
            assert by_name[name]["row_count"] == counted
    finally:
        con.close()

    ayp = by_name[AYP_2024_25]
    assert ayp["compatible"] is True and ayp["missing_fields"] == []
    summary = ayp["input_summary"]
    assert summary["agri_years"] == ["2024-25"]
    # Every combination is either sent or counted out, with a reason.
    assert summary["sent"] + sum(o["count"] for o in summary["out_of_domain"]) == (
        summary["combinations"]
    )
    reasons = {o["reason"] for o in summary["out_of_domain"]}
    # Paddy is sown in every district, and the model covers minor crops only.
    assert "crop not in the model's minor_crops (GET /metadata)" in reasons

    def missing(name: str) -> set[str]:
        return {m["field"] for m in by_name[name]["missing_fields"]}

    # Each incompatible dataset names exactly the request fields it lacks.
    assert by_name["price_statistics_2020"]["compatible"] is False
    assert missing("price_statistics_2020") == {"season", "area_ha"}
    assert missing("earas_state_series") == {"district"}
    assert missing("earas_2024_25_district_land_use") == {"season", "minor_crop", "area_ha"}
    assert all(d["input_summary"] is None for d in listing["items"] if d["missing_fields"])


def test_dataset_compatibility_is_not_guessed_when_the_service_is_down(
    client: TestClient, service_down: None
):
    listing = client.get("/sandbox/datasets").json()
    assert listing["model_checked"] is False
    assert "could not be checked" in listing["message"]
    assert listing["items"] and all(d["compatible"] is None for d in listing["items"])

    body = client.get("/sandbox/model-config").json()
    assert body["checked"] is False and body["config"] is None
    assert "Current model could not be checked: service unavailable" in body["message"]


def test_an_incompatible_dataset_fails_the_run_with_a_typed_code(
    client: TestClient, service: FakeModelService, test_db: Path
):
    status = _run(client, test_db, "price_statistics_2020")
    assert status["status"] == "failed"
    assert status["error_code"] == "DATASET_INCOMPATIBLE"
    assert "season" in status["message"] and "area_ha" in status["message"]
    assert service.predict_calls == 0


def test_out_of_domain_combinations_are_never_sent(
    client: TestClient, test_db: Path, monkeypatch: pytest.MonkeyPatch
):
    seen: list[tuple] = []
    fake = FakeModelService()
    real_predict = fake.predict

    def predict(district: str, season: str, minor_crop: str, area_ha: float) -> dict:
        seen.append((district, season, minor_crop, area_ha))
        return real_predict(district, season, minor_crop, area_ha)

    fake.predict = predict
    monkeypatch.setattr(sandbox_service, "ModelServiceClient", lambda: fake)
    status = _run(client, test_db)
    assert status["status"] == "completed", status["message"]

    area = METADATA["area_ha_range"]
    assert seen and all(
        d in METADATA["districts"] and s in METADATA["seasons"]
        and c in METADATA["minor_crops"] and area["min"] <= a <= area["max"]
        for d, s, c, a in seen
    )
    results = client.get(f"/sandbox/runs/{status['run_id']}/results").json()
    assert results["input_summary"]["sent"] == len(seen)
    assert "outside the model's input domains and were not sent" in status["message"]


# --------------------------------------------------------------------------
# 4. A run: live, replayed, or failed -- and never invented
# --------------------------------------------------------------------------
def test_a_run_against_the_service_stores_what_it_returned(
    client: TestClient, service: FakeModelService, test_db: Path
):
    """(a) With the service answering, the run completes with stored results."""
    status = _run(client, test_db)
    assert status["status"] == "completed", status["message"]
    assert status["progress"] == 100
    run_id = status["run_id"]
    assert client.get(f"/sandbox/runs/{run_id}").json()["status"] == "completed"

    results = client.get(f"/sandbox/runs/{run_id}/results").json()
    assert results["served_from_cache"] is False
    assert results["replayed_from"] is None

    # One estimate per sown 2024-25 combination the model covers, each from
    # the service, and every one of them stored.
    predictions = results["predictions"]
    assert len(predictions) == service.predict_calls > 20
    assert _prediction_count(test_db, run_id) == len(predictions)
    assert {p["output_label"] for p in predictions} == {"Analytical Estimates"}
    assert results["data_origin"] == {"model": len(predictions)}

    # The metrics are computed from the held-out records the service sent, so
    # they can be checked against those records directly.
    assert results["pooled"]["n"] == len(HELD_OUT)
    residuals = [h["Actual_Yield_qtl_per_ha"] - h["Predicted_Yield_qtl_per_ha"] for h in HELD_OUT]
    assert results["pooled"]["mae"] == pytest.approx(sum(map(abs, residuals)) / len(residuals), abs=1e-4)
    per_crop = {row["crop_id"]: row for row in results["per_crop"]}
    assert per_crop["CR13"]["n"] == 3 and per_crop["CR13"]["crop_name"] == "Mung"
    # A single held-out record has no variance to explain: a gap, not a zero.
    assert per_crop["CR10"]["n"] == 1 and per_crop["CR10"]["r2"] is None

    # Held-out pairs arrive in the service's spellings and leave as master names.
    names = {(p["district_name"], p["crop_name"]) for p in results["actual_vs_predicted"]}
    assert ("Angul", "Biri") in names and ("Khordha", "Kulthi") in names
    assert results["explanation"] == "Crop identity carries most of the signal."


def test_an_unreachable_service_replays_an_earlier_run_and_says_the_model_is_unchecked(
    client: TestClient, test_db: Path, monkeypatch: pytest.MonkeyPatch
):
    """(b) Service down entirely: the current model cannot be read, so the
    replay matches dataset and use case, and says the model went unchecked."""
    fake = FakeModelService()
    monkeypatch.setattr(sandbox_service, "ModelServiceClient", lambda: fake)
    live = _run(client, test_db)
    live_results = client.get(f"/sandbox/runs/{live['run_id']}/results").json()

    monkeypatch.setattr(sandbox_service, "ModelServiceClient", UnreachableModelService)
    replay = _run(client, test_db)
    assert replay["status"] == "completed"
    assert "unavailable" in replay["message"] and live["run_id"] in replay["message"]
    assert "Current model could not be checked: service unavailable" in replay["message"]

    results = client.get(f"/sandbox/runs/{replay['run_id']}/results").json()
    assert results["served_from_cache"] is True
    assert results["replayed_from"] == live["run_id"]
    assert results["replayed_run_at"]
    assert results["model_checked"] is False
    # The configuration shown is the replayed run's, stored when it ran.
    assert results["model_configuration"] == live_results["model_configuration"]
    assert results["model_config_hash"] == live_results["model_config_hash"]
    assert results["pooled"] == live_results["pooled"]
    assert [p["predicted_yield_qtl_per_ha"] for p in results["predictions"]] == [
        p["predicted_yield_qtl_per_ha"] for p in live_results["predictions"]
    ]


class PredictDown(FakeModelService):
    """The service states its model, then stops answering /predict."""

    def predict(self, *_args: Any, **_kwargs: Any) -> dict:
        raise ModelServiceUnavailableError("POST /predict did not answer within 5s")


def test_a_replay_never_serves_results_from_a_different_model(
    client: TestClient, test_db: Path, monkeypatch: pytest.MonkeyPatch
):
    """Same dataset, different configuration hash: no replay."""
    monkeypatch.setattr(sandbox_service, "ModelServiceClient", FakeModelService)
    live = _run(client, test_db)
    assert live["status"] == "completed", live["message"]

    # The same model, readable, but /predict is down: the earlier run is replayed.
    monkeypatch.setattr(sandbox_service, "ModelServiceClient", PredictDown)
    same = _run(client, test_db)
    assert same["status"] == "completed", same["message"]
    same_results = client.get(f"/sandbox/runs/{same['run_id']}/results").json()
    assert same_results["model_checked"] is True
    assert "same model configuration" in same["message"]

    # A retrained model whose /metadata changed: a different hash, nothing to replay.
    changed = {**METADATA, "area_ha_range": {"min": 0.5, "max": 90000.0}}
    monkeypatch.setattr(sandbox_service, "ModelServiceClient", lambda: PredictDown(changed))
    other = _run(client, test_db)
    assert other["status"] == "failed"
    assert other["error_code"] == "MODEL_SERVICE_UNAVAILABLE"
    assert "No earlier run of this dataset and this model configuration" in other["message"]
    assert _prediction_count(test_db, other["run_id"]) == 0


def test_an_unreachable_service_with_nothing_to_replay_fails_and_stores_nothing(
    client: TestClient, service_down: None, test_db: Path
):
    """(c) Service down, no earlier run: the run fails and writes no predictions."""
    status = _run(client, test_db, MINOR_2023_24)
    assert status["status"] == "failed"
    assert status["error_code"] == "MODEL_SERVICE_UNAVAILABLE"
    assert "unavailable" in status["message"]
    assert "No earlier run" in status["message"]
    assert _prediction_count(test_db, status["run_id"]) == 0

    con = duckdb.connect(str(test_db))
    try:
        stored = con.execute(
            "SELECT count(*) FROM analytics.sandbox_result WHERE run_id = ?", [status["run_id"]]
        ).fetchone()[0]
    finally:
        con.close()
    assert stored == 0
    assert client.get(f"/sandbox/runs/{status['run_id']}/results").status_code == 404


class EvaluationDown(FakeModelService):
    """Estimates answer; both parts of the evaluation fail."""

    def get_actual_vs_predicted(self, limit: int = 50) -> dict[str, Any]:
        raise ModelServiceFailedError("GET /actual-vs-predicted", 500)

    def get_feature_importance(self) -> dict[str, Any]:
        raise ModelServiceFailedError("GET /feature-importance", 500)


def test_when_the_evaluation_fails_the_estimates_stay_and_the_explanation_is_a_string(
    client: TestClient, test_db: Path, monkeypatch: pytest.MonkeyPatch
):
    fake = EvaluationDown()
    monkeypatch.setattr(sandbox_service, "ModelServiceClient", lambda: fake)
    status = _run(client, test_db)
    assert status["status"] == "completed_with_warnings", status["message"]
    assert _prediction_count(test_db, status["run_id"]) == fake.predict_calls > 20

    con = duckdb.connect(str(test_db))
    try:
        explanation, pooled = con.execute(
            "SELECT explanation, pooled_metrics FROM analytics.sandbox_result WHERE run_id = ?",
            [status["run_id"]],
        ).fetchone()
    finally:
        con.close()
    # sandbox_result.explanation is NOT NULL: an empty string, never None.
    assert explanation == ""
    assert json.loads(pooled) is None

    results = client.get(f"/sandbox/runs/{status['run_id']}/results").json()
    assert results["explanation"] == "" and results["feature_importance"] == []
    assert len(results["warnings"]) == 2


def test_a_storage_failure_fails_the_run_with_a_typed_code_not_a_500(
    client: TestClient, test_db: Path, monkeypatch: pytest.MonkeyPatch
):
    fake = FakeModelService()
    monkeypatch.setattr(sandbox_service, "ModelServiceClient", lambda: fake)

    def broken(*_args: Any, **_kwargs: Any) -> None:
        raise duckdb.IOException("disk full")

    # The evaluation cannot be stored: the estimates, stored first, remain.
    monkeypatch.setattr(sandbox_service, "_store_evaluation", broken)
    status = _run(client, test_db)
    assert status["status"] == "failed"
    assert status["error_code"] == "STORAGE_FAILED"
    assert "estimates were stored, but storing the model's evaluation failed" in status["message"]
    assert "disk full" not in status["message"]
    assert _prediction_count(test_db, status["run_id"]) == fake.predict_calls

    # The estimates cannot be stored: none is kept, and the run says so.
    monkeypatch.setattr(sandbox_service, "_store_predictions", broken)
    status = _run(client, test_db)
    assert status["status"] == "failed"
    assert status["error_code"] == "STORAGE_FAILED"
    assert "storing them failed, so none was kept" in status["message"]
    assert _prediction_count(test_db, status["run_id"]) == 0


def test_a_prediction_the_service_does_not_return_fails_the_run(
    client: TestClient, test_db: Path, monkeypatch: pytest.MonkeyPatch
):
    """A missing figure is not replaced with a guess; the run fails whole."""
    fake = FakeModelService()
    fake.predict = lambda *args, **kwargs: {"output_label": "Analytical Estimates"}
    monkeypatch.setattr(sandbox_service, "ModelServiceClient", lambda: fake)

    status = _run(client, test_db)
    assert status["status"] == "failed"
    assert "no predicted yield" in status["message"]
    assert _prediction_count(test_db, status["run_id"]) == 0


# --------------------------------------------------------------------------
# 5. Publishing: dashboard rows and lineage
# --------------------------------------------------------------------------
def test_publishing_fills_the_dashboard_forecasts(
    client: TestClient, service: FakeModelService, test_db: Path
):
    run_id = _run(client, test_db)["run_id"]
    config_hash = client.get(f"/sandbox/runs/{run_id}/results").json()["model_config_hash"]
    version = client.post(
        f"/sandbox/runs/{run_id}/versions", json={"label": "Minor Crops GBR Candidate 1"}
    ).json()
    assert version["published"] is False
    # The version carries the model configuration, as stated or as not stated.
    params = version["parameters"]
    assert params["model_name"] == "Tuned Gradient Boosting Regressor"
    assert params["target"] == "Yield_rate_qtl_per_ha"
    assert params["features"] == "district, season, minor_crop, area_ha"
    assert params["model_version"] == "not stated by the model service"
    assert params["training_period"] == "not stated by the model service"
    assert params["model_config_hash"] == config_hash
    assert client.post(f"/sandbox/versions/{version['version_id']}/publish").json()["published"]

    forecasts = [
        f for f in client.get("/dashboard/forecasts").json()
        if f["version_id"] == version["version_id"]
    ]
    assert len(forecasts) == service.predict_calls
    assert {f["output_label"] for f in forecasts} == {"Analytical Estimates"}
    assert all(f["data_origin"] == {"model": 1} for f in forecasts)
    assert {f["model_config_hash"] for f in forecasts} == {config_hash}
    assert {f["agri_year"] for f in forecasts} == {"2024-25"}
    # Each estimate is set against the actual for its own season.
    assert sum(f["actual_yield"] is not None for f in forecasts) > 0


def test_lineage_edges_created_on_publish(
    client: TestClient, service: FakeModelService, test_db: Path
):
    run_id = _run(client, test_db)["run_id"]
    version_id = client.post(
        f"/sandbox/runs/{run_id}/versions", json={"label": "Governance Test"}
    ).json()["version_id"]
    client.post(f"/sandbox/versions/{version_id}/publish")

    con = duckdb.connect(str(test_db))
    try:
        edges = con.execute(
            "SELECT from_node, to_node, edge_type FROM analytics.lineage_edge "
            "WHERE dataset_version_id = ?",
            [version_id],
        ).fetchall()
    finally:
        con.close()

    # run -> version -> published_forecast -> dashboard
    hops = {(e[0], e[1]) for e in edges}
    assert hops == {
        (run_id, version_id),
        (version_id, "published_forecast"),
        ("published_forecast", "dashboard"),
    }


def test_an_unpublished_run_is_not_queryable_until_it_is_published(
    client: TestClient, service: FakeModelService, test_db: Path
):
    """A run is a draft. Its estimates reach /query and exports only once published."""
    run_id = _run(client, test_db)["run_id"]
    spec = {
        "metric": "predicted_yield",
        "dimensions": ["district"],
        "filters": [{"dimension": "run_id", "op": "in", "values": [run_id]}],
    }

    def queried() -> list:
        response = client.post("/query", json=spec)
        # A 200 with no rows, not a rejection: the view itself withholds the
        # draft, so the gate holds for any caller, not only a validated spec.
        assert response.status_code == 200, response.text
        return response.json()["rows"]

    assert queried() == []
    version_id = client.post(
        f"/sandbox/runs/{run_id}/versions", json={"label": "Saved, not published"}
    ).json()["version_id"]
    assert queried() == [], "saving a version must not publish it"

    client.post(f"/sandbox/versions/{version_id}/publish")
    assert len(queried()) > 0


# --------------------------------------------------------------------------
# 6. Export of a run's results, by derived spec, with the label in the file
# --------------------------------------------------------------------------
def test_sandbox_derived_spec_export(
    client: TestClient, service: FakeModelService, test_db: Path
):
    run_id = _run(client, test_db)["run_id"]
    config_hash = client.get(f"/sandbox/runs/{run_id}/results").json()["model_config_hash"]
    version_id = client.post(
        f"/sandbox/runs/{run_id}/versions", json={"label": "Export test"}
    ).json()["version_id"]
    client.post(f"/sandbox/versions/{version_id}/publish")

    record = client.post(
        "/export",
        json={
            "export_type": "model_output",
            "format": "csv",
            "panel_title": "Minor-crop yield estimates",
            "query_spec": {
                "metric": "predicted_yield",
                "dimensions": ["district", "crop", "season"],
                "filters": [{"dimension": "run_id", "op": "in", "values": [run_id]}],
                "limit": 100,
            },
        },
    )
    assert record.status_code == 201, record.text
    context = record.json()["context"]
    assert context["context_origin"] == "derived"
    assert context["data_origin"]["model"] == service.predict_calls
    assert any("Analytical Estimates" in note for note in context["provenance_notes"])
    # The file says which model the rows came from, and what it did not state.
    [config] = context["model_configurations"]
    assert config["model_config_hash"] == config_hash and config["run_ids"] == run_id
    assert config["training_period"] == "not stated by the model service"

    csv_text = client.get(f"/export/{record.json()['export_id']}/download").text
    assert "Model configuration" in csv_text and config_hash in csv_text
    assert "Analytical Estimates" in csv_text
    assert "Context: derived" in csv_text
    assert "Predicted yield" in csv_text


# --------------------------------------------------------------------------
# 6. Over HTTP: what each kind of failure does to a run
#
# These drive the real ModelServiceClient against a stub transport, so the
# request, the status classification and the messages are the code's own.
# --------------------------------------------------------------------------
LIMIT_422 = {
    "detail": [{
        "type": "less_than_equal", "loc": ["query", "limit"],
        "msg": "Input should be less than or equal to 200", "input": "100000",
    }]
}


def _http_service(
    monkeypatch: pytest.MonkeyPatch, overrides: dict[str, Any]
) -> list[httpx.Request]:
    """A stub model service on HTTP. ``overrides`` maps a path to a Response,
    or to an exception to raise; every other path answers like the fake."""
    fake = FakeModelService()
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path in overrides:
            outcome = overrides[path]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        if path == "/openapi.json":
            return httpx.Response(200, json=OPENAPI)
        if path == "/health":
            return httpx.Response(200, json=HEALTH)
        if path == "/metadata":
            return httpx.Response(200, json=fake.get_metadata())
        if path == "/predict":
            body = json.loads(request.content)
            return httpx.Response(200, json=fake.predict(
                body["district"], body["season"], body["minor_crop"], body["area_ha"]
            ))
        if path == "/actual-vs-predicted":
            return httpx.Response(200, json={"comparisons": HELD_OUT, "total_samples": len(HELD_OUT)})
        if path == "/feature-importance":
            return httpx.Response(200, json=fake.get_feature_importance())
        return httpx.Response(404, json={"detail": "Not Found"})

    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(
        sandbox_service, "ModelServiceClient",
        lambda: ModelServiceClient("http://model-service.test", transport=transport),
    )
    return seen


def test_a_422_on_the_held_out_records_keeps_every_prediction(
    client: TestClient, test_db: Path, monkeypatch: pytest.MonkeyPatch
):
    seen = _http_service(
        monkeypatch, {"/actual-vs-predicted": httpx.Response(422, json=LIMIT_422)}
    )

    status = _run(client, test_db)

    assert status["status"] == "completed_with_warnings", status["message"]
    rejection = (
        "The model service rejected a request: GET /actual-vs-predicted?limit=200 "
        "returned 422: query.limit: Input should be less than or equal to 200"
    )
    assert rejection in status["message"]
    assert "unavailable" not in status["message"].split("Model evaluation")[0]

    # Every estimate the service returned is stored, none discarded.
    predict_calls = [r for r in seen if r.url.path == "/predict"]
    assert len(predict_calls) > 20
    assert _prediction_count(test_db, status["run_id"]) == len(predict_calls)
    # The held-out records were asked for within the service's declared limit.
    held_out = next(r for r in seen if r.url.path == "/actual-vs-predicted")
    assert held_out.url.params["limit"] == "200"

    results = client.get(f"/sandbox/runs/{status['run_id']}/results").json()
    assert results["status"] == "completed_with_warnings"
    assert any(rejection in warning for warning in results["warnings"])
    # No held-out records, so no metrics: absent, not invented.
    assert results["pooled"] is None
    assert results["per_crop"] == [] and results["actual_vs_predicted"] == []
    # Feature importance did answer, so it is kept.
    assert results["explanation"] == "Crop identity carries most of the signal."
    # The comparison against 2024-25 actuals comes from our own database.
    assert len(results["predictions"]) == len(predict_calls)
    assert any(p["actual_yield_qtl_per_ha"] is not None for p in results["predictions"])


def test_a_refused_connection_is_reported_as_unavailable(
    client: TestClient, test_db: Path, monkeypatch: pytest.MonkeyPatch
):
    _http_service(monkeypatch, {"/metadata": httpx.ConnectError("connection refused")})

    status = _run(client, test_db, MINOR_2023_24)

    assert status["status"] == "failed"
    assert "The model service at http://model-service.test is unavailable" in status["message"]
    assert "could not connect" in status["message"]
    assert _prediction_count(test_db, status["run_id"]) == 0


def test_a_4xx_on_a_prediction_names_the_endpoint_status_and_reason(
    client: TestClient, test_db: Path, monkeypatch: pytest.MonkeyPatch
):
    _http_service(
        monkeypatch, {"/predict": httpx.Response(400, json={"detail": "Unknown district 'ANUGUL'"})}
    )

    status = _run(client, test_db)

    assert status["status"] == "failed"
    assert (
        "The model service rejected a request: POST /predict returned 400: "
        "Unknown district 'ANUGUL'"
    ) in status["message"]
    assert "unavailable" not in status["message"]
    assert _prediction_count(test_db, status["run_id"]) == 0


def test_a_5xx_is_reported_as_the_service_erring_not_as_it_being_down(
    client: TestClient, test_db: Path, monkeypatch: pytest.MonkeyPatch
):
    _http_service(monkeypatch, {"/metadata": httpx.Response(500, text="Internal Server Error")})

    status = _run(client, test_db)

    assert status["status"] == "failed"
    assert "The model service returned an error: GET /metadata, 500" in status["message"]
    assert "unavailable" not in status["message"]


def test_a_whole_run_uses_one_connection_pool(
    client: TestClient, test_db: Path, monkeypatch: pytest.MonkeyPatch
):
    opened: list[httpx.Client] = []
    real_client = httpx.Client

    class CountingClient(real_client):  # type: ignore[misc, valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            opened.append(self)

    seen = _http_service(monkeypatch, {})
    monkeypatch.setattr(sandbox_client.httpx, "Client", CountingClient)

    status = _run(client, test_db)

    assert status["status"] == "completed", status["message"]
    assert len(seen) > 20
    assert len(opened) == 1, f"{len(seen)} requests opened {len(opened)} clients"
    assert opened[0].is_closed, "the pool is released when the run ends"
