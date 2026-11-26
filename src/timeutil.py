"""Local Europe/Budapest timestamps → UTC half-open intervals."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

BUDAPEST = ZoneInfo("Europe/Budapest")
UTC = ZoneInfo("UTC")


def parse_local(value: str, *, tz_name: str = "Europe/Budapest") -> datetime:
    """Parse ``YYYY-MM-DD`` or ``YYYY-MM-DDTHH:MM[:SS]`` as local wall time."""
    raw = value.strip()
    tz = ZoneInfo(tz_name)
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(raw, fmt)
            break
        except ValueError:
            continue
    else:
        raise ValueError(f"unrecognized datetime: {value!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt


def to_utc_interval(
    start_local: str,
    end_local: str,
    *,
    tz_name: str = "Europe/Budapest",
) -> tuple[datetime, datetime]:
    """Return ``[start, end)`` as timezone-aware UTC datetimes."""
    start = parse_local(start_local, tz_name=tz_name).astimezone(UTC)
    end = parse_local(end_local, tz_name=tz_name).astimezone(UTC)
    if end <= start:
        raise ValueError("end must be after start")
    return start, end
