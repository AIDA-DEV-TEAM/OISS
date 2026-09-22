"""Curated crop master, mirroring ``district_master.csv`` / ``district_aliases.csv``.

The five vocabularies in play (2022-23 EARAS, 2023-24 EARAS, the 2024-25 report,
the price statistics and the teammate's yield API) name the same crops
differently. Every spelling that actually occurs in a bundled source is listed
here explicitly. Lookup is exact-after-normalisation; an unlisted name raises a
``UNKNOWN_CROP`` finding rather than being guessed at.

``crop_id`` is ``CR01``..``CR23``, assigned alphabetically by display name so the
ids are stable across rebuilds.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from app.config import EXTRACTED
from app.masters.normalise import normalise_key

CROP_GROUPS = ("cereal", "pulse", "oilseed", "fibre", "tuber", "vegetable", "sugar")


@dataclass(frozen=True)
class Crop:
    display_name: str
    crop_group: str
    in_earas: bool
    in_price: bool
    aliases: tuple[str, ...] = field(default=())


# Equivalences per the brief: Biri = Blackgram, Mung = Greengram,
# Kulthi = Horsegram, Nizer = Niger, Grountnut (as printed) = Groundnut.
_CROPS: tuple[Crop, ...] = (
    Crop("Arhar", "pulse", False, True, ("Arhar", "Tur", "Pigeonpea")),
    Crop("Bajra", "cereal", False, True, ("Bajra",)),
    Crop("Biri", "pulse", True, True, ("Biri", "Blackgram", "Black Gram", "Urad")),
    Crop("Castor", "oilseed", False, True, ("Castor",)),
    Crop("Cotton", "fibre", False, True, ("Cotton",)),
    Crop("Gram", "pulse", False, True, ("Gram", "Bengal Gram", "Chana")),
    Crop("Groundnut", "oilseed", True, True, ("Groundnut", "Grountnut", "Ground Nut")),
    Crop("Jowar", "cereal", False, True, ("Jowar",)),
    Crop("Jute", "fibre", True, True, ("Jute",)),
    Crop("Kulthi", "pulse", True, True, ("Kulthi", "Horsegram", "Horse Gram")),
    Crop("Linseed", "oilseed", False, True, ("Linseed",)),
    Crop("Maize", "cereal", True, True, ("Maize",)),
    Crop("Mung", "pulse", True, True, ("Mung", "Greengram", "Green Gram", "Moong")),
    Crop("Mustard", "oilseed", True, True, ("Mustard", "Rape & Mustard", "Rapeseed & Mustard")),
    Crop("Nizer", "oilseed", True, False, ("Nizer", "Niger", "Nigerseed")),
    Crop("Onion", "vegetable", False, True, ("Onion",)),
    Crop("Paddy", "cereal", True, True, ("Paddy", "Rice", "Paddy/Rice")),
    Crop("Potato", "tuber", True, True, ("Potato",)),
    Crop("Ragi", "cereal", True, True, ("Ragi", "Mandia", "Finger Millet")),
    Crop("Sugarcane", "sugar", True, True, ("Sugarcane", "Sugar Cane")),
    Crop("Sunflower", "oilseed", False, True, ("Sunflower",)),
    Crop("Til", "oilseed", True, True, ("Til", "Sesamum", "Sesame")),
    Crop("Wheat", "cereal", True, True, ("Wheat",)),
)


def _build() -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, alias_rows = [], []
    for index, crop in enumerate(sorted(_CROPS, key=lambda c: c.display_name), start=1):
        crop_id = f"CR{index:02d}"
        rows.append(
            {
                "crop_id": crop_id,
                "display_name": crop.display_name,
                "crop_group": crop.crop_group,
                "in_earas": crop.in_earas,
                "in_price": crop.in_price,
            }
        )
        # Spaced and unspaced spellings ("Black Gram"/"Blackgram") fold to one
        # key; keep the first spelling of each key, drop the rest.
        seen: dict[str, str] = {}
        for name in (crop.display_name, *crop.aliases):
            seen.setdefault(normalise_key(name), name)
        for name in seen.values():
            alias_rows.append(
                {
                    "name_as_published": name,
                    "normalised_key": normalise_key(name),
                    "crop_id": crop_id,
                    "display_name": crop.display_name,
                }
            )
    master = pd.DataFrame(rows)
    aliases = pd.DataFrame(alias_rows).sort_values(
        ["crop_id", "normalised_key"], kind="stable", ignore_index=True
    )
    # A key mapping to two different crops would make lookup non-deterministic.
    clashes = aliases.groupby("normalised_key").crop_id.nunique()
    if (clashes > 1).any():
        raise ValueError(
            f"crop alias keys map to multiple crops: {sorted(clashes[clashes > 1].index)}"
        )
    return master, aliases


CROP_MASTER, CROP_ALIASES = _build()
_BY_KEY: dict[str, str] = dict(zip(CROP_ALIASES.normalised_key, CROP_ALIASES.crop_id))


def resolve_crop(name: object) -> Optional[str]:
    """Return the ``crop_id`` for a published crop name, or ``None`` if unknown."""
    return _BY_KEY.get(normalise_key(name))


def write_crop_master_csv(path=None) -> "pathlib.Path":
    """Write the generated ``crop_master.csv`` alongside the district master."""
    target = path or (EXTRACTED / "crop_master.csv")
    CROP_MASTER.to_csv(target, index=False, lineterminator="\n")
    CROP_ALIASES.to_csv(
        target.parent / "crop_aliases.csv", index=False, lineterminator="\n"
    )
    return target


import pathlib  # noqa: E402  (only needed for the return annotation above)
