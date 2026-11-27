"""Matplotlib chart helpers — exceedances rendered in bold red."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.metrics import is_day_local, night_date_local

RED = "#c62828"
RED_FILL = "#e53935"
DARK = "#212121"
WINDOW_COLOR = "#1565c0"
ON_COLOR = "#ef6c00"
def _with_gap_breaks(
    t_local: pd.Series,
    y: np.ndarray,
    *,
    max_gap: pd.Timedelta = pd.Timedelta(minutes=2),
) -> tuple[pd.DatetimeIndex, np.ndarray]:
    """Insert NaNs so the line does not connect across day/night gaps."""
    if len(t_local) == 0:
        return t_local, y
    times = list(t_local)
    vals = list(y.astype(float))
    out_t: list = [times[0]]
    out_y: list[float] = [vals[0]]
    for i in range(1, len(times)):
        if times[i] - times[i - 1] > max_gap:
            out_t.append(times[i - 1] + max_gap / 2)
            out_y.append(np.nan)
        out_t.append(times[i])
        out_y.append(vals[i])
    return pd.DatetimeIndex(out_t), np.array(out_y, dtype=float)


def _to_local_ts(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert("Europe/Budapest")


def _draw_machine_on_bands(
    ax,
    events: pd.DataFrame | None,
    *,
    x_min: pd.Timestamp,
    x_max: pd.Timestamp,
    data_times: pd.Series | None = None,
    max_data_gap: pd.Timedelta = pd.Timedelta(minutes=5),
) -> bool:
    """Orange vertical bands where the detector says the machine was on.

    Bands are clipped to stretches that actually have plotted samples, so a
    long detected event cannot paint across a measurement outage.
    """
    if events is None or events.empty:
        return False

    segments = _data_segments(
        data_times, x_min=x_min, x_max=x_max, max_data_gap=max_data_gap
    )

    drawn = False
    for _, ev in events.iterrows():
        s = _to_local_ts(ev["started_at"])
        e = _to_local_ts(ev["ended_at"])
        if e <= x_min or s >= x_max:
            continue
        for seg_a, seg_b in segments:
            left = max(s, x_min, seg_a)
            right = min(e, x_max, seg_b)
            if right <= left:
                continue
            ax.axvspan(
                left,
                right,
                color=ON_COLOR,
                alpha=0.18,
                zorder=0,
                linewidth=0,
            )
            drawn = True
    return drawn


def _data_segments(
    data_times: pd.Series | None,
    *,
    x_min: pd.Timestamp,
    x_max: pd.Timestamp,
    max_data_gap: pd.Timedelta = pd.Timedelta(minutes=5),
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    if data_times is None or len(data_times) == 0:
        return [(x_min, x_max)]
    times = list(pd.DatetimeIndex(data_times).sort_values())
    segments: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    seg_start = times[0]
    prev = times[0]
    for t in times[1:]:
        if t - prev > max_data_gap:
            segments.append((seg_start, prev))
            seg_start = t
        prev = t
    segments.append((seg_start, prev))
    return segments


def _draw_assessment_window(
    ax,
    *,
    window_start: str | None,
    window_end: str | None,
    window_label: str | None,
    x_min: pd.Timestamp,
    x_max: pd.Timestamp,
    data_times: pd.Series | None = None,
) -> bool:
    if not window_start or not window_end:
        return False
    s = _to_local_ts(window_start)
    e = _to_local_ts(window_end)
    if e <= x_min or s >= x_max:
        return False
    segments = _data_segments(data_times, x_min=x_min, x_max=x_max)
    drawn = False
    label = window_label or "rendeleti megítélési ablak"
    for seg_a, seg_b in segments:
        left = max(s, x_min, seg_a)
        right = min(e, x_max, seg_b)
        if right <= left:
            continue
        ax.axvspan(
            left,
            right,
            color=WINDOW_COLOR,
            alpha=0.22,
            zorder=1,
            linewidth=0,
            label=label if not drawn else None,
        )
        ax.axvline(left, color=WINDOW_COLOR, linewidth=1.4, linestyle="-")
        ax.axvline(right, color=WINDOW_COLOR, linewidth=1.4, linestyle="-")
        drawn = True
    return drawn


def minute_laeq_chart(
    minutes: pd.DataFrame,
    *,
    out_path: Path,
    limit_db: float,
    title: str,
    period: str = "all",
    day_limit: float | None = None,
    night_limit: float | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    window_label: str | None = None,
    events: pd.DataFrame | None = None,
) -> Path:
    """Draw 1-minute LAeq chart.

    ``period``:
      - ``day``: only 06–22 local, single day limit line
      - ``night``: only 22–06 local, single night limit line
      - ``all``: whole series (legacy); uses day_limit/night_limit if given

    Optional overlays:
      - assessment window (blue band)
      - machine-on events (orange bands)
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 3.5), dpi=140)

    df = minutes.copy()
    if df.empty:
        ax.text(0.5, 0.5, "Nincs adat", ha="center", va="center", transform=ax.transAxes)
        ax.set_title(title, fontsize=11, fontweight="bold", color=DARK)
        fig.tight_layout()
        fig.savefig(out_path, bbox_inches="tight")
        plt.close(fig)
        return out_path

    df["measured_at"] = pd.to_datetime(df["measured_at"], utc=True)
    df["laeq_db"] = pd.to_numeric(df["laeq_db"], errors="coerce")
    df = df.dropna(subset=["laeq_db"]).sort_values("measured_at")

    if period == "day":
        mask = df["measured_at"].map(lambda ts: is_day_local(ts.to_pydatetime()))
        df = df.loc[mask]
        limit = float(limit_db)
        limit_label = f"nappali határ {limit:.0f} dB"
    elif period == "night":
        mask = df["measured_at"].map(lambda ts: not is_day_local(ts.to_pydatetime()))
        df = df.loc[mask]
        limit = float(limit_db)
        limit_label = f"éjjeli határ {limit:.0f} dB"
    else:
        limit = float(limit_db)
        limit_label = f"határ {limit:.0f} dB"

    if df.empty:
        ax.text(
            0.5,
            0.5,
            "Nincs adat ebben a napszakban",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
    else:
        t = df["measured_at"]
        t_local = t.dt.tz_convert("Europe/Budapest")
        y = df["laeq_db"].astype(float).to_numpy()
        x_min = t_local.iloc[0]
        x_max = t_local.iloc[-1]

        on_drawn = _draw_machine_on_bands(
            ax,
            events,
            x_min=x_min,
            x_max=x_max,
            data_times=t_local,
        )
        win_drawn = _draw_assessment_window(
            ax,
            window_start=window_start,
            window_end=window_end,
            window_label=window_label,
            x_min=x_min,
            x_max=x_max,
            data_times=t_local,
        )
        if on_drawn:
            # Proxy legend entry (bands themselves are many)
            ax.axvspan(
                x_min,
                x_min,
                color=ON_COLOR,
                alpha=0.35,
                label="gép jár (detektált)",
            )

        if period == "all" and day_limit is not None and night_limit is not None:
            limits = np.array(
                [
                    day_limit if is_day_local(ts.to_pydatetime()) else night_limit
                    for ts in t
                ]
            )
        else:
            limits = np.full(len(y), limit, dtype=float)

        t_plot, y_plot = _with_gap_breaks(t_local, y)
        lim_plot = np.full(len(y_plot), limit, dtype=float)
        lim_plot[np.isnan(y_plot)] = np.nan
        if period == "all" and day_limit is not None and night_limit is not None:
            lim_raw = limits
            _, lim_plot = _with_gap_breaks(t_local, lim_raw)

        over = (~np.isnan(y_plot)) & (~np.isnan(lim_plot)) & (y_plot > lim_plot)

        ax.fill_between(
            t_plot,
            lim_plot,
            y_plot,
            where=over,
            interpolate=True,
            color=RED_FILL,
            alpha=0.45,
            label="határérték felett",
            zorder=2,
        )
        ax.plot(
            t_plot,
            y_plot,
            color=DARK,
            linewidth=1.5,
            label="1 perces LAeq",
            zorder=3,
        )
        if over.any():
            ax.scatter(
                t_plot[over],
                y_plot[over],
                s=16,
                color=RED,
                zorder=4,
                label="túllépés",
            )

        ax.axhline(
            limit if period != "all" else (day_limit or limit),
            color=RED,
            linestyle="--",
            linewidth=2.2,
            label=limit_label if period != "all" else f"nappali határ {day_limit:.0f} dB",
            zorder=2,
        )
        if period == "all" and night_limit is not None:
            ax.axhline(
                night_limit,
                color="#b71c1c",
                linestyle=":",
                linewidth=2.4,
                label=f"éjjeli határ {night_limit:.0f} dB",
            )

        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M", tz=t_local.dt.tz))
        fig.autofmt_xdate(rotation=25, ha="right")
        ax.set_ylabel("dB", fontweight="bold")
        # Outside the axes so the curve / overlays stay readable.
        ax.legend(
            loc="upper center",
            bbox_to_anchor=(0.5, -0.34),
            ncol=3,
            fontsize=7.5,
            frameon=True,
            fancybox=False,
            edgecolor="#9e9e9e",
            framealpha=0.95,
            columnspacing=1.2,
            handlelength=1.8,
        )
        ax.grid(True, alpha=0.3)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        if over.any():
            max_over = float((y_plot[over] - lim_plot[over]).max())
            ax.text(
                0.01,
                0.98,
                f"MAX TÚLLÉPÉS: +{max_over:.1f} dB",
                transform=ax.transAxes,
                va="top",
                ha="left",
                fontsize=11,
                fontweight="bold",
                color="white",
                bbox=dict(boxstyle="round,pad=0.35", facecolor=RED, edgecolor="none"),
            )
        _ = (win_drawn, on_drawn)

    ax.set_title(title, fontsize=11, fontweight="bold", color=DARK)
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def day_night_laeq_charts(
    minutes: pd.DataFrame,
    *,
    work_dir: Path,
    day_limit: float,
    night_limit: float,
    start_local: str,
    end_local: str,
    day_window: dict | None = None,
    night_window: dict | None = None,
    events: pd.DataFrame | None = None,
) -> tuple[Path, Path]:
    day_path = work_dir / "minute_laeq_day.png"
    night_path = work_dir / "minute_laeq_night.png"
    day_window = day_window or {}
    night_window = night_window or {}
    minute_laeq_chart(
        minutes,
        out_path=day_path,
        limit_db=day_limit,
        period="day",
        title=(
            f"Nappal (06–22) — 1 perces LAeq · határ {day_limit:.0f} dB · "
            f"{start_local} → {end_local}"
        ),
        window_start=day_window.get("worst_start"),
        window_end=day_window.get("worst_end"),
        window_label="legzajosabb 8 óra (rendelet)",
        events=events,
    )
    minute_laeq_chart(
        minutes,
        out_path=night_path,
        limit_db=night_limit,
        period="night",
        title=(
            f"Éjjel (22–06) — 1 perces LAeq · határ {night_limit:.0f} dB · "
            f"{start_local} → {end_local}"
        ),
        window_start=night_window.get("worst_start"),
        window_end=night_window.get("worst_end"),
        window_label="legzajosabb 30 perc (rendelet)",
        events=events,
    )
    return day_path, night_path


def night_exceedance_stats(
    minutes: pd.DataFrame,
    *,
    night_limit: float,
) -> pd.DataFrame:
    """Per night-date: minutes over limit and max exceedance (dB)."""
    if minutes is None or minutes.empty:
        return pd.DataFrame(
            columns=["night_date", "minutes_over", "max_exceedance_db", "mean_over_db"]
        )
    df = minutes.copy()
    df["measured_at"] = pd.to_datetime(df["measured_at"], utc=True)
    df["laeq_db"] = pd.to_numeric(df["laeq_db"], errors="coerce")
    df = df.dropna(subset=["laeq_db"])
    night = df.loc[
        ~df["measured_at"].map(lambda ts: is_day_local(ts.to_pydatetime()))
    ].copy()
    if night.empty:
        return pd.DataFrame(
            columns=["night_date", "minutes_over", "max_exceedance_db", "mean_over_db"]
        )
    night["night_date"] = night["measured_at"].map(
        lambda ts: night_date_local(ts.to_pydatetime())
    )
    night["exceedance"] = night["laeq_db"].astype(float) - float(night_limit)
    rows = []
    for d, grp in night.groupby("night_date"):
        over = grp.loc[grp["exceedance"] > 0]
        rows.append(
            {
                "night_date": d,
                "minutes_over": int(len(over)),
                "max_exceedance_db": (
                    round(float(over["exceedance"].max()), 1) if len(over) else 0.0
                ),
                "mean_over_db": (
                    round(float(over["exceedance"].mean()), 1) if len(over) else 0.0
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("night_date").reset_index(drop=True)


def night_exceedance_chart(
    minutes: pd.DataFrame,
    *,
    out_path: Path,
    night_limit: float,
) -> tuple[Path, list[dict]]:
    """Bar chart: minutes over night limit per night (+ max ΔdB labels)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    stats = night_exceedance_stats(minutes, night_limit=night_limit)
    rows = stats.to_dict(orient="records") if not stats.empty else []

    fig, ax = plt.subplots(figsize=(10, 3.4), dpi=140)
    if stats.empty:
        ax.text(
            0.5,
            0.5,
            "Nincs éjjeli adat",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
    else:
        labels = [
            f"{r['night_date'].strftime('%m.%d.')} éjjel"
            if hasattr(r["night_date"], "strftime")
            else f"{r['night_date']} éjjel"
            for r in rows
        ]
        mins = [int(r["minutes_over"]) for r in rows]
        colors = [RED if m > 0 else "#9e9e9e" for m in mins]
        bars = ax.bar(labels, mins, color=colors, edgecolor=DARK, linewidth=0.6)
        for bar, r in zip(bars, rows):
            if r["minutes_over"] <= 0:
                continue
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height(),
                f"+{r['max_exceedance_db']:.1f} dB",
                ha="center",
                va="bottom",
                fontsize=8,
                fontweight="bold",
                color=RED,
            )
        ax.set_ylabel("perc a határ felett", fontweight="bold")
        ax.set_ylim(0, max(mins + [1]) * 1.25)
        ax.grid(True, axis="y", alpha=0.3)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    ax.set_title(
        f"Éjszakai túllépés — hány perc volt {night_limit:.0f} dB felett "
        f"(felirat = max ΔdB az éjjel)",
        fontsize=11,
        fontweight="bold",
        color=DARK,
    )
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)

    serializable = []
    for r in rows:
        serializable.append(
            {
                "night_date": str(r["night_date"]),
                "minutes_over": int(r["minutes_over"]),
                "max_exceedance_db": float(r["max_exceedance_db"]),
                "mean_over_db": float(r["mean_over_db"]),
            }
        )
    return out_path, serializable


def _env_temp_frame(env: pd.DataFrame) -> pd.DataFrame:
    if env is None or env.empty or "temperature_c" not in env.columns:
        return pd.DataFrame(columns=["measured_at", "temperature_c"])
    df = env.copy()
    df["measured_at"] = pd.to_datetime(df["measured_at"], utc=True)
    df["temperature_c"] = pd.to_numeric(df["temperature_c"], errors="coerce")
    return df.dropna(subset=["temperature_c"]).sort_values("measured_at")


def mean_temp_in_interval(
    env: pd.DataFrame,
    start: pd.Timestamp | str,
    end: pd.Timestamp | str,
) -> float | None:
    """Mean outdoor °C during [start, end]; nearest sample if none inside."""
    df = _env_temp_frame(env)
    if df.empty:
        return None
    s = pd.Timestamp(start)
    e = pd.Timestamp(end)
    if s.tzinfo is None:
        s = s.tz_localize("UTC")
    if e.tzinfo is None:
        e = e.tz_localize("UTC")
    chunk = df[(df["measured_at"] >= s) & (df["measured_at"] <= e)]
    if not chunk.empty:
        return round(float(chunk["temperature_c"].mean()), 1)
    # nearest sample to midpoint
    mid = s + (e - s) / 2
    idx = (df["measured_at"] - mid).abs().idxmin()
    return round(float(df.loc[idx, "temperature_c"]), 1)


def outdoor_temperature_summary(
    env: pd.DataFrame,
    *,
    events: pd.DataFrame | None = None,
) -> dict | None:
    """Min/max/mean outdoor temperature from environment_sample."""
    df = _env_temp_frame(env)
    if df.empty:
        return None
    local = df["measured_at"].dt.tz_convert("Europe/Budapest")
    source = None
    if "source" in env.columns and env["source"].notna().any():
        source = str(env["source"].dropna().iloc[0])
    out: dict = {
        "n": int(len(df)),
        "t_min_c": round(float(df["temperature_c"].min()), 1),
        "t_max_c": round(float(df["temperature_c"].max()), 1),
        "t_mean_c": round(float(df["temperature_c"].mean()), 1),
        "t_on_mean_c": None,
        "start_local": local.iloc[0].strftime("%Y.%m.%d. %H:%M"),
        "end_local": local.iloc[-1].strftime("%Y.%m.%d. %H:%M"),
        "source": source,
    }
    if events is not None and not events.empty:
        on_vals: list[float] = []
        for _, ev in events.iterrows():
            if pd.isna(ev.get("ended_at")):
                continue
            t = mean_temp_in_interval(df, ev["started_at"], ev["ended_at"])
            if t is not None:
                on_vals.append(t)
        if on_vals:
            out["t_on_mean_c"] = round(float(sum(on_vals) / len(on_vals)), 1)
    return out
