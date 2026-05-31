from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import psycopg2
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from orchestration.config import validate_required_env

VRM_BASE = "https://vrmapi.victronenergy.com/v2"

REQUIRED_ENV_KEYS = [
    "VRM_API_TOKEN",
    "VRM_SITE_ID",
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

# Codes returned by /stats that we map to silver columns.
# Energy sums: [ts_ms, value]; measurements: [ts_ms, avg, min, max].
STATS_CODES = {"bs", "bv", "total_solar_yield", "total_consumption"}


@dataclass(frozen=True)
class BackfillConfig:
    token: str
    site_id: str
    start_date: date
    end_date: date
    chunk_days: int = DEFAULT_CHUNK_DAYS


def build_backfill_config_from_env() -> BackfillConfig:
    validate_required_env(REQUIRED_ENV_KEYS, env=os.environ)

    end_date = date.today() - timedelta(days=1)
    start_date = end_date - timedelta(days=DEFAULT_BACKFILL_DAYS)

    if os.getenv("VRM_BACKFILL_START"):
        start_date = date.fromisoformat(os.environ["VRM_BACKFILL_START"])
    if os.getenv("VRM_BACKFILL_END"):
        end_date = date.fromisoformat(os.environ["VRM_BACKFILL_END"])

    return BackfillConfig(
        token=os.environ["VRM_API_TOKEN"],
        site_id=os.environ["VRM_SITE_ID"],
        start_date=start_date,
        end_date=end_date,
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


def fetch_stats_chunk(
    session: requests.Session,
    token: str,
    site_id: str,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    start_ts = int(
        datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc).timestamp()
    )
    end_ts = int(
        datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=timezone.utc).timestamp()
    )
    resp = session.get(
        f"{VRM_BASE}/installations/{site_id}/stats",
        headers={"x-authorization": f"Token {token}"},
        params=[("start", start_ts), ("end", end_ts), ("interval", "hours")],
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def unpack_to_hourly_rows(
    records: dict[str, list],
    fetched_at: datetime,
) -> list[tuple[datetime, datetime, dict]]:
    """Unpack the stats response into one flat dict per hour timestamp."""
    by_hour: dict[int, dict] = {}

    for code, entries in records.items():
        if code not in STATS_CODES or not entries:
            continue
        for entry in entries:
            ts_ms = entry[0]
            value = entry[1]  # avg for measurements, sum for energy fields
            by_hour.setdefault(ts_ms, {})[code] = value

    rows = []
    for ts_ms, payload in sorted(by_hour.items()):
        fetched_hour = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).replace(
            minute=0, second=0, microsecond=0
        )
        rows.append((fetched_hour, fetched_at, payload))

    return rows


def upsert_stats_rows(
    conn,
    site_id: str,
    rows: list[tuple[datetime, datetime, dict]],
) -> int:
    with conn.cursor() as cur:
        for fetched_hour, fetched_at, payload in rows:
            cur.execute(
                """
                INSERT INTO bronze.vrm_stats_raw
                    (site_id, fetched_at, fetched_hour, payload)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (site_id, fetched_hour)
                DO UPDATE SET
                    payload    = EXCLUDED.payload,
                    fetched_at = EXCLUDED.fetched_at
                """,
                (site_id, fetched_at, fetched_hour, json.dumps(payload)),
            )
    conn.commit()
    return len(rows)


def build_http_client() -> requests.Session:
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


def run_backfill(
    config: BackfillConfig, session: requests.Session, conn
) -> int:
    chunks = date_chunks(config.start_date, config.end_date, config.chunk_days)
    fetched_at = datetime.now(tz=timezone.utc)

    print(
        f"[vrm_backfill] Backfilling site={config.site_id} "
        f"from {config.start_date} to {config.end_date}"
    )
    print(
        f"[vrm_backfill] Split into {len(chunks)} chunks "
        f"of up to {config.chunk_days} days"
    )

    total_rows = 0
    for i, (chunk_start, chunk_end) in enumerate(chunks, 1):
        print(f"[vrm_backfill] Chunk {i}/{len(chunks)}: {chunk_start} → {chunk_end}")
        response = fetch_stats_chunk(
            session, config.token, config.site_id, chunk_start, chunk_end
        )
        rows = unpack_to_hourly_rows(response.get("records", {}), fetched_at)
        if rows:
            count = upsert_stats_rows(conn, config.site_id, rows)
            total_rows += count
            print(f"[vrm_backfill]   Upserted {count} rows")
        else:
            print("[vrm_backfill]   No data in chunk")

    print(f"[vrm_backfill] Done. Total rows upserted: {total_rows}")
    return total_rows


def main() -> int:
    print(f"[vrm_backfill] Starting at {datetime.now(timezone.utc).isoformat()}")

    try:
        config = build_backfill_config_from_env()
    except ValueError as e:
        print(f"[vrm_backfill] Config error: {e}")
        return 1

    try:
        conn = psycopg2.connect(
            host=os.environ["SUPABASE_DB_HOST"],
            port=int(os.environ["SUPABASE_DB_PORT"]),
            dbname=os.environ["SUPABASE_DB_NAME"],
            user=os.environ["SUPABASE_DB_USER"],
            password=os.environ["SUPABASE_DB_PASSWORD"],
            sslmode="require",
        )
    except Exception as e:
        print(f"[vrm_backfill] DB connection failed: {e}")
        return 1

    session = build_http_client()

    try:
        run_backfill(config, session, conn)
    except Exception as e:
        print(f"[vrm_backfill] Backfill failed: {e}")
        conn.close()
        return 1

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
