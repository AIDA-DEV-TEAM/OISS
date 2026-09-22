"""The IDENTITY_MISMATCH warnings must stay explainable as publisher rounding.

DE&S publishes area, yield and production independently rounded, so on small
quantities ``area x yield`` cannot reproduce ``production`` exactly. This test
pins that explanation: every mismatch must be consistent with the intervals the
published decimal precision allows. If one is not, the cause is something other
than rounding and the test says so rather than letting it pass as noise.
"""
from __future__ import annotations

import pandas as pd
import pytest

from app.ingest.readers import SOURCES_BY_NAME, read_source
from app.validation.rules import IDENTITY_TOLERANCE

# (measure columns, factor to canonical units, half of the last published decimal
# place in published units). The 2022-23 file is Stata-typed, so its precision
# comes from the publisher's convention -- whole hectares and whole quintals --
# not from how pandas renders the float.
SOURCES = {
    "earas_2022_23_district_minor_crops": {
        "columns": ("Area_hectares", "Yield_Rate_qtl_ha", "Prodn_quintals"),
        "factors": (1.0, 1.0, 1.0),
        "half_ulp": (0.5, 0.005, 0.5),
        "labels": ("District", "Crop", "Season"),
    },
    "earas_2023_24_district_minor_crops": {
        "columns": ("Area_ha", "Yield_rate_qtl_per_ha", "Production_qtls"),
        "factors": (1.0, 1.0, 1.0),
        "half_ulp": (0.5, 0.005, 0.5),
        "labels": ("District", "Minor_Crop", "Season"),
    },
    "earas_2023_24_district_paddy": {
        "columns": ("Area_000ha", "Yield_rate_qtl_ha", "Production_000MT"),
        "factors": (1_000.0, 1.0, 10_000.0),
        "half_ulp": (0.005, 0.005, 0.005),
        "labels": ("District", "Crop_Paddy_Rice", "Season"),
    },
}


def _mismatches(name: str) -> pd.DataFrame:
    spec = SOURCES[name]
    raw = read_source(SOURCES_BY_NAME[name])
    area_column, yield_column, production_column = spec["columns"]
    area_factor, yield_factor, production_factor = spec["factors"]

    area = pd.to_numeric(raw[area_column], errors="coerce") * area_factor
    rate = pd.to_numeric(raw[yield_column], errors="coerce") * yield_factor
    production = pd.to_numeric(raw[production_column], errors="coerce") * production_factor

    deviation = ((area * rate) - production).abs() / production.abs().where(production != 0)
    flagged = deviation.notna() & (deviation > IDENTITY_TOLERANCE)

    area_slack = spec["half_ulp"][0] * area_factor
    yield_slack = spec["half_ulp"][1] * yield_factor
    production_slack = spec["half_ulp"][2] * production_factor

    # Widest and narrowest products the published, rounded inputs could stand for.
    lowest = (area - area_slack).clip(lower=0) * (rate - yield_slack).clip(lower=0)
    highest = (area + area_slack) * (rate + yield_slack)
    consistent = (highest >= production - production_slack) & (
        lowest <= production + production_slack
    )

    return pd.DataFrame(
        {
            "source": name,
            "district": raw[spec["labels"][0]],
            "crop": raw[spec["labels"][1]],
            "season": raw[spec["labels"][2]],
            "production": production,
            "deviation_pct": deviation * 100,
            "rounding_explains": consistent,
        }
    )[flagged]


@pytest.fixture(scope="module")
def mismatches() -> pd.DataFrame:
    return pd.concat([_mismatches(name) for name in SOURCES], ignore_index=True)


def test_every_identity_mismatch_is_explained_by_published_rounding(
    mismatches: pd.DataFrame,
) -> None:
    unexplained = mismatches[~mismatches.rounding_explains]
    assert unexplained.empty, (
        "identity mismatches not attributable to rounding:\n"
        + unexplained.to_string(index=False)
    )


def test_mismatches_concentrate_at_small_quantities(mismatches: pd.DataFrame) -> None:
    """Rounding bites when the quantity is near the published unit, not at scale."""
    assert len(mismatches) > 0
    assert mismatches.production.max() < 10_000, (
        "a large-quantity mismatch is not rounding"
    )
    small = mismatches[mismatches.production <= 100]
    assert len(small) / len(mismatches) > 0.7, (
        "mismatches are not concentrated at small quantities:\n"
        + mismatches.to_string(index=False)
    )


def test_mismatches_are_not_confined_to_one_crop_or_source(
    mismatches: pd.DataFrame,
) -> None:
    """Clustering would point at a systematic error rather than rounding."""
    assert mismatches.source.nunique() == len(SOURCES)
    largest_crop_share = mismatches.crop.value_counts(normalize=True).iloc[0]
    assert largest_crop_share < 0.25, (
        f"one crop accounts for {largest_crop_share:.0%} of mismatches:\n"
        + mismatches.crop.value_counts().to_string()
    )


def test_the_count_matches_what_the_loader_reports(mismatches: pd.DataFrame, con) -> None:
    reported = con.execute(
        "SELECT finding_count FROM analytics.finding_summary "
        "WHERE rule_code = 'IDENTITY_MISMATCH'"
    ).fetchone()
    assert reported is not None
    assert reported[0] == len(mismatches)
