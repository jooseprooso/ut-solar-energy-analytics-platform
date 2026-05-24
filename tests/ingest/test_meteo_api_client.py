from unittest.mock import Mock

import pytest

from src.ingest.meteo_api_client import (
    HOURLY_VARIABLES,
    OPEN_METEO_URL,
    MeteoApiConfig,
    fetch_hourly_weather,
)


@pytest.fixture
def config():
    return MeteoApiConfig(latitude=58.2538, longitude=22.4922, timezone="auto")


@pytest.fixture
def mock_http_client():
    client = Mock()
    client.get.return_value.json.return_value = {"hourly": {"time": []}}
    client.get.return_value.raise_for_status.return_value = None
    return client


class TestFetchHourlyWeather:
    def test_calls_correct_url(self, config, mock_http_client):
        fetch_hourly_weather(config, http_client=mock_http_client)
        call_args = mock_http_client.get.call_args
        assert call_args[0][0] == OPEN_METEO_URL

    def test_passes_expected_params(self, config, mock_http_client):
        fetch_hourly_weather(config, http_client=mock_http_client)
        call_args = mock_http_client.get.call_args
        params = call_args[1]["params"]
        assert params["latitude"] == 58.2538
        assert params["longitude"] == 22.4922
        assert params["timezone"] == "auto"
        assert params["past_hours"] == 24
        assert params["forecast_hours"] == 24
        assert params["hourly"] == ",".join(HOURLY_VARIABLES)

    def test_returns_parsed_json(self, config, mock_http_client):
        mock_http_client.get.return_value.json.return_value = {"data": "test"}
        result = fetch_hourly_weather(config, http_client=mock_http_client)
        assert result == {"data": "test"}

    def test_raises_on_http_error(self, config, mock_http_client):
        from requests.exceptions import HTTPError

        mock_http_client.get.return_value.raise_for_status.side_effect = HTTPError("404")
        with pytest.raises(HTTPError):
            fetch_hourly_weather(config, http_client=mock_http_client)

    def test_uses_injected_client(self, config, mock_http_client):
        fetch_hourly_weather(config, http_client=mock_http_client)
        mock_http_client.get.assert_called_once()
