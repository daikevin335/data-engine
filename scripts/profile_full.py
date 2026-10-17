import sys
import pandas as pd

path = sys.argv[1]
cols = ["ride_id", "rideable_type", "started_at", "ended_at", "member_casual"]
df = pd.read_csv(path, usecols=cols)

print("rows:", len(df))
print("in-memory size (MB):", round(df.memory_usage(deep=True).sum() / 1e6, 1))
print("missing:\n", df.isna().sum())
print("duplicate ride_id (whole file):", df["ride_id"].duplicated().sum())
print("rideable_type:", df["rideable_type"].value_counts(dropna=False).to_dict())
print("member_casual:", df["member_casual"].value_counts(dropna=False).to_dict())

start = pd.to_datetime(df["started_at"], errors="coerce")
end = pd.to_datetime(df["ended_at"], errors="coerce")
dur = (end - start).dt.total_seconds()
print("unparseable:", start.isna().sum(), end.isna().sum())
print("duration <= 0:", (dur <= 0).sum())
print("duration > 24h:", (dur > 86400).sum())
print(dur.describe())