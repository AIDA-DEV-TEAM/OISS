"""Same inputs must produce the same database."""
from __future__ import annotations

import hashlib

import duckdb
import pytest

from app.ingest.loaders import build

# These three carry load timestamps by design; the brief allows time only there.
TIMESTAMPED = {"load_run", "dataset_version", "reconciliation_check"}


def fingerprint(path) -> dict[str, str]:
    """Content hash per table, ignoring row order and column order."""
    con = duckdb.connect(str(path), read_only=True)
    try:
        tables = con.execute(
            """
            SELECT table_schema, table_name FROM information_schema.tables
            WHERE table_type = 'BASE TABLE' ORDER BY 1, 2
            """
        ).fetchall()
        out: dict[str, str] = {}
        for schema, table in tables:
            key = f"{schema}.{table}"
            if table in TIMESTAMPED:
                count = con.execute(f"SELECT count(*) FROM {key}").fetchone()[0]
                out[key] = f"rows={count}"
                continue
            frame = con.execute(f"SELECT * FROM {key}").df()
            columns = sorted(frame.columns)
            frame = frame[columns].sort_values(columns, kind="stable").astype(str)
            out[key] = hashlib.sha256(frame.to_csv(index=False).encode()).hexdigest()
        return out
    finally:
        con.close()


@pytest.fixture(scope="module")
def rebuilt(tmp_path_factory) -> tuple[dict, dict, dict, dict]:
    directory = tmp_path_factory.mktemp("determinism")
    first_summary = build(directory / "first.duckdb")
    second_summary = build(directory / "second.duckdb")
    return (
        fingerprint(directory / "first.duckdb"),
        fingerprint(directory / "second.duckdb"),
        first_summary,
        second_summary,
    )


def test_every_table_is_byte_identical_across_rebuilds(rebuilt) -> None:
    first, second, _, _ = rebuilt
    differing = {key for key in first if first[key] != second.get(key)}
    assert differing == set(), f"non-deterministic tables: {sorted(differing)}"


def test_run_id_is_derived_from_the_inputs(rebuilt) -> None:
    _, _, first_summary, second_summary = rebuilt
    assert first_summary["run_id"] == second_summary["run_id"]
    assert first_summary["run_id"].startswith("build-")


def test_dataset_version_ids_are_content_addressed(rebuilt) -> None:
    _, _, first_summary, second_summary = rebuilt
    first_ids = sorted(s["dataset_version_id"] for s in first_summary["sources"])
    second_ids = sorted(s["dataset_version_id"] for s in second_summary["sources"])
    assert first_ids == second_ids
    for source in first_summary["sources"]:
        assert source["dataset_version_id"].startswith(source["dataset_name"] + "@")


def test_row_counts_are_stable(rebuilt) -> None:
    _, _, first_summary, second_summary = rebuilt
    assert first_summary["row_counts"] == second_summary["row_counts"]
