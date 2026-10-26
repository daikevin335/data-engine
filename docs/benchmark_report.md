# Benchmark report: baseline vs chunked

This report compares the two strategies on Citi Bike trip data from September 2026. Every number comes from a saved result in `benchmarks/`. Nothing here is estimated unless it says so.

## Summary

- Both strategies return the same answer on every file and every run (`Outputs equivalent: True`).
- On the whole New York month (4,982,855 rows, 972 MB), chunked used 67% less extra memory than the baseline (668.5 MB against 2,021.7 MB) and took 17% longer (8.00 s against 6.84 s), at 100,000 rows per chunk.
- The memory saving grows with file size: 47% at 1M rows, 57% at 2M, 67% at 4.98M. The time penalty shrinks: 29%, 21%, 17%.
- Chunk size matters much less than expected on large files. Memory differs by 18% between 10,000 and 250,000 rows per chunk, because most of chunked's memory is the set of seen ride IDs and not the chunk.
- The default chunk size is 50,000 rows, chosen from the whole-month sweep. It is nearly tied with 100,000 and 250,000, so this is a judgement call, not a clear winner.

## Method

- Each measured run happens in a **fresh Python process**, because peak memory is a high-water mark that never decreases within a process.
- Imports happen before measuring, so library memory is not counted. "Extra MB" is peak memory after the run minus peak memory before it. "Peak MB" is the total.
- One **warm-up round** is discarded, so every measured run reads the file from the operating system's cache.
- Runs **alternate** which strategy goes first.
- Reported time is the **median** of the trials. Throughput is rows read divided by that median.
- Memory units: macOS reports bytes and Linux reports KiB; the tool converts both and was checked against a known 300 MB allocation.
- The two strategies' outputs are compared on every run: counts and group names must match exactly, and sums and averages to a relative tolerance of 1e-9, because adding the same numbers in a different order can change the last bit.

**Environment:** Python 3.14.0, pandas 3.0.6, macOS (arm64), 10 CPU cores, 16 GB RAM. One machine only.

**Trials:** 5 per result, except the whole-month chunk-size sweep, which used 3 trials for 10,000, 50,000 and 250,000 rows (100,000 used 5).

**Noise floor:** across the four sweep runs the baseline's median time varied from 6.54 to 6.84 s and its extra memory from 1,966 to 2,022 MB, about 5%. Differences smaller than that should not be read as real.

## Data

Citi Bike trip data, September 2026. The five columns used are `ride_id`, `rideable_type`, `started_at`, `ended_at` and `member_casual`.

| File | Rows | Size |
| --- | --- | --- |
| Jersey City (`JC-202609`) | 106,628 | 23.2 MB |
| New York part 1 | 1,000,000 | 195.3 MB |
| New York parts 1 and 2 joined | 2,000,000 | 390.1 MB |
| New York whole month (5 parts joined) | 4,982,855 | 972.2 MB |

On the whole month: no missing values, unparseable timestamps, non-positive durations or duplicate ride IDs. 46,814 rows (0.94%) fell outside the 60 to 3,600 s duration range, leaving 4,936,041 rows used. The duplicate-removal rule never removed a row on this data, so only the tests have exercised it.

## Results: file size (chunk size 100,000)

| Rows | Strategy | Median s | Rows per s | Extra MB | Peak MB |
| --- | --- | --- | --- | --- | --- |
| 106,628 | baseline | 0.133 | 798,886 | 82.6 | 159.0 |
| 106,628 | chunked | 0.164 | 651,230 | 80.5 | 156.9 |
| 1,000,000 | baseline | 1.190 | 840,174 | 394.9 | 471.3 |
| 1,000,000 | chunked | 1.531 | 653,080 | 207.2 | 283.5 |
| 2,000,000 | baseline | 2.534 | 789,395 | 794.2 | 870.5 |
| 2,000,000 | chunked | 3.063 | 652,912 | 338.3 | 414.7 |
| 4,982,855 | baseline | 6.841 | 728,352 | 2,021.7 | 2,098.2 |
| 4,982,855 | chunked | 8.000 | 622,858 | 668.5 | 744.8 |

- Baseline memory is linear in rows: about 400 bytes per row, so 395, 794 and 2,022 MB at 1M, 2M and 4.98M rows.
- On the small Jersey City file chunked saves almost nothing (80.5 against 82.6 MB), because the chunk is about as large as the file.
- Chunked is never faster than the baseline in these measurements.

## Results: chunk size on the whole month

| Chunk size | Trials | Chunked median s | Chunked extra MB | Time vs same-run baseline | Memory vs same-run baseline |
| --- | --- | --- | --- | --- | --- |
| 10,000 | 3 | 8.62 | 618.5 | 27% slower | 69% less |
| 50,000 | 3 | 7.82 | 664.4 | 20% slower | 67% less |
| 100,000 | 5 | 8.00 | 668.5 | 17% slower | 67% less |
| 250,000 | 3 | 8.04 | 727.1 | 22% slower | 63% less |

- A 25 times larger chunk adds only 109 MB. At 10,000 rows the chunk is a few MB, yet chunked still used 618 MB. The likely cause is the `seen` set of ride IDs, at roughly 120 bytes per ride. This is an inference from the numbers; the set has not been measured directly.
- 50,000 and 100,000 rows cannot be told apart: their times differ by 0.18 s, inside the 100,000 trials' own spread, and their memory differs by under 1%.
- 10,000 rows is about 8% slower than the middle sizes for roughly 45 MB (7%) less memory.

The smaller Jersey City file gave a different picture (smaller chunks cut memory by up to 60% at 2,000 rows, at up to 86% more time). That result does not carry over to large files, so the default was not chosen from it.

## Limits of these results

- One machine, one month of data, one run of each sweep size apart from the 5-trial runs.
- The whole-month baseline needs about 2 GB, which fits easily in 16 GB. These measurements show that chunked uses less memory. They do not show a case where the baseline fails.
- Chunked memory is not bounded by chunk size, because the `seen` set grows with the number of unique rides.
- The time per row of both strategies fell as files grew (baseline 840,000 to 728,000 rows per s). No cause was measured.

## Reproduce

From the repository root, with the data files in `data/` (not committed):

```
python -m data_engine.benchmark run data/nyc_all.csv --trials 5 --out benchmarks/nyc-5parts.json
python -m data_engine.benchmark run data/nyc_all.csv --trials 3 --chunksize 50000 --out benchmarks/nyc-5parts-chunk50000.json
```

Saved results: `benchmarks/jc-202609*.json`, `benchmarks/nyc-1part.json`, `benchmarks/nyc-2parts.json`, `benchmarks/nyc-5parts*.json`.