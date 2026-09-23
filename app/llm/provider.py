"""Language-model providers behind one interface.

The provider a state-government deployment may use is whatever that
organisation has approved, so nothing outside this module names one. Callers
get a :class:`Provider` from :func:`build_provider` and call ``complete``.

Three implementations:

* :class:`GeminiProvider` -- the hosted model, over HTTPS.
* :class:`CachedProvider` -- wraps any provider (or none) and answers every
  input it has seen before from disk, byte for byte. A live call is made only
  for new input. With no API key, or with the network down, questions asked
  before still answer; new ones fail with :class:`ProviderUnavailable`.
* :class:`FixtureProvider` -- answers from a script instead of a model. Used by
  the tests and by ``python -m app.cli seed-assistant``, which records the
  starter questions' responses into the shipped cache.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal, Mapping, Optional, Protocol, Sequence, Union

import httpx

from app import config

ResponseFormat = Literal["json", "text"]


@dataclass(frozen=True)
class Message:
    role: Literal["user", "model"]
    text: str


@dataclass(frozen=True)
class Completion:
    text: str
    # What produced the text: a model name, or "fixture".
    model: str
    served_from_cache: bool = False


class ProviderError(RuntimeError):
    """The provider answered, but not usefully (bad request, refused, empty)."""


class ProviderUnavailable(ProviderError):
    """No answer could be had: no provider configured, timeout, or no network."""


class Provider(Protocol):
    model: str

    def complete(
        self, system: str, messages: Sequence[Message], response_format: ResponseFormat
    ) -> Completion: ...


def input_key(system: str, messages: Sequence[Message], response_format: ResponseFormat) -> str:
    """The cache key: a hash of everything the model is shown, and nothing else.

    The model name is left out on purpose, so a response recorded offline keeps
    answering after a model is configured.
    """
    canonical = json.dumps(
        {
            "system": system,
            "messages": [{"role": m.role, "text": m.text} for m in messages],
            "response_format": response_format,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Gemini
# --------------------------------------------------------------------------
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiProvider:
    def __init__(self, api_key: str, model: str, timeout: float) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def complete(
        self, system: str, messages: Sequence[Message], response_format: ResponseFormat
    ) -> Completion:
        generation: dict[str, object] = {"temperature": 0}
        if response_format == "json":
            generation["responseMimeType"] = "application/json"
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": m.role, "parts": [{"text": m.text}]} for m in messages],
            "generationConfig": generation,
        }
        try:
            # The key travels in a header, never the URL, so it cannot end up
            # in an access log.
            response = httpx.post(
                GEMINI_URL.format(model=self.model),
                headers={"x-goog-api-key": self.api_key},
                json=body,
                timeout=self.timeout,
            )
        except httpx.TimeoutException as exc:
            raise ProviderUnavailable(f"{self.model} did not answer within {self.timeout:g}s") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"{self.model} could not be reached") from exc

        if response.status_code == 429 or response.status_code >= 500:
            raise ProviderUnavailable(f"{self.model} returned HTTP {response.status_code}")
        if response.status_code != 200:
            raise ProviderError(f"{self.model} rejected the request (HTTP {response.status_code})")
        try:
            parts = response.json()["candidates"][0]["content"]["parts"]
            text = "".join(part.get("text", "") for part in parts)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"{self.model} returned no text") from exc
        if not text.strip():
            raise ProviderError(f"{self.model} returned no text")
        return Completion(text=text, model=self.model)


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------
class CachedProvider:
    """Answers seen-before input from disk; asks ``inner`` only for new input.

    Cache first rather than live first: the same question over the same data
    then answers identically every time, which is what a demo in front of a
    directorate needs, and a slow provider cannot stall a question already
    answered once.
    """

    def __init__(self, inner: Optional[Provider], cache_dir: Path) -> None:
        self.inner = inner
        self.cache_dir = Path(cache_dir)
        self.model = inner.model if inner is not None else "none"

    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def lookup(self, key: str) -> Optional[Completion]:
        path = self._path(key)
        if not path.exists():
            return None
        entry = json.loads(path.read_text(encoding="utf-8"))
        return Completion(text=entry["response"], model=entry["model"], served_from_cache=True)

    def store(self, key: str, completion: Completion) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "key": key,
            "model": completion.model,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "response": completion.text,
        }
        # Written whole, then renamed, so a crash cannot leave half an entry
        # that later reads as a cached answer.
        handle, temp = tempfile.mkstemp(dir=self.cache_dir, suffix=".tmp")
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(entry, out, ensure_ascii=False, indent=2)
        os.replace(temp, self._path(key))

    def complete(
        self, system: str, messages: Sequence[Message], response_format: ResponseFormat
    ) -> Completion:
        key = input_key(system, messages, response_format)
        cached = self.lookup(key)
        if cached is not None:
            return cached
        if self.inner is None:
            raise ProviderUnavailable(
                "no language model is configured (LLM_API_KEY is not set) and this "
                "input has not been answered before"
            )
        completion = self.inner.complete(system, messages, response_format)
        self.store(key, completion)
        return completion


# --------------------------------------------------------------------------
# Fixture
# --------------------------------------------------------------------------
Responder = Callable[[str, Sequence[Message], ResponseFormat], str]


class FixtureProvider:
    """A scripted stand-in for a model.

    ``responses`` is either a sequence, answered in order, or a function of the
    input. Every call is kept in ``calls`` so a test can inspect exactly what a
    model would have been shown.
    """

    model = "fixture"

    def __init__(self, responses: Union[Sequence[str], Responder, Mapping[str, str]]) -> None:
        self._responses = responses
        self._next = 0
        self.calls: list[tuple[str, list[Message], ResponseFormat]] = []

    def complete(
        self, system: str, messages: Sequence[Message], response_format: ResponseFormat
    ) -> Completion:
        self.calls.append((system, list(messages), response_format))
        if callable(self._responses):
            text = self._responses(system, messages, response_format)
        elif isinstance(self._responses, Mapping):
            key = input_key(system, messages, response_format)
            if key not in self._responses:
                raise ProviderUnavailable("the fixture has no response for this input")
            text = self._responses[key]
        else:
            if self._next >= len(self._responses):
                raise ProviderUnavailable("the fixture has no more responses")
            text = self._responses[self._next]
            self._next += 1
        return Completion(text=text, model=self.model)


class UnreachableProvider:
    """A provider whose network is down. For tests and outage drills."""

    def __init__(self, model: str = "unreachable") -> None:
        self.model = model

    def complete(
        self, system: str, messages: Sequence[Message], response_format: ResponseFormat
    ) -> Completion:
        raise ProviderUnavailable(f"{self.model} could not be reached")


def build_provider() -> CachedProvider:
    """The provider the app runs with, from the environment.

    ``LLM_PROVIDER=gemini`` with ``LLM_API_KEY`` set gives a live model behind
    the cache. Anything else -- including no key at all -- gives the cache
    alone, so the app runs and the starter questions answer with no key.
    """
    inner: Optional[Provider] = None
    if config.LLM_PROVIDER == "gemini" and config.LLM_API_KEY:
        inner = GeminiProvider(config.LLM_API_KEY, config.LLM_MODEL, config.LLM_TIMEOUT_SECONDS)
    return CachedProvider(inner, config.LLM_CACHE_DIR)
