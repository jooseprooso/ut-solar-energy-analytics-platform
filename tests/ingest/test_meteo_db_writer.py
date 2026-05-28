from unittest.mock import Mock

import pytest

from src.ingest.meteo_db_writer import UPSERT_SQL, upsert_meteo_rows


@pytest.fixture
def mock_conn():
    conn = Mock()
    conn.cursor.return_value = Mock()
    return conn


@pytest.fixture
def sample_rows():
    return [
        {
            "timestamp_utc": "2026-05-24T00:00:00+00:00",
            "latitude": 58.2538,
            "longitude": 22.4922,
            "variable_name": "sunshine_duration",
            "value": 3600.0,
            "unit": "s",
        },
        {
            "timestamp_utc": "2026-05-24T01:00:00+00:00",
            "latitude": 58.2538,
            "longitude": 22.4922,
            "variable_name": "sunshine_duration",
            "value": 1800.0,
            "unit": "s",
        },
    ]


class TestUpsertMeteoRows:
    def test_ensures_table_exists_before_upsert(self, mock_conn, sample_rows):
        upsert_meteo_rows(sample_rows, mock_conn)
        create_sql = mock_conn.cursor.return_value.execute.call_args.args[0]
        assert "CREATE TABLE IF NOT EXISTS bronze.meteo_raw" in create_sql

    def test_calls_executemany_with_correct_sql(self, mock_conn, sample_rows):
        upsert_meteo_rows(sample_rows, mock_conn)
        cursor = mock_conn.cursor.return_value
        cursor.executemany.assert_called_once_with(UPSERT_SQL, sample_rows)

    def test_supports_smoke_test_table_name(self, mock_conn, sample_rows):
        upsert_meteo_rows(sample_rows, mock_conn, table_name="smoke_test_meteo_raw")
        cursor = mock_conn.cursor.return_value
        create_sql = cursor.execute.call_args.args[0]
        upsert_sql = cursor.executemany.call_args.args[0]
        assert "CREATE TABLE IF NOT EXISTS bronze.smoke_test_meteo_raw" in create_sql
        assert "INSERT INTO bronze.smoke_test_meteo_raw" in upsert_sql

    def test_commits_transaction(self, mock_conn, sample_rows):
        upsert_meteo_rows(sample_rows, mock_conn)
        mock_conn.commit.assert_called_once()

    def test_closes_cursor(self, mock_conn, sample_rows):
        upsert_meteo_rows(sample_rows, mock_conn)
        mock_conn.cursor.return_value.close.assert_called_once()

    def test_returns_row_count(self, mock_conn, sample_rows):
        result = upsert_meteo_rows(sample_rows, mock_conn)
        assert result == 2

    def test_empty_list_returns_zero(self, mock_conn):
        result = upsert_meteo_rows([], mock_conn)
        assert result == 0

    def test_empty_list_does_not_call_db(self, mock_conn):
        upsert_meteo_rows([], mock_conn)
        mock_conn.cursor.assert_not_called()
        mock_conn.commit.assert_not_called()
