"""Night exceedance aggregation."""

from __future__ import annotations

import pandas as pd

from src.charts import night_exceedance_stats


def test_night_exceedance_groups_by_night_date():
    # CET = UTC+1 in November
    rows = [
        ("2026-11-23T22:00:00+00:00", 45.0),  # local 23:00 — night of 23rd
        ("2026-11-23T22:01:00+00:00", 30.0),  # under
        ("2026-11-24T00:00:00+00:00", 50.0),  # local 01:00 — still night of 23rd
        ("2026-11-24T10:00:00+00:00", 60.0),  # day — ignored
        ("2026-11-24T21:30:00+00:00", 42.0),  # local 22:30 — night of 24th
    ]
    minutes = pd.DataFrame(
        {
            "measured_at": [pd.Timestamp(t) for t, _ in rows],
            "laeq_db": [v for _, v in rows],
        }
    )
    stats = night_exceedance_stats(minutes, night_limit=40.0)
    assert len(stats) == 2
    first = stats.iloc[0]
    assert str(first["night_date"]) == "2026-11-23"
    assert first["minutes_over"] == 2
    assert first["max_exceedance_db"] == 10.0  # 50 - 40
    second = stats.iloc[1]
    assert str(second["night_date"]) == "2026-11-24"
    assert second["minutes_over"] == 1
    assert second["max_exceedance_db"] == 2.0
