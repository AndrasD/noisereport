"""Neutral limit-window evaluation with sensitivity table."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.metrics import BUDAPEST, energetic_laeq, is_day_local, night_date_local

# PeakTech display stream ≈ 20 Hz; plaintiff's diary uses ≥50% coverage.
DEFAULT_EXPECTED_HZ = 20.0
DEFAULT_MIN_COVERAGE = 0.5


@dataclass
class WindowResult:
    label: str
    window: str
    start: str
    end: str
    laeq_db: float
    limit_db: float
    exceedance_db: float
    sample_count: int


def _limit_for_ts(ts: pd.Timestamp, day_limit: float, night_limit: float) -> float:
    return day_limit if is_day_local(ts.to_pydatetime()) else night_limit


def _prepare(sound: pd.DataFrame) -> pd.DataFrame:
    df = sound.copy()
    df["measured_at"] = pd.to_datetime(df["measured_at"], utc=True)
    df["level_db"] = pd.to_numeric(df["level_db"], errors="coerce")
    return df.dropna(subset=["level_db"]).sort_values("measured_at")


def _window_fully_in_period(
    start: pd.Timestamp,
    end: pd.Timestamp,
    kind: str,
) -> bool:
    """True if the half-open [start, end) lies entirely in one day or night period."""
    start_dt = start.to_pydatetime()
    last_dt = (end - pd.Timedelta(seconds=1)).to_pydatetime()
    if kind == "day":
        return (
            is_day_local(start_dt)
            and is_day_local(last_dt)
            and start_dt.astimezone(BUDAPEST).date()
            == last_dt.astimezone(BUDAPEST).date()
        )
    return (
        not is_day_local(start_dt)
        and not is_day_local(last_dt)
        and night_date_local(start_dt) == night_date_local(last_dt)
    )


def rolling_laeq_windows(
    sound: pd.DataFrame,
    *,
    window: pd.Timedelta,
    step: pd.Timedelta | None = None,
    day_limit: float = 50.0,
    night_limit: float = 40.0,
    period: str | None = None,
    expected_hz: float = DEFAULT_EXPECTED_HZ,
    min_coverage: float = DEFAULT_MIN_COVERAGE,
) -> list[WindowResult]:
    """Rolling LAeq windows.

    ``period``:
      - ``day``: window entirely within one local calendar day 06–22
      - ``night``: window entirely within one night (22–06, same night_date)
      - ``None``: all windows (limit from midpoint)
    """
    df = _prepare(sound)
    if df.empty:
        return []
    step = step or window
    t0 = df["measured_at"].iloc[0]
    t1 = df["measured_at"].iloc[-1]
    min_samples = max(10, int(window.total_seconds() * expected_hz * min_coverage))
    results: list[WindowResult] = []
    start = t0
    while start + window <= t1 + pd.Timedelta(seconds=1):
        end = start + window
        mid = start + (window / 2)
        if period in ("day", "night") and not _window_fully_in_period(
            start, end, period
        ):
            start = start + step
            continue
        chunk = df[(df["measured_at"] >= start) & (df["measured_at"] < end)]
        if len(chunk) >= min_samples:
            laeq = energetic_laeq(chunk["level_db"].astype(float).tolist())
            if period == "day":
                limit = day_limit
            elif period == "night":
                limit = night_limit
            else:
                limit = _limit_for_ts(mid, day_limit, night_limit)
            results.append(
                WindowResult(
                    label=str(window),
                    window=str(window),
                    start=start.isoformat(),
                    end=end.isoformat(),
                    laeq_db=round(laeq, 2),
                    limit_db=limit,
                    exceedance_db=round(laeq - limit, 2),
                    sample_count=int(len(chunk)),
                )
            )
        start = start + step
    return results


def _worst(results: list[WindowResult]) -> WindowResult | None:
    if not results:
        return None
    return max(results, key=lambda r: r.laeq_db)


def evaluate_limits(
    sound: pd.DataFrame,
    *,
    day_limit: float = 50.0,
    night_limit: float = 40.0,
    expected_hz: float = DEFAULT_EXPECTED_HZ,
    min_coverage: float = DEFAULT_MIN_COVERAGE,
) -> dict:
    # Regulatory assessment windows (27/2008. §2 (2))
    day_8h = rolling_laeq_windows(
        sound,
        window=pd.Timedelta(hours=8),
        step=pd.Timedelta(minutes=30),
        day_limit=day_limit,
        night_limit=night_limit,
        period="day",
        expected_hz=expected_hz,
        min_coverage=min_coverage,
    )
    night_30m = rolling_laeq_windows(
        sound,
        window=pd.Timedelta(minutes=30),
        step=pd.Timedelta(minutes=5),
        day_limit=day_limit,
        night_limit=night_limit,
        period="night",
        expected_hz=expected_hz,
        min_coverage=min_coverage,
    )
    worst_day = _worst(day_8h)
    worst_night = _worst(night_30m)

    def _row_from_worst(
        *,
        key: str,
        label: str,
        explain: str,
        limit: float,
        results: list[WindowResult],
        worst: WindowResult | None,
    ) -> dict:
        if worst is None:
            return {
                "window": key,
                "label": label,
                "explain": explain,
                "limit_db": limit,
                "windows_evaluated": 0,
                "windows_over_limit": 0,
                "over_limit_ratio": 0.0,
                "max_laeq": None,
                "max_exceedance_db": None,
                "worst_start": None,
                "worst_end": None,
                "is_over": False,
                "is_assessment": True,
            }
        over = [r for r in results if r.exceedance_db > 0]
        return {
            "window": key,
            "label": label,
            "explain": explain,
            "limit_db": limit,
            "windows_evaluated": len(results),
            "windows_over_limit": len(over),
            "over_limit_ratio": round(len(over) / len(results), 3) if results else 0.0,
            "max_laeq": worst.laeq_db,
            "max_exceedance_db": worst.exceedance_db,
            "worst_start": worst.start,
            "worst_end": worst.end,
            "is_over": worst.exceedance_db > 0,
            "is_assessment": True,
        }

    assessment_rows = [
        _row_from_worst(
            key="8h_day",
            label="Nappal — legzajosabb 8 óra",
            explain=(
                "A rendelet szerint nappal (06–22) a legnagyobb zajterhelést adó "
                "folyamatos 8 órát kell nézni. Ez a sor azt az 8 órás szakaszt mutatja."
            ),
            limit=day_limit,
            results=day_8h,
            worst=worst_day,
        ),
        _row_from_worst(
            key="30min_night",
            label="Éjjel — legzajosabb fél óra",
            explain=(
                "A rendelet szerint éjjel (22–06) a legnagyobb zajterhelést adó "
                "folyamatos fél órát kell nézni. Ez a sor azt a 30 perces szakaszt mutatja."
            ),
            limit=night_limit,
            results=night_30m,
            worst=worst_night,
        ),
    ]

    # Keep legacy summary keys for alert headline (8h / 30min)
    summary_rows = [
        {
            "window": "8h",
            "windows_evaluated": assessment_rows[0]["windows_evaluated"],
            "windows_over_limit": assessment_rows[0]["windows_over_limit"],
            "over_limit_ratio": assessment_rows[0]["over_limit_ratio"],
            "max_laeq": assessment_rows[0]["max_laeq"],
            "max_exceedance_db": assessment_rows[0]["max_exceedance_db"],
            "is_over": assessment_rows[0]["is_over"],
        },
        {
            "window": "30min",
            "windows_evaluated": assessment_rows[1]["windows_evaluated"],
            "windows_over_limit": assessment_rows[1]["windows_over_limit"],
            "over_limit_ratio": assessment_rows[1]["over_limit_ratio"],
            "max_laeq": assessment_rows[1]["max_laeq"],
            "max_exceedance_db": assessment_rows[1]["max_exceedance_db"],
            "is_over": assessment_rows[1]["is_over"],
        },
    ]

    by_window = {"8h": day_8h, "30min": night_30m}
    window_labels = {
        "30min": "Éjjel — legzajosabb fél óra",
        "8h": "Nappal — legzajosabb 8 óra",
    }
    sensitivity = []
    for delta in (1.0, 2.0, 3.0):
        for name, res in by_window.items():
            if not res:
                continue
            louder = sum(1 for r in res if (r.laeq_db + delta) > r.limit_db)
            quieter = sum(1 for r in res if (r.laeq_db - delta) > r.limit_db)
            n = len(res)
            sensitivity.append(
                {
                    "window": name,
                    "window_label": window_labels[name],
                    "delta_db": delta,
                    "over_if_plus": louder,
                    "over_if_minus": quieter,
                    "n": n,
                    "pct_if_quieter": round(100.0 * quieter / n, 0) if n else 0,
                    "is_assessment": True,
                }
            )

    quietest_night = min((r.laeq_db for r in night_30m), default=None)
    quietest_day = min((r.laeq_db for r in day_8h), default=None)

    return {
        "summary": summary_rows,
        "assessment_rows": assessment_rows,
        "sensitivity": sensitivity,
        "primary_windows": ["8h", "30min"],
        "quietest_night_window_db": (
            round(quietest_night, 1) if quietest_night is not None else None
        ),
        "quietest_day_window_db": (
            round(quietest_day, 1) if quietest_day is not None else None
        ),
        "note": (
            "A táblázat a 27/2008. (XII. 3.) KvVM–EüM 2. § (2) szerinti "
            "megítélési időket mutatja: nappal a legzajosabb folyamatos 8 óra, "
            "éjjel a legzajosabb folyamatos fél óra."
        ),
    }
