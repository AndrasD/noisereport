"""Coverage / heatmap / on-off stats."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.regularity import (
    clip_events_to_data,
    duty_heatmap,
    on_hours_clipped,
    on_hours_from_on_off_rows,
    on_off_period_stats,
    valid_measure_hours_from_minutes,
)


def _ts(s: str) -> pd.Timestamp:
    return pd.Timestamp(s, tz="UTC")


def test_valid_measure_hours_from_minute_rows() -> None:
    minutes = pd.DataFrame(
        {
            "measured_at": pd.date_range(
                "2024-01-01 10:00", periods=90, freq="min", tz="UTC"
            ),
            "laeq_db": 45.0,
        }
    )
    assert valid_measure_hours_from_minutes(minutes) == 1.5


def test_on_ratio_uses_valid_not_wall_clock() -> None:
    minutes = pd.DataFrame(
        {
            "measured_at": pd.date_range(
                "2024-01-01 10:00", periods=60, freq="min", tz="UTC"
            ),
            "laeq_db": 50.0,
        }
    )
    events = pd.DataFrame(
        [
            {
                "started_at": _ts("2024-01-01 10:00:00"),
                "ended_at": _ts("2024-01-01 10:30:00"),
                "duration_s": 1800.0,
            }
        ]
    )
    rows = on_off_period_stats(minutes, events)
    valid = valid_measure_hours_from_minutes(minutes)
    on_h = on_hours_from_on_off_rows(rows)
    assert valid == 1.0
    assert abs(on_h - 0.5) < 1e-9
    assert abs(100.0 * on_h / valid - 50.0) < 1e-6


def test_clip_events_drops_gap_span() -> None:
    t0 = _ts("2024-01-01 10:00:00")
    sound_times = pd.Series(
        list(pd.date_range(t0, periods=10, freq="min"))
        + list(pd.date_range(t0 + pd.Timedelta(hours=3), periods=10, freq="min"))
    )
    events = pd.DataFrame(
        [
            {
                "started_at": t0,
                "ended_at": t0 + pd.Timedelta(hours=3, minutes=10),
                "duration_s": 3 * 3600 + 600,
            }
        ]
    )
    clipped = clip_events_to_data(events, sound_times)
    assert not clipped.empty
    assert len(clipped) >= 2
    assert clipped["duration_s"].sum() < 3 * 3600


def test_heatmap_nan_for_no_data(tmp_path: Path) -> None:
    start = _ts("2024-01-01 10:00:00")
    end = _ts("2024-01-01 14:00:00")
    sound_times = pd.Series(pd.date_range(start, periods=60, freq="min"))
    events = pd.DataFrame(
        [
            {
                "started_at": start,
                "ended_at": start + pd.Timedelta(minutes=30),
                "duration_s": 1800.0,
            }
        ]
    )
    out = tmp_path / "heat.png"
    duty_heatmap(
        events,
        out_path=out,
        start=start,
        end=end,
        sound_times=sound_times,
    )
    assert out.exists()
    from src.regularity import _data_minute_mask

    minutes = pd.date_range(
        start.tz_convert("Europe/Budapest").floor("min"),
        end.tz_convert("Europe/Budapest").floor("min"),
        freq="min",
        inclusive="left",
    )
    has = _data_minute_mask(minutes, sound_times)
    assert has.any() and (~has).any()


def test_on_off_period_stats_day_night_sums_to_on_total() -> None:
    rows_m = []
    base_day = _ts("2024-01-01 10:00:00")
    for i in range(20):
        rows_m.append(
            {
                "measured_at": base_day + pd.Timedelta(minutes=i),
                "laeq_db": 55.0 if i < 10 else 40.0,
            }
        )
    base_night = _ts("2024-01-01 23:00:00")
    for i in range(20):
        rows_m.append(
            {
                "measured_at": base_night + pd.Timedelta(minutes=i),
                "laeq_db": 48.0 if i < 10 else 35.0,
            }
        )
    minutes = pd.DataFrame(rows_m)
    events = pd.DataFrame(
        [
            {
                "started_at": base_day,
                "ended_at": base_day + pd.Timedelta(minutes=10),
                "duration_s": 600.0,
            },
            {
                "started_at": base_night,
                "ended_at": base_night + pd.Timedelta(minutes=10),
                "duration_s": 600.0,
            },
        ]
    )
    stats = on_off_period_stats(minutes, events)
    assert len(stats) == 4
    by_key = {(r["period"], r["state"]): r for r in stats}
    day_on = by_key[("Nappal (06–22)", "Gép jár")]
    day_off = by_key[("Nappal (06–22)", "Gép nem jár")]
    night_on = by_key[("Éjjel (22–06)", "Gép jár")]
    night_off = by_key[("Éjjel (22–06)", "Gép nem jár")]
    assert day_on["laeq_db"] > day_off["laeq_db"]
    assert night_on["laeq_db"] > night_off["laeq_db"]
    assert day_on["minutes_approx"] == 10
    assert night_on["minutes_approx"] == 10
    on_h = on_hours_from_on_off_rows(stats)
    assert abs(on_h - 20 / 60.0) < 1e-9
    assert abs(on_h - on_hours_clipped(events)) < 1e-9
    total_min = sum(r["minutes_approx"] for r in stats)
    assert total_min == len(minutes)
