"""The no-new-numbers check applied to anything a model writes.

Every number in model prose must be one the backend supplied: a value from the
result rows, a year or value from the applied filters, or a count stated in a
caveat. Rounding is allowed -- "52.19" may quote 52.1915 -- arithmetic is not.
A sum, a difference, a share or a unit conversion is a number the database
never produced, so it fails.

Numbers written as words ("three districts") are not checked; the prompts ask
for digits only where a figure is quoted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

# Agricultural years and months (2024-25, 2019-07) are labels, matched as whole
# strings rather than split into two numbers.
_YEAR = re.compile(r"(?<![\w-])\d{4}-\d{2}(?![\w-]|\.\d)")
# A number not glued to letters, so district and crop codes (OD07, CR17) are
# not read as figures.
_NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")


@dataclass(frozen=True)
class Allowed:
    years: frozenset[str]
    values: tuple[float, ...]


def _tokens(text: str) -> tuple[list[str], list[str]]:
    years = _YEAR.findall(text)
    rest = _YEAR.sub(" ", text)
    numbers = [token.rstrip(",") for token in _NUMBER.findall(rest)]
    return years, [token for token in numbers if token]


def collect(sources: Iterable[object]) -> Allowed:
    """Every number and year appearing anywhere in ``sources``, recursively."""
    years: set[str] = set()
    values: set[float] = set()

    def walk(item: object) -> None:
        if item is None or isinstance(item, bool):
            return
        if isinstance(item, (int, float)):
            values.add(abs(float(item)))
        elif isinstance(item, str):
            found_years, found_numbers = _tokens(item)
            years.update(found_years)
            values.update(abs(float(token.replace(",", ""))) for token in found_numbers)
        elif isinstance(item, dict):
            for value in item.values():
                walk(value)
        elif isinstance(item, (list, tuple, set, frozenset)):
            for value in item:
                walk(value)
        else:
            # numpy scalars and the like
            try:
                values.add(abs(float(item)))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                walk(str(item))

    for source in sources:
        walk(source)
    return Allowed(frozenset(years), tuple(sorted(values)))


def _matches(token: str, allowed: tuple[float, ...]) -> bool:
    decimals = len(token.split(".", 1)[1]) if "." in token else 0
    written = float(token.replace(",", ""))
    # Within half a unit of the last written digit: a rounding of a supplied
    # value, not a new one.
    tolerance = 0.5 * 10 ** (-decimals) + 1e-9
    return any(abs(value - written) <= tolerance for value in allowed)


def unsupported(text: str, allowed: Allowed) -> list[str]:
    """The numbers in ``text`` that ``allowed`` does not account for."""
    years, numbers = _tokens(text)
    bad = [year for year in years if year not in allowed.years]
    bad += [token for token in numbers if not _matches(token, allowed.values)]
    return bad
