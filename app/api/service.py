"""Service layer for the API: all logic lives here, routes only call in.

The upload path deliberately reuses :func:`app.ingest.loaders.process_source`,
the same function the batch build uses, so an uploaded file produces exactly the
findings the loader would produce for it. What differs is only what is written:
an upload records its version, findings and quarantined rows for audit, and
never touches ``staging`` or the ``analytics`` facts, so a demo upload cannot
change the figures on the dashboard.
"""
from __future__ import annotations

import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd

from app import db
from app.ingest import loaders
from app.ingest.readers import (
    SOURCES,
    SourceSpec,
    detect_source_type,
    spec_for_upload,
)
from app.validation.rules import Finding

# Row-level detail returned with an upload, allocated *per rule*. A flat cap
# across all rules starved the later ones: uploading the price CSV reported 847
# MISSING_VALUE findings in the summary and returned none of them, because
# MSP_SUBSTITUTED fired first and consumed every slot.
FINDINGS_PER_RULE = 50


def _records(frame: pd.DataFrame) -> list[dict]:
    """Rows as plain dicts with SQL NULLs as None, not as float NaN.

    DuckDB nulls arrive from pandas as NaN, which Pydantic rejects for a
    ``Optional[str]`` field, so they are normalised once here at the boundary.
    """
    if frame.empty:
        return []
    return frame.astype(object).where(frame.notna(), None).to_dict("records")


@lru_cache(maxsize=1)
def block_lookup() -> dict[str, str]:
    """(district_id, normalised block name) -> block_id, built once per process."""
    _, lookup = loaders.build_block_dimension()
    return lookup


def health(con: duckdb.DuckDBPyConnection, database: Path) -> dict[str, object]:
    fact_rows: dict[str, int] = {}
    for table in ("fact_price", "fact_crop_ayp", "fact_land_use", "fact_state_series"):
        fact_rows[table] = con.execute(
            f"SELECT count(*) FROM analytics.{table}"
        ).fetchone()[0]
    last = con.execute(
        "SELECT run_id, status FROM analytics.load_run ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return {
        "status": "ok",
        "database": str(database),
        "database_present": database.exists(),
        "fact_rows": fact_rows,
        "last_run_id": last[0] if last else None,
        "last_run_status": last[1] if last else None,
        "schema_version": db.schema_version(con),
    }


def list_datasets(
    con: duckdb.DuckDBPyConnection, page: int, size: int, layer: Optional[str] = None
) -> tuple[list[dict], int]:
    where, params = "", []
    if layer:
        where, params = "WHERE layer = ?", [layer]
    total = con.execute(
        f"SELECT count(*) FROM analytics.dataset_version {where}", params
    ).fetchone()[0]
    rows = con.execute(
        f"""
        SELECT * FROM analytics.dataset_version {where}
        ORDER BY layer, dataset_name
        LIMIT ? OFFSET ?
        """,
        [*params, size, (page - 1) * size],
    ).df()
    return _records(rows), total


def get_dataset(con: duckdb.DuckDBPyConnection, dataset_version_id: str) -> Optional[dict]:
    rows = con.execute(
        "SELECT * FROM analytics.dataset_version WHERE dataset_version_id = ?",
        [dataset_version_id],
    ).df()
    return None if rows.empty else _records(rows)[0]


def list_findings(
    con: duckdb.DuckDBPyConnection,
    dataset_version_id: str,
    page: int,
    size: int,
    severity: Optional[str] = None,
    rule_code: Optional[str] = None,
) -> tuple[list[dict], int]:
    clauses, params = ["dataset_version_id = ?"], [dataset_version_id]
    if severity:
        clauses.append("severity = ?")
        params.append(severity)
    if rule_code:
        clauses.append("rule_code = ?")
        params.append(rule_code)
    where = " AND ".join(clauses)
    total = con.execute(
        f"SELECT count(*) FROM analytics.validation_finding WHERE {where}", params
    ).fetchone()[0]
    rows = con.execute(
        f"""
        SELECT * FROM analytics.validation_finding WHERE {where}
        ORDER BY severity, rule_code, row_ref
        LIMIT ? OFFSET ?
        """,
        [*params, size, (page - 1) * size],
    ).df()
    return _records(rows), total


def get_lineage(
    con: duckdb.DuckDBPyConnection, dataset_version_id: str
) -> Optional[dict]:
    version = get_dataset(con, dataset_version_id)
    if version is None:
        return None
    edges = con.execute(
        """
        SELECT from_node, to_node, edge_type, dataset_version_id
        FROM analytics.lineage_edge WHERE dataset_version_id = ?
        ORDER BY edge_type, from_node, to_node
        """,
        [dataset_version_id],
    ).df()
    return {
        "dataset_version_id": dataset_version_id,
        "dataset_name": version["dataset_name"],
        "source_file": version["source_file"],
        "edges": _records(edges),
    }


def _finding_records(findings: list[Finding], run_id: str, version_id: str) -> list[dict]:
    return [
        {
            "run_id": run_id,
            "dataset_version_id": version_id,
            "rule_code": finding.rule_code,
            "severity": finding.severity,
            "row_ref": finding.row_ref,
            "column_name": finding.column_name,
            "message": finding.message,
            "observed_value": finding.observed_value,
        }
        for finding in findings
    ]


def set_active_version(
    con: duckdb.DuckDBPyConnection, dataset_version_id: str, active: bool
) -> Optional[dict[str, object]]:
    """Make one version the one queries count, or hand back to the build's.

    Exactly one version per dataset feeds the facts. Activating a version
    deactivates its siblings; deactivating an upload returns the dataset to the
    version the batch build registered, which is what "undo" means here.
    """
    version = get_dataset(con, dataset_version_id)
    if version is None:
        return None
    name = version["dataset_name"]

    previously = [
        row[0]
        for row in con.execute(
            "SELECT dataset_version_id FROM analytics.dataset_version "
            "WHERE dataset_name = ? AND is_active AND dataset_version_id <> ?",
            [name, dataset_version_id],
        ).fetchall()
    ]

    if active:
        con.execute(
            "UPDATE analytics.dataset_version SET is_active = FALSE WHERE dataset_name = ?",
            [name],
        )
        con.execute(
            "UPDATE analytics.dataset_version SET is_active = TRUE WHERE dataset_version_id = ?",
            [dataset_version_id],
        )
        return {"dataset_name": name, "activated": dataset_version_id, "deactivated": previously}

    con.execute(
        "UPDATE analytics.dataset_version SET is_active = FALSE WHERE dataset_version_id = ?",
        [dataset_version_id],
    )
    # Fall back to the batch build's version so the dataset is never dark.
    fallback = con.execute(
        "SELECT dataset_version_id FROM analytics.dataset_version "
        "WHERE dataset_name = ? AND layer <> 'upload' ORDER BY loaded_at LIMIT 1",
        [name],
    ).fetchone()
    if fallback:
        con.execute(
            "UPDATE analytics.dataset_version SET is_active = TRUE WHERE dataset_version_id = ?",
            [fallback[0]],
        )
    return {
        "dataset_name": name,
        "activated": fallback[0] if fallback else None,
        "deactivated": [dataset_version_id],
    }


def ingest_schemas() -> list[dict[str, object]]:
    """Every declared upload target, with the columns it expects."""
    return [
        {
            "dataset_name": spec.name,
            "source_type": spec.source_type,
            "expected_columns": list(spec.expected_columns),
        }
        for spec in sorted(SOURCES, key=lambda s: s.name)
    ]


# Sent as `dataset_name` when the file matches no declared schema.
UNREGISTERED = "__unregistered__"

_DEFAULT_SUFFIX = {"stata": ".dta", "excel": ".xlsx", "csv": ".csv"}


def _unregistered_name(filename: str) -> str:
    """A stable dataset name for a file with no declared schema."""
    stem = Path(filename).stem.lower()
    slug = "".join(char if char.isalnum() else "_" for char in stem).strip("_")
    return f"upload_{slug or 'file'}"[:60]


class BuildVersionImmutable(RuntimeError):
    """Raised when the promotion path is asked to touch a build version.

    The batch build's fact rows are the reference the reconciliation checks
    assert against. Nothing an uploader does may rewrite them.
    """


def _assert_upload_version(con: duckdb.DuckDBPyConnection, version_id: str) -> None:
    """Refuse to let the promotion path delete or re-append a build version."""
    row = con.execute(
        "SELECT layer FROM analytics.dataset_version WHERE dataset_version_id = ?",
        [version_id],
    ).fetchone()
    if row is not None and row[0] != "upload":
        raise BuildVersionImmutable(
            f"{version_id} was created by the batch build (layer {row[0]!r}); "
            "the promotion path may only write versions it created"
        )


def _detail_sample(records: list[dict], per_rule: int) -> list[dict]:
    """The first ``per_rule`` findings of each rule, in the loader's own order.

    Every rule the summary names therefore has rows behind it, which is what the
    ingest screen expands into.
    """
    seen: dict[str, int] = {}
    sample: list[dict] = []
    for record in records:
        code = str(record["rule_code"])
        taken = seen.get(code, 0)
        if taken < per_rule:
            sample.append(record)
            seen[code] = taken + 1
    return sample



def _duplicate_result(
    con: duckdb.DuckDBPyConnection,
    result: "loaders.StageResult",
    spec: "SourceSpec",
    run_id: str,
    version_id: str,
    filename: str,
    started_at: datetime,
    existing_layer: str,
) -> dict[str, object]:
    """Record a re-upload of content already loaded, and change nothing else.

    No staging table, no fact rows, no findings rewritten: the version that
    already exists describes these exact bytes, and it stays as its loader
    wrote it.
    """
    con.execute("DELETE FROM analytics.load_run WHERE run_id = ?", [run_id])
    con.execute(
        "DELETE FROM analytics.lineage_edge "
        "WHERE dataset_version_id = ? AND edge_type = 'duplicate_of' AND from_node = ?",
        [version_id, f"upload:{filename}"],
    )
    loaders.append_rows(
        con,
        "analytics.lineage_edge",
        pd.DataFrame(
            [
                {
                    "from_node": f"upload:{filename}",
                    "to_node": version_id,
                    "edge_type": "duplicate_of",
                    "dataset_version_id": version_id,
                }
            ]
        ),
    )
    loaders.append_rows(
        con,
        "analytics.load_run",
        pd.DataFrame(
            [
                {
                    "run_id": run_id,
                    "started_at": started_at,
                    "finished_at": datetime.now(timezone.utc),
                    "status": "duplicate",
                    "summary_json": None,
                }
            ]
        ),
    )
    # The findings already stored against that version, so a duplicate shows the
    # same screen as the original rather than a summary with nothing behind it.
    stored = validation_summary(con, version_id) or []
    stored_detail = _records(
        con.execute(
            """
            SELECT * FROM analytics.validation_finding
            WHERE dataset_version_id = ?
            ORDER BY rule_code, row_ref
            """,
            [version_id],
        ).df()
    )
    detail = _detail_sample(stored_detail, FINDINGS_PER_RULE)
    severity_counts = {level: 0 for level in ("error", "warning", "info")}
    for row in stored:
        severity_counts[str(row["severity"])] += int(row["finding_count"])
    return {
        "run_id": run_id,
        "dataset_name": spec.name,
        "dataset_version_id": version_id,
        "filename": filename,
        "data_origin": spec.data_origin,
        "rows_read": int(len(result.raw)),
        "rows_staged": 0,
        "rows_promoted": 0,
        "staging_table": None,
        "promoted_to": None,
        "rows_quarantined": 0,
        "error_count": severity_counts["error"],
        "warning_count": severity_counts["warning"],
        "info_count": severity_counts["info"],
        "findings_by_rule": [
            {"rule_code": row["rule_code"], "severity": row["severity"], "count": row["finding_count"]}
            for row in stored
        ],
        "findings": detail,
        "quarantine_table": None,
        "duplicate_of": version_id,
        "duplicate_layer": existing_layer,
    }

def ingest_upload(
    con: duckdb.DuckDBPyConnection,
    dataset_name: str,
    filename: str,
    content: bytes,
    data_origin: Optional[str] = None,
    findings_per_rule: int = FINDINGS_PER_RULE,
) -> dict[str, object]:
    """Validate an uploaded file through the batch loader's own code path.

    Bad rows are quarantined and reported; the request still succeeds.
    """
    # The reader comes from the uploaded bytes, never from the target dataset.
    # Choosing it from the target meant a CSV uploaded against a Stata-backed
    # dataset was handed to the Stata parser, which died on the first byte
    # before any validation rule could report the mismatch.
    uploaded_type = detect_source_type(filename, content)
    unregistered = not dataset_name or dataset_name == UNREGISTERED

    if unregistered:
        # No declared schema to check against, so the file is validated for the
        # problems that hold for any table. Its own name keeps the version id
        # readable in the lineage graph.
        spec = SourceSpec(
            name=_unregistered_name(filename),
            path=Path(filename),
            source_type=uploaded_type,
            data_origin=data_origin or "",
            target_table="",
            expected_columns=(),
            encoding="utf-8-sig" if uploaded_type == "csv" else "utf-8",
        )
    else:
        spec = spec_for_upload(dataset_name)

    reader_spec = spec
    if uploaded_type != spec.source_type:
        # utf-8-sig because a mismatched upload has no declared encoding of its
        # own, and it reads plain UTF-8 identically while tolerating a BOM.
        reader_spec = replace(
            spec,
            source_type=uploaded_type,
            encoding="utf-8-sig" if uploaded_type == "csv" else spec.encoding,
        )

    suffix = Path(filename).suffix or _DEFAULT_SUFFIX[uploaded_type]
    with tempfile.TemporaryDirectory() as directory:
        temp_path = Path(directory) / f"upload{suffix}"
        temp_path.write_bytes(content)
        if unregistered:
            result = loaders.process_unregistered_source(reader_spec, temp_path)
        else:
            result = loaders.process_source(reader_spec, temp_path, blocks=block_lookup())

    run_id = loaders.run_id_for([result.sha256], prefix="upload")
    version_id = result.dataset_version_id
    started_at = datetime.now(timezone.utc)

    # Re-uploading the same bytes is idempotent: the version id is content
    # addressed, so replace this run's audit rows rather than duplicating them.
    con.execute(
        "DELETE FROM analytics.validation_finding WHERE run_id = ? AND dataset_version_id = ?",
        [run_id, version_id],
    )
    con.execute("DELETE FROM analytics.load_run WHERE run_id = ?", [run_id])

    # Content-addressed ids mean identical bytes are the same version. If that
    # version already exists, the content is already loaded: re-promoting it
    # would delete and rewrite rows that are already correct, and for a build
    # version that is rows nothing is allowed to touch. Record the attempt and
    # stop.
    existing = con.execute(
        "SELECT layer FROM analytics.dataset_version WHERE dataset_version_id = ?",
        [version_id],
    ).fetchone()
    if existing is not None:
        return _duplicate_result(
            con, result, spec, run_id, version_id, filename, started_at, str(existing[0])
        )

    # Tables and edges for this upload. An edge is only written after the table
    # it points at exists, so the lineage graph never names something absent.
    safe = version_id.replace("@", "_")
    quarantine_table: Optional[str] = None
    staging_table: Optional[str] = None
    edges: list[dict[str, str]] = []

    if not result.quarantined.empty:
        quarantine_table = f"quarantine.upload_{safe}"
        loaders.write_table(con, quarantine_table, result.quarantined.astype("string"))
        edges.append(
            {
                "from_node": f"upload:{filename}",
                "to_node": quarantine_table,
                "edge_type": "validate",
            }
        )

    # Rows that failed an error rule stay in quarantine; the rest are promoted.
    # Promotion is per row, not all-or-nothing: a file with two bad rows out of
    # 6,300 contributes the other 6,298.
    promoted = 0
    staged_rows = 0
    if not unregistered and not result.staged.empty:
        staged = result.staged.copy()
        staged["dataset_version_id"] = version_id
        staged["data_origin"] = spec.data_origin
        staging_table = f"staging.upload_{safe}"
        loaders.write_table(con, staging_table, staged)
        staged_rows = int(len(staged))
        edges.append(
            {
                "from_node": f"upload:{filename}",
                "to_node": staging_table,
                "edge_type": "transform",
            }
        )

        target = spec.target_table
        frame = loaders.fact_frame(target, staged, spec.name)
        if frame is not None and not frame.empty:
            _assert_upload_version(con, version_id)
            con.execute(
                f"DELETE FROM analytics.{target} WHERE dataset_version_id = ?", [version_id]
            )
            loaders.append_rows(con, f"analytics.{target}", frame)
            promoted = int(len(frame))
            edges.append(
                {
                    "from_node": staging_table,
                    "to_node": f"analytics.{target}",
                    "edge_type": "load",
                }
            )
    elif unregistered and not result.raw.empty:
        # No declared schema means no fact table to promote into, so an
        # unregistered upload stops at staging. Quarantined rows are held back
        # here exactly as they are for a registered one: staging is what passed.
        kept = result.raw.drop(index=result.quarantined.index, errors="ignore")
        staging_table = f"staging.upload_{safe}"
        loaders.write_table(con, staging_table, kept.astype("string"))
        staged_rows = int(len(kept))
        edges.append(
            {
                "from_node": f"upload:{filename}",
                "to_node": staging_table,
                "edge_type": "transform",
            }
        )

    loaders.append_rows(
        con,
        "analytics.dataset_version",
        pd.DataFrame(
            [
                {
                    "dataset_version_id": version_id,
                    "dataset_name": spec.name,
                    "source_file": f"upload:{filename}",
                    "source_type": spec.source_type,
                    "sha256": result.sha256,
                    "row_count": int(len(result.raw)),
                    "layer": "upload",
                    "loaded_at": started_at,
                    "generator_version": spec.generator_version,
                    # Promoted, but not counted until someone activates it.
                    "is_active": False,
                }
            ]
        ),
    )
    if edges:
        loaders.append_rows(
            con,
            "analytics.lineage_edge",
            pd.DataFrame([{**edge, "dataset_version_id": version_id} for edge in edges]),
        )

    records = _finding_records(result.findings, run_id, version_id)
    loaders.append_rows(con, "analytics.validation_finding", pd.DataFrame(records))

    counts: dict[tuple[str, str], int] = {}
    for finding in result.findings:
        key = (finding.rule_code, finding.severity)
        counts[key] = counts.get(key, 0) + 1

    # Three outcomes, because "failed" for two bad rows in 6,300 is a lie.
    if not result.raw.empty and result.findings == []:
        status = "completed"
    elif promoted > 0 or (unregistered and staging_table):
        status = "completed_with_findings" if result.findings else "completed"
    else:
        status = "failed"
    loaders.append_rows(
        con,
        "analytics.load_run",
        pd.DataFrame(
            [
                {
                    "run_id": run_id,
                    "started_at": started_at,
                    "finished_at": datetime.now(timezone.utc),
                    "status": status,
                    "summary_json": None,
                }
            ]
        ),
    )

    by_severity = {level: 0 for level in ("error", "warning", "info")}
    for finding in result.findings:
        by_severity[finding.severity] += 1

    return {
        "run_id": run_id,
        "dataset_name": spec.name,
        "dataset_version_id": version_id,
        "filename": filename,
        "data_origin": spec.data_origin,
        "rows_read": int(len(result.raw)),
        # What was actually written to the staging table, not what was
        # computed: this used to report a count for uploads that never reached
        # a staging table, and zero for unregistered ones that did.
        "rows_staged": staged_rows,
        "rows_promoted": promoted,
        "staging_table": staging_table,
        "promoted_to": f"analytics.{spec.target_table}" if promoted else None,
        "rows_quarantined": int(len(result.quarantined)),
        "error_count": by_severity["error"],
        "warning_count": by_severity["warning"],
        "info_count": by_severity["info"],
        "findings_by_rule": [
            {"rule_code": code, "severity": severity, "count": count}
            for (code, severity), count in sorted(counts.items())
        ],
        "findings": _detail_sample(records, findings_per_rule),
        "quarantine_table": quarantine_table,
    }


# --------------------------------------------------------------------------
# Layer journey and validation summary
# --------------------------------------------------------------------------
# What each layer is for, in the words the storage screen uses.
LAYER_PURPOSE = {
    "raw": "As published. Every column text, nothing repaired.",
    "quarantine": "Rows an error-severity rule rejected, with the rule that rejected them.",
    "staging": "Typed, with canonical district, crop, block and period ids attached.",
    "analytics": "Fact rows the dashboard and assistant read.",
}


def _table_exists(con: duckdb.DuckDBPyConnection, schema: str, table: str) -> bool:
    return bool(
        con.execute(
            """
            SELECT count(*) FROM information_schema.tables
            WHERE table_schema = ? AND table_name = ?
            """,
            [schema, table],
        ).fetchone()[0]
    )


def _count(con: duckdb.DuckDBPyConnection, schema: str, table: str) -> Optional[int]:
    if not _table_exists(con, schema, table):
        return None
    return int(con.execute(f'SELECT count(*) FROM "{schema}"."{table}"').fetchone()[0])


def layer_journey(
    con: duckdb.DuckDBPyConnection, dataset_version_id: str
) -> Optional[list[dict[str, object]]]:
    """Row counts per layer for one dataset version, and what changed between them.

    The transition text is derived from the counts rather than written per
    dataset, so it cannot drift from what the loader actually did.
    """
    from app.ingest.readers import SOURCES_BY_NAME

    version = get_dataset(con, dataset_version_id)
    if version is None:
        return None
    name = version["dataset_name"]
    spec = SOURCES_BY_NAME.get(name)

    # An upload writes its own tables, keyed by version id. Reading the bundled
    # dataset's tables instead reported the build's counts for an upload, and
    # showed 0 quarantined for an upload that had quarantined rows.
    upload = version["layer"] == "upload"
    suffix = f"upload_{dataset_version_id.replace('@', '_')}"
    raw_key = suffix if upload else name

    rows: list[dict[str, object]] = []
    raw_count = int(version["row_count"]) if upload else _count(con, "raw", name)
    if raw_count is None:
        raw_count = int(version["row_count"])
    rows.append(
        {
            "layer": "raw",
            "label": "Raw / landing",
            "table": f"raw.{name}",
            "row_count": raw_count,
            "purpose": LAYER_PURPOSE["raw"],
            "transition": f"{raw_count:,} rows read from {Path(version['source_file']).name}.",
        }
    )

    quarantined = (
        _count(con, "quarantine", suffix) if upload else _count(con, "quarantine", name)
    ) or 0
    rows.append(
        {
            "layer": "quarantine",
            "label": "Validation / quarantine",
            "table": f"quarantine.{raw_key}",
            "row_count": quarantined,
            "purpose": LAYER_PURPOSE["quarantine"],
            "transition": (
                f"{quarantined:,} rows held back by an error rule."
                if quarantined
                else "No row failed an error rule."
            ),
        }
    )

    staged = _count(con, "staging", raw_key) or 0
    if staged and raw_count and staged % raw_count == 0 and staged > raw_count:
        factor = staged // raw_count
        movement = (
            f"{raw_count:,} source rows became {staged:,}: area, yield and "
            f"production are published side by side and split into {factor} rows, "
            "one per measure."
        )
    elif staged < raw_count:
        movement = (
            f"{raw_count - staged:,} rows did not reach staging "
            "(quarantined, or carrying no canonical id)."
        )
    else:
        movement = f"{staged:,} rows typed and given canonical ids."
    rows.append(
        {
            "layer": "staging",
            "label": "Cleansed / staging",
            "table": f"staging.{raw_key}",
            "row_count": staged,
            "purpose": LAYER_PURPOSE["staging"],
            "transition": movement,
        }
    )

    target = spec.target_table if spec is not None else None
    analytics_count = 0
    if target:
        analytics_count = int(
            con.execute(
                f"SELECT count(*) FROM analytics.{target} WHERE dataset_version_id = ?",
                [dataset_version_id],
            ).fetchone()[0]
        )
    rows.append(
        {
            "layer": "analytics",
            "label": "Analytics-ready",
            "table": f"analytics.{target}" if target else None,
            "row_count": analytics_count,
            "purpose": LAYER_PURPOSE["analytics"],
            "transition": (
                f"{analytics_count:,} fact rows carrying data_origin and "
                "dataset_version_id."
                if analytics_count
                else "State-total rows are kept in staging and never loaded as district facts."
                if staged
                else "Nothing loaded."
            ),
        }
    )
    return rows


def validation_summary(
    con: duckdb.DuckDBPyConnection, dataset_version_id: str
) -> Optional[list[dict[str, object]]]:
    """Per-rule finding counts for one dataset version, with a sample reference."""
    if get_dataset(con, dataset_version_id) is None:
        return None
    rows = con.execute(
        """
        SELECT rule_code, severity, count(*) AS finding_count,
               min(row_ref) AS sample_row_ref, min(message) AS sample_message,
               count(DISTINCT column_name) AS column_count
        FROM analytics.validation_finding
        WHERE dataset_version_id = ?
        GROUP BY rule_code, severity
        ORDER BY severity, rule_code
        """,
        [dataset_version_id],
    ).df()
    return _records(rows)
