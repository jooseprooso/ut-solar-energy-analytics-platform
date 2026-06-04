from __future__ import annotations

from unittest.mock import MagicMock
from datetime import datetime, date, timezone

from src.forecast.db import upsert_forecasts, UPSERT_SQL


class TestUpsertForecasts:
    def test_returns_zero_for_empty(self):
        conn = MagicMock()
        assert upsert_forecasts(conn, []) == 0
        conn.cursor.assert_not_called()

    def test_calls_executemany_with_rows(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        rows = [
            ("771912", datetime(2026, 5, 10, 8, tzinfo=timezone.utc),
             date(2026, 5, 10), "backtest", 1.23,
             datetime(2026, 5, 10, tzinfo=timezone.utc), "ridge_v1"),
        ]
        count = upsert_forecasts(conn, rows)

        assert count == 1
        cursor.executemany.assert_called_once_with(UPSERT_SQL, rows)
        conn.commit.assert_called_once()
        cursor.close.assert_called_once()

    def test_idempotent_upsert_sql(self):
        assert "ON CONFLICT" in UPSERT_SQL
        assert "DO UPDATE SET" in UPSERT_SQL
