"""The dashboard narrative (RFP area 4): prose over a SQL fact bundle.

A FixtureProvider stands in for the model. Every test checks the same rule:
no number reaches the reader unless the facts contain it.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import duckdb
import pytest
from fastapi.testclient import TestClient

from app.api import main as api_main
from app.llm.provider import CachedProvider, FixtureProvider, UnreachableProvider
from app.narrative.service import narrate
from app.semantic.spec import QuerySpec

# District paddy production for 2023-24: 174,828,800 qtl, the reconciled figure.
SPEC = QuerySpec.model_validate({
    "metric": "production",
    "filters": [
        {"dimension": "crop", "op": "in", "values": ["CR17"]},
        {"dimension": "agri_year", "op": "eq", "values": ["2023-24"]},
    ],
})


@pytest.fixture(scope="module")
def narrative_db(db_path: Path, tmp_path_factory) -> Path:
    target = tmp_path_factory.mktemp("narrative") / "oiss.duckdb"
    shutil.copyfile(db_path, target)
    return target


@pytest.fixture
def db(narrative_db: Path) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(str(narrative_db))
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture(autouse=True)
def _reset_overrides():
    yield
    api_main.app.dependency_overrides.clear()
    api_main.close_connections()


def _facts(db) -> dict[str, Any]:
    """The facts for SPEC, read through a narrative that never calls a model."""
    return narrate(db, SPEC, FixtureProvider([]))


def test_the_facts_are_the_sql_figures(db) -> None:
    result = _facts(db)
    whole = next(f for f in result["facts_used"] if f["scope"] == "whole selection")
    # 174.83 lakh MT, the figure the reconciliation checks against DE&S.
    assert whole["value"] == 174_828_800.0
    assert whole["unit"] == "qtl"


def test_a_paragraph_quoting_the_facts_verbatim_is_used(db) -> None:
    leader = next(f for f in _facts(db)["facts_used"] if f["label"].startswith("Highest"))
    district = leader["label"].split(": ", 1)[1]
    prose = (
        f"Paddy production in 2023-24 was 174,828,800 qtl, led by {district} at "
        f"{leader['value']:,.0f} qtl."
    )

    result = narrate(db, SPEC, FixtureProvider([prose]))

    assert result["narrative"] == prose
    assert result["narrative_source"] == "model"
    assert result["model"] == "fixture"


def test_an_injected_wrong_number_fails_validation_and_falls_back(db) -> None:
    wrong = "Paddy production in 2023-24 was 181,000,000 qtl."
    provider = FixtureProvider([wrong, wrong])

    result = narrate(db, SPEC, provider)

    assert result["narrative_source"] == "template"
    assert "181,000,000" not in result["narrative"]
    assert "174,828,800" in result["narrative"]
    assert "181,000,000" in provider.calls[1][1][-1].text, "retried once, naming the number"


def test_a_cache_hit_returns_the_identical_narrative(db, tmp_path: Path) -> None:
    prose = "Paddy production in 2023-24 was 174,828,800 qtl."
    inner = FixtureProvider([prose])
    provider = CachedProvider(inner, tmp_path)

    first = narrate(db, SPEC, provider)
    second = narrate(db, SPEC, provider)

    assert first["served_from_cache"] is False
    assert second["served_from_cache"] is True
    assert second["narrative"].encode() == first["narrative"].encode()
    assert len(inner.calls) == 1


def test_with_the_provider_unreachable_the_panel_still_states_the_figures(
    narrative_db: Path, tmp_path: Path
) -> None:
    api_main.app.dependency_overrides[api_main.database_path] = lambda: narrative_db
    api_main.app.dependency_overrides[api_main.get_llm_provider] = lambda: CachedProvider(
        UnreachableProvider(), tmp_path
    )
    response = TestClient(api_main.app).post(
        "/narrative/dashboard", json={"query_spec": SPEC.model_dump(by_alias=True)}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["narrative_source"] == "template"
    assert body["model"] is None
    assert "174,828,800 qtl" in body["narrative"]
    assert body["llm_calls"][0]["outcome"] == "unavailable"


def test_the_model_is_shown_no_table_names_or_sql(db) -> None:
    provider = FixtureProvider(["Paddy production in 2023-24 was 174,828,800 qtl."])
    narrate(db, SPEC, provider)
    shown = provider.calls[0][0] + provider.calls[0][1][0].text

    tables = [
        name for (name,) in db.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema IN ('raw', 'quarantine', 'staging', 'analytics')"
        ).fetchall()
    ]
    assert [name for name in tables if re.search(rf"\b{re.escape(name)}\b", shown)] == []
    assert "analytics." not in shown
    assert not re.search(r"\b(SELECT|FROM|WHERE|JOIN)\b", shown)
