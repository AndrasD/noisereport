"""Matplotlib chart helpers — exceedances rendered in bold red."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.metrics import is_day_local

RED = "#c62828"
RED_FILL = "#e53935"
DARK = "#212121"


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


def minute_laeq_chart(
    minutes: pd.DataFrame,
    *,
    out_path: Path,
    limit_db: float,
    title: str,
    period: str = "all",
    day_limit: float | None = None,
    night_limit: float | None = None,
) -> Path:
    """Draw 1-minute LAeq chart.

    ``period``:
      - ``day``: only 06–22 local, single day limit line
      - ``night``: only 22–06 local, single night limit line
      - ``all``: whole series (legacy); uses day_limit/night_limit if given
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 3.4), dpi=140)

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
        # Align limits with gap breaks (repeat limit, nan at breaks)
        lim_plot = np.full(len(y_plot), limit, dtype=float)
        lim_plot[np.isnan(y_plot)] = np.nan
        if period == "all" and day_limit is not None and night_limit is not None:
            # rebuild limits on unbroken series then break
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
        )
        ax.plot(t_plot, y_plot, color=DARK, linewidth=1.5, label="1 perces LAeq", zorder=3)
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
        )
        if period == "all" and night_limit is not None:
            ax.axhline(
                night_limit,
                color="#b71c1c",
                linestyle=":",
                linewidth=2.4,
                label=f"éjjeli határ {night_limit:.0f} dB",
            )
        elif period != "all":
            # single limit already drawn
            pass

        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M", tz=t_local.dt.tz))
        fig.autofmt_xdate(rotation=25, ha="right")
        ax.set_ylabel("dB", fontweight="bold")
        ax.legend(loc="upper right", fontsize=8, framealpha=0.92)
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
) -> tuple[Path, Path]:
    day_path = work_dir / "minute_laeq_day.png"
    night_path = work_dir / "minute_laeq_night.png"
    minute_laeq_chart(
        minutes,
        out_path=day_path,
        limit_db=day_limit,
        period="day",
        title=f"Nappal (06–22) — 1 perces LAeq · határ {day_limit:.0f} dB · {start_local} → {end_local}",
    )
    minute_laeq_chart(
        minutes,
        out_path=night_path,
        limit_db=night_limit,
        period="night",
        title=f"Éjjel (22–06) — 1 perces LAeq · határ {night_limit:.0f} dB · {start_local} → {end_local}",
    )
    return day_path, night_path
