{{ config(materialized='view') }}

with source as (
    select * from bronze.vrm_log_raw
)

select
    {{ dbt_utils.generate_surrogate_key(['site_id', 'recorded_at']) }} as vrm_log_key,
    site_id,
    recorded_at,
    fetched_at,

    -- Battery Monitor [512]
    battery_soc                                                        as battery_soc_pct,
    battery_voltage                                                    as battery_voltage_v,
    battery_current                                                    as battery_current_a,
    battery_power                                                      as battery_power_w,
    battery_temperature                                                as battery_temp_c,
    battery_discharged_energy                                          as battery_discharged_kwh,
    battery_charged_energy                                             as battery_charged_kwh,

    -- AC consumption per phase — System overview [0]
    ac_consumption_l1                                                  as ac_consumption_l1_w,
    ac_consumption_l2                                                  as ac_consumption_l2_w,
    ac_consumption_l3                                                  as ac_consumption_l3_w,
    case when ac_consumption_l1 is not null
        then ac_consumption_l1 + ac_consumption_l2 + ac_consumption_l3
    end                                                                as ac_consumption_total_w,

    -- PV power per phase — PV Inverter [20]
    pv_power_l1                                                        as pv_power_l1_w,
    pv_power_l2                                                        as pv_power_l2_w,
    pv_power_l3                                                        as pv_power_l3_w,
    case when pv_power_l1 is not null
        then pv_power_l1 + pv_power_l2 + pv_power_l3
    end                                                                as pv_power_total_w,

    -- PV energy per phase — PV Inverter [20]
    pv_energy_l1                                                       as pv_energy_l1_kwh,
    pv_energy_l2                                                       as pv_energy_l2_kwh,
    pv_energy_l3                                                       as pv_energy_l3_kwh,
    case when pv_energy_l1 is not null
        then pv_energy_l1 + pv_energy_l2 + pv_energy_l3
    end                                                                as pv_energy_total_kwh,

    -- Grid — VE.Bus System [276]
    grid_input_power_l1                                                as grid_input_power_l1_w,
    grid_input_power_l2                                                as grid_input_power_l2_w,
    grid_input_power_l3                                                as grid_input_power_l3_w,
    case when grid_input_power_l1 is not null
        then grid_input_power_l1 + grid_input_power_l2 + grid_input_power_l3
    end                                                                as grid_input_power_total_w,
    grid_input_voltage_l1                                              as grid_input_voltage_l1_v,
    grid_input_voltage_l2                                              as grid_input_voltage_l2_v,
    grid_input_voltage_l3                                              as grid_input_voltage_l3_v,
    grid_input_current_l1                                              as grid_input_current_l1_a,
    grid_input_current_l2                                              as grid_input_current_l2_a,
    grid_input_current_l3                                              as grid_input_current_l3_a,
    grid_input_frequency_l1                                            as grid_input_frequency_l1_hz,
    grid_input_frequency_l2                                            as grid_input_frequency_l2_hz,
    grid_input_frequency_l3                                            as grid_input_frequency_l3_hz,
    grid_alarm

from source
