"""The same checks run against BOTH job stores, so swapping one for the other is proven safe.

The Postgres checks need a database. Point TEST_DATABASE_URL at an EMPTY TEST database, e.g.
    export TEST_DATABASE_URL="postgresql+psycopg://data_engine:PASSWORD@127.0.0.1:5433/data_engine_test"
Without it those tests are reported as skipped (not passed). The tests DROP the jobs table,
so a database whose name does not end in "_test" is refused.
"""
import os
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from data_engine.api import create_app
from data_engine.jobs import JobStore, now_iso
from data_engine.pg_jobs import Base, PostgresJobStore
from tests.test_baseline import HEADER, ROWS

TEST_URL = os.environ.get("TEST_DATABASE_URL")
needs_postgres = pytest.mark.skipif(not TEST_URL, reason="TEST_DATABASE_URL is not set")


def check_test_database_url(url):
    name = make_url(url).database or ""
    if not name.endswith("_test"):
        raise RuntimeError(f"refusing to wipe database {name!r}: its name must end in '_test'")


def fresh_postgres_store():
    check_test_database_url(TEST_URL)
    store = PostgresJobStore(TEST_URL)
    Base.metadata.drop_all(store._engine)
    store.init_schema()
    return store


@pytest.fixture(params=["memory", pytest.param("postgres", marks=needs_postgres)])
def store(request):
    if request.param == "memory":
        yield JobStore()
        return
    s = fresh_postgres_store()
    yield s
    s.dispose()


# ---- checks that must hold for both stores ----------------------------------------------

def test_create_returns_a_queued_job(store):
    job = store.create({"file": "trips.csv", "strategy": "chunked", "chunksize": 3})
    assert len(job["id"]) == 32
    assert job["status"] == "queued"
    assert job["params"] == {"file": "trips.csv", "strategy": "chunked", "chunksize": 3}
    datetime.fromisoformat(job["created_at"])  # a valid ISO timestamp
    assert job["finished_at"] is None and job["seconds"] is None
    assert job["error"] is None and job["result"] is None


def test_get_returns_what_was_created_and_none_for_unknown(store):
    job = store.create({"file": "a.csv"})
    assert store.get(job["id"]) == job
    assert store.get("doesnotexist") is None


def test_update_changes_only_the_given_fields(store):
    job = store.create({"file": "a.csv"})
    finished = now_iso()
    store.update(job["id"], status="succeeded", seconds=0.25, finished_at=finished)
    got = store.get(job["id"])
    assert got["status"] == "succeeded"
    assert got["seconds"] == 0.25
    assert got["finished_at"] == finished
    assert got["params"] == job["params"] and got["created_at"] == job["created_at"]
    assert got["error"] is None


def test_results_come_back_exactly(store):
    job = store.create({"file": "a.csv"})
    result = {
        "counts": {"rows_read": 12, "rows_used": 5},
        "groups": [{"member_casual": "casual", "count": 2, "sum_duration": 6978862.1899999995,
                    "avg_duration": 820.1741908567399}],
    }
    store.update(job["id"], status="succeeded", result=result)
    assert store.get(job["id"])["result"] == result


def test_update_of_an_unknown_job_raises_keyerror(store):
    with pytest.raises(KeyError):
        store.update("doesnotexist", status="running")


def test_changing_a_returned_record_does_not_change_the_store(store):
    job = store.create({"file": "a.csv"})
    job["status"] = "hacked"
    assert store.get(job["id"])["status"] == "queued"

# ---- Postgres-only checks ---------------------------------------------------------------

@needs_postgres
def test_unknown_field_names_are_rejected():
    s = fresh_postgres_store()
    job = s.create({"file": "a.csv"})
    with pytest.raises(ValueError):
        s.update(job["id"], statsu="running")  # a typo must not be silently ignored
    s.dispose()

@needs_postgres
def test_a_job_survives_a_new_store_on_the_same_database():
    first = fresh_postgres_store()
    job = first.create({"file": "a.csv"})
    first.update(job["id"], status="failed", error="ValueError")
    first.dispose()
    second = PostgresJobStore(TEST_URL)  # like a restarted server: new connections, same database
    got = second.get(job["id"])
    assert got["status"] == "failed" and got["error"] == "ValueError"
    second.dispose()


@needs_postgres
def test_api_jobs_survive_a_server_restart(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "trips.csv").write_text(HEADER + "\n".join(ROWS) + "\n")
    first = fresh_postgres_store()
    client = TestClient(create_app(data, first, benchmarks_dir=tmp_path / "b"))
    job_id = client.post("/jobs", json={"file": "trips.csv", "chunksize": 3}).json()["id"]
    results_before = client.get(f"/jobs/{job_id}/results").json()
    status_before = client.get(f"/jobs/{job_id}").json()
    first.dispose()

    second = PostgresJobStore(TEST_URL)  # "restart": a brand-new app and store
    client = TestClient(create_app(data, second, benchmarks_dir=tmp_path / "b"))
    assert client.get(f"/jobs/{job_id}").json() == status_before
    assert client.get(f"/jobs/{job_id}/results").json() == results_before
    assert results_before["counts"]["rows_read"] == 12
    second.dispose()


# ---- the safety rail itself (no database needed) ----------------------------------------

def test_the_test_helper_refuses_a_database_not_named_test():
    with pytest.raises(RuntimeError):
        check_test_database_url("postgresql+psycopg://u:p@127.0.0.1:5433/data_engine")
    check_test_database_url("postgresql+psycopg://u:p@127.0.0.1:5433/data_engine_test")  # accepted