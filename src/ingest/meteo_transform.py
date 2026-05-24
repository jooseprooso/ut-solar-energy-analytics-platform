from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def parse_hourly_response(
    raw_json: dict[str, Any],
    latitude: float,
    longitude: float,
) -> list[dict[str, Any]]:
    hourly = raw_json.get("hourly", {})
    timestamps = hourly.get("time", [])
    units = raw_json.get("hourly_units", {})

    rows: list[dict[str, Any]] = []

    for variable_name, values in hourly.items():
        if variable_name == "time":
            continue
        unit = units.get(variable_name, "unknown")

        for ts_str, value in zip(timestamps, values):
            rows.append({
                "timestamp_utc": _parse_timestamp(ts_str),
                "latitude": latitude,
                "longitude": longitude,
                "variable_name": variable_name,
                "value": value,
                "unit": unit,
            })

    return rows


def _parse_timestamp(ts_str: str) -> datetime:
    dt = datetime.fromisoformat(ts_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
