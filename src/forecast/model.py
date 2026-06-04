from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge


FEATURE_COLS = [
    "shortwave_radiation_wm2",
    "direct_radiation_wm2",
    "sunshine_duration_s",
    "cloud_cover_pct",
]

TARGET_COL = "pv_energy_total_kwh"


def _encode_hour(hour: pd.Series) -> pd.DataFrame:
    """Cyclical hour encoding with sin/cos."""
    rad = 2 * np.pi * hour / 24.0
    return pd.DataFrame({"hour_sin": np.sin(rad), "hour_cos": np.cos(rad)})


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build feature matrix from mart columns. Expects FEATURE_COLS + hour_of_day."""
    features = df[FEATURE_COLS].fillna(0).copy()
    features["shortwave_radiation_sq"] = features["shortwave_radiation_wm2"] ** 2
    features["direct_radiation_sq"] = features["direct_radiation_wm2"] ** 2
    hour_enc = _encode_hour(df["hour_of_day"])
    return pd.concat([features, hour_enc], axis=1)


def filter_daytime(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only daytime rows with valid PV and radiation data."""
    mask = df["is_daytime"].astype(bool) & df[TARGET_COL].notna()
    return df.loc[mask].copy()


def train_and_predict(
    train_df: pd.DataFrame,
    predict_df: pd.DataFrame,
    alpha: float = 1.0,
) -> np.ndarray:
    """Train Ridge on daytime rows, predict daytime only; nighttime = 0."""
    train_day = filter_daytime(train_df)
    if len(train_day) < 24:
        raise ValueError(f"Too few training rows ({len(train_day)}), need at least 24")

    X_train = build_features(train_day)
    y_train = train_day[TARGET_COL].values

    model = Ridge(alpha=alpha)
    model.fit(X_train, y_train)

    y_hat = np.zeros(len(predict_df))
    daytime_mask = predict_df["is_daytime"].astype(bool).values
    if daytime_mask.any():
        X_pred = build_features(predict_df.loc[daytime_mask])
        y_hat[daytime_mask] = np.maximum(model.predict(X_pred), 0.0)

    return y_hat
