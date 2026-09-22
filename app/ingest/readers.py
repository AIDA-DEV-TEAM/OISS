"""Per-source readers and the source registry.

Each bundled dataset is declared once as a :class:`SourceSpec`. The spec carries
everything that differs between sources -- path, file type, encoding, declared
columns, whether the rows are official or synthetic -- so the loader itself has
no per-source branching, and an uploaded file is read by exactly the same code
as the bundled one.

Publisher quirks absorbed here (and only here):

* UTF-8 BOM on two of the 2023-24 CSVs.
* Trailing spaces in published headers (``Season ``, ``Minor_Crop ``).
* ``2022_23`` vs ``2023-24`` agricultural-year spellings.
* Stata ``.dta`` microdata for 2022-23.

Everything is read as text. Typing happens in the staging step, after the
validation rules have had a chance to see the value as published.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

from app.config import EXTRACTED, RAW, SYNTHETIC
from app.masters.normalise import normalise_agri_year

CHUNK = 1 << 20


@dataclass(frozen=True)
class SourceSpec:
    """Everything the loader needs to know about one source file."""

    name: str
    path: Path
    source_type: str  # 'csv' | 'stata'
    data_origin: str  # 'official' | 'synthetic'
    target_table: str
    expected_columns: tuple[str, ...]
    encoding: str = "utf-8"
    year_columns: tuple[str, ...] = field(default=())
    generator_version: Optional[str] = None

    @property
    def raw_table(self) -> str:
        return f"raw.{self.name}"

    @property
    def staging_table(self) -> str:
        return f"staging.{self.name}"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


# Stata 12 and earlier open with <version><byteorder><filetype><unused>, where
# byteorder is 1 or 2 and filetype is 1. Stata 13+ announces itself in text.
_STATA_OLD_VERSIONS = frozenset({102, 103, 104, 105, 108, 110, 111, 112, 113, 114, 115})
_STATA_MAGIC = b"<stata_dta>"


def looks_like_stata(content: bytes) -> bool:
    """True when the bytes carry a Stata header, whatever the file is called."""
    if content[: len(_STATA_MAGIC)] == _STATA_MAGIC:
        return True
    return (
        len(content) >= 3
        and content[0] in _STATA_OLD_VERSIONS
        and content[1] in (1, 2)
        and content[2] == 1
    )


def detect_source_type(filename: str, content: bytes) -> str:
    """Pick the reader from the uploaded file itself, never from the target.

    Content is authoritative: a browser labels whatever it is given, so a CSV
    renamed ``.dta`` must still be read as a CSV and reported as a schema
    mismatch rather than crashing the Stata parser. The extension only decides
    when there are too few bytes to judge.
    """
    if looks_like_stata(content):
        return "stata"
    if len(content) < 3 and Path(filename).suffix.lower() == ".dta":
        return "stata"
    return "csv"


def read_source(spec: SourceSpec, path: Optional[Path] = None) -> pd.DataFrame:
    """Read a source file to an all-text frame with normalised headers.

    ``path`` overrides the spec's own path so an uploaded copy can be read by
    the identical code path.
    """
    target = Path(path) if path is not None else spec.path
    if spec.source_type == "stata":
        frame = pd.read_stata(target, convert_categoricals=False)
        frame = frame.astype("string")
    elif spec.source_type == "csv":
        frame = pd.read_csv(
            target, dtype="string", encoding=spec.encoding, keep_default_na=False
        )
        frame = frame.replace("", pd.NA)
    else:
        raise ValueError(f"unsupported source_type {spec.source_type!r}")

    # Published headers carry stray whitespace; the BOM is handled by the encoding.
    frame.columns = [str(column).strip() for column in frame.columns]
    for column in spec.year_columns:
        if column in frame.columns:
            frame[column] = frame[column].map(normalise_agri_year).astype("string")
    return frame.reset_index(drop=True)


_EARAS = RAW / "earas"

SOURCES: tuple[SourceSpec, ...] = (
    SourceSpec(
        name="price_statistics_2020",
        path=EXTRACTED / "price_statistics_odisha_2020_raw_long.csv",
        source_type="csv",
        data_origin="official",
        target_table="fact_price",
        expected_columns=(
            "table_no", "pdf_page", "price_type", "commodity", "sl_no",
            "district_as_published", "year", "raw_value", "price_rs_per_quintal",
            "cell_status",
        ),
        year_columns=("year",),
    ),
    SourceSpec(
        name="synthetic_monthly_prices",
        path=SYNTHETIC / "synthetic_monthly_prices.csv",
        source_type="csv",
        data_origin="synthetic",
        target_table="fact_price",
        expected_columns=(
            "agri_year", "month_start", "calendar_year", "month", "district_id",
            "district", "price_type", "commodity", "price_rs_per_quintal", "unit",
            "data_origin", "annual_level_basis", "annual_level_rs_per_quintal",
            "generator_version", "generator_seed",
        ),
        year_columns=("agri_year",),
        generator_version="synthetic-prices-v1",
    ),
    SourceSpec(
        name="earas_2024_25_district_crop_ayp",
        path=EXTRACTED / "earas_2024_25_district_crop_ayp_raw.csv",
        source_type="csv",
        data_origin="official",
        target_table="fact_crop_ayp",
        expected_columns=(
            "reference_year", "source_report", "pdf_page", "table_no", "crop_table",
            "product", "sl_no", "district_as_published", "is_state_total", "season",
            "measure", "unit", "raw_value", "value", "cell_status",
        ),
        year_columns=("reference_year",),
    ),
    SourceSpec(
        name="earas_2024_25_district_land_use",
        path=EXTRACTED / "earas_2024_25_district_land_use_raw.csv",
        source_type="csv",
        data_origin="official",
        target_table="fact_land_use",
        expected_columns=(
            "reference_year", "source_report", "pdf_page", "table_no", "sl_no",
            "district_as_published", "is_state_total", "land_use_category", "measure",
            "unit", "raw_value", "value", "cell_status",
        ),
        year_columns=("reference_year",),
    ),
    SourceSpec(
        name="earas_state_series",
        path=EXTRACTED / "earas_state_series_latest.csv",
        source_type="csv",
        data_origin="official",
        target_table="fact_state_series",
        expected_columns=(
            "reference_year", "crop", "product", "season", "measure", "unit",
            "raw_value", "value", "cell_status", "source_report", "report_year",
            "table_no", "pdf_page", "reports_containing_value",
        ),
        year_columns=("reference_year",),
    ),
    SourceSpec(
        name="earas_2022_23_block_land_use",
        path=_EARAS / "2022-23" / "blockwise_LUS_202223.dta",
        source_type="stata",
        data_origin="official",
        target_table="fact_land_use",
        expected_columns=(
            "Year", "District", "Block", "Code", "Block_Urban_Dist_State_Total",
            "Land_Use_Category", "Area_Hectare",
        ),
        year_columns=("Year",),
    ),
    SourceSpec(
        name="earas_2022_23_block_paddy",
        path=_EARAS / "2022-23" / "blockwise_paddy_AYP_2022-23.dta",
        source_type="stata",
        data_origin="official",
        target_table="fact_crop_ayp",
        expected_columns=(
            "Year", "District", "Block", "Block_Urban_Dist_total", "Season", "Crop",
            "Area_ha", "YieldRate_qtl_per_ha", "Production_qtl",
        ),
        year_columns=("Year",),
    ),
    SourceSpec(
        name="earas_2022_23_district_minor_crops",
        path=_EARAS / "2022-23" / "distwise_minorcrops_AYP2022-23.dta",
        source_type="stata",
        data_origin="official",
        target_table="fact_crop_ayp",
        expected_columns=(
            "Year", "District", "Season", "Crop", "Area_hectares",
            "Yield_Rate_qtl_ha", "Prodn_quintals",
        ),
        year_columns=("Year",),
    ),
    SourceSpec(
        name="earas_2023_24_block_land_use",
        path=_EARAS / "2023-24" / "blockwise_LUS_2023_24.csv",
        source_type="csv",
        data_origin="official",
        target_table="fact_land_use",
        encoding="utf-8-sig",
        expected_columns=(
            "Year", "District", "Block", "Code", "Block_Urban", "Land Use Category",
            "Area in Ha",
        ),
        year_columns=("Year",),
    ),
    SourceSpec(
        name="earas_2023_24_block_paddy",
        path=_EARAS / "2023-24" / "blockwise_paddy_AYP_2023_24.csv",
        source_type="csv",
        data_origin="official",
        target_table="fact_crop_ayp",
        expected_columns=(
            "Year", "District", "Block", "Block_Urban", "Season", "Crop", "Area_ha",
            "Yield_qtl_per_ha", "Production_qtls",
        ),
        year_columns=("Year",),
    ),
    SourceSpec(
        name="earas_2023_24_district_paddy",
        path=_EARAS / "2023-24" / "dist_paddy_AYP_2023-24.csv",
        source_type="csv",
        data_origin="official",
        target_table="fact_crop_ayp",
        encoding="utf-8-sig",
        expected_columns=(
            "Year", "District", "Season", "Crop_Paddy_Rice", "Area_000ha",
            "Yield_rate_qtl_ha", "Production_000MT",
        ),
        year_columns=("Year",),
    ),
    SourceSpec(
        name="earas_2023_24_district_minor_crops",
        path=_EARAS / "2023-24" / "distwise_minor_crop_AYP_2023-24.csv",
        source_type="csv",
        data_origin="official",
        target_table="fact_crop_ayp",
        expected_columns=(
            "Year", "District", "Season", "Minor_Crop", "Area_ha",
            "Yield_rate_qtl_per_ha", "Production_qtls",
        ),
        year_columns=("Year",),
    ),
)

SOURCES_BY_NAME: dict[str, SourceSpec] = {spec.name: spec for spec in SOURCES}


def spec_for_upload(dataset_name: str) -> SourceSpec:
    """Look up the spec an uploaded file claims to be an instance of."""
    try:
        return SOURCES_BY_NAME[dataset_name]
    except KeyError:
        known = ", ".join(sorted(SOURCES_BY_NAME))
        raise KeyError(f"unknown dataset {dataset_name!r}; known datasets: {known}")
