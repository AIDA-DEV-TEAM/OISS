"""FastAPI app for the OISS PoC data layer.

Routes are thin: they validate input, call :mod:`app.api.service` and shape the
response. No business logic here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import duckdb
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse

from app import db
from app.api import service
from app.api.schemas import (
    DatasetVersion,
    DimensionInfo,
    DimensionValue,
    ErrorResponse,
    Health,
    IngestResult,
    IngestSchema,
    LayerStage,
    Lineage,
    MetricInfo,
    NarrativeFactsResponse,
    Page,
    QueryResponse,
    RecordsResponse,
    RuleSummary,
    SpecErrorResponse,
    ValidationFinding,
)
from app.semantic import service as semantic
from app.semantic.registry import DIMENSIONS_BY_ID
from app.semantic.spec import QuerySpec, SpecError
from app.config import DB_PATH

app = FastAPI(
    title="OISS PoC data layer",
    version="0.1.0",
    description=(
        "Odisha Integrated Statistical System proof of concept: ingestion, "
        "validation, lineage and versioning over DE&S published data."
    ),
)

MAX_UPLOAD_BYTES = 64 * 1024 * 1024


class DataError(Exception):
    """A client-visible problem with the request, carrying a stable code."""

    def __init__(self, status_code: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


@app.exception_handler(DataError)
async def data_error_handler(request: Request, exc: DataError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(detail=exc.detail, code=exc.code).model_dump(),
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Keep every error body shaped as {detail, code}; never leak internals."""
    codes = {400: "bad_request", 404: "not_found", 413: "payload_too_large", 422: "unprocessable_entity"}
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            detail=str(exc.detail), code=codes.get(exc.status_code, "error")
        ).model_dump(),
    )


def database_path() -> Path:
    return DB_PATH


# One connection per database file, shared for the process lifetime. DuckDB
# refuses to mix read-only and read-write connections to the same file, and
# reopening per request costs more than it saves. The connection serialises
# concurrent use internally.
_CONNECTIONS: dict[str, duckdb.DuckDBPyConnection] = {}


def get_connection(
    path: Annotated[Path, Depends(database_path)],
) -> duckdb.DuckDBPyConnection:
    if not path.exists():
        raise DataError(
            503, "database_missing", f"{path} does not exist; run `python -m app.cli build`"
        )
    key = str(path.resolve())
    connection = _CONNECTIONS.get(key)
    if connection is None:
        connection = db.connect(path)
        try:
            connection.execute(db.VIEW_DDL)
        except Exception:
            pass
        _CONNECTIONS[key] = connection
    return connection


def close_connections() -> None:
    """Release the database files; used by tests and on shutdown."""
    for connection in _CONNECTIONS.values():
        connection.close()
    _CONNECTIONS.clear()


@app.on_event("shutdown")
async def _shutdown() -> None:
    close_connections()


Connection = Annotated[duckdb.DuckDBPyConnection, Depends(get_connection)]


@app.get("/health", response_model=Health)
async def get_health(
    path: Annotated[Path, Depends(database_path)],
) -> Health:
    if not path.exists():
        return Health(
            status="database_missing",
            database=str(path),
            database_present=False,
            fact_rows={},
        )
    return Health(**service.health(get_connection(path), path))


@app.get("/datasets", response_model=Page[DatasetVersion])
async def list_datasets(
    con: Connection,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=200)] = 50,
    layer: Optional[str] = None,
) -> Page[DatasetVersion]:
    items, total = service.list_datasets(con, page, size, layer)
    return Page[DatasetVersion](items=items, total=total, page=page, size=size)


@app.get("/datasets/{dataset_version_id}", response_model=DatasetVersion)
async def get_dataset(con: Connection, dataset_version_id: str) -> DatasetVersion:
    version = service.get_dataset(con, dataset_version_id)
    if version is None:
        raise DataError(404, "dataset_not_found", f"no dataset version {dataset_version_id!r}")
    return DatasetVersion(**version)


@app.get(
    "/datasets/{dataset_version_id}/validation", response_model=Page[ValidationFinding]
)
async def get_dataset_validation(
    con: Connection,
    dataset_version_id: str,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=500)] = 100,
    severity: Optional[str] = None,
    rule_code: Optional[str] = None,
) -> Page[ValidationFinding]:
    if service.get_dataset(con, dataset_version_id) is None:
        raise DataError(404, "dataset_not_found", f"no dataset version {dataset_version_id!r}")
    items, total = service.list_findings(
        con, dataset_version_id, page, size, severity, rule_code
    )
    return Page[ValidationFinding](items=items, total=total, page=page, size=size)


@app.get("/datasets/{dataset_version_id}/layers", response_model=Page[LayerStage])
async def get_dataset_layers(con: Connection, dataset_version_id: str) -> Page[LayerStage]:
    """Row counts per storage layer, and what happened between them."""
    stages = service.layer_journey(con, dataset_version_id)
    if stages is None:
        raise DataError(404, "dataset_not_found", f"no dataset version {dataset_version_id!r}")
    return Page[LayerStage](items=stages, total=len(stages), page=1, size=len(stages))


@app.get(
    "/datasets/{dataset_version_id}/validation/summary", response_model=Page[RuleSummary]
)
async def get_validation_summary(
    con: Connection, dataset_version_id: str
) -> Page[RuleSummary]:
    """Finding counts per rule for one dataset version."""
    summary = service.validation_summary(con, dataset_version_id)
    if summary is None:
        raise DataError(404, "dataset_not_found", f"no dataset version {dataset_version_id!r}")
    return Page[RuleSummary](items=summary, total=len(summary), page=1, size=len(summary))


@app.get("/lineage", response_model=Page[Lineage])
async def get_lineage_for_many(
    con: Connection,
    dataset_version_id: Annotated[list[str], Query(min_length=1)],
) -> Page[Lineage]:
    """Lineage for several versions at once.

    Takes the ``dataset_version_id`` values straight from a query response's
    ``applied_context.source_datasets``, so "where did this chart come from" is
    one call rather than one per dataset.
    """
    unknown = [
        version_id for version_id in dataset_version_id
        if service.get_dataset(con, version_id) is None
    ]
    if unknown:
        raise DataError(
            404, "dataset_not_found", f"no dataset version(s) {unknown}"
        )
    items = [service.get_lineage(con, version_id) for version_id in dataset_version_id]
    return Page[Lineage](items=items, total=len(items), page=1, size=len(items))


@app.get("/lineage/{dataset_version_id}", response_model=Lineage)
async def get_lineage(con: Connection, dataset_version_id: str) -> Lineage:
    lineage = service.get_lineage(con, dataset_version_id)
    if lineage is None:
        raise DataError(404, "dataset_not_found", f"no dataset version {dataset_version_id!r}")
    return Lineage(**lineage)


@app.get("/ingest/schemas", response_model=Page[IngestSchema])
async def list_ingest_schemas() -> Page[IngestSchema]:
    """The declared schemas an upload can be validated against."""
    items = service.ingest_schemas()
    return Page[IngestSchema](
        items=[IngestSchema(**item) for item in items],
        total=len(items),
        page=1,
        size=len(items),
    )


@app.post("/ingest/upload", response_model=IngestResult, status_code=201)
async def ingest_upload(
    con: Connection,
    dataset_name: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
) -> IngestResult:
    """Validate an uploaded file against a known dataset's schema and rules.

    Bad rows are quarantined and reported; the request succeeds regardless, so
    the demo can show findings rather than an error page.
    """
    content = await file.read()
    if not content:
        raise DataError(400, "empty_file", "the uploaded file is empty")
    if len(content) > MAX_UPLOAD_BYTES:
        raise DataError(413, "payload_too_large", "the uploaded file is too large")
    try:
        result = service.ingest_upload(
            con, dataset_name, file.filename or "upload", content
        )
    except KeyError as exc:
        raise DataError(400, "unknown_dataset", str(exc.args[0])) from exc
    except (UnicodeDecodeError, ValueError) as exc:
        raise DataError(400, "unreadable_file", f"the file could not be parsed: {exc}") from exc
    return IngestResult(**result)


# --------------------------------------------------------------------------
# Semantic layer
# --------------------------------------------------------------------------
@app.exception_handler(SpecError)
async def spec_error_handler(request: Request, exc: SpecError) -> JSONResponse:
    """422 with the offending field and what it could have been.

    An LLM reads this to correct its own spec and retry.
    """
    return JSONResponse(status_code=422, content=exc.as_body())


@app.get("/semantic/metrics", response_model=Page[MetricInfo])
async def list_metrics() -> Page[MetricInfo]:
    items = semantic.metric_catalogue()
    return Page[MetricInfo](items=items, total=len(items), page=1, size=len(items))


@app.get("/semantic/dimensions", response_model=Page[DimensionInfo])
async def list_dimensions() -> Page[DimensionInfo]:
    items = semantic.dimension_catalogue()
    return Page[DimensionInfo](items=items, total=len(items), page=1, size=len(items))


@app.get("/semantic/dimensions/{dimension_id}/values", response_model=Page[DimensionValue])
async def list_dimension_values(
    con: Connection,
    dimension_id: str,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=1_000)] = 500,
) -> Page[DimensionValue]:
    if dimension_id not in DIMENSIONS_BY_ID:
        raise SpecError(
            "dimension_id", f"unknown dimension {dimension_id!r}",
            sorted(DIMENSIONS_BY_ID), "unknown_dimension",
        )
    items = semantic.dimension_values(con, dimension_id)
    start = (page - 1) * size
    return Page[DimensionValue](
        items=items[start : start + size], total=len(items), page=page, size=size
    )


@app.post("/query", response_model=QueryResponse,
          responses={422: {"model": SpecErrorResponse}})
async def post_query(con: Connection, spec: QuerySpec) -> QueryResponse:
    """Run a query spec. Rows always arrive with their context and caveats."""
    return QueryResponse(**semantic.run_query(con, spec))


@app.post("/query/records", response_model=RecordsResponse,
          responses={422: {"model": SpecErrorResponse}})
async def post_query_records(con: Connection, spec: QuerySpec) -> RecordsResponse:
    """The supporting fact rows behind a result, each with its source file."""
    return RecordsResponse(**semantic.run_records(con, spec))


@app.post("/query/narrative-facts", response_model=NarrativeFactsResponse,
          responses={422: {"model": SpecErrorResponse}})
async def post_narrative_facts(
    con: Connection, spec: QuerySpec
) -> NarrativeFactsResponse:
    """One precomputed bundle for a dashboard view: totals, movement, leaders,
    laggards, largest changes and anomalies, plus the caveats that apply.

    Pure SQL. The GenAI step writes prose from this and does no arithmetic.
    """
    return NarrativeFactsResponse(**semantic.run_narrative_facts(con, spec))
