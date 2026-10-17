import sys 
import pandas as pd 

path = sys.argv[1]
df = pd.read_csv(path, nrows=100_000)

print(df.dtypes)
print(df.head(3).T)
print("\nMissing values per column:")
print(df.isna().sum())
print("\nDuplicate ride_id count:", df["ride_id"].duplicated().sum())
print("\nrideable_type values:", df["rideable_type"].value_counts(dropna=False).to_dict())
print("member_casual values:", df["member_casual"].value_counts(dropna=False).to_dict())

start = pd.to_datetime(df["started_at"], errors="coerce")
end = pd.to_datetime(df["ended_at"], errors="coerce")
dur = (end - start).dt.total_seconds()
print("\nUnparseable timestamps:", start.isna().sum(), end.isna().sum())
print("Duration seconds (describe):")
print(dur.describe())
print("Negative durations:", (dur < 0).sum())