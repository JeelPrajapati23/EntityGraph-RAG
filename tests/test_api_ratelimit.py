"""/query rate limit: synthetic resources, fake clock, no Groq/HF calls."""
from fastapi.testclient import TestClient

import reachfix.api.app as app_module
from reachfix.api import Resources, create_app
from reachfix.api.ratelimit import QueryLimiter
from reachfix.depgraph import DepGraphContext
from reachfix.graph import NetworkXGraphStore
from reachfix.npm.lookup import NodeLookup


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_per_ip_limit_refuses_then_frees_after_an_hour():
    clock = Clock()
    limiter = QueryLimiter(per_ip_hour=2, clock=clock)
    assert limiter.acquire("a") is None
    assert limiter.acquire("a") is None
    assert "2 questions per hour" in limiter.acquire("a")
    assert limiter.acquire("b") is None  # other clients are unaffected

    clock.now += 3600
    assert limiter.acquire("a") is None


def test_daily_limit_is_shared_by_every_ip():
    clock = Clock()
    limiter = QueryLimiter(per_day=2, clock=clock)
    assert limiter.acquire("a") is None
    assert limiter.acquire("b") is None
    assert "used its 2 questions for today" in limiter.acquire("c")

    clock.now += 86400
    assert limiter.acquire("c") is None


def test_refused_queries_are_not_counted():
    clock = Clock()
    limiter = QueryLimiter(per_ip_hour=1, per_day=2, clock=clock)
    assert limiter.acquire("a") is None
    for _ in range(5):
        assert limiter.acquire("a") is not None
    assert limiter.acquire("b") is None  # a's refusals didn't use up the daily cap


def test_from_env_is_off_unless_configured(monkeypatch):
    monkeypatch.delenv("REACHFIX_QUERY_LIMIT_PER_IP_HOUR", raising=False)
    monkeypatch.delenv("REACHFIX_QUERY_LIMIT_PER_DAY", raising=False)
    assert QueryLimiter.from_env() is None

    monkeypatch.setenv("REACHFIX_QUERY_LIMIT_PER_IP_HOUR", "5")
    limiter = QueryLimiter.from_env()
    assert (limiter.per_ip_hour, limiter.per_day) == (5, 0)


def test_query_endpoint_returns_429_using_forwarded_client_ip(monkeypatch):
    monkeypatch.setattr(app_module, "route_query", lambda *a, **k: {
        "query": "q", "route": "semantic", "executed_route": "semantic", "pattern": None,
        "executed_pattern": None, "classification_reasoning": "", "warnings": [], "results": []})
    monkeypatch.setattr(app_module, "synthesize_answer", lambda result, **k: {"answer": "ok"})
    ctx = DepGraphContext(store=NetworkXGraphStore(), lookup=NodeLookup([]), index=None, chunks_by_id={},
                          embedding_client=None)
    app = create_app(Resources(ctx=ctx, schema=None, client=None), query_limiter=QueryLimiter(per_ip_hour=1))

    with TestClient(app) as client:
        first = {"x-forwarded-for": "203.0.113.7, 10.0.0.1"}
        assert client.post("/query", json={"query": "q"}, headers=first).status_code == 200
        refused = client.post("/query", json={"query": "q"}, headers=first)
        assert refused.status_code == 429
        assert "per hour" in refused.json()["detail"]
        assert client.post("/query", json={"query": "q"},
                           headers={"x-forwarded-for": "198.51.100.2"}).status_code == 200
