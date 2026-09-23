"""The conversational assistant (RFP area 5).

No test talks to a hosted model. A FixtureProvider stands in for it, scripted
per test, and keeps every prompt it was shown so the tests can check what a
model would have seen.
"""
from __future__ import annotations

import ast
import json
import re
import shutil
from pathlib import Path
from typing import Any

import duckdb
import pytest
from fastapi.testclient import TestClient

from app import config
from app.api import main as api_main
from app.assistant import prompts
from app.assistant.service import ask
from app.assistant.starters import STARTERS
from app.llm import numbers
from app.llm.provider import (
    CachedProvider,
    FixtureProvider,
    Message,
    UnreachableProvider,
)

ROOT = Path(__file__).resolve().parent.parent

PADDY_2023_24 = {
    "action": "query",
    "spec": {
        "metric": "production",
        "dimensions": [],
        "filters": [
            {"dimension": "crop", "op": "eq", "values": ["CR17"]},
            {"dimension": "grain_source", "op": "eq", "values": ["published_state"]},
            {"dimension": "agri_year", "op": "eq", "values": ["2023-24"]},
        ],
    },
}
PADDY_ANSWER = "State paddy production in 2023-24 was 174,830,000 qtl."

BLOCK_PRICES = {
    "action": "query",
    "spec": {
        "metric": "avg_price",
        "dimensions": ["block"],
        "filters": [
            {"dimension": "district", "op": "eq", "values": ["OD04"]},
            {"dimension": "price_type", "op": "eq", "values": ["wholesale"]},
            {"dimension": "data_origin", "op": "eq", "values": ["synthetic"]},
        ],
    },
}


@pytest.fixture(scope="module")
def assistant_db(db_path: Path, tmp_path_factory) -> Path:
    """A private copy: the assistant logs every call to it."""
    target = tmp_path_factory.mktemp("assistant") / "oiss.duckdb"
    shutil.copyfile(db_path, target)
    return target


@pytest.fixture
def db(assistant_db: Path) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(str(assistant_db))
    try:
        yield connection
    finally:
        connection.close()


def _client(assistant_db: Path, provider: Any) -> TestClient:
    api_main.close_connections()
    api_main.app.dependency_overrides[api_main.database_path] = lambda: assistant_db
    api_main.app.dependency_overrides[api_main.get_llm_provider] = lambda: provider
    return TestClient(api_main.app)


@pytest.fixture(autouse=True)
def _reset_overrides():
    yield
    api_main.app.dependency_overrides.clear()
    api_main.close_connections()


# --------------------------------------------------------------------------
# A known question gives a known figure
# --------------------------------------------------------------------------
def test_a_question_mapped_to_a_known_query_returns_the_exact_figure(assistant_db: Path) -> None:
    provider = FixtureProvider([json.dumps(PADDY_2023_24), PADDY_ANSWER])
    client = _client(assistant_db, provider)

    response = client.post(
        "/assistant/ask", json={"question": "What was state paddy production in 2023-24?"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "answered"
    assert body["rows"][0]["value"] == 174_830_000.0
    assert body["answer"] == PADDY_ANSWER
    assert body["answer_source"] == "model"
    assert body["period"] == "2023-24"
    assert body["interpretation"]["metric_label"] == "Production"
    assert body["applied_filters"][0]["values_display"] == ["Paddy (CR17)"]
    assert body["source_datasets"], "an answer names the dataset it read"
    assert body["served_from_cache"] is False


def test_a_starter_question_answers_from_the_shipped_cache(assistant_db: Path) -> None:
    provider = CachedProvider(UnreachableProvider(), config.LLM_CACHE_DIR)
    client = _client(assistant_db, provider)

    body = client.post(
        "/assistant/ask",
        json={"question": "Which districts had the highest paddy yield in 2024-25?"},
    ).json()

    assert body["status"] == "answered", body
    assert body["rows"][0]["district"] == "Dhenkanal"
    assert body["rows"][0]["value"] == 54.9995
    assert body["chart_spec"]["kind"] == "bar"
    assert body["interpretation"]["model"] == "fixture"


# --------------------------------------------------------------------------
# Refusing rather than guessing
# --------------------------------------------------------------------------
def test_a_question_needing_an_unavailable_dimension_is_refused(db) -> None:
    provider = FixtureProvider([json.dumps(BLOCK_PRICES), json.dumps(BLOCK_PRICES)])

    result = ask(db, "What are wholesale prices in each block of Bargarh?", provider)

    assert result["status"] == "declined"
    assert "block" in result["limitation"]
    assert result["rows"] == [] and result["chart_spec"] is None
    # The rejection went back to the model once before giving up.
    assert len(provider.calls) == 2
    correction = provider.calls[1][1][-1].text
    assert "invalid_grain" in correction


def test_a_rejected_spec_is_answered_once_the_model_corrects_it(db) -> None:
    wrong = json.loads(json.dumps(PADDY_2023_24))
    wrong["spec"]["dimensions"] = ["month"]
    provider = FixtureProvider([json.dumps(wrong), json.dumps(PADDY_2023_24), PADDY_ANSWER])

    result = ask(db, "What was state paddy production in 2023-24?", provider)

    assert result["status"] == "answered"
    assert result["interpretation"]["corrected"] is True


def test_the_models_own_refusal_is_passed_on(db) -> None:
    refusal = {"action": "refuse", "limitation": "The data holds no rainfall figures."}
    result = ask(db, "How much did it rain in Puri?", FixtureProvider([json.dumps(refusal)]))

    assert result["status"] == "declined"
    assert result["limitation"] == "The data holds no rainfall figures."


def test_a_figure_in_a_refusal_that_the_catalogue_lacks_is_not_shown(db) -> None:
    refusal = {"action": "refuse", "limitation": "Rainfall was 1,482 mm, which we do not hold."}
    result = ask(db, "How much did it rain?", FixtureProvider([json.dumps(refusal)]))

    assert "1,482" not in result["limitation"]


def test_a_selection_with_no_rows_is_declined_with_the_coverage(db) -> None:
    official_2023 = {
        "action": "query",
        "spec": {
            "metric": "avg_price",
            "dimensions": [],
            "filters": [
                {"dimension": "data_origin", "op": "eq", "values": ["official"]},
                {"dimension": "agri_year", "op": "eq", "values": ["2023-24"]},
            ],
        },
    }
    provider = FixtureProvider([json.dumps(official_2023)])

    result = ask(db, "What were official prices in 2023-24?", provider)

    assert result["status"] == "declined"
    assert "data_origin = official: 2013-14 to 2018-19" in result["limitation"]
    assert len(provider.calls) == 1, "no prose is written for an empty result"


# --------------------------------------------------------------------------
# Post-validation of prose
# --------------------------------------------------------------------------
def test_an_injected_wrong_number_fails_post_validation(db) -> None:
    wrong = "State paddy production in 2023-24 was 181,000,000 qtl."
    provider = FixtureProvider([json.dumps(PADDY_2023_24), wrong, wrong])

    result = ask(db, "What was state paddy production in 2023-24?", provider)

    assert result["answer_source"] == "template"
    assert "181,000,000" not in result["answer"]
    assert "174,830,000" in result["answer"]
    # Retried once, naming the number, before falling back.
    assert "181,000,000" in provider.calls[2][1][-1].text


def test_the_number_check_allows_rounding_but_not_arithmetic() -> None:
    allowed = numbers.collect([[{"district": "Angul", "value": 52.1915}, {"value": 47.1514}]])

    assert numbers.unsupported("Angul at 52.19 qtl/ha", allowed) == []
    assert numbers.unsupported("Angul at 52.2", allowed) == []
    # The difference between two supplied values is a new number.
    assert numbers.unsupported("a gap of 5.04", allowed) == ["5.04"]
    # Codes are not figures; years must be supplied like any other number.
    assert numbers.unsupported("Cuttack (OD07) in 2024-25", allowed) == ["2024-25"]


# --------------------------------------------------------------------------
# Cache and outage
# --------------------------------------------------------------------------
def test_a_cache_hit_returns_identical_bytes_and_says_so(tmp_path: Path) -> None:
    inner = FixtureProvider(["Réponse — 174,830,000 qtl.\n"])
    provider = CachedProvider(inner, tmp_path)
    messages = [Message("user", "What was paddy production?")]

    first = provider.complete("system", messages, "text")
    second = provider.complete("system", messages, "text")

    assert first.served_from_cache is False
    assert second.served_from_cache is True
    assert second.text.encode("utf-8") == first.text.encode("utf-8")
    assert len(inner.calls) == 1, "the second call never reached the model"


def test_a_repeated_question_is_served_from_cache_with_the_same_answer(
    assistant_db: Path, tmp_path: Path
) -> None:
    inner = FixtureProvider([json.dumps(PADDY_2023_24), PADDY_ANSWER])
    client = _client(assistant_db, CachedProvider(inner, tmp_path))
    question = {"question": "What was state paddy production in 2023-24?"}

    first = client.post("/assistant/ask", json=question).json()
    second = client.post("/assistant/ask", json=question).json()

    assert first["served_from_cache"] is False
    assert second["served_from_cache"] is True
    assert second["answer"] == first["answer"]
    assert second["rows"] == first["rows"]


def test_with_the_provider_unreachable_cached_questions_still_answer(assistant_db: Path) -> None:
    client = _client(assistant_db, CachedProvider(UnreachableProvider(), config.LLM_CACHE_DIR))

    for starter in STARTERS:
        body = client.post("/assistant/ask", json={"question": starter.question}).json()
        expected = "declined" if starter.reply["action"] == "refuse" else "answered"
        assert body["status"] == expected, (starter.question_id, body.get("limitation"))
        assert body["served_from_cache"] is True

    fresh = client.post("/assistant/ask", json={"question": "A question never asked?"}).json()
    assert fresh["status"] == "unavailable"
    assert fresh["rows"] == []


def test_every_call_is_logged_for_review(db) -> None:
    before = db.execute("SELECT count(*) FROM analytics.llm_call").fetchone()[0]
    ask(db, "What was state paddy production in 2023-24?",
        FixtureProvider([json.dumps(PADDY_2023_24), PADDY_ANSWER]))

    logged = db.execute(
        "SELECT purpose, outcome, response_text FROM analytics.llm_call "
        "ORDER BY created_at DESC LIMIT 2"
    ).fetchall()
    assert db.execute("SELECT count(*) FROM analytics.llm_call").fetchone()[0] == before + 2
    assert {row[0] for row in logged} == {"interpret", "answer"}
    assert PADDY_ANSWER in {row[2] for row in logged}


def test_the_starter_questions_are_listed(assistant_db: Path) -> None:
    body = _client(assistant_db, FixtureProvider([])).get("/assistant/questions").json()
    assert body["total"] == 6
    assert [item["question_id"] for item in body["items"]] == [s.question_id for s in STARTERS]


# --------------------------------------------------------------------------
# Model output never reaches the database; prompts hold no tables or SQL
# --------------------------------------------------------------------------
def test_model_output_cannot_reach_the_database_except_as_a_validated_spec(db) -> None:
    count = "SELECT count(*) FROM analytics.fact_price"
    before = db.execute(count).fetchone()[0]
    injected = json.loads(json.dumps(PADDY_2023_24))
    injected["spec"]["filters"][0]["values"] = ["CR17'; DROP TABLE analytics.fact_price; --"]
    with_sql = {**PADDY_2023_24, "sql": "SELECT * FROM analytics.fact_price"}
    provider = FixtureProvider([json.dumps(injected), json.dumps(with_sql)])

    result = ask(db, "What was paddy production?", provider)

    assert result["status"] == "declined"
    assert db.execute(count).fetchone()[0] == before


def test_the_assistant_and_llm_modules_execute_no_sql_of_their_own() -> None:
    """The one statement they run is the log insert, a constant with bound
    parameters. Everything else goes through the semantic layer."""
    executed: list[tuple[str, str]] = []
    for path in [*(ROOT / "app" / "assistant").glob("*.py"), *(ROOT / "app" / "llm").glob("*.py")]:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"execute", "sql", "executemany", "query"}
            ):
                argument = node.args[0] if node.args else None
                executed.append(
                    (path.name, argument.id if isinstance(argument, ast.Name) else ast.dump(argument))
                )
    assert sorted(executed) == [("log.py", "LLM_DDL"), ("log.py", "_INSERT")]


def test_no_prompt_contains_a_table_name_or_sql(db) -> None:
    provider = FixtureProvider(
        [json.dumps(BLOCK_PRICES), json.dumps(PADDY_2023_24), PADDY_ANSWER + " 9,999."]
        + [PADDY_ANSWER]
    )
    ask(db, "What was state paddy production in 2023-24?", provider)
    shown = "\n".join(
        system + "\n" + "\n".join(message.text for message in messages)
        for system, messages, _ in provider.calls
    )
    assert len(provider.calls) == 4, "interpret, correction, answer, answer retry"

    tables = [
        name
        for (name,) in db.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema IN ('raw', 'quarantine', 'staging', 'analytics')"
        ).fetchall()
    ]
    assert tables
    leaked = [name for name in tables if re.search(rf"\b{re.escape(name)}\b", shown)]
    assert leaked == []
    for schema in ("raw.", "quarantine.", "staging.", "analytics."):
        assert schema not in shown
    assert not re.search(r"\b(SELECT|INSERT|UPDATE|DELETE|JOIN|WHERE|GROUP BY)\b", shown)
    assert "Catalogue:" in prompts.interpret_message(db, "x")


# --------------------------------------------------------------------------
# The Gemini provider, with the network stubbed
# --------------------------------------------------------------------------
def test_gemini_sends_the_key_in_a_header_and_reads_the_text(monkeypatch) -> None:
    import httpx

    from app.llm.provider import GeminiProvider

    seen: dict[str, Any] = {}

    def fake_post(url: str, headers: dict, json: dict, timeout: float) -> httpx.Response:
        seen.update(url=url, headers=headers, body=json, timeout=timeout)
        payload = {"candidates": [{"content": {"parts": [{"text": '{"action": "refuse", '},
                                                          {"text": '"limitation": "x"}'}]}}]}
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(httpx, "post", fake_post)
    completion = GeminiProvider("secret-key", "gemini-test", 7).complete(
        "system", [Message("user", "q")], "json"
    )

    assert completion.text == '{"action": "refuse", "limitation": "x"}'
    assert completion.model == "gemini-test"
    assert "secret-key" not in seen["url"]
    assert seen["headers"] == {"x-goog-api-key": "secret-key"}
    assert seen["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert seen["timeout"] == 7


def test_gemini_timeouts_and_server_errors_count_as_unavailable(monkeypatch) -> None:
    import httpx

    from app.llm.provider import GeminiProvider, ProviderUnavailable

    def timeout(*_args: Any, **_kwargs: Any) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    provider = GeminiProvider("k", "gemini-test", 1)
    monkeypatch.setattr(httpx, "post", timeout)
    with pytest.raises(ProviderUnavailable):
        provider.complete("s", [Message("user", "q")], "text")

    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(503))
    with pytest.raises(ProviderUnavailable):
        provider.complete("s", [Message("user", "q")], "text")
