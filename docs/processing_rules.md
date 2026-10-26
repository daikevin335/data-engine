# Processing Rules

Both the baseline and chunked implementations must apply these rules identically.

Data source: Citi Bike trip history, https://citibikenyc.com/system-data
(not redistributed here; download it yourself into `data/`)

## Cleaning (in order)
1. Read only: ride_id, rideable_type, started_at, ended_at, member_casual.
2. Drop rows with a missing field or an unparseable timestamp; count them.
3. duration_seconds = ended_at - started_at.
4. Drop rows with duration_seconds <= 0; count them.
5. Drop repeated ride_id values, keeping the first in file order; count them.

## User-configurable operations
6. Filter: min_duration_seconds <= duration_seconds <= max_duration_seconds.
7. Group by member_casual and rideable_type.
8. Per group: COUNT, SUM of duration_seconds, AVG of duration_seconds
   (AVG = SUM / COUNT, computed once at the end).

## Observed in JC-202609 (Jersey City, 106,628 rows)
No missing values, duplicates, unparseable timestamps, or non-positive durations.
37 trips longer than 24 hours. Only the Jersey City file has been checked so far.
## Checked on New York data (202609)

- Part 1 (1,000,000 rows): no missing values, duplicate ride IDs, unparseable timestamps or non-positive durations; 166 trips over 24 hours.
- Whole month (all 5 parts joined, 4,982,855 rows): no missing values, no unparseable timestamps, no non-positive durations, and no duplicate ride IDs across parts. 46,814 rows (0.94%) fell outside the 60 to 3600 second range, leaving 4,936,041 rows used.
- Source: `benchmarks/nyc-5parts.json`. The duplicate-removal rule removed no rows on this data, so only the tests have exercised it.
