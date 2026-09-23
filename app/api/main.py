"""FastAPI app for the OISS PoC data layer.

Routes are thin: they validate input, call :mod:`app.api.service` and shape the
response. No business logic here.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Optional

import duckdb
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from app import db
from app.api import service
from app.assistant import service as assistant
from app.narrative import service as narrative
from app.exports import service as exports
from app.api.schemas import (
    AskRequest,
    AssistantAnswer,
    DashboardNarrative,
    NarrativeRequest,
    StarterQuestion,
    DatasetVersion,
    DimensionInfo,
    DimensionValue,
    ErrorResponse,
    ExportLimits,
    ExportRecord,
    ExportRequest,
    Health,
    ActivationResult,
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
    SandboxDatasetList,
    SandboxModelConfig,
    CreateRunRequest,
    SandboxRunStatus,
    SandboxResults,
    SaveVersionRequest,
    SandboxVersion,
    PublishVersionResponse,
    PublishedForecast,
)
from app.semantic import service as semantic
from app.semantic.registry import DIMENSIONS_BY_ID
from app.semantic.spec import QuerySpec, SpecError
from app.config import DB_PATH
from app.sandbox.client import ModelServiceError
from app.sandbox import service as sandbox_service
from app.sandbox.service import SandboxError
from app.llm.provider import Provider, build_provider

app = FastAPI(
    title="OISS PoC data layer",
    version="0.1.0",
    description=(
        "Odisha Integrated Statistical System proof of concept: ingestion, "
        "validation, lineage and versioning over DE&S published data."
    ),
)

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 64 * 1024 * 1024

# What each generated export is served as. A browser that is told the truth
# about the type opens a PDF and downloads a workbook, which is what a user
# expects of each.
MEDIA_TYPES = {
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
    "json": "application/json",
    "png": "image/png",
}


class DataError(Exception):
    """A client-visible problem with the request, carrying a stable code."""

    def __init__(
        self,
        status_code: int,
        code: str,
        detail: str,
        field: str | None = None,
        allowed_values: list[str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail
        # A rejected field names itself, so a caller can correct it without
        # guessing which of its inputs was wrong.
        self.field = field
        self.allowed_values = allowed_values


@app.exception_handler(DataError)
async def data_error_handler(request: Request, exc: DataError) -> JSONResponse:
    body = ErrorResponse(detail=exc.detail, code=exc.code).model_dump()
    if exc.field:
        body["field"] = exc.field
    if exc.allowed_values:
        body["allowed_values"] = exc.allowed_values
    return JSONResponse(status_code=exc.status_code, content=body)


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


@app.exception_handler(ModelServiceError)
async def model_service_error_handler(request: Request, exc: ModelServiceError) -> JSONResponse:
    """Translate ModelServiceError into standard ErrorResponse format."""
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(detail=exc.detail, code=exc.code).model_dump(),
    )


@app.exception_handler(SandboxError)
async def sandbox_error_handler(request: Request, exc: SandboxError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(detail=exc.detail, code=exc.code).model_dump(),
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """No bare 500s: a structured error, with the details in the server log only."""
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            detail="The server hit an unexpected error; the server log has the details.",
            code="INTERNAL_ERROR",
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


@app.on_event("startup")
async def _check_schema_version() -> None:
    """Refuse to start against a database built for another schema version.

    Without this an old database serves until a request touches a changed
    table, and then fails with a 500. A missing database is left to the
    existing 503 on each request, so the backend can start before a build.
    """
    path = app.dependency_overrides.get(database_path, database_path)()
    if not path.exists():
        return
    try:
        db.check_schema_version(get_connection(path))
    except db.SchemaMismatch as mismatch:
        logger.error("%s", mismatch)
        close_connections()
        raise


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


@app.post("/datasets/{dataset_version_id}/activate", response_model=ActivationResult)
async def activate_version(con: Connection, dataset_version_id: str) -> ActivationResult:
    """Make this version the one queries count for its dataset."""
    result = service.set_active_version(con, dataset_version_id, True)
    if result is None:
        raise DataError(404, "dataset_not_found", f"no dataset version {dataset_version_id!r}")
    return ActivationResult(**result)


@app.post("/datasets/{dataset_version_id}/deactivate", response_model=ActivationResult)
async def deactivate_version(con: Connection, dataset_version_id: str) -> ActivationResult:
    """Stop counting this version, returning the dataset to the build's."""
    result = service.set_active_version(con, dataset_version_id, False)
    if result is None:
        raise DataError(404, "dataset_not_found", f"no dataset version {dataset_version_id!r}")
    return ActivationResult(**result)


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
    file: Annotated[UploadFile, File()],
    dataset_name: Annotated[str, Form()] = "",
    data_origin: Annotated[str, Form()] = "",
) -> IngestResult:
    """Validate an uploaded file against a known dataset's schema and rules.

    An empty ``dataset_name`` means the file matches no declared schema: it is
    still read and validated, for the problems that hold for any table.

    Bad rows are quarantined and reported; the request succeeds regardless, so
    the demo can show findings rather than an error page.
    """
    content = await file.read()
    if not content:
        raise DataError(400, "empty_file", "the uploaded file is empty")
    if not dataset_name:
        # An unregistered file has no dataset definition to take this from, and
        # data_origin is never defaulted: the uploader declares it.
        if data_origin not in {"official", "synthetic"}:
            raise DataError(
                422,
                "data_origin_required",
                "data_origin must be 'official' or 'synthetic' for a file that "
                "matches no registered dataset",
                field="data_origin",
                allowed_values=["official", "synthetic"],
            )
    if len(content) > MAX_UPLOAD_BYTES:
        raise DataError(413, "payload_too_large", "the uploaded file is too large")
    try:
        result = service.ingest_upload(
            con, dataset_name, file.filename or "upload", content, data_origin or None
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


# --------------------------------------------------------------------------
# Exports (RFP area 8)
# --------------------------------------------------------------------------
@app.post("/export", response_model=ExportRecord, status_code=201,
          responses={422: {"model": SpecErrorResponse}})
async def create_export(con: Connection, request: ExportRequest) -> ExportRecord:
    """Produce a file and record it, synchronously.

    A request carrying a query spec has its context derived from running that
    spec here; one carrying an inline payload says so inside the file.
    """
    if request.query_spec is None and request.payload is None:
        raise DataError(
            422,
            "export_source_required",
            "an export needs either a query_spec or a payload",
            field="query_spec",
        )
    payload = request.payload
    try:
        record = exports.create_export(
            con,
            export_type=request.export_type,
            fmt=request.format,
            panel_title=request.panel_title,
            query_spec=request.query_spec,
            rows=payload.rows if payload else None,
            context=payload.context if payload else None,
            caveats=[c.model_dump() for c in payload.caveats] if payload else None,
            include_context=request.options.include_context,
            include_caveats=request.options.include_caveats,
            include_records=request.options.include_records,
        )
    except exports.ExportError as error:
        raise DataError(400, error.code, error.detail) from error
    return ExportRecord(**record)


@app.get("/exports/limits", response_model=ExportLimits)
async def get_export_limits() -> ExportLimits:
    """The row ceiling, so the export dialog warns with the figure that applies."""
    return ExportLimits(**exports.limits())


@app.get("/exports", response_model=Page[ExportRecord])
async def list_exports(
    con: Connection,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page[ExportRecord]:
    items = exports.list_exports(con)
    start = (page - 1) * size
    return Page[ExportRecord](
        items=[ExportRecord(**item) for item in items[start : start + size]],
        total=len(items),
        page=page,
        size=size,
    )


@app.get("/export/{export_id}", response_model=ExportRecord)
async def get_export(con: Connection, export_id: str) -> ExportRecord:
    record = exports.get_export(con, export_id)
    if record is None:
        raise DataError(404, "export_not_found", f"no export {export_id!r}")
    return ExportRecord(**record)


@app.get("/export/{export_id}/download")
async def download_export(con: Connection, export_id: str) -> FileResponse:
    """The file itself, named as it was generated."""
    record = exports.get_export(con, export_id)
    if record is None:
        raise DataError(404, "export_not_found", f"no export {export_id!r}")
    path = exports.export_file(con, export_id)
    if path is None:
        raise DataError(
            410, "export_file_missing",
            f"export {export_id!r} is recorded but its file is no longer on disk",
        )
    return FileResponse(path, filename=record["filename"], media_type=MEDIA_TYPES[record["format"]])


# --------------------------------------------------------------------------
# Sandbox & Forecasting (Task 7)
# --------------------------------------------------------------------------
@app.get("/sandbox/model-config", response_model=SandboxModelConfig)
async def get_sandbox_model_config() -> SandboxModelConfig:
    """The model configuration as the model service states it, each field sourced."""
    return SandboxModelConfig(**await run_in_threadpool(sandbox_service.get_model_config))


@app.get("/sandbox/datasets", response_model=SandboxDatasetList)
async def list_sandbox_datasets(con: Connection) -> SandboxDatasetList:
    """Every dataset, with its compatibility against the model's request."""
    cursor = con.cursor()
    try:
        listing = await run_in_threadpool(sandbox_service.list_datasets, cursor)
    finally:
        cursor.close()
    return SandboxDatasetList(**listing)


@app.post("/sandbox/runs", response_model=SandboxRunStatus, status_code=201)
async def create_sandbox_run(con: Connection, request: CreateRunRequest) -> SandboxRunStatus:
    """Run the pre-trained model over a dataset; returns when the run has ended.

    Several hundred model calls take a while, so they run off the event loop on
    their own cursor. This is not a background job: the request waits.
    """
    cursor = con.cursor()
    try:
        res = await run_in_threadpool(sandbox_service.create_run, cursor, request.model_dump())
        status = sandbox_service.get_run_status(cursor, res["run_id"])
    finally:
        cursor.close()
    return SandboxRunStatus(**status)


@app.get("/sandbox/runs/{run_id}", response_model=SandboxRunStatus)
async def get_sandbox_run_status(con: Connection, run_id: str) -> SandboxRunStatus:
    """Check the status and progress of a sandbox run."""
    status = sandbox_service.get_run_status(con, run_id)
    return SandboxRunStatus(**status)


@app.get("/sandbox/runs/{run_id}/results", response_model=SandboxResults)
async def get_sandbox_run_results(con: Connection, run_id: str) -> SandboxResults:
    """Retrieve full evaluation metrics, feature importance, and sample predictions."""
    results = sandbox_service.get_run_results(con, run_id)
    return SandboxResults(**results)


@app.post("/sandbox/runs/{run_id}/versions", response_model=SandboxVersion, status_code=201)
async def save_sandbox_version(con: Connection, run_id: str, request: SaveVersionRequest) -> SandboxVersion:
    """Save a run as a named model version for governance."""
    ver = sandbox_service.save_version(con, run_id, request.label)
    return SandboxVersion(**ver)


@app.post("/sandbox/versions/{version_id}/publish", response_model=PublishVersionResponse)
async def publish_sandbox_version(con: Connection, version_id: str) -> PublishVersionResponse:
    """Publish a model version's forecasts to the dashboard and record lineage."""
    res = sandbox_service.publish_version(con, version_id)
    return PublishVersionResponse(**res)


@app.get("/dashboard/forecasts", response_model=list[PublishedForecast])
async def get_dashboard_forecasts(con: Connection) -> list[PublishedForecast]:
    """Retrieve published crop-yield forecasts with actual-vs-forecast comparison."""
    return [PublishedForecast(**fc) for fc in sandbox_service.get_dashboard_forecasts(con)]


# --------------------------------------------------------------------------
# Assistant (RFP area 5)
# --------------------------------------------------------------------------
def get_llm_provider() -> Provider:
    """The configured model behind the response cache; overridden in tests."""
    return build_provider()


LlmProvider = Annotated[Provider, Depends(get_llm_provider)]


@app.get("/assistant/questions", response_model=Page[StarterQuestion])
async def list_assistant_questions() -> Page[StarterQuestion]:
    """Starter questions, answered from the shipped cache with no API key."""
    items = assistant.starter_questions()
    return Page[StarterQuestion](items=items, total=len(items), page=1, size=len(items))


@app.post("/assistant/ask", response_model=AssistantAnswer)
async def ask_assistant(
    con: Connection, provider: LlmProvider, request: AskRequest
) -> AssistantAnswer:
    """A free-text question, answered from the loaded data or declined.

    A model call can take seconds, so it runs off the event loop on its own
    cursor rather than holding every other request behind it.
    """
    cursor = con.cursor()
    try:
        answer = await run_in_threadpool(assistant.ask, cursor, request.question, provider)
    finally:
        cursor.close()
    return AssistantAnswer(**answer)


@app.post("/narrative/dashboard", response_model=DashboardNarrative,
          responses={422: {"model": SpecErrorResponse}})
async def dashboard_narrative(
    con: Connection, provider: LlmProvider, request: NarrativeRequest
) -> DashboardNarrative:
    """"What this view shows": prose over the view's SQL fact bundle.

    Written by the model when one is available and its figures check out;
    otherwise rendered from the same facts by a template, and labelled so.
    """
    cursor = con.cursor()
    try:
        result = await run_in_threadpool(narrative.narrate, cursor, request.query_spec, provider)
    finally:
        cursor.close()
    return DashboardNarrative(**result)
