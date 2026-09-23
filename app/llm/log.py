"""Every prompt and response, kept in a local table for review.

Nothing here leaves the machine. The table is the audit trail for what the
model was shown and what it said, including calls that failed and calls served
from the cache.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Sequence

import duckdb

from app.db import LLM_DDL
from app.llm.provider import Message

logger = logging.getLogger(__name__)

# The only statement in the assistant's path that writes. The model's text
# reaches it as a bound parameter, stored for review and never executed.
_INSERT = """
INSERT INTO analytics.llm_call (
    call_id, created_at, purpose, model, input_key, system_prompt, messages_json,
    response_text, served_from_cache, outcome, error, latency_ms
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def log_call(
    con: duckdb.DuckDBPyConnection,
    *,
    purpose: str,
    model: Optional[str],
    key: str,
    system: str,
    messages: Sequence[Message],
    response: Optional[str],
    served_from_cache: bool,
    outcome: str,
    error: Optional[str],
    latency_ms: int,
) -> None:
    try:
        # Databases built before the assistant existed lack the table.
        con.execute(LLM_DDL)
        con.execute(
            _INSERT,
            [
                uuid.uuid4().hex,
                datetime.now(timezone.utc).replace(tzinfo=None),
                purpose,
                model,
                key,
                system,
                json.dumps([{"role": m.role, "text": m.text} for m in messages], ensure_ascii=False),
                response,
                served_from_cache,
                outcome,
                error,
                latency_ms,
            ],
        )
    except duckdb.Error as exc:
        # A read-only database cannot keep the log; the answer still stands.
        logger.warning("could not log a model call: %s", exc)
