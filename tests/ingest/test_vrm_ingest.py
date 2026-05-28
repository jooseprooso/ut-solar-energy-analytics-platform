from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
import requests as req

from src.ingest.vrm_ingest import _fetch_diagnostics, _upsert, main

SAMPLE_PAYLOAD = {
    "records": [
        {"idDataAttribute": 1, "description": "Battery voltage", "rawValue": 25.98, "unit": "V"},
        {"idDataAttribute": 2, "description": "Solar power", "rawValue": 1200.0, "unit": "W"},
    ]
}

FULL_ENV = {
    "VRM_API_TOKEN": "test-token",
    "VRM_SITE_ID": "12345",
    "SUPABASE_DB_HOST": "localhost",
    "SUPABASE_DB_PORT": "5432",
    "SUPABASE_DB_NAME": "testdb",
    "SUPABASE_DB_USER": "user",
    "SUPABASE_DB_PASSWORD": "secret",
}


def _mock_conn():
    cursor = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn, cursor


class TestFetchDiagnostics:
    def test_returns_payload_on_success(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = SAMPLE_PAYLOAD
        with patch("src.ingest.vrm_ingest.requests.get", return_value=mock_resp):
            result = _fetch_diagnostics("token", "42")
        assert result == SAMPLE_PAYLOAD

    def test_uses_correct_url(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = SAMPLE_PAYLOAD
        with patch("src.ingest.vrm_ingest.requests.get", return_value=mock_resp) as mock_get:
            _fetch_diagnostics("token", "99999")
        url = mock_get.call_args[0][0]
        assert url == "https://vrmapi.victronenergy.com/v2/installations/99999/diagnostics"

    def test_sends_bearer_token_header(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = SAMPLE_PAYLOAD
        with patch("src.ingest.vrm_ingest.requests.get", return_value=mock_resp) as mock_get:
            _fetch_diagnostics("my-secret-token", "42")
        headers = mock_get.call_args[1]["headers"]
        assert headers["x-authorization"] == "Token my-secret-token"

    def test_raises_on_http_error(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = req.HTTPError("403 Forbidden")
        with patch("src.ingest.vrm_ingest.requests.get", return_value=mock_resp):
            with pytest.raises(req.HTTPError):
                _fetch_diagnostics("bad-token", "42")

    def test_raises_on_timeout(self):
        with patch("src.ingest.vrm_ingest.requests.get", side_effect=req.Timeout):
            with pytest.raises(req.Timeout):
                _fetch_diagnostics("token", "42")


class TestUpsert:
    def test_executes_insert_into_bronze_vrm_raw(self):
        conn, cursor = _mock_conn()
        _upsert(conn, "42", datetime(2026, 5, 27, 10, tzinfo=timezone.utc), SAMPLE_PAYLOAD)
        sql = cursor.execute.call_args[0][0]
        assert "INSERT INTO bronze.vrm_raw" in sql

    def test_sql_contains_on_conflict_upsert(self):
        conn, cursor = _mock_conn()
        _upsert(conn, "42", datetime(2026, 5, 27, 10, tzinfo=timezone.utc), SAMPLE_PAYLOAD)
        sql = cursor.execute.call_args[0][0]
        assert "ON CONFLICT" in sql
        assert "DO UPDATE" in sql

    def test_passes_site_id_as_first_param(self):
        conn, cursor = _mock_conn()
        _upsert(conn, "site-xyz", datetime(2026, 5, 27, 10, tzinfo=timezone.utc), SAMPLE_PAYLOAD)
        params = cursor.execute.call_args[0][1]
        assert params[0] == "site-xyz"

    def test_passes_fetched_at_as_second_param(self):
        conn, cursor = _mock_conn()
        ts = datetime(2026, 5, 27, 10, 0, 0, tzinfo=timezone.utc)
        _upsert(conn, "42", ts, SAMPLE_PAYLOAD)
        params = cursor.execute.call_args[0][1]
        assert params[1] == ts

    def test_passes_diagnostics_as_endpoint(self):
        conn, cursor = _mock_conn()
        _upsert(conn, "42", datetime(2026, 5, 27, 10, tzinfo=timezone.utc), SAMPLE_PAYLOAD)
        params = cursor.execute.call_args[0][1]
        assert params[3] == "diagnostics"

    def test_serialises_payload_as_json(self):
        conn, cursor = _mock_conn()
        _upsert(conn, "42", datetime(2026, 5, 27, 10, tzinfo=timezone.utc), SAMPLE_PAYLOAD)
        params = cursor.execute.call_args[0][1]
        assert json.loads(params[4]) == SAMPLE_PAYLOAD

    def test_commits_after_insert(self):
        conn, _ = _mock_conn()
        _upsert(conn, "42", datetime(2026, 5, 27, 10, tzinfo=timezone.utc), SAMPLE_PAYLOAD)
        conn.commit.assert_called_once()


class TestMain:
    def test_skips_and_returns_zero_when_token_missing(self, monkeypatch):
        monkeypatch.delenv("VRM_API_TOKEN", raising=False)
        monkeypatch.setenv("VRM_SITE_ID", "12345")
        assert main() == 0

    def test_skips_and_returns_zero_when_site_id_missing(self, monkeypatch):
        monkeypatch.setenv("VRM_API_TOKEN", "token")
        monkeypatch.delenv("VRM_SITE_ID", raising=False)
        assert main() == 0

    def test_returns_zero_on_successful_run(self, monkeypatch):
        for k, v in FULL_ENV.items():
            monkeypatch.setenv(k, v)
        mock_conn = MagicMock()
        with patch("src.ingest.vrm_ingest._fetch_diagnostics", return_value=SAMPLE_PAYLOAD), \
             patch("src.ingest.vrm_ingest._db_conn", return_value=mock_conn), \
             patch("src.ingest.vrm_ingest._upsert"):
            assert main() == 0

    def test_fetches_with_token_and_site_id_from_env(self, monkeypatch):
        for k, v in FULL_ENV.items():
            monkeypatch.setenv(k, v)
        mock_conn = MagicMock()
        with patch("src.ingest.vrm_ingest._fetch_diagnostics", return_value=SAMPLE_PAYLOAD) as mock_fetch, \
             patch("src.ingest.vrm_ingest._db_conn", return_value=mock_conn), \
             patch("src.ingest.vrm_ingest._upsert"):
            main()
        mock_fetch.assert_called_once_with("test-token", "12345")

    def test_upserts_fetched_payload(self, monkeypatch):
        for k, v in FULL_ENV.items():
            monkeypatch.setenv(k, v)
        mock_conn = MagicMock()
        with patch("src.ingest.vrm_ingest._fetch_diagnostics", return_value=SAMPLE_PAYLOAD), \
             patch("src.ingest.vrm_ingest._db_conn", return_value=mock_conn), \
             patch("src.ingest.vrm_ingest._upsert") as mock_upsert:
            main()
        mock_upsert.assert_called_once()
        conn_arg, site_arg, _ts, payload_arg = mock_upsert.call_args[0]
        assert site_arg == "12345"
        assert payload_arg == SAMPLE_PAYLOAD

    def test_closes_db_connection_after_success(self, monkeypatch):
        for k, v in FULL_ENV.items():
            monkeypatch.setenv(k, v)
        mock_conn = MagicMock()
        with patch("src.ingest.vrm_ingest._fetch_diagnostics", return_value=SAMPLE_PAYLOAD), \
             patch("src.ingest.vrm_ingest._db_conn", return_value=mock_conn), \
             patch("src.ingest.vrm_ingest._upsert"):
            main()
        mock_conn.close.assert_called_once()

    def test_closes_db_connection_even_when_upsert_raises(self, monkeypatch):
        for k, v in FULL_ENV.items():
            monkeypatch.setenv(k, v)
        mock_conn = MagicMock()
        with patch("src.ingest.vrm_ingest._fetch_diagnostics", return_value=SAMPLE_PAYLOAD), \
             patch("src.ingest.vrm_ingest._db_conn", return_value=mock_conn), \
             patch("src.ingest.vrm_ingest._upsert", side_effect=Exception("db failure")):
            with pytest.raises(Exception):
                main()
        mock_conn.close.assert_called_once()
