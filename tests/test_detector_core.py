from datetime import datetime, timedelta, timezone

from src.detector_core import detect_machine_events


def _rows(levels: list[float], *, step: int = 5) -> list[dict]:
    start = datetime(2026, 11, 24, 10, 0, tzinfo=timezone.utc)
    return [
        {
            "window_start": start + timedelta(seconds=index * step),
            "window_end": start + timedelta(seconds=(index + 1) * step),
            "level_p90_db": level,
            "level_median_db": level,
            "fft_count": 1,
            "dominant_hz": 72.0,
            "heard_count": 0,
            "not_heard_count": 0,
        }
        for index, level in enumerate(levels)
    ]


PARAMS = {
    "window_seconds": 5,
    "start_delta_db": 5.0,
    "stop_delta_db": 3.0,
    "start_confirm_windows": 3,
    "stop_confirm_windows": 2,
    "min_event_seconds": 10,
}


def test_detector_emits_hysteresis_interval():
    events = detect_machine_events(_rows([40, 41, 40, 47, 48, 49, 48, 40, 40]), PARAMS)
    assert len(events) == 1
    assert events[0].started_at.isoformat() == "2026-11-24T10:00:15+00:00"
    assert events[0].ended_at.isoformat() == "2026-11-24T10:00:35+00:00"
    assert events[0].parameters["dominant_hz_median"] == 72.0


def test_detector_uses_not_heard_as_baseline_and_does_not_trigger_short_peak():
    events = detect_machine_events(_rows([40, 40, 51, 40, 40, 40]), PARAMS)
    assert events == []


def test_detector_marks_open_ended_event():
    events = detect_machine_events(_rows([40, 40, 47, 48, 49]), PARAMS)
    assert len(events) == 1
    assert "open_ended" in events[0].quality_flags


def test_manual_truth_starts_and_stops_on_explicit_observations():
    rows = _rows([40, 47, 47, 47, 47, 47, 47, 40])
    rows[1]["heard_count"] = 1
    rows[6]["heard_count"] = 0
    rows[6]["not_heard_count"] = 1
    events = detect_machine_events(
        rows,
        {**PARAMS, "manual_truth": True, "min_event_seconds": 5},
    )
    assert len(events) == 1
    assert events[0].started_at == rows[1]["window_start"]
    assert events[0].ended_at == rows[6]["window_start"]
    assert "manual_heard" in events[0].quality_flags
