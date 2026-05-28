from unittest.mock import Mock, patch

import pytest

from src.ingest.meteo_ingest import main


@pytest.fixture
def full_env(monkeypatch):
    env_vars = {
        "METEO_LAT": "58.2538",
        "METEO_LON": "22.4922",
        "METEO_TIMEZONE": "auto",
        "SUPABASE_DB_HOST": "localhost",
        "SUPABASE_DB_PORT": "5432",
        "SUPABASE_DB_NAME": "testdb",
        "SUPABASE_DB_USER": "user",
        "SUPABASE_DB_PASSWORD": "pass",
    }
    for key, val in env_vars.items():
        monkeypatch.setenv(key, val)


class TestMain:
    def test_returns_1_when_env_vars_missing(self, monkeypatch):
        monkeypatch.delenv("METEO_LAT", raising=False)
        monkeypatch.delenv("METEO_LON", raising=False)
        assert main() == 1

    @patch("src.ingest.meteo_ingest.fetch_hourly_weather")
    def test_returns_1_when_api_fails(self, mock_fetch, full_env):
        mock_fetch.side_effect = RuntimeError("connection timeout")
        assert main() == 1

    @patch("src.ingest.meteo_ingest.build_connection")
    @patch("src.ingest.meteo_ingest.fetch_hourly_weather")
    def test_returns_1_when_db_fails(self, mock_fetch, mock_build_conn, full_env):
        mock_fetch.return_value = {
            "hourly_units": {"time": "iso8601", "sunshine_duration": "s"},
            "hourly": {"time": ["2026-05-24T00:00"], "sunshine_duration": [100.0]},
        }
        mock_build_conn.side_effect = RuntimeError("db unreachable")
        assert main() == 1

    @patch("src.ingest.meteo_ingest.upsert_meteo_rows")
    @patch("src.ingest.meteo_ingest.build_connection")
    @patch("src.ingest.meteo_ingest.fetch_hourly_weather")
    def test_returns_0_on_success(self, mock_fetch, mock_build_conn, mock_upsert, full_env):
        mock_fetch.return_value = {
            "hourly_units": {"time": "iso8601", "sunshine_duration": "s"},
            "hourly": {"time": ["2026-05-24T00:00"], "sunshine_duration": [100.0]},
        }
        mock_conn = Mock()
        mock_build_conn.return_value = mock_conn
        mock_upsert.return_value = 1
        assert main() == 0
        mock_upsert.assert_called_once()
        mock_conn.close.assert_called_once()

    @patch("src.ingest.meteo_ingest.upsert_meteo_rows")
    @patch("src.ingest.meteo_ingest.build_connection")
    @patch("src.ingest.meteo_ingest.fetch_hourly_weather")
    def test_uses_smoke_test_prefix_when_provided(
        self, mock_fetch, mock_build_conn, mock_upsert, full_env, monkeypatch
    ):
        monkeypatch.setenv("BRONZE_TABLE_PREFIX", "smoke_test_")
        mock_fetch.return_value = {
            "hourly_units": {"time": "iso8601", "sunshine_duration": "s"},
            "hourly": {"time": ["2026-05-24T00:00"], "sunshine_duration": [100.0]},
        }
        mock_conn = Mock()
        mock_build_conn.return_value = mock_conn
        mock_upsert.return_value = 1

        assert main() == 0
        mock_upsert.assert_called_once()
        assert mock_upsert.call_args.kwargs["table_name"] == "smoke_test_meteo_raw"

    @patch("src.ingest.meteo_ingest.upsert_meteo_rows")
    @patch("src.ingest.meteo_ingest.build_connection")
    @patch("src.ingest.meteo_ingest.fetch_hourly_weather")
    def test_returns_0_when_no_rows(self, mock_fetch, mock_build_conn, mock_upsert, full_env):
        mock_fetch.return_value = {"hourly_units": {}, "hourly": {}}
        assert main() == 0
        mock_build_conn.assert_not_called()

    @patch("src.ingest.meteo_ingest.upsert_meteo_rows")
    @patch("src.ingest.meteo_ingest.build_connection")
    @patch("src.ingest.meteo_ingest.fetch_hourly_weather")
    def test_prints_progress(self, mock_fetch, mock_build_conn, mock_upsert, full_env, capsys):
        mock_fetch.return_value = {
            "hourly_units": {"time": "iso8601", "sunshine_duration": "s"},
            "hourly": {"time": ["2026-05-24T00:00"], "sunshine_duration": [100.0]},
        }
        mock_build_conn.return_value = Mock()
        mock_upsert.return_value = 1
        main()
        output = capsys.readouterr().out
        assert "[meteo_ingest]" in output
