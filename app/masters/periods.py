"""Deterministic ``period_id`` construction for the three period grains."""
from __future__ import annotations

import pandas as pd

from app.masters.normalise import normalise_agri_year

def year_period(agri_year: object) -> str:
    return f"Y:{normalise_agri_year(agri_year)}"


def season_period(agri_year: object, season: object) -> str:
    return f"S:{normalise_agri_year(agri_year)}:{str(season).strip()}"


def month_period(month_start: object) -> str:
    """``month_start`` is the first day of the calendar month, e.g. 2014-02-01."""
    stamp = pd.Timestamp(month_start)
    return f"M:{stamp.year:04d}-{stamp.month:02d}"


def period_rows(periods: pd.DataFrame) -> pd.DataFrame:
    """Deduplicate collected period tuples into ``dim_period`` rows."""
    return (
        periods.drop_duplicates(subset=["period_id"])
        .sort_values("period_id", kind="stable", ignore_index=True)
        .loc[:, ["period_id", "agri_year", "season", "month_start", "period_type"]]
        .copy()
    )
