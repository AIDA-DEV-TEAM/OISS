"""Record the starter questions' responses into the shipped cache.

Runs each starter through the real pipeline with the recorded replies in
:mod:`app.assistant.starters` standing in for the model, so the cache holds
exactly the inputs a live run produces. A recorded answer that fails the number
check, or a spec the registry rejects, stops the recording: the cache must
never ship something the pipeline would not have accepted.

Re-run after changing a prompt, the registry or the data, since each of those
changes the cache keys.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

import duckdb

from app.assistant import prompts
from app.assistant.service import ask
from app.assistant.starters import STARTERS, Starter
from app.llm.provider import CachedProvider, FixtureProvider, Message, ResponseFormat


def _starter_for(messages: Sequence[Message]) -> Starter:
    first = messages[0].text
    for starter in STARTERS:
        if f"Question: {starter.question}" in first or json.dumps(starter.question) in first:
            return starter
    raise LookupError("no starter matches this input")


def _respond(system: str, messages: Sequence[Message], _format: ResponseFormat) -> str:
    starter = _starter_for(messages)
    if system == prompts.INTERPRET_SYSTEM:
        return json.dumps(starter.reply)
    if starter.answer is None:
        raise LookupError(f"{starter.question_id} has no recorded answer")
    return starter.answer


def seed(con: duckdb.DuckDBPyConnection, cache_dir: Path) -> list[dict[str, str]]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Entries recorded by an earlier seed have stale keys once anything changes.
    for path in cache_dir.glob("*.json"):
        if json.loads(path.read_text(encoding="utf-8")).get("model") == "fixture":
            path.unlink()

    provider = CachedProvider(FixtureProvider(_respond), cache_dir)
    recorded = []
    for starter in STARTERS:
        result = ask(con, starter.question, provider)
        expected = "declined" if starter.reply["action"] == "refuse" else "answered"
        if result["status"] != expected:
            raise RuntimeError(
                f"{starter.question_id}: expected {expected}, got {result['status']}: "
                f"{result.get('limitation')}"
            )
        if expected == "answered" and result["answer_source"] != "model":
            raise RuntimeError(
                f"{starter.question_id}: the recorded answer failed the number check"
            )
        recorded.append({"question_id": starter.question_id, "status": result["status"]})
    return recorded
