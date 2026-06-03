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

staging as (
    select * from {{ ref('stg_vrm_log_hourly') }}
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
    {{ dbt_utils.generate_surrogate_key(['staging.site_id', 'staging.recorded_at']) }}  as vrm_log_key,
    {{ dbt_utils.generate_surrogate_key(['staging.recorded_at']) }}                      as time_key,
    {{ dbt_utils.generate_surrogate_key(['sites.latitude', 'sites.longitude']) }}        as location_key,
    staging.site_id,
    staging.recorded_at                     as timestamp_utc,
    staging.fetched_at,
    staging.battery_soc_pct,
    staging.battery_voltage_v,
    staging.battery_current_a,
    staging.battery_power_w,
    staging.battery_temp_c,
    staging.battery_discharged_kwh,
    staging.battery_charged_kwh,
    staging.ac_consumption_l1_w,
    staging.ac_consumption_l2_w,
    staging.ac_consumption_l3_w,
    staging.ac_consumption_total_w,
    staging.pv_power_l1_w,
    staging.pv_power_l2_w,
    staging.pv_power_l3_w,
    staging.pv_power_total_w,
    staging.pv_energy_l1_kwh,
    staging.pv_energy_l2_kwh,
    staging.pv_energy_l3_kwh,
    staging.pv_energy_total_kwh,
    staging.grid_input_power_l1_w,
    staging.grid_input_power_l2_w,
    staging.grid_input_power_l3_w,
    staging.grid_input_power_total_w,
    staging.grid_input_voltage_l1_v,
    staging.grid_input_voltage_l2_v,
    staging.grid_input_voltage_l3_v,
    staging.grid_input_current_l1_a,
    staging.grid_input_current_l2_a,
    staging.grid_input_current_l3_a,
    staging.grid_input_frequency_l1_hz,
    staging.grid_input_frequency_l2_hz,
    staging.grid_input_frequency_l3_hz,
    staging.grid_alarm
from staging
left join sites on staging.site_id = sites.site_id
