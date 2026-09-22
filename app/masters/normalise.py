"""Deterministic string normalisation shared by every master lookup.

One function per vocabulary so that the district resolver, the crop resolver and
the block resolver all fold names the same way. No fuzzy matching anywhere: a
name either folds onto a known key or it is a validation finding.
"""
from __future__ import annotations

import re

_NON_ALNUM = re.compile(r"[^A-Z0-9]+")
_AGRI_YEAR = re.compile(r"^(\d{4})\D?(\d{2,4})$")

# Odisha agricultural year runs July -> June.
AGRI_YEAR_START_MONTH = 7


def normalise_key(value: object) -> str:
    """Fold a published name to its lookup key: uppercase, alphanumerics only.

    Collapses the real-world variation in the DE&S sources -- ``ORISSA  STATE``
    (two spaces), ``Athamalik``/``ATHAMALIK``, ``Nabarangapur``/``Nabrangpur``
    is *not* collapsed (that is an alias-table job, not a normalisation job).
    """
    if value is None:
        return ""
    return _NON_ALNUM.sub("", str(value).strip().upper())


def normalise_agri_year(value: object) -> str:
    """Normalise every published agricultural-year spelling to ``YYYY-YY``.

    The 2022-23 Stata files publish ``2022_23``; everything else publishes
    ``2023-24``. Returns the input stripped if it cannot be parsed, so the
    caller's validation rule -- not this helper -- reports the problem.
    """
    raw = str(value).strip() if value is not None else ""
    match = _AGRI_YEAR.match(raw)
    if not match:
        return raw
    start, end = match.group(1), match.group(2)
    return f"{start}-{end[-2:]}"

