CREATE SCHEMA IF NOT EXISTS bronze;

CREATE TABLE IF NOT EXISTS bronze.vrm_log_raw (
    id                        BIGSERIAL    PRIMARY KEY,
    site_id                   TEXT         NOT NULL,
    recorded_at               TIMESTAMPTZ  NOT NULL,
    fetched_at                TIMESTAMPTZ  NOT NULL,
    -- Full CSV row preserved as nested {block_label: {metric_name: value}} for reprocessing.
    metrics                   JSONB        NOT NULL,
    -- Battery Monitor [512]
    battery_soc               NUMERIC,
    battery_voltage           NUMERIC,
    battery_current           NUMERIC,
    battery_temperature       NUMERIC,
    battery_discharged_energy NUMERIC,
    battery_charged_energy    NUMERIC,
    -- System overview [0]
    battery_power             NUMERIC,
    ac_consumption_l1         NUMERIC,
    ac_consumption_l2         NUMERIC,
    ac_consumption_l3         NUMERIC,
    -- PV Inverter [20]
    pv_power_l1               NUMERIC,
    pv_power_l2               NUMERIC,
    pv_power_l3               NUMERIC,
    pv_energy_l1              NUMERIC,
    pv_energy_l2              NUMERIC,
    pv_energy_l3              NUMERIC,
    -- VE.Bus System [276]
    grid_input_power_l1       NUMERIC,
    grid_input_power_l2       NUMERIC,
    grid_input_power_l3       NUMERIC,
    grid_input_voltage_l1     NUMERIC,
    grid_input_voltage_l2     NUMERIC,
    grid_input_voltage_l3     NUMERIC,
    grid_input_current_l1     NUMERIC,
    grid_input_current_l2     NUMERIC,
    grid_input_current_l3     NUMERIC,
    grid_input_frequency_l1   NUMERIC,
    grid_input_frequency_l2   NUMERIC,
    grid_input_frequency_l3   NUMERIC,
    -- System overview [276]
    grid_alarm                TEXT
);

-- One row per (site, hour): retries and backfill reruns overwrite rather than duplicate.
CREATE UNIQUE INDEX IF NOT EXISTS vrm_log_raw_site_recorded_at
    ON bronze.vrm_log_raw (site_id, recorded_at);
