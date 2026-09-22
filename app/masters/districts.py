"""District master + alias resolver.

``district_master.csv`` (30 districts) and ``district_aliases.csv`` (103
spellings) are produced by ``scripts/build_district_master.py`` and are read
here read-only. Resolution is exact-after-normalisation; state-total labels
resolve to ``OD00`` and are reported separately so callers can keep them out of
district-level aggregates.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

import pandas as pd

from app.config import EXTRACTED, STATE_DISTRICT_ID
from app.masters.normalise import normalise_key

MASTER_PATH = EXTRACTED / "district_master.csv"
ALIASES_PATH = EXTRACTED / "district_aliases.csv"

MASTER_COLUMNS = [
    "district_id",
    "display_name",
    "lgd_name",
    "lgd_code",
    "census_2011_code",
    "headquarters",
]


@dataclass(frozen=True)
class DistrictMatch:
    district_id: str
    display_name: str
    is_state_total: bool


@lru_cache(maxsize=1)
def _tables() -> tuple[pd.DataFrame, dict[str, DistrictMatch]]:
    master = pd.read_csv(MASTER_PATH, dtype=str)
    aliases = pd.read_csv(ALIASES_PATH, dtype=str)
    lookup: dict[str, DistrictMatch] = {}
    for row in aliases.itertuples(index=False):
        lookup[normalise_key(row.name_as_published)] = DistrictMatch(
            district_id=row.district_id,
            display_name=row.display_name,
            is_state_total=row.district_id == STATE_DISTRICT_ID,
        )
    # The master's own display names must resolve even if an alias row is missing.
    for row in master.itertuples(index=False):
        lookup.setdefault(
            normalise_key(row.display_name),
            DistrictMatch(row.district_id, row.display_name, False),
        )
    return master, lookup


def district_master() -> pd.DataFrame:
    """The 30 real districts, ordered by ``district_id``."""
    master, _ = _tables()
    return (
        master[MASTER_COLUMNS]
        .sort_values("district_id", kind="stable", ignore_index=True)
        .copy()
    )


def resolve_district(name: object) -> Optional[DistrictMatch]:
    """Resolve a published district name; ``None`` means unknown (never guessed)."""
    _, lookup = _tables()
    return lookup.get(normalise_key(name))
