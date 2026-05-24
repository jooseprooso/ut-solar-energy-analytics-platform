from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestration.config import validate_required_env
from src.ingest.meteo_api_client import MeteoApiConfig, fetch_hourly_weather
from src.ingest.meteo_transform import parse_hourly_response
from src.ingest.meteo_db_writer import build_connection, upsert_meteo_rows


REQUIRED_ENV_KEYS = [
    "METEO_LAT",
    "METEO_LON",
    "SUPABASE_DB_HOST",
    "SUPABASE_DB_PORT",
    "SUPABASE_DB_NAME",
    "SUPABASE_DB_USER",
    "SUPABASE_DB_PASSWORD",
]


def main() -> int:
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"[meteo_ingest] Starting at {timestamp}")

    try:
        validate_required_env(REQUIRED_ENV_KEYS, env=os.environ)
    except ValueError as e:
        print(f"[meteo_ingest] Config error: {e}")
        return 1

    config = MeteoApiConfig(
        latitude=float(os.environ["METEO_LAT"]),
        longitude=float(os.environ["METEO_LON"]),
        timezone=os.getenv("METEO_TIMEZONE", "UTC"),
    )

    try:
        print(f"[meteo_ingest] Fetching data for ({config.latitude}, {config.longitude})")
        raw_json = fetch_hourly_weather(config)
    except Exception as e:
        print(f"[meteo_ingest] API fetch failed: {e}")
        return 1

    rows = parse_hourly_response(raw_json, config.latitude, config.longitude)
    print(f"[meteo_ingest] Parsed {len(rows)} rows from API response")

    if not rows:
        print("[meteo_ingest] No data to write, exiting.")
        return 0

    try:
        conn = build_connection(
            host=os.environ["SUPABASE_DB_HOST"],
            port=os.environ["SUPABASE_DB_PORT"],
            dbname=os.environ["SUPABASE_DB_NAME"],
            user=os.environ["SUPABASE_DB_USER"],
            password=os.environ["SUPABASE_DB_PASSWORD"],
        )
        count = upsert_meteo_rows(rows, conn)
        conn.close()
    except Exception as e:
        print(f"[meteo_ingest] DB write failed: {e}")
        return 1

    print(f"[meteo_ingest] Successfully upserted {count} rows to bronze.meteo_raw")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
