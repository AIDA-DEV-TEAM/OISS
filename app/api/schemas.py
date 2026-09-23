"""Pydantic request/response schemas. No ORM or dataframe leaks past this line."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, Optional, TypeVar

from pydantic import BaseModel, Field

from app.semantic.spec import QuerySpec

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """List response envelope used by every collection endpoint."""

    items: list[T]
    total: int
    page: int
    size: int


class ErrorResponse(BaseModel):
    detail: str
    code: str


class Health(BaseModel):
    status: str
    database: str
    database_present: bool
    fact_rows: dict[str, int]
    last_run_id: Optional[str] = None
    last_run_status: Optional[str] = None
    # The version the database was built at (analytics.schema_meta).
    schema_version: Optional[int] = None


class ActivationResult(BaseModel):
    """Which version now feeds the facts for a dataset."""

    dataset_name: str
    activated: Optional[str] = None
    deactivated: list[str] = Field(default_factory=list)


class DatasetVersion(BaseModel):
    dataset_version_id: str
    dataset_name: str
    source_file: str
    source_type: str
    sha256: str
    row_count: int
    layer: str
    loaded_at: datetime
    generator_version: Optional[str] = None
    is_active: bool = Field(
        default=True,
        description="Whether queries count this version. Exactly one version "
        "per dataset is active; an upload starts inactive.",
    )


class ValidationFinding(BaseModel):
    run_id: str
    dataset_version_id: str
    rule_code: str
    severity: str
    row_ref: Optional[str] = None
    column_name: Optional[str] = None
    message: Optional[str] = None
    observed_value: Optional[str] = None


class LineageEdge(BaseModel):
    from_node: str
    to_node: str
    edge_type: str
    dataset_version_id: str


class Lineage(BaseModel):
    dataset_version_id: str
    dataset_name: str
    source_file: str
    edges: list[LineageEdge]


class RuleCount(BaseModel):
    rule_code: str
    severity: str
    count: int


class IngestResult(BaseModel):
    """Outcome of POST /ingest/upload -- findings, never an exception."""

    run_id: str
    dataset_name: str
    dataset_version_id: str
    filename: str
    data_origin: str
    rows_read: int
    rows_staged: int = Field(
        description="Rows written to the upload's staging table; 0 when nothing was staged."
    )
    rows_promoted: int = Field(
        default=0,
        description="Rows appended to the analytics fact table under this version.",
    )
    rows_quarantined: int
    error_count: int
    warning_count: int
    info_count: int
    findings_by_rule: list[RuleCount]
    findings: list[ValidationFinding] = Field(
        description="Capped at findings_limit; the full set is queryable at "
        "/datasets/{dataset_version_id}/validation"
    )
    quarantine_table: Optional[str] = None
    staging_table: Optional[str] = None
    promoted_to: Optional[str] = None
    duplicate_of: Optional[str] = Field(
        default=None,
        description="Set when these exact bytes are already loaded. Nothing was "
        "written: the named version already describes this content.",
    )
    duplicate_layer: Optional[str] = Field(
        default=None, description="Which layer created the version already holding it."
    )


# --------------------------------------------------------------------------
# Semantic layer
# --------------------------------------------------------------------------
class MetricInfo(BaseModel):
    metric_id: str
    label: str
    unit: str
    definition: str
    allowed_dimensions: list[str]
    required_dimensions: list[str]
    forbidden_dimensions: list[str]
    requires_scope: list[str]
    default_aggregation: str
    facts: list[str]


class DimensionInfo(BaseModel):
    dimension_id: str
    label: str
    description: str
    value_type: str
    is_coded: bool
    available_on: list[str]


class DimensionValue(BaseModel):
    value: str
    label: str


class SourceDataset(BaseModel):
    dataset_version_id: str
    dataset_name: str
    source_file: str
    layer: str


class AppliedContext(BaseModel):
    """What was asked, what was read, and how much of it."""

    metric: str
    metric_label: str
    unit: str
    dimensions: list[str]
    filters: list[dict[str, Any]]
    period: Optional[dict[str, Any]] = None
    relation: str
    source_datasets: list[SourceDataset]
    data_origin: dict[str, int]
    grain_source: dict[str, int] = Field(default_factory=dict)
    row_count: int
    underlying_row_count: int
    generated_at: str
    # The panel-level disclosure wording for this result, derived from
    # data_origin and grain_source. The UI renders these lines; an export
    # writes the same ones into the file.
    provenance_notes: list[str] = Field(default_factory=list)


class Caveat(BaseModel):
    code: str
    severity: str
    message: str
    affected_rows: int


class QueryResponse(BaseModel):
    rows: list[dict[str, Any]]
    applied_context: AppliedContext
    caveats: list[Caveat]
    records: Optional[list[dict[str, Any]]] = None


class RecordsResponse(BaseModel):
    """Drill-down: the fact rows behind a result cell."""

    records: list[dict[str, Any]]
    returned: int
    total_matching: int
    truncated: bool
    source_datasets: list[SourceDataset]


class NarrativeFactsResponse(BaseModel):
    """Everything a narrative may assert, precomputed so the LLM does no maths."""

    headline: dict[str, Any]
    movement: Optional[dict[str, Any]] = None
    leaders: list[dict[str, Any]]
    laggards: list[dict[str, Any]]
    largest_changes: list[dict[str, Any]]
    anomalies: list[dict[str, Any]]
    applied_context: AppliedContext
    caveats: list[Caveat]


class SpecErrorResponse(BaseModel):
    """422 body: machine-readable so a caller can correct itself and retry."""

    detail: str
    code: str
    field: str
    allowed_values: list[str]


class LayerStage(BaseModel):
    """One hop of a dataset's journey through the storage layers."""

    layer: str
    label: str
    table: Optional[str] = None
    row_count: int
    purpose: str
    transition: str


class IngestSchema(BaseModel):
    """The declared shape an uploaded file is validated against.

    Lets the ingest screen match a file's own header to the right dataset
    instead of guessing, so a mismatch is reported rather than stumbled into.
    """

    dataset_name: str
    source_type: str
    expected_columns: list[str]


class RuleSummary(BaseModel):
    """Findings for one rule within one dataset version."""

    rule_code: str
    severity: str
    finding_count: int
    sample_row_ref: Optional[str] = None
    sample_message: Optional[str] = None
    column_count: int


# --------------------------------------------------------------------------
# Exports (RFP area 8)
# --------------------------------------------------------------------------
class ExportOptions(BaseModel):
    """What the caller wants inside the file."""

    include_context: bool = True
    include_caveats: bool = True
    include_records: bool = True


class ExportPayload(BaseModel):
    """Rows and context for a surface that has no query spec yet.

    The assistant and the sandbox are still fixture-backed, so their exports
    cannot be reproduced from a spec. A file built this way says so.
    """

    rows: list[dict[str, Any]] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    caveats: list[Caveat] = Field(default_factory=list)


class ExportedContext(BaseModel):
    """The context written into an export file and shown on the Exports screen.

    A superset of :class:`AppliedContext`: it adds what the file needs and the
    query does not have -- which panel asked, how the context was obtained, the
    disclosure lines, the caveats and a period phrase a reader can read. Every
    field is optional except the panel, because an export of a surface with no
    query spec has fewer of them and must not pretend otherwise.
    """

    panel_title: str
    metric: Optional[str] = None
    metric_label: Optional[str] = None
    unit: Optional[str] = None
    dimensions: list[str] = Field(default_factory=list)
    filters: list[dict[str, Any]] = Field(default_factory=list)
    period: Optional[dict[str, Any]] = None
    # The same range as `period`, phrased once here rather than in each reader.
    period_label: Optional[str] = None
    relation: Optional[str] = None
    source_datasets: list[SourceDataset] = Field(default_factory=list)
    data_origin: dict[str, int] = Field(default_factory=dict)
    grain_source: dict[str, int] = Field(default_factory=dict)
    row_count: int = 0
    underlying_row_count: int = 0
    truncated: bool = False
    matching_row_count: Optional[int] = None
    provenance_notes: list[str] = Field(default_factory=list)
    caveats: list[Caveat] = Field(default_factory=list)
    # "derived" when this service ran the query itself; otherwise it names the
    # fact that the calling surface supplied it.
    context_origin: str = "derived"
    generated_at: Optional[str] = None
    # For model output: the configuration of the model behind the rows.
    model_configurations: list[dict[str, str]] = Field(default_factory=list)


class ExportRequest(BaseModel):
    export_type: Literal[
        "dashboard_panel", "records_grid", "assistant_answer", "model_output", "narrative"
    ]
    format: Literal["csv", "xlsx", "pdf", "json", "png"]
    panel_title: str = Field(min_length=1, max_length=200)
    # Preferred: the service runs this itself, so the file's context describes
    # the rows in the file rather than whatever the caller believed.
    query_spec: Optional[QuerySpec] = None
    payload: Optional[ExportPayload] = None
    options: ExportOptions = Field(default_factory=ExportOptions)


class ExportLimits(BaseModel):
    """Limits the export service enforces."""

    row_ceiling: int


class ExportRecord(BaseModel):
    """One produced file, with the context it carries."""

    export_id: str
    export_type: str
    format: str
    status: str
    filename: str
    size_bytes: int
    created_at: str
    context: ExportedContext


# --------------------------------------------------------------------------
# Sandbox and Crop Yield Forecasting (RFP areas 6 and 7)
# --------------------------------------------------------------------------
class StatedText(BaseModel):
    """A value the model service stated, and the endpoint that stated it.
    Both None when the service does not state it: shown as not stated."""

    value: Optional[str] = None
    source: Optional[str] = None


class ModelFeature(BaseModel):
    name: str
    type: str
    description: str


class StatedFeatures(BaseModel):
    value: list[ModelFeature]
    source: str


class StatedDomains(BaseModel):
    """The /metadata lists that bound what the model accepts. Input domains,
    not features: the features are the /predict request fields."""

    value: dict[str, Any]
    source: str


class ModelConfig(BaseModel):
    service_url: str
    fetched_at: str
    model_name: StatedText
    target: StatedText
    model_version: StatedText
    training_period: StatedText
    features: StatedFeatures
    input_domains: StatedDomains


class SandboxUseCase(BaseModel):
    id: str
    label: str
    description: str
    # Why the use case is fixed rather than chosen.
    fixed_reason: str


class SandboxModelConfig(BaseModel):
    # False when the service could not be read; `message` says why.
    checked: bool
    message: Optional[str] = None
    config: Optional[ModelConfig] = None
    config_hash: Optional[str] = None
    use_case: SandboxUseCase


class MissingField(BaseModel):
    field: str
    reason: str


class DomainCount(BaseModel):
    reason: str
    count: int


class InputSummary(BaseModel):
    """A dataset's combinations checked against the model's input domains."""

    agri_years: list[str]
    combinations: int
    sent: int
    out_of_domain: list[DomainCount]
    rule: str


class SandboxDataset(BaseModel):
    dataset_id: str
    label: str
    years: str
    # Fact rows this dataset holds in the database, counted by query.
    row_count: int
    # None when the model service could not be read to check it.
    compatible: Optional[bool] = None
    missing_fields: list[MissingField]
    input_summary: Optional[InputSummary] = None


class SandboxDatasetList(BaseModel):
    items: list[SandboxDataset]
    total: int
    page: int
    size: int
    model_checked: bool
    message: Optional[str] = None


class CreateRunRequest(BaseModel):
    dataset_id: str
    use_case: Literal["minor_crop_yield"] = "minor_crop_yield"


class SandboxRunStatus(BaseModel):
    run_id: str
    status: Literal["queued", "running", "completed", "completed_with_warnings", "failed"]
    progress: int
    message: str
    # Why a failed run failed: MODEL_SERVICE_UNAVAILABLE, MODEL_SERVICE_REJECTED,
    # MODEL_SERVICE_ERROR, DATASET_INCOMPATIBLE, NO_INPUTS_IN_DOMAIN,
    # STORAGE_FAILED, MALFORMED_RESPONSE.
    error_code: Optional[str] = None


class MetricSet(BaseModel):
    # None when it cannot be computed: fewer than two held-out records, or no
    # variance in the actuals. A missing R² is a gap, never a zero.
    r2: Optional[float] = None
    rmse: float
    mae: float
    n: int


class PerCropMetric(MetricSet):
    crop_id: str
    crop_name: str


class ActualVsPredicted(BaseModel):
    district_name: str
    crop_name: str
    actual: float
    predicted: float
    residual: float


class FeatureImportance(BaseModel):
    feature: str
    label: str
    weight: float


class PredictionRow(BaseModel):
    district_id: str
    district_name: str
    crop_id: str
    crop_name: str
    season: str
    agri_year: str
    area_ha: float
    predicted_yield_qtl_per_ha: float
    estimated_production_qtls: float
    output_label: str = "Analytical Estimates"
    # The yield DE&S published for the same district, crop, season and year;
    # None where none was published.
    actual_yield_qtl_per_ha: Optional[float] = None


class SandboxResults(BaseModel):
    run_id: str
    status: Literal["completed", "completed_with_warnings"]
    # What could not be produced, and why. The matching sections are empty.
    warnings: list[str]
    # None when the held-out comparison could not be fetched: shown as a dash.
    pooled: Optional[MetricSet] = None
    per_crop: list[PerCropMetric]
    actual_vs_predicted: list[ActualVsPredicted]
    feature_importance: list[FeatureImportance]
    explanation: str
    predictions: list[PredictionRow]
    data_origin: dict[str, int]
    served_from_cache: bool = False
    # The live run these results were replayed from, when served_from_cache,
    # and when that run was made.
    replayed_from: Optional[str] = None
    replayed_run_at: Optional[str] = None
    # The model the estimates came from. For a replay, the replayed run's.
    model_configuration: Optional[ModelConfig] = None
    model_config_hash: Optional[str] = None
    # False when the service could not be read to confirm its current model.
    model_checked: bool
    input_summary: Optional[InputSummary] = None
    agri_years: list[str]
    # "Model estimate vs published <year> actual" unless the service states a
    # training period that ends before the year.
    comparison_label: str


class SaveVersionRequest(BaseModel):
    label: str


class SandboxVersion(BaseModel):
    version_id: str
    run_id: str
    label: str
    created_at: str
    published: bool
    parameters: dict[str, str]


class PublishVersionResponse(BaseModel):
    version_id: str
    published: bool = True


class PublishedForecast(BaseModel):
    crop_id: str
    crop_name: str
    district_id: str
    district_name: str
    season: str
    agri_year: str
    actual_yield: Optional[float] = None
    forecast_yield: float
    unit: str = "qtl/ha"
    version_id: str
    output_label: str = "Analytical Estimates"
    model_config_hash: Optional[str] = None
    data_origin: dict[str, int]



# --------------------------------------------------------------------------
# Assistant (RFP area 5)
# --------------------------------------------------------------------------
class StarterQuestion(BaseModel):
    question_id: str
    question: str


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class DescribedFilter(BaseModel):
    """A filter as applied, with the master's display names beside its codes."""

    dimension: str
    op: str
    values: list[str]
    dimension_label: str
    values_display: list[str]


class DimensionRef(BaseModel):
    id: str
    label: str


class Interpretation(BaseModel):
    """How the question was read: the query the model chose, after validation."""

    metric: str
    metric_label: str
    unit: str
    dimensions: list[DimensionRef]
    filters: list[DescribedFilter]
    period: Optional[str] = None
    order: Optional[str] = None
    limit: int
    # True when the first reading was rejected and the model corrected it.
    corrected: bool
    # What produced the reading: a model name, or "fixture" for a recorded reply.
    model: str


class ChartSpec(BaseModel):
    kind: Literal["bar", "line"]
    x_key: str
    y_key: str
    unit: str
    series_label: str
    data: list[dict[str, Any]]


class LlmCall(BaseModel):
    purpose: str
    model: str
    served_from_cache: bool
    outcome: Literal["ok", "unavailable", "error"]
    error: Optional[str] = None


class AssistantAnswer(BaseModel):
    question: str
    # answered: rows and a validated answer. declined: the data cannot answer it.
    # unavailable: no model could be reached to interpret a question not asked before.
    status: Literal["answered", "declined", "unavailable"]
    answer: str
    # model: prose that passed the number check. template: rendered from the rows.
    answer_source: Optional[Literal["model", "template"]] = None
    limitation: Optional[str] = None
    interpretation: Optional[Interpretation] = None
    # The validated spec that produced the rows; an export re-runs it.
    query_spec: Optional[QuerySpec] = None
    chart_spec: Optional[ChartSpec] = None
    applied_filters: list[DescribedFilter]
    source_datasets: list[SourceDataset]
    period: Optional[str] = None
    rows: list[dict[str, Any]]
    records_preview: list[dict[str, Any]]
    records_total: int
    caveats: list[Caveat]
    applied_context: Optional[AppliedContext] = None
    data_origin: dict[str, int]
    grain_source: dict[str, int]
    provenance_notes: list[str]
    llm_calls: list[LlmCall]
    served_from_cache: bool


# --------------------------------------------------------------------------
# Dashboard narrative (RFP area 4)
# --------------------------------------------------------------------------
class NarrativeRequest(BaseModel):
    # The view's own query; the narrative describes exactly what it selects.
    query_spec: QuerySpec


class NarrativeFact(BaseModel):
    """One figure the narrative may quote, computed in SQL."""

    label: str
    value: Optional[float] = None
    unit: str
    scope: Optional[str] = None


class DashboardNarrative(BaseModel):
    narrative: str
    # model: prose that passed the number check. template: rendered from the facts.
    narrative_source: Literal["model", "template"]
    # The model that wrote it (or "fixture"); absent for a template.
    model: Optional[str] = None
    facts_used: list[NarrativeFact]
    caveats: list[Caveat]
    applied_context: AppliedContext
    data_origin: dict[str, int]
    served_from_cache: bool
    llm_calls: list[LlmCall]
