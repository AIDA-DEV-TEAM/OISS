"""Source -> raw -> staging -> analytics, with versions, lineage and findings.

The one code path the brief insists on lives here: :func:`process_source` reads,
validates and stages a file and is the *only* way rows are prepared, whether
they came from the bundled dataset or from ``POST /ingest/upload``. The two
differ solely in whether :func:`persist_source` is then called to write the
result. Findings are therefore identical by construction.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import duckdb
import pandas as pd

from app import db
from app.config import DB_PATH
from app.masters import periods
from app.masters.crop_master import CROP_MASTER, resolve_crop, write_crop_master_csv
from app.masters.districts import ALIASES_PATH, MASTER_PATH, district_master, resolve_district
from app.masters.normalise import normalise_key
from app.ingest.readers import SOURCES, SourceSpec, read_source, sha256_of
from app.validation import rules as R
from app.validation.rules import Finding, RuleContext

# --------------------------------------------------------------------------
# Units
# --------------------------------------------------------------------------
# Published units vary by year and table; analytics keeps the published value
# and unit untouched and adds a canonical pair so years can be compared.
# Canonical: area in hectares, production in quintals, yield in quintals/hectare.
UNIT_FACTORS: dict[str, tuple[str, float]] = {
    "ha": ("ha", 1.0),
    "'000 ha": ("ha", 1_000.0),
    "hectare": ("ha", 1.0),
    "qtl": ("qtl", 1.0),
    "MT": ("qtl", 10.0),
    "'000 MT": ("qtl", 10_000.0),
    "qtl/ha": ("qtl/ha", 1.0),
    "%": ("%", 1.0),
    "Rs/quintal": ("Rs/quintal", 1.0),
}


def canonicalise(values: pd.Series, unit: pd.Series) -> tuple[pd.Series, pd.Series]:
    factors = unit.map(lambda u: UNIT_FACTORS.get(str(u), (str(u), 1.0))[1])
    names = unit.map(lambda u: UNIT_FACTORS.get(str(u), (str(u), 1.0))[0])
    return values * factors.astype(float), names.astype("string")


# Land-use category labels differ between the block microdata and the 2024-25
# report; both fold onto the report's wording.
LAND_USE_CANONICAL: dict[str, str] = {
    "FOREST": "Forest",
    "LANDPUTTONONAGRICULTURALUSE": "Land put to non-agricultural uses",
    "LANDPUTTONONAGRICULTURALUSES": "Land put to non-agricultural uses",
    "BARRENNONCULTIVABLELAND": "Barren and un-cultivable land",
    "BARRENANDUNCULTIVABLELAND": "Barren and un-cultivable land",
    "PERMANENTPASTURESOTHERGRAZINGLAND": "Permanent pastures and other grazing land",
    "PERMANENTPASTURESANDOTHERGRAZINGLAND": "Permanent pastures and other grazing land",
    "LANDUNDERMISCTREECROPGROVESNOTINCLUDEDINNETAREASOWN": (
        "Land under misc. tree crops & groves not included in net area sown"
    ),
    "LANDUNDERMISCTREECROPSGROVESNOTINCLUDEDINNETAREASOWN": (
        "Land under misc. tree crops & groves not included in net area sown"
    ),
    "CULTIVABLEWASTE": "Cultivable waste",
    "OLDFALLOWS": "Old fallows",
    "CURRENTFALLOWS": "Current fallows",
    "NETAREASOWNTOTAL": "Net area sown",
    "NETAREASOWN": "Net area sown",
    "NETAREASOWNIRRIGATED": "Net area sown (irrigated)",
    "NETAREASOWNUNIRRIGATED": "Net area sown (unirrigated)",
    "TOTALAREAUNDERSURVEY": "Total area under survey",
    "GEOGRAPHICALAREA": "Geographical area",
    "AREANOTINCLUDEDUNDERSURVEY": "Area not included under survey",
}

# The nine categories that must sum to 'Total area under survey'.
LAND_USE_NINE = (
    "Forest",
    "Land put to non-agricultural uses",
    "Barren and un-cultivable land",
    "Permanent pastures and other grazing land",
    "Land under misc. tree crops & groves not included in net area sown",
    "Cultivable waste",
    "Old fallows",
    "Current fallows",
    "Net area sown",
)

PRICE_TYPES = {"FARMHARVEST": "farm_harvest", "WHOLESALE": "wholesale"}

CELL_STATUS_TO_VALUE_STATUS = {
    "ok": "ok",
    "dash": "not_reported",
    "blank": "not_reported",
    # 'S' in the printed report: less than half a unit, which is not zero.
    "below_half_unit": "below_half_unit",
    "provisional": "provisional",
}

NATURAL_KEYS: dict[str, tuple[str, ...]] = {
    "fact_price": ("period_id", "district_id", "crop_id", "price_type"),
    "fact_crop_ayp": (
        "period_id", "district_id", "block_ref", "crop_id", "product", "measure",
    ),
    "fact_land_use": (
        "period_id", "district_id", "block_ref", "land_use_category", "measure",
    ),
    "fact_state_series": ("period_id", "crop_id", "product", "season", "measure"),
}


@dataclass
class StageResult:
    """What one source produced, before anything is written."""

    spec: SourceSpec
    dataset_version_id: str
    sha256: str
    source_path: Path
    raw: pd.DataFrame
    staged: pd.DataFrame
    quarantined: pd.DataFrame
    findings: list[Finding] = field(default_factory=list)

    def findings_frame(self, run_id: str) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "run_id": run_id,
                    "dataset_version_id": self.dataset_version_id,
                    "rule_code": f.rule_code,
                    "severity": f.severity,
                    "row_ref": f.row_ref,
                    "column_name": f.column_name,
                    "message": f.message,
                    "observed_value": f.observed_value,
                }
                for f in self.findings
            ],
            columns=[
                "run_id", "dataset_version_id", "rule_code", "severity", "row_ref",
                "column_name", "message", "observed_value",
            ],
        )

    def summary(self) -> dict[str, object]:
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.rule_code] = counts.get(finding.rule_code, 0) + 1
        return {
            "dataset_name": self.spec.name,
            "dataset_version_id": self.dataset_version_id,
            "source_file": str(self.source_path),
            "data_origin": self.spec.data_origin,
            "target_table": self.spec.target_table,
            "rows_read": int(len(self.raw)),
            "rows_staged": int(len(self.staged)),
            "rows_quarantined": int(len(self.quarantined)),
            "findings_by_rule": dict(sorted(counts.items())),
        }


# --------------------------------------------------------------------------
# Helpers shared by the transforms
# --------------------------------------------------------------------------
def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype("string").str.strip().str.replace(",", "", regex=False),
        errors="coerce",
    )


def _district_ids(names: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Resolve a column of published names to ids plus a state-total flag."""
    matches = names.map(resolve_district)
    ids = matches.map(lambda m: m.district_id if m else pd.NA).astype("string")
    is_state = matches.map(lambda m: bool(m and m.is_state_total)).astype(bool)
    return ids, is_state


def _crop_ids(names: pd.Series) -> pd.Series:
    return names.map(lambda n: resolve_crop(n) or pd.NA).astype("string")


def _product(values: pd.Series) -> pd.Series:
    """Collapse the published product vocabulary onto paddy | rice | minor."""
    lowered = values.astype("string").str.strip().str.lower()
    return lowered.where(lowered.isin(["paddy", "rice"]), "minor").astype("string")


def _land_use_canonical(values: pd.Series) -> pd.Series:
    return values.map(
        lambda v: LAND_USE_CANONICAL.get(normalise_key(v), str(v).strip())
    ).astype("string")


def _block_ref(frame: pd.DataFrame) -> pd.Series:
    """Key part that keeps unmatched blocks unique when block_id is NULL."""
    return (
        frame["block_id"].fillna("~" + frame["block_name_as_published"].fillna(""))
        .astype("string")
    )


def _not_grown(values: pd.Series, marker: str) -> pd.Series:
    """Rows the publisher means as 'not grown': 0 in 2022-23, blank in 2023-24."""
    if marker == "zero":
        return values.notna() & (values == 0)
    return values.isna()


# --------------------------------------------------------------------------
# Transforms: one per source, each returning (staged rows, findings)
# --------------------------------------------------------------------------
Transform = Callable[
    [pd.DataFrame, RuleContext, dict[str, str], frozenset[str]],
    tuple[pd.DataFrame, list[Finding]],
]


def _t_price(raw: pd.DataFrame, ctx: RuleContext, blocks, presence):
    findings: list[Finding] = []
    findings += R.check_type_mismatch(raw, ["price_rs_per_quintal"], ctx)
    findings += R.check_unknown_district(raw, "district_as_published", ctx)
    findings += R.check_unknown_crop(raw, "commodity", ctx)
    findings += R.check_total_row_in_detail(raw, "district_as_published", ctx)
    findings += R.check_out_of_range(raw, "price_rs_per_quintal", "price", ctx)
    findings += R.check_msp_substituted(raw, "cell_status", "commodity", ctx)

    district_id, is_state = _district_ids(raw["district_as_published"])
    # A dash against a crop this district never prices is not a missing value.
    classified = raw.assign(
        _series_key=[
            price_key(d, c, PRICE_TYPES.get(normalise_key(t), ""))
            for d, c, t in zip(district_id, _crop_ids(raw["commodity"]), raw["price_type"])
        ]
    )
    findings += R.check_missing_value(
        classified, ["price_rs_per_quintal"], ctx, presence, "_series_key"
    )
    findings += R.check_structurally_absent(
        classified, ["price_rs_per_quintal"], ctx, presence, "_series_key"
    )
    staged = pd.DataFrame(index=raw.index)
    staged["period_id"] = raw["year"].map(periods.year_period)
    staged["agri_year"] = raw["year"]
    staged["season"] = pd.NA
    staged["month_start"] = pd.NaT
    staged["period_type"] = "year"
    staged["district_id"] = district_id
    staged["is_state_total"] = is_state
    staged["crop_id"] = _crop_ids(raw["commodity"])
    staged["price_type"] = raw["price_type"].map(
        lambda v: PRICE_TYPES.get(normalise_key(v), pd.NA)
    )
    staged["price_rs_per_quintal"] = _numeric(raw["price_rs_per_quintal"])
    staged["unit"] = "Rs/quintal"
    staged["annual_level_basis"] = pd.NA
    staged["annual_level_rs_per_quintal"] = pd.NA
    staged["value_status"] = (
        raw["cell_status"].map(CELL_STATUS_TO_VALUE_STATUS).fillna("ok")
    )
    staged["source_row_ref"] = (
        "table=" + raw["table_no"].astype("string") + "|page=" + raw["pdf_page"].astype("string")
    )
    findings += R.check_duplicate_key(staged, NATURAL_KEYS["fact_price"], ctx)
    return staged, findings


def _t_synthetic_price(raw: pd.DataFrame, ctx: RuleContext, blocks, presence):
    findings: list[Finding] = []
    findings += R.check_type_mismatch(
        raw, ["price_rs_per_quintal", "annual_level_rs_per_quintal"], ctx
    )
    findings += R.check_unknown_district(raw, "district", ctx)
    findings += R.check_unknown_crop(raw, "commodity", ctx)
    findings += R.check_out_of_range(raw, "price_rs_per_quintal", "price", ctx)
    findings += R.check_missing_value(raw, ["price_rs_per_quintal"], ctx)

    district_id, is_state = _district_ids(raw["district"])
    # The generator already writes a district_id; resolving the name independently
    # and comparing catches a hand-edited upload that disagrees with itself.
    disagreeing = raw["district_id"].astype("string") != district_id
    for index in raw.index[disagreeing.fillna(True)]:
        findings.append(
            Finding(
                "CROSS_SOURCE_MISMATCH",
                "info",
                ctx.row_ref(raw, index),
                "district_id",
                f"district_id {raw.at[index, 'district_id']!r} does not match the "
                f"name {raw.at[index, 'district']!r}",
                str(raw.at[index, "district_id"]),
            )
        )

    staged = pd.DataFrame(index=raw.index)
    staged["period_id"] = raw["month_start"].map(periods.month_period)
    staged["agri_year"] = raw["agri_year"]
    staged["season"] = pd.NA
    staged["month_start"] = pd.to_datetime(raw["month_start"], errors="coerce")
    staged["period_type"] = "month"
    staged["district_id"] = district_id
    staged["is_state_total"] = is_state
    staged["crop_id"] = _crop_ids(raw["commodity"])
    staged["price_type"] = raw["price_type"].map(
        lambda v: PRICE_TYPES.get(normalise_key(v), pd.NA)
    )
    staged["price_rs_per_quintal"] = _numeric(raw["price_rs_per_quintal"])
    staged["unit"] = raw["unit"]
    staged["annual_level_basis"] = raw["annual_level_basis"]
    staged["annual_level_rs_per_quintal"] = _numeric(raw["annual_level_rs_per_quintal"])
    staged["value_status"] = "ok"
    staged["source_row_ref"] = (
        "generator=" + raw["generator_version"].astype("string")
        + "|seed=" + raw["generator_seed"].astype("string")
    )
    findings += R.check_duplicate_key(staged, NATURAL_KEYS["fact_price"], ctx)
    return staged, findings


def _t_report_crop_ayp(raw: pd.DataFrame, ctx: RuleContext, blocks, presence):
    findings: list[Finding] = []
    findings += R.check_type_mismatch(raw, ["value"], ctx)
    findings += R.check_unknown_district(raw, "district_as_published", ctx)
    findings += R.check_unknown_crop(raw, "crop_table", ctx)
    findings += R.check_total_row_in_detail(raw, "district_as_published", ctx)
    yields = raw[raw["measure"] == "yield_rate"]
    findings += R.check_out_of_range(yields, "value", "yield", ctx)

    district_id, is_state = _district_ids(raw["district_as_published"])
    season = raw["season"].astype("string").str.strip()
    classified = raw.assign(
        _series_key=[
            ayp_key(d, c, s)
            for d, c, s in zip(district_id, _crop_ids(raw["crop_table"]), season)
        ]
    )
    findings += R.check_missing_value(classified, ["value"], ctx, presence, "_series_key")
    findings += R.check_structurally_absent(
        classified, ["value"], ctx, presence, "_series_key"
    )
    is_total = season == "Total"
    staged = pd.DataFrame(index=raw.index)
    staged["period_id"] = [
        periods.year_period(y) if t else periods.season_period(y, s)
        for y, s, t in zip(raw["reference_year"], season, is_total)
    ]
    staged["agri_year"] = raw["reference_year"]
    staged["season"] = season.where(~is_total, pd.NA)
    staged["month_start"] = pd.NaT
    staged["period_type"] = pd.Series(["year" if t else "season" for t in is_total], index=raw.index)
    staged["district_id"] = district_id
    staged["is_state_total"] = is_state
    staged["block_id"] = pd.NA
    staged["block_name_as_published"] = pd.NA
    staged["crop_id"] = _crop_ids(raw["crop_table"])
    staged["product"] = _product(raw["product"])
    staged["measure"] = raw["measure"]
    staged["value"] = _numeric(raw["value"])
    staged["unit"] = raw["unit"]
    staged["value_canonical"], staged["unit_canonical"] = canonicalise(
        staged["value"], staged["unit"]
    )
    staged["value_status"] = raw["cell_status"].map(CELL_STATUS_TO_VALUE_STATUS).fillna("ok")
    staged["source_row_ref"] = (
        "table=" + raw["table_no"].astype("string") + "|page=" + raw["pdf_page"].astype("string")
    )
    staged["block_ref"] = _block_ref(staged)
    findings += R.check_duplicate_key(staged, NATURAL_KEYS["fact_crop_ayp"], ctx)
    return staged, findings


def _t_report_land_use(raw: pd.DataFrame, ctx: RuleContext, blocks, presence):
    findings: list[Finding] = []
    findings += R.check_type_mismatch(raw, ["value"], ctx)
    findings += R.check_unknown_district(raw, "district_as_published", ctx)
    findings += R.check_total_row_in_detail(raw, "district_as_published", ctx)
    findings += R.check_missing_value(raw, ["value"], ctx)

    district_id, is_state = _district_ids(raw["district_as_published"])
    staged = pd.DataFrame(index=raw.index)
    staged["period_id"] = raw["reference_year"].map(periods.year_period)
    staged["agri_year"] = raw["reference_year"]
    staged["season"] = pd.NA
    staged["month_start"] = pd.NaT
    staged["period_type"] = "year"
    staged["district_id"] = district_id
    staged["is_state_total"] = is_state
    staged["block_id"] = pd.NA
    staged["block_name_as_published"] = pd.NA
    staged["land_use_category"] = _land_use_canonical(raw["land_use_category"])
    staged["measure"] = raw["measure"]
    staged["value"] = _numeric(raw["value"])
    staged["unit"] = raw["unit"]
    staged["value_canonical"], staged["unit_canonical"] = canonicalise(
        staged["value"], staged["unit"]
    )
    staged["value_status"] = raw["cell_status"].map(CELL_STATUS_TO_VALUE_STATUS).fillna("ok")
    staged["source_row_ref"] = (
        "table=" + raw["table_no"].astype("string") + "|page=" + raw["pdf_page"].astype("string")
    )
    staged["block_ref"] = _block_ref(staged)
    findings += R.check_duplicate_key(staged, NATURAL_KEYS["fact_land_use"], ctx)
    return staged, findings


def _t_state_series(raw: pd.DataFrame, ctx: RuleContext, blocks, presence):
    findings: list[Finding] = []
    findings += R.check_type_mismatch(raw, ["value"], ctx)
    findings += R.check_unknown_crop(raw, "crop", ctx)
    findings += R.check_out_of_range(raw[raw["measure"] == "yield_rate"], "value", "yield", ctx)
    classified = raw.assign(
        _series_key=[
            state_key(c, s)
            for c, s in zip(
                _crop_ids(raw["crop"]), raw["season"].astype("string").str.strip()
            )
        ]
    )
    findings += R.check_missing_value(classified, ["value"], ctx, presence, "_series_key")
    findings += R.check_structurally_absent(
        classified, ["value"], ctx, presence, "_series_key"
    )

    staged = pd.DataFrame(index=raw.index)
    staged["period_id"] = raw["reference_year"].map(periods.year_period)
    staged["agri_year"] = raw["reference_year"]
    staged["season"] = pd.NA
    staged["month_start"] = pd.NaT
    staged["period_type"] = "year"
    staged["crop_id"] = _crop_ids(raw["crop"])
    staged["product"] = _product(raw["product"])
    staged["season_label"] = raw["season"].astype("string").str.strip()
    staged["measure"] = raw["measure"]
    staged["value"] = _numeric(raw["value"])
    staged["unit"] = raw["unit"]
    staged["value_canonical"], staged["unit_canonical"] = canonicalise(
        staged["value"], staged["unit"]
    )
    staged["value_status"] = raw["cell_status"].map(CELL_STATUS_TO_VALUE_STATUS).fillna("ok")
    staged["source_row_ref"] = (
        "report=" + raw["report_year"].astype("string")
        + "|table=" + raw["table_no"].astype("string")
    )
    key = ("period_id", "crop_id", "product", "season_label", "measure")
    findings += R.check_duplicate_key(staged, key, ctx)
    return staged, findings


def _block_land_use(
    raw: pd.DataFrame,
    ctx: RuleContext,
    blocks: dict[str, str],
    *,
    district_col: str,
    block_col: str,
    flag_col: str,
    category_col: str,
    area_col: str,
    year_col: str,
):
    findings: list[Finding] = []
    findings += R.check_type_mismatch(raw, [area_col], ctx)
    findings += R.check_unknown_district(raw, district_col, ctx)
    findings += R.check_total_row_in_detail(raw, district_col, ctx)
    findings += R.check_missing_value(raw, [area_col], ctx)

    district_id, is_state = _district_ids(raw[district_col])
    is_urban = raw[flag_col].astype("string").str.strip().str.upper() == "URBAN"
    block_key = district_id.fillna("") + "|" + raw[block_col].map(normalise_key)
    block_id = block_key.map(blocks).astype("string")
    # Urban rows are not coded blocks; they get a district-scoped pseudo block.
    block_id = block_id.where(~is_urban, "BU" + district_id.fillna(""))

    staged = pd.DataFrame(index=raw.index)
    staged["period_id"] = raw[year_col].map(periods.year_period)
    staged["agri_year"] = raw[year_col]
    staged["season"] = pd.NA
    staged["month_start"] = pd.NaT
    staged["period_type"] = "year"
    staged["district_id"] = district_id
    staged["is_state_total"] = is_state
    staged["block_id"] = block_id
    staged["block_name_as_published"] = raw[block_col]
    staged["land_use_category"] = _land_use_canonical(raw[category_col])
    staged["measure"] = "area"
    staged["value"] = _numeric(raw[area_col])
    staged["unit"] = "ha"
    staged["value_canonical"], staged["unit_canonical"] = canonicalise(
        staged["value"], staged["unit"]
    )
    staged["value_status"] = staged["value"].isna().map(
        {True: "not_reported", False: "ok"}
    )
    staged["source_row_ref"] = "block=" + raw[block_col].astype("string")
    staged["block_ref"] = _block_ref(staged)
    findings += R.check_duplicate_key(staged, NATURAL_KEYS["fact_land_use"], ctx)
    return staged, findings


def _t_lus_2022_23(raw, ctx, blocks, presence):
    return _block_land_use(
        raw, ctx, blocks,
        district_col="District", block_col="Block",
        flag_col="Block_Urban_Dist_State_Total", category_col="Land_Use_Category",
        area_col="Area_Hectare", year_col="Year",
    )


def _t_lus_2023_24(raw, ctx, blocks, presence):
    return _block_land_use(
        raw, ctx, blocks,
        district_col="District", block_col="Block", flag_col="Block_Urban",
        category_col="Land Use Category", area_col="Area in Ha", year_col="Year",
    )


def _ayp_long(
    raw: pd.DataFrame,
    ctx: RuleContext,
    blocks: dict[str, str],
    presence: frozenset[str],
    *,
    district_col: str,
    crop_col: str,
    season_col: str,
    year_col: str,
    measures: dict[str, tuple[str, str]],
    not_grown: str,
    block_col: Optional[str] = None,
    flag_col: Optional[str] = None,
):
    """Shared transform for every wide EARAS area/yield/production file."""
    numeric_columns = list(measures)
    area_col, yield_col, production_col = numeric_columns
    findings: list[Finding] = []

    # 'S' is the publisher's "less than half a unit" marker, not stray text and
    # not zero. Blank it before the type rule runs so the row is kept, then
    # record it through value_status.
    below_half = {
        column: raw[column].astype("string").str.strip().str.upper() == "S"
        for column in numeric_columns
    }
    cleaned = raw.copy()
    for column, marker in below_half.items():
        cleaned.loc[marker, column] = pd.NA

    findings += R.check_type_mismatch(cleaned, numeric_columns, ctx)
    findings += R.check_unknown_district(raw, district_col, ctx)
    findings += R.check_unknown_crop(raw, crop_col, ctx)
    findings += R.check_total_row_in_detail(raw, district_col, ctx)

    # Published values first, then the "not grown" convention, so that a
    # not-grown cell is never also reported as an implausible value.
    values = {column: _numeric(cleaned[column]) for column in numeric_columns}
    not_grown_mask = {
        column: _not_grown(values[column], not_grown) & ~below_half[column]
        for column in numeric_columns
    }
    for column in numeric_columns:
        values[column] = values[column].where(
            ~(not_grown_mask[column] | below_half[column])
        )

    # Area, yield and production are published in different units per file
    # (ha/qtl vs '000 ha/'000 MT), so both rules compare canonical values.
    canonical = {
        measures[column][0]: values[column] * UNIT_FACTORS[measures[column][1]][1]
        for column in numeric_columns
    }
    context_columns = [
        column
        for column in (district_col, block_col, crop_col, season_col)
        if column is not None and column in raw.columns
    ]
    comparable = pd.DataFrame(canonical, index=raw.index).join(raw[context_columns])
    canonical_ctx = RuleContext(ctx.dataset_name, tuple(context_columns))
    findings += R.check_out_of_range(comparable, "yield_rate", "yield", canonical_ctx)
    findings += R.check_identity(
        comparable, "area", "yield_rate", "production", canonical_ctx
    )

    district_id, is_state = _district_ids(raw[district_col])

    if block_col is not None:
        is_urban = raw[flag_col].astype("string").str.strip().str.upper() == "URBAN"
        block_key = district_id.fillna("") + "|" + raw[block_col].map(normalise_key)
        block_id = block_key.map(blocks).astype("string")
        block_id = block_id.where(~is_urban, "BU" + district_id.fillna(""))
        # Paddy block spellings diverge from the land-use file that defines the
        # codes; those rows load with a null block_id rather than being dropped.
        unmatched = raw[block_id.isna() & district_id.notna()]
        findings += R.check_unknown_block(unmatched, district_col, block_col, set(blocks), ctx)
        block_names = raw[block_col]
    else:
        block_id = pd.Series(pd.NA, index=raw.index, dtype="string")
        block_names = pd.Series(pd.NA, index=raw.index, dtype="string")

    base = pd.DataFrame(index=raw.index)
    base["period_id"] = [
        periods.season_period(y, s) for y, s in zip(raw[year_col], raw[season_col])
    ]
    base["agri_year"] = raw[year_col]
    base["season"] = raw[season_col].astype("string").str.strip()
    base["month_start"] = pd.NaT
    base["period_type"] = "season"
    base["district_id"] = district_id
    base["is_state_total"] = is_state
    base["block_id"] = block_id
    base["block_name_as_published"] = block_names
    base["crop_id"] = _crop_ids(raw[crop_col])
    base["product"] = _product(raw[crop_col])
    base["source_row_ref"] = "src=" + ctx.dataset_name
    # A crop with no value in any year is not grown here; the key rides along
    # through the melt so every measure row keeps its series identity.
    geography = (
        district_id.fillna("") + ":" + raw[block_col].map(normalise_key)
        if block_col is not None
        else district_id
    )
    base["_series_key"] = [
        ayp_key(g, c, s)
        for g, c, s in zip(geography, base["crop_id"], base["season"])
    ]

    # One row per measure, each carrying its own value_status.
    parts = []
    for column, (measure, unit) in measures.items():
        part = base.copy()
        part["measure"] = measure
        part["unit"] = unit
        part["value"] = values[column]
        status = pd.Series("ok", index=raw.index, dtype="string")
        status = status.mask(not_grown_mask[column], "not_reported")
        status = status.mask(below_half[column], "below_half_unit")
        part["value_status"] = status
        parts.append(part)
    staged = pd.concat(parts)
    staged["value_canonical"], staged["unit_canonical"] = canonicalise(
        staged["value"], staged["unit"]
    )
    staged = staged.reset_index(drop=True)
    staged["block_ref"] = _block_ref(staged)

    long_ctx = RuleContext(
        ctx.dataset_name, ("district_id", "block_name_as_published", "crop_id", "season", "measure")
    )
    findings += R.check_missing_value(staged, ["value"], long_ctx, presence, "_series_key")
    findings += R.check_structurally_absent(
        staged, ["value"], long_ctx, presence, "_series_key"
    )
    findings += R.check_duplicate_key(staged, NATURAL_KEYS["fact_crop_ayp"], ctx)
    return staged.drop(columns=["_series_key"]), findings


def _t_paddy_2022_23(raw, ctx, blocks, presence):
    return _ayp_long(
        raw, ctx, blocks, presence,
        district_col="District", crop_col="Crop", season_col="Season", year_col="Year",
        measures={
            "Area_ha": ("area", "ha"),
            "YieldRate_qtl_per_ha": ("yield_rate", "qtl/ha"),
            "Production_qtl": ("production", "qtl"),
        },
        not_grown="zero", block_col="Block", flag_col="Block_Urban_Dist_total",
    )


def _t_minor_2022_23(raw, ctx, blocks, presence):
    return _ayp_long(
        raw, ctx, blocks, presence,
        district_col="District", crop_col="Crop", season_col="Season", year_col="Year",
        measures={
            "Area_hectares": ("area", "ha"),
            "Yield_Rate_qtl_ha": ("yield_rate", "qtl/ha"),
            "Prodn_quintals": ("production", "qtl"),
        },
        not_grown="zero",
    )


def _t_paddy_block_2023_24(raw, ctx, blocks, presence):
    return _ayp_long(
        raw, ctx, blocks, presence,
        district_col="District", crop_col="Crop", season_col="Season", year_col="Year",
        measures={
            "Area_ha": ("area", "ha"),
            "Yield_qtl_per_ha": ("yield_rate", "qtl/ha"),
            "Production_qtls": ("production", "qtl"),
        },
        not_grown="blank", block_col="Block", flag_col="Block_Urban",
    )


def _t_paddy_dist_2023_24(raw, ctx, blocks, presence):
    return _ayp_long(
        raw, ctx, blocks, presence,
        district_col="District", crop_col="Crop_Paddy_Rice", season_col="Season",
        year_col="Year",
        measures={
            "Area_000ha": ("area", "'000 ha"),
            "Yield_rate_qtl_ha": ("yield_rate", "qtl/ha"),
            "Production_000MT": ("production", "'000 MT"),
        },
        not_grown="blank",
    )


def _t_minor_2023_24(raw, ctx, blocks, presence):
    return _ayp_long(
        raw, ctx, blocks, presence,
        district_col="District", crop_col="Minor_Crop", season_col="Season",
        year_col="Year",
        measures={
            "Area_ha": ("area", "ha"),
            "Yield_rate_qtl_per_ha": ("yield_rate", "qtl/ha"),
            "Production_qtls": ("production", "qtl"),
        },
        not_grown="blank",
    )


TRANSFORMS: dict[str, Transform] = {
    "price_statistics_2020": _t_price,
    "synthetic_monthly_prices": _t_synthetic_price,
    "earas_2024_25_district_crop_ayp": _t_report_crop_ayp,
    "earas_2024_25_district_land_use": _t_report_land_use,
    "earas_state_series": _t_state_series,
    "earas_2022_23_block_land_use": _t_lus_2022_23,
    "earas_2022_23_block_paddy": _t_paddy_2022_23,
    "earas_2022_23_district_minor_crops": _t_minor_2022_23,
    "earas_2023_24_block_land_use": _t_lus_2023_24,
    "earas_2023_24_block_paddy": _t_paddy_block_2023_24,
    "earas_2023_24_district_paddy": _t_paddy_dist_2023_24,
    "earas_2023_24_district_minor_crops": _t_minor_2023_24,
}

ROW_REF_COLUMNS: dict[str, tuple[str, ...]] = {
    "price_statistics_2020": ("district_as_published", "commodity", "year"),
    "synthetic_monthly_prices": ("district", "commodity", "month_start"),
    "earas_2024_25_district_crop_ayp": ("district_as_published", "crop_table", "season", "measure"),
    "earas_2024_25_district_land_use": ("district_as_published", "land_use_category", "measure"),
    "earas_state_series": ("reference_year", "crop", "season", "measure"),
    "earas_2022_23_block_land_use": ("District", "Block", "Land_Use_Category"),
    "earas_2022_23_block_paddy": ("District", "Block", "Season"),
    "earas_2022_23_district_minor_crops": ("District", "Season", "Crop"),
    "earas_2023_24_block_land_use": ("District", "Block", "Land Use Category"),
    "earas_2023_24_block_paddy": ("District", "Block", "Season"),
    "earas_2023_24_district_paddy": ("District", "Season", "Crop_Paddy_Rice"),
    "earas_2023_24_district_minor_crops": ("District", "Season", "Minor_Crop"),
}


# --------------------------------------------------------------------------
# dim_block
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Presence index: which series exist at all
# --------------------------------------------------------------------------
# Sources consulted when deciding whether a null is a gap or a series that was
# never published. Synthetic prices are excluded: they are generated for every
# combination by construction, so including them would mark everything present.
PRESENCE_SOURCES = (
    "earas_2022_23_district_minor_crops",
    "earas_2023_24_district_minor_crops",
    "earas_2023_24_district_paddy",
    "earas_2024_25_district_crop_ayp",
    "earas_2022_23_block_paddy",
    "earas_2023_24_block_paddy",
    "earas_state_series",
    "price_statistics_2020",
)


def ayp_key(geography: object, crop_id: object, season: object) -> str:
    return f"ayp|{geography}|{crop_id}|{season}"


def price_key(district_id: object, crop_id: object, price_type: object) -> str:
    return f"price|{district_id}|{crop_id}|{price_type}"


def state_key(crop_id: object, season: object) -> str:
    return f"state|{crop_id}|{season}"


@lru_cache(maxsize=1)
def build_presence_index() -> frozenset[str]:
    """Every (geography, crop, season) series that has a value somewhere.

    Built from official sources only, by reading them once. A key absent from
    this set means the crop is not grown or not priced there in any year of any
    source -- which is a fact about Odisha, not a data-quality problem.
    """
    from app.ingest.readers import SOURCES_BY_NAME

    present: set[str] = set()
    for name in PRESENCE_SOURCES:
        spec = SOURCES_BY_NAME[name]
        if not spec.path.exists():
            continue
        raw = read_source(spec)
        present |= _presence_keys_for(name, raw)
    return frozenset(present)


def _has_value(series: pd.Series) -> pd.Series:
    """Non-null and non-zero: 2022-23 writes 'not grown' as 0, 2023-24 as blank."""
    values = _numeric(series)
    return values.notna() & (values != 0)


def _presence_keys_for(name: str, raw: pd.DataFrame) -> set[str]:
    """Keys with at least one real measured value in this source."""
    if name == "price_statistics_2020":
        rows = raw[_has_value(raw["price_rs_per_quintal"])]
        district_id, _ = _district_ids(rows["district_as_published"])
        crop_id = _crop_ids(rows["commodity"])
        price_type = rows["price_type"].map(lambda v: PRICE_TYPES.get(normalise_key(v), ""))
        return {
            price_key(d, c, p)
            for d, c, p in zip(district_id, crop_id, price_type)
            if pd.notna(d) and pd.notna(c)
        }

    if name == "earas_state_series":
        rows = raw[_has_value(raw["value"])]
        crop_id = _crop_ids(rows["crop"])
        season = rows["season"].astype("string").str.strip()
        return {state_key(c, s) for c, s in zip(crop_id, season) if pd.notna(c)}

    if name == "earas_2024_25_district_crop_ayp":
        rows = raw[
            _has_value(raw["value"]) & (raw["is_state_total"].astype("string") == "0")
        ]
        district_id, _ = _district_ids(rows["district_as_published"])
        crop_id = _crop_ids(rows["crop_table"])
        season = rows["season"].astype("string").str.strip()
        return {
            ayp_key(d, c, s)
            for d, c, s in zip(district_id, crop_id, season)
            if pd.notna(d) and pd.notna(c)
        }

    spec = AYP_PRESENCE_COLUMNS[name]
    measured = pd.concat(
        [_has_value(raw[column]) for column in spec["measures"]], axis=1
    ).any(axis=1)
    rows = raw[measured]
    district_id, _ = _district_ids(rows[spec["district"]])
    crop_id = _crop_ids(rows[spec["crop"]])
    season = rows[spec["season"]].astype("string").str.strip()
    if spec.get("block"):
        # Block files are keyed on the block, because a crop absent from one
        # block is not a gap just because the district grows it elsewhere.
        geography = district_id.fillna("") + ":" + rows[spec["block"]].map(normalise_key)
    else:
        geography = district_id
    return {
        ayp_key(g, c, s)
        for g, c, s in zip(geography, crop_id, season)
        if pd.notna(g) and pd.notna(c)
    }


AYP_PRESENCE_COLUMNS: dict[str, dict[str, object]] = {
    "earas_2022_23_district_minor_crops": {
        "district": "District", "crop": "Crop", "season": "Season",
        "measures": ["Area_hectares", "Prodn_quintals"],
    },
    "earas_2023_24_district_minor_crops": {
        "district": "District", "crop": "Minor_Crop", "season": "Season",
        "measures": ["Area_ha", "Production_qtls"],
    },
    "earas_2023_24_district_paddy": {
        "district": "District", "crop": "Crop_Paddy_Rice", "season": "Season",
        "measures": ["Area_000ha", "Production_000MT"],
    },
    "earas_2022_23_block_paddy": {
        "district": "District", "crop": "Crop", "season": "Season", "block": "Block",
        "measures": ["Area_ha", "Production_qtl"],
    },
    "earas_2023_24_block_paddy": {
        "district": "District", "crop": "Crop", "season": "Season", "block": "Block",
        "measures": ["Area_ha", "Production_qtls"],
    },
}


BLOCK_SOURCES = ("earas_2023_24_block_land_use", "earas_2022_23_block_land_use")


def build_block_dimension() -> tuple[pd.DataFrame, dict[str, str]]:
    """Build ``dim_block`` from the land-use files -- the only ones with Code.

    Block names repeat across districts (``Nuagaon`` appears in several), so the
    lookup key is always ``(district_id, normalised block name)``, never the name
    alone.
    """
    from app.ingest.readers import SOURCES_BY_NAME

    rows: dict[str, dict[str, object]] = {}
    lookup: dict[str, str] = {}
    for name in BLOCK_SOURCES:
        spec = SOURCES_BY_NAME[name]
        if not spec.path.exists():
            continue
        raw = read_source(spec)
        district_column, block_column = "District", "Block"
        code_column = "Code"
        flag_column = "Block_Urban" if "Block_Urban" in raw.columns else "Block_Urban_Dist_State_Total"
        district_id, _ = _district_ids(raw[district_column])
        is_urban = raw[flag_column].astype("string").str.strip().str.upper() == "URBAN"
        for index in raw.index:
            if pd.isna(district_id.at[index]):
                continue
            key = f"{district_id.at[index]}|{normalise_key(raw.at[index, block_column])}"
            if bool(is_urban.at[index]):
                block_id = f"BU{district_id.at[index]}"
                code: object = None
                display = f"{raw.at[index, block_column]} (urban)"
            else:
                code_value = _numeric(pd.Series([raw.at[index, code_column]])).iloc[0]
                if pd.isna(code_value):
                    continue
                code = int(code_value)
                block_id = f"B{code:03d}"
                display = str(raw.at[index, block_column]).strip()
            rows.setdefault(
                block_id,
                {
                    "block_id": block_id,
                    "district_id": district_id.at[index],
                    "block_code": code,
                    "display_name": display,
                    "is_urban": bool(is_urban.at[index]),
                },
            )
            lookup.setdefault(key, block_id)
    frame = pd.DataFrame(list(rows.values())).sort_values(
        "block_id", kind="stable", ignore_index=True
    )
    return frame, lookup


# --------------------------------------------------------------------------
# The one code path
# --------------------------------------------------------------------------
def process_source(
    spec: SourceSpec,
    path: Optional[Path] = None,
    blocks: Optional[dict[str, str]] = None,
    presence: Optional[frozenset[str]] = None,
) -> StageResult:
    """Read, validate and stage one file. Writes nothing.

    Used identically by the batch build and by ``POST /ingest/upload``.
    """
    source_path = Path(path) if path is not None else spec.path
    ctx = RuleContext(spec.name, ROW_REF_COLUMNS.get(spec.name, ()))
    raw = read_source(spec, source_path)

    findings = R.check_schema(raw, spec.expected_columns, ctx)
    if any(f.rule_code == "SCHEMA_MISMATCH" for f in findings):
        # Without the declared columns the transform cannot run; report and stop.
        return StageResult(
            spec=spec,
            dataset_version_id=dataset_version_id(spec.name, sha256_of(source_path)),
            sha256=sha256_of(source_path),
            source_path=source_path,
            raw=raw,
            staged=raw.iloc[0:0],
            quarantined=raw.copy(),
            findings=findings,
        )

    staged, transform_findings = TRANSFORMS[spec.name](
        raw, ctx, blocks or {}, presence if presence is not None else build_presence_index()
    )
    findings += transform_findings

    # Error-severity findings quarantine their row. Indices refer to the raw
    # frame; staged rows inherit them through the index (melts keep it).
    bad_raw = R.quarantine_index(findings)
    quarantined = raw.loc[sorted(bad_raw & set(raw.index))].copy()
    if not quarantined.empty:
        reasons = {}
        for finding in findings:
            if finding.severity != "error":
                continue
            head = finding.row_ref.split("|", 1)[0]
            if head.startswith("row="):
                index = int(head[4:])
                reasons.setdefault(index, []).append(finding.rule_code)
        quarantined["quarantine_rules"] = [
            ",".join(sorted(set(reasons.get(index, [])))) for index in quarantined.index
        ]

    staged = staged.copy()
    if "block_ref" not in staged.columns:
        staged["block_ref"] = pd.NA
    keep = ~staged.index.isin(bad_raw)
    # A row missing a canonical id after resolution cannot be a fact row.
    for column in ("district_id", "crop_id"):
        if column in staged.columns:
            keep &= staged[column].notna().to_numpy()
    staged = staged.loc[keep].reset_index(drop=True)

    digest = sha256_of(source_path)
    return StageResult(
        spec=spec,
        dataset_version_id=dataset_version_id(spec.name, digest),
        sha256=digest,
        source_path=source_path,
        raw=raw,
        staged=staged,
        quarantined=quarantined,
        findings=findings,
    )


def dataset_version_id(dataset_name: str, sha256: str) -> str:
    """Content-addressed and therefore stable across rebuilds."""
    return f"{dataset_name}@{sha256[:12]}"


def run_id_for(digests: list[str], prefix: str = "build") -> str:
    """Deterministic run id: same inputs give the same run."""
    joined = "|".join(sorted(digests)).encode()
    return f"{prefix}-{hashlib.sha256(joined).hexdigest()[:12]}"


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------
FACT_COLUMNS: dict[str, tuple[str, ...]] = {
    "fact_price": (
        "period_id", "district_id", "crop_id", "price_type", "price_rs_per_quintal",
        "unit", "annual_level_basis", "annual_level_rs_per_quintal", "source_row_ref",
        "dataset_version_id", "data_origin", "value_status",
    ),
    "fact_crop_ayp": (
        "period_id", "district_id", "block_id", "crop_id", "product", "measure",
        "value", "unit", "value_canonical", "unit_canonical",
        "block_name_as_published", "source_row_ref",
        "dataset_version_id", "data_origin", "value_status",
    ),
    "fact_land_use": (
        "period_id", "district_id", "block_id", "land_use_category", "measure",
        "value", "unit", "value_canonical", "unit_canonical",
        "block_name_as_published", "source_row_ref",
        "dataset_version_id", "data_origin", "value_status",
    ),
    "fact_state_series": (
        "period_id", "crop_id", "product", "season", "measure", "value", "unit",
        "value_canonical", "unit_canonical", "source_row_ref",
        "dataset_version_id", "data_origin", "value_status",
    ),
}

PERIOD_COLUMNS = ("period_id", "agri_year", "season", "month_start", "period_type")


def write_table(con: duckdb.DuckDBPyConnection, table: str, frame: pd.DataFrame) -> None:
    con.register("_frame", frame)
    con.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM _frame")
    con.unregister("_frame")


def append_rows(con: duckdb.DuckDBPyConnection, table: str, frame: pd.DataFrame) -> None:
    if frame.empty:
        return
    con.register("_frame", frame)
    columns = ", ".join(f'"{column}"' for column in frame.columns)
    con.execute(f"INSERT INTO {table} ({columns}) SELECT {columns} FROM _frame")
    con.unregister("_frame")


def lineage_edges(result: StageResult) -> pd.DataFrame:
    """source file -> raw -> staging -> analytics -> export, per the brief."""
    spec = result.spec
    nodes = [
        (f"file:{result.source_path.name}", spec.raw_table, "extract"),
        (spec.raw_table, spec.staging_table, "transform"),
        (spec.staging_table, f"analytics.{spec.target_table}", "load"),
        (f"analytics.{spec.target_table}", f"export:{spec.target_table}", "publish"),
    ]
    return pd.DataFrame(
        [
            {
                "from_node": source,
                "to_node": target,
                "edge_type": kind,
                "dataset_version_id": result.dataset_version_id,
            }
            for source, target, kind in nodes
        ]
    )


def persist_source(
    con: duckdb.DuckDBPyConnection,
    result: StageResult,
    run_id: str,
    loaded_at: datetime,
) -> None:
    """Write one processed source into raw, quarantine, staging and governance."""
    spec = result.spec
    write_table(con, spec.raw_table, result.raw.astype("string"))
    write_table(con, f"quarantine.{spec.name}", result.quarantined.astype("string"))

    staged = result.staged.copy()
    staged["dataset_version_id"] = result.dataset_version_id
    # Declared by the spec, never inferred and never defaulted.
    staged["data_origin"] = spec.data_origin
    write_table(con, spec.staging_table, staged)

    version = pd.DataFrame(
        [
            {
                "dataset_version_id": result.dataset_version_id,
                "dataset_name": spec.name,
                "source_file": str(result.source_path),
                "source_type": spec.source_type,
                "sha256": result.sha256,
                "row_count": int(len(result.raw)),
                "layer": "raw",
                "loaded_at": loaded_at,
                "generator_version": spec.generator_version,
            }
        ]
    )
    append_rows(con, "analytics.dataset_version", version)
    append_rows(con, "analytics.lineage_edge", lineage_edges(result))
    append_rows(con, "analytics.validation_finding", result.findings_frame(run_id))


def populate_analytics(
    con: duckdb.DuckDBPyConnection, results: list[StageResult]
) -> None:
    """Fill dim_period and the fact tables from every staging table."""
    period_frames = []
    for result in results:
        staged = con.execute(f"SELECT * FROM {result.spec.staging_table}").df()
        if staged.empty:
            continue
        frame = pd.DataFrame(index=staged.index)
        for column in PERIOD_COLUMNS:
            if column in staged.columns:
                frame[column] = staged[column]
            else:
                frame[column] = pd.NaT if column == "month_start" else pd.NA
        period_frames.append(frame)
    if period_frames:
        append_rows(con, "analytics.dim_period", periods.period_rows(pd.concat(period_frames)))

    for result in results:
        target = result.spec.target_table
        staged = con.execute(f"SELECT * FROM {result.spec.staging_table}").df()
        if staged.empty:
            continue
        if target == "fact_state_series":
            # The period is year-grain there, so its 'season' is null; the real
            # season lives in its own fact column.
            staged = staged.drop(columns=["season"]).rename(
                columns={"season_label": "season"}
            )
        elif "is_state_total" in staged.columns:
            # State totals stay in staging for the reconciliation checks but are
            # never mixed into district-grain analytics.
            staged = staged[~staged["is_state_total"].astype(bool)]
        wanted = list(FACT_COLUMNS[target])
        missing = [column for column in wanted if column not in staged.columns]
        if missing:
            raise ValueError(f"{result.spec.name}: staging is missing {missing}")
        frame = staged[wanted].sort_values(
            wanted[:6], kind="stable", ignore_index=True
        )
        append_rows(con, f"analytics.{target}", frame)


def load_masters(con: duckdb.DuckDBPyConnection, loaded_at: datetime) -> dict[str, str]:
    """Load dim_district, dim_crop and dim_block, and version the master files."""
    append_rows(con, "analytics.dim_district", district_master())
    append_rows(con, "analytics.dim_crop", CROP_MASTER)
    blocks_frame, lookup = build_block_dimension()
    append_rows(con, "analytics.dim_block", blocks_frame)

    crop_csv = write_crop_master_csv()
    targets = {
        "district_master": "analytics.dim_district",
        "district_aliases": "analytics.dim_district",
        "crop_master": "analytics.dim_crop",
    }
    versions = []
    for path, name in (
        (MASTER_PATH, "district_master"),
        (ALIASES_PATH, "district_aliases"),
        (crop_csv, "crop_master"),
    ):
        digest = sha256_of(path)
        version_id = dataset_version_id(name, digest)
        versions.append(
            {
                "dataset_version_id": version_id,
                "dataset_name": name,
                "source_file": str(path),
                "source_type": "csv",
                "sha256": digest,
                "row_count": int(len(pd.read_csv(path))),
                "layer": "reference",
                "loaded_at": loaded_at,
                "generator_version": None,
            }
        )
        append_rows(
            con,
            "analytics.lineage_edge",
            pd.DataFrame(
                [
                    {
                        "from_node": f"file:{path.name}",
                        "to_node": targets[name],
                        "edge_type": "reference",
                        "dataset_version_id": version_id,
                    }
                ]
            ),
        )
    append_rows(con, "analytics.dataset_version", pd.DataFrame(versions))
    return lookup


# Two DE&S files publish 2023-24 paddy at different grains; comparing them is a
# provenance signal for the demo, not an error, so the findings are 'info'.
CROSS_SOURCE_PAIRS: tuple[tuple[str, str], ...] = (
    ("earas_2023_24_district_paddy", "earas_2023_24_block_paddy"),
)


def cross_source_findings(results: list[StageResult]) -> dict[str, list[Finding]]:
    """Compare the same measure across two sources, in canonical units."""
    by_name = {result.spec.name: result for result in results}
    out: dict[str, list[Finding]] = {}
    for left_name, right_name in CROSS_SOURCE_PAIRS:
        if left_name not in by_name or right_name not in by_name:
            continue
        ctx = RuleContext(f"{left_name} vs {right_name}")

        def district_totals(name: str) -> pd.DataFrame:
            staged = by_name[name].staged
            subset = staged[
                (staged["product"] == "paddy")
                & staged["measure"].isin(["area", "production"])
                & ~staged["is_state_total"].astype(bool)
            ]
            return (
                subset.groupby(["district_id", "measure"], dropna=False)["value_canonical"]
                .sum(min_count=1)
                .reset_index()
            )

        out.setdefault(left_name, []).extend(
            R.check_cross_source_mismatch(
                district_totals(left_name),
                district_totals(right_name),
                ["district_id", "measure"],
                "value_canonical",
                ctx,
                left_label=left_name,
                right_label=right_name,
            )
        )
    return out


def table_row_counts(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    rows = con.execute(
        """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema IN ('raw', 'quarantine', 'staging', 'analytics')
          AND table_type = 'BASE TABLE'
        ORDER BY table_schema, table_name
        """
    ).fetchall()
    counts: dict[str, int] = {}
    for schema, table in rows:
        counts[f"{schema}.{table}"] = con.execute(
            f"SELECT count(*) FROM {schema}.{table}"
        ).fetchone()[0]
    return counts


def build_finding_summary(con: duckdb.DuckDBPyConnection, run_id: str) -> pd.DataFrame:
    """Per-rule breakdown with one sample reference, for the validation screen.

    The sample is the alphabetically first row_ref so the summary is stable
    across rebuilds rather than picking an arbitrary row.
    """
    return con.execute(
        """
        SELECT
            run_id,
            rule_code,
            severity,
            count(*) AS finding_count,
            count(DISTINCT dataset_version_id) AS dataset_count,
            min(row_ref) AS sample_row_ref,
            min(message) AS sample_message
        FROM analytics.validation_finding
        WHERE run_id = ?
        GROUP BY run_id, rule_code, severity
        ORDER BY severity, rule_code
        """,
        [run_id],
    ).df()


# The district view rolls block rows up where no district row was published;
# this records that hop so "where did this number come from" is answerable from
# lineage_edge rather than only from the view definition.
def rollup_lineage_edges(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    rows = con.execute(
        """
        SELECT DISTINCT dataset_version_id
        FROM analytics.v_district_crop_ayp
        WHERE grain_source = 'aggregated_from_blocks'
        ORDER BY 1
        """
    ).fetchall()
    return pd.DataFrame(
        [
            {
                "from_node": "analytics.fact_crop_ayp[block]",
                "to_node": "analytics.v_district_crop_ayp",
                "edge_type": "aggregate",
                "dataset_version_id": version_id,
            }
            for (version_id,) in rows
        ]
    )


def findings_by_rule(con: duckdb.DuckDBPyConnection, run_id: str) -> dict[str, int]:
    rows = con.execute(
        """
        SELECT rule_code, severity, count(*)
        FROM analytics.validation_finding
        WHERE run_id = ?
        GROUP BY ALL
        ORDER BY 1, 2
        """,
        [run_id],
    ).fetchall()
    return {f"{code} ({severity})": count for code, severity, count in rows}


def build(db_path: Optional[Path] = None) -> dict[str, object]:
    """Rebuild the database from scratch and return the load summary."""
    from app.ingest import checks

    target = db.reset_database(db_path or DB_PATH)
    started_at = datetime.now(timezone.utc)
    con = db.connect(target)
    try:
        db.create_schema(con)
        lookup = load_masters(con, started_at)
        presence = build_presence_index()

        results: list[StageResult] = []
        for spec in SOURCES:
            if not spec.path.exists():
                raise FileNotFoundError(f"missing source for {spec.name}: {spec.path}")
            results.append(process_source(spec, blocks=lookup, presence=presence))

        for name, findings in cross_source_findings(results).items():
            next(r for r in results if r.spec.name == name).findings.extend(findings)

        run_id = run_id_for([result.sha256 for result in results])
        for result in results:
            persist_source(con, result, run_id, started_at)
        populate_analytics(con, results)
        append_rows(con, "analytics.lineage_edge", rollup_lineage_edges(con))

        finding_summary = build_finding_summary(con, run_id)
        append_rows(con, "analytics.finding_summary", finding_summary)

        check_results = checks.run_all(con, results)
        failed = [check for check in check_results if not check.passed]
        status = "failed" if failed else "succeeded"

        # Written before the counts are taken so the summary reports the finished
        # database rather than one mid-load.
        append_rows(
            con,
            "analytics.reconciliation_check",
            pd.DataFrame(
                [{"run_id": run_id, **check.as_dict()} for check in check_results]
            ),
        )
        append_rows(
            con,
            "analytics.load_run",
            pd.DataFrame(
                [
                    {
                        "run_id": run_id,
                        "started_at": started_at,
                        "finished_at": datetime.now(timezone.utc),
                        "status": status,
                        "summary_json": None,
                    }
                ]
            ),
        )

        summary: dict[str, object] = {
            "run_id": run_id,
            "status": status,
            "database": str(target),
            "sources": [result.summary() for result in results],
            "row_counts": table_row_counts(con),
            "findings_by_rule": findings_by_rule(con, run_id),
            "finding_summary": finding_summary.to_dict("records"),
            "checks": [check.as_dict() for check in check_results],
        }
        con.execute(
            "UPDATE analytics.load_run SET summary_json = ? WHERE run_id = ?",
            [json.dumps(summary, default=str), run_id],
        )
        return summary
    finally:
        con.close()
