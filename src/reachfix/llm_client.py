"""Thin Groq wrapper for chat/JSON completions (openai/gpt-oss-120b by default).

Shared by every generation call site: exploit-condition extraction, router
classification and answer synthesis. Groq's OpenAI-compatible API has no
response_schema-level validation, so generate_json only guarantees
syntactically valid JSON (via response_format json_object); callers still
validate the returned text against their own Pydantic model (the
conditions/ extraction model, depgraph/classify.py's decision model).

GROQ_API_KEY may hold several comma-separated keys. Groq's limits are per
organization, so they only help if each key belongs to a different one.
build_client then returns a RotatingGroq instead of a plain Groq client.
"""

import logging
import os
import time
from types import SimpleNamespace

from groq import APIConnectionError, Groq, InternalServerError, RateLimitError

DEFAULT_MODEL = "openai/gpt-oss-120b"

log = logging.getLogger(__name__)


def parse_api_keys(raw: str | None) -> list[str]:
    return [k.strip() for k in (raw or "").split(",") if k.strip()]


def build_client(api_key: str | None = None) -> "Groq | RotatingGroq":
    keys = parse_api_keys(api_key or os.environ.get("GROQ_API_KEY"))
    if not keys:
        raise RuntimeError("GROQ_API_KEY is not set (check .env)")
    if len(keys) == 1:
        return Groq(api_key=keys[0])
    return RotatingGroq(keys)


def is_daily_limit(exc: RateLimitError) -> bool:
    """A per-day quota (tokens or requests), as opposed to a per-minute one."""
    return "per day" in str(exc)


def retry_after_seconds(exc: RateLimitError, default: float = 5.0, cap: float = 60.0) -> float:
    try:
        return min(float(exc.response.headers.get("retry-after", default)), cap)
    except (AttributeError, TypeError, ValueError):
        return default


class RotatingGroq:
    """Spreads calls over several Groq API keys and moves past rate-limited ones.

    Exposes the one method call sites use, `chat.completions.create`, so it
    is a drop-in for `Groq` in generate_text / generate_json.

    - Daily-limit 429 (TPD/RPD): that key is retired for the life of this
      object, and the call moves on to the next key.
    - Per-minute 429 (TPM/RPM): the call moves on to the next key. Once every
      live key has been throttled in a row, wait for the server's
      `retry-after` and go round again.
    - Connection errors and 5xx: retried on the same key with backoff.
    - Every key retired: the last daily-limit error is raised.

    Keys are only ever logged by position ("key 3/8"), never by value.
    """

    MAX_THROTTLED_ROUNDS = 10
    MAX_TRANSIENT_RETRIES = 2

    def __init__(self, api_keys: list[str], *, sleep=time.sleep, client_factory=None):
        factory = client_factory or (lambda key: Groq(api_key=key, max_retries=0))
        self._clients = [factory(key) for key in api_keys]
        self._retired: set[int] = set()
        self._last_daily_error: RateLimitError | None = None
        self._current = 0
        self._sleep = sleep
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    @property
    def live_keys(self) -> int:
        return len(self._clients) - len(self._retired)

    def _label(self, index: int) -> str:
        return f"key {index + 1}/{len(self._clients)}"

    def _advance(self, index: int) -> None:
        """Point at the next live key after `index`, if any."""
        for step in range(1, len(self._clients) + 1):
            candidate = (index + step) % len(self._clients)
            if candidate not in self._retired:
                self._current = candidate
                return

    def _create(self, **kwargs):
        throttled: set[int] = set()
        rounds = transient = 0
        while True:
            if self.live_keys == 0:
                raise self._last_daily_error
            index = self._current
            try:
                return self._clients[index].chat.completions.create(**kwargs)
            except RateLimitError as exc:
                if is_daily_limit(exc):
                    self._retired.add(index)
                    self._last_daily_error = exc
                    log.warning("Groq %s hit its daily limit; %d keys left", self._label(index), self.live_keys)
                    self._advance(index)
                    continue
                throttled.add(index)
                self._advance(index)
                if throttled >= set(range(len(self._clients))) - self._retired:
                    rounds += 1
                    if rounds > self.MAX_THROTTLED_ROUNDS:
                        raise
                    wait = retry_after_seconds(exc)
                    log.warning("every live Groq key is rate limited per minute; waiting %.0fs", wait)
                    self._sleep(wait)
                    throttled.clear()
            except (APIConnectionError, InternalServerError):
                transient += 1
                if transient > self.MAX_TRANSIENT_RETRIES:
                    raise
                self._sleep(2 ** transient)


def _messages(system_prompt: str | None, user_prompt: str) -> list[dict]:
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})
    return messages


def generate_text(
    client: Groq,
    *,
    user_prompt: str,
    system_prompt: str | None = None,
    model_name: str = DEFAULT_MODEL,
    temperature: float = 0.0,
) -> str:
    response = client.chat.completions.create(
        model=model_name, messages=_messages(system_prompt, user_prompt), temperature=temperature,
    )
    return response.choices[0].message.content


def generate_json(
    client: Groq,
    *,
    user_prompt: str,
    system_prompt: str | None = None,
    model_name: str = DEFAULT_MODEL,
    temperature: float = 0.0,
) -> str:
    response = client.chat.completions.create(
        model=model_name,
        messages=_messages(system_prompt, user_prompt),
        temperature=temperature,
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content
