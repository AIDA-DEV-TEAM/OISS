"""The semantic registry: the only vocabulary a caller may use.

Nothing downstream writes SQL. A caller -- eventually an LLM -- names a metric,
some dimensions and some filters; this module says what those names mean and
what is allowed, and :mod:`app.semantic.compiler` turns the result into
parameterised SQL. A name that is not here is rejected, never guessed at.

Two rules carry most of the weight:

* ``yield_rate`` is a ratio of sums, never a mean of published yields. A mean
  would weight a 50 ha block the same as a 5,000 ha one.
* Every metric declares the grains it is valid at. Asking for ``avg_price`` by
  block is refused rather than silently answered with district figures.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Dimension:
    """A column a caller may group or filter by."""

    id: str
    label: str
    description: str
    # Column holding the value the caller supplies in a filter.
    key_column: str
    # Column holding the human-readable label returned in rows.
    label_column: str
    value_type: str = "string"

    @property
    def is_coded(self) -> bool:
        return self.key_column != self.label_column


DIMENSIONS: tuple[Dimension, ...] = (
    Dimension("district", "District", "One of the 30 districts of Odisha",
              "district_id", "district_name"),
    Dimension("block", "Block", "Block within a district; block-grain data exists "
              "for paddy and land use only", "block_id", "block_name"),
    Dimension("crop", "Crop", "Crop from the crop master", "crop_id", "crop_name"),
    Dimension("crop_group", "Crop group",
              "cereal, pulse, oilseed, fibre, tuber, vegetable or sugar",
              "crop_group", "crop_group"),
    Dimension("season", "Season", "Autumn, Winter, Summer or Total",
              "season", "season"),
    Dimension("agri_year", "Agricultural year", "July to June, written YYYY-YY",
              "agri_year", "agri_year"),
    Dimension("month", "Month", "Calendar month, written YYYY-MM; monthly price "
              "series only", "month", "month"),
    Dimension("price_type", "Price type", "farm_harvest or wholesale",
              "price_type", "price_type"),
    Dimension("land_use_category", "Land use category",
              "One of the published land-use categories",
              "land_use_category", "land_use_category"),
    Dimension("product", "Product", "paddy, rice or minor", "product", "product"),
    Dimension("data_origin", "Data origin", "official (published by DE&S) or "
              "synthetic (generated for the demo)", "data_origin", "data_origin"),
    Dimension("grain_source", "Grain source",
              "published_district, published_block, published_state or aggregated_from_blocks",
              "grain_source", "grain_source"),
)

DIMENSIONS_BY_ID: dict[str, Dimension] = {d.id: d for d in DIMENSIONS}


# --------------------------------------------------------------------------
# Relations
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Relation:
    """A queryable view plus the dimensions it actually carries."""

    name: str
    dimensions: frozenset[str]
    measure_column: Optional[str] = None
    # Always applied. The crop reports publish per-season rows *and* a Total row
    # that repeats their sum, so querying both would double every figure.
    base_predicate: Optional[str] = None


RELATIONS: dict[str, Relation] = {
    "price": Relation(
        "analytics.v_price",
        frozenset({"district", "crop", "crop_group", "price_type", "agri_year",
                   "month", "data_origin"}),
    ),
    "crop_ayp_district": Relation(
        "analytics.v_district_crop_ayp",
        frozenset({"district", "crop", "crop_group", "season", "agri_year",
                   "product", "data_origin", "grain_source"}),
        measure_column="measure",
        base_predicate="period_type = 'season'",
    ),
    "crop_ayp_block": Relation(
        "analytics.v_block_crop_ayp",
        frozenset({"district", "block", "crop", "crop_group", "season", "agri_year",
                   "product", "data_origin", "grain_source"}),
        measure_column="measure",
        base_predicate="period_type = 'season'",
    ),
    "crop_ayp_state": Relation(
        "analytics.v_state_crop_ayp",
        frozenset({"crop", "crop_group", "season", "agri_year",
                   "product", "data_origin", "grain_source"}),
        measure_column="measure",
        base_predicate="season <> 'Total'",
    ),
    "land_use": Relation(
        "analytics.v_land_use",
        frozenset({"district", "block", "land_use_category", "agri_year",
                   "data_origin", "grain_source"}),
        measure_column="measure",
    ),
}


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Metric:
    """One thing a caller may ask for, and the rules for asking."""

    id: str
    label: str
    unit: str
    definition: str
    # Relation keys this metric can read, in preference order. More than one
    # means the compiler picks by the grain the caller asked for.
    relations: tuple[str, ...]
    allowed_dimensions: frozenset[str]
    default_aggregation: str
    # Dimensions that must appear for the metric to be computable.
    required_dimensions: frozenset[str] = field(default_factory=frozenset)
    # Dimensions the metric consumes and therefore cannot be grouped by.
    forbidden_dimensions: frozenset[str] = field(default_factory=frozenset)
    # Dimensions that must be pinned -- grouped by, or filtered to specific
    # values -- because blending across them would be meaningless.
    requires_scope: frozenset[str] = field(default_factory=frozenset)
    facts: tuple[str, ...] = ()

    def allows(self, dimension_id: str) -> bool:
        return dimension_id in self.allowed_dimensions


_PRICE_DIMENSIONS = frozenset(
    {"district", "crop", "crop_group", "price_type", "agri_year", "month", "data_origin"}
)
_AYP_DIMENSIONS = frozenset(
    {"district", "block", "crop", "crop_group", "season", "agri_year", "product",
     "data_origin", "grain_source"}
)

METRICS: tuple[Metric, ...] = (
    Metric(
        "avg_price", "Average price", "Rs/quintal",
        "Mean price over the selected period and grain.",
        ("price",), _PRICE_DIMENSIONS, "avg",
        requires_scope=frozenset({"data_origin"}), facts=("fact_price",),
    ),
    Metric(
        "price_yoy_pct", "Price change year on year", "%",
        "Year-on-year change in avg_price. Requires agri_year as a dimension.",
        ("price",), _PRICE_DIMENSIONS - {"month"}, "avg",
        required_dimensions=frozenset({"agri_year"}),
        requires_scope=frozenset({"data_origin"}), facts=("fact_price",),
    ),
    Metric(
        "fhp_wholesale_gap", "Wholesale minus farm harvest price", "Rs/quintal",
        "Wholesale price minus farm harvest price for the same district, crop "
        "and year.",
        ("price",), _PRICE_DIMENSIONS - {"price_type"}, "avg",
        forbidden_dimensions=frozenset({"price_type"}),
        requires_scope=frozenset({"data_origin"}), facts=("fact_price",),
    ),
    Metric(
        "fhp_wholesale_gap_pct", "Wholesale premium over farm harvest price", "%",
        "fhp_wholesale_gap as a share of the farm harvest price.",
        ("price",), _PRICE_DIMENSIONS - {"price_type"}, "avg",
        forbidden_dimensions=frozenset({"price_type"}),
        requires_scope=frozenset({"data_origin"}), facts=("fact_price",),
    ),
    Metric(
        "area", "Crop area", "ha", "Area under the crop.",
        ("crop_ayp_district", "crop_ayp_block", "crop_ayp_state"), _AYP_DIMENSIONS, "sum",
        facts=("fact_crop_ayp", "fact_state_series"),
    ),
    Metric(
        "production", "Production", "qtl", "Quantity produced.",
        ("crop_ayp_district", "crop_ayp_block", "crop_ayp_state"), _AYP_DIMENSIONS, "sum",
        facts=("fact_crop_ayp", "fact_state_series"),
    ),
    Metric(
        "yield_rate", "Yield rate", "qtl/ha",
        "Production divided by area. Always a ratio of sums, never an average "
        "of published yields.",
        ("crop_ayp_district", "crop_ayp_block", "crop_ayp_state"), _AYP_DIMENSIONS, "ratio",
        facts=("fact_crop_ayp", "fact_state_series"),
    ),
    Metric(
        "yield_yoy_pct", "Yield change year on year", "%",
        "Year-on-year change in yield_rate. Requires agri_year as a dimension.",
        ("crop_ayp_district", "crop_ayp_block", "crop_ayp_state"), _AYP_DIMENSIONS, "ratio",
        required_dimensions=frozenset({"agri_year"}), facts=("fact_crop_ayp", "fact_state_series"),
    ),
    Metric(
        "production_share_pct", "Share of state production", "%",
        "A district's production as a share of the state total for the same "
        "crop, season and year.",
        ("crop_ayp_district",), _AYP_DIMENSIONS - {"block", "grain_source"}, "sum",
        required_dimensions=frozenset({"district"}), facts=("fact_crop_ayp",),
    ),
    Metric(
        "land_use_share_pct", "Share of area under survey", "%",
        "A land-use category as a share of the district's total area under "
        "survey.",
        ("land_use",),
        frozenset({"district", "block", "land_use_category", "agri_year",
                   "data_origin", "grain_source"}),
        "sum",
        required_dimensions=frozenset({"land_use_category"}),
        facts=("fact_land_use",),
    ),
    Metric(
        "cropping_area_share_pct", "Share of district crop area", "%",
        "A crop's area as a share of all crop area recorded for that district, "
        "season and year.",
        ("crop_ayp_district",), _AYP_DIMENSIONS - {"block", "grain_source"}, "sum",
        required_dimensions=frozenset({"crop"}), facts=("fact_crop_ayp",),
    ),
)

METRICS_BY_ID: dict[str, Metric] = {m.id: m for m in METRICS}

# Filter operators a caller may use.
OPERATORS = ("eq", "in", "not_in", "between", "gte", "lte")


def metric_ids() -> list[str]:
    return sorted(METRICS_BY_ID)


def dimension_ids() -> list[str]:
    return sorted(DIMENSIONS_BY_ID)


def relation_for(
    metric: Metric, requested: set[str], grain_source_filter: Optional[set[str]] = None
) -> Relation:
    """Pick the relation that serves the grain the caller asked for.

    Block grain is only served by a relation that carries the block dimension;
    otherwise the first declared relation wins, unless published_state grain is requested.
    """
    if grain_source_filter and "published_state" in grain_source_filter:
        if "crop_ayp_state" in metric.relations:
            return RELATIONS["crop_ayp_state"]
    for key in metric.relations:
        relation = RELATIONS[key]
        if requested <= relation.dimensions:
            return relation
    # No relation covers the request; the caller gets a validation error naming
    # the dimensions that cannot be served together.
    raise KeyError(
        ", ".join(sorted(requested - RELATIONS[metric.relations[0]].dimensions))
    )
