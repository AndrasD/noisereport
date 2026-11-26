"""Extract a measurement period into Parquet snapshots + SHA-256 manifest."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from src.db import connect, make_engine
from src.timeutil import to_utc_interval

_ROOT = Path(__file__).resolve().parents[1]

# Deterministic column order per extract table (SELECT only).
TABLE_SPECS: dict[str, dict[str, Any]] = {
    "sound_sample": {
        "schema": "noise_monitor",
        "sql": """
            SELECT measured_at, sample_id, device_id, sensor_id, session_id,
                   level_db, weighting, time_weighting, measurement_mode,
                   quality_flags, decoder_version, device_time, received_at
            FROM noise_monitor.sound_sample
            WHERE measured_at >= :start AND measured_at < :end
            ORDER BY measured_at, sample_id
        """,
        "time_filter": "measured_at",
    },
    "fft_band": {
        "schema": "noise_monitor",
        "sql": """
            SELECT measured_at, band_id, device_id,
                   fft_window_measured_at, fft_window_id,
                   band_label, f_low_hz, f_high_hz, level_db, power,
                   quality_flags
            FROM noise_monitor.fft_band
            WHERE measured_at >= :start AND measured_at < :end
            ORDER BY measured_at, band_id
        """,
        "time_filter": "measured_at",
    },
    "fft_window": {
        "schema": "noise_monitor",
        "sql": """
            SELECT measured_at, window_id, device_id, sensor_id, session_id,
                   sample_rate_hz, window_size, window_function, overlap_ratio,
                   quality_flags, metadata, spectrum_db,
                   device_time, received_at
            FROM noise_monitor.fft_window
            WHERE measured_at >= :start AND measured_at < :end
            ORDER BY measured_at, window_id
        """,
        "time_filter": "measured_at",
    },
    "manual_observations": {
        "schema": "noise_monitor",
        "sql": """
            SELECT observation_id, device_id, observed_at, observation,
                   note, session_id, created_at
            FROM noise_monitor.manual_observations
            WHERE observed_at >= :start AND observed_at < :end
            ORDER BY observed_at, observation_id
        """,
        "time_filter": "observed_at",
    },
    "minute_stat": {
        "schema": "noise_report",
        "sql": """
            SELECT measured_at, minute_stat_id, device_id, run_id, metric_method,
                   laeq_db, lmax_db, lmin_db, l10_db, l50_db, l90_db,
                   coverage_ratio, sample_count, quality_summary
            FROM noise_report.minute_stat
            WHERE measured_at >= :start AND measured_at < :end
            ORDER BY measured_at, minute_stat_id
        """,
        "time_filter": "measured_at",
    },
    "gps_fix": {
        "schema": "noise_monitor",
        # Overlapping intervals with [start, end)
        "sql": """
            SELECT measured_at, fix_id, device_id, sensor_id, session_id,
                   valid_from, valid_to, latitude, longitude, altitude_m,
                   speed_m_s, course_deg, hdop, satellites, fix_quality,
                   gps_time, quality_flags, device_time, received_at
            FROM noise_monitor.gps_fix
            WHERE valid_from < :end
              AND (valid_to IS NULL OR valid_to > :start)
            ORDER BY measured_at, fix_id
        """,
        "time_filter": "interval_overlap",
    },
    "environment_sample": {
        "schema": "noise_monitor",
        "sql": """
            SELECT measured_at, sample_id, device_id, sensor_id, session_id,
                   valid_from, valid_to, temperature_c, relative_humidity,
                   pressure_hpa, source, quality_flags, device_time, received_at
            FROM noise_monitor.environment_sample
            WHERE valid_from < :end
              AND (valid_to IS NULL OR valid_to > :start)
            ORDER BY measured_at, sample_id
        """,
        "time_filter": "interval_overlap",
    },
}


@dataclass(frozen=True)
class ExtractResult:
    snapshot_dir: Path
    manifest_path: Path
    extract_hash: str
    row_counts: dict[str, int]


def load_config(path: Path | None = None) -> dict[str, Any]:
    cfg_path = path or (_ROOT / "config.yaml")
    with cfg_path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _snapshot_name(start_utc: datetime, end_utc: datetime) -> str:
    def fmt(dt: datetime) -> str:
        return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    return f"{fmt(start_utc)}_{fmt(end_utc)}"


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """Make Parquet writes more deterministic across runs."""
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = pd.to_datetime(out[col], utc=True)
    return out


def fetch_table(
    conn: Connection,
    table: str,
    start_utc: datetime,
    end_utc: datetime,
) -> tuple[pd.DataFrame, str]:
    spec = TABLE_SPECS[table]
    sql = text(spec["sql"])
    df = pd.read_sql(sql, conn, params={"start": start_utc, "end": end_utc})
    return _normalize_df(df), " ".join(spec["sql"].split())


def run_extract(
    start_local: str,
    end_local: str,
    *,
    engine: Engine | None = None,
    snapshots_dir: Path | None = None,
    tables: list[str] | None = None,
    config: dict[str, Any] | None = None,
) -> ExtractResult:
    cfg = config or load_config()
    tz_name = cfg.get("timezone", "Europe/Budapest")
    start_utc, end_utc = to_utc_interval(start_local, end_local, tz_name=tz_name)

    table_list = tables or list(cfg.get("extract", {}).get("tables", TABLE_SPECS.keys()))
    for t in table_list:
        if t not in TABLE_SPECS:
            raise KeyError(f"unknown extract table: {t}")

    base = snapshots_dir or (_ROOT / cfg.get("paths", {}).get("snapshots_dir", "snapshots"))
    snap = base / _snapshot_name(start_utc, end_utc)
    snap.mkdir(parents=True, exist_ok=True)

    files: dict[str, Any] = {}
    row_counts: dict[str, int] = {}
    eng = engine or make_engine()

    print(
        f"[extract] {start_local} → {end_local}  "
        f"({start_utc.isoformat()} → {end_utc.isoformat()} UTC)",
        flush=True,
    )
    print(f"[extract] snapshot: {snap}", flush=True)

    with connect(eng) as conn:
        for i, table in enumerate(table_list, start=1):
            print(
                f"[extract] ({i}/{len(table_list)}) lekérdezés: {table} …",
                flush=True,
            )
            df, sql_norm = fetch_table(conn, table, start_utc, end_utc)
            path = snap / f"{table}.parquet"
            print(
                f"[extract] ({i}/{len(table_list)}) írás: {table} "
                f"({len(df)} sor) …",
                flush=True,
            )
            # Fixed engine options for reproducibility
            df.to_parquet(path, index=False, engine="pyarrow", compression="zstd")
            digest = sha256_file(path)
            row_counts[table] = int(len(df))
            files[table] = {
                "path": path.name,
                "rows": row_counts[table],
                "sha256": digest,
                "sql": sql_norm,
            }
            print(
                f"[extract] ({i}/{len(table_list)}) kész: {table}  "
                f"sha256={digest[:12]}…",
                flush=True,
            )

    # Aggregate extract hash: sorted table digests
    agg = hashlib.sha256()
    for table in sorted(files):
        agg.update(table.encode())
        agg.update(b":")
        agg.update(files[table]["sha256"].encode())
        agg.update(b"\n")
    extract_hash = agg.hexdigest()

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "timezone": tz_name,
        "start_local": start_local,
        "end_local": end_local,
        "start_utc": start_utc.isoformat(),
        "end_utc": end_utc.isoformat(),
        "interval": "[start, end)",
        "tables": files,
        "extract_sha256": extract_hash,
        "row_counts": row_counts,
    }
    manifest_path = snap / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return ExtractResult(
        snapshot_dir=snap,
        manifest_path=manifest_path,
        extract_hash=extract_hash,
        row_counts=row_counts,
    )
