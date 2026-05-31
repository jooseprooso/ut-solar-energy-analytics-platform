{{
  config(
    materialized='incremental',
    unique_key='vrm_hourly_key',
    incremental_strategy='delete+insert',
)
}}

with
{% if is_incremental() %}
lookback as (
    select max(fetched_at) - interval '1 hour' as cutoff from {{ this }}
),
{% endif %}

vrm as (
    select * from {{ ref('fct_vrm_energy_hourly') }}
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
    vrm.vrm_hourly_key,
    vrm.timestamp_utc,
    vrm.site_id,

    -- PV toodang
    vrm.pv_total_w,
    vrm.pv_l1_w,
    vrm.pv_l2_w,
    vrm.pv_l3_w,

    -- Energiavood
    vrm.pv_to_battery_kwh,
    vrm.pv_to_consumers_kwh,
    vrm.grid_to_battery_kwh,
    vrm.grid_to_consumers_kwh,
    vrm.battery_to_consumers_kwh,

    -- Tarbimine
    vrm.load_total_w,

    -- Aku
    vrm.battery_soc_pct,
    vrm.battery_power_w,
    vrm.battery_state,
    vrm.battery_soh_pct,

    -- PV koguenergia (self-consumption arvutuse nimetaja)
    vrm.pvinverter_energy_delta_kwh,

    -- Süsteemi olek
    vrm.system_state,
    vrm.grid_alarm,
    vrm.pvinverter_status,

    -- Ilmastik (Open-Meteo)
    meteo.shortwave_radiation_wm2,
    meteo.sunshine_duration_s,
    meteo.direct_radiation_wm2,
    meteo.cloud_cover_pct,

    -- Kalendrimärgendid
    time_dim.season,
    time_dim.is_daytime,

    -- Põhi-KPI-d (ainult kWh aditiivsed faktid, NULL kui nimetaja puudub)
    case
        when (vrm.pv_to_consumers_kwh + vrm.battery_to_consumers_kwh + vrm.grid_to_consumers_kwh) > 0
        then (vrm.pv_to_consumers_kwh + vrm.battery_to_consumers_kwh)
             / (vrm.pv_to_consumers_kwh + vrm.battery_to_consumers_kwh + vrm.grid_to_consumers_kwh)
    end as self_sufficiency_rate,

    case
        when vrm.pvinverter_energy_delta_kwh > 0
        then (vrm.pv_to_consumers_kwh + vrm.pv_to_battery_kwh)
             / vrm.pvinverter_energy_delta_kwh
    end as self_consumption_rate,

    case
        when meteo.shortwave_radiation_wm2 > 0 and sites.capacity_kw > 0
        then vrm.pvinverter_energy_delta_kwh
             / (meteo.shortwave_radiation_wm2 / 1000.0 * sites.capacity_kw)
    end as performance_ratio,

    vrm.fetched_at
from vrm
left join meteo    on vrm.timestamp_utc = meteo.timestamp_utc
left join time_dim on vrm.time_key = time_dim.time_key
left join sites    on vrm.site_id = sites.site_id
