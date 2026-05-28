CREATE TABLE IF NOT EXISTS bronze.meteo_raw (
    id              BIGSERIAL PRIMARY KEY,
    timestamp_utc   TIMESTAMPTZ NOT NULL,
    latitude        DOUBLE PRECISION NOT NULL,
    longitude       DOUBLE PRECISION NOT NULL,
    variable_name   TEXT NOT NULL,
    value           DOUBLE PRECISION,
    unit            TEXT NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_meteo_raw_ts_var
        UNIQUE (timestamp_utc, latitude, longitude, variable_name)
);
