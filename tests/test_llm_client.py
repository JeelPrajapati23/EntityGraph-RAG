from types import SimpleNamespace

import httpx
import pytest
from groq import Groq, InternalServerError, RateLimitError

from reachfix.llm_client import RotatingGroq, build_client, generate_text, parse_api_keys

REQUEST = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
DAILY = "Rate limit reached ... on tokens per day (TPD): Limit 200000, Used 198398"
MINUTE = "Rate limit reached ... on tokens per minute (TPM): Limit 8000, Used 7900"


def rate_limit(message, retry_after="7"):
    return RateLimitError(message, response=httpx.Response(429, request=REQUEST, headers={"retry-after": retry_after}),
                          body=None)


def server_error():
    return InternalServerError("boom", response=httpx.Response(503, request=REQUEST), body=None)


def completion(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


class FakeClient:
    """Plays back a script of outcomes (an exception to raise, or a reply text)."""

    def __init__(self, name, outcomes):
        self.name, self.outcomes, self.calls = name, list(outcomes), 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0) if self.outcomes else f"reply from {self.name}"
        if isinstance(outcome, Exception):
            raise outcome
        return completion(outcome)


def rotating(*scripts):
    fakes = {f"k{i}": FakeClient(f"k{i}", script) for i, script in enumerate(scripts)}
    sleeps = []
    client = RotatingGroq(list(fakes), sleep=sleeps.append, client_factory=fakes.__getitem__)
    return client, list(fakes.values()), sleeps


def ask(client):
    return generate_text(client, user_prompt="hi")


def test_parse_api_keys():
    assert parse_api_keys(" gsk_a, gsk_b ,,gsk_c ") == ["gsk_a", "gsk_b", "gsk_c"]
    assert parse_api_keys(None) == []


def test_build_client_single_key_is_plain_groq_and_several_rotate():
    assert isinstance(build_client("gsk_one"), Groq)
    assert isinstance(build_client("gsk_one,gsk_two"), RotatingGroq)
    with pytest.raises(RuntimeError):
        build_client("  ,  ")


def test_daily_limit_retires_key_and_later_calls_skip_it():
    client, (k0, k1), _ = rotating([rate_limit(DAILY)], [])

    assert ask(client) == "reply from k1"
    assert ask(client) == "reply from k1"
    assert k0.calls == 1 and client.live_keys == 1


def test_all_keys_exhausted_raises_the_daily_error():
    client, _, _ = rotating([rate_limit(DAILY)], [rate_limit(DAILY)])

    with pytest.raises(RateLimitError, match="per day"):
        ask(client)
    with pytest.raises(RateLimitError, match="per day"):  # and keeps raising without new calls
        ask(client)


def test_per_minute_limit_moves_to_next_key_without_retiring():
    client, (k0, k1), sleeps = rotating([rate_limit(MINUTE)], [])

    assert ask(client) == "reply from k1"
    assert client.live_keys == 2 and sleeps == []


def test_waits_retry_after_once_every_live_key_is_throttled():
    client, _, sleeps = rotating([rate_limit(MINUTE), "ok from k0"], [rate_limit(MINUTE, retry_after="3")])

    assert ask(client) == "ok from k0"
    assert sleeps == [3.0]


def test_throttled_rounds_are_bounded():
    client, _, sleeps = rotating([rate_limit(MINUTE)] * 50, [rate_limit(MINUTE)] * 50)

    with pytest.raises(RateLimitError, match="per minute"):
        ask(client)
    assert len(sleeps) == RotatingGroq.MAX_THROTTLED_ROUNDS


def test_transient_errors_retry_on_same_key_with_backoff():
    client, (k0, k1), sleeps = rotating([server_error(), server_error(), "recovered"], [])

    assert ask(client) == "recovered"
    assert k1.calls == 0 and sleeps == [2, 4]


def test_log_messages_never_contain_keys(caplog):
    fakes = {"gsk_SECRET0": FakeClient("a", [rate_limit(DAILY)]), "gsk_SECRET1": FakeClient("b", [])}
    client = RotatingGroq(list(fakes), sleep=lambda s: None, client_factory=fakes.__getitem__)

    ask(client)

    assert "key 1/2" in caplog.text and "SECRET" not in caplog.text
