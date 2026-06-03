{{
  config(
    materialized='incremental',
    unique_key='vrm_log_key',
    incremental_strategy='delete+insert',
)
}}

with
{% if is_incremental() %}
lookback as (
    select max(fetched_at) - interval '1 hour' as cutoff from {{ this }}
),
{% endif %}

fct as (
    select * from {{ ref('fct_vrm_log_hourly') }}
    {% if is_incremental() %}
    where fetched_at > (select cutoff from lookback)
    {% endif %}
),

meteo as (
    select * from {{ ref('fct_meteo_hourly') }}
),

time_dim as (
    select * from {{ ref('dim_time') }}
),

sites as (
    select site_id::text as site_id, capacity_kw
    from {{ ref('vrm_sites') }}
)

select
    fct.vrm_log_key,
    fct.timestamp_utc,
    fct.site_id,

    -- Required measurement fields
    fct.battery_soc_pct,
    fct.battery_voltage_v,
    fct.battery_current_a,
    fct.battery_power_w,
    fct.battery_temp_c,
    fct.battery_discharged_kwh,
    fct.battery_charged_kwh,

    -- AC consumption (required) — System overview [0]
    fct.ac_consumption_l1_w,
    fct.ac_consumption_l2_w,
    fct.ac_consumption_l3_w,
    fct.ac_consumption_total_w,

    -- PV power and energy (required) — PV Inverter [20]
    fct.pv_power_l1_w,
    fct.pv_power_l2_w,
    fct.pv_power_l3_w,
    fct.pv_power_total_w,
    fct.pv_energy_l1_kwh,
    fct.pv_energy_l2_kwh,
    fct.pv_energy_l3_kwh,
    fct.pv_energy_total_kwh,

    -- Grid — VE.Bus System [276]
    fct.grid_input_power_l1_w,
    fct.grid_input_power_l2_w,
    fct.grid_input_power_l3_w,
    fct.grid_input_power_total_w,
    fct.grid_alarm,

    -- Weather (Open-Meteo, LEFT JOIN — NULL when meteo unavailable)
    meteo.shortwave_radiation_wm2,
    meteo.direct_radiation_wm2,
    meteo.sunshine_duration_s,
    meteo.cloud_cover_pct,

    -- Calendar labels (dim_time, LEFT JOIN)
    time_dim.season,
    time_dim.is_daytime,

    -- KPIs

    -- Standard IEC 61724 performance ratio: actual yield vs theoretical max given irradiance.
    -- NULL when radiation too low (≤50 W/m²) or system capacity unknown.
    case
        when meteo.shortwave_radiation_wm2 > 50 and sites.capacity_kw > 0
        then fct.pv_energy_total_kwh
             / (meteo.shortwave_radiation_wm2 / 1000.0 * sites.capacity_kw)
    end                                                             as performance_ratio,

    -- Normalised yield — comparable across sites of different size (kWh/kWp).
    -- NULL when capacity unknown.
    case
        when sites.capacity_kw > 0
        then fct.pv_energy_total_kwh / sites.capacity_kw
    end                                                             as specific_yield_kwh_per_kwp,

    -- Net battery energy this hour: positive = net charging, negative = net discharging.
    fct.battery_charged_kwh - fct.battery_discharged_kwh           as battery_net_kwh,

    -- Grid import estimate: hourly-average grid power (W) converted to kWh.
    -- Labelled _estimate because it assumes constant power within the hour.
    case
        when fct.grid_input_power_total_w is not null
        then fct.grid_input_power_total_w / 1000.0
    end                                                             as grid_import_kwh_estimate,

    -- Supply-side proxy for self-sufficiency: fraction of total energy supply from PV.
    -- Approximate — does not use GX internal energy-flow accounting.
    case
        when fct.pv_energy_total_kwh is not null
            and fct.grid_input_power_total_w is not null
            and (fct.pv_energy_total_kwh + fct.grid_input_power_total_w / 1000.0) > 0
        then fct.pv_energy_total_kwh
             / (fct.pv_energy_total_kwh + fct.grid_input_power_total_w / 1000.0)
    end                                                             as pv_cover_ratio,

    fct.fetched_at

from fct
left join meteo    on fct.timestamp_utc = meteo.timestamp_utc
left join time_dim on fct.time_key = time_dim.time_key
left join sites    on fct.site_id = sites.site_id
