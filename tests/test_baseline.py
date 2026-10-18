import pytest

from data_engine.baseline import run_baseline

HEADER = "ride_id,rideable_type,started_at,ended_at,member_casual\n"

ROWS = [
    "A,classic_bike,2026-09-08 08:00:00.000,2026-09-08 08:10:00.000,member",  # kept, 600 s
    "B,classic_bike,2026-09-08 09:00:00,2026-09-08 09:20:00,member",          # kept, 1200 s (no milliseconds)
    "C,electric_bike,2026-09-08 10:00:00.500,2026-09-08 10:05:00.500,casual", # kept, 300 s
    "D,electric_bike,2026-09-08 11:00:00,2026-09-08 11:30:00,casual",         # kept, 1800 s
    "A,classic_bike,2026-09-08 12:00:00,2026-09-08 12:50:00,member",          # repeated ride_id -> dropped
    "F,classic_bike,2026-09-08 13:10:00,2026-09-08 13:00:00,casual",          # ends before it starts -> dropped
    "G,classic_bike,2026-09-08 14:00:00,2026-09-08 14:00:00,casual",          # zero duration -> dropped
    "H,classic_bike,2026-09-08 15:00:00,,casual",                             # missing ended_at -> dropped
    "I,classic_bike,not a time,2026-09-08 16:10:00,casual",                   # unparseable -> dropped
    "J,electric_bike,2026-09-08 17:00:00,2026-09-08 17:00:30,member",         # 30 s: valid, removed by filter
    "K,electric_bike,2026-09-08 18:00:00,2026-09-08 20:00:00,member",         # 7200 s: valid, removed by filter
    "L,classic_bike,2026-09-08 21:00:00,2026-09-08 21:30:00,member",          # kept, 1800 s
]


@pytest.fixture
def csv_path(tmp_path):
    p = tmp_path / "trips.csv"
    p.write_text(HEADER + "\n".join(ROWS) + "\n")
    return p


def test_groups_and_aggregates(csv_path):
    result, _ = run_baseline(csv_path, min_duration=60, max_duration=3600)
    rows = {
        (r.member_casual, r.rideable_type): (r.count, r.sum_duration, r.avg_duration)
        for r in result.itertuples()
    }
    assert rows == {
        ("member", "classic_bike"): (3, 3600.0, 1200.0),   # A, B, L
        ("casual", "electric_bike"): (2, 2100.0, 1050.0),  # C, D
    }


def test_drop_counts(csv_path):
    _, counts = run_baseline(csv_path, min_duration=60, max_duration=3600)
    assert counts == {
        "rows_read": 12,
        "dropped_missing": 1,
        "dropped_unparseable": 1,
        "dropped_nonpositive_duration": 2,
        "dropped_duplicate": 1,
        "dropped_by_filter": 2,
        "rows_used": 5,
    }


def test_wider_filter_keeps_more_rows(csv_path):
    result, counts = run_baseline(csv_path, min_duration=1, max_duration=10_000)
    assert counts["rows_used"] == 7  # adds J (30 s) and K (7200 s)


def test_empty_file_gives_empty_result(tmp_path):
    p = tmp_path / "empty.csv"
    p.write_text(HEADER)
    result, counts = run_baseline(p)
    assert len(result) == 0
    assert counts["rows_read"] == 0
    assert counts["rows_used"] == 0