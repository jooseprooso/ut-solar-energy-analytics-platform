from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.forecast import db
from src.forecast.backtest import run_walk_forward, MODEL_VERSION
from src.forecast.model import train_and_predict


def _resolve_target_date() -> date:
    """Tomorrow in the configured timezone (simplified: UTC + offset from METEO_TIMEZONE)."""
    return (datetime.now(timezone.utc) + timedelta(days=1)).date()


def _run_backtest(conn, site_id: str) -> int:
    print(f"[forecast] Loading mart data for site={site_id}")
    df = db.load_mart_data(conn, site_id)
    print(f"[forecast] Loaded {len(df)} rows, {df['date_day'].nunique()} days")

    rows = run_walk_forward(df, site_id)
    print(f"[forecast] Backtest produced {len(rows)} forecast rows")

    count = db.upsert_forecasts(conn, rows)
    print(f"[forecast] Upserted {count} backtest rows")
    return count


def _run_live(conn, site_id: str) -> int:
    target = _resolve_target_date()
    print(f"[forecast] Live forecast for {target}, site={site_id}")

    train_df = db.load_mart_data(conn, site_id)
    if train_df.empty:
        print("[forecast] No training data available — skipping live")
        return 0

    pred_df = db.load_meteo_forecast(conn, target)
    if pred_df.empty:
        print(f"[forecast] No meteo forecast for {target} — skipping live")
        return 0

    try:
        y_hat = train_and_predict(train_df, pred_df)
    except ValueError as e:
        print(f"[forecast] Cannot predict: {e}")
        return 0

    issued_at = datetime.now(timezone.utc)
    rows = [
        (
            site_id,
            ts,
            target,
            "live",
            float(kwh),
            issued_at,
            MODEL_VERSION,
        )
        for ts, kwh in zip(pred_df["timestamp_utc"], y_hat)
    ]

    count = db.upsert_forecasts(conn, rows)
    print(f"[forecast] Upserted {count} live rows for {target}")
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="PV forecast runner")
    parser.add_argument(
        "--mode",
        choices=["backtest", "live"],
        default="live",
        help="backtest = walk-forward over history; live = predict tomorrow",
    )
    args = parser.parse_args()

    site_id = os.getenv("VRM_SITE_ID")
    if not site_id:
        print("[forecast] VRM_SITE_ID not set — skipping")
        return 0

    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"[forecast] Starting mode={args.mode} at {timestamp}")

    conn = db.build_connection()
    try:
        if args.mode == "backtest":
            _run_backtest(conn, site_id)
        else:
            _run_live(conn, site_id)
    finally:
        conn.close()

    print("[forecast] Done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
