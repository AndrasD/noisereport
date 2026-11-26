"""Data-quality checks on an extract snapshot."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Gap:
    start: str
    end: str
    duration_s: float


@dataclass
class QcReport:
    snapshot_dir: str
    expected_samples_per_minute: float
    sound_sample_count: int
    duration_minutes: float
    expected_samples: float
    coverage_ratio: float
    duplicate_timestamps: int
    level_db_min: float | None
    level_db_max: float | None
    impossible_level_count: int
    gaps: list[Gap]
    gps_fix_rows: int
    gps_with_fix: int
    notes: list[str]


def load_config(path: Path | None = None) -> dict[str, Any]:
    with (path or _ROOT / "config.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _read_parquet(snap: Path, name: str) -> pd.DataFrame:
    path = snap / f"{name}.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def run_qc(snapshot_dir: Path, *, config: dict[str, Any] | None = None) -> QcReport:
    cfg = config or load_config()
    expected_per_min = float(cfg.get("expected_samples_per_minute", 1200.0))
    snap = Path(snapshot_dir)

    manifest = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))
    start = pd.Timestamp(manifest["start_utc"])
    end = pd.Timestamp(manifest["end_utc"])
    duration_min = max((end - start).total_seconds() / 60.0, 0.0)

    sound = _read_parquet(snap, "sound_sample")
    notes: list[str] = []
    gaps: list[Gap] = []

    if sound.empty:
        return QcReport(
            snapshot_dir=str(snap),
            expected_samples_per_minute=expected_per_min,
            sound_sample_count=0,
            duration_minutes=duration_min,
            expected_samples=duration_min * expected_per_min,
            coverage_ratio=0.0,
            duplicate_timestamps=0,
            level_db_min=None,
            level_db_max=None,
            impossible_level_count=0,
            gaps=[],
            gps_fix_rows=0,
            gps_with_fix=0,
            notes=["no sound_sample rows"],
        )

    ts = pd.to_datetime(sound["measured_at"], utc=True).sort_values()
    dup = int(ts.duplicated().sum())
    levels = pd.to_numeric(sound["level_db"], errors="coerce")
    impossible = int(((levels < 20) | (levels > 140) | levels.isna()).sum())

    # Gaps: successive samples farther than 2 s apart (stream is ~20 Hz)
    ts_list = list(ts)
    for i in range(1, len(ts_list)):
        d = (ts_list[i] - ts_list[i - 1]).total_seconds()
        if d > 2.0:
            gaps.append(
                Gap(
                    start=ts_list[i - 1].isoformat(),
                    end=ts_list[i].isoformat(),
                    duration_s=round(d, 3),
                )
            )

    expected = duration_min * expected_per_min
    coverage = (len(sound) / expected) if expected > 0 else 0.0

    gps = _read_parquet(snap, "gps_fix")
    gps_rows = len(gps)
    gps_fix = 0
    if not gps.empty and "fix_quality" in gps.columns:
        gps_fix = int(gps["fix_quality"].notna().sum())

    if coverage < 0.5:
        notes.append("coverage below 50%")
    if impossible:
        notes.append(f"{impossible} levels outside 20–140 dB")
    if dup:
        notes.append(f"{dup} duplicate measured_at values")

    return QcReport(
        snapshot_dir=str(snap),
        expected_samples_per_minute=expected_per_min,
        sound_sample_count=len(sound),
        duration_minutes=round(duration_min, 3),
        expected_samples=round(expected, 1),
        coverage_ratio=round(coverage, 4),
        duplicate_timestamps=dup,
        level_db_min=float(levels.min()) if len(levels) else None,
        level_db_max=float(levels.max()) if len(levels) else None,
        impossible_level_count=impossible,
        gaps=gaps[:200],  # cap for report size
        gps_fix_rows=gps_rows,
        gps_with_fix=gps_fix,
        notes=notes,
    )


def write_qc_outputs(report: QcReport, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = Path(report.snapshot_dir).name
    json_path = output_dir / f"qc_{stamp}.json"
    gaps_path = output_dir / f"qc_gaps_{stamp}.csv"

    payload = asdict(report)
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    pd.DataFrame([asdict(g) for g in report.gaps]).to_csv(gaps_path, index=False)
    return json_path, gaps_path
