from __future__ import annotations

from typing import Any, Protocol


class DbConnection(Protocol):
    def cursor(self) -> Any: ...
    def commit(self) -> None: ...


UPSERT_SQL = """\
INSERT INTO bronze.meteo_raw (timestamp_utc, latitude, longitude, variable_name, value, unit)
VALUES (%(timestamp_utc)s, %(latitude)s, %(longitude)s, %(variable_name)s, %(value)s, %(unit)s)
ON CONFLICT (timestamp_utc, latitude, longitude, variable_name)
DO UPDATE SET value = EXCLUDED.value, unit = EXCLUDED.unit, ingested_at = now()
"""


def upsert_meteo_rows(rows: list[dict[str, Any]], conn: DbConnection) -> int:
    if not rows:
        return 0
    cursor = conn.cursor()
    cursor.executemany(UPSERT_SQL, rows)
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
