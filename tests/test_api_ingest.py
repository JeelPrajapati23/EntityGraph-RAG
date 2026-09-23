"""Synthetic fixtures only — no real scripts spawned, no network."""
import threading

import pytest
from fastapi.testclient import TestClient

from entitygraph_rag.api import Resources, create_app
from entitygraph_rag.api.ingest import IngestInProgressError, IngestManager, IngestRequest, build_steps
from entitygraph_rag.graph import NetworkXGraphStore
from entitygraph_rag.router import EntityLookup

KEY = "test-ingest-key"
AUTH = {"X-API-Key": KEY}


def _resources(n_chunks: int) -> Resources:
    return Resources(
        chunks_by_id={f"c{i}": {"chunk_id": f"c{i}"} for i in range(n_chunks)},
        entity_lookup=EntityLookup([]), store=NetworkXGraphStore(),
        index=None, schema=None, client=None, embedding_client=None,
    )


@pytest.fixture
def processed_dir(tmp_path):
    processed = tmp_path / "processed"
    processed.mkdir()
    (processed / "chunks.jsonl").write_text("old", encoding="utf-8")
    return processed


def _manager(processed_dir, run_step, loader=lambda: _resources(3)):
    return IngestManager(loader, processed_dir=processed_dir, run_step=run_step, log_dir=None)


def _step_names(steps):
    return [name for name, _ in steps]


def test_build_steps_default_runs_full_pipeline():
    steps = build_steps(IngestRequest())
    assert _step_names(steps) == [
        "fetch_filings", "fetch_transcripts", "build_chunks", "extract_triples",
        "resolve_entities", "build_graph", "build_index",
    ]
    assert all("--tickers" not in argv for _, argv in steps)


def test_build_steps_skip_fetch_tickers_and_extract_limit():
    steps = dict(build_steps(IngestRequest(tickers=["nvda", " aapl"], skip_fetch=True, extract_limit=50)))

    assert "fetch_filings" not in steps
    assert steps["build_chunks"] == ["scripts/build_chunks.py", "--tickers", "NVDA,AAPL"]
    assert steps["extract_triples"] == ["scripts/extract_triples.py", "--tickers", "NVDA,AAPL", "--limit", "50"]
    assert "--limit" not in steps["build_index"]


def test_successful_job_runs_every_step_then_reloads(processed_dir):
    ran = []

    def run_step(argv, on_line):
        ran.append(argv[0])
        on_line(f"ran {argv[0]}")
        return 0

    reloaded = []
    manager = _manager(processed_dir, run_step)
    job = manager.start(IngestRequest(skip_fetch=True), on_reloaded=reloaded.append)
    manager.wait(job.job_id, timeout=5)

    assert job.status == "succeeded"
    assert ran == [argv[0] for _, argv in build_steps(IngestRequest(skip_fetch=True))]
    assert all(step["status"] == "succeeded" for step in job.steps)
    assert len(reloaded[0].chunks_by_id) == 3
    assert "ran scripts/build_index.py" in job.log_tail
    assert sorted(p.name for p in processed_dir.parent.iterdir()) == ["processed", "processed.prev"]
    assert (processed_dir.parent / "processed.prev" / "chunks.jsonl").read_text(encoding="utf-8") == "old"


def test_failed_step_restores_previous_artifacts(processed_dir):
    def run_step(argv, on_line):
        (processed_dir / "chunks.jsonl").write_text("half-rebuilt", encoding="utf-8")
        return 1 if argv[0] == "scripts/extract_triples.py" else 0

    reloaded = []
    manager = _manager(processed_dir, run_step)
    job = manager.start(IngestRequest(skip_fetch=True), on_reloaded=reloaded.append)
    manager.wait(job.job_id, timeout=5)

    assert job.status == "failed"
    assert "extract_triples" in job.error
    statuses = {step["name"]: step["status"] for step in job.steps}
    assert statuses["build_chunks"] == "succeeded"
    assert statuses["extract_triples"] == "failed"
    assert statuses["build_index"] == "pending"
    assert reloaded == []
    assert (processed_dir / "chunks.jsonl").read_text(encoding="utf-8") == "old"
    assert [p.name for p in processed_dir.parent.iterdir()] == ["processed"]


def test_reload_failure_also_restores(processed_dir):
    def run_step(argv, on_line):
        (processed_dir / "chunks.jsonl").write_text("corrupt", encoding="utf-8")
        return 0

    def bad_loader():
        raise FileNotFoundError("graph.pkl missing")

    manager = _manager(processed_dir, run_step, loader=bad_loader)
    job = manager.start(IngestRequest(skip_fetch=True), on_reloaded=lambda r: None)
    manager.wait(job.job_id, timeout=5)

    assert job.status == "failed"
    assert "graph.pkl missing" in job.error
    assert (processed_dir / "chunks.jsonl").read_text(encoding="utf-8") == "old"


def test_second_job_rejected_while_first_runs(processed_dir):
    release = threading.Event()

    def run_step(argv, on_line):
        release.wait(5)
        return 0

    manager = _manager(processed_dir, run_step)
    first = manager.start(IngestRequest(skip_fetch=True), on_reloaded=lambda r: None)
    with pytest.raises(IngestInProgressError):
        manager.start(IngestRequest(skip_fetch=True), on_reloaded=lambda r: None)

    release.set()
    manager.wait(first.job_id, timeout=5)
    second = manager.start(IngestRequest(skip_fetch=True), on_reloaded=lambda r: None)
    manager.wait(second.job_id, timeout=5)
    assert second.status == "succeeded"


def test_api_ingest_swaps_resources_on_success(processed_dir):
    release = threading.Event()

    def run_step(argv, on_line):
        release.wait(5)
        return 0

    manager = _manager(processed_dir, run_step, loader=lambda: _resources(7))
    with TestClient(create_app(_resources(1), ingest_manager=manager, ingest_api_key=KEY)) as client:
        resp = client.post("/ingest", headers=AUTH, json={"skip_fetch": True})
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]

        assert client.post("/ingest", headers=AUTH, json={}).status_code == 409
        assert client.get("/health").json()["chunks"] == 1  # still serving old artifacts

        release.set()
        manager.wait(job_id, timeout=5)

        assert client.get(f"/ingest/{job_id}", headers=AUTH).json()["status"] == "succeeded"
        assert client.get("/health").json()["chunks"] == 7
        assert [job["job_id"] for job in client.get("/ingest", headers=AUTH).json()] == [job_id]


def test_api_ingest_unknown_job_is_404(processed_dir):
    manager = _manager(processed_dir, lambda argv, on_line: 0)
    with TestClient(create_app(_resources(1), ingest_manager=manager, ingest_api_key=KEY)) as client:
        assert client.get("/ingest/nope", headers=AUTH).status_code == 404


def test_api_ingest_validates_body(processed_dir):
    manager = _manager(processed_dir, lambda argv, on_line: 0)
    with TestClient(create_app(_resources(1), ingest_manager=manager, ingest_api_key=KEY)) as client:
        assert client.post("/ingest", headers=AUTH, json={"max_per_form": 0}).status_code == 422


def test_second_success_replaces_previous_backup(processed_dir):
    def run_step(argv, on_line):
        n = int((processed_dir / "chunks.jsonl").read_text(encoding="utf-8").replace("old", "0"))
        if argv[0] == "scripts/build_index.py":
            (processed_dir / "chunks.jsonl").write_text(str(n + 1), encoding="utf-8")
        return 0

    manager = _manager(processed_dir, run_step)
    for _ in range(2):
        job = manager.start(IngestRequest(skip_fetch=True), on_reloaded=lambda r: None)
        manager.wait(job.job_id, timeout=5)

    assert (processed_dir / "chunks.jsonl").read_text(encoding="utf-8") == "2"
    assert (processed_dir.parent / "processed.prev" / "chunks.jsonl").read_text(encoding="utf-8") == "1"
    assert sorted(p.name for p in processed_dir.parent.iterdir()) == ["processed", "processed.prev"]


def test_api_ingest_rejects_missing_or_wrong_key(processed_dir):
    manager = _manager(processed_dir, lambda argv, on_line: 0)
    with TestClient(create_app(_resources(1), ingest_manager=manager, ingest_api_key=KEY)) as client:
        assert client.post("/ingest", json={}).status_code == 401
        assert client.post("/ingest", headers={"X-API-Key": "wrong"}, json={}).status_code == 401
        assert client.get("/ingest").status_code == 401
        assert client.get("/ingest/nope").status_code == 401
    assert manager.all_jobs() == []


def test_api_ingest_disabled_without_configured_key(processed_dir, monkeypatch):
    monkeypatch.delenv("INGEST_API_KEY", raising=False)
    manager = _manager(processed_dir, lambda argv, on_line: 0)
    with TestClient(create_app(_resources(1), ingest_manager=manager)) as client:
        assert client.post("/ingest", headers=AUTH, json={}).status_code == 503
        assert client.get("/health").status_code == 200
