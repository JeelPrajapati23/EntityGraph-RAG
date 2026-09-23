"""Background ingest jobs: rebuild every pipeline artifact, then hot-swap the API's resources.

Runs the existing scripts/ (fetch → chunk → extract → resolve → graph →
index) as subprocesses, in order, rather than re-implementing them — the
scripts stay the single source of truth for each step, and a crash in one
can't take the server down with it. Every script overwrites its output, so
each job is a from-scratch rebuild; the extraction and embedding caches
(.cache/, keyed by chunk hash) keep that from re-paying Groq/HF for chunks
that haven't changed.

Only one job runs at a time — they all write the same data/processed/.
That directory is backed up before the first step and restored if any step
(or the final reload) fails, so a failed job never leaves the API, or its
next restart, serving half-rebuilt artifacts. On success the backup is
kept as data/processed.prev (replacing any older one) rather than deleted,
since a "successful" rebuild can still produce a worse graph than the one
it replaced (e.g. extract_limit picking different chunks). Jobs live in
memory only: a server restart forgets them.
"""

import os
import shutil
import subprocess
import sys
import threading
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from .resources import DEFAULT_PROCESSED_DIR, REPO_ROOT, Resources

LOG_TAIL_LINES = 200

# (argv, on_line) -> exit code. Swappable so tests never spawn real scripts.
StepRunner = Callable[[list[str], Callable[[str], None]], int]


class IngestRequest(BaseModel):
    tickers: list[str] | None = Field(default=None, description="ticker subset; default is every company in config/companies.yaml")
    skip_fetch: bool = Field(default=False, description="rebuild from already-downloaded data/raw/ instead of re-fetching")
    max_per_form: int = Field(default=2, ge=1, le=10)
    limit_per_company: int = Field(default=4, ge=1, le=20)
    extract_limit: int | None = Field(default=None, ge=1, description="max chunks to extract triples from (cost control)")


def build_steps(req: IngestRequest) -> list[tuple[str, list[str]]]:
    """(step name, script argv) for each pipeline stage this request runs, in order."""
    tickers = ["--tickers", ",".join(t.strip().upper() for t in req.tickers)] if req.tickers else []
    extract_limit = ["--limit", str(req.extract_limit)] if req.extract_limit else []

    steps = []
    if not req.skip_fetch:
        steps += [
            ("fetch_filings", ["scripts/fetch_edgar_filings.py", *tickers, "--max-per-form", str(req.max_per_form)]),
            ("fetch_transcripts", ["scripts/fetch_transcripts.py", *tickers, "--limit-per-company", str(req.limit_per_company)]),
        ]
    steps += [
        ("build_chunks", ["scripts/build_chunks.py", *tickers]),
        ("extract_triples", ["scripts/extract_triples.py", *tickers, *extract_limit]),
        ("resolve_entities", ["scripts/resolve_entities.py"]),
        ("build_graph", ["scripts/build_graph.py"]),
        ("build_index", ["scripts/build_index.py", *tickers]),
    ]
    return steps


def run_script(argv: list[str], on_line: Callable[[str], None]) -> int:
    """Run one repo script with this interpreter, streaming its combined stdout/stderr line by line."""
    proc = subprocess.Popen(
        [sys.executable, "-u", *argv],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    for line in proc.stdout:
        on_line(line.rstrip("\n"))
    return proc.wait()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class IngestJob:
    job_id: str
    params: dict
    steps: list[dict]
    status: str = "queued"  # queued | running | succeeded | failed
    error: str | None = None
    created_at: str = field(default_factory=_now)
    finished_at: str | None = None
    log_tail: deque = field(default_factory=lambda: deque(maxlen=LOG_TAIL_LINES))

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "error": self.error,
            "params": self.params,
            "steps": self.steps,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "log_tail": list(self.log_tail),
        }


class IngestInProgressError(Exception):
    def __init__(self, job_id: str):
        super().__init__(f"ingest job {job_id} is already running")
        self.job_id = job_id


class IngestManager:
    def __init__(
        self,
        loader: Callable[[], Resources],
        *,
        processed_dir: Path = DEFAULT_PROCESSED_DIR,
        run_step: StepRunner = run_script,
        log_dir: Path | None = REPO_ROOT / "logs",
    ):
        self._loader = loader
        self._processed_dir = processed_dir
        self._run_step = run_step
        self._log_dir = log_dir
        self._jobs: dict[str, IngestJob] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()
        self._active_job_id: str | None = None

    def start(self, req: IngestRequest, on_reloaded: Callable[[Resources], None]) -> IngestJob:
        """Queue a job and start it on a background thread; raises IngestInProgressError if one is running."""
        with self._lock:
            if self._active_job_id is not None:
                raise IngestInProgressError(self._active_job_id)
            steps = build_steps(req)
            job = IngestJob(
                job_id=uuid.uuid4().hex[:12],
                params=req.model_dump(),
                steps=[{"name": name, "status": "pending", "returncode": None} for name, _ in steps],
            )
            self._jobs[job.job_id] = job
            self._active_job_id = job.job_id
            thread = threading.Thread(target=self._run, args=(job, steps, on_reloaded), daemon=True)
            self._threads[job.job_id] = thread
        thread.start()
        return job

    def get(self, job_id: str) -> IngestJob | None:
        return self._jobs.get(job_id)

    def all_jobs(self) -> list[IngestJob]:
        return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def wait(self, job_id: str, timeout: float | None = None) -> None:
        thread = self._threads.get(job_id)
        if thread is not None:
            thread.join(timeout)

    def _run(self, job: IngestJob, steps: list[tuple[str, list[str]]], on_reloaded: Callable[[Resources], None]) -> None:
        job.status = "running"
        backup_dir = self._processed_dir.with_name(f"{self._processed_dir.name}.bak-{job.job_id}")
        log_file = None
        try:
            if self._log_dir is not None:
                self._log_dir.mkdir(parents=True, exist_ok=True)
                log_file = (self._log_dir / f"ingest-{job.job_id}.log").open("w", encoding="utf-8")

            def log(line: str) -> None:
                job.log_tail.append(line)
                if log_file is not None:
                    log_file.write(line + "\n")
                    log_file.flush()

            if self._processed_dir.exists():
                shutil.copytree(self._processed_dir, backup_dir)

            for step, (name, argv) in zip(job.steps, steps):
                step["status"] = "running"
                step["started_at"] = _now()
                log(f"=== {name}: {' '.join(argv)}")
                returncode = self._run_step(argv, log)
                step["returncode"] = returncode
                step["finished_at"] = _now()
                if returncode != 0:
                    step["status"] = "failed"
                    raise RuntimeError(f"step {name} exited with code {returncode}")
                step["status"] = "succeeded"

            log("=== reloading API resources")
            on_reloaded(self._loader())
            job.status = "succeeded"
            self._keep_as_previous(backup_dir)
        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            job.log_tail.append(f"!!! {e}")
            for step in job.steps:
                if step["status"] == "running":
                    step["status"] = "failed"
            self._restore(backup_dir)
        finally:
            job.finished_at = _now()
            if log_file is not None:
                log_file.close()
            with self._lock:
                self._active_job_id = None

    def _keep_as_previous(self, backup_dir: Path) -> None:
        if not backup_dir.exists():
            return
        previous_dir = self._processed_dir.with_name(f"{self._processed_dir.name}.prev")
        shutil.rmtree(previous_dir, ignore_errors=True)
        backup_dir.rename(previous_dir)

    def _restore(self, backup_dir: Path) -> None:
        if not backup_dir.exists():
            return
        shutil.rmtree(self._processed_dir, ignore_errors=True)
        backup_dir.rename(self._processed_dir)
