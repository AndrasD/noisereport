import math

import pytest

from src.metrics import energetic_laeq, is_day_local, night_date_local, percentile_db
from datetime import datetime
from zoneinfo import ZoneInfo

UTC = ZoneInfo("UTC")
BUDAPEST = ZoneInfo("Europe/Budapest")


def test_equal_levels_laeq() -> None:
    assert energetic_laeq([50.0, 50.0]) == pytest.approx(50.0)


def test_plus_3db_pair_average() -> None:
    # Energetic mean of L and L+3 dB (twice the intensity)
    assert energetic_laeq([60.0, 63.0102999566]) == pytest.approx(61.7609, abs=1e-3)


def test_double_duration_same_level_unchanged() -> None:
    # Doubling sample count at the same level does not change LAeq
    assert energetic_laeq([55.0] * 10) == pytest.approx(55.0)


def test_percentile_known_series() -> None:
    levels = [10, 20, 30, 40, 50]
    assert percentile_db(levels, 0.0) == 10
    assert percentile_db(levels, 1.0) == 50
    assert percentile_db(levels, 0.5) == 30


def test_day_night_split() -> None:
    day = datetime(2026, 11, 25, 10, 0, tzinfo=BUDAPEST)
    night = datetime(2026, 11, 25, 23, 0, tzinfo=BUDAPEST)
    early = datetime(2026, 11, 26, 2, 0, tzinfo=BUDAPEST)
    assert is_day_local(day)
    assert not is_day_local(night)
    assert not is_day_local(early)
    assert night_date_local(night).isoformat() == "2026-11-25"
    assert night_date_local(early).isoformat() == "2026-11-25"


def test_empty_raises() -> None:
    with pytest.raises(ValueError):
        energetic_laeq([])


def test_sustained_peak_ignores_single_sample_spike() -> None:
    import pandas as pd
    from src.metrics import sustained_peak_db

    # Mostly 50 dB, one instantaneous 81 dB sample
    idx = pd.date_range("2026-11-25T10:00:00Z", periods=60, freq="1s")
    levels = [50.0] * 60
    levels[30] = 81.2
    sound = pd.DataFrame({"measured_at": idx, "level_db": levels})
    peak = sustained_peak_db(sound)
    assert peak is not None
    # One 81.2 sample cannot dominate a full minute LAeq the way raw Lmax would
    assert peak < 70.0
    assert peak < 81.0

