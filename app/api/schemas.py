"""Pydantic request/response schemas. No ORM or dataframe leaks past this line."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

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
    rows_staged: int
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
