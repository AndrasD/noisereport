"""PDF report: thin daily LAeq slice + analysis chapters (8–11)."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

from src import __version__
from src.charts import day_night_laeq_charts
from src.detect import run_detection
from src.limits import evaluate_limits
from src.metrics import minute_stats_from_sound, period_stats, sustained_peak_db
from src.regularity import cycle_summary, duty_heatmap, events_to_frame
from src.spectrum import (
    dominant_hz_histogram,
    mean_third_octave,
    spectrum_difference_chart,
)

_ROOT = Path(__file__).resolve().parents[1]


def load_config(path: Path | None = None) -> dict[str, Any]:
    with (path or _ROOT / "config.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def git_commit() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return out or "unknown"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def format_period_display(start_local: str, end_local: str) -> str:
    """Human-readable local period, e.g. 2026.11.23. 08:00 – 2026.11.25. 13:00."""

    def _one(raw: str) -> str:
        text = raw.strip().replace("T", " ")
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(text, fmt)
                if fmt == "%Y-%m-%d":
                    return dt.strftime("%Y.%m.%d.")
                return dt.strftime("%Y.%m.%d. %H:%M")
            except ValueError:
                continue
        return raw

    return f"{_one(start_local)}  –  {_one(end_local)}"


@dataclass
class ReportPaths:
    pdf_path: Path
    html_path: Path
    chart_day_path: Path
    chart_night_path: Path


def build_thin_report(
    snapshot_dir: Path,
    *,
    config: dict[str, Any] | None = None,
    output_dir: Path | None = None,
    with_analysis: bool = True,
) -> ReportPaths:
    cfg = config or load_config()
    snap = Path(snapshot_dir)
    manifest = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))
    sound = pd.read_parquet(snap / "sound_sample.parquet")
    minutes = minute_stats_from_sound(sound)

    limits_block = cfg.get("limits", {})
    limits = limits_block.get("limits_dba") or cfg.get("limits_dba", {})
    day_limit = float(limits.get("day", 50))
    night_limit = float(limits.get("night", 40))
    legal_source = limits_block.get(
        "legal_source", "27/2008. (XII. 3.) KvVM–EüM"
    )
    legal_url = limits_block.get(
        "legal_url", "https://net.jogtar.hu/jogszabaly?docid=a0800027.kvv"
    )
    protected_area = limits_block.get(
        "protected_area",
        "Lakóterület (kisvárosias, kertvárosias beépítésű)",
    )
    assessment = limits_block.get("assessment", {})
    assess_day = assessment.get("day_window", "8h")
    assess_night = assessment.get("night_window", "30min")

    out_root = Path(output_dir or cfg.get("paths", {}).get("output_dir", "output"))
    stamp = snap.name
    work = out_root / f"report_{stamp}"
    work.mkdir(parents=True, exist_ok=True)

    print(f"[report] mutatók / nappali+éjjeli ábra… ({len(sound)} hangminta)", flush=True)
    chart_day_path, chart_night_path = day_night_laeq_charts(
        minutes,
        work_dir=work,
        day_limit=day_limit,
        night_limit=night_limit,
        start_local=manifest["start_local"],
        end_local=manifest["end_local"],
    )

    overall = period_stats(sound)
    day = period_stats(sound, day_only=True)
    night = period_stats(sound, day_only=False)

    def fmt_stats(s, *, limit: float | None = None, peak_db: float | None = None):
        if s is None:
            return None
        over = None if limit is None else s.laeq_db > limit
        exceed = None if limit is None else round(s.laeq_db - limit, 1)
        # Display peak = max 1-minute LAeq (not raw sample max / short spikes)
        display_peak = round(peak_db, 1) if peak_db is not None else round(s.laeq_db, 1)
        return {
            "laeq_db": round(s.laeq_db, 1),
            "l10_db": round(s.l10_db, 1),
            "l50_db": round(s.l50_db, 1),
            "l90_db": round(s.l90_db, 1),
            "lmax_db": display_peak,
            "sample_count": s.sample_count,
            "over_limit": over,
            "exceedance_db": exceed,
            "limit_db": limit,
        }

    daily_rows = []
    if not sound.empty:
        s2 = sound.copy()
        s2["measured_at"] = pd.to_datetime(s2["measured_at"], utc=True)
        s2["local_date"] = s2["measured_at"].dt.tz_convert("Europe/Budapest").dt.date
        for d, grp in s2.groupby("local_date"):
            st = period_stats(grp)
            if st is None:
                continue
            peak = sustained_peak_db(grp)
            over = st.laeq_db > day_limit
            daily_rows.append(
                {
                    "date": str(d),
                    "laeq_db": round(st.laeq_db, 1),
                    "l10_db": round(st.l10_db, 1),
                    "l50_db": round(st.l50_db, 1),
                    "l90_db": round(st.l90_db, 1),
                    "lmax_db": round(peak, 1) if peak is not None else round(st.laeq_db, 1),
                    "sample_count": st.sample_count,
                    "over_limit": over,
                    "exceedance_db": round(st.laeq_db - day_limit, 1),
                }
            )

    overall_fmt = fmt_stats(
        overall, limit=day_limit, peak_db=sustained_peak_db(sound)
    )
    day_fmt = fmt_stats(
        day, limit=day_limit, peak_db=sustained_peak_db(sound, day_only=True)
    )
    night_fmt = fmt_stats(
        night, limit=night_limit, peak_db=sustained_peak_db(sound, day_only=False)
    )

    # Alert banner — plain language for a non-expert lawyer
    alert_over = False
    alert_bits: list[str] = []
    max_exceed = None
    measured_day = day_fmt["laeq_db"] if day_fmt else None
    measured_night = night_fmt["laeq_db"] if night_fmt else None
    if day_fmt and day_fmt["over_limit"]:
        alert_over = True
        alert_bits.append(
            f"Nappal a mért átlagzaj {day_fmt['laeq_db']:.1f} dB — "
            f"a megengedett {day_limit:.0f} dB-nél "
            f"{day_fmt['exceedance_db']:.1f} dB-lel hangosabb."
        )
        max_exceed = day_fmt["exceedance_db"]
    if night_fmt and night_fmt["over_limit"]:
        alert_over = True
        alert_bits.append(
            f"Éjjel a mért átlagzaj {night_fmt['laeq_db']:.1f} dB — "
            f"a megengedett {night_limit:.0f} dB-nél "
            f"{night_fmt['exceedance_db']:.1f} dB-lel hangosabb."
        )
        max_exceed = (
            night_fmt["exceedance_db"]
            if max_exceed is None
            else max(max_exceed, night_fmt["exceedance_db"])
        )
    if not minutes.empty:
        m = minutes.copy()
        m["measured_at"] = pd.to_datetime(m["measured_at"], utc=True)
        from src.metrics import is_day_local as _is_day

        lims = m["measured_at"].map(
            lambda ts: day_limit if _is_day(ts.to_pydatetime()) else night_limit
        )
        deltas = m["laeq_db"].astype(float) - lims.astype(float)
        if (deltas > 0).any():
            alert_over = True
            over_mins = int((deltas > 0).sum())
            # Do NOT fold 1-minute spike peaks into headline max_exceed
            alert_bits.append(
                f"Percenkénti bontásban {over_mins} perc volt a határérték felett."
            )

    analysis: dict[str, Any] = {
        "enabled": False,
        "event_count": 0,
        "measure_hours": 0.0,
        "on_hours": 0.0,
        "on_ratio_pct": 0.0,
        "cycle": None,
        "limit_summary": [],
        "assessment_rows": [],
        "sensitivity": [],
        "sensitivity_assessment": [],
        "heatmap_uri": None,
        "spectrum_uri": None,
        "dominant_uri": None,
        "limit_note": None,
    }

    if with_analysis:
        print("[report] üzemészlelés + elemző fejezetek…", flush=True)
        events, score, _ = run_detection(snap)
        ev_dicts = [
            {
                "started_at": e.started_at.isoformat(),
                "ended_at": e.ended_at.isoformat() if e.ended_at else None,
            }
            for e in events
            if e.ended_at is not None
        ]
        ev_df = events_to_frame(ev_dicts)
        heatmap = duty_heatmap(
            ev_df,
            out_path=work / "heatmap.png",
            start=manifest["start_utc"],
            end=manifest["end_utc"],
        )
        fft_band = (
            pd.read_parquet(snap / "fft_band.parquet")
            if (snap / "fft_band.parquet").exists()
            else pd.DataFrame()
        )
        fft_window = (
            pd.read_parquet(snap / "fft_window.parquet")
            if (snap / "fft_window.parquet").exists()
            else pd.DataFrame()
        )
        bands = mean_third_octave(fft_band, ev_df)
        spectrum_path = spectrum_difference_chart(bands, out_path=work / "spectrum.png")
        dominant_path = dominant_hz_histogram(
            fft_window, ev_df, out_path=work / "dominant_hz.png"
        )
        lim = evaluate_limits(sound, day_limit=day_limit, night_limit=night_limit)
        # Headline max exceedance: only regulatory assessment windows
        # (night 30 min, day 8 h) — not short 1-minute spikes.
        limit_summary = list(lim.get("summary") or [])
        assessment_rows = list(lim.get("assessment_rows") or [])
        for r in assessment_rows:
            if r.get("max_exceedance_db") and r["max_exceedance_db"] > 0:
                alert_over = True
                max_exceed = (
                    float(r["max_exceedance_db"])
                    if max_exceed is None
                    else max(max_exceed, float(r["max_exceedance_db"]))
                )

        start_utc = pd.Timestamp(manifest["start_utc"])
        end_utc = pd.Timestamp(manifest["end_utc"])
        measure_hours = max((end_utc - start_utc).total_seconds() / 3600.0, 0.0)
        cycle = cycle_summary(ev_df)
        on_hours = float(cycle.get("total_on_hours") or 0.0)
        on_ratio = (on_hours / measure_hours) if measure_hours > 0 else 0.0

        analysis = {
            "enabled": True,
            "event_count": len(events),
            "measure_hours": round(measure_hours, 2),
            "on_hours": round(on_hours, 2),
            "on_ratio_pct": round(100.0 * on_ratio, 1),
            "cycle": cycle,
            "limit_summary": limit_summary,
            "assessment_rows": assessment_rows,
            "sensitivity": lim["sensitivity"],
            "sensitivity_assessment": [
                row for row in lim["sensitivity"] if row.get("is_assessment")
            ],
            "limit_note": lim["note"],
            "heatmap_uri": heatmap.resolve().as_uri(),
            "spectrum_uri": spectrum_path.resolve().as_uri(),
            "dominant_uri": dominant_path.resolve().as_uri(),
            "events": [
                {
                    "started_at": e.started_at.isoformat(),
                    "ended_at": e.ended_at.isoformat() if e.ended_at else None,
                    "duration_min": round(
                        (e.ended_at - e.started_at).total_seconds() / 60.0, 1
                    )
                    if e.ended_at
                    else None,
                }
                for e in events[:50]
            ],
        }

    report_id = f"NR-{stamp}"
    extract_short = manifest.get("extract_sha256", "")[:12]
    ctx = {
        "report_id": report_id,
        "version": __version__,
        "git_commit": git_commit(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "start_local": manifest["start_local"],
        "end_local": manifest["end_local"],
        "period_display": format_period_display(
            manifest["start_local"], manifest["end_local"]
        ),
        "extract_sha256_short": extract_short,
        "extract_sha256": manifest.get("extract_sha256"),
        "metric_method": cfg.get("metric_method", ""),
        "day_limit": day_limit,
        "night_limit": night_limit,
        "legal_source": legal_source,
        "legal_url": legal_url,
        "protected_area": protected_area,
        "assess_day": assess_day,
        "assess_night": assess_night,
        "overall": overall_fmt,
        "day": day_fmt,
        "night": night_fmt,
        "daily_rows": daily_rows,
        "chart_day_uri": chart_day_path.resolve().as_uri(),
        "chart_night_uri": chart_night_path.resolve().as_uri(),
        "analysis": analysis,
        "alert": {
            "over": alert_over,
            "title": "A mért zaj meghaladja a megengedett szintet",
            "plain_verdict": (
                "A mért zaj többször is hangosabb, mint amit a rendelet "
                "kisvárosias/kertvárosias lakóterületre nappal/éjjel megenged. "
                "A piros kiemelések ezt mutatják."
                if alert_over
                else "Ebben az időszakban a számított átlagok a beállított "
                "határértékek alatt maradtak."
            ),
            "max_exceedance_db": None if max_exceed is None else round(max_exceed, 1),
            "max_exceedance_basis": (
                "nappali/éjjeli átlag és rendeleti megítélési ablakok "
                "(nappal 8 óra, éjjel 30 perc) — rövid 1 perces kilengés nélkül"
            ),
            "bits": alert_bits,
            "allowed_day": day_limit,
            "allowed_night": night_limit,
            "measured_day": measured_day,
            "measured_night": measured_night,
            "limits_line": (
                f"Jogszabály: {legal_source} · terület: {protected_area} · "
                f"nappal max. {day_limit:.0f} dB · éjjel max. {night_limit:.0f} dB"
            ),
        },
        "disclaimer": (
            "Ez a dokumentum a zajjal érintett (elszenvedő) fél mérési "
            "összefoglalója ügyvédi áttekintéshez. Nem akkreditált laboratóriumi "
            "jegyzőkönyv. A számok PeakTech kijelzős mintákból számított "
            f"energetikus LAeq értékek. A {day_limit:.0f}/{night_limit:.0f} dB "
            f"a {legal_source} 1. melléklet szerinti L_TH irányérték "
            f"({protected_area}). A rendelet hivatalosan L_AM megítélési szintet "
            "ír elő; a piros kiemelés a mért LAeq és az L_TH egyszerű összevetése."
        ),
    }

    env = Environment(
        loader=FileSystemLoader(str(_ROOT / cfg.get("paths", {}).get("templates_dir", "templates"))),
        autoescape=select_autoescape(["html", "xml"]),
    )
    html = env.get_template("report.html").render(**ctx)
    html_path = work / "report.html"
    html_path.write_text(html, encoding="utf-8")

    print("[report] WeasyPrint PDF render…", flush=True)
    pdf_path = work / "report.pdf"
    HTML(string=html, base_url=str(work)).write_pdf(pdf_path)
    print("[report] kész.", flush=True)

    return ReportPaths(
        pdf_path=pdf_path,
        html_path=html_path,
        chart_day_path=chart_day_path,
        chart_night_path=chart_night_path,
    )
