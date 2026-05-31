from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

DEFAULT_RETRIES = 3
DEFAULT_BACKOFF_FACTOR = 1.0
RETRY_STATUS_CODES = (502, 503, 504)

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


def _build_session_with_retries(
    retries: int = DEFAULT_RETRIES,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    status_forcelist: tuple[int, ...] = RETRY_STATUS_CODES,
) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def fetch_hourly_weather(
    config: MeteoApiConfig,
    http_client: HttpClient | None = None,
) -> dict[str, Any]:
    client = http_client or _build_session_with_retries()
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
