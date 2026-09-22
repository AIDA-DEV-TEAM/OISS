"""Machine-readable caveats attached to a result set by rule.

The narrative step and the assistant verbalise these rather than inventing their
own hedges, so each caveat carries a stable code, a severity, a sentence and the
number of rows it applies to. A caveat is never advisory decoration: it always
corresponds to something true about the rows that were just returned.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

import duckdb

from app.semantic.compiler import CompiledQuery
from app.semantic.spec import QuerySpec


@dataclass(frozen=True)
class Caveat:
    code: str
    severity: str
    message: str
    affected_rows: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class ScopeStats:
    """What the filtered rows actually contain, read once."""

    row_count: int = 0
    official_rows: int = 0
    synthetic_rows: int = 0
    projected_rows: int = 0
    imputed_rows: int = 0
    msp_rows: int = 0
    aggregated_rows: int = 0
    published_block_rows: int = 0
    dataset_version_ids: tuple[str, ...] = ()
    years: tuple[str, ...] = ()


def collect_scope(
    con: duckdb.DuckDBPyConnection, compiled: CompiledQuery
) -> ScopeStats:
    """Summarise the base rows behind a result, in one pass."""
    selects = [
        "count(*) AS row_count",
        "count(*) FILTER (WHERE data_origin = 'official') AS official_rows",
        "count(*) FILTER (WHERE data_origin = 'synthetic') AS synthetic_rows",
        "list(DISTINCT dataset_version_id) AS dataset_version_ids",
        "list(DISTINCT agri_year) AS years",
    ]
    if compiled.has_basis:
        selects += [
            "count(*) FILTER (WHERE annual_level_basis = 'projected') AS projected_rows",
            "count(*) FILTER (WHERE annual_level_basis = 'imputed') AS imputed_rows",
            "count(*) FILTER (WHERE value_status = 'provisional') AS msp_rows",
        ]
    if compiled.has_grain_source:
        selects += [
            "count(*) FILTER (WHERE grain_source = 'aggregated_from_blocks') "
            "AS aggregated_rows",
            "count(*) FILTER (WHERE grain_source = 'published_block') "
            "AS published_block_rows",
        ]
    sql = f"WITH base AS ({compiled.base_sql}) SELECT {', '.join(selects)} FROM base"
    row = con.execute(sql, list(compiled.base_params)).df().to_dict("records")[0]
    return ScopeStats(
        row_count=int(row["row_count"]),
        official_rows=int(row["official_rows"]),
        synthetic_rows=int(row["synthetic_rows"]),
        projected_rows=int(row.get("projected_rows") or 0),
        imputed_rows=int(row.get("imputed_rows") or 0),
        msp_rows=int(row.get("msp_rows") or 0),
        aggregated_rows=int(row.get("aggregated_rows") or 0),
        published_block_rows=int(row.get("published_block_rows") or 0),
        dataset_version_ids=_as_tuple(row["dataset_version_ids"]),
        years=_as_tuple(row["years"]),
    )


def _as_tuple(values: object) -> tuple[str, ...]:
    """DuckDB list() arrives as a numpy array, which has no usable truthiness."""
    if values is None:
        return ()
    return tuple(sorted(str(value) for value in values))


def _year_range(first: str, last: str) -> list[str]:
    start, end = int(first.split("-")[0]), int(last.split("-")[0])
    return [f"{year}-{str(year + 1)[-2:]}" for year in range(start, end + 1)]


def _period_gap(spec: QuerySpec, stats: ScopeStats) -> Optional[Caveat]:
    """Years the caller asked for that hold no data at all."""
    if spec.period is None or not (spec.period.from_year and spec.period.to_year):
        return None
    requested = _year_range(spec.period.from_year, spec.period.to_year)
    missing = [year for year in requested if year not in stats.years]
    if not missing:
        return None
    shown = ", ".join(missing[:6]) + (" and others" if len(missing) > 6 else "")
    return Caveat(
        "PERIOD_GAP",
        "warning",
        f"No data for {shown} in the selected scope; the figures cover "
        f"{len(stats.years)} of the {len(requested)} requested years.",
        len(missing),
    )


def _structurally_absent(
    spec: QuerySpec, presence: frozenset[str], relation_name: str
) -> Optional[Caveat]:
    """Combinations the caller named that do not exist in any source."""
    pinned: dict[str, list[str]] = {
        f.dimension: list(f.values) for f in spec.filters if f.op in ("eq", "in")
    }
    crops = pinned.get("crop")
    if not crops:
        return None

    absent = 0
    if relation_name == "analytics.v_price":
        districts = pinned.get("district")
        price_types = pinned.get("price_type") or ["farm_harvest", "wholesale"]
        if not districts:
            return None
        for district in districts:
            for crop in crops:
                for price_type in price_types:
                    if f"price|{district}|{crop}|{price_type}" not in presence:
                        absent += 1
    else:
        districts = pinned.get("district")
        seasons = pinned.get("season") or ["Autumn", "Winter", "Summer"]
        if not districts:
            return None
        for district in districts:
            for crop in crops:
                for season in seasons:
                    if f"ayp|{district}|{crop}|{season}" not in presence:
                        absent += 1
    if not absent:
        return None
    return Caveat(
        "STRUCTURALLY_ABSENT",
        "info",
        f"{absent} of the requested combinations are not grown or not priced "
        "anywhere in the sources, so they return no rows rather than zero.",
        absent,
    )


def _cross_source(
    con: duckdb.DuckDBPyConnection, stats: ScopeStats
) -> Optional[Caveat]:
    """Recorded disagreements between DE&S sources covering this scope."""
    if not stats.dataset_version_ids:
        return None
    placeholders = ", ".join("?" for _ in stats.dataset_version_ids)
    count = con.execute(
        f"""
        SELECT count(*) FROM analytics.validation_finding
        WHERE rule_code = 'CROSS_SOURCE_MISMATCH'
          AND dataset_version_id IN ({placeholders})
        """,
        list(stats.dataset_version_ids),
    ).fetchone()[0]
    if not count:
        return None
    return Caveat(
        "CROSS_SOURCE_MISMATCH",
        "info",
        f"{count} recorded disagreement(s) between DE&S sources cover the data "
        "behind this result.",
        int(count),
    )


def build_caveats(
    con: duckdb.DuckDBPyConnection,
    spec: QuerySpec,
    compiled: CompiledQuery,
    stats: ScopeStats,
    presence: frozenset[str],
) -> list[Caveat]:
    """Every caveat that is true of this result, most severe first."""
    caveats: list[Caveat] = []

    if stats.synthetic_rows:
        caveats.append(
            Caveat(
                "SYNTHETIC_DATA",
                "warning",
                f"{stats.synthetic_rows} of {stats.row_count} underlying rows are "
                "synthetic, generated for the demonstration and not published by "
                "DE&S.",
                stats.synthetic_rows,
            )
        )
    if stats.projected_rows:
        caveats.append(
            Caveat(
                "PROJECTED_LEVELS",
                "warning",
                f"{stats.projected_rows} synthetic rows sit on projected annual "
                "levels, for years after the last published price statistics.",
                stats.projected_rows,
            )
        )
    if stats.imputed_rows:
        caveats.append(
            Caveat(
                "IMPUTED_LEVELS",
                "warning",
                f"{stats.imputed_rows} synthetic rows sit on imputed annual "
                "levels, where the published series had no value.",
                stats.imputed_rows,
            )
        )
    if stats.msp_rows:
        caveats.append(
            Caveat(
                "MSP_SUBSTITUTED",
                "info",
                f"{stats.msp_rows} paddy price rows are the Minimum Support "
                "Price, which the report prints in place of an observed market "
                "price.",
                stats.msp_rows,
            )
        )
    if stats.aggregated_rows:
        caveats.append(
            Caveat(
                "AGGREGATED_FROM_BLOCKS",
                "info",
                f"{stats.aggregated_rows} rows were aggregated from block-level "
                "records because DE&S published no district figure; yields are "
                "recomputed as total production over total area.",
                stats.aggregated_rows,
            )
        )

    gap = _period_gap(spec, stats)
    if gap is not None:
        caveats.append(gap)

    absent = _structurally_absent(spec, presence, compiled.relation.name)
    if absent is not None:
        caveats.append(absent)

    mismatch = _cross_source(con, stats)
    if mismatch is not None:
        caveats.append(mismatch)

    order = {"warning": 0, "info": 1}
    return sorted(caveats, key=lambda c: (order.get(c.severity, 2), c.code))
