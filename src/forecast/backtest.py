from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from src.forecast.model import train_and_predict


MIN_TRAIN_DAYS = 7
MODEL_VERSION = "ridge_v1"


def run_walk_forward(
    df: pd.DataFrame,
    site_id: str,
) -> list[tuple[Any, ...]]:
    """Walk-forward backtest: for each day D, train on days < D and predict D.

    Returns list of upsert-ready tuples for gold.fct_pv_forecast_hourly.
    """
    df = df.copy()
    df["date_day"] = pd.to_datetime(df["date_day"])
    days = sorted(df["date_day"].unique())

    if len(days) < MIN_TRAIN_DAYS + 1:
        raise ValueError(
            f"Need at least {MIN_TRAIN_DAYS + 1} days for backtest, got {len(days)}"
        )

    forecast_rows: list[tuple[Any, ...]] = []
    issued_at = datetime.now(timezone.utc)

    for target_day in days[MIN_TRAIN_DAYS:]:
        train_mask = df["date_day"] < target_day
        pred_mask = df["date_day"] == target_day

        train_df = df.loc[train_mask]
        pred_df = df.loc[pred_mask]

        if pred_df.empty:
            continue

        try:
            y_hat = train_and_predict(train_df, pred_df)
        except ValueError:
            continue

        for ts, forecast_kwh in zip(pred_df["timestamp_utc"], y_hat):
            forecast_rows.append((
                site_id,
                ts,
                pd.Timestamp(target_day).date(),
                "backtest",
                float(forecast_kwh),
                issued_at,
                MODEL_VERSION,
            ))

    return forecast_rows
