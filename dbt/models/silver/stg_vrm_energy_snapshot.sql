{{
  config(
    materialized='incremental',
    unique_key='vrm_snapshot_key',
    incremental_strategy='delete+insert',
)
}}

with source as (
    select
        site_id,
        fetched_at,
        fetched_hour,
        payload
    from bronze.vrm_raw
    {% if is_incremental() %}
    where fetched_at > (select max(fetched_at) - interval '1 hour' from {{ this }})
    {% endif %}
),

expanded as (
    select
        site_id,
        fetched_at,
        fetched_hour,
        jsonb_array_elements(payload -> 'records') as record
    from source
),

pivoted as (
    select
        site_id,
        fetched_hour,
        max(fetched_at) as fetched_at,

        -- Energiavood (kWh, süsteemi ülevaate perioodisumma)
        max(case when record ->> 'code' = 'Pb'  then (record ->> 'rawValue')::numeric end) as pv_to_battery_kwh,
        max(case when record ->> 'code' = 'Pc'  then (record ->> 'rawValue')::numeric end) as pv_to_consumers_kwh,
        max(case when record ->> 'code' = 'Gb'  then (record ->> 'rawValue')::numeric end) as grid_to_battery_kwh,
        max(case when record ->> 'code' = 'Gc'  then (record ->> 'rawValue')::numeric end) as grid_to_consumers_kwh,
        max(case when record ->> 'code' = 'Bc'  then (record ->> 'rawValue')::numeric end) as battery_to_consumers_kwh,

        -- PV võimsus faaside kaupa (W, hetkeväärtus süsteemi ülevaates)
        max(case when record ->> 'code' = 'P'   then (record ->> 'rawValue')::numeric end) as pv_l1_w,
        max(case when record ->> 'code' = 'P2'  then (record ->> 'rawValue')::numeric end) as pv_l2_w,
        max(case when record ->> 'code' = 'P3'  then (record ->> 'rawValue')::numeric end) as pv_l3_w,

        -- Tarbimine faaside kaupa (W, hetkeväärtus)
        max(case when record ->> 'code' = 'a1'  then (record ->> 'rawValue')::numeric end) as load_l1_w,
        max(case when record ->> 'code' = 'a2'  then (record ->> 'rawValue')::numeric end) as load_l2_w,
        max(case when record ->> 'code' = 'a3'  then (record ->> 'rawValue')::numeric end) as load_l3_w,

        -- Aku seisund (süsteemi ülevaade)
        max(case when record ->> 'code' = 'bs'  then (record ->> 'rawValue')::numeric end)  as battery_soc_pct,
        max(case when record ->> 'code' = 'bp'  then (record ->> 'rawValue')::numeric end)  as battery_power_w,
        max(case when record ->> 'code' = 'bv'  then (record ->> 'rawValue')::numeric end)  as battery_voltage_v,
        max(case when record ->> 'code' = 'bT'  then (record ->> 'rawValue')::numeric end)  as battery_temp_c,
        max(case when record ->> 'code' = 'bst' then record ->> 'formattedValue' end)        as battery_state,

        -- Aku tervis (Battery Monitor seade)
        max(case when record ->> 'code' = 'SOH'  then (record ->> 'rawValue')::numeric end) as battery_soh_pct,
        max(case when record ->> 'code' = 'dH21' then (record ->> 'rawValue')::numeric end) as battery_discharged_kwh_delta,
        max(case when record ->> 'code' = 'dH22' then (record ->> 'rawValue')::numeric end) as battery_charged_kwh_delta,

        -- PV inverteri koguenergia perioodil (kWh) — self-consumption arvutuse nimetaja
        max(case when record ->> 'code' = 'dpE' then (record ->> 'rawValue')::numeric end) as pvinverter_energy_delta_kwh,

        -- Süsteemi olek ja alarmid
        max(case when record ->> 'code' = 'ss'  then record ->> 'formattedValue' end) as system_state,
        max(case when record ->> 'code' = 'Agl' then record ->> 'formattedValue' end) as grid_alarm,
        max(case when record ->> 'code' = 'pS'  then record ->> 'formattedValue' end) as pvinverter_status

    from expanded
    group by site_id, fetched_hour
),

final as (
    select
        {{ dbt_utils.generate_surrogate_key(['site_id', 'fetched_hour']) }} as vrm_snapshot_key,
        site_id,
        fetched_hour,
        fetched_at,

        -- Arvutatud koguväärtused — NULL kui kõik faasid puuduvad (seade maas)
        case when pv_l1_w is not null then pv_l1_w + pv_l2_w + pv_l3_w end     as pv_total_w,
        case when load_l1_w is not null then load_l1_w + load_l2_w + load_l3_w end as load_total_w,

        pv_to_battery_kwh,
        pv_to_consumers_kwh,
        grid_to_battery_kwh,
        grid_to_consumers_kwh,
        battery_to_consumers_kwh,
        pv_l1_w,
        pv_l2_w,
        pv_l3_w,
        load_l1_w,
        load_l2_w,
        load_l3_w,
        battery_soc_pct,
        battery_power_w,
        battery_voltage_v,
        battery_temp_c,
        battery_state,
        battery_soh_pct,
        battery_discharged_kwh_delta,
        battery_charged_kwh_delta,
        pvinverter_energy_delta_kwh,
        system_state,
        grid_alarm,
        pvinverter_status

    from pivoted
)

select * from final
