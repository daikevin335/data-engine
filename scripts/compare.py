import sys
import pandas as pd
from data_engine.baseline import run_baseline
from data_engine.chunked import run_chunked

path = sys.argv[1]
expected, expected_counts = run_baseline(path)
for chunksize in (5_000, 20_000, 100_000):
    actual, actual_counts = run_chunked(path, chunksize = chunksize)
    pd.testing.assert_frame_equal(actual, expected)
    assert actual_counts == expected_counts
    print("chunksize", chunksize, "-> identical to baseline")