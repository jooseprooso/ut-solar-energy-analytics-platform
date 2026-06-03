{{ config(materialized='view') }}

with latest as (
    select site_id, fetched_at, fetched_hour, payload
    from bronze.vrm_raw
    where (site_id, fetched_hour) in (
        select site_id, max(fetched_hour)
        from bronze.vrm_raw
        group by site_id
    )
),

expanded as (
    select
        site_id,
        fetched_at,
        fetched_hour,
        jsonb_array_elements(payload -> 'records') as record
    from latest
),

pivoted as (
    select
        site_id,
        fetched_hour,
        max(fetched_at) as fetched_at,

        -- Energiavood (kWh)
        max(case when record ->> 'code' = 'Pb'  then (record ->> 'rawValue')::numeric end) as pv_to_battery_kwh,
        max(case when record ->> 'code' = 'Pc'  then (record ->> 'rawValue')::numeric end) as pv_to_consumers_kwh,
        max(case when record ->> 'code' = 'Gb'  then (record ->> 'rawValue')::numeric end) as grid_to_battery_kwh,
        max(case when record ->> 'code' = 'Gc'  then (record ->> 'rawValue')::numeric end) as grid_to_consumers_kwh,
        max(case when record ->> 'code' = 'Bc'  then (record ->> 'rawValue')::numeric end) as battery_to_consumers_kwh,

        -- PV võimsus faaside kaupa (W)
        max(case when record ->> 'code' = 'P'   then (record ->> 'rawValue')::numeric end) as pv_l1_w,
        max(case when record ->> 'code' = 'P2'  then (record ->> 'rawValue')::numeric end) as pv_l2_w,
        max(case when record ->> 'code' = 'P3'  then (record ->> 'rawValue')::numeric end) as pv_l3_w,

        -- Tarbimine faaside kaupa (W)
        max(case when record ->> 'code' = 'a1'  then (record ->> 'rawValue')::numeric end) as load_l1_w,
        max(case when record ->> 'code' = 'a2'  then (record ->> 'rawValue')::numeric end) as load_l2_w,
        max(case when record ->> 'code' = 'a3'  then (record ->> 'rawValue')::numeric end) as load_l3_w,

        -- Aku seisund
        max(case when record ->> 'code' = 'bs'  then (record ->> 'rawValue')::numeric end)  as battery_soc_pct,
        max(case when record ->> 'code' = 'bp'  then (record ->> 'rawValue')::numeric end)  as battery_power_w,
        max(case when record ->> 'code' = 'bv'  then (record ->> 'rawValue')::numeric end)  as battery_voltage_v,
        max(case when record ->> 'code' = 'bT'  then (record ->> 'rawValue')::numeric end)  as battery_temp_c,
        max(case when record ->> 'code' = 'bst' then record ->> 'formattedValue' end)        as battery_state,

        -- Aku tervis
        max(case when record ->> 'code' = 'SOH'  then (record ->> 'rawValue')::numeric end) as battery_soh_pct,
        max(case when record ->> 'code' = 'dH21' then (record ->> 'rawValue')::numeric end) as battery_discharged_kwh_delta,
        max(case when record ->> 'code' = 'dH22' then (record ->> 'rawValue')::numeric end) as battery_charged_kwh_delta,

        -- PV inverteri koguenergia
        max(case when record ->> 'code' = 'dpE' then (record ->> 'rawValue')::numeric end) as pvinverter_energy_delta_kwh,

        -- Süsteemi olek
        max(case when record ->> 'code' = 'ss'  then record ->> 'formattedValue' end) as system_state,
        max(case when record ->> 'code' = 'Agl' then record ->> 'formattedValue' end) as grid_alarm,
        max(case when record ->> 'code' = 'pS'  then record ->> 'formattedValue' end) as pvinverter_status

    from expanded
    group by site_id, fetched_hour
),

meteo as (
    select * from {{ ref('fct_meteo_hourly') }}
),

sites as (
    select site_id::text as site_id, capacity_kw
    from {{ ref('vrm_sites') }}
)

select
    pivoted.site_id,
    pivoted.fetched_hour                as timestamp_utc,

    -- Kalendrimärgendid (arvutatakse inline, ei sõltu dim_time olemasolust)
    extract(hour from pivoted.fetched_hour)::int    as hour_of_day,
    pivoted.fetched_hour::date                      as date_day,
    case
        when extract(month from pivoted.fetched_hour) in (12, 1, 2) then 'winter'
        when extract(month from pivoted.fetched_hour) in (3, 4, 5)  then 'spring'
        when extract(month from pivoted.fetched_hour) in (6, 7, 8)  then 'summer'
        else 'autumn'
    end                                             as season,
    (extract(hour from pivoted.fetched_hour) between 6 and 20)
                                                    as is_daytime,

    -- PV toodang
    case when pivoted.pv_l1_w is not null
        then pivoted.pv_l1_w + pivoted.pv_l2_w + pivoted.pv_l3_w
    end                             as pv_total_w,
    pivoted.pv_l1_w,
    pivoted.pv_l2_w,
    pivoted.pv_l3_w,

    -- Energiavood
    pivoted.pv_to_battery_kwh,
    pivoted.pv_to_consumers_kwh,
    pivoted.grid_to_battery_kwh,
    pivoted.grid_to_consumers_kwh,
    pivoted.battery_to_consumers_kwh,

    -- Tarbimine
    case when pivoted.load_l1_w is not null
        then pivoted.load_l1_w + pivoted.load_l2_w + pivoted.load_l3_w
    end                             as load_total_w,

    -- Aku
    pivoted.battery_soc_pct,
    pivoted.battery_power_w,
    pivoted.battery_voltage_v,
    pivoted.battery_temp_c,
    pivoted.battery_state,
    pivoted.battery_soh_pct,
    pivoted.battery_discharged_kwh_delta,
    pivoted.battery_charged_kwh_delta,
    pivoted.pvinverter_energy_delta_kwh,

    -- Süsteemi olek
    pivoted.system_state,
    pivoted.grid_alarm,
    pivoted.pvinverter_status,

    -- Ilmaandmed (LEFT JOIN — NULL kui meteo pole saadaval)
    meteo.shortwave_radiation_wm2,
    meteo.direct_radiation_wm2,
    meteo.sunshine_duration_s,
    meteo.cloud_cover_pct,

    -- KPI-d
    case
        when (pivoted.pv_to_consumers_kwh + pivoted.battery_to_consumers_kwh
              + pivoted.grid_to_consumers_kwh) > 0
        then (pivoted.pv_to_consumers_kwh + pivoted.battery_to_consumers_kwh)
             / (pivoted.pv_to_consumers_kwh + pivoted.battery_to_consumers_kwh
                + pivoted.grid_to_consumers_kwh)
    end                             as self_sufficiency_rate,

    case
        when pivoted.pvinverter_energy_delta_kwh > 0
        then least(1.0, (pivoted.pv_to_consumers_kwh + pivoted.pv_to_battery_kwh)
             / pivoted.pvinverter_energy_delta_kwh)
    end                             as self_consumption_rate,

    case
        when meteo.shortwave_radiation_wm2 > 0 and sites.capacity_kw > 0
        then pivoted.pvinverter_energy_delta_kwh
             / (meteo.shortwave_radiation_wm2 / 1000.0 * sites.capacity_kw)
    end                             as performance_ratio,

    pivoted.fetched_at

from pivoted
left join meteo on pivoted.fetched_hour = meteo.timestamp_utc
left join sites on pivoted.site_id = sites.site_id
