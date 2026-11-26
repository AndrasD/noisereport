"""Operating regularity: heatmap and cycle statistics."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


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


def duty_heatmap(
    events: pd.DataFrame,
    *,
    out_path: Path,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> Path:
    """Fraction of each local hour that the machine was on (date × hour)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    start = pd.Timestamp(start).tz_convert("Europe/Budapest")
    end = pd.Timestamp(end).tz_convert("Europe/Budapest")

    # Build minute grid
    minutes = pd.date_range(start.floor("min"), end.floor("min"), freq="min", inclusive="left")
    on = np.zeros(len(minutes), dtype=bool)
    if not events.empty:
        for _, ev in events.iterrows():
            s = pd.Timestamp(ev["started_at"]).tz_convert("Europe/Budapest")
            e = pd.Timestamp(ev["ended_at"]).tz_convert("Europe/Budapest")
            on |= (minutes >= s) & (minutes < e)

    df = pd.DataFrame({"ts": minutes, "on": on})
    df["date"] = df["ts"].dt.date
    df["hour"] = df["ts"].dt.hour
    pivot = df.groupby(["date", "hour"])["on"].mean().unstack("hour").reindex(columns=range(24))

    fig, ax = plt.subplots(figsize=(10, max(2.5, 0.35 * len(pivot))), dpi=120)
    if pivot.empty:
        ax.text(0.5, 0.5, "Nincs esemény", ha="center", va="center", transform=ax.transAxes)
    else:
        im = ax.imshow(pivot.values, aspect="auto", cmap="Reds", vmin=0, vmax=1, interpolation="nearest")
        ax.set_xticks(range(24))
        ax.set_xticklabels([str(h) for h in range(24)], fontsize=7)
        ax.set_yticks(range(len(pivot.index)))
        ax.set_yticklabels([str(d) for d in pivot.index], fontsize=8)
        ax.set_xlabel("óra (Europe/Budapest)")
        fig.colorbar(im, ax=ax, fraction=0.02, pad=0.02, label="üzemarány")
        # Emphasize night hours (22–06)
        ax.axvspan(-0.5, 5.5, color="#c62828", alpha=0.08, zorder=0)
        ax.axvspan(21.5, 23.5, color="#c62828", alpha=0.08, zorder=0)
    ax.set_title("Üzemelési mintázat (dátum × óra) — piros = gép jár", fontsize=11, fontweight="bold", color="#b71c1c")
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
    e["local_date"] = pd.to_datetime(e["started_at"], utc=True).dt.tz_convert("Europe/Budapest").dt.date
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
