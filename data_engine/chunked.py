import pandas as pd

from data_engine.cleaning import COLUMNS, add_duration

GROUP_COLS = ["member_casual", "rideable_type"]


def run_chunked(path, min_duration=60, max_duration=3600, chunksize=100_000):
    totals = {}  # (member_casual, rideable_type) -> [count, sum_duration]
    seen = set()  # every ride_id kept so far, to catch duplicates across chunks
    counts = {
        "rows_read": 0,
        "dropped_missing": 0,
        "dropped_unparseable": 0,
        "dropped_nonpositive_duration": 0,
        "dropped_duplicate": 0,
        "dropped_by_filter": 0,
        "rows_used": 0,
    }

    for chunk in pd.read_csv(path, usecols = COLUMNS, chunksize = chunksize):
        chunk, chunk_counts = add_duration(chunk)
        for key, value in chunk_counts.items():
            counts[key] += value

        before = len(chunk)
        chunk = chunk.drop_duplicates(subset = "ride_id", keep = "first")  # repeats inside this chunk
        chunk = chunk[~chunk["ride_id"].isin(seen)]                    # repeats of earlier chunks
        seen.update(chunk["ride_id"])
        counts["dropped_duplicate"] += before - len(chunk)

        before = len(chunk)
        chunk = chunk[(chunk["duration_seconds"] >= min_duration) & (chunk["duration_seconds"] <= max_duration)]
        counts["dropped_by_filter"] += before - len(chunk)

        partial = chunk.groupby(GROUP_COLS)["duration_seconds"].agg(count = "count", total = "sum")
        for key, row in partial.iterrows():
            running = totals.setdefault(key, [0, 0.0])
            running[0] += int(row["count"])
            running[1] += float(row["total"])

    rows = [
        {"member_casual": m, "rideable_type": r, "count": n, "sum_duration": s, "avg_duration": s / n}
        for (m, r), (n, s) in sorted(totals.items())
    ]
    result = pd.DataFrame(rows, columns=GROUP_COLS + ["count", "sum_duration", "avg_duration"])
    counts["rows_used"] = int(result["count"].sum()) if len(result) else 0
    return result, counts