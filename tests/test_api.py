import json

import pytest
from fastapi.testclient import TestClient

from data_engine.api import create_app
from data_engine.benchmark import outputs_equivalent, run_benchmark
from data_engine.jobs import JobStore
from tests.test_baseline import HEADER, ROWS


@pytest.fixture
def env(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "trips.csv").write_text(HEADER + "\n".join(ROWS) + "\n")
    (data_dir / "notes.txt").write_text("not a csv")
    (data_dir / "bad.csv").write_text("a,b\n1,2\n")  # missing the columns the engine needs
    (tmp_path / "secret.csv").write_text(HEADER + "\n".join(ROWS) + "\n")  # OUTSIDE the data dir
    store = JobStore()
    client = TestClient(create_app(data_dir, store))
    return client, store, tmp_path


def submit(client, **body):
    return client.post("/jobs", json=body)


def test_health(env):
    client, _, _ = env
    assert client.get("/health").json() == {"status": "ok"}


def test_submit_then_fetch_results(env):
    client, _, _ = env
    r = submit(client, file="trips.csv", strategy="chunked", chunksize=3)
    assert r.status_code == 202
    job_id = r.json()["id"]
    # TestClient finishes background tasks before returning, so the job is already done.
    status = client.get(f"/jobs/{job_id}").json()
    assert status["status"] == "succeeded"
    assert "result" not in status  # the status endpoint stays small
    results = client.get(f"/jobs/{job_id}/results").json()
    assert results["counts"]["rows_read"] == 12
    assert results["counts"]["rows_used"] == 5
    assert sum(g["count"] for g in results["groups"]) == 5


def test_both_strategies_give_the_same_answer_through_the_api(env):
    client, _, _ = env
    out = {}
    for strategy in ("baseline", "chunked"):
        job_id = submit(client, file="trips.csv", strategy=strategy, chunksize=3).json()["id"]
        res = client.get(f"/jobs/{job_id}/results").json()
        out[strategy] = {"counts": res["counts"], "result": res["groups"]}
    assert outputs_equivalent(out["baseline"], out["chunked"])


@pytest.mark.parametrize("name", ["../secret.csv", "sub/../../secret.csv"])
def test_path_traversal_is_rejected(env, name):
    client, store, tmp_path = env
    assert (tmp_path / "secret.csv").exists()  # the attack WOULD work if unguarded
    r = submit(client, file=name)
    assert r.status_code == 400
    assert store._jobs == {}  # no job was even created


def test_absolute_path_is_rejected(env):
    client, _, tmp_path = env
    r = submit(client, file=str(tmp_path / "secret.csv"))
    assert r.status_code == 400


def test_symlink_pointing_outside_is_rejected(env):
    client, _, tmp_path = env
    (tmp_path / "data" / "link.csv").symlink_to(tmp_path / "secret.csv")
    assert submit(client, file="link.csv").status_code == 400


def test_non_csv_is_rejected(env):
    client, _, _ = env
    assert submit(client, file="notes.txt").status_code == 400


def test_missing_file_is_404(env):
    client, _, _ = env
    assert submit(client, file="nope.csv").status_code == 404


@pytest.mark.parametrize("body", [
    {"file": "trips.csv", "strategy": "fastest"},
    {"file": "trips.csv", "chunksize": 0},
    {"file": "trips.csv", "chunksize": -5},
    {},
])
def test_invalid_requests_are_422(env, body):
    client, _, _ = env
    assert submit(client, **body).status_code == 422


def test_unknown_job_is_404(env):
    client, _, _ = env
    assert client.get("/jobs/doesnotexist").status_code == 404
    assert client.get("/jobs/doesnotexist/results").status_code == 404


def test_failed_job_reports_the_error_type_but_not_server_paths(env):
    client, _, tmp_path = env
    job_id = submit(client, file="bad.csv").json()["id"]
    status = client.get(f"/jobs/{job_id}").json()
    assert status["status"] == "failed"
    assert status["error"] == "ValueError"
    assert str(tmp_path) not in json.dumps(status)
    assert client.get(f"/jobs/{job_id}/results").status_code == 409


def test_results_before_the_job_finishes_are_409(env):
    client, store, _ = env
    job = store.create({"file": "trips.csv"})  # stays "queued": nothing runs it
    r = client.get(f"/jobs/{job['id']}/results")
    assert r.status_code == 409
    assert "queued" in r.json()["detail"]


# ---- GET /benchmark -------------------------------------------------------------------

def make_report(file="a.csv", size=1.0, chunksize=100):
    return {
        "file": file, "file_size_mb": size, "chunksize": chunksize, "trials": 3, "warmup_runs": 1,
        "environment": {"python": "3.14.0"}, "outputs_equivalent": True,
        "summary": {"baseline": {"median_seconds": 1.0}, "chunked": {"median_seconds": 1.2}},
        "raw_runs": {"baseline": [{"result": "large raw data"}], "chunked": []},
    }


@pytest.fixture
def bench(tmp_path):
    bdir = tmp_path / "benchmarks"
    bdir.mkdir()
    return TestClient(create_app(tmp_path, benchmarks_dir=bdir)), bdir


def test_benchmark_lists_saved_reports_sorted_without_raw_data(bench):
    client, bdir = bench
    (bdir / "big.json").write_text(json.dumps(make_report("big.csv", size=900.0, chunksize=50_000)))
    (bdir / "small-b.json").write_text(json.dumps(make_report("small.csv", size=20.0, chunksize=500)))
    (bdir / "small-a.json").write_text(json.dumps(make_report("small.csv", size=20.0, chunksize=100)))
    reports = client.get("/benchmark").json()["reports"]
    assert [r["name"] for r in reports] == ["small-a", "small-b", "big"]  # size, then chunk size
    assert all("raw_runs" not in r for r in reports)
    assert reports[0]["summary"]["chunked"]["median_seconds"] == 1.2


def test_benchmark_with_no_folder_is_an_empty_list(tmp_path):
    client = TestClient(create_app(tmp_path, benchmarks_dir=tmp_path / "does_not_exist"))
    assert client.get("/benchmark").json() == {"reports": []}


def test_benchmark_skips_files_that_are_not_valid_reports(bench):
    client, bdir = bench
    (bdir / "good.json").write_text(json.dumps(make_report()))
    (bdir / "broken.json").write_text("{not json")
    (bdir / "a_list.json").write_text("[1, 2]")
    (bdir / "partial.json").write_text(json.dumps({"file": "x.csv"}))  # missing fields
    (bdir / "notes.txt").write_text("ignored: not .json")
    r = client.get("/benchmark")
    assert r.status_code == 200
    assert [x["name"] for x in r.json()["reports"]] == ["good"]


def test_benchmark_serves_a_report_written_by_the_real_benchmark_tool(bench, tmp_path):
    # Contract test: if benchmark.py's output format changes, this fails here.
    client, bdir = bench
    csv = tmp_path / "trips.csv"
    csv.write_text(HEADER + "\n".join(ROWS) + "\n")
    report = run_benchmark(csv, trials=1, warmup=0, chunksize=3)
    (bdir / "real.json").write_text(json.dumps(report))
    got = client.get("/benchmark").json()["reports"]
    assert len(got) == 1
    assert got[0]["outputs_equivalent"] is True
    assert got[0]["chunksize"] == 3
    assert set(got[0]["summary"]) == {"baseline", "chunked"}