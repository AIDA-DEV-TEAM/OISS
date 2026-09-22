"""The query spec: what a caller may send, validated against the registry.

Validation errors are machine-readable on purpose. An LLM that gets one back
must be able to see which field was wrong and what it could have said instead,
and retry without a human in the loop.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.semantic import registry
from app.semantic.registry import DIMENSIONS_BY_ID, METRICS_BY_ID


class SpecError(Exception):
    """A spec that is well-formed but asks for something the registry forbids."""

    def __init__(
        self,
        field: str,
        detail: str,
        allowed_values: Optional[list[str]] = None,
        code: str = "invalid_query_spec",
    ) -> None:
        super().__init__(detail)
        self.field = field
        self.detail = detail
        self.allowed_values = allowed_values or []
        self.code = code

    def as_body(self) -> dict[str, object]:
        return {
            "detail": self.detail,
            "code": self.code,
            "field": self.field,
            "allowed_values": self.allowed_values,
        }


class Filter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension: str
    op: Literal["eq", "in", "not_in", "between", "gte", "lte"] = "in"
    values: list[str] = Field(min_length=1)


class Period(BaseModel):
    """Inclusive agricultural-year range, e.g. 2022-23 to 2024-25."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_year: Optional[str] = Field(default=None, alias="from")
    to_year: Optional[str] = Field(default=None, alias="to")


class OrderBy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = "value"
    direction: Literal["asc", "desc"] = "desc"


class QuerySpec(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    metric: str
    dimensions: list[str] = Field(default_factory=list)
    filters: list[Filter] = Field(default_factory=list)
    period: Optional[Period] = None
    order_by: Optional[OrderBy] = None
    limit: int = Field(default=100, ge=1, le=5_000)
    include_records: bool = False


def validate_spec(spec: QuerySpec, known_values: dict[str, set[str]]) -> None:
    """Check a spec against the registry and the values actually in the data.

    Raises :class:`SpecError` naming the offending field and what was allowed.
    ``known_values`` maps a dimension id to its selectable values.
    """
    metric = METRICS_BY_ID.get(spec.metric)
    if metric is None:
        raise SpecError("metric", f"unknown metric {spec.metric!r}", registry.metric_ids(),
                        "unknown_metric")

    seen: set[str] = set()
    for dimension_id in spec.dimensions:
        if dimension_id not in DIMENSIONS_BY_ID:
            raise SpecError(
                "dimensions", f"unknown dimension {dimension_id!r}",
                registry.dimension_ids(), "unknown_dimension",
            )
        if dimension_id in seen:
            raise SpecError(
                "dimensions", f"dimension {dimension_id!r} is listed twice",
                sorted(set(spec.dimensions)), "duplicate_dimension",
            )
        seen.add(dimension_id)
        if dimension_id in metric.forbidden_dimensions:
            raise SpecError(
                "dimensions",
                f"metric {metric.id!r} consumes {dimension_id!r} and cannot be "
                "grouped by it",
                sorted(metric.allowed_dimensions), "dimension_consumed_by_metric",
            )
        if not metric.allows(dimension_id):
            raise SpecError(
                "dimensions",
                f"metric {metric.id!r} is not valid at {dimension_id!r} grain",
                sorted(metric.allowed_dimensions), "invalid_grain",
            )

    missing = metric.required_dimensions - seen
    if missing:
        raise SpecError(
            "dimensions",
            f"metric {metric.id!r} requires {sorted(missing)} as "
            f"{'a dimension' if len(missing) == 1 else 'dimensions'}",
            sorted(metric.required_dimensions), "missing_required_dimension",
        )

    # Scope rules: some dimensions must be pinned rather than averaged across.
    pinned = seen | {
        f.dimension for f in spec.filters if f.op in ("eq", "in")
    }
    unpinned = metric.requires_scope - pinned
    if unpinned:
        raise SpecError(
            "filters",
            f"metric {metric.id!r} requires {sorted(unpinned)} to be pinned: group "
            "by it, or filter it to specific values. Official and synthetic price "
            "series both exist and averaging across them is not meaningful.",
            sorted(metric.requires_scope), "unpinned_scope",
        )

    for index, filter_ in enumerate(spec.filters):
        field = f"filters[{index}]"
        dimension = DIMENSIONS_BY_ID.get(filter_.dimension)
        if dimension is None:
            raise SpecError(
                f"{field}.dimension", f"unknown dimension {filter_.dimension!r}",
                registry.dimension_ids(), "unknown_dimension",
            )
        if filter_.dimension not in metric.allowed_dimensions:
            raise SpecError(
                f"{field}.dimension",
                f"metric {metric.id!r} cannot be filtered by {filter_.dimension!r}",
                sorted(metric.allowed_dimensions), "invalid_filter_dimension",
            )
        if filter_.op == "eq" and len(filter_.values) != 1:
            raise SpecError(
                f"{field}.values", "op 'eq' takes exactly one value", None,
                "invalid_filter_values",
            )
        if filter_.op == "between" and len(filter_.values) != 2:
            raise SpecError(
                f"{field}.values", "op 'between' takes exactly two values", None,
                "invalid_filter_values",
            )
        allowed = known_values.get(filter_.dimension)
        # Range operators compare rather than match, so their operands need not
        # be existing values.
        if allowed is not None and filter_.op in ("eq", "in", "not_in"):
            unknown = [value for value in filter_.values if value not in allowed]
            if unknown:
                raise SpecError(
                    f"{field}.values",
                    f"unknown value(s) {unknown} for dimension {filter_.dimension!r}",
                    sorted(allowed)[:200], "unknown_filter_value",
                )

    # The relation must be able to serve every dimension asked for at once.
    requested = seen | {f.dimension for f in spec.filters}
    try:
        registry.relation_for(metric, requested)
    except KeyError as exc:
        raise SpecError(
            "dimensions",
            f"metric {metric.id!r} cannot serve {exc.args[0]} together with the "
            "other dimensions requested",
            sorted(metric.allowed_dimensions), "invalid_grain",
        ) from exc

    if spec.order_by is not None:
        allowed_order = {"value", *seen}
        if spec.order_by.field not in allowed_order:
            raise SpecError(
                "order_by.field",
                f"cannot order by {spec.order_by.field!r}; order by 'value' or a "
                "dimension in the query",
                sorted(allowed_order), "invalid_order_by",
            )

    if spec.period is not None:
        years = known_values.get("agri_year") or set()
        for bound, value in (("from", spec.period.from_year), ("to", spec.period.to_year)):
            if value is not None and not _looks_like_agri_year(value):
                raise SpecError(
                    f"period.{bound}",
                    f"{value!r} is not an agricultural year in the form YYYY-YY",
                    sorted(years)[:200], "invalid_period",
                )
        if (
            spec.period.from_year
            and spec.period.to_year
            and spec.period.from_year > spec.period.to_year
        ):
            raise SpecError(
                "period", "period 'from' is after period 'to'", None, "invalid_period",
            )


def _looks_like_agri_year(value: str) -> bool:
    parts = value.split("-")
    return (
        len(parts) == 2
        and len(parts[0]) == 4
        and len(parts[1]) == 2
        and parts[0].isdigit()
        and parts[1].isdigit()
    )
