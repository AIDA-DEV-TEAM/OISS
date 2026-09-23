"""External model service client and spelling translation.

Translates between OISS master IDs (OD01, CR03) and the model service's
spellings (ANUGUL, BLACKGRAM) through the district and crop masters, validates
inputs against the service's /metadata, and talks to it on MODEL_API_BASE_URL.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Optional

import httpx

from app.config import MODEL_API_BASE_URL
from app.masters.crop_master import CROP_MASTER, resolve_crop
from app.masters.districts import district_master, resolve_district


class ModelServiceError(RuntimeError):
    """Base error for model service communication."""
    def __init__(self, code: str, detail: str, status_code: int = 400) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code


class ModelServiceUnavailableError(ModelServiceError):
    """Nothing answered: the connection was refused or timed out."""
    def __init__(self, detail: str = "Model service is unreachable") -> None:
        super().__init__("MODEL_SERVICE_UNAVAILABLE", detail, status_code=503)


class ModelServiceRejectedError(ModelServiceError):
    """The service answered 4xx: it is up, and refused what was asked."""
    def __init__(self, endpoint: str, status: int, detail: str) -> None:
        super().__init__(
            "MODEL_SERVICE_REJECTED",
            f"The model service rejected a request: {endpoint} returned {status}: {detail}",
            status_code=502,
        )
        self.endpoint = endpoint
        self.status = status


class ModelServiceFailedError(ModelServiceError):
    """The service answered 5xx: it is up, and broke on what was asked."""
    def __init__(self, endpoint: str, status: int) -> None:
        super().__init__(
            "MODEL_SERVICE_ERROR",
            f"The model service returned an error: {endpoint}, {status}",
            status_code=502,
        )
        self.endpoint = endpoint
        self.status = status


# The service declares /actual-vs-predicted?limit with le=200 (its
# /openapi.json; crop_yield backend/main.py:111) and holds 111 held-out
# records, so 200 asks for all of them. A larger value is rejected with 422.
HELD_OUT_LIMIT = 200


# --------------------------------------------------------------------------
# Spelling translation, through the district and crop masters
#
# The model service has its own spellings (ANUGUL, KHURDA, BLACKGRAM, NIGER).
# There is no hand-kept map of them here: the masters' alias tables already
# resolve every one to an ID, and the service lists its own spellings in
# /metadata. IDs cross the API boundary, never spellings (prompt 7).
# --------------------------------------------------------------------------
VALID_SEASONS = {"Autumn", "Winter", "Summer"}
DEFAULT_AREA_MIN = 0.25
DEFAULT_AREA_MAX = 85465.0

_DISTRICT_IDS = frozenset(district_master()["district_id"])
_CROP_IDS = frozenset(CROP_MASTER["crop_id"])


def model_to_district_id(spelling: str) -> str:
    """The master ID for a district as the model service spells it."""
    match = resolve_district(spelling)
    if match is None or match.is_state_total:
        raise ModelServiceError("UNKNOWN_DISTRICT", f"Unknown district: {spelling}")
    return match.district_id


def model_to_crop_id(spelling: str) -> str:
    """The master ID for a crop as the model service spells it."""
    crop_id = resolve_crop(spelling)
    if crop_id is None:
        raise ModelServiceError("UNKNOWN_CROP", f"Unknown crop: {spelling}")
    return crop_id


@lru_cache(maxsize=16)
def _spellings_by_id(spellings: tuple[str, ...], kind: str) -> dict[str, str]:
    """The service's own spelling for each master ID it covers."""
    resolve = model_to_district_id if kind == "district" else model_to_crop_id
    by_id: dict[str, str] = {}
    for spelling in spellings:
        try:
            by_id[resolve(spelling)] = spelling
        except ModelServiceError:
            # Not in the masters: nothing on this side can ask for it.
            continue
    return by_id


def _as_district_id(value: str) -> str:
    return value if value in _DISTRICT_IDS else model_to_district_id(value)


def _as_crop_id(value: str) -> str:
    return value if value in _CROP_IDS else model_to_crop_id(value)


def district_id_to_model(district_id: str, metadata: dict[str, Any]) -> str:
    """The spelling the service uses for a district, taken from its /metadata."""
    spelling = _spellings_by_id(tuple(metadata.get("districts") or ()), "district").get(
        _as_district_id(district_id)
    )
    if spelling is None:
        raise ModelServiceError("UNKNOWN_DISTRICT", f"Unknown district {district_id!r}")
    return spelling


def crop_id_to_model(crop_id: str, metadata: dict[str, Any]) -> str:
    """The spelling the service uses for a crop, taken from its /metadata."""
    crops = metadata.get("minor_crops") or metadata.get("crops") or ()
    spelling = _spellings_by_id(tuple(crops), "crop").get(_as_crop_id(crop_id))
    if spelling is None:
        raise ModelServiceError("UNKNOWN_CROP", f"Unknown crop {crop_id!r}")
    return spelling


def validate_input(
    district_id_or_name: str,
    crop_id_or_name: str,
    season: str,
    area_ha: float,
    metadata: dict[str, Any],
) -> tuple[str, str, str, float]:
    """Validates inputs against /metadata; returns them in the service's spellings."""
    try:
        model_district = district_id_to_model(district_id_or_name, metadata)
    except ModelServiceError:
        raise ModelServiceError("UNKNOWN_DISTRICT", f"Unknown district {district_id_or_name!r}")

    try:
        model_crop = crop_id_to_model(crop_id_or_name, metadata)
    except ModelServiceError:
        raise ModelServiceError("UNKNOWN_CROP", f"Unknown crop {crop_id_or_name!r}")

    norm_season = season.strip().capitalize()
    valid_seasons = set(metadata.get("seasons", VALID_SEASONS))
    if norm_season not in valid_seasons:
        raise ModelServiceError(
            "UNKNOWN_SEASON", f"Unknown season {season!r}; expected one of {sorted(valid_seasons)}"
        )

    area_range = metadata.get("area_ha_range") or metadata.get("area_range_ha")
    if isinstance(area_range, dict):
        min_area = area_range.get("min", DEFAULT_AREA_MIN)
        max_area = area_range.get("max", DEFAULT_AREA_MAX)
    else:
        min_area = metadata.get("area_ha_min", DEFAULT_AREA_MIN)
        max_area = metadata.get("area_ha_max", DEFAULT_AREA_MAX)

    if area_ha <= 0 or area_ha < min_area or area_ha > max_area:
        raise ModelServiceError(
            "AREA_OUT_OF_RANGE",
            f"Area {area_ha} ha is out of allowable range ({min_area} to {max_area} ha)",
        )

    return model_district, model_crop, norm_season, float(area_ha)


class ModelServiceClient:
    """HTTP client for the external model service.

    One connection pool for the client's whole life: a run makes several
    hundred calls, and a fresh client per call opened a fresh local port for
    each, which can exhaust Windows' ephemeral ports. Use it as a context
    manager, or call :meth:`close`, so the pool is released.

    Every failure is classified, because each means something different to the
    person reading the run's message:

    * nothing answered (refused, timed out) -> :class:`ModelServiceUnavailableError`
    * it answered 4xx -> :class:`ModelServiceRejectedError`, with its own detail
    * it answered 5xx -> :class:`ModelServiceFailedError`
    """

    def __init__(
        self,
        base_url: str = MODEL_API_BASE_URL,
        timeout: float = 5.0,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        # Tests pass a stub transport; the app always uses the network.
        self._transport = transport
        self._http: Optional[httpx.Client] = None

    def __enter__(self) -> "ModelServiceClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._http is not None:
            self._http.close()
            self._http = None

    def _client(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(
                base_url=self.base_url, timeout=self.timeout, transport=self._transport
            )
        return self._http

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        endpoint = f"{method} {path}"
        if params:
            endpoint += "?" + "&".join(f"{key}={value}" for key, value in params.items())
        try:
            response = self._client().request(method, path, params=params, json=json_body)
        except httpx.TimeoutException as exc:
            raise ModelServiceUnavailableError(
                f"{endpoint} did not answer within {self.timeout:g}s"
            ) from exc
        except httpx.TransportError as exc:
            raise ModelServiceUnavailableError(f"{endpoint} could not connect: {exc}") from exc

        if 400 <= response.status_code < 500:
            raise ModelServiceRejectedError(endpoint, response.status_code, _detail(response))
        if response.status_code >= 500:
            raise ModelServiceFailedError(endpoint, response.status_code)
        try:
            body = response.json()
        except ValueError as exc:
            raise ModelServiceError(
                "MALFORMED_RESPONSE", f"{endpoint} returned {response.status_code} but no JSON"
            ) from exc
        if not isinstance(body, dict):
            raise ModelServiceError(
                "MALFORMED_RESPONSE", f"{endpoint} returned JSON that is not an object"
            )
        return body

    def is_healthy(self) -> bool:
        try:
            self._request("GET", "/health")
            return True
        except ModelServiceError:
            return False

    def get_health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def get_openapi(self) -> dict[str, Any]:
        return self._request("GET", "/openapi.json")

    def get_metadata(self) -> dict[str, Any]:
        return self._request("GET", "/metadata")

    def predict(self, district: str, season: str, minor_crop: str, area_ha: float) -> dict[str, Any]:
        payload = {
            "district": district,
            "season": season,
            "minor_crop": minor_crop,
            "area_ha": area_ha,
        }
        return self._request("POST", "/predict", json_body=payload)

    def get_actual_vs_predicted(self, limit: int = HELD_OUT_LIMIT) -> dict[str, Any]:
        return self._request("GET", "/actual-vs-predicted", params={"limit": limit})

    def get_feature_importance(self) -> dict[str, Any]:
        return self._request("GET", "/feature-importance")


def _detail(response: httpx.Response) -> str:
    """The service's own reason for a rejection, as plainly as it gives one.

    FastAPI reports validation failures as a list of {loc, msg}; anything else
    is passed through as sent, cut short.
    """
    try:
        body = response.json()
    except ValueError:
        return response.text.strip()[:300] or "no detail given"
    detail = body.get("detail") if isinstance(body, dict) else body
    if isinstance(detail, list):
        parts = []
        for item in detail:
            if isinstance(item, dict):
                where = ".".join(str(p) for p in item.get("loc", []))
                parts.append(f"{where}: {item.get('msg', '')}".strip(": "))
            else:
                parts.append(str(item))
        return "; ".join(parts) or "no detail given"
    return str(detail)[:300] if detail else "no detail given"
