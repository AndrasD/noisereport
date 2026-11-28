"""Operating regularity: heatmap and cycle statistics."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.metrics import is_day_local, level_stats


def events_to_frame(events: list[dict]) -> pd.DataFrame:
    if not events:
        return pd.DataFrame(columns=["started_at", "ended_at", "duration_s"])
    rows = []
    for ev in events:
        start = pd.Timestamp(ev["started_at"])
        end = pd.Timestamp(ev["ended_at"])
        rows.append(
            {
                "started_at": start,
                "ended_at": end,
                "duration_s": (end - start).total_seconds(),
            }
        )
    return pd.DataFrame(rows)


def _data_minute_mask(
    minutes_index: pd.DatetimeIndex,
    sound_times: pd.Series | None,
    *,
    max_data_gap: pd.Timedelta = pd.Timedelta(minutes=5),
) -> np.ndarray:
    """True where the minute falls inside a stretch that has sound samples."""
    has = np.zeros(len(minutes_index), dtype=bool)
    if sound_times is None or len(sound_times) == 0:
        return has
    times = pd.DatetimeIndex(pd.to_datetime(sound_times, utc=True)).sort_values()
    times = times.tz_convert("Europe/Budapest")
    # Mark minutes that contain at least one sample (floor to minute)
    sample_mins = times.floor("min").unique()
    minute_set = set(sample_mins)
    for i, m in enumerate(minutes_index):
        if m in minute_set:
            has[i] = True
    # Also fill short gaps inside continuous segments (same as chart segment logic)
    if len(times) < 2:
        return has
    seg_start = times[0]
    prev = times[0]
    segments: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for t in times[1:]:
        if t - prev > max_data_gap:
            segments.append((seg_start, prev))
            seg_start = t
        prev = t
    segments.append((seg_start, prev))
    for a, b in segments:
        has |= (minutes_index >= a.floor("min")) & (minutes_index <= b.floor("min"))
    return has


def clip_events_to_data(
    events: pd.DataFrame,
    sound_times: pd.Series | None,
    *,
    max_data_gap: pd.Timedelta = pd.Timedelta(minutes=5),
) -> pd.DataFrame:
    """Split/clip detector events so they do not span measurement outages."""
    if events is None or events.empty:
        return events_to_frame([])
    if sound_times is None or len(sound_times) == 0:
        return events_to_frame([])

    times = list(pd.DatetimeIndex(pd.to_datetime(sound_times, utc=True)).sort_values())
    segments: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    seg_start = times[0]
    prev = times[0]
    for t in times[1:]:
        if t - prev > max_data_gap:
            segments.append((seg_start, prev))
            seg_start = t
        prev = t
    segments.append((seg_start, prev))

    rows = []
    for _, ev in events.iterrows():
        s = pd.Timestamp(ev["started_at"])
        e = pd.Timestamp(ev["ended_at"])
        if s.tzinfo is None:
            s = s.tz_localize("UTC")
        if e.tzinfo is None:
            e = e.tz_localize("UTC")
        for a, b in segments:
            left = max(s, a)
            right = min(e, b)
            if right <= left:
                continue
            rows.append(
                {
                    "started_at": left,
                    "ended_at": right,
                    "duration_s": (right - left).total_seconds(),
                }
            )
    return pd.DataFrame(rows) if rows else events_to_frame([])


def valid_measure_hours_from_minutes(minutes: pd.DataFrame) -> float:
    """Hours with at least one 1-minute LAeq row (valid measurement time)."""
    if minutes is None or minutes.empty:
        return 0.0
    return float(len(minutes)) / 60.0


def on_hours_clipped(events: pd.DataFrame) -> float:
    if events is None or events.empty:
        return 0.0
    return float(events["duration_s"].sum()) / 3600.0


def duty_heatmap(
    events: pd.DataFrame,
    *,
    out_path: Path,
    start: pd.Timestamp,
    end: pd.Timestamp,
    sound_times: pd.Series | None = None,
) -> Path:
    """Fraction of each local hour that the machine was on (date × hour).

    Cells with no sound data are shown separately (grey), not as 0% on.
    Events are clipped to data-bearing stretches when ``sound_times`` is given.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    start = pd.Timestamp(start).tz_convert("Europe/Budapest")
    end = pd.Timestamp(end).tz_convert("Europe/Budapest")

    clipped = clip_events_to_data(events, sound_times) if sound_times is not None else events

    minutes = pd.date_range(start.floor("min"), end.floor("min"), freq="min", inclusive="left")
    has_data = _data_minute_mask(minutes, sound_times)
    on = np.zeros(len(minutes), dtype=bool)
    if clipped is not None and not clipped.empty:
        for _, ev in clipped.iterrows():
            s = pd.Timestamp(ev["started_at"]).tz_convert("Europe/Budapest")
            e = pd.Timestamp(ev["ended_at"]).tz_convert("Europe/Budapest")
            on |= (minutes >= s) & (minutes < e)
    on &= has_data

    df = pd.DataFrame({"ts": minutes, "on": on, "has": has_data})
    df["date"] = df["ts"].dt.date
    df["hour"] = df["ts"].dt.hour

    # duty among minutes that have data; NaN where no data in that hour-cell
    def _cell(grp: pd.DataFrame) -> float:
        if not grp["has"].any():
            return np.nan
        return float(grp.loc[grp["has"], "on"].mean())

    pivot = (
        df.groupby(["date", "hour"], sort=True)
        .apply(_cell, include_groups=False)
        .unstack("hour")
        .reindex(columns=range(24))
    )

    fig, ax = plt.subplots(figsize=(10, max(2.5, 0.35 * max(len(pivot), 1))), dpi=120)
    if pivot.empty:
        ax.text(0.5, 0.5, "Nincs esemény", ha="center", va="center", transform=ax.transAxes)
    else:
        cmap = plt.cm.Reds.copy().with_extremes(bad="#e0e0e0")
        im = ax.imshow(
            np.ma.masked_invalid(pivot.values.astype(float)),
            aspect="auto",
            cmap=cmap,
            vmin=0,
            vmax=1,
            interpolation="nearest",
        )
        ax.set_xticks(range(24))
        ax.set_xticklabels([str(h) for h in range(24)], fontsize=7)
        ax.set_yticks(range(len(pivot.index)))
        ax.set_yticklabels([str(d) for d in pivot.index], fontsize=8)
        ax.set_xlabel("óra (helyi idő)")
        cbar = fig.colorbar(im, ax=ax, fraction=0.02, pad=0.02)
        cbar.set_label("gép jár (arány, ahol van adat)")
        ax.axvspan(-0.5, 5.5, color="#c62828", alpha=0.08, zorder=0)
        ax.axvspan(21.5, 23.5, color="#c62828", alpha=0.08, zorder=0)
        ax.text(
            0.0,
            -0.18,
            "szürke = nincs mérési adat abban az órában",
            transform=ax.transAxes,
            fontsize=8,
            color="#555",
        )
    ax.set_title(
        "Üzemelési mintázat (dátum × óra) — piros = gép jár",
        fontsize=11,
        fontweight="bold",
        color="#b71c1c",
    )
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def cycle_summary(events: pd.DataFrame) -> dict:
    if events.empty:
        return {
            "event_count": 0,
            "total_on_hours": 0.0,
            "mean_cycle_min": None,
            "median_cycle_min": None,
            "per_day": [],
        }
    e = events.copy()
    e["local_date"] = pd.to_datetime(e["started_at"], utc=True).dt.tz_convert(
        "Europe/Budapest"
    ).dt.date
    per_day = []
    for d, grp in e.groupby("local_date"):
        per_day.append(
            {
                "date": str(d),
                "cycles": int(len(grp)),
                "on_hours": round(float(grp["duration_s"].sum()) / 3600.0, 2),
            }
        )
    return {
        "event_count": int(len(e)),
        "total_on_hours": round(float(e["duration_s"].sum()) / 3600.0, 2),
        "mean_cycle_min": round(float(e["duration_s"].mean()) / 60.0, 2),
        "median_cycle_min": round(float(e["duration_s"].median()) / 60.0, 2),
        "per_day": per_day,
    }


def _format_duration_minutes(total_min: int) -> str:
    if total_min < 1:
        return "0 mp"
    h, m = divmod(int(total_min), 60)
    if h and m:
        return f"{h} óra {m} perc"
    if h:
        return f"{h} óra"
    return f"{m} perc"


def on_off_period_stats(
    minutes: pd.DataFrame,
    events: pd.DataFrame,
) -> list[dict]:
    """Day/night × machine on/off from the same 1-minute LAeq grid as coverage.

    Durations are exact minute counts (not event-duration sums), so
    day_on + night_on equals total on-time used in the operating ratio.
    """
    if minutes is None or minutes.empty:
        return []
    df = minutes.copy()
    df["measured_at"] = pd.to_datetime(df["measured_at"], utc=True)
    level_col = "laeq_db" if "laeq_db" in df.columns else "level_db"
    if level_col not in df.columns:
        return []
    df["level_db"] = pd.to_numeric(df[level_col], errors="coerce")
    df = df.dropna(subset=["level_db"]).sort_values("measured_at")
    if df.empty:
        return []

    on = pd.Series(False, index=df.index)
    if events is not None and not events.empty:
        for _, ev in events.iterrows():
            s = pd.Timestamp(ev["started_at"])
            e = pd.Timestamp(ev["ended_at"])
            if s.tzinfo is None:
                s = s.tz_localize("UTC")
            if e.tzinfo is None:
                e = e.tz_localize("UTC")
            on |= (df["measured_at"] >= s) & (df["measured_at"] < e)
    df["on"] = on
    df["is_day"] = df["measured_at"].map(lambda ts: is_day_local(ts.to_pydatetime()))

    rows = []
    for is_day, period_label in ((True, "Nappal (06–22)"), (False, "Éjjel (22–06)")):
        for is_on, state_label in ((True, "Gép jár"), (False, "Gép nem jár")):
            grp = df.loc[(df["is_day"] == is_day) & (df["on"] == is_on)]
            if grp.empty:
                rows.append(
                    {
                        "period": period_label,
                        "state": state_label,
                        "laeq_db": None,
                        "l90_db": None,
                        "sample_count": 0,
                        "minutes_approx": 0,
                        "duration_hm": "0 mp",
                    }
                )
                continue
            levels = grp["level_db"].astype(float).tolist()
            st = level_stats(levels)
            mins = int(len(grp))
            rows.append(
                {
                    "period": period_label,
                    "state": state_label,
                    "laeq_db": round(st.laeq_db, 1),
                    "l90_db": round(st.l90_db, 1),
                    "sample_count": mins,
                    "minutes_approx": mins,
                    "duration_hm": _format_duration_minutes(mins),
                }
            )
    return rows


def on_hours_from_on_off_rows(rows: list[dict]) -> float:
    """Total machine-on hours from on/off table rows (same basis as the table)."""
    total_min = sum(
        int(r.get("minutes_approx") or 0)
        for r in rows
        if r.get("state") == "Gép jár"
    )
    return total_min / 60.0
