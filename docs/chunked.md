# Milestone 3: Chunked implementation

The chunked strategy reads the CSV in pieces of `chunksize` rows, cleans and filters each piece, adds that piece's per-group count and sum into running totals, then discards the piece. It must return exactly the same result as the baseline ([milestone-2-baseline.md](milestone-2-baseline.md)) at any chunk size.

## Components

| File | Purpose |
| --- | --- |
| `data_engine/chunked.py` | `run_chunked(path, min_duration, max_duration, chunksize)`: same inputs and outputs as `run_baseline`, plus the chunk size. |
| `tests/test_chunked.py` | Hand-computed answers, baseline-equivalence at several chunk sizes, and edge cases that span chunks. |
| `scripts/compare.py` | Runs both strategies on a real CSV and fails if their tables or drop counts differ. |

Cleaning is not duplicated: `run_chunked` calls the same `add_duration` function as the baseline, so both strategies apply rules 2-4 identically.

## How it differs from the baseline

| | Baseline | Chunked |
| --- | --- | --- |
| Reading | Whole file into one table | Pieces of `chunksize` rows, one at a time |
| State kept between pieces | Not applicable | Per-group count and sum, plus the set of `ride_id` values accepted so far |
| Average | sum / count | sum / count, computed once after the last chunk |
| Duplicates | `drop_duplicates` over the whole table | Within the chunk, then against the set of earlier IDs |

## Design decisions

- **Running sums and counts, never running averages.** An average carries no record of how many rows produced it, so averaging chunk averages gives a confident wrong answer whenever a group is spread unevenly across chunks. Counts and sums add across chunks, and the average is derived once at the end. `test_average_is_weighted_not_average_of_averages` checks this: the member group is split 1 / 2 / 1 across three chunks, averaging chunk averages gives about 466.7 s, and the correct answer is 400 s.
- **Duplicates need memory of earlier chunks.** Removing duplicates inside each chunk misses a repeat of a ride from an earlier chunk. The chunked version keeps a set of every `ride_id` it has accepted, so its memory still grows with the number of unique rides. It is smaller than the baseline's footprint, but not constant. The size of this cost has not been measured yet.
- **Direct set lookup, not `Series.isin(seen)`.** The first version checked earlier chunks with `isin(seen)`. Pandas rebuilds an array from the whole Python set on every call, so each check cost time proportional to everything seen so far. In a micro-test with 1.9 million seen IDs, one check on a 100,000-row chunk took about 1,044 ms, against about 34 ms with a per-row `rid in seen` lookup. The lookup keeps the cost proportional to the chunk. The output is identical, and the cross-chunk duplicate tests fail if the check is removed. This was found while building the benchmark, not by the tests, because the tests check results and not speed.
- **Same rule order as the baseline.** The set is updated after cleaning and before the duration filter, so a ride filtered out for being too long still counts as seen. A repeated ID whose first copy was invalid (for example, a negative duration) keeps the valid second copy in both strategies. A test covers this.

## Verification

From the repository root:

```
python -m pytest -v
PYTHONPATH=. python scripts/compare.py data/JC-202609-citibike-tripdata.csv
```

The tests include:

- the 12-row fixture with known answers, at chunk sizes 1, 2, 3, 5, 11, 12 and 1000;
- equality with the baseline (table and drop counts) at the same chunk sizes;
- a duplicate whose two copies fall in different chunks;
- the weighted-average case above;
- a duplicate whose first copy is invalid;
- an empty file.

### Results

- Test suite (baseline, chunked and benchmark tests together): 28 passed (Python 3.14.0, pandas 3.0.6, pytest 9.1.1, macOS).
- `compare.py` on `JC-202609-citibike-tripdata.csv`: 
`chunksize 5000 -> identical to baseline
chunksize 20000 -> identical to baseline
chunksize 100000 -> identical to baseline`.

## Limitations

- Equivalence has been tested on a small fixture and the Jersey City file only. The much larger New York files have not been tried.
- No runtime or memory measurements exist yet. This milestone establishes that the two strategies agree, not that either is faster or smaller. Benchmarks come next.
- Chunk size affects both speed and memory, and no default has been chosen on evidence. The default of 100,000 rows is a placeholder.