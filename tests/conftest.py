"""Shared fixtures. The database is built once per session, from scratch."""
from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from app.ingest.loaders import build


@pytest.fixture(scope="session")
def built(tmp_path_factory) -> tuple[Path, dict]:
    """A freshly built database plus its load summary."""
    path = tmp_path_factory.mktemp("oiss") / "oiss.duckdb"
    summary = build(path)
    return path, summary


@pytest.fixture(scope="session")
def summary(built) -> dict:
    return built[1]


@pytest.fixture(scope="session")
def db_path(built) -> Path:
    return built[0]


@pytest.fixture
def con(db_path) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        yield connection
    finally:
        connection.close()
