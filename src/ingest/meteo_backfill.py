from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestration.config import validate_required_env
from src.ingest.meteo_api_client import HOURLY_VARIABLES, HttpClient
from src.ingest.meteo_db_writer import DbConnection, build_connection, upsert_meteo_rows
from src.ingest.meteo_transform import parse_hourly_response

ARCHIVE_API_URL = "https://archive-api.open-meteo.com/v1/archive"

REQUIRED_ENV_KEYS = [
    "METEO_LAT",
    "METEO_LON",
    "SUPABASE_DB_HOST",
    "SUPABASE_DB_PORT",
    "SUPABASE_DB_NAME",
    "SUPABASE_DB_USER",
    "SUPABASE_DB_PASSWORD",
]

DEFAULT_BACKFILL_DAYS = 182
DEFAULT_CHUNK_DAYS = 30
DEFAULT_RETRIES = 5
DEFAULT_BACKOFF_FACTOR = 1.0
RETRY_STATUS_CODES = (502, 503, 504)


@dataclass(frozen=True)
class BackfillConfig:
    latitude: float
    longitude: float
    start_date: date
    end_date: date
    table_name: str = "meteo_raw"
    chunk_days: int = DEFAULT_CHUNK_DAYS


def build_backfill_config_from_env() -> BackfillConfig:
    validate_required_env(REQUIRED_ENV_KEYS, env=os.environ)

    latitude = float(os.environ["METEO_LAT"])
    longitude = float(os.environ["METEO_LON"])

    end_date = date.today() - timedelta(days=1)
    start_date = end_date - timedelta(days=DEFAULT_BACKFILL_DAYS)

    backfill_start_override = os.getenv("METEO_BACKFILL_START")
    backfill_end_override = os.getenv("METEO_BACKFILL_END")
    if backfill_start_override:
        start_date = date.fromisoformat(backfill_start_override)
    if backfill_end_override:
        end_date = date.fromisoformat(backfill_end_override)

    table_prefix = os.getenv("BRONZE_TABLE_PREFIX", "")

    return BackfillConfig(
        latitude=latitude,
        longitude=longitude,
        start_date=start_date,
        end_date=end_date,
        table_name=f"{table_prefix}meteo_raw",
    )


def date_chunks(
    start: date, end: date, chunk_days: int = DEFAULT_CHUNK_DAYS
) -> list[tuple[date, date]]:
    chunks: list[tuple[date, date]] = []
    current = start
    while current <= end:
        chunk_end = min(current + timedelta(days=chunk_days - 1), end)
        chunks.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)
    return chunks


def fetch_archive_chunk(
    http_client: HttpClient,
    latitude: float,
    longitude: float,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "hourly": ",".join(HOURLY_VARIABLES),
        "timezone": "UTC",
    }
    response = http_client.get(ARCHIVE_API_URL, params=params)
    response.raise_for_status()
    return response.json()


def run_backfill(
    config: BackfillConfig, http_client: HttpClient, conn: DbConnection
) -> int:
    chunks = date_chunks(config.start_date, config.end_date, config.chunk_days)
    print(
        f"[meteo_backfill] Backfilling ({config.latitude}, {config.longitude}) "
        f"from {config.start_date} to {config.end_date}"
    )
    print(f"[meteo_backfill] Split into {len(chunks)} chunks of up to {config.chunk_days} days")

    total_rows = 0

    for i, (chunk_start, chunk_end) in enumerate(chunks, 1):
        print(f"[meteo_backfill] Chunk {i}/{len(chunks)}: {chunk_start} to {chunk_end}")
        raw_json = fetch_archive_chunk(
            http_client, config.latitude, config.longitude, chunk_start, chunk_end
        )
        rows = parse_hourly_response(raw_json, config.latitude, config.longitude)
        if rows:
            count = upsert_meteo_rows(rows, conn, table_name=config.table_name)
            total_rows += count
            print(f"[meteo_backfill]   Upserted {count} rows")
        else:
            print("[meteo_backfill]   No data in chunk")

    print(f"[meteo_backfill] Done. Total rows upserted: {total_rows}")
    return total_rows


def build_http_client() -> HttpClient:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    session = requests.Session()
    retry = Retry(
        total=DEFAULT_RETRIES,
        backoff_factor=DEFAULT_BACKOFF_FACTOR,
        status_forcelist=RETRY_STATUS_CODES,
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def main() -> int:
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"[meteo_backfill] Starting at {timestamp}")

    try:
        config = build_backfill_config_from_env()
    except ValueError as e:
        print(f"[meteo_backfill] Config error: {e}")
        return 1

    try:
        conn = build_connection(
            host=os.environ["SUPABASE_DB_HOST"],
            port=os.environ["SUPABASE_DB_PORT"],
            dbname=os.environ["SUPABASE_DB_NAME"],
            user=os.environ["SUPABASE_DB_USER"],
            password=os.environ["SUPABASE_DB_PASSWORD"],
        )
    except Exception as e:
        print(f"[meteo_backfill] DB connection failed: {e}")
        return 1

    http_client = build_http_client()

    try:
        run_backfill(config, http_client, conn)
    except Exception as e:
        print(f"[meteo_backfill] Backfill failed: {e}")
        conn.close()
        return 1

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
