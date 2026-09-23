"""The panel-level provenance disclosure, in one place.

The UI shows these as a quiet line in a panel header; an export writes the same
line into the file -- the CSV header block, the Excel Context sheet, the PDF
footer, the JSON applied_context. The wording lives here rather than in either
surface so a file and the screen it came from can never word the same
disclosure differently.

Derived from three backend fields and nothing else: ``data_origin``,
``annual_level_basis`` and ``grain_source``.
"""
from __future__ import annotations

from typing import Mapping, Optional, Union

Mix = Union[Mapping[str, int], str, None]

SYNTHETIC = "Representative dataset modelled on DE&S Price Statistics, 2013-19"
MODEL = "Analytical Estimates"
AGGREGATED = "District figures aggregated from block-level data"


def _present(value: Mix, key: str) -> bool:
    """True when ``key`` is named, whether it arrived as a mix or a scalar."""
    if not value:
        return False
    if isinstance(value, str):
        return value == key
    return int(value.get(key, 0) or 0) > 0


def provenance_notes(
    data_origin: Mix = None,
    grain_source: Mix = None,
    annual_level_basis: Mix = None,
) -> list[str]:
    """The disclosure lines this data owes its reader, in a fixed order."""
    notes: list[str] = []
    if _present(data_origin, "synthetic"):
        notes.append(SYNTHETIC)
    if _present(data_origin, "model"):
        notes.append(MODEL)
    if _present(grain_source, "aggregated_from_blocks"):
        notes.append(AGGREGATED)
    return notes


def notes_from_context(context: Optional[Mapping[str, object]]) -> list[str]:
    """The same lines, straight from an ``applied_context``."""
    if not context:
        return []
    origin = context.get("data_origin")
    grain = context.get("grain_source")
    return provenance_notes(
        data_origin=origin if isinstance(origin, (dict, str)) else None,
        grain_source=grain if isinstance(grain, (dict, str)) else None,
    )
