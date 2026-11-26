"""Offline machine on/off detection from a Parquet snapshot."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.detector_core import DetectorEvent, detect_machine_events

_ROOT = Path(__file__).resolve().parents[1]


def load_detector_config(path: Path | None = None) -> dict[str, Any]:
    cfg_path = path or (_ROOT / "config" / "detector_1.1.0.yaml")
    with cfg_path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_feature_windows(
    sound: pd.DataFrame,
    manuals: pd.DataFrame,
    fft_windows: pd.DataFrame | None = None,
    *,
    window_seconds: int = 5,
) -> list[dict[str, Any]]:
    """Build 5 s feature windows compatible with ``detect_machine_events``."""
    if sound.empty:
        return []

    s = sound.copy()
    s["measured_at"] = pd.to_datetime(s["measured_at"], utc=True)
    s["level_db"] = pd.to_numeric(s["level_db"], errors="coerce")
    s = s.dropna(subset=["level_db", "measured_at"]).sort_values("measured_at")
    step = pd.Timedelta(seconds=window_seconds)
    s["window_start"] = s["measured_at"].dt.floor(f"{window_seconds}s")

    rows: list[dict[str, Any]] = []
    for start, grp in s.groupby("window_start", sort=True):
        levels = grp["level_db"].astype(float)
        rows.append(
            {
                "window_start": start.to_pydatetime(),
                "window_end": (start + step).to_pydatetime(),
                "level_p90_db": float(levels.quantile(0.9)),
                "level_median_db": float(levels.median()),
                "fft_count": 0,
                "dominant_hz": None,
                "heard_count": 0,
                "not_heard_count": 0,
            }
        )
    if not rows:
        return []

    feat = pd.DataFrame(rows)

    if fft_windows is not None and not fft_windows.empty:
        f = fft_windows.copy()
        f["measured_at"] = pd.to_datetime(f["measured_at"], utc=True)
        f["window_start"] = f["measured_at"].dt.floor(f"{window_seconds}s")

        def _dom(meta: Any) -> float | None:
            if isinstance(meta, dict):
                v = meta.get("dominant_hz")
            elif isinstance(meta, str):
                try:
                    v = json.loads(meta).get("dominant_hz")
                except json.JSONDecodeError:
                    return None
            else:
                return None
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        if "metadata" in f.columns:
            f["dominant_hz"] = f["metadata"].map(_dom)
        else:
            f["dominant_hz"] = None
        agg = f.groupby("window_start").agg(
            fft_count=("measured_at", "count"),
            dominant_hz=("dominant_hz", "median"),
        )
        feat = feat.set_index("window_start")
        feat.update(agg)
        feat["fft_count"] = feat["fft_count"].fillna(0).astype(int)
        feat = feat.reset_index()

    if manuals is not None and not manuals.empty:
        m = manuals.copy()
        m["observed_at"] = pd.to_datetime(m["observed_at"], utc=True)
        m["window_start"] = m["observed_at"].dt.floor(f"{window_seconds}s")
        for start, grp in m.groupby("window_start"):
            heard = int((grp["observation"] == "heard").sum())
            not_heard = int((grp["observation"] == "not_heard").sum())
            mask = feat["window_start"] == start
            if mask.any():
                feat.loc[mask, "heard_count"] = heard
                feat.loc[mask, "not_heard_count"] = not_heard
            else:
                # observation without sound window — still inject a stub so manual_truth applies
                feat = pd.concat(
                    [
                        feat,
                        pd.DataFrame(
                            [
                                {
                                    "window_start": start.to_pydatetime()
                                    if hasattr(start, "to_pydatetime")
                                    else start,
                                    "window_end": (
                                        (start + step).to_pydatetime()
                                        if hasattr(start, "to_pydatetime")
                                        else start + timedelta(seconds=window_seconds)
                                    ),
                                    "level_p90_db": None,
                                    "level_median_db": None,
                                    "fft_count": 0,
                                    "dominant_hz": None,
                                    "heard_count": heard,
                                    "not_heard_count": not_heard,
                                }
                            ]
                        ),
                    ],
                    ignore_index=True,
                )
                feat = feat.sort_values("window_start").reset_index(drop=True)

    return feat.to_dict(orient="records")


@dataclass
class DetectionScore:
    observations: int
    hits: int
    hit_rate: float
    details: list[dict[str, Any]]


def score_against_manuals(
    events: list[DetectorEvent],
    manuals: pd.DataFrame,
) -> DetectionScore:
    if manuals is None or manuals.empty:
        return DetectionScore(0, 0, 0.0, [])

    details: list[dict[str, Any]] = []
    hits = 0
    m = manuals.copy()
    m["observed_at"] = pd.to_datetime(m["observed_at"], utc=True)

    for _, row in m.iterrows():
        t = row["observed_at"].to_pydatetime()
        obs = str(row["observation"])
        on = any(
            ev.started_at <= t < (ev.ended_at or ev.started_at)
            for ev in events
            if ev.ended_at is not None
        )
        expected_on = obs == "heard"
        hit = on == expected_on
        if hit:
            hits += 1
        details.append(
            {
                "observed_at": t.isoformat(),
                "observation": obs,
                "detector_on": on,
                "hit": hit,
            }
        )
    n = len(details)
    return DetectionScore(n, hits, (hits / n) if n else 0.0, details)


def run_detection(
    snapshot_dir: Path,
    *,
    detector_config_path: Path | None = None,
) -> tuple[list[DetectorEvent], DetectionScore, Path]:
    snap = Path(snapshot_dir)
    cfg = load_detector_config(detector_config_path)
    params = cfg["parameters"]
    window_seconds = int(params.get("window_seconds", 5))

    sound = pd.read_parquet(snap / "sound_sample.parquet")
    manuals = (
        pd.read_parquet(snap / "manual_observations.parquet")
        if (snap / "manual_observations.parquet").exists()
        else pd.DataFrame()
    )
    fft = (
        pd.read_parquet(snap / "fft_window.parquet")
        if (snap / "fft_window.parquet").exists()
        else None
    )

    feature_rows = build_feature_windows(
        sound, manuals, fft, window_seconds=window_seconds
    )
    events = detect_machine_events(
        feature_rows,
        params,
        method=cfg.get("method", "acoustic_hysteresis"),
        param_version=str(cfg.get("param_version", "1.1.0")),
    )
    score = score_against_manuals(events, manuals)

    out = snap / "machine_events.json"
    payload = {
        "method": cfg.get("method"),
        "param_version": cfg.get("param_version"),
        "parameters": params,
        "event_count": len(events),
        "score": {
            "observations": score.observations,
            "hits": score.hits,
            "hit_rate": score.hit_rate,
            "details": score.details,
        },
        "events": [
            {
                "started_at": e.started_at.isoformat(),
                "ended_at": e.ended_at.isoformat() if e.ended_at else None,
                "event_kind": e.event_kind,
                "method": e.method,
                "param_version": e.param_version,
                "parameters": e.parameters,
                "quality_flags": list(e.quality_flags),
            }
            for e in events
        ],
    }
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return events, score, out
