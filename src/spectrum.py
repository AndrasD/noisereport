"""Spectral analysis helpers from fft_band / fft_window extracts."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def _mask_on(ts: pd.Series, events: pd.DataFrame) -> pd.Series:
    on = pd.Series(False, index=ts.index)
    if events.empty:
        return on
    for _, ev in events.iterrows():
        s = pd.Timestamp(ev["started_at"])
        e = pd.Timestamp(ev["ended_at"])
        on |= (ts >= s) & (ts < e)
    return on


def mean_third_octave(
    fft_band: pd.DataFrame,
    events: pd.DataFrame,
) -> pd.DataFrame:
    if fft_band.empty:
        return pd.DataFrame(
            columns=["band_label", "f_center_hz", "on_db", "off_db", "delta_db"]
        )

    df = fft_band.copy()
    df["measured_at"] = pd.to_datetime(df["measured_at"], utc=True)
    df["level_db"] = pd.to_numeric(df["level_db"], errors="coerce")
    df["f_low_hz"] = pd.to_numeric(df["f_low_hz"], errors="coerce")
    df["f_high_hz"] = pd.to_numeric(df["f_high_hz"], errors="coerce")
    df = df.dropna(subset=["level_db", "f_low_hz", "f_high_hz"])
    df["on"] = _mask_on(df["measured_at"], events)
    df["f_center_hz"] = np.sqrt(df["f_low_hz"] * df["f_high_hz"])

    rows = []
    for label, grp in df.groupby("band_label", sort=False):
        on = grp.loc[grp["on"], "level_db"]
        off = grp.loc[~grp["on"], "level_db"]
        on_db = float(on.mean()) if len(on) else None
        off_db = float(off.mean()) if len(off) else None
        delta = (on_db - off_db) if on_db is not None and off_db is not None else None
        rows.append(
            {
                "band_label": label,
                "f_center_hz": float(grp["f_center_hz"].median()),
                "on_db": on_db,
                "off_db": off_db,
                "delta_db": delta,
            }
        )
    out = pd.DataFrame(rows).sort_values("f_center_hz")
    return out


def spectrum_difference_chart(bands: pd.DataFrame, *, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 3.4), dpi=120)
    if bands.empty or bands["on_db"].isna().all():
        ax.text(
            0.5,
            0.5,
            "Nincs spektrumadat",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
    else:
        x = bands["f_center_hz"].astype(float)
        ax.semilogx(x, bands["on_db"], label="gép jár", color="#c45c26")
        ax.semilogx(x, bands["off_db"], label="gép nem jár", color="#1f4e79")
        if bands["delta_db"].notna().any():
            ax.semilogx(
                x,
                bands["delta_db"],
                label="különbség",
                color="#2a7f62",
                linestyle="--",
            )
        ax.set_xlabel("Hz")
        ax.set_ylabel("relatív hangosság")
        ax.grid(True, which="both", alpha=0.25)
        ax.legend(fontsize=8)
        ax.axvline(50, color="#888", linestyle=":", linewidth=1, alpha=0.8)
        ax.text(
            50,
            ax.get_ylim()[1],
            " 50 Hz",
            fontsize=7,
            color="#666",
            va="top",
        )
    ax.set_title(
        "Hangmagasság-összehasonlítás (relatív) — gép jár vs nem jár",
        fontsize=11,
    )
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def _dominant_hz(meta) -> float | None:
    if isinstance(meta, dict):
        v = meta.get("dominant_hz")
        return float(v) if v is not None else None
    if isinstance(meta, str) and meta.strip():
        try:
            parsed = json.loads(meta)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict) and parsed.get("dominant_hz") is not None:
            return float(parsed["dominant_hz"])
    return None


def dominant_hz_histogram(
    fft_window: pd.DataFrame, events: pd.DataFrame, *, out_path: Path
) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 3.0), dpi=120)
    if fft_window.empty:
        ax.text(
            0.5, 0.5, "Nincs FFT ablak", ha="center", va="center", transform=ax.transAxes
        )
    else:
        f = fft_window.copy()
        f["measured_at"] = pd.to_datetime(f["measured_at"], utc=True)
        f["dominant_hz"] = (
            f["metadata"].map(_dominant_hz) if "metadata" in f.columns else None
        )
        f["dominant_hz"] = pd.to_numeric(f["dominant_hz"], errors="coerce")
        f = f.dropna(subset=["dominant_hz"])
        f["on"] = _mask_on(f["measured_at"], events)
        on = f.loc[f["on"], "dominant_hz"].to_numpy()
        off = f.loc[~f["on"], "dominant_hz"].to_numpy()
        hi = max(200.0, float(f["dominant_hz"].max()) if len(f) else 200.0)
        bins = np.linspace(0, hi, 60)

        def _pct_hist(vals: np.ndarray, **kwargs):
            if len(vals) == 0:
                return
            weights = np.full(len(vals), 100.0 / len(vals))
            ax.hist(vals, bins=bins, weights=weights, **kwargs)

        _pct_hist(on, alpha=0.65, label="gép jár", color="#c45c26")
        _pct_hist(off, alpha=0.45, label="gép nem jár", color="#1f4e79")
        ax.legend(fontsize=8)
        ax.set_xlabel("domináns hangmagasság (Hz)")
        ax.set_ylabel("% az osztályon belül")
        ax.axvline(50, color="#888", linestyle=":", linewidth=1, alpha=0.8)
    ax.set_title("Domináns hangmagasság — arányos eloszlás")
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path
