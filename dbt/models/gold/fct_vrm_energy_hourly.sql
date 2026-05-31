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

staging as (
    select * from {{ ref('stg_vrm_energy_snapshot') }}
    {% if is_incremental() %}
    where fetched_at > (select cutoff from lookback)
    {% endif %}
),

sites as (
    select
        site_id::text as site_id,
        latitude,
        longitude
    from {{ ref('vrm_sites') }}
)

select
    {{ dbt_utils.generate_surrogate_key(['staging.site_id', 'staging.fetched_hour']) }}    as vrm_hourly_key,
    {{ dbt_utils.generate_surrogate_key(['staging.fetched_hour']) }}                        as time_key,
    {{ dbt_utils.generate_surrogate_key(['sites.latitude', 'sites.longitude']) }}           as location_key,
    staging.site_id,
    staging.fetched_hour                    as timestamp_utc,
    staging.pv_total_w,
    staging.pv_l1_w,
    staging.pv_l2_w,
    staging.pv_l3_w,
    staging.load_total_w,
    staging.load_l1_w,
    staging.load_l2_w,
    staging.load_l3_w,
    staging.pv_to_battery_kwh,
    staging.pv_to_consumers_kwh,
    staging.grid_to_battery_kwh,
    staging.grid_to_consumers_kwh,
    staging.battery_to_consumers_kwh,
    staging.battery_soc_pct,
    staging.battery_power_w,
    staging.battery_voltage_v,
    staging.battery_temp_c,
    staging.battery_state,
    staging.battery_soh_pct,
    staging.battery_discharged_kwh_delta,
    staging.battery_charged_kwh_delta,
    staging.pvinverter_energy_delta_kwh,
    staging.system_state,
    staging.grid_alarm,
    staging.pvinverter_status,
    staging.fetched_at
from staging
left join sites on staging.site_id = sites.site_id
