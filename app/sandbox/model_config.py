"""What the model service states about the model it serves.

The model is pre-trained and fixed: nothing on this side configures it. So a
run's "model configuration" is only ever what the service itself states, read
from three of its endpoints, each field labelled with the one that stated it:

* ``GET /openapi.json`` -- the ``POST /predict`` request schema: the fields a
  prediction needs, which is what a dataset must be able to supply;
* ``GET /health`` -- the model's name and target variable;
* ``GET /metadata`` -- the input domains: the districts, seasons, crops and
  area range the model accepts. These are domains, not features.

Nothing is inferred. A field the service does not state (today: the model
version and the training period) is recorded as not stated, and shown so.

The configuration hash is taken over everything the configuration was read
from, not over the fields picked out of it, so any change to the model's
request schema, its /health model fields or its /metadata makes a new hash,
and a replay never serves results produced by a different model. A retrain
that changes none of those is undetectable from outside, which is why the
missing version and training period are reported rather than papered over.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from app.sandbox.client import ModelServiceClient, ModelServiceError

HEALTH = "GET /health"
METADATA = "GET /metadata"
PREDICT_SCHEMA = "GET /openapi.json (POST /predict request schema)"

# /health fields that describe the service's state at this moment, not the
# model. Hashing them would make every restart look like a new model.
_HEALTH_STATE_FIELDS = {"status", "model_loaded"}

# The keys a version or training period would be stated under, if the service
# stated one. Read from /health first, then /metadata; never guessed.
_VERSION_KEYS = ("model_version",)
_TRAINING_KEYS = ("training_period",)

# The /metadata lists that bound what the model accepts.
_DOMAIN_KEYS = ("districts", "seasons", "minor_crops", "area_ha_range")


def _predict_request_schema(openapi: dict[str, Any]) -> dict[str, Any]:
    """The JSON schema of POST /predict's body, with its $ref resolved."""
    try:
        schema = openapi["paths"]["/predict"]["post"]["requestBody"]["content"][
            "application/json"]["schema"]
    except (KeyError, TypeError) as exc:
        raise ModelServiceError(
            "MALFORMED_RESPONSE", "GET /openapi.json does not describe a POST /predict body"
        ) from exc
    ref = schema.get("$ref") if isinstance(schema, dict) else None
    if ref:
        name = ref.rsplit("/", 1)[-1]
        schema = (openapi.get("components") or {}).get("schemas", {}).get(name)
        if not isinstance(schema, dict):
            raise ModelServiceError(
                "MALFORMED_RESPONSE", f"GET /openapi.json references {ref} but does not define it"
            )
    return schema


def _stated(value: Any, source: str) -> dict[str, Any]:
    return {"value": value, "source": source}


def _not_stated() -> dict[str, Any]:
    return {"value": None, "source": None}


def _first_stated(keys: tuple[str, ...], health: dict, metadata: dict) -> dict[str, Any]:
    for body, source in ((health, HEALTH), (metadata, METADATA)):
        for key in keys:
            if body.get(key) not in (None, ""):
                return _stated(str(body[key]), source)
    return _not_stated()


def config_hash(request_schema: dict, health: dict, metadata: dict) -> str:
    """sha256 over the request schema, /health's model fields and all of /metadata."""
    model_fields = {k: v for k, v in health.items() if k not in _HEALTH_STATE_FIELDS}
    canonical = json.dumps(
        {"predict_request_schema": request_schema, "health": model_fields, "metadata": metadata},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fetch(cli: ModelServiceClient) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """The model configuration, its hash, and the raw /metadata inputs are checked against."""
    openapi = cli.get_openapi()
    health = cli.get_health()
    metadata = cli.get_metadata()
    schema = _predict_request_schema(openapi)

    properties = schema.get("properties") or {}
    features = [
        {
            "name": name,
            "type": str((properties.get(name) or {}).get("type") or "unspecified"),
            "description": str((properties.get(name) or {}).get("description") or ""),
        }
        for name in schema.get("required") or []
    ]
    config = {
        "service_url": cli.base_url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "model_name": (
            _stated(str(health["model_name"]), HEALTH) if health.get("model_name")
            else _not_stated()
        ),
        "target": (
            _stated(str(health["target_variable"]), HEALTH) if health.get("target_variable")
            else _not_stated()
        ),
        "model_version": _first_stated(_VERSION_KEYS, health, metadata),
        "training_period": _first_stated(_TRAINING_KEYS, health, metadata),
        "features": _stated(features, PREDICT_SCHEMA),
        "input_domains": _stated(
            {key: metadata.get(key) for key in _DOMAIN_KEYS if key in metadata}, METADATA
        ),
    }
    return config, config_hash(schema, health, metadata), metadata


_AGRI_YEAR = re.compile(r"\b(\d{4})-\d{2}\b")


def comparison_label(config: Optional[dict[str, Any]], agri_year: str) -> str:
    """How a run's estimates may be described against that year's published actual.

    "Forecast" only when the service states a training period that visibly ends
    before the year. A period that is not stated, or that cannot be read as
    agricultural years, could include the year, so the estimates are only
    estimates: calling them a forecast would claim the model never saw it.
    """
    period = ((config or {}).get("training_period") or {}).get("value")
    target = _AGRI_YEAR.match(agri_year)
    ends = [int(y) for y in _AGRI_YEAR.findall(period or "")]
    if target and ends and max(ends) < int(target.group(1)):
        return f"Model forecast vs published {agri_year} actual"
    return f"Model estimate vs published {agri_year} actual"
