"""Creating, recording and listing exports.

Two ways in, and the difference is recorded in the file:

* a **query spec**, which this service executes itself. The context written
  into the file is then derived here from that execution -- not taken from
  whatever the caller claimed -- so a file's context always matches its rows.
* an inline **payload**, for surfaces with no single spec to re-run (the
  dashboard narrative, and panels built from more than one query). Those files
  say their context was supplied by the caller.

Generation is synchronous. There is no queue to poll, so an export is either
created and complete or the request failed, and the status never lies about
work that is not happening.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import duckdb

from app.config import EXPORTS
from app.exports import provenance, writers
from app.sandbox import service as sandbox
from app.semantic import service as semantic
from app.semantic.spec import QuerySpec

EXTENSIONS = {"csv": "csv", "xlsx": "xlsx", "pdf": "pdf", "json": "json", "png": "png"}

# The most rows one file may carry. Owned here and served by GET
# /exports/limits, so the dialog that warns about it cannot disagree with the
# service that enforces it.
EXPORT_ROW_CEILING = 100_000


# Columns a tabular export always drops: they repeat what the context block
# already states, once, at the top of the file.
INTERNAL_COLUMNS = {"unit"}

_UNSAFE = re.compile(r"[^a-z0-9]+")


class ExportError(RuntimeError):
    """An export that cannot be produced, with a client-safe reason."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _slug(text: str) -> str:
    return _UNSAFE.sub("_", text.lower()).strip("_")[:60] or "export"


def _export_id(panel_title: str, fmt: str, created_at: datetime) -> str:
    digest = hashlib.sha256(
        f"{panel_title}|{fmt}|{created_at.isoformat()}".encode("utf-8")
    ).hexdigest()[:12]
    return f"exp-{digest}"


def _columns(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """Column order as the rows present it, minus what the context repeats."""
    seen: list[str] = []
    for row in rows:
        for key in row:
            if key not in seen and key not in INTERNAL_COLUMNS:
                seen.append(key)
    return seen


# --------------------------------------------------------------------------
# Building the context that travels with the file
# --------------------------------------------------------------------------
def _context_from_query(
    panel_title: str,
    applied: Mapping[str, Any],
    row_count: int,
    caveats: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """The applied context of the query this service just ran.

    ``row_count`` is the number of rows actually written, which is what a
    reader of the file needs; ``underlying_row_count`` stays as the query
    reported it.
    """
    context = dict(applied)
    context["panel_title"] = panel_title
    context["row_count"] = row_count
    context["context_origin"] = "derived"
    context["period_label"] = writers.period_phrase(context)
    context["provenance_notes"] = provenance.notes_from_context(context)
    context["caveats"] = [dict(c) for c in caveats]
    return context


def _context_from_payload(
    panel_title: str,
    supplied: Optional[Mapping[str, Any]],
    row_count: int,
    caveats: Sequence[Mapping[str, Any]],
    con: Optional[duckdb.DuckDBPyConnection] = None,
) -> dict[str, Any]:
    supplied = dict(supplied or {})
    if con is not None and supplied.get("filters"):
        supplied["filters"] = semantic.describe_filters(con, supplied["filters"])
    else:
        supplied.setdefault("filters", [])
    supplied.setdefault("source_datasets", [])
    supplied.setdefault("data_origin", {})
    supplied.setdefault("underlying_row_count", row_count)
    supplied.setdefault("generated_at", datetime.now(timezone.utc).isoformat())
    supplied["panel_title"] = panel_title
    supplied["row_count"] = row_count
    # Said plainly, because a reader cannot otherwise tell this file's context
    # apart from one the service derived by running the query itself.
    supplied["context_origin"] = "supplied by the calling surface"
    supplied["period_label"] = writers.period_phrase(supplied)
    supplied["provenance_notes"] = provenance.notes_from_context(supplied)
    supplied["caveats"] = [dict(c) for c in caveats]
    return supplied


# --------------------------------------------------------------------------
# Creating an export
# --------------------------------------------------------------------------
def create_export(
    con: duckdb.DuckDBPyConnection,
    *,
    export_type: str,
    fmt: str,
    panel_title: str,
    query_spec: Optional[QuerySpec] = None,
    rows: Optional[Sequence[Mapping[str, Any]]] = None,
    context: Optional[Mapping[str, Any]] = None,
    caveats: Optional[Sequence[Mapping[str, Any]]] = None,
    include_context: bool = True,
    include_caveats: bool = True,
    include_records: bool = True,
    directory: Optional[Path] = None,
    row_ceiling: Optional[int] = None,
) -> dict[str, Any]:
    if fmt not in EXTENSIONS:
        raise ExportError("unknown_format", f"unknown export format {fmt!r}")

    ceiling = row_ceiling if row_ceiling is not None else EXPORT_ROW_CEILING

    if query_spec is not None:
        # Re-run the spec without its display limit, subject to hard ceiling
        result = semantic.run_query(con, query_spec, row_limit=ceiling)
        data_rows = list(result["rows"])
        applied = dict(result["applied_context"])
        file_caveats = list(result["caveats"])
        if applied.get("truncated"):
            matching = int(applied.get("matching_row_count") or len(data_rows))
            file_caveats.append(
                {
                    "severity": "warning",
                    "code": "TRUNCATED_EXPORT",
                    "message": f"Truncated at {len(data_rows):,} of {matching:,} rows",
                    "affected_rows": matching - len(data_rows),
                }
            )
        file_context = _context_from_query(panel_title, applied, len(data_rows), file_caveats)
        if query_spec.metric == "predicted_yield":
            # Model output travels with the configuration of the model behind it.
            file_context["model_configurations"] = sandbox.model_configurations(con, query_spec)
    else:
        data_rows = [dict(row) for row in (rows or [])]
        file_caveats = [dict(c) for c in (caveats or [])]
        file_context = _context_from_payload(
            panel_title, context, len(data_rows), file_caveats, con=con
        )

    if not include_records and fmt in {"csv", "xlsx", "json"}:
        # A context-only file: the caveats and the context, no rows. The row
        # count still states what the selection held.
        written_rows: list[Mapping[str, Any]] = []
    else:
        written_rows = data_rows

    columns = _columns(data_rows)
    created_at = datetime.now(timezone.utc)
    export_id = _export_id(panel_title, fmt, created_at)
    filename = f"{_slug(panel_title)}_{export_id}.{EXTENSIONS[fmt]}"
    target_dir = Path(directory) if directory is not None else EXPORTS
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / filename

    _write(fmt, path, written_rows, columns, file_context, file_caveats,
           include_context, include_caveats)

    size = path.stat().st_size
    record = {
        "export_id": export_id,
        "export_type": export_type,
        "format": fmt,
        "status": "completed",
        "filename": filename,
        "size_bytes": size,
        "created_at": created_at.isoformat(),
        "context": file_context,
    }
    _record(con, record, path, file_context)
    return record


def _write(
    fmt: str,
    path: Path,
    rows: Sequence[Mapping[str, Any]],
    columns: Sequence[str],
    context: Mapping[str, Any],
    caveats: Sequence[Mapping[str, Any]],
    include_context: bool,
    include_caveats: bool,
) -> None:
    if fmt == "csv":
        writers.write_csv(path, rows, columns, context, caveats,
                          include_context, include_caveats)
    elif fmt == "json":
        writers.write_json(path, rows, context, caveats, include_context, include_caveats)
    elif fmt == "xlsx":
        writers.write_xlsx(path, rows, columns, context, caveats,
                           include_context, include_caveats)
    elif fmt == "png":
        writers.write_png(path, rows, context, caveats, include_context, include_caveats)
    elif fmt == "pdf":
        # The PDF of a chartable selection shows the chart, rendered by the
        # same code that produces the PNG so the two cannot disagree.
        chart: Optional[Path] = None
        temp: Optional[Path] = None
        if rows and len(context.get("dimensions") or []) == 1:
            # mkstemp hands back an open descriptor, and on Windows an open
            # handle blocks the unlink below; close it before writing.
            handle, name = tempfile.mkstemp(suffix=".png")
            os.close(handle)
            temp = Path(name)
            writers.write_png(temp, rows, context, [], include_context=False,
                              include_caveats=False)
            chart = temp
        try:
            writers.write_pdf(path, rows, columns, context, caveats,
                              include_context, include_caveats, chart=chart)
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# Recording it: a row, and a lineage edge per contributing version
# --------------------------------------------------------------------------
def _record(
    con: duckdb.DuckDBPyConnection,
    record: Mapping[str, Any],
    path: Path,
    context: Mapping[str, Any],
) -> None:
    con.execute(
        """
        INSERT INTO analytics.export
            (export_id, export_type, format, status, filename, file_path,
             size_bytes, created_at, context_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            record["export_id"],
            record["export_type"],
            record["format"],
            record["status"],
            record["filename"],
            str(path),
            int(record["size_bytes"]),
            datetime.fromisoformat(str(record["created_at"])),
            json.dumps(context, default=str),
        ],
    )

    # An export is a leaf of the lineage graph: one edge from each dataset
    # version that contributed a row, so "what came out of this version" is a
    # question the graph can answer.
    node = f"export:{record['filename']}"
    relation = context.get("relation")
    for source in context.get("source_datasets") or []:
        version_id = source.get("dataset_version_id")
        if not version_id:
            continue
        con.execute(
            """
            INSERT INTO analytics.lineage_edge
                (from_node, to_node, edge_type, dataset_version_id)
            VALUES (?, ?, 'export', ?)
            """,
            [str(relation) if relation else str(version_id), node, version_id],
        )


# --------------------------------------------------------------------------
# Reading exports back
# --------------------------------------------------------------------------
_SELECT = """
SELECT export_id, export_type, format, status, filename, file_path,
       size_bytes, created_at, context_json
FROM analytics.export
"""


def _row_to_record(row: Sequence[Any]) -> dict[str, Any]:
    return {
        "export_id": row[0],
        "export_type": row[1],
        "format": row[2],
        "status": row[3],
        "filename": row[4],
        "size_bytes": int(row[6]),
        "created_at": row[7].isoformat() if hasattr(row[7], "isoformat") else str(row[7]),
        "context": json.loads(row[8]),
    }


def limits() -> dict[str, int]:
    """What the export service enforces, for the UI to read rather than copy."""
    return {"row_ceiling": EXPORT_ROW_CEILING}


def list_exports(con: duckdb.DuckDBPyConnection, limit: int = 100) -> list[dict[str, Any]]:
    rows = con.execute(f"{_SELECT} ORDER BY created_at DESC LIMIT ?", [limit]).fetchall()
    return [_row_to_record(row) for row in rows]


def get_export(con: duckdb.DuckDBPyConnection, export_id: str) -> Optional[dict[str, Any]]:
    row = con.execute(f"{_SELECT} WHERE export_id = ?", [export_id]).fetchone()
    return _row_to_record(row) if row else None


def export_file(con: duckdb.DuckDBPyConnection, export_id: str) -> Optional[Path]:
    """Where the generated file lives, or None when it is gone from disk."""
    row = con.execute(
        "SELECT file_path FROM analytics.export WHERE export_id = ?", [export_id]
    ).fetchone()
    if row is None:
        return None
    path = Path(str(row[0]))
    return path if path.exists() else None
