"""Versioned acoustic detector operating on PostgreSQL feature windows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class DetectorEvent:
    """One derived heat-pump operating interval."""

    started_at: datetime
    ended_at: datetime | None
    event_kind: str
    method: str
    param_version: str
    parameters: dict[str, Any]
    quality_flags: tuple[str, ...]


def detect_machine_events(
    rows: Sequence[Mapping[str, Any]],
    parameters: Mapping[str, Any],
    *,
    method: str = "acoustic_hysteresis",
    param_version: str = "1.0.0",
) -> list[DetectorEvent]:
    """Detect persistent acoustic runs from feature-window rows.

    The detector deliberately uses a conservative hysteresis state machine:
    several consecutive elevated windows are needed to start an event and
    several quiet windows are needed to end it. Missing sound windows do not
    start an event and are recorded as a quality flag when an event is open.
    """
    ordered = sorted((_normalise_row(row) for row in rows), key=lambda row: row["start"])
    if not ordered:
        return []

    window_seconds = _positive_int(parameters, "window_seconds", 5)
    start_delta = _positive_float(parameters, "start_delta_db", 5.0)
    stop_delta = _positive_float(parameters, "stop_delta_db", 3.0)
    start_confirm = _positive_int(parameters, "start_confirm_windows", 3)
    stop_confirm = _positive_int(parameters, "stop_confirm_windows", 6)
    min_event_seconds = _positive_int(parameters, "min_event_seconds", 15)
    manual_truth = bool(parameters.get("manual_truth", False))

    baseline = _baseline(ordered, manual_truth=manual_truth)
    events: list[DetectorEvent] = []
    active_start: datetime | None = None
    stop_start: datetime | None = None
    start_streak = 0
    stop_streak = 0
    evidence: list[dict[str, Any]] = []
    quality: set[str] = set()
    previous_start: datetime | None = None

    for row in ordered:
        start = row["start"]
        end = row["end"]
        if previous_start is not None:
            gap = (start - previous_start).total_seconds()
            if gap > window_seconds * 2:
                start_streak = 0
                stop_streak = 0
                if active_start is not None:
                    quality.add("data_gap")
        previous_start = start

        level = row["level"]
        manual_heard = row["heard"] > row["not_heard"]
        manual_not_heard = row["not_heard"] > row["heard"]

        # In the manual-truth profile, an explicit observation is a hard
        # constraint for this feature window.  It does not fabricate a
        # duration: acoustic evidence is still used between observations.
        if manual_truth and manual_not_heard:
            if active_start is not None:
                ended_at = start
                if (ended_at - active_start).total_seconds() >= min_event_seconds:
                    events.append(_build_event(
                        active_start, ended_at, baseline, evidence, quality,
                        method, param_version, parameters,
                    ))
            active_start = None
            stop_start = None
            start_streak = 0
            stop_streak = 0
            evidence.clear()
            continue

        if manual_truth and manual_heard and active_start is None:
            active_start = start
            stop_start = None
            start_streak = 0
            stop_streak = 0
            quality = {"manual_heard"}

        if level is None:
            if active_start is not None:
                quality.add("missing_sound")
            start_streak = 0
            stop_streak = 0
            continue

        delta = level - baseline
        elevated = delta >= start_delta or (manual_heard and delta >= stop_delta)
        quiet = delta <= stop_delta and not manual_heard

        if active_start is None:
            stop_streak = 0
            if elevated:
                if start_streak == 0:
                    candidate_start = start
                start_streak += 1
                evidence.append(_evidence(row, delta))
                if start_streak >= start_confirm:
                    active_start = candidate_start
                    stop_start = None
                    quality = set()
            else:
                start_streak = 0
                evidence.clear()
            continue

        if row["fft_count"] == 0:
            quality.add("no_fft")
        evidence.append(_evidence(row, delta))
        if len(evidence) > 200:
            evidence = evidence[-200:]

        if quiet:
            if stop_streak == 0:
                stop_start = start
            stop_streak += 1
            if stop_streak >= stop_confirm:
                ended_at = stop_start or start
                if (ended_at - active_start).total_seconds() >= min_event_seconds:
                    events.append(_build_event(
                        active_start, ended_at, baseline, evidence, quality,
                        method, param_version, parameters,
                    ))
                active_start = None
                stop_start = None
                start_streak = 0
                stop_streak = 0
                evidence.clear()
        else:
            stop_streak = 0
            stop_start = None

    if active_start is not None:
        ended_at = ordered[-1]["end"]
        if (ended_at - active_start).total_seconds() >= min_event_seconds:
            quality.add("open_ended")
            events.append(_build_event(
                active_start, ended_at, baseline, evidence, quality,
                method, param_version, parameters,
            ))
    return events


def _normalise_row(row: Mapping[str, Any]) -> dict[str, Any]:
    start = _as_datetime(row.get("window_start"))
    end = _as_datetime(row.get("window_end"))
    level = row.get("level_p90_db")
    if level is None:
        level = row.get("level_median_db")
    return {
        "start": start,
        "end": end or start + timedelta(seconds=5),
        "level": _as_float(level),
        "fft_count": int(row.get("fft_count") or 0),
        "dominant_hz": _as_float(row.get("dominant_hz")),
        "heard": int(row.get("heard_count") or 0),
        "not_heard": int(row.get("not_heard_count") or 0),
    }


def _baseline(rows: Sequence[Mapping[str, Any]], *, manual_truth: bool = False) -> float:
    if manual_truth:
        # A hard "not heard" label constrains the state but must not by
        # itself define the acoustic baseline: the label can be correct even
        # when the measured level is elevated by another source.
        unlabeled = [
            row for row in rows
            if row["heard"] == 0 and row["not_heard"] == 0
        ]
        if unlabeled:
            rows = unlabeled
    labelled_quiet = [
        float(row["level"])
        for row in rows
        if row["level"] is not None and row["not_heard"] > row["heard"]
    ]
    levels = [float(row["level"]) for row in rows if row["level"] is not None]
    if not levels:
        return 0.0
    if labelled_quiet:
        return float(median(labelled_quiet))
    levels.sort()
    return float(median(levels[: max(1, len(levels) // 5)]))


def _evidence(row: Mapping[str, Any], delta: float) -> dict[str, Any]:
    return {
        "window_start": row["start"].isoformat(),
        "level_db": round(float(row["level"]), 3),
        "delta_db": round(float(delta), 3),
        "dominant_hz": row.get("dominant_hz"),
    }


def _build_event(
    started_at: datetime,
    ended_at: datetime,
    baseline: float,
    evidence: Sequence[Mapping[str, Any]],
    quality: set[str],
    method: str,
    param_version: str,
    parameters: Mapping[str, Any],
) -> DetectorEvent:
    levels = [float(item["level_db"]) for item in evidence]
    deltas = [float(item["delta_db"]) for item in evidence]
    hz = [float(item["dominant_hz"]) for item in evidence if item.get("dominant_hz") is not None]
    max_delta = max(deltas, default=0.0)
    confidence = min(1.0, max(0.0, max_delta / max(10.0, float(parameters.get("start_delta_db", 5.0) * 2))))
    if any(item.get("dominant_hz") is not None for item in evidence):
        confidence = min(1.0, confidence + 0.1)
    if any("manual" in flag for flag in quality):
        confidence = max(0.0, confidence - 0.1)
    event_parameters = dict(parameters)
    event_parameters.update({
        "baseline_db": round(baseline, 3),
        "peak_db": round(max(levels), 3) if levels else None,
        "max_delta_db": round(max_delta, 3),
        "dominant_hz_median": round(float(median(hz)), 3) if hz else None,
        "feature_window_count": len(evidence),
        "confidence": round(confidence, 3),
        "evidence": list(evidence[-20:]),
    })
    return DetectorEvent(
        started_at=started_at,
        ended_at=ended_at,
        event_kind="run",
        method=method,
        param_version=param_version,
        parameters=event_parameters,
        quality_flags=tuple(sorted(quality)),
    )


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _as_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def _positive_int(parameters: Mapping[str, Any], key: str, default: int) -> int:
    value = int(parameters.get(key, default))
    if value <= 0:
        raise ValueError(f"{key} must be positive")
    return value


def _positive_float(parameters: Mapping[str, Any], key: str, default: float) -> float:
    value = float(parameters.get(key, default))
    if value <= 0:
        raise ValueError(f"{key} must be positive")
    return value
