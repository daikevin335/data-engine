import pandas as pd

COLUMNS = ["ride_id", "rideable_type", "started_at", "ended_at", "member_casual"]

def add_duration(df):
    counts = {"rows_read": len(df)}

    before = len(df)
    df = df.dropna(subset = COLUMNS)
    counts["dropped_missing"] = before - len(df)

    started = pd.to_datetime(df["started_at"], errors = "coerce", format = "ISO8601") # errors="coerce" turns unparsable value into missing value (NaT) instead of crashing  
    ended = pd.to_datetime(df["ended_at"], errors = "coerce", format = "ISO8601")
    ok = started.notna() & ended.notna() # true/false mark of rows where both timestamps parsed 
    counts["dropped_unparseable"] = int((~ok).sum())
    df = df.loc[ok].copy()

    df["duration_seconds"] = (ended[ok] - started[ok]).dt.total_seconds()

    before = len(df)
    df = df[df["duration_seconds"] > 0]
    counts["dropped_nonpositive_duration"] = before - len(df)

    return df, counts 