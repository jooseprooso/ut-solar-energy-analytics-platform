CREATE TABLE IF NOT EXISTS gold.fct_pv_forecast_hourly (
    id                      BIGSERIAL PRIMARY KEY,
    site_id                 TEXT             NOT NULL,
    timestamp_utc           TIMESTAMPTZ      NOT NULL,
    date_day                DATE             NOT NULL,
    forecast_type           TEXT             NOT NULL,
    pv_energy_forecast_kwh  DOUBLE PRECISION NOT NULL,
    forecast_issued_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),
    model_version           TEXT             NOT NULL DEFAULT 'ridge_v1',
    created_at              TIMESTAMPTZ      NOT NULL DEFAULT now(),
    CONSTRAINT uq_fct_pv_forecast UNIQUE (site_id, timestamp_utc, forecast_type)
);

CREATE INDEX IF NOT EXISTS idx_fct_pv_forecast_site_date
    ON gold.fct_pv_forecast_hourly (site_id, date_day);
