"""Named, independently callable validation rules.

Each rule takes a dataframe plus a :class:`RuleContext` and returns a list of
:class:`Finding`. Severity decides what the loader does with the row:

* ``error``   -- the row is quarantined and never reaches staging/analytics.
* ``warning`` -- the row passes through, flagged.
* ``info``    -- recorded for lineage/provenance only.

Rules never mutate the frame and never repair a value. Deciding what to do with
a finding is the loader's job, not the rule's.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

import pandas as pd

from app.masters.crop_master import resolve_crop
from app.masters.districts import resolve_district
from app.masters.normalise import normalise_key

SEVERITIES = ("error", "warning", "info")

# Plausibility bounds from the brief. Yields are quintals/hectare, prices are
# rupees/quintal; anything outside these is a warning, not a rejection.
YIELD_MIN, YIELD_MAX = 0.0, 1_200.0
PRICE_MIN, PRICE_MAX = 0.0, 50_000.0
IDENTITY_TOLERANCE = 0.02


@dataclass(frozen=True)
class Finding:
    rule_code: str
    severity: str
    row_ref: str
    column_name: Optional[str]
    message: str
    observed_value: Optional[str]

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"unknown severity {self.severity!r}")


@dataclass
class RuleContext:
    """Identifies the rows a rule is looking at, for readable row references."""

    dataset_name: str
    row_ref_columns: Sequence[str] = field(default_factory=tuple)

    def row_ref(self, frame: pd.DataFrame, index: object) -> str:
        parts = [f"row={index}"]
        for column in self.row_ref_columns:
            if column in frame.columns:
                parts.append(f"{column}={frame.at[index, column]}")
        return "|".join(parts)


def quarantine_index(findings: Iterable[Finding]) -> set[int]:
    """Row indices that at least one ``error`` finding points at."""
    out: set[int] = set()
    for finding in findings:
        if finding.severity != "error":
            continue
        head = finding.row_ref.split("|", 1)[0]
        if head.startswith("row="):
            out.add(int(head[4:]))
    return out


# --------------------------------------------------------------------------
# Structural rules
# --------------------------------------------------------------------------
def check_schema(
    frame: pd.DataFrame, expected: Sequence[str], ctx: RuleContext
) -> list[Finding]:
    """SCHEMA_MISMATCH -- a declared column is missing, or an extra one appeared."""
    findings: list[Finding] = []
    present = list(frame.columns)
    for column in expected:
        if column not in present:
            findings.append(
                Finding(
                    "SCHEMA_MISMATCH",
                    "error",
                    f"dataset={ctx.dataset_name}",
                    column,
                    f"expected column {column!r} is missing",
                    None,
                )
            )
    for column in present:
        if column not in expected:
            findings.append(
                Finding(
                    "SCHEMA_MISMATCH",
                    "error",
                    f"dataset={ctx.dataset_name}",
                    column,
                    f"unexpected column {column!r} not in the declared schema",
                    None,
                )
            )
    return findings


def check_type_mismatch(
    frame: pd.DataFrame, columns: Sequence[str], ctx: RuleContext
) -> list[Finding]:
    """TYPE_MISMATCH -- non-numeric text where a number is required.

    A blank is not a type error (that is MISSING_VALUE); ``NA``, a dash and
    stray text are.
    """
    findings: list[Finding] = []
    for column in columns:
        if column not in frame.columns:
            continue
        raw = frame[column]
        blank = raw.isna() | (raw.astype(str).str.strip() == "")
        coerced = pd.to_numeric(
            raw.astype(str).str.strip().str.replace(",", "", regex=False),
            errors="coerce",
        )
        bad = coerced.isna() & ~blank
        for index in frame.index[bad]:
            findings.append(
                Finding(
                    "TYPE_MISMATCH",
                    "error",
                    ctx.row_ref(frame, index),
                    column,
                    f"{column!r} is not numeric",
                    str(frame.at[index, column]),
                )
            )
    return findings


def check_duplicate_key(
    frame: pd.DataFrame, key_columns: Sequence[str], ctx: RuleContext
) -> list[Finding]:
    """DUPLICATE_KEY -- more than one row on the fact's natural key."""
    usable = [column for column in key_columns if column in frame.columns]
    if not usable:
        return []
    duplicated = frame.duplicated(subset=usable, keep="first")
    findings: list[Finding] = []
    for index in frame.index[duplicated]:
        key = ", ".join(f"{column}={frame.at[index, column]}" for column in usable)
        findings.append(
            Finding(
                "DUPLICATE_KEY",
                "error",
                ctx.row_ref(frame, index),
                ",".join(usable),
                f"duplicate natural key ({key})",
                key,
            )
        )
    return findings


# --------------------------------------------------------------------------
# Master-data rules
# --------------------------------------------------------------------------
def check_unknown_district(
    frame: pd.DataFrame, column: str, ctx: RuleContext
) -> list[Finding]:
    """UNKNOWN_DISTRICT -- a name absent from district_aliases (never guessed)."""
    if column not in frame.columns:
        return []
    findings: list[Finding] = []
    for name in frame[column].dropna().unique():
        if resolve_district(name) is not None:
            continue
        for index in frame.index[frame[column] == name]:
            findings.append(
                Finding(
                    "UNKNOWN_DISTRICT",
                    "error",
                    ctx.row_ref(frame, index),
                    column,
                    f"district {name!r} is not in district_aliases.csv",
                    str(name),
                )
            )
    return findings


def check_unknown_crop(
    frame: pd.DataFrame, column: str, ctx: RuleContext
) -> list[Finding]:
    """UNKNOWN_CROP -- a crop name absent from the crop master."""
    if column not in frame.columns:
        return []
    findings: list[Finding] = []
    for name in frame[column].dropna().unique():
        if resolve_crop(name) is not None:
            continue
        for index in frame.index[frame[column] == name]:
            findings.append(
                Finding(
                    "UNKNOWN_CROP",
                    "error",
                    ctx.row_ref(frame, index),
                    column,
                    f"crop {name!r} is not in the crop master",
                    str(name),
                )
            )
    return findings


def check_unknown_block(
    frame: pd.DataFrame,
    district_column: str,
    block_column: str,
    known_keys: set[str],
    ctx: RuleContext,
) -> list[Finding]:
    """UNKNOWN_BLOCK -- a (district, block) pair with no match in dim_block.

    70-odd paddy blocks are spelled differently from the land-use file that
    defines the block codes. Those rows keep their district and load with a null
    ``block_id`` rather than being dropped, so this is a warning.
    """
    if district_column not in frame.columns or block_column not in frame.columns:
        return []
    findings: list[Finding] = []
    for index in frame.index:
        district = resolve_district(frame.at[index, district_column])
        if district is None:
            continue
        key = f"{district.district_id}|{normalise_key(frame.at[index, block_column])}"
        if key in known_keys:
            continue
        name = frame.at[index, block_column]
        findings.append(
            Finding(
                "UNKNOWN_BLOCK",
                "warning",
                ctx.row_ref(frame, index),
                block_column,
                f"block {name!r} does not match a coded block in "
                f"{district.display_name}; loaded with block_id = NULL",
                str(name),
            )
        )
    return findings


# --------------------------------------------------------------------------
# Value rules
# --------------------------------------------------------------------------
def check_out_of_range(
    frame: pd.DataFrame, column: str, kind: str, ctx: RuleContext
) -> list[Finding]:
    """OUT_OF_RANGE -- negative or implausible yields and prices."""
    if column not in frame.columns:
        return []
    low, high = (YIELD_MIN, YIELD_MAX) if kind == "yield" else (PRICE_MIN, PRICE_MAX)
    values = pd.to_numeric(frame[column], errors="coerce")
    bad = values.notna() & ((values <= low) | (values > high))
    findings: list[Finding] = []
    for index in frame.index[bad]:
        findings.append(
            Finding(
                "OUT_OF_RANGE",
                "warning",
                ctx.row_ref(frame, index),
                column,
                f"{kind} value outside the plausible range ({low}, {high}]",
                str(values.at[index]),
            )
        )
    return findings


def _null_rows(frame: pd.DataFrame, column: str) -> pd.Index:
    return frame.index[pd.to_numeric(frame[column], errors="coerce").isna()]


def _absent(frame: pd.DataFrame, index: object, key_column: Optional[str], present: Optional[set[str]]) -> bool:
    """True when this row's series has no value anywhere in any source."""
    if present is None or key_column is None or key_column not in frame.columns:
        return False
    return frame.at[index, key_column] not in present


def check_missing_value(
    frame: pd.DataFrame,
    columns: Sequence[str],
    ctx: RuleContext,
    present_keys: Optional[set[str]] = None,
    key_column: Optional[str] = None,
) -> list[Finding]:
    """MISSING_VALUE -- a gap inside an otherwise populated series.

    With ``present_keys`` supplied, a null whose whole series is empty is left
    to :func:`check_structurally_absent` instead, so this warning means a real
    hole rather than a crop that is simply not grown there.
    """
    findings: list[Finding] = []
    for column in columns:
        if column not in frame.columns:
            continue
        for index in _null_rows(frame, column):
            if _absent(frame, index, key_column, present_keys):
                continue
            findings.append(
                Finding(
                    "MISSING_VALUE",
                    "warning",
                    ctx.row_ref(frame, index),
                    column,
                    f"{column!r} has no value",
                    None,
                )
            )
    return findings


def check_structurally_absent(
    frame: pd.DataFrame,
    columns: Sequence[str],
    ctx: RuleContext,
    present_keys: set[str],
    key_column: str,
) -> list[Finding]:
    """STRUCTURALLY_ABSENT -- the series does not exist, rather than being missing.

    A crop that is not grown (or not priced) in a district never has a value in
    any year of any source. Reporting that as a data-quality warning would bury
    the real gaps, so it is recorded as information.
    """
    if key_column not in frame.columns:
        return []
    findings: list[Finding] = []
    for column in columns:
        if column not in frame.columns:
            continue
        for index in _null_rows(frame, column):
            if not _absent(frame, index, key_column, present_keys):
                continue
            findings.append(
                Finding(
                    "STRUCTURALLY_ABSENT",
                    "info",
                    ctx.row_ref(frame, index),
                    column,
                    "no value in any year of any source for this series; treated "
                    "as not grown or not priced rather than as a missing value",
                    str(frame.at[index, key_column]),
                )
            )
    return findings


def check_total_row_in_detail(
    frame: pd.DataFrame, column: str, ctx: RuleContext
) -> list[Finding]:
    """TOTAL_ROW_IN_DETAIL -- a state/total row sitting among district rows."""
    if column not in frame.columns:
        return []
    findings: list[Finding] = []
    for index in frame.index:
        name = frame.at[index, column]
        match = resolve_district(name)
        if match is None or not match.is_state_total:
            continue
        findings.append(
            Finding(
                "TOTAL_ROW_IN_DETAIL",
                "warning",
                ctx.row_ref(frame, index),
                column,
                f"{name!r} is a state total mixed into district rows; excluded "
                "from district-level aggregates",
                str(name),
            )
        )
    return findings


def check_identity(
    frame: pd.DataFrame,
    area_column: str,
    yield_column: str,
    production_column: str,
    ctx: RuleContext,
    tolerance: float = IDENTITY_TOLERANCE,
) -> list[Finding]:
    """IDENTITY_MISMATCH -- area x yield differs from production beyond tolerance."""
    for column in (area_column, yield_column, production_column):
        if column not in frame.columns:
            return []
    area = pd.to_numeric(frame[area_column], errors="coerce")
    rate = pd.to_numeric(frame[yield_column], errors="coerce")
    production = pd.to_numeric(frame[production_column], errors="coerce")
    expected = area * rate
    deviation = (expected - production).abs() / production.abs().where(production != 0)
    bad = deviation.notna() & (deviation > tolerance)
    findings: list[Finding] = []
    for index in frame.index[bad]:
        findings.append(
            Finding(
                "IDENTITY_MISMATCH",
                "warning",
                ctx.row_ref(frame, index),
                production_column,
                f"area x yield = {expected.at[index]:.2f} but production is "
                f"{production.at[index]:.2f} ({deviation.at[index] * 100:.1f} pct apart)",
                str(production.at[index]),
            )
        )
    return findings


def check_cross_source_mismatch(
    left: pd.DataFrame,
    right: pd.DataFrame,
    key_columns: Sequence[str],
    value_column: str,
    ctx: RuleContext,
    tolerance: float = IDENTITY_TOLERANCE,
    left_label: str = "left",
    right_label: str = "right",
) -> list[Finding]:
    """CROSS_SOURCE_MISMATCH -- the same measure differs between two DE&S sources."""
    merged = left.merge(right, on=list(key_columns), suffixes=("_l", "_r"), how="inner")
    left_values = pd.to_numeric(merged[f"{value_column}_l"], errors="coerce")
    right_values = pd.to_numeric(merged[f"{value_column}_r"], errors="coerce")
    deviation = (left_values - right_values).abs() / right_values.abs().where(
        right_values != 0
    )
    bad = deviation.notna() & (deviation > tolerance)
    findings: list[Finding] = []
    for index in merged.index[bad]:
        key = ", ".join(f"{column}={merged.at[index, column]}" for column in key_columns)
        findings.append(
            Finding(
                "CROSS_SOURCE_MISMATCH",
                "info",
                f"key={key}",
                value_column,
                f"{left_label} reports {left_values.at[index]:.2f} where "
                f"{right_label} reports {right_values.at[index]:.2f}",
                str(left_values.at[index]),
            )
        )
    return findings


def check_msp_substituted(
    frame: pd.DataFrame, status_column: str, commodity_column: str, ctx: RuleContext
) -> list[Finding]:
    """MSP_SUBSTITUTED -- provisional paddy prices are MSP, not observed prices."""
    if status_column not in frame.columns:
        return []
    flagged = frame[status_column].astype(str).str.strip() == "provisional"
    findings: list[Finding] = []
    for index in frame.index[flagged]:
        commodity = (
            frame.at[index, commodity_column]
            if commodity_column in frame.columns
            else "?"
        )
        findings.append(
            Finding(
                "MSP_SUBSTITUTED",
                "info",
                ctx.row_ref(frame, index),
                status_column,
                f"{commodity} price is the minimum support price, not an observed "
                "market price",
                "provisional",
            )
        )
    return findings
