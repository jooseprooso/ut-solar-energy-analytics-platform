import os
from datetime import datetime, timezone


def main() -> int:
    table_prefix = os.getenv("BRONZE_TABLE_PREFIX", "")
    target_table = f"{table_prefix}vrm_raw"
    token = os.getenv("VRM_API_TOKEN")
    site_id = os.getenv("VRM_SITE_ID")
    if not token or not site_id:
        print("[vrm_ingest] Missing VRM_API_TOKEN or VRM_SITE_ID.")
        return 1

    timestamp = datetime.now(tz=timezone.utc).isoformat()
    print(f"[vrm_ingest] Stub run OK for site={site_id} at {timestamp}")
    print(f"[vrm_ingest] TODO: implement VRM API pull and UPSERT to bronze.{target_table}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
