"""Benchmark procedure for the baseline and chunked strategies.

Each measured run happens in a FRESH Python process, so that:
  * peak memory (the process's high-water mark) belongs to that run only, and
  * one run cannot leave memory or caches behind that help the next one.

Usage, from the repository root:
    python -m data_engine.benchmark run data/some_file.csv --trials 5
"""
import argparse
import json
import math
import os
import platform
import resource
import statistics
import subprocess
import sys
import time
from pathlib import Path

STRATEGIES = ("baseline", "chunked")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _peak_rss_mb():
    """Peak resident memory of this process so far, in MB (1 MB = 1,000,000 bytes)."""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes; Linux reports kibibytes (1024 bytes).
    peak_bytes = peak if sys.platform == "darwin" else peak * 1024
    return peak_bytes / 1e6


def outputs_equivalent(a, b, rel_tol=1e-9):
    """Do two runs' outputs agree? Counts and group names must match EXACTLY.
    Float columns need only match to within rel_tol, because adding the same numbers
    in a different order (one pass vs. chunk by chunk) can change the last bit."""
    if a["counts"] != b["counts"] or len(a["result"]) != len(b["result"]):
        return False
    for ra, rb in zip(a["result"], b["result"]):
        if (ra["member_casual"], ra["rideable_type"], ra["count"]) != (rb["member_casual"], rb["rideable_type"], rb["count"]):
            return False
        for col in ("sum_duration", "avg_duration"):
            if not math.isclose(ra[col], rb[col], rel_tol=rel_tol):
                return False
    return True


def measure_one(strategy, path, chunksize):
    """Run one strategy once IN THIS PROCESS and return its measurements."""
    # Import everything first, so import cost and library memory are not
    # counted as part of the strategy's own work.
    from data_engine.baseline import run_baseline
    from data_engine.chunked import run_chunked

    rss_before = _peak_rss_mb()
    start = time.perf_counter()
    if strategy == "baseline":
        result, counts = run_baseline(path)
    else:
        result, counts = run_chunked(path, chunksize=chunksize)
    seconds = time.perf_counter() - start
    rss_after = _peak_rss_mb()

    return {
        "strategy": strategy,
        "seconds": seconds,
        "rows_read": counts["rows_read"],
        "rows_used": counts["rows_used"],
        "peak_rss_mb": rss_after,
        "extra_rss_mb": max(rss_after - rss_before, 0.0),
        "counts": counts,
        "result": result.to_dict("records"),
    }


def _run_in_fresh_process(strategy, path, chunksize):
    cmd = [sys.executable, "-m", "data_engine.benchmark", "worker", strategy, str(path), str(chunksize)]
    done = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
    if done.returncode != 0:
        # Show the worker's own error. Without this, all you see is "exit status 1".
        raise RuntimeError(f"The {strategy} worker crashed. Its error output was:\n{done.stderr}")
    return json.loads(done.stdout)


def summarize(runs):
    """Median (and spread) of a list of runs of ONE strategy."""
    seconds = [r["seconds"] for r in runs]
    median_seconds = statistics.median(seconds)
    return {
        "trials": len(runs),
        "median_seconds": median_seconds,
        "min_seconds": min(seconds),
        "max_seconds": max(seconds),
        "median_rows_per_second": runs[0]["rows_read"] / median_seconds,
        "median_extra_rss_mb": statistics.median(r["extra_rss_mb"] for r in runs),
        "median_peak_rss_mb": statistics.median(r["peak_rss_mb"] for r in runs),
    }


def environment():
    import pandas

    return {
        "python": platform.python_version(),
        "pandas": pandas.__version__,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
    }


def run_benchmark(path, trials=5, chunksize=100_000, warmup=1):
    path = Path(path).resolve()
    runs = {s: [] for s in STRATEGIES}

    # Warm-up runs are thrown away. The first read of a file comes from disk;
    # later reads come from the operating system's cache, and we want every
    # measured run to start in the same state.
    for _ in range(warmup):
        for s in STRATEGIES:
            _run_in_fresh_process(s, path, chunksize)

    for t in range(trials):
        # Alternate which strategy goes first so neither always runs "cold" or "hot".
        order = STRATEGIES if t % 2 == 0 else tuple(reversed(STRATEGIES))
        for s in order:
            runs[s].append(_run_in_fresh_process(s, path, chunksize))

    summary = {s: summarize(runs[s]) for s in STRATEGIES}
    reference = runs["baseline"][0]
    identical = all(outputs_equivalent(reference, r) for s in STRATEGIES for r in runs[s])
    return {
        "file": path.name,
        "file_size_mb": round(path.stat().st_size / 1e6, 1),
        "chunksize": chunksize,
        "trials": trials,
        "warmup_runs": warmup,
        "environment": environment(),
        "outputs_equivalent": identical,
        "summary": summary,
        "raw_runs": runs,
    }


def format_report(report):
    lines = [
        f"File: {report['file']} ({report['file_size_mb']} MB), chunksize {report['chunksize']}, "
        f"{report['trials']} trials (+{report['warmup_runs']} warm-up)",
        f"Outputs equivalent across all runs: {report['outputs_equivalent']}",
        "",
        f"{'strategy':<10}{'median s':>10}{'min s':>9}{'max s':>9}{'rows/s':>12}{'extra MB':>10}{'peak MB':>9}",
    ]
    for s in STRATEGIES:
        m = report["summary"][s]
        lines.append(
            f"{s:<10}{m['median_seconds']:>10.3f}{m['min_seconds']:>9.3f}{m['max_seconds']:>9.3f}"
            f"{m['median_rows_per_second']:>12,.0f}{m['median_extra_rss_mb']:>10.1f}{m['median_peak_rss_mb']:>9.1f}"
        )
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="benchmark both strategies on a CSV")
    run.add_argument("path")
    run.add_argument("--trials", type=int, default=5)
    run.add_argument("--chunksize", type=int, default=100_000)
    run.add_argument("--out", help="also save the full report as JSON to this path")

    worker = sub.add_parser("worker", help="(internal) measure one run and print JSON")
    worker.add_argument("strategy", choices=STRATEGIES)
    worker.add_argument("path")
    worker.add_argument("chunksize", type=int)

    args = parser.parse_args(argv)
    if args.command == "worker":
        print(json.dumps(measure_one(args.strategy, args.path, args.chunksize)))
        return

    report = run_benchmark(args.path, trials=args.trials, chunksize=args.chunksize)
    print(format_report(report))
    print("\nEnvironment:", report["environment"])
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, indent=2))
        print("Saved:", args.out)


if __name__ == "__main__":
    main()