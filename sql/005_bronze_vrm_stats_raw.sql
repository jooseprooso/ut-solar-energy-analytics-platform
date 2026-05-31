CREATE TABLE IF NOT EXISTS bronze.vrm_stats_raw (
    id           BIGSERIAL    PRIMARY KEY,
    site_id      TEXT         NOT NULL,
    fetched_at   TIMESTAMPTZ  NOT NULL,
    fetched_hour TIMESTAMPTZ  NOT NULL,
    payload      JSONB        NOT NULL
);

-- One row per (site, hour): backfill reruns overwrite rather than duplicate.
CREATE UNIQUE INDEX IF NOT EXISTS vrm_stats_raw_site_hour
    ON bronze.vrm_stats_raw (site_id, fetched_hour);
