import pandas as pd

from src.limits import evaluate_limits, rolling_laeq_windows
from src.metrics import energetic_laeq


def test_rolling_one_minute() -> None:
    idx = pd.date_range("2026-11-25T10:00:00Z", periods=90, freq="1s")
    sound = pd.DataFrame({"measured_at": idx, "level_db": 50.0})
    res = rolling_laeq_windows(
        sound,
        window=pd.Timedelta(minutes=1),
        step=pd.Timedelta(minutes=1),
        day_limit=50,
        night_limit=40,
        period="day",
    )
    assert res
    assert res[0].laeq_db == energetic_laeq([50.0])


def test_evaluate_limits_assessment_rows() -> None:
    # Long enough daytime block for an 8h window (~10 hours of samples)
    idx = pd.date_range("2026-11-25T05:00:00Z", periods=10 * 3600, freq="1s")  # 06–16 local CET
    sound = pd.DataFrame({"measured_at": idx, "level_db": 55.0})
    out = evaluate_limits(sound, day_limit=50, night_limit=40)
    assert out["assessment_rows"]
    labels = [r["label"] for r in out["assessment_rows"]]
    assert any("Nappal" in x for x in labels)
    assert any("Éjjel" in x for x in labels)
    day_row = next(r for r in out["assessment_rows"] if r["window"] == "8h_day")
    assert day_row["max_laeq"] is not None
    assert day_row["max_laeq"] > 50
