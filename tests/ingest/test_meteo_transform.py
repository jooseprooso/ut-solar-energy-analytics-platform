from datetime import datetime, timezone

import pytest

from src.ingest.meteo_transform import parse_hourly_response


@pytest.fixture
def sample_api_response():
    return {
        "hourly_units": {
            "time": "iso8601",
            "sunshine_duration": "s",
            "shortwave_radiation": "W/m²",
            "direct_radiation": "W/m²",
            "cloud_cover": "%",
        },
        "hourly": {
            "time": [
                "2026-05-24T00:00",
                "2026-05-24T01:00",
                "2026-05-24T02:00",
            ],
            "sunshine_duration": [3600.0, 1800.0, 0.0],
            "shortwave_radiation": [250.0, 120.0, 0.0],
            "direct_radiation": [200.0, 80.0, 0.0],
            "cloud_cover": [10.0, 50.0, 100.0],
        },
    }


class TestParseHourlyResponse:
    def test_returns_rows_for_all_variables(self, sample_api_response):
        rows = parse_hourly_response(sample_api_response, 58.2538, 22.4922)
        assert len(rows) == 12  # 4 variables x 3 timestamps

    def test_row_contains_expected_keys(self, sample_api_response):
        rows = parse_hourly_response(sample_api_response, 58.2538, 22.4922)
        expected_keys = {
            "timestamp_utc",
            "latitude",
            "longitude",
            "variable_name",
            "value",
            "unit",
        }
        assert set(rows[0].keys()) == expected_keys

    def test_preserves_coordinates(self, sample_api_response):
        rows = parse_hourly_response(sample_api_response, 58.2538, 22.4922)
        for row in rows:
            assert row["latitude"] == 58.2538
            assert row["longitude"] == 22.4922

    def test_preserves_units(self, sample_api_response):
        rows = parse_hourly_response(sample_api_response, 58.2538, 22.4922)
        units_by_var = {row["variable_name"]: row["unit"] for row in rows}
        assert units_by_var["sunshine_duration"] == "s"
        assert units_by_var["shortwave_radiation"] == "W/m²"
        assert units_by_var["direct_radiation"] == "W/m²"
        assert units_by_var["cloud_cover"] == "%"

    def test_handles_null_values(self):
        response = {
            "hourly_units": {"time": "iso8601", "sunshine_duration": "s"},
            "hourly": {
                "time": ["2026-05-24T00:00", "2026-05-24T01:00"],
                "sunshine_duration": [3600.0, None],
            },
        }
        rows = parse_hourly_response(response, 58.2538, 22.4922)
        assert rows[0]["value"] == 3600.0
        assert rows[1]["value"] is None

    def test_empty_hourly_returns_empty_list(self):
        response = {"hourly_units": {}, "hourly": {}}
        rows = parse_hourly_response(response, 58.2538, 22.4922)
        assert rows == []

    def test_missing_hourly_key_returns_empty_list(self):
        response = {}
        rows = parse_hourly_response(response, 58.2538, 22.4922)
        assert rows == []

    def test_timestamps_are_utc_aware(self, sample_api_response):
        rows = parse_hourly_response(sample_api_response, 58.2538, 22.4922)
        for row in rows:
            assert row["timestamp_utc"].tzinfo is not None

    def test_parses_naive_timestamp_as_utc(self):
        response = {
            "hourly_units": {"time": "iso8601", "sunshine_duration": "s"},
            "hourly": {
                "time": ["2026-05-24T12:00"],
                "sunshine_duration": [100.0],
            },
        }
        rows = parse_hourly_response(response, 58.2538, 22.4922)
        assert rows[0]["timestamp_utc"] == datetime(2026, 5, 24, 12, 0, tzinfo=timezone.utc)
