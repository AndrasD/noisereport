"""Spectral analysis helpers from fft_band / fft_window extracts."""

from __future__ import annotations

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
        return pd.DataFrame(columns=["band_label", "f_center_hz", "on_db", "off_db", "delta_db"])

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
        ax.text(0.5, 0.5, "Nincs spektrumadat", ha="center", va="center", transform=ax.transAxes)
    else:
        x = bands["f_center_hz"].astype(float)
        ax.semilogx(x, bands["on_db"], label="üzem", color="#c45c26")
        ax.semilogx(x, bands["off_db"], label="nem üzem", color="#1f4e79")
        if bands["delta_db"].notna().any():
            ax.semilogx(x, bands["delta_db"], label="különbség", color="#2a7f62", linestyle="--")
        ax.set_xlabel("Hz")
        ax.set_ylabel("dB")
        ax.grid(True, which="both", alpha=0.25)
        ax.legend(fontsize=8)
    ax.set_title("Átlag 1/3 oktáv spektrum — üzem vs nem üzem")
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def dominant_hz_histogram(fft_window: pd.DataFrame, events: pd.DataFrame, *, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 3.0), dpi=120)
    if fft_window.empty:
        ax.text(0.5, 0.5, "Nincs FFT ablak", ha="center", va="center", transform=ax.transAxes)
    else:
        f = fft_window.copy()
        f["measured_at"] = pd.to_datetime(f["measured_at"], utc=True)

        def _dom(meta):
            if isinstance(meta, dict):
                return meta.get("dominant_hz")
            return None

        f["dominant_hz"] = f["metadata"].map(_dom) if "metadata" in f.columns else None
        f["dominant_hz"] = pd.to_numeric(f["dominant_hz"], errors="coerce")
        f = f.dropna(subset=["dominant_hz"])
        f["on"] = _mask_on(f["measured_at"], events)
        on = f.loc[f["on"], "dominant_hz"]
        off = f.loc[~f["on"], "dominant_hz"]
        bins = np.linspace(0, max(200, float(f["dominant_hz"].max())), 40)
        if len(on):
            ax.hist(on, bins=bins, alpha=0.65, label="üzem", color="#c45c26")
        if len(off):
            ax.hist(off, bins=bins, alpha=0.45, label="nem üzem", color="#1f4e79")
        ax.legend(fontsize=8)
        ax.set_xlabel("domináns Hz")
        ax.set_ylabel("darab")
    ax.set_title("Domináns frekvencia eloszlás")
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path
