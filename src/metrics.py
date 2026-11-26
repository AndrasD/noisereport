"""Energetic LAeq and percentile metrics from sound samples."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

import pandas as pd

BUDAPEST = ZoneInfo("Europe/Budapest")


def energetic_laeq(levels: Sequence[float]) -> float:
    if not levels:
        raise ValueError("no levels")
    mean_lin = sum(10.0 ** (x / 10.0) for x in levels) / len(levels)
    return 10.0 * math.log10(mean_lin)


def percentile_db(levels: Sequence[float], q: float) -> float:
    """q in [0, 1]; linear interpolation on sorted dB values (not energetic)."""
    if not levels:
        raise ValueError("no levels")
    ordered = sorted(levels)
    if len(ordered) == 1:
        return ordered[0]
    pos = q * (len(ordered) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    frac = pos - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


@dataclass(frozen=True)
class LevelStats:
    laeq_db: float
    lmax_db: float
    lmin_db: float
    l10_db: float
    l50_db: float
    l90_db: float
    sample_count: int


def level_stats(levels: Sequence[float]) -> LevelStats:
    if not levels:
        raise ValueError("no levels")
    return LevelStats(
        laeq_db=energetic_laeq(levels),
        lmax_db=max(levels),
        lmin_db=min(levels),
        # Acoustic convention: L10 = level exceeded 10% of time ≈ high end
        l10_db=percentile_db(levels, 0.90),
        l50_db=percentile_db(levels, 0.50),
        l90_db=percentile_db(levels, 0.10),
        sample_count=len(levels),
    )


def is_day_local(ts: datetime, *, day_start: time = time(6, 0), day_end: time = time(22, 0)) -> bool:
    local = ts.astimezone(BUDAPEST)
    t = local.time()
    return day_start <= t < day_end


def night_date_local(ts: datetime) -> datetime.date:
    """Assign night samples after 22:00 to the calendar date that started the night."""
    local = ts.astimezone(BUDAPEST)
    if local.time() >= time(22, 0):
        return local.date()
    if local.time() < time(6, 0):
        return (local - timedelta(days=1)).date()
    return local.date()


def minute_stats_from_sound(sound: pd.DataFrame) -> pd.DataFrame:
    """Compute per-minute LAeq/percentiles from sound_sample parquet frame."""
    if sound.empty:
        return pd.DataFrame(
            columns=[
                "measured_at",
                "laeq_db",
                "lmax_db",
                "lmin_db",
                "l10_db",
                "l50_db",
                "l90_db",
                "sample_count",
                "is_day",
            ]
        )

    df = sound.copy()
    df["measured_at"] = pd.to_datetime(df["measured_at"], utc=True)
    df["level_db"] = pd.to_numeric(df["level_db"], errors="coerce")
    df = df.dropna(subset=["level_db"])
    df["minute"] = df["measured_at"].dt.floor("min")

    rows = []
    for minute, grp in df.groupby("minute", sort=True):
        levels = grp["level_db"].astype(float).tolist()
        stats = level_stats(levels)
        ts = minute.to_pydatetime()
        rows.append(
            {
                "measured_at": minute,
                "laeq_db": round(stats.laeq_db, 2),
                "lmax_db": round(stats.lmax_db, 2),
                "lmin_db": round(stats.lmin_db, 2),
                "l10_db": round(stats.l10_db, 2),
                "l50_db": round(stats.l50_db, 2),
                "l90_db": round(stats.l90_db, 2),
                "sample_count": stats.sample_count,
                "is_day": is_day_local(ts),
            }
        )
    return pd.DataFrame(rows)


def period_stats(
    sound: pd.DataFrame,
    *,
    day_only: bool | None = None,
) -> LevelStats | None:
    if sound.empty:
        return None
    df = sound.copy()
    df["measured_at"] = pd.to_datetime(df["measured_at"], utc=True)
    df["level_db"] = pd.to_numeric(df["level_db"], errors="coerce")
    df = df.dropna(subset=["level_db"])
    if day_only is True:
        mask = df["measured_at"].map(lambda t: is_day_local(t.to_pydatetime()))
        df = df.loc[mask]
    elif day_only is False:
        mask = df["measured_at"].map(lambda t: not is_day_local(t.to_pydatetime()))
        df = df.loc[mask]
    levels = df["level_db"].astype(float).tolist()
    if not levels:
        return None
    return level_stats(levels)


def sustained_peak_db(sound: pd.DataFrame, *, day_only: bool | None = None) -> float | None:
    """Peak for display: max of 1-minute LAeq (ignores very short sample spikes)."""
    if sound.empty:
        return None
    df = sound.copy()
    if day_only is True:
        df["measured_at"] = pd.to_datetime(df["measured_at"], utc=True)
        df = df.loc[df["measured_at"].map(lambda t: is_day_local(t.to_pydatetime()))]
    elif day_only is False:
        df["measured_at"] = pd.to_datetime(df["measured_at"], utc=True)
        df = df.loc[df["measured_at"].map(lambda t: not is_day_local(t.to_pydatetime()))]
    minutes = minute_stats_from_sound(df)
    if minutes.empty:
        return None
    return float(minutes["laeq_db"].max())
