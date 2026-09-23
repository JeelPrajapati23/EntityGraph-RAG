import json
from datetime import datetime, timedelta, timezone

from reachfix.npm.live_releases import ABBREVIATED, RegistryClient
from reachfix.npm.osv import OsvClient, batch_query, fetch_record


class Response:
    def __init__(self, body):
        self.status_code, self.body = 200, body

    def json(self):
        return self.body

    def raise_for_status(self):
        pass


class FakeSession:
    """Answers querybatch from `pages` (one list of results per call) and GET /vulns/{id} from `records`."""

    def __init__(self, pages=(), records=None):
        self.pages, self.records, self.calls = list(pages), records or {}, []

    def request(self, method, url, timeout=None, json=None, headers=None):
        self.calls.append((method, url, json or headers))
        if url.endswith("/querybatch"):
            return Response({"results": self.pages.pop(0)})
        return Response(self.records[url.rsplit("/", 1)[1]])


def test_batch_query_follows_page_tokens():
    session = FakeSession(pages=[
        [{"vulns": [{"id": "GHSA-a", "modified": "t1"}], "next_page_token": "p2"}, {}],
        [{"vulns": [{"id": "GHSA-b", "modified": "t2"}]}],
    ])
    matches = batch_query(session, [("lib", "1.0.0"), ("safe", "2.0.0")])

    assert matches == {("lib", "1.0.0"): {"GHSA-a": "t1", "GHSA-b": "t2"}}
    assert session.calls[1][2] == {"queries": [{"package": {"name": "lib", "ecosystem": "npm"}, "version": "1.0.0",
                                                "page_token": "p2"}]}


def test_fetch_record_reuses_cache_until_modified_changes(tmp_path):
    (tmp_path / "GHSA-a.json").write_text(json.dumps({"id": "GHSA-a", "modified": "2026-01-01T00:00:00.123456789Z"}))
    session = FakeSession(records={"GHSA-a": {"id": "GHSA-a", "modified": "2026-02-01T00:00:00Z"}})

    # querybatch reports microseconds, the record nanoseconds: the same instant.
    assert fetch_record(session, tmp_path, "GHSA-a", "2026-01-01T00:00:00.123456Z")[1] is False
    record, downloaded = fetch_record(session, tmp_path, "GHSA-a", "2026-02-01T00:00:00Z")
    assert downloaded and json.loads((tmp_path / "GHSA-a.json").read_text())["modified"] == record["modified"]
    assert [p.name for p in tmp_path.iterdir()] == ["GHSA-a.json"]  # no temp file left behind


def test_client_lookup_returns_matches_and_records(tmp_path):
    session = FakeSession(pages=[[{"vulns": [{"id": "GHSA-a", "modified": "t"}]}]],
                          records={"GHSA-a": {"id": "GHSA-a", "modified": "t"}})
    matches, records = OsvClient(tmp_path / "live", session).lookup([("lib", "1.0.0")])
    assert matches == {("lib", "1.0.0"): {"GHSA-a"}} and records == {"GHSA-a": {"id": "GHSA-a", "modified": "t"}}


def test_registry_client_caches_with_a_ttl(tmp_path):
    packument = {"name": "@s/lib", "versions": {"1.0.0": {"dependencies": {"a": "^1"}, "deprecated": "old"},
                                                "1.0.1": {"optionalDependencies": {"b": "^2"}}}}
    session = FakeSession(records={"@s%2Flib": packument})
    clock = [datetime(2026, 9, 23, tzinfo=timezone.utc)]
    client = RegistryClient(tmp_path, session, ttl=timedelta(days=1), now=lambda: clock[0])

    got, failed = client.fetch(["@s/lib", "@s/lib"])
    assert failed == {} and got["@s/lib"] == {
        "versions": ["1.0.0", "1.0.1"], "complete": True,
        "manifests": {"1.0.0": {"dependencies": {"a": "^1"}, "deprecated": "old"},
                      "1.0.1": {"dependencies": {"b": "^2"}, "deprecated": None}}}
    assert session.calls == [("GET", "https://registry.npmjs.org/@s%2Flib", {"Accept": ABBREVIATED})]
    assert [p.name for p in tmp_path.iterdir()] == ["@s__lib.json"]

    client.fetch(["@s/lib"])  # cached
    clock[0] += timedelta(days=2)
    client.fetch(["@s/lib"])  # expired
    assert len(session.calls) == 2


def test_registry_client_reports_failures(tmp_path):
    got, failed = RegistryClient(tmp_path, FakeSession(records={})).fetch(["nope"])
    assert got == {} and list(failed) == ["nope"]
