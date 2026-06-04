{{ config(materialized='table') }}

with daily_actual as (
    select
        site_id,
        date_day,
        sum(pv_energy_total_kwh) as pv_energy_actual_kwh
    from {{ ref('mart_vrm_log_hourly') }}
    where pv_energy_total_kwh is not null
    group by site_id, date_day
),

daily_forecast as (
    select
        site_id,
        date_day,
        forecast_type,
        model_version,
        max(forecast_issued_at) as forecast_issued_at,
        sum(pv_energy_forecast_kwh) as pv_energy_forecast_kwh
    from {{ source('gold_external', 'fct_pv_forecast_hourly') }}
    group by site_id, date_day, forecast_type, model_version
)

select
    a.site_id,
    a.date_day,
    f.forecast_type,
    f.model_version,
    a.pv_energy_actual_kwh,
    f.pv_energy_forecast_kwh,
    a.pv_energy_actual_kwh - f.pv_energy_forecast_kwh as forecast_error_kwh,
    case
        when a.pv_energy_actual_kwh > 0
        then 100.0 * (a.pv_energy_actual_kwh - f.pv_energy_forecast_kwh)
             / a.pv_energy_actual_kwh
    end as forecast_error_pct,
    abs(a.pv_energy_actual_kwh - f.pv_energy_forecast_kwh) as abs_error_kwh,
    f.forecast_issued_at as evaluated_at

from daily_actual a
inner join daily_forecast f
    on a.site_id = f.site_id
    and a.date_day = f.date_day
