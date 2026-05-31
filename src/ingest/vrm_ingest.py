import json
import os
from datetime import datetime, timezone

import psycopg2
import requests

VRM_BASE = "https://vrmapi.victronenergy.com/v2"


def _fetch_diagnostics(token: str, site_id: str) -> dict:
    url = f"{VRM_BASE}/installations/{site_id}/diagnostics"
    resp = requests.get(
        url,
        headers={"x-authorization": f"Token {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _upsert(conn, site_id: str, fetched_at: datetime, payload: dict) -> None:
    fetched_hour = fetched_at.replace(minute=0, second=0, microsecond=0)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bronze.vrm_raw (site_id, fetched_at, fetched_hour, endpoint, payload)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (site_id, fetched_hour, endpoint)
            DO UPDATE SET
                payload    = EXCLUDED.payload,
                fetched_at = EXCLUDED.fetched_at
            """,
            (site_id, fetched_at, fetched_hour, "diagnostics", json.dumps(payload)),
        )
    conn.commit()


def _db_conn():
    return psycopg2.connect(
        host=os.environ["SUPABASE_DB_HOST"],
        port=int(os.environ["SUPABASE_DB_PORT"]),
        dbname=os.environ["SUPABASE_DB_NAME"],
        user=os.environ["SUPABASE_DB_USER"],
        password=os.environ["SUPABASE_DB_PASSWORD"],
        sslmode="require",
    )


def main() -> int:
    table_prefix = os.getenv("BRONZE_TABLE_PREFIX", "")
    target_table = f"{table_prefix}vrm_raw"
    token = os.getenv("VRM_API_TOKEN")
    site_id = os.getenv("VRM_SITE_ID")
    if not token or not site_id:
        print("[vrm_ingest] Missing VRM_API_TOKEN or VRM_SITE_ID — skipping.")
        return 0

    fetched_at = datetime.now(tz=timezone.utc)
    print(f"[vrm_ingest] Fetching diagnostics for site={site_id} at {fetched_at.isoformat()}")

    payload = _fetch_diagnostics(token, site_id)
    record_count = len(payload.get("records", []))
    print(f"[vrm_ingest] Received {record_count} diagnostic records")

    conn = _db_conn()
    try:
        _upsert(conn, site_id, fetched_at, payload)
        print("[vrm_ingest] Upserted to bronze.vrm_raw OK")
    finally:
        conn.close()

    timestamp = datetime.now(tz=timezone.utc).isoformat()
    print(f"[vrm_ingest] Stub run OK for site={site_id} at {timestamp}")
    print(f"[vrm_ingest] TODO: implement VRM API pull and UPSERT to bronze.{target_table}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
