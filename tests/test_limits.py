from datetime import time

import pandas as pd

from src.limits import evaluate_limits, rolling_laeq_windows, _window_fully_in_period
from src.metrics import energetic_laeq


def test_rolling_one_minute() -> None:
    idx = pd.date_range("2026-11-25T10:00:00Z", periods=90, freq="1s")
    sound = pd.DataFrame({"measured_at": idx, "level_db": 50.0})
    res = rolling_laeq_windows(
        sound,
        window=pd.Timedelta(minutes=1),
        step=pd.Timedelta(minutes=1),
        day_limit=50,
        night_limit=40,
        period="day",
        expected_hz=1.0,
        min_coverage=0.5,
    )
    assert res
    assert res[0].laeq_db == energetic_laeq([50.0])


def test_evaluate_limits_assessment_rows() -> None:
    # Long enough daytime block for an 8h window (~10 hours of samples)
    idx = pd.date_range("2026-11-25T05:00:00Z", periods=10 * 3600, freq="1s")  # 06–16 local CET
    sound = pd.DataFrame({"measured_at": idx, "level_db": 55.0})
    out = evaluate_limits(
        sound, day_limit=50, night_limit=40, expected_hz=1.0, min_coverage=0.5
    )
    assert out["assessment_rows"]
    labels = [r["label"] for r in out["assessment_rows"]]
    assert any("Nappal" in x for x in labels)
    assert any("Éjjel" in x for x in labels)
    day_row = next(r for r in out["assessment_rows"] if r["window"] == "8h_day")
    assert day_row["max_laeq"] is not None
    assert day_row["max_laeq"] > 50


def test_window_fully_in_period_rejects_night_spill_into_day() -> None:
    # 03:00–11:00 local CET spans night then day — not a valid day window
    start = pd.Timestamp("2026-11-25 02:00:00+00")  # 03:00 CET
    end = pd.Timestamp("2026-11-25 10:00:00+00")  # 11:00 CET
    assert not _window_fully_in_period(start, end, "day")
    # 06:00–14:00 local is fully daytime
    start_ok = pd.Timestamp("2026-11-25 05:00:00+00")
    end_ok = pd.Timestamp("2026-11-25 13:00:00+00")
    assert _window_fully_in_period(start_ok, end_ok, "day")


def test_day_assessment_ignores_loud_night() -> None:
    """Loud 03–06 local + quiet day → worst daytime 8h ≈ quiet level, not ~65 dB."""
    start = pd.Timestamp("2026-11-24 21:00:00", tz="Europe/Budapest").tz_convert("UTC")
    end = pd.Timestamp("2026-11-25 22:00:00", tz="Europe/Budapest").tz_convert("UTC")
    idx = pd.date_range(start, end, freq="1s", inclusive="left")
    levels = []
    for ts in idx:
        local_t = ts.tz_convert("Europe/Budapest").time()
        if time(3, 0) <= local_t < time(6, 0):
            levels.append(70.0)
        else:
            levels.append(35.0)
    sound = pd.DataFrame({"measured_at": idx, "level_db": levels})
    out = evaluate_limits(
        sound, day_limit=50.0, night_limit=40.0, expected_hz=1.0, min_coverage=0.5
    )
    day_row = next(r for r in out["assessment_rows"] if r["window"] == "8h_day")
    assert day_row["max_laeq"] is not None
    assert day_row["max_laeq"] < 36.0
    assert day_row["is_over"] is False
    # Night should still see the loud stretch
    night_row = next(r for r in out["assessment_rows"] if r["window"] == "30min_night")
    assert night_row["max_laeq"] is not None
    assert night_row["max_laeq"] > 65.0


def test_night_window_does_not_cross_0600() -> None:
    # 05:45–06:15 local crosses into daytime
    start = pd.Timestamp("2026-11-25 05:45:00", tz="Europe/Budapest").tz_convert("UTC")
    end = pd.Timestamp("2026-11-25 06:15:00", tz="Europe/Budapest").tz_convert("UTC")
    assert not _window_fully_in_period(start, end, "night")
    start_ok = pd.Timestamp("2026-11-24 22:00:00", tz="Europe/Budapest").tz_convert(
        "UTC"
    )
    end_ok = pd.Timestamp("2026-11-24 22:30:00", tz="Europe/Budapest").tz_convert("UTC")
    assert _window_fully_in_period(start_ok, end_ok, "night")
