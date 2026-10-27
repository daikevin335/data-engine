"""REST API for submitting and inspecting processing jobs.

Run from the repository root:
    uvicorn data_engine.api:build_app --factory --reload
Interactive docs appear at http://127.0.0.1:8000/docs
"""
import json
import logging
import os
import time
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, Field

from data_engine.baseline import run_baseline
from data_engine.chunked import run_chunked
from data_engine.jobs import JobStore, now_iso

log = logging.getLogger(__name__)


class JobRequest(BaseModel):
    # A file NAME inside the data directory, e.g. "JC-202609-citibike-tripdata.csv".
    file: str
    strategy: Literal["baseline", "chunked"] = "chunked"
    chunksize: int = Field(50_000, ge=1, le=10_000_000)


def resolve_data_file(data_dir, name):
    """Turn a client-supplied file name into a safe path, or raise an HTTP error.

    The client must never be able to read files outside the data directory,
    so ".." and absolute paths are rejected, and so are links that point out of it.
    """
    path = (data_dir / name).resolve()  # resolve() follows ".." and symlinks
    if data_dir not in path.parents or path.suffix.lower() != ".csv":
        raise HTTPException(400, "file must be a .csv inside the data directory")
    if not path.is_file():
        raise HTTPException(404, "file not found in the data directory")
    return path


def load_benchmark_reports(benchmarks_dir):
    """Summaries of the saved benchmark reports (the JSON files benchmark.py writes).

    The raw per-run data is left out: it is large and holds full job outputs.
    A file that is not a valid report is skipped and logged, not allowed to break the endpoint.
    """
    reports = []
    if not benchmarks_dir.is_dir():
        return reports
    for path in benchmarks_dir.glob("*.json"):
        try:
            raw = json.loads(path.read_text())
            reports.append({
                "name": path.stem,
                "file": raw["file"],
                "file_size_mb": raw["file_size_mb"],
                "chunksize": raw["chunksize"],
                "trials": raw["trials"],
                "outputs_equivalent": raw["outputs_equivalent"],
                "environment": raw["environment"],
                "summary": raw["summary"],
            })
        except (OSError, ValueError, KeyError, TypeError):
            log.warning("skipping unreadable benchmark file %s", path.name)
    reports.sort(key=lambda r: (r["file_size_mb"], r["chunksize"], r["name"]))
    return reports


def run_job(store, job_id, path, strategy, chunksize):
    """Runs in the background, after the HTTP response has already been sent."""
    store.update(job_id, status="running")
    start = time.perf_counter()
    try:
        if strategy == "baseline":
            result, counts = run_baseline(path)
        else:
            result, counts = run_chunked(path, chunksize=chunksize)
    except Exception as exc:
        # Full detail goes to the server log. The client gets only the error type,
        # because messages can contain server file paths.
        log.exception("job %s failed", job_id)
        store.update(job_id, status="failed", error=type(exc).__name__,
                     seconds=time.perf_counter() - start, finished_at=now_iso())
        return
    store.update(
        job_id,
        status="succeeded",
        result={"counts": counts, "groups": result.to_dict("records")},
        seconds=time.perf_counter() - start,
        finished_at=now_iso(),
    )


def create_app(data_dir, store=None, benchmarks_dir="benchmarks"):
    """Build the app. Taking the folders and the store as arguments lets tests use their own."""
    data_dir = Path(data_dir).resolve()
    benchmarks_dir = Path(benchmarks_dir).resolve()
    store = store or JobStore()
    app = FastAPI(title="data-engine")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/benchmark")
    def benchmark():
        # Serves MEASURED results saved earlier. It does not run a benchmark: that takes
        # minutes, and measuring while the server handles other requests would skew it.
        # The folder is fixed on the server, so the client chooses nothing here.
        return {"reports": load_benchmark_reports(benchmarks_dir)}

    @app.post("/jobs", status_code=202)
    def submit_job(request: JobRequest, background: BackgroundTasks):
        path = resolve_data_file(data_dir, request.file)
        job = store.create(request.model_dump())
        background.add_task(run_job, store, job["id"], path, request.strategy, request.chunksize)
        return {"id": job["id"], "status": job["status"]}

    @app.get("/jobs/{job_id}")
    def job_status(job_id: str):
        job = store.get(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        return {k: v for k, v in job.items() if k != "result"}

    @app.get("/jobs/{job_id}/results")
    def job_results(job_id: str):
        job = store.get(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        if job["status"] != "succeeded":
            raise HTTPException(409, f"job is {job['status']}, results are not available")
        return job["result"]

    return app


def store_from_env():
    """PostgreSQL if DATABASE_URL is set, otherwise the in-memory store."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        log.warning("DATABASE_URL is not set: using the in-memory job store (jobs are lost on restart)")
        return JobStore()
    from data_engine.pg_jobs import PostgresJobStore  # imported here: memory-only use needs no database library

    store = PostgresJobStore(url)
    store.init_schema()
    return store


def build_app():
    """The app uvicorn runs. A function, not a module-level variable, so that merely
    importing this module (as the tests do) never opens a database connection."""
    return create_app(
        os.environ.get("DATA_ENGINE_DATA_DIR", "data"),
        store=store_from_env(),
        benchmarks_dir=os.environ.get("DATA_ENGINE_BENCHMARKS_DIR", "benchmarks"),
    )