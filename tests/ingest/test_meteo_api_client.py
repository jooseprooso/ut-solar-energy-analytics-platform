from datetime import date
from unittest.mock import MagicMock, Mock

import pytest

from src.ingest.meteo_api_client import (
    ARCHIVE_API_URL,
    HOURLY_VARIABLES,
    OPEN_METEO_URL,
    MeteoApiConfig,
    fetch_archive_chunk,
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


class TestFetchArchiveChunk:
    def test_calls_api_with_correct_params(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"hourly": {}}
        mock_client.get.return_value = mock_response

        result = fetch_archive_chunk(
            mock_client, 58.2483, 22.4939, date(2026, 1, 1), date(2026, 1, 30)
        )

        mock_client.get.assert_called_once()
        call_args = mock_client.get.call_args
        assert call_args[0][0] == ARCHIVE_API_URL
        params = call_args[1]["params"]
        assert params["latitude"] == 58.2483
        assert params["longitude"] == 22.4939
        assert params["start_date"] == "2026-01-01"
        assert params["end_date"] == "2026-01-30"
        assert "sunshine_duration" in params["hourly"]
        mock_response.raise_for_status.assert_called_once()
        assert result == {"hourly": {}}

    def test_raises_on_http_error(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("502 Bad Gateway")
        mock_client.get.return_value = mock_response

        with pytest.raises(Exception, match="502 Bad Gateway"):
            fetch_archive_chunk(
                mock_client, 58.2483, 22.4939, date(2026, 1, 1), date(2026, 1, 30)
            )
