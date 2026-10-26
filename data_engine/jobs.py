"""Job records and where they are kept.

This is an in-memory store: simple, fast, and lost when the server restarts.
The API only talks to the small interface below (create / get / update), so a
PostgreSQL-backed store can replace it later without touching the endpoints.
"""
import threading
import uuid
from datetime import datetime, timezone


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobStore:
    def __init__(self):
        self._jobs = {}
        # Jobs run in background threads while requests read them,
        # so every access goes through one lock.
        self._lock = threading.Lock()

    def create(self, params):
        job = {
            "id": uuid.uuid4().hex,
            "status": "queued",        # queued -> running -> succeeded | failed
            "params": params,
            "created_at": now_iso(),
            "finished_at": None,
            "seconds": None,
            "error": None,
            "result": None,
        }
        with self._lock:
            self._jobs[job["id"]] = job
            return dict(job)

    def get(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def update(self, job_id, **fields):
        with self._lock:
            self._jobs[job_id].update(fields)