import pytest

from data_engine.benchmark import STRATEGIES, outputs_equivalent, run_benchmark, summarize
from tests.test_baseline import HEADER, ROWS


def _run(seconds, extra):
    return {"seconds": seconds, "rows_read": 1000, "extra_rss_mb": extra, "peak_rss_mb": extra + 100}


def _out(sum_duration=3600.0, count=3, counts=None):
    return {
        "counts": counts or {"rows_read": 12, "rows_used": 5},
        "result": [{
            "member_casual": "member", "rideable_type": "classic_bike",
            "count": count, "sum_duration": sum_duration, "avg_duration": sum_duration / count,
        }],
    }


def test_summarize_uses_median_not_mean():
    # One slow outlier (e.g. something else using the CPU). Median ignores it, mean would not.
    s = summarize([_run(1.0, 10), _run(1.1, 12), _run(9.0, 50)])
    assert s["median_seconds"] == pytest.approx(1.1)
    assert s["median_extra_rss_mb"] == pytest.approx(12)
    assert s["max_seconds"] == pytest.approx(9.0)


def test_throughput_is_rows_over_median_seconds():
    s = summarize([_run(2.0, 1), _run(4.0, 1), _run(10.0, 1)])
    assert s["median_rows_per_second"] == pytest.approx(1000 / 4.0)


def test_equivalence_tolerates_last_bit_float_difference():
    # Real example seen in benchmarking: 201545136.138 vs 201545136.13799998.
    assert outputs_equivalent(_out(201545136.138), _out(201545136.13799998))


def test_equivalence_rejects_a_real_difference():
    assert not outputs_equivalent(_out(3600.0), _out(3600.5))          # sum differs
    assert not outputs_equivalent(_out(count=3), _out(count=4))        # count differs
    assert not outputs_equivalent(_out(), _out(counts={"rows_read": 12, "rows_used": 6}))  # drop counts differ


def test_worker_crash_shows_the_real_error(tmp_path):
    with pytest.raises(RuntimeError, match="FileNotFoundError"):
        run_benchmark(tmp_path / "does_not_exist.csv", trials=1, warmup=0)


def test_benchmark_end_to_end_on_tiny_file(tmp_path):
    p = tmp_path / "trips.csv"
    p.write_text(HEADER + "\n".join(ROWS) + "\n")
    report = run_benchmark(p, trials=2, chunksize=3, warmup=0)
    assert report["outputs_equivalent"] is True
    for s in STRATEGIES:
        assert report["summary"][s]["trials"] == 2
        assert report["summary"][s]["median_seconds"] > 0
        assert len(report["raw_runs"][s]) == 2
    assert report["raw_runs"]["baseline"][0]["rows_read"] == 12