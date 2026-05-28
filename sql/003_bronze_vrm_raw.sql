CREATE SCHEMA IF NOT EXISTS bronze;

CREATE TABLE IF NOT EXISTS bronze.vrm_raw (
    id           BIGSERIAL    PRIMARY KEY,
    site_id      TEXT         NOT NULL,
    fetched_at   TIMESTAMPTZ  NOT NULL,
    fetched_hour TIMESTAMPTZ  NOT NULL,
    endpoint     TEXT         NOT NULL,
    payload      JSONB        NOT NULL
);

-- One row per (site, hour, endpoint): retries/backfills overwrite rather than duplicate.
CREATE UNIQUE INDEX IF NOT EXISTS vrm_raw_site_hour_endpoint
    ON bronze.vrm_raw (site_id, fetched_hour, endpoint);
