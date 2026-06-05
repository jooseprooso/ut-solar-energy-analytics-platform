from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.ingest.meteo_backfill import (
    BackfillConfig,
    build_backfill_config_from_env,
    date_chunks,
    main,
    run_backfill,
)


class TestDateChunks:
    def test_single_chunk_when_range_smaller_than_chunk_size(self):
        chunks = date_chunks(date(2026, 1, 1), date(2026, 1, 15), chunk_days=30)
        assert chunks == [(date(2026, 1, 1), date(2026, 1, 15))]

    def test_splits_into_multiple_chunks(self):
        chunks = date_chunks(date(2026, 1, 1), date(2026, 3, 31), chunk_days=30)
        assert len(chunks) == 3
        assert chunks[0] == (date(2026, 1, 1), date(2026, 1, 30))
        assert chunks[1] == (date(2026, 1, 31), date(2026, 3, 1))
        assert chunks[2] == (date(2026, 3, 2), date(2026, 3, 31))

    def test_exact_chunk_boundary(self):
        chunks = date_chunks(date(2026, 1, 1), date(2026, 1, 30), chunk_days=30)
        assert chunks == [(date(2026, 1, 1), date(2026, 1, 30))]

    def test_single_day(self):
        chunks = date_chunks(date(2026, 5, 1), date(2026, 5, 1), chunk_days=30)
        assert chunks == [(date(2026, 5, 1), date(2026, 5, 1))]


class TestRunBackfill:
    def test_processes_all_chunks_and_returns_total_rows(self):
        config = BackfillConfig(
            latitude=58.2483,
            longitude=22.4939,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 10),
        )
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "hourly": {
                "time": ["2026-05-01T00:00", "2026-05-01T01:00"],
                "sunshine_duration": [3600.0, 3600.0],
                "shortwave_radiation": [100.0, 200.0],
                "direct_radiation": [80.0, 160.0],
                "cloud_cover": [10.0, 20.0],
            },
            "hourly_units": {
                "sunshine_duration": "s",
                "shortwave_radiation": "W/m²",
                "direct_radiation": "W/m²",
                "cloud_cover": "%",
            },
        }
        mock_client.get.return_value = mock_response

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        total = run_backfill(config, mock_client, mock_conn)

        assert total == 8
        mock_client.get.assert_called_once()
        mock_conn.commit.assert_called_once()

    def test_handles_empty_response(self):
        config = BackfillConfig(
            latitude=58.2483,
            longitude=22.4939,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 5),
        )
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"hourly": {"time": []}, "hourly_units": {}}
        mock_client.get.return_value = mock_response

        mock_conn = MagicMock()

        total = run_backfill(config, mock_client, mock_conn)

        assert total == 0

    def test_propagates_fetch_error(self):
        config = BackfillConfig(
            latitude=58.2483,
            longitude=22.4939,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 5),
        )
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("503 Service Unavailable")
        mock_client.get.return_value = mock_response

        mock_conn = MagicMock()

        with pytest.raises(Exception, match="503 Service Unavailable"):
            run_backfill(config, mock_client, mock_conn)


class TestBuildBackfillConfigFromEnv:
    @pytest.fixture
    def env_vars(self, monkeypatch):
        monkeypatch.setenv("METEO_LAT", "58.2483")
        monkeypatch.setenv("METEO_LON", "22.4939")
        monkeypatch.setenv("SUPABASE_DB_HOST", "localhost")
        monkeypatch.setenv("SUPABASE_DB_PORT", "5432")
        monkeypatch.setenv("SUPABASE_DB_NAME", "test_db")
        monkeypatch.setenv("SUPABASE_DB_USER", "user")
        monkeypatch.setenv("SUPABASE_DB_PASSWORD", "pass")

    def test_raises_on_missing_env(self):
        with pytest.raises(ValueError):
            build_backfill_config_from_env()

    def test_builds_config_with_defaults(self, env_vars):
        config = build_backfill_config_from_env()

        assert config.latitude == 58.2483
        assert config.longitude == 22.4939
        assert config.table_name == "meteo_raw"
        assert (config.end_date - config.start_date).days == 182

    def test_respects_date_overrides(self, env_vars, monkeypatch):
        monkeypatch.setenv("METEO_BACKFILL_START", "2026-03-01")
        monkeypatch.setenv("METEO_BACKFILL_END", "2026-04-01")

        config = build_backfill_config_from_env()

        assert config.start_date == date(2026, 3, 1)
        assert config.end_date == date(2026, 4, 1)

    def test_respects_table_prefix(self, env_vars, monkeypatch):
        monkeypatch.setenv("BRONZE_TABLE_PREFIX", "test_")

        config = build_backfill_config_from_env()

        assert config.table_name == "test_meteo_raw"


class TestMain:
    @pytest.fixture
    def env_vars(self, monkeypatch):
        monkeypatch.setenv("METEO_LAT", "58.2483")
        monkeypatch.setenv("METEO_LON", "22.4939")
        monkeypatch.setenv("SUPABASE_DB_HOST", "localhost")
        monkeypatch.setenv("SUPABASE_DB_PORT", "5432")
        monkeypatch.setenv("SUPABASE_DB_NAME", "test_db")
        monkeypatch.setenv("SUPABASE_DB_USER", "user")
        monkeypatch.setenv("SUPABASE_DB_PASSWORD", "pass")
        monkeypatch.setenv("METEO_BACKFILL_START", "2026-05-01")
        monkeypatch.setenv("METEO_BACKFILL_END", "2026-05-10")

    def test_returns_1_on_missing_env(self):
        assert main() == 1

    @patch("src.ingest.meteo_backfill.build_connection")
    @patch("src.ingest.meteo_backfill.build_http_client")
    @patch("src.ingest.meteo_backfill.run_backfill")
    def test_returns_0_on_success(self, mock_run, mock_http, mock_conn, env_vars):
        mock_run.return_value = 100

        result = main()

        assert result == 0
        mock_run.assert_called_once()
        mock_conn.return_value.close.assert_called_once()

    @patch("src.ingest.meteo_backfill.build_connection")
    def test_returns_1_on_db_connection_failure(self, mock_conn, env_vars):
        mock_conn.side_effect = Exception("connection refused")

        result = main()

        assert result == 1

    @patch("src.ingest.meteo_backfill.build_connection")
    @patch("src.ingest.meteo_backfill.build_http_client")
    @patch("src.ingest.meteo_backfill.run_backfill")
    def test_returns_1_on_backfill_failure(self, mock_run, mock_http, mock_conn, env_vars):
        mock_run.side_effect = Exception("API error")

        result = main()

        assert result == 1
        mock_conn.return_value.close.assert_called_once()
