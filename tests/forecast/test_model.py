from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.forecast.model import build_features, filter_daytime, train_and_predict


def _make_df(n_days: int = 10) -> pd.DataFrame:
    """Create a synthetic mart-like DataFrame for testing."""
    rows = []
    for day in range(n_days):
        for hour in range(24):
            is_day = 6 <= hour <= 20
            rad = max(0, 500 * np.sin(np.pi * (hour - 6) / 14)) if is_day else 0.0
            pv = rad / 1000.0 * 6.0 * (0.8 + 0.1 * np.random.randn()) if is_day else 0.0
            rows.append({
                "site_id": "test",
                "timestamp_utc": pd.Timestamp(f"2026-05-{day + 1:02d} {hour:02d}:00:00+00:00"),
                "date_day": pd.Timestamp(f"2026-05-{day + 1:02d}").date(),
                "hour_of_day": hour,
                "month": 5,
                "is_daytime": is_day,
                "pv_energy_total_kwh": pv if pv > 0 else 0.0,
                "shortwave_radiation_wm2": rad,
                "direct_radiation_wm2": rad * 0.7,
                "sunshine_duration_s": 3600.0 if rad > 50 else 0.0,
                "cloud_cover_pct": 20.0,
            })
    return pd.DataFrame(rows)


class TestBuildFeatures:
    def test_returns_expected_columns(self):
        df = _make_df(1)
        features = build_features(df)
        assert "shortwave_radiation_wm2" in features.columns
        assert "hour_sin" in features.columns
        assert "hour_cos" in features.columns
        assert len(features) == len(df)

    def test_no_future_pv_in_features(self):
        df = _make_df(1)
        features = build_features(df)
        assert "pv_energy_total_kwh" not in features.columns


class TestFilterDaytime:
    def test_filters_nighttime(self):
        df = _make_df(1)
        filtered = filter_daytime(df)
        assert all(filtered["is_daytime"])
        assert len(filtered) < len(df)


class TestTrainAndPredict:
    def test_predictions_non_negative(self):
        df = _make_df(10)
        train_df = df[df["date_day"] < df["date_day"].iloc[-24]]
        pred_df = df[df["date_day"] == df["date_day"].iloc[-1]]

        y_hat = train_and_predict(train_df, pred_df)
        assert all(y_hat >= 0.0)

    def test_raises_on_insufficient_data(self):
        df = _make_df(1)
        train_df = df[~df["is_daytime"]]
        pred_df = df[df["is_daytime"]]

        with pytest.raises(ValueError, match="Too few training rows"):
            train_and_predict(train_df, pred_df)
