import pandas as pd
import pytest

from data_engine.baseline import run_baseline
from data_engine.chunked import run_chunked
from tests.test_baseline import HEADER, ROWS

CHUNK_SIZES = [1, 2, 3, 5, 11, 12, 1000]


@pytest.fixture
def csv_path(tmp_path):
    p = tmp_path / "trips.csv"
    p.write_text(HEADER + "\n".join(ROWS) + "\n")
    return p


@pytest.mark.parametrize("chunksize", CHUNK_SIZES)
def test_chunked_matches_hand_computed_answer(csv_path, chunksize):
    result, counts = run_chunked(csv_path, chunksize=chunksize)
    rows = {
        (r.member_casual, r.rideable_type): (r.count, r.sum_duration, r.avg_duration)
        for r in result.itertuples()
    }
    assert rows == {
        ("member", "classic_bike"): (3, 3600.0, 1200.0),
        ("casual", "electric_bike"): (2, 2100.0, 1050.0),
    }
    assert counts["rows_read"] == 12
    assert counts["dropped_duplicate"] == 1
    assert counts["rows_used"] == 5


@pytest.mark.parametrize("chunksize", CHUNK_SIZES)
def test_chunked_equals_baseline(csv_path, chunksize):
    expected, expected_counts = run_baseline(csv_path)
    actual, actual_counts = run_chunked(csv_path, chunksize=chunksize)
    pd.testing.assert_frame_equal(actual, expected)
    assert actual_counts == expected_counts


def test_duplicate_spanning_chunks_is_dropped(tmp_path):
    # chunksize=1 puts the two "A" rows in different chunks.
    p = tmp_path / "dup.csv"
    p.write_text(
        HEADER
        + "A,classic_bike,2026-09-08 08:00:00,2026-09-08 08:10:00,member\n"
        + "B,classic_bike,2026-09-08 09:00:00,2026-09-08 09:10:00,member\n"
        + "A,classic_bike,2026-09-08 10:00:00,2026-09-08 10:20:00,member\n"
    )
    result, counts = run_chunked(p, chunksize=1)
    assert counts["dropped_duplicate"] == 1
    assert result["count"].tolist() == [2]


def test_average_is_weighted_not_average_of_averages(tmp_path):
    # chunksize=3 -> chunk 1 = R0, R1, R2 (member/classic, 1000, 1000, 1000 s)... see rows below.
    # Group sizes differ across chunks: chunk 1 has 1 ride of 1000 s, chunk 2 has 3 rides of 200 s.
    # Average of chunk averages = (1000 + 200) / 2 = 600. True average = (1000 + 3*200) / 4 = 400.
    p = tmp_path / "weighted.csv"
    p.write_text(
        HEADER
        + "R0,classic_bike,2026-09-08 08:00:00,2026-09-08 08:16:40,member\n"   # 1000 s
        + "S0,classic_bike,2026-09-08 08:30:00,2026-09-08 08:30:30,casual\n"   # filler, other group
        + "R1,classic_bike,2026-09-08 09:00:00,2026-09-08 09:03:20,member\n"   # 200 s
        + "R2,classic_bike,2026-09-08 10:00:00,2026-09-08 10:03:20,member\n"   # 200 s
        + "R3,classic_bike,2026-09-08 11:00:00,2026-09-08 11:03:20,member\n"   # 200 s
    )
    result, _ = run_chunked(p, min_duration=1, chunksize=2)
    member = result[result["member_casual"] == "member"].iloc[0]
    assert member["count"] == 4
    assert member["avg_duration"] == pytest.approx(400.0)


def test_duplicate_whose_first_copy_was_invalid_matches_baseline(tmp_path):
    # First "X" has a negative duration (dropped by cleaning), second "X" is valid.
    # Both strategies must keep the valid one.
    p = tmp_path / "edge.csv"
    p.write_text(
        HEADER
        + "X,classic_bike,2026-09-08 08:10:00,2026-09-08 08:00:00,member\n"
        + "X,classic_bike,2026-09-08 09:00:00,2026-09-08 09:10:00,member\n"
    )
    expected, expected_counts = run_baseline(p)
    actual, actual_counts = run_chunked(p, chunksize=1)
    pd.testing.assert_frame_equal(actual, expected)
    assert actual_counts == expected_counts
    assert actual_counts["rows_used"] == 1


def test_empty_file(tmp_path):
    p = tmp_path / "empty.csv"
    p.write_text(HEADER)
    result, counts = run_chunked(p, chunksize=10)
    assert len(result) == 0
    assert counts["rows_read"] == 0
    assert counts["rows_used"] == 0