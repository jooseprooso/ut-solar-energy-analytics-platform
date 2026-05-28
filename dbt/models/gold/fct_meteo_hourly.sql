{{
  config(
    materialized='incremental',
    unique_key='meteo_hourly_key',
    incremental_strategy='merge'
  )
}}

with staging as (
    select * from {{ ref('stg_meteo_hourly') }}
    {% if is_incremental() %}
    where timestamp_utc > (select max(timestamp_utc) - interval '72 hours' from {{ this }})
    {% endif %}
)

select
    {{ dbt_utils.generate_surrogate_key(['staging.timestamp_utc', 'staging.latitude', 'staging.longitude']) }} as meteo_hourly_key,
    {{ dbt_utils.generate_surrogate_key(['staging.timestamp_utc']) }} as time_key,
    {{ dbt_utils.generate_surrogate_key(['staging.latitude', 'staging.longitude']) }} as location_key,
    staging.sunshine_duration_s,
    staging.shortwave_radiation_wm2,
    staging.direct_radiation_wm2,
    staging.cloud_cover_pct
from staging
