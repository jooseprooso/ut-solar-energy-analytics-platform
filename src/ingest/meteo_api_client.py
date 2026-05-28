from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import requests


OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

HOURLY_VARIABLES = [
    "sunshine_duration",
    "shortwave_radiation",
    "direct_radiation",
    "cloud_cover",
]


class HttpClient(Protocol):
    def get(self, url: str, params: dict[str, Any]) -> Any: ...


@dataclass(frozen=True)
class MeteoApiConfig:
    latitude: float
    longitude: float
    timezone: str
    past_hours: int = 24
    forecast_hours: int = 24


def fetch_hourly_weather(
    config: MeteoApiConfig,
    http_client: HttpClient | None = None,
) -> dict[str, Any]:
    client = http_client or requests
    params = {
        "latitude": config.latitude,
        "longitude": config.longitude,
        "hourly": ",".join(HOURLY_VARIABLES),
        "timezone": config.timezone,
        "past_hours": config.past_hours,
        "forecast_hours": config.forecast_hours,
    }
    response = client.get(OPEN_METEO_URL, params=params)
    response.raise_for_status()
    return response.json()
