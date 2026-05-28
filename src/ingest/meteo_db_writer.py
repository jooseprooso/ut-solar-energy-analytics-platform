from __future__ import annotations

import re
from typing import Any, Protocol


class DbConnection(Protocol):
    def cursor(self) -> Any: ...
    def commit(self) -> None: ...


DEFAULT_TABLE_NAME = "meteo_raw"
TABLE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

UPSERT_SQL = """\
INSERT INTO bronze.meteo_raw (timestamp_utc, latitude, longitude, variable_name, value, unit)
VALUES (%(timestamp_utc)s, %(latitude)s, %(longitude)s, %(variable_name)s, %(value)s, %(unit)s)
ON CONFLICT (timestamp_utc, latitude, longitude, variable_name)
DO UPDATE SET value = EXCLUDED.value, unit = EXCLUDED.unit, ingested_at = now()
"""


def _validate_table_name(table_name: str) -> None:
    if not TABLE_NAME_RE.fullmatch(table_name):
        raise ValueError(f"Invalid table name: {table_name}")


def _build_upsert_sql(table_name: str) -> str:
    if table_name == DEFAULT_TABLE_NAME:
        return UPSERT_SQL
    return f"""\
INSERT INTO bronze.{table_name} (timestamp_utc, latitude, longitude, variable_name, value, unit)
VALUES (%(timestamp_utc)s, %(latitude)s, %(longitude)s, %(variable_name)s, %(value)s, %(unit)s)
ON CONFLICT (timestamp_utc, latitude, longitude, variable_name)
DO UPDATE SET value = EXCLUDED.value, unit = EXCLUDED.unit, ingested_at = now()
"""


def _build_create_table_sql(table_name: str) -> str:
    constraint_name = f"uq_{table_name}_ts_var"
    return f"""\
CREATE TABLE IF NOT EXISTS bronze.{table_name} (
    id              BIGSERIAL PRIMARY KEY,
    timestamp_utc   TIMESTAMPTZ NOT NULL,
    latitude        DOUBLE PRECISION NOT NULL,
    longitude       DOUBLE PRECISION NOT NULL,
    variable_name   TEXT NOT NULL,
    value           DOUBLE PRECISION,
    unit            TEXT NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT {constraint_name}
        UNIQUE (timestamp_utc, latitude, longitude, variable_name)
)
"""


def upsert_meteo_rows(
    rows: list[dict[str, Any]], conn: DbConnection, table_name: str = DEFAULT_TABLE_NAME
) -> int:
    if not rows:
        return 0
    _validate_table_name(table_name)
    cursor = conn.cursor()
    cursor.execute(_build_create_table_sql(table_name))
    cursor.executemany(_build_upsert_sql(table_name), rows)
    conn.commit()
    cursor.close()
    return len(rows)


def build_connection(
    host: str, port: str, dbname: str, user: str, password: str
) -> Any:
    import psycopg2

    return psycopg2.connect(
        host=host, port=int(port), dbname=dbname, user=user, password=password
    )
