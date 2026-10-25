import pandas as pd

from data_engine.cleaning import COLUMNS, add_duration


def run_baseline(path, min_duration = 60, max_duration = 3600):
    df = pd.read_csv(path, usecols = COLUMNS) # load only the 5 cols needed 
    df, counts = add_duration(df)

    # remove dupes 
    before = len(df)
    df = df.drop_duplicates(subset = "ride_id", keep = "first")
    counts["dropped_duplicate"] = before - len(df)

    # duration filter 
    before = len(df)
    df = df[(df["duration_seconds"] >= min_duration) & (df["duration_seconds"] <= max_duration)]
    counts["dropped_by_filter"] = before - len(df)

    # group and aggregate 
    grouped = df.groupby(["member_casual", "rideable_type"])["duration_seconds"].agg(
        count = "count", sum_duration = "sum"
    )
    # avg duration ii
    grouped["avg_duration"] = grouped["sum_duration"] / grouped["count"]
    counts["rows_used"] = int(grouped["count"].sum())

    return grouped.reset_index(), counts