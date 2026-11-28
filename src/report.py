"""PDF report: thin daily slice + full lawyer-facing structure (step 12)."""

from __future__ import annotations

import src.macos_libs  # noqa: F401  — before WeasyPrint (Homebrew dylib path)

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
from src.charts import (
    day_night_laeq_charts,
    night_exceedance_chart,
    mean_temp_in_interval,
    outdoor_temperature_summary,
)
from src.detect import run_detection
from src.findings import (
    GLOSSARY,
    LIMITATIONS,
    build_findings,
    resolve_summary_type,
    summary_type_label,
)
from src.limits import evaluate_limits
from src.metrics import minute_stats_from_sound, period_stats, sustained_peak_db
from src.qc import run_qc
from src.regularity import (
    clip_events_to_data,
    cycle_summary,
    duty_heatmap,
    events_to_frame,
    on_hours_from_on_off_rows,
    on_off_period_stats,
    valid_measure_hours_from_minutes,
)
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


def _fmt_stats(s, *, limit: float | None = None, peak_db: float | None = None):
    if s is None:
        return None
    over = None if limit is None else s.laeq_db > limit
    exceed = None if limit is None else round(s.laeq_db - limit, 1)
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


def _local_display(value: str | datetime | pd.Timestamp) -> str:
    """Local Europe/Budapest time as YYYY.MM.DD HH:MM."""
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    local = ts.tz_convert("Europe/Budapest")
    return local.strftime("%Y.%m.%d %H:%M")


def format_hours_minutes(hours: float | None) -> str:
    """e.g. 64.9 → '64 óra 54 perc'; under 1 min → 'N mp'."""
    if hours is None:
        return "—"
    total_sec = int(round(float(hours) * 3600.0))
    if total_sec < 0:
        total_sec = 0
    if total_sec < 60:
        return f"{total_sec} mp"
    total_min = total_sec // 60
    h, m = divmod(total_min, 60)
    if h and m:
        return f"{h} óra {m} perc"
    if h:
        return f"{h} óra"
    return f"{m} perc"


def format_minutes_hm(minutes: float | None) -> str:
    """e.g. 162.1 → '2 óra 42 perc'; 0.3 → '18 mp'."""
    if minutes is None:
        return "—"
    return format_hours_minutes(float(minutes) / 60.0)


def _build_timeline(
    *,
    manifest: dict[str, Any],
    qc_gaps: list[Any],
    events: list[dict[str, Any]],
    summary_type: str,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = [
        {
            "when": _local_display(manifest["start_utc"]),
            "kind": "Mérés kezdete",
            "detail": f"Időszak kezdete (helyi): {manifest['start_local']}",
        },
        {
            "when": _local_display(manifest["end_utc"]),
            "kind": "Mérés vége (intervallum vége)",
            "detail": f"Félig nyitott vége (helyi): {manifest['end_local']}",
        },
    ]
    # Significant gaps only (≥ 60 s) to keep the table readable
    big_gaps = [g for g in qc_gaps if float(getattr(g, "duration_s", 0) or 0) >= 60.0]
    cap = 15 if summary_type == "weekly" else 8
    for g in big_gaps[:cap]:
        rows.append(
            {
                "when": _local_display(g.start),
                "kind": "Adatkiesés",
                "detail": (
                    f"{_local_display(g.start)} – {_local_display(g.end)} "
                    f"({float(g.duration_s):.0f} s)"
                ),
            }
        )
    if len(big_gaps) > cap:
        rows.append(
            {
                "when": "—",
                "kind": "Adatkiesés (további)",
                "detail": f"Még {len(big_gaps) - cap} kiesés ≥ 60 s a mérésben.",
            }
        )

    ev_cap = 12 if summary_type == "weekly" else 8
    for ev in events[:ev_cap]:
        if not ev.get("ended_at"):
            continue
        rows.append(
            {
                "when": _local_display(ev["started_at"]),
                "kind": "Gépüzem (detektált)",
                "detail": (
                    f"{_local_display(ev['started_at'])} – "
                    f"{_local_display(ev['ended_at'])} "
                    f"({ev.get('duration_min', '—')} perc)"
                ),
            }
        )
    if len(events) > ev_cap:
        rows.append(
            {
                "when": "—",
                "kind": "Gépüzem (további)",
                "detail": f"Összesen {len(events)} szakasz — teljes lista a mellékletben.",
            }
        )

    def _sort_key(r: dict[str, str]) -> str:
        return r["when"] if r["when"] != "—" else "9999"

    rows.sort(key=_sort_key)
    return rows


def _compute_report_bundle(
    snapshot_dir: Path,
    *,
    config: dict[str, Any] | None = None,
    output_dir: Path | None = None,
    with_analysis: bool = True,
) -> tuple[dict[str, Any], Path, Path, Path]:
    """Shared metrics/charts/analysis for thin and full layouts.

    Returns (ctx_core, work_dir, chart_day_path, chart_night_path).
    """
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

    site = cfg.get("site") or {}
    instrument = cfg.get("instrument") or {}

    out_root = Path(output_dir or cfg.get("paths", {}).get("output_dir", "output"))
    stamp = snap.name
    work = out_root / f"report_{stamp}"
    work.mkdir(parents=True, exist_ok=True)

    overall = period_stats(sound)
    day = period_stats(sound, day_only=True)
    night = period_stats(sound, day_only=False)

    # Whole-period LAeq has no single decree limit (day 50 / night 40 differ) —
    # keep as info only, never mark IRÁNYÉRTÉK FELETT against the daytime limit.
    overall_fmt = _fmt_stats(
        overall, limit=None, peak_db=sustained_peak_db(sound)
    )
    day_fmt = _fmt_stats(
        day, limit=day_limit, peak_db=sustained_peak_db(sound, day_only=True)
    )
    night_fmt = _fmt_stats(
        night, limit=night_limit, peak_db=sustained_peak_db(sound, day_only=False)
    )

    alert_over = False
    alert_bits: list[str] = []
    max_exceed = None
    measured_day = day_fmt["laeq_db"] if day_fmt else None
    measured_night = night_fmt["laeq_db"] if night_fmt else None
    if day_fmt and day_fmt["over_limit"]:
        alert_over = True
        alert_bits.append(
            f"Nappal a mért átlagzaj {day_fmt['laeq_db']:.1f} dB — "
            f"az irányérték {day_limit:.0f} dB-nél "
            f"{day_fmt['exceedance_db']:.1f} dB-lel hangosabb."
        )
        max_exceed = day_fmt["exceedance_db"]
    if night_fmt and night_fmt["over_limit"]:
        alert_over = True
        alert_bits.append(
            f"Éjjel a mért átlagzaj {night_fmt['laeq_db']:.1f} dB — "
            f"az irányérték {night_limit:.0f} dB-nél "
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
            alert_bits.append(
                f"Percenkénti bontásban {over_mins} perc volt a határérték felett."
            )

    analysis: dict[str, Any] = {
        "enabled": False,
        "event_count": 0,
        "measure_hours": 0.0,
        "measure_hm": "0 perc",
        "wall_hours": 0.0,
        "wall_hm": "0 perc",
        "valid_measure_hours": 0.0,
        "valid_measure_hm": "0 perc",
        "on_hours": 0.0,
        "on_hm": "0 perc",
        "on_day_hm": "—",
        "on_night_hm": "—",
        "on_ratio_pct": 0.0,
        "cycle": None,
        "limit_summary": [],
        "assessment_rows": [],
        "sensitivity": [],
        "sensitivity_assessment": [],
        "quietest_night_window_db": None,
        "quietest_day_window_db": None,
        "heatmap_uri": None,
        "spectrum_uri": None,
        "dominant_uri": None,
        "night_exceedance_uri": None,
        "night_exceedance_rows": [],
        "temperature": None,
        "limit_note": None,
        "events": [],
        "detector_version": None,
        "on_off_rows": [],
    }

    day_window: dict[str, Any] | None = None
    night_window: dict[str, Any] | None = None
    ev_df = events_to_frame([])

    if with_analysis:
        print("[report] üzemészlelés + határablakok…", flush=True)
        events, _score, _ = run_detection(snap)
        ev_dicts = [
            {
                "started_at": e.started_at.isoformat(),
                "ended_at": e.ended_at.isoformat() if e.ended_at else None,
            }
            for e in events
            if e.ended_at is not None
        ]
        ev_df = events_to_frame(ev_dicts)
        lim = evaluate_limits(sound, day_limit=day_limit, night_limit=night_limit)
        assessment_rows = list(lim.get("assessment_rows") or [])
        for r in assessment_rows:
            if r.get("window") == "8h_day":
                day_window = r
            elif r.get("window") == "30min_night":
                night_window = r
            if r.get("max_exceedance_db") and r["max_exceedance_db"] > 0:
                alert_over = True
                max_exceed = (
                    float(r["max_exceedance_db"])
                    if max_exceed is None
                    else max(max_exceed, float(r["max_exceedance_db"]))
                )

    env = (
        pd.read_parquet(snap / "environment_sample.parquet")
        if (snap / "environment_sample.parquet").exists()
        else pd.DataFrame()
    )
    temp_summary = outdoor_temperature_summary(
        env, events=ev_df if with_analysis else None
    )

    print(
        f"[report] nappali+éjjeli ábra "
        f"(ablak+üzem overlay)… ({len(sound)} hangminta)",
        flush=True,
    )
    chart_day_path, chart_night_path = day_night_laeq_charts(
        minutes,
        work_dir=work,
        day_limit=day_limit,
        night_limit=night_limit,
        start_local=manifest["start_local"],
        end_local=manifest["end_local"],
        day_window=day_window,
        night_window=night_window,
        events=ev_df if with_analysis else None,
    )
    night_exc_path, night_exc_rows = night_exceedance_chart(
        minutes,
        out_path=work / "night_exceedance.png",
        night_limit=night_limit,
    )
    for row in night_exc_rows:
        row["minutes_over_hm"] = format_minutes_hm(row.get("minutes_over"))
        if row.get("night_date") is not None and hasattr(row["night_date"], "strftime"):
            row["night_date"] = row["night_date"].strftime("%Y.%m.%d.")

    if with_analysis:
        print("[report] spektrum / mintázat…", flush=True)
        sound_times = (
            pd.to_datetime(sound["measured_at"], utc=True)
            if not sound.empty
            else None
        )
        ev_clipped = clip_events_to_data(ev_df, sound_times)
        heatmap = duty_heatmap(
            ev_df,
            out_path=work / "heatmap.png",
            start=manifest["start_utc"],
            end=manifest["end_utc"],
            sound_times=sound_times,
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
        bands = mean_third_octave(fft_band, ev_clipped)
        spectrum_path = spectrum_difference_chart(bands, out_path=work / "spectrum.png")
        dominant_path = dominant_hz_histogram(
            fft_window, ev_clipped, out_path=work / "dominant_hz.png"
        )
        limit_summary = list(lim.get("summary") or [])
        assessment_rows = list(lim.get("assessment_rows") or [])

        start_utc = pd.Timestamp(manifest["start_utc"])
        end_utc = pd.Timestamp(manifest["end_utc"])
        wall_hours = max((end_utc - start_utc).total_seconds() / 3600.0, 0.0)
        valid_hours = valid_measure_hours_from_minutes(minutes)
        cycle = cycle_summary(ev_clipped)
        # Same 1-minute grid as the on/off table → day_on + night_on == on_hm
        on_off_rows = on_off_period_stats(minutes, ev_clipped)
        on_hours = on_hours_from_on_off_rows(on_off_rows)
        on_ratio = (on_hours / valid_hours) if valid_hours > 0 else 0.0
        on_day_hm = next(
            (
                r["duration_hm"]
                for r in on_off_rows
                if r["period"].startswith("Nappal") and r["state"] == "Gép jár"
            ),
            "—",
        )
        on_night_hm = next(
            (
                r["duration_hm"]
                for r in on_off_rows
                if r["period"].startswith("Éjjel") and r["state"] == "Gép jár"
            ),
            "—",
        )

        det_cfg_path = _ROOT / "config" / "detector_1.1.0.yaml"
        det_ver = "1.1.0"
        if det_cfg_path.exists():
            det_cfg = yaml.safe_load(det_cfg_path.read_text(encoding="utf-8")) or {}
            det_ver = str(det_cfg.get("param_version") or det_ver)

        analysis = {
            "enabled": True,
            "event_count": int(cycle.get("event_count") or len(ev_clipped)),
            "measure_hours": round(valid_hours, 2),
            "measure_hm": format_hours_minutes(valid_hours),
            "wall_hours": round(wall_hours, 2),
            "wall_hm": format_hours_minutes(wall_hours),
            "valid_measure_hours": round(valid_hours, 2),
            "valid_measure_hm": format_hours_minutes(valid_hours),
            "on_hours": round(on_hours, 2),
            "on_hm": format_hours_minutes(on_hours),
            "on_day_hm": on_day_hm,
            "on_night_hm": on_night_hm,
            "on_ratio_pct": round(100.0 * on_ratio, 1),
            "cycle": cycle,
            "limit_summary": limit_summary,
            "assessment_rows": assessment_rows,
            "sensitivity": lim["sensitivity"],
            "sensitivity_assessment": [
                row for row in lim["sensitivity"] if row.get("is_assessment")
            ],
            "quietest_night_window_db": lim.get("quietest_night_window_db"),
            "quietest_day_window_db": lim.get("quietest_day_window_db"),
            "limit_note": lim["note"],
            "heatmap_uri": heatmap.resolve().as_uri(),
            "spectrum_uri": spectrum_path.resolve().as_uri(),
            "dominant_uri": dominant_path.resolve().as_uri(),
            "night_exceedance_uri": night_exc_path.resolve().as_uri(),
            "night_exceedance_rows": night_exc_rows,
            "temperature": temp_summary,
            "detector_version": det_ver,
            "on_off_rows": on_off_rows,
            "events": [
                {
                    "started_at": _local_display(e.started_at),
                    "ended_at": _local_display(e.ended_at) if e.ended_at else None,
                    "duration_min": round(
                        (e.ended_at - e.started_at).total_seconds() / 60.0, 1
                    )
                    if e.ended_at
                    else None,
                    "duration_hm": (
                        format_minutes_hm(
                            (e.ended_at - e.started_at).total_seconds() / 60.0
                        )
                        if e.ended_at
                        else "—"
                    ),
                    "temp_c": (
                        mean_temp_in_interval(env, e.started_at, e.ended_at)
                        if e.ended_at is not None
                        else None
                    ),
                }
                for e in events
            ],
        }
    else:
        analysis["night_exceedance_uri"] = night_exc_path.resolve().as_uri()
        analysis["night_exceedance_rows"] = night_exc_rows
        analysis["temperature"] = temp_summary

    report_id = f"NR-{stamp}"
    extract_short = manifest.get("extract_sha256", "")[:12]
    created_at = datetime.now(timezone.utc).isoformat()
    commit = git_commit()

    # Labeled deltas (assessment window vs loudest minute) — do not conflate
    exceedance_items: list[dict[str, Any]] = []
    if day_window and day_window.get("max_exceedance_db") is not None:
        exceedance_items.append(
            {
                "label": "Nappali megítélési ablak (legzajosabb 8 óra)",
                "db": round(float(day_window["max_exceedance_db"]), 1),
            }
        )
    if night_window and night_window.get("max_exceedance_db") is not None:
        exceedance_items.append(
            {
                "label": "Éjjeli megítélési ablak (legzajosabb 30 perc)",
                "db": round(float(night_window["max_exceedance_db"]), 1),
            }
        )
    if day_fmt and day_fmt.get("lmax_db") is not None:
        exceedance_items.append(
            {
                "label": "Nappali leghangosabb perc (átlaghoz képest nem irányérték)",
                "db": round(float(day_fmt["lmax_db"]) - day_limit, 1),
            }
        )
    if night_fmt and night_fmt.get("lmax_db") is not None:
        exceedance_items.append(
            {
                "label": "Éjjeli leghangosabb perc",
                "db": round(float(night_fmt["lmax_db"]) - night_limit, 1),
            }
        )

    night_over = bool(night_window and night_window.get("is_over"))
    day_over = bool(day_window and day_window.get("is_over"))
    if night_over and not day_over:
        alert_title = "Éjjel a mért zaj a rendelet szerinti irányérték felett van"
    elif night_over and day_over:
        alert_title = (
            "Éjjel robusztusan, nappal kisebb mértékben az irányérték felett"
        )
    elif day_over:
        alert_title = "Nappal a mért zaj a rendelet szerinti irányérték felett van"
    elif alert_over:
        alert_title = "A mért zaj a rendelet szerinti irányérték felett van"
    else:
        alert_title = "A mért zaj a rendelet szerinti irányérték alatt / körül maradt"

    alert = {
        "over": alert_over,
        "title": alert_title,
        "plain_verdict": (
            (
                "Éjjel a legzajosabb fél órában, nappal a legzajosabb 8 órában "
                "hasonlítjuk a mért zajt a rendelet irányértékéhez "
                f"(nappal {day_limit:.0f} / éjjel {night_limit:.0f} dB). "
                "Ez mért összzaj, nem hivatalos megítélési szint. "
                "Az éjjeli és nappali eltérés erőssége különbözhet — lásd a "
                "fő megállapításokat és az érzékenységi mellékletet."
            )
            if alert_over
            else (
                "Ebben az időszakban a számított zaj a rendelet irányértékei "
                f"alatt / körül maradt (nappal {day_limit:.0f} / éjjel "
                f"{night_limit:.0f} dB)."
            )
        ),
        "max_exceedance_db": None if max_exceed is None else round(max_exceed, 1),
        "max_exceedance_basis": (
            "A lentebb címkézett eltérések: megítélési ablak vs. leghangosabb perc "
            "— nem ugyanazt mérik."
        ),
        "exceedance_items": exceedance_items,
        "bits": alert_bits,
        "allowed_day": day_limit,
        "allowed_night": night_limit,
        "measured_day": measured_day,
        "measured_night": measured_night,
        "limits_line": (
            f"Jogszabály: {legal_source} · terület: {protected_area} · "
            f"nappal irányérték {day_limit:.0f} dB · éjjel {night_limit:.0f} dB"
        ),
    }

    disclaimer = (
        "Mérési napló / tájékoztató az ügyvédnek: a zajjal érintett "
        "(elszenvedő) fél saját mérései. Nem szakértői vélemény, nem akkreditált "
        "laboratóriumi jegyzőkönyv. A számok a műszer kijelzős mintáiból számított "
        f"átlagos zajszintek. A {day_limit:.0f}/{night_limit:.0f} dB a "
        f"{legal_source} szerinti irányérték ({protected_area}). "
        "A piros kiemelés a mért zaj és az irányérték egyszerű összevetése."
    )

    ctx = {
        "report_id": report_id,
        "version": __version__,
        "git_commit": commit,
        "created_at": created_at,
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
        "chart_day_uri": chart_day_path.resolve().as_uri(),
        "chart_night_uri": chart_night_path.resolve().as_uri(),
        "analysis": analysis,
        "alert": alert,
        "disclaimer": disclaimer,
        "site": site,
        "instrument": instrument,
        "manifest": manifest,
        "snapshot_name": stamp,
    }
    return ctx, work, chart_day_path, chart_night_path


def _render_pdf(
    *,
    template_name: str,
    ctx: dict[str, Any],
    work: Path,
    pdf_name: str,
    html_name: str,
    cfg: dict[str, Any],
) -> tuple[Path, Path]:
    env = Environment(
        loader=FileSystemLoader(
            str(_ROOT / cfg.get("paths", {}).get("templates_dir", "templates"))
        ),
        autoescape=select_autoescape(["html", "xml"]),
    )
    html = env.get_template(template_name).render(**ctx)
    html_path = work / html_name
    html_path.write_text(html, encoding="utf-8")
    print("[report] WeasyPrint PDF render…", flush=True)
    pdf_path = work / pdf_name
    HTML(string=html, base_url=str(work)).write_pdf(pdf_path)
    print("[report] kész.", flush=True)
    return pdf_path, html_path


def build_thin_report(
    snapshot_dir: Path,
    *,
    config: dict[str, Any] | None = None,
    output_dir: Path | None = None,
    with_analysis: bool = True,
) -> ReportPaths:
    """Original 6-page lawyer slice (unchanged template)."""
    cfg = config or load_config()
    ctx, work, chart_day_path, chart_night_path = _compute_report_bundle(
        snapshot_dir,
        config=cfg,
        output_dir=output_dir,
        with_analysis=with_analysis,
    )
    # Thin template expects events capped at 50 (historical behaviour)
    if ctx["analysis"].get("events"):
        ctx = dict(ctx)
        analysis = dict(ctx["analysis"])
        analysis["events"] = analysis["events"][:50]
        ctx["analysis"] = analysis

    pdf_path, html_path = _render_pdf(
        template_name="report.html",
        ctx=ctx,
        work=work,
        pdf_name="report_thin.pdf",
        html_name="report_thin.html",
        cfg=cfg,
    )
    return ReportPaths(
        pdf_path=pdf_path,
        html_path=html_path,
        chart_day_path=chart_day_path,
        chart_night_path=chart_night_path,
    )


def build_full_report(
    snapshot_dir: Path,
    *,
    config: dict[str, Any] | None = None,
    output_dir: Path | None = None,
    with_analysis: bool = True,
    summary_type: str | None = None,
) -> ReportPaths:
    """Step-12 full structure: summary → main → annexes."""
    cfg = config or load_config()
    ctx, work, chart_day_path, chart_night_path = _compute_report_bundle(
        snapshot_dir,
        config=cfg,
        output_dir=output_dir,
        with_analysis=with_analysis,
    )

    report_cfg = cfg.get("report") or {}
    requested = summary_type or report_cfg.get("default_type") or "auto"
    stype = resolve_summary_type(
        ctx["manifest"]["start_utc"],
        ctx["manifest"]["end_utc"],
        requested,
    )

    print("[report] QC + timeline + findings…", flush=True)
    qc = run_qc(snapshot_dir, config=cfg)
    timeline = _build_timeline(
        manifest=ctx["manifest"],
        qc_gaps=qc.gaps,
        events=list(ctx["analysis"].get("events") or []),
        summary_type=stype,
    )
    findings = build_findings(
        alert=ctx["alert"],
        analysis=ctx["analysis"],
        day=ctx["day"],
        night=ctx["night"],
        day_limit=float(ctx["day_limit"]),
        night_limit=float(ctx["night_limit"]),
    )

    events_main_cap = 12 if stype == "weekly" else 8

    full_ctx = dict(ctx)
    full_ctx.update(
        {
            "summary_type": stype,
            "summary_type_label": summary_type_label(stype),
            "findings": findings,
            "timeline": timeline,
            "glossary": GLOSSARY,
            "limitations": LIMITATIONS,
            "qc": {
                "coverage_pct": round(100.0 * qc.coverage_ratio, 1),
                "sound_sample_count": qc.sound_sample_count,
                "duration_hm": format_hours_minutes(qc.duration_minutes / 60.0),
                "gap_count": qc.gap_count_total,
                "gap_hours_hm": format_hours_minutes(qc.gap_seconds_total / 3600.0),
                "gap_ge_60s": sum(1 for g in qc.gaps if g.duration_s >= 60),
                "gaps_long": [
                    {
                        "start": _local_display(g.start),
                        "end": _local_display(g.end),
                        "duration_hm": format_minutes_hm(g.duration_s / 60.0),
                    }
                    for g in qc.gaps
                    if g.duration_s >= 60
                ][:40],
                "duplicate_timestamps": qc.duplicate_timestamps,
                "notes": qc.notes,
                "level_db_min": qc.level_db_min,
                "level_db_max": qc.level_db_max,
            },
            "events_main": (ctx["analysis"].get("events") or [])[:events_main_cap],
            "events_all": ctx["analysis"].get("events") or [],
            "scope_text": (
                f"Ez a dokumentum {summary_type_label(stype).lower()} a "
                f"{ctx['period_display']} időszakra. "
                "Határa: a mért LAeq és a 27/2008. KvVM–EüM L_TH irányérték "
                "összevetése; nem hitelesített L_AM napló."
            ),
        }
    )

    pdf_path, html_path = _render_pdf(
        template_name="report_full.html",
        ctx=full_ctx,
        work=work,
        pdf_name="report.pdf",
        html_name="report.html",
        cfg=cfg,
    )
    return ReportPaths(
        pdf_path=pdf_path,
        html_path=html_path,
        chart_day_path=chart_day_path,
        chart_night_path=chart_night_path,
    )


def build_report(
    snapshot_dir: Path,
    *,
    layout: str = "full",
    summary_type: str | None = None,
    config: dict[str, Any] | None = None,
    output_dir: Path | None = None,
    with_analysis: bool = True,
) -> ReportPaths:
    cfg = config or load_config()
    report_cfg = cfg.get("report") or {}
    layout = (layout or report_cfg.get("default_layout") or "full").lower()
    if layout == "thin":
        return build_thin_report(
            snapshot_dir,
            config=cfg,
            output_dir=output_dir,
            with_analysis=with_analysis,
        )
    return build_full_report(
        snapshot_dir,
        config=cfg,
        output_dir=output_dir,
        with_analysis=with_analysis,
        summary_type=summary_type,
    )
