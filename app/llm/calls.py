"""One model call: made through whatever provider is configured, and logged.

Shared by the assistant and the dashboard narrative, so every prompt either
of them sends lands in the same review table in the same shape.
"""
from __future__ import annotations

import time
from typing import Any, Optional, Sequence

import duckdb

from app.llm.log import log_call
from app.llm.provider import (
    Completion,
    Message,
    Provider,
    ProviderError,
    ProviderUnavailable,
    ResponseFormat,
    input_key,
)


def logged_call(
    con: duckdb.DuckDBPyConnection,
    provider: Provider,
    purpose: str,
    system: str,
    messages: Sequence[Message],
    response_format: ResponseFormat,
    calls: list[dict[str, Any]],
) -> Optional[Completion]:
    """One model call, logged whatever happens. None when there is no answer."""
    started = time.perf_counter()
    completion: Optional[Completion] = None
    outcome, error = "ok", None
    try:
        completion = provider.complete(system, messages, response_format)
    except ProviderUnavailable as exc:
        outcome, error = "unavailable", str(exc)
    except ProviderError as exc:
        outcome, error = "error", str(exc)
    log_call(
        con,
        purpose=purpose,
        model=completion.model if completion else provider.model,
        key=input_key(system, messages, response_format),
        system=system,
        messages=messages,
        response=completion.text if completion else None,
        served_from_cache=bool(completion and completion.served_from_cache),
        outcome=outcome,
        error=error,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    calls.append(
        {
            "purpose": purpose,
            "model": completion.model if completion else provider.model,
            "served_from_cache": bool(completion and completion.served_from_cache),
            "outcome": outcome,
            "error": error,
        }
    )
    return completion
