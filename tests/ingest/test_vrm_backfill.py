from __future__ import annotations

import json
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
import requests as req

from src.ingest.vrm_backfill import (
    BackfillConfig,
    build_backfill_config_from_env,
    date_chunks,
    fetch_stats_chunk,
    main,
    run_backfill,
    unpack_to_hourly_rows,
    upsert_stats_rows,
)

FULL_ENV = {
    "VRM_API_TOKEN": "test-token",
    "VRM_SITE_ID": "771912",
    "SUPABASE_DB_HOST": "localhost",
    "SUPABASE_DB_PORT": "5432",
    "SUPABASE_DB_NAME": "testdb",
    "SUPABASE_DB_USER": "user",
    "SUPABASE_DB_PASSWORD": "secret",
}

SAMPLE_RECORDS = {
    "bs": [[1780000000000, 90.0, 88.0, 92.0], [1780003600000, 85.0, 83.0, 87.0]],
    "bv": [[1780000000000, 52.5, 52.1, 52.9], [1780003600000, 51.8, 51.5, 52.1]],
    "total_solar_yield": [[1780000000000, 0.45], [1780003600000, 0.62]],
    "total_consumption": [[1780000000000, 1.1], [1780003600000, 0.9]],
    "total_genset": [],
    "grid_history_from": [],
}


def _mock_conn():
    cursor = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn, cursor


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


class TestFetchStatsChunk:
    def test_calls_correct_url(self):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"records": {}}
        mock_session.get.return_value = mock_resp

        fetch_stats_chunk(mock_session, "tok", "771912", date(2026, 1, 1), date(2026, 1, 30))

        url = mock_session.get.call_args[0][0]
        assert url == "https://vrmapi.victronenergy.com/v2/installations/771912/stats"

    def test_sends_bearer_token_header(self):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"records": {}}
        mock_session.get.return_value = mock_resp

        fetch_stats_chunk(mock_session, "my-token", "771912", date(2026, 1, 1), date(2026, 1, 30))

        headers = mock_session.get.call_args[1]["headers"]
        assert headers["x-authorization"] == "Token my-token"

    def test_sends_hourly_interval(self):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"records": {}}
        mock_session.get.return_value = mock_resp

        fetch_stats_chunk(mock_session, "tok", "771912", date(2026, 1, 1), date(2026, 1, 30))

        params = dict(mock_session.get.call_args[1]["params"])
        assert params["interval"] == "hours"

    def test_raises_on_http_error(self):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = req.HTTPError("403 Forbidden")
        mock_session.get.return_value = mock_resp

        with pytest.raises(req.HTTPError):
            fetch_stats_chunk(mock_session, "bad-token", "771912", date(2026, 1, 1), date(2026, 1, 2))


class TestUnpackToHourlyRows:
    def test_returns_one_row_per_timestamp(self):
        fetched_at = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
        rows = unpack_to_hourly_rows(SAMPLE_RECORDS, fetched_at)
        assert len(rows) == 2

    def test_row_structure_is_fetched_hour_fetched_at_payload(self):
        fetched_at = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
        rows = unpack_to_hourly_rows(SAMPLE_RECORDS, fetched_at)
        fetched_hour, fa, payload = rows[0]
        assert isinstance(fetched_hour, datetime)
        assert fa == fetched_at
        assert isinstance(payload, dict)

    def test_fetched_hour_is_truncated_to_hour(self):
        fetched_at = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
        rows = unpack_to_hourly_rows(SAMPLE_RECORDS, fetched_at)
        for fetched_hour, _, _ in rows:
            assert fetched_hour.minute == 0
            assert fetched_hour.second == 0

    def test_maps_known_codes_into_payload(self):
        fetched_at = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
        rows = unpack_to_hourly_rows(SAMPLE_RECORDS, fetched_at)
        _, _, payload = rows[0]
        assert "bs" in payload
        assert "bv" in payload
        assert "total_solar_yield" in payload
        assert "total_consumption" in payload

    def test_excludes_unknown_codes(self):
        fetched_at = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
        rows = unpack_to_hourly_rows(SAMPLE_RECORDS, fetched_at)
        _, _, payload = rows[0]
        assert "total_genset" not in payload
        assert "grid_history_from" not in payload

    def test_uses_avg_value_for_measurements(self):
        fetched_at = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
        rows = unpack_to_hourly_rows(SAMPLE_RECORDS, fetched_at)
        _, _, payload = rows[0]
        assert payload["bs"] == 90.0   # avg, not min/max

    def test_empty_records_returns_no_rows(self):
        fetched_at = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
        rows = unpack_to_hourly_rows({}, fetched_at)
        assert rows == []

    def test_rows_are_sorted_by_timestamp(self):
        fetched_at = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
        rows = unpack_to_hourly_rows(SAMPLE_RECORDS, fetched_at)
        hours = [r[0] for r in rows]
        assert hours == sorted(hours)


class TestUpsertStatsRows:
    def test_inserts_into_vrm_stats_raw(self):
        conn, cursor = _mock_conn()
        fetched_at = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
        fetched_hour = datetime(2026, 5, 31, 10, 0, tzinfo=timezone.utc)
        rows = [(fetched_hour, fetched_at, {"bs": 90.0})]

        upsert_stats_rows(conn, "771912", rows)

        sql = cursor.execute.call_args[0][0]
        assert "INSERT INTO bronze.vrm_stats_raw" in sql
        assert "ON CONFLICT" in sql

    def test_serialises_payload_as_json(self):
        conn, cursor = _mock_conn()
        fetched_at = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
        fetched_hour = datetime(2026, 5, 31, 10, 0, tzinfo=timezone.utc)
        payload = {"bs": 90.0, "total_solar_yield": 0.45}
        rows = [(fetched_hour, fetched_at, payload)]

        upsert_stats_rows(conn, "771912", rows)

        params = cursor.execute.call_args[0][1]
        assert json.loads(params[3]) == payload

    def test_returns_row_count(self):
        conn, _ = _mock_conn()
        fetched_at = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
        rows = [
            (datetime(2026, 5, 31, h, 0, tzinfo=timezone.utc), fetched_at, {"bs": 90.0})
            for h in range(5)
        ]
        count = upsert_stats_rows(conn, "771912", rows)
        assert count == 5

    def test_commits_after_inserts(self):
        conn, _ = _mock_conn()
        fetched_at = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
        rows = [(datetime(2026, 5, 31, 10, 0, tzinfo=timezone.utc), fetched_at, {"bs": 90.0})]
        upsert_stats_rows(conn, "771912", rows)
        conn.commit.assert_called_once()


class TestRunBackfill:
    def _make_config(self):
        return BackfillConfig(
            token="tok",
            site_id="771912",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 10),
        )

    def test_processes_all_chunks_and_returns_total_rows(self):
        config = self._make_config()
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"records": SAMPLE_RECORDS}
        mock_session.get.return_value = mock_resp
        conn, _ = _mock_conn()

        total = run_backfill(config, mock_session, conn)

        assert total == 2
        mock_session.get.assert_called_once()

    def test_handles_empty_response(self):
        config = self._make_config()
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"records": {}}
        mock_session.get.return_value = mock_resp
        conn, _ = _mock_conn()

        total = run_backfill(config, mock_session, conn)

        assert total == 0

    def test_propagates_fetch_error(self):
        config = self._make_config()
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("503 Service Unavailable")
        mock_session.get.return_value = mock_resp
        conn, _ = _mock_conn()

        with pytest.raises(Exception, match="503 Service Unavailable"):
            run_backfill(config, mock_session, conn)

    def test_multiple_chunks_sum_rows(self):
        config = BackfillConfig(
            token="tok",
            site_id="771912",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
            chunk_days=30,
        )
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"records": SAMPLE_RECORDS}
        mock_session.get.return_value = mock_resp
        conn, _ = _mock_conn()

        total = run_backfill(config, mock_session, conn)

        assert mock_session.get.call_count == 3
        assert total == 6  # 2 rows per chunk × 3 chunks


class TestBuildBackfillConfigFromEnv:
    @pytest.fixture
    def env_vars(self, monkeypatch):
        for k, v in FULL_ENV.items():
            monkeypatch.setenv(k, v)

    def test_raises_on_missing_env(self):
        with pytest.raises(ValueError):
            build_backfill_config_from_env()

    def test_builds_config_from_env(self, env_vars):
        config = build_backfill_config_from_env()
        assert config.token == "test-token"
        assert config.site_id == "771912"
        assert (config.end_date - config.start_date).days == 182

    def test_respects_date_overrides(self, env_vars, monkeypatch):
        monkeypatch.setenv("VRM_BACKFILL_START", "2026-03-01")
        monkeypatch.setenv("VRM_BACKFILL_END", "2026-04-01")

        config = build_backfill_config_from_env()

        assert config.start_date == date(2026, 3, 1)
        assert config.end_date == date(2026, 4, 1)


class TestMain:
    @pytest.fixture
    def env_vars(self, monkeypatch):
        for k, v in FULL_ENV.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("VRM_BACKFILL_START", "2026-05-01")
        monkeypatch.setenv("VRM_BACKFILL_END", "2026-05-10")

    def test_returns_1_on_missing_env(self):
        assert main() == 1

    @patch("src.ingest.vrm_backfill.psycopg2.connect")
    @patch("src.ingest.vrm_backfill.build_http_client")
    @patch("src.ingest.vrm_backfill.run_backfill")
    def test_returns_0_on_success(self, mock_run, mock_http, mock_conn, env_vars):
        mock_run.return_value = 100

        result = main()

        assert result == 0
        mock_run.assert_called_once()
        mock_conn.return_value.close.assert_called_once()

    @patch("src.ingest.vrm_backfill.psycopg2.connect")
    def test_returns_1_on_db_connection_failure(self, mock_conn, env_vars):
        mock_conn.side_effect = Exception("connection refused")

        result = main()

        assert result == 1

    @patch("src.ingest.vrm_backfill.psycopg2.connect")
    @patch("src.ingest.vrm_backfill.build_http_client")
    @patch("src.ingest.vrm_backfill.run_backfill")
    def test_returns_1_on_backfill_failure(self, mock_run, mock_http, mock_conn, env_vars):
        mock_run.side_effect = Exception("API error")

        result = main()

        assert result == 1
        mock_conn.return_value.close.assert_called_once()
