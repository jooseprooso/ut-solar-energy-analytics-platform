from __future__ import annotations

import csv
import io
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import psycopg2
import requests

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from orchestration.config import validate_required_env

REPORTS_API = "https://vrm-reports-api.victronenergy.com/download"

FLAT_COLUMN_MAP: dict[str, tuple[str, str]] = {
    "battery_soc":               ("Battery Monitor [512]", "State of charge"),
    "battery_voltage":           ("Battery Monitor [512]", "Voltage"),
    "battery_current":           ("Battery Monitor [512]", "Current"),
    "battery_temperature":       ("Battery Monitor [512]", "Battery temperature"),
    "battery_power":             ("System overview [0]",   "Battery Power"),
    "battery_discharged_energy": ("Battery Monitor [512]", "Discharged Energy"),
    "battery_charged_energy":    ("Battery Monitor [512]", "Charged Energy"),
    "ac_consumption_l1":         ("System overview [0]",   "AC Consumption L1"),
    "ac_consumption_l2":         ("System overview [0]",   "AC Consumption L2"),
    "ac_consumption_l3":         ("System overview [0]",   "AC Consumption L3"),
    "pv_power_l1":               ("PV Inverter [20]",      "L1 Power"),
    "pv_power_l2":               ("PV Inverter [20]",      "L2 Power"),
    "pv_power_l3":               ("PV Inverter [20]",      "L3 Power"),
    "pv_energy_l1":              ("PV Inverter [20]",      "L1 Energy"),
    "pv_energy_l2":              ("PV Inverter [20]",      "L2 Energy"),
    "pv_energy_l3":              ("PV Inverter [20]",      "L3 Energy"),
    "grid_input_power_l1":       ("VE.Bus System [276]",   "Input power 1"),
    "grid_input_power_l2":       ("VE.Bus System [276]",   "Input power 2"),
    "grid_input_power_l3":       ("VE.Bus System [276]",   "Input power 3"),
    "grid_input_frequency_l1":   ("VE.Bus System [276]",   "Input frequency 1"),
    "grid_input_frequency_l2":   ("VE.Bus System [276]",   "Input frequency 2"),
    "grid_input_frequency_l3":   ("VE.Bus System [276]",   "Input frequency 3"),
    "grid_input_current_l1":     ("VE.Bus System [276]",   "Input current phase 1"),
    "grid_input_current_l2":     ("VE.Bus System [276]",   "Input current phase 2"),
    "grid_input_current_l3":     ("VE.Bus System [276]",   "Input current phase 3"),
    "grid_input_voltage_l1":     ("VE.Bus System [276]",   "Input voltage phase 1"),
    "grid_input_voltage_l2":     ("VE.Bus System [276]",   "Input voltage phase 2"),
    "grid_input_voltage_l3":     ("VE.Bus System [276]",   "Input voltage phase 3"),
    "grid_alarm":                ("System overview [276]", "Grid alarm"),
}

REQUIRED_ENV_KEYS = [
    "VRM_API_TOKEN",
    "VRM_SITE_ID",
    "SUPABASE_DB_HOST",
    "SUPABASE_DB_PORT",
    "SUPABASE_DB_NAME",
    "SUPABASE_DB_USER",
    "SUPABASE_DB_PASSWORD",
]

_FLAT_COLS = list(FLAT_COLUMN_MAP.keys())
_col_list = ", ".join(_FLAT_COLS)
_placeholders = ", ".join(["%s"] * len(_FLAT_COLS))
_conflict_set = ", ".join(f"{c} = EXCLUDED.{c}" for c in _FLAT_COLS)

UPSERT_SQL = (
    f"INSERT INTO bronze.vrm_log_raw "
    f"(site_id, recorded_at, fetched_at, metrics, {_col_list}) "
    f"VALUES (%s, %s, %s, %s, {_placeholders}) "
    f"ON CONFLICT (site_id, recorded_at) DO UPDATE SET "
    f"fetched_at = EXCLUDED.fetched_at, metrics = EXCLUDED.metrics, {_conflict_set}"
)

_MAX_RETRIES = 8
_INITIAL_BACKOFF = 2.0
_MAX_BACKOFF = 120.0


@dataclass(frozen=True)
class IngestConfig:
    token: str
    site_id: int
    start_unix: int
    end_unix: int


def download_report(
    session: requests.Session,
    token: str,
    site_id: int,
    start_unix: int,
    end_unix: int,
) -> str:
    headers = {"X-Authorization": f"Token {token}"}
    params = {
        "idSite": site_id,
        "startTime": start_unix,
        "endTime": end_unix,
        "type": "log",
        "format": "csv",
    }
    delay = _INITIAL_BACKOFF
    last_err: str | None = None

    for _ in range(_MAX_RETRIES):
        resp = session.get(REPORTS_API, headers=headers, params=params, timeout=120)

        if resp.status_code == 429:
            last_err = resp.text
            time.sleep(delay)
            delay = min(delay * 2, _MAX_BACKOFF)
            continue

        if resp.status_code == 202:
            raise RuntimeError(f"HTTP 202 async response: {resp.text[:500]}")

        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:800]}")

        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "json" in ctype or resp.text.lstrip().startswith("{"):
            raise RuntimeError(f"Expected CSV body, got JSON: {resp.text[:500]}")

        return resp.text

    raise RuntimeError(f"HTTP 429: too many rate limit responses; last: {last_err}")


def parse_header_timezone(row1_col0: str) -> timezone | ZoneInfo:
    s = (row1_col0 or "").strip()
    if not s:
        return timezone.utc

    m = re.match(r"^([A-Za-z]+/[A-Za-z0-9_+\-]+)", s)
    if m:
        try:
            return ZoneInfo(m.group(1))
        except Exception:
            pass

    m2 = re.search(r"\(([+-])(\d{2}):(\d{2})\)", s)
    if m2:
        sign = 1 if m2.group(1) == "+" else -1
        h, mi = int(m2.group(2)), int(m2.group(3))
        return timezone(timedelta(hours=sign * h, minutes=sign * mi))

    return timezone.utc


def column_runs(header_row0: list[str]) -> list[tuple[int, int, str]]:
    if len(header_row0) < 2:
        return []

    runs: list[tuple[int, int, str]] = []
    start = 1
    cur = (header_row0[1] or "").strip()

    for i in range(2, len(header_row0)):
        val = (header_row0[i] or "").strip()
        if val != cur:
            runs.append((start, i - 1, cur))
            start = i
            cur = val

    runs.append((start, len(header_row0) - 1, cur))
    return runs


def coerce_value(raw: str | None) -> Any:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if re.fullmatch(r"-?\d+", s):
        try:
            return int(s)
        except ValueError:
            pass
    try:
        return float(s)
    except ValueError:
        return s


def parse_sample_time(s: str, tz: timezone | ZoneInfo) -> datetime | None:
    s = (s or "").strip()
    if not s or s.lower() == "timestamp":
        return None

    naive: datetime | None = None

    if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", s):
        if "." in s[:23]:
            head, _, rest = s.partition(".")
            frac = re.match(r"^(\d+)", rest)
            frac_s = (frac.group(1) if frac else "")[:6].ljust(6, "0")
            try:
                naive = datetime.strptime(head + "." + frac_s, "%Y-%m-%d %H:%M:%S.%f")
            except ValueError:
                pass
        if naive is None:
            try:
                naive = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None
    else:
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                return dt.astimezone(timezone.utc)
            naive = dt
        except ValueError:
            return None

    if naive is None:
        return None

    return naive.replace(tzinfo=tz).astimezone(timezone.utc)


def build_metrics(
    row: list[str],
    row0: list[str],
    row1: list[str],
    runs: list[tuple[int, int, str]],
) -> dict[str, dict[str, Any]]:
    metrics: dict[str, dict[str, Any]] = {}

    for start, end, label in runs:
        block = label.strip() if label else "unknown"
        inner: dict[str, Any] = {}
        for j in range(start, end + 1):
            name = row1[j] if j < len(row1) else f"col_{j}"
            key = name.strip() if name else f"col_{j}"
            raw = row[j] if j < len(row) else ""
            v = coerce_value(raw)
            if v is None:
                continue
            inner[key] = v
        if inner:
            metrics[block] = inner

    return metrics


def extract_flat_values(metrics: dict[str, dict[str, Any]]) -> list[Any]:
    values: list[Any] = []
    for col in FLAT_COLUMN_MAP:
        block, key = FLAT_COLUMN_MAP[col]
        raw = metrics.get(block, {}).get(key)
        if raw is not None and col != "grid_alarm":
            try:
                raw = float(raw)
            except (ValueError, TypeError):
                raw = None
        values.append(raw)
    return values


def upsert_log_row(
    conn,
    site_id: str,
    recorded_at: datetime,
    fetched_at: datetime,
    metrics: dict[str, Any],
    flat_values: list[Any],
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            UPSERT_SQL,
            (site_id, recorded_at, fetched_at, json.dumps(metrics), *flat_values),
        )
    conn.commit()


def ingest_csv_text(
    text: str,
    site_id: str,
    conn,
    fetched_at: datetime,
    dry_run: bool = False,
) -> int:
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)

    if len(rows) < 4:
        raise ValueError(f"CSV must have at least 4 rows (header), got {len(rows)}")

    row0, row1 = rows[0], rows[1]
    width = min(len(row0), len(row1))
    row0, row1 = row0[:width], row1[:width]

    sample_tz = parse_header_timezone(row1[0] if row1 else "")
    runs = column_runs(row0)

    inserted = 0

    with conn.cursor() as cur:
        for row in rows[3:]:
            if not row:
                continue
            recorded = parse_sample_time(row[0], sample_tz)
            if recorded is None:
                continue
            row_pad = (row + [""] * max(0, width - len(row)))[:width]
            metrics = build_metrics(row_pad, row0, row1, runs)
            if not metrics:
                continue
            if dry_run:
                inserted += 1
                continue
            flat_vals = extract_flat_values(metrics)
            cur.execute(
                UPSERT_SQL,
                (site_id, recorded, fetched_at, json.dumps(metrics), *flat_vals),
            )
            inserted += 1

    if not dry_run:
        conn.commit()

    return inserted


def build_ingest_config() -> IngestConfig:
    validate_required_env(REQUIRED_ENV_KEYS, env=os.environ)

    now = datetime.now(timezone.utc)
    end_dt = now.replace(minute=0, second=0, microsecond=0)
    start_dt = end_dt - timedelta(hours=1)

    if os.getenv("VRM_LOG_START"):
        start_dt = datetime.fromisoformat(os.environ["VRM_LOG_START"]).replace(
            tzinfo=timezone.utc
        )
    if os.getenv("VRM_LOG_END"):
        end_dt = datetime.fromisoformat(os.environ["VRM_LOG_END"]).replace(
            tzinfo=timezone.utc
        )

    return IngestConfig(
        token=os.environ["VRM_API_TOKEN"],
        site_id=int(os.environ["VRM_SITE_ID"]),
        start_unix=int(start_dt.timestamp()),
        end_unix=int(end_dt.timestamp()),
    )


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
    try:
        config = build_ingest_config()
    except ValueError as e:
        print(f"[vrm_log_ingest] Config error: {e}")
        return 1

    try:
        conn = _db_conn()
    except Exception as e:
        print(f"[vrm_log_ingest] DB connection failed: {e}")
        return 1

    fetched_at = datetime.now(timezone.utc)
    session = requests.Session()

    try:
        print(
            f"[vrm_log_ingest] Downloading site={config.site_id} "
            f"{config.start_unix}→{config.end_unix}"
        )
        text = download_report(session, config.token, config.site_id,
                               config.start_unix, config.end_unix)
        count = ingest_csv_text(text, str(config.site_id), conn, fetched_at)
        print(f"[vrm_log_ingest] Upserted {count} rows")
    except Exception as e:
        print(f"[vrm_log_ingest] Failed: {e}")
        conn.close()
        return 1

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
