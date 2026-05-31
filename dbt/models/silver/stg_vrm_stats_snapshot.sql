{{ config(materialized='view') }}

with source as (
    select
        site_id,
        fetched_at,
        fetched_hour,
        payload
    from bronze.vrm_stats_raw
)

select
    {{ dbt_utils.generate_surrogate_key(['site_id', 'fetched_hour']) }} as vrm_snapshot_key,
    site_id,
    fetched_hour,
    fetched_at,

    -- Column order matches stg_vrm_energy_snapshot exactly (required for UNION in gold fact)
    null::numeric                                      as pv_total_w,
    null::numeric                                      as load_total_w,

    -- Granular energy flows not available in stats endpoint
    null::numeric                                      as pv_to_battery_kwh,
    null::numeric                                      as pv_to_consumers_kwh,
    null::numeric                                      as grid_to_battery_kwh,
    null::numeric                                      as grid_to_consumers_kwh,
    null::numeric                                      as battery_to_consumers_kwh,

    -- No per-phase breakdown in stats endpoint
    null::numeric                                      as pv_l1_w,
    null::numeric                                      as pv_l2_w,
    null::numeric                                      as pv_l3_w,
    null::numeric                                      as load_l1_w,
    null::numeric                                      as load_l2_w,
    null::numeric                                      as load_l3_w,

    -- Battery state: available
    (payload ->> 'bs')::numeric                        as battery_soc_pct,
    null::numeric                                      as battery_power_w,
    (payload ->> 'bv')::numeric                        as battery_voltage_v,
    null::numeric                                      as battery_temp_c,
    null::text                                         as battery_state,
    null::numeric                                      as battery_soh_pct,
    null::numeric                                      as battery_discharged_kwh_delta,
    null::numeric                                      as battery_charged_kwh_delta,

    -- total_solar_yield is the only energy flow available; drives performance_ratio
    (payload ->> 'total_solar_yield')::numeric         as pvinverter_energy_delta_kwh,

    -- State strings not available in stats endpoint
    null::text                                         as system_state,
    null::text                                         as grid_alarm,
    null::text                                         as pvinverter_status

from source
