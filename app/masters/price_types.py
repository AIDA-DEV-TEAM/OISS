"""The two price series DE&S publishes, as a master like districts and crops.

``PRICE_TYPE_ALIASES`` resolves a published spelling to its code; the master
gives each code its display name, so a filter or a file reads "Farm harvest"
rather than ``farm_harvest``.
"""
from __future__ import annotations

import pandas as pd

# normalise_key of the published label -> code.
PRICE_TYPE_ALIASES: dict[str, str] = {"FARMHARVEST": "farm_harvest", "WHOLESALE": "wholesale"}

PRICE_TYPE_MASTER = pd.DataFrame(
    [
        {"price_type": "farm_harvest", "display_name": "Farm harvest"},
        {"price_type": "wholesale", "display_name": "Wholesale"},
    ]
)
