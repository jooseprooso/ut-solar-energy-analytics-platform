from __future__ import annotations

import os
from datetime import date
from typing import Any

import pandas as pd


def build_connection() -> Any:
    import psycopg2

    return psycopg2.connect(
        host=os.environ["SUPABASE_DB_HOST"],
        port=int(os.environ["SUPABASE_DB_PORT"]),
        dbname=os.environ["SUPABASE_DB_NAME"],
        user=os.environ["SUPABASE_DB_USER"],
        password=os.environ["SUPABASE_DB_PASSWORD"],
    )


MART_COLUMNS = [
    "site_id",
    "timestamp_utc",
    "date_day",
    "hour_of_day",
    "month",
    "is_daytime",
    "pv_energy_total_kwh",
    "shortwave_radiation_wm2",
    "direct_radiation_wm2",
    "sunshine_duration_s",
    "cloud_cover_pct",
]


def load_mart_data(conn: Any, site_id: str) -> pd.DataFrame:
    """Load all historical rows from gold.mart_vrm_log_hourly for a site."""
    cols = ", ".join(MART_COLUMNS)
    sql = f"SELECT {cols} FROM gold.mart_vrm_log_hourly WHERE site_id = %s ORDER BY timestamp_utc"
    return pd.read_sql(sql, conn, params=(site_id,))


def load_meteo_forecast(conn: Any, target_date: date) -> pd.DataFrame:
    """Load meteo forecast rows for a future date from gold.fct_meteo_hourly."""
    sql = """
        SELECT
            timestamp_utc,
            timestamp_utc::date AS date_day,
            extract(hour FROM timestamp_utc)::int AS hour_of_day,
            extract(month FROM timestamp_utc)::int AS month,
            (extract(hour FROM timestamp_utc) BETWEEN 6 AND 20) AS is_daytime,
            shortwave_radiation_wm2,
            direct_radiation_wm2,
            sunshine_duration_s,
            cloud_cover_pct
        FROM gold.fct_meteo_hourly
        WHERE timestamp_utc::date = %s
        ORDER BY timestamp_utc
    """
    return pd.read_sql(sql, conn, params=(target_date,))


UPSERT_SQL = """\
INSERT INTO gold.fct_pv_forecast_hourly
    (site_id, timestamp_utc, date_day, forecast_type, pv_energy_forecast_kwh,
     forecast_issued_at, model_version)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (site_id, timestamp_utc, forecast_type)
DO UPDATE SET
    pv_energy_forecast_kwh = EXCLUDED.pv_energy_forecast_kwh,
    forecast_issued_at     = EXCLUDED.forecast_issued_at,
    model_version          = EXCLUDED.model_version
"""


def upsert_forecasts(
    conn: Any,
    rows: list[tuple[Any, ...]],
) -> int:
    """Upsert forecast rows into gold.fct_pv_forecast_hourly.

    Each row tuple: (site_id, timestamp_utc, date_day, forecast_type,
                     pv_energy_forecast_kwh, forecast_issued_at, model_version)
    """
    if not rows:
        return 0
    cur = conn.cursor()
    cur.executemany(UPSERT_SQL, rows)
    conn.commit()
    cur.close()
    return len(rows)
