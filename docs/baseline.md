# Milestone 2: Baseline implementation

The baseline strategy loads the whole CSV into memory and processes it in one pass. It implements the shared rules in [processing_rules.md](processing_rules.md), and it is the reference that the chunked implementation is compared against.

## Components

| File | Purpose |
| --- | --- |
| `data_engine/cleaning.py` | Rules 2-4: drop rows with missing fields, parse timestamps, compute `duration_seconds`, drop non-positive durations. Shared by both strategies. |
| `data_engine/baseline.py` | `run_baseline(path, min_duration, max_duration)`: read five columns, clean, drop repeated `ride_id`, apply the duration range, group by rider type and bike type, compute count and sum, derive the average. |
| `tests/test_baseline.py` | 12 hand-made rows with expected answers worked out on paper. |
| `scripts/run_baseline.py` | Runs the baseline on a real CSV from the command line. |

`run_baseline` returns a table with one row per (`member_casual`, `rideable_type`) group, with columns `count`, `sum_duration` and `avg_duration`, plus a dictionary counting the rows dropped by each rule.

## Design decisions

- **Shared cleaning module.** Both strategies call the same cleaning function, so they do equivalent work by construction.
- **Explicit ISO8601 timestamp parsing.** Without an explicit format, pandas guesses the format from the first value and silently turns valid rows in a different style (for example, no milliseconds) into missing values. With the explicit format removed in a test run, 9 of the 12 test rows were wrongly dropped as unparseable and three tests failed.
- **Duplicate order.** Repeated `ride_id` values are dropped after cleaning and before the duration filter, keeping the first occurrence in file order. The chunked implementation must follow the same order.
- **Count and sum, then derive the average.** Counts and sums combine correctly across chunks. Averages do not.

## Verification

Run the tests from the repository root:

```
python -m pytest -v
```

The four baseline tests passed on Python 3.14.0 with pandas 3.0.6.

### Real-data run: Jersey City, September 2026

Command: `PYTHONPATH=. python scripts/run_baseline.py data/JC-202609-citibike-tripdata.csv`

Rows read: 106,628. Rows used: 105,594. The duration filter (60 to 3,600 s) removed 1,034 rows, all of them trips over an hour. No rows were dropped as missing, unparseable, non-positive or duplicate.

| Rider | Bike | Trips | Average duration (s) |
| --- | --- | --- | --- |
| casual | classic | 8,509 | 820.2 |
| casual | electric | 18,616 | 581.8 |
| member | classic | 33,907 | 489.3 |
| member | electric | 44,562 | 444.4 |

The four counts sum to 105,594, which equals rows read minus rows filtered.

## Limitations

- Correctness on the real file has been checked for internal consistency only. An independent cross-check with the standard library is still to be run.
- No runtime or memory measurements have been made yet. Benchmarks come in a later milestone.
- Only the Jersey City file has been inspected. The much larger New York files may differ.