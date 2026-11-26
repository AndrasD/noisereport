from datetime import datetime, timezone

import pytest

from src.timeutil import parse_local, to_utc_interval


def test_parse_date_local() -> None:
    dt = parse_local("2026-11-20")
    assert dt.tzinfo is not None
    assert dt.hour == 0
    assert dt.day == 20


def test_winter_utc_offset() -> None:
    # CET (UTC+1) in November
    start, end = to_utc_interval("2026-11-20", "2026-11-21")
    assert start == datetime(2026, 11, 19, 23, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 11, 20, 23, 0, tzinfo=timezone.utc)


def test_end_before_start_raises() -> None:
    with pytest.raises(ValueError):
        to_utc_interval("2026-11-21", "2026-11-20")
