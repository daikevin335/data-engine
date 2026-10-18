import csv
import sys
from datetime import datetime

count, total = 0, 0.0
seen = set()
with open(sys.argv[1], newline="") as f:
    for row in csv.DictReader(f):
        if row["ride_id"] in seen:
            continue
        seen.add(row["ride_id"])
        start = datetime.fromisoformat(row["started_at"])
        end = datetime.fromisoformat(row["ended_at"])
        d = (end - start).total_seconds()
        if 60 <= d <= 3600 and row["member_casual"] == "casual" and row["rideable_type"] == "classic_bike":
            count += 1
            total += d

print(count, round(total), round(total / count, 6))