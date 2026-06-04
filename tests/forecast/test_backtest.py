from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.forecast.backtest import run_walk_forward, MIN_TRAIN_DAYS


def _make_df(n_days: int = 15) -> pd.DataFrame:
    rows = []
    for day in range(1, n_days + 1):
        for hour in range(24):
            is_day = 6 <= hour <= 20
            rad = max(0, 500 * np.sin(np.pi * (hour - 6) / 14)) if is_day else 0.0
            pv = rad / 1000.0 * 6.0 * 0.85 if is_day else 0.0
            rows.append({
                "site_id": "test",
                "timestamp_utc": pd.Timestamp(f"2026-05-{day:02d} {hour:02d}:00:00+00:00"),
                "date_day": f"2026-05-{day:02d}",
                "hour_of_day": hour,
                "month": 5,
                "is_daytime": is_day,
                "pv_energy_total_kwh": pv,
                "shortwave_radiation_wm2": rad,
                "direct_radiation_wm2": rad * 0.7,
                "sunshine_duration_s": 3600.0 if rad > 50 else 0.0,
                "cloud_cover_pct": 20.0,
            })
    return pd.DataFrame(rows)


class TestWalkForward:
    def test_skips_first_n_days(self):
        df = _make_df(15)
        rows = run_walk_forward(df, "test")
        forecast_dates = {r[2] for r in rows}
        all_dates = sorted(pd.to_datetime(df["date_day"]).dt.date.unique())
        for d in all_dates[:MIN_TRAIN_DAYS]:
            assert d not in forecast_dates, f"Day {d} should be training-only"

    def test_produces_rows(self):
        df = _make_df(15)
        rows = run_walk_forward(df, "test")
        assert len(rows) > 0
        assert all(r[3] == "backtest" for r in rows)

    def test_raises_on_too_few_days(self):
        df = _make_df(MIN_TRAIN_DAYS)
        with pytest.raises(ValueError, match="Need at least"):
            run_walk_forward(df, "test")

    def test_forecast_type_is_backtest(self):
        df = _make_df(12)
        rows = run_walk_forward(df, "test")
        assert all(r[3] == "backtest" for r in rows)
