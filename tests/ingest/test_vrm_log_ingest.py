from __future__ import annotations

import json
import textwrap
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.ingest.vrm_log_ingest import (
    FLAT_COLUMN_MAP,
    build_ingest_config,
    build_metrics,
    coerce_value,
    column_runs,
    download_report,
    extract_flat_values,
    ingest_csv_text,
    main,
    parse_header_timezone,
    parse_sample_time,
    unix_chunks,
    upsert_log_row,
)

_EV = "src.ingest.vrm_log_ingest.execute_values"

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

FULL_ENV = {
    "VRM_API_TOKEN": "test-token",
    "VRM_SITE_ID": "771912",
    "SUPABASE_DB_HOST": "localhost",
    "SUPABASE_DB_PORT": "5432",
    "SUPABASE_DB_NAME": "testdb",
    "SUPABASE_DB_USER": "user",
    "SUPABASE_DB_PASSWORD": "secret",
}

# Minimal valid 4-row CSV covering the required fields.
# Timestamps are Europe/Tallinn (+03:00) → UTC = local − 3 h.
SAMPLE_CSV = textwrap.dedent("""\
    ,Battery Monitor [512],Battery Monitor [512],System overview [0],System overview [0],System overview [0],PV Inverter [20],PV Inverter [20],PV Inverter [20]
    Europe/Tallinn (+03:00),State of charge,Voltage,AC Consumption L1,AC Consumption L2,AC Consumption L3,L1 Energy,L2 Energy,L3 Energy
    ,%,V,W,W,W,kWh,kWh,kWh
    2026-01-01 12:00:00,85.5,52.1,500.0,480.0,510.0,0.45,0.42,0.48
    2026-01-01 13:00:00,80.2,51.8,520.0,500.0,530.0,0.38,0.35,0.40
""")


def _mock_conn():
    cursor = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn, cursor


# ---------------------------------------------------------------------------
# TestUnixChunks
# ---------------------------------------------------------------------------

class TestUnixChunks:
    def test_single_chunk_when_range_less_than_one_day(self):
        assert unix_chunks(0, 3600, chunk_days=1) == [(0, 3600)]

    def test_splits_range_into_daily_chunks(self):
        chunks = unix_chunks(0, 3 * 86400, chunk_days=1)
        assert len(chunks) == 3
        assert chunks[0] == (0, 86400)
        assert chunks[1] == (86400, 2 * 86400)
        assert chunks[2] == (2 * 86400, 3 * 86400)

    def test_last_chunk_is_clipped_to_end(self):
        chunks = unix_chunks(0, 86400 + 3600, chunk_days=1)
        assert len(chunks) == 2
        assert chunks[1] == (86400, 86400 + 3600)

    def test_returns_empty_when_end_before_start(self):
        assert unix_chunks(100, 50) == []

    def test_returns_empty_when_start_equals_end(self):
        assert unix_chunks(100, 100) == []

    def test_respects_chunk_days(self):
        chunks = unix_chunks(0, 7 * 86400, chunk_days=7)
        assert len(chunks) == 1
        assert chunks[0] == (0, 7 * 86400)

    def test_multi_day_chunk_splits_correctly(self):
        chunks = unix_chunks(0, 14 * 86400, chunk_days=7)
        assert len(chunks) == 2


# ---------------------------------------------------------------------------
# TestDownloadReport
# ---------------------------------------------------------------------------

class TestDownloadReport:
    def _ok_session(self, text="col\nval"):
        session = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.text = text
        resp.headers = {"Content-Type": "text/csv"}
        session.get.return_value = resp
        return session

    def test_calls_correct_url(self):
        session = self._ok_session()
        download_report(session, "tok", 771912, 1700000000, 1700003600)
        url = session.get.call_args[0][0]
        assert url == "https://vrm-reports-api.victronenergy.com/download"

    def test_sends_authorization_header(self):
        session = self._ok_session()
        download_report(session, "my-token", 771912, 1700000000, 1700003600)
        headers = session.get.call_args[1]["headers"]
        assert headers["X-Authorization"] == "Token my-token"

    def test_sends_required_query_params(self):
        session = self._ok_session()
        download_report(session, "tok", 771912, 1700000000, 1700003600)
        params = dict(session.get.call_args[1]["params"])
        assert params["idSite"] == 771912
        assert params["startTime"] == 1700000000
        assert params["endTime"] == 1700003600
        assert params["type"] == "log"
        assert params["format"] == "csv"

    def test_returns_csv_text_on_200(self):
        session = self._ok_session("a,b\n1,2")
        result = download_report(session, "tok", 771912, 1700000000, 1700003600)
        assert result == "a,b\n1,2"

    def test_raises_on_non_200_status(self):
        session = MagicMock()
        resp = MagicMock()
        resp.status_code = 500
        resp.text = "Internal Server Error"
        resp.headers = {"Content-Type": "text/plain"}
        session.get.return_value = resp
        with pytest.raises(RuntimeError, match="500"):
            download_report(session, "tok", 771912, 1700000000, 1700003600)

    def test_raises_on_202_async_response(self):
        session = MagicMock()
        resp = MagicMock()
        resp.status_code = 202
        resp.text = "pending"
        resp.headers = {"Content-Type": "text/plain"}
        session.get.return_value = resp
        with pytest.raises(RuntimeError, match="202"):
            download_report(session, "tok", 771912, 1700000000, 1700003600)

    def test_raises_when_body_is_json(self):
        session = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.text = '{"error": "unauthorized"}'
        resp.headers = {"Content-Type": "application/json"}
        session.get.return_value = resp
        with pytest.raises(RuntimeError, match="JSON"):
            download_report(session, "tok", 771912, 1700000000, 1700003600)

    def test_retries_on_429_and_eventually_succeeds(self):
        session = MagicMock()
        rate_limited = MagicMock()
        rate_limited.status_code = 429
        rate_limited.text = "rate limited"
        rate_limited.headers = {"Content-Type": "text/plain"}
        ok = MagicMock()
        ok.status_code = 200
        ok.text = "col\nval"
        ok.headers = {"Content-Type": "text/csv"}
        session.get.side_effect = [rate_limited, rate_limited, ok]

        with patch("src.ingest.vrm_log_ingest.time.sleep"):
            result = download_report(session, "tok", 771912, 1700000000, 1700003600)

        assert result == "col\nval"
        assert session.get.call_count == 3

    def test_raises_after_max_429_retries(self):
        session = MagicMock()
        resp = MagicMock()
        resp.status_code = 429
        resp.text = "rate limited"
        resp.headers = {"Content-Type": "text/plain"}
        session.get.return_value = resp

        with patch("src.ingest.vrm_log_ingest.time.sleep"):
            with pytest.raises(RuntimeError, match="429"):
                download_report(session, "tok", 771912, 1700000000, 1700003600)


# ---------------------------------------------------------------------------
# TestParseHeaderTimezone
# ---------------------------------------------------------------------------

class TestParseHeaderTimezone:
    def test_parses_named_timezone(self):
        tz = parse_header_timezone("Europe/Tallinn (+03:00)")
        # January is UTC+2 (EET) in Tallinn regardless of the +03:00 label in the header
        dt = datetime(2026, 1, 1, 12, 0, tzinfo=tz)
        assert dt.astimezone(timezone.utc).hour == 10

    def test_falls_back_to_utc_offset_when_name_unknown(self):
        tz = parse_header_timezone("Unknown/Zone (+05:30)")
        offset = datetime(2026, 1, 1, 12, 0, tzinfo=tz).utcoffset()
        assert offset == timedelta(hours=5, minutes=30)

    def test_parses_negative_offset(self):
        tz = parse_header_timezone("America/New_York (-05:00)")
        dt = datetime(2026, 1, 1, 12, 0, tzinfo=tz)
        assert dt.astimezone(timezone.utc).hour == 17

    def test_returns_utc_for_empty_string(self):
        assert parse_header_timezone("") == timezone.utc

    def test_returns_utc_for_whitespace(self):
        assert parse_header_timezone("   ") == timezone.utc


# ---------------------------------------------------------------------------
# TestColumnRuns
# ---------------------------------------------------------------------------

class TestColumnRuns:
    def test_groups_consecutive_equal_labels(self):
        row0 = ["", "Battery Monitor [512]", "Battery Monitor [512]", "System overview [0]"]
        runs = column_runs(row0)
        assert runs[0] == (1, 2, "Battery Monitor [512]")
        assert runs[1] == (3, 3, "System overview [0]")

    def test_single_column_per_block(self):
        row0 = ["", "Block A", "Block B", "Block C"]
        runs = column_runs(row0)
        assert len(runs) == 3
        assert all(start == end for start, end, _ in runs)

    def test_all_same_label_is_one_run(self):
        row0 = ["", "Block A", "Block A", "Block A"]
        runs = column_runs(row0)
        assert len(runs) == 1
        assert runs[0] == (1, 3, "Block A")

    def test_empty_and_single_element_rows_return_empty(self):
        assert column_runs([]) == []
        assert column_runs(["only_col0"]) == []

    def test_strips_whitespace_from_labels(self):
        row0 = ["", "  Block A  ", "  Block A  ", " Block B "]
        runs = column_runs(row0)
        assert runs[0][2] == "Block A"
        assert runs[1][2] == "Block B"


# ---------------------------------------------------------------------------
# TestCoerceValue
# ---------------------------------------------------------------------------

class TestCoerceValue:
    def test_integer_string_returns_int(self):
        assert coerce_value("42") == 42
        assert isinstance(coerce_value("42"), int)

    def test_float_string_returns_float(self):
        assert coerce_value("3.14") == pytest.approx(3.14)

    def test_non_numeric_returns_string(self):
        assert coerce_value("alarm active") == "alarm active"

    def test_empty_string_returns_none(self):
        assert coerce_value("") is None

    def test_none_returns_none(self):
        assert coerce_value(None) is None

    def test_whitespace_only_returns_none(self):
        assert coerce_value("   ") is None

    def test_negative_integer(self):
        assert coerce_value("-5") == -5

    def test_negative_float(self):
        assert coerce_value("-3.14") == pytest.approx(-3.14)


# ---------------------------------------------------------------------------
# TestParseSampleTime
# ---------------------------------------------------------------------------

class TestParseSampleTime:
    def test_parses_local_datetime_and_converts_to_utc(self):
        tz = timezone(timedelta(hours=3))
        dt = parse_sample_time("2026-01-01 12:00:00", tz)
        assert dt == datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)

    def test_result_is_always_utc(self):
        dt = parse_sample_time("2026-06-01 10:00:00", timezone.utc)
        assert dt.tzinfo == timezone.utc

    def test_returns_none_for_empty_string(self):
        assert parse_sample_time("", timezone.utc) is None

    def test_returns_none_for_header_literal(self):
        assert parse_sample_time("timestamp", timezone.utc) is None

    def test_returns_none_for_unparseable_string(self):
        assert parse_sample_time("not a date", timezone.utc) is None

    def test_handles_fractional_seconds(self):
        dt = parse_sample_time("2026-01-01 12:00:00.500000", timezone.utc)
        assert dt is not None
        assert dt.hour == 12


# ---------------------------------------------------------------------------
# TestBuildMetrics
# ---------------------------------------------------------------------------

class TestBuildMetrics:
    def _headers(self):
        row0 = ["", "Battery Monitor [512]", "Battery Monitor [512]", "System overview [0]"]
        row1 = ["Europe/Tallinn (+03:00)", "State of charge", "Voltage", "AC Consumption L1"]
        runs = column_runs(row0)
        return row0, row1, runs

    def test_returns_nested_dict_keyed_by_block_then_metric(self):
        row0, row1, runs = self._headers()
        metrics = build_metrics(["ts", "85.5", "52.1", "500.0"], row0, row1, runs)
        assert metrics["Battery Monitor [512]"]["State of charge"] == pytest.approx(85.5)
        assert metrics["System overview [0]"]["AC Consumption L1"] == pytest.approx(500.0)

    def test_excludes_empty_values(self):
        row0, row1, runs = self._headers()
        metrics = build_metrics(["ts", "85.5", "", "500.0"], row0, row1, runs)
        assert "Voltage" not in metrics.get("Battery Monitor [512]", {})

    def test_multiple_blocks_all_present(self):
        row0 = ["", "Block A", "Block B"]
        row1 = ["tz", "m1", "m2"]
        runs = column_runs(row0)
        metrics = build_metrics(["ts", "1.0", "2.0"], row0, row1, runs)
        assert "Block A" in metrics
        assert "Block B" in metrics

    def test_returns_empty_dict_when_all_values_empty(self):
        row0 = ["", "Block A", "Block A"]
        row1 = ["tz", "m1", "m2"]
        runs = column_runs(row0)
        metrics = build_metrics(["ts", "", ""], row0, row1, runs)
        assert metrics == {}


# ---------------------------------------------------------------------------
# TestExtractFlatValues
# ---------------------------------------------------------------------------

class TestExtractFlatValues:
    def _full_metrics(self):
        return {
            "Battery Monitor [512]": {
                "State of charge": 85.5,
                "Voltage": 52.1,
                "Current": -5.0,
                "Battery temperature": 25.3,
                "Discharged Energy": 0.3,
                "Charged Energy": 0.1,
            },
            "System overview [0]": {
                "Battery Power": -250.0,
                "AC Consumption L1": 500.0,
                "AC Consumption L2": 480.0,
                "AC Consumption L3": 510.0,
            },
            "PV Inverter [20]": {
                "L1 Power": 700.0,
                "L2 Power": 650.0,
                "L3 Power": 720.0,
                "L1 Energy": 0.45,
                "L2 Energy": 0.42,
                "L3 Energy": 0.48,
            },
        }

    def test_returns_list_matching_flat_column_map_length(self):
        assert len(extract_flat_values(self._full_metrics())) == len(FLAT_COLUMN_MAP)

    def test_battery_soc_at_correct_position(self):
        keys = list(FLAT_COLUMN_MAP.keys())
        values = extract_flat_values(self._full_metrics())
        assert values[keys.index("battery_soc")] == pytest.approx(85.5)

    def test_pv_energy_l1_at_correct_position(self):
        keys = list(FLAT_COLUMN_MAP.keys())
        values = extract_flat_values(self._full_metrics())
        assert values[keys.index("pv_energy_l1")] == pytest.approx(0.45)

    def test_ac_consumption_l1_at_correct_position(self):
        keys = list(FLAT_COLUMN_MAP.keys())
        values = extract_flat_values(self._full_metrics())
        assert values[keys.index("ac_consumption_l1")] == pytest.approx(500.0)

    def test_missing_block_returns_none_for_all_its_columns(self):
        values = extract_flat_values({})
        assert all(v is None for v in values)

    def test_grid_alarm_not_coerced_to_float(self):
        metrics = {"System overview [276]": {"Grid alarm": "No alarm"}}
        keys = list(FLAT_COLUMN_MAP.keys())
        values = extract_flat_values(metrics)
        assert values[keys.index("grid_alarm")] == "No alarm"


# ---------------------------------------------------------------------------
# TestIngestCsvText
# ---------------------------------------------------------------------------

class TestIngestCsvText:
    def test_raises_when_fewer_than_4_rows(self):
        conn, _ = _mock_conn()
        with pytest.raises(ValueError, match="4"):
            ingest_csv_text("r0\nr1\nr2\n", "771912", conn,
                            datetime(2026, 1, 1, tzinfo=timezone.utc))

    def test_returns_count_of_data_rows(self):
        conn, _ = _mock_conn()
        with patch(_EV):
            count = ingest_csv_text(SAMPLE_CSV, "771912", conn,
                                    datetime(2026, 1, 1, 12, tzinfo=timezone.utc))
        assert count == 2

    def test_dry_run_skips_db_writes(self):
        conn, _ = _mock_conn()
        with patch(_EV) as mock_ev:
            ingest_csv_text(SAMPLE_CSV, "771912", conn,
                            datetime(2026, 1, 1, 12, tzinfo=timezone.utc), dry_run=True)
        mock_ev.assert_not_called()
        conn.commit.assert_not_called()

    def test_skips_blank_rows(self):
        conn, _ = _mock_conn()
        with patch(_EV):
            count = ingest_csv_text(SAMPLE_CSV + "\n\n", "771912", conn,
                                    datetime(2026, 1, 1, 12, tzinfo=timezone.utc))
        assert count == 2

    def test_commits_after_processing(self):
        conn, _ = _mock_conn()
        with patch(_EV):
            ingest_csv_text(SAMPLE_CSV, "771912", conn,
                            datetime(2026, 1, 1, 12, tzinfo=timezone.utc))
        conn.commit.assert_called_once()

    def test_all_rows_sent_in_single_execute_values_call(self):
        conn, _ = _mock_conn()
        with patch(_EV) as mock_ev:
            ingest_csv_text(SAMPLE_CSV, "771912", conn,
                            datetime(2026, 1, 1, 12, tzinfo=timezone.utc))
        mock_ev.assert_called_once()
        batch = mock_ev.call_args[0][2]
        assert len(batch) == 2

    def test_timestamps_converted_to_utc(self):
        conn, _ = _mock_conn()
        with patch(_EV) as mock_ev:
            ingest_csv_text(SAMPLE_CSV, "771912", conn,
                            datetime(2026, 1, 1, 12, tzinfo=timezone.utc))
        batch = mock_ev.call_args[0][2]
        recorded_at = batch[0][1]
        # 2026-01-01 12:00:00 Europe/Tallinn → 10:00 UTC (UTC+2 in January, EET)
        assert recorded_at == datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# TestUpsertLogRow
# ---------------------------------------------------------------------------

class TestUpsertLogRow:
    def _flat(self, **overrides):
        vals = [None] * len(FLAT_COLUMN_MAP)
        keys = list(FLAT_COLUMN_MAP.keys())
        for k, v in overrides.items():
            vals[keys.index(k)] = v
        return vals

    def test_inserts_into_bronze_vrm_log_raw(self):
        conn, cursor = _mock_conn()
        upsert_log_row(conn, "771912",
                       datetime(2026, 1, 1, 9, tzinfo=timezone.utc),
                       datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
                       {}, self._flat())
        assert "INSERT INTO bronze.vrm_log_raw" in cursor.execute.call_args[0][0]

    def test_sql_has_on_conflict_do_update(self):
        conn, cursor = _mock_conn()
        upsert_log_row(conn, "771912",
                       datetime(2026, 1, 1, 9, tzinfo=timezone.utc),
                       datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
                       {}, self._flat())
        sql = cursor.execute.call_args[0][0]
        assert "ON CONFLICT" in sql
        assert "DO UPDATE" in sql

    def test_site_id_is_first_param(self):
        conn, cursor = _mock_conn()
        upsert_log_row(conn, "site-99",
                       datetime(2026, 1, 1, 9, tzinfo=timezone.utc),
                       datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
                       {}, self._flat())
        assert cursor.execute.call_args[0][1][0] == "site-99"

    def test_recorded_at_is_second_param(self):
        conn, cursor = _mock_conn()
        recorded = datetime(2026, 1, 1, 9, tzinfo=timezone.utc)
        upsert_log_row(conn, "771912", recorded,
                       datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
                       {}, self._flat())
        assert cursor.execute.call_args[0][1][1] == recorded

    def test_fetched_at_is_third_param(self):
        conn, cursor = _mock_conn()
        fetched = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
        upsert_log_row(conn, "771912",
                       datetime(2026, 1, 1, 9, tzinfo=timezone.utc),
                       fetched, {}, self._flat())
        assert cursor.execute.call_args[0][1][2] == fetched

    def test_metrics_serialised_as_json(self):
        conn, cursor = _mock_conn()
        metrics = {"Block": {"key": 1.0}}
        upsert_log_row(conn, "771912",
                       datetime(2026, 1, 1, 9, tzinfo=timezone.utc),
                       datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
                       metrics, self._flat())
        assert json.loads(cursor.execute.call_args[0][1][3]) == metrics

    def test_commits_after_insert(self):
        conn, _ = _mock_conn()
        upsert_log_row(conn, "771912",
                       datetime(2026, 1, 1, 9, tzinfo=timezone.utc),
                       datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
                       {}, self._flat())
        conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# TestBuildIngestConfig
# ---------------------------------------------------------------------------

class TestBuildIngestConfig:
    def test_raises_on_missing_env(self):
        with pytest.raises(ValueError):
            build_ingest_config()

    def test_reads_token_and_site_id(self, monkeypatch):
        for k, v in FULL_ENV.items():
            monkeypatch.setenv(k, v)
        config = build_ingest_config()
        assert config.token == "test-token"
        assert config.site_id == 771912

    def test_site_id_cast_to_int(self, monkeypatch):
        for k, v in FULL_ENV.items():
            monkeypatch.setenv(k, v)
        assert isinstance(build_ingest_config().site_id, int)

    def test_default_window_is_last_completed_hour(self, monkeypatch):
        for k, v in FULL_ENV.items():
            monkeypatch.setenv(k, v)
        config = build_ingest_config()
        now = datetime.now(timezone.utc)
        expected_end = int(now.replace(minute=0, second=0, microsecond=0).timestamp())
        expected_start = expected_end - 3600
        assert abs(config.start_unix - expected_start) <= 5
        assert abs(config.end_unix - expected_end) <= 5

    def test_start_override_via_env(self, monkeypatch):
        for k, v in FULL_ENV.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("VRM_LOG_START", "2026-01-01T00:00:00")
        config = build_ingest_config()
        assert config.start_unix == int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())

    def test_end_override_via_env(self, monkeypatch):
        for k, v in FULL_ENV.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("VRM_LOG_END", "2026-01-02T00:00:00")
        config = build_ingest_config()
        assert config.end_unix == int(datetime(2026, 1, 2, tzinfo=timezone.utc).timestamp())

    def test_default_chunk_days_is_1(self, monkeypatch):
        for k, v in FULL_ENV.items():
            monkeypatch.setenv(k, v)
        assert build_ingest_config().chunk_days == 1

    def test_chunk_days_override_via_env(self, monkeypatch):
        for k, v in FULL_ENV.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("VRM_LOG_CHUNK_DAYS", "7")
        assert build_ingest_config().chunk_days == 7

    def test_chunk_days_above_7_raises(self, monkeypatch):
        for k, v in FULL_ENV.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("VRM_LOG_CHUNK_DAYS", "8")
        with pytest.raises(ValueError, match="exceeds the safe maximum"):
            build_ingest_config()


# ---------------------------------------------------------------------------
# TestMain
# ---------------------------------------------------------------------------

class TestMain:
    @pytest.fixture
    def env_vars(self, monkeypatch):
        for k, v in FULL_ENV.items():
            monkeypatch.setenv(k, v)

    def test_returns_1_on_missing_env(self):
        assert main() == 1

    @patch("src.ingest.vrm_log_ingest.psycopg2.connect")
    @patch("src.ingest.vrm_log_ingest.requests.Session")
    @patch("src.ingest.vrm_log_ingest.download_report", return_value=SAMPLE_CSV)
    @patch("src.ingest.vrm_log_ingest.ingest_csv_text", return_value=2)
    def test_returns_0_on_success(self, _ingest, _dl, _sess, _conn, env_vars):
        assert main() == 0

    @patch("src.ingest.vrm_log_ingest.psycopg2.connect",
           side_effect=Exception("connection refused"))
    def test_returns_1_on_db_failure(self, _conn, env_vars):
        assert main() == 1

    @patch("src.ingest.vrm_log_ingest.psycopg2.connect")
    @patch("src.ingest.vrm_log_ingest.requests.Session")
    @patch("src.ingest.vrm_log_ingest.download_report",
           side_effect=RuntimeError("503"))
    def test_returns_1_on_download_failure(self, _dl, _sess, _conn, env_vars):
        assert main() == 1

    @patch("src.ingest.vrm_log_ingest.psycopg2.connect")
    @patch("src.ingest.vrm_log_ingest.requests.Session")
    @patch("src.ingest.vrm_log_ingest.download_report", return_value=SAMPLE_CSV)
    @patch("src.ingest.vrm_log_ingest.ingest_csv_text", return_value=2)
    def test_closes_connection_on_success(self, _ingest, _dl, _sess, mock_conn, env_vars):
        main()
        mock_conn.return_value.close.assert_called_once()

    @patch("src.ingest.vrm_log_ingest.psycopg2.connect")
    @patch("src.ingest.vrm_log_ingest.requests.Session")
    @patch("src.ingest.vrm_log_ingest.download_report",
           side_effect=RuntimeError("fail"))
    def test_closes_connection_on_failure(self, _dl, _sess, mock_conn, env_vars):
        main()
        mock_conn.return_value.close.assert_called_once()

    @patch("src.ingest.vrm_log_ingest.time.sleep")
    @patch("src.ingest.vrm_log_ingest.psycopg2.connect")
    @patch("src.ingest.vrm_log_ingest.requests.Session")
    @patch("src.ingest.vrm_log_ingest.download_report", return_value=SAMPLE_CSV)
    @patch("src.ingest.vrm_log_ingest.ingest_csv_text", return_value=2)
    def test_calls_download_once_per_chunk(
        self, _ingest, mock_dl, _sess, _conn, mock_sleep, monkeypatch
    ):
        for k, v in FULL_ENV.items():
            monkeypatch.setenv(k, v)
        # 3-day backfill with chunk_days=1 → 3 download calls
        monkeypatch.setenv("VRM_LOG_START", "2026-01-01T00:00:00")
        monkeypatch.setenv("VRM_LOG_END", "2026-01-04T00:00:00")
        monkeypatch.setenv("VRM_LOG_CHUNK_DAYS", "1")
        main()
        assert mock_dl.call_count == 3
        assert mock_sleep.call_count == 2  # sleep between chunks, not after last
